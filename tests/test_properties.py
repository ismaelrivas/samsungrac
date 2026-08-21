# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for DeviceProperty, GetJsonStatus, ModeOperation and TemperatureOperation."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
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
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template

from custom_components.climate_ip.const import (
    CONF_SUBDEVICE_ID,
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
    DEFAULT_JSON_STATUS_PAYLOAD,
    KEY_DEVICE_CONFIG,
    KEY_DEVICE_MODE,
    KEY_DEVICE_STATE,
    KEY_DUID,
    KEY_IDENTIFIERS,
    KEY_PATH_TO_DEVICES,
    PROPERTY_TYPE_ENUM,
    PROPERTY_TYPE_MODE,
    PROPERTY_TYPE_STRING,
    PROPERTY_TYPE_SWITCH,
    PROPERTY_TYPE_TEMP,
    STATUS_GETTER_JSON,
)
from custom_components.climate_ip.exceptions import AuthError, CannotConnect
from custom_components.climate_ip.properties import (
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
    _template_log_fn,
    create_property,
    create_status_getter,
    register_property,
    register_status_getter,
    render_template,
)


@pytest.fixture
def mock_logger():
    """Create a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def mock_controller(mock_logger):  # pylint: disable=unused-argument
    """Create a mock controller with log_prefix and hass."""
    controller = MagicMock()
    controller.log_prefix = "[TestController]"
    controller.hass = MagicMock()
    controller.hass.data = {}
    mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
    mock_loop.call_soon_threadsafe = lambda cb, *args: cb(*args)
    controller.hass.loop = mock_loop
    controller.device_id = "test_duid"
    type(controller).pure_device_state = PropertyMock(return_value={})
    type(controller).device_state = PropertyMock(return_value={})
    return controller


@pytest.fixture
def mock_connection():
    """Create a mock connection."""
    connection = MagicMock()
    connection.create_updated.return_value = connection
    connection.is_async_native = True

    # Ensure async_execute and async_execute_with_retry are awaitable
    connection.async_execute = AsyncMock(return_value=("{}"))
    connection.async_execute_with_retry = AsyncMock(return_value={})

    connection._lock = MagicMock()
    connection.async_lock = MagicMock()
    connection.async_lock.__aenter__ = AsyncMock()
    connection.async_lock.__aenter__ = AsyncMock()
    connection.async_lock.__aexit__ = AsyncMock()
    connection._connection_template = None
    connection.connection_template = None

    return connection


# ====================================================================================
# PHASE 1: DeviceProperty HARDENED TESTS
# ====================================================================================


async def test_device_property_init(mock_connection, mock_controller):
    """Assert strict initial state to kill __init__ mutants."""
    prop = DeviceProperty("test_id", mock_connection, mock_controller, "mock_getter")
    assert prop._name == "test_id"
    assert prop.id == "test_id"
    assert prop._feature_flag is None
    assert prop.value is None
    assert prop._connection == mock_connection
    assert prop._controller == mock_controller
    assert prop._status_getter == "mock_getter"
    assert prop._status_template is None
    assert prop._connection_template is None
    assert prop._validation_template is None
    assert prop._status_template_raw is None
    assert prop._connection_template_raw is None
    assert prop._validation_template_raw is None
    assert prop._device_state is None
    assert prop._friendly_name is None
    assert prop._device_class is None
    assert prop._unit_of_measurement is None
    assert prop._state_class is None
    assert prop._entity_category is None
    assert prop._feature_flag is None
    assert prop.log_prefix == "[TestController]"
    assert prop.all_values == []


async def test_device_property_load_from_yaml(mock_connection, mock_controller):
    """Test loading DeviceProperty from YAML."""
    prop = DeviceProperty("test_prop", mock_connection, mock_controller)

    yaml_node = {
        "name": "Test Property",
        "device_class": "temperature",
        "unit_of_measurement": "°C",
        CONFIG_DEVICE_CONNECTION: {"type": "test"},
    }

    assert prop.load_from_yaml(yaml_node) is True
    assert prop.name == "Test Property"
    assert prop.device_class == "temperature"
    # Strict identity
    assert prop.unit_of_measurement == UnitOfTemperature.CELSIUS
    assert prop.state_class == "measurement"  # Assigned automatically for temperature


async def test_device_property_load_state_class_exception(
    mock_connection, mock_controller
):
    """Pattern 2: Exception when loading state_class."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    yaml_node = {"state_class": "invalid_class"}
    with pytest.raises(ValueError, match="Invalid state_class 'invalid_class' in YAML"):
        prop.load_from_yaml(yaml_node)


async def test_device_property_load_from_yaml_immediate_assertions(
    mock_connection, mock_controller
):
    """Pinpoint assertions to instantly kill load_from_yaml mutants with sudden death."""
    prop = DeviceProperty("test_prop", mock_connection, mock_controller)

    # Line 446: return False on None
    assert prop.load_from_yaml(None) is False

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
    }

    result = prop.load_from_yaml(node)
    assert result is True

    # Line 449: _type
    assert prop._type == "test_type"

    # Line 451: _state_node
    assert prop._state_node == "StateNode"

    # Lines 454-456: _status_template and hass passing
    assert prop._status_template is not None
    assert prop._status_template.hass is mock_controller.hass
    assert prop._status_template_raw == "{{ device_state.power }}"

    # Lines 457-459: _connection_template and hass passing
    assert prop._connection_template is not None
    assert prop._connection_template.hass is mock_controller.hass
    assert prop._connection_template_raw == '{"method": "GET"}'

    # Lines 460-462: _validation_template and hass passing
    assert prop._validation_template is not None
    assert prop._validation_template.hass is mock_controller.hass
    assert prop._validation_template_raw == "{{ 'valid' }}"

    # Lines 464-465: _connection updated
    assert prop._connection is not None
    mock_connection.create_updated.assert_called_with({"url": "/test"})

    # Line 473: _friendly_name
    assert prop._friendly_name == "Test Name"

    # Line 475: _unit_of_measurement
    assert prop._unit_of_measurement == UnitOfTemperature.CELSIUS

    # Line 476: _entity_category
    assert prop._entity_category == "diagnostic"

    # Line 479-481: _state_class
    assert prop._state_class == SensorStateClass.MEASUREMENT

    # Device class automatic state class mapping branches:
    # Lines 487-496: (GAS, ENERGY, WATER, CO) -> TOTAL_INCREASING
    for dev_cls in ("gas", "energy", "water", "carbon_monoxide"):
        p_tot = DeviceProperty("p_tot", mock_connection, mock_controller)
        assert p_tot.load_from_yaml({"device_class": dev_cls}) is True
        assert p_tot._state_class == SensorStateClass.TOTAL_INCREASING

    # Lines 497-505: (POWER, TEMPERATURE, HUMIDITY, etc.) -> MEASUREMENT
    for dev_cls in ("power", "temperature", "humidity", "voltage", "current"):
        p_meas = DeviceProperty("p_meas", mock_connection, mock_controller)
        assert p_meas.load_from_yaml({"device_class": dev_cls}) is True
        assert p_meas._state_class == SensorStateClass.MEASUREMENT

    # Non-sensor or unmapped device class -> state_class remains None
    p_none = DeviceProperty("p_none", mock_connection, mock_controller)
    assert p_none.load_from_yaml({"device_class": "battery"}) is True
    assert p_none._state_class is None


def test_x_render_template_strict_kwargs_and_parse_result():
    """Test x_render_template / render_template strict kwargs and parse_result."""
    mock_tmpl = MagicMock(spec=Template)
    mock_tmpl.async_render.return_value = "rendered_value"

    res = render_template(mock_tmpl, device_state={"test": 1}, extra="foo")
    assert res == "rendered_value"
    mock_tmpl.async_render.assert_called_once_with(
        {"device_state": {"test": 1}, "extra": "foo"},
        parse_result=True,
        log_fn=_template_log_fn,
    )


async def test_getjsonstatus_init(mock_connection, mock_controller):
    """Assert GetJsonStatus __init__ state to kill mutants."""
    g = GetJsonStatus("json_getter", mock_connection, mock_controller)
    assert g._name == "json_getter"
    assert g._connection is mock_connection
    assert g._controller is mock_controller
    # GetJsonStatus passes itself as the status_getter to DeviceProperty
    assert g._status_getter is g
    assert g._json_status is None
    assert g._attrs == {}
    assert GetJsonStatus.match_type(STATUS_GETTER_JSON) is True
    assert GetJsonStatus.match_type("other") is False








async def test_getjsonstatus_async_update_sync_success(
    mock_connection, mock_controller
):
    """Test happy path for sync connection execution."""
    g = GetJsonStatus("test_sync_success", mock_connection, mock_controller)
    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(return_value={"ok": True})

    res = await g.async_update_state(None, False)
    assert res == {"ok": True}
    assert g.value == {"ok": True}






