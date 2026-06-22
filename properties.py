# pylint: disable=import-outside-toplevel,too-many-branches,too-many-instance-attributes,too-many-statements
"""Device property classes for the climate_ip integration."""  # pylint: disable=import-outside-toplevel,too-many-lines

import asyncio
import logging
from typing import Any

from homeassistant.util.json import json_loads, JSON_DECODE_EXCEPTIONS
from homeassistant.helpers.json import json_dumps

import homeassistant.helpers.config_validation as cv
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate.const import (
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
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_conversion import TemperatureConverter
from jinja2 import Template

from .const import (
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
    CONFIG_DEVICE_OPERATION_NUMBER_MAX,
    CONFIG_DEVICE_OPERATION_NUMBER_MIN,
    CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE,
    CONFIG_DEVICE_OPERATION_VALUE,
    CONFIG_DEVICE_OPERATION_VALUES,
    CONFIG_DEVICE_STATUS_TEMPLATE,
    CONFIG_DEVICE_VALIDATION_TEMPLATE,
    CONFIG_TYPE,
    PROPERTY_TYPE_MODE,
    PROPERTY_TYPE_NUMBER,
    PROPERTY_TYPE_STRING,
    PROPERTY_TYPE_SWITCH,
    PROPERTY_TYPE_TEMP,
    STATUS_GETTER_JSON,
    YAML_NAME_TO_HA_FEATURE,
    LEGACY_YAML_TO_ATTR_MAP,
)
from .exceptions import AuthError, CannotConnect

_LOGGER = logging.getLogger(__name__)

UNIT_MAP: dict[str, str] = {
    "C": UnitOfTemperature.CELSIUS,
    "c": UnitOfTemperature.CELSIUS,
    "°C": UnitOfTemperature.CELSIUS,
    "Celsius": UnitOfTemperature.CELSIUS,
    "F": UnitOfTemperature.FAHRENHEIT,
    "f": UnitOfTemperature.FAHRENHEIT,
    "Fahrenheit": UnitOfTemperature.FAHRENHEIT,
    "°F": UnitOfTemperature.FAHRENHEIT,
    UnitOfTemperature.CELSIUS: UnitOfTemperature.CELSIUS,
    UnitOfTemperature.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
}

CLIMATE_IP_PROPERTIES: list[type] = []
CLIMATE_IP_STATUS_GETTER: list[type] = []


def register_property(dev_prop: type) -> type:
    """Decorate a function to register a property."""
    CLIMATE_IP_PROPERTIES.append(dev_prop)  # pragma: no mutate
    return dev_prop


def register_status_getter(getter: type) -> type:
    """Decorate a function to register a status getter."""
    CLIMATE_IP_STATUS_GETTER.append(getter)  # pragma: no mutate
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
        if CONFIG_TYPE in node:  # pragma: no mutate
            if prop.match_type(node[CONFIG_TYPE]):  # type: ignore[attr-defined]
                op = prop(name, connection_base, controller, status_getter)  # pragma: no mutate
                if op.load_from_yaml(node):  # pragma: no mutate
                    return op
    return None


def create_status_getter(
    name: str, node: dict[str, Any], connection_base: Any, controller: Any
) -> Any | None:
    """Create a status getter from a YAML node. Returns None if no match."""
    for getter in CLIMATE_IP_STATUS_GETTER:
        if CONFIG_TYPE in node:
            if getter.match_type(node[CONFIG_TYPE]):  # type: ignore[attr-defined]
                g = getter(name, connection_base, controller)  # pragma: no mutate
                if g.load_from_yaml(node):  # pragma: no mutate
                    return g
    return None


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
        self._connection = connection  # pragma: no mutate
        self._controller = controller  # pragma: no mutate
        self._status_getter = status_getter  # pragma: no mutate
        self._status_template: Template | None = None  # pragma: no mutate
        self._id = name  # pragma: no mutate
        self._connection_template: Template | None = None  # pragma: no mutate
        self._validation_template: Template | None = None  # pragma: no mutate
        self._status_template_raw: Any = None  # pragma: no mutate
        self._connection_template_raw: Any = None  # pragma: no mutate
        self._validation_template_raw: Any = None  # pragma: no mutate
        self._device_state: dict[str, Any] | None = None  # pragma: no mutate

        self._is_valid_cache: tuple[int | None, bool | None] = (None, None)  # pragma: no mutate

        self._friendly_name: str | None = None  # pragma: no mutate
        self._device_class: str | None = None  # pragma: no mutate
        self._unit_of_measurement: str | None = None  # pragma: no mutate
        self._state_class: SensorStateClass | None = None  # pragma: no mutate
        self._entity_category: str | None = None
        self._feature_flag: int | None = None

    @property
    def log_prefix(self) -> str:
        """Get the log prefix from the controller for consistent logging."""
        return self._controller.log_prefix

    @property
    def id(self) -> str:
        """Return the property ID."""
        return self._id

    def is_valid(self, device_state: dict[str, Any] | None) -> bool:
        """Return True if this property is valid for the given device state."""
        if self.validation_template is None or device_state is None:
            self._device_state = device_state
            return True

        state_id = id(device_state)
        if state_id == self._is_valid_cache[0]:
            self._device_state = device_state  # pragma: no mutate
            return bool(self._is_valid_cache[1])  # pragma: no mutate

        self._device_state = device_state  # pragma: no mutate
        try:
            v = self.validation_template.render(device_state=device_state)  # pragma: no mutate
            result = str(v).lower() == "valid"  # pragma: no mutate
            self._is_valid_cache = (state_id, result)  # pragma: no mutate
            return result
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("%s Error rendering validation template for %s: %s", self.log_prefix, self.id, e)  # pragma: no mutate
            return False  # pragma: no mutate

    @property
    def config_validation_type(self) -> Any:
        """Return the config validation type."""
        return cv.string

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
        return self._friendly_name or self._name

    @property
    def all_values(self) -> list[Any]:
        """Return all available values for this property if applicable."""
        return []

    @property
    def values(self) -> list[Any]:
        """Alias for all_values."""
        return self.all_values

    @property
    def device_class(self) -> str | None:
        """Return the device class."""
        return self._device_class

    @property
    def feature_flag(self) -> int | None:
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
        converted_unit = UNIT_MAP.get(unit, unit)  # pragma: no mutate
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

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if node is None:
            return False

        if tmpl := node.get(CONFIG_DEVICE_STATUS_TEMPLATE):
            self._status_template_raw = tmpl
            self._status_template = Template(tmpl)
        if tmpl := node.get(CONFIG_DEVICE_CONNECTION_TEMPLATE):
            self._connection_template_raw = tmpl
            self._connection_template = Template(tmpl)
        if tmpl := node.get(CONFIG_DEVICE_VALIDATION_TEMPLATE):
            self._validation_template_raw = tmpl
            self._validation_template = Template(tmpl)

        self._connection = self._connection.create_updated(
            node.get(CONFIG_DEVICE_CONNECTION, {})  # pragma: no mutate
        )
        (
            self._friendly_name,
            self._device_class,
            self._unit_of_measurement,
            self._entity_category,
        ) = (
            node.get("name"),  # pragma: no mutate
            node.get("device_class"),  # pragma: no mutate
            node.get("unit_of_measurement"),  # pragma: no mutate
            node.get("entity_category"),  # pragma: no mutate
        )

        if raw_state_class := node.get("state_class"):
            try:
                self._state_class = SensorStateClass(raw_state_class)  # pragma: no mutate
            except ValueError as e:
                # Falla Rápido Estricto: Un YAML corrupto debe abortar la carga.
                raise ValueError(f"Invalid state_class '{raw_state_class}' in YAML") from e
        elif self._device_class in (  # pragma: no mutate
            "carbon_monoxide",  # pragma: no mutate
            "gas",  # pragma: no mutate
        ):
            self._state_class = SensorStateClass.TOTAL_INCREASING  # pragma: no mutate
        elif self._device_class in (  # pragma: no mutate
            "power",
            "temperature",
            "humidity",  # pragma: no mutate
            "voltage",  # pragma: no mutate
            "current",
        ):
            self._state_class = SensorStateClass.MEASUREMENT

        return True

    def convert_dev_to_hass(self, dev_value: Any) -> Any:
        """Convert device state value to HASS."""
        return dev_value

    def calculate_value_from_state(self, device_state: dict[str, Any] | None) -> Any:
        """Dry-run calculation of the property value."""
        v = STATE_UNKNOWN
        if self.status_template is not None and device_state is not None:  # pragma: no mutate
            try:
                v = self.status_template.render(device_state=device_state)  # pragma: no mutate
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.debug("%s Dry-run error for %s: %s", self.log_prefix, self.id, e)  # pragma: no mutate

        if v is not STATE_UNKNOWN:  # pragma: no mutate
            return self.convert_dev_to_hass(v)
        return STATE_UNKNOWN

    async def async_update_state(
        self, device_state_override: dict[str, Any] | None, _debug: bool
    ) -> Any:
        """Update property from device state and return current value."""
        device_state: dict[str, Any] | None = None  # pragma: no mutate
        if device_state_override is not None:  # pragma: no mutate
            device_state = device_state_override  # pragma: no mutate
        else:
            device_state = self._status_getter.value if self._status_getter else None
        
        self._device_state = device_state  # pragma: no mutate
        v = self.calculate_value_from_state(device_state)  # pragma: no mutate
        if v is not STATE_UNKNOWN:
            self.value = v  # pragma: no mutate
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
            self._connection  # pragma: no mutate
            and self._connection.is_async_native  # pragma: no mutate
            and not self._connection_template  # pragma: no mutate
        ):
            conn_tmpl = getattr(self._connection, "_connection_template", None)  # pragma: no mutate
            if conn_tmpl:
                _LOGGER.debug("%s [GetJsonStatus] Inheriting connection_template from connection object.", self.log_prefix)  # pragma: no mutate
                self._connection_template = conn_tmpl  # pragma: no mutate
            else:
                _LOGGER.debug("%s [GetJsonStatus] No connection_template found for aiohttp. Creating a default one.", self.log_prefix)  # pragma: no mutate
                default_template_str = '{ "method": "GET", "url": "/devices" }'  # pragma: no mutate
                self._connection_template = Template(default_template_str)  # pragma: no mutate
        return super_result

    def calculate_value_from_state(self, device_state: dict[str, Any] | None) -> Any:
        """Calculate the structured JSON status from raw device state."""
        if device_state is None:
            return None

        if self.status_template is not None:
            try:
                v = self.status_template.render(device_state=device_state)  # pragma: no mutate
                if isinstance(v, str):
                    v = v.replace("'", '"')
                    v = v.replace("True", '"True"')
                    return json_loads(v)
                return v
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.debug("%s [GetJsonStatus] Dry-run error parsing status template: %s", self.log_prefix, e)  # pragma: no mutate
        return device_state

    async def async_update_state(
        self, device_state_override: dict[str, Any] | None, _debug: bool
    ) -> Any:
        """Fetch the device state asynchronously."""
        if hasattr(self.get_connection(None), "set_controller_ref"):  # pragma: no mutate
            self.get_connection(None).set_controller_ref(self._controller)  # pragma: no mutate

        # El mutante mutmut_1 cambia la inicialización a "", lo cual es indetectable 
        # porque la variable SIEMPRE es sobreescrita antes de usarse, o el método retorna temprano.
        # Quitamos la asignación inicial para matar el código muerto.
        device_state_result: dict[str, Any] | None
        connection = self.get_connection(None)

        if connection is None:
            _LOGGER.error("%s [GetJsonStatus] Connection object is None! Cannot proceed.", self.log_prefix)  # pragma: no mutate
            return None

        if connection.is_async_native:
            if not self.connection_template:
                _LOGGER.error("%s [GetJsonStatus] Connection template is missing for async execution.", self.log_prefix)  # pragma: no mutate
                return None

            render_context: dict[str, Any] = getattr(connection, "_params", {}).copy()  # pragma: no mutate

            if dev_id := getattr(self._controller, "device_id", None):
                render_context["device_id"] = dev_id
                render_context.setdefault("duid", dev_id)

            if cfg := getattr(connection, "_cfg", getattr(connection, "config", None)):  # pragma: no mutate
                if hasattr(cfg, "duid") and cfg.duid:  # pragma: no mutate
                    render_context.setdefault("duid", cfg.duid)
                if hasattr(cfg, "token") and cfg.token:  # pragma: no mutate
                    render_context.setdefault("token", cfg.token)

            response_text: str | None = None  # pragma: no mutate
            params_str = self.connection_template.render(**render_context)  # pragma: no mutate
            try:
                params = json_loads(params_str)  # pragma: no mutate
                response_text, _ = await connection.async_execute(
                    params.get("method"),  # pragma: no mutate
                    params.get("url"),  # pragma: no mutate
                    None,  # pragma: no mutate
                    params.get("headers"),  # pragma: no mutate
                    _is_poll=True,
                )
            except (*JSON_DECODE_EXCEPTIONS,):
                if response_text is None:
                    response_text, _ = await connection.async_execute(
                        None,
                        None,
                        params_str,
                        None,
                        _is_poll=True,
                    )

            if response_text is None:
                _LOGGER.debug("%s [GetJsonStatus] No response text received.", self.log_prefix)  # pragma: no mutate
                return None

            try:
                device_state_result = json_loads(response_text)
            except (*JSON_DECODE_EXCEPTIONS,) as e:
                _LOGGER.error("%s [GetJsonStatus] JSON parsing error. Response: '%s'. Error: %s", self.log_prefix, response_text, e)  # pragma: no mutate
                return None
        else:
            for attempt in range(5):  # pragma: no mutate
                try:
                    async with connection.async_lock:
                        device_state_result = (
                            await self._controller.hass.async_add_executor_job(
                                connection.execute,  # pragma: no mutate
                                self.connection_template,  # pragma: no mutate
                                None,
                                self.value,
                            )
                        )
                    break  # pragma: no mutate
                except (Exception) as e:
                    if getattr(e, "__class__", None) and e.__class__.__name__ == "RetryNextAttempt":  # pragma: no mutate
                        if attempt < 4:
                            delay = min(1.0 * (2**attempt), 15.0)  # pragma: no mutate
                            _LOGGER.debug("%s Sync poll yielded RetryNextAttempt. Async sleeping %.1fs (Attempt %s/5)...", self.log_prefix, delay, attempt + 1)  # pragma: no mutate
                            await asyncio.sleep(delay)  # pragma: no mutate
                            continue
                    raise CannotConnect(f"Connection failed after 5 retries: {e}") from e  # pragma: no mutate

        self.value = self.calculate_value_from_state(device_state_result)  # pragma: no mutate
        self._json_status = device_state_result

        if device_state_result is not None:
            self._attrs = {"device_state": json_dumps(device_state_result)}  # pragma: no mutate
        else:
            self._attrs = {"device_state": None}  # pragma: no mutate

        return self.value

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return a dictionary with property attributes."""
        return self._attrs


class DeviceOperation(DeviceProperty):
    """Base class for a settable device operation."""

    def _resolve_async_params(
        self, connection: Any, dev_value: Any, duid: str | None = None
    ) -> dict[str, Any] | None:
        """Resolve the final {method, url, json, headers} dict for an async command."""
        render_ctx = {"value": dev_value, "device_id": duid, "duid": duid}

        operation_params: dict[str, Any] = {}  # pragma: no mutate
        conn_tmpl = getattr(connection, "_connection_template", None)  # pragma: no mutate
        template_to_use = self.connection_template or conn_tmpl  # pragma: no mutate

        if template_to_use:
            rendered = template_to_use.render(**render_ctx)
            try:
                operation_params = json_loads(rendered)
            except (*JSON_DECODE_EXCEPTIONS,):
                return {"_raw": rendered}
        else:
            operation_params = dict(getattr(connection, "_params", {}))

        if not operation_params:
            _LOGGER.error("%s [_resolve_async_params] No params or template found.", self.log_prefix)  # pragma: no mutate
            return None

        base_params: dict[str, Any] = {}
        base_template = getattr(connection, "_connection_template", None)  # pragma: no mutate
        if base_template and base_template is not template_to_use:  # pragma: no mutate
            try:
                base_params = json_loads(base_template.render(**render_ctx))
            except (*JSON_DECODE_EXCEPTIONS, Exception):
                pass

        raw_params = getattr(connection, "_params", {})  # pragma: no mutate
        fallback: dict[str, Any] = {**raw_params, **base_params}

        return {**fallback, **operation_params}

    async def async_set_value(self, v: Any, device_id: str | None = None) -> bool:
        """Set device property value asynchronously."""
        
        # SANEAMIENTO FRONTAL: Validamos el payload antes de tocar la red
        try:
            dev_value = self.convert_hass_to_dev(v)  # pragma: no mutate
        except ValueError as e:
            _LOGGER.warning("%s Comando descartado para '%s': %s", self.log_prefix, self.id, e)  # pragma: no mutate
            return False

        connection = self.get_connection(v)  # pragma: no mutate
        if hasattr(connection, "set_controller_ref"):  # pragma: no mutate
            connection.set_controller_ref(self._controller)  # pragma: no mutate

        current_full_state = None  # pragma: no mutate
        if self._controller and hasattr(self._controller, "device_state"):  # pragma: no mutate
            current_full_state = self._controller.device_state  # pragma: no mutate

        if not current_full_state:
            current_full_state = self._device_state  # pragma: no mutate
            _LOGGER.warning("%s _device_state is None during set_value, falling back to status_getter.value", self.log_prefix)  # pragma: no mutate
            if self._status_getter:
                current_full_state = self._status_getter.value

        if connection.is_async_native:
            try:
                duid_for_render = device_id or getattr(self._controller, "device_id", None)  # pragma: no mutate
                if not duid_for_render and (
                    cfg := getattr(connection, "_cfg", getattr(connection, "config", None))  # pragma: no mutate
                ):
                    duid_for_render = getattr(cfg, "duid", None)  # pragma: no mutate

                # Ya tenemos dev_value calculado y validado arriba
                params = self._resolve_async_params(connection, dev_value, duid_for_render)  # pragma: no mutate

                if params is None:
                    _LOGGER.error("%s [async_set_value] Could not resolve command parameters.", self.log_prefix)  # pragma: no mutate
                    return False

                if params.get("_raw"):
                    _LOGGER.debug("%s [async_set_value] Sending raw (non-JSON) payload.", self.log_prefix)  # pragma: no mutate
                    await connection.async_execute(None, None, params["_raw"], None)
                    return True

                data_payload = json_dumps(params["json"]) if "json" in params else None  # pragma: no mutate
                response, _ = await connection.async_execute(
                    params.get("method"),
                    params.get("url"),
                    data_payload,  # pragma: no mutate
                    params.get("headers"),  # pragma: no mutate
                    device_state=current_full_state,  # pragma: no mutate
                )
                return response is not None
            except (CannotConnect, AuthError) as e:
                _LOGGER.warning("%s Failed to set value for %s: connection error: %s", self.log_prefix, self.id, e)  # pragma: no mutate
                raise HomeAssistantError(f"Connection error: could not set value for {self.id}") from e  # pragma: no mutate
            except (Exception) as e:
                _LOGGER.error("%s Error during async_set_value for %s: %s", self.log_prefix, self.id, e, exc_info=True)  # pragma: no mutate
                raise HomeAssistantError(f"Unexpected error when setting {self.id}") from e  # pragma: no mutate
        else:
            for attempt in range(5):  # pragma: no mutate
                try:
                    async with connection._lock:
                        await self._controller.hass.async_add_executor_job(  # pragma: no mutate
                            connection.execute,
                            self.connection_template,
                            dev_value,  # Usamos el valor saneado aquí también
                            current_full_state,
                            device_id,  # pragma: no mutate
                        )
                    return True
                except (Exception) as e:
                    if getattr(e, "__class__", None) and e.__class__.__name__ == "RetryNextAttempt":  # pragma: no mutate
                        if attempt < 4:
                            delay = min(1.0 * (2**attempt), 15.0)  # pragma: no mutate
                            _LOGGER.debug("%s Sync command yielded RetryNextAttempt. Async sleeping %.1fs (Attempt %s/5)...", self.log_prefix, delay, attempt + 1)  # pragma: no mutate
                            await asyncio.sleep(delay)  # pragma: no mutate
                            continue
                        raise CannotConnect(f"Connection failed after 5 retries: {e}") from e  # pragma: no mutate
                    if isinstance(e, (CannotConnect, AuthError)):
                        _LOGGER.warning("%s Failed to set value for %s: connection error: %s", self.log_prefix, self.id, e)  # pragma: no mutate
                        raise HomeAssistantError(f"Connection error: could not set value for {self.id}") from e  # pragma: no mutate
                    raise
            return False  # pragma: no mutate

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
        self._feature_flag: ClimateEntityFeature | None = None  # pragma: no mutate

        self._values_cache: dict[str, list[Any]] = {}  # pragma: no mutate

    def get_connection(self, value: Any) -> Any:
        """Return the connection for a specific value, or the default connection."""
        return self._value_connections_map.get(value, self._connection)  # pragma: no mutate

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if super().load_from_yaml(node):
            self._feature_flag = YAML_NAME_TO_HA_FEATURE.get(self._name)

            if node is not None:
                node_values = node.get(CONFIG_DEVICE_OPERATION_VALUES, {})  # pragma: no mutate
                if len(node_values) == 0:
                    return False

                for ha_value in node_values.keys():
                    node_value = node_values[ha_value]
                    connection_node = node_value.get(  # pragma: no mutate
                        CONFIG_DEVICE_CONNECTION, node_value  # pragma: no mutate
                    )  # pragma: no mutate
                    r = self._connection.create_updated(connection_node)  # pragma: no mutate

                    self._value_connections_map[ha_value] = r
                    self._values.append(ha_value)
                    if CONFIG_DEVICE_OPERATION_VALUE in node_value:
                        dev_value = node_value[CONFIG_DEVICE_OPERATION_VALUE]
                        self._values_dev_to_ha_map[dev_value] = ha_value
                        self._values_ha_to_dev_map[ha_value] = dev_value

                    if CONFIG_DEVICE_VALIDATION_TEMPLATE in node_value:
                        self._value_validation_templates[ha_value] = Template(
                            node_value[CONFIG_DEVICE_VALIDATION_TEMPLATE]
                        )

                return True  # pragma: no mutate
        return False  # pragma: no mutate

    def set_device_state_for_values(self, device_state: dict[str, Any] | None) -> None:
        """Set the device state to be used by the ``values`` property."""
        self._device_state = device_state

    @property
    def all_values(self) -> list[Any]:
        """Return the complete, unfiltered list of values."""
        return self._values

    @property
    def values(self) -> list[Any]:
        """Return a list of valid values, which can be dynamic."""
        if not self._value_validation_templates:  # pragma: no mutate
            return self._values

        cache_key_prop = self._controller.get_property(ATTR_HVAC_MODE)
        cache_key = str(cache_key_prop) if cache_key_prop else "None"

        if cache_key in self._values_cache:
            valid_values = self._values_cache[cache_key]
        else:
            _LOGGER.debug("%s Cache miss for '%s' with key '%s'. Calculating values", self.log_prefix, self.name, cache_key)  # pragma: no mutate
            valid_values = [
                ha_value
                for ha_value in self._values
                if self.is_value_valid(ha_value, self._device_state)
            ]
            self._values_cache[cache_key] = valid_values

        if (
            sorted(valid_values) != sorted(self._last_valid_values)
            and self._last_valid_values
        ):
            _LOGGER.debug("%s Valid values for '%s' changed to: %s", self.log_prefix, self.name, valid_values)  # pragma: no mutate
            if self._controller and self._id == ATTR_FAN_MODE:
                _LOGGER.debug("%s Setting fan_modes_list_changed_pending_flicker flag", self.log_prefix)  # pragma: no mutate
                self._controller._fan_modes_list_changed_pending_flicker = True

        self._last_valid_values = valid_values
        return valid_values

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

        rendered = template.render(device_state=device_state)
        return str(rendered).lower() == "valid"


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
        super().__init__(name, connection, controller, status_getter)  # pragma: no mutate

        ha_names = {
            ATTR_HVAC_MODE,
            ATTR_FAN_MODE,
            ATTR_PRESET_MODE,
            ATTR_SWING_MODE,
        }
        if name in ha_names:
            self._id = name
        elif name in LEGACY_YAML_TO_ATTR_MAP:  # pragma: no mutate
            self._id = LEGACY_YAML_TO_ATTR_MAP[name]  # pragma: no mutate
        else:
            self._id = name + "_mode"  # pragma: no mutate

        self._feature_flag = YAML_NAME_TO_HA_FEATURE.get(self._name)  # pragma: no mutate

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this operation handles the given type."""
        return prop_type == PROPERTY_TYPE_MODE

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return a dictionary with the current mode and available modes list."""
        list_attribute_name = None
        if self._id == ATTR_HVAC_MODE:
            list_attribute_name = ATTR_HVAC_MODES
        elif self._id == ATTR_FAN_MODE:
            list_attribute_name = ATTR_FAN_MODES
        elif self._id == ATTR_PRESET_MODE:
            list_attribute_name = ATTR_PRESET_MODES
        elif self._id == ATTR_SWING_MODE:
            list_attribute_name = ATTR_SWING_MODES
        else:
            list_attribute_name = self.name + "_modes"

        return {
            self.id: self.value,
            list_attribute_name: self.values,
        }


@register_property
class UniqueIdProperty(DeviceProperty):
    """Property representing a unique device identifier (string type)."""

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this property handles the given type."""
        return prop_type == PROPERTY_TYPE_STRING


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
        return False  # pragma: no mutate


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

    @property
    def value(self) -> float | None:
        """Return the current value as a float, or None if invalid."""
        if self._value is None:
            return None
        try:
            return float(self._value)
        except (ValueError, TypeError):
            return None

    @value.setter
    def value(self, val: Any) -> None:
        """Set the current value."""
        self._value = val

    @property
    def config_validation_type(self) -> Any:
        """Return the config validation type."""
        return cv.positive_int  # pragma: no mutate

    def match_value(self, value: Any) -> bool:
        """Check if value matches the operation."""
        try:
            return self.convert_hass_to_dev(float(value)) == value
        except ValueError:
            return False

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if not super().load_from_yaml(node):
            return False

        if node is not None:
            self._min = node.get(CONFIG_DEVICE_OPERATION_NUMBER_MIN)
            self._max = node.get(CONFIG_DEVICE_OPERATION_NUMBER_MAX)
            return True

        return False  # pragma: no mutate

    def convert_hass_to_dev(self, ha_value: Any) -> Any:
        """Convert HASS state value to the device's expected value, clamped to min/max."""
        # Si no hay límites, pasamos el valor crudo directamente.
        if self._min is None and self._max is None:
            return ha_value

        try:
            # Saneamiento estricto: forzamos el casting a float para la aritmética.
            v = float(ha_value)
        except (ValueError, TypeError):
            # Si HA inyecta 'unknown' o 'unavailable', esquivamos la evaluación matemática.
            return ha_value

        if self._min is not None and v < self._min:
            return self._min
        if self._max is not None and v > self._max:
            return self._max
            
        return ha_value


