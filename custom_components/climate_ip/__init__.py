"""The Climate IP integration."""
import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

# Import controllers and connections so they can be registered
from .controller_yaml import YamlController
from .connection_request import ConnectionRequest, ConnectionRequestPrint
from .connection_request_tls_auto import ConnectionRequestTlsAuto
from .samsung_2878 import ConnectionSamsung2878
from .properties import (
    GetJsonStatus,
    ModeOperation,
    NumericOperation,
    SwitchOperation,
    TemperatureOperation,
    UniqueIdProperty,
)

from .const import DOMAIN, DEVICE_TYPE_TO_CONFIG_FILE, CONF_DEVICE_TYPE, CONF_CONFIG_FILE

# List of platforms that this integration will configure.
PLATFORMS = ["climate"]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Climate IP from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    config_data = dict(entry.data)
    device_type = config_data.get(CONF_DEVICE_TYPE)
    
    if CONF_CONFIG_FILE not in config_data:
        config_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)

    hass.data[DOMAIN][entry.entry_id] = config_data
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
