# pylint: disable=duplicate-code,no-else-return,line-too-long,abstract-method,comparison-with-callable
"""Asynchronous connection engine for modern Samsung devices (port 8888) using aiohttp.

This engine implements HTTP Keep-Alive for low latency and correct mTLS.
"""

import asyncio
import contextlib
from dataclasses import dataclass
from http import HTTPStatus
import logging
import os
from pathlib import Path
import ssl
import sys
from typing import TYPE_CHECKING, Any, Self

import aiohttp
from aiohttp.hdrs import AUTHORIZATION, CONNECTION, CONTENT_TYPE
import yarl

from homeassistant.const import CONF_MAC, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template
from homeassistant.util.json import json_loads

from . import helpers
from .connection import Connection, register_connection
from .const import (
    CONF_CERT,
    CONF_DEVICE_ID,
    CONF_INSECURE_SSL,
    CONF_KEEP_ALIVE,
    CONF_USE_HTTP,
    CONFIG_DEVICE_CONDITION_TEMPLATE,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
    GLOBAL_HTTP_TIMEOUT,
    MAIN_DEVICE_ID,
    NETWORK_POLL_TIMEOUT,
    PORT_SAMSUNG_8888,
)
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .helpers import (
    async_create_samsung_ssl_context,
    format_placeholders,
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

CONNECTION_TYPE_AIOHTTP_8888 = "samsung_8888_aiohttp"  # pragma: no mutate

DEFAULT_PORT = 8888  # pragma: no mutate
DEFAULT_SSL_CIPHERS = "ALL:@SECLEVEL=0"  # pragma: no mutate
HEADER_VALUE_JSON = "application/json"  # pragma: no mutate
HEADER_VALUE_CLOSE = "close"  # pragma: no mutate
KEEPALIVE_TIMEOUT = 75  # pragma: no mutate

_HEADER_VIOLATION_MARKERS = ("invalid header", "header token")  # pragma: no mutate
_LOCAL_HOST_MARKERS = (
    "localhost",
    "127.0.0.1",
    "::1",
    "192.168.",
    "10.",
    "172.",
    ".local",
)  # pragma: no mutate
_MAX_EXC_CHAIN_DEPTH = 5  # pragma: no mutate

_KEY_PROBE_URL = "probe_url"  # pragma: no mutate
_KEY_URL = "url"  # pragma: no mutate
_KEY_JSON = "json"  # pragma: no mutate
_KEY_METHOD = "method"  # pragma: no mutate
_KEY_HEADERS = "headers"  # pragma: no mutate

AUTH_BEARER_PREFIX = "Bearer {}"  # pragma: no mutate
DEFAULT_HTTP_METHOD = "GET"  # pragma: no mutate


@register_connection
class ConnectionAiohttp8888(Connection):
    """Asynchronous connection handler for Samsung devices on port 8888."""

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        config: dict[str, Any],
        logger: logging.Logger,
        hass: HomeAssistant | None = None,
        session: aiohttp.ClientSession | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Initialize the aiohttp connection."""
        super().__init__(
            config, logger, hass=hass, session=session, ip_address=ip_address
        )
        self._token: str | None = config.get(CONF_TOKEN)
        self._raw_cert_path: str | None = config.get(CONF_CERT)
        self._cert_path: str | None = None
        self._shared_state = AiohttpSharedState()
        self._embedded_command: ConnectionAiohttp8888 | None = None
        self._keep_alive: bool = config.get(CONF_KEEP_ALIVE, True)

        if not self._token or not self._token.strip():
            _LOGGER.error(  # pylint: disable=hass-logger-period
                "[aiohttp_init] aiohttp engine started without a token. This will fail."
            )
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
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix  # type: ignore[no-any-return]
        return f"[{(self._ip_address or '').strip() or 'NO_IP'}]"

    @property
    def _ssl_context(self) -> ssl.SSLContext | None:
        """Return the shared SSL context."""
        return self._shared_state.ssl_context

    @property
    def _resolved_target(self) -> tuple[str, str]:
        """Strictly and centrally resolve the Host and MAC address."""
        raw_mac = self._params.get(CONF_MAC)
        return self._ip_address or "", (
            str(raw_mac) if raw_mac is not None else ""
        )  # pragma: no mutate

    @property
    def _auth_context(self) -> tuple[str | None, str | None]:
        """Centralized resolution of active token and device_id."""
        if not self._controller:
            return self._token, None
        cfg = self._controller.config
        cfg_dev_id = cfg.get(CONF_DEVICE_ID)
        dev_id = (
            cfg_dev_id
            if (cfg_dev_id and cfg_dev_id != MAIN_DEVICE_ID)
            else (self._controller.device_id or cfg_dev_id)
        )
        return cfg.get(CONF_TOKEN, self._token), dev_id

    @property
    def _probe_url_path(self) -> str:
        """Centrally resolve the probe or standard URL path from params."""
        return str(self._params.get(_KEY_PROBE_URL) or self._params.get(_KEY_URL) or "")

    def set_controller_ref(self, controller: YamlController) -> None:
        """Set a reference to the main controller."""
        self._controller = controller
        if self._embedded_command is not None:
            self._embedded_command.set_controller_ref(controller)

    def _resolve_cert_path(self, cert_file: str | None) -> str | None:
        """Resolve the full path to the certificate file."""
        return resolve_cert_path(cert_file, str(Path(__file__).parent), self._hass)

    def _resolve_and_verify_cert(self, raw_path: str | None) -> str | None:
        """Synchronously resolve and verify certificate path."""
        if not raw_path or not raw_path.strip():
            return None
        path = self._resolve_cert_path(raw_path)
        return path if path and os.path.exists(path) else None

    async def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create the SSL context for mTLS, local targets, or insecure SSL."""
        host, _ = self._resolved_target
        is_local = any(loc in host.lower() for loc in _LOCAL_HOST_MARKERS)

        if self._cert_path is None and self._raw_cert_path and self._hass:
            self._cert_path = (
                await self._hass.async_add_executor_job(
                    self._resolve_and_verify_cert, self._raw_cert_path
                )
                or ""
            )

        has_cert = bool(self._cert_path and self._cert_path.strip())
        if not (has_cert or self._config.get(CONF_INSECURE_SSL) or is_local):
            return None

        try:
            return await async_create_samsung_ssl_context(
                cert_path=self._cert_path if has_cert else None,
                ciphers=DEFAULT_SSL_CIPHERS,
                verify_mode=ssl.CERT_NONE,
            )
        except (ssl.SSLError, OSError, ValueError) as e:
            raise CannotConnect(f"SSL context creation failed: {e}") from e

    @staticmethod
    def _is_wrapped_parser_violation(exc: aiohttp.ClientResponseError) -> bool:
        """Detect HTTP parser violations wrapped by aiohttp into ClientResponseError."""
        message = exc.message if isinstance(exc.message, str) else ""
        if exc.status == HTTPStatus.BAD_REQUEST and any(
            marker in message.lower() for marker in _HEADER_VIOLATION_MARKERS
        ):
            return True

        cause: BaseException | None = exc.__cause__ or exc.__context__
        depth = 0
        while cause is not None and depth < _MAX_EXC_CHAIN_DEPTH:  # pragma: no mutate
            if isinstance(cause, aiohttp.http_exceptions.HttpProcessingError):
                return True
            cause = cause.__cause__ or cause.__context__
            depth += 1  # pragma: no mutate
        return False

    @staticmethod
    def _is_http_protocol_violation(exc: BaseException) -> bool:
        """Check if exception represents an HTTP protocol/header violation requiring fallback to RAW."""
        if isinstance(exc, aiohttp.ClientConnectorError):
            return False  # pragma: no mutate
        if isinstance(exc, aiohttp.ClientResponseError):
            return ConnectionAiohttp8888._is_wrapped_parser_violation(exc)
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

    @staticmethod
    def build_8888_ssl_context(cert_path: str) -> ssl.SSLContext:
        """Build SSL context for Samsung 8888 devices in executor thread."""
        cf_helpers = sys.modules.get("custom_components.climate_ip.config_flow_helpers")
        ssl_mod = getattr(cf_helpers, "ssl", ssl)
        ssl_context: ssl.SSLContext = ssl_mod.create_default_context()

        if cert_path:
            resolved_cert = helpers.resolve_cert_path(
                cert_path, os.path.dirname(__file__)
            )
            if resolved_cert and os.path.exists(resolved_cert):
                with contextlib.suppress(Exception):
                    ssl_context.load_verify_locations(cafile=resolved_cert)
        else:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    @classmethod
    async def async_test_8888_connection(
        cls,
        hass: HomeAssistant,
        ip_address: str,
        token: str,
        cert_path: str,
    ) -> bool:
        """Probe Samsung 8888 HTTPS endpoint during config flow validation."""
        session = aiohttp_client.async_get_clientsession(hass)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        ssl_context = await hass.async_add_executor_job(
            cls.build_8888_ssl_context, cert_path
        )
        async with session.get(
            f"https://{ip_address}:{PORT_SAMSUNG_8888}/devices",
            headers=headers,
            ssl=ssl_context,
            timeout=GLOBAL_HTTP_TIMEOUT,  # type: ignore[arg-type] # pragma: no mutate
        ) as resp:
            return resp.status == 200

    @classmethod
    async def async_validate_rest_device(
        cls,
        hass: HomeAssistant,
        ip_address: str,
        token: str | None,
        *,
        fetch_device_id: bool = False,
    ) -> str | None:
        """Validate REST API connectivity and optionally extract the first SmartThings deviceId."""
        ip_addr = ip_address.strip()
        host_str = (
            f"[{ip_addr}]"
            if ip_addr.count(":") > 1 and not ip_addr.startswith("[")
            else ip_addr
        )
        req_kwargs: dict[str, Any] = {
            "headers": {"Authorization": f"Bearer {token}"},  # pragma: no mutate
            "timeout": GLOBAL_HTTP_TIMEOUT,  # pragma: no mutate
        }
        if any(loc in host_str.lower() for loc in _LOCAL_HOST_MARKERS):
            req_kwargs["ssl"] = False

        try:
            session = aiohttp_client.async_get_clientsession(hass)
            async with session.get(
                f"https://{host_str}/v1/devices", **req_kwargs
            ) as response:  # pragma: no mutate
                if response.status != HTTPStatus.OK:
                    raise CannotConnect("HTTP Status Error")

                if fetch_device_id:
                    with contextlib.suppress(
                        ValueError, TypeError, KeyError, aiohttp.ClientPayloadError
                    ):
                        resp_json = await response.json()
                        items = resp_json.get("items", [])  # pragma: no mutate
                        if items and isinstance(items, list) and "deviceId" in items[0]:
                            return str(items[0]["deviceId"])
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CannotConnect(f"REST API connection error: {err}") from err

        return None

    def load_from_yaml(
        self, node: dict[str, Any] | None, connection_base: Connection | None = None
    ) -> bool:
        """Load configuration from yaml node dictionary."""
        if connection_base is not None and hasattr(connection_base, "_params"):
            self._params.update(connection_base._params)  # noqa: SLF001

        if node is not None:
            if (keep_alive := node.get(CONF_KEEP_ALIVE)) is not None:
                self._keep_alive = keep_alive
            if isinstance(
                node_params := node.get(CONFIG_DEVICE_CONNECTION_PARAMS), dict
            ):
                self._params.update(node_params)
        return True

    def create_updated(self, yaml_node: dict[str, Any] | None) -> Self:
        """Create a new connection instance with updated parameters from YAML."""
        # pylint: disable=protected-access
        new_conn = ConnectionAiohttp8888(  # pragma: no mutate
            config=self._config,
            logger=self._logger,
            hass=self._hass,
            session=self._session,
            ip_address=self._ip_address,
        )
        new_conn._controller = self._controller
        new_conn._shared_state = self._shared_state
        new_conn._cert_path = self._cert_path
        new_conn.load_from_yaml(yaml_node, self)

        if yaml_node is not None:
            if (
                conn_tmpl := yaml_node.get(CONFIG_DEVICE_CONNECTION_TEMPLATE)
            ) is not None:
                new_conn._connection_template = Template(
                    conn_tmpl,
                    self._hass,  # type: ignore[arg-type]
                )

            if (embedded_node := yaml_node.get(CONFIG_DEVICE_CONNECTION)) is not None:
                new_conn._embedded_command = new_conn.create_updated(embedded_node)
                if (
                    cond_str := embedded_node.get(CONFIG_DEVICE_CONDITION_TEMPLATE)
                ) is not None:
                    new_conn._embedded_command.condition_template = Template(
                        cond_str,
                        self._hass,  # type: ignore[arg-type]
                    )
        # pylint: enable=protected-access

        return new_conn  # type: ignore[return-value]

    @property
    def is_async_native(self) -> bool:
        """Indicate if the connection is native asynchronous (aiohttp)."""
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
        """Probe the connection (HTTPS mTLS ONLY) and memorize it for future use."""
        if self._shared_state.initialized:
            return None

        if self._shared_state.lock is None:
            self._shared_state.lock = asyncio.Lock()

        async with self._shared_state.lock:
            if self._shared_state.initialized:
                return None  # type: ignore[unreachable]

            current_token, _ = self._auth_context
            probe_headers = {AUTHORIZATION: AUTH_BEARER_PREFIX.format(current_token)}

            if (
                not self._config.get(CONF_USE_HTTP)
                and self._shared_state.ssl_context is None
            ):
                self._shared_state.ssl_context = await self._create_ssl_context()

            try:
                probe_url = self._build_full_url(self._probe_url_path)
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
                    if response.status not in (
                        HTTPStatus.OK,
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.FORBIDDEN,
                        HTTPStatus.NOT_FOUND,
                        HTTPStatus.METHOD_NOT_ALLOWED,
                    ):
                        raise CannotConnect(
                            f"Unexpected probe response: {response.status}"
                        )

                    transport = getattr(response.connection, "transport", None)
                    ssl_obj = (
                        transport.get_extra_info("ssl_object") if transport else None
                    )
                    negotiated_tls = (
                        getattr(ssl_obj, "version", lambda: "Unknown")()
                        if not asyncio.iscoroutine(ssl_obj)
                        else "Unknown"
                    )
                    _LOGGER.info(
                        "%s [aiohttp] Connection successful. Status: %s. Negotiated TLS: %s",
                        self.log_prefix,
                        response.status,
                        negotiated_tls,
                    )

                    self._shared_state.initialized = True
                    return (
                        await response.text()
                        if response.status == HTTPStatus.OK
                        else None
                    )

            except aiohttp.ClientConnectorError as e:
                self._shared_state.ssl_context = None
                raise CannotConnect(
                    f"Device unreachable: {self._format_connector_error(e)}"
                ) from e

            except (
                aiohttp.ClientError,
                aiohttp.http_exceptions.BadHttpMessage,
                TimeoutError,
                ValueError,
            ) as e:
                if self._is_http_protocol_violation(e):
                    raise InvalidHeaderError(
                        f"Protocol violation during probe: {e}"
                    ) from e
                _LOGGER.warning(  # pylint: disable=hass-logger-period
                    "%s [aiohttp_probe] Initial probe with HTTPS (mTLS) failed: %s.",
                    self.log_prefix,
                    e,
                    exc_info=True,
                )
                self._shared_state.ssl_context = None
                raise CannotConnect(
                    f"Connection initialization failed (HTTPS): {e}"
                ) from e

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared HA session (if keep_alive) or a dedicated local session."""
        if self._keep_alive and self._session is not None:
            return self._session  # type: ignore[no-any-return]

        local_session = self._shared_state.local_session
        if local_session is None or local_session.closed:
            ssl_context = self._shared_state.ssl_context
            conn_kwargs: dict[str, Any] = {
                "keepalive_timeout": KEEPALIVE_TIMEOUT,
                "limit": 1,  # pragma: no mutate
            }
            if not self._config.get(CONF_USE_HTTP):
                conn_kwargs["ssl"] = ssl_context if ssl_context is not None else True
            connector = aiohttp.TCPConnector(**conn_kwargs)
            timeout = aiohttp.ClientTimeout(
                total=NETWORK_POLL_TIMEOUT, connect=GLOBAL_HTTP_TIMEOUT
            )  # pragma: no mutate
            local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            self._shared_state.local_session = local_session

        return local_session

    def _build_full_url(self, url_path: str | None) -> str:
        """Construct the full URL, handling absolute URLs and standard relative paths."""
        use_http = bool(self._config.get(CONF_USE_HTTP))
        if url_path and url_path.startswith("http"):
            full_url = (
                url_path.replace("https://", "http://", 1)  # pragma: no mutate
                if use_http and url_path.startswith("https://")
                else url_path
            )
        else:
            host, _ = self._resolved_target
            protocol = "http" if use_http else "https"
            path = url_path or ""
            has_port = ":" in host and not host.endswith("]")
            full_url = (
                f"{protocol}://{host}{path}"
                if has_port
                else f"{protocol}://{host}:{DEFAULT_PORT}{path}"
            )

        return self._format_url(full_url)

    def _format_url(self, url: str) -> str:
        """Replace placeholders and mutate URL scheme/port safely."""
        host, mac = self._resolved_target
        token, dev_id = self._auth_context
        parsed_url = yarl.URL(format_placeholders(url, token, host, dev_id, mac))

        if ":" not in host and parsed_url.port == DEFAULT_PORT:
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
        if not current_token or not current_token.strip():
            raise AuthError("Token not configured for the aiohttp engine")

        req_headers: dict[str, str] = format_placeholders(
            headers.copy() if headers else {}, current_token, host, dev_id, mac
        )
        req_headers.setdefault(AUTHORIZATION, AUTH_BEARER_PREFIX.format(current_token))
        req_headers.setdefault(CONTENT_TYPE, HEADER_VALUE_JSON)
        if self._force_close_connection:
            req_headers[CONNECTION] = HEADER_VALUE_CLOSE

        return req_headers

    def _handle_http_version_fallback(self, response: aiohttp.ClientResponse) -> None:
        """Adjust Keep-Alive strategy based on the server's HTTP version."""
        ver = response.version
        self._force_close_connection = not (
            ver is not None and ver.major == 1 and ver.minor >= 1
        )

    async def _async_execute_request(
        self,
        method: str,
        full_url: str,
        data: str | None,
        headers: dict[str, str] | None,
    ) -> tuple[str, dict[str, str] | None]:
        """Execute a command asynchronously using aiohttp."""
        current_token, dev_id = self._auth_context
        host, mac = self._resolved_target

        req_headers = self._prepare_request_headers(  # pragma: no mutate
            headers, current_token, host, dev_id, mac
        )

        ssl_context: ssl.SSLContext | bool | None = self._shared_state.ssl_context
        if full_url.startswith("https://") and ssl_context is None:
            ssl_context = await self._create_ssl_context()
        elif full_url.startswith("http://"):
            ssl_context = False

        try:
            async with self.async_lock:
                session = await self._get_session()
                method = (method or "").strip() or DEFAULT_HTTP_METHOD

                async with session.request(
                    method,
                    url=full_url,
                    headers=req_headers,
                    data=data,
                    ssl=ssl_context,  # type: ignore[arg-type]
                    timeout=aiohttp.ClientTimeout(total=GLOBAL_HTTP_TIMEOUT),
                ) as response:
                    response_text = await response.text()

                self._handle_http_version_fallback(response)

                if response.status != HTTPStatus.OK:
                    if response.status in (
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.FORBIDDEN,
                    ):
                        raise AuthError(
                            "Device returned 401 Unauthorized during active command execution."
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
                raise InvalidHeaderError(
                    f"HTTP header/protocol error on aiohttp: {e}"
                ) from e

            if not self._force_close_connection:
                self._force_close_connection = True
                req_headers[CONNECTION] = HEADER_VALUE_CLOSE
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
                        raise InvalidHeaderError(
                            f"HTTP header/protocol error during retry on aiohttp: {retry_exc}"
                        ) from retry_exc
                    raise CannotConnect(
                        f"Target device returned an unexpected error response during retry: {retry_exc}"
                    ) from retry_exc

            clean_e = (
                self._format_connector_error(e)
                if isinstance(e, aiohttp.ClientConnectorError)
                else str(e)
            )
            raise CannotConnect(f"Connection error: {clean_e}") from e
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            raise CannotConnect(f"Unexpected data parsing error: {e}") from e

    async def _execute_embedded_command(
        self,
        device_state: dict[str, Any] | None,
        url: str | None,
        method: str,
        headers: dict[str, str] | None,
    ) -> None:
        """Evaluate and execute an embedded command if conditions are met."""
        if self._embedded_command is None:
            return

        if device_state is None:
            _LOGGER.warning(  # pylint: disable=hass-logger-period
                "%s [async_execute] Embedded command found, but cannot check its condition (device_state is missing). Skipping.",
                self.log_prefix,
            )
            return

        try:
            if not self._embedded_command.check_execute_condition(device_state):
                return

            embedded_template = self._embedded_command.connection_template
            if embedded_template is not None:
                embedded_params = json_loads(
                    embedded_template.async_render(parse_result=False)
                )
            elif self._embedded_command.params:
                embedded_params = self._embedded_command.params.copy()
            else:
                return

            if embedded_params:
                host, mac = self._resolved_target
                token, dev_id = self._auth_context
                embedded_params = format_placeholders(
                    embedded_params, token, host, dev_id, mac
                )
                json_payload = embedded_params.get(_KEY_JSON)
                await self._embedded_command.async_execute(
                    method=embedded_params.get(_KEY_METHOD, method),
                    url=embedded_params.get(_KEY_URL, url),
                    data=json_dumps(json_payload) if json_payload is not None else None,
                    headers=embedded_params.get(
                        _KEY_HEADERS, headers
                    ),  # pragma: no mutate
                    device_state=device_state,
                )
        except (CannotConnect, AuthError) as e:
            _LOGGER.warning(
                "%s [async_execute] Embedded command failed due to connection error: %s",
                self.log_prefix,
                e,
            )
            raise
        except (aiohttp.ClientError, TimeoutError, OSError) as e:
            raise CannotConnect(f"Embedded command network error: {e}") from e
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            raise CannotConnect(f"Embedded command parsing error: {e}") from e

    async def async_execute(
        self,
        method: str,
        url: str | None,
        data: Any,
        headers: dict[str, str] | None,
        device_state: dict[str, Any] | None = None,
        _is_probe: bool = False,  # pragma: no mutate
        _is_poll: bool = False,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Orchestrate the execution of commands, including embedded ones."""
        probe_response_text = await self._try_connection()
        full_url = self._build_full_url(url)

        await self._execute_embedded_command(device_state, url, method, headers)

        if not self.check_execute_condition(device_state):
            return "{}", {}

        if _is_poll and not self._keep_alive:
            local_session = self._shared_state.local_session
            if local_session is not None:
                self._shared_state.local_session = None
                if not local_session.closed:
                    with contextlib.suppress(
                        aiohttp.ClientError, TimeoutError, OSError
                    ):
                        await local_session.close()

        if (
            probe_response_text is not None
            and method == DEFAULT_HTTP_METHOD
            and full_url == self._build_full_url(self._probe_url_path)
        ):
            return probe_response_text, None

        return await self._async_execute_request(method, full_url, data, headers)

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the aiohttp connection."""
        return {
            "is_connected": self._shared_state.initialized,
            "force_close_connection": self._force_close_connection,
            "keep_alive_enabled": self._keep_alive,
            "has_ssl_context": self._shared_state.ssl_context is not None,
        }

    async def close(self) -> None:
        """Close the connection and release resources."""
        if self._embedded_command is not None:
            await self._embedded_command.close()

        try:
            if self._shared_state.lock is None:
                self._shared_state.lock = asyncio.Lock()
            async with self._shared_state.lock:
                local_session = self._shared_state.local_session
                if local_session is not None:
                    try:
                        if not local_session.closed:
                            await local_session.close()
                    except (aiohttp.ClientError, TimeoutError, OSError) as e:
                        _LOGGER.error(
                            "%s [aiohttp] Error closing local session: %s",
                            self.log_prefix,
                            e,
                        )
                    finally:
                        self._shared_state.local_session = None

                self._shared_state.initialized = False
                self._shared_state.ssl_context = None
                self._shared_state.force_close_connection = False
        except RuntimeError as e:  # pragma: no mutate
            _LOGGER.error(
                "%s [aiohttp] Error locking/resetting shared state during close: %s",
                self.log_prefix,
                e,
            )
