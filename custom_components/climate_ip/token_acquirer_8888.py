# climate_ip/token_acquirer_8888.py
"""Helper to acquire a token from modern Samsung AC units (port 8888) using asyncio."""

import asyncio
import json
import logging
import os
import ssl
import re
from typing import Optional

import aiohttp

from .exceptions import TokenAcquisitionError
from .helpers import mask_sensitive_data

_LOGGER = logging.getLogger(__name__)

class SamsungTokenAcquirer8888:
    """Manages the token acquisition process for modern Samsung ACs using asyncio.
    Uses a raw TCP server to handle malformed HTTP headers from some AC units.
    """

    def __init__(self, hass, ac_ip: str, cert_path: str):
        self._hass = hass
        self._ac_ip = ac_ip

        # Resolve the certificate path.
        if cert_path and not os.path.dirname(cert_path):
            _LOGGER.debug(
                "Certificate path '%s' appears to be a filename. Resolving relative to integration directory.",
                cert_path,
            )
            self._cert_path = os.path.join(os.path.dirname(__file__), cert_path)
        else:
            self._cert_path = cert_path
        _LOGGER.debug("Final resolved certificate path for token acquirer: %s", self._cert_path)

        self._listener_ip = hass.config.api.local_ip
        self._listener_port = 8889
        self._ac_port = 8888
        self._token_received_event = asyncio.Event()
        self._received_token: Optional[str] = None
        
        # Asyncio server components
        self._server: Optional[asyncio.AbstractServer] = None

    async def _handle_client(self, reader, writer):
        """Handle incoming connection from the AC."""
        addr = writer.get_extra_info('peername')
        _LOGGER.debug("Token listener accepted connection from %s", addr)

        try:
            # Read data with a timeout
            # The AC sends a small JSON payload.
            # However, data might arrive in multiple chunks (headers first, then body).
            # We need to read until we catch the token or time out.
            data = b""
            end_time = asyncio.get_event_loop().time() + 10.0
            
            while True:
                remaining = end_time - asyncio.get_event_loop().time()
                if remaining <= 0:
                     break
                
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=remaining)
                    if not chunk:
                        break
                    data += chunk
                    
                    # Check if we have enough data to stop reading
                    # We stop if we see the closing brace of the JSON or the specific token key
                    decoded_check = data.decode('utf-8', errors='ignore')
                    if 'DeviceToken' in decoded_check and '}' in decoded_check:
                        break
                except asyncio.TimeoutError:
                    break

            if not data:
                _LOGGER.debug("Token listener received empty data.")
                return

            decoded_data = data.decode('utf-8', errors='ignore')
            _LOGGER.debug("Token listener received raw data:\n%s", mask_sensitive_data(decoded_data))

            token = None
            
            # STRATEGY 1: Regex extraction (Most robust for malformed headers)
            # We look for DeviceToken key in JSON-like structure or just raw string
            match = re.search(r'DeviceToken["\s:]+([^"\s}]+)', decoded_data)
            if match:
                token = match.group(1).strip('"')
                _LOGGER.info("Token successfully extracted via Regex.")
            else:
                 # STRATEGY 2: Try finding JSON body if regex fails
                 json_start = decoded_data.find('{')
                 if json_start != -1:
                     try:
                         json_candidate = decoded_data[json_start:]
                         json_data = json.loads(json_candidate)
                         token = json_data.get('DeviceToken')
                         if token:
                             _LOGGER.info("Token successfully extracted via JSON parsing.")
                     except Exception:
                         pass

            if token:
                _LOGGER.info("Token successfully received from AC unit.")
                self._received_token = token
                self._token_received_event.set()
                
                # Send a polite 200 OK response, even if the request was malformed
                response = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/plain\r\n"
                    "Content-Length: 2\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    "OK"
                )
                writer.write(response.encode('utf-8'))
                await writer.drain()
            else:
                _LOGGER.warning("Connection received but no token could be extracted.")
                # Send 400 Bad Request
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: text/plain\r\n"
                    "Content-Length: 15\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    "Token not found"
                )
                writer.write(response.encode('utf-8'))
                await writer.drain()

        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout reading from AC connection.")
        except Exception as e:
            _LOGGER.error("Error handling AC connection: %s", e, exc_info=True)
        finally:
            _LOGGER.debug("Closing connection from %s", addr)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


    async def _start_listener_server(self) -> bool:
        """Starts the custom TCP listener server."""
        try:
            # Setup SSL for the server
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1
            try:
                ssl_context.set_ciphers('HIGH:!aNULL:!MD5:@SECLEVEL=0')
            except Exception as e:
                _LOGGER.warning("Failed to set ciphers with SECLEVEL=0: %s", e)

            await self._hass.async_add_executor_job(
                ssl_context.load_cert_chain, self._cert_path
            )
            
            # Start the server
            self._server = await asyncio.start_server(
                self._handle_client, '0.0.0.0', self._listener_port, ssl=ssl_context
            )
            
            _LOGGER.info("Async token listener (custom TCP) server started on port %s", self._listener_port)
            return True
        except Exception as e:
            _LOGGER.error("Failed to start listener server: %s", e, exc_info=True)
            return False

    async def async_initiate_pairing(self) -> None:
        """
        Phase 1: Starts the local server and sends the initial token request to the AC.
        """
        if not await self._start_listener_server():
            raise TokenAcquisitionError("Failed to start the local listener server")
        
        url = f"https://{self._ac_ip}:{self._ac_port}/devicetoken/request"
        headers = {'Host': f"{self._listener_ip}:{self._listener_port}"}
        payload = {"DeviceToken": "xxxxxxxxxxx"}

        _LOGGER.info("Requesting token from AC at %s:%s", self._ac_ip, self._ac_port)

        # Setup Client SSL Context
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1
        ssl_context.set_ciphers('HIGH:!aNULL:!MD5:@SECLEVEL=0')
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        await self._hass.async_add_executor_job(
            ssl_context.load_cert_chain, self._cert_path
        )

        try:
            async with aiohttp.ClientSession() as session:
                _LOGGER.debug(
                    "Sending pairing request to URL: %s, Headers: %s, Payload: %s",
                    url, headers, payload
                )
                
                async with session.post(
                    url, 
                    json=payload, 
                    headers=headers, 
                    ssl=ssl_context, 
                    timeout=30
                ) as response:
                    
                    _LOGGER.debug(
                        "AC responded to pairing request with status %s",
                        response.status
                    )

                    if response.status == 200:
                        _LOGGER.info("Token request accepted by AC (200 OK)")
                        # Try to read body for debugging, but don't fail if it times out (missing Content-Length)
                        try:
                            resp_text = await asyncio.wait_for(response.text(), timeout=2.0)
                            _LOGGER.debug("AC response body: %s", resp_text)
                        except (asyncio.TimeoutError, aiohttp.ClientError):
                            _LOGGER.debug("AC response body could not be read (timeout/error), assuming empty.")
                    else:
                         # For non-200, we really want to see the error message if possible
                        try:
                            resp_text = await asyncio.wait_for(response.text(), timeout=2.0)
                        except Exception:
                            resp_text = "<unknown>"
                        raise TokenAcquisitionError(
                            f"AC responded with non-200 status: {response.status} - {resp_text}"
                        )

        except aiohttp.ClientError as e:
            await self.async_close()
            raise TokenAcquisitionError(f"Failed to connect to AC: {e}")
        except Exception as e:
            await self.async_close()
            raise TokenAcquisitionError(f"Unexpected error during pairing request: {e}")

    async def async_wait_for_token(self) -> str:
        """
        Phase 2: Waits for the token to be received by the local server.
        """
        try:
            await asyncio.wait_for(self._token_received_event.wait(), timeout=60)
            if self._received_token:
                return self._received_token
            raise TokenAcquisitionError("Event was set but no token was stored")
        except asyncio.TimeoutError:
            raise TokenAcquisitionError("Timed out waiting for the AC to send the token")
        finally:
            await self.async_close()

    async def async_close(self) -> None:
        """Shuts down the listener server."""
        if self._server:
            _LOGGER.info("Shutting down async token listener server")
            self._server.close()
            await self._server.wait_closed()
            self._server = None