async def test_getjsonstatus_async_update_sync_retry(
    mock_connection, mock_controller, caplog
):
    """Pattern 2: Test 5 retries in sync connection and final CannotConnect."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(
        side_effect=CannotConnect("Connection failed after 5 retries")
    )

    with pytest.raises(CannotConnect, match="Connection failed after 5 retries"):
        await g.async_update_state(None, False)



async def test_mode_operation_mapping(mock_connection, mock_controller):
    """Test ModeOperation loads values and maps them correctly."""
    mode_op = ModeOperation("hvac", mock_connection, mock_controller)

    yaml_node = {
        CONFIG_TYPE: "modes",
        CONFIG_DEVICE_OPERATION_VALUES: {
            "off": {CONFIG_DEVICE_OPERATION_VALUE: "0"},
            "cool": {CONFIG_DEVICE_OPERATION_VALUE: "1"},
        },
    }

    assert mode_op.load_from_yaml(yaml_node) is True
    assert "off" in mode_op.values
    assert "cool" in mode_op.values

    assert mode_op.convert_hass_to_dev("off") == "0"
    assert mode_op.convert_dev_to_hass("1") == "cool"


async def test_malformed_xml_buffer(mock_connection, mock_controller) -> None:
    """Check tolerance when the unit sends partial or incomplete XML payload."""
    from custom_components.climate_ip.properties import DeviceProperty

    prop = DeviceProperty("test_prop", mock_connection, mock_controller)
    prop._value = "STATE_ON"
    # To simulate malformed XML resulting in empty dictionary from defusedxml during property update mapping
    await prop.async_update_state(device_state_override={})
    assert prop.value == "STATE_ON"


# ====================================================================================
# PHASE 2: DeviceOperation HARDENED TESTS
# ====================================================================================




async def test_deviceoperation_async_set_value_sanitization(
    mock_connection, mock_controller, caplog
):
    """Test front-end sanitization logic."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)

    with patch.object(
        op, "convert_hass_to_dev", side_effect=ValueError("Invalid value")
    ):
        res = await op.async_set_value("bad_value")
        assert res is False
        assert "Command discarded" in caplog.text


async def test_deviceoperation_async_set_value_async_native_raw(
    mock_connection, mock_controller
):
    """Test async native set value with raw payload."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = True

    with patch.object(op, "_resolve_async_params", return_value={"_raw": "payload"}):
        res = await op.async_set_value("val")
        assert res is True
        mock_connection.async_execute.assert_called_once_with(
            None, None, "payload", None
        )




async def test_deviceoperation_async_set_value_async_native_exceptions(
    mock_connection, mock_controller
):
    """Test async native AuthError -> HomeAssistantError conversion."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = True

    with patch.object(op, "_resolve_async_params", return_value={"method": "GET", "url": "/test"}):
        mock_connection.async_execute.side_effect = AuthError("Token expired")
        with pytest.raises(HomeAssistantError, match="Connection error"):
            await op.async_set_value("val")


async def test_deviceoperation_async_set_value_sync_success(
    mock_connection, mock_controller
):
    """Test sync execution wraps properly."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(return_value={})

    res = await op.async_set_value("val")
    assert res is True
    mock_connection.async_execute_with_retry.assert_called_once()


async def test_deviceoperation_async_set_value_sync_retry(
    mock_connection, mock_controller, caplog
):
    """Test sync RetryNextAttempt mechanism loops and finally raises CannotConnect."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(
        side_effect=CannotConnect("Connection failed after 5 retries")
    )

    with pytest.raises(
        HomeAssistantError, match="Connection error: could not set value for test_op"
    ):
        await op.async_set_value("val")


# ====================================================================================
# PHASE 2: BasicDeviceOperation HARDENED TESTS
# ====================================================================================


async def test_basicdeviceoperation_load_from_yaml(mock_connection, mock_controller):
    """Test loading specific value mappings and retrieving connections."""
    op = BasicDeviceOperation("test_op", mock_connection, mock_controller)

    yaml_node = {
        CONFIG_TYPE: "modes",
        CONFIG_DEVICE_OPERATION_VALUES: {
            "on": {
                CONFIG_DEVICE_OPERATION_VALUE: "1",
                CONFIG_DEVICE_CONNECTION: {"type": "on_conn"},
            },
            "off": {CONFIG_DEVICE_OPERATION_VALUE: "0"},
        },
    }

    assert op.load_from_yaml(yaml_node) is True
    assert op.all_values == ["on", "off"]
    assert op._values_dev_to_ha_map["1"] == "on"
    assert op._values_ha_to_dev_map["off"] == "0"

    conn_on = op.get_connection("on")
    assert conn_on is not None


async def test_basicdeviceoperation_dynamic_values(mock_connection, mock_controller):
    """Test that dynamic valid values are properly cached based on HVAC mode."""
    op = BasicDeviceOperation("test_op", mock_connection, mock_controller)

    yaml_node = {
        CONFIG_TYPE: "modes",
        CONFIG_DEVICE_OPERATION_VALUES: {
            "on": {
                CONFIG_DEVICE_OPERATION_VALUE: "1",
                CONFIG_DEVICE_VALIDATION_TEMPLATE: "{% if device_state.p == 1 %}valid{% endif %}",
            },
            "off": {
                CONFIG_DEVICE_OPERATION_VALUE: "0",
                CONFIG_DEVICE_VALIDATION_TEMPLATE: "valid",
            },
        },
    }

    op.load_from_yaml(yaml_node)

    mock_mode_prop = MagicMock(spec=DeviceProperty)
    type(mock_mode_prop).value = PropertyMock(return_value="cool")
    mock_mode_prop.id = "none"
    mock_controller.get_property.return_value = mock_mode_prop

    op._device_state = {"p": 1}
    # Both are valid
    vals = op.values
    assert vals == ["on", "off"]
    assert op._values_cache["none"] == ["on", "off"]

    # Change state to make 'on' invalid, but since we use the same mock mode "cool", it should use cache!
    op._device_state = {"p": 0}
    vals2 = op.values
    assert vals2 == ["on", "off"]  # Cache hit

    # Change cache key to bypass cache
    type(mock_mode_prop).value = PropertyMock(return_value="heat")
    mock_mode_prop.id = "heat_mode"
    vals3 = op.values
    assert vals3 == ["off"]  # Cache miss, recalculates, 'on' is invalid
    assert op._values_cache["heat_mode"] == ["off"]

    # Kill fallback map mutants
    assert op.convert_hass_to_dev("unmapped_ha") == "unmapped_ha"
    assert op.convert_dev_to_hass("unmapped_dev") == "unmapped_dev"


# ====================================================================================
# PHASE 3: Typed Operations HARDENED TESTS
# ====================================================================================


async def test_typed_operations_strict_init(mock_connection, mock_controller):
    """Kill __init__ mutants for all typed operations."""
    # BasicNumericOperation
    op_num = BasicNumericOperation(
        "test_num", mock_connection, mock_controller, "getter1"
    )
    assert op_num._name == "test_num"
    assert op_num._connection == mock_connection
    assert op_num._controller == mock_controller
    assert op_num._status_getter == "getter1"
    assert op_num._min is None
    assert op_num._max is None
    assert op_num._value is None

    # TemperatureOperation
    op_temp = TemperatureOperation(
        "test_temp", mock_connection, mock_controller, "getter2"
    )
    assert op_temp._name == "test_temp"
    assert op_temp._connection == mock_connection
    assert op_temp._controller == mock_controller
    assert op_temp._status_getter == "getter2"
    assert op_temp._unit_template is None
    assert op_temp._device_unit == UnitOfTemperature.CELSIUS
    assert op_temp._hass_unit == UnitOfTemperature.CELSIUS

    # SwitchOperation
    op_switch = SwitchOperation("test_sw", mock_connection, mock_controller, "getter3")
    assert op_switch._name == "test_sw"
    assert op_switch._connection == mock_connection
    assert op_switch._controller == mock_controller
    assert op_switch._status_getter == "getter3"


async def test_modeoperation_init(mock_connection, mock_controller):
    """Test ModeOperation assigns _id based on standard names."""
    op = ModeOperation(ATTR_HVAC_MODE, mock_connection, mock_controller)
    assert op.id == ATTR_HVAC_MODE

    op2 = ModeOperation("custom_mode", mock_connection, mock_controller)
    assert op2.id == "custom_mode_mode"


async def test_switchoperation_load_from_yaml(mock_connection, mock_controller):
    """Test SwitchOperation maps booleans correctly and handles edge cases."""
    op = SwitchOperation("test_switch", mock_connection, mock_controller)
    assert SwitchOperation.match_type(PROPERTY_TYPE_SWITCH) is True
    assert SwitchOperation.match_type("other") is False
    assert SwitchOperation.match_type(PROPERTY_TYPE_MODE) is False

    # Fail cases: None or failed super load_from_yaml
    assert op.load_from_yaml(None) is False
    assert op.load_from_yaml({"type": "invalid_unmatched_type"}) is False

    # Normal case: both ON and OFF
    yaml_node = {
        CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
        CONFIG_DEVICE_OPERATION_VALUES: {
            STATE_ON: {CONFIG_DEVICE_OPERATION_VALUE: "1"},
            STATE_OFF: {CONFIG_DEVICE_OPERATION_VALUE: "0"},
        },
    }
    assert op.load_from_yaml(yaml_node) is True
    assert op._values_ha_to_dev_map[False] == "0"
    assert op._values_ha_to_dev_map[True] == "1"
    assert op.convert_hass_to_dev(True) == "1"
    assert op.convert_hass_to_dev(False) == "0"

    # Edge case: only ON configured
    op_on_only = SwitchOperation("test_on", mock_connection, mock_controller)
    assert op_on_only.load_from_yaml({
        CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
        CONFIG_DEVICE_OPERATION_VALUES: {
            STATE_ON: {CONFIG_DEVICE_OPERATION_VALUE: "1"},
        },
    }) is True
    assert op_on_only._values_ha_to_dev_map[True] == "1"
    assert False not in op_on_only._values_ha_to_dev_map

    # Edge case: only OFF configured
    op_off_only = SwitchOperation("test_off", mock_connection, mock_controller)
    assert op_off_only.load_from_yaml({
        CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
        CONFIG_DEVICE_OPERATION_VALUES: {
            STATE_OFF: {CONFIG_DEVICE_OPERATION_VALUE: "0"},
        },
    }) is True
    assert op_off_only._values_ha_to_dev_map[False] == "0"
    assert True not in op_off_only._values_ha_to_dev_map


