# pylint: disable=too-many-branches,too-many-instance-attributes
"""Device property classes for the climate_ip integration."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Final, Protocol, runtime_checkable

from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    ClimateEntityFeature,
)
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_SUBDEVICE_ID,
    CONF_TOKEN_KEY,
    CONFIG_DEVICE_CLASS,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
    CONFIG_DEVICE_NAME,
    CONFIG_DEVICE_OPERATION_NUMBER_MAX,
    CONFIG_DEVICE_OPERATION_NUMBER_MIN,
    CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE,
    CONFIG_DEVICE_OPERATION_VALUE,
    CONFIG_DEVICE_OPERATION_VALUES,
    CONFIG_DEVICE_STATUS_TEMPLATE,
    CONFIG_DEVICE_VALIDATION_TEMPLATE,
    CONFIG_ENTITY_CATEGORY,
    CONFIG_OPTIMISTIC_CASCADES,
    CONFIG_STATE_CLASS,
    CONFIG_STATE_NODE,
    CONFIG_TARGET_NODE,
    CONFIG_TYPE,
    CONFIG_UNIT_OF_MEASUREMENT,
    CONFIG_VALUE_MAP,
    DEFAULT_CACHE_KEY_ID,
    DEFAULT_JSON_STATUS_PAYLOAD,
    DEGREE_SYMBOL,
    FALLBACK_DEVICE_ID,
    ID_DELIMITER,
    KEY_DEFAULT,
    KEY_DEVICE_CONFIG,
    KEY_DEVICE_MODE,
    KEY_DEVICE_STATE,
    KEY_DEVICES,
    KEY_DUID,
    KEY_HEADERS,
    KEY_HVAC,
    KEY_IDENTIFIERS,
    KEY_JSON_PAYLOAD,
    KEY_METHOD,
    KEY_PATH_TO_DEVICES,
    KEY_RAW_PAYLOAD,
    KEY_STATUS,
    KEY_URL,
    LEGACY_YAML_TO_ATTR_MAP,
    MODE_PROPERTY_SUFFIX,
    PROPERTY_TYPE_ENUM,
    PROPERTY_TYPE_MODE,
    PROPERTY_TYPE_NUMBER,
    PROPERTY_TYPE_STRING,
    PROPERTY_TYPE_SWITCH as PROPERTY_TYPE_SWITCH,  # noqa: PLC0414
    PROPERTY_TYPE_TEMP,
    PROPERTY_TYPE_UNIQUE_ID,
    STATUS_GETTER_JSON,
    TEMP_UNIT_CELSIUS_ALIASES,
    TEMP_UNIT_FAHRENHEIT_ALIASES,
    TMPL_VAR_DEVICE_ID,
    TMPL_VAR_DEVICE_STATE,
    TMPL_VAR_VALUE,
    VALIDATION_SUCCESS_TOKEN,
    YAML_NAME_TO_HA_FEATURE,
)
from .exceptions import AuthError, CannotConnect
from .helpers import get_value_by_path

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class ConnectionWithParams(Protocol):
    """Connection that supports parameter-based execution."""

    _params: dict[str, Any]
    _connection_template: Template | None
    connection_template: Template | None
    config: dict[str, Any]
    is_async_native: bool

    async def async_execute(
        self,
        method: str | None,
        url: str | None,
        data: Any,
        headers: dict[str, Any] | None,
        **kwargs: Any,
    ) -> tuple[str | None, dict[str, Any] | None]: ...

    async def async_execute_with_retry(
        self,
        template: Any,
        value: Any,
        device_state: Any = None,
        device_id: str | None = None,
    ) -> Any: ...

    def create_updated(self, yaml_node: dict[str, Any] | None) -> Any: ...


_WARNED_TEMPLATE_MESSAGES: set[str] = set()


def clear_template_warning_cache() -> None:
    """Clear the deduplicated template warning cache (e.g. when reloading YAML maps)."""
    _WARNED_TEMPLATE_MESSAGES.clear()


def _template_log_fn(level: int, msg: str) -> None:
    """Route template variable warnings to debug level, logging each unique message only once."""
    if msg not in _WARNED_TEMPLATE_MESSAGES:
        _WARNED_TEMPLATE_MESSAGES.add(msg)
        _LOGGER.debug("Template variable warning: %s", msg)


def render_template(template: Template | str | None | Any, **kwargs: Any) -> Any:
    """Render Jinja2 template strictly using Home Assistant's Template.async_render."""
    if template is None or isinstance(template, str):
        return template
    if isinstance(template, Template):
        return template.async_render(kwargs, parse_result=True, log_fn=_template_log_fn)
    raise TypeError(
        f"Expected HomeAssistant Template or str, got {type(template).__name__}"
    )


def parse_temperature_unit(unit: str | UnitOfTemperature | Any) -> UnitOfTemperature:
    """Strictly parse and validate temperature unit strings."""
    if isinstance(unit, UnitOfTemperature):
        return unit
    if isinstance(unit, str):
        u = unit.replace(DEGREE_SYMBOL, "").strip().upper()
        if u in TEMP_UNIT_CELSIUS_ALIASES:
            return UnitOfTemperature.CELSIUS
        if u in TEMP_UNIT_FAHRENHEIT_ALIASES:
            return UnitOfTemperature.FAHRENHEIT

    raise ValueError(f"Invalid temperature unit: {unit}")


_parse_temperature_unit = parse_temperature_unit


def _normalize_unit(unit: str | UnitOfTemperature | Any) -> Any:
    """Normalize temperature aliases, otherwise return unchanged (for non-temp units)."""
    try:
        return _parse_temperature_unit(unit)
    except ValueError:
        return unit


HA_MODE_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        ATTR_HVAC_MODE,
        ATTR_FAN_MODE,
        ATTR_PRESET_MODE,
        ATTR_SWING_MODE,
    }
)

CLIMATE_IP_PROPERTIES: list[type[DeviceProperty]] = []
CLIMATE_IP_STATUS_GETTER: list[type[GetJsonStatus]] = []


