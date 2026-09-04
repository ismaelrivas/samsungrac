# pylint: disable=import-outside-toplevel,line-too-long,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-return-statements,too-many-statements,unused-import
"""YAML configuration loader for climate_ip controllers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    ATTR_TEMPERATURE,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.util.yaml import load_yaml
import voluptuous as vol

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
from .properties import TemperatureOperation, create_property, create_status_getter

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = "yaml"

# Module-level cache for raw YAML file content.
_YAML_FILE_CACHE: dict[str, dict[str, Any]] = {}


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

        self.service_schema_map: dict[Any, Any] = {
            vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids
        }

        self.connection: Connection | None = None
        self.state_getter = None
        self.name = CONST_CONTROLLER_TYPE
        self.poll: bool | None = None
        self.is_fully_initialized = False

        self._parsed_yaml_config: dict[str, Any] | None = None
        self._parsed_yaml_cache: dict[str | None, dict[str, Any]] = {}

    @property
    def parsed_yaml_cache(self) -> dict[str | None, dict[str, Any]]:
        """Return the parsed YAML cache for the current device."""
        return self._parsed_yaml_cache

    async def async_initialize(self) -> bool:
        """Perform initial YAML configuration loading and set up the base connection."""
        raw_file = self.controller.yaml_file
        if raw_file is None:
            _LOGGER.error(  # pragma: no mutate
                "%s No configuration file specified. Aborting initialization.",  # pragma: no mutate
                self.controller.log_prefix,  # pragma: no mutate
            )  # pragma: no mutate
            return False

        # Resolve relative filenames to absolute package path; keep absolute paths as-is
        file = (
            str(Path(__file__).parent / raw_file)
            if not Path(raw_file).is_absolute()
            else raw_file
        )

        # Check cache by resolved path, then raw fallback
        if file in _YAML_FILE_CACHE:
            _LOGGER.debug(  # pragma: no mutate
                "%s [Cache] Using cached YAML file content for: %s",  # pragma: no mutate
                self.controller.log_prefix,  # pragma: no mutate
                file,  # pragma: no mutate
            )  # pragma: no mutate
            self._parsed_yaml_config = _YAML_FILE_CACHE[file]
        elif raw_file in _YAML_FILE_CACHE:
            _LOGGER.debug(  # pragma: no mutate
                "%s [Cache] Using cached YAML file content for: %s",  # pragma: no mutate
                self.controller.log_prefix,  # pragma: no mutate
                raw_file,  # pragma: no mutate
            )  # pragma: no mutate
            self._parsed_yaml_config = _YAML_FILE_CACHE[raw_file]
        else:
            try:
                raw_loaded_yaml: Any
                try:
                    hass_ref = self.controller.hass
                except AttributeError:
                    hass_ref = None

                if hass_ref is not None:  # pragma: no mutate
                    raw_loaded_yaml = await hass_ref.async_add_executor_job(
                        load_yaml, file
                    )
                else:
                    raw_loaded_yaml = load_yaml(file)  # pragma: no mutate

                if isinstance(raw_loaded_yaml, dict):
                    self._parsed_yaml_config = raw_loaded_yaml
                else:
                    self._parsed_yaml_config = None

                if self._parsed_yaml_config is not None:
                    _YAML_FILE_CACHE[file] = self._parsed_yaml_config
                _LOGGER.debug(  # pragma: no mutate
                    "%s [Cache] YAML file loaded and cached: %s",  # pragma: no mutate
                    self.controller.log_prefix,  # pragma: no mutate
                    file,  # pragma: no mutate
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
            _LOGGER.error(
                "%s YAML configuration is empty or could not be read.",
                self.controller.log_prefix,
            )
            return False

        yaml_device = self._parsed_yaml_config
        try:
            dev_id = self.controller.device_id or ""
        except AttributeError:
            dev_id = ""
        self._parsed_yaml_cache[dev_id] = yaml_device

        if CONFIG_DEVICE not in yaml_device:
            _LOGGER.error(
                "%s Configuration file '%s' is missing the 'device' root key",
                self.controller.log_prefix,
                file,
            )
            return False

        ac = yaml_device[CONFIG_DEVICE]

        connection_node = ac.get(CONFIG_DEVICE_CONNECTION, {}).copy()

        # Sanitized configuration dictionary access
        try:
            controller_config = self.controller.config
        except AttributeError:
            try:
                controller_config = self.controller._config
            except AttributeError:
                controller_config = {}
        device_type = controller_config.get(CONF_DEVICE_TYPE)

        if device_type == DEVICE_TYPE_SAMSUNG_2878:
            _LOGGER.debug(
                "%s Using 'samsung_2878' connection engine", self.controller.log_prefix
            )
            connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_2878"
        elif device_type in DEVICE_TYPE_AIOHTTP_SUPPORTED:
            conn_method = controller_config.get(CONF_CONN_METHOD, CONN_METHOD_AIOHTTP)

            entry_id = controller_config.get("entry_id")
            try:
                hass_ref = self.controller.hass
            except AttributeError:
                hass_ref = None

            if hass_ref is not None and entry_id:
                entry = hass_ref.config_entries.async_get_entry(entry_id)
                if entry:
                    _LOGGER.debug(
                        "%s [Init] Retrieved ConfigEntry. Options: %s",
                        self.controller.log_prefix,
                        entry.options,
                    )
                    if entry.options:
                        conn_method = entry.options.get(CONF_CONN_METHOD, conn_method)

            if conn_method == CONN_METHOD_AIOHTTP:
                _LOGGER.debug(
                    "%s Using 'Modern (aiohttp)' connection engine (from options)",
                    self.controller.log_prefix,
                )
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = "samsung_8888_aiohttp"
            elif conn_method == CONN_METHOD_RAW:
                _LOGGER.debug(
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
                connection_node[CONFIG_DEVICE_CONNECTION_TYPE] = (
                    ac.get(  # pragma: no mutate
                        CONFIG_DEVICE_CONNECTION,
                        {},  # pragma: no mutate
                    ).get(CONFIG_DEVICE_CONNECTION_TYPE, "request")
                )  # pragma: no mutate

        try:
            key = self.controller.unique_id
        except AttributeError:
            key = None
        if not key:
            _LOGGER.error(
                "%s Cannot create a unique connection without a unique_id",
                self.controller.log_prefix,
            )
            return False

        _LOGGER.debug(
            "%s Creating new connection object for %s", self.controller.log_prefix, key
        )
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
                try:
                    hass_ref = self.controller.hass
                except AttributeError:
                    hass_ref = None
                try:
                    session_ref = self.controller._session
                except AttributeError:
                    session_ref = None
                try:
                    ip_ref = self.controller.ip_address
                except AttributeError:
                    ip_ref = None

                if conn_class.__name__ == "ConnectionAiohttp8888":
                    merged_config = {**controller_config, **connection_node}
                    self.connection = conn_class(
                        merged_config,
                        _LOGGER,
                        hass_ref,
                        session_ref,
                        ip_ref,
                    )
                elif conn_class.__name__ == "ConnectionRaw8888":
                    self.connection = conn_class(
                        controller_config,
                        _LOGGER,
                        hass_ref,
                        session_ref,
                        ip_ref,
                    )
                else:
                    self.connection = conn_class(
                        controller_config,
                        _LOGGER,
                        hass=hass_ref,
                    )

                if self.connection and self.connection.load_from_yaml(
                    connection_node, None
                ):
                    break

        if self.connection is None:
            _LOGGER.error(
                "%s No matching connection class found for type '%s'",
                self.controller.log_prefix,
                conn_type_str,
            )
            return False

        try:
            self.connection.set_controller_ref(self.controller)
        except AttributeError:
            pass

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
                "%s Missing 'status' configuration node in '%s'",
                self.controller.log_prefix,
                file,
            )
            return False

        self.name = ac.get(ATTR_NAME, CONST_CONTROLLER_TYPE)

        poll_config = str(ac.get(CONFIG_DEVICE_POLL, "")).lower()  # pragma: no mutate
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

        try:
            dev_id = self.controller.device_id or ""  # pragma: no mutate
        except AttributeError:
            dev_id = ""
        if dev_id in self._parsed_yaml_cache:
            yaml_device = self._parsed_yaml_cache[dev_id]
        else:
            yaml_device = self._parsed_yaml_config
            self._parsed_yaml_cache[dev_id] = yaml_device

        ac = yaml_device.get(CONFIG_DEVICE, {}) if yaml_device else {}

        nodes = ac.get(CONFIG_DEVICE_OPERATIONS, {})
        for op_key in nodes.keys():
            op = create_property(
                op_key,
                nodes[op_key],
                self.connection,
                self.controller,
                self.state_getter,
            )
            if op is not None:
                try:
                    op_id = op.id
                except AttributeError:
                    op_id = op_key
                self.operations[op_id] = op
                try:
                    schema = op.config_validation_type
                except AttributeError:
                    schema = cv.string
                self.service_schema_map[vol.Optional(op_id)] = schema

        nodes = ac.get(CONFIG_DEVICE_SWITCHES, {})
        for op_key in nodes.keys():
            op = create_property(  # pragma: no mutate
                op_key,
                nodes[op_key],
                self.connection,
                self.controller,
                self.state_getter,
            )
            if op is not None:  # pragma: no mutate
                try:
                    op_id = op.id
                except AttributeError:
                    op_id = op_key  # pragma: no mutate
                self.operations[op_id] = op  # pragma: no mutate
                if op_id not in self.operations_list:  # pragma: no mutate
                    self.operations_list.append(op_id)  # pragma: no mutate
                try:
                    schema = op.config_validation_type
                except AttributeError:
                    schema = cv.string
                self.service_schema_map[vol.Optional(op_id)] = (
                    schema  # pragma: no mutate
                )

        nodes = ac.get(CONFIG_DEVICE_ATTRIBUTES, {})
        for key in nodes.keys():
            prop = create_property(  # pragma: no mutate
                key, nodes[key], self.connection, self.controller, self.state_getter
            )
            if prop is not None:  # pragma: no mutate
                try:
                    prop_id = prop.id
                except AttributeError:
                    prop_id = key  # pragma: no mutate
                self.properties[prop_id] = prop  # pragma: no mutate
                if "unit_of_measurement" in nodes[key]:  # pragma: no mutate
                    try:
                        prop.set_unit_of_measurement(
                            nodes[key]["unit_of_measurement"]
                        )  # pragma: no mutate
                    except AttributeError:
                        pass

        node_sensors = ac.get(CONFIG_DEVICE_SENSORS, {})
        _LOGGER.debug(
            "%s Loading %d sensors", self.controller.log_prefix, len(node_sensors)
        )  # pragma: no mutate
        for name in node_sensors.keys():
            prop = create_property(  # pragma: no mutate
                name,  # pragma: no mutate
                node_sensors[name],  # pragma: no mutate
                self.connection,  # pragma: no mutate
                self.controller,  # pragma: no mutate
                self.state_getter,  # pragma: no mutate
            )
            if prop:  # pragma: no mutate
                self.sensors[name] = prop  # pragma: no mutate
                self.sensors_list.append(name)  # pragma: no mutate

        # Apply temperature units from config/options.
        configured_unit = DEFAULT_CONF_TEMP_UNIT
        try:
            hass_ref = self.controller.hass
        except AttributeError:
            hass_ref = None

        if hass_ref:
            configured_unit = hass_ref.config.units.temperature_unit

        native_current_unit = DEFAULT_CONF_TEMP_UNIT  # pragma: no mutate
        native_target_unit = DEFAULT_CONF_TEMP_UNIT  # pragma: no mutate

        try:
            controller_config = self.controller.config
        except AttributeError:
            try:
                controller_config = self.controller._config
            except AttributeError:
                controller_config = {}

        entry_id = controller_config.get("entry_id")
        if hass_ref and entry_id:
            entry = hass_ref.config_entries.async_get_entry(
                entry_id
            )  # pragma: no mutate
            if entry:
                native_current_unit = entry.options.get(
                    CONF_TEMP_NATIVE_CURRENT,
                    entry.data.get(
                        CONF_TEMP_NATIVE_CURRENT, configured_unit
                    ),  # pragma: no mutate
                )
                native_target_unit = entry.options.get(
                    CONF_TEMP_NATIVE_TARGET,
                    entry.data.get(
                        CONF_TEMP_NATIVE_TARGET, configured_unit
                    ),  # pragma: no mutate
                )
                _LOGGER.debug(
                    "%s [Init] Configured temperature units — Display: %s, Native Current: %s, Native Target: %s",
                    self.controller.log_prefix,
                    configured_unit,
                    native_current_unit,
                    native_target_unit,
                )

        def apply_unit(prop_instance: Any) -> None:
            """Apply the correct temperature unit using explicit type checking."""
            if not prop_instance:
                return

            try:
                device_class = prop_instance.device_class
            except AttributeError:
                device_class = None

            is_temp = (
                isinstance(prop_instance, TemperatureOperation)
                or device_class == "temperature"
            )

            if is_temp:
                try:
                    prop_instance.set_hass_unit(configured_unit)
                    try:
                        prop_id = prop_instance.id
                    except AttributeError:
                        prop_id = None
                    if prop_id == ATTR_TEMPERATURE:
                        prop_instance.set_device_unit(native_target_unit)
                    else:
                        prop_instance.set_device_unit(native_current_unit)
                    _LOGGER.debug(
                        "%s Applying dual units to property '%s'. Display: %s",
                        self.controller.log_prefix,
                        prop_id or "unknown",
                        configured_unit,
                    )  # pragma: no mutate
                except AttributeError:
                    try:
                        prop_instance.set_unit_of_measurement(configured_unit)
                        try:
                            prop_id = prop_instance.id
                        except AttributeError:
                            prop_id = None
                        _LOGGER.debug(
                            "%s Applying configured unit '%s' to property '%s'",
                            self.controller.log_prefix,
                            configured_unit,
                            prop_id or "unknown",
                        )  # pragma: no mutate
                    except AttributeError:
                        pass

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
            "%s [DEBUG INIT] Finished initialization! Operations mapped: %s",
            self.controller.log_prefix,
            self.operations_list,
        )