async def test_basicnumericoperation_value_property(mock_connection, mock_controller):
    """Test BasicNumericOperation value parsing and fallbacks."""
    op = BasicNumericOperation("test_num", mock_connection, mock_controller)
    assert op.value is None

    op.value = "23.5"
    assert op.value == 23.5

    op.value = "invalid"
    assert op.value is None

    with patch.object(op, "convert_hass_to_dev", return_value=23.5):
        assert op.match_value(23.5) is True

    with patch.object(op, "convert_hass_to_dev", side_effect=ValueError):
        assert op.match_value("not_a_num") is False


async def test_temperatureoperation_unit_conversion(mock_connection, mock_controller):
    """Test TemperatureOperation converts correctly."""
    op = TemperatureOperation("test_temp", mock_connection, mock_controller)

    op.set_device_unit(UnitOfTemperature.CELSIUS)
    op.set_hass_unit(UnitOfTemperature.FAHRENHEIT)
    assert op._hass_unit == UnitOfTemperature.FAHRENHEIT

    assert op.convert_dev_to_hass(0) == 32.0
    assert op.convert_hass_to_dev(50.0) == 10.0

    op.set_device_unit(UnitOfTemperature.FAHRENHEIT)
    op.set_hass_unit(UnitOfTemperature.CELSIUS)
    assert op._hass_unit == UnitOfTemperature.CELSIUS

    assert op.convert_dev_to_hass(50.0) == 10.0
    assert op.convert_hass_to_dev(10.0) == 50.0


async def test_deviceoperation_async_set_value_config_fallbacks(
    mock_connection, mock_controller
):
    """Kill mutants in async_set_value related to cfg and duid fallback."""
    op = DeviceOperation("test", mock_connection, mock_controller)
    op._connection_template = Template(hass=MagicMock(data={}), template="")
    op.convert_hass_to_dev = MagicMock(return_value="val")

    # 1. No device_id, No cfg, No config, No device_state
    mock_controller.device_id = None
    mock_controller.device_state = None
    del mock_connection._cfg
    del mock_connection.config

    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(return_value={"success": True})

    await op.async_set_value("val")
    mock_connection.async_execute_with_retry.assert_called_once_with(
        op._connection_template, "val", {}, None
    )

    # 2. No duid attribute on cfg
    mock_cfg = MagicMock(spec=[])
    mock_connection._cfg = mock_cfg
    mock_connection.async_execute_with_retry.reset_mock()
    await op.async_set_value("val")
    mock_connection.async_execute_with_retry.assert_called_once_with(
        op._connection_template, "val", {}, None
    )


async def test_global_factories_and_registers(mock_connection, mock_controller):
    """Kill mutants in create_property, create_status_getter and decorators."""

    class DummyProp:
        @staticmethod
        def match_type(t):
            return t == "dummy_prop"

        def __init__(self, name, conn, ctrl, getter):
            self.name = name
            self.conn = conn
            self.ctrl = ctrl
            self.getter = getter
            self.loaded = False

        def load_from_yaml(self, node):
            self.loaded = True
            return True

    class DummyGetter:
        @staticmethod
        def match_type(t):
            return t == "dummy_getter"

        def __init__(self, name, conn, ctrl):
            self.name = name
            self.conn = conn
            self.ctrl = ctrl
            self.loaded = False

        def load_from_yaml(self, node):
            self.loaded = True
            return True

    register_property(DummyProp)
    register_status_getter(DummyGetter)
    assert DummyProp in CLIMATE_IP_PROPERTIES
    assert DummyGetter in CLIMATE_IP_STATUS_GETTER

    node = {CONFIG_TYPE: "dummy_prop"}
    prop = create_property(
        "test_prop", node, mock_connection, mock_controller, "my_getter"
    )
    assert prop is not None
    assert prop.name == "test_prop"
    assert prop.conn == mock_connection
    assert prop.ctrl == mock_controller
    assert prop.getter == "my_getter"

    node_g = {CONFIG_TYPE: "dummy_getter"}
    g = create_status_getter("test_getter", node_g, mock_connection, mock_controller)
    assert g is not None
    assert g.name == "test_getter"
    assert g.conn == mock_connection
    assert g.ctrl == mock_controller

    # Clean up globals so tests don't leak
    CLIMATE_IP_PROPERTIES.remove(DummyProp)
    CLIMATE_IP_STATUS_GETTER.remove(DummyGetter)


async def test_basicdeviceoperation_load_from_yaml_edge_cases(
    mock_connection, mock_controller
):
    """Kill mutants related to load_from_yaml fallbacks, empty values, feature flags."""
    from homeassistant.components.climate import ClimateEntityFeature

    with patch.dict(
        "custom_components.climate_ip.properties.YAML_NAME_TO_HA_FEATURE",
        {"test_flag_op": ClimateEntityFeature.FAN_MODE},
        clear=True,
    ):
        op = BasicDeviceOperation("test_flag_op", mock_connection, mock_controller)

        # 1. Test empty values dict returns False
        assert (
            op.load_from_yaml({CONFIG_TYPE: "op", CONFIG_DEVICE_OPERATION_VALUES: {}})
            is False
        )

        # 1b. Test missing CONFIG_DEVICE_OPERATION_VALUES uses fallback {} and returns False
        assert op.load_from_yaml({CONFIG_TYPE: "op"}) is False

        # 4. Test missing CONFIG_DEVICE_CONNECTION in node uses whole node
        mock_connection.create_updated.reset_mock()
        yaml_node = {
            CONFIG_TYPE: "op",
            CONFIG_DEVICE_OPERATION_VALUES: {"on": {"some_other_key": "val"}},
        }
        assert op.load_from_yaml(yaml_node) is True

        # 2. Test feature flag assignment securely patched
        assert op._feature_flag is ClimateEntityFeature.FAN_MODE

        # Verify create_updated was called with the whole node '{"some_other_key": "val"}' because CONFIG_DEVICE_CONNECTION was missing.
        mock_connection.create_updated.assert_called_with({"some_other_key": "val"})

    # 3. Test get_connection fallback (None returns default)
    assert op.get_connection(None) == mock_connection


async def test_basicdeviceoperation_is_value_valid_edge_cases(
    mock_connection, mock_controller
):
    """Kill mutants in is_value_valid logic."""
    op = BasicDeviceOperation("test", mock_connection, mock_controller)
    # Template is None -> returns True
    assert op.is_value_valid("test_val", {"k": "v"}) is True

    # Template is not None but device_state is None -> returns False
    op._value_validation_templates["test_val"] = MagicMock()
    assert op.is_value_valid("test_val", None) is False


async def test_set_device_state_for_values(mock_connection, mock_controller):
    """Kill mutants in set_device_state_for_values."""
    op = BasicDeviceOperation("test", mock_connection, mock_controller)
    op.set_device_state_for_values({"test_state": 1})
    assert op._device_state == {"test_state": 1}


async def test_basicnumericoperation_load_from_yaml(mock_connection, mock_controller):
    """Kill mutants in BasicNumericOperation load_from_yaml."""
    op = BasicNumericOperation("test", mock_connection, mock_controller)

    # 1. Test super() failing returns False
    assert op.load_from_yaml(None) is False

    # 2. Test missing min/max sets them to None and returns True
    yaml_node = {CONFIG_TYPE: "test"}
    assert op.load_from_yaml(yaml_node) is True
    assert op._min is None
    assert op._max is None
    assert op._connection is mock_connection

    # 3. Test explicit min/max
    yaml_node_2 = {
        CONFIG_TYPE: "test",
        CONFIG_DEVICE_OPERATION_NUMBER_MIN: 10,
        CONFIG_DEVICE_OPERATION_NUMBER_MAX: 30,
    }
    assert op.load_from_yaml(yaml_node_2) is True
    assert op._min == 10
    assert op._max == 30



async def test_deviceoperation_async_set_value_mutants(
    mock_connection, mock_controller
):
    """Verify async_set_value handling."""
    op = DeviceOperation("test", mock_connection, mock_controller)
    op._connection_template = Template(hass=MagicMock(data={}), template="")
    op.convert_hass_to_dev = MagicMock(return_value="val")

    # Verify current_full_state fallback
    type(mock_controller).pure_device_state = PropertyMock(return_value={})
    type(mock_controller).device_state = PropertyMock(return_value={})
    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(return_value={"success": True})

    await op.async_set_value("val")
    mock_connection.async_execute_with_retry.assert_called_once_with(
        op._connection_template, "val", {}, None
    )


async def test_basicdeviceoperation_init_and_get_conn(mock_connection, mock_controller):
    """Verify BasicDeviceOperation __init__ and get_connection."""
    op = BasicDeviceOperation("test", mock_connection, mock_controller)
    assert op._feature_flag is None

    op._value_connections_map = {"on": "mock_on_conn"}
    assert op.get_connection("on") == "mock_on_conn"
    assert op.get_connection("off") == mock_connection


async def test_basic_numeric_operation_match_value(mock_connection, mock_controller):
    """Test BasicNumericOperation match_value."""
    op = BasicNumericOperation("test", mock_connection, mock_controller)
    # default convert_hass_to_dev just returns the float if no map
    assert op.match_value(10.0) is True
    # Testing ValueError path
    assert op.match_value("invalid_str") is False





