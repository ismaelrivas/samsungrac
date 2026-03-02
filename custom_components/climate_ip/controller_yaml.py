import aiofiles
import asyncio
import time

from homeassistant.components.climate import ClimateEntityFeature, HVACMode, ATTR_HVAC_MODE
import copy
import re
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.entity_component
from homeassistant.helpers import config_entry_oauth2_flow
import voluptuous as vol
import yaml
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    ATTR_TEMPERATURE,
    CONF_MAC,
    CONF_IP_ADDRESS,
    CONF_TOKEN,
    STATE_ON,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util.dt import now
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from requests.exceptions import RequestException
from homeassistant.helpers.update_coordinator import UpdateFailed

from .connection import CLIMATE_IP_CONNECTIONS
from .controller import ATTR_POWER, ClimateController, register_controller
from .properties import DeviceProperty, create_property, create_status_getter
from .state import ClimateIPDeviceState
# FIX: Import the missing constant
from .const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_8888_GROUP,
    DEVICE_TYPE_AIOHTTP_SUPPORTED,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    # --- START OF MODIFICATION (Milestone 4) ---
    CONF_CONN_METHOD,
    CONN_METHOD_AIOHTTP,
    CONN_METHOD_REQUESTS,
    CONN_METHOD_RAW,
    # --- END OF MODIFICATION (Milestone 4) ---
    # --- END OF MODIFICATION (Milestone 4) ---
    DOMAIN, # Import DOMAIN
)
from .exceptions import CannotConnect, AuthError, InvalidHeaderError
from .helpers import stream_wrapper, get_value_by_path, mask_sensitive_data
from .const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONFIG_DEVICE,
    CONFIG_DEVICE_ATTRIBUTES,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_OPERATIONS,
    CONFIG_DEVICE_OPERATION_VALUES,
    CONFIG_DEVICE_SWITCHES,
    CONFIG_DEVICE_SENSORS,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_STATUS,
    CONFIG_DEVICE_CONNECTION_TYPE,
    DEFAULT_CONF_TEMP_UNIT,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
)

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = "yaml"
CONST_MAX_GET_STATUS_RETRIES = 4

# Class-level cache to store the raw content of YAML files.
from .controller_yaml_init import YamlControllerInitMixin, clear_yaml_cache
from .controller_yaml_state import YamlControllerStateMixin

@register_controller
class YamlController(ClimateController):
    """
    YAML-based controller, refactored to support asynchronous operations.
    """
