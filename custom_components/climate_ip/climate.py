"""
Platform that offers support for IP controlled climate devices.
This file defines the Home Assistant climate entity.
"""
import asyncio
import logging
import time
from datetime import timedelta

import voluptuous as vol
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
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    DOMAIN,
    ClimateEntity,
    HVACMode,
)
from homeassistant.components.climate.const import (
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ClimateEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    ATTR_TEMPERATURE,
    CONF_IP_ADDRESS,
    CONF_TOKEN,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from homeassistant.helpers.service import extract_entity_ids
from homeassistant.components import persistent_notification
from homeassistant.helpers.translation import async_get_translations


from .controller import ATTR_POWER, create_controller
from .const import DOMAIN
from .yaml_const import (
    CONFIG_DEVICE_NAME,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_UPDATE_DELAY,
    CONF_DEBUG,
)

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES_MAP = {
    ATTR_TEMPERATURE: ClimateEntityFeature.TARGET_TEMPERATURE,
    ATTR_TARGET_TEMP_HIGH: ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
    ATTR_TARGET_TEMP_LOW: ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
    ATTR_FAN_MODE: ClimateEntityFeature.FAN_MODE,
    ATTR_SWING_MODE: ClimateEntityFeature.SWING_MODE,
    ATTR_PRESET_MODE: ClimateEntityFeature.PRESET_MODE,
}

SCAN_INTERVAL = timedelta(seconds=15)
DEFAULT_UPDATE_DELAY = 1.5
SERVICE_SET_CUSTOM_OPERATION = "climate_ip_set_property"
CLIMATE_IP_DATA = "climate_ip_data"
ENTITIES = "entities"
DEFAULT_CLIMATE_IP_TEMP_MIN = 8
DEFAULT_CLIMATE_IP_TEMP_MAX = 30

# This function will now handle the YAML import process.
async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Climate IP platform from YAML and start the import flow."""
    _LOGGER.info("Climate IP YAML configuration found. Starting import process.")
    
    # Load translations for the notification
    translations = await async_get_translations(
        hass, hass.config.language, "common", {DOMAIN}
    )

    # Create a persistent notification to inform the user to remove the YAML configuration.
    persistent_notification.async_create(
        hass,
        message=translations["component.climate_ip.common.deprecated_yaml_message"],
        title=translations["component.climate_ip.common.deprecated_yaml_title"],
        notification_id="climate_ip_yaml_deprecated",
    )
    
    # Trigger the import flow.
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "import"},
            data=config,
        )
    )
    
    # We return True to indicate that the platform setup has been handled.
    # No entities are added here directly anymore.
    return True

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the climate entity from a config entry."""
    config = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.info("Setting up Climate IP entity for %s", config.get(CONF_IP_ADDRESS, "unknown IP"))
    
    try:
        device_controller = await create_controller("yaml", config, _LOGGER)
    except Exception as e:
        _LOGGER.error("Error creating device controller for %s: %s", config.get(CONF_IP_ADDRESS), e)
        return

    if not device_controller:
        _LOGGER.error("Could not initialize device controller for %s.", config.get(CONF_IP_ADDRESS))
        return

    async_add_entities([ClimateIP(device_controller, config)], True)

    async def async_service_handler(service):
        params = {key: value for key, value in service.data.items() if key != ATTR_ENTITY_ID}
        entity_ids = service.data.get(ATTR_ENTITY_ID)
        _LOGGER.debug("Handling service call '%s' for entities: %s with params: %s", service.service, entity_ids, params)
        
        devices_to_update = []
        if CLIMATE_IP_DATA in hass.data and ENTITIES in hass.data[CLIMATE_IP_DATA]:
            if entity_ids:
                devices_to_update = [
                    device for device in hass.data[CLIMATE_IP_DATA][ENTITIES]
                    if device.entity_id in entity_ids
                ]
            else:
                devices_to_update = hass.data[CLIMATE_IP_DATA][ENTITIES]
        
        for device in devices_to_update:
            if hasattr(device, "async_set_custom_operation"):
                await device.async_set_custom_operation(**params)

    service_schema = device_controller.service_schema_map or {}
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CUSTOM_OPERATION,
        async_service_handler,
        schema=vol.Schema(service_schema),
    )