async def test_numeric_boundaries_exact(mock_connection, mock_controller):
    """Test boundary testing for BasicNumericOperation.convert_hass_to_dev."""
    op = BasicNumericOperation("test_bounds", mock_connection, mock_controller)
    op._min = 10.0
    op._max = 30.0

    # Exact lower boundary
    assert op.convert_hass_to_dev(10.0) == 10.0

    # Exact upper boundary
    assert op.convert_hass_to_dev(30.0) == 30.0

    # Just below min → clamped to min
    assert op.convert_hass_to_dev(9.9) == 10.0

    # Just above max → clamped to max
    assert op.convert_hass_to_dev(30.1) == 30.0

    # Middle of range → passes through unchanged
    assert op.convert_hass_to_dev(20.0) == 20.0

    # None with limits set → returns ha_value unchanged
    import pytest
    with pytest.raises(ValueError):
        op.convert_hass_to_dev(None)

    # "unknown" with limits set → returns "unknown"
    with pytest.raises(ValueError):
        op.convert_hass_to_dev("unknown")

    # Only min set, no max
    op._min = 5.0
    op._max = None
    assert op.convert_hass_to_dev(5.0) == 5.0
    assert op.convert_hass_to_dev(4.9) == 5.0
    assert op.convert_hass_to_dev(100.0) == 100.0

    # Only max set, no min
    op._min = None
    op._max = 50.0
    assert op.convert_hass_to_dev(50.0) == 50.0
    assert op.convert_hass_to_dev(50.1) == 50.0
    assert op.convert_hass_to_dev(0.0) == 0.0

    # Neither min nor max
    op._min = None
    op._max = None
    with pytest.raises(ValueError):
        op.convert_hass_to_dev("unknown")
    assert op.convert_hass_to_dev(42.0) == 42.0


async def test_temperature_boundaries_exact(mock_connection, mock_controller):
    """Test boundary testing for TemperatureOperation.convert_hass_to_dev."""
    op = TemperatureOperation("test_temp_bounds", mock_connection, mock_controller)
    # Same unit to isolate clamping logic from conversion
    op.set_device_unit(UnitOfTemperature.CELSIUS)
    op.set_hass_unit(UnitOfTemperature.CELSIUS)
    op._min = 16.0
    op._max = 30.0

    # Exact boundaries → pass through
    assert op.convert_hass_to_dev(16.0) == 16.0
    assert op.convert_hass_to_dev(30.0) == 30.0

    # Below min → clamped
    assert op.convert_hass_to_dev(15.9) == 16.0
    assert op.convert_hass_to_dev(0.0) == 16.0

    # Above max → clamped
    assert op.convert_hass_to_dev(30.1) == 30.0
    assert op.convert_hass_to_dev(100.0) == 30.0

    # None → ValueError
    with pytest.raises(ValueError, match="Invalid payload"):
        op.convert_hass_to_dev(None)

    # "unknown" → ValueError
    with pytest.raises(ValueError, match="Invalid payload"):
        op.convert_hass_to_dev("unknown")


# ====================================================================================
# FRENTE 3: AUTOPSIA DEL PAYLOAD ASÍNCRONO
# ====================================================================================


async def test_getattr_fallback_connection_template(mock_connection, mock_controller):
    """Verify missing _params triggers fail-fast AttributeError."""
    op = DeviceOperation("test_fallback", mock_connection, mock_controller)

    # Test that missing _params strictly fails
    if hasattr(mock_connection, "_params"):
        delattr(mock_connection, "_params")

    op.convert_hass_to_dev = MagicMock(return_value="dev_val_raw")

    import pytest
    with pytest.raises(AttributeError):
        await op.async_set_value("ha_val")








def test_device_property_load_from_yaml_yaml_loaders(mock_connection, mock_controller):
    """Load_from_yaml testing on basic properties."""
    prop = DeviceProperty("test_yaml", mock_connection, mock_controller)

    assert prop.load_from_yaml(None) is False
    assert prop.load_from_yaml({}) is True

    node = {
        "values": {"ha_on": "dev_1", "ha_off": "dev_0"},
        "status_template": "state.value",
        "connection_template": "conn",
        "validation_template": "val",
        "name": "Test Name",
        "device_class": "temperature",
        "unit_of_measurement": "C",
        "entity_category": "diagnostic",
        "state_class": "measurement",
    }
    assert prop.load_from_yaml(node) is True
    assert prop._status_template is not None
    assert prop._status_template_raw == "state.value"
    assert prop._connection_template is not None
    assert prop._connection_template_raw == "conn"
    assert prop._validation_template is not None
    assert prop._validation_template_raw == "val"
    assert prop._friendly_name == "Test Name"
    assert prop._device_class == "temperature"
    assert prop._unit_of_measurement == "C"
    assert prop._entity_category == "diagnostic"
    assert prop._state_class.value == "measurement"


@pytest.mark.parametrize(
    "dev_class", ["power", "temperature", "humidity", "voltage", "current"]
)
def test_device_property_load_from_yaml_state_class(
    mock_connection, mock_controller, dev_class
):
    """Test that default state_class is assigned to specific device classes."""
    prop = DeviceProperty("test_state_class", mock_connection, mock_controller)
    node = {"device_class": dev_class}
    prop.load_from_yaml(node)
    assert prop._state_class is not None
    assert prop._state_class.value == "measurement"


def test_device_property_load_from_yaml_state_class_other(
    mock_connection, mock_controller
):
    """Test that default state_class is NOT assigned to other device classes."""
    prop = DeviceProperty("test_state_class", mock_connection, mock_controller)
    node = {"device_class": "battery"}
    prop.load_from_yaml(node)
    assert prop._state_class is None

    b_op = BasicDeviceOperation("test_bop", mock_connection, mock_controller)
    node_bop = {"values": {"ha_on": {"connection": {"type": "tcp"}}}}
    mock_connection.create_updated.return_value = mock_connection
    assert b_op.load_from_yaml(node_bop) is True
    assert b_op._value_connections_map["ha_on"] == mock_connection

    sw_op = SwitchOperation("test_sw", mock_connection, mock_controller)
    node_sw = {"values": {"ha_on": {"value": "dev_1"}, "ha_off": {"value": "dev_0"}}}
    assert sw_op.load_from_yaml(node_sw) is True

    g = GetJsonStatus("test_yaml_get", mock_connection, mock_controller)
    assert g.load_from_yaml({"status_template": "x"}) is True


# FRONT C: Config Fallback


def test_mode_operation_init(mock_connection, mock_controller):
    """ModeOperation initialization features."""
    op_hvac = ModeOperation("hvac_mode", mock_connection, mock_controller)
    assert op_hvac._feature_flag is None

    op_fan = ModeOperation("fan", mock_connection, mock_controller)
    assert op_fan._feature_flag is not None


def test_basic_numeric_bounds_strict(mock_connection, mock_controller):
    """Test strict '<=' and '>=' handling and min/max condition flips."""
    op = BasicNumericOperation("test_bounds", mock_connection, mock_controller)

    # Both min and max set
    op._min = 10.0
    op._max = 30.0
    assert op.convert_hass_to_dev(10) == 10.0
    assert op.convert_hass_to_dev(30) == 30.0
    assert op.convert_hass_to_dev(5) == 10.0
    assert op.convert_hass_to_dev(35) == 30.0
    assert op.convert_hass_to_dev(20) == 20.0

    # Only min set (max is None) -> tests line 1262: min_bound condition flip and line 1263: max_bound fallback float('inf')
    op._min = 10.0
    op._max = None
    assert op.convert_hass_to_dev(5) == 10.0
    assert op.convert_hass_to_dev(10) == 10.0
    assert op.convert_hass_to_dev(50) == 50.0

    # Only max set (min is None) -> tests line 1263: max_bound condition flip and line 1262: min_bound fallback float('-inf')
    op._min = None
    op._max = 30.0
    assert op.convert_hass_to_dev(35) == 30.0
    assert op.convert_hass_to_dev(30) == 30.0
    assert op.convert_hass_to_dev(-50) == -50.0




async def test_device_property_mutants():
    conn = MagicMock(
        is_async_native=True,
        _params={},
        async_execute=AsyncMock(return_value=("ok")),
    )
    conn._lock = AsyncMock()
    conn.create_updated.return_value = conn
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}

    op = DeviceProperty("test_prop", conn, ctrl)
    assert op.load_from_yaml({"type": "test", "name": "Test"}) is True

    op.set_unit_of_measurement("C")
    assert op._unit_of_measurement == UnitOfTemperature.CELSIUS


async def test_basic_device_operation_mutants():
    conn = MagicMock()
    conn.create_updated.return_value = conn
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}

    op = BasicDeviceOperation("test_bdo", conn, ctrl)
    op._values_ha_to_dev_map = {"ha_val": {"connection": {"type": "new"}}}
    assert op.load_from_yaml({"type": "test", "values": {"ha_val": {}}}) is True


async def test_basic_numeric_operation_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = BasicNumericOperation("test_bno", conn, ctrl)
    assert op.load_from_yaml({"type": "test"}) is True


async def test_mode_operation_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = ModeOperation("test_mode", conn, ctrl)

    assert op.load_from_yaml(None) is False

    assert op.id == "test_mode_mode"

    op2 = ModeOperation(ATTR_HVAC_MODE, conn, ctrl)
    assert op2.id == ATTR_HVAC_MODE