def register_property(dev_prop: type[DeviceProperty]) -> type[DeviceProperty]:
    """Decorate a function to register a property."""
    if dev_prop not in CLIMATE_IP_PROPERTIES:
        CLIMATE_IP_PROPERTIES.append(dev_prop)
    return dev_prop


def register_status_getter(getter: type[GetJsonStatus]) -> type[GetJsonStatus]:
    """Decorate a function to register a status getter."""
    if getter not in CLIMATE_IP_STATUS_GETTER:
        CLIMATE_IP_STATUS_GETTER.append(getter)
    return getter


def create_property(
    name: str,
    node: dict[str, Any],
    connection_base: Any,
    controller: Any,
    status_getter: Any | None = None,
) -> Any | None:
    """Create a device property from a YAML node. Returns None if no match."""
    for prop in CLIMATE_IP_PROPERTIES:
        if CONFIG_TYPE in node:
            if prop.match_type(node[CONFIG_TYPE]):
                op = prop(name, connection_base, controller, status_getter)
                if op.load_from_yaml(node):
                    return op
    return None


def create_status_getter(
    name: str, node: dict[str, Any], connection_base: Any, controller: Any
) -> Any | None:
    """Create a status getter from a YAML node. Returns None if no match."""
    for getter in CLIMATE_IP_STATUS_GETTER:
        if CONFIG_TYPE in node:
            if getter.match_type(node[CONFIG_TYPE]):
                g = getter(name, connection_base, controller)
                if g.load_from_yaml(node):
                    return g
    return None


