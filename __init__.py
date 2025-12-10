import asyncio
import logging
import copy
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_NAME, Platform, CONF_TOKEN, CONF_MAC
# --- START OF MODIFICATION: Centralize connection imports to break circular dependency ---
# Import all connection classes here to ensure they are registered at startup.
from .connection import _CONNECTIONS_STORE, _CONNECTIONS_LOCK
from .connection_request import ConnectionRequest, ConnectionRequestPrint
from .connection_request_tls_auto import ConnectionRequestTlsAuto
from .samsung_2878 import ConnectionSamsung2878
from .connection_aiohttp import ConnectionAiohttp8888
# --- END OF MODIFICATION ---
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
from .controller_yaml import YamlController, clear_yaml_cache

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

async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    # This is called when the user changes options in the UI.
    _LOGGER.debug("Configuration options updated, reloading climate_ip integration for entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)

    # --- START OF FIX: Clear connection cache on options update ---
    # When switching between aiohttp and requests, the old connection object
    # must be discarded to force the creation of a new one with the correct engine.
    key_to_remove = entry.unique_id
    async with _CONNECTIONS_LOCK:
        if key_to_remove in _CONNECTIONS_STORE:
            _LOGGER.debug("Options update: Removing connection object for '%s' to allow engine switch.", key_to_remove)
            _CONNECTIONS_STORE.pop(key_to_remove)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Samsung Climate IP from a config entry."""

    # --- START OF FIX: Clear connection cache on setup ---
    # This is crucial for the self-healing mechanism. If the previous load failed
    # (e.g., due to malformed headers), `async_unload_entry` is not called, and the
    # old connection object (aiohttp) would remain in the cache. By clearing the cache
    # here, we ensure that a new connection object (requests) is created
    # that respects the updated configuration.
    key_to_remove = entry.unique_id
    async with _CONNECTIONS_LOCK:
        if key_to_remove in _CONNECTIONS_STORE:
            _LOGGER.debug("Pre-setup cache clean: Removing connection object for '%s' to ensure clean start.", key_to_remove)
            _CONNECTIONS_STORE.pop(key_to_remove)
    # --- END OF FIX ---

    # --- START OF FIX: Merge options into runtime_config at startup ---
    # This ensures that settings from the OptionsFlow (like conn_method) are
    # available to the controller right from the start.
    runtime_config = {**entry.data, **entry.options}
    # --- END OF FIX ---
    runtime_config["unique_id"] = entry.unique_id
    runtime_config["entry_id"] = entry.entry_id  # Pass entry_id to the controller

    device_type = runtime_config.get(CONF_DEVICE_TYPE)
    # --- START OF FIX: Ensure device_type is not None before using it as a key ---
    if device_type:
        runtime_config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)

    # --- START OF MODIFICATION (Milestone 3) ---
    session = async_get_clientsession(hass)
    # --- END OF MODIFICATION (Milestone 3) ---

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

            device_config_data["hass"] = hass
            device_config_data["session"] = session
            controller = YamlController(config=device_config_data, logger=_LOGGER)

            
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
        runtime_config["hass"] = hass
        runtime_config["session"] = session
        controller = YamlController(config=runtime_config, logger=_LOGGER)

        
        if not await controller.initialize():
            _LOGGER.error("%s Failed to initialize controller for %s", controller.log_prefix, entry.title, exc_info=True)
            return False

        coordinator = SamsungClimateCoordinator(hass, controller, entry)
        # Wait for the first refresh to complete before setting up platforms.
        # This ensures that the initial state is available for sensor validation.
        await coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Add listener for options changes.
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True

async def remove_connection(config):
    """Remove a connection object from the store."""
    key = config.get("unique_id")
    if not key:
        _LOGGER.warning("Cannot remove a connection without a unique_id in the config")
        return

    async with _CONNECTIONS_LOCK:
        if key in _CONNECTIONS_STORE:
            _LOGGER.debug("Removing connection object for %s", key)
            _CONNECTIONS_STORE.pop(key)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.entry_id)

    # Clear the YAML cache to ensure changes are loaded on reload.
    clear_yaml_cache()

    # The connection cache is now cleared in async_setup_entry to handle failed reloads.
    # We leave the standard Home Assistant unload logic here.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        if entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
            _LOGGER.debug("Coordinator removed from hass.data for entry %s", entry.entry_id)

    # --- START OF FIX: Stop connection listener on unload ---
    # We must explicitly stop the connection listener (if it exists) to prevent
    # "zombie" tasks from running in the background after reload/unload.
    key_to_remove = entry.unique_id
    async with _CONNECTIONS_LOCK:
        if key_to_remove in _CONNECTIONS_STORE:
            connection = _CONNECTIONS_STORE[key_to_remove]
            if hasattr(connection, "stop_listening"):
                _LOGGER.debug("Stopping connection listener for '%s'", key_to_remove)
                try:
                    await connection.stop_listening()
                except Exception as e:
                    _LOGGER.error("Error stopping connection listener for '%s': %s", key_to_remove, e)
            
            _LOGGER.debug("Removing connection object for '%s' from store.", key_to_remove)
            _CONNECTIONS_STORE.pop(key_to_remove)
    # --- END OF FIX ---

    return unload_ok