async def test_switch_operation_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = SwitchOperation("test_switch", conn, ctrl)
    op._values_ha_to_dev_map = {STATE_OFF: "0", STATE_ON: "1"}
    assert (
        op.load_from_yaml({"type": "switch", "values": {STATE_ON: {}, STATE_OFF: {}}})
        is True
    )


async def test_getjsonstatus_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = GetJsonStatus("test_json", conn, ctrl)
    assert op.load_from_yaml({"type": "json"}) is True
    op.calculate_value_from_state(None)




async def test_static_yaml_strings_and_base_units(mock_connection, mock_controller):
    """Test static YAML strings and base set_unit_of_measurement."""
    from homeassistant.components.sensor import SensorStateClass

    from custom_components.climate_ip.properties import DeviceProperty

    op_co = DeviceProperty("test_co", mock_connection, mock_controller)
    op_co.load_from_yaml({"device_class": "carbon_monoxide"})
    assert op_co._state_class == SensorStateClass.TOTAL_INCREASING

    op_gas = DeviceProperty("test_gas", mock_connection, mock_controller)
    op_gas.load_from_yaml({"device_class": "gas"})
    assert op_gas._state_class == SensorStateClass.TOTAL_INCREASING

    # 2. set_unit_of_measurement in base class (Kills .get(unit) returning default)
    op_unit = DeviceProperty("test_unit", mock_connection, mock_controller)
    op_unit.set_unit_of_measurement("UNIDAD_BASE_DESCONOCIDA")
    assert op_unit._unit_of_measurement == "UNIDAD_BASE_DESCONOCIDA"


async def test_device_property_connection_fallback_dict(
    mock_connection, mock_controller
):
    """Verify mutant kill silencioso node.get(CONFIG_DEVICE_CONNECTION)."""
    from custom_components.climate_ip.properties import DeviceProperty

    op = DeviceProperty("test_conn", mock_connection, mock_controller)

    # Inject YAML missing CONFIG_DEVICE_CONNECTION key
    op.load_from_yaml({"name": "Test"})

    # Strictly assert factory received empty dictionary and not None
    mock_connection.create_updated.assert_called_with({})


async def test_device_property_remaining_mutants():
    conn = MagicMock(is_async_native=True, _params={})
    conn._lock = AsyncMock()
    conn.create_updated.return_value = conn
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}

    op = DeviceProperty("test_prop", conn, ctrl)

    # load_from_yaml -> None connection config
    op.load_from_yaml({"type": "test", "name": "Test"})
    conn.create_updated.assert_called_with({})

    # device classes
    op.load_from_yaml({"type": "test", "device_class": "carbon_monoxide"})
    assert op._state_class == SensorStateClass.TOTAL_INCREASING

    # set_unit_of_measurement unknown unit
    op.set_unit_of_measurement("unknown_unit")
    assert op._unit_of_measurement == "unknown_unit"

    # Test is_valid with None device_state
    op._validation_template = Template(hass=MagicMock(data={}), template=
        "{% if device_state %}valid{% else %}invalid{% endif %}"
    )
    assert op.is_valid({"val": "ok"}) is True

    # calculate_value_from_state boolean or
    with patch("custom_components.climate_ip.properties._LOGGER.debug") as mock_debug:
        op._status_template = None
        assert op.calculate_value_from_state({"val": "ok"}) is None
        mock_debug.assert_not_called()

    # async_update_state
    op._status_getter = MagicMock(value={"val": "got"})
    await op.async_update_state({"val": "override"}, False)
    assert op._device_state == {"val": "override"}

    await op.async_update_state(None, False)
    assert op._device_state == {"val": "got"}

    op._status_getter = None
    await op.async_update_state(None, False)
    assert op._device_state is None


async def test_getjsonstatus_remaining_mutants():
    conn = MagicMock(is_async_native=False)
    conn._lock = AsyncMock()
    conn.create_updated.return_value = conn
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = GetJsonStatus("test_json", conn, ctrl)

    # load_from_yaml boolean logic
    op._connection_template = None
    op.load_from_yaml({"type": "json"})
    assert op._connection_template is None

    # calculate_value_from_state none device_state
    op._status_template = Template(hass=MagicMock(data={}), template='{"result": "{{ device_state.val }}"}')
    assert op.calculate_value_from_state({"val": "ok"}) == {"result": "ok"}


async def test_basicdeviceoperation_remaining_mutants():
    conn = MagicMock()
    conn.create_updated.return_value = conn
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = BasicDeviceOperation("test_bdo", conn, ctrl)

    # load_from_yaml empty values
    assert op.load_from_yaml({"type": "test", "values": {}}) is False

    # with connection parameter
    op.load_from_yaml(
        {"type": "test", "values": {"ha_val": {"connection": {"type": "new"}}}}
    )
    conn.create_updated.assert_called_with({"type": "new"})

    # load_from_yaml empty values
    assert op.load_from_yaml({"type": "test", "values": {}}) is False

    # with connection parameter
    op.load_from_yaml(
        {"type": "test", "values": {"ha_val": {"connection": {"type": "new"}}}}
    )
    conn.create_updated.assert_called_with({"type": "new"})


async def test_basicnumericoperation_remaining_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    BasicNumericOperation("test_bno", conn, ctrl)


async def test_modeoperation_remaining_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    status_getter = MagicMock()
    op = ModeOperation("test_mode", conn, ctrl, status_getter=status_getter)
    assert op._status_getter == status_getter


async def test_switchoperation_remaining_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = SwitchOperation("test_switch", conn, ctrl)
    assert op.load_from_yaml({"type": "switch"}) is False


async def test_temperatureoperation_remaining_mutants():
    conn = MagicMock(is_async_native=True, _params={})
    conn._lock = AsyncMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = TemperatureOperation("test_temp", conn, ctrl)

    # load_from_yaml false return
    assert op.load_from_yaml(None) is False

    # set_hass_unit measurement
    op.set_hass_unit(UnitOfTemperature.CELSIUS)
    assert op._unit_of_measurement == UnitOfTemperature.CELSIUS

    # calculate_value_from_state unit fallback
    op._device_unit = UnitOfTemperature.FAHRENHEIT
    op._unit_template = Template(hass=MagicMock(data={}), template="{{ device_state.unit }}")
    with pytest.raises(HomeAssistantError, match="Error parsing unit template"):
        op.calculate_value_from_state({"unit": "unknown"})

    op._unit_template = None
    op.calculate_value_from_state({"val": "10"})
    assert op._device_unit == UnitOfTemperature.FAHRENHEIT

    # async_update_state
    op._status_getter = MagicMock(value={"val": "got"})
    await op.async_update_state({"val": "override"}, False)
    assert op.value is None

    # Verify async_update_state log behavior
    with patch("custom_components.climate_ip.properties._LOGGER.debug") as mock_debug:
        op._unit_template = None
        await op.async_update_state({"val": "ok"}, False)
        mock_debug.assert_not_called()

    # calculate_value_from_state device_unit
    op._device_unit = UnitOfTemperature.FAHRENHEIT
    op._hass_unit = UnitOfTemperature.CELSIUS
    op._unit_template = None
    op._status_template = Template(hass=MagicMock(data={}), template="{{ device_state.val }}")
    v = op.calculate_value_from_state({"val": "77"})
    assert v == 25.0


# ====================================================================================
# Unit Tests: Strict Specs, Missing Attributes, Match & State Attributes
# ====================================================================================


async def test_device_operation_match_value():
    """Test DeviceOperation.match_value returns False."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = DeviceOperation("test_op", conn, ctrl)
    assert op.match_value("on") is False
    assert op.match_value(123) is False


async def test_basic_device_operation_match_value():
    """Test BasicDeviceOperation.match_value against values_ha_to_dev_map."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = BasicDeviceOperation("test_bdo", conn, ctrl)
    op._values_ha_to_dev_map = {"cool": "1", "heat": "2"}
    assert op.match_value("cool") is True
    assert op.match_value("heat") is True
    assert op.match_value("dry") is False


async def test_mode_operation_match_type():
    """Test ModeOperation.match_type checks PROPERTY_TYPE_MODE."""
    assert ModeOperation.match_type(PROPERTY_TYPE_MODE) is True
    assert ModeOperation.match_type("switch") is False
    assert ModeOperation.match_type("number") is False