class YamlController(YamlControllerInitMixin, YamlControllerStateMixin, ClimateController):
    def __init__(self, config: Dict[str, Any], logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self.hass = config.get("hass")
        self._session = config.get("session")
        
        self._config = config
        self._yaml = config.get(CONF_CONFIG_FILE)
        
        # --- START OF FIX: Handle tests vs real integration keys ---
        # The configuration flow uses CONF_IP_ADDRESS, but our tests and older configs might use CONF_HOST
        self._ip_address = config.get(CONF_IP_ADDRESS) or config.get("host") # "host" == CONF_HOST
        # --- END OF FIX ---
        
        self._device_id = config.get(CONF_DEVICE_ID, None)
        self._token = config.get(CONF_TOKEN, None)
        self._unique_id = config.get("unique_id") or config.get(CONF_MAC) or self._ip_address

        # --- FIX: Bugfix 9.0.10 - Fallback device_id if missing (e.g. single device config) ---
        if not self._device_id:
            if config.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_SAMSUNG_2878:
                 # For 2878, the DUID is essential. Fallback to unique_id or mac.
                 # Usually unique_id holds the sanitized MAC or DUID.
                 self._device_id = self._unique_id
                 _LOGGER.info("%s [Init] device_id was missing, fell back to unique_id: %s", 
                              f"[{self._unique_id[-6:]}]" if self._unique_id else "[Unknown]", 
                              self._device_id)
            else:
                 # For others, fallback to unique_id is usually safe/better than None
                 self._device_id = self._unique_id
        # --- END FIX ---

        self._id_discovered = self._device_id is not None

        self._operations = {}
        self._operations_list = []
        self._properties = {}
        self._properties_list = []

        # Optimization: Cache for device keys extracted from templates.
        self._prop_template_key_cache: Dict[str, Optional[str]] = {}

        # --- ADD SENSOR STORAGE ---
        self._sensors: Dict[str, "DeviceProperty"] = {}
        self._sensors_list: List[str] = []
        # --- END OF ADDITION ---
        self._name = CONST_CONTROLLER_TYPE
        self._attributes = {"controller": self.id}
        self._state_getter = None
        self._debug = config.get("debug", False)
        self._temp_unit = UnitOfTemperature.CELSIUS
        self._service_schema_map = {vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids}
        self._last_device_state = None
        self._shared_raw_client = None # For shared connection pooling
        
        self._raw_yaml_config = None
        # Context-aware cache for parsed YAML. Keyed by device_id.
        self._parsed_yaml_cache: Dict[Optional[str], Dict] = {}

        self.coordinator = None # Reference to the coordinator
        self._is_fully_initialized = False
        # Flag to signal that the fan modes list has changed and a UI flicker is needed.
        self._fan_modes_list_changed_pending_flicker: bool = False

        self._last_state_fetch_time = 0
        self._cached_device_state = None
        self.discovered_devices = None
        # Pre-compile regex for performance. This is safe and state-independent.
        self._device_state_key_regex = re.compile(r"device_state[\[\.](['\"]?)([A-Za-z0-9_]+)\1")

        self._poll = None
        self._consecutive_connection_errors = 0
        self._pending_updates: Dict[str, Tuple[Any, float]] = {}

    @staticmethod
    def match_type(type: str) -> bool:
        return str(type).lower() == CONST_CONTROLLER_TYPE

    @property
    def name(self) -> str:
        return self._name

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def poll(self) -> Optional[bool]:
        """Return the polling state from the YAML configuration."""

        return self._poll

    async def async_set_property(self, property_name, new_value, device_id: Optional[str] = None):
        """
        Asynchronously sets a property on the device.
        """
        if not self._is_fully_initialized:
            _LOGGER.error("%s Cannot set property '%s': controller not fully initialized", self.log_prefix, property_name)
            return False

        op = self._operations.get(property_name)
        if op:
            try:
                # --- START OF FIX: Register Pending Update ---
                # Store the value and current time to prevent immediate overwrite by stale polls.
                self._pending_updates[property_name] = (new_value, time.time())
                _LOGGER.debug("%s Registered pending update for '%s': %s", self.log_prefix, property_name, new_value)
                # --- END OF FIX ---

                return await op.async_set_value(new_value, self._device_id)
            except (RequestException, CannotConnect) as e:
                raise UpdateFailed(f"Failed to set property '{property_name}': {e}") from e
            
        _LOGGER.error("%s Failed to set property '%s': property not found", self.log_prefix, property_name)
        return False

    def get_property(self, property_name):
        value = None
        if property_name in self._operations:
            value = self._operations[property_name].value
        elif property_name in self._properties:
            value = self._properties[property_name].value
        elif property_name in self._sensors:
            value = self._sensors[property_name].value
        else:
            value = self._attributes.get(property_name)

        if value == STATE_UNKNOWN:
            value = None
        
        return value

    def get_property_object(self, property_name: str) -> Optional[Any]:
        """Returns the actual property object, not just its value."""
        if property_name in self._operations:
            return self._operations[property_name]
        if property_name in self._properties:
            return self._properties[property_name]
        if property_name in self._sensors:  # <-- ADD THIS LINE
            return self._sensors[property_name]  # <-- ADD THIS LINE
        _LOGGER.debug("%s Property object '%s' not found", self.log_prefix, property_name)
        return None

    def get_property_all_values(self, property_name: str) -> Optional[List[str]]:
        """Returns the complete, unfiltered list of values for a property."""
        prop = self.get_property_object(property_name)
        if prop and hasattr(prop, 'all_values'):
            return prop.all_values
        _LOGGER.debug("%s Property '%s' does not have an 'all_values' attribute", self.log_prefix, property_name)
        return None

    @property
    def state_attributes(self):
        return self._attributes

    @property
    def temperature_unit(self):
        return self._temp_unit

    @property
    def service_schema_map(self):
        return self._service_schema_map

    @property
    def operations(self):
        return self._operations_list

    @property
    def attributes(self) -> list:
        return self._properties_list

    @property
    def sensors(self) -> List["DeviceProperty"]:
        """Return a list of all defined sensor property objects."""
        # Return the actual property objects, not just the names
        return [self._sensors[name] for name in self._sensors_list if name in self._sensors]

    @property
    def device_state(self) -> Dict[str, Any]:
        """
        Return the current *unwrapped* device state.
        This provides access to the sub-device state (e.g. {'Mode': ...}) 
        which is used by properties and sensors, rather than the raw connection state
        (e.g. {'Devices': ...}).
        """
        if self._last_device_state:
             return self._last_device_state
        
        # Fallback to raw state if no unwrapped state is available yet
        if self._state_getter:
             return self._state_getter.value
        
        return {}


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_CONFIG_FILE): cv.string,
        vol.Optional(CONF_IP_ADDRESS): cv.string,
        vol.Optional(CONF_TOKEN): cv.string,
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_TEMP_NATIVE_CURRENT, default=DEFAULT_CONF_TEMP_UNIT): cv.string,
        vol.Optional(CONF_TEMP_NATIVE_TARGET, default=DEFAULT_CONF_TEMP_UNIT): cv.string,
    }
)