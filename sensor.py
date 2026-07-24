"""
Platform that offers support for IP controlled climate device sensors.
This file defines the Home Assistant sensor entities, adapted for DataUpdateCoordinator.
"""

import logging

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant import const
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClimateIPConfigEntry
from .coordinator import SamsungClimateCoordinator
from .helpers import parse_entity_category
from .properties import DeviceProperty, UniqueIdProperty

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ClimateIPConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor entities from a config entry."""
    coordinator_data = entry.runtime_data

    entities_to_add: list[ClimateIpSensor] = []
    coordinators: list[SamsungClimateCoordinator] = (
        list(coordinator_data.values())
        if isinstance(coordinator_data, dict)
        else [coordinator_data]
    )

    for coordinator in coordinators:
        raw_device_state = coordinator.controller.device_state

        for sensor_prop in coordinator.controller.sensors:
            if sensor_prop.is_valid(raw_device_state):
                parsed_category = parse_entity_category(
                    getattr(sensor_prop, "entity_category", None)
                )

                device_class = getattr(sensor_prop, "device_class", None)
                icon = getattr(sensor_prop, "icon", None)
                if not icon and not device_class:
                    icon = "mdi:eye"
                yaml_name = getattr(
                    sensor_prop, "name", None
                )  # Explicit name from YAML (can be empty)
                # Build a modern SensorEntityDescription from the YAML property.
                # Instantiated in the platform, not inside the entity class.
                description = SensorEntityDescription(
                    key=sensor_prop.id,
                    translation_key=sensor_prop.id,
                    name=yaml_name,
                    device_class=device_class,
                    native_unit_of_measurement=getattr(
                        sensor_prop, "unit_of_measurement", None
                    ),
                    state_class=getattr(sensor_prop, "state_class", None),
                    entity_category=parsed_category,
                    icon=icon,
                )

                entities_to_add.append(
                    ClimateIpSensor(coordinator, description, sensor_prop)
                )

    if entities_to_add:
        msg = (
            "%s Adding %d YAML-defined sensors to Home Assistant."  # pragma: no mutate
        )
        _LOGGER.info(
            msg,
            coordinators[0].log_prefix if coordinators else "[ClimateIP]",
            len(entities_to_add),
        )  # pragma: no mutate
        async_add_entities(entities_to_add)


class ClimateIpSensor(CoordinatorEntity[SamsungClimateCoordinator], SensorEntity):
    """Representation of a Climate IP sensor defined by YAML."""

    _attr_native_value: str | float | None

    def __init__(
        self,
        coordinator: SamsungClimateCoordinator,
        description: SensorEntityDescription,
        property_object: DeviceProperty,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        # Inject the standardised description provided by the platform setup.
        self.entity_description = description
        self._property = property_object

        # _attr_has_entity_name = True lets HA build the display name as
        # "Device Name ▸ EntityDescription Name" without double-prefixing.
        self._attr_has_entity_name = True
        self._attr_native_value = None
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"

        # Ensure initial state from coordinator to prevent being unavailable on startup.
        self._sync_data_from_coordinator()

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the coordinator for consistency."""
        return self.coordinator.log_prefix

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for the device registry."""
        return self.coordinator.device_info

    def _sync_data_from_coordinator(self) -> None:
        """Synchronize the entity's state with the latest data from the coordinator."""
        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        raw_device_state = self.coordinator.controller.device_state
        is_valid = self._property.is_valid(raw_device_state)

        if is_valid:
            self._update_state()
            self.async_write_ha_state()
        else:
            self._attr_native_value = None
            msg = "%s Marking sensor '%s' as unavailable because it is no longer valid."  # pragma: no mutate
            _LOGGER.debug(
                msg, self.log_prefix, self.entity_description.key
            )  # pragma: no mutate
            self.async_write_ha_state()

    def _update_state(self) -> None:
        """Update the state of the sensor from the coordinator data."""
        value = self.coordinator.get_property(self.entity_description.key)

        if value is None or value == const.STATE_UNKNOWN:
            self._attr_native_value = None
            return

        # fmt: off
        is_str = getattr(self._property, "value_is_string", False)  # pragma: no mutate
        # fmt: on
        if isinstance(self._property, UniqueIdProperty) or is_str:
            self._attr_native_value = str(value)
        else:
            try:
                self._attr_native_value = float(value)
            except (ValueError, TypeError):
                self._attr_native_value = None
                msg = "%s Could not parse sensor value for %s: %s"  # pragma: no mutate
                _LOGGER.warning(
                    msg, self.log_prefix, self.entity_description.key, value
                )  # pragma: no mutate
