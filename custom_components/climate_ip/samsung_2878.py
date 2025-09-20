 import asyncio
import json
import logging
import os
import re
import ssl
import traceback
from socket import AF_INET, SOCK_STREAM

import xmltodict
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN

from .connection import Connection, register_connection
from .properties import DeviceProperty, register_status_getter
from .yaml_const import (
    CONF_CERT,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
    CONFIG_DEVICE_POWER_TEMPLATE,
)

CONNECTION_TYPE_S2878 = "samsung_2878"
CONF_DUID = "duid"

class connection_config:
    def __init__(self, host, port, token, cert, duid):
        self.host = host
        self.port = port
        self.token = token
        self.duid = duid
        self.cert = cert

@register_connection
class ConnectionSamsung2878(Connection):
    """
    Manages a persistent async socket connection to old Samsung AC devices.
    This version is designed to be stable, fast, and robust against network issues.
    """
    def __init__(self, hass_config, logger):
        super(ConnectionSamsung2878, self).__init__(hass_config, logger)
        self._params = {}
        self._connection_init_template = None
        self._cfg = connection_config(None, None, None, None, None)
        self._device_status = {}
        self._socket_timeout = 20.0

        self._reader = None
        self._writer = None
        self._lock = asyncio.Lock()
        
        self.update_configuration_from_hass(hass_config)
        self._power_template = None

    def update_configuration_from_hass(self, hass_config):
        if hass_config is not None:
            cert_file = hass_config.get(CONF_CERT)
            if not cert_file: cert_file = None
            if cert_file and not os.path.isabs(cert_file):
                cert_file = os.path.join(os.path.dirname(__file__), cert_file)

            duid = None
            mac = hass_config.get(CONF_MAC)
            if mac: duid = re.sub(":", "", mac)

            self._cfg = connection_config(
                hass_config.get(CONF_IP_ADDRESS),
                hass_config.get(CONF_PORT, 2878),
                hass_config.get(CONF_TOKEN),
                cert_file,
                duid,
            )
            self._params.update({CONF_DUID: duid, CONF_TOKEN: self._cfg.token})

    def load_from_yaml(self, node, connection_base):
        from jinja2 import Template

        if connection_base: self._params.update(connection_base._params.copy())
        if not node: return False
        
        params_node = node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {})
        if CONFIG_DEVICE_CONNECTION_TEMPLATE in params_node:
            self._connection_init_template = Template(params_node[CONFIG_DEVICE_CONNECTION_TEMPLATE])
        elif not connection_base:
            self.logger.error("Missing 'connection_template' in connection section")
            return False

        if CONFIG_DEVICE_POWER_TEMPLATE in params_node:
            self._power_template = Template(params_node[CONFIG_DEVICE_POWER_TEMPLATE])

        if not connection_base:
            if not self._cfg.host: self.logger.error("Missing 'host' parameter")
            if not self._cfg.token: self.logger.error("Missing 'token' parameter")
            if not self._cfg.duid: self.logger.error("Missing 'mac' parameter")
            self.logger.info(f"Config - host:{self._cfg.host}:{self._cfg.port}, duid:{self._cfg.duid}, cert:{self._cfg.cert}")

        self._params.update(params_node)
        return True

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_S2878

    def create_updated(self, node):
        c = ConnectionSamsung2878(None, self.logger)
        c._cfg = self._cfg
        c._connection_init_template = self._connection_init_template
        c._power_template = self._power_template
        c.load_from_yaml(node, self)
        return c

    async def _close_connection(self):
        """Helper to gracefully close the connection."""
        if self._writer:
            self.logger.info("Closing connection.")
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                self.logger.warning(f"Ignoring error during connection close: {e}")
        self._writer = self._reader = None

    async def _establish_connection_and_handshake(self):
        """Establishes a new connection and performs the full authentication handshake."""
        await self._close_connection()
        cfg = self._cfg
        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
            ssl_context.set_ciphers("HIGH:!DH:!aNULL:@SECLEVEL=0")
            
            # Key insight: The server's certificate is self-signed and will always fail
            # strict validation. We must disable verification to connect.
            ssl_context.verify_mode = ssl.CERT_NONE
            
            if cfg.cert:
                # If a cert is provided, it's for CLIENT authentication, not server verification.
                # The server expects us to present this cert.
                self.logger.info(f"Loading client certificate from {cfg.cert} for authentication.")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: ssl_context.load_cert_chain(certfile=cfg.cert)
                )
            else:
                self.logger.info("No certificate provided, skipping client authentication.")

            self.logger.info(f"Connecting to {cfg.host}:{cfg.port}...")
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    cfg.host, cfg.port, ssl=ssl_context, server_hostname=cfg.host
                ),
                timeout=self._socket_timeout,
            )
            
            # --- Handshake Logic ---
            initial_msg = await self._read_response()
            if not initial_msg or "DPLUG" not in initial_msg:
                self.logger.error(f"Handshake failed: Did not receive DPLUG. Got: {initial_msg}")
                await self._close_connection()
                return False
            
            auth_command = self._connection_init_template.render(**self._params) + "\n"
            await self._write_data(auth_command)

            auth_response = await self._read_response()
            if not auth_response or 'Type="AuthToken" Status="Okay"' not in auth_response:
                self.logger.error(f"Handshake failed: Authentication not Okay. Got: {auth_response}")
                await self._close_connection()
                return False

            self.logger.info("Authentication successful. Connection is ready.")
            return True
        except Exception as e:
            self.logger.error(f"Connection and handshake failed: {e}", exc_info=True)
            await self._close_connection()
            return False

    async def _read_response(self, timeout=8.0):
        """
        Reads data from the socket until a complete message is received.
        Handles fragmentation and recognizes all known completion conditions.
        """
        if not self._reader or self._reader.at_eof():
            self.logger.warning("Read failed: reader is not available or at EOF.")
            await self._close_connection()
            return None

        full_response = ""
        try:
            end_time = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < end_time:
                remaining_time = end_time - asyncio.get_event_loop().time()
                if remaining_time <= 0:
                    raise asyncio.TimeoutError

                chunk = await asyncio.wait_for(self._reader.read(4096), timeout=remaining_time)
                if not chunk:
                    self.logger.warning("Connection closed by peer while reading.")
                    await self._close_connection()
                    return full_response if full_response else None

                full_response += chunk.decode("utf-8", errors='ignore')
                
                stripped_response = full_response.strip()
                if "DPLUG-1.6" in stripped_response or stripped_response.endswith(('</Response>', '</Update>', '/>')):
                    return full_response

        except asyncio.TimeoutError:
            self.logger.warning(f"Read timed out after {timeout} seconds. Data received: '{full_response.strip()}'")
            return full_response if full_response else None
        except Exception as e:
            self.logger.error(f"Error during read: {e}", exc_info=True)
            await self._close_connection()
            return None

    async def _write_data(self, data_str: str):
        """Writes data to the socket. Does not handle reconnection, assumes connection is valid."""
        if not self._writer or self._writer.is_closing():
             self.logger.error("Write failed: writer is not available.")
             return False
        try:
            self.logger.info(f"Sending: {data_str.strip()}")
            self._writer.write(data_str.encode("utf-8"))
            await self._writer.drain()
            return True
        except Exception as e:
            self.logger.error(f"Write failed: {e}. Closing connection.")
            await self._close_connection()
            return False

    def _parse_and_update_state(self, response_xml):
        """Parses one or more XML documents from a single response string."""
        if not response_xml: return
        
        for doc_part in response_xml.split('<?xml'):
            if not doc_part.strip(): continue
            
            full_doc = '<?xml' + doc_part
            try:
                data = xmltodict.parse(full_doc)
                device_data = None
                
                if "Response" in data and data["Response"].get("@Type") == "DeviceState":
                    device_data = data['Response']['DeviceState'].get('Device')
                elif "Update" in data and data["Update"].get("@Type") == "Status":
                    device_data = data['Update'].get('Status')
                elif "Response" in data and data["Response"].get("@Type") in ("DeviceControl", "AuthToken"):
                    continue
                else:
                    self.logger.warning(f"Received unhandled XML structure: {full_doc}")
                    continue

                if not device_data: continue
                attrs = device_data.get('Attr', [])
                if not isinstance(attrs, list): attrs = [attrs]
                
                for attr in attrs:
                    if '@ID' in attr and '@Value' in attr:
                        self._device_status[attr['@ID']] = attr['@Value']
                self.logger.info(f"Device state updated: {self._device_status}")

            except Exception as e:
                self.logger.error(f"Error parsing XML document: {e}", exc_info=True)

    async def _send_command_and_get_response(self, command):
        """Sends a single command and reads the response. Handles reconnection."""
        if not self._writer or self._writer.is_closing():
            self.logger.info("Connection is down. Re-establishing.")
            if not await self._establish_connection_and_handshake():
                self.logger.error("Failed to re-establish connection. Command aborted.")
                return None
        
        if await self._write_data(command):
            return await self._read_response()
        
        self.logger.warning("Write failed. Retrying command once.")
        if await self._establish_connection_and_handshake():
            if await self._write_data(command):
                return await self._read_response()
        
        self.logger.error("Failed to send command after retry.")
        return None

    async def execute(self, template, v, device_state):
        """Main entry point for sending commands or polling the device."""
        async with self._lock:
            is_polling_request = template and not v and not device_state
            
            if is_polling_request:
                command = f'<Request Type="DeviceState" DUID="{self._cfg.duid}"></Request>\n'
                response = await self._send_command_and_get_response(command)
                self._parse_and_update_state(response)
            else:
                params = self._params.copy()
                params.update({"value": v, "device_state": device_state})
                command_str = template.render(**params).strip()
                
                if self._power_template:
                    power_command_str = self._power_template.render(**params).strip()
                    if power_command_str:
                        self.logger.info("Executing power command first.")
                        response = await self._send_command_and_get_response(power_command_str + "\n")
                        self._parse_and_update_state(response)
                        await asyncio.sleep(0.5)
                
                response = await self._send_command_and_get_response(command_str + "\n")
                self._parse_and_update_state(response)
            
            return self._device_status
