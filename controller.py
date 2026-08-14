# pylint: disable=import-outside-toplevel,too-many-public-methods,useless-return
"""Base class for a climate device controller. Strict enforcement."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol, runtime_checkable

from homeassistant.const import UnitOfTemperature

if TYPE_CHECKING:
    from .state import ClimateIPDeviceState

ATTR_POWER = "power"
CLIMATE_CONTROLLERS: list[type[ClimateController]] = []

class ControllerError(Exception):
    """Base exception for controller errors."""


class ControllerInitializationError(ControllerError):
    """Raised when controller fails to initialize."""


@runtime_checkable
class ControllerInterface(Protocol):
    """Protocol for climate controllers. Defines the mandatory contract."""

    @property
    def log_prefix(self) -> str: ...
    @property
    def unique_id(self) -> str | None: ...
    @property
    def poll(self) -> bool | None: ...
    @property
    def climate_state(self) -> ClimateIPDeviceState: ...
    @property
    def shared_raw_client(self) -> Any | None: ...
    @shared_raw_client.setter
    def shared_raw_client(self, client: Any | None) -> None: ...

    async def async_get_status(self) -> dict[str, Any] | None: ...
    async def async_set_property(
        self, property_name: str, new_value: Any, device_id: str | None = None
    ) -> bool: ...
    async def async_predict_and_correct_state(
        self, current_hass_state: ClimateIPDeviceState, property_name: str, new_value: Any
    ) -> tuple[Any, dict[str, Any]]: ...
    async def async_shutdown(self) -> None: ...
    async def async_merge_device_state(self, data: dict[str, Any]) -> bool: ...
    async def async_clear_pending_updates(self, keys: list[str]) -> None: ...
    def is_property_superseded(self, prop: str, val: Any) -> bool: ...
    def clear_state_cache(self) -> None: ...

    # Contratos de Callbacks
    def register_token_callback(
        self,
        callback: (
            Callable[[str], Coroutine[Any, Any, None]] | Callable[[str], None] | None
        ),
    ) -> None: ...
    def on_token_refreshed(self, new_token: str) -> None: ...
    def on_ssl_config_updated(self, ssl_config: dict[str, Any]) -> None: ...
    async def on_push_update_callback(self, data: dict[str, Any]) -> None: ...
    async def request_refresh_callback(self) -> None: ...
    def on_offline_callback(self, reason: str) -> None: ...
    def on_connection_failed_callback(self) -> None: ...


class ClimateController(ABC):
    """Abstract base class for a device controller. Enforcement through ABC."""

    # pylint: disable=import-outside-toplevel,too-many-public-methods,useless-return

    def __init__(self, config: dict[str, Any], logger: logging.Logger) -> None:
        """Initialize the controller."""
        self._logger = logger
        self.hass: Any | None = None
        self._connection: Any = None
        self._shared_raw_client: Any = None
        self.discovered_devices: list[dict[str, Any]] | None = None
        self._token_refreshed_callback: (
            Callable[[str], Coroutine[Any, Any, None]] | Callable[[str], None] | None
        ) = None

    @property
    def shared_raw_client(self) -> Any | None:
        """Return the shared raw socket client."""
        return self._shared_raw_client

    @shared_raw_client.setter
    def shared_raw_client(self, client: Any | None) -> None:
        """Set the shared raw socket client."""
        self._shared_raw_client = client

    @staticmethod
    @abstractmethod
    def match_type(controller_type: str) -> bool:
        """Contract: Must define if it handles a type."""

    @abstractmethod
    async def initialize(self) -> bool:
        """Abstract initialization. Must be implemented."""

    @abstractmethod
    async def async_get_status(self) -> dict[str, Any] | None:
        """Get the current status of the device."""

    @property
    def connection(self) -> Any | None:
        """Return the active connection object."""
        return self._connection

    @property
    @abstractmethod
    def is_push_device(self) -> bool:
        """Contract: Must declare if push is supported."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """Contract: Must declare availability."""

    @property
    @abstractmethod
    def poll(self) -> bool | None:
        """Return the polling state of the controller."""

    @property
    @abstractmethod
    def unique_id(self) -> str | None:
        """Return the unique id of the controller."""

    @property
    @abstractmethod
    def device_id(self) -> str | None:
        """Return the device id of the controller."""

    @property
    @abstractmethod
    def ip_address(self) -> str | None:
        """Contract: Subclasses must expose their IP address."""

    @property
    def host(self) -> str | None:
        """Return the host or IP address of the controller."""
        return self.ip_address

    @property
    def log_prefix(self) -> str:
        """Standardized log prefix."""
        uid = self.unique_id
        nm = self.name
        
        if uid is not None:
            ident = str(uid)
        elif nm is not None:
            ident = str(nm)
        else:
            ident = "NO_ID"

        base_part, _, sub_part = ident.partition("_")
        clean_mac = base_part.replace(":", "").replace("-", "")
        mac_suffix = clean_mac[-6:] if len(clean_mac) > 0 else "NO_ID"
        if len(sub_part) > 0 and sub_part not in ("main", "0", mac_suffix, clean_mac):
            return f"[{mac_suffix}:{sub_part}]"
        return f"[{mac_suffix}]"

    @property
    @abstractmethod
    def name(self) -> str | None:
        """Return the name of the controller."""

    @property
    @abstractmethod
    def debug(self) -> bool:
        """Return the debug state of the controller."""

    @abstractmethod
    async def async_set_property(
        self, property_name: str, new_value: Any, device_id: str | None = None
    ) -> bool:
        """Asynchronously set the value of a property on the device."""

    @abstractmethod
    async def async_refresh_from_connection(self) -> None:
        """Refresh the controller's properties from the connection's internal state."""

    @abstractmethod
    async def async_clear_pending_updates(self, keys: list[str]) -> None:
        """Clear pending updates (anti-flicker locks) on failure."""

    @abstractmethod
    def get_property(self, property_name: str) -> Any:
        """Return the value of a property."""

    @property
    @abstractmethod
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the device."""

    @property
    @abstractmethod
    def temperature_unit(self) -> UnitOfTemperature:
        """Return the temperature unit of the controller."""

    @property
    @abstractmethod
    def service_schema_map(self) -> dict[Any, Any] | None:
        """Return the service schema map for custom services."""

    @property
    @abstractmethod
    def operations(self) -> list[str]:
        """Return a list of available operations."""

    @property
    @abstractmethod
    def attributes(self) -> list[str]:
        """Return a list of available attributes."""

    @property
    @abstractmethod
    def climate_state(self) -> Any:
        """Return the strictly typed state representation of the device."""

    # =========================================================================
    # STRICT CONTRACT CALLBACKS (Zero Trust)
    # Define safe default no-op implementations to prevent dynamic hasattr() calls
    # =========================================================================

    def register_token_callback(
        self,
        callback: (
            Callable[[str], Coroutine[Any, Any, None]] | Callable[[str], None] | None
        ),
    ) -> None:
        """Register an explicit token refreshed callback."""
        self._token_refreshed_callback = callback

    def on_token_refreshed(self, new_token: str) -> None:
        """Invoke the registered token refreshed callback if present."""
        if not isinstance(new_token, str) or len(new_token.strip()) == 0:
            raise TypeError("new_token must be a non-empty string")
        if self._token_refreshed_callback is not None:
            self._token_refreshed_callback(new_token)

    def on_ssl_config_updated(self, ssl_config: dict[str, Any]) -> None:  # noqa: B027
        """Callback invoked when the network negotiates a new SSL configuration."""
        pass

    async def on_push_update_callback(self, data: dict[str, Any]) -> None:  # noqa: B027
        """Callback invoked when the device sends a push update."""
        pass

    async def request_refresh_callback(self) -> None:  # noqa: B027
        """Callback to trigger a state update in Home Assistant."""
        pass

    def on_offline_callback(self, reason: str) -> None:  # noqa: B027
        """Callback invoked when the device is declared offline."""
        pass

    def on_connection_failed_callback(self) -> None:  # noqa: B027
        """Callback invoked on critical connection failures."""
        pass

    def is_property_superseded(self, prop: str, val: Any) -> bool:
        """Return True if an outgoing property command has been superseded by a newer target."""
        poller = getattr(self, "poller", None)
        pending_updates = getattr(poller, "_pending_updates", None)
        if pending_updates is not None and prop in pending_updates:
            current_target = pending_updates[prop][0]
            if current_target != val:
                return True
        return False

    def clear_state_cache(self) -> None:
        """Clear internal state cache."""
        poller = getattr(self, "poller", None)
        if poller is not None and hasattr(poller, "clear_state_cache"):
            poller.clear_state_cache()