async def test_mode_operation_state_attributes_matrix():
    """Test ModeOperation.state_attributes for all attribute types."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}

    # 1. ATTR_HVAC_MODE
    op_hvac = ModeOperation(ATTR_HVAC_MODE, conn, ctrl)
    op_hvac.value = "cool"
    op_hvac._values = ["off", "cool", "heat"]
    attrs_hvac = op_hvac.state_attributes
    assert attrs_hvac == {
        ATTR_HVAC_MODE: "cool",
        ATTR_HVAC_MODES: ["off", "cool", "heat"],
    }

    # 2. ATTR_FAN_MODE
    op_fan = ModeOperation(ATTR_FAN_MODE, conn, ctrl)
    op_fan.value = "auto"
    op_fan._values = ["auto", "low", "high"]
    attrs_fan = op_fan.state_attributes
    assert attrs_fan == {
        ATTR_FAN_MODE: "auto",
        ATTR_FAN_MODES: ["auto", "low", "high"],
    }

    # 3. ATTR_PRESET_MODE
    op_preset = ModeOperation(ATTR_PRESET_MODE, conn, ctrl)
    op_preset.value = "eco"
    op_preset._values = ["eco", "boost"]
    attrs_preset = op_preset.state_attributes
    assert attrs_preset == {
        ATTR_PRESET_MODE: "eco",
        ATTR_PRESET_MODES: ["eco", "boost"],
    }

    # 4. ATTR_SWING_MODE
    op_swing = ModeOperation(ATTR_SWING_MODE, conn, ctrl)
    op_swing.value = "off"
    op_swing._values = ["off", "vertical"]
    attrs_swing = op_swing.state_attributes
    assert attrs_swing == {
        ATTR_SWING_MODE: "off",
        ATTR_SWING_MODES: ["off", "vertical"],
    }

    # 5. Custom mode name
    op_custom = ModeOperation("my_special", conn, ctrl)
    op_custom.value = "val1"
    op_custom._values = ["val1", "val2"]
    attrs_custom = op_custom.state_attributes
    assert attrs_custom == {
        "my_special_mode": "val1",
        "my_special_modes": ["val1", "val2"],
    }


async def test_create_property_and_status_getter_none_returns():
    """Test create_property and create_status_getter return None for unhandled types."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}

    # Missing CONFIG_TYPE
    assert create_property("test", {}, conn, ctrl) is None
    assert create_status_getter("test", {}, conn, ctrl) is None

    # Mismatched CONFIG_TYPE
    assert (
        create_property("test", {CONFIG_TYPE: "non_existent_type"}, conn, ctrl) is None
    )
    assert (
        create_status_getter("test", {CONFIG_TYPE: "non_existent_type"}, conn, ctrl)
        is None
    )


async def test_get_json_status_load_from_yaml_existing_template():
    """Test load_from_yaml preserves existing _connection_template."""
    conn = MagicMock(is_async_native=True, _connection_template=Template(hass=MagicMock(data={}), template="inherited"))
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    g = GetJsonStatus("test", conn, ctrl)
    existing_tmpl = Template(hass=MagicMock(data={}), template="pre_existing")
    g._connection_template = existing_tmpl

    res = g.load_from_yaml({"type": STATUS_GETTER_JSON})
    assert res is True
    assert g._connection_template is existing_tmpl


async def test_get_json_status_load_from_yaml_default_template():
    """Test load_from_yaml creates default template when connection lacks one."""
    conn = MagicMock(spec=["is_async_native", "create_updated", "connection_template", "_connection_template"])
    conn.is_async_native = True
    conn.create_updated.return_value = conn
    conn.connection_template = None
    conn._connection_template = None
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    g = GetJsonStatus("test", conn, ctrl)
    g._connection_template = None

    res = g.load_from_yaml({"type": STATUS_GETTER_JSON})
    assert res is True
    assert g._connection_template is not None
    assert g._connection_template.render() == DEFAULT_JSON_STATUS_PAYLOAD




async def test_device_operation_resolve_async_params_missing_attr():
    """Test getattr(connection, '_connection_template') fallback with strict spec."""
    conn = MagicMock(spec=["_params", "_connection_template"])
    conn._params = {"method": "GET", "url": "/api"}
    conn._connection_template = None
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    ctrl.log_prefix = "TEST"

    op = DeviceOperation("test", conn, ctrl)
    op._connection_template = None

    params = op._resolve_async_params(conn, "val")
    assert params == {"method": "GET", "url": "/api"}


async def test_device_operation_resolve_async_params_condition_flip():
    """Test base_template resolution when conn template is different or matches template_to_use."""
    conn = MagicMock(spec=["_params", "_connection_template"])
    conn._params = {"fallback_key": "val"}
    conn._connection_template = Template(
        hass=MagicMock(data={}),
        template='{"base_param": "from_conn", "url": "/base", "dev": "{{ device_id }}"}',
    )
    ctrl = MagicMock()
    ctrl.device_id = "12345"
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    ctrl.log_prefix = "TEST"

    op = DeviceOperation("test", conn, ctrl)
    op._connection_template = Template(
        hass=MagicMock(data={}),
        template='{"method": "POST", "url": "/set/{{ value }}"}',
    )

    # Both op connection_template and conn _connection_template are rendered and merged:
    params = op._resolve_async_params(conn, "cool", duid="12345")
    assert params == {
        "fallback_key": "val",
        "base_param": "from_conn",
        "dev": "12345",
        "method": "POST",
        "url": "/set/cool",
    }

    # When conn._connection_template is identical to op._connection_template, base_template is skipped
    conn._connection_template = op._connection_template
    params_same = op._resolve_async_params(conn, "heat", duid="12345")
    assert params_same == {
        "fallback_key": "val",
        "method": "POST",
        "url": "/set/heat",
    }


async def test_get_json_status_load_from_yaml_inherits_connection_template():
    """Test load_from_yaml inherits _connection_template from connection object."""
    custom_tmpl = Template(hass=MagicMock(data={}), template='{"method": "GET", "url": "/inherited_endpoint"}')
    conn = MagicMock(is_async_native=True, connection_template=custom_tmpl)
    conn.create_updated.return_value = conn
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    g = GetJsonStatus("test", conn, ctrl)
    g._connection_template = (
        None  # Crucial: template must be None so it inherits conn_tmpl!
    )

    res = g.load_from_yaml({"type": STATUS_GETTER_JSON})
    assert res is True
    assert g._connection_template is custom_tmpl
    assert (
        g._connection_template.render()
        == '{"method": "GET", "url": "/inherited_endpoint"}'
    )

    # Test fallback to _connection_template when connection_template is None
    conn2 = MagicMock(is_async_native=True, connection_template=None, _connection_template=custom_tmpl)
    conn2.create_updated.return_value = conn2
    g2 = GetJsonStatus("test2", conn2, ctrl)
    g2._connection_template = None
    assert g2.load_from_yaml({"type": STATUS_GETTER_JSON}) is True
    assert g2._connection_template is custom_tmpl

    # Test when connection lacks template -> creates default template
    conn_no_tmpl = MagicMock(is_async_native=True, connection_template=None, _connection_template=None)
    conn_no_tmpl.create_updated.return_value = conn_no_tmpl
    g3 = GetJsonStatus("test3", conn_no_tmpl, ctrl)
    g3._connection_template = None
    assert g3.load_from_yaml({"type": STATUS_GETTER_JSON}) is True
    assert g3._connection_template is not None
    assert g3._connection_template.render() == DEFAULT_JSON_STATUS_PAYLOAD

    # Test when connection is not async native -> does not inherit
    conn_sync = MagicMock(is_async_native=False, connection_template=custom_tmpl)
    conn_sync.create_updated.return_value = conn_sync
    g4 = GetJsonStatus("test4", conn_sync, ctrl)
    g4._connection_template = None
    assert g4.load_from_yaml({"type": STATUS_GETTER_JSON}) is True
    assert g4._connection_template is None


