# climate_ip/token_acquirer_8888.py
"""Helper to acquire a token from modern Samsung AC units (port 8888)."""

import asyncio
import http.server
import json
import logging
import os
import ssl
import threading
import re  # Added for robust token extraction
import socket # Added to handle timeouts
from functools import partial
from typing import Optional

# Third-party imports
import requests
import urllib3
import urllib3.connection as connection_mod
import urllib3.util.response as response_util
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from urllib3.exceptions import HeaderParsingError
from urllib3.poolmanager import PoolManager

# Local imports
from .exceptions import TokenAcquisitionError

_LOGGER = logging.getLogger(__name__)

# --- MONKEY PATCH START ---
# Monkey-patch urllib3 to be more tolerant of malformed headers from some AC units.
# This is necessary because some devices may return headers with extra spaces.

_LOGGER_PATCH = logging.getLogger(__package__)
_original_assert = response_util.assert_header_parsing

def _tolerant_assert_header_parsing(headers):
    """A tolerant version of assert_header_parsing that logs instead of raising."""
    try:
        _original_assert(headers)
    except HeaderParsingError as e:
        _LOGGER_PATCH.debug("Ignored HeaderParsingError: %s", e)

# Apply the patch
response_util.assert_header_parsing = _tolerant_assert_header_parsing
connection_mod.assert_header_parsing = _tolerant_assert_header_parsing
# --- MONKEY PATCH END ---


class TLSv1Adapter(HTTPAdapter):
    """A requests adapter that forces TLSv1.0 protocol."""

    def init_poolmanager(self, connections, maxsize, block=False):
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
        context.set_ciphers('HIGH:!aNULL:!MD5:@SECLEVEL=0')
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=context,
        )