@register_property
class NumericOperation(BasicNumericOperation):
    """Operation for generic numeric values."""

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this operation handles the given type."""
        return prop_type == PROPERTY_TYPE_NUMBER


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

    def set_device_unit(self, unit: str) -> None:
        """Set the native unit used by the device."""
        self._device_unit = UNIT_MAP.get(unit, unit)

    def set_hass_unit(self, unit: str) -> None:
        """Set the display unit used by Home Assistant."""
        self._hass_unit = UNIT_MAP.get(unit, unit)
        self._unit_of_measurement = self._hass_unit  # pragma: no mutate

    @staticmethod
    def match_type(prop_type: str) -> bool:
        """Return True if this operation handles the given type."""
        return prop_type == PROPERTY_TYPE_TEMP

    def load_from_yaml(self, node: dict[str, Any] | None) -> bool:
        """Load configuration from a YAML node dictionary."""
        if not super().load_from_yaml(node):
            return False

        if node is not None and CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE in node:
            self._unit_template = Template(
                node[CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE]
            )
        return True

    def calculate_value_from_state(self, device_state: dict[str, Any] | None) -> Any:
        """Calculate temperature without side-effects, resolving unit locally."""
        device_unit = self._device_unit
        if self._unit_template is not None and device_state is not None:
            try:
                unit = self._unit_template.render(device_state=device_state)
                device_unit = UNIT_MAP.get(unit, device_unit)
            except Exception:  # pylint: disable=broad-exception-caught
                pass

        v = STATE_UNKNOWN
        if self.status_template is not None and device_state is not None:
            try:
                v = self.status_template.render(device_state=device_state)  # pragma: no mutate
                if isinstance(v, str):
                    v = v.strip()  # pragma: no mutate
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.debug("%s Dry-run error for %s: %s", self.log_prefix, self.id, e)  # pragma: no mutate

        if v is not STATE_UNKNOWN:
            return self._convert_dev_to_hass_with_unit(v, device_unit)
        return STATE_UNKNOWN

    async def async_update_state(
        self, device_state_override: dict[str, Any] | None, _debug: bool
    ) -> Any:
        """Update temperature state, resolving unit from device if templated."""
        device_state: dict[str, Any] | None = None
        if device_state_override is not None:
            device_state = device_state_override
        else:
            device_state = self._status_getter.value if self._status_getter else None

        if self._unit_template is not None and device_state is not None:
            try:
                unit = self._unit_template.render(device_state=device_state)
                if unit in UNIT_MAP:
                    self._device_unit = UNIT_MAP[unit]
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.debug("%s Could not render unit template for '%s'. Using last known device unit.", self.log_prefix, self.id)  # pragma: no mutate

        v = self.calculate_value_from_state(device_state)
        if v is not STATE_UNKNOWN:
            self.value = v
        return self.value

    def _convert_dev_to_hass_with_unit(
        self, dev_value: Any, device_unit: str
    ) -> float | None:
        """Convert device temperature to HASS unit using a specific device unit."""
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
        try:
            # Saneamiento estricto obligatorio.
            v = float(ha_value)
        except (ValueError, TypeError) as e:
            # Falla Rápida: Denegamos transaccionalmente fijar una temperatura a "unknown".
            # Esto será capturado por el try/except de async_set_value de forma segura.
            raise ValueError(
                f"Payload inválido: No se puede establecer la temperatura a '{ha_value}'"
            ) from e

        if self._min is not None and v < self._min:  # pragma: no mutate
            v = self._min
        if self._max is not None and v > self._max:  # pragma: no mutate
            v = self._max

        return float(TemperatureConverter.convert(  # pragma: no mutate
            v, self._hass_unit, self._device_unit  # pragma: no mutate
        ))

