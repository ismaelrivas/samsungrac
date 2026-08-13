# pylint: disable=too-many-branches,too-many-instance-attributes
"""Device property classes for the climate_ip integration."""

from __future__ import annotations

import ast
import dataclasses
import logging
from typing import Any, final

from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
)
from homeassistant.components.sensor import SensorStateClass
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, UnitOfTemperature
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
    CONFIG_STATE_CLASS,
    CONFIG_STATE_NODE,
    CONFIG_TYPE,
    CONFIG_UNIT_OF_MEASUREMENT,
    DEFAULT_CACHE_KEY_ID,
    DEFAULT_JSON_STATUS_PAYLOAD,
    DEGREE_SYMBOL,
    FALLBACK_DEVICE_ID,
    ID_DELIMITER,
    KEY_DEVICE_CONFIG,
    KEY_DEVICE_MODE,
    KEY_DUID,
    KEY_HEADERS,
    KEY_HVAC,
    KEY_IDENTIFIERS,
    KEY_METHOD,
    KEY_PATH_TO_DEVICES,
    KEY_RAW_PAYLOAD,
    KEY_STATUS,
    KEY_URL,
    LEGACY_YAML_TO_ATTR_MAP,
    MEASUREMENT_DEVICE_CLASSES,
    MODE_PROPERTY_SUFFIX,
    PROPERTY_TYPE_ENUM,
    PROPERTY_TYPE_MODE,
    PROPERTY_TYPE_NUMBER,
    PROPERTY_TYPE_STRING,
    PROPERTY_TYPE_SWITCH,
    PROPERTY_TYPE_TEMP,
    PROPERTY_TYPE_UNIQUE_ID,
    STATUS_GETTER_JSON,
    TEMP_UNIT_CELSIUS_ALIASES,
    TEMP_UNIT_FAHRENHEIT_ALIASES,
    TOTAL_INCREASING_DEVICE_CLASSES,
    VALIDATION_SUCCESS_TOKEN,
    YAML_NAME_TO_HA_FEATURE,
)
from .exceptions import AuthError, CannotConnect
from .helpers import get_value_by_path

_LOGGER = logging.getLogger(__name__)


def render_template(template: Template | str | Any, **kwargs: Any) -> Any:
    """Render a Jinja2 template strictly using async execution when available within the event loop."""
    if template is None:
        return None
    if isinstance(template, str):
        return template
    async_render = getattr(template, "async_render", None)
    if callable(async_render):
        return async_render(kwargs, parse_result=True)
    render_func = getattr(template, "render", None)
    if callable(render_func):
        return render_func(**kwargs)
    return str(template)


def _parse_temperature_unit(unit: str | UnitOfTemperature | Any, strict: bool = False) -> Any:
    """Strictly parse and validate temperature unit strings."""
    if isinstance(unit, UnitOfTemperature):
        return unit
    if isinstance(unit, bool) or not isinstance(unit, str):
        if strict:
            raise ValueError(f"Invalid temperature unit: {unit}")
        return UnitOfTemperature.CELSIUS

    u = unit.replace(DEGREE_SYMBOL, "").strip().upper()
    if u in TEMP_UNIT_CELSIUS_ALIASES:
        return UnitOfTemperature.CELSIUS
    if u in TEMP_UNIT_FAHRENHEIT_ALIASES:
        return UnitOfTemperature.FAHRENHEIT

    if strict:
        raise ValueError(f"Invalid temperature unit: {unit}")
    return unit


HA_MODE_ATTRIBUTES: final[frozenset[str]] = frozenset({
    ATTR_HVAC_MODE,
    ATTR_FAN_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
})

CLIMATE_IP_PROPERTIES: list[type] = []
CLIMATE_IP_STATUS_GETTER: list[type] = []


def register_property(dev_prop: type) -> type:
    """Decorate a function to register a property."""
    CLIMATE_IP_PROPERTIES.append(dev_prop)
    return dev_prop


