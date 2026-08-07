# pylint: disable=f-string-without-interpolation,line-too-long,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-statements,unused-variable
"""Helper to acquire a token from modern Samsung AC units (port 8888) using asyncio."""

import asyncio
import logging
import re
import ssl
from pathlib import Path
from typing import Any

from homeassistant.helpers.json import json_dumps
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads

from .exceptions import CannotConnect, TokenAcquisitionError
from .helpers import mask_sensitive_data

_LOGGER = logging.getLogger(__name__)

# Precompiled regex for DeviceToken extraction
DEVICE_TOKEN_RE = re.compile(r'DeviceToken["\s:]+([^"\s}]+)')


class SamsungTokenAcquirer8888:
    """Manages the token acquisition process for modern Samsung ACs using asyncio.
    Uses a raw TCP server to handle malformed HTTP headers from some AC units.
    """

    # pylint: disable=f-string-without-interpolation,line-too-long,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-statements,unused-variable

    def __init__(self, hass: Any, ac_ip: str, cert_path: str) -> None:
        """Initialize the acquirer."""
        self._hass = hass
        self._ac_ip = ac_ip

        # Resolve the certificate path.
        if cert_path and not ("/" in cert_path or "\\" in cert_path):
            self._cert_path = str(Path(__file__).parent / cert_path)
        else:
            self._cert_path = cert_path
        _LOGGER.debug(
            "Final resolved certificate path for token acquirer: %s", self._cert_path
        )  # pragma: no mutate

        self._listener_ip: str = hass.config.api.local_ip
        self._listener_port: int = 8889
        self._ac_port: int = 8888
        self._token_received_event = asyncio.Event()
        self._received_token: str | None = None

        # Asyncio server components
        self._server: asyncio.AbstractServer | None = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming connection from the AC."""
        addr = writer.get_extra_info("peername")  # pragma: no mutate
        _LOGGER.debug(
            "Token listener accepted connection from %s", addr
        )  # pragma: no mutate

        try:
            # Read data with a timeout
            # The AC sends a small JSON payload.
            # However, data might arrive in multiple chunks (headers first, then body).
            # We need to read until we catch the token or time out.
            data = b""

            try:
                async with asyncio.timeout(10.0):
                    while True:
                        chunk = await reader.read(4096)
                        if not chunk:
                            break
                        data += chunk

                        # Check if we have enough data to stop reading
                        # We stop if we see the closing brace of the JSON or the specific token key
                        decoded_check = data.decode(
                            "utf-8", errors="ignore"
                        )  # pragma: no mutate
                        if "DeviceToken" in decoded_check and "}" in decoded_check:
                            break
            except TimeoutError:
                pass  # Break out cleanly if we hit the limit

            if not data:
                _LOGGER.debug(
                    "Token listener received empty data."
                )  # pragma: no mutate
                return

            decoded_data = data.decode("utf-8", errors="ignore")  # pragma: no mutate
            _LOGGER.debug(  # pragma: no mutate
                "Token listener received raw data:\n%s",
                mask_sensitive_data(decoded_data),
            )

            token: str | None = None  # pragma: no mutate

            # STRATEGY 1: Regex extraction (Most robust for malformed headers)
            # We look for DeviceToken key in JSON-like structure or just raw string
            match = DEVICE_TOKEN_RE.search(decoded_data)
            if match:
                token = match.group(1).strip('"')
                _LOGGER.info(
                    "Token successfully extracted via Regex."
                )  # pragma: no mutate
            else:
                # STRATEGY 2: Try finding JSON body if regex fails
                json_start = decoded_data.find("{")
                if json_start != -1:
                    try:
                        json_candidate = decoded_data[json_start:]
                        json_data = json_loads(json_candidate)
                        token = json_data.get("DeviceToken")
                        if token:
                            _LOGGER.info(
                                "Token successfully extracted via JSON parsing."
                            )  # pragma: no mutate
                    # Specific exceptions instead of a broad catch-all
                    except (*JSON_DECODE_EXCEPTIONS, ValueError):
                        pass

            if token:
                _LOGGER.info(
                    "Token successfully received from AC unit."
                )  # pragma: no mutate
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
                writer.write(response.encode("utf-8"))
                await writer.drain()
            else:
                _LOGGER.warning(
                    "Connection received but no token could be extracted."
                )  # pragma: no mutate
                # Send 400 Bad Request
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: text/plain\r\n"
                    "Content-Length: 15\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    "Token not found"
                )
                writer.write(response.encode("utf-8"))
                await writer.drain()

        except Exception as e:  # pylint: disable=broad-exception-caught
            # This is the main server loop for a client, so catching broad exceptions
            # here is acceptable to prevent a single bad client from crashing the listener.
            _LOGGER.error(
                "Error handling AC connection: %s", e, exc_info=True
            )  # pragma: no mutate
        finally:
            _LOGGER.debug("Closing connection from %s", addr)  # pragma: no mutate
            writer.close()
            try:
                await writer.wait_closed()
            except (TimeoutError, OSError, ConnectionError):
                pass

    async def _start_listener_server(self) -> bool:
        """Starts the custom TCP listener server."""
        try:
            # pylint: disable=import-outside-toplevel
            from .helpers import async_create_samsung_ssl_context

            ssl_context = await async_create_samsung_ssl_context(
                cert_path=self._cert_path,
                ciphers="HIGH:!aNULL:!MD5:@SECLEVEL=0",
                is_server=True,
            )

            # Start the server securely on the HA interface rather than 0.0.0.0 uniformly
            bind_ip = self._listener_ip or "0.0.0.0"
            try:
                self._server = await asyncio.start_server(
                    self._handle_client, bind_ip, self._listener_port, ssl=ssl_context
                )
            except OSError as bind_err:
                _LOGGER.error(  # pragma: no mutate
                    "Port %s is in use or IP %s is unbindable: %s",
                    self._listener_port,
                    bind_ip,
                    bind_err,
                )
                raise TokenAcquisitionError(  # pragma: no mutate
                    f"Cannot bind to {bind_ip}:{self._listener_port}"
                ) from bind_err

            _LOGGER.info(  # pragma: no mutate
                "Async token listener (custom TCP) server started on %s:%s",
                bind_ip,
                self._listener_port,
            )
            return True
        except TokenAcquisitionError:
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Failed to start listener server: %s", e, exc_info=True
            )  # pragma: no mutate
            return False

    async def async_initiate_pairing(self) -> None:
        """
        Phase 1: Starts the local server and sends the initial token request to the AC.
        """
        if not await self._start_listener_server():
            raise TokenAcquisitionError(
                "Failed to start the local listener server"
            )  # pragma: no mutate

        headers = {"Host": f"{self._listener_ip}:{self._listener_port}"}
        payload = {"DeviceToken": "xxxxxxxxxxx"}

        _LOGGER.info(
            "Requesting token from AC at %s:%s", self._ac_ip, self._ac_port
        )  # pragma: no mutate

        # Setup Client SSL Context
        # pylint: disable=import-outside-toplevel
        from .helpers import async_create_samsung_ssl_context

        ssl_context = await async_create_samsung_ssl_context(
            cert_path=self._cert_path,
            ciphers="HIGH:!aNULL:!MD5:@SECLEVEL=0",
            verify_mode=ssl.CERT_NONE,
        )

        try:
            _LOGGER.debug(  # pragma: no mutate
                "Sending pairing request via raw socket to %s:%s, Headers: %s, Payload: %s",
                self._ac_ip,
                self._ac_port,
                headers,
                payload,
            )

            # Open a raw socket instead of aiohttp (required for non-standard SSL handshake)
            async with asyncio.timeout(30.0):
                reader, writer = await asyncio.open_connection(
                    self._ac_ip, self._ac_port, ssl=ssl_context
                )

                # Build HTTP request manually (raw socket does not have an HTTP client layer)
                body = json_dumps(payload)
                request_lines = [
                    "POST /devicetoken/request HTTP/1.1",
                    f"Host: {headers['Host']}",
                    "Content-Type: application/json",
                    f"Content-Length: {len(body)}",
                    "Connection: close",
                    "",
                    f"{body}",
                ]
                request_data = "\r\n".join(request_lines)

                writer.write(request_data.encode("utf-8"))
                await writer.drain()

                # Read the response
                response_data = b""
                while True:
                    chunk = await reader.read(4096)
                    if not chunk:
                        break
                    response_data += chunk

                writer.close()
                await writer.wait_closed()

            # Parse the response leniently: we only check for a 200 OK status line
            decoded_resp = response_data.decode(
                "utf-8", errors="ignore"
            )  # pragma: no mutate
            _LOGGER.debug(
                "AC responded to pairing request with:\n%s", decoded_resp[:200]
            )  # pragma: no mutate

            # Only verify that the response looks like a 200 OK (lenient: malformed headers accepted)
            if "200 OK" in decoded_resp:
                _LOGGER.info(
                    "Token request accepted by AC (200 OK via raw socket)"
                )  # pragma: no mutate
            else:
                first_line = (
                    decoded_resp.split("\r\n")[0]
                    if decoded_resp
                    else "<empty response>"
                )
                raise TokenAcquisitionError(  # pragma: no mutate
                    f"AC responded with non-200 status or malformed response: {first_line}"
                )

        except (TimeoutError, ConnectionError, OSError) as e:
            await self.async_close()
            raise CannotConnect(
                f"Failed to connect to AC via raw socket: {e}"
            ) from e  # pragma: no mutate
        except TokenAcquisitionError:
            await self.async_close()
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            await self.async_close()
            raise TokenAcquisitionError(
                f"Unexpected error during pairing request: {e}"
            ) from e  # pragma: no mutate

    async def async_wait_for_token(self) -> str:
        """
        Phase 2: Waits for the token to be received by the local server.
        """
        try:
            async with asyncio.timeout(60.0):
                await self._token_received_event.wait()

            if self._received_token:
                return self._received_token
            raise TokenAcquisitionError(
                "Event was set but no token was stored"
            )  # pragma: no mutate
        except TimeoutError as exc:
            raise TokenAcquisitionError(
                "Timed out waiting for the AC to send the token"
            ) from exc  # pragma: no mutate
        finally:
            await self.async_close()

    async def async_close(self) -> None:
        """Shuts down the listener server."""
        if self._server:
            _LOGGER.info(
                "Shutting down async token listener server"
            )  # pragma: no mutate
            self._server.close()
            await self._server.wait_closed()
            self._server = None
