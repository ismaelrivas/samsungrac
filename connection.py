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
    """Decorate a function to register a connection type."""
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
        self._lock = asyncio.Lock()
        
        # FAIL-FAST DOCTRINE: Formalize ghost attributes
        self._controller: Any | None = None
        self.condition_template: Any | None = None

    @property
    def log_prefix(self) -> str:
        """Generate a consistent log prefix. Subclasses must override if needed."""
        return ""

    @property
    def async_lock(self) -> asyncio.Lock:
        """Return the shared asyncio.Lock for this connection's (host, port)."""
        host: str | None = self._params.get("host") or self._config.get("host")
        port: str | int = self._params.get("port") or self._config.get("port", "default")

        if not host:
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
        """Load configuration from yaml node dictionary."""
        # pylint: disable=unused-argument
        return False

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the connection for troubleshooting."""
        return {
            "type": self.__class__.__name__,
            "status": "not_implemented_in_base_class",  # pragma: no mutate
        }

    def execute(
        self, template: Any, value: Any, device_state: Any, device_id: str | None = None
    ) -> Any:
        """Execute a synchronous command."""
        raise NotImplementedError

    async def async_execute_with_retry(
        self, template: Any, value: Any, device_state: Any = None, device_id: str | None = None
    ) -> Any:
        """Asynchronously execute synchronous command with non-blocking exponential backoff."""
        import asyncio
        from .exceptions import CannotConnect, RetryNextAttempt

        MAX_SYNC_RETRIES = 5  # pragma: no mutate
        MAX_RETRY_DELAY_SEC = 15.0  # pragma: no mutate

        for attempt in range(MAX_SYNC_RETRIES):
            try:
                async with self.async_lock:
                    # STRICT ACCESS: Trust the initialized variables
                    hass = self._hass or (self._controller.hass if self._controller else None)
                    if hass:
                        return await hass.async_add_executor_job(
                            self.execute, template, value, device_state, device_id
                        )
                    return await asyncio.to_thread(
                        self.execute, template, value, device_state, device_id
                    )
            except RetryNextAttempt as e:
                if attempt < MAX_SYNC_RETRIES - 1:
                    delay = min(1.0 * (2**attempt), MAX_RETRY_DELAY_SEC)
                    self._logger.debug(
                        "%s Sync command yielded RetryNextAttempt. Async sleeping %.1fs (Attempt %s/%s)...",
                        self.log_prefix, delay, attempt + 1, MAX_SYNC_RETRIES
                    )  # pragma: no mutate
                    await asyncio.sleep(delay)
                    continue
                raise CannotConnect(f"Connection failed after {MAX_SYNC_RETRIES} retries: {e}") from e  # pragma: no mutate
            except Exception as e:
                raise CannotConnect(f"Connection failed after {MAX_SYNC_RETRIES} retries: {e}") from e  # pragma: no mutate

        raise CannotConnect("Max retries exhausted.")  # Fallback safety, should not be reached

    # pylint: disable=too-many-arguments,too-many-positional-arguments
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
        """Return True if the command should be executed for the given device state."""
        _log = self._logger or logging.getLogger(__name__)
        
        condition = self.condition_template
        if condition is None:
            return True
            
        try:
            # ZERO DISTRUST: Modern HA templates always implement async_render
            rendered = condition.async_render({"device_state": device_state})
            _log.debug(
                "%s Execute condition result: %s",
                self.log_prefix,
                rendered,
            )  # pragma: no mutate
            return str(rendered).strip() == "1"
        except Exception as e:  # pylint: disable=broad-except
            _log.error(
                "%s Error evaluating execute condition, executing command anyway. Error: %s",
                self.log_prefix,
                e,
                exc_info=True,
            )  # pragma: no mutate
            return True

    def execute_legacy(  # pylint: disable=unused-argument
        self, template: Any, value: Any, device_state: Any, device_id: str | None = None
    ) -> dict[str, Any] | None:
        """Execute connection and return JSON object as result or None if unsuccessful."""
        return None

    def create_updated(self, yaml_node: dict[str, Any] | None) -> "Connection | None":
        """Create a copy of connection object updated from a YAML configuration node."""
        # pylint: disable=unused-argument
        return self