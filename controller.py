# pylint: disable=import-outside-toplevel,too-many-public-methods,useless-return
"""Base class for a climate device controller."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from homeassistant.const import UnitOfTemperature

ATTR_POWER = "power"

CLIMATE_CONTROLLERS: list[type["ClimateController"]] = []

_T = TypeVar("_T")


@runtime_checkable
class ControllerInterface(Protocol):
    """Protocol for climate controllers."""

    @property
    def log_prefix(self) -> str:
        """Return a log prefix."""

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID."""

    @property
    def operations(self) -> list[str]:
        """Return the list of operations."""

    @property
    def attributes(self) -> list[str]:
        """Return the list of attributes."""

    @property
    def is_push_device(self) -> bool:
        """Return True if device uses push updates."""

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""

    @property
    def poll(self) -> bool | None:
        """Return the polling state."""

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit."""

    @property
    def climate_state(self) -> Any:
        """Return the strictly typed state representation."""

    def get_property(self, property_name: str) -> Any:
        """Return a property value."""

    def get_property_object(self, property_name: str) -> Any:
        """Return the property object."""

    async def async_get_status(self) -> dict[str, Any] | None:
        """Fetch the latest status."""

    async def async_set_property(
        self, property_name: str, new_value: Any, device_id: str | None = None
    ) -> bool:
        """Set a property value."""

    async def async_shutdown(self) -> None:
        """Shut down the controller."""

    async def async_merge_device_state(
        self, data: dict[str, Any], is_response: bool = False, is_update: bool = False
    ) -> bool:
        """Merge device state updates."""

    async def async_predict_and_correct_state(
        self, current_state: Any, property_name: str, new_value: Any
    ) -> tuple[Any, dict[str, Any]]:
        """Predict and correct the state after a change."""


class ClimateController(ABC, Generic[_T]):
    """Abstract base class for a device controller."""
# pylint: disable=import-outside-toplevel,too-many-public-methods,useless-return

    def __init__(self, config: dict[str, Any], logger: logging.Logger) -> None:
        """Initialize the controller."""
        _ = config  # unused in base class; subclasses use it
        self._logger = logger
        self._connection = None
        self._shared_raw_client = None
        self.discovered_devices: list[dict[str, Any]] | None = None

    @staticmethod
    def match_type(controller_type: str) -> bool:
        """Check if this controller class matches the given type string."""
        # Subclasses must override this.
        _ = controller_type
        return False

    @abstractmethod
    async def initialize(self) -> bool:
        """Perform asynchronous initialization for the controller.

        Returns:
            True if initialization was successful, False otherwise.
        """
        raise NotImplementedError()

    @abstractmethod
    async def async_get_status(self) -> dict[str, Any] | None:
        """Get the current status of the device for the DataUpdateCoordinator."""
        raise NotImplementedError()

    @property
    def connection(self) -> Any | None:
        """Return the connection object for the controller."""
        return self._connection

    @property
    def is_push_device(self) -> bool:
        """Return True if the device uses push-based updates."""
        if not self._connection:
            return False
        return self._connection.is_push_supported

    @property
    def available(self) -> bool:
        """Return True if the controller is connected and available."""
        # Subclasses should override this to reflect the actual connection state
        return True

    @property
    @abstractmethod
    def poll(self) -> bool | None:
        """Return the polling state of the controller."""
        raise NotImplementedError()

    @property
    def id(self) -> str | None:
        """Return the unique id of the controller."""
        return None

    @property
    def unique_id(self) -> str | None:
        """Return the unique id of the controller."""
        # Subclasses are expected to override this
        return None

    @property
    def device_id(self) -> str | None:
        """Return the device id of the controller."""
        # Subclasses are expected to override this
        return None

    @property
    def log_prefix(self) -> str:
        """Return a short identifier for logging purposes."""
        unique_id = self.unique_id
        if unique_id and len(unique_id) >= 6:  # Use last 6 chars for a short prefix
            return f"[{unique_id[-6:]}]"
        return f"[{self.name or 'NO_ID'}]"

    @property
    def name(self) -> str | None:
        """Return the name of the controller."""
        return None

    @property
    def debug(self) -> bool:
        """Return the debug state of the controller."""
        return False

    async def update_state(self) -> bool:
        """Asynchronously update the state of the controller from the device."""
        raise NotImplementedError()

    @abstractmethod
    async def async_set_property(self, property_name: str, new_value: Any) -> bool:
        """Asynchronously set the value of a property on the device."""
        raise NotImplementedError()

    async def async_refresh_from_connection(self) -> None:
        """Refresh the controller's properties from the connection's internal state."""

    @abstractmethod
    def get_property(self, property_name: str) -> Any:
        """Return the value of a property."""
        raise NotImplementedError()

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the device."""
        raise NotImplementedError()

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit of the controller."""
        return UnitOfTemperature.CELSIUS

    @property
    def service_schema_map(self) -> dict[Any, Any] | None:
        """Return the service schema map for custom services."""
        return None

    @property
    def operations(self) -> list[str]:
        """Return a list of available operations (settable properties)."""
        return []

    @property
    def attributes(self) -> list[str]:
        """Return a list of available attributes (read-only properties)."""
        return []

    @property
    def climate_state(self) -> Any:
        """Return the strictly typed state representation of the device."""
        raise NotImplementedError()


def register_controller(controller: type["ClimateController"]) -> type["ClimateController"]:
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
                logger.error("Failed to initialize controller for type %s", controller_type)
            except (ValueError, TypeError, KeyError) as e:
                logger.error(
                    "climate_ip: Configuration or data error while creating controller %s: %s",
                    controller_type,
                    e,
                )
            except (ConnectionError, OSError, TimeoutError) as e:
                logger.error(
                    "climate_ip: Network error while initializing controller %s: %s",
                    controller_type,
                    e,
                )

    logger.error("Controller for type %s not found", controller_type)
    return None
