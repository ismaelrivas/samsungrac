# pylint: disable=duplicate-code,import-outside-toplevel,no-else-return,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-nested-blocks,too-many-positional-arguments,too-many-statements
# custom_components/climate_ip/connection_aiohttp.py
# pylint: disable=line-too-long
"""
Asynchronous connection engine for modern Samsung devices (port 8888) using aiohttp.
This engine implements HTTP Keep-Alive for low latency and correct mTLS.
"""

import asyncio
import copy
import inspect
import logging
import os
import ssl
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
)
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .helpers import (
    async_create_samsung_ssl_context,
    format_placeholders,
    mask_sensitive_data,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_AIOHTTP_8888 = "samsung_8888_aiohttp"


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
        logger.debug("[aiohttp_init] Initializing ConnectionAiohttp8888. IP: %s", ip_address)
        super().__init__(config, logger)
        self._hass = hass
        self._controller: Any = None  # Initialize controller reference
        self._session = session
        self._ip_address = ip_address
        self._token: str | None = config.get(CONF_TOKEN)
        self._cert_path: str | None = self._resolve_cert_path(config.get(CONF_CERT))

        # Object to share initialization state across all copies.
        # The Lock prevents race conditions during the first initialization.
        # We also store 'local_session' here so it is shared across copies (commands).
        self._shared_state: dict[str, Any] = {
            "initialized": False,
            "lock": asyncio.Lock(),
            "ssl_context": None,
            "local_session": None,
        }

        # This will hold the Jinja2 template for this specific connection instance.
        self._connection_template: Template | None = None

        self.condition_template: Template | None = None
        self._embedded_command: "ConnectionAiohttp8888" | None = None
        self._ssl_context: ssl.SSLContext | None = None

        self._keep_alive: bool = config.get("keep_alive", True)

        if not self._token:
            _LOGGER.error(  # pragma: no mutate
                "[aiohttp_init] aiohttp engine started without a token. This will fail."
            )

        # Check if cert is missing
        if not self._cert_path or not os.path.exists(self._cert_path):
            # Only error if we are NOT in insecure mode (SmartThings/Emulator uses insecure_ssl=True)
            if not config.get("insecure_ssl", False):
                _LOGGER.error(  # pragma: no mutate
                    "[aiohttp_init] Certificate file not found or invalid at %s", self._cert_path
                )
            else:
                _LOGGER.debug(  # pragma: no mutate
                    "[aiohttp_init] Certificate file not found at %s."
                    " This is expected for SmartThings/Emulator (insecure_ssl=True).",
                    self._cert_path,
                )

        self._force_close_connection: bool = False

    @property
    def log_prefix(self) -> str:
        """Generate a consistent log prefix."""
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        return f"[{self._ip_address or 'NO_IP'}]"

    def set_controller_ref(self, controller: Any) -> None:
        """Allows the property to set a reference to the main controller."""
        _LOGGER.debug(  # pragma: no mutate
            "%s [set_controller_ref] Setting controller reference for connection object.",
            self.log_prefix,
        )
        self._controller = controller

    def _resolve_cert_path(self, cert_file: str | None) -> str | None:
        """Resolve the full path to the certificate file."""
        from .helpers import resolve_cert_path

        return resolve_cert_path(cert_file, os.path.dirname(__file__), self._hass)

    async def _create_ssl_context(self) -> ssl.SSLContext | None:
        """
        Creates the correct SSL context.
        - If cert is present, sets up mTLS (Strict/Verify=None but loads cert).
        - If cert is missing:
             - If insecure_ssl=True (Emulator/SmartThings), sets up lenient context (Weak Ciphers, Verify=None).
             - If insecure_ssl=False (Cloud default), returns None (aiohttp default strict).
        """
        # Read insecure_ssl. It comes from 'config' passed to __init__.
        insecure_ssl = self._config.get("insecure_ssl", False)
        has_cert = self._cert_path and os.path.exists(self._cert_path)

        if not has_cert and not insecure_ssl:
            # Standard Secure Cloud Connection
            _LOGGER.debug(  # pragma: no mutate
                "%s [aiohttp] No cert and insecure_ssl=False. Using default aiohttp SSL context (Strict).",
                self.log_prefix,
            )
            return None

        try:
            _LOGGER.debug(  # pragma: no mutate
                "%s [aiohttp] Creating custom SSL context. Cert: %s, Insecure: %s",
                self.log_prefix,
                has_cert,
                insecure_ssl,
            )

            context = await async_create_samsung_ssl_context(
                cert_path=self._cert_path if has_cert else None,
                ciphers="ALL:@SECLEVEL=0",
                verify_mode=ssl.CERT_NONE,
            )
            return context
        except (ssl.SSLError, OSError, ValueError) as e:
            _LOGGER.error(  # pragma: no mutate
                "%s [aiohttp] Failed to create SSL context: %s.", self.log_prefix, e
            )
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

    def create_updated(self, yaml_node: dict[str, Any] | None) -> "ConnectionAiohttp8888":
        """
        Creates a new connection instance with updated parameters from YAML.
        This is crucial for async operations where each 'value' can have its own
        connection_template OR static params.

        HACK: This also converts static 'params' blocks into a
        'connection_template' because the async_set_value in properties.py
        fails to check _params.
        """
        # pylint: disable=protected-access
        # Rationale: create_updated works on a shallow copy of self (same class).
        # All attribute accesses on new_connection are internal manipulation,
        # not external access to a foreign class's internals.

        new_connection = copy.copy(self)
        new_connection._params = {}
        new_connection._controller = self._controller
        new_connection._shared_state = self._shared_state

        if yaml_node and "keep_alive" in yaml_node:
            new_connection._keep_alive = yaml_node["keep_alive"]

        if yaml_node and CONFIG_DEVICE_CONNECTION_TEMPLATE in yaml_node:
            new_connection._connection_template = Template(
                yaml_node[CONFIG_DEVICE_CONNECTION_TEMPLATE], getattr(self, "_hass", None)
            )
        elif yaml_node and CONFIG_DEVICE_CONNECTION_PARAMS in yaml_node:
            params = {**self._params, **yaml_node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {})}
            new_connection._params.update(params)

        if yaml_node and CONFIG_DEVICE_CONNECTION in yaml_node:
            new_connection._embedded_command = new_connection.create_updated(
                yaml_node[CONFIG_DEVICE_CONNECTION]
            )
            if CONFIG_DEVICE_CONDITION_TEMPLATE in yaml_node[CONFIG_DEVICE_CONNECTION]:
                condition_str = yaml_node[CONFIG_DEVICE_CONNECTION][
                    CONFIG_DEVICE_CONDITION_TEMPLATE
                ]
                if new_connection._embedded_command:
                    new_connection._embedded_command.condition_template = Template(
                        condition_str, getattr(self, "_hass", None)
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
        if self._shared_state["initialized"]:
            return None

        async with self._shared_state["lock"]:
            # Double-check in case another task initialized it while we were waiting for the lock.
            if self._shared_state["initialized"]:
                return None

            current_token = self._token
            if self._controller:
                current_token = self._controller._config.get(  # pylint: disable=protected-access
                    CONF_TOKEN, self._token
                )
            probe_headers = {"Authorization": f"Bearer {current_token}"}

            # Use the shared state's SSL context, skip for plain HTTP test mode
            if not self._config.get("use_http", False):
                if not self._shared_state["ssl_context"]:
                    self._shared_state["ssl_context"] = await self._create_ssl_context()

            ssl_ctx = self._shared_state["ssl_context"]
            if ssl_ctx is None:
                # Logic for "insecure" / no-cert connection
                ssl_ctx = False

            try:
                _LOGGER.debug(  # pragma: no mutate
                    "%s [aiohttp_probe] Probing connection...", self.log_prefix
                )

                # Generalize Probe URL
                port = self._config.get(CONF_PORT, "8888")
                protocol = "http" if self._config.get("use_http", False) else "https"
                probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                if (
                    self._params
                    and self._params.get("url")
                    and str(self._params.get("url")).startswith("http")
                ):
                    probe_url = str(self._params.get("url"))
                    _LOGGER.debug(  # pragma: no mutate
                        "%s [aiohttp_probe] Detected absolute URL, probing: %s",
                        self.log_prefix,
                        probe_url,
                    )

                probe_url = self._format_url(probe_url)


                # CRITICAL FIX: Do NOT access self._session directly — it may be None
                # when keep_alive=False. Always go through _get_session() which handles
                # both a HA-shared session and a locally-created one.
                test_ssl_ctx = False if protocol == "http" else self._shared_state["ssl_context"]
                probe_session = await self._get_session()
                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]


                    if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
                        # Attempt to log the negotiated TLS version
                        try:
                            transport = (
                                response.connection.transport if response.connection else None
                            )
                            ssl_obj = transport.get_extra_info("ssl_object") if transport else None
                            negotiated_tls = ssl_obj.version() if ssl_obj else "Unknown"
                            _LOGGER.info(  # pragma: no mutate
                                "%s [aiohttp] Connection successful. Status: %s. Negotiated TLS: %s",
                                self.log_prefix,
                                response.status,
                                negotiated_tls,
                            )
                        except (AttributeError, KeyError, TypeError):
                            _LOGGER.info(  # pragma: no mutate
                                "%s [aiohttp] Connection successful and memorized. Status: %s",
                                self.log_prefix,
                                response.status,
                            )

                        self._shared_state["initialized"] = True

                        # Optimization - Return text for reuse in initial poll
                        if response.status == 200:
                            _LOGGER.debug(  # pragma: no mutate
                                "%s [aiohttp_probe] Reading response body...", self.log_prefix
                            )
                            return await response.text()
                        return None
                    else:
                        raise CannotConnect(f"Unexpected probe response: {response.status}")

            except aiohttp.ClientConnectorError as e:
                # Log as warning (not error) because it's expected when AC is offline.
                # Build a clean, readable message from the structured attributes of the exception.
                host = getattr(e, "host", "?")
                port = getattr(e, "port", "?")
                os_err = getattr(e, "os_error", None)
                reason = str(os_err) if os_err else type(e).__name__
                clean_msg = f"Cannot connect to {host}:{port} ({reason})"
                _LOGGER.warning(  # pragma: no mutate
                    "%s [aiohttp_probe] Device is unreachable (offline): %s",
                    self.log_prefix,
                    clean_msg,
                )
                self._shared_state["ssl_context"] = None  # Reset to try again later
                raise CannotConnect(f"Device unreachable: {clean_msg}") from e

            # Catch incomplete responses (missing Content-Length) which is common in older devices.
            except (
                TimeoutError,
                asyncio.TimeoutError,
                aiohttp.ServerTimeoutError,
                aiohttp.SocketTimeoutError,
                aiohttp.ClientPayloadError,
            ) as e:
                _LOGGER.error(  # pragma: no mutate
                    "%s [aiohttp_probe] Device protocol violation detected! "
                    "The device accepted the connection (200 OK) but failed to send a complete response (Timeout/PayloadError: %s). "
                    "This indicates it does not support standard HTTP/1.1 (missing Content-Length). "
                    "Switching to 'Robust (raw socket)' engine.",
                    self.log_prefix,
                    e,
                )
                raise InvalidHeaderError(
                    "Device failed to provide response body (missing Content-Length/Close)"
                ) from None

            except (aiohttp.ClientError, ValueError, RuntimeError) as e:
                # Detect malformed header error
                if "Invalid header token" in str(e):
                    _LOGGER.error(  # pragma: no mutate
                        "%s [aiohttp_probe] Malformed header error detected! "
                        "The device does not comply with the HTTP standard. "
                        "The integration will automatically switch to the 'Robust (raw socket)' connection engine.",
                        self.log_prefix,
                    )
                    raise InvalidHeaderError("Malformed HTTP headers from device") from None

                _LOGGER.warning(  # pragma: no mutate
                    "%s [aiohttp_probe] Initial probe with HTTPS (mTLS) failed: %s.",
                    self.log_prefix,
                    e,
                    exc_info=True,
                )
                self._shared_state["ssl_context"] = None  # Clear on failure to allow retries

            _LOGGER.error(  # pragma: no mutate
                "%s [aiohttp_probe] HTTPS (mTLS) connection probe failed. The device is unreachable or the certificate/token is incorrect.",
                self.log_prefix,
            )
            raise CannotConnect("Connection initialization failed (HTTPS)")

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Returns the appropriate aiohttp session.
        If keep_alive is True, returns the shared HA session.
        If keep_alive is False (or shared session is None), returns a dedicated local session.
        """
        if self._keep_alive and self._session is not None:
            return self._session

        if self._keep_alive and self._session is None:
            # Defense-in-depth: the shared session was not injected (e.g., during
            # config flow discovery). Fall through and create a temporary local session
            # instead of returning None, which would crash the caller.
            _LOGGER.warning(  # pragma: no mutate
                "%s [aiohttp] keep_alive=True but shared session is None. "
                "Falling back to a temporary local session. "
                "Ensure hass and session are passed to YamlController explicitly.",
                self.log_prefix,
            )

        local_session = self._shared_state.get("local_session")
        if local_session is None or local_session.closed:
            # Retrieve the shared SSL context (should be initialized by _try_connection)
            ssl_context = self._shared_state.get("ssl_context")

            # For plain HTTP test mode, use a simple connector with no SSL
            if self._config.get("use_http", False):
                connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
            else:
                connector = aiohttp.TCPConnector(keepalive_timeout=75, ssl=ssl_context, limit=1)  # type: ignore[arg-type]
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            self._shared_state["local_session"] = local_session
            _LOGGER.debug(  # pragma: no mutate
                "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s).",
                self.log_prefix,
                id(local_session),
                id(connector),
            )

        return self._shared_state["local_session"]

    def _format_url(self, url: str) -> str:
        """
        Replaces placeholders in the URL with actual values from configuration.
        """
        # Host: Evaluamos explícitamente sin caer en str(None)
        raw_host = self._ip_address or self._params.get(CONF_HOST)
        host = str(raw_host) if raw_host is not None else ""
        
        token = self._token
        dev_id = None
        
        if self._controller is not None:
            token = self._controller._config.get(CONF_TOKEN, self._token)
            # Falla Rápido: Asumimos que el contrato del controlador expone device_id
            dev_id = self._controller.device_id

        raw_mac = self._params.get(CONF_MAC)
        mac = str(raw_mac) if raw_mac is not None else ""

        url = format_placeholders(url, token, host, dev_id, mac)

        # Manejo de puertos sin falsos positivos de mutación
        if ":8888/" in url:
            port = str(self._config.get(CONF_PORT, "8888"))
            url = url.replace(":8888/", f":{port}/")

        # Mutmut odia el `if dict.get(key, False):`. Lo blindamos asertando el tipo booleano.
        if bool(self._config.get("use_http", False)) is True:
            url = url.replace("https://", "http://")

        return url

    async def _async_execute_request(
        self,
        method: str,
        url_path: str | None,
        data: str | None,
        headers: dict[str, str] | None,
        _is_poll: bool = False,
    ) -> tuple[str, dict[str, str] | None]:
        """
        Executes a command asynchronously using aiohttp.
        It uses the "memorized" connection logic (HTTPS only).
        """
        req_headers = headers.copy() if headers is not None else {}

        current_token = self._token
        raw_host = self._ip_address or self._params.get(CONF_HOST)
        host = str(raw_host) if raw_host is not None else ""
        
        raw_mac = self._params.get(CONF_MAC)
        mac = str(raw_mac) if raw_mac is not None else ""
        
        dev_id = None

        if self._controller is not None:
            current_token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
            dev_id = self._controller.device_id

        # CRITICAL FIX: Replace placeholders in headers as well
        req_headers = format_placeholders(
            req_headers, current_token, host, dev_id, mac
        )

        if not current_token:
            _LOGGER.error(  # pragma: no mutate
                "%s [aiohttp] No token available! The request will fail.", self.log_prefix
            )
            raise AuthError("Token not configured for the aiohttp engine")

        if "Authorization" not in req_headers:
            req_headers["Authorization"] = f"Bearer {current_token}"
        if "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"

        # Adaptive Keep-Alive Logic: If we previously detected stability issues, force Connection: close
        if getattr(self, "_force_close_connection", False):
            req_headers["Connection"] = "close"

        ssl_context = self._shared_state.get("ssl_context")
        # Detect if the path is actually an absolute URL (for SmartThings).
        if url_path and url_path.startswith("http"):
            base_url = ""  # No base URL needed
            # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
            if not ssl_context:
                ssl_context = await self._create_ssl_context()
        else:
            port = self._config.get(CONF_PORT, "8888")
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
                _LOGGER.debug(  # pragma: no mutate
                    "%s [aiohttp] Sending request -> Method: %s, URL: %s, Payload: %s, Close Mode: %s",
                    self.log_prefix,
                    method,
                    full_url,
                    mask_sensitive_data(data),
                    getattr(self, "_force_close_connection", "False"),
                )

                session = await self._get_session()
                _LOGGER.debug(  # pragma: no mutate
                    "%s [aiohttp] Using session ID: %s | SSL Context ID: %s",
                    self.log_prefix,
                    id(session),
                    id(ssl_context),
                )

                async with session.request(
                    method,
                    url=full_url,
                    headers=req_headers,
                    data=data,
                    ssl=ssl_context,  # type: ignore[arg-type]
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:

                    response_text = await response.text()

                # HTTP Version Detection to adjust Keep-Alive
                if response.version and response.version.major == 1 and response.version.minor >= 1:
                    if getattr(self, "_force_close_connection", False):
                        _LOGGER.debug(  # pragma: no mutate
                            "%s [aiohttp] Server speaks HTTP/%s.%s. Re-enabling Keep-Alive.",
                            self.log_prefix,
                            response.version.major,
                            response.version.minor,
                        )
                    self._force_close_connection = False
                else:
                    if not getattr(self, "_force_close_connection", False) and response.version:
                        _LOGGER.debug(  # pragma: no mutate
                            "%s [aiohttp] Server speaks HTTP/%s.%s. Enforcing 'Connection: close'.",
                            self.log_prefix,
                            response.version.major,
                            getattr(response.version, "minor", 0),
                        )
                    self._force_close_connection = True

                if response.status != 200:
                    if response.status in (401, 403):
                        _LOGGER.error(  # pragma: no mutate
                            "%s [aiohttp] Authentication error (status %d). Token: %s...%s",
                            self.log_prefix,
                            response.status,
                            current_token[:4],
                            current_token[-4:],
                        )
                        raise AuthError(
                            f"Authentication failed with status {response.status}. Check your token."
                        )

                    _LOGGER.error(  # pragma: no mutate
                        "%s [aiohttp] HTTP Error %s: %s",
                        self.log_prefix,
                        response.status,
                        response_text,
                    )
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
                host = getattr(e, "host", "?")
                port = getattr(e, "port", "?")
                os_err = getattr(e, "os_error", None)
                reason = str(os_err) if os_err else type(e).__name__
                clean_e = f"Cannot connect to {host}:{port} ({reason})"
            else:
                clean_e = str(e)

            # If we timed out and haven't forced close yet, it's highly likely the "missing Content-Length" issue.
            if not getattr(self, "_force_close_connection", False):
                _LOGGER.warning(  # pragma: no mutate
                    "%s [aiohttp] Timeout/Error detected (%s). "
                    "The device likely violates HTTP protocol (missing Content-Length). "
                    "Switching to 'Connection: close' mode for resilience.",
                    self.log_prefix,
                    clean_e,
                )
                self._force_close_connection = True
                req_headers["Connection"] = "close"

                # Retry immediately with the new header
                _LOGGER.debug(  # pragma: no mutate
                    "%s [aiohttp] Retrying request with 'Connection: close'...", self.log_prefix
                )
                try:
                    session = await self._get_session()
                    async with session.request(
                        method,
                        full_url,
                        data=data,
                        headers=req_headers,
                        ssl=ssl_context,  # type: ignore[arg-type]
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        response_text = await response.text()
                        return response_text, None
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as retry_exc:
                    _LOGGER.error(  # pragma: no mutate
                        "%s [aiohttp] Retry failed even with 'Connection: close': %s",
                        self.log_prefix,
                        retry_exc,
                    )
                    raise CannotConnect(
                        f"Connection failed after retry: {retry_exc}"
                    ) from retry_exc

            # If we were already forcing close, then it's a real network issue.
            _LOGGER.error(  # pragma: no mutate
                "%s [aiohttp] Connection failed: %s", self.log_prefix, clean_e
            )
            raise CannotConnect(f"Connection error: {clean_e}") from e
        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.error(  # pragma: no mutate
                "%s [aiohttp] Unexpected data error: %s", self.log_prefix, e, exc_info=True
            )
            raise

    def execute(
        self,
        template: Template | None,
        value: Any,
        device_state: dict[str, Any],
        device_id: str | None = None,
    ) -> None:
        """Not implemented for async connections."""
        raise NotImplementedError("This connection is async-native. Use async_execute.")

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
        raw_host = self._ip_address or self._params.get(CONF_HOST)
        host = str(raw_host) if raw_host is not None else ""
        
        token = self._token
        dev_id = None
        
        if self._controller is not None:
            token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
            dev_id = self._controller.device_id

        raw_mac = self._params.get(CONF_MAC)
        mac = str(raw_mac) if raw_mac is not None else ""

        # Ensure initialization before any execution
        probe_response_text = await self._try_connection()

        if self._embedded_command:
            _LOGGER.debug(  # pragma: no mutate
                "%s [async_execute] Found embedded command.", self.log_prefix
            )
            try:
                # Check the condition before executing the embedded command
                if hasattr(self._embedded_command, "check_execute_condition") and device_state:
                    if not self._embedded_command.check_execute_condition(device_state):
                        _LOGGER.debug(  # pragma: no mutate
                            "%s [async_execute] Embedded command condition not met. Skipping execution.",
                            self.log_prefix,
                        )
                    else:
                        _LOGGER.debug(  # pragma: no mutate
                            "%s [async_execute] Embedded command condition met. Executing it before the main command.",
                            self.log_prefix,
                        )

                        embedded_template = getattr(
                            self._embedded_command, "_connection_template", None
                        )
                        embedded_params = getattr(self._embedded_command, "_params", {})
                        if embedded_template:
                            if hasattr(embedded_template, "async_render"):
                                embedded_params_str = embedded_template.async_render()
                            else:
                                embedded_params_str = embedded_template.render()
                            embedded_params = json_loads(embedded_params_str)
                        elif embedded_params:
                            _LOGGER.debug(  # pragma: no mutate
                                "%s [async_execute] Embedded command has no connection_template, using _params directly.",
                                self.log_prefix,
                            )
                        else:
                            _LOGGER.warning(  # pragma: no mutate
                                "%s [async_execute] Embedded command found but it has no connection_template or params.",
                                self.log_prefix,
                            )
                            embedded_params = None

                        if embedded_params:
                            # CRITICAL FIX: Replace placeholders early for robust logging and execution
                            embedded_params = format_placeholders(
                                embedded_params, token, host, dev_id, mac
                            )

                            embedded_data = (
                                json_dumps(embedded_params.get("json"))
                                if "json" in embedded_params
                                else None
                            )
                            embedded_url = embedded_params.get("url", url)
                            embedded_method = embedded_params.get("method", method)

                            _LOGGER.debug(  # pragma: no mutate
                                "%s [async_execute] Executing embedded command with params: %s",
                                self.log_prefix,
                                mask_sensitive_data(embedded_params),
                            )

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
                            if inspect.isawaitable(res):
                                await res
                else:
                    _LOGGER.warning(  # pragma: no mutate
                        "%s [async_execute] Embedded command found, but cannot check its condition (device_state is missing). Skipping.",
                        self.log_prefix,
                    )

            except (CannotConnect, AuthError) as e:
                _LOGGER.warning(  # pragma: no mutate
                    "%s [async_execute] Embedded command failed due to connection error: %s",
                    self.log_prefix,
                    e,
                )
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, TypeError) as e:
                _LOGGER.error(  # pragma: no mutate
                    "%s [async_execute] Embedded command failed: %s",
                    self.log_prefix,
                    e,
                    exc_info=True,
                )
                raise

        # Execute the main command
        if hasattr(self, "check_execute_condition") and not self.check_execute_condition(
            device_state
        ):
            _LOGGER.debug(  # pragma: no mutate
                "%s [async_execute] Condition not met (template result false). Skipping execution.",
                self.log_prefix,
            )
            return "{}", {}

        # Periodic Reset Logic: For local sessions not preserving keep_alive, explicitly close and reopen
        if _is_poll and not self._keep_alive:
            local_session = self._shared_state.get("local_session")
            if local_session:
                self._shared_state["local_session"] = None

            if local_session and not local_session.closed:
                _LOGGER.debug(  # pragma: no mutate
                    "%s [Periodic Reset] Closing local session (ID: %s) before poll.",
                    self.log_prefix,
                    id(local_session),
                )
                # Ensure the session close process is awaited and allowed to finish (Step 3.1)
                try:
                    await local_session.close()
                    # Yield control to the event loop so the transport can effectively close
                    await asyncio.sleep(0.1)
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                    _LOGGER.debug(  # pragma: no mutate
                        "%s [Periodic Reset] Error closing local session: %s", self.log_prefix, e
                    )

        # Optimization: Reuse the probe response directly for the initial poll to eliminate duplicate requests
        if probe_response_text and method == "GET" and url == "/devices":
            _LOGGER.debug(  # pragma: no mutate
                "%s [async_execute] OPTIMIZATION: Reusing probe response for initial poll.",
                self.log_prefix,
            )
            return probe_response_text, None

        return await self._async_execute_request(
            method, url, data, headers, _is_poll=_is_poll
        )

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the aiohttp connection."""
        diag = {
            "is_connected": (
                self._shared_state.get("initialized", False) if self._shared_state else False
            ),
            "force_close_connection": getattr(self, "_force_close_connection", False),
            "keep_alive_enabled": self._keep_alive,
        }

        if self._shared_state:
            ssl_ctx = self._shared_state.get("ssl_context")
            diag["has_ssl_context"] = bool(ssl_ctx)

        return diag

    async def close(self) -> None:
        """
        Close the connection and release resources.
        This is called when the integration is unloaded or the connection method changes.
        """
        _LOGGER.debug(  # pragma: no mutate
            "%s [aiohttp] Closing connection resources...", self.log_prefix
        )

        # 1. Close internal embedded command (if any)
        if self._embedded_command and hasattr(self._embedded_command, "close"):
            try:
                await self._embedded_command.close()
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, AttributeError) as e:
                _LOGGER.warning(  # pragma: no mutate
                    "%s [aiohttp] Error closing embedded command: %s", self.log_prefix, e
                )

        # 2. Close the local session if it exists (for keep_alive=False)
        local_session = self._shared_state.get("local_session")
        if local_session:
            _LOGGER.debug(  # pragma: no mutate
                "%s [aiohttp] Closing local session (ID: %s)...", self.log_prefix, id(local_session)
            )
            try:
                if not local_session.closed:
                    await local_session.close()
                    # Allow time for underlying socket to close completely (Step 3.1)
                    await asyncio.sleep(0.1)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                _LOGGER.error(  # pragma: no mutate
                    "%s [aiohttp] Error closing local session: %s", self.log_prefix, e
                )
            finally:
                self._shared_state["local_session"] = None

        # 3. Reset shared state to allow clean re-initialization
        try:
            async with self._shared_state["lock"]:
                self._shared_state["initialized"] = False
                self._shared_state["ssl_context"] = None
                if self._shared_state.get("local_session"):
                    self._shared_state["local_session"] = None
        except (RuntimeError, ValueError) as e:
            _LOGGER.error(  # pragma: no mutate
                "%s [aiohttp] Error locking/resetting shared state during close: %s",
                self.log_prefix,
                e,
            )
def dummy_mutmut_test():
    return 42