def register_status_getter(getter: type) -> type:
    """Decorate a function to register a status getter."""
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
            if prop.match_type(node[CONFIG_TYPE]):  # type: ignore[attr-defined]
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
            if getter.match_type(node[CONFIG_TYPE]):  # type: ignore[attr-defined]
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
        connection: Any,
        controller: Any,
        status_getter: Any | None = None,
    ) -> None:
        """Initialise the device property."""
        self._name = name
        self._value: Any = STATE_UNKNOWN
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

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this property handles the given type."""
        return prop_type == PROPERTY_TYPE_STRING

    @property
    def log_prefix(self) -> str:
        """Get the log prefix from the controller for consistent logging."""
        return self._controller.log_prefix

    @property
    def id(self) -> str:
        """Return the property ID."""
        return self._id

    @property
    def _raw_device_state(self) -> dict[str, Any]:
        """Safely extract the raw JSON dictionary required by YAML templates."""
        raw_dict = None
        if self._controller is not None:
            ctrl_pure = self._controller.pure_device_state
            if isinstance(ctrl_pure, dict) and len(ctrl_pure) != 0:
                raw_dict = ctrl_pure
        if raw_dict is None and self._controller is not None:
            ctrl_state = self._controller.device_state
            if isinstance(ctrl_state, dict) and len(ctrl_state) != 0:
                raw_dict = ctrl_state
        if (
            raw_dict is None
            and self._status_getter is not None
            and isinstance(self._status_getter.value, dict)
        ):
            raw_dict = self._status_getter.value
        if raw_dict is None and self._controller is not None:
            status_prop = self._controller.get_property(KEY_STATUS)
            if status_prop is not None and isinstance(status_prop.value, dict):
                raw_dict = status_prop.value
        if raw_dict is None and isinstance(self._device_state, dict):
            raw_dict = self._device_state
        if raw_dict is None:
            if dataclasses.is_dataclass(self._device_state):
                raw_dict = dataclasses.asdict(self._device_state)
            else:
                raw_dict = {}

        if isinstance(raw_dict, dict):
            device_id = self._controller.device_id if self._controller is not None else FALLBACK_DEVICE_ID
            loader = self._controller.loader if self._controller is not None else None
            cache = loader.parsed_yaml_cache if loader is not None else {}
            id_map = cache.get(device_id, {}).get(KEY_DEVICE_CONFIG, {}).get(KEY_IDENTIFIERS, {})
            path = id_map.get(KEY_PATH_TO_DEVICES)
            
            if path is None or len(path) == 0:
                return dict(raw_dict)
                
            devices_list = get_value_by_path(raw_dict, path)
            if isinstance(devices_list, list) and len(devices_list) != 0:
                id_path = id_map.get(CONF_SUBDEVICE_ID, [CONF_SUBDEVICE_ID])
                
                # Strict match by device_id
                for dev in devices_list:
                    dev_id = get_value_by_path(dev, id_path)
                    if dev_id is not None and str(dev_id) == str(device_id):
                        return dict(dev)
                
                # Fallback: Find the first AC unit (must have a 'Mode' key to exclude WiFi-Kit)
                for dev in devices_list:
                    if KEY_DEVICE_MODE in dev:
                        return dict(dev)
                        
                # Absolute fallback
                return dict(devices_list[0])
            return dict(raw_dict)
        return {}

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
        """Update internal state or values based on the current device state."""
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
        converted_unit = _parse_temperature_unit(unit, strict=False)
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
        return self._type in (
            PROPERTY_TYPE_STRING,
            PROPERTY_TYPE_ENUM,
        ) or self.device_class in (SensorDeviceClass.ENUM, SensorDeviceClass.PROBLEM)

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if node is None:
            return False

        self._type = node.get(CONFIG_TYPE)

        if state_node := node.get(CONFIG_STATE_NODE):
            self._state_node = state_node

        if tmpl := node.get(CONFIG_DEVICE_STATUS_TEMPLATE):
            self._status_template_raw = tmpl
            self._status_template = Template(tmpl, self._controller.hass)
        if tmpl := node.get(CONFIG_DEVICE_CONNECTION_TEMPLATE):
            self._connection_template_raw = tmpl
            self._connection_template = Template(tmpl, self._controller.hass)
        if tmpl := node.get(CONFIG_DEVICE_VALIDATION_TEMPLATE):
            self._validation_template_raw = tmpl
            self._validation_template = Template(tmpl, self._controller.hass)

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
        elif self._device_class in TOTAL_INCREASING_DEVICE_CLASSES:
            self._state_class = SensorStateClass.TOTAL_INCREASING
        elif self._device_class in MEASUREMENT_DEVICE_CLASSES:
            self._state_class = SensorStateClass.MEASUREMENT
        elif self._device_class is not None:
            try:
                dev_class_enum = SensorDeviceClass(self._device_class)
                if dev_class_enum in (SensorDeviceClass.GAS, SensorDeviceClass.ENERGY, SensorDeviceClass.WATER):
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
            except ValueError:
                pass

        return True

    def convert_dev_to_hass(self, dev_value: Any) -> Any:
        """Convert device state value to HASS."""
        return dev_value

    def calculate_value_from_state(self, device_state: dict[str, Any] | None) -> Any:
        """Dry-run calculation of the property value."""
        v = STATE_UNKNOWN
        if self.status_template is not None and device_state is not None:
            try:
                v = render_template(self.status_template, device_state=device_state)
            except (TemplateError, TypeError, ValueError) as e:
                _LOGGER.debug(
                    "%s Dry-run error for %s: %s", self.log_prefix, self.id, e
                )  # pragma: no mutate

        if v != STATE_UNKNOWN:
            return self.convert_dev_to_hass(v)
        return STATE_UNKNOWN

    async def async_update_state(
        self, device_state_override: dict[str, Any] | None = None, *_args: Any
    ) -> Any:
        """Update property from device state and return current value."""
        if device_state_override is not None:
            device_state = device_state_override
        else:
            device_state = self._status_getter.value if self._status_getter else None

        self._device_state = device_state
        v = self.calculate_value_from_state(device_state)
        if v != STATE_UNKNOWN:
            self.value = v
        return self.value

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
        connection: Any,
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
            conn_tmpl = getattr(self._connection, "connection_template", None)
            if conn_tmpl is None:
                conn_tmpl = getattr(self._connection, "_connection_template", None)
            if conn_tmpl is not None:
                _LOGGER.debug(
                    "%s [GetJsonStatus] Inheriting connection_template from connection object.",
                    self.log_prefix,
                )  # pragma: no mutate
                self._connection_template = conn_tmpl
            else:
                _LOGGER.debug(
                    "%s [GetJsonStatus] No connection_template found for aiohttp. Creating a default one.",
                    self.log_prefix,
                )  # pragma: no mutate
                default_template_str = DEFAULT_JSON_STATUS_PAYLOAD
                self._connection_template = Template(default_template_str, self._controller.hass)
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
                _LOGGER.debug(
                    "%s [GetJsonStatus] Dry-run error parsing status template: %s",
                    self.log_prefix,
                    e,
                )  # pragma: no mutate
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

            render_context: dict[str, Any] = getattr(connection, "_params", {}).copy()

            cfg = getattr(connection, "config", {}) if connection is not None else None
            duid_from_cfg = (
                cfg.get(KEY_DUID)
                if isinstance(cfg, dict)
                else getattr(cfg, KEY_DUID, None)
                if cfg is not None
                else None
            )
            
            duid_for_render = getattr(self._controller, "device_id", None) or duid_from_cfg
            if not duid_for_render:
                raise ValueError("Could not resolve device_id/duid for async command parameter rendering")
            
            render_context["device_id"] = duid_for_render
            render_context.setdefault(KEY_DUID, duid_for_render)
            
            token_from_cfg = (
                cfg.get(CONF_TOKEN_KEY)
                if isinstance(cfg, dict)
                else getattr(cfg, CONF_TOKEN_KEY, None)
                if cfg is not None
                else None
            )
            if token_from_cfg:
                render_context.setdefault(CONF_TOKEN_KEY, token_from_cfg)

            response_text: str | None = None  # pragma: no mutate
            params_str = render_template(self.connection_template, **render_context)
            if isinstance(params_str, dict):
                params = params_str
            else:
                try:
                    params = json_loads(params_str)
                except (ValueError, TypeError):
                    params = None

            if isinstance(params, dict):
                raw_params = getattr(connection, "_params", {})
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
                device_state_result = json_loads(response_text)
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
            self._attrs = {"device_state": json_dumps(device_state_result)}
        else:
            self._attrs = {"device_state": None}

        return self.value

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return a dictionary with property attributes."""
        return self._attrs


