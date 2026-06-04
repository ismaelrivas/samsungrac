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
from .properties import create_property, create_status_getter

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = "yaml"

# Module-level cache for raw YAML file content.
_YAML_FILE_CACHE: dict[str, dict] = {}


def clear_yaml_cache() -> None:
    """Clear the YAML file content cache to allow reloading from disk."""
    if _YAML_FILE_CACHE:
        _LOGGER.info("Clearing YAML file cache to force re-read on reload.")
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

    async def async_initialize(self) -> bool:
        """Perform initial YAML configuration loading and set up the base connection."""
        # pylint: disable=import-outside-toplevel,protected-access
        file = self.controller._yaml
        if file is not None and file.find("\\") == -1 and file.find("/") == -1:
            file = os.path.join(os.path.dirname(__file__), file)
        _LOGGER.debug("%s Loading configuration file: %s", self.controller.log_prefix, file)

        if file is None:
            _LOGGER.error(
                "%s No configuration file specified. Aborting initialization.",
                self.controller.log_prefix,
            )
            return False

        if file in _YAML_FILE_CACHE:
            _LOGGER.debug(
                "%s [Cache] Using cached YAML file content for: %s",
                self.controller.log_prefix,
                file,
            )
            self._parsed_yaml_config = _YAML_FILE_CACHE[file]
        else:
            try:

                def _read_file() -> str:
                    with open(file, "r", encoding="utf-8") as stream:
                        return stream.read()

                if getattr(self.controller, "hass", None):
                    self._parsed_yaml_config = await self.controller.hass.async_add_executor_job(
                        load_yaml, file
                    )
                else:
                    self._parsed_yaml_config = load_yaml(file)

                _YAML_FILE_CACHE[file] = self._parsed_yaml_config
                _LOGGER.debug(
                    "%s [Cache] YAML file loaded and cached: %s", self.controller.log_prefix, file
                )
            except Exception as exc:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                _LOGGER.error(
                    "%s Error loading YAML configuration %s: %s",
                    self.controller.log_prefix,
                    file,
                    exc,
                    exc_info=True,
                )
                return False

        if not self._parsed_yaml_config:
            _LOGGER.error(
                "%s YAML configuration is empty or could not be read.", self.controller.log_prefix
            )
            return False

        # Note: We are now using load_yaml directly which returns a dict.
        # Previously we used stream_wrapper on the string and then parsed.
        # Since load_yaml is requested for native HA behavior, we use the dict directly.
        yaml_device = self._parsed_yaml_config



        self._parsed_yaml_cache[self.controller.device_id] = yaml_device

        if CONFIG_DEVICE not in yaml_device:
            _LOGGER.error(
                "%s Configuration file '%s' is missing the 'device' root key",
                self.controller.log_prefix,
                file,
            )
            return False

        ac = yaml_device.get(CONFIG_DEVICE, {}) if yaml_device else {}

        connection_node = ac.get(CONFIG_DEVICE_CONNECTION, {}).copy()
        device_type = self.controller._config.get(CONF_DEVICE_TYPE)

        if device_type == DEVICE_TYPE_SAMSUNG_2878:
            _LOGGER.info("%s Using 'samsung_2878' connection engine", self.controller.log_prefix)
            connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_2878"
        elif device_type in DEVICE_TYPE_AIOHTTP_SUPPORTED:
            conn_method = self.controller._config.get(CONF_CONN_METHOD, CONN_METHOD_AIOHTTP)

            entry_id = self.controller._config.get("entry_id")
            if self.controller.hass and entry_id:
                entry = self.controller.hass.config_entries.async_get_entry(entry_id)
                if entry:
                    _LOGGER.debug(
                        "%s [Init] Retrieved ConfigEntry. Options: %s",
                        self.controller.log_prefix,
                        entry.options,
                    )
                    if entry.options:
                        conn_method = entry.options.get(CONF_CONN_METHOD, conn_method)

            if conn_method == CONN_METHOD_AIOHTTP:
                _LOGGER.info(
                    "%s Using 'Modern (aiohttp)' connection engine (from options)",
                    self.controller.log_prefix,
                )
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_8888_aiohttp"
            elif conn_method == CONN_METHOD_RAW:
                _LOGGER.info(
                    "%s Using 'Robust (raw socket)' connection engine (from options)",
                    self.controller.log_prefix,
                )
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_8888_raw"
            else:
                _LOGGER.warning(
                    "%s [DEPRECATED] Using obsolete 'request' (synchronous) engine. "
                    "Please reconfigure this device via Integrations UI -> Reconfigure "
                    "to use Modern (aiohttp) or Robust (raw socket) for better performance and stability.",
                    self.controller.log_prefix,
                )
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = ac.get(
                    CONFIG_DEVICE_CONNECTION, {}
                ).get(CONFIG_DEVICE_CONNECTION_TYPE, "request")

        key = self.controller.unique_id
        if not key:
            _LOGGER.error(
                "%s Cannot create a unique connection without a unique_id",
                self.controller.log_prefix,
            )
            return False

        _LOGGER.debug("%s Creating new connection object for %s", self.controller.log_prefix, key)
        conn_type_str = connection_node.get(CONFIG_DEVICE_CONNECTION_TYPE)

        self.connection = None

        for conn_class in CLIMATE_IP_CONNECTIONS:
            if conn_class.match_type(conn_type_str):  # type: ignore[attr-defined]
                _LOGGER.debug(
                    "%s Found matching connection class '%s' for type '%s'",
                    self.controller.log_prefix,
                    conn_class.__name__,
                    conn_type_str,
                )
                if conn_class.__name__ == "ConnectionAiohttp8888":
                    merged_config = {**self.controller._config, **connection_node}
                    self.connection = conn_class(  # type: ignore[call-arg,assignment]
                        merged_config,
                        _LOGGER,
                        self.controller.hass,
                        self.controller._session,
                        self.controller.ip_address,
                    )
                elif conn_class.__name__ == "ConnectionRaw8888":
                    self.connection = conn_class(  # type: ignore[call-arg,assignment]
                        self.controller._config,
                        _LOGGER,
                        self.controller.hass,
                        self.controller._session,
                        self.controller.ip_address,
                    )
                else:
                    self.connection = conn_class(
                        self.controller._config, _LOGGER, hass=self.controller.hass
                    )  # type: ignore[call-arg,assignment]

                if self.connection and self.connection.load_from_yaml(connection_node, None):
                    break

        if not self.connection:
            _LOGGER.error(
                "%s No matching connection class found for type '%s'",
                self.controller.log_prefix,
                conn_type_str,
            )

        if self.connection is None:
            _LOGGER.error("%s Could not create connection object", self.controller.log_prefix)
            return False

        _LOGGER.debug(
            "%s Connection object created successfully. Type: %s",
            self.controller.log_prefix,
            type(self.connection).__name__,
        )

        self.state_getter = create_status_getter(
            "state", ac.get(CONFIG_DEVICE_STATUS, {}), self.connection, self.controller
        )
        if self.state_getter is None:
            _LOGGER.error(
                "%s Missing 'status' configuration node in '%s'", self.controller.log_prefix, file
            )
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

        # Use the context-aware cache, keyed by device_id.
        if self.controller.device_id in self._parsed_yaml_cache:
            yaml_device = self._parsed_yaml_cache[self.controller.device_id]
        else:
            # We use the loaded dict directly.
            yaml_device = self._parsed_yaml_config





            self._parsed_yaml_cache[self.controller.device_id] = yaml_device

        ac = yaml_device.get(CONFIG_DEVICE, {}) if yaml_device else {}

        nodes = ac.get(CONFIG_DEVICE_OPERATIONS, {})
        for op_key in nodes.keys():
            op = create_property(
                op_key, nodes[op_key], self.connection, self.controller, self.state_getter
            )
            if op is not None:
                self.operations[op.id] = op
                if op not in self.operations_list:
                    self.operations_list.append(op)
                self.service_schema_map[vol.Optional(op.id)] = op.config_validation_type

        nodes = ac.get(CONFIG_DEVICE_SWITCHES, {})
        for op_key in nodes.keys():
            op = create_property(
                op_key, nodes[op_key], self.connection, self.controller, self.state_getter
            )
            if op is not None:
                self.operations[op.id] = op
                if op not in self.operations_list:
                    self.operations_list.append(op)
                self.service_schema_map[vol.Optional(op.id)] = op.config_validation_type

        nodes = ac.get(CONFIG_DEVICE_ATTRIBUTES, {})
        for key in nodes.keys():
            prop = create_property(
                key, nodes[key], self.connection, self.controller, self.state_getter
            )
            if prop is not None:
                self.properties[prop.id] = prop
                has_setter = hasattr(prop, "set_unit_of_measurement")
                has_unit_key = "unit_of_measurement" in nodes[key]
                if has_setter and has_unit_key:
                    unit_value = nodes[key]["unit_of_measurement"]
                    prop.set_unit_of_measurement(unit_value)

        node_sensors = ac.get(CONFIG_DEVICE_SENSORS, {})
        _LOGGER.debug("%s Loading %d sensors", self.controller.log_prefix, len(node_sensors))
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
        if self.controller.hass:
            configured_unit = self.controller.hass.config.units.temperature_unit

        native_current_unit = DEFAULT_CONF_TEMP_UNIT
        native_target_unit = DEFAULT_CONF_TEMP_UNIT

        # pylint: disable=import-outside-toplevel,protected-access
        entry_id = self.controller._config.get("entry_id")
        if self.controller.hass and entry_id:
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
                _LOGGER.debug(
                    "%s [Init] Configured temperature units — Display: %s, "
                    "Native Current: %s, Native Target: %s",
                    self.controller.log_prefix,
                    configured_unit,
                    native_current_unit,
                    native_target_unit,
                )

        def apply_unit(prop: Any) -> None:
            """Apply the correct temperature unit to a single property."""
            if not prop:
                return
            is_temp = False
            if hasattr(prop, "match_type") and prop.match_type("temperature"):
                is_temp = True
            elif getattr(prop, "device_class", None) == "temperature":
                is_temp = True

            if is_temp:
                if hasattr(prop, "set_hass_unit") and hasattr(prop, "set_device_unit"):
                    _LOGGER.debug(
                        "%s Applying dual units to property '%s'. Display: %s",
                        self.controller.log_prefix,
                        prop.id,
                        configured_unit,
                    )
                    prop.set_hass_unit(configured_unit)
                    if prop.id == ATTR_TEMPERATURE:
                        prop.set_device_unit(native_target_unit)
                    else:
                        prop.set_device_unit(native_current_unit)
                elif hasattr(prop, "set_unit_of_measurement"):
                    _LOGGER.debug(
                        "%s Applying configured unit '%s' to property '%s'",
                        self.controller.log_prefix,
                        configured_unit,
                        prop.id,
                    )
                    prop.set_unit_of_measurement(configured_unit)

        for op in self.operations.values():
            apply_unit(op)
        for prop in self.properties.values():
            apply_unit(prop)
        for sensor in self.sensors.values():
            apply_unit(sensor)

        self.operations_list = list(self.operations.keys())
        self.properties_list = list(self.properties.keys())
        self.is_fully_initialized = True
        _LOGGER.debug(
            "%s Controller config loading is now fully completed.", self.controller.log_prefix
        )
