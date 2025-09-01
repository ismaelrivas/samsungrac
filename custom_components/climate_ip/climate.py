import logging
from typing import Any, Dict, Optional

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import ATTR_MAX_TEMP, ATTR_MIN_TEMP
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_DEVICES
from .controller import ATTR_POWER
from .coordinator import SamsungClimateCoordinator

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES_MAP = {
    ATTR_TEMPERATURE: ClimateEntityFeature.TARGET_TEMPERATURE,
    ATTR_FAN_MODE: ClimateEntityFeature.FAN_MODE,
    ATTR_SWING_MODE: ClimateEntityFeature.SWING_MODE,
    ATTR_PRESET_MODE: ClimateEntityFeature.PRESET_MODE,
}

DEFAULT_CLIMATE_IP_TEMP_MIN = 8
DEFAULT_CLIMATE_IP_TEMP_MAX = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate entity from a config entry."""
    coordinators = hass.data[DOMAIN][entry.entry_id]
    
    if isinstance(coordinators, dict):
        entities = []
        for device_id, coordinator in coordinators.items():
            # Find the device_info for this device_id in the entry data
            device_info = next((d for d in entry.data.get(CONF_DEVICES, []) if d.get('id') == device_id), None)
            if device_info:
                entities.append(ClimateIP(coordinator, entry.data, device_info, entry.unique_id))
        async_add_entities(entities, True)
    else:
        # Fallback for single-device setups or older configs
        coordinator = coordinators
        async_add_entities([ClimateIP(coordinator, entry.data, None, entry.unique_id)], True)


class ClimateIP(CoordinatorEntity[SamsungClimateCoordinator], ClimateEntity):
    """Representation of a climate_ip climate device using a coordinator."""

    def __init__(self, coordinator: SamsungClimateCoordinator, config: Dict[str, Any], device_info: Optional[Dict[str, Any]] = None, main_unique_id: str = None):
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._config = config
        self._main_unique_id = main_unique_id or coordinator.unique_id
        
        if device_info:
            # For multi-device entries, use the name of the specific indoor unit
            self._name = device_info.get("name")
            self._attr_unique_id = device_info.get("uuid") or f"{self._main_unique_id}_{device_info.get('id')}"
        else:
            # For single-device entries, create a default name if none is provided
            self._attr_unique_id = self.coordinator.unique_id
            user_defined_name = self._config.get(CONF_NAME)
            if user_defined_name:
                self._name = user_defined_name
            else:
                # Fallback to a generated name based on the device's unique id
                self._name = f"Samsung AC {self.coordinator.unique_id}"

        # Comprueba las propiedades que se pueden establecer (operaciones)
        features = ClimateEntityFeature(0)
        if ATTR_TEMPERATURE in self.coordinator.operations:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        
        if ATTR_FAN_MODE in self.coordinator.operations:
            features |= ClimateEntityFeature.FAN_MODE
            
        if ATTR_SWING_MODE in self.coordinator.operations:
            features |= ClimateEntityFeature.SWING_MODE
            
        if ATTR_PRESET_MODE in self.coordinator.operations:
            features |= ClimateEntityFeature.PRESET_MODE
            
        # Comprueba si hay control de encendido, lo que habilita turn_on y turn_off
        if ATTR_POWER in self.coordinator.operations:
            features |= ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        self._attr_supported_features = features

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the coordinator for consistency."""
        return self.coordinator.log_prefix

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        if self.coordinator.is_push_device:
            connection = self.coordinator.controller.connection
            if connection and hasattr(connection, 'set_update_callback'):
                _LOGGER.debug("%s Climate entity added; setting up push update callback and starting listener.", self.log_prefix)
                connection.set_update_callback(self.coordinator.async_handle_push_update)
                connection.start_listening()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self.coordinator.is_push_device:
            connection = self.coordinator.controller.connection
            if connection and hasattr(connection, 'stop_listening'):
                _LOGGER.debug("%s Climate entity removing; stopping push listener.", self.log_prefix)
                await connection.stop_listening()
        await super().async_will_remove_from_hass()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for the device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._main_unique_id)},
            name=self._config.get(CONF_NAME, "Samsung AC"), # Use the name from the config entry for the device
            manufacturer="Samsung",
        )

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.async_set_property(ATTR_TEMPERATURE, temp)

    async def async_set_hvac_mode(self, hvac_mode: str):
        """Set new target hvac mode."""
        await self.coordinator.async_set_property(ATTR_HVAC_MODE, hvac_mode)

    async def async_set_fan_mode(self, fan_mode: str):
        """Set new target fan mode."""
        await self.coordinator.async_set_property(ATTR_FAN_MODE, fan_mode)

    async def async_set_swing_mode(self, swing_mode: str):
        """Set new target swing operation."""
        await self.coordinator.async_set_property(ATTR_SWING_MODE, swing_mode)

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new target preset mode."""
        await self.coordinator.async_set_property(ATTR_PRESET_MODE, preset_mode)

    async def async_turn_on(self):
        """Turn the climate device on."""
        await self.coordinator.async_set_property(ATTR_POWER, STATE_ON)

    async def async_turn_off(self):
        """Turn the climate device off."""
        await self.coordinator.async_set_property(ATTR_POWER, STATE_OFF)

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self.coordinator.state_attributes

    @property
    def temperature_unit(self):
        """Return the temperature unit."""
        return self.coordinator.temperature_unit

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.coordinator.get_property(ATTR_CURRENT_TEMPERATURE)

    @property
    def target_temperature(self):
        """Return the target temperature."""
        return self.coordinator.get_property(ATTR_TEMPERATURE)

    @property
    def hvac_mode(self):
        """Return the current hvac mode."""
        mode = self.coordinator.get_property(ATTR_HVAC_MODE)
        return mode if mode else HVACMode.OFF

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes."""
        modes = self.coordinator.get_property(ATTR_HVAC_MODES) or []
        if 'power' in self.coordinator.operations and HVACMode.OFF not in modes:
            return modes + [HVACMode.OFF]
        return modes

    @property
    def fan_mode(self):
        """Return the current fan mode."""
        return self.coordinator.get_property(ATTR_FAN_MODE)

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        return self.coordinator.get_property(ATTR_FAN_MODES)

    @property
    def swing_mode(self):
        """Return the current swing mode."""
        return self.coordinator.get_property(ATTR_SWING_MODE)

    @property
    def swing_modes(self):
        """Return the list of available swing modes."""
        return self.coordinator.get_property(ATTR_SWING_MODES)

    @property
    def preset_mode(self):
        """Return the current preset mode."""
        return self.coordinator.get_property(ATTR_PRESET_MODE)

    @property
    def preset_modes(self):
        """Return the list of available preset modes."""
        return self.coordinator.get_property(ATTR_PRESET_MODES)

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        min_t = self.coordinator.get_property(ATTR_MIN_TEMP)
        return min_t if min_t is not None else DEFAULT_CLIMATE_IP_TEMP_MIN

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        max_t = self.coordinator.get_property(ATTR_MAX_TEMP)
        return max_t if max_t is not None else DEFAULT_CLIMATE_IP_TEMP_MAX