class DeviceOperation(DeviceProperty):
    """Base class for a settable device operation."""

    def _resolve_async_params(
        self,
        connection: Any,
        dev_value: Any,
        duid: str | None = None,
        device_state: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve the final {method, url, json, headers} dict for an async command."""
        render_ctx = {
            "value": dev_value,
            "device_id": duid,
            KEY_DUID: duid,
            "device_state": device_state if device_state is not None else {},
        }
        conn_tmpl = getattr(connection, "_connection_template", None)
        template_to_use = self.connection_template if self.connection_template is not None else conn_tmpl

        if template_to_use is not None:
            rendered = render_template(template_to_use, **render_ctx)
            if isinstance(rendered, dict):
                operation_params = rendered
            else:
                try:
                    operation_params = json_loads(rendered)
                except (ValueError, TypeError):
                    operation_params = None

            if not isinstance(operation_params, dict):
                return {KEY_RAW_PAYLOAD: rendered}
        else:
            operation_params = dict(getattr(connection, "_params", {}))

        if not operation_params:
            _LOGGER.error(
                "%s [_resolve_async_params] No params or template found.",
                self.log_prefix,
            )  # pragma: no mutate
            return None

        base_params: dict[str, Any] = {}
        base_template = getattr(connection, "_connection_template", None)
        if base_template is not None and base_template is not template_to_use:
            rendered_base = render_template(base_template, **render_ctx)
            if isinstance(rendered_base, dict):
                base_params = rendered_base
            else:
                try:
                    base_params = json_loads(rendered_base)
                except (ValueError, TypeError):
                    pass

            if not isinstance(base_params, dict):
                base_params = {}

        raw_params = getattr(connection, "_params", {})
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
                cfg = getattr(connection, "config", {})
                duid_from_cfg = cfg.get(KEY_DUID) if isinstance(cfg, dict) else getattr(cfg, KEY_DUID, None)
                duid_for_render = device_id or getattr(self._controller, "device_id", None) or duid_from_cfg
                if duid_for_render is None or len(duid_for_render) == 0:
                    raise ValueError("Could not resolve device_id/duid for async command parameter rendering")

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
                    await connection.async_execute(None, None, params[KEY_RAW_PAYLOAD], None)
                    return True

                data_payload = json_dumps(params["json"]) if "json" in params else None
                method = params.get(KEY_METHOD)
                url = params.get(KEY_URL)
                
                if method is None or url is None:
                    raise ValueError(f"Strict routing failed: Missing method or url in YAML configuration for {self.id}")
                    
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
                _LOGGER.warning(
                    "%s Failed to set value for %s: connection error: %s",
                    self.log_prefix,
                    self.id,
                    e,
                )  # pragma: no mutate
                raise HomeAssistantError(
                    f"Connection error: could not set value for {self.id}"
                ) from e  # pragma: no mutate
            except (TimeoutError, OSError) as e:
                _LOGGER.error(
                    "%s Error during async_set_value for %s: %s",
                    self.log_prefix,
                    self.id,
                    e,
                    exc_info=True,
                )  # pragma: no mutate
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
                _LOGGER.warning(
                    "%s Failed to set value for %s: connection error: %s",
                    self.log_prefix,
                    self.id,
                    e,
                )  # pragma: no mutate
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
        connection: Any,
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
                node_values = node.get(CONFIG_DEVICE_OPERATION_VALUES, {})
                if not node_values:
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
                            self._controller.hass
                        )

                return True
        return False

    def set_device_state_for_values(self, device_state: dict[str, Any] | None) -> None:
        """Set the device state to be used by the ``values`` property."""
        self._device_state = device_state
        self._values_cache.clear()

    @property
    def all_values(self) -> list[Any]:
        """Return the complete, unfiltered list of values."""
        return list(self._values)

    @property
    def values(self) -> list[Any]:
        """Return a list of valid values, which can be dynamic."""
        if not self._value_validation_templates:
            return list(self._values)

        hvac_node = None
        hvac_prop = None
        if self._controller is not None:
            if hasattr(self._controller, "get_property_object"):
                hvac_prop = self._controller.get_property_object(ATTR_HVAC_MODE)
            if hvac_prop is None or not isinstance(getattr(hvac_prop, "state_node", None), str):
                loader = getattr(self._controller, "loader", None)
                ops = getattr(loader, "operations", None)
                if isinstance(ops, dict):
                    fallback_prop = ops.get(ATTR_HVAC_MODE) or ops.get(KEY_HVAC)
                    if fallback_prop is not None:
                        hvac_prop = fallback_prop

        if hvac_prop is not None and isinstance(self._device_state, dict):
            state_node = getattr(hvac_prop, "state_node", None)
            if isinstance(state_node, str) and bool(state_node):
                hvac_node = get_value_by_path(
                    self._device_state, state_node.split(".")
                )

        cache_key_prop = self._controller.get_property(ATTR_HVAC_MODE) if self._controller is not None else None
        cache_key_id = DEFAULT_CACHE_KEY_ID
        if isinstance(cache_key_prop, DeviceProperty):
            cache_key_id = cache_key_prop.id
        elif isinstance(cache_key_prop, str):
            cache_key_id = cache_key_prop
        elif cache_key_prop is not None:
            prop_id = getattr(cache_key_prop, "id", None)
            if isinstance(prop_id, str):
                cache_key_id = prop_id

        cache_key = (
            f"{cache_key_id}{ID_DELIMITER}{hvac_node}"
            if hvac_node is not None
            else cache_key_id
        )


        if cache_key in self._values_cache:
            valid_values = self._values_cache[cache_key]
        else:
            _LOGGER.debug(
                "%s Cache miss for '%s' with key '%s'. Calculating values",
                self.log_prefix,
                self.name,
                cache_key,
            )  # pragma: no mutate
            valid_values = [
                ha_value
                for ha_value in self._values
                if self.is_value_valid(ha_value, self._device_state)
            ]
            self._values_cache[cache_key] = valid_values

        if (
            len(valid_values) != 0
            and len(self._last_valid_values) != 0
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
        connection: Any,
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
            list_attribute_name = f"{self._id}s"

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
        connection: Any,
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
        """Return the current value as a float, or None if invalid or boolean."""
        if self._value is None or isinstance(self._value, bool):
            return None
        try:
            return float(self._value)
        except (ValueError, TypeError):
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
            return self.convert_hass_to_dev(float(value)) == value
        except (ValueError, TypeError):
            return False

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if super().load_from_yaml(node) is False:
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
        connection: Any,
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
        self._device_unit = _parse_temperature_unit(unit, strict=True)

    def set_hass_unit(self, unit: str | UnitOfTemperature) -> None:
        """Set the display unit used by Home Assistant."""
        self._hass_unit = _parse_temperature_unit(unit, strict=True)
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
                node[CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE],
                self._controller.hass
            )
        return True

    def calculate_value_from_state(self, device_state: dict[str, Any] | None) -> Any:
        """Calculate temperature without side-effects, resolving unit locally."""
        device_unit = self._device_unit
        if self._unit_template is not None and device_state is not None:
            try:
                unit = render_template(self._unit_template, device_state=device_state)
                device_unit = _parse_temperature_unit(unit, strict=False)
            except TemplateError as err:
                _LOGGER.error("%s Error rendering unit template for %s: %s", self.log_prefix, self.id, err)
                raise HomeAssistantError(f"Error rendering unit template: {err}") from err
            except (TypeError, ValueError) as e:
                _LOGGER.error("Error parsing unit template: %s", e)
                raise HomeAssistantError(f"Error parsing unit template: {e}") from e

        v = STATE_UNKNOWN
        if self.status_template is not None and device_state is not None:
            try:
                v = render_template(self.status_template, device_state=device_state)
                if isinstance(v, str):
                    v = v.strip()
            except TemplateError as err:
                _LOGGER.error("%s Error rendering status template for %s: %s", self.log_prefix, self.id, err)
                raise HomeAssistantError(f"Error rendering status template: {err}") from err
            except (TypeError, ValueError) as e:
                _LOGGER.error("%s Error rendering status template for %s: %s", self.log_prefix, self.id, e)
                raise HomeAssistantError(f"Error rendering status template: {e}") from e

        if v != STATE_UNKNOWN:
            res = self._convert_dev_to_hass_with_unit(v, device_unit)
            _LOGGER.debug(
                "%s [Forensic-Temp] Calculated %s value '%s' (raw: %s, dev_unit: %s)",
                self.log_prefix,
                self.id,
                res,
                v,
                device_unit,
            )  # pragma: no mutate
            return res
        return STATE_UNKNOWN

    async def async_update_state(
        self, device_state_override: dict[str, Any] | None = None, *_args: Any
    ) -> Any:
        """Update temperature state, resolving unit from device if templated."""
        if device_state_override is not None:
            device_state = device_state_override
        else:
            device_state = self._status_getter.value if self._status_getter else None

        if self._unit_template is not None and device_state is not None:
            try:
                unit = render_template(self._unit_template, device_state=device_state)
                self._device_unit = _parse_temperature_unit(unit, strict=True)
            except TemplateError as err:
                _LOGGER.error("%s Could not render unit template for '%s': %s", self.log_prefix, self.id, err)
                raise HomeAssistantError(f"Could not render unit template: {err}") from err
            except (TypeError, ValueError) as e:
                _LOGGER.error("%s Could not render unit template for '%s': %s", self.log_prefix, self.id, e)
                raise HomeAssistantError(f"Could not render unit template: {e}") from e

        v = self.calculate_value_from_state(device_state)
        if v != STATE_UNKNOWN:
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
            raise ValueError(
                f"Invalid payload: Cannot set temperature to '{ha_value}'"
            )
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
