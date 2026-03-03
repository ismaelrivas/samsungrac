"""The Samsung Climate IP integration."""
import asyncio
import logging
from typing import Dict, Any
import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed
from homeassistant.const import CONF_NAME, Platform, CONF_TOKEN, CONF_MAC
# Connection classes imported here to ensure registration at startup.
from .connection import CLIMATE_IP_CONNECTIONS
from .connection_request import ConnectionRequest, ConnectionRequestPrint
from .connection_request_tls_auto import ConnectionRequestTlsAuto
from .samsung_2878 import ConnectionSamsung2878
from .connection_aiohttp import ConnectionAiohttp8888
from .connection_raw import ConnectionRaw8888
from .helpers import mask_sensitive_data
from .properties import (
    GetJsonStatus,
    ModeOperation,
    NumericOperation,
    SwitchOperation,
    TemperatureOperation,
    UniqueIdProperty,
)

from .const import (
    DOMAIN, 
    DEVICE_TYPE_TO_CONFIG_FILE, 
    CONF_DEVICE_TYPE, 
    CONF_CONFIG_FILE, 
    CONF_DEVICES, 
    CONF_DEVICE_ID,
    CONF_CONN_METHOD,
    CONN_METHOD_AIOHTTP,
)
from .coordinator import SamsungClimateCoordinator
from .controller_yaml import YamlController, clear_yaml_cache

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.SWITCH]


async def async_setup(hass: HomeAssistant, _typing_config: dict) -> bool:
    """Set up the Climate IP component."""
    
    async def async_reload_yaml(_call):
        """Handle the service call to reload YAML configurations."""
        _LOGGER.info("Reloading climate_ip YAML configurations and restarting integrations.")
        
        # 1. Clear the dictionary holding parsed YAML files
        clear_yaml_cache()
        
        # 2. Grab all loaded config entries for this domain
        entries = hass.config_entries.async_entries(DOMAIN)
        
        # 3. Ask Home Assistant to elegantly reload each one
        reload_tasks = [
            hass.config_entries.async_reload(entry.entry_id)
            for entry in entries
        ]
        
        if reload_tasks:
            await asyncio.gather(*reload_tasks)
            
        _LOGGER.info("Successfully reloaded %s climate_ip integrations.", len(reload_tasks))

    # Register the new reload service
    hass.services.async_register(DOMAIN, "reload", async_reload_yaml)
    
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    # This is called when the user changes options in the UI.
    # Reloading the entry triggers async_unload_entry, which performs the definitive cleanup.
    _LOGGER.debug(
        "Configuration options updated, reloading climate_ip integration for entry %s",
        entry.entry_id,
    )
    await hass.config_entries.async_reload(entry.entry_id)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung Climate IP from a config entry."""

    # Initialize hass.data[DOMAIN] if it doesn't exist
    hass.data.setdefault(DOMAIN, {})

    # Merge options into runtime_config at startup so settings from the OptionsFlow
    # (like conn_method) are available to the controller right from the start.
    runtime_config: Dict[str, Any] = {**entry.data, **entry.options}
    runtime_config["unique_id"] = entry.unique_id
    runtime_config["entry_id"] = entry.entry_id

    device_type = runtime_config.get(CONF_DEVICE_TYPE)
    if device_type:
        runtime_config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)

    # Create a dedicated aiohttp session with extended keepalive for devices polled
    # every 60s+ (the default HA session has only a 30s keepalive which drops connections).
    
    # Initialize sessions store if needed
    hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})
    
    conn_method = runtime_config.get(CONF_CONN_METHOD)
    if conn_method == CONN_METHOD_AIOHTTP:
        _LOGGER.debug(
            "Creating dedicated aiohttp session with keepalive_timeout=75s for valid persistent connection."
        )
        connector = aiohttp.TCPConnector(keepalive_timeout=75)
        # We don't need to close this session explicitly? Actually we DO, because we created it.
        # We will store it in hass.data to close it on unload.
        session = aiohttp.ClientSession(connector=connector)
        hass.data[DOMAIN]["sessions"][entry.entry_id] = session
    else:
        session = async_get_clientsession(hass)

    _LOGGER.info("Starting setup for device %s at %s (Device Type: %s)", 
                 runtime_config.get(CONF_MAC, "Unknown"), 
                 runtime_config.get("ip_address", "Unknown"), 
                 device_type)
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
                _LOGGER.error(
                    "%s Failed to initialize controller for device %s",
                    controller.log_prefix, device_name, exc_info=True
                )
                continue

            coordinator = SamsungClimateCoordinator(hass, controller, entry)
            # Wait for the first refresh to complete before setting up platforms.
            # This ensures that the initial state is available for sensor validation.
            try:
                await coordinator.async_config_entry_first_refresh()
            except ConfigEntryAuthFailed:
                raise
            except Exception as ex:
                _LOGGER.error(
                    "%s Initial connection to Climate IP failed: %s",
                    controller.log_prefix, ex
                )
                raise ConfigEntryNotReady(f"Device unreachable during startup: {ex}") from ex
            coordinators[device_id] = coordinator
        
        if not coordinators:
            _LOGGER.error(
                "No coordinators could be set up for entry %s",
                entry.title, exc_info=True
            )
            return False
        
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators
    else:
        runtime_config["hass"] = hass
        runtime_config["session"] = session
        controller = YamlController(config=runtime_config, logger=_LOGGER)

        
        if not await controller.initialize():
            _LOGGER.error(
                "%s Failed to initialize controller for %s",
                controller.log_prefix, entry.title, exc_info=True
            )
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



async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.entry_id)

    # Clear the YAML cache to ensure changes are loaded on reload.
    clear_yaml_cache()

    # Stop background tasks BEFORE unloading platforms to prevent asymmetric cleanup.
    entry_data = hass.data[DOMAIN].get(entry.entry_id)
    if entry_data:
        _LOGGER.debug("Shutting down background connection tasks for entry %s", entry.entry_id)
        if isinstance(entry_data, dict): # Multiple devices
            for coordinator in entry_data.values():
                await coordinator.async_shutdown()
        elif hasattr(entry_data, "async_shutdown"): # Single coordinator
            await entry_data.async_shutdown()

    # We leave the standard Home Assistant unload logic here.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        if entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
            _LOGGER.debug("Coordinator(s) removed from hass.data for entry %s", entry.entry_id)

    # Close dedicated aiohttp session created for this entry
    if "sessions" in hass.data[DOMAIN] and entry.entry_id in hass.data[DOMAIN]["sessions"]:
        session = hass.data[DOMAIN]["sessions"].pop(entry.entry_id)
        if hasattr(session, "close") and callable(session.close) and not session.closed:
            connector = session.connector  # Grab connector before close
            await session.close()
            # Explicitly close the underlying connector to release file descriptors immediately
            # instead of relying on a synthetic sleep delay (aiohttp 3.x requirement)
            if connector and not connector.closed:
                await connector.close()
        _LOGGER.debug("Closed dedicated aiohttp session for entry %s", entry.entry_id)

    return unload_ok
