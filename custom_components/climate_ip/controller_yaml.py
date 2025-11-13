import aiofiles
import asyncio
from homeassistant.components.climate import ClimateEntityFeature, HVACMode, ATTR_HVAC_MODE
import re
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.entity_component
import voluptuous as vol
import yaml
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    ATTR_TEMPERATURE,
    CONF_IP_ADDRESS,
    CONF_TEMPERATURE_UNIT,
    CONF_TOKEN,
    STATE_ON,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from requests.exceptions import RequestException
from homeassistant.helpers.update_coordinator import UpdateFailed

from .connection import create_connection
from .controller import ATTR_POWER, ClimateController, register_controller
from .properties import create_property, create_status_getter
from .state import ClimateIPDeviceState
# FIX: Import the missing constant
from .const import CONF_DEVICE_TYPE, DEVICE_TYPE_MIM_H03, DEVICE_TYPE_SAMSUNG_8888, DEVICE_TYPE_SAMSUNG_2878
from .exceptions import CannotConnect
from .helpers import find_key_in_data
from .yaml_const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONFIG_DEVICE,
    CONFIG_DEVICE_ATTRIBUTES,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_NAME,
    CONFIG_DEVICE_OPERATIONS,
    CONFIG_DEVICE_SENSORS,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_STATUS,
    CONFIG_DEVICE_UNIQUE_ID,
    CONFIG_DEVICE_VALIDATE_PROPS,
)

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = "yaml"
CONST_MAX_GET_STATUS_RETRIES = 4

def _get_value_by_path(data: dict, path: list) -> Any:
    """
    Navigate through a nested dictionary using a list of keys.
    Returns the found value or None if the path does not exist.
    """
    if not data or not path:
        return None
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def StreamWrapper(data: str, token: str, ip_address: str, device_id: str) -> str:
    """
    Replaces placeholder values in a string.
    """
    if token is not None:
        data = data.replace("__CLIMATE_IP_TOKEN__", token)
    if ip_address is not None:
        data = data.replace("__CLIMATE_IP_HOST__", ip_address)
    if device_id is not None:
        data = data.replace("__DEVICE_ID__", str(device_id))
    return data


