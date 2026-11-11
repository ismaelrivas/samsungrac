"""Base entity for the Samsung Climate IP integration."""

import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SamsungClimateCoordinator

_LOGGER = logging.getLogger(__name__)


class SamsungClimateEntity(CoordinatorEntity[SamsungClimateCoordinator]):
    """Defines a base Samsung Climate IP entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SamsungClimateCoordinator) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the coordinator for consistency."""
        return self.coordinator.log_prefix

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for the device registry."""
        return self.coordinator.device_info