def register_controller(
    controller: type[ClimateController],
) -> type[ClimateController]:
    """A decorator to register a controller class."""
    CLIMATE_CONTROLLERS.append(controller)
    return controller


async def create_controller(
    controller_type: str, config: dict[str, Any], logger: logging.Logger
) -> ClimateController | None:
    """Factory function to create a controller instance based on its type."""
    for controller_class in CLIMATE_CONTROLLERS:
        if controller_class.match_type(controller_type):
            try:
                controller = controller_class(config, logger)
                if await controller.initialize():
                    return controller

                # Halt execution explicitly if matched but initialization fails
                logger.error(
                    "Failed to initialize controller for type %s", controller_type
                )  # pragma: no mutate
                raise ControllerInitializationError(
                    f"Initialization failed for {controller_type}"
                )

            except (ValueError, TypeError, KeyError) as e:
                logger.error(
                    "climate_ip: Configuration or data error while creating controller %s: %s",  # pragma: no mutate
                    controller_type,
                    e,
                )
                return None
            except (ConnectionError, OSError, TimeoutError) as e:
                logger.error(
                    "climate_ip: Network error while initializing controller %s: %s",  # pragma: no mutate
                    controller_type,
                    e,
                )
                return None

    logger.error(
        "Controller for type %s not found", controller_type
    )  # pragma: no mutate
    return None
