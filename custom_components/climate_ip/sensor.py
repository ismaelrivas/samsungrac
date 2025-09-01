"""
Platform that offers support for IP controlled climate device sensors.
This file defines the Home Assistant sensor entities, adapted for DataUpdateCoordinator.
"""
import logging
from typing import Any, Dict

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .coordinator import SamsungClimateCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="AC_OUTDOOR_TEMP",
        name="Outdoor Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="AC_ADD2_USEDPOWER",
        name="Energy Consumed",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement="kWh", # Assuming the unit is kWh
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="AC_ADD2_USEDTIME",
        name="Usage Time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor entities from a config entry."""
    coordinators = hass.data[DOMAIN][entry.entry_id]
    
    # If we have a dictionary of coordinators, we only need one for the outdoor unit sensors.
    # We can just pick the first one.
    if isinstance(coordinators, dict):
        if not coordinators:
            _LOGGER.warning("No coordinators found for sensor setup.")
            return
        coordinator = next(iter(coordinators.values()))
    else:
        coordinator = coordinators

    entities_to_add = []
    for description in SENSOR_TYPES:
        # Check if the device state has this sensor key
        if coordinator.data and description.key in coordinator.data:
            entities_to_add.append(ClimateIpSensor(coordinator, description))

    if entities_to_add:
        _LOGGER.info("%s Adding %d sensors to Home Assistant.", coordinator.log_prefix, len(entities_to_add))
        async_add_entities(entities_to_add)


class ClimateIpSensor(CoordinatorEntity[SamsungClimateCoordinator], SensorEntity):
    """Representation of a Climate IP sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SamsungClimateCoordinator,
        description: SensorEntityDescription,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"
        
        # Set initial state from coordinator data
        self._update_state()

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the coordinator for consistency."""
        return self.coordinator.log_prefix

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for the device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.unique_id)},
            # This makes the sensor part of the same device as the climate entity
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Update the state of the sensor from the coordinator data."""
        value = self.coordinator.data.get(self.entity_description.key)
        key = self.entity_description.key

        try:
            if value is None:
                self._attr_native_value = None
                return

            numeric_value = float(value)

            if key == "AC_OUTDOOR_TEMP":
                # The device provides this value in Fahrenheit. Convert to Celsius.
                celsius_value = (numeric_value - 32) * 5 / 9
                self._attr_native_value = round(celsius_value, 1)
            elif key == "AC_ADD2_USEDPOWER":
                # Assuming value is in Wh and converting to kWh
                self._attr_native_value = round(numeric_value / 1000, 2)
            elif key == "AC_ADD2_USEDTIME":
                # Assuming value is in minutes and converting to hours
                self._attr_native_value = round(numeric_value / 60, 2)
            else:
                self._attr_native_value = numeric_value

        except (ValueError, TypeError):
            self._attr_native_value = None
            _LOGGER.warning(
                "%s Could not parse sensor value for %s: %s", self.log_prefix, self.entity_id, value
            )
