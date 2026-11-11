"""Consolidated orthogonal test suite for custom_components.climate_ip.properties."""

from dataclasses import dataclass
import logging
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.climate_ip.const import (
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
    DEFAULT_JSON_STATUS_PAYLOAD,
    KEY_DEVICE_CONFIG,
    KEY_DEVICE_MODE,
    KEY_DEVICE_STATE,
    KEY_DUID,
    KEY_HVAC,
    KEY_IDENTIFIERS,
    KEY_PATH_TO_DEVICES,
    KEY_RAW_PAYLOAD,
    KEY_STATUS,
    PROPERTY_TYPE_ENUM,
    PROPERTY_TYPE_MODE,
    PROPERTY_TYPE_NUMBER,
    PROPERTY_TYPE_SENSOR,
    PROPERTY_TYPE_STRING,
    PROPERTY_TYPE_SWITCH,
    PROPERTY_TYPE_TEMP,
    PROPERTY_TYPE_UNIQUE_ID,
    STATUS_GETTER_JSON,
)
from custom_components.climate_ip.exceptions import AuthError, CannotConnect
import custom_components.climate_ip.properties as properties_mod
from custom_components.climate_ip.properties import (
    _WARNED_TEMPLATE_MESSAGES,
    CLIMATE_IP_PROPERTIES,
    CLIMATE_IP_STATUS_GETTER,
    BasicDeviceOperation,
    BasicNumericOperation,
    DeviceOperation,
    DeviceProperty,
    GetJsonStatus,
    ModeOperation,
    SwitchOperation,
    TemperatureOperation,
    UniqueIdProperty,
    _normalize_unit,
    _template_log_fn,
    clear_template_warning_cache,
    create_property,
    create_status_getter,
    parse_temperature_unit,
    register_property,
    register_status_getter,
    render_template,
)
from homeassistant.components.climate import (
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template

# ---------------------------------------------------------------------------
# Autouse fixture overrides (isolate pure unit tests from HA/network hooks)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def auto_clear_yaml_cache() -> None:
    """No-op override of global yaml cache fixture for isolated unit tests."""
    return


@pytest.fixture(autouse=True)
def force_task_cancellation() -> None:
    """No-op override of async task cancellation fixture."""
    return


@pytest.fixture(autouse=True)
def auto_mock_network() -> None:
    """No-op override of network mock fixture."""
    return


@pytest.fixture(autouse=True)
def ruthless_aiohttp_teardown() -> None:
    """No-op override of aiohttp teardown fixture."""
    return


@pytest.fixture(autouse=True)
def block_unmocked_network_io() -> None:
    """No-op override of global network monkeypatch fixture."""
    return


# ---------------------------------------------------------------------------
# Lightweight in-memory doubles (zero MagicMock/hass bootstrap overhead)
# ---------------------------------------------------------------------------

_SHARED_TEMPLATE_DATA: dict[Any, Any] = {}


class _StubConfig:
    """Minimal HomeAssistant config double."""

    def __init__(self, *, legacy_templates: bool = False) -> None:
        self.legacy_templates = legacy_templates


class _StubHass:
    """Minimal HomeAssistant double sharing compiled Jinja2 environments."""

    def __init__(self, *, legacy_templates: bool = False) -> None:
        self.data = _SHARED_TEMPLATE_DATA
        self.config = _StubConfig(legacy_templates=legacy_templates)


class _StubLoader:
    """Minimal YAML loader double."""

    def __init__(self) -> None:
        self.parsed_yaml_cache: dict[str, Any] = {}
        self.operations: dict[str, Any] = {}


class _StubStatusGetter:
    """Minimal status getter double."""

    def __init__(self, value: Any = None) -> None:
        self.value = value


class _StubPropRef:
    """Minimal property reference double for state node / status value lookups."""

    def __init__(
        self,
        *,
        value: Any = None,
        state_node: str | None = None,
    ) -> None:
        self.value = value
        self.state_node = state_node


class _StubController:
    """Lightweight in-memory controller double."""

    def __init__(self, hass: _StubHass | None = None) -> None:
        self.hass = hass if hass is not None else _StubHass()
        self.log_prefix = "[TestController]"
        self.device_id: str | None = "test_duid"
        self.pure_device_state: Any = {}
        self.device_state: Any = {}
        self.loader: _StubLoader | None = _StubLoader()
        self.connection: Any = None
        self.fan_modes_list_changed_pending_flicker = False
        self._props: dict[str, Any] = {}
        self._prop_objs: dict[str, Any] = {}
        self.prop_error: Exception | None = None

    def get_property(self, name: str) -> Any:
        """Return registered property or raise configured error."""
        if self.prop_error is not None:
            raise self.prop_error
        return self._props.get(name)

    def get_property_object(self, name: str) -> Any:
        """Return registered property object."""
        return self._prop_objs.get(name)


class _StubConnection:
    """Lightweight in-memory ConnectionWithParams double."""

    def __init__(
        self,
        *,
        is_async_native: bool = True,
        params: Any = None,
        private_params: Any = None,
        connection_template: Any = None,
        private_connection_template: Any = None,
        config: dict[str, Any] | None = None,
        execute_result: tuple[Any, Any] = ("{}", None),
        retry_result: Any = None,
    ) -> None:
        self.is_async_native = is_async_native
        self.params = params
        self._params = private_params
        self.connection_template = connection_template
        self._connection_template = private_connection_template
        self.config: dict[str, Any] = {} if config is None else config
        self.execute_result: tuple[Any, Any] = execute_result
        self.retry_result: Any = retry_result
        self.execute_error: BaseException | None = None
        self.retry_error: BaseException | None = None
        self.updated_nodes: list[dict[str, Any] | None] = []
        self.execute_calls: list[tuple[Any, Any, Any, Any, dict[str, Any]]] = []
        self.retry_calls: list[tuple[Any, Any, Any, Any]] = []
        self.updated_result: Any = self

    def create_updated(self, yaml_node: dict[str, Any] | None) -> Any:
        """Record YAML connection node and return configured connection."""
        self.updated_nodes.append(yaml_node)
        return self.updated_result

    async def async_execute(
        self,
        method: str | None,
        url: str | None,
        data: Any,
        headers: dict[str, Any] | None,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        """Record async execution call and return or raise configured result."""
        self.execute_calls.append((method, url, data, headers, kwargs))
        if self.execute_error is not None:
            raise self.execute_error
        return self.execute_result

    async def async_execute_with_retry(
        self,
        template: Any,
        value: Any,
        device_state: Any = None,
        device_id: str | None = None,
    ) -> Any:
        """Record sync retry call and return or raise configured result."""
        self.retry_calls.append((template, value, device_state, device_id))
        if self.retry_error is not None:
            raise self.retry_error
        return self.retry_result


@dataclass
class _StateDataclass:
    """Dataclass fixture for _resolve_raw_state_source testing."""

    power: str
    temp: int


# ---------------------------------------------------------------------------
# 1. Module helpers, registries & factories
# ---------------------------------------------------------------------------


def test_template_helpers_and_temperature_unit_normalization() -> None:
    """Test template warning cache, render_template, and temperature unit parsing."""
    clear_template_warning_cache()
    assert len(_WARNED_TEMPLATE_MESSAGES) == 0

    try:
        with patch.object(properties_mod._LOGGER, "debug") as mock_debug:
            _template_log_fn(logging.WARNING, "warn msg 1")
            assert "warn msg 1" in _WARNED_TEMPLATE_MESSAGES
            mock_debug.assert_called_once_with(
                "Template variable warning: %s", "warn msg 1"
            )

            mock_debug.reset_mock()
            _template_log_fn(logging.WARNING, "warn msg 1")
            mock_debug.assert_not_called()

            _template_log_fn(logging.WARNING, "warn msg 2")
            mock_debug.assert_called_once_with(
                "Template variable warning: %s", "warn msg 2"
            )
            assert "warn msg 2" in _WARNED_TEMPLATE_MESSAGES

        assert render_template(None) is None
        assert render_template("literal_value") == "literal_value"

        hass = _StubHass()
        assert render_template(Template("{{ 42 }}", hass)) == 42
        assert render_template(Template("{{ val }}", hass), val=7) == 7

        clear_template_warning_cache()
        render_template(Template("{{ undefined_var }}", hass))
        assert len(_WARNED_TEMPLATE_MESSAGES) == 1

        with pytest.raises(TypeError, match="Expected HomeAssistant Template or str"):
            render_template(123)
    finally:
        clear_template_warning_cache()
    assert len(_WARNED_TEMPLATE_MESSAGES) == 0

    assert (
        parse_temperature_unit(UnitOfTemperature.CELSIUS) is UnitOfTemperature.CELSIUS
    )
    assert (
        parse_temperature_unit(UnitOfTemperature.FAHRENHEIT)
        is UnitOfTemperature.FAHRENHEIT
    )
    assert parse_temperature_unit("°C") is UnitOfTemperature.CELSIUS
    assert parse_temperature_unit(" c ") is UnitOfTemperature.CELSIUS
    assert parse_temperature_unit("°F") is UnitOfTemperature.FAHRENHEIT
    assert parse_temperature_unit(" fahrenheit ") is UnitOfTemperature.FAHRENHEIT

    with pytest.raises(ValueError, match="Invalid temperature unit"):
        parse_temperature_unit("kelvin")
    with pytest.raises(ValueError, match="Invalid temperature unit"):
        parse_temperature_unit(999)

    assert _normalize_unit("°C") is UnitOfTemperature.CELSIUS
    assert _normalize_unit("ppm") == "ppm"


def test_property_and_status_getter_registries_and_factories() -> None:
    """Test property/status_getter registration idempotency and factory creation."""

    class _DummyProp:
        @staticmethod
        def match_type(prop_type: str) -> bool:
            return prop_type in ("dummy_prop", "dummy_prop_fail")

        def __init__(
            self, name: str, conn: Any, ctrl: Any, getter: Any | None = None
        ) -> None:
            self.name = name
            self.conn = conn
            self.ctrl = ctrl
            self.getter = getter

        def load_from_yaml(self, node: dict[str, Any]) -> bool:
            return node.get(CONFIG_TYPE) == "dummy_prop"

    class _DummyGetter:
        @staticmethod
        def match_type(prop_type: str) -> bool:
            return prop_type in ("dummy_getter", "dummy_getter_fail")

        def __init__(self, name: str, conn: Any, ctrl: Any) -> None:
            self.name = name
            self.conn = conn
            self.ctrl = ctrl

        def load_from_yaml(self, node: dict[str, Any]) -> bool:
            return node.get(CONFIG_TYPE) == "dummy_getter"

    conn = _StubConnection()
    ctrl = _StubController()
    try:
        assert register_property(_DummyProp) is _DummyProp  # type: ignore[arg-type]
        register_property(_DummyProp)  # type: ignore[arg-type]
        assert CLIMATE_IP_PROPERTIES.count(_DummyProp) == 1  # type: ignore[arg-type]

        assert register_status_getter(_DummyGetter) is _DummyGetter  # type: ignore[arg-type]
        register_status_getter(_DummyGetter)  # type: ignore[arg-type]
        assert CLIMATE_IP_STATUS_GETTER.count(_DummyGetter) == 1  # type: ignore[arg-type]

        prop = create_property(
            "p1", {CONFIG_TYPE: "dummy_prop"}, conn, ctrl, "my_getter"
        )
        assert prop is not None
        assert (prop.name, prop.conn, prop.ctrl, prop.getter) == (
            "p1",
            conn,
            ctrl,
            "my_getter",
        )

        getter = create_status_getter("g1", {CONFIG_TYPE: "dummy_getter"}, conn, ctrl)
        assert getter is not None
        assert (getter.name, getter.conn, getter.ctrl) == ("g1", conn, ctrl)

        assert create_property("p", {}, conn, ctrl, "g") is None
        assert create_property("p", {CONFIG_TYPE: "unknown"}, conn, ctrl, "g") is None
        assert (
            create_property("p", {CONFIG_TYPE: "dummy_prop_fail"}, conn, ctrl, "g")
            is None
        )

        assert create_status_getter("g", {}, conn, ctrl) is None
        assert create_status_getter("g", {CONFIG_TYPE: "unknown"}, conn, ctrl) is None
        assert (
            create_status_getter("g", {CONFIG_TYPE: "dummy_getter_fail"}, conn, ctrl)
            is None
        )
    finally:
        if _DummyProp in CLIMATE_IP_PROPERTIES:
            CLIMATE_IP_PROPERTIES.remove(_DummyProp)  # type: ignore[arg-type]
        if _DummyGetter in CLIMATE_IP_STATUS_GETTER:
            CLIMATE_IP_STATUS_GETTER.remove(_DummyGetter)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. DeviceProperty: YAML loading, static helpers, routing, state & cascades
# ---------------------------------------------------------------------------


def test_device_property_yaml_loading_and_metadata_accessors() -> None:
    """Test DeviceProperty YAML parsing, connection helpers, and metadata getters."""
    conn = _StubConnection(
        params={"method": "GET", "url": "/public"},
        private_params={"method": "POST", "url": "/private"},
    )
    ctrl = _StubController()
    prop = DeviceProperty("raw_prop", conn, ctrl)

    assert DeviceProperty.match_type(PROPERTY_TYPE_STRING) is True
    assert DeviceProperty.match_type(PROPERTY_TYPE_SENSOR) is True
    assert DeviceProperty.match_type(PROPERTY_TYPE_MODE) is False
    assert prop.log_prefix == "[TestController]"
    assert prop.id == "raw_prop"
    assert prop.name == "raw_prop"
    assert prop.all_values == []
    assert prop.convert_dev_to_hass(42) == 42
    assert prop.load_from_yaml(None) is False
    assert prop.load_from_yaml({}) is True
    assert conn.updated_nodes[-1] == {}

    # _get_connection_params and _get_connection_template precedence & fallbacks
    assert DeviceProperty._get_connection_params(conn) == {
        "method": "GET",
        "url": "/public",
    }
    conn_priv = _StubConnection(params="bad", private_params={"k": "v"})
    priv_copy = DeviceProperty._get_connection_params(conn_priv)
    assert priv_copy == {"k": "v"}
    assert priv_copy is not conn_priv._params
    assert DeviceProperty._get_connection_params(_StubConnection()) == {}

    tmpl_pub = Template("{{ 1 }}", ctrl.hass)
    tmpl_priv = Template("{{ 2 }}", ctrl.hass)
    assert (
        DeviceProperty._get_connection_template(
            _StubConnection(
                connection_template=tmpl_pub, private_connection_template=tmpl_priv
            )
        )
        is tmpl_pub
    )
    assert (
        DeviceProperty._get_connection_template(
            _StubConnection(
                connection_template=123, private_connection_template=tmpl_priv
            )
        )
        is tmpl_priv
    )
    assert (
        DeviceProperty._get_connection_template(
            _StubConnection(connection_template="raw_str")
        )
        == "raw_str"
    )
    assert DeviceProperty._get_connection_template(_StubConnection()) is None

    # Full YAML node load
    node = {
        CONFIG_TYPE: "test_type",
        CONFIG_STATE_NODE: "StateNode",
        CONFIG_DEVICE_STATUS_TEMPLATE: "{{ device_state.power }}",
        CONFIG_DEVICE_CONNECTION_TEMPLATE: '{"method": "GET"}',
        CONFIG_DEVICE_VALIDATION_TEMPLATE: "{{ 'valid' }}",
        CONFIG_DEVICE_CONNECTION: {"url": "/test"},
        CONFIG_DEVICE_NAME: "Test Name",
        CONFIG_DEVICE_CLASS: "temperature",
        CONFIG_UNIT_OF_MEASUREMENT: "°C",
        CONFIG_ENTITY_CATEGORY: "diagnostic",
        CONFIG_STATE_CLASS: "measurement",
        "icon": "mdi:thermostat",
    }
    assert prop.load_from_yaml(node) is True
    assert prop._type == "test_type"
    assert prop.state_node == "StateNode"
    assert prop.status_template is not None
    assert prop.status_template.hass is ctrl.hass
    assert prop._status_template_raw == "{{ device_state.power }}"
    assert prop.connection_template is not None
    assert prop.connection_template.hass is ctrl.hass
    assert prop._connection_template_raw == '{"method": "GET"}'
    assert prop.validation_template is not None
    assert prop.validation_template.hass is ctrl.hass
    assert prop._validation_template_raw == "{{ 'valid' }}"
    assert conn.updated_nodes[-1] == {"url": "/test"}
    assert prop.get_connection("any") is conn
    assert prop.name == "Test Name"
    assert prop.device_class == "temperature"
    assert prop.unit_of_measurement == "°C"
    assert prop.entity_category == "diagnostic"
    assert prop.state_class == SensorStateClass.MEASUREMENT
    assert prop.feature_flag is None
    assert prop.icon == "mdi:thermostat"

    # State class auto-mapping & validation errors
    with pytest.raises(ValueError, match="Invalid state_class 'invalid_class' in YAML"):
        prop.load_from_yaml({CONFIG_STATE_CLASS: "invalid_class"})

    for dev_cls in ("gas", "energy", "water", "carbon_monoxide"):
        p_tot = DeviceProperty("p_tot", _StubConnection(), ctrl)
        assert p_tot.load_from_yaml({CONFIG_DEVICE_CLASS: dev_cls}) is True
        assert p_tot.state_class == SensorStateClass.TOTAL_INCREASING

    for dev_cls in (
        "power",
        "temperature",
        "humidity",
        "voltage",
        "current",
        "pressure",
    ):
        p_meas = DeviceProperty("p_meas", _StubConnection(), ctrl)
        assert p_meas.load_from_yaml({CONFIG_DEVICE_CLASS: dev_cls}) is True
        assert p_meas.state_class == SensorStateClass.MEASUREMENT

    for non_mapped in ("battery", "unrecognized_custom_class"):
        p_none = DeviceProperty("p_none", _StubConnection(), ctrl)
        assert p_none.load_from_yaml({CONFIG_DEVICE_CLASS: non_mapped}) is True
        assert p_none.state_class is None


def test_device_property_units_and_value_is_string_matrix() -> None:
    """Test set_unit_of_measurement, set_device_state_for_values, and value_is_string."""
    prop = DeviceProperty("test_unit", _StubConnection(), _StubController())
    prop.set_device_state_for_values({"power": "on"})

    prop.set_unit_of_measurement("C")
    assert prop.unit_of_measurement == UnitOfTemperature.CELSIUS
    prop.set_unit_of_measurement("UNKNOWN_UNIT")
    assert prop.unit_of_measurement == "UNKNOWN_UNIT"

    for p_type in (PROPERTY_TYPE_STRING, PROPERTY_TYPE_SENSOR, PROPERTY_TYPE_ENUM):
        prop._type = p_type
        prop._device_class = None
        assert prop.value_is_string is True

    prop._type = "other_type"
    prop._device_class = SensorDeviceClass.ENUM
    assert prop.value_is_string is True

    prop._device_class = None
    assert prop.value_is_string is False
    prop._device_class = "temperature"
    assert prop.value_is_string is False


def test_device_property_raw_state_resolution_and_subdevice_routing() -> None:
    """Test _resolve_raw_state_source priority order, dataclass fallback, and subdevice routing."""
    ctrl = _StubController()
    getter = _StubStatusGetter({"from_getter": 1})
    prop = DeviceProperty("test_prop", _StubConnection(), ctrl, getter)
    prop._device_state = {"from_self": 1}

    # 1. pure_device_state takes priority when non-empty
    ctrl.pure_device_state = {"pure": 1}
    ctrl.device_state = {"parsed": 1}
    assert prop._resolve_raw_state_source() == {"pure": 1}

    # 2. device_state fallback when pure_device_state is empty/None
    ctrl.pure_device_state = {}
    assert prop._resolve_raw_state_source() == {"parsed": 1}

    # 3. _status_getter.value fallback when controller states are empty/None
    ctrl.device_state = None
    assert prop._resolve_raw_state_source() == {"from_getter": 1}

    # 4. controller.get_property(KEY_STATUS) fallback & error tolerance
    prop._status_getter = None
    ctrl._props[KEY_STATUS] = _StubPropRef(value={"status_key": "val_123"})
    assert prop._resolve_raw_state_source() == {"status_key": "val_123"}

    for err in (KeyError("k"), AttributeError("a"), TypeError("t")):
        ctrl.prop_error = err
        assert prop._resolve_raw_state_source() == {"from_self": 1}
    ctrl.prop_error = None
    ctrl._props.clear()

    # 5. Raw _device_state fallbacks: dict, dataclass instance vs dataclass class, None
    prop._controller = None
    assert prop._resolve_raw_state_source() == {"from_self": 1}
    assert prop._raw_device_state == {"from_self": 1}

    prop._device_state = _StateDataclass(power="on", temp=22)
    assert prop._resolve_raw_state_source() == {"power": "on", "temp": 22}

    prop._device_state = _StateDataclass
    assert prop._resolve_raw_state_source() is None
    assert prop._raw_device_state == {}

    # 6. _route_to_subdevice paths
    prop._controller = ctrl
    ctrl.device_id = "ac_unit_2"
    assert ctrl.loader is not None
    ctrl.loader.parsed_yaml_cache = {
        "ac_unit_2": {
            KEY_DEVICE_CONFIG: {
                KEY_IDENTIFIERS: {
                    KEY_PATH_TO_DEVICES: ["Devices"],
                    CONF_SUBDEVICE_ID: ["id"],
                }
            }
        }
    }

    assert prop._route_to_subdevice({"Devices": None}) == {"Devices": None}
    assert prop._route_to_subdevice({"Devices": []}) == {"Devices": []}
    assert prop._route_to_subdevice({"Devices": "bad"}) == {"Devices": "bad"}

    devices = [
        {"id": "ac_unit_1", "name": "Unit 1"},
        {"id": "ac_unit_2", "name": "Unit 2"},
    ]
    assert prop._route_to_subdevice({"Devices": devices}) == {
        "id": "ac_unit_2",
        "name": "Unit 2",
    }

    devices_mode = [
        {"id": "wifi_kit_0", "wifi": True},
        {"id": "ac_unknown", KEY_DEVICE_MODE: "Cool", "temp": 24},
    ]
    assert prop._route_to_subdevice({"Devices": devices_mode}) == {
        "id": "ac_unknown",
        KEY_DEVICE_MODE: "Cool",
        "temp": 24,
    }

    assert prop._route_to_subdevice(
        {"Devices": [{"id": "x", "p": "on"}, {"id": "y", "p": "off"}]}
    ) == {"id": "x", "p": "on"}
    assert prop._route_to_subdevice({"Devices": ["non_dict"]}) == {}

    ctrl.loader.parsed_yaml_cache["ac_unit_2"][KEY_DEVICE_CONFIG][KEY_IDENTIFIERS] = {
        KEY_PATH_TO_DEVICES: ["Devices"],
        CONF_SUBDEVICE_ID: ["uuid"],
    }
    assert prop._route_to_subdevice(
        {
            "Devices": [
                {"id": "ac_unit_2", "uuid": "decoy"},
                {"id": "other", "uuid": "ac_unit_2", "name": "Target"},
            ]
        }
    ) == {"id": "other", "uuid": "ac_unit_2", "name": "Target"}

    ctrl.loader.parsed_yaml_cache["ac_unit_2"][KEY_DEVICE_CONFIG][KEY_IDENTIFIERS] = {
        KEY_PATH_TO_DEVICES: ["Devices"],
    }
    assert prop._route_to_subdevice(
        {"Devices": [{"id": "other"}, {"id": "ac_unit_2", "name": "Target"}]}
    ) == {"id": "ac_unit_2", "name": "Target"}

    ctrl.loader.parsed_yaml_cache["ac_unit_2"][KEY_DEVICE_CONFIG][KEY_IDENTIFIERS] = {}
    assert prop._route_to_subdevice({"general": 1}) == {"general": 1}

    prop._controller = None
    assert prop._route_to_subdevice({"general": 2}) == {"general": 2}


async def test_device_property_validation_calculation_and_async_update() -> None:
    """Test is_valid, calculate_value_from_state, async_update_state, state_attributes, and async_set_value."""
    ctrl = _StubController()
    prop = DeviceProperty("test_prop", _StubConnection(), ctrl)

    # is_valid matrix
    assert prop.is_valid({"power": "on"}) is True
    prop._validation_template = Template(
        "{{ 'valid' if device_state.power == 'on' else 'invalid' }}", ctrl.hass
    )
    assert prop.is_valid(None) is True
    assert prop.is_valid({"power": "on"}) is True
    assert prop._device_state == {"power": "on"}
    assert prop.is_valid({"power": "off"}) is False

    prop._validation_template = Template("{{ 1 / 0 }}", ctrl.hass)
    assert prop.is_valid({"power": "on"}) is False

    # calculate_value_from_state & async_update_state
    prop._status_getter = _StubStatusGetter({"power": "got"})
    assert prop.calculate_value_from_state({"power": "on"}) is None
    prop._status_template = Template("{{ device_state.power }}", ctrl.hass)
    assert prop.calculate_value_from_state(None) is None

    assert await prop.async_update_state({"power": "override"}, False) == "override"
    assert prop._device_state == {"power": "override"}
    assert prop.state_attributes == {"test_prop": "override"}

    assert await prop.async_update_state(None, False) == "got"
    assert prop._device_state == {"power": "got"}

    # Empty dict or None leaves existing value unchanged
    prop.value = "STATE_ON"
    prop._status_template = None
    await prop.async_update_state(device_state_override={})
    assert prop.value == "STATE_ON"

    prop._status_getter = None
    assert await prop.async_update_state(None, False) == "STATE_ON"
    assert prop._device_state is None

    # TemplateError in calculate_value_from_state raises HomeAssistantError
    prop._status_template = Template("{{ 1 / 0 }}", ctrl.hass)
    with pytest.raises(
        HomeAssistantError, match="Template evaluation failed for test_prop"
    ):
        prop.calculate_value_from_state({"power": "on"})

    # Base async_set_value always returns False
    assert await prop.async_set_value("off") is False
    assert await prop.async_set_value("off", device_id="main") is False


def test_device_property_optimistic_cascades() -> None:
    """Test apply_optimistic_cascades across root, nested, bool keys, defaults, and invalid rules."""
    prop = DeviceProperty("test_cascades", _StubConnection(), _StubController())

    # Guard cases: non-dict state, missing/empty/non-list cascades
    prop._config = {
        CONFIG_OPTIMISTIC_CASCADES: [
            {CONFIG_TARGET_NODE: "Operation.power", CONFIG_VALUE_MAP: {"heat": "On"}}
        ]
    }
    prop.apply_optimistic_cascades("not_a_dict", "heat")

    for invalid_cascades in (None, [], "invalid_type", 123):
        prop._config = (
            {}
            if invalid_cascades is None
            else {CONFIG_OPTIMISTIC_CASCADES: invalid_cascades}
        )
        state_noop = {"power": "Off"}
        prop.apply_optimistic_cascades(state_noop, "cool")
        assert state_noop == {"power": "Off"}

    # Empty Devices list does not fail or create Devices[0]
    prop._config = {
        CONFIG_OPTIMISTIC_CASCADES: [
            {CONFIG_TARGET_NODE: "power", CONFIG_VALUE_MAP: {"on": "On"}}
        ]
    }
    state_empty_devs: dict[str, Any] = {"power": "Off", "Devices": []}
    prop.apply_optimistic_cascades(state_empty_devs, "on")
    assert state_empty_devs == {"power": "On", "Devices": []}

    # Root + Devices[0] nested cascade with default fallback
    prop.load_from_yaml(
        {
            CONFIG_OPTIMISTIC_CASCADES: [
                {
                    CONFIG_TARGET_NODE: "AC_FUN_POWER",
                    CONFIG_VALUE_MAP: {"off": "Off", "default": "On"},
                },
                {
                    CONFIG_TARGET_NODE: "Operation.sub.power",
                    CONFIG_VALUE_MAP: {"off": "Off", "default": "On"},
                },
            ]
        }
    )
    state_nested: dict[str, Any] = {
        "AC_FUN_POWER": "Off",
        "Operation": "primitive_string",
        "Devices": [{"Operation": 12345}],
    }
    prop.apply_optimistic_cascades(state_nested, "cool")
    assert state_nested["AC_FUN_POWER"] == "On"
    assert state_nested["Operation"]["sub"]["power"] == "On"
    assert state_nested["Devices"][0]["Operation"]["sub"]["power"] == "On"

    prop.apply_optimistic_cascades(state_nested, "off")
    assert state_nested["AC_FUN_POWER"] == "Off"
    assert state_nested["Operation"]["sub"]["power"] == "Off"

    # Boolean value_map keys map to on/off and true/false
    prop._config = {
        CONFIG_OPTIMISTIC_CASCADES: [
            {
                CONFIG_TARGET_NODE: "Operation.power",
                CONFIG_VALUE_MAP: {False: "PowerOff", True: "PowerOn"},
            }
        ]
    }
    for input_val, expected in (
        ("off", "PowerOff"),
        (False, "PowerOff"),
        ("false", "PowerOff"),
        ("on", "PowerOn"),
        (True, "PowerOn"),
        ("true", "PowerOn"),
    ):
        state_bool = {"Operation": {"power": "Initial"}}
        prop.apply_optimistic_cascades(state_bool, input_val)
        assert state_bool["Operation"]["power"] == expected

    # Malformed rules skipped (continue, not break) and non-dict/non-str guards
    prop._config = {
        CONFIG_OPTIMISTIC_CASCADES: [
            None,
            "invalid_non_dict_rule",
            {CONFIG_TARGET_NODE: None, CONFIG_VALUE_MAP: {"on": "On"}},
            {CONFIG_TARGET_NODE: "", CONFIG_VALUE_MAP: {"on": "On"}},
            {CONFIG_TARGET_NODE: 9999, CONFIG_VALUE_MAP: {"on": "On"}},
            {CONFIG_TARGET_NODE: "valid_target", CONFIG_VALUE_MAP: {}},
            {CONFIG_TARGET_NODE: "valid_target2", CONFIG_VALUE_MAP: None},
            {CONFIG_TARGET_NODE: "power", CONFIG_VALUE_MAP: {"on": "On"}},
            {CONFIG_TARGET_NODE: "fan", CONFIG_VALUE_MAP: {"on": "High"}},
        ]
    }
    state_multi: dict[str, Any] = {"power": "Off", "fan": "Low"}
    prop.apply_optimistic_cascades(state_multi, "on")
    assert state_multi == {"power": "On", "fan": "High"}


# ---------------------------------------------------------------------------
# 3. GetJsonStatus
# ---------------------------------------------------------------------------


def test_get_json_status_init_yaml_and_template_synthesis() -> None:
    """Test GetJsonStatus initialization, template inheritance, and synthesis."""
    ctrl = _StubController()
    conn_init = _StubConnection()
    g = GetJsonStatus("json_getter", conn_init, ctrl)
    assert g._name == "json_getter"
    assert g._connection is conn_init
    assert g._controller is ctrl
    assert g._status_getter is g
    assert g._json_status is None
    assert g._attrs == {}
    assert GetJsonStatus.match_type(STATUS_GETTER_JSON) is True
    assert GetJsonStatus.match_type("other") is False

    # Inherit public connection_template and private _connection_template fallback
    custom_tmpl = Template('{"method": "GET", "url": "/inherited"}', ctrl.hass)
    g_pub = GetJsonStatus(
        "g_pub", _StubConnection(connection_template=custom_tmpl), ctrl
    )
    assert g_pub.load_from_yaml({CONFIG_TYPE: STATUS_GETTER_JSON}) is True
    assert g_pub.connection_template is custom_tmpl

    g_priv = GetJsonStatus(
        "g_priv", _StubConnection(private_connection_template=custom_tmpl), ctrl
    )
    assert g_priv.load_from_yaml({CONFIG_TYPE: STATUS_GETTER_JSON}) is True
    assert g_priv.connection_template is custom_tmpl

    # Synthesize from public params url (beats _params) and from _params url
    g_synth_pub = GetJsonStatus(
        "g_synth_pub",
        _StubConnection(
            params={"method": "GET", "url": "/api/public"},
            private_params={"method": "POST", "url": "/api/private"},
        ),
        ctrl,
    )
    assert g_synth_pub.load_from_yaml({CONFIG_TYPE: STATUS_GETTER_JSON}) is True
    assert g_synth_pub.connection_template is not None
    assert g_synth_pub.connection_template.template == json_dumps(
        {"method": "GET", "url": "/api/public"}
    )

    # Default payload when no template and no url in params
    g_def = GetJsonStatus("g_def", _StubConnection(), ctrl)
    assert g_def.load_from_yaml({CONFIG_TYPE: STATUS_GETTER_JSON}) is True
    assert g_def.connection_template is not None
    assert g_def.connection_template.template == DEFAULT_JSON_STATUS_PAYLOAD

    # Sync connection (is_async_native=False) does not synthesize or inherit
    g_sync = GetJsonStatus(
        "g_sync",
        _StubConnection(is_async_native=False, connection_template=custom_tmpl),
        ctrl,
    )
    assert g_sync.load_from_yaml({CONFIG_TYPE: STATUS_GETTER_JSON}) is True
    assert g_sync.connection_template is None


def test_get_json_status_calculate_value_from_state() -> None:
    """Test GetJsonStatus.calculate_value_from_state across JSON, raw string, dict, and errors."""
    ctrl = _StubController()
    legacy_hass = _StubHass(legacy_templates=True)
    g = GetJsonStatus("test_json", _StubConnection(is_async_native=False), ctrl)

    assert g.calculate_value_from_state(None) is None
    assert g.calculate_value_from_state({"raw": 1}) == {"raw": 1}

    # Modern Template parses JSON into dict directly (non-str branch)
    g._status_template = Template('{"result": "{{ device_state.val }}"}', ctrl.hass)
    assert g.calculate_value_from_state({"val": "ok"}) == {"result": "ok"}

    # Legacy Template returns padded JSON string -> stripped and json_loads parsed
    g._status_template = Template(
        '  {"result": "{{ device_state.val }}"}  ', legacy_hass
    )
    assert g.calculate_value_from_state({"val": "ok"}) == {"result": "ok"}

    # Non-JSON string -> stripped and returned as str
    g._status_template = Template("{{ '  plain_text  ' }}", legacy_hass)
    assert g.calculate_value_from_state({"val": "ok"}) == "plain_text"

    # TemplateError raises HomeAssistantError
    g._status_template = Template("{{ 1 / 0 }}", ctrl.hass)
    with pytest.raises(
        HomeAssistantError, match="Template evaluation failed for test_json"
    ):
        g.calculate_value_from_state({"val": "ok"})


async def test_get_json_status_async_update_state() -> None:
    """Test GetJsonStatus.async_update_state across async native, synthesis, sync, and error paths."""
    ctrl = _StubController()

    # 1. connection is None -> returns None
    g_none_conn = GetJsonStatus("g_none", _StubConnection(), ctrl)
    g_none_conn._connection = None
    assert await g_none_conn.async_update_state() is None

    # 2. Missing connection_template and no url in params -> returns None
    conn = _StubConnection()
    g = GetJsonStatus("test_getter", conn, ctrl)
    assert await g.async_update_state(None, False) is None

    # 3. Synthesize connection_template on-the-fly from params["url"]
    conn.params = {"method": "GET", "url": "/api/v1/devicestate"}
    conn.execute_result = ('{"power": "on", "mode": "cool"}', 200)
    res_synth = await g.async_update_state()
    assert res_synth == {"power": "on", "mode": "cool"}
    assert g.connection_template is not None
    assert g.connection_template.template == json_dumps(
        {"method": "GET", "url": "/api/v1/devicestate"}
    )
    assert conn.execute_calls[-1] == (
        "GET",
        "/api/v1/devicestate",
        None,
        {},
        {"_is_poll": True},
    )

    # 4. Missing duid when controller=None and config lacks duid -> ValueError
    g._controller = None
    conn.config = {}
    with pytest.raises(ValueError, match="Could not resolve device_id/duid"):
        await g.async_update_state(None, False)

    # 5. Controller DUID + token + JSON template (non-str dict from modern Template)
    g._controller = ctrl
    ctrl.device_id = "ctrl_duid"
    conn.params = None
    conn._params = {"base_key": "base_val"}
    conn.config = {CONF_TOKEN_KEY: "my_secret_token"}
    g._connection_template = Template(
        '{"method": "GET", "url": "/status/{{ device_id }}", "headers": {"Token": "{{ token }}"}}',
        ctrl.hass,
    )
    conn.execute_result = ('{"power": "on", "temperature": 22}', None)
    conn.execute_calls.clear()
    res = await g.async_update_state(None, False)
    assert res == {"power": "on", "temperature": 22}
    assert g.value == {"power": "on", "temperature": 22}
    assert g._json_status == {"power": "on", "temperature": 22}
    assert g.state_attributes == {
        KEY_DEVICE_STATE: json_dumps({"power": "on", "temperature": 22})
    }
    assert conn.execute_calls[-1] == (
        "GET",
        "/status/ctrl_duid",
        None,
        {"Token": "my_secret_token"},
        {"_is_poll": True},
    )

    # 6. Controller=None fallback to connection.config[KEY_DUID] and legacy string JSON render
    legacy_hass = _StubHass(legacy_templates=True)
    g._controller = None
    conn.config = {KEY_DUID: "cfg_duid", CONF_TOKEN_KEY: "my_token"}
    g._connection_template = Template(
        '{"method": "GET", "url": "/status/{{ duid }}", "headers": {"Token": "{{ token }}"}}',
        legacy_hass,
    )
    conn.execute_result = ('{"power": "on"}', None)
    conn.execute_calls.clear()
    assert await g.async_update_state(None, False) == {"power": "on"}
    assert conn.execute_calls[-1] == (
        "GET",
        "/status/cfg_duid",
        None,
        {"Token": "my_token"},
        {"_is_poll": True},
    )
    g._controller = ctrl

    # 7. Raw (non-JSON) connection template payload, None response, invalid JSON response
    g._connection_template = Template("GET_STATUS_RAW", ctrl.hass)
    conn.execute_result = ('{"raw_result": 1}', None)
    conn.execute_calls.clear()
    assert await g.async_update_state(None, False) == {"raw_result": 1}
    assert conn.execute_calls[-1] == (
        None,
        None,
        "GET_STATUS_RAW",
        None,
        {"_is_poll": True},
    )

    conn.execute_result = (None, None)
    assert await g.async_update_state(None, False) is None

    conn.execute_result = ("not_json_at_all", None)
    assert await g.async_update_state(None, False) is None

    # 8. Sync connection mode: None, dict result, and CannotConnect propagation
    conn.is_async_native = False
    conn.retry_result = None
    g._connection_template = Template("sync_tmpl", ctrl.hass)
    assert await g.async_update_state(None, False) is None
    assert g.state_attributes == {KEY_DEVICE_STATE: None}

    g.value = {"prev_state": 1}
    conn.retry_result = {"sync_ok": True}
    conn.retry_calls.clear()
    assert await g.async_update_state(None, False) == {"sync_ok": True}
    assert g.value == {"sync_ok": True}
    assert conn.retry_calls[-1] == (
        g.connection_template,
        None,
        {"prev_state": 1},
        None,
    )

    conn.retry_error = CannotConnect("Connection failed after 5 retries")
    with pytest.raises(CannotConnect, match="Connection failed after 5 retries"):
        await g.async_update_state(None, False)


# ---------------------------------------------------------------------------
# 4. DeviceOperation
# ---------------------------------------------------------------------------


def test_device_operation_resolve_async_params() -> None:
    """Test DeviceOperation._resolve_async_params, match_value, and convert_hass_to_dev."""
    ctrl = _StubController()
    legacy_hass = _StubHass(legacy_templates=True)
    conn = _StubConnection(private_params={"method": "GET", "url": "/api"})
    op = DeviceOperation("test_op", conn, ctrl)

    assert op.match_value("on") is False
    assert op.convert_hass_to_dev("val") == "val"

    # 1. Fallback to connection._params when templates are None; empty params -> None
    assert op._resolve_async_params(conn, "val") == {"method": "GET", "url": "/api"}
    conn_empty = _StubConnection(private_params={})
    assert op._resolve_async_params(conn_empty, "val") is None

    # 2. Modern Template returns dict directly with device_state context
    op._connection_template = Template('{"temp": "{{ device_state.val }}"}', ctrl.hass)
    assert op._resolve_async_params(
        conn_empty, "v", duid="123", device_state={"val": 25}
    ) == {"temp": "25"}

    # 3. Legacy Template returns non-JSON raw string -> KEY_RAW_PAYLOAD
    op._connection_template = Template("RAW_CMD_{{ value }}", legacy_hass)
    assert op._resolve_async_params(conn_empty, "high") == {
        KEY_RAW_PAYLOAD: "RAW_CMD_high"
    }

    # 4. Merge raw_params + base_template + op template (different vs identical templates)
    conn_merged = _StubConnection(
        params={"fallback_key": "from_pub"},
        private_connection_template=Template(
            '{"base_param": "from_conn", "url": "/base", "dev": "{{ device_id }}"}',
            ctrl.hass,
        ),
    )
    op._connection_template = Template(
        '{"method": "POST", "url": "/set/{{ value }}"}', ctrl.hass
    )
    assert op._resolve_async_params(conn_merged, "cool", duid="12345") == {
        "fallback_key": "from_pub",
        "base_param": "from_conn",
        "dev": "12345",
        "method": "POST",
        "url": "/set/cool",
    }

    # Base template yielding valid JSON string (legacy) and invalid JSON fallback
    conn_merged._connection_template = Template(
        '{"base_param": "from_legacy"}', legacy_hass
    )
    assert op._resolve_async_params(conn_merged, "cool", duid="12345") == {
        "fallback_key": "from_pub",
        "base_param": "from_legacy",
        "method": "POST",
        "url": "/set/cool",
    }

    conn_merged._connection_template = Template("not_json_base", legacy_hass)
    assert op._resolve_async_params(conn_merged, "cool", duid="12345") == {
        "fallback_key": "from_pub",
        "method": "POST",
        "url": "/set/cool",
    }

    # Shared template: base_template is template_to_use -> rendered exactly once
    shared_tmpl = Template('{"method": "GET", "url": "/test"}', legacy_hass)
    op._connection_template = None
    conn_merged._connection_template = shared_tmpl
    with patch.object(
        properties_mod, "render_template", wraps=properties_mod.render_template
    ) as spy_render:
        assert op._resolve_async_params(conn_merged, "v") == {
            "fallback_key": "from_pub",
            "method": "GET",
            "url": "/test",
        }
        assert spy_render.call_count == 1


async def test_device_operation_async_set_value_async_native() -> None:
    """Test DeviceOperation.async_set_value in async native mode, routing, raw payloads, and errors."""
    ctrl = _StubController()
    conn = _StubConnection(config={KEY_DUID: "duid_123"})
    op = DeviceOperation("test_op", conn, ctrl)

    # 1. Frontend sanitization error discards command without network call
    with (
        patch.object(
            op, "convert_hass_to_dev", side_effect=ValueError("Invalid value")
        ),
        patch.object(properties_mod._LOGGER, "warning") as mock_warn,
    ):
        assert await op.async_set_value("bad_value") is False
        assert "Command discarded" in mock_warn.call_args[0][0]
    assert conn.execute_calls == []

    # 2. Missing duid anywhere -> ValueError
    ctrl.device_id = None
    conn.config = {}
    with pytest.raises(ValueError, match="Could not resolve device_id/duid"):
        await op.async_set_value("val")

    # 3. _resolve_async_params returns None -> returns False
    ctrl.device_id = "test_duid"
    assert await op.async_set_value("val") is False

    # 4. Raw payload bypasses HTTP JSON framing
    op._connection_template = Template("payload", _StubHass(legacy_templates=True))
    assert await op.async_set_value("val") is True
    assert conn.execute_calls[-1] == (None, None, "payload", None, {})

    # 5. Positional args to _resolve_async_params + DUID from config when ctrl.device_id is None
    ctrl.device_id = None
    conn.config = {KEY_DUID: "duid_from_cfg"}
    op._device_state = {"power": "off"}
    with patch.object(
        op, "_resolve_async_params", return_value={"method": "POST", "url": "/api/set"}
    ) as mock_resolve:
        assert await op.async_set_value("test_val", device_id="explicit_duid") is True
        mock_resolve.assert_called_once_with(
            conn, "test_val", "explicit_duid", {"power": "off"}
        )

    # 6. HTTP JSON payload, routing fallbacks (params -> conn._params -> ctrl.connection._params -> POST)
    conn.execute_calls.clear()
    op._connection_template = Template(
        '{"method": "POST", "url": "/set/{{ value }}", "json": {"state": "{{ value }}"}, "headers": {"Content-Type": "json"}}',
        ctrl.hass,
    )
    assert await op.async_set_value("on") is True
    assert conn.execute_calls[-1] == (
        "POST",
        "/set/on",
        json_dumps({"state": "on"}),
        {"Content-Type": "json"},
        {"device_state": {"power": "off"}},
    )

    # Fallback to conn._params for method, url, headers (both via _resolve_async_params and direct async_set_value fallback)
    op._connection_template = Template('{"json": {"power": "on"}}', ctrl.hass)
    conn._params = {
        "method": "PUT",
        "url": "/conn_endpoint",
        "headers": {"X-Custom": "1"},
    }
    conn.execute_calls.clear()
    assert await op.async_set_value("on") is True
    assert conn.execute_calls[-1] == (
        "PUT",
        "/conn_endpoint",
        json_dumps({"power": "on"}),
        {"X-Custom": "1"},
        {"device_state": {"power": "off"}},
    )

    ctrl.connection = None
    with patch.object(op, "_resolve_async_params", return_value={}):
        conn.execute_calls.clear()
        assert await op.async_set_value("on") is True
        assert conn.execute_calls[-1] == (
            "PUT",
            "/conn_endpoint",
            None,
            {"X-Custom": "1"},
            {"device_state": {"power": "off"}},
        )

    with patch.object(
        op, "_resolve_async_params", return_value={"method": "DELETE", "url": "/keep"}
    ):
        conn.execute_calls.clear()
        assert await op.async_set_value("on") is True
        assert conn.execute_calls[-1] == (
            "DELETE",
            "/keep",
            None,
            {"X-Custom": "1"},
            {"device_state": {"power": "off"}},
        )

    # Fallback to controller.connection._params and POST default
    conn._params = {}
    ctrl_conn = _StubConnection(private_params={"method": "PATCH", "url": "/ctrl_ep"})
    ctrl.connection = ctrl_conn
    conn.execute_calls.clear()
    assert await op.async_set_value("on") is True
    assert conn.execute_calls[-1] == (
        "PATCH",
        "/ctrl_ep",
        json_dumps({"power": "on"}),
        {},
        {"device_state": {"power": "off"}},
    )

    ctrl_conn._params = {"url": "/ctrl_ep"}
    conn.execute_calls.clear()
    assert await op.async_set_value("on") is True
    assert conn.execute_calls[-1][0] == "POST"

    # Response None -> False
    conn.execute_result = (None, 500)
    assert await op.async_set_value("on") is False
    conn.execute_result = ("{}", None)

    # Strict routing ValueError on missing url or non-string method/url
    ctrl_conn._params = {"method": "POST"}
    with pytest.raises(
        ValueError, match="Strict routing failed: Missing method or url"
    ):
        await op.async_set_value("on")

    ctrl.connection = None
    conn._params = {"method": 12345, "url": 67890}
    with pytest.raises(
        ValueError, match="Strict routing failed: Missing method or url"
    ):
        await op.async_set_value("on")

    # 7. Exception mapping -> HomeAssistantError
    conn._params = {"method": "POST", "url": "/ok"}
    for err, msg_pat in (
        (CannotConnect("cannot"), "Connection error: could not set value for test_op"),
        (AuthError("auth"), "Connection error: could not set value for test_op"),
        (TimeoutError("timeout"), "Unexpected error when setting test_op"),
        (OSError("net"), "Unexpected error when setting test_op"),
    ):
        conn.execute_error = err
        with pytest.raises(HomeAssistantError, match=msg_pat):
            await op.async_set_value("on")


async def test_device_operation_async_set_value_sync_mode() -> None:
    """Test DeviceOperation.async_set_value in sync mode and error conversion."""
    ctrl = _StubController()
    ctrl.device_id = None
    ctrl.device_state = None
    conn = _StubConnection(is_async_native=False)
    op = DeviceOperation("test_sync_op", conn, ctrl)
    op._connection_template = Template("cmd", ctrl.hass)

    assert await op.async_set_value("val") is True
    assert conn.retry_calls[-1] == (op.connection_template, "val", {}, None)

    assert await op.async_set_value("val", device_id="main") is True
    assert conn.retry_calls[-1] == (op.connection_template, "val", {}, "main")

    for err in (CannotConnect("sync err"), AuthError("sync auth")):
        conn.retry_error = err
        with pytest.raises(
            HomeAssistantError,
            match="Connection error: could not set value for test_sync_op",
        ):
            await op.async_set_value("val")


# ---------------------------------------------------------------------------
# 5. BasicDeviceOperation, ModeOperation, UniqueIdProperty, SwitchOperation
# ---------------------------------------------------------------------------


def test_basic_device_operation_yaml_mappings_and_connections() -> None:
    """Test BasicDeviceOperation YAML loading, value maps, connections, and conversions."""
    conn = _StubConnection()
    ctrl = _StubController()
    with patch.dict(
        "custom_components.climate_ip.properties.YAML_NAME_TO_HA_FEATURE",
        {"test_flag_op": ClimateEntityFeature.FAN_MODE},
        clear=True,
    ):
        op = BasicDeviceOperation("test_flag_op", conn, ctrl)
        assert (
            op.load_from_yaml({CONFIG_TYPE: "op", CONFIG_DEVICE_OPERATION_VALUES: {}})
            is False
        )
        assert op.load_from_yaml({CONFIG_TYPE: "op"}) is False

        conn.updated_nodes.clear()
        yaml_node = {
            CONFIG_TYPE: "modes",
            CONFIG_DEVICE_OPERATION_VALUES: {
                "on": {
                    CONFIG_DEVICE_OPERATION_VALUE: "1",
                    CONFIG_DEVICE_CONNECTION: {"type": "on_conn"},
                },
                "off": {
                    CONFIG_DEVICE_OPERATION_VALUE: "0",
                    "fallback_key": "val",
                },
            },
        }
        assert op.load_from_yaml(yaml_node) is True
        assert op.feature_flag is ClimateEntityFeature.FAN_MODE
        assert op.all_values == ["on", "off"]
        assert op.match_value("on") is True
        assert op.match_value("dry") is False
        assert op.convert_dev_to_hass(" 1 ") == "on"
        assert op.convert_dev_to_hass("unmapped_dev") == "unmapped_dev"
        assert op.convert_hass_to_dev("off") == "0"
        assert op.convert_hass_to_dev("unmapped_ha") == "unmapped_ha"
        assert {"type": "on_conn"} in conn.updated_nodes
        assert {"value": "0", "fallback_key": "val"} in conn.updated_nodes

    op_plain = BasicDeviceOperation("plain", conn, ctrl)
    assert op_plain.feature_flag is None
    op_plain._value_connections_map = {"on": "on_conn_obj"}
    assert op_plain.get_connection("on") == "on_conn_obj"
    assert op_plain.get_connection("off") is conn


def test_basic_device_operation_dynamic_values_caching_and_flicker() -> None:
    """Test dynamic value validation, HVAC cache keys, cache invalidation, and flicker detection."""
    ctrl = _StubController()
    op = BasicDeviceOperation(ATTR_FAN_MODE, _StubConnection(), ctrl)

    # Static values returned directly when no validation templates exist
    op._values = ["auto", "low"]
    assert op.values == ["auto", "low"]

    yaml_node = {
        CONFIG_TYPE: "modes",
        CONFIG_DEVICE_OPERATION_VALUES: {
            "auto": {
                CONFIG_DEVICE_OPERATION_VALUE: "0",
                CONFIG_DEVICE_VALIDATION_TEMPLATE: "{% if device_state.p == 1 %}valid{% endif %}",
            },
            "low": {
                CONFIG_DEVICE_OPERATION_VALUE: "1",
                CONFIG_DEVICE_VALIDATION_TEMPLATE: "valid",
            },
            "turbo": {CONFIG_DEVICE_OPERATION_VALUE: "2"},
        },
    }
    op._values.clear()
    assert op.load_from_yaml(yaml_node) is True
    assert op.is_value_valid("turbo", {"p": 0}) is True
    assert op.is_value_valid("auto", None) is False

    # Resolve HVAC node via get_property_object, compute cache key via DeviceProperty
    hvac_prop_obj = _StubPropRef(state_node="hvac.mode")
    ctrl._prop_objs[ATTR_HVAC_MODE] = hvac_prop_obj
    ctrl._props[ATTR_HVAC_MODE] = DeviceProperty("cool_id", _StubConnection(), ctrl)
    op._device_state = {"p": 1, "hvac": {"mode": "cool"}}
    assert op.values == ["auto", "low", "turbo"]
    assert op._values_cache["cool_id_cool"] == ["auto", "low", "turbo"]
    assert ctrl.fan_modes_list_changed_pending_flicker is False

    # Cache hit preserves prior list and does NOT set flicker flag
    op._device_state = {"p": 0, "hvac": {"mode": "cool"}}
    assert op.values == ["auto", "low", "turbo"]
    assert ctrl.fan_modes_list_changed_pending_flicker is False

    # Cache miss (after clearing cache) recalculates and sets flicker flag on ATTR_FAN_MODE
    op.set_device_state_for_values({"p": 0, "hvac": {"mode": "cool"}})
    assert op._values_cache == {}
    assert op.values == ["low", "turbo"]
    assert ctrl.fan_modes_list_changed_pending_flicker is True

    # Cache key when controller.get_property returns a plain str & loader.operations checks ATTR_HVAC_MODE before KEY_HVAC
    ctrl._props[ATTR_HVAC_MODE] = "str_cache_key"
    ctrl._prop_objs.clear()
    assert ctrl.loader is not None
    ctrl.loader.operations = {
        ATTR_HVAC_MODE: _StubPropRef(state_node="hvac_node"),
        KEY_HVAC: _StubPropRef(state_node="mode"),
    }
    op._device_state = {"p": 1, "hvac_node": "dry", "mode": "heat"}
    assert op._resolve_hvac_node() == "dry"
    ctrl.loader.operations = {KEY_HVAC: _StubPropRef(state_node="mode")}
    assert op._resolve_hvac_node() == "heat"
    assert op._compute_cache_key(None) == "str_cache_key"

    # _resolve_hvac_node guard branches (empty state_node, missing loader, None controller)
    ctrl._prop_objs[ATTR_HVAC_MODE] = _StubPropRef(state_node="")
    ctrl.loader.operations = {}
    op._device_state = {"": "should_not_reach"}
    assert op._resolve_hvac_node() is None

    ctrl._prop_objs.clear()
    ctrl.loader = None
    assert op._resolve_hvac_node() is None

    op._controller = None
    assert op._resolve_hvac_node() is None


def test_mode_operation_and_unique_id_property() -> None:
    """Test ModeOperation init, match_type, mapping, state_attributes, and UniqueIdProperty."""
    ctrl = _StubController()
    conn = _StubConnection()
    getter = _StubStatusGetter()

    assert ModeOperation.match_type(PROPERTY_TYPE_MODE) is True
    assert ModeOperation.match_type(PROPERTY_TYPE_SWITCH) is False
    assert UniqueIdProperty.match_type(PROPERTY_TYPE_UNIQUE_ID) is True
    assert UniqueIdProperty.match_type(PROPERTY_TYPE_STRING) is False

    op_legacy = ModeOperation("hvac", conn, ctrl, status_getter=getter)
    assert op_legacy.id == ATTR_HVAC_MODE
    assert op_legacy._status_getter is getter
    assert op_legacy.feature_flag == ClimateEntityFeature.TARGET_TEMPERATURE

    op_fan = ModeOperation("fan", conn, ctrl)
    assert op_fan.id == ATTR_FAN_MODE
    assert op_fan.feature_flag == ClimateEntityFeature.FAN_MODE

    op_custom = ModeOperation("my_special", conn, ctrl)
    assert op_custom.id == "my_special_mode"
    assert op_custom.feature_flag is None

    assert (
        op_legacy.load_from_yaml(
            {
                CONFIG_TYPE: PROPERTY_TYPE_MODE,
                CONFIG_DEVICE_OPERATION_VALUES: {
                    "off": {CONFIG_DEVICE_OPERATION_VALUE: "0"},
                    "cool": {CONFIG_DEVICE_OPERATION_VALUE: "1"},
                },
            }
        )
        is True
    )
    assert op_legacy.convert_hass_to_dev("off") == "0"
    assert op_legacy.convert_dev_to_hass("1") == "cool"

    for attr_name, list_key in (
        (ATTR_HVAC_MODE, ATTR_HVAC_MODES),
        (ATTR_FAN_MODE, ATTR_FAN_MODES),
        (ATTR_PRESET_MODE, ATTR_PRESET_MODES),
        (ATTR_SWING_MODE, ATTR_SWING_MODES),
        ("my_special", "my_special_modes"),
    ):
        op_attr = ModeOperation(attr_name, conn, ctrl)
        op_attr.value = "v1"
        op_attr._values = ["v1", "v2"]
        assert op_attr.state_attributes == {op_attr.id: "v1", list_key: ["v1", "v2"]}

    with patch.object(properties_mod, "ATTR_HVAC_MODES", "custom_hvac_modes_mapped"):
        op_patched = ModeOperation(ATTR_HVAC_MODE, conn, ctrl)
        op_patched.value = "cool"
        op_patched._values = ["cool", "heat"]
        assert op_patched.state_attributes == {
            ATTR_HVAC_MODE: "cool",
            "custom_hvac_modes_mapped": ["cool", "heat"],
        }


def test_switch_operation_yaml_and_lock_eviction() -> None:
    """Test SwitchOperation boolean mapping and should_evict_all_locks behavior."""
    ctrl = _StubController()
    conn = _StubConnection()

    assert SwitchOperation.match_type(PROPERTY_TYPE_SWITCH) is True
    assert SwitchOperation.match_type(PROPERTY_TYPE_MODE) is False

    op = SwitchOperation("power", conn, ctrl)
    assert op.load_from_yaml(None) is False
    assert op.load_from_yaml({CONFIG_TYPE: "invalid"}) is False
    assert (
        op.load_from_yaml(
            {
                CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
                CONFIG_DEVICE_OPERATION_VALUES: {
                    STATE_ON: {CONFIG_DEVICE_OPERATION_VALUE: "1"},
                    STATE_OFF: {CONFIG_DEVICE_OPERATION_VALUE: "0"},
                },
            }
        )
        is True
    )
    assert op.convert_hass_to_dev(True) == "1"
    assert op.convert_hass_to_dev(False) == "0"

    op_on_only = SwitchOperation("on_only", conn, ctrl)
    assert (
        op_on_only.load_from_yaml(
            {
                CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
                CONFIG_DEVICE_OPERATION_VALUES: {
                    STATE_ON: {CONFIG_DEVICE_OPERATION_VALUE: "1"}
                },
            }
        )
        is True
    )
    assert op_on_only._values_ha_to_dev_map[True] == "1"
    assert False not in op_on_only._values_ha_to_dev_map

    op_off_only = SwitchOperation("off_only", conn, ctrl)
    assert (
        op_off_only.load_from_yaml(
            {
                CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
                CONFIG_DEVICE_OPERATION_VALUES: {
                    STATE_OFF: {CONFIG_DEVICE_OPERATION_VALUE: "0"}
                },
            }
        )
        is True
    )
    assert op_off_only._values_ha_to_dev_map[False] == "0"
    assert True not in op_off_only._values_ha_to_dev_map

    for pwr_id in ("power", "AC_FUN_POWER"):
        sw = SwitchOperation(pwr_id, conn, ctrl)
        sw._status_template = Template("{{ device_state.val }}", ctrl.hass)
        for off_val in ("off", "Off", "OFF", STATE_OFF):
            assert sw.should_evict_all_locks({"val": off_val}, {"val"}) is True
        for on_val in ("on", "On", "ON", "standby"):
            assert sw.should_evict_all_locks({"val": on_val}, {"val"}) is False
        assert sw.should_evict_all_locks({}, set()) is False

    for other_id in ("other_switch", "fan_power", "power_mode", "AC_FUN_POWER_2"):
        sw_other = SwitchOperation(other_id, conn, ctrl)
        sw_other._status_template = Template("{{ device_state.val }}", ctrl.hass)
        assert sw_other.should_evict_all_locks({"val": "off"}, {"val"}) is False

    with patch.object(
        op, "calculate_value_from_state", return_value="Off"
    ) as mock_calc:
        assert op.should_evict_all_locks({"dummy": 1}, set()) is True
        mock_calc.assert_called_once_with({"dummy": 1})
    with patch.object(op, "calculate_value_from_state", return_value=None):
        assert op.should_evict_all_locks({"dummy": 1}, set()) is False


# ---------------------------------------------------------------------------
# 6. BasicNumericOperation & TemperatureOperation
# ---------------------------------------------------------------------------


def test_basic_numeric_operation() -> None:
    """Test BasicNumericOperation YAML loading, value validation, match_value, and bounds."""
    assert BasicNumericOperation.match_type(PROPERTY_TYPE_NUMBER) is True
    assert BasicNumericOperation.match_type(PROPERTY_TYPE_TEMP) is False

    op = BasicNumericOperation("test_num", _StubConnection(), _StubController())
    assert op.load_from_yaml(None) is False
    assert op.load_from_yaml({}) is False
    assert op.load_from_yaml({CONFIG_TYPE: PROPERTY_TYPE_NUMBER}) is True
    assert op._min is None
    assert op._max is None

    assert (
        op.load_from_yaml(
            {
                CONFIG_TYPE: PROPERTY_TYPE_NUMBER,
                CONFIG_DEVICE_OPERATION_NUMBER_MIN: 10.0,
                CONFIG_DEVICE_OPERATION_NUMBER_MAX: 30.0,
            }
        )
        is True
    )
    assert op._min == 10.0
    assert op._max == 30.0

    # value getter/setter validation
    for raw_val, expected in (
        (None, None),
        (True, None),
        (23, 23.0),
        (" 23.5 ", 23.5),
        ("invalid", None),
        (object(), None),
    ):
        op.value = raw_val
        assert op.value == expected

    # match_value & convert_hass_to_dev errors
    assert op.match_value(True) is False
    assert op.match_value(20.0) is True
    assert op.match_value("not_a_num") is False
    with pytest.raises(TypeError, match="Invalid numeric value"):
        op.convert_hass_to_dev(True)
    with pytest.raises(ValueError, match="Invalid numeric value"):
        op.convert_hass_to_dev("not_a_num")

    # Clamping matrix: both bounds, min-only, max-only, unbounded
    assert (op.convert_hass_to_dev(10), op.convert_hass_to_dev(30)) == (10.0, 30.0)
    assert (op.convert_hass_to_dev(5), op.convert_hass_to_dev(35)) == (10.0, 30.0)
    assert op.convert_hass_to_dev(20) == 20.0

    op._min, op._max = 10.0, None
    assert (op.convert_hass_to_dev(5), op.convert_hass_to_dev(50)) == (10.0, 50.0)

    op._min, op._max = None, 30.0
    assert (op.convert_hass_to_dev(35), op.convert_hass_to_dev(-50)) == (30.0, -50.0)

    op._min, op._max = None, None
    assert op.convert_hass_to_dev(-100) == -100.0


def test_temperature_operation_yaml_and_unit_conversions() -> None:
    """Test TemperatureOperation YAML loading, unit conversions, and clamping boundaries."""
    ctrl = _StubController()
    op = TemperatureOperation("test_temp", _StubConnection(), ctrl)

    assert TemperatureOperation.match_type(PROPERTY_TYPE_TEMP) is True
    assert TemperatureOperation.match_type(PROPERTY_TYPE_NUMBER) is False

    assert op.load_from_yaml(None) is False
    assert op._unit_template is None
    assert op.load_from_yaml({CONFIG_TYPE: PROPERTY_TYPE_TEMP}) is True
    assert op._unit_template is None

    assert (
        op.load_from_yaml(
            {
                CONFIG_TYPE: PROPERTY_TYPE_TEMP,
                CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE: "{{ device_state.temp_unit }}",
            }
        )
        is True
    )
    assert isinstance(op._unit_template, Template)
    assert op._unit_template.hass is ctrl.hass

    # Unit conversion C <-> F and invalid device inputs
    op.set_device_unit(UnitOfTemperature.CELSIUS)
    op.set_hass_unit(UnitOfTemperature.FAHRENHEIT)
    assert op.unit_of_measurement == UnitOfTemperature.FAHRENHEIT
    assert op.convert_dev_to_hass(0) == 32.0
    assert op.convert_hass_to_dev(50.0) == 10.0

    op.set_device_unit(UnitOfTemperature.FAHRENHEIT)
    op.set_hass_unit(UnitOfTemperature.CELSIUS)
    assert op.convert_dev_to_hass(50.0) == 10.0
    assert op.convert_hass_to_dev(10.0) == 50.0
    assert op.convert_dev_to_hass(None) is None
    assert op.convert_dev_to_hass(True) is None
    assert op.convert_dev_to_hass("bad_temp") is None

    # Exact clamping boundaries in same unit
    op.set_device_unit(UnitOfTemperature.CELSIUS)
    op._min = 16.0
    op._max = 30.0
    assert (op.convert_hass_to_dev(16.0), op.convert_hass_to_dev(30.0)) == (16.0, 30.0)
    assert (op.convert_hass_to_dev(15.9), op.convert_hass_to_dev(30.1)) == (16.0, 30.0)

    with pytest.raises(TypeError, match="Invalid payload"):
        op.convert_hass_to_dev(True)
    for bad_input in (None, "unknown"):
        with pytest.raises(ValueError, match="Invalid payload"):
            op.convert_hass_to_dev(bad_input)


async def test_temperature_operation_state_calculation_and_async_update() -> None:
    """Test TemperatureOperation.calculate_value_from_state and async_update_state."""
    ctrl = _StubController()
    legacy_hass = _StubHass(legacy_templates=True)
    getter = _StubStatusGetter({"temp_unit": "F", "current_temp": " 77 "})
    op = TemperatureOperation("test_temp", _StubConnection(), ctrl, getter)
    op.set_hass_unit(UnitOfTemperature.CELSIUS)

    # 1. Dynamic unit_template + legacy string status_template via status_getter
    op._unit_template = Template("{{ device_state.temp_unit }}", ctrl.hass)
    op._status_template = Template("{{ device_state.current_temp }}", legacy_hass)
    assert await op.async_update_state() == 25.0
    assert op.value == 25.0
    assert op._device_unit == UnitOfTemperature.FAHRENHEIT

    # 2. device_state_override without unit_template preserves _device_unit
    op._unit_template = None
    assert (
        await op.async_update_state(device_state_override={"current_temp": "50"})
        == 10.0
    )

    # 3. None device_state and None status_template keep previous value
    op._status_getter = None
    assert await op.async_update_state() == 10.0
    op._status_template = None
    assert op.calculate_value_from_state({"current_temp": "50"}) is None

    # 4. Unit template errors in calculate_value_from_state and async_update_state
    op._unit_template = Template("{{ 1 / 0 }}", ctrl.hass)
    with pytest.raises(HomeAssistantError, match="Error rendering unit template"):
        op.calculate_value_from_state({"temp_unit": "C"})
    with pytest.raises(HomeAssistantError, match="Could not render unit template"):
        await op.async_update_state(device_state_override={"temp_unit": "C"})

    op._unit_template = Template("{{ 'unknown' }}", ctrl.hass)
    with pytest.raises(HomeAssistantError, match="Error parsing unit template"):
        op.calculate_value_from_state({"temp_unit": "unknown"})
    with pytest.raises(HomeAssistantError, match="Could not render unit template"):
        await op.async_update_state(device_state_override={"temp_unit": "unknown"})

    # 5. Status template TemplateError and TypeError in calculate_value_from_state
    op._unit_template = None
    op._status_template = Template("{{ 1 / 0 }}", ctrl.hass)
    with pytest.raises(HomeAssistantError, match="Error rendering status template"):
        op.calculate_value_from_state({"current_temp": "70"})

    op._status_template = 123  # type: ignore[assignment]
    with pytest.raises(HomeAssistantError, match="Error rendering status template"):
        op.calculate_value_from_state({"current_temp": "70"})
