import asyncio
import logging
import copy

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_NAME, Platform, CONF_TOKEN, CONF_MAC
from .connection import create_connection, remove_connection
from .samsung_2878 import ConnectionSamsung2878
from .properties import (
    GetJsonStatus,
    ModeOperation,
    NumericOperation,
    SwitchOperation,
    TemperatureOperation,
    UniqueIdProperty,
)

from .const import DOMAIN, DEVICE_TYPE_TO_CONFIG_FILE, CONF_DEVICE_TYPE, CONF_CONFIG_FILE, CONF_DEVICES, CONF_DEVICE_ID
from .coordinator import SamsungClimateCoordinator
from .controller_yaml import YamlController

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]

def _mask_sensitive_data(data: dict) -> dict:
    """Return a copy of a dictionary with sensitive values masked."""
    if not isinstance(data, dict):
        return data
        
    masked_data = copy.deepcopy(data)
    
    sensitive_keys = [CONF_TOKEN, CONF_MAC, "unique_id", "uuid"]
    
    for key, value in masked_data.items():
        if key in sensitive_keys and isinstance(value, str) and len(value) > 4:
            masked_data[key] = f"***{value[-4:]}"
            
    return masked_data

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Samsung Climate IP from a config entry."""

    runtime_config = dict(entry.data)
    runtime_config["unique_id"] = entry.unique_id

    device_type = runtime_config.get(CONF_DEVICE_TYPE)
    runtime_config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)

    _LOGGER.debug("Starting setup for entry %s with runtime config: %s", entry.entry_id, _mask_sensitive_data(runtime_config))

    if devices_config := runtime_config.get(CONF_DEVICES):
        coordinators = {}
        for device_info in devices_config:
            device_id = device_info.get("id")
            device_name = device_info.get("name")
            device_uuid = device_info.get("uuid")

            device_config_data = runtime_config.copy()
            device_config_data[CONF_DEVICE_ID] = device_id
            device_config_data["unique_id"] = device_uuid or f"{entry.unique_id}_{device_id}"
            
            _LOGGER.debug(
                "Setting up controller for device: %s with unique_id: %s",
                device_name, device_config_data["unique_id"]
            )

            controller = YamlController(
                config=device_config_data,
                logger=_LOGGER
            )
            
            if not await controller.initialize():
                _LOGGER.error("%s Failed to initialize controller for device %s", controller.log_prefix, device_name, exc_info=True)
                continue

            coordinator = SamsungClimateCoordinator(hass, controller, entry)
            # Wait for the first refresh to complete before setting up platforms.
            # This ensures that the initial state is available for sensor validation.
            await coordinator.async_config_entry_first_refresh()
            coordinators[device_id] = coordinator
        
        if not coordinators:
            _LOGGER.error("No coordinators could be set up for entry %s", entry.title, exc_info=True)
            return False
        
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators
    else:
        controller = YamlController(
            config=runtime_config,
            logger=_LOGGER
        )
        
        if not await controller.initialize():
            _LOGGER.error("%s Failed to initialize controller for %s", controller.log_prefix, entry.title, exc_info=True)
            return False

        coordinator = SamsungClimateCoordinator(hass, controller, entry)
        # Wait for the first refresh to complete before setting up platforms.
        # This ensures that the initial state is available for sensor validation.
        await coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.data)
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    connection_to_clean = None
    if coordinator and hasattr(coordinator, 'controller'):
        connection_to_clean = coordinator.controller.connection

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Coordinator removed from hass.data")

        if connection_to_clean:
            _LOGGER.debug("Removing connection from singleton store")
            await remove_connection(connection_to_clean.config)

    return unload_ok
