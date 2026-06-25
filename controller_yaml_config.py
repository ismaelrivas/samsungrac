# pylint: disable=import-outside-toplevel,line-too-long,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-return-statements,too-many-statements,unused-import
"""YAML configuration loader for climate_ip controllers."""

import logging
import os
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.util.yaml import load_yaml
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    ATTR_TEMPERATURE,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TOKEN,
)

from .connection import CLIMATE_IP_CONNECTIONS, Connection
from .const import (
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    CONFIG_DEVICE,
    CONFIG_DEVICE_ATTRIBUTES,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_TYPE,
    CONFIG_DEVICE_OPERATIONS,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_SENSORS,
    CONFIG_DEVICE_STATUS,
    CONFIG_DEVICE_SWITCHES,
    CONN_METHOD_AIOHTTP,
    CONN_METHOD_RAW,
    DEFAULT_CONF_TEMP_UNIT,
    DEVICE_TYPE_AIOHTTP_SUPPORTED,
    DEVICE_TYPE_SAMSUNG_2878,
)
from .helpers import stream_wrapper
from .properties import create_property, create_status_getter, TemperatureOperation

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = "yaml"

# Module-level cache for raw YAML file content.
_YAML_FILE_CACHE: dict[str, dict] = {}


def clear_yaml_cache() -> None:
    """Clear the YAML file content cache to allow reloading from disk."""
    if _YAML_FILE_CACHE:
        _LOGGER.info("Clearing YAML file cache to force re-read on reload.")  # pragma: no mutate
        _YAML_FILE_CACHE.clear()


