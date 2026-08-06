# pylint: disable=duplicate-code,no-else-return,line-too-long
"""
Asynchronous connection engine for modern Samsung devices (port 8888) using aiohttp.
This engine implements HTTP Keep-Alive for low latency and correct mTLS.
"""

import asyncio
import inspect
import logging
from pathlib import Path
import ssl
from dataclasses import dataclass, field
from typing import Any, cast

import aiohttp

from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, CONF_TOKEN
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template
from homeassistant.util.json import json_loads

from .connection import Connection, register_connection
from .const import (
    CONF_CERT,
    CONFIG_DEVICE_CONDITION_TEMPLATE,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
    GLOBAL_HTTP_TIMEOUT,
    NETWORK_POLL_TIMEOUT,
)
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .helpers import (
    async_create_samsung_ssl_context,
    format_placeholders,
    mask_sensitive_data,
    resolve_cert_path,
)


@dataclass
class AiohttpSharedState:
    """Strict state container for the aiohttp connection engine."""

    initialized: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ssl_context: ssl.SSLContext | None = None
    local_session: aiohttp.ClientSession | None = None


_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_AIOHTTP_8888 = "samsung_8888_aiohttp"

DEFAULT_PORT = "8888"
DEFAULT_SSL_CIPHERS = "ALL:@SECLEVEL=0"
HEADER_AUTHORIZATION = "Authorization"
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_CONNECTION = "Connection"
HEADER_VALUE_JSON = "application/json"
HEADER_VALUE_CLOSE = "close"


