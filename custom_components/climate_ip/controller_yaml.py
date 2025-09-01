import aiofiles
import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

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
    Navega por un diccionario anidado utilizando una lista de claves.
    Devuelve el valor encontrado o None si la ruta no existe.
    """
    if not data or not path:
        return None
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def StreamWrapper(data, token, ip_address, device_id):
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
        self._name = CONST_CONTROLLER_TYPE
        self._attributes = {"controller": self.id}
        self._state_getter = None
        self._debug = config.get("debug", False)
        self._temp_unit = UnitOfTemperature.CELSIUS
        self._service_schema_map = {vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids}
        self._last_device_state = None
        self._poll = None
        
        self._raw_yaml_config = None
        self._is_fully_initialized = False

        self._last_state_fetch_time = 0
        self._cached_device_state = None
        # --- CORRECCIÓN: Se vuelve a añadir el atributo que faltaba ---
        self.discovered_devices = None

    @property
    def unique_id(self) -> Optional[str]:
        return self._unique_id

    @property
    def device_id(self) -> Optional[str]:
        return self._device_id

    async def _finish_initialization(self):
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
            op = create_property(op_key, nodes[op_key], self._connection, self)
            if op is not None:
                self._operations[op.id] = op
                self._service_schema_map[vol.Optional(op.id)] = op.config_validation_type

        nodes = ac.get(CONFIG_DEVICE_ATTRIBUTES, {})
        for key in nodes.keys():
            prop = create_property(key, nodes[key], self._connection, self)
            if prop is not None:
                self._properties[prop.id] = prop
        
        self._operations_list = list(self._operations.keys())
        self._properties_list = list(self._properties.keys())
        self._is_fully_initialized = True
        _LOGGER.debug("%s Controller is now fully initialized.", self.log_prefix)


    async def initialize(self):
        file = self._yaml
        if file is not None and file.find("\\") == -1 and file.find("/") == -1:
            file = os.path.join(os.path.dirname(__file__), file)
        _LOGGER.debug("%s Loading configuration file: %s", self.log_prefix, file)

        if file is None:
            _LOGGER.error("%s No configuration file specified. Aborting initialization.", self.log_prefix)
            return False

        try:
            async with aiofiles.open(file, "r") as stream:
                self._raw_yaml_config = await stream.read()
                
                partial_render_str = StreamWrapper(
                    self._raw_yaml_config, self._token, self._ip_address, None
                )
                yaml_device = yaml.safe_load(partial_render_str)

        except Exception as exc:
            _LOGGER.error("%s Error loading YAML configuration %s: %s", self.log_prefix, file, exc)
            return False

        if CONFIG_DEVICE not in yaml_device:
            _LOGGER.error("%s Configuration file '%s' is missing the 'device' root key.", self.log_prefix, file)
            return False

        ac = yaml_device.get(CONFIG_DEVICE, {})
        self._poll = ac.get(CONFIG_DEVICE_POLL, None)
        
        connection_node = ac.get(CONFIG_DEVICE_CONNECTION, {})
        self._connection = await create_connection(connection_node, self._config, _LOGGER)

        if self._connection is None:
            _LOGGER.error("%s Cannot create connection object!", self.log_prefix)
            return False

        self._state_getter = create_status_getter(
            "state", ac.get(CONFIG_DEVICE_STATUS, {}), self._connection, self
        )
        if self._state_getter is None:
            _LOGGER.error("%s Missing 'status' configuration node in '%s'.", self.log_prefix, file)
            return False
        
        self._name = ac.get(ATTR_NAME, CONST_CONTROLLER_TYPE)
        
        return True

    async def async_get_status(self) -> Optional[Dict[str, Any]]:
        now = time.time()
        if self._cached_device_state and (now - self._last_state_fetch_time < 1):
            _LOGGER.debug("%s Returning cached device state to de-duplicate poll.", self.log_prefix)
            return self._cached_device_state.copy()

        _LOGGER.debug("%s No fresh cache, polling device for state.", self.log_prefix)
        device_state = await self.async_update_state()
        
        if device_state:
            self._cached_device_state = device_state
            self._last_state_fetch_time = now

        return device_state.copy() if device_state else None

    @staticmethod
    def match_type(type):
        return str(type).lower() == CONST_CONTROLLER_TYPE

    @property
    def name(self):
        return self._name

    @property
    def debug(self):
        return self._debug

    async def async_update_properties_from_state(self, full_device_state):
        """
        Selects the correct device object from the full state and updates all properties.
        """
        if not full_device_state or not self._is_fully_initialized:
            return

        device_to_process = full_device_state
        device_type = self._config.get(CONF_DEVICE_TYPE)

        if device_type in [DEVICE_TYPE_MIM_H03, DEVICE_TYPE_SAMSUNG_8888]:
            yaml_conf = yaml.safe_load(self._raw_yaml_config)
            id_map = yaml_conf.get(CONFIG_DEVICE, {}).get("identifiers")
            if id_map:
                devices_list = _get_value_by_path(full_device_state, id_map.get("path_to_devices", []))
                if devices_list:
                    found_device = None
                    if self._device_id:
                        found_device = next((d for d in devices_list if d and str(_get_value_by_path(d, id_map.get("id", []))) == str(self._device_id)), None)
                    
                    if not found_device and devices_list:
                        found_device = devices_list[0]

                    if found_device:
                        _LOGGER.debug("%s Passing specific device object to templates for ID %s.", self.log_prefix, self._device_id)
                        device_to_process = found_device
                    else:
                        _LOGGER.warning("%s Could not find device with ID %s in update. Templates will likely fail.", self.log_prefix, self._device_id)
                else:
                     _LOGGER.warning("%s Could not find device list in update. Templates will likely fail.", self.log_prefix)
            else:
                _LOGGER.warning("%s Cannot select specific device state for %s without 'identifiers' map. Using full state.", self.log_prefix, device_type)
        
        all_properties = list(self._operations.values()) + list(self._properties.values())
        update_tasks = [
            prop.async_update_state(device_to_process, self._debug) for prop in all_properties
        ]

        if update_tasks:
            await asyncio.gather(*update_tasks)
        
        for prop in all_properties:
            self._attributes.update(prop.state_attributes)

    async def async_update_state(self):
        """
        Fetches the full state from the device, runs discovery once, and then
        calls async_update_properties_from_state to process the data.
        """
        if not self._state_getter:
            raise IOError("State getter is not initialized.")

        self._attributes = {ATTR_NAME: self.name}
        
        try:
            full_device_state = await self._state_getter.async_update_state(
                self._last_device_state, self._debug
            )
        except RequestException as e:
            raise CannotConnect(f"Error communicating with device: {e}") from e

        if full_device_state is None:
            raise CannotConnect("Failed to get device state: No data received.")

        try:
            if not self._is_fully_initialized:
                device_type = self._config.get(CONF_DEVICE_TYPE)
                if device_type != DEVICE_TYPE_SAMSUNG_2878:
                    yaml_conf = yaml.safe_load(self._raw_yaml_config)
                    id_map = yaml_conf.get(CONFIG_DEVICE, {}).get("identifiers")
                    if id_map:
                        # --- CORRECCIÓN: Se guarda la lista de dispositivos para el config_flow ---
                        self.discovered_devices = _get_value_by_path(full_device_state, id_map.get("path_to_devices", []))
                        if self.discovered_devices:
                            device_to_discover = None
                            if device_type == DEVICE_TYPE_MIM_H03:
                                if self._device_id:
                                    device_to_discover = next((d for d in self.discovered_devices if d and str(d.get('id')) == str(self._device_id)), None)
                                elif len(self.discovered_devices) > 1 and self.discovered_devices[1]:
                                    device_to_discover = self.discovered_devices[1]
                                else:
                                    device_to_discover = self.discovered_devices[0] if self.discovered_devices else None
                            else:
                                device_to_discover = self.discovered_devices[0] if self.discovered_devices else None
                            
                            if device_to_discover:
                                discovered_id = _get_value_by_path(device_to_discover, id_map.get("id", []))
                                discovered_uuid = _get_value_by_path(device_to_discover, id_map.get("uuid", []))
                                if discovered_id is not None: self._device_id = str(discovered_id)
                                if discovered_uuid: self._unique_id = str(discovered_uuid)
                                _LOGGER.info("%s Discovered: id=%s, uuid=%s", self.log_prefix, self._device_id, self._unique_id)
                
                await self._finish_initialization()
        except Exception as e:
            _LOGGER.error("%s Error during initial device discovery: %s", self.log_prefix, e, exc_info=True)

        await self.async_update_properties_from_state(full_device_state)
        
        self._last_device_state = full_device_state
        return self._last_device_state

    async def async_set_property(self, property_name, new_value, device_id: str = None):
        """
        Asynchronously sets a property on the device.
        """
        if not self._is_fully_initialized:
            _LOGGER.error("%s Cannot set property '%s': controller not fully initialized.", self.log_prefix, property_name)
            return False

        op = self._operations.get(property_name)
        if op:
            try:
                return await op.async_set_value(new_value, self._device_id)
            except RequestException as e:
                raise CannotConnect(f"Failed to set property '{property_name}': {e}") from e
            
        _LOGGER.error("%s Failed to set property '%s': property not found.", self.log_prefix, property_name)
        return False

    def get_property(self, property_name):
        value = None
        if property_name in self._operations:
            value = self._operations[property_name].value
        elif property_name in self._properties:
            value = self._properties[property_name].value
        else:
            value = self._attributes.get(property_name)

        if value == STATE_UNKNOWN:
            return None
        
        return value

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


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_CONFIG_FILE): cv.string,
        vol.Optional(CONF_IP_ADDRESS): cv.string,
        vol.Optional(CONF_TOKEN): cv.string,
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_TEMPERATURE_UNIT, default=UnitOfTemperature.CELSIUS): cv.string,
    }
)
