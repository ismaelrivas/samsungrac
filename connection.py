"""Base connection class and registry for climate_ip connections."""

import asyncio
import logging
from abc import abstractmethod
from typing import Any

CLIMATE_IP_CONNECTIONS: list[type["Connection"]] = []

# Centralised per-host lock registry.
# Key: (host, port) tuple resolved from config/params at runtime.
# Value: a shared asyncio.Lock instance for all connections to that address.
_HOST_LOCKS: dict[tuple[str, str | int], asyncio.Lock] = {}


def register_connection(conn: type["Connection"]) -> type["Connection"]:
    """Decorate a function to register a property."""
    CLIMATE_IP_CONNECTIONS.append(conn)
    return conn


class Connection:
    """Abstract base class for all climate_ip connection types."""

    def __init__(
        self, config: dict[str, Any], logger: logging.Logger, hass: Any | None = None
    ) -> None:
        """Initialize the connection with config and logger."""
        self._params: dict[str, Any] = {}
        self._logger = logger
        self._config = config
        self._hass = hass
        # Per-instance fallback lock (used only when host cannot be resolved).
        # For same-host serialization use the async_lock property instead.
        self._lock = asyncio.Lock()

    @property
    def async_lock(self) -> asyncio.Lock:
        """Return the shared asyncio.Lock for this connection's (host, port).

        All connection instances that point to the same physical device will
        receive the SAME lock object, ensuring requests are serialised per host
        even when HA launches multiple entity updates concurrently.
        """
        # Try to resolve host and port from _params first, then _config.
        host: str | None = (
            self._params.get("host")
            or self._config.get("host")
        )
        port: str | int = (
            self._params.get("port")
            or self._config.get("port", "default")
        )

        if not host:
            # Cannot identify the host – fall back to the per-instance lock
            # so the behaviour is at worst identical to before this change.
            return self._lock

        key: tuple[str, str | int] = (str(host), str(port))
        if key not in _HOST_LOCKS:
            _HOST_LOCKS[key] = asyncio.Lock()
        return _HOST_LOCKS[key]

    @property
    def logger(self) -> logging.Logger:
        """Return the logger instance."""
        return self._logger

    @property
    def config(self) -> dict[str, Any]:
        """Return the configuration dictionary."""
        return self._config

    def load_from_yaml(self, node: dict[str, Any] | None, connection_base: Any) -> bool:
        """Load configuration from yaml node dictionary.

        Use connection base as base but DO NOT modify it.
        Return True if successful False otherwise.
        """
        # pylint: disable=import-outside-toplevel,unused-argument
        _ = node, connection_base
        return False

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the connection for troubleshooting.

        Override in subclasses to provide specific connection details.
        """
        return {"type": self.__class__.__name__, "status": "not_implemented_in_base_class"}

    def execute(
        self, template: Any, value: Any, device_state: Any, device_id: str | None = None
    ) -> Any:
        """Execute a synchronous command."""
        raise NotImplementedError

    # pylint: disable=import-outside-toplevel,too-many-arguments,too-many-positional-arguments
    async def async_execute(
        self,
        method: str,
        url: str | None,
        data: Any,
        headers: dict[str, str] | None,
        device_state: dict[str, Any] | None = None,
        _is_probe: bool = False,
        _is_poll: bool = False,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Execute an asynchronous command."""
        raise NotImplementedError

    @property
    def is_async_native(self) -> bool:
        """Indicate if the connection is native asynchronous (aiohttp)."""
        return False

    @property
    @abstractmethod
    def is_push_supported(self) -> bool:
        """Return True if this connection type supports push updates."""
        raise NotImplementedError()

    def check_execute_condition(self, device_state: dict[str, Any] | None) -> bool:
        """Return True if the command should be executed for the given device state.

        Evaluates the optional Jinja2 ``condition_template`` attribute.  The
        template must render to the string ``"1"`` for the command to run.
        Any other rendered value means skip; a missing template means always run.

        This single shared implementation replaces 4 previously duplicated copies
        in connection_request, connection_request_tls_auto, connection_aiohttp and
        connection_raw.
        """
        _log = self._logger or logging.getLogger(__name__)
        condition = getattr(self, "condition_template", None)
        if condition is None:
            return True
        try:
            if hasattr(condition, "async_render"):
                rendered = condition.async_render({"device_state": device_state})
            else:
                rendered = condition.render(device_state=device_state)
            _log.debug(
                "%s Execute condition result: %s",
                getattr(self, "log_prefix", ""),
                rendered,
            )
            return str(rendered).strip() == "1"
        except Exception as e:  # pylint: disable=import-outside-toplevel,broad-except
            _log.error(
                "%s Error evaluating execute condition, executing command anyway. Error: %s",
                getattr(self, "log_prefix", ""),
                e,
                exc_info=True,
            )
            return True

    def execute_legacy(  # pylint: disable=import-outside-toplevel,unused-argument
        self, template: Any, value: Any, device_state: Any, device_id: str | None = None
    ) -> dict[str, Any] | None:
        """Execute connection and return JSON object as result or None if unsuccessful."""
        return None

    def create_updated(self, yaml_node: dict[str, Any] | None) -> "Connection | None":
        """Create a copy of connection object updated from a YAML configuration node."""
        # pylint: disable=import-outside-toplevel,unused-argument
        _ = yaml_node
        return self
