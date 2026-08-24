# pylint: disable=duplicate-code,no-else-return,line-too-long,abstract-method,too-many-lines,comparison-with-callable
"""
Asynchronous connection engine for modern Samsung devices (port 8888) using aiohttp.
This engine implements HTTP Keep-Alive for low latency and correct mTLS.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
import logging
import os
from pathlib import Path
import ssl
from typing import TYPE_CHECKING, Any, cast

import aiohttp
from aiohttp.hdrs import AUTHORIZATION, CONNECTION, CONTENT_TYPE
from homeassistant.const import CONF_MAC, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template
from homeassistant.util.json import json_loads
import yarl

from .connection import Connection, register_connection
from .const import (
    CONF_CERT,
    CONF_INSECURE_SSL,
    CONF_KEEP_ALIVE,
    CONF_USE_HTTP,
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

if TYPE_CHECKING:
    from .controller_yaml import YamlController


@dataclass
class AiohttpSharedState:
    """Strict state container for the aiohttp connection engine."""

    initialized: bool = False
    lock: asyncio.Lock | None = None
    ssl_context: ssl.SSLContext | None = None
    local_session: aiohttp.ClientSession | None = None
    force_close_connection: bool = False


_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_AIOHTTP_8888 = "samsung_8888_aiohttp"

DEFAULT_PORT = 8888
DEFAULT_SSL_CIPHERS = "ALL:@SECLEVEL=0"
HEADER_VALUE_JSON = "application/json"
HEADER_VALUE_CLOSE = "close"
KEEPALIVE_TIMEOUT = 75

_KEY_PROBE_URL = "probe_url"
_KEY_URL = "url"
_KEY_JSON = "json"
_KEY_METHOD = "method"
_KEY_HEADERS = "headers"

AUTH_BEARER_PREFIX = "Bearer {}"
DEFAULT_HTTP_METHOD = "GET"


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
        hass: HomeAssistant | None = None,
        session: aiohttp.ClientSession | None = None,
        ip_address: str | None = None,
    ) -> None:
        super().__init__(config, logger, hass=hass)
        self._hass = hass
        self._controller: YamlController | None = (
            None  # Initialize controller reference
        )
        self._session = session
        self._ip_address = ip_address
        self._token: str | None = config.get(CONF_TOKEN)
        self._raw_cert_path: str | None = config.get(CONF_CERT)
        self._cert_path: str | None = None

        # Strict object to share initialization state across all copies.
        # The Lock prevents race conditions during the first initialization.
        # We also store 'local_session' here so it is shared across copies (commands).
        self._shared_state = AiohttpSharedState()

        # This will hold the Jinja2 template for this specific connection instance.
        self._connection_template: Template | None = None

        self.condition_template: Template | None = None
        self._embedded_command: ConnectionAiohttp8888 | None = None

        self._keep_alive: bool = config.get(CONF_KEEP_ALIVE, True)

        if self._token is None or len(self._token.strip()) == 0:
            err_msg = (
                "[aiohttp_init] aiohttp engine started without a token. This will fail."
            )
            _LOGGER.error(err_msg)
            raise AuthError("[aiohttp_init] aiohttp engine started without a token.")

    @property
    def _force_close_connection(self) -> bool:
        """Return shared force close connection flag."""
        return self._shared_state.force_close_connection

    @_force_close_connection.setter
    def _force_close_connection(self, value: bool) -> None:
        """Set shared force close connection flag."""
        self._shared_state.force_close_connection = value

    @property
    def log_prefix(self) -> str:
        """Generate a consistent log prefix."""
        if self._controller is not None and self._controller.unique_id is not None:
            return self._controller.log_prefix
        ip = (
            self._ip_address
            if self._ip_address is not None and len(self._ip_address.strip()) > 0
            else "NO_IP"
        )
        return f"[{ip}]"

    @property
    def _ssl_context(self) -> ssl.SSLContext | None:
        """Return the shared SSL context."""
        return self._shared_state.ssl_context

    @property
    def _resolved_target(self) -> tuple[str, str]:
        """Strictly and centrally resolve the Host and MAC address."""
        host = self._ip_address if self._ip_address is not None else ""
        raw_mac = self._params.get(CONF_MAC)
        mac = str(raw_mac) if raw_mac is not None else ""  # pragma: no mutate
        return host, mac

    @property
    def _auth_context(self) -> tuple[str | None, str | None]:
        """Centralized resolution of active token and device_id."""
        token = self._token
        dev_id = None
        if self._controller is not None:
            token = self._controller.config.get(CONF_TOKEN, self._token)
            dev_id = self._controller.device_id
        return token, dev_id

    @property
    def _probe_url_path(self) -> str:
        """Centrally resolve the probe or standard URL path from params."""
        if len(self._params) > 0:
            probe_url = self._params.get(_KEY_PROBE_URL)
            if probe_url is not None:
                return cast(str, probe_url)
            url = self._params.get(_KEY_URL)
            if url is not None:
                return cast(str, url)
        return ""

    def set_controller_ref(self, controller: YamlController) -> None:
        """Allows the property to set a reference to the main controller."""
        debug_msg = "%s [set_controller_ref] Setting controller reference for connection object."
        _LOGGER.debug(debug_msg, self.log_prefix)
        self._controller = controller
        if self._embedded_command is not None:
            self._embedded_command.set_controller_ref(controller)

    def _resolve_cert_path(self, cert_file: str | None) -> str | None:
        """Resolve the full path to the certificate file."""
        return resolve_cert_path(cert_file, str(Path(__file__).parent), self._hass)

    def _resolve_and_verify_cert(self, raw_path: str | None) -> str | None:
        """Synchronously resolve and verify certificate path."""
        if raw_path is None or len(raw_path.strip()) == 0:
            return None
        path = self._resolve_cert_path(raw_path)
        if path is None or len(path.strip()) == 0 or not os.path.exists(path):
            return None
        return path

    async def _create_ssl_context(self) -> ssl.SSLContext | None:
        """
        Creates the correct SSL context.
        - If cert is present, sets up mTLS (Strict/Verify=None but loads cert).
        - If cert is missing:
             - If insecure_ssl=True (Emulator/SmartThings), sets up lenient context (Weak Ciphers, Verify=None).
             - If insecure_ssl=False (Cloud default), returns None (aiohttp default strict).
        """
        # Read insecure_ssl. It comes from 'config' passed to __init__.
        insecure_ssl = self._config.get(CONF_INSECURE_SSL, False)

        # Consolidated executor call
        if (
            self._cert_path is None
            and self._raw_cert_path is not None
            and self._hass is not None
        ):
            resolved = await self._hass.async_add_executor_job(
                self._resolve_and_verify_cert, self._raw_cert_path
            )
            self._cert_path = resolved if resolved is not None else ""

        has_cert = self._cert_path is not None and len(self._cert_path.strip()) > 0

        if not has_cert and not insecure_ssl:
            # Standard Secure Cloud Connection
            debug_msg = "%s [aiohttp] No cert and insecure_ssl=False. Using default aiohttp SSL context (Strict)."
            _LOGGER.debug(debug_msg, self.log_prefix)
            return None

        try:
            debug_msg = (
                "%s [aiohttp] Creating custom SSL context. Cert: %s, Insecure: %s"
            )
            _LOGGER.debug(debug_msg, self.log_prefix, has_cert, insecure_ssl)

            context = await async_create_samsung_ssl_context(
                cert_path=self._cert_path if has_cert else None,
                ciphers=DEFAULT_SSL_CIPHERS,
                verify_mode=ssl.CERT_NONE,
            )
            return context
        except (ssl.SSLError, OSError, ValueError) as e:
            err_msg = "%s [aiohttp] Failed to create SSL context: %s."
            _LOGGER.error(err_msg, self.log_prefix, e)
            raise CannotConnect(f"SSL context creation failed: {e}") from e

    @staticmethod
    def _is_http_protocol_violation(exc: BaseException) -> bool:
        """Check if exception represents an HTTP protocol/header violation requiring fallback to RAW."""
        if isinstance(exc, aiohttp.ClientConnectorError):
            return False  # pragma: no mutate
        return isinstance(
            exc,
            (
                aiohttp.ClientPayloadError,
                aiohttp.http_exceptions.BadHttpMessage,
                ValueError,
                ConnectionError,
            ),
        )

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Return True if this connection handles the given type string."""
        return type_str == CONNECTION_TYPE_AIOHTTP_8888

    def load_from_yaml(
        self, node: dict[str, Any] | None, connection_base: Connection
    ) -> bool:
        """Load configuration from yaml node dictionary."""
        if node is not None:
            keep_alive = node.get(CONF_KEEP_ALIVE)
            if keep_alive is not None:
                self._keep_alive = keep_alive
        return True

    def create_updated(self, yaml_node: dict[str, Any] | None) -> ConnectionAiohttp8888:
        """
        Creates a new connection instance with updated parameters from YAML.
        """
        # pylint: disable=protected-access
        new_connection = ConnectionAiohttp8888(  # pragma: no mutate
            config=self._config,
            logger=self._logger,
            hass=self._hass,
            session=self._session,
            ip_address=self._ip_address,
        )
        new_connection._params = {}
        new_connection._controller = self._controller
        new_connection._shared_state = self._shared_state
        new_connection._cert_path = self._cert_path

        if yaml_node is not None:
            keep_alive = yaml_node.get(CONF_KEEP_ALIVE)
            if keep_alive is not None:
                new_connection._keep_alive = keep_alive

            connection_template = yaml_node.get(CONFIG_DEVICE_CONNECTION_TEMPLATE)
            if connection_template is not None:
                new_connection._connection_template = Template(
                    connection_template,
                    cast(HomeAssistant, self._hass),
                )
            elif CONFIG_DEVICE_CONNECTION_PARAMS in yaml_node:
                node_params = yaml_node.get(CONFIG_DEVICE_CONNECTION_PARAMS)
                node_params = node_params if node_params is not None else {}
                params = {
                    **self._params,
                    **node_params,
                }
                new_connection._params.update(params)

            embedded_node = yaml_node.get(CONFIG_DEVICE_CONNECTION)
            if embedded_node is not None:
                new_connection._embedded_command = new_connection.create_updated(
                    embedded_node
                )
                condition_str = embedded_node.get(CONFIG_DEVICE_CONDITION_TEMPLATE)
                if condition_str is not None:
                    if new_connection._embedded_command is not None:
                        new_connection._embedded_command.condition_template = Template(
                            condition_str,
                            cast(HomeAssistant, self._hass),
                        )
        # pylint: enable=protected-access

        return new_connection

    @property
    def is_async_native(self) -> bool:
        """Indicates if the connection is native asynchronous (aiohttp)."""
        return True

    @property
    def is_available(self) -> bool:
        """Return True indicating if this connection is initialized and available."""
        return self._shared_state.initialized

    @property
    def is_push_supported(self) -> bool:
        """Return True indicating this connection type supports push updates."""
        return False

    @property
    def connection_template(self) -> Template | None:
        """Return the embedded connection template."""
        return self._connection_template

    @connection_template.setter
    def connection_template(self, value: Template | None) -> None:
        """Set the embedded connection template."""
        self._connection_template = value

    @property
    def params(self) -> dict[str, Any]:
        """Return the embedded connection parameters."""
        return self._params

    def _format_connector_error(self, e: aiohttp.ClientConnectorError) -> str:
        """Format a clean error message from a ClientConnectorError."""
        host = getattr(e, "host", "?")
        port = getattr(e, "port", "?")
        reason = (
            str(e.os_error) if e.os_error is not None else type(e).__name__
        )  # pragma: no mutate
        return f"Cannot connect to {host}:{port} ({reason})"

    async def _try_connection(self) -> str | None:
        """
        Probes the connection (HTTPS mTLS ONLY)
        and memorizes it for future use.
        Returns response text if successful, None otherwise.
        """
        # Use Lock for safe, one-time initialization
        if self._shared_state.initialized:
            return None

        if self._shared_state.lock is None:
            self._shared_state.lock = asyncio.Lock()

        async with self._shared_state.lock:
            # Double-check in case another task initialized it while we were waiting for the lock.
            if self._shared_state.initialized:
                return None

            current_token, _ = self._auth_context
            probe_headers = {AUTHORIZATION: AUTH_BEARER_PREFIX.format(current_token)}

            # Use the shared state's SSL context, skip for plain HTTP test mode
            if not self._config.get(CONF_USE_HTTP, False):
                if self._shared_state.ssl_context is None:
                    self._shared_state.ssl_context = await self._create_ssl_context()

            try:
                debug_msg = "%s [aiohttp_probe] Probing connection..."
                _LOGGER.debug(debug_msg, self.log_prefix)

                # Generalize Probe URL
                url_path = self._probe_url_path

                if url_path is not None and url_path.startswith("http"):
                    debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"
                    _LOGGER.debug(debug_msg, self.log_prefix, url_path)

                probe_url = self._build_full_url(url_path)

                # CRITICAL FIX: Do NOT access self._session directly — it may be None
                # when keep_alive=False. Always go through _get_session() which handles
                # both a HA-shared session and a locally-created one.
                test_ssl_ctx: ssl.SSLContext | bool = (
                    False
                    if probe_url.startswith("http://")
                    else (self._shared_state.ssl_context or True)
                )
                probe_session = await self._get_session()
                async with probe_session.request(
                    DEFAULT_HTTP_METHOD,
                    probe_url,
                    headers=probe_headers,
                    ssl=test_ssl_ctx,
                    timeout=aiohttp.ClientTimeout(
                        total=GLOBAL_HTTP_TIMEOUT, sock_read=GLOBAL_HTTP_TIMEOUT // 2
                    ),
                ) as response:
                    if response.status in (
                        HTTPStatus.OK,
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.FORBIDDEN,
                        HTTPStatus.NOT_FOUND,
                        HTTPStatus.METHOD_NOT_ALLOWED,
                    ):  # Added 404 and 405 for Not Found / Method Not Allowed
                        # Attempt to log the negotiated TLS version
                        transport = (
                            response.connection.transport
                            if response.connection is not None
                            else None
                        )
                        ssl_obj = (
                            transport.get_extra_info("ssl_object")
                            if transport is not None
                            else None
                        )
                        negotiated_tls = "Unknown"
                        if ssl_obj is not None and not asyncio.iscoroutine(ssl_obj):
                            try:
                                negotiated_tls = ssl_obj.version()
                            except AttributeError:
                                pass
                        info_msg = "%s [aiohttp] Connection successful. Status: %s. Negotiated TLS: %s"
                        _LOGGER.info(
                            info_msg,
                            self.log_prefix,
                            response.status,
                            negotiated_tls,
                        )

                        self._shared_state.initialized = True

                        # Optimization - Return text for reuse in initial poll
                        if response.status == HTTPStatus.OK:
                            debug_msg = "%s [aiohttp_probe] Reading response body..."
                            _LOGGER.debug(debug_msg, self.log_prefix)
                            return await response.text()
                        return None
                    else:
                        exc_msg = f"Unexpected probe response: {response.status}"
                        raise CannotConnect(exc_msg)

            except aiohttp.ClientConnectorError as e:
                # Log as warning (not error) because it's expected when AC is offline.
                # Build a clean, readable message from the structured attributes of the exception.
                clean_msg = self._format_connector_error(e)
                warn_msg = "%s [aiohttp_probe] Device is unreachable (offline): %s"
                _LOGGER.warning(warn_msg, self.log_prefix, clean_msg)
                self._shared_state.ssl_context = None  # Reset to try again later
                exc_msg = f"Device unreachable: {clean_msg}"
                raise CannotConnect(exc_msg) from e

            except (
                aiohttp.ClientError,
                aiohttp.http_exceptions.BadHttpMessage,
                TimeoutError,
                ValueError,
            ) as e:
                if self._is_http_protocol_violation(e):
                    _LOGGER.warning(
                        "%s [aiohttp_probe] Device HTTP protocol/header violation detected: %s. "
                        "Switching to 'Robust (raw socket)' engine.",
                        self.log_prefix,
                        e,
                    )
                    raise InvalidHeaderError(
                        f"Protocol violation during probe: {e}"
                    ) from e
                warn_msg = (
                    "%s [aiohttp_probe] Initial probe with HTTPS (mTLS) failed: %s."
                )
                _LOGGER.warning(warn_msg, self.log_prefix, e, exc_info=True)
                self._shared_state.ssl_context = (
                    None  # Clear on failure to allow retries
                )
                err_msg = "%s [aiohttp_probe] HTTPS (mTLS) connection probe failed: %s"
                _LOGGER.error(err_msg, self.log_prefix, e)
                raise CannotConnect(
                    f"Connection initialization failed (HTTPS): {e}"
                ) from e

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Returns the appropriate aiohttp session.
        If keep_alive is True, returns the shared HA session.
        If keep_alive is False (or shared session is None), returns a dedicated local session.
        """
        # 1. Shared session logic (Keep-Alive)
        if self._keep_alive:
            if self._session is not None:
                return cast(aiohttp.ClientSession, self._session)
            # If we reach here, keep_alive is True but there is no session.
            warn_msg = "%s [aiohttp] keep_alive=True but shared session is None. Falling back to a temporary local session. Ensure hass and session are passed to YamlController explicitly."
            _LOGGER.warning(warn_msg, self.log_prefix)

        # 2. Local session logic
        local_session = self._shared_state.local_session

        # Evaluate condition directly without intermediate variable allocation
        if local_session is None or local_session.closed:
            # Retrieve the shared SSL context (should be initialized by _try_connection)
            ssl_context = self._shared_state.ssl_context

            # For plain HTTP test mode, use a simple connector with no SSL
            if self._config.get(CONF_USE_HTTP):
                connector = aiohttp.TCPConnector(
                    keepalive_timeout=KEEPALIVE_TIMEOUT, limit=1
                )
            else:
                connector = aiohttp.TCPConnector(
                    keepalive_timeout=KEEPALIVE_TIMEOUT,
                    ssl=ssl_context if ssl_context is not None else True,
                    limit=1,  # pragma: no mutate
                )

            timeout = aiohttp.ClientTimeout(
                total=NETWORK_POLL_TIMEOUT, connect=GLOBAL_HTTP_TIMEOUT
            )  # pragma: no mutate
            local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            self._shared_state.local_session = local_session

            debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."
            _LOGGER.debug(debug_msg, self.log_prefix, id(local_session), id(connector))

        return local_session

    def _build_full_url(self, url_path: str | None) -> str:
        """Constructs the full URL, handling absolute URLs and standard relative paths."""
        if url_path is not None and url_path.startswith("http"):
            full_url = url_path
            if self._config.get(CONF_USE_HTTP, False) and full_url.startswith(
                "https://"
            ):
                full_url = full_url.replace(
                    "https://", "http://", 1
                )  # pragma: no mutate
        else:
            host, _ = self._resolved_target
            port = self._config.get(CONF_PORT, DEFAULT_PORT)
            protocol = "http" if self._config.get(CONF_USE_HTTP, False) else "https"
            path = url_path if url_path is not None else ""
            full_url = f"{protocol}://{host}:{port}{path}"

        return self._format_url(full_url)

    def _format_url(self, url: str) -> str:
        """Replaces placeholders and mutates URL scheme/port safely."""
        host, mac = self._resolved_target
        token, dev_id = self._auth_context

        # 1. Resolve placeholders first
        url = format_placeholders(url, token, host, dev_id, mac)

        # 2. Parse URL safely
        parsed_url = yarl.URL(url)

        # 3. Mutate port if it matches default and config specifies otherwise
        if parsed_url.port == DEFAULT_PORT:
            parsed_url = parsed_url.with_port(
                int(self._config.get(CONF_PORT, DEFAULT_PORT))
            )

        return str(parsed_url)

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
        req_headers = format_placeholders(req_headers, current_token, host, dev_id, mac)

        if current_token is None or len(current_token.strip()) == 0:
            err_msg = "%s [aiohttp] No token available! The request will fail."
            _LOGGER.error(err_msg, self.log_prefix)
            exc_msg = "Token not configured for the aiohttp engine"
            raise AuthError(exc_msg)

        if AUTHORIZATION not in req_headers:
            req_headers[AUTHORIZATION] = AUTH_BEARER_PREFIX.format(current_token)
        if CONTENT_TYPE not in req_headers:
            req_headers[CONTENT_TYPE] = HEADER_VALUE_JSON

        # Adaptive Keep-Alive Logic: If we previously detected stability issues, force Connection: close
        if self._force_close_connection:
            req_headers[CONNECTION] = HEADER_VALUE_CLOSE

        return cast(dict[str, str], req_headers)

    def _handle_http_version_fallback(self, response: aiohttp.ClientResponse) -> None:
        """Adjust Keep-Alive strategy based on the server's HTTP version."""
        if (
            response.version is not None
            and response.version.major == 1
            and response.version.minor >= 1
        ):
            if self._force_close_connection:
                debug_msg = (
                    "%s [aiohttp] Server speaks HTTP/%s.%s. Re-enabling Keep-Alive."
                )
                _LOGGER.debug(
                    debug_msg,
                    self.log_prefix,
                    response.version.major,
                    response.version.minor,
                )
            self._force_close_connection = False
        else:
            if not self._force_close_connection and response.version is not None:
                debug_msg = "%s [aiohttp] Server speaks HTTP/%s.%s. Enforcing 'Connection: close'."
                _LOGGER.debug(
                    debug_msg,
                    self.log_prefix,
                    response.version.major,
                    response.version.minor,
                )
            self._force_close_connection = True

    async def _async_execute_request(
        self,
        method: str,
        full_url: str,
        data: str | None,
        headers: dict[str, str] | None,
    ) -> tuple[str, dict[str, str] | None]:
        """
        Executes a command asynchronously using aiohttp.
        It uses the "memorized" connection logic (HTTPS only).
        """
        current_token, dev_id = self._auth_context
        host, mac = self._resolved_target

        req_headers = self._prepare_request_headers(  # pragma: no mutate
            headers, current_token, host, dev_id, mac
        )

        ssl_context: ssl.SSLContext | bool | None = self._shared_state.ssl_context

        # Detect if the path is actually an absolute URL (for SmartThings).
        if full_url.startswith("https://") and ssl_context is None:
            ssl_context = await self._create_ssl_context()

        # If the final URL is plain HTTP (e.g. test mode), don't use SSL
        if full_url.startswith("http://"):
            ssl_context = False

        try:
            # Strict Serialization with Lock: ensures that requests are executed one by one
            # to prevent multiple concurrent connections and force reuse.
            async with self.async_lock:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    debug_msg = "%s [aiohttp] Sending request -> Method: %s, URL: %s, Payload: %s, Close Mode: %s"
                    _LOGGER.debug(
                        debug_msg,
                        self.log_prefix,
                        method,
                        full_url,
                        mask_sensitive_data(data),
                        self._force_close_connection,
                    )

                session = await self._get_session()

                method = (
                    method.strip()
                    if (method is not None and method.strip() != "")
                    else DEFAULT_HTTP_METHOD
                )

                async with session.request(
                    method,
                    url=full_url,
                    headers=req_headers,
                    data=data,
                    ssl=ssl_context,  # type: ignore[arg-type]
                    timeout=aiohttp.ClientTimeout(total=GLOBAL_HTTP_TIMEOUT),
                ) as response:
                    response_text = await response.text()

                # HTTP Version Detection to adjust Keep-Alive
                self._handle_http_version_fallback(response)

                if response.status != HTTPStatus.OK:
                    if response.status in (
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.FORBIDDEN,
                    ):
                        err_msg = (
                            "%s [aiohttp] Authentication error (status %d). Token: %s"
                        )
                        _LOGGER.error(
                            err_msg,
                            self.log_prefix,
                            response.status,
                            mask_sensitive_data(current_token),
                        )
                        exc_msg = "Device returned 401 Unauthorized during active command execution."
                        raise AuthError(exc_msg)

                    err_msg = "%s [aiohttp] HTTP Error %s: %s"
                    _LOGGER.error(
                        err_msg, self.log_prefix, response.status, response_text
                    )
                    response.raise_for_status()

                return response_text, dict(response.headers)

        except (
            TimeoutError,
            aiohttp.ClientConnectorError,
            aiohttp.ClientError,
            aiohttp.http_exceptions.BadHttpMessage,
        ) as e:
            if self._is_http_protocol_violation(e):
                err_msg = (
                    "%s [aiohttp] Device HTTP protocol/header violation detected: %s. "
                    "Switching to 'Robust (raw socket)' engine."
                )
                _LOGGER.warning(err_msg, self.log_prefix, e)
                raise InvalidHeaderError(
                    f"HTTP header/protocol error on aiohttp: {e}"
                ) from e

            # Adaptive recovery on timeout/connection drop
            if isinstance(e, aiohttp.ClientConnectorError):
                clean_e = self._format_connector_error(e)
            else:
                clean_e = str(e)

            # If we timed out and haven't forced close yet, it's highly likely the "missing Content-Length" issue.
            if not self._force_close_connection:
                warn_msg = "%s [aiohttp] Timeout/Error detected (%s). The device likely violates HTTP protocol (missing Content-Length). Switching to 'Connection: close' mode for resilience."
                _LOGGER.warning(warn_msg, self.log_prefix, clean_e)

                # CRITICAL FIX: Persist the state so we don't repeat this penalty
                self._force_close_connection = True
                req_headers[CONNECTION] = HEADER_VALUE_CLOSE

                # Retry immediately with the new header
                debug_msg = "%s [aiohttp] Retrying request with 'Connection: close'..."
                _LOGGER.debug(debug_msg, self.log_prefix)
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
                        self._handle_http_version_fallback(response)
                        return response_text, dict(response.headers)
                except (
                    aiohttp.ClientError,
                    aiohttp.http_exceptions.BadHttpMessage,
                    TimeoutError,
                    OSError,
                ) as retry_exc:
                    if self._is_http_protocol_violation(retry_exc):
                        err_msg = (
                            "%s [aiohttp] Device HTTP protocol/header violation during retry: %s. "
                            "Switching to 'Robust (raw socket)' engine."
                        )
                        _LOGGER.warning(
                            err_msg, self.log_prefix, retry_exc
                        )  # pragma: no mutate
                        raise InvalidHeaderError(
                            f"HTTP header/protocol error during retry on aiohttp: {retry_exc}"
                        ) from retry_exc

                    err_msg = (
                        "%s [aiohttp] Retry failed even with 'Connection: close': %s"
                    )
                    _LOGGER.error(err_msg, self.log_prefix, retry_exc)
                    error_msg = f"Target device returned an unexpected error response during retry: {retry_exc}"
                    raise CannotConnect(error_msg) from retry_exc

            # If we were already forcing close, then it's a real network issue.
            err_msg = "%s [aiohttp] Connection failed: %s"
            _LOGGER.error(err_msg, self.log_prefix, clean_e)
            exc_msg = f"Connection error: {clean_e}"
            raise CannotConnect(exc_msg) from e
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            err_msg = "%s [aiohttp] Unexpected data parsing error: %s"
            _LOGGER.debug(err_msg, self.log_prefix, e, exc_info=True)
            raise CannotConnect(f"Unexpected data parsing error: {e}") from e

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

        debug_msg = "%s [async_execute] Found embedded command."
        _LOGGER.debug(debug_msg, self.log_prefix)
        try:
            if device_state is None:
                warn_msg = "%s [async_execute] Embedded command found, but cannot check its condition (device_state is missing). Skipping."
                _LOGGER.warning(warn_msg, self.log_prefix)
            else:
                embedded_cond_result = self._embedded_command.check_execute_condition(
                    device_state
                )
                if not embedded_cond_result:
                    debug_msg = "%s [async_execute] Embedded command condition not met. Skipping execution."
                    _LOGGER.debug(debug_msg, self.log_prefix)
                    return

                debug_msg = "%s [async_execute] Embedded command condition met. Executing it before the main command."
                _LOGGER.debug(debug_msg, self.log_prefix)

                embedded_template = self._embedded_command.connection_template

                if embedded_template is not None:
                    embedded_params_str = embedded_template.async_render(
                        parse_result=False
                    )
                    embedded_params = json_loads(embedded_params_str)
                elif len(self._embedded_command.params) > 0:
                    debug_msg = "%s [async_execute] Embedded command has no connection_template, using _params directly."
                    _LOGGER.debug(debug_msg, self.log_prefix)
                    embedded_params = self._embedded_command.params.copy()
                else:
                    warn_msg = "%s [async_execute] Embedded command found but it has no connection_template or params."
                    _LOGGER.warning(warn_msg, self.log_prefix)
                    embedded_params = None

                if embedded_params is not None:
                    # CRITICAL FIX: Replace placeholders early for robust logging and execution
                    embedded_params = format_placeholders(
                        embedded_params, token, host, dev_id, mac
                    )

                    json_payload = embedded_params.get(_KEY_JSON)
                    embedded_data = (
                        json_dumps(json_payload) if json_payload is not None else None
                    )
                    embedded_url = embedded_params.get(_KEY_URL, url)
                    embedded_method = embedded_params.get(_KEY_METHOD, method)

                    if _LOGGER.isEnabledFor(logging.DEBUG):
                        debug_msg = "%s [async_execute] Executing embedded command with params: %s"
                        _LOGGER.debug(
                            debug_msg,
                            self.log_prefix,
                            mask_sensitive_data(embedded_params),
                        )

                    await self._embedded_command.async_execute(
                        method=embedded_method,
                        url=embedded_url,
                        data=embedded_data,
                        headers=embedded_params.get(
                            _KEY_HEADERS, headers
                        ),  # pragma: no mutate
                        device_state=device_state,
                    )

        except (CannotConnect, AuthError) as e:
            warn_msg = (
                "%s [async_execute] Embedded command failed due to connection error: %s"
            )
            _LOGGER.warning(warn_msg, self.log_prefix, e)
            raise
        except (
            aiohttp.ClientError,
            TimeoutError,
            OSError,
        ) as e:
            err_msg = "%s [async_execute] Embedded command failed: %s"
            _LOGGER.error(err_msg, self.log_prefix, e, exc_info=True)
            raise CannotConnect(f"Embedded command network error: {e}") from e
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            err_msg = "%s [async_execute] Embedded command payload parsing error: %s"
            _LOGGER.error(err_msg, self.log_prefix, e, exc_info=True)
            raise CannotConnect(f"Embedded command parsing error: {e}") from e

    async def async_execute(
        self,
        method: str,
        url: str | None,
        data: Any,
        headers: dict[str, str] | None,  # Main command's headers
        device_state: dict[str, Any] | None = None,  # Pass device state for conditions
        _is_probe: bool = False,
        _is_poll: bool = False,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """
        Orchestrates the execution of commands, including embedded ones.
        """
        # Resolve variables for placeholder replacement early for embedded logging
        host, mac = self._resolved_target
        token, dev_id = self._auth_context

        # Ensure initialization before any execution
        probe_response_text = await self._try_connection()
        full_url = self._build_full_url(url)

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
        if not self.check_execute_condition(device_state):
            debug_msg = "%s [async_execute] Condition not met. Skipping execution."
            _LOGGER.debug(debug_msg, self.log_prefix)
            return "{}", {}

        # Periodic Reset Logic: For local sessions not preserving keep_alive, explicitly close and reopen
        if _is_poll and not self._keep_alive:
            local_session = self._shared_state.local_session
            if local_session is not None:
                self._shared_state.local_session = None
                if not local_session.closed:
                    debug_msg = "%s [Periodic Reset] Closing local session (ID: %s) before poll."
                    _LOGGER.debug(debug_msg, self.log_prefix, id(local_session))
                    # Ensure the session close process is awaited
                    try:
                        await local_session.close()
                    except (aiohttp.ClientError, TimeoutError, OSError) as e:
                        debug_msg = (
                            "%s [Periodic Reset] Error closing local session: %s"
                        )
                        _LOGGER.debug(debug_msg, self.log_prefix, e)

        # Optimization: Reuse the probe response directly for the initial poll to eliminate duplicate requests
        if (
            probe_response_text is not None
            and method == DEFAULT_HTTP_METHOD
            and full_url == self._build_full_url(self._probe_url_path)
        ):
            debug_msg = "%s [async_execute] OPTIMIZATION: Reusing probe response for initial poll."
            _LOGGER.debug(debug_msg, self.log_prefix)
            return probe_response_text, None

        return await self._async_execute_request(method, full_url, data, headers)

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
        debug_msg = "%s [aiohttp] Closing connection resources..."
        _LOGGER.debug(debug_msg, self.log_prefix)

        # 1. Close internal embedded command (if any)
        if self._embedded_command is not None:
            await self._embedded_command.close()

        # 2. Close the local session and reset shared state under lock
        try:
            if self._shared_state.lock is None:
                self._shared_state.lock = asyncio.Lock()
            async with self._shared_state.lock:
                local_session = self._shared_state.local_session
                if local_session is not None:
                    debug_msg = "%s [aiohttp] Closing local session (ID: %s)..."
                    _LOGGER.debug(debug_msg, self.log_prefix, id(local_session))
                    try:
                        if not local_session.closed:
                            await local_session.close()
                    except (aiohttp.ClientError, TimeoutError, OSError) as e:
                        err_msg = "%s [aiohttp] Error closing local session: %s"
                        _LOGGER.error(err_msg, self.log_prefix, e)
                    finally:
                        self._shared_state.local_session = None

                self._shared_state.initialized = False
                self._shared_state.ssl_context = None
                self._shared_state.force_close_connection = False
        except RuntimeError as e:  # pragma: no mutate
            err_msg = (
                "%s [aiohttp] Error locking/resetting shared state during close: %s"
            )
            _LOGGER.error(err_msg, self.log_prefix, e)