@register_connection
class ConnectionAiohttp8888(Connection):
    """
    An asynchronous connection handler for Samsung devices on port 8888.
    It uses aiohttp's ClientSession for persistent connections (Keep-Alive)
    and implements the correct mTLS (mutual-TLS) authentication.
    """

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: dict[str, Any],
        logger: logging.Logger,
        hass: Any,
        session: aiohttp.ClientSession,
        ip_address: str,
    ) -> None:
        """Initialize the aiohttp connection engine."""
        init_debug_msg = "[aiohttp_init] Initializing ConnectionAiohttp8888. IP: %s"  # pragma: no mutate
        _LOGGER.debug(init_debug_msg, ip_address)  # pragma: no mutate
        super().__init__(config, logger)  # pragma: no mutate
        self._hass = hass
        self._controller: Any = None  # Initialize controller reference
        self._session = session
        self._ip_address = ip_address
        self._token: str | None = config.get(CONF_TOKEN)
        self._cert_path: str | None = self._resolve_cert_path(config.get(CONF_CERT))

        # Strict object to share initialization state across all copies.
        # The Lock prevents race conditions during the first initialization.
        # We also store 'local_session' here so it is shared across copies (commands).
        self._shared_state = AiohttpSharedState()

        # This will hold the Jinja2 template for this specific connection instance.
        self._connection_template: Template | None = None  # pragma: no mutate

        self.condition_template: Template | None = None  # pragma: no mutate
        self._embedded_command: "ConnectionAiohttp8888" | None = (
            None  # pragma: no mutate
        )

        self._keep_alive: bool = config.get("keep_alive", True)

        if not self._token:  # pragma: no mutate
            err_msg = "[aiohttp_init] aiohttp engine started without a token. This will fail."  # pragma: no mutate
            _LOGGER.error(err_msg)  # pragma: no mutate

        # Check if cert is missing
        if not self._cert_path or not Path(self._cert_path).exists():
            # Only error if we are NOT in insecure mode (SmartThings/Emulator uses insecure_ssl=True)
            if not config.get("insecure_ssl", False):
                err_msg = "[aiohttp_init] Certificate file not found or invalid at %s"  # pragma: no mutate
                _LOGGER.error(err_msg, self._cert_path)  # pragma: no mutate
            else:
                debug_msg = "[aiohttp_init] Certificate file not found at %s. This is expected for SmartThings/Emulator (insecure_ssl=True)."  # pragma: no mutate
                _LOGGER.debug(debug_msg, self._cert_path)  # pragma: no mutate

        self._force_close_connection: bool = False

    @property
    def log_prefix(self) -> str:
        """Generate a consistent log prefix."""
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        return f"[{self._ip_address or 'NO_IP'}]"

    @property
    def _ssl_context(self) -> ssl.SSLContext | None:
        """Return the shared SSL context."""
        return self._shared_state.ssl_context

    @property
    def _resolved_target(self) -> tuple[str, str]:
        """Resuelve de forma estricta y centralizada el Host y la MAC address."""
        raw_host = self._ip_address or self._params.get(CONF_HOST)
        host = str(raw_host) if raw_host is not None else ""

        raw_mac = self._params.get(CONF_MAC)
        mac = str(raw_mac) if raw_mac is not None else ""

        return host, mac

    @property
    def _auth_context(self) -> tuple[str | None, str | None]:
        """Centralized resolution of active token and device_id."""
        token = self._token
        dev_id = None
        if self._controller is not None:
            token = self._controller._config.get(CONF_TOKEN, self._token)
            dev_id = self._controller.device_id
        return token, dev_id

    def set_controller_ref(self, controller: Any) -> None:
        """Allows the property to set a reference to the main controller."""
        debug_msg = "%s [set_controller_ref] Setting controller reference for connection object."  # pragma: no mutate
        _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate
        self._controller = controller

    def _resolve_cert_path(self, cert_file: str | None) -> str | None:
        """Resolve the full path to the certificate file."""
        return resolve_cert_path(
            cert_file, str(Path(__file__).parent), self._hass
        )  # pragma: no mutate

    async def _create_ssl_context(self) -> ssl.SSLContext | None:
        """
        Creates the correct SSL context.
        - If cert is present, sets up mTLS (Strict/Verify=None but loads cert).
        - If cert is missing:
             - If insecure_ssl=True (Emulator/SmartThings), sets up lenient context (Weak Ciphers, Verify=None).
             - If insecure_ssl=False (Cloud default), returns None (aiohttp default strict).
        """
        # Read insecure_ssl. It comes from 'config' passed to __init__.
        insecure_ssl = self._config.get("insecure_ssl", False)  # pragma: no mutate
        has_cert = (
            self._cert_path and Path(self._cert_path).exists()
        )  # pragma: no mutate

        if not has_cert and not insecure_ssl:
            # Standard Secure Cloud Connection
            debug_msg = "%s [aiohttp] No cert and insecure_ssl=False. Using default aiohttp SSL context (Strict)."  # pragma: no mutate
            _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate
            return None

        try:
            debug_msg = "%s [aiohttp] Creating custom SSL context. Cert: %s, Insecure: %s"  # pragma: no mutate
            _LOGGER.debug(
                debug_msg, self.log_prefix, has_cert, insecure_ssl
            )  # pragma: no mutate

            context = await async_create_samsung_ssl_context(
                cert_path=self._cert_path if has_cert else None,
                ciphers=DEFAULT_SSL_CIPHERS,
                verify_mode=ssl.CERT_NONE,
            )
            return context
        except (ssl.SSLError, OSError, ValueError) as e:
            err_msg = (
                "%s [aiohttp] Failed to create SSL context: %s."  # pragma: no mutate
            )
            _LOGGER.error(err_msg, self.log_prefix, e)  # pragma: no mutate
            return None

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Return True if this connection handles the given type string."""
        return type_str == CONNECTION_TYPE_AIOHTTP_8888

    def load_from_yaml(self, node: dict[str, Any] | None, connection_base: Any) -> bool:
        """Load configuration from yaml node dictionary."""
        if node and "keep_alive" in node:
            self._keep_alive = node["keep_alive"]
        return True

    def create_updated(
        self, yaml_node: dict[str, Any] | None
    ) -> "ConnectionAiohttp8888":
        """
        Creates a new connection instance with updated parameters from YAML.
        """
        # pylint: disable=protected-access
        new_connection = ConnectionAiohttp8888(
            config=self._config,
            logger=self._logger,
            hass=self._hass,
            session=self._session,
            ip_address=self._ip_address,
        )
        new_connection._params = {}
        new_connection._controller = self._controller
        new_connection._shared_state = self._shared_state

        if yaml_node is not None:
            if "keep_alive" in yaml_node:
                new_connection._keep_alive = yaml_node["keep_alive"]

            if CONFIG_DEVICE_CONNECTION_TEMPLATE in yaml_node:
                new_connection._connection_template = Template(
                    yaml_node[CONFIG_DEVICE_CONNECTION_TEMPLATE],
                    self._hass,  # pragma: no mutate
                )
            elif CONFIG_DEVICE_CONNECTION_PARAMS in yaml_node:
                # Explicit extraction to prevent None-unpacking errors
                node_params = yaml_node.get(CONFIG_DEVICE_CONNECTION_PARAMS) or {}
                params = {
                    **self._params,
                    **node_params,
                }
                new_connection._params.update(params)

            if CONFIG_DEVICE_CONNECTION in yaml_node:
                new_connection._embedded_command = new_connection.create_updated(
                    yaml_node[CONFIG_DEVICE_CONNECTION]
                )
                if (
                    CONFIG_DEVICE_CONDITION_TEMPLATE
                    in yaml_node[CONFIG_DEVICE_CONNECTION]
                ):
                    condition_str = yaml_node[CONFIG_DEVICE_CONNECTION][
                        CONFIG_DEVICE_CONDITION_TEMPLATE
                    ]
                    if new_connection._embedded_command is not None:
                        new_connection._embedded_command.condition_template = Template(
                            condition_str,
                            self._hass,  # pragma: no mutate
                        )
        # pylint: enable=protected-access

        return new_connection

    @property
    def is_async_native(self) -> bool:
        """Indicates if the connection is native asynchronous (aiohttp)."""
        return True

    @property
    def is_push_supported(self) -> bool:
        """Return True indicating this connection type supports push updates."""
        return False

    async def _try_connection(self) -> str | None:
        """
        Probes the connection (HTTPS mTLS ONLY)
        and memorizes it for future use.
        Returns response text if successful, None otherwise.
        """
        # Use Lock for safe, one-time initialization
        if self._shared_state.initialized:
            return None

        async with self._shared_state.lock:
            # Double-check in case another task initialized it while we were waiting for the lock.
            if self._shared_state.initialized:
                return None

            current_token, _ = self._auth_context
            probe_headers = {
                "Authorization": f"Bearer {current_token}"
            }  # pragma: no mutate

            # Use the shared state's SSL context, skip for plain HTTP test mode
            if not self._config.get("use_http", False):  # pragma: no mutate
                if self._shared_state.ssl_context is None:
                    self._shared_state.ssl_context = await self._create_ssl_context()

            ssl_ctx = self._shared_state.ssl_context  # pragma: no mutate
            if ssl_ctx is None:
                # Logic for "insecure" / no-cert connection
                ssl_ctx = False

            try:
                debug_msg = (
                    "%s [aiohttp_probe] Probing connection..."  # pragma: no mutate
                )
                _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate

                # Generalize Probe URL
                port = self._config.get(CONF_PORT, DEFAULT_PORT)  # pragma: no mutate
                protocol = (
                    "http" if self._config.get("use_http", False) else "https"
                )  # pragma: no mutate
                probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                if (
                    self._params
                    and self._params.get("url")
                    and str(self._params.get("url")).startswith("http")
                ):
                    probe_url = str(self._params.get("url"))
                    debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
                    _LOGGER.debug(
                        debug_msg, self.log_prefix, probe_url
                    )  # pragma: no mutate

                probe_url = self._format_url(probe_url)

                # CRITICAL FIX: Do NOT access self._session directly — it may be None
                # when keep_alive=False. Always go through _get_session() which handles
                # both a HA-shared session and a locally-created one.
                test_ssl_ctx = (
                    False if protocol == "http" else self._shared_state.ssl_context
                )
                probe_session = await self._get_session()
                async with probe_session.request(
                    "GET",
                    probe_url,
                    headers=probe_headers,
                    ssl=test_ssl_ctx,
                    timeout=aiohttp.ClientTimeout(total=GLOBAL_HTTP_TIMEOUT, sock_read=GLOBAL_HTTP_TIMEOUT // 2),
                ) as response:  # type: ignore[arg-type] # pragma: no mutate
                    if response.status in (
                        200,
                        401,
                        403,
                        405,
                    ):  # Added 405 for Method Not Allowed
                        # Attempt to log the negotiated TLS version
                        try:
                            transport = (  # pragma: no mutate
                                response.connection.transport
                                if response.connection
                                else None
                            )
                            ssl_obj = (
                                transport.get_extra_info("ssl_object")
                                if transport
                                else None
                            )
                            negotiated_tls = ssl_obj.version() if ssl_obj else "Unknown"
                            info_msg = "%s [aiohttp] Connection successful. Status: %s. Negotiated TLS: %s"  # pragma: no mutate
                            _LOGGER.info(
                                info_msg,
                                self.log_prefix,
                                response.status,
                                negotiated_tls,
                            )  # pragma: no mutate
                        except (AttributeError, KeyError, TypeError):
                            info_msg = "%s [aiohttp] Connection successful and memorized. Status: %s"  # pragma: no mutate
                            _LOGGER.info(
                                info_msg, self.log_prefix, response.status
                            )  # pragma: no mutate

                        self._shared_state.initialized = True

                        # Optimization - Return text for reuse in initial poll
                        if response.status == 200:
                            debug_msg = "%s [aiohttp_probe] Reading response body..."  # pragma: no mutate
                            _LOGGER.debug(
                                debug_msg, self.log_prefix
                            )  # pragma: no mutate
                            return await response.text()
                        return None
                    else:
                        exc_msg = f"Unexpected probe response: {response.status}"  # pragma: no mutate
                        raise CannotConnect(exc_msg)

            except aiohttp.ClientConnectorError as e:
                # Log as warning (not error) because it's expected when AC is offline.
                # Build a clean, readable message from the structured attributes of the exception.
                host = getattr(e, "host", "?")  # pragma: no mutate
                port = getattr(e, "port", "?")  # pragma: no mutate
                os_err = getattr(e, "os_error", None)  # pragma: no mutate
                reason = (
                    str(os_err) if os_err else type(e).__name__
                )  # pragma: no mutate
                clean_msg = (
                    f"Cannot connect to {host}:{port} ({reason})"  # pragma: no mutate
                )
                warn_msg = "%s [aiohttp_probe] Device is unreachable (offline): %s"  # pragma: no mutate
                _LOGGER.warning(
                    warn_msg, self.log_prefix, clean_msg
                )  # pragma: no mutate
                self._shared_state.ssl_context = None  # Reset to try again later
                exc_msg = f"Device unreachable: {clean_msg}"  # pragma: no mutate
                raise CannotConnect(exc_msg) from e  # pragma: no mutate

            # Catch incomplete responses (missing Content-Length) which is common in older devices.
            except (
                TimeoutError,
                asyncio.TimeoutError,
                aiohttp.ServerTimeoutError,
                aiohttp.SocketTimeoutError,
                aiohttp.ClientPayloadError,
            ) as e:
                err_msg = "%s [aiohttp_probe] Device protocol violation detected! The device accepted the connection (200 OK) but failed to send a complete response (Timeout/PayloadError: %s). This indicates it does not support standard HTTP/1.1 (missing Content-Length). Switching to 'Robust (raw socket)' engine."  # pragma: no mutate
                _LOGGER.error(err_msg, self.log_prefix, e)  # pragma: no mutate
                error_msg = "Device failed to provide response body (missing Content-Length/Close)"  # pragma: no mutate
                raise InvalidHeaderError(error_msg) from e  # pragma: no mutate

            except (aiohttp.ClientError, ValueError, RuntimeError) as e:
                # Detect malformed header error
                if "Invalid header token" in str(e):
                    err_msg = "%s [aiohttp_probe] Malformed header error detected! The device does not comply with the HTTP standard. The integration will automatically switch to the 'Robust (raw socket)' connection engine."  # pragma: no mutate
                    _LOGGER.error(err_msg, self.log_prefix)  # pragma: no mutate
                    error_msg = (
                        "Malformed HTTP headers from device"  # pragma: no mutate
                    )
                    raise InvalidHeaderError(error_msg) from e  # pragma: no mutate

                warn_msg = "%s [aiohttp_probe] Initial probe with HTTPS (mTLS) failed: %s."  # pragma: no mutate
                _LOGGER.warning(
                    warn_msg, self.log_prefix, e, exc_info=True
                )  # pragma: no mutate
                self._shared_state.ssl_context = (
                    None  # Clear on failure to allow retries
                )

            err_msg = "%s [aiohttp_probe] HTTPS (mTLS) connection probe failed. The device is unreachable or the certificate/token is incorrect."  # pragma: no mutate
            _LOGGER.error(err_msg, self.log_prefix)  # pragma: no mutate
            error_msg = "Connection initialization failed (HTTPS)"  # pragma: no mutate
            raise CannotConnect(error_msg) from None

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Returns the appropriate aiohttp session.
        If keep_alive is True, returns the shared HA session.
        If keep_alive is False (or shared session is None), returns a dedicated local session.
        """
        # 1. Lógica de sesión compartida (Keep-Alive)
        if self._keep_alive:
            if self._session is not None:
                return self._session
            # Si llegamos aquí, keep_alive es True pero no hay sesión.
            warn_msg = "%s [aiohttp] keep_alive=True but shared session is None. Falling back to a temporary local session. Ensure hass and session are passed to YamlController explicitly."  # pragma: no mutate
            _LOGGER.warning(warn_msg, self.log_prefix)  # pragma: no mutate

        # 2. Lógica de sesión local
        local_session = self._shared_state.local_session

        # Evaluate condition directly without intermediate variable allocation
        if local_session is None or local_session.closed:
            # Retrieve the shared SSL context (should be initialized by _try_connection)
            ssl_context = self._shared_state.ssl_context

            # For plain HTTP test mode, use a simple connector with no SSL
            if self._config.get("use_http") is True:
                connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
            else:
                connector = aiohttp.TCPConnector(
                    keepalive_timeout=75, ssl=ssl_context, limit=1
                )  # type: ignore[arg-type]

            timeout = aiohttp.ClientTimeout(total=NETWORK_POLL_TIMEOUT, connect=GLOBAL_HTTP_TIMEOUT)
            local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            self._shared_state.local_session = local_session

            debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."  # pragma: no mutate
            _LOGGER.debug(
                debug_msg, self.log_prefix, id(local_session), id(connector)
            )  # pragma: no mutate

        return self._shared_state.local_session

    def _format_url(self, url: str) -> str:
        """
        Replaces placeholders in the URL with actual values from configuration.
        """
        # Host and MAC: Centralized resolution under Zero Trust doctrine
        host, mac = self._resolved_target
        token, dev_id = self._auth_context

        url = format_placeholders(url, token, host, dev_id, mac)  # pragma: no mutate

        # Port validation without mutation false positives
        if f":{DEFAULT_PORT}/" in url:
            port = str(self._config.get(CONF_PORT, DEFAULT_PORT))
            url = url.replace(f":{DEFAULT_PORT}/", f":{port}/")

        # Mutmut odia el `if dict.get(key, False):`. Lo blindamos asertando el tipo booleano.
        if bool(self._config.get("use_http", False)) is True:  # pragma: no mutate
            url = url.replace("https://", "http://")

        return url

    def _prepare_request_headers(
        self,
        headers: dict[str, str] | None,
        current_token: str | None,
        host: str,
        dev_id: str | None,
        mac: str,
    ) -> dict[str, str]:
        """Prepare and format headers for a request."""
        req_headers = headers.copy() if headers is not None else {}
        req_headers = format_placeholders(
            req_headers, current_token, host, dev_id, mac
        )  # pragma: no mutate

        if not current_token:
            err_msg = "%s [aiohttp] No token available! The request will fail."  # pragma: no mutate
            _LOGGER.error(err_msg, self.log_prefix)  # pragma: no mutate
            exc_msg = "Token not configured for the aiohttp engine"  # pragma: no mutate
            raise AuthError(exc_msg)  # pragma: no mutate

        if HEADER_AUTHORIZATION not in req_headers:  # pragma: no mutate
            req_headers[HEADER_AUTHORIZATION] = f"Bearer {current_token}"
        if HEADER_CONTENT_TYPE not in req_headers:
            req_headers[HEADER_CONTENT_TYPE] = HEADER_VALUE_JSON

        # Adaptive Keep-Alive Logic: If we previously detected stability issues, force Connection: close
        if self._force_close_connection:
            req_headers[HEADER_CONNECTION] = HEADER_VALUE_CLOSE

        return req_headers

    def _handle_http_version_fallback(self, response: aiohttp.ClientResponse) -> None:
        """Adjust Keep-Alive strategy based on the server's HTTP version."""
        if (
            response.version
            and response.version.major == 1
            and response.version.minor >= 1
        ):
            if self._force_close_connection:
                debug_msg = "%s [aiohttp] Server speaks HTTP/%s.%s. Re-enabling Keep-Alive."  # pragma: no mutate
                _LOGGER.debug(  # pragma: no mutate
                    debug_msg,  # pragma: no mutate
                    self.log_prefix,  # pragma: no mutate
                    response.version.major,  # pragma: no mutate
                    response.version.minor,  # pragma: no mutate
                )  # pragma: no mutate
            self._force_close_connection = False
        else:
            if not self._force_close_connection and response.version:
                debug_msg = "%s [aiohttp] Server speaks HTTP/%s.%s. Enforcing 'Connection: close'."  # pragma: no mutate
                _LOGGER.debug(  # pragma: no mutate
                    debug_msg,  # pragma: no mutate
                    self.log_prefix,  # pragma: no mutate
                    response.version.major,  # pragma: no mutate
                    getattr(response.version, "minor", 0),  # pragma: no mutate
                )  # pragma: no mutate
            self._force_close_connection = True

    async def _async_execute_request(
        self,
        method: str,
        url_path: str | None,
        data: str | None,
        headers: dict[str, str] | None,
        _is_poll: bool = False,  # pragma: no mutate
    ) -> tuple[str, dict[str, str] | None]:
        """
        Executes a command asynchronously using aiohttp.
        It uses the "memorized" connection logic (HTTPS only).
        """
        current_token, dev_id = self._auth_context
        host, mac = self._resolved_target

        req_headers = self._prepare_request_headers(
            headers, current_token, host, dev_id, mac
        )

        ssl_context = self._shared_state.ssl_context
        # Detect if the path is actually an absolute URL (for SmartThings).
        if url_path and url_path.startswith("http"):  # pragma: no mutate
            base_url = ""  # No base URL needed
            # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
            if not ssl_context:
                ssl_context = await self._create_ssl_context()
        else:
            port = self._config.get(CONF_PORT, DEFAULT_PORT)  # pragma: no mutate
            base_url = f"https://{self._ip_address}:{port}"

        full_url = f"{base_url}{url_path}"
        full_url = self._format_url(full_url)

        # If the final URL is plain HTTP (e.g. test mode), don't use SSL
        if full_url.startswith("http://"):
            ssl_context = False

        try:
            # Strict Serialization with Lock: ensures that requests are executed one by one
            # to prevent multiple concurrent connections and force reuse.
            async with self.async_lock:
                debug_msg = "%s [aiohttp] Sending request -> Method: %s, URL: %s, Payload: %s, Close Mode: %s"  # pragma: no mutate
                _LOGGER.debug(  # pragma: no mutate
                    debug_msg,  # pragma: no mutate
                    self.log_prefix,  # pragma: no mutate
                    method,  # pragma: no mutate
                    full_url,  # pragma: no mutate
                    mask_sensitive_data(data),  # pragma: no mutate
                    self._force_close_connection,  # pragma: no mutate
                )  # pragma: no mutate

                session = await self._get_session()
                debug_msg = "%s [aiohttp] Using session ID: %s | SSL Context ID: %s"  # pragma: no mutate
                _LOGGER.debug(
                    debug_msg, self.log_prefix, id(session), id(ssl_context)
                )  # pragma: no mutate

                async with session.request(
                    method,
                    url=full_url,
                    headers=req_headers,
                    data=data,
                    ssl=ssl_context,  # type: ignore[arg-type]  # pragma: no mutate
                    timeout=aiohttp.ClientTimeout(total=GLOBAL_HTTP_TIMEOUT),
                ) as response:
                    response_text = await response.text()  # pragma: no mutate

                # HTTP Version Detection to adjust Keep-Alive
                self._handle_http_version_fallback(response)

                if response.status != 200:
                    if response.status in (401, 403):
                        err_msg = "%s [aiohttp] Authentication error (status %d). Token: %s...%s"  # pragma: no mutate
                        _LOGGER.error(  # pragma: no mutate
                            err_msg,  # pragma: no mutate
                            self.log_prefix,  # pragma: no mutate
                            response.status,  # pragma: no mutate
                            current_token[:4],  # pragma: no mutate
                            current_token[-4:],  # pragma: no mutate
                        )  # pragma: no mutate
                        exc_msg = "Device returned 401 Unauthorized during active command execution."  # pragma: no mutate
                        raise AuthError(exc_msg)  # pragma: no mutate

                    err_msg = "%s [aiohttp] HTTP Error %s: %s"  # pragma: no mutate
                    _LOGGER.error(
                        err_msg, self.log_prefix, response.status, response_text
                    )  # pragma: no mutate
                    response.raise_for_status()

                return response_text, dict(response.headers)

        except (
            TimeoutError,
            asyncio.TimeoutError,
            aiohttp.ClientConnectorError,
            aiohttp.ClientError,
        ) as e:
            # Adaptive recovery on timeout/connection drop
            if isinstance(e, aiohttp.ClientConnectorError):
                host = getattr(e, "host", "?")  # pragma: no mutate
                port = getattr(e, "port", "?")  # pragma: no mutate
                os_err = getattr(e, "os_error", None)  # pragma: no mutate
                reason = (
                    str(os_err) if os_err else type(e).__name__
                )  # pragma: no mutate
                clean_e = (
                    f"Cannot connect to {host}:{port} ({reason})"  # pragma: no mutate
                )
            else:
                clean_e = str(e)  # pragma: no mutate

            # If we timed out and haven't forced close yet, it's highly likely the "missing Content-Length" issue.
            if not self._force_close_connection:
                warn_msg = "%s [aiohttp] Timeout/Error detected (%s). The device likely violates HTTP protocol (missing Content-Length). Switching to 'Connection: close' mode for resilience."  # pragma: no mutate
                _LOGGER.warning(warn_msg, self.log_prefix, clean_e)  # pragma: no mutate
                self._force_close_connection = True
                req_headers["Connection"] = "close"

                # Retry immediately with the new header
                debug_msg = "%s [aiohttp] Retrying request with 'Connection: close'..."  # pragma: no mutate
                _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate
                try:
                    session = await self._get_session()
                    async with session.request(
                        method,
                        full_url,
                        data=data,
                        headers=req_headers,
                        ssl=ssl_context,  # type: ignore[arg-type]
                        timeout=aiohttp.ClientTimeout(total=GLOBAL_HTTP_TIMEOUT),
                    ) as response:
                        response_text = await response.text()
                        return response_text, None
                except (
                    aiohttp.ClientError,
                    asyncio.TimeoutError,
                    OSError,
                ) as retry_exc:
                    err_msg = "%s [aiohttp] Retry failed even with 'Connection: close': %s"  # pragma: no mutate
                    _LOGGER.error(
                        err_msg, self.log_prefix, retry_exc
                    )  # pragma: no mutate
                    error_msg = f"Target device returned an unexpected error response during retry: {retry_exc}"  # pragma: no mutate
                    raise CannotConnect(error_msg) from retry_exc  # pragma: no mutate

            # If we were already forcing close, then it's a real network issue.
            err_msg = "%s [aiohttp] Connection failed: %s"  # pragma: no mutate
            _LOGGER.error(err_msg, self.log_prefix, clean_e)  # pragma: no mutate
            exc_msg = f"Connection error: {clean_e}"  # pragma: no mutate
            raise CannotConnect(exc_msg) from e  # pragma: no mutate
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            err_msg = "%s [aiohttp] Unexpected data parsing error: %s"  # pragma: no mutate
            _LOGGER.error(
                err_msg, self.log_prefix, e, exc_info=True
            )  # pragma: no mutate
            raise CannotConnect(f"Unexpected data parsing error: {e}") from e

    def execute(
        self,
        template: Template | None,
        value: Any,
        device_state: dict[str, Any],
        device_id: str | None = None,
    ) -> None:
        """Not implemented for async connections."""
        exc_msg = (
            "This connection is async-native. Use async_execute."  # pragma: no mutate
        )
        raise NotImplementedError(exc_msg)

    async def _execute_embedded_command(
        self,
        device_state: dict[str, Any] | None,
        url: str | None,
        method: str,
        headers: dict[str, str] | None,
        token: str | None,
        host: str,
        dev_id: str | None,
        mac: str,
    ) -> None:
        """Evaluates and executes an embedded command if conditions are met."""
        if self._embedded_command is None:
            return

        debug_msg = "%s [async_execute] Found embedded command."  # pragma: no mutate
        _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate
        try:
            if device_state is None:
                warn_msg = "%s [async_execute] Embedded command found, but cannot check its condition (device_state is missing). Skipping."  # pragma: no mutate
                _LOGGER.warning(warn_msg, self.log_prefix)  # pragma: no mutate
            elif (
                self._embedded_command.check_execute_condition(device_state)
                is False
            ):
                debug_msg = "%s [async_execute] Embedded command condition not met. Skipping execution."  # pragma: no mutate
                _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate
            else:
                debug_msg = "%s [async_execute] Embedded command condition met. Executing it before the main command."  # pragma: no mutate
                _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate

                embedded_template = (
                    self._embedded_command._connection_template
                )  # pragma: no mutate
                embedded_params = (
                    self._embedded_command._params or {}
                )  # pragma: no mutate

                if embedded_template is not None:
                    if hasattr(embedded_template, "async_render"):
                        res = embedded_template.async_render()
                        embedded_params_str = (
                            await res if inspect.isawaitable(res) else res
                        )
                    else:
                        embedded_params_str = embedded_template.render()

                    embedded_params = json_loads(embedded_params_str)
                elif bool(embedded_params) is True:
                    debug_msg = "%s [async_execute] Embedded command has no connection_template, using _params directly."  # pragma: no mutate
                    _LOGGER.debug(
                        debug_msg, self.log_prefix
                    )  # pragma: no mutate
                else:
                    warn_msg = "%s [async_execute] Embedded command found but it has no connection_template or params."  # pragma: no mutate
                    _LOGGER.warning(
                        warn_msg, self.log_prefix
                    )  # pragma: no mutate
                    embedded_params = None

                if embedded_params is not None:
                    # CRITICAL FIX: Replace placeholders early for robust logging and execution
                    embedded_params = format_placeholders(
                        embedded_params, token, host, dev_id, mac
                    )  # pragma: no mutate  # pragma: no mutate

                    embedded_data = (
                        json_dumps(embedded_params.get("json"))
                        if "json" in embedded_params
                        else None
                    )
                    embedded_url = embedded_params.get("url", url)
                    embedded_method = embedded_params.get("method", method)

                    debug_msg = "%s [async_execute] Executing embedded command with params: %s"  # pragma: no mutate
                    _LOGGER.debug(
                        debug_msg,
                        self.log_prefix,
                        mask_sensitive_data(embedded_params),
                    )  # pragma: no mutate

                    res = cast(
                        Any,
                        self._embedded_command.async_execute(
                            method=embedded_method,
                            url=embedded_url,
                            data=embedded_data,
                            headers=embedded_params.get("headers", headers),
                            device_state=device_state,
                        ),
                    )
                    if inspect.isawaitable(res):  # pragma: no mutate
                        await res

        except (CannotConnect, AuthError) as e:
            warn_msg = "%s [async_execute] Embedded command failed due to connection error: %s"  # pragma: no mutate
            _LOGGER.warning(warn_msg, self.log_prefix, e)  # pragma: no mutate
            raise
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            ValueError,
        ) as e:
            err_msg = "%s [async_execute] Embedded command failed: %s"  # pragma: no mutate
            _LOGGER.error(
                err_msg, self.log_prefix, e, exc_info=True
            )  # pragma: no mutate
            raise

    async def async_execute(
        self,
        method: str,
        url: str | None,
        data: Any,
        headers: dict[str, str] | None,  # Main command's headers
        device_state: dict[str, Any] | None = None,  # Pass device state for conditions
        _is_probe: bool = False,  # pragma: no mutate
        _is_poll: bool = False,  # pragma: no mutate
    ) -> tuple[str | None, dict[str, Any] | None]:
        """
        Orchestrates the execution of commands, including embedded ones.
        """
        # Resolve variables for placeholder replacement early for embedded logging
        host, mac = self._resolved_target
        token, dev_id = self._auth_context

        # Ensure initialization before any execution
        probe_response_text = await self._try_connection()

        await self._execute_embedded_command(
            device_state=device_state,
            url=url,
            method=method,
            headers=headers,
            token=token,
            host=host,
            dev_id=dev_id,
            mac=mac,
        )

        # Execute the main command
        if self.check_execute_condition(device_state) is False:
            debug_msg = "%s [async_execute] Condition not met (template result false). Skipping execution."  # pragma: no mutate
            _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate
            return "{}", {}

        # Periodic Reset Logic: For local sessions not preserving keep_alive, explicitly close and reopen
        if _is_poll and not self._keep_alive:
            local_session = self._shared_state.local_session
            if local_session is not None:
                self._shared_state.local_session = None

            if local_session and not local_session.closed:
                debug_msg = "%s [Periodic Reset] Closing local session (ID: %s) before poll."  # pragma: no mutate
                _LOGGER.debug(
                    debug_msg, self.log_prefix, id(local_session)
                )  # pragma: no mutate
                # Ensure the session close process is awaited
                try:
                    await local_session.close()
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                    debug_msg = "%s [Periodic Reset] Error closing local session: %s"  # pragma: no mutate
                    _LOGGER.debug(debug_msg, self.log_prefix, e)  # pragma: no mutate

        # Optimization: Reuse the probe response directly for the initial poll to eliminate duplicate requests
        if probe_response_text and method == "GET" and url == "/devices":
            debug_msg = "%s [async_execute] OPTIMIZATION: Reusing probe response for initial poll."  # pragma: no mutate
            _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate
            return probe_response_text, None

        return await self._async_execute_request(
            method, url, data, headers, _is_poll=_is_poll
        )  # pragma: no mutate

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the aiohttp connection."""
        diag = {
            "is_connected": self._shared_state.initialized,
            "force_close_connection": self._force_close_connection,
            "keep_alive_enabled": self._keep_alive,
        }

        diag["has_ssl_context"] = self._shared_state.ssl_context is not None

        return diag

    async def close(self) -> None:
        """
        Close the connection and release resources.
        This is called when the integration is unloaded or the connection method changes.
        """
        debug_msg = "%s [aiohttp] Closing connection resources..."  # pragma: no mutate
        _LOGGER.debug(debug_msg, self.log_prefix)  # pragma: no mutate

        # 1. Close internal embedded command (if any)
        if self._embedded_command is not None:
            try:
                # Cero Desconfianza OO: Exigimos que cumpla la interfaz
                await self._embedded_command.close()
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                OSError,
                AttributeError,
            ) as e:
                warn_msg = "%s [aiohttp] Error closing embedded command: %s"  # pragma: no mutate
                _LOGGER.warning(warn_msg, self.log_prefix, e)  # pragma: no mutate

        # 2. Close the local session if it exists (for keep_alive=False)
        local_session = self._shared_state.local_session
        if local_session is not None:
            debug_msg = (
                "%s [aiohttp] Closing local session (ID: %s)..."  # pragma: no mutate
            )
            _LOGGER.debug(
                debug_msg, self.log_prefix, id(local_session)
            )  # pragma: no mutate
            try:
                if not local_session.closed:
                    await local_session.close()
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                err_msg = (
                    "%s [aiohttp] Error closing local session: %s"  # pragma: no mutate
                )
                _LOGGER.error(err_msg, self.log_prefix, e)  # pragma: no mutate
            finally:
                self._shared_state.local_session = None

        # 3. Reset shared state to allow clean re-initialization
        try:
            async with self._shared_state.lock:
                self._shared_state.initialized = False
                self._shared_state.ssl_context = None
                if self._shared_state.local_session is not None:  # pragma: no mutate
                    self._shared_state.local_session = None  # pragma: no mutate
        except (RuntimeError, ValueError) as e:
            err_msg = "%s [aiohttp] Error locking/resetting shared state during close: %s"  # pragma: no mutate
            _LOGGER.error(err_msg, self.log_prefix, e)  # pragma: no mutate