@register_controller
class YamlController(ClimateController):
    """
    YAML-based controller, refactored to support asynchronous operations.
    """

    def __init__(self, config, logger):
        super(YamlController, self).__init__(config, logger)
        
        self._config = config
        self._yaml = config.get(CONF_CONFIG_FILE)
        self._ip_address = config.get(CONF_IP_ADDRESS, None)
        self._device_id = config.get(CONF_DEVICE_ID, None) 
        self._token = config.get(CONF_TOKEN, None)
        self._unique_id = config.get("unique_id") or config.get(CONF_MAC) or self._ip_address
        self._id_discovered = self._device_id is not None

        self._operations = {}
        self._operations_list = []
        self._properties = {}
        self._properties_list = []

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
        
        self._raw_yaml_config = None
        self.coordinator = None # Reference to the coordinator
        self._is_fully_initialized = False
        # Flag to signal that the fan modes list has changed and a UI flicker is needed.
        self._fan_modes_list_changed_pending_flicker: bool = False

        self._last_state_fetch_time = 0
        self._cached_device_state = None
        self.discovered_devices = None
        self._poll = None

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

    async def _finish_initialization(self):
        """
        Completes the controller's initialization after the device_id has been discovered.
        This involves loading the final operational and attribute properties from the YAML.
        """
        if self._is_fully_initialized or not self._raw_yaml_config:
            return

        _LOGGER.debug("%s Finishing initialization with discovered device_id: %s", self.log_prefix, self._device_id)
        
        final_yaml_str = StreamWrapper(
            self._raw_yaml_config, self._token, self._ip_address, self._device_id
        )
        yaml_device = yaml.safe_load(final_yaml_str)
        ac = yaml_device.get(CONFIG_DEVICE, {})

        nodes = ac.get(CONFIG_DEVICE_OPERATIONS, {})
        for op_key in nodes.keys():
            op = create_property(op_key, nodes[op_key], self._connection, self, self._state_getter)
            if op is not None:
                self._operations[op.id] = op
                self._service_schema_map[vol.Optional(op.id)] = op.config_validation_type

        nodes = ac.get(CONFIG_DEVICE_ATTRIBUTES, {})
        for key in nodes.keys():
            prop = create_property(key, nodes[key], self._connection, self, self._state_getter)
            if prop is not None:
                self._properties[prop.id] = prop
        
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
        
        self._operations_list = list(self._operations.keys())
        self._properties_list = list(self._properties.keys())
        self._is_fully_initialized = True
        _LOGGER.debug("%s Controller is now fully initialized.", self.log_prefix)


    async def initialize(self):
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

        try:
            async with aiofiles.open(file, "r", encoding="utf-8") as stream:
                self._raw_yaml_config = await stream.read()
                
                partial_render_str = StreamWrapper(
                    self._raw_yaml_config, self._token, self._ip_address, self._device_id
                )
                yaml_device = yaml.safe_load(partial_render_str)

        except Exception as exc:
            _LOGGER.error("%s Error loading YAML configuration %s: %s", self.log_prefix, file, exc)
            return False

        if CONFIG_DEVICE not in yaml_device:
            _LOGGER.error("%s Configuration file '%s' is missing the 'device' root key", self.log_prefix, file)
            return False

        ac = yaml_device.get(CONFIG_DEVICE, {})
        
        connection_node = ac.get(CONFIG_DEVICE_CONNECTION, {})
        self._connection = await create_connection(connection_node, self._config, _LOGGER)

        if self._connection is None:
            _LOGGER.error("%s Cannot create connection object", self.log_prefix)
            return False

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

    # async def async_get_status(self) -> Optional[Dict[str, Any]]:
    #     now = time.time()
    #     if self._cached_device_state and (now - self._last_state_fetch_time < 1):
    #         _LOGGER.debug("%s Returning cached device state to de-duplicate poll.", self.log_prefix)
    #         return self._cached_device_state.copy()

    #     _LOGGER.debug("%s No fresh cache, polling device for state.", self.log_prefix)
    #     device_state = await self.async_update_state()
        
    #     if device_state:
    #         self._cached_device_state = device_state
    #         self._last_state_fetch_time = now

    #     return device_state.copy() if device_state else None

    async def async_get_status(self) -> Optional[Dict[str, Any]]:
        """
        Fetches the device state. The caching logic has been removed
        to prevent conflicts with the post-command async_refresh().
        """
        _LOGGER.debug("%s Polling device for state.", self.log_prefix)

        # Directly call async_update_state to ensure the most recent state is always fetched when requested.
        device_state = await self.async_update_state()
        return device_state.copy() if device_state else None

    async def async_update_state(self) -> Optional[Dict[str, Any]]: # This is the main polling function
        """
        Fetches the full device state from the physical device using the state_getter.
        This method also handles the one-time discovery of sub-devices.
        """
        try:
            full_device_state = await self._state_getter.async_update_state(None, self._debug)
        except RequestException as e:
            raise UpdateFailed(f"Error communicating with device: {e}") from e

        if full_device_state is None:
            raise UpdateFailed("Failed to get device state: No data received")

        # --- One-time device discovery and initialization logic ---
        if not self._is_fully_initialized:
            try:
                device_type = self._config.get(CONF_DEVICE_TYPE)
                yaml_conf = yaml.safe_load(self._raw_yaml_config)
                id_map = yaml_conf.get(CONFIG_DEVICE, {}).get("identifiers")

                if id_map:
                    _LOGGER.debug("%s 'identifiers' map found, running discovery", self.log_prefix)
                    self.discovered_devices = _get_value_by_path(full_device_state, id_map.get("path_to_devices", []))
                    
                    if self.discovered_devices:
                        device_to_discover = None
                        
                        if device_type == DEVICE_TYPE_MIM_H03: # Special logic for MIM-H03
                            # For MIM-H03, find the coordinator unit (the one without a "Mode")
                            device_to_discover = next((d for d in self.discovered_devices if d and "Mode" not in d), None)
                            if not device_to_discover and self.discovered_devices:
                                # Fallback for older configs or different structures
                                device_to_discover = self.discovered_devices[0]
                        else: # Default for SAMSUNG_8888 and others
                            device_to_discover = self.discovered_devices[0] if self.discovered_devices else None
                        
                        if device_to_discover:
                            discovered_id = _get_value_by_path(device_to_discover, id_map.get("id", []))
                            if discovered_id is not None:
                                self._device_id = str(discovered_id)
                            _LOGGER.info("%s Discovered device with id=%s", self.log_prefix, self._device_id)

                # Now that _device_id is potentially assigned, finish initialization
                await self._finish_initialization()

            except Exception as e:
                _LOGGER.error("%s Error during initial device discovery: %s", self.log_prefix, e, exc_info=True)
                # Do not return here, allow property update to proceed with what we have

        await self.async_update_properties_from_state(full_device_state)
        return self._state_getter.value

    @staticmethod
    def match_type(type):
        return str(type).lower() == CONST_CONTROLLER_TYPE

    @property
    def name(self):
        return self._name

    @property
    def debug(self):
        return self._debug
    
    @property
    def poll(self) -> Optional[bool]:
        """Return the polling state from the YAML configuration."""
        _LOGGER.debug("%s Poll property accessed, returning: %s", self.log_prefix, self._poll)
        return self._poll

    async def async_update_properties_from_state(self, full_device_state: Optional[Dict[str, Any]] = None):
        """
        Updates all properties from a given device state dictionary.
        If no state is provided, it reconstructs it from the current Home Assistant state.
        """
        if not self._is_fully_initialized:
            return

        # FIX: Check if coordinator exists before accessing its data.
        current_hass_state = self.coordinator.data if self.coordinator else None
        if not current_hass_state:
            _LOGGER.debug("%s Coordinator data is not available (normal during setup or first poll)", self.log_prefix)

        if full_device_state is None:
            _LOGGER.debug("%s [UpdateProps] No state provided, rebuilding from HASS for merge", self.log_prefix)
            if not current_hass_state:
                _LOGGER.error("%s [UpdateProps] Cannot rebuild state from HASS: coordinator data is null. Aborting update", self.log_prefix)
                return # ABORT
            full_device_state = await self._build_device_state_from_hass(current_hass_state)
        else:
            _LOGGER.debug("%s [UpdateProps] Using provided state (poll/prediction)", self.log_prefix)
        
        if full_device_state is None:
            _LOGGER.error("%s [UpdateProps] full_device_state is None, cannot update properties. Aborting", self.log_prefix)
            return

        device_to_process = full_device_state
        
        # --- START: Sub-device selection logic ---
        try:
            yaml_conf = yaml.safe_load(self._raw_yaml_config)
            id_map = yaml_conf.get(CONFIG_DEVICE, {}).get("identifiers")
            
            if id_map:
                _LOGGER.debug("%s 'identifiers' map found. Searching in path: %s", self.log_prefix, id_map.get("path_to_devices", []))
                devices_list = _get_value_by_path(full_device_state, id_map.get("path_to_devices", []))
                
                if devices_list:
                    _LOGGER.debug("%s Found %d devices in state. Selecting correct one.", self.log_prefix, len(devices_list))
                    
                    # Simplified logic: Take the first valid device
                    found_device = devices_list[0] if devices_list[0] else None
                    # TODO: This should be improved to select the device based on self._device_id
                    if found_device:
                        _LOGGER.debug("%s Success. 'device_to_process' is now the sub-device", self.log_prefix)
                        device_to_process = found_device
                    else:
                        _LOGGER.warning("%s 'devices_list' exists but the first element is empty or null", self.log_prefix)
                else:
                    _LOGGER.warning("%s 'identifiers' exists but the path '%s' did not return a list", self.log_prefix, id_map.get("path_to_devices", []))
            else:
                _LOGGER.debug("%s No 'identifiers' map. Using full state (normal for 2878)", self.log_prefix)

        except Exception as e:
            _LOGGER.error("%s Error during sub-device selection: %s. Using full state.", self.log_prefix, e, exc_info=True)
            device_to_process = full_device_state
        # --- END: Sub-device selection logic ---

        corrections = {}
        all_properties = list(self._operations.values()) + list(self._properties.values()) + list(self._sensors.values())
        _LOGGER.debug("%s Updating %d properties using device_state: %s", self.log_prefix, len(all_properties), str(device_to_process))
        
        for prop in all_properties:
            try:
                await prop.async_update_state(device_to_process, self._debug)
            except Exception as e:
                _LOGGER.error("%s FAILED to update property '%s'. Error: %s", self.log_prefix, prop.name, e, exc_info=True)
        
        for prop in all_properties:
            if hasattr(prop, 'set_device_state_for_values'):
                prop.set_device_state_for_values(device_to_process)

        _LOGGER.debug("%s Checking for post-update state inconsistencies", self.log_prefix)
        for op_name, op in self._operations.items():
            if hasattr(op, 'values') and op.value is not None and op.value != STATE_UNKNOWN:
                if op.value not in op.values:
                    new_value = op.values[0] if op.values else STATE_UNKNOWN
                    _LOGGER.info(
                        "%s State auto-correction for '%s'. Value '%s' is no longer valid in %s. Setting to '%s'. Triggering UI flicker",
                        self.log_prefix, op.name, op.value, op.values, new_value,
                    )
                    op._value = new_value
                    corrections[op.id] = new_value

                    # If this auto-correction is for a property with a feature flag (like fan_mode),
                    # ensure the pending flicker flag is set so the coordinator can handle it on the next update.
                    if hasattr(op, '_feature_flag') and op._feature_flag == ClimateEntityFeature.FAN_MODE:
                        self._fan_modes_list_changed_pending_flicker = True

        self._rebuild_attributes()
        return corrections
    def _rebuild_attributes(self):
        """Rebuilds the _attributes dictionary from all properties."""
        self._attributes = {ATTR_NAME: self.name}
        all_properties = list(self._operations.values()) + list(self._properties.values())
        for prop in all_properties:
            self._attributes.update(prop.state_attributes)

    async def _build_device_state_from_hass(self, hass_state: ClimateIPDeviceState) -> Optional[Dict[str, Any]]:
        """
        Converts a Home Assistant state object (ClimateIPDeviceState) back into a
        raw device state dictionary, similar to what self._state_getter.value would contain.
        This is essentially the inverse of async_update_properties_from_state.

        *** This function reads from the provided hass_state. ***
        """
        if not self._is_fully_initialized:
            _LOGGER.warning("%s Cannot convert HASS state to device state: controller not fully initialized", self.log_prefix)
            return None

        last_real_state = self._state_getter.value
        if not last_real_state:
            _LOGGER.warning("%s [HASS->DEV] No previous real device state available to use as a template", self.log_prefix)
            return {}

        reconstructed_state = json.loads(json.dumps(last_real_state))
        _LOGGER.debug("%s [HASS->DEV] Rebuilding from real state template", self.log_prefix)

        all_props = list(self._operations.values()) + list(self._properties.values())

        for op in all_props:
            hass_value = getattr(hass_state, op.id, None)
            if hass_value is not None:
                op._value = hass_value
                
                device_value = op.convert_hass_to_dev(hass_value)
                
                template_str = ""
                if op.status_template and hasattr(op.status_template, 'template'):
                    template_str = op.status_template.template
                
                match = re.search(r"device_state[\[\.](['\"]?)([A-Z0-9_]+)\1", template_str)
                if match:
                    device_key = match.group(2)
                    if device_key in reconstructed_state:
                        reconstructed_state[device_key] = device_value
        
        return reconstructed_state

    async def _build_device_state_from_props(self) -> Optional[Dict[str, Any]]:
        """
        Builds a raw device state dictionary (template) using the current
        *internal* values of the properties (operations + attributes).

        *** This function reads from self._operations[x].value and self._properties[x].value ***
        """
        if not self._is_fully_initialized:
            _LOGGER.warning("%s Cannot build device state from properties: controller not fully initialized", self.log_prefix)
            return None

        last_real_state = self._state_getter.value
        if not last_real_state:
            _LOGGER.warning("%s [PROP->DEV] No previous real device state available to use as a template", self.log_prefix)
            return {}

        reconstructed_state = json.loads(json.dumps(last_real_state))
        _LOGGER.debug("%s [PROP->DEV] Rebuilding from real state template", self.log_prefix)

        all_props = list(self._operations.values()) + list(self._properties.values())

        for op in all_props:
            prop_value = op.value
            
            if prop_value is not None:
                device_value = op.convert_hass_to_dev(prop_value)
                pass
        
        return reconstructed_state

    async def async_merge_device_state(self, new_data: Dict[str, Any], is_response: bool, is_update: bool):
        """
        Combines a partial state update (from a push or a response) with the current state,
        rebuilding the full state from Home Assistant to ensure consistency.
        """
        if not new_data:
            _LOGGER.debug("%s async_merge_device_state called with no new data", self.log_prefix)
            return

        _LOGGER.debug("%s Merging partial update: %s", self.log_prefix, new_data)

        current_hass_state = self.coordinator.data
        if not current_hass_state:
            _LOGGER.warning("%s Cannot merge state, coordinator data is not available", self.log_prefix)
            base_state = self._state_getter.value
        else:
            base_state = await self._build_device_state_from_hass(current_hass_state)
            _LOGGER.debug("%s Base state reconstructed from HASS: %s", self.log_prefix, base_state)     

        if base_state is None:
            _LOGGER.error("%s Could not get a base state for merging. Aborting.", self.log_prefix)
            return

        base_state.update(new_data)
        _LOGGER.debug("%s Resulting merged state: %s", self.log_prefix, base_state)

        self._state_getter._value = base_state
        await self.async_update_properties_from_state(base_state)

    def _get_device_key_from_template(self, template_obj: Any) -> Optional[str]:
        """
        Extracts the *primary* device state key (e.g., 'AC_FUN_OPMODE') 
        from a Home Assistant Template object.
        """
        if not template_obj:
            return None
        
        template_string = None
        if hasattr(template_obj, 'template'):
            template_string = str(template_obj.template)
        elif hasattr(template_obj, 'source'):
            template_string = str(template_obj.source)
        else:
            template_string = str(template_obj)
        if not template_string:
            _LOGGER.debug("%s [Regex] Could not get template text from object: %s", self.log_prefix, template_obj)
            return None

        match = re.search(r"device_state[\[\.](['\"]?)([A-Za-z0-9_]+)\1", template_string)
        if match:
            return match.group(2)
            
        _LOGGER.warning("%s [Regex] Could not extract 'device_state' key from template: %s", self.log_prefix, template_string)
        return None

    async def async_predict_and_correct_state(self, current_hass_state: ClimateIPDeviceState, property_name: str, new_value: Any) -> (ClimateEntityFeature, Dict[str, Any]):
        """
        Predicts the device state after a change, performs corrections,
        and triggers feature flags if necessary.
        It now uses the current state from Home Assistant (via the coordinator) as the baseline.
        """
        _LOGGER.debug("%s [Predict] Coordinator state '%s' ", self.log_prefix, str(current_hass_state))
        last_real_state = self._state_getter.value

        if not self._is_fully_initialized:
            _LOGGER.info("%s [Predict] Cannot predict state: controller not fully initialized", self.log_prefix)
            return ClimateEntityFeature(0), {}
            
        if not last_real_state:
            _LOGGER.info("%s [Predict] Cannot predict state: last real state is unavailable", self.log_prefix)
            return ClimateEntityFeature(0), {}
        
        corrections = {}

        _LOGGER.debug("%s [Predict] Predicting state for change: %s -> %s", self.log_prefix, property_name, new_value)

        
        original_values = {
            op_name: (op.value.value if isinstance(op.value, HVACMode) else op.value)
            for op_name, op in self._operations.items()
        }

        _LOGGER.debug("%s [Predict] Syncing internal props to current_hass_state", self.log_prefix)
        for op in self._operations.values():
            if hasattr(current_hass_state, op.id):
                op._value = getattr(current_hass_state, op.id)
        for prop in self._properties.values():
            if hasattr(current_hass_state, prop.id):
                prop._value = getattr(current_hass_state, prop.id)


        prop_to_change = self._operations.get(property_name)
        if not prop_to_change:
            _LOGGER.warning("%s [Predict] Property '%s' not found for prediction", self.log_prefix, property_name)
            return ClimateEntityFeature(0), {}
        
        prop_to_change._value = new_value
        _LOGGER.debug("%s [Predict] Applied change to internal property '%s'", self.log_prefix, property_name)

        future_state = await self._build_device_state_from_props()
        if not future_state:
            _LOGGER.error("%s [Predict] Failed to reconstruct future state from internal properties", self.log_prefix)
            return ClimateEntityFeature(0), {}

        try:
            device_value = prop_to_change.convert_hass_to_dev(new_value)
            
            device_key = None
            template_str = ""
            if prop_to_change.status_template and hasattr(prop_to_change.status_template, 'template'):
                template_str = prop_to_change.status_template.template
            
            match = re.search(r"device_state[\[\.](['\"]?)([A-Z0-9_]+)\1", template_str)
            
            if match:
                device_key = match.group(2)
                if device_key in future_state:
                    _LOGGER.debug("%s [Predict] Auto-injecting '%s' into key '%s' (from YAML map)", self.log_prefix, device_value, device_key)
                    future_state[device_key] = device_value
                else:
                    _LOGGER.warning("%s [Predict] Auto-key '%s' found for '%s', but key not in state. Fallback", self.log_prefix, device_key, property_name)
                    device_key = None
            else:
                 _LOGGER.debug("%s [Predict] Auto-key failed for '%s' (template complex?). Using manual logic", self.log_prefix, property_name)

            if device_key is None:
                if property_name == ATTR_TEMPERATURE:
                    _LOGGER.debug("%s [Predict] Manual-injecting temperature: %s", self.log_prefix, new_value)
                    if 'Temperatures' in future_state:
                        future_state['Temperatures'][0]['desired'] = new_value
                    else:
                        _LOGGER.debug("%s [Predict] Manual temp prediction failed, 'Temperatures' key missing", self.log_prefix)
                
                elif property_name == ATTR_HVAC_MODE:
                    if 'AC_FUN_OPMODE' in future_state:
                        _LOGGER.debug("%s [Predict] Manual-injecting hvac_mode: %s into AC_FUN_OPMODE", self.log_prefix, device_value)
                        future_state['AC_FUN_OPMODE'] = device_value
                    else:
                        _LOGGER.debug("%s [Predict] Manual hvac_mode prediction failed, 'AC_FUN_OPMODE' key missing", self.log_prefix)
                
                else:
                    _LOGGER.debug("%s [Predict] Auto-key failed and no manual logic exists for '%s'. Prediction may be inaccurate", self.log_prefix, property_name)

        except Exception as e:
            _LOGGER.error("%s [Predict] Error while writing prediction: %s", self.log_prefix, e)

        _LOGGER.debug("%s [Predict] Updating properties with simulated future state: %s", self.log_prefix, str(future_state)[:200] + "...")
        corrections.update(await self.async_update_properties_from_state(future_state))
        
        return ClimateEntityFeature(0), corrections

    async def async_set_property(self, property_name, new_value, device_id: str = None):
        """
        Asynchronously sets a property on the device.
        """
        if not self._is_fully_initialized:
            _LOGGER.error("%s Cannot set property '%s': controller not fully initialized", self.log_prefix, property_name)
            return False

        op = self._operations.get(property_name)
        if op:
            try:
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

    # --- ADD THIS NEW PROPERTY ---
    @property
    def sensors(self) -> List["DeviceProperty"]:
        """Return a list of all defined sensor property objects."""
        # Return the actual property objects, not just the names
        return [self._sensors[name] for name in self._sensors_list if name in self._sensors]
    # --- END OF ADDITION ---


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_CONFIG_FILE): cv.string,
        vol.Optional(CONF_IP_ADDRESS): cv.string,
        vol.Optional(CONF_TOKEN): cv.string,
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_TEMPERATURE_UNIT, default=UnitOfTemperature.CELSIUS): cv.string,
    }
)