class ClimateIP(ClimateEntity):
    """Representation of a Samsung climate device."""

    def __init__(self, rac_controller, config):
        """Initialize the climate device."""
        _LOGGER.debug("Initializing ClimateIP entity for controller: %s", rac_controller.name)
        self.rac = rac_controller
        self._name = config.get(CONFIG_DEVICE_NAME, None)
        self._poll = None
        self._attr_unique_id = "climate_ip_" + (self.rac.unique_id or self._name or config.get(CONF_IP_ADDRESS))

        poll_value = config.get(CONFIG_DEVICE_POLL)
        if isinstance(poll_value, bool):
            self._poll = poll_value
        elif isinstance(poll_value, str) and poll_value:
            if poll_value.lower() == "true":
                self._poll = True
            elif poll_value.lower() == "false":
                self._poll = False
        
        features = 0
        for f, feature_flag in SUPPORTED_FEATURES_MAP.items():
            if f in self.rac.operations or f in self.rac.attributes:
                features |= feature_flag
        if 'power' in self.rac.operations:
            features |= ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        
        self._attr_supported_features = features
        self._update_delay = float(config.get(CONFIG_DEVICE_UPDATE_DELAY, DEFAULT_UPDATE_DELAY))
        self._last_optimistic_update_time = 0
        self._optimistic_debounce_seconds = 10
        _LOGGER.debug("ClimateIP entity '%s' initialized with unique_id: %s and features: %s", self.name, self._attr_unique_id, features)


    @property
    def should_poll(self):
        """Return the polling state."""
        if self._poll is not None:
            return self._poll
        return self.rac.poll

    async def async_update(self):
        """Update the state of the device from the controller."""
        if time.time() - self._last_optimistic_update_time < self._optimistic_debounce_seconds:
            _LOGGER.debug("[%s] Skipping poll to allow optimistic update to settle.", self.name)
            return
        _LOGGER.debug("[%s] Asynchronously updating state.", self.name)
        await self.rac.async_update_state()

    async def _send_and_verify(self, prop, value):
        """Send a command and optimistically update the state."""
        _LOGGER.debug("[%s] Sending property '%s' with value '%s'.", self.name, prop, value)
        if prop in self.rac._operations:
            self.rac._operations[prop]._value = value
        self._last_optimistic_update_time = time.time()
        self.async_write_ha_state()
        self.hass.async_create_task(self.rac.async_set_property(prop, value))

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        new_temp = kwargs.get(ATTR_TEMPERATURE)
        _LOGGER.debug("[%s] Service call: set_temperature to %s", self.name, new_temp)
        if new_temp is not None:
            await self._send_and_verify(ATTR_TEMPERATURE, new_temp)

    async def async_set_hvac_mode(self, hvac_mode: str):
        """Set new target hvac mode."""
        _LOGGER.debug("[%s] Service call: set_hvac_mode to %s", self.name, hvac_mode)
        await self._send_and_verify(ATTR_HVAC_MODE, hvac_mode)

    async def async_set_fan_mode(self, fan_mode: str):
        """Set new target fan mode."""
        _LOGGER.debug("[%s] Service call: set_fan_mode to %s", self.name, fan_mode)
        await self._send_and_verify(ATTR_FAN_MODE, fan_mode)

    async def async_set_swing_mode(self, swing_mode: str):
        """Set new target swing operation."""
        _LOGGER.debug("[%s] Service call: set_swing_mode to %s", self.name, swing_mode)
        await self._send_and_verify(ATTR_SWING_MODE, swing_mode)

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new target preset mode."""
        _LOGGER.debug("[%s] Service call: set_preset_mode to %s", self.name, preset_mode)
        await self._send_and_verify(ATTR_PRESET_MODE, preset_mode)

    async def async_turn_on(self):
        """Turn the climate device on."""
        _LOGGER.debug("[%s] Service call: turn_on", self.name)
        await self._send_and_verify(ATTR_POWER, STATE_ON)

    async def async_turn_off(self):
        """Turn the climate device off."""
        _LOGGER.debug("[%s] Service call: turn_off", self.name)
        await self._send_and_verify(ATTR_POWER, STATE_OFF)
        
    async def async_set_custom_operation(self, **kwargs):
        """Set custom device mode to specified value."""
        for key, value in kwargs.items():
            _LOGGER.info("[%s] Custom operation, setting property %s to %s", self.name, key, value)
            await self.rac.async_set_property(key, value)
        await asyncio.sleep(self._update_delay)
        await self.async_update()
        self.async_write_ha_state()

    @property
    def name(self):
        """Return the name of the climate device."""
        if self._name is not None:
            return self._name
        return "climate_ip_" + self.rac.name

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attrs = self.rac.state_attributes
        _LOGGER.debug("[%s] Providing extra_state_attributes: %s", self.name, attrs)
        return attrs

    @property
    def temperature_unit(self):
        return self.rac.temperature_unit

    @property
    def current_temperature(self):
        temp = self.rac.get_property(ATTR_CURRENT_TEMPERATURE)
        _LOGGER.debug("[%s] Getting current_temperature: %s", self.name, temp)
        return temp

    @property
    def target_temperature(self):
        temp = self.rac.get_property(ATTR_TEMPERATURE)
        _LOGGER.debug("[%s] Getting target_temperature: %s", self.name, temp)
        return temp
        
    @property
    def hvac_mode(self):
        mode = self.rac.get_property(ATTR_HVAC_MODE)
        _LOGGER.debug("[%s] Getting hvac_mode: %s", self.name, mode)
        return mode if mode not in [STATE_UNKNOWN, STATE_UNAVAILABLE, "", None] else HVACMode.OFF

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes."""
        modes = self.rac.get_property(ATTR_HVAC_MODES) or []
        if 'power' in self.rac.operations and HVACMode.OFF not in modes:
            modes_with_off = modes + [HVACMode.OFF]
            _LOGGER.debug("[%s] Getting hvac_modes: %s", self.name, modes_with_off)
            return modes_with_off
        _LOGGER.debug("[%s] Getting hvac_modes: %s", self.name, modes)
        return modes
        
    @property
    def fan_mode(self):
        mode = self.rac.get_property(ATTR_FAN_MODE)
        _LOGGER.debug("[%s] Getting fan_mode: %s", self.name, mode)
        return mode

    @property
    def fan_modes(self):
        modes = self.rac.get_property(ATTR_FAN_MODES)
        _LOGGER.debug("[%s] Getting fan_modes: %s", self.name, modes)
        return modes

    @property
    def swing_mode(self):
        mode = self.rac.get_property(ATTR_SWING_MODE)
        _LOGGER.debug("[%s] Getting swing_mode: %s", self.name, mode)
        return mode

    @property
    def swing_modes(self):
        modes = self.rac.get_property(ATTR_SWING_MODES)
        _LOGGER.debug("[%s] Getting swing_modes: %s", self.name, modes)
        return modes
        
    @property
    def preset_mode(self):
        mode = self.rac.get_property(ATTR_PRESET_MODE)
        _LOGGER.debug("[%s] Getting preset_mode: %s", self.name, mode)
        return mode

    @property
    def preset_modes(self):
        modes = self.rac.get_property(ATTR_PRESET_MODES)
        _LOGGER.debug("[%s] Getting preset_modes: %s", self.name, modes)
        return modes
    
    @property
    def min_temp(self):
        """Return the minimum temperature."""
        min_t = self.rac.get_property(ATTR_MIN_TEMP)
        if min_t is not None:
            return min_t
        return DEFAULT_CLIMATE_IP_TEMP_MIN

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        max_t = self.rac.get_property(ATTR_MAX_TEMP)
        if max_t is not None:
            return max_t
        return DEFAULT_CLIMATE_IP_TEMP_MAX
    
    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        _LOGGER.debug("[%s] Entity added to hass.", self.name)
        if CLIMATE_IP_DATA not in self.hass.data:
            self.hass.data[CLIMATE_IP_DATA] = {ENTITIES: []}
        self.hass.data[CLIMATE_IP_DATA][ENTITIES].append(self)

    async def async_will_remove_from_hass(self):
        """Run when entity will be removed from hass."""
        await super().async_will_remove_from_hass()
        _LOGGER.debug("[%s] Entity will be removed from hass.", self.name)
        if CLIMATE_IP_DATA in self.hass.data and self in self.hass.data[CLIMATE_IP_DATA][ENTITIES]:
            self.hass.data[CLIMATE_IP_DATA][ENTITIES].remove(self)
