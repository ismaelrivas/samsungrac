import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_NAME

from .connection import create_connection, remove_connection # Modified import
from .samsung_2878 import ConnectionSamsung2878
from .properties import (
    GetJsonStatus,
    ModeOperation,
    NumericOperation,
    SwitchOperation,
    TemperatureOperation,
    UniqueIdProperty,
)

from .const import DOMAIN, DEVICE_TYPE_TO_CONFIG_FILE, CONF_DEVICE_TYPE, CONF_CONFIG_FILE, PLATFORMS, CONF_DEVICES, CONF_DEVICE_ID
from .coordinator import SamsungClimateCoordinator
from .controller_yaml import YamlController

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Samsung Climate IP from a config entry."""
    
    # Create a mutable copy of the config entry data.
    config_data = dict(entry.data)
    
    # Pass the unique_id from the config entry to the controller
    # to ensure it's available from the start.
    config_data["unique_id"] = entry.unique_id
    
    device_type = config_data.get(CONF_DEVICE_TYPE)
    
    # Determine the correct YAML configuration file if not specified.
    if CONF_CONFIG_FILE not in config_data or not config_data[CONF_CONFIG_FILE]:
        config_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)
        _LOGGER.debug("Configuration file not specified, using default for type '%s': %s",
                      device_type, config_data[CONF_CONFIG_FILE])

    # Check if there are multiple devices configured within this entry
    devices_config = config_data.get(CONF_DEVICES)

    if devices_config:
        # If multiple devices are present, create a coordinator for each
        coordinators = {}
        for device_info in devices_config:
            device_id = device_info.get("id")
            device_name = device_info.get("name")
            device_uuid = device_info.get("uuid")

            # Create a copy of config_data for each device, overriding device_id and unique_id
            device_config_data = config_data.copy()
            device_config_data[CONF_DEVICE_ID] = device_id
            device_config_data["unique_id"] = device_uuid or f"{entry.unique_id}_{device_id}"
            
            _LOGGER.debug("Setting up controller for device: %s with unique_id: %s", device_name, device_config_data["unique_id"])

            controller = YamlController(
                config=device_config_data,
                logger=_LOGGER
            )
            
            if not await controller.initialize():
                _LOGGER.error("%s Failed to initialize controller for device %s", controller.log_prefix, device_name)
                # Continue to next device, or handle error as appropriate
                continue

            coordinator = SamsungClimateCoordinator(hass, controller, entry)
            await coordinator.async_config_entry_first_refresh()
            coordinators[device_id] = coordinator
        
        if not coordinators:
            _LOGGER.error("No coordinators could be set up for entry %s with devices %s", entry.title, devices_config)
            return False
        
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators
    else:
        # Original logic for single device setup
        controller = YamlController(
            config=config_data,
            logger=_LOGGER
        )
        
        if not await controller.initialize():
            _LOGGER.error("%s Failed to initialize controller for %s", controller.log_prefix, entry.title)
            return False

        coordinator = SamsungClimateCoordinator(hass, controller, entry)
        await coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 5. Load the platforms (climate.py, sensor.py).
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.data)

    # Get the coordinator to access the connection object before it's removed
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    connection_to_clean = None
    if coordinator and hasattr(coordinator, 'controller'):
        connection_to_clean = coordinator.controller.connection

    # Unload the platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove the coordinator from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Coordinator removed from hass.data")

        # Clean up the connection from the singleton store
        if connection_to_clean:
            _LOGGER.debug("Removing connection from singleton store.")
            await remove_connection(connection_to_clean.config)

    return unload_ok