@register_property
class DeviceProperty:
    """Base class for a device property (read-only or read-write)."""

    def __init__(
        self,
        name: str,
        connection: ConnectionWithParams,
        controller: Any,
        status_getter: Any | None = None,
    ) -> None:
        """Initialise the device property."""
        self._name = name
        self._value: Any = None
        self._connection = connection
        self._controller = controller
        self._status_getter = status_getter
        self._status_template: Template | None = None
        self._id = name
        self._connection_template: Template | None = None
        self._validation_template: Template | None = None
        self._status_template_raw: Any = None
        self._connection_template_raw: Any = None
        self._validation_template_raw: Any = None
        self._device_state: dict[str, Any] | None = None
        self._state_node: str | None = None
        self._type: str | None = None

        self._friendly_name: str | None = None
        self._device_class: str | None = None
        self._unit_of_measurement: str | None = None
        self._state_class: SensorStateClass | None = None
        self._entity_category: str | None = None
        self._feature_flag: ClimateEntityFeature | None = None
        self._config: dict[str, Any] = {}

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this property handles the given type."""
        return prop_type == PROPERTY_TYPE_STRING

    @property
    def log_prefix(self) -> str:
        """Get the log prefix from the controller for consistent logging."""
        return str(self._controller.log_prefix)

    @property
    def id(self) -> str:
        """Return the property ID."""
        return self._id

    def _resolve_raw_state_source(self) -> dict[str, Any] | None:
        """Resolve the raw state dictionary from the controller or status getter.

        Priority order:
        1. controller.pure_device_state — Unmutated network state representing
           the true state before this command.
        2. controller.device_state — Last parsed device state from poller.
        3. _status_getter.value — Live status getter dict.
        4. Other fallbacks (status property, dataclass conversion).
        """
        if self._controller is not None:
            if (
                isinstance(self._controller.pure_device_state, dict)
                and self._controller.pure_device_state
            ):
                return self._controller.pure_device_state
            if (
                isinstance(self._controller.device_state, dict)
                and self._controller.device_state
            ):
                return self._controller.device_state

        if self._status_getter is not None and isinstance(
            self._status_getter.value, dict
        ):
            return self._status_getter.value

        if self._controller is not None:
            status_prop = self._controller.get_property(KEY_STATUS)
            if status_prop is not None and isinstance(status_prop.value, dict):
                return status_prop.value

        # 4. Raw device_state fallback (dataclass / dict)
        if isinstance(self._device_state, dict):
            return self._device_state
        if dataclasses.is_dataclass(self._device_state):
            return dataclasses.asdict(self._device_state)
        return None

    def _route_to_subdevice(self, raw_dict: dict[str, Any]) -> dict[str, Any]:
        """Route the raw state to the correct subdevice if applicable."""
        device_id = (
            self._controller.device_id
            if self._controller is not None
            else FALLBACK_DEVICE_ID
        )
        loader = self._controller.loader if self._controller is not None else None
        cache = loader.parsed_yaml_cache if loader is not None else {}
        id_map = (
            cache.get(device_id, {}).get(KEY_DEVICE_CONFIG, {}).get(KEY_IDENTIFIERS, {})
        )
        path = id_map.get(KEY_PATH_TO_DEVICES)

        if path is None:
            return raw_dict

        devices_list = get_value_by_path(raw_dict, path)
        if not isinstance(devices_list, list) or len(devices_list) == 0:
            return raw_dict

        id_path = id_map.get(CONF_SUBDEVICE_ID, [CONF_SUBDEVICE_ID])

        # Strict match by device_id
        for dev in devices_list:
            dev_id = get_value_by_path(dev, id_path)
            if dev_id is not None and str(dev_id) == str(device_id):
                return dev if isinstance(dev, dict) else {}

        # Fallback: Find the first AC unit (must have a 'Mode' key to exclude WiFi-Kit)
        for dev in devices_list:
            if isinstance(dev, dict) and KEY_DEVICE_MODE in dev:
                return dev

        # Absolute fallback
        first_dev = devices_list[0]
        return first_dev if isinstance(first_dev, dict) else {}

    @property
    def _raw_device_state(self) -> dict[str, Any]:
        """Safely extract the raw JSON dictionary required by YAML templates."""
        raw_dict = self._resolve_raw_state_source()
        if raw_dict is None:
            return {}
        return self._route_to_subdevice(raw_dict)

    def is_valid(self, device_state: dict[str, Any] | None) -> bool:
        """Return True if this property is valid for the given device state."""
        self._device_state = device_state
        if self.validation_template is None or device_state is None:
            return True

        try:
            v = render_template(
                self.validation_template, device_state=self._raw_device_state
            )
            return str(v).strip().lower() == VALIDATION_SUCCESS_TOKEN
        except (TemplateError, TypeError, ValueError) as e:
            _LOGGER.error(
                "%s Error rendering validation template for %s: %s",
                self.log_prefix,
                self.id,
                e,
            )  # pragma: no mutate
            return False

    @property
    def status_template(self) -> Template | None:
        """Return the status Jinja2 template."""
        return self._status_template

    @property
    def value(self) -> Any:
        """Return the current value."""
        return self._value

    @value.setter
    def value(self, val: Any) -> None:
        """Set the current value."""
        self._value = val

    @property
    def name(self) -> str:
        """Return the friendly name of the property, or the ID if not set."""
        return self._friendly_name if self._friendly_name is not None else self._name

    @property
    def all_values(self) -> list[Any]:
        """Return all available values for this property if applicable."""
        return []

    @property
    def device_class(self) -> str | None:
        """Return the device class."""
        return self._device_class

    @property
    def feature_flag(self) -> ClimateEntityFeature | None:
        """Return the feature flag associated with this property."""
        return self._feature_flag

    def set_device_state_for_values(self, device_state: dict[str, Any]) -> None:
        """
        Optional override hook.
        Update internal state or values based on the current device state.
        Subclasses should override this method if they need to update dynamically.
        """
        pass

    @property
    def unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def entity_category(self) -> str | None:
        """Return the entity category."""
        return self._entity_category

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return the state class."""
        return self._state_class

    def set_unit_of_measurement(self, unit: str) -> None:
        """Set the static unit of measurement, converting temperature aliases."""
        converted_unit = _normalize_unit(unit)
        self._unit_of_measurement = converted_unit

    def get_connection(self, value: Any) -> Any:
        """Return the connection for the given value."""
        return self._connection

    @property
    def connection_template(self) -> Template | None:
        """Return the connection Jinja2 template."""
        return self._connection_template

    @property
    def validation_template(self) -> Template | None:
        """Return the validation Jinja2 template."""
        return self._validation_template

    @property
    def state_node(self) -> str | None:
        """Return the state node path mapped in the device state structure."""
        return self._state_node

    @property
    def value_is_string(self) -> bool:
        """Return True if the property value should be treated as a string."""
        return (
            self._type
            in (
                PROPERTY_TYPE_STRING,
                PROPERTY_TYPE_ENUM,
            )
            or self.device_class == SensorDeviceClass.ENUM
        )

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if node is None:
            return False

        self._config = dict(node)
        self._type = node.get(CONFIG_TYPE)

        state_node = node.get(CONFIG_STATE_NODE)
        if state_node is not None:
            self._state_node = state_node

        tmpl = node.get(CONFIG_DEVICE_STATUS_TEMPLATE)
        if tmpl is not None:
            self._status_template_raw = tmpl
            self._status_template = Template(tmpl, self._controller.hass)

        conn_tmpl = node.get(CONFIG_DEVICE_CONNECTION_TEMPLATE)
        if conn_tmpl is not None:
            self._connection_template_raw = conn_tmpl
            self._connection_template = Template(conn_tmpl, self._controller.hass)

        val_tmpl = node.get(CONFIG_DEVICE_VALIDATION_TEMPLATE)
        if val_tmpl is not None:
            self._validation_template_raw = val_tmpl
            self._validation_template = Template(val_tmpl, self._controller.hass)

        self._connection = self._connection.create_updated(
            node.get(CONFIG_DEVICE_CONNECTION, {})
        )
        (
            self._friendly_name,
            self._device_class,
            self._unit_of_measurement,
            self._entity_category,
        ) = (
            node.get(CONFIG_DEVICE_NAME),
            node.get(CONFIG_DEVICE_CLASS),
            node.get(CONFIG_UNIT_OF_MEASUREMENT),
            node.get(CONFIG_ENTITY_CATEGORY),
        )

        if raw_state_class := node.get(CONFIG_STATE_CLASS):
            try:
                self._state_class = SensorStateClass(raw_state_class)
            except ValueError as e:
                # Strict Fail-Fast: Corrupt YAML must abort loading.
                raise ValueError(
                    f"Invalid state_class '{raw_state_class}' in YAML"
                ) from e
        elif self._device_class is not None:
            try:
                dev_class_enum = SensorDeviceClass(self._device_class)
                if dev_class_enum in (
                    SensorDeviceClass.GAS,
                    SensorDeviceClass.ENERGY,
                    SensorDeviceClass.WATER,
                    SensorDeviceClass.CO,
                ):
                    self._state_class = SensorStateClass.TOTAL_INCREASING
                elif dev_class_enum in (
                    SensorDeviceClass.POWER,
                    SensorDeviceClass.TEMPERATURE,
                    SensorDeviceClass.HUMIDITY,
                    SensorDeviceClass.VOLTAGE,
                    SensorDeviceClass.CURRENT,
                    SensorDeviceClass.PRESSURE,
                ):
                    self._state_class = SensorStateClass.MEASUREMENT
            except ValueError as err:
                _LOGGER.warning(
                    "%s Invalid device_class '%s' cannot be mapped to state_class: %s",
                    self.log_prefix,
                    self._device_class,
                    err,
                )

        return True

    def convert_dev_to_hass(self, dev_value: Any) -> Any:
        """Convert device state value to HASS."""
        return dev_value

    def apply_optimistic_cascades(
        self, state: dict[str, Any], value: Any, _dev_val: Any = None
    ) -> None:
        """Optimistically cascade state changes based on YAML configuration."""
        property_config = self._config
        cascades = property_config.get(CONFIG_OPTIMISTIC_CASCADES)

        if cascades is None or not isinstance(cascades, list):
            return

        val_str = str(value).lower() if value is not None else ""

        target_nodes = [state]
        if (
            KEY_DEVICES in state
            and isinstance(state[KEY_DEVICES], list)
            and len(state[KEY_DEVICES]) > 0
            and isinstance(state[KEY_DEVICES][0], dict)
        ):
            target_nodes.append(state[KEY_DEVICES][0])

        for cascade_rule in cascades:
            if not isinstance(cascade_rule, dict):
                continue
            target_path = cascade_rule.get(CONFIG_TARGET_NODE)
            raw_value_map = cascade_rule.get(CONFIG_VALUE_MAP)

            if target_path is None or not isinstance(raw_value_map, dict):
                continue

            value_map: dict[str, Any] = {}
            for k, v in raw_value_map.items():
                if isinstance(k, bool):
                    value_map["off" if not k else "on"] = v
                    value_map[str(k).lower()] = v
                else:
                    value_map[str(k).lower()] = v

            new_val = value_map.get(val_str)
            if new_val is None:
                new_val = value_map.get(KEY_DEFAULT)

            if new_val is not None:
                path_parts = str(target_path).split(".")

                for target_node in target_nodes:
                    current_level = target_node
                    for part in path_parts[:-1]:
                        if part not in current_level or not isinstance(
                            current_level[part], dict
                        ):
                            current_level[part] = {}
                        current_level = current_level[part]

                    final_key = path_parts[-1]
                    current_level[final_key] = new_val

    def calculate_value_from_state(self, device_state: dict[str, Any] | None) -> Any:
        """Dry-run calculation of the property value."""
        v = None
        if self.status_template is not None and device_state is not None:
            try:
                v = render_template(self.status_template, device_state=device_state)
            except (TemplateError, TypeError, ValueError) as e:
                _LOGGER.error(
                    "%s Status template evaluation failed for %s: %s",
                    self.log_prefix,
                    self.id,
                    e,
                )
                raise HomeAssistantError(
                    f"Template evaluation failed for {self.id}: {e}"
                ) from e

        if v is not None:
            return self.convert_dev_to_hass(v)
        return None

    async def async_update_state(
        self, device_state_override: dict[str, Any] | None = None, *_args: Any
    ) -> Any:
        """Update property from device state and return current value."""
        device_state: dict[str, Any] | None
        if device_state_override is not None:
            device_state = device_state_override
        elif self._status_getter and isinstance(self._status_getter.value, dict):
            device_state = self._status_getter.value
        else:
            device_state = None

        self._device_state = device_state
        v = self.calculate_value_from_state(device_state)
        if v is not None:
            self.value = v
        return self.value

    async def async_set_value(self, v: Any, device_id: str | None = None) -> bool:
        """Set property value on device."""
        return False

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return a dictionary with property attributes."""
        return {self.id: self.value}


@register_status_getter
class GetJsonStatus(DeviceProperty):
    """Status getter that fetches device state as JSON."""

    def __init__(
        self,
        name: str,
        connection: ConnectionWithParams,
        controller: Any,
        status_getter: Any | None = None,
    ) -> None:
        """Initialise the JSON status getter."""
        super().__init__(name, connection, controller, self)
        self._json_status: dict[str, Any] | None = None
        self._attrs: dict[str, Any] = {}

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this getter handles the given type."""
        return prop_type == STATUS_GETTER_JSON

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load the connection details from the 'status' node in YAML."""
        super_result = super().load_from_yaml(node)

        if (
            self._connection is not None
            and self._connection.is_async_native
            and self._connection_template is None
        ):
            conn_tmpl = (
                getattr(self._connection, "connection_template", None)
                or getattr(self._connection, "_connection_template", None)
            )
            if conn_tmpl is not None:
                self._connection_template = conn_tmpl
            else:
                _LOGGER.debug(
                    "%s [GetJsonStatus] No connection_template found for aiohttp. Creating a default one.",
                    self.log_prefix,
                )  # pragma: no mutate
                default_template_str = DEFAULT_JSON_STATUS_PAYLOAD
                self._connection_template = Template(
                    default_template_str, self._controller.hass
                )
        return super_result

    def calculate_value_from_state(self, device_state: dict[str, Any] | None) -> Any:
        """Calculate the structured JSON status from raw device state."""
        if device_state is None:
            return None

        if self.status_template is not None:
            try:
                v = render_template(self.status_template, device_state=device_state)
                if isinstance(v, str):
                    v = v.strip()
                    try:
                        return json_loads(v)
                    except JSON_DECODE_EXCEPTIONS:
                        return v
                return v
            except (TemplateError, TypeError, ValueError) as e:
                _LOGGER.error(
                    "%s [GetJsonStatus] Status template evaluation failed: %s",
                    self.log_prefix,
                    e,
                )
                raise HomeAssistantError(
                    f"Template evaluation failed for {self.id}: {e}"
                ) from e
        return device_state

    async def async_update_state(
        self, device_state_override: dict[str, Any] | None = None, *_args: Any
    ) -> Any:
        """Fetch the device state asynchronously."""
        device_state_result: dict[str, Any] | None = None  # pragma: no mutate
        connection = self.get_connection(None)

        if connection is None:
            _LOGGER.error(
                "%s [GetJsonStatus] Connection object is None! Cannot proceed.",
                self.log_prefix,
            )  # pragma: no mutate
            return None

        if connection.is_async_native:
            if self.connection_template is None:
                _LOGGER.error(
                    "%s [GetJsonStatus] Connection template is missing for async execution.",
                    self.log_prefix,
                )  # pragma: no mutate
                return None

            render_context: dict[str, Any] = dict(connection._params)

            cfg = connection.config if isinstance(connection.config, dict) else {}
            duid_from_cfg = cfg.get(KEY_DUID)

            duid_for_render = (
                self._controller.device_id
                if self._controller is not None
                else duid_from_cfg
            )
            if duid_for_render is None:
                raise ValueError(
                    "Could not resolve device_id/duid for async command parameter rendering"
                )

            render_context[TMPL_VAR_DEVICE_ID] = duid_for_render
            render_context.setdefault(KEY_DUID, duid_for_render)

            token_from_cfg = cfg.get(CONF_TOKEN_KEY)
            if token_from_cfg is not None:
                render_context.setdefault(CONF_TOKEN_KEY, token_from_cfg)

            response_text: str | None = None  # pragma: no mutate
            params_str = render_template(self.connection_template, **render_context)
            if isinstance(params_str, dict):
                params: dict[str, Any] | None = params_str
            else:
                try:
                    loaded = json_loads(params_str)
                    params = loaded if isinstance(loaded, dict) else None
                except (ValueError, TypeError):
                    params = None

            if isinstance(params, dict):
                raw_params = connection._params
                final_params = {**raw_params, **params}
                response_text, _ = await connection.async_execute(
                    final_params.get(KEY_METHOD),
                    final_params.get(KEY_URL),
                    None,
                    final_params.get(KEY_HEADERS) or {},
                    _is_poll=True,
                )
            else:
                response_text, _ = await connection.async_execute(
                    None,
                    None,
                    params_str,
                    None,
                    _is_poll=True,
                )

            if response_text is None:
                _LOGGER.debug(
                    "%s [GetJsonStatus] No response text received.", self.log_prefix
                )  # pragma: no mutate
                return None

            try:
                loaded_state = json_loads(response_text)
                device_state_result = loaded_state if isinstance(loaded_state, dict) else None
            except JSON_DECODE_EXCEPTIONS as e:
                _LOGGER.error(
                    "%s [GetJsonStatus] JSON parsing error. Response: '%s'. Error: %s",
                    self.log_prefix,
                    response_text,
                    e,
                )  # pragma: no mutate
                return None
        else:
            device_state_result = await connection.async_execute_with_retry(
                self.connection_template, None, self.value
            )

        self.value = self.calculate_value_from_state(device_state_result)
        self._json_status = device_state_result

        if device_state_result is not None:
            self._attrs = {KEY_DEVICE_STATE: json_dumps(device_state_result)}
        else:
            self._attrs = {KEY_DEVICE_STATE: None}

        return self.value

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return a dictionary with property attributes."""
        return self._attrs