class SamsungTokenAcquirer8888:
    """Manages the token acquisition process for modern Samsung ACs."""

    def __init__(self, hass, ac_ip: str, cert_path: str):
        self._hass = hass
        self._ac_ip = ac_ip

        # Resolve the certificate path. If a path without a directory is provided,
        # assume it is relative to the integration's directory.
        if cert_path and not os.path.dirname(cert_path):
            _LOGGER.debug(
                "Certificate path '%s' appears to be a filename. Resolving relative to integration directory.",
                cert_path,
            )
            self._cert_path = os.path.join(os.path.dirname(__file__), cert_path)
        else:
            # The path is absolute or contains directory components, use it as is.
            self._cert_path = cert_path
        _LOGGER.debug("Final resolved certificate path for token acquirer: %s", self._cert_path)

        self._listener_ip = hass.config.api.local_ip
        self._listener_port = 8889  # Port for our temporary server
        self._ac_port = 8888
        self._token_received_event = asyncio.Event()
        self._received_token: Optional[str] = None
        self._httpd: Optional[http.server.HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None

    def _token_handler_factory(self):
        """Factory to create a request handler with access to this instance."""
        acquirer_instance = self

        class TokenHandler(http.server.BaseHTTPRequestHandler):
            """Handles the POST request from the AC to deliver the token."""

            def do_POST(self):
                token = None
                try:
                    # LOG: Log incoming request headers and body for debugging.
                    _LOGGER.debug("Token listener received POST request. Headers: %s", self.headers)

                    content_length_str = self.headers.get('Content-Length')
                    raw_data = b""

                    if content_length_str:
                        # Happy path: Headers are correct
                        try:
                            content_length = int(content_length_str)
                            raw_data = self.rfile.read(content_length)
                        except ValueError:
                             _LOGGER.warning("Invalid Content-Length received: %s", content_length_str)
                    else:
                        # Malformed path: The AC sent bad headers (e.g. empty lines in header section)
                        # causing Python to stop parsing early. Content-Length is likely in the 'body'
                        # waiting to be read from the socket.
                        _LOGGER.debug(
                            "Content-Length missing (likely malformed AC headers). Attempting blind read."
                        )
                        
                        # We set a timeout to avoid hanging if the socket is empty, 
                        # though usually the data is already buffered.
                        try:
                            self.connection.settimeout(2.0)
                            # Read a chunk large enough to contain the malformed headers + JSON body
                            # 2048 bytes is plenty for a token request.
                            raw_data = self.rfile.read(2048)
                        except socket.timeout:
                            _LOGGER.debug("Socket timed out during blind read (this might be expected if data was short)")
                        except Exception as e:
                            _LOGGER.error("Error during blind read: %s", e)

                    # Decode data
                    decoded_data = raw_data.decode('utf-8', errors='ignore')
                    _LOGGER.debug("Token listener processed data: %s", decoded_data)

                    # STRATEGY 1: Try parsing valid JSON
                    try:
                        if decoded_data.strip():
                            # If the data contains malformed headers at the start, JSON load will fail.
                            # We try finding the start of the JSON object first.
                            json_start = decoded_data.find('{')
                            if json_start != -1:
                                json_candidate = decoded_data[json_start:]
                                data = json.loads(json_candidate)
                                token = data.get('DeviceToken')
                    except Exception as json_err:
                        _LOGGER.debug("Standard JSON parsing failed: %s", json_err)

                    # STRATEGY 2: Regex fallback (Robust)
                    # If JSON parsing failed (due to garbage data), use regex to grab the token directly.
                    if not token:
                        _LOGGER.debug("Attempting Regex token extraction.")
                        # Looks for "DeviceToken" : "xxxxxxxx" ignoring whitespace/quotes style
                        match = re.search(r'DeviceToken["\s:]+([^"\s}]+)', decoded_data)
                        if match:
                            token = match.group(1).strip('"')

                    if token:
                        _LOGGER.info("Token successfully received from AC unit.")
                        acquirer_instance._received_token = token
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b'OK')
                        # Signal that the token has been received
                        acquirer_instance._hass.loop.call_soon_threadsafe(
                            acquirer_instance._token_received_event.set
                        )
                    else:
                        _LOGGER.warning("POST request processed but no token could be extracted.")
                        self.send_response(400, "Token not found")
                        self.end_headers()

                except Exception as e:
                    _LOGGER.error("Error handling POST request from AC: %s", e, exc_info=True)
                    try:
                        self.send_response(500, "Internal Server Error")
                        self.end_headers()
                    except:
                        pass

            def log_message(self, format, *args):
                # Suppress logging to keep the console clean
                return

        return TokenHandler

    def _start_listener_server(self):
        """Starts the HTTPS listener server in a separate thread."""
        try:
            handler_class = self._token_handler_factory()

            # FIX: Allow reusing the address to prevent "Address in use" errors on restart
            class ReusableTCPServer(http.server.HTTPServer):
                allow_reuse_address = True

            self._httpd = ReusableTCPServer(('0.0.0.0', self._listener_port), handler_class)

            context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
            context.set_ciphers('HIGH:!aNULL:!MD5:@SECLEVEL=0')
            context.load_cert_chain(certfile=self._cert_path)

            self._httpd.socket = context.wrap_socket(self._httpd.socket, server_side=True)

            self._server_thread = threading.Thread(target=self._httpd.serve_forever)
            self._server_thread.daemon = True
            self._server_thread.start()
            _LOGGER.info("Temporary token listener server started on port %s", self._listener_port)
            return True
        except Exception as e:
            _LOGGER.error("Failed to start listener server: %s", e, exc_info=True)
            return False

    async def async_initiate_pairing(self) -> None:
        """
        Phase 1: Starts the local server and sends the initial token request to the AC.
        """
        if not await self._hass.async_add_executor_job(self._start_listener_server):
            raise TokenAcquisitionError("Failed to start the local listener server")

        await asyncio.sleep(1)  # Give the server a moment to start

        url = f"https://{self._ac_ip}:{self._ac_port}/devicetoken/request"
        headers = {'Host': f"{self._listener_ip}:{self._listener_port}"}
        payload = {"DeviceToken": "xxxxxxxxxxx"}

        _LOGGER.info("Requesting token from AC at %s:%s", self._ac_ip, self._ac_port)
        session = requests.Session()
        session.mount('https://', TLSv1Adapter())

        try:
            urllib3.disable_warnings(InsecureRequestWarning)

            # LOG: Log the outgoing request details for debugging.
            _LOGGER.debug(
                "Sending pairing request to URL: %s, Headers: %s, Payload: %s",
                url,
                headers,
                payload,
            )

            # FIX: Correctly wrap the blocking call for async_add_executor_job
            func = partial(
                session.post,
                url,
                headers=headers,
                json=payload,
                cert=self._cert_path,
                verify=False,
                timeout=30,  # FIX: Increase timeout from 15 to 30 seconds for the handshake.
            )
            response = await self._hass.async_add_executor_job(func)

            # LOG: Log the response from the AC.
            _LOGGER.debug(
                "AC responded to pairing request with status %s and body: %s",
                response.status_code,
                response.text,
            )

            if response.status_code != 200:
                raise TokenAcquisitionError(
                    f"AC responded with non-200 status: {response.status_code} - {response.text}"
                )
            _LOGGER.info("Token request sent successfully to the AC unit")

        except requests.exceptions.RequestException as e:
            await self.async_close()
            raise TokenAcquisitionError(f"Failed to connect to AC: {e}")

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
        if self._httpd:
            _LOGGER.info("Shutting down temporary token listener server")
            await self._hass.async_add_executor_job(self._httpd.shutdown)
            if self._server_thread:
                self._server_thread.join()
            self._httpd = None
            self._server_thread = None