async def test_device_property_calculate_value_from_state_valid():
    """Test calculate_value_from_state returns rendered value from template."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    prop = DeviceProperty("test_prop", conn, ctrl)
    prop._status_template = Template(hass=MagicMock(data={}), template="{{ device_state.power }}")

    val = prop.calculate_value_from_state({"power": "on"})
    assert val == "on"
    assert val is not None
    assert val != STATE_UNKNOWN


def test_load_from_yaml_missing_connection_and_values(mock_connection, mock_controller):
    """Verify load_from_yaml when CONFIG_DEVICE_CONNECTION and CONFIG_DEVICE_OPERATION_VALUES are missing."""
    prop = DeviceProperty("test_prop", mock_connection, mock_controller)
    assert prop.load_from_yaml({"name": "test"}) is True

    op = BasicDeviceOperation("test_op", mock_connection, mock_controller)
    # Missing CONFIG_DEVICE_OPERATION_VALUES should safely return False instead of raising TypeError on len(None)
    assert op.load_from_yaml({"name": "test_op"}) is False


def test_basicdeviceoperation_values_hvac_mode_key(mock_connection, mock_controller):
    """Verify that hvac_mode key in loader operations is resolved for hvac_prop."""
    op = BasicDeviceOperation("test_op", mock_connection, mock_controller)
    op._value_validation_templates = {"on": MagicMock()}
    mock_hvac_op = MagicMock()
    mock_hvac_op.state_node = "hvac_state"
    
    mock_loader = MagicMock()
    mock_loader.operations = {"hvac_mode": mock_hvac_op}
    mock_controller.loader = mock_loader

    mock_prop = MagicMock()
    mock_prop.id = "none"
    mock_controller.get_property.return_value = mock_prop
    op._device_state = {"hvac_state": "cool"}

    # Must resolve mock_hvac_op via "hvac_mode" key and use hvac_state in cache key
    vals = op.values
    assert op._values_cache["none_cool"] == vals


async def test_getjsonstatus_calculate_value_json_strict(
    mock_connection, mock_controller
):
    """Kill json_loads(None) and render_template parameter mutants."""
    getter = GetJsonStatus("test_json_strict", mock_connection, mock_controller)
    # Give it a template referencing device_state
    getter._status_template = Template(
        hass=MagicMock(data={}),
        template='{"status": "{{ device_state.power }}", "code": {{ device_state.code }}}'
    )

    result = getter.calculate_value_from_state({"power": "active", "code": 100})

    assert isinstance(result, dict)
    assert result == {"status": "active", "code": 100}

    # When status_template is None -> returns device_state directly
    getter._status_template = None
    assert getter.calculate_value_from_state({"raw": 1}) == {"raw": 1}


def test_apply_optimistic_cascades_comprehensive(mock_connection, mock_controller):
    """Test that apply_optimistic_cascades correctly mutates root, nested state, and handles edge cases."""
    prop = DeviceProperty("test_cascades", mock_connection, mock_controller)

    # 1. No config -> no-op
    state = {"power": "Off"}
    prop.apply_optimistic_cascades(state, "cool")
    assert state == {"power": "Off"}

    # 2. cascades is not a list (string, int, or None) -> early return without mutating
    prop._config = {"optimistic_cascades": "invalid_type"}
    state_str = {"power": "Off"}
    prop.apply_optimistic_cascades(state_str, "cool")
    assert state_str == {"power": "Off"}

    prop._config = {"optimistic_cascades": 123}
    state_int = {"power": "Off"}
    prop.apply_optimistic_cascades(state_int, "cool")
    assert state_int == {"power": "Off"}

    # 3. state has empty Devices list -> len > 0 check avoids IndexError
    prop._config = {
        "optimistic_cascades": [
            {"target_node": "power", "value_map": {"on": "On"}}
        ]
    }
    state_empty_devs = {"power": "Off", "Devices": []}
    prop.apply_optimistic_cascades(state_empty_devs, "on")
    assert state_empty_devs["power"] == "On"
    assert state_empty_devs["Devices"] == []

    # 4. Standard root and nested cascade execution
    prop.load_from_yaml({
        "optimistic_cascades": [
            {
                "target_node": "AC_FUN_POWER",
                "value_map": {
                    "off": "Off",
                    "default": "On",
                },
            },
            {
                "target_node": "Operation.power",
                "value_map": {
                    "off": "Off",
                    "default": "On",
                },
            },
        ]
    })

    # Test "cool" -> turns power to "On"
    state1 = {
        "AC_FUN_POWER": "Off",
        "Operation": {"power": "Off"},
        "Devices": [{"Operation": {"power": "Off"}}],
    }
    prop.apply_optimistic_cascades(state1, "cool")
    assert state1["AC_FUN_POWER"] == "On"
    assert state1["Operation"]["power"] == "On"
    assert state1["Devices"][0]["Operation"]["power"] == "On"

    # Test "off" -> turns power to "Off"
    state2 = {
        "AC_FUN_POWER": "On",
        "Operation": {"power": "On"},
    }
    prop.apply_optimistic_cascades(state2, "off")
    assert state2["AC_FUN_POWER"] == "Off"
    assert state2["Operation"]["power"] == "Off"

    # 5. Multiple cascade rules with invalid rules in between -> continue vs break
    prop._config = {
        "optimistic_cascades": [
            "invalid_non_dict_rule",
            {"target_node": None, "value_map": {"on": "On"}},
            {"target_node": "mode", "value_map": "invalid_value_map"},
            {"target_node": "power", "value_map": {"on": "On"}},
            {"target_node": "fan", "value_map": {"on": "High"}},
        ]
    }
    state_multi = {"power": "Off", "fan": "Low"}
    prop.apply_optimistic_cascades(state_multi, "on")
    assert state_multi["power"] == "On"
    assert state_multi["fan"] == "High"

    # 6. Intermediate non-dict path replacement
    prop._config = {
        "optimistic_cascades": [
            {"target_node": "nested.sub.key", "value_map": {"on": "active"}}
        ]
    }
    state_nested_override = {"nested": "primitive_string"}
    prop.apply_optimistic_cascades(state_nested_override, "on")
    assert isinstance(state_nested_override["nested"], dict)
    assert state_nested_override["nested"]["sub"]["key"] == "active"

    # 7. Default fallback in value_map
    prop._config = {
        "optimistic_cascades": [
            {"target_node": "status", "value_map": {"on": "On", "default": "Unknown"}}
        ]
    }
    state_default = {"status": "Old"}
    prop.apply_optimistic_cascades(state_default, "unmapped_val")
    assert state_default["status"] == "Unknown"

    # 8. Empty/missing optimistic_cascades in config
    prop._config = {}
    state_no_cfg = {"power": "Off"}
    prop.apply_optimistic_cascades(state_no_cfg, "on")
    assert state_no_cfg == {"power": "Off"}

    # 9. Rules with empty string target_node, empty dict value_map, or None value_map
    prop._config = {
        "optimistic_cascades": [
            {"target_node": "", "value_map": {"on": "On"}},
            {"target_node": "valid_target", "value_map": {}},
            {"target_node": "valid_target2", "value_map": None},
            {"target_node": "power", "value_map": {"on": "On"}},
        ]
    }
    state_edge = {"power": "Off"}
    prop.apply_optimistic_cascades(state_edge, "on")
    assert state_edge["power"] == "On"
    assert "valid_target" not in state_edge
    assert "valid_target2" not in state_edge


def test_template_log_fn_and_clear_cache():
    """Test _template_log_fn logs unique warning only once and clear_template_warning_cache clears it."""
    from custom_components.climate_ip.properties import (
        _WARNED_TEMPLATE_MESSAGES,
        _template_log_fn,
        clear_template_warning_cache,
    )

    clear_template_warning_cache()
    assert len(_WARNED_TEMPLATE_MESSAGES) == 0

    with patch("custom_components.climate_ip.properties._LOGGER.debug") as mock_debug:
        _template_log_fn(logging.WARNING, "test warning message 1")
        assert "test warning message 1" in _WARNED_TEMPLATE_MESSAGES
        mock_debug.assert_called_once_with("Template variable warning: %s", "test warning message 1")

        # Second call with the same message should not log again
        mock_debug.reset_mock()
        _template_log_fn(logging.WARNING, "test warning message 1")
        mock_debug.assert_not_called()

        # Different message should log
        _template_log_fn(logging.WARNING, "test warning message 2")
        mock_debug.assert_called_once_with("Template variable warning: %s", "test warning message 2")
        assert "test warning message 2" in _WARNED_TEMPLATE_MESSAGES

    clear_template_warning_cache()
    assert len(_WARNED_TEMPLATE_MESSAGES) == 0


def test_device_property_route_to_subdevice():
    """Test _route_to_subdevice covers path resolution, id matching, mode fallback, and default fallback."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.device_id = "ac_unit_2"
    ctrl.loader = MagicMock()
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
    prop = DeviceProperty("test_prop", conn, ctrl)

    # 1. Path is None -> returns copy of raw_dict
    ctrl.loader.parsed_yaml_cache["ac_unit_2"][KEY_DEVICE_CONFIG][KEY_IDENTIFIERS] = {}
    raw_dict = {"general": 1}
    assert prop._route_to_subdevice(raw_dict) == {"general": 1}

    # 2. Path exists, but devices_list is not list or empty
    ctrl.loader.parsed_yaml_cache["ac_unit_2"][KEY_DEVICE_CONFIG][KEY_IDENTIFIERS] = {
        KEY_PATH_TO_DEVICES: ["Devices"],
        CONF_SUBDEVICE_ID: ["id"],
    }
    assert prop._route_to_subdevice({"Devices": None}) == {"Devices": None}
    assert prop._route_to_subdevice({"Devices": []}) == {"Devices": []}
    assert prop._route_to_subdevice({"Devices": "not_a_list"}) == {"Devices": "not_a_list"}

    # 3. Strict match by device_id across multiple devices
    devices = [
        {"id": "ac_unit_1", "name": "Unit 1"},
        {"id": "ac_unit_2", "name": "Unit 2"},
        {"id": "ac_unit_3", "name": "Unit 3"},
    ]
    routed = prop._route_to_subdevice({"Devices": devices})
    assert routed == {"id": "ac_unit_2", "name": "Unit 2"}

    # 4. Fallback to first AC unit with KEY_DEVICE_MODE when device_id doesn't match
    devices_mode_fallback = [
        {"id": "wifi_kit_0", "wifi": True},
        {"id": "ac_unknown", KEY_DEVICE_MODE: "Cool", "temp": 24},
        {"id": "ac_other", KEY_DEVICE_MODE: "Heat", "temp": 21},
    ]
    routed_mode = prop._route_to_subdevice({"Devices": devices_mode_fallback})
    assert routed_mode == {"id": "ac_unknown", KEY_DEVICE_MODE: "Cool", "temp": 24}

    # 5. Absolute fallback (first item) when neither device_id nor KEY_DEVICE_MODE matches
    devices_abs_fallback = [
        {"id": "other_1", "power": "on"},
        {"id": "other_2", "power": "off"},
    ]
    routed_abs = prop._route_to_subdevice({"Devices": devices_abs_fallback})
    assert routed_abs == {"id": "other_1", "power": "on"}


def test_device_property_is_valid_strict(mock_connection, mock_controller):
    """Test is_valid strictly evaluates template and condition flips."""
    prop = DeviceProperty("test_prop", mock_connection, mock_controller)

    # 1. validation_template is None -> True
    prop._validation_template = None
    assert prop.is_valid({"any": "state"}) is True

    # 2. device_state is None -> True
    prop._validation_template = Template(hass=MagicMock(data={}), template="true")
    assert prop.is_valid(None) is True

    # 3. validation_template is not None, device_state is not None, template renders "valid" -> True
    prop._validation_template = Template(
        hass=MagicMock(data={}),
        template="{{ 'valid' if device_state.power == 'on' else 'invalid' }}",
    )
    assert prop.is_valid({"power": "on"}) is True

    # 4. validation_template is not None, device_state is not None, template renders "invalid" -> False
    assert prop.is_valid({"power": "off"}) is False

    # 5. TemplateError / Exception -> False
    prop._validation_template = Template(hass=MagicMock(data={}), template="{{ 1 / 0 }}")
    assert prop.is_valid({"power": "on"}) is False


