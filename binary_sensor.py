"""Platform that offers diagnostic connectivity binary sensors for Climate IP devices."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClimateIPConfigEntry
from .const import DOMAIN
from .coordinator import SamsungClimateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ClimateIPConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connectivity binary sensor entities from a config entry."""
    coordinator_data = entry.runtime_data

    coordinators: list[SamsungClimateCoordinator] = (
        list(coordinator_data.values())
        if isinstance(coordinator_data, dict)
        else ([coordinator_data] if coordinator_data else [])
    )

    entities_to_add: list[ClimateIPConnectivitySensor] = []

    for coordinator in coordinators:
        description = BinarySensorEntityDescription(
            key="connectivity",
            translation_key="connectivity",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        entities_to_add.append(ClimateIPConnectivitySensor(coordinator, description))

    if entities_to_add:
        _LOGGER.info(
            "%s Adding diagnostic connectivity binary sensors to Home Assistant.",
            coordinators[0].log_prefix,
        )
        async_add_entities(entities_to_add)


class ClimateIPConnectivitySensor(
    CoordinatorEntity[SamsungClimateCoordinator], BinarySensorEntity
):
    """Representation of a Climate IP connectivity diagnostic binary sensor."""

    entity_description: BinarySensorEntityDescription

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SamsungClimateCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the connectivity binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        unique_prefix = getattr(coordinator, "unique_id", None) or DOMAIN
        self._attr_unique_id = f"{unique_prefix}_{description.key}"

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the coordinator for consistency."""
        return self.coordinator.log_prefix

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for the device registry."""
        return self.coordinator.device_info

    @property
    def available(self) -> bool:
        """Return True so the connectivity sensor remains readable when offline."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True if the last network update was successful."""
        return bool(self.coordinator.last_update_success)