class YamlConfigLoader:
    """Class responsible for loading and parsing the YAML configuration."""

    def __init__(self, controller: Any) -> None:
        """Initialize the loader with a reference to the main controller facade."""
        self.controller = controller

        self.operations: dict[str, Any] = {}
        self.operations_list: list[str] = []
        self.properties: dict[str, Any] = {}
        self.properties_list: list[str] = []
        self.sensors: dict[str, Any] = {}
        self.sensors_list: list[str] = []

        self.service_schema_map: dict[Any, Any] = {vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids}

        self.connection: Connection | None = None
        self.state_getter = None
        self.name = CONST_CONTROLLER_TYPE
        self.poll: bool | None = None
        self.is_fully_initialized = False

        self._parsed_yaml_config: dict | None = None
        self._parsed_yaml_cache: dict[str | None, dict] = {}

    @property
    def parsed_yaml_cache(self) -> dict[str | None, dict]:
        """Return the parsed YAML cache for the current device."""
        return self._parsed_yaml_cache

    async def async_initialize(self) -> bool:
        """Perform initial YAML configuration loading and set up the base connection."""
        file = getattr(self.controller, "_yaml", None)
        if file is not None and file.find("\\") == -1 and file.find("/") == -1:
            file = os.path.join(os.path.dirname(__file__), file)
        _LOGGER.debug("%s Loading configuration file: %s", self.controller.log_prefix, file)  # pragma: no mutate

        if file is None:
            _LOGGER.error(  # pragma: no mutate
                "%s No configuration file specified. Aborting initialization.",  # pragma: no mutate
                self.controller.log_prefix,  # pragma: no mutate
            )  # pragma: no mutate
            return False

        if file in _YAML_FILE_CACHE:
            _LOGGER.debug(  # pragma: no mutate
                "%s [Cache] Using cached YAML file content for: %s",  # pragma: no mutate
                self.controller.log_prefix,  # pragma: no mutate
                file,  # pragma: no mutate
            )  # pragma: no mutate
            self._parsed_yaml_config = _YAML_FILE_CACHE[file]
        else:
            try:
                if hasattr(self.controller, "hass") and self.controller.hass is not None:
                    self._parsed_yaml_config = await self.controller.hass.async_add_executor_job(
                        load_yaml, file
                    )
                else:
                    self._parsed_yaml_config = load_yaml(file)

                _YAML_FILE_CACHE[file] = self._parsed_yaml_config
                _LOGGER.debug(  # pragma: no mutate
                    "%s [Cache] YAML file loaded and cached: %s", self.controller.log_prefix, file  # pragma: no mutate
                )  # pragma: no mutate
            except Exception as exc:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                _LOGGER.error(  # pragma: no mutate
                    "%s Error loading YAML configuration %s: %s",  # pragma: no mutate
                    self.controller.log_prefix,  # pragma: no mutate
                    file,  # pragma: no mutate
                    exc,  # pragma: no mutate
                    exc_info=True,  # pragma: no mutate
                )  # pragma: no mutate
                return False

        if not self._parsed_yaml_config:
            _LOGGER.error(  # pragma: no mutate
                "%s YAML configuration is empty or could not be read.", self.controller.log_prefix  # pragma: no mutate
            )  # pragma: no mutate
            return False

        yaml_device = self._parsed_yaml_config
        self._parsed_yaml_cache[getattr(self.controller, "device_id", "")] = yaml_device

        if CONFIG_DEVICE not in yaml_device:
            _LOGGER.error(  # pragma: no mutate 
                "%s Configuration file '%s' is missing the 'device' root key",  # pragma: no mutate
                self.controller.log_prefix,  # pragma: no mutate
                file,  # pragma: no mutate
            )  # pragma: no mutate
            return False

        ac = yaml_device.get(CONFIG_DEVICE, {}) if yaml_device else {}

        connection_node = ac.get(CONFIG_DEVICE_CONNECTION, {}).copy()
        
        # Saneamiento del acceso a la configuración
        controller_config = getattr(self.controller, "_config", getattr(self.controller, "config", {}))
        device_type = controller_config.get(CONF_DEVICE_TYPE)

        if device_type == DEVICE_TYPE_SAMSUNG_2878:
            _LOGGER.info("%s Using 'samsung_2878' connection engine", self.controller.log_prefix)  # pragma: no mutate
            connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_2878"
        elif device_type in DEVICE_TYPE_AIOHTTP_SUPPORTED:
            conn_method = controller_config.get(CONF_CONN_METHOD, CONN_METHOD_AIOHTTP)

            entry_id = controller_config.get("entry_id")
            if getattr(self.controller, "hass", None) and entry_id:
                entry = self.controller.hass.config_entries.async_get_entry(entry_id)
                if entry:
                    _LOGGER.debug(  # pragma: no mutate
                        "%s [Init] Retrieved ConfigEntry. Options: %s",  # pragma: no mutate
                        self.controller.log_prefix,  # pragma: no mutate
                        entry.options,  # pragma: no mutate
                    )  # pragma: no mutate
                    if entry.options:
                        conn_method = entry.options.get(CONF_CONN_METHOD, conn_method)

            if conn_method == CONN_METHOD_AIOHTTP:
                _LOGGER.info(  # pragma: no mutate
                    "%s Using 'Modern (aiohttp)' connection engine (from options)",  # pragma: no mutate
                    self.controller.log_prefix,  # pragma: no mutate
                )  # pragma: no mutate
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_8888_aiohttp"
            elif conn_method == CONN_METHOD_RAW:
                _LOGGER.info(  # pragma: no mutate
                    "%s Using 'Robust (raw socket)' connection engine (from options)",  # pragma: no mutate
                    self.controller.log_prefix,  # pragma: no mutate
                )  # pragma: no mutate
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_8888_raw"
            else:
                _LOGGER.warning(  # pragma: no mutate
                    "%s [DEPRECATED] Using obsolete 'request' (synchronous) engine. "  # pragma: no mutate
                    "Please reconfigure this device via Integrations UI -> Reconfigure "  # pragma: no mutate
                    "to use Modern (aiohttp) or Robust (raw socket) for better performance and stability.",  # pragma: no mutate
                    self.controller.log_prefix,  # pragma: no mutate
                )  # pragma: no mutate
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = ac.get(
                    CONFIG_DEVICE_CONNECTION, {}
                ).get(CONFIG_DEVICE_CONNECTION_TYPE, "request")

        key = getattr(self.controller, "unique_id", None)
        if not key:
            _LOGGER.error(  # pragma: no mutate
                "%s Cannot create a unique connection without a unique_id",  # pragma: no mutate
                self.controller.log_prefix,  # pragma: no mutate
            )  # pragma: no mutate
            return False

        _LOGGER.debug("%s Creating new connection object for %s", self.controller.log_prefix, key)  # pragma: no mutate
        conn_type_str = connection_node.get(CONFIG_DEVICE_CONNECTION_TYPE)

        self.connection = None

        for conn_class in CLIMATE_IP_CONNECTIONS:
            if conn_class.match_type(conn_type_str):  # type: ignore[attr-defined]
                _LOGGER.debug(  # pragma: no mutate
                    "%s Found matching connection class '%s' for type '%s'",  # pragma: no mutate
                    self.controller.log_prefix,  # pragma: no mutate
                    conn_class.__name__,  # pragma: no mutate
                    conn_type_str,  # pragma: no mutate
                )  # pragma: no mutate
                if conn_class.__name__ == "ConnectionAiohttp8888":
                    merged_config = {**controller_config, **connection_node}
                    self.connection = conn_class(  # type: ignore[call-arg,assignment]
                        merged_config,
                        _LOGGER,
                        getattr(self.controller, "hass", None),
                        getattr(self.controller, "_session", None),
                        getattr(self.controller, "ip_address", None),
                    )
                elif conn_class.__name__ == "ConnectionRaw8888":
                    self.connection = conn_class(  # type: ignore[call-arg,assignment]
                        controller_config,
                        _LOGGER,
                        getattr(self.controller, "hass", None),
                        getattr(self.controller, "_session", None),
                        getattr(self.controller, "ip_address", None),
                    )
                else:
                    self.connection = conn_class(
                        controller_config, _LOGGER, hass=getattr(self.controller, "hass", None)
                    )  # type: ignore[call-arg,assignment]

                if self.connection and self.connection.load_from_yaml(connection_node, None):
                    break

        if not self.connection:
            _LOGGER.error(  # pragma: no mutate
                "%s No matching connection class found for type '%s'",  # pragma: no mutate
                self.controller.log_prefix,  # pragma: no mutate
                conn_type_str,  # pragma: no mutate
            )  # pragma: no mutate

        if self.connection is None:
            _LOGGER.error("%s Could not create connection object", self.controller.log_prefix)  # pragma: no mutate
            return False

        _LOGGER.debug(  # pragma: no mutate
            "%s Connection object created successfully. Type: %s",  # pragma: no mutate
            self.controller.log_prefix,  # pragma: no mutate
            type(self.connection).__name__,  # pragma: no mutate
        )   # pragma: no mutate

        self.state_getter = create_status_getter(
            "state", ac.get(CONFIG_DEVICE_STATUS, {}), self.connection, self.controller
        )
        if self.state_getter is None:
            _LOGGER.error(  # pragma: no mutate
                "%s Missing 'status' configuration node in '%s'", self.controller.log_prefix, file  # pragma: no mutate
            )  # pragma: no mutate
            return False

        self.name = ac.get(ATTR_NAME, CONST_CONTROLLER_TYPE)

        poll_config = str(ac.get(CONFIG_DEVICE_POLL, "")).lower()
        if poll_config == "true":
            self.poll = True
        elif poll_config == "false":
            self.poll = False
        else:
            self.poll = None

        return True

    async def async_finish_initialization(self) -> None:
        """Complete controller initialization once device_id has been discovered."""
        if self.is_fully_initialized or not self._parsed_yaml_config:
            return

        dev_id = getattr(self.controller, "device_id", "")
        if dev_id in self._parsed_yaml_cache:
            yaml_device = self._parsed_yaml_cache[dev_id]
        else:
            yaml_device = self._parsed_yaml_config
            self._parsed_yaml_cache[dev_id] = yaml_device

        ac = yaml_device.get(CONFIG_DEVICE, {}) if yaml_device else {}

        nodes = ac.get(CONFIG_DEVICE_OPERATIONS, {})
        for op_key in nodes.keys():
            op = create_property(
                op_key, nodes[op_key], self.connection, self.controller, self.state_getter
            )
            if op is not None:
                op_id = getattr(op, "id", op_key)
                self.operations[op_id] = op
                if op_id not in self.operations_list:
                    self.operations_list.append(op_id)
                self.service_schema_map[vol.Optional(op_id)] = getattr(op, "config_validation_type", cv.string)

        nodes = ac.get(CONFIG_DEVICE_SWITCHES, {})
        for op_key in nodes.keys():
            op = create_property(
                op_key, nodes[op_key], self.connection, self.controller, self.state_getter
            )
            if op is not None:
                op_id = getattr(op, "id", op_key)
                self.operations[op_id] = op
                if op_id not in self.operations_list:
                    self.operations_list.append(op_id)
                self.service_schema_map[vol.Optional(op_id)] = getattr(op, "config_validation_type", cv.string)

        nodes = ac.get(CONFIG_DEVICE_ATTRIBUTES, {})
        for key in nodes.keys():
            prop = create_property(
                key, nodes[key], self.connection, self.controller, self.state_getter
            )
            if prop is not None:
                prop_id = getattr(prop, "id", key)
                self.properties[prop_id] = prop
                if hasattr(prop, "set_unit_of_measurement") and "unit_of_measurement" in nodes[key]:
                    prop.set_unit_of_measurement(nodes[key]["unit_of_measurement"])

        node_sensors = ac.get(CONFIG_DEVICE_SENSORS, {})
        _LOGGER.debug("%s Loading %d sensors", self.controller.log_prefix, len(node_sensors))  # pragma: no mutate
        for name in node_sensors.keys():
            prop = create_property(
                name,
                node_sensors[name],
                self.connection,
                self.controller,
                self.state_getter,
            )
            if prop:
                self.sensors[name] = prop
                self.sensors_list.append(name)

        # Apply temperature units from config/options.
        configured_unit = DEFAULT_CONF_TEMP_UNIT
        if getattr(self.controller, "hass", None):
            configured_unit = self.controller.hass.config.units.temperature_unit

        native_current_unit = DEFAULT_CONF_TEMP_UNIT
        native_target_unit = DEFAULT_CONF_TEMP_UNIT

        controller_config = getattr(self.controller, "_config", getattr(self.controller, "config", {}))
        entry_id = controller_config.get("entry_id")
        if getattr(self.controller, "hass", None) and entry_id:
            entry = self.controller.hass.config_entries.async_get_entry(entry_id)
            if entry:
                native_current_unit = entry.options.get(
                    CONF_TEMP_NATIVE_CURRENT,
                    entry.data.get(CONF_TEMP_NATIVE_CURRENT, configured_unit),
                )
                native_target_unit = entry.options.get(
                    CONF_TEMP_NATIVE_TARGET,
                    entry.data.get(CONF_TEMP_NATIVE_TARGET, configured_unit),
                )
                _LOGGER.debug(  # pragma: no mutate
                    "%s [Init] Configured temperature units — Display: %s, Native Current: %s, Native Target: %s",  # pragma: no mutate
                    self.controller.log_prefix,  # pragma: no mutate
                    configured_unit,  # pragma: no mutate
                    native_current_unit,  # pragma: no mutate
                    native_target_unit,  # pragma: no mutate
                )  # pragma: no mutate

        def apply_unit(prop_instance: Any) -> None:
            """Apply the correct temperature unit using explicit type checking."""
            if not prop_instance:
                return
                
            is_temp = isinstance(prop_instance, TemperatureOperation) or getattr(prop_instance, "device_class", None) == "temperature"

            if is_temp:
                if hasattr(prop_instance, "set_hass_unit") and hasattr(prop_instance, "set_device_unit"):
                    _LOGGER.debug(  # pragma: no mutate
                        "%s Applying dual units to property '%s'. Display: %s",  # pragma: no mutate
                        self.controller.log_prefix,  # pragma: no mutate
                        getattr(prop_instance, "id", "unknown"),  # pragma: no mutate
                        configured_unit,  # pragma: no mutate
                    )  # pragma: no mutate
                    prop_instance.set_hass_unit(configured_unit)
                    if getattr(prop_instance, "id", "") == ATTR_TEMPERATURE:
                        prop_instance.set_device_unit(native_target_unit)
                    else:
                        prop_instance.set_device_unit(native_current_unit)
                elif hasattr(prop_instance, "set_unit_of_measurement"):
                    _LOGGER.debug(  # pragma: no mutate
                        "%s Applying configured unit '%s' to property '%s'",  # pragma: no mutate
                        self.controller.log_prefix,  # pragma: no mutate
                        configured_unit,  # pragma: no mutate
                        getattr(prop_instance, "id", "unknown"),  # pragma: no mutate
                    )  # pragma: no mutate
                    prop_instance.set_unit_of_measurement(configured_unit)

        for op in self.operations.values():
            apply_unit(op)
        for prop in self.properties.values():
            apply_unit(prop)
        for sensor in self.sensors.values():
            apply_unit(sensor)

        self.operations_list = list(self.operations.keys())
        self.properties_list = list(self.properties.keys())
        self.is_fully_initialized = True
        _LOGGER.debug(  # pragma: no mutate
            "%s Controller config loading is now fully completed.", self.controller.log_prefix  # pragma: no mutate
        )  # pragma: no mutate
