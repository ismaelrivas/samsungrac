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
_YAML_FILE_CACHE: Dict[str, str] = {}

def clear_yaml_cache():
    """Clears the YAML file content cache to allow reloading from disk."""
    if _YAML_FILE_CACHE:
        _LOGGER.info("Clearing YAML file cache to force re-read on reload.")
        _YAML_FILE_CACHE.clear()



class YamlControllerInitMixin:
    """Mixin for initialization and YAML loading logic."""

    @property
    def is_fully_initialized(self) -> bool:
        """Return True if the controller has completed its initialization."""
        return self._is_fully_initialized

    @property
    def log_prefix(self) -> str:
        return f"[{self.unique_id[-6:]}]" if self.unique_id and len(self.unique_id) >= 6 else f"[{self.name or 'NO_ID'}]"

    @property
    def unique_id(self) -> Optional[str]:
        return self._unique_id

    @property
    def device_id(self) -> Optional[str]:
        return self._device_id

    @property
    def token(self) -> Optional[str]:
        """Return the device token."""
        return self._token

    @property
    def ip_address(self) -> Optional[str]:
        """Return the device IP address."""
        return self._ip_address

    async def _finish_initialization(self):
        """
        Completes the controller's initialization after the device_id has been discovered.
        This involves loading the final operational and attribute properties from the YAML.
        """
        if self._is_fully_initialized or not self._raw_yaml_config:
            return
        
        # Use the context-aware cache
        if self._device_id in self._parsed_yaml_cache:
            yaml_device = self._parsed_yaml_cache[self._device_id]
        else:
            final_yaml_str = stream_wrapper(
                self._raw_yaml_config, self._token, self._ip_address, self._device_id
            )
            
            def _parse_yaml(data_str):
                return yaml.safe_load(data_str)
                
            if getattr(self, "hass", None):
                yaml_device = await self.hass.async_add_executor_job(_parse_yaml, final_yaml_str)
            else:
                yaml_device = yaml.safe_load(final_yaml_str)
                
            self._parsed_yaml_cache[self._device_id] = yaml_device

        ac = yaml_device.get(CONFIG_DEVICE, {}) if yaml_device else {}

        nodes = ac.get(CONFIG_DEVICE_OPERATIONS, {})
        for op_key in nodes.keys():

            op = create_property(op_key, nodes[op_key], self._connection, self, self._state_getter)
            if op is not None:
                self._operations[op.id] = op
                # --- FIX: Populate _operations_list ---
                if op not in self._operations_list:
                    self._operations_list.append(op)
                # --- END FIX ---
                self._service_schema_map[vol.Optional(op.id)] = op.config_validation_type

        nodes = ac.get(CONFIG_DEVICE_SWITCHES, {})
        for op_key in nodes.keys():
            # Switches are just operations with type='switch'. We use create_property which checks type.
            op = create_property(op_key, nodes[op_key], self._connection, self, self._state_getter)
            if op is not None:
                self._operations[op.id] = op
                # --- FIX: Populate _operations_list ---
                if op not in self._operations_list:
                    self._operations_list.append(op)
                # --- END FIX ---
                self._service_schema_map[vol.Optional(op.id)] = op.config_validation_type
        # --- END OF MODIFICATION ---

        nodes = ac.get(CONFIG_DEVICE_ATTRIBUTES, {})
        for key in nodes.keys():
            prop = create_property(key, nodes[key], self._connection, self, self._state_getter)
            if prop is not None:
                self._properties[prop.id] = prop
                # --- START OF MODIFICATION ---
                # Add support for static 'unit_of_measurement' in attributes, same as in sensors.
                has_setter = hasattr(prop, 'set_unit_of_measurement')
                has_unit_key = 'unit_of_measurement' in nodes[key]
                has_unit_key = 'unit_of_measurement' in nodes[key]

                if has_setter and has_unit_key:
                    unit_value = nodes[key]['unit_of_measurement']
                    prop.set_unit_of_measurement(unit_value)
                # --- END OF MODIFICATION ---
        
        # --- ADD THIS BLOCK TO LOAD SENSORS ---
        node_sensors = ac.get(CONFIG_DEVICE_SENSORS, {})
        _LOGGER.debug("%s Loading %d sensors", self.log_prefix, len(node_sensors))
        for name in node_sensors.keys():
            prop = create_property(
                name,
                node_sensors[name],
                self._connection,
                self,
                self._state_getter,
            )
            if prop:
                self._sensors[name] = prop
                self._sensors_list.append(name)
        # --- END OF ADDITION ---
        
        # --- START OF MODIFICATION: Apply temperature unit from config/options ---
        # Retrieve the Native temperature units from the config entry options (primary) or data (fallback)
        # For the display unit, we use Home Assistant's global configured temperature unit
        configured_unit = self.hass.config.units.temperature_unit if self.hass else DEFAULT_CONF_TEMP_UNIT
        native_current_unit = DEFAULT_CONF_TEMP_UNIT
        native_target_unit = DEFAULT_CONF_TEMP_UNIT

        entry_id = self._config.get("entry_id")
        if self.hass and entry_id:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry:
                native_current_unit = entry.options.get(CONF_TEMP_NATIVE_CURRENT, entry.data.get(CONF_TEMP_NATIVE_CURRENT, configured_unit))
                native_target_unit = entry.options.get(CONF_TEMP_NATIVE_TARGET, entry.data.get(CONF_TEMP_NATIVE_TARGET, configured_unit))
                _LOGGER.debug("%s [Init] Configured temperature units - Display (HA Global): %s, Native Current: %s, Native Target: %s", 
                              self.log_prefix, configured_unit, native_current_unit, native_target_unit)
        
        # Helper function to apply unit
        def apply_unit(prop):
            if not prop: return
            # Check if it's a temperature property or has device_class "temperature"
            is_temp = False
            if hasattr(prop, 'match_type') and prop.match_type("temperature"):
                is_temp = True
            elif prop.device_class == "temperature":
                is_temp = True
            
            if is_temp:
                if hasattr(prop, 'set_hass_unit') and hasattr(prop, 'set_device_unit'):
                    _LOGGER.debug("%s Applying dual units to property '%s'. Display: %s", self.log_prefix, prop.id, configured_unit)
                    prop.set_hass_unit(configured_unit)
                    if prop.id == ATTR_TEMPERATURE:
                        prop.set_device_unit(native_target_unit)
                    else:
                        prop.set_device_unit(native_current_unit)
                elif hasattr(prop, 'set_unit_of_measurement'):
                    _LOGGER.debug("%s Applying configured unit '%s' to property '%s'", self.log_prefix, configured_unit, prop.id)
                    prop.set_unit_of_measurement(configured_unit)

        # Iterate over all operations
        for op in self._operations.values():
            apply_unit(op)
            
        # Iterate over all attributes (properties)
        for prop in self._properties.values():
            apply_unit(prop)
            
        # Iterate over all sensors
        for sensor in self._sensors.values():
            apply_unit(sensor)
        # --- END OF MODIFICATION ---

        self._operations_list = list(self._operations.keys())
        self._properties_list = list(self._properties.keys())
        self._is_fully_initialized = True
        _LOGGER.debug("%s Controller is now fully initialized.", self.log_prefix)

    async def initialize(self) -> bool:
        """
        Performs the initial loading of the YAML configuration file and sets up the base connection.
        """
        file = self._yaml
        if file is not None and file.find("\\") == -1 and file.find("/") == -1:
            file = os.path.join(os.path.dirname(__file__), file)
        _LOGGER.debug("%s Loading configuration file: %s", self.log_prefix, file)

        if file is None:
            _LOGGER.error("%s No configuration file specified. Aborting initialization.", self.log_prefix)
            return False

        # --- START: Improved YAML caching logic ---
        if file in _YAML_FILE_CACHE:
            _LOGGER.debug("%s [Cache] Using cached YAML file content for: %s", self.log_prefix, file)
            self._raw_yaml_config = _YAML_FILE_CACHE[file]
        else:
            try:
                async with aiofiles.open(file, "r", encoding="utf-8") as stream:
                    self._raw_yaml_config = await stream.read()
                    _YAML_FILE_CACHE[file] = self._raw_yaml_config
                    _LOGGER.debug("%s [Cache] YAML file loaded and cached: %s", self.log_prefix, file)
            except Exception as exc:
                _LOGGER.error("%s Error loading YAML configuration %s: %s", self.log_prefix, file, exc, exc_info=True)
                return False
        # --- END: Improved YAML caching logic ---

        # --- START OF FIX: Ensure raw_yaml_config is not None before proceeding ---
        if not self._raw_yaml_config:
            _LOGGER.error("%s YAML configuration is empty or could not be read.", self.log_prefix)
            return False
        # --- END OF FIX ---
        # The initial parsing uses the current device_id (which can be None) as the cache key.
        partial_render_str = stream_wrapper(self._raw_yaml_config, self._token, self._ip_address, self._device_id)
        
        def _parse_yaml(data_str):
            return yaml.safe_load(data_str)
            
        if getattr(self, "hass", None):
            yaml_device = await self.hass.async_add_executor_job(_parse_yaml, partial_render_str)
        else:
            yaml_device = yaml.safe_load(partial_render_str)
            
        self._parsed_yaml_cache[self._device_id] = yaml_device

        if CONFIG_DEVICE not in yaml_device:
            _LOGGER.error("%s Configuration file '%s' is missing the 'device' root key", self.log_prefix, file)
            return False

        ac = yaml_device.get(CONFIG_DEVICE, {}) if yaml_device else {}
        
        # --- START OF MODIFICATION (Milestone 4) ---
        # Start with the connection node from YAML as a base.
        connection_node = ac.get(CONFIG_DEVICE_CONNECTION, {}).copy()
        device_type = self._config.get(CONF_DEVICE_TYPE)
        
        # --- START OF FIX: Determine connection engine BEFORE creating the connection object ---
        if device_type == DEVICE_TYPE_SAMSUNG_2878:
            _LOGGER.info("%s Using 'samsung_2878' connection engine", self.log_prefix)
            connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_2878" # Hard-coded for this device type
        elif device_type in DEVICE_TYPE_AIOHTTP_SUPPORTED:
            # Read the selected connection method from the config entry's options.
            conn_method = self._config.get(CONF_CONN_METHOD, CONN_METHOD_REQUESTS) # Default
            
            # --- START OF FIX: Retrieve entry using entry_id ---
            entry_id = self._config.get("entry_id")
            if self.hass and entry_id:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry:
                     _LOGGER.debug("%s [Init] Retrieved ConfigEntry. Options: %s", self.log_prefix, entry.options)
                     if entry.options:
                        conn_method = entry.options.get(CONF_CONN_METHOD, conn_method)
            # --- END OF FIX ---
            if conn_method == CONN_METHOD_AIOHTTP:
                _LOGGER.info("%s Using 'Modern (aiohttp)' connection engine (from options)", self.log_prefix)
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_8888_aiohttp"
            elif conn_method == CONN_METHOD_RAW:
                _LOGGER.info("%s Using 'Robust (raw socket)' connection engine (from options)", self.log_prefix)
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_8888_raw"
            else:
                _LOGGER.info("%s Using 'Legacy (requests)' connection engine (from options)", self.log_prefix)
                # For 'requests', we use the connection type defined in the base YAML (e.g., 'request' or 'tls_auto')
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = ac.get(CONFIG_DEVICE_CONNECTION, {}).get(CONFIG_DEVICE_CONNECTION_TYPE, "request")
        # --- END OF FIX ---

        # This call will now create the correct connection type based on the logic above
        # --- START OF MODIFICATION (Milestone 3) ---


        # --- START: Logic moved from connection.py ---
        key = self.unique_id
        if not key:
            _LOGGER.error("%s Cannot create a unique connection without a unique_id", self.log_prefix)
            return False

        _LOGGER.debug("%s Creating new connection object for %s", self.log_prefix, key)
        conn_type_str = connection_node.get(CONFIG_DEVICE_CONNECTION_TYPE)
        
        # Instantiate connection directly
        # Connection classes are already registered in CLIMATE_IP_CONNECTIONS via __init__.py imports

        self._connection = None

        for conn_class in CLIMATE_IP_CONNECTIONS:
            if conn_class.match_type(conn_type_str):
                _LOGGER.debug("%s Found matching connection class '%s' for type '%s'", self.log_prefix, conn_class.__name__, conn_type_str)
                if conn_class.__name__ == "ConnectionAiohttp8888":
                    # Merge global config with YAML connection node to ensure insecure_ssl and others are passed
                    merged_config = {**self._config, **connection_node}
                    self._connection = conn_class(merged_config, _LOGGER, self.hass, self._session, self._ip_address)
                elif conn_class.__name__ == "ConnectionRaw8888":
                        self._connection = conn_class(self._config, _LOGGER, self.hass, self._session, self._ip_address)
                else:
                    self._connection = conn_class(self._config, _LOGGER)
                
                if self._connection.load_from_yaml(connection_node, None):
                    # Connection created and loaded successfully
                    break
        
        if not self._connection:
                _LOGGER.error("%s No matching connection class found for type '%s'", self.log_prefix, conn_type_str)
        # --- END: Logic moved from connection.py ---

        if self._connection is None:
            _LOGGER.error("%s Could not create connection object", self.log_prefix)
            return False
        
        # --- START OF MODIFICATION: Add logging ---
        _LOGGER.debug("%s Connection object created successfully. Type: %s", self.log_prefix, type(self._connection).__name__)
        # --- END OF MODIFICATION ---

        self._state_getter = create_status_getter(
            "state", ac.get(CONFIG_DEVICE_STATUS, {}), self._connection, self
        )
        if self._state_getter is None:
            _LOGGER.error("%s Missing 'status' configuration node in '%s'", self.log_prefix, file)
            return False
        
        self._name = ac.get(ATTR_NAME, CONST_CONTROLLER_TYPE)
        
        poll_config = str(ac.get(CONFIG_DEVICE_POLL, "")).lower()
        if poll_config == "true":
            self._poll = True
        elif poll_config == "false":
            self._poll = False
        else:
            self._poll = None # Let the coordinator decide
        
        return True

