"""Raw socket connection engine for Samsung devices on port 8888."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template
from homeassistant.util.json import json_loads

if TYPE_CHECKING:
    from .controller import ClimateController

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant

from .connection import Connection, register_connection
from .const import (
    CONF_CERT,
    CONF_KEEP_ALIVE,
    CONFIG_DEVICE_CONDITION_TEMPLATE,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
)
from .exceptions import AuthError, CannotConnect
from .helpers import format_placeholders
from .protocol_8888 import Samsung8888Client

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_RAW_8888 = "samsung_8888_raw"  # pragma: no mutate

DEFAULT_SCHEME_PORTS = {"https": 443, "http": 80}
HEADER_AUTH = "Authorization"
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_VALUE_JSON = "application/json"


@register_connection
class ConnectionRaw8888(Connection):
    """Wrapper for the robust raw socket API with auto-negotiation."""

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Return True if this connection handles the given type string."""
        return type_str == CONNECTION_TYPE_RAW_8888

    def load_from_yaml(
        self, node: dict[str, Any] | None, _connection_base: Any
    ) -> bool:
        """Load configuration from yaml node dictionary."""
        if not node:
            return False

        if CONF_KEEP_ALIVE in node:
            self._keep_alive = node[CONF_KEEP_ALIVE]
        self._params.update(node.get("params", {}))
        return True

    def create_updated(self, yaml_node: dict[str, Any] | None) -> ConnectionRaw8888:
        """Create a new connection instance with updated parameters from YAML."""
        new_conn = ConnectionRaw8888(
            config=self._config,  # pragma: no mutate
            logger=self.logger,  # pragma: no mutate
            hass=self._hass,  # pragma: no mutate
            session=None,  # pragma: no mutate
            ip_address=self._host,  # pragma: no mutate
        )
        if self._controller:  # pragma: no mutate
            new_conn.set_controller_ref(self._controller)  # pragma: no mutate
        new_conn._params = self._params.copy()

        if not yaml_node:
            return new_conn

        if CONF_KEEP_ALIVE in yaml_node:
            new_conn._keep_alive = yaml_node[CONF_KEEP_ALIVE]

        template_str = yaml_node.get(CONFIG_DEVICE_CONNECTION_TEMPLATE)
        if template_str:
            new_conn._connection_template = Template(template_str, self._hass)

        params_node = yaml_node.get(CONFIG_DEVICE_CONNECTION_PARAMS)
        if params_node:
            new_conn._params.update(params_node)

        embedded_node = yaml_node.get(CONFIG_DEVICE_CONNECTION)
        if embedded_node:
            new_conn._embedded_command = new_conn.create_updated(embedded_node)
            condition_str = embedded_node.get(CONFIG_DEVICE_CONDITION_TEMPLATE)
            if condition_str and new_conn._embedded_command:
                new_conn._embedded_command.condition_template = Template(
                    condition_str, self._hass
                )

        return new_conn

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the raw connection."""
        return {
            "is_connected": getattr(self, "_is_connected", False),
            "engine": CONNECTION_TYPE_RAW_8888,
            "keep_alive_enabled": getattr(self, "_keep_alive", False),
            "has_embedded_command": self._embedded_command is not None,
            "has_shared_client": (
                getattr(self._controller, "shared_raw_client", None) is not None
                if self._controller
                else False
            ),
        }

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: dict[str, Any],
        logger: logging.Logger,
        hass: HomeAssistant,
        session: Any | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Initialize the connection."""
        super().__init__(config, logger)
        self._hass = hass

        self._host: str = ip_address or cast(str, config.get(CONF_IP_ADDRESS, ""))
        self._cert: str | None = self._resolve_cert_path(config.get(CONF_CERT))
        self._controller: ClimateController | None = None
        self._client: Samsung8888Client | None = None
        self._internal_shared_client: Samsung8888Client | None = None
        self._params: dict[str, Any] = {}
        self._connection_template: Template | None = None
        self.condition_template: Template | None = None
        self._embedded_command: ConnectionRaw8888 | None = None
        self._keep_alive = config.get(CONF_KEEP_ALIVE, True)

        self._is_connected: bool = False

    @staticmethod
    def _resolve_cert_path(cert_file: Any) -> str | None:
        """Resolve absolute certificate path securely without boolean mutation traps."""
        if not cert_file:
            return None
        cert_path = Path(str(cert_file))
        if not cert_path.is_absolute() and cert_path.name == str(cert_file):
            return str(Path(__file__).parent / str(cert_file))
        return str(cert_file)

    def set_controller_ref(self, controller: ClimateController) -> None:
        """Set reference to the main controller and propagate downwards."""
        self._controller = controller
        if self._embedded_command:
            self._embedded_command.set_controller_ref(controller)

    @staticmethod
    def _extract_port(url: str | Any) -> int:
        """Extract port from URL or fallback to defaults."""
        if not isinstance(url, str):
            return 8888  # pragma: no mutate
        parsed = urlparse(url)
        if parsed.port:
            return parsed.port
        return DEFAULT_SCHEME_PORTS.get(parsed.scheme, 8888)  # pragma: no mutate

    async def async_get_client(self) -> Samsung8888Client:
        """Get the raw client, initializing it if necessary (shared or standalone)."""
        if not self._host:
            raise CannotConnect(
                "Host/IP address not provided for RAW connection"
            )  # pragma: no mutate

        if self._controller:
            client = getattr(self._controller, "shared_raw_client", None)
            if client is None:
                port = self._extract_port(self._params.get("url"))
                client = Samsung8888Client(
                    self._host, port, self._cert, log_prefix=self.log_prefix
                )
                if hasattr(self._controller, "shared_raw_client"):
                    self._controller.shared_raw_client = client
                else:
                    self._internal_shared_client = client
            return client

        if self._client is None:
            port = self._extract_port(self._params.get("url"))
            self._client = Samsung8888Client(
                self._host, port, self._cert, log_prefix=self.log_prefix
            )
        return self._client

    @property
    def log_prefix(self) -> str:
        """Generate a consistent log prefix."""
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        return f"[{self._host or 'NO_IP'}]"

    @property
    def is_async_native(self) -> bool:
        """Return True if connection is native async."""
        return True

    @property
    def is_available(self) -> bool:
        """Return True indicating if this connection is currently connected and available."""
        return getattr(self, "_is_connected", False)

    @property
    def is_push_supported(self) -> bool:
        """Return True indicating this connection type supports push updates."""
        return False

    @property
    def connection_template(self) -> Template | None:
        """Return the embedded connection template."""
        return self._connection_template

    @property
    def params(self) -> dict[str, Any]:
        """Return the embedded connection parameters."""
        return self._params

    def _get_token_and_ids(self) -> tuple[str | None, str, str | None, str]:
        """Resolve credentials strictly without OO-distrust."""
        host = self._host or str(self._config.get(CONF_IP_ADDRESS, ""))
        mac = str(self._config.get(CONF_MAC, ""))
        dev_id: str | None = None
        current_token: str | None = str(self._config.get(CONF_TOKEN, "")) or None

        if self._controller:
            # FAIL-FAST DOCTRINE: Direct access to formal properties.
            # If the controller lacks them, it must raise AttributeError.
            dev_id = self._controller.device_id

            # Evaluación estricta: propiedad pública primero, diccionario de fallback segundo.
            ctrl_config = getattr(self._controller, "config", None)
            if not isinstance(ctrl_config, dict):
                ctrl_config = getattr(self._controller, "_config", {}) or {}

            current_token = (
                self._controller.token
                or str(ctrl_config.get(CONF_TOKEN, ""))
                or current_token
            )

        return current_token, host, dev_id, mac

    async def _async_handle_embedded_command(
        self,
        method: str,
        url: str | None,
        headers: dict[str, str] | None,
        device_state: dict[str, Any] | None,
        auth_ctx: tuple[str | None, str, str | None, str],
    ) -> None:
        """Evaluate and execute embedded pre-flight commands if conditions are met."""
        if not self._embedded_command:
            return

        current_token, host, dev_id, mac = auth_ctx

        if (
            device_state is not None
            and not self._embedded_command.check_execute_condition(device_state)
        ):
            return

        embedded_template = self._embedded_command.connection_template
        raw_params = self._embedded_command.params
        embedded_params = dict(raw_params) if raw_params else {}

        if embedded_template:
            embedded_params_str = embedded_template.async_render(parse_result=False)
            embedded_params = json_loads(str(embedded_params_str))
        elif not embedded_params:
            return

        embedded_params = format_placeholders(
            embedded_params, current_token, host, dev_id, mac
        )
        json_payload = embedded_params.get("json")
        embedded_data = json_dumps(json_payload) if json_payload is not None else None

        embedded_url = embedded_params.get("url", url)
        embedded_method = embedded_params.get("method", method)

        await self._embedded_command.async_execute(
            method=embedded_method,
            url=embedded_url,
            data=embedded_data,
            headers=embedded_params.get("headers", headers),
            device_state=device_state,
        )

    def _get_active_clients(self) -> list[Any]:
        """Yield all active raw socket clients associated with this connection."""
        clients = []
        if self._client:
            clients.append(self._client)
        if self._controller and getattr(self._controller, "shared_raw_client", None):
            clients.append(self._controller.shared_raw_client)
        elif getattr(self, "_internal_shared_client", None):
            clients.append(self._internal_shared_client)
        return clients

    async def _handle_periodic_reset(self, is_poll: bool) -> None:
        """Force close sockets on poll sweeps if keep-alive is disabled."""
        if not is_poll or self._keep_alive:
            return

        for client in self._get_active_clients():
            try:
                await client.close()
            except (TimeoutError, OSError) as e:  # pragma: no mutate
                _LOGGER.debug(
                    "%s [RAW] Ignored error during reset: %s", self.log_prefix, e
                )

        self._client = None
        self._internal_shared_client = None
        if self._controller and hasattr(self._controller, "shared_raw_client"):
            self._controller.shared_raw_client = None

    def _format_request_url(
        self,
        url: str | None,
        auth_ctx: tuple[str | None, str, str | None, str],
    ) -> str:
        """Format request URL with placeholders."""
        current_token, host, dev_id, mac = auth_ctx
        return format_placeholders(url, current_token, host, dev_id, mac)

    def _format_request_body(
        self,
        data: Any,
        auth_ctx: tuple[str | None, str, str | None, str],
    ) -> Any:
        """Format request data body into dictionary or JSON representation."""
        current_token, host, dev_id, mac = auth_ctx
        data = format_placeholders(data, current_token, host, dev_id, mac)
        return data if isinstance(data, dict) else (json_loads(data) if data else None)

    def _format_request_headers(
        self,
        headers: dict[str, str] | None,
        auth_ctx: tuple[str | None, str, str | None, str],
    ) -> dict[str, str]:
        """Format request headers and inject authentication credentials."""
        current_token, host, dev_id, mac = auth_ctx
        req_headers = headers.copy() if headers else {}
        req_headers = format_placeholders(req_headers, current_token, host, dev_id, mac)

        if not current_token:
            raise AuthError(
                "Token not configured for the raw engine"
            )  # pragma: no mutate

        req_headers.setdefault(
            HEADER_AUTH, f"Bearer {current_token}"
        )  # pragma: no mutate
        req_headers.setdefault(
            HEADER_CONTENT_TYPE, HEADER_VALUE_JSON
        )  # pragma: no mutate

        return req_headers

    def _prepare_request_payload(
        self,
        url: str | None,
        data: Any,
        headers: dict[str, str] | None,
        auth_ctx: tuple[str | None, str, str | None, str],
    ) -> tuple[str, str, Any, dict[str, str]]:
        """Assemble fully materialized network vectors."""
        formatted_url = self._format_request_url(url, auth_ctx)
        path = str(urlparse(formatted_url).path) if formatted_url else ""
        body = self._format_request_body(data, auth_ctx)
        req_headers = self._format_request_headers(headers, auth_ctx)

        return formatted_url, path, body, req_headers

    async def async_execute(
        self,
        method: str,
        url: str | None,
        data: Any,
        headers: dict[str, str] | None,
        device_state: dict[str, Any] | None = None,
        _is_probe: bool = False,  # pragma: no mutate
        _is_poll: bool = False,  # pragma: no mutate
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Orchestrates the execution of commands, including embedded ones."""
        auth_ctx = self._get_token_and_ids()

        try:
            await self._async_handle_embedded_command(
                method, url, headers, device_state, auth_ctx
            )
        except (CannotConnect, AuthError):
            raise  # pragma: no mutate
        except Exception as e:
            raise CannotConnect(
                f"Embedded command failed: {e}"
            ) from e  # pragma: no mutate

        await self._handle_periodic_reset(_is_poll)

        # Delegate the actual raw socket dispatch
        return await self._async_execute_request(
            method, url, data, headers, auth_ctx, _is_probe
        )

    async def _async_execute_request(
        self,
        method: str,
        url: str | None,
        data: Any,
        headers: dict[str, str] | None,
        auth_ctx: tuple[str | None, str, str | None, str],
        _is_probe: bool,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Dispatches the raw socket request."""
        debug_enabled = _LOGGER.isEnabledFor(logging.DEBUG)
        start_time = time.perf_counter() if debug_enabled else 0.0

        url, path, body, req_headers = self._prepare_request_payload(
            url, data, headers, auth_ctx
        )

        client = await self.async_get_client()
        try:
            async with self.async_lock:
                resp, err = await client.request(method, path, body, req_headers)

            if err:
                raise CannotConnect(f"API Error: {err}")  # pragma: no mutate

            if debug_enabled:
                elapsed = time.perf_counter() - start_time  # pragma: no mutate
                _LOGGER.debug(
                    "%s [RAW] Request completed in %.3f seconds",
                    self.log_prefix,
                    elapsed,
                )  # pragma: no mutate

            return resp, None

        except CannotConnect:
            if _is_probe:
                return None, None
            raise
        except AuthError as exc:
            raise AuthError("Invalid token") from exc  # pragma: no mutate
        except (
            ConnectionResetError,
            BrokenPipeError,
            TimeoutError,
            OSError,
        ) as e:
            raise CannotConnect(f"Socket error: {e}") from e  # pragma: no mutate

    async def close(self) -> None:
        """Close the connection and release resources safely."""
        if self._embedded_command:
            try:
                await self._embedded_command.close()
            except (TimeoutError, OSError) as e:  # pragma: no mutate
                _LOGGER.debug(
                    "%s [RAW] Ignored error closing embedded command: %s",
                    self.log_prefix,
                    e,
                )

        for client in self._get_active_clients():
            try:
                await client.close()
            except (TimeoutError, OSError) as e:  # pragma: no mutate
                _LOGGER.debug(
                    "%s [RAW] Ignored error during cleanup: %s", self.log_prefix, e
                )

        self._client = None
        self._internal_shared_client = None
        if self._controller and hasattr(self._controller, "shared_raw_client"):
            self._controller.shared_raw_client = None