def test_device_property_value_is_string_matrix(mock_connection, mock_controller):
    """Test value_is_string property across types and device classes to kill boolean mutants."""
    prop = DeviceProperty("test_prop", mock_connection, mock_controller)

    # Type is PROPERTY_TYPE_STRING, device_class is None -> True
    prop._type = PROPERTY_TYPE_STRING
    prop._device_class = None
    assert prop.value_is_string is True

    # Type is PROPERTY_TYPE_ENUM, device_class is None -> True
    prop._type = PROPERTY_TYPE_ENUM
    prop._device_class = None
    assert prop.value_is_string is True

    # Type is something else, device_class is SensorDeviceClass.ENUM -> True
    prop._type = "other_type"
    prop._device_class = SensorDeviceClass.ENUM
    assert prop.value_is_string is True

    # Type is something else, device_class is not ENUM (e.g. None or temperature) -> False
    prop._type = "other_type"
    prop._device_class = None
    assert prop.value_is_string is False

    prop._device_class = "temperature"
    assert prop.value_is_string is False


async def test_getjsonstatus_async_update_state_async_native_comprehensive(
    mock_connection, mock_controller
):
    """Test GetJsonStatus.async_update_state in async native mode across all branches and fallbacks."""
    g = GetJsonStatus("test_getter", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    mock_connection._params = {"base_key": "base_val"}
    mock_connection.config = {"duid": "cfg_duid", "token": "cfg_token"}

    # 1. Connection template is None -> returns None and logs error
    g._connection_template = None
    res = await g.async_update_state(None, False)
    assert res is None

    # 2. DUID resolution failure when neither controller nor config has device_id/duid
    g._controller = None
    mock_connection.config = {}
    g._connection_template = Template(hass=MagicMock(data={}), template='{"method": "GET", "url": "/status"}')
    with pytest.raises(ValueError, match="Could not resolve device_id/duid"):
        await g.async_update_state(None, False)

    # 3. Successful async native execution with JSON payload template
    g._controller = mock_controller
    mock_controller.device_id = "ctrl_duid"
    mock_connection.config = {"token": "my_secret_token"}
    g._connection_template = Template(
        hass=MagicMock(data={}),
        template='{"method": "GET", "url": "/status/{{ device_id }}", "headers": {"Token": "{{ token }}"}}',
    )
    mock_connection.async_execute = AsyncMock(
        return_value=('{"power": "on", "temperature": 22}', None)
    )

    res = await g.async_update_state(None, False)
    assert res == {"power": "on", "temperature": 22}
    assert g.value == {"power": "on", "temperature": 22}
    assert g._json_status == {"power": "on", "temperature": 22}
    assert g.state_attributes == {KEY_DEVICE_STATE: json_dumps({"power": "on", "temperature": 22})}
    mock_connection.async_execute.assert_called_once_with(
        "GET",
        "/status/ctrl_duid",
        None,
        {"Token": "my_secret_token"},
        _is_poll=True,
    )

    # 3b. DUID fallback from connection.config when controller is None, testing {{ duid }}
    g._controller = None
    mock_connection.config = {KEY_DUID: "cfg_duid", "token": "my_token"}
    g._connection_template = Template(
        hass=MagicMock(data={}),
        template='{"method": "GET", "url": "/status/{{ duid }}", "headers": {"Token": "{{ token }}"}}',
    )
    mock_connection.async_execute = AsyncMock(
        return_value=('{"power": "on"}', None)
    )
    res_cfg_duid = await g.async_update_state(None, False)
    assert res_cfg_duid == {"power": "on"}
    mock_connection.async_execute.assert_called_once_with(
        "GET",
        "/status/cfg_duid",
        None,
        {"Token": "my_token"},
        _is_poll=True,
    )
    g._controller = mock_controller

    # 4. Successful async native execution with raw (non-JSON) string template
    mock_connection.async_execute.reset_mock()
    g._connection_template = Template(hass=MagicMock(data={}), template="GET_STATUS_RAW")
    mock_connection.async_execute = AsyncMock(
        return_value=('{"raw_result": 1}', None)
    )
    res_raw = await g.async_update_state(None, False)
    assert res_raw == {"raw_result": 1}
    mock_connection.async_execute.assert_called_once_with(
        None,
        None,
        "GET_STATUS_RAW",
        None,
        _is_poll=True,
    )

    # 5. Response text is None from async_execute -> returns None
    mock_connection.async_execute = AsyncMock(return_value=(None, None))
    res_none = await g.async_update_state(None, False)
    assert res_none is None

    # 6. Response text is invalid JSON -> returns None
    mock_connection.async_execute = AsyncMock(return_value=("not_json_at_all", None))
    res_invalid = await g.async_update_state(None, False)
    assert res_invalid is None

    # 7. Sync mode fallback (is_async_native = False) with None result sets _attrs to None
    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(return_value=None)
    g._connection_template = Template(hass=MagicMock(data={}), template="test")
    res_sync_none = await g.async_update_state(None, False)
    assert res_sync_none is None
    assert g._attrs == {KEY_DEVICE_STATE: None}

    # 8. Sync mode success verifies self.connection_template passed to async_execute_with_retry
    mock_connection.is_async_native = False
    g._connection_template = Template(hass=MagicMock(data={}), template="sync_tmpl")
    g.value = {"prev_state": 1}
    mock_connection.async_execute_with_retry = AsyncMock(return_value={"sync_ok": True})
    res_sync_ok = await g.async_update_state(None, False)
    assert res_sync_ok == {"sync_ok": True}
    assert g.value == {"sync_ok": True}
    mock_connection.async_execute_with_retry.assert_called_once_with(
        g.connection_template, None, {"prev_state": 1}
    )


async def test_deviceoperation_async_set_value_async_native_http_response(
    mock_connection, mock_controller
):
    """Test DeviceOperation.async_set_value in async native mode for response presence, failure, and strict routing."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    mock_controller.device_id = "test_duid"

    # 1. Successful HTTP call returns response text -> returns True
    op._connection_template = Template(
        hass=MagicMock(data={}),
        template='{"method": "POST", "url": "/set_state", "json": {"state": "on"}, "headers": {"Content-Type": "json"}}',
    )
    mock_connection.async_execute = AsyncMock(return_value=('{"success": true}', None))
    res = await op.async_set_value("on")
    assert res is True
    mock_connection.async_execute.assert_called_once_with(
        "POST",
        "/set_state",
        json_dumps({"state": "on"}),
        {"Content-Type": "json"},
        device_state={},
    )

    # 2. HTTP call returns (None, None) -> returns False
    mock_connection.async_execute = AsyncMock(return_value=(None, None))
    res_none = await op.async_set_value("on")
    assert res_none is False

    # 3. Missing method or url raises ValueError
    op._connection_template = Template(
        hass=MagicMock(data={}),
        template='{"headers": {"Content-Type": "json"}}',
    )
    with pytest.raises(ValueError, match="Strict routing failed: Missing method or url"):
        await op.async_set_value("on")


async def test_deviceoperation_resolve_async_params_non_dict_base(
    mock_connection, mock_controller
):
    """Test _resolve_async_params handles base_template rendering a non-dict JSON without TypeError."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection._params = {"default_header": "test_header"}
    # Base template returns a JSON list instead of a dict
    mock_connection._connection_template = Template(
        hass=MagicMock(data={}), template="[1, 2, 3]"
    )
    op._connection_template = Template(
        hass=MagicMock(data={}),
        template='{"method": "POST", "url": "/api/set"}',
    )

    params = op._resolve_async_params(mock_connection, "val")
    # Base params should safely fallback to {} and merge with raw_params and operation_params
    assert params == {
        "default_header": "test_header",
        "method": "POST",
        "url": "/api/set",
    }


async def test_temperatureoperation_load_from_yaml_unit_template(
    mock_connection, mock_controller
):
    """Test TemperatureOperation.load_from_yaml parses unit_template and handles invalid nodes."""
    op = TemperatureOperation("test_temp", mock_connection, mock_controller)

    # 1. node is None -> returns False
    assert op.load_from_yaml(None) is False
    assert op._unit_template is None

    # 2. node without unit template -> returns True, unit_template is None
    assert op.load_from_yaml({"type": PROPERTY_TYPE_TEMP}) is True
    assert op._unit_template is None

    # 3. node with unit template -> returns True, unit_template is compiled Template
    yaml_node = {
        "type": PROPERTY_TYPE_TEMP,
        CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE: "{{ device_state.temp_unit }}",
    }
    assert op.load_from_yaml(yaml_node) is True
    assert isinstance(op._unit_template, Template)


async def test_temperatureoperation_async_update_state_status_getter(
    mock_connection, mock_controller
):
    """Test TemperatureOperation.async_update_state dynamically resolves unit and value via status_getter."""
    status_getter = MagicMock()
    status_getter.value = {"temp_unit": "F", "current_temp": "77"}

    op = TemperatureOperation("test_temp", mock_connection, mock_controller, status_getter)
    op._unit_template = Template(hass=MagicMock(data={}), template="{{ device_state.temp_unit }}")
    op._status_template = Template(hass=MagicMock(data={}), template="{{ device_state.current_temp }}")
    op._hass_unit = UnitOfTemperature.CELSIUS

    # Update without device_state_override to exercise self._status_getter.value branch
    val = await op.async_update_state()
    assert val == 25.0
    assert op.value == 25.0
    assert op._device_unit == UnitOfTemperature.FAHRENHEIT