class DeviceOperation(DeviceProperty):
    """Base class for a settable device operation."""

    def _resolve_async_params(
        self,
        connection: ConnectionWithParams,
        dev_value: Any,
        duid: str | None = None,
        device_state: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve the final {method, url, json, headers} dict for an async command."""
        render_ctx = {
            TMPL_VAR_VALUE: dev_value,
            TMPL_VAR_DEVICE_ID: duid,
            KEY_DUID: duid,
            TMPL_VAR_DEVICE_STATE: device_state if device_state is not None else {},
        }
        conn_tmpl = connection._connection_template
        template_to_use = (
            self.connection_template
            if self.connection_template is not None
            else conn_tmpl
        )

        if template_to_use is not None:
            rendered = render_template(template_to_use, **render_ctx)
            if isinstance(rendered, dict):
                operation_params: dict[str, Any] | None = rendered
            else:
                try:
                    loaded_op = json_loads(rendered)
                    operation_params = loaded_op if isinstance(loaded_op, dict) else None
                except (ValueError, TypeError):
                    operation_params = None

            if not isinstance(operation_params, dict):
                return {KEY_RAW_PAYLOAD: rendered}
        else:
            raw_p = connection._params
            operation_params = (
                dict(raw_p) if raw_p is not None and len(raw_p) > 0 else None
            )

        if operation_params is None:
            _LOGGER.error(
                "%s [_resolve_async_params] No params or template found.",
                self.log_prefix,
            )  # pragma: no mutate
            return None

        base_params: dict[str, Any] = {}
        base_template = connection._connection_template
        if base_template is not None and base_template is not template_to_use:
            rendered_base = render_template(base_template, **render_ctx)
            if isinstance(rendered_base, dict):
                base_params = rendered_base
            else:
                try:
                    loaded_base = json_loads(rendered_base)
                    base_params = loaded_base if isinstance(loaded_base, dict) else {}
                except (ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "%s Base parameter template rendered invalid JSON for %s: %s",
                        self.log_prefix,
                        self.id,
                        err,
                    )
                    base_params = {}

            if not isinstance(base_params, dict):
                base_params = {}

        raw_params = connection._params
        if not isinstance(raw_params, dict):
            raw_params = {}
        fallback: dict[str, Any] = {**raw_params, **base_params}

        return {**fallback, **operation_params}

    async def async_set_value(self, v: Any, device_id: str | None = None) -> bool:
        """Set device property value asynchronously."""

        # FRONTEND SANITIZATION: Validate payload before hitting the network
        try:
            dev_value = self.convert_hass_to_dev(v)
        except ValueError as e:
            _LOGGER.warning(
                "%s Command discarded for '%s': %s", self.log_prefix, self.id, e
            )  # pragma: no mutate
            return False

        connection = self.get_connection(v)
        current_full_state = self._raw_device_state

        if connection.is_async_native:
            try:
                cfg = connection.config if isinstance(connection.config, dict) else {}
                duid_from_cfg = cfg.get(KEY_DUID)
                duid_for_render = (
                    device_id
                    if device_id is not None
                    else (
                        self._controller.device_id
                        if self._controller is not None
                        else None
                    )
                )
                if duid_for_render is None:
                    duid_for_render = duid_from_cfg
                if duid_for_render is None:
                    raise ValueError(
                        "Could not resolve device_id/duid for async command parameter rendering"
                    )

                # dev_value is already calculated and validated above
                params = self._resolve_async_params(
                    connection, dev_value, duid_for_render, current_full_state
                )

                if params is None:
                    _LOGGER.error(
                        "%s [async_set_value] Could not resolve command parameters.",
                        self.log_prefix,
                    )  # pragma: no mutate
                    return False

                if params.get(KEY_RAW_PAYLOAD) is not None:
                    _LOGGER.debug(
                        "%s [async_set_value] Sending raw (non-JSON) payload.",
                        self.log_prefix,
                    )  # pragma: no mutate
                    await connection.async_execute(
                        None, None, params[KEY_RAW_PAYLOAD], None
                    )
                    return True

                data_payload = (
                    json_dumps(params[KEY_JSON_PAYLOAD])
                    if KEY_JSON_PAYLOAD in params
                    else None
                )
                method = params.get(KEY_METHOD)
                url = params.get(KEY_URL)

                if method is None or url is None:
                    raise ValueError(
                        f"Strict routing failed: Missing method or url in YAML configuration for {self.id}"
                    )

                response, _ = await connection.async_execute(
                    method,
                    url,
                    data_payload,
                    params.get(KEY_HEADERS) or {},
                    device_state=current_full_state,
                )
                if response is not None:
                    return True
                return False
            except (CannotConnect, AuthError) as e:
                raise HomeAssistantError(
                    f"Connection error: could not set value for {self.id}"
                ) from e  # pragma: no mutate
            except (TimeoutError, OSError) as e:
                raise HomeAssistantError(
                    f"Unexpected error when setting {self.id}"
                ) from e  # pragma: no mutate
        else:
            try:
                await connection.async_execute_with_retry(
                    self.connection_template, dev_value, current_full_state, device_id
                )
                return True
            except (CannotConnect, AuthError) as e:
                raise HomeAssistantError(
                    f"Connection error: could not set value for {self.id}"
                ) from e  # pragma: no mutate

    def match_value(self, value: Any) -> bool:
        """Check if value matches the operation. True if the value is correct."""
        return False

    def convert_hass_to_dev(self, ha_value: Any) -> Any:
        """Convert HASS state value to the device's expected value."""
        return ha_value


class BasicDeviceOperation(DeviceOperation):
    """Device operation that maps a fixed set of HA values to device values."""

    def __init__(
        self,
        name: str,
        connection: ConnectionWithParams,
        controller: Any,
        status_getter: Any | None = None,
    ) -> None:
        """Initialise the basic device operation."""
        super().__init__(name, connection, controller, status_getter)
        self._values_dev_to_ha_map: dict[Any, Any] = {}
        self._values_ha_to_dev_map: dict[Any, Any] = {}
        self._values: list[Any] = []
        self._value_connections_map: dict[Any, Any] = {}
        self._value_validation_templates: dict[Any, Template] = {}
        self._last_valid_values: list[Any] = []
        self._feature_flag: ClimateEntityFeature | None = None

        self._values_cache: dict[str, list[Any]] = {}

    def get_connection(self, value: Any) -> Any:
        """Return the connection for a specific value, or the default connection."""
        return self._value_connections_map.get(value, self._connection)

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if super().load_from_yaml(node):
            self._feature_flag = YAML_NAME_TO_HA_FEATURE.get(self._name)

            if node is not None:
                node_values = node.get(CONFIG_DEVICE_OPERATION_VALUES)
                if not isinstance(node_values, dict) or len(node_values) == 0:
                    return False

                for ha_value in node_values.keys():
                    node_value = node_values[ha_value]
                    connection_node = node_value.get(
                        CONFIG_DEVICE_CONNECTION, node_value
                    )
                    r = self._connection.create_updated(connection_node)

                    self._value_connections_map[ha_value] = r
                    self._values.append(ha_value)
                    if CONFIG_DEVICE_OPERATION_VALUE in node_value:
                        dev_value = node_value[CONFIG_DEVICE_OPERATION_VALUE]
                        self._values_dev_to_ha_map[dev_value] = ha_value
                        self._values_ha_to_dev_map[ha_value] = dev_value

                    if CONFIG_DEVICE_VALIDATION_TEMPLATE in node_value:
                        self._value_validation_templates[ha_value] = Template(
                            node_value[CONFIG_DEVICE_VALIDATION_TEMPLATE],
                            self._controller.hass,
                        )

                return True
        return False

    def set_device_state_for_values(self, device_state: dict[str, Any] | None) -> None:
        """
        Optional override hook.
        Update the operation's known device state and invalidate the valid values cache.
        """
        self._device_state = device_state
        self._values_cache.clear()

    @property
    def all_values(self) -> list[Any]:
        """Return the complete, unfiltered list of values."""
        return list(self._values)

    def _resolve_hvac_node(self) -> str | None:
        """Resolve the current HVAC node state."""
        if self._controller is None or not isinstance(self._device_state, dict):
            return None

        hvac_prop = self._controller.get_property_object(ATTR_HVAC_MODE)
        if hvac_prop is None or not isinstance(hvac_prop.state_node, str):
            loader = self._controller.loader
            if loader is not None and isinstance(loader.operations, dict):
                hvac_prop = loader.operations.get(
                    ATTR_HVAC_MODE
                ) or loader.operations.get(KEY_HVAC)

        if (
            hvac_prop is None
            or not isinstance(hvac_prop.state_node, str)
            or not hvac_prop.state_node
            or self._device_state is None
        ):
            return None

        return get_value_by_path(self._device_state, hvac_prop.state_node.split("."))

    def _compute_cache_key(self, hvac_node: str | None) -> str:
        """Compute a deterministic cache key."""
        cache_key_prop = (
            self._controller.get_property(ATTR_HVAC_MODE)
            if self._controller is not None
            else None
        )
        cache_key_id = DEFAULT_CACHE_KEY_ID

        if isinstance(cache_key_prop, DeviceProperty):
            cache_key_id = cache_key_prop.id
        elif isinstance(cache_key_prop, str):
            cache_key_id = cache_key_prop

        return (
            f"{cache_key_id}{ID_DELIMITER}{hvac_node}"
            if hvac_node is not None
            else cache_key_id
        )

    def _validate_and_cache(self, cache_key: str) -> list[Any]:
        """Validate all values against the current state and cache them."""
        if cache_key in self._values_cache:
            return self._values_cache[cache_key]

        valid_values = [
            ha_value
            for ha_value in self._values
            if self.is_value_valid(ha_value, self._device_state)
        ]
        self._values_cache[cache_key] = valid_values
        return valid_values

    def _detect_value_changes(self, valid_values: list[Any]) -> None:
        """Detect if the valid values have changed and trigger updates if necessary."""
        if (
            valid_values
            and self._last_valid_values
            and sorted(valid_values) != sorted(self._last_valid_values)
        ):
            _LOGGER.debug(
                "%s Valid values for '%s' changed to: %s",
                self.log_prefix,
                self.name,
                valid_values,
            )  # pragma: no mutate
            if self._controller is not None and self._id == ATTR_FAN_MODE:
                _LOGGER.debug(
                    "%s Setting fan_modes_list_changed_pending_flicker flag",
                    self.log_prefix,
                )  # pragma: no mutate
                self._controller.fan_modes_list_changed_pending_flicker = True

    @property
    def values(self) -> list[Any]:
        """Return a list of valid values, which can be dynamic."""
        if len(self._value_validation_templates) == 0:
            return list(self._values)

        hvac_node = self._resolve_hvac_node()
        cache_key = self._compute_cache_key(hvac_node)
        valid_values = self._validate_and_cache(cache_key)

        self._detect_value_changes(valid_values)
        self._last_valid_values = list(valid_values)
        return list(valid_values)

    def match_value(self, value: Any) -> bool:
        """Check if value matches the operation. True if the value is correct."""
        return value in self._values_ha_to_dev_map

    def convert_dev_to_hass(self, dev_value: Any) -> Any:
        """Convert device state value to its HASS representation."""
        if isinstance(dev_value, str):
            dev_value = dev_value.strip()
        return self._values_dev_to_ha_map.get(dev_value, dev_value)

    def convert_hass_to_dev(self, ha_value: Any) -> Any:
        """Convert HASS state value to the device's expected value."""
        return self._values_ha_to_dev_map.get(ha_value, ha_value)

    def is_value_valid(
        self, ha_value: Any, device_state: dict[str, Any] | None
    ) -> bool:
        """Check if a specific HA value is valid for the given device state."""
        template = self._value_validation_templates.get(ha_value)
        if template is None:
            return True

        if device_state is None:
            return False

        rendered = render_template(template, device_state=device_state)
        return str(rendered).lower() == VALIDATION_SUCCESS_TOKEN


@register_property
class ModeOperation(BasicDeviceOperation):
    """Operation representing a mode selection (hvac, fan, swing, preset)."""

    def __init__(
        self,
        name: str,
        connection: ConnectionWithParams,
        controller: Any,
        status_getter: Any | None = None,
    ) -> None:
        """Initialise the mode operation and resolve the HA property ID."""
        super().__init__(name, connection, controller, status_getter)

        if name in HA_MODE_ATTRIBUTES:
            self._id = name
        elif name in LEGACY_YAML_TO_ATTR_MAP:
            self._id = LEGACY_YAML_TO_ATTR_MAP[name]
        else:
            self._id = f"{name}{MODE_PROPERTY_SUFFIX}"

        self._feature_flag = YAML_NAME_TO_HA_FEATURE.get(self._name)

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this operation handles the given type."""
        return prop_type == PROPERTY_TYPE_MODE

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return a dictionary with the current mode and available modes list."""
        mode_map = {
            ATTR_HVAC_MODE: ATTR_HVAC_MODES,
            ATTR_FAN_MODE: ATTR_FAN_MODES,
            ATTR_PRESET_MODE: ATTR_PRESET_MODES,
            ATTR_SWING_MODE: ATTR_SWING_MODES,
        }
        list_attribute_name = mode_map.get(self._id)
        if list_attribute_name is None:
            list_attribute_name = f"{self.id}s"

        return {
            self.id: self.value,
            list_attribute_name: self.values,
        }


@register_property
class UniqueIdProperty(DeviceProperty):
    """Property representing a unique identifier.

    Used as a type discriminator in sensor.py to bypass numeric parsing
    and preserve the raw string value (e.g. MAC addresses, device IDs).
    """

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this property handles the given type."""
        return prop_type == PROPERTY_TYPE_UNIQUE_ID


@register_property
class SwitchOperation(BasicDeviceOperation):
    """Operation representing an on/off switch."""

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this operation handles the given type."""
        return prop_type == PROPERTY_TYPE_SWITCH

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if super().load_from_yaml(node):
            if STATE_OFF in self._values_ha_to_dev_map:
                self._values_ha_to_dev_map[False] = self._values_ha_to_dev_map[
                    STATE_OFF
                ]
            if STATE_ON in self._values_ha_to_dev_map:
                self._values_ha_to_dev_map[True] = self._values_ha_to_dev_map[STATE_ON]
            return True
        return False


@register_property
class BasicNumericOperation(DeviceOperation):
    """Base operation for numeric (integer/float) values with optional min/max."""

    def __init__(
        self,
        name: str,
        connection: ConnectionWithParams,
        controller: Any,
        status_getter: Any | None = None,
    ) -> None:
        """Initialise the basic numeric operation."""
        super().__init__(name, connection, controller, status_getter)
        self._min: float | None = None
        self._max: float | None = None
        self._value: float | None = None

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this operation handles the given type."""
        return prop_type == PROPERTY_TYPE_NUMBER

    @property
    def value(self) -> float | None:
        """Return the current value as a float, strictly validating numeric types."""
        if self._value is None or isinstance(self._value, bool):
            return None
        if isinstance(self._value, (int, float)):
            return float(self._value)
        if isinstance(self._value, str):
            try:
                return float(self._value.strip())
            except ValueError:
                return None
        return None

    @value.setter
    def value(self, val: Any) -> None:
        """Set the current value."""
        self._value = val

    def match_value(self, value: Any) -> bool:
        """Check if value matches the operation."""
        if isinstance(value, bool):
            return False
        try:
            converted = float(self.convert_hass_to_dev(float(value)))
            return round(converted, 2) == round(float(value), 2)
        except (ValueError, TypeError):
            return False

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if not node or super().load_from_yaml(node) is False:
            return False

        # node is guaranteed not to be None here
        self._min = node.get(CONFIG_DEVICE_OPERATION_NUMBER_MIN)
        self._max = node.get(CONFIG_DEVICE_OPERATION_NUMBER_MAX)
        return True

    def convert_hass_to_dev(self, ha_value: Any) -> Any:
        """Convert HASS state value to the device's expected value, clamped to min/max."""
        if isinstance(ha_value, bool):
            raise ValueError(f"Invalid numeric value: {ha_value}")
        try:
            v = float(ha_value)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Invalid numeric value: {ha_value}") from err

        min_bound = self._min if self._min is not None else float("-inf")
        max_bound = self._max if self._max is not None else float("inf")
        return max(min_bound, min(v, max_bound))


@register_property
class TemperatureOperation(BasicNumericOperation):
    """Operation for temperature values with unit conversion support."""

    def __init__(
        self,
        name: str,
        connection: ConnectionWithParams,
        controller: Any,
        status_getter: Any | None = None,
    ) -> None:
        """Initialise the temperature operation."""
        super().__init__(name, connection, controller, status_getter)
        self._unit_template: Template | None = None
        self._device_unit = UnitOfTemperature.CELSIUS
        self._hass_unit = UnitOfTemperature.CELSIUS

    def set_device_unit(self, unit: str | UnitOfTemperature) -> None:
        """Set the native unit used by the device."""
        self._device_unit = _parse_temperature_unit(unit)

    def set_hass_unit(self, unit: str | UnitOfTemperature) -> None:
        """Set the display unit used by Home Assistant."""
        self._hass_unit = _parse_temperature_unit(unit)
        self._unit_of_measurement = self._hass_unit

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this operation handles the given type."""
        return prop_type == PROPERTY_TYPE_TEMP

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if super().load_from_yaml(node) is False:
            return False

        if node is not None and CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE in node:
            self._unit_template = Template(
                node[CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE], self._controller.hass
            )
        return True

    def calculate_value_from_state(self, device_state: dict[str, Any] | None) -> Any:
        """Calculate temperature without side-effects, resolving unit locally."""
        device_unit = self._device_unit
        if self._unit_template is not None and device_state is not None:
            try:
                unit = render_template(self._unit_template, device_state=device_state)
                device_unit = _parse_temperature_unit(unit)
            except TemplateError as err:
                _LOGGER.error(
                    "%s Error rendering unit template for %s: %s",
                    self.log_prefix,
                    self.id,
                    err,
                )
                raise HomeAssistantError(
                    f"Error rendering unit template: {err}"
                ) from err
            except (TypeError, ValueError) as e:
                _LOGGER.error("Error parsing unit template: %s", e)
                raise HomeAssistantError(f"Error parsing unit template: {e}") from e

        v = None
        if self.status_template is not None and device_state is not None:
            try:
                v = render_template(self.status_template, device_state=device_state)
                if isinstance(v, str):
                    v = v.strip()
            except TemplateError as err:
                _LOGGER.error(
                    "%s Error rendering status template for %s: %s",
                    self.log_prefix,
                    self.id,
                    err,
                )
                raise HomeAssistantError(
                    f"Error rendering status template: {err}"
                ) from err
            except (TypeError, ValueError) as e:
                _LOGGER.error(
                    "%s Error rendering status template for %s: %s",
                    self.log_prefix,
                    self.id,
                    e,
                )
                raise HomeAssistantError(f"Error rendering status template: {e}") from e

        if v is not None:
            return self._convert_dev_to_hass_with_unit(v, device_unit)
        return None

    async def async_update_state(
        self, device_state_override: dict[str, Any] | None = None, *_args: Any
    ) -> Any:
        """Update temperature state, resolving unit from device if templated."""
        device_state: dict[str, Any] | None
        if device_state_override is not None:
            device_state = device_state_override
        elif self._status_getter and isinstance(self._status_getter.value, dict):
            device_state = self._status_getter.value
        else:
            device_state = None

        if self._unit_template is not None and device_state is not None:
            try:
                unit = render_template(self._unit_template, device_state=device_state)
                self._device_unit = _parse_temperature_unit(unit)
            except TemplateError as err:
                raise HomeAssistantError(
                    f"Could not render unit template: {err}"
                ) from err
            except (TypeError, ValueError) as e:
                raise HomeAssistantError(f"Could not render unit template: {e}") from e

        v = self.calculate_value_from_state(device_state)
        if v is not None:
            self.value = v
        return self.value

    def _convert_dev_to_hass_with_unit(
        self, dev_value: Any, device_unit: str
    ) -> float | None:
        """Convert device temperature to HASS unit using a specific device unit."""
        if dev_value is None or isinstance(dev_value, bool):
            return None
        try:
            raw_converted = float(
                TemperatureConverter.convert(
                    float(dev_value), device_unit, self._hass_unit
                )
            )
            return raw_converted
        except (ValueError, TypeError):
            return None

    def convert_dev_to_hass(self, dev_value: Any) -> float | None:
        """Convert device temperature to HASS unit."""
        return self._convert_dev_to_hass_with_unit(dev_value, self._device_unit)

    def convert_hass_to_dev(self, ha_value: Any) -> float:
        """Convert HASS temperature to device unit, clamped to min/max."""
        if isinstance(ha_value, bool):
            raise ValueError(f"Invalid payload: Cannot set temperature to '{ha_value}'")
        try:
            # Mandatory strict sanitization.
            v = float(ha_value)
        except (ValueError, TypeError) as e:
            # Fail-Fast: Reject setting temperature to "unknown".
            # Caught safely by try/except block in async_set_value.
            raise ValueError(
                f"Invalid payload: Cannot set temperature to '{ha_value}'"
            ) from e

        if self._min is not None:
            v = max(v, self._min)
        if self._max is not None:
            v = min(v, self._max)

        return float(
            TemperatureConverter.convert(v, self._hass_unit, self._device_unit)
        )
