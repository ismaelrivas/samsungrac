import asyncio
import logging
import os
import re
import ssl
from typing import Callable, Dict, Any, Optional, Tuple

import xmltodict
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN

from .connection import Connection, register_connection
from .exceptions import AuthError, CannotConnect
from .properties import DeviceProperty, register_status_getter
from .yaml_const import (
    CONF_CERT,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
    CONFIG_DEVICE_POWER_TEMPLATE,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_S2878 = "samsung_2878"
CONF_DUID = "duid"

INITIAL_RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 300
RECONNECT_FACTOR = 2
COMMAND_TIMEOUT = 10.0
MAX_RECONNECT_RETRIES = 5

class connection_config:
    def __init__(self, host, port, token, cert, duid):
        self.host = host
        self.port = port
        self.token = token
        self.duid = duid
        self.cert = cert

@register_connection
class ConnectionSamsung2878(Connection):
    def __init__(self, hass_config, logger):
        super(ConnectionSamsung2878, self).__init__(hass_config, logger)
        self._params = {}
        self._connection_init_template = None
        self._cfg = connection_config(None, None, None, None, None)
        self._device_status = {}
        self._socket_timeout = 15.0
        self._controller = None

        self._reader = None
        self._writer = None
        self._lock = asyncio.Lock() # To serialize execute() calls
        self._cmd_queue = asyncio.Queue()
        self._manager_task: Optional[asyncio.Task] = None
        self._update_callback: Optional[Callable[[], None]] = None
        self._pending_future: Optional[asyncio.Future] = None
        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._reconnect_retries = 0
        self._is_ready = asyncio.Event() # Event to signal when connection is ready
        
        self.update_configuration_from_hass(hass_config)
        self._power_template = None
        self.start_listening()

    def set_controller_ref(self, controller):
        self._controller = controller

    @property
    def log_prefix(self) -> str:
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        if self._cfg and self._cfg.duid:
            return f"[{self._cfg.duid[-6:]}]"
        return "[NO_ID]"

    def set_update_callback(self, callback: Callable[[], None]) -> None:
        self._update_callback = callback

    def start_listening(self) -> None:
        if self._manager_task is None or self._manager_task.done():
            _LOGGER.info("%s Starting new connection manager task.", self.log_prefix)
            self._reconnect_retries = 0
            self._manager_task = asyncio.create_task(self._connection_manager())
        else:
            _LOGGER.debug("%s Connection manager task already running.", self.log_prefix)

    async def stop_listening(self) -> None:
        _LOGGER.info("%s Stopping connection manager.", self.log_prefix)
        if self._manager_task:
            self._manager_task.cancel()
            try:
                await self._manager_task
            except asyncio.CancelledError:
                pass
            self._manager_task = None
        await self._close_connection()

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
            _LOGGER.error("%s Missing 'connection_template' in connection section", self.log_prefix)
            return False

        if CONFIG_DEVICE_POWER_TEMPLATE in params_node:
            self._power_template = Template(params_node[CONFIG_DEVICE_POWER_TEMPLATE])

        if not connection_base:
            if not self._cfg.host: _LOGGER.error("%s Missing 'host' parameter", self.log_prefix)
            if not self._cfg.token: _LOGGER.error("%s Missing 'token' parameter", self.log_prefix)
            if not self._cfg.duid: _LOGGER.error("%s Missing 'mac' parameter", self.log_prefix)

        self._params.update(params_node)
        return True

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_S2878

    def create_updated(self, node):
        self.load_from_yaml(node, self)
        return self

    async def _post_connect_status_request(self):
        """Queue a request for the full device status after a connection is established."""
        try:
            # Give the system a moment to be ready for a new command
            await asyncio.sleep(1)
            
            command = f'<Request Type="DeviceState" DUID="{self._cfg.duid}"></Request>\n'
            _LOGGER.info("%s Queuing post-reconnection status request.", self.log_prefix)
            
            future = asyncio.get_event_loop().create_future()
            await self._cmd_queue.put((command, future))
            
            # Wait for the command to be processed
            await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
            _LOGGER.debug("%s Post-reconnection status request successfully processed.", self.log_prefix)

        except asyncio.TimeoutError:
            _LOGGER.warning("%s Post-reconnection status request timed out.", self.log_prefix)
        except Exception as e:
            _LOGGER.error("%s Failed to queue post-reconnection status request: %s", self.log_prefix, e, exc_info=True)

    async def _close_connection(self):
        self._is_ready.clear()
        if self._writer:
            _LOGGER.info("%s Closing connection.", self.log_prefix)
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                _LOGGER.warning("%s Ignoring error during connection close: %s", self.log_prefix, e)
        self._writer = self._reader = None

    async def _establish_connection_and_handshake(self):
        await self._close_connection()
        cfg = self._cfg
        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
            ssl_context.set_ciphers("HIGH:!DH:!aNULL:@SECLEVEL=0")
            ssl_context.verify_mode = ssl.CERT_NONE
            ssl_context.check_hostname = False

            _LOGGER.info("%s Connecting to %s:%s...", self.log_prefix, cfg.host, cfg.port)
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(cfg.host, cfg.port, ssl=ssl_context),
                timeout=self._socket_timeout,
            )
            
            initial_msg = await self._read_full_response(timeout=self._socket_timeout)
            if not initial_msg or "DPLUG-1.6" not in initial_msg:
                _LOGGER.error("%s Handshake failed: Did not receive DPLUG. Got: %s", self.log_prefix, initial_msg)
                raise CannotConnect("Handshake failed: Did not receive DPLUG")
            
            auth_command = self._connection_init_template.render(**self._params) + "\n"
            await self._write_data(auth_command)

            auth_response = await self._read_full_response()
            if not auth_response or 'Type="AuthToken" Status="Okay"' not in auth_response:
                _LOGGER.error("%s Handshake failed: Authentication not Okay. Got: %s", self.log_prefix, auth_response)
                raise AuthError("Authentication failed")

            _LOGGER.info("%s Authentication successful. Connection is ready.", self.log_prefix)
            self._reconnect_delay = INITIAL_RECONNECT_DELAY
            self._reconnect_retries = 0
            self._is_ready.set() # Signal that we are ready for commands
            
            # Request a full status update after successful connection
            asyncio.create_task(self._post_connect_status_request())
            
            return True
        except (asyncio.TimeoutError, OSError) as e:
            _LOGGER.error("%s Connection and handshake failed: %s", self.log_prefix, e)
            await self._close_connection()
            raise CannotConnect(f"Connection failed: {e}") from e
        except Exception as e:
            _LOGGER.error("%s Connection and handshake failed with unexpected error: %s", self.log_prefix, e, exc_info=True)
            await self._close_connection()
            raise CannotConnect(f"An unexpected error occurred during connection: {e}") from e

    async def _read_full_response(self, timeout=8.0) -> Optional[str]:
        if not self._reader or self._reader.at_eof(): return None
        try:
            buffer = b""
            end_time = asyncio.get_event_loop().time() + timeout
            while True:
                remaining_time = end_time - asyncio.get_event_loop().time()
                if remaining_time <= 0: raise asyncio.TimeoutError

                chunk = await asyncio.wait_for(self._reader.read(4096), timeout=remaining_time)
                if not chunk: 
                    await self._close_connection()
                    return buffer.decode("utf-8", errors='ignore') if buffer else None
                
                buffer += chunk
                decoded_buffer = buffer.decode("utf-8", errors='ignore').strip()
                if "</Response>" in decoded_buffer or "</Update>" in decoded_buffer or "DPLUG-1.6" in decoded_buffer or decoded_buffer.endswith("/>"):
                    return decoded_buffer

        except (asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
            _LOGGER.debug("%s No full response received in %s seconds: %s", self.log_prefix, timeout, e)
            return None
        except Exception as e:
            _LOGGER.error("%s Error during read: %s", self.log_prefix, e, exc_info=True)
            await self._close_connection()
            return None

    async def _write_data(self, data_str: str):
        if not self._writer or self._writer.is_closing():
            _LOGGER.error("%s Write failed: writer is not available.", self.log_prefix)
            raise CannotConnect("Connection is not available for writing")
        try:
            self._writer.write(data_str.encode("utf-8"))
            await self._writer.drain()
            return True
        except Exception as e:
            _LOGGER.error("%s Write failed: %s. Closing connection.", self.log_prefix, e)
            await self._close_connection()
            raise CannotConnect(f"Failed to write to connection: {e}") from e

    def _parse_and_update_state(self, response_xml: str):
        if not response_xml: return False, False
        
        is_update = False
        is_response = False
        for doc_part in response_xml.split('<?xml'):
            if not doc_part.strip(): continue
            full_doc = '<?xml' + doc_part
            try:
                data = xmltodict.parse(full_doc)
                
                if "Response" in data:
                    is_response = True
                    device_data = data['Response'].get('DeviceState', {}).get('Device')
                elif "Update" in data:
                    is_update = True
                    device_data = data['Update'].get('Status')
                else:
                    continue

                if not device_data: continue
                attrs = device_data.get('Attr', [])
                if not isinstance(attrs, list): attrs = [attrs]
                
                for attr in attrs:
                    if '@ID' in attr and '@Value' in attr:
                        self._device_status[attr['@ID']] = attr['@Value']
                _LOGGER.debug("%s Device state updated: %s", self.log_prefix, self._device_status)

            except Exception as e:
                _LOGGER.error("%s Error parsing XML document: %s", self.log_prefix, e, exc_info=True)
        
        return is_response, is_update

    async def _connection_manager(self):
        _LOGGER.debug("%s Connection manager task started.", self.log_prefix)
        buffer = b""
        read_task = None
        queue_task = None
        while True:
            try:
                if not self._writer or self._writer.is_closing():
                    _LOGGER.debug("%s Manager: Connection is down.", self.log_prefix)
                    if self._pending_future and not self._pending_future.done():
                        self._pending_future.set_exception(CannotConnect("Connection lost"))
                        self._pending_future = None
                    
                    try:
                        await self._establish_connection_and_handshake()
                        _LOGGER.debug("%s Manager: Connection established.", self.log_prefix)
                    except (CannotConnect, AuthError) as e:
                        self._reconnect_retries += 1
                        _LOGGER.warning("%s Could not connect to device: %s. (Attempt %d of %d)", self.log_prefix, e, self._reconnect_retries, MAX_RECONNECT_RETRIES)
                        
                        if self._reconnect_retries >= MAX_RECONNECT_RETRIES:
                            _LOGGER.error("%s Max reconnect retries reached in connection manager. Stopping attempts. The coordinator will take over.", self.log_prefix)
                            break # Exit the manager loop

                        await self._close_connection()
                        await asyncio.sleep(self._reconnect_delay)
                        self._reconnect_delay = min(self._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY)
                        continue

                # Define tasks to wait for
                read_task = asyncio.create_task(self._reader.read(8192))
                tasks = [read_task]

                if not self._pending_future:
                    queue_task = asyncio.create_task(self._cmd_queue.get())
                    tasks.append(queue_task)
                else:
                    queue_task = None
                
                _LOGGER.debug("%s Manager: Waiting for I/O. Pending future: %s", self.log_prefix, bool(self._pending_future))
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                # --- Process Completed Tasks ---
                if queue_task and queue_task in done:
                    _LOGGER.debug("%s Manager: Command received from queue.", self.log_prefix)
                    command, future = queue_task.result()
                    self._pending_future = future
                    try:
                        await self._write_data(command)
                    except CannotConnect as e:
                        if not self._pending_future.done():
                            self._pending_future.set_exception(e)
                        self._pending_future = None

                if read_task in done:
                    _LOGGER.debug("%s Manager: Data received from socket.", self.log_prefix)
                    data = read_task.result()
                    if not data: 
                        _LOGGER.info("%s Connection closed by peer.", self.log_prefix)
                        await self._close_connection()
                        continue
                    
                    buffer += data
                    # Process buffer to find full XML messages
                    while b"</Response>" in buffer or b"</Update>" in buffer or b"/>" in buffer:
                        end_tag = b"</Response>" if b"</Response>" in buffer else (b"</Update>" if b"</Update>" in buffer else b"/>")
                        end_index = buffer.find(end_tag) + len(end_tag)
                        message = buffer[:end_index]
                        buffer = buffer[end_index:]
                        
                        xml_data = message.decode("utf-8", errors='ignore')
                        _LOGGER.debug("%s Manager: Processing message: %s", self.log_prefix, xml_data.strip())
                        is_response, is_update = self._parse_and_update_state(xml_data)

                        if is_response and self._pending_future and not self._pending_future.done():
                            _LOGGER.debug("%s Manager: Resolving future.", self.log_prefix)
                            self._pending_future.set_result(True)
                            self._pending_future = None
                        
                        # Notify coordinator on any state change (push or poll response)
                        if (is_response or is_update) and self._update_callback:
                            _LOGGER.debug("%s Manager: Calling update callback on state change (is_response=%s, is_update=%s).", self.log_prefix, is_response, is_update)
                            asyncio.create_task(self._update_callback())
                
                for task in pending:
                    task.cancel()

            except asyncio.CancelledError:
                _LOGGER.info("%s Connection manager stopped.", self.log_prefix)
                if self._pending_future and not self._pending_future.done():
                    self._pending_future.set_exception(asyncio.CancelledError())
                
                # Clean up tasks on cancellation
                if read_task and not read_task.done():
                    read_task.cancel()
                if queue_task and not queue_task.done():
                    queue_task.cancel()
                
                break
            except Exception as e:
                _LOGGER.error("%s Unhandled exception in connection manager: %s", self.log_prefix, e, exc_info=True)
                if self._pending_future and not self._pending_future.done():
                    self._pending_future.set_exception(e)
                self._pending_future = None
                await self._close_connection()
                await asyncio.sleep(self._reconnect_delay)

    async def execute(self, template, v, device_state):
        # Wait for the connection to be ready before proceeding
        try:
            await asyncio.wait_for(self._is_ready.wait(), timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError as e:
            _LOGGER.error("%s Timed out waiting for connection to be ready.", self.log_prefix)
            raise CannotConnect("Connection not ready") from e

        async with self._lock:
            is_polling_request = template and not v and not device_state
            if is_polling_request:
                command = f'<Request Type="DeviceState" DUID="{self._cfg.duid}"></Request>\n'
            else:
                params = self._params.copy()
                params.update({"value": v, "device_state": device_state})
                command = template.render(**params).strip() + "\n"

            _LOGGER.debug("%s Queuing command: %s", self.log_prefix, command.strip())
            future = asyncio.get_event_loop().create_future()
            await self._cmd_queue.put((command, future))

            try:
                await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
                _LOGGER.debug("%s Command successfully executed.", self.log_prefix)
            except asyncio.TimeoutError as e:
                _LOGGER.error("%s Command timed out: %s", self.log_prefix, command.strip())
                raise CannotConnect("Command timed out") from e
            except Exception as e:
                _LOGGER.error("%s Command failed with exception: %s", self.log_prefix, e, exc_info=True)
                raise

        return self._device_status
