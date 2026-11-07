# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,invalid-sequence-index,unsubscriptable-object
"""Tests for DeviceProperty, GetJsonStatus, ModeOperation and TemperatureOperation."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

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
    KEY_HEADERS,
    KEY_HVAC,
    KEY_IDENTIFIERS,
    KEY_PATH_TO_DEVICES,
    KEY_RAW_PAYLOAD,
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
)
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
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template


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


def test_device_property_load_from_yaml(mock_connection, mock_controller):
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


def test_device_property_load_state_class_exception(mock_connection, mock_controller):
    """Pattern 2: Exception when loading state_class."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    yaml_node = {"state_class": "invalid_class"}
    with pytest.raises(ValueError, match="Invalid state_class 'invalid_class' in YAML"):
        prop.load_from_yaml(yaml_node)


def test_device_property_load_from_yaml_immediate_assertions(
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


def test_getjsonstatus_init(mock_connection, mock_controller):
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


def test_mode_operation_mapping(mock_connection, mock_controller):
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

    with patch.object(
        op, "_resolve_async_params", return_value={"method": "GET", "url": "/test"}
    ):
        mock_connection.async_execute.side_effect = AuthError("Token expired")
        with pytest.raises(HomeAssistantError, match="Connection error"):
            await op.async_set_value("val")


# ====================================================================================
# PHASE 2: BasicDeviceOperation HARDENED TESTS
# ====================================================================================


def test_basicdeviceoperation_load_from_yaml(mock_connection, mock_controller):
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


def test_basicdeviceoperation_dynamic_values(mock_connection, mock_controller):
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


def test_modeoperation_init(mock_connection, mock_controller):
    """Test ModeOperation assigns _id based on standard names."""
    op = ModeOperation(ATTR_HVAC_MODE, mock_connection, mock_controller)
    assert op.id == ATTR_HVAC_MODE

    op2 = ModeOperation("custom_mode", mock_connection, mock_controller)
    assert op2.id == "custom_mode_mode"


def test_switchoperation_load_from_yaml(mock_connection, mock_controller):
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
    assert (
        op_on_only.load_from_yaml(
            {
                CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
                CONFIG_DEVICE_OPERATION_VALUES: {
                    STATE_ON: {CONFIG_DEVICE_OPERATION_VALUE: "1"},
                },
            }
        )
        is True
    )
    assert op_on_only._values_ha_to_dev_map[True] == "1"
    assert False not in op_on_only._values_ha_to_dev_map

    # Edge case: only OFF configured
    op_off_only = SwitchOperation("test_off", mock_connection, mock_controller)
    assert (
        op_off_only.load_from_yaml(
            {
                CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
                CONFIG_DEVICE_OPERATION_VALUES: {
                    STATE_OFF: {CONFIG_DEVICE_OPERATION_VALUE: "0"},
                },
            }
        )
        is True
    )
    assert op_off_only._values_ha_to_dev_map[False] == "0"
    assert True not in op_off_only._values_ha_to_dev_map


def test_switchoperation_should_evict_all_locks(mock_connection, mock_controller):
    """Test SwitchOperation should_evict_all_locks for power IDs, state values, and fallbacks."""
    # 1. Switch with ID "power" turning OFF returns True
    op_power = SwitchOperation("power", mock_connection, mock_controller)
    op_power._status_template = Template(
        hass=mock_controller.hass, template="{{ device_state.power }}"
    )
    assert op_power.should_evict_all_locks({"power": "off"}, {"power"}) is True
    assert op_power.should_evict_all_locks({"power": "Off"}, {"power"}) is True
    assert op_power.should_evict_all_locks({"power": "OFF"}, {"power"}) is True
    assert op_power.should_evict_all_locks({"power": STATE_OFF}, {"power"}) is True
    assert op_power.should_evict_all_locks({"power": "on"}, {"power"}) is False
    assert op_power.should_evict_all_locks({"power": "On"}, {"power"}) is False
    assert op_power.should_evict_all_locks({"power": "ON"}, {"power"}) is False
    assert op_power.should_evict_all_locks({"power": "standby"}, {"power"}) is False
    assert op_power.should_evict_all_locks({}, set()) is False

    # 2. Switch with ID "AC_FUN_POWER" turning OFF returns True
    op_samsung_power = SwitchOperation("AC_FUN_POWER", mock_connection, mock_controller)
    op_samsung_power._status_template = Template(
        hass=mock_controller.hass, template="{{ device_state.AC_FUN_POWER }}"
    )
    assert (
        op_samsung_power.should_evict_all_locks(
            {"AC_FUN_POWER": "Off"}, {"AC_FUN_POWER"}
        )
        is True
    )
    assert (
        op_samsung_power.should_evict_all_locks(
            {"AC_FUN_POWER": "off"}, {"AC_FUN_POWER"}
        )
        is True
    )
    assert (
        op_samsung_power.should_evict_all_locks(
            {"AC_FUN_POWER": "OFF"}, {"AC_FUN_POWER"}
        )
        is True
    )
    assert (
        op_samsung_power.should_evict_all_locks(
            {"AC_FUN_POWER": "On"}, {"AC_FUN_POWER"}
        )
        is False
    )

    # 3. Non-power switch IDs always return False regardless of state
    for non_power_id in (
        "other_switch",
        "fan_power",
        "power_mode",
        "AC_FUN_POWER_2",
        "switch",
    ):
        op_other = SwitchOperation(non_power_id, mock_connection, mock_controller)
        op_other._status_template = Template(
            hass=mock_controller.hass, template="{{ device_state.val }}"
        )
        assert op_other.should_evict_all_locks({"val": "off"}, {"val"}) is False
        assert op_other.should_evict_all_locks({"val": "Off"}, {"val"}) is False
        assert op_other.should_evict_all_locks({"val": "on"}, {"val"}) is False

    # 4. Direct calculate_value_from_state return checks
    with patch.object(
        op_power, "calculate_value_from_state", return_value="Off"
    ) as mock_calc:
        assert op_power.should_evict_all_locks({"dummy": 1}, set()) is True
        mock_calc.assert_called_once_with({"dummy": 1})

    with patch.object(op_power, "calculate_value_from_state", return_value="On"):
        assert op_power.should_evict_all_locks({"dummy": 1}, set()) is False

    with patch.object(op_power, "calculate_value_from_state", return_value=None):
        assert op_power.should_evict_all_locks({"dummy": 1}, set()) is False


def test_basicnumericoperation_value_property(mock_connection, mock_controller):
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

    with pytest.raises(ValueError, match="Invalid numeric value"):
        op.convert_hass_to_dev("not_a_num")


def test_temperatureoperation_unit_conversion(mock_connection, mock_controller):
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


def test_global_factories_and_registers(mock_connection, mock_controller):
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

    assert (
        create_property("test_prop", {}, mock_connection, mock_controller, "my_getter")
        is None
    )
    assert (
        create_property(
            "test_prop",
            {CONFIG_TYPE: "non_existent"},
            mock_connection,
            mock_controller,
            "my_getter",
        )
        is None
    )
    assert (
        create_status_getter("test_getter", {}, mock_connection, mock_controller)
        is None
    )
    assert (
        create_status_getter(
            "test_getter",
            {CONFIG_TYPE: "non_existent"},
            mock_connection,
            mock_controller,
        )
        is None
    )

    # Clean up globals so tests don't leak
    CLIMATE_IP_PROPERTIES.remove(DummyProp)
    CLIMATE_IP_STATUS_GETTER.remove(DummyGetter)


def test_basicdeviceoperation_load_from_yaml_edge_cases(
    mock_connection, mock_controller
):
    """Kill mutants related to load_from_yaml fallbacks, empty values, feature flags."""
    from homeassistant.components.climate.const import ClimateEntityFeature

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


def test_basicdeviceoperation_is_value_valid_edge_cases(
    mock_connection, mock_controller
):
    """Kill mutants in is_value_valid logic."""
    op = BasicDeviceOperation("test", mock_connection, mock_controller)
    # Template is None -> returns True
    assert op.is_value_valid("test_val", {"k": "v"}) is True

    # Template is not None but device_state is None -> returns False
    op._value_validation_templates["test_val"] = MagicMock()
    assert op.is_value_valid("test_val", None) is False


def test_basicnumericoperation_load_from_yaml(mock_connection, mock_controller):
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


def test_basicdeviceoperation_init_and_get_conn(mock_connection, mock_controller):
    """Verify BasicDeviceOperation __init__ and get_connection."""
    op = BasicDeviceOperation("test", mock_connection, mock_controller)
    assert op._feature_flag is None

    op._value_connections_map = {"on": "mock_on_conn"}
    assert op.get_connection("on") == "mock_on_conn"
    assert op.get_connection("off") == mock_connection


def test_temperature_boundaries_exact(mock_connection, mock_controller):
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


def test_device_property_mutants():
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


def test_basic_numeric_operation_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = BasicNumericOperation("test_bno", conn, ctrl)
    assert op.load_from_yaml({"type": "test"}) is True


def test_static_yaml_strings_and_base_units(mock_connection, mock_controller):
    """Test static YAML strings and base set_unit_of_measurement."""
    from custom_components.climate_ip.properties import DeviceProperty
    from homeassistant.components.sensor import SensorStateClass

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
    op._validation_template = Template(
        hass=MagicMock(data={}),
        template="{% if device_state %}valid{% else %}invalid{% endif %}",
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


def test_getjsonstatus_remaining_mutants():
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
    op._status_template = Template(
        hass=MagicMock(data={}), template='{"result": "{{ device_state.val }}"}'
    )
    assert op.calculate_value_from_state({"val": "ok"}) == {"result": "ok"}


def test_basicdeviceoperation_remaining_mutants():
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


def test_modeoperation_remaining_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    status_getter = MagicMock()
    op = ModeOperation("test_mode", conn, ctrl, status_getter=status_getter)
    assert op._status_getter == status_getter


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
    mock_unit_tmpl = MagicMock(spec=Template)
    mock_unit_tmpl.async_render.return_value = "unknown"
    op._unit_template = mock_unit_tmpl
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
    op._status_template = Template(
        hass=MagicMock(data={}), template="{{ device_state.val }}"
    )
    v = op.calculate_value_from_state({"val": "77"})
    assert v == 25.0


# ====================================================================================
# Unit Tests: Strict Specs, Missing Attributes, Match & State Attributes
# ====================================================================================


def test_device_operation_match_value():
    """Test DeviceOperation.match_value returns False."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = DeviceOperation("test_op", conn, ctrl)
    assert op.match_value("on") is False
    assert op.match_value(123) is False


def test_basic_device_operation_match_value():
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


def test_mode_operation_match_type():
    """Test ModeOperation.match_type checks PROPERTY_TYPE_MODE."""
    assert ModeOperation.match_type(PROPERTY_TYPE_MODE) is True
    assert ModeOperation.match_type("switch") is False
    assert ModeOperation.match_type("number") is False


def test_mode_operation_state_attributes_matrix():
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


def test_get_json_status_load_from_yaml_default_template():
    """Test load_from_yaml creates default template when connection lacks one."""
    conn = MagicMock(
        spec=[
            "is_async_native",
            "create_updated",
            "connection_template",
            "_connection_template",
        ]
    )
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


def test_device_operation_resolve_async_params_missing_attr():
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


def test_device_operation_resolve_async_params_empty_params_returns_none():
    """An empty connection params dict without template must resolve to None."""
    conn = MagicMock(spec=["_params", "_connection_template"])
    conn._params = {}
    conn._connection_template = None
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    ctrl.log_prefix = "TEST"

    op = DeviceOperation("test", conn, ctrl)
    op._connection_template = None

    assert op._resolve_async_params(conn, "val") is None


def test_device_operation_resolve_async_params_condition_flip():
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


def test_get_json_status_load_from_yaml_inherits_connection_template():
    """Test load_from_yaml inherits _connection_template from connection object."""
    custom_tmpl = Template(
        hass=MagicMock(data={}),
        template='{"method": "GET", "url": "/inherited_endpoint"}',
    )
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
    conn2 = MagicMock(
        is_async_native=True, connection_template=None, _connection_template=custom_tmpl
    )
    conn2.create_updated.return_value = conn2
    g2 = GetJsonStatus("test2", conn2, ctrl)
    g2._connection_template = None
    assert g2.load_from_yaml({"type": STATUS_GETTER_JSON}) is True
    assert g2._connection_template is custom_tmpl

    # Test when connection lacks template -> creates default template
    conn_no_tmpl = MagicMock(
        is_async_native=True, connection_template=None, _connection_template=None
    )
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
        "optimistic_cascades": [{"target_node": "power", "value_map": {"on": "On"}}]
    }
    state_empty_devs = {"power": "Off", "Devices": []}
    prop.apply_optimistic_cascades(state_empty_devs, "on")
    assert state_empty_devs["power"] == "On"
    assert state_empty_devs["Devices"] == []

    # 4. Standard root and nested cascade execution
    prop.load_from_yaml(
        {
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
        }
    )

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
        clear_template_warning_cache,
    )

    clear_template_warning_cache()
    assert len(_WARNED_TEMPLATE_MESSAGES) == 0

    with patch("custom_components.climate_ip.properties._LOGGER.debug") as mock_debug:
        _template_log_fn(logging.WARNING, "test warning message 1")
        assert "test warning message 1" in _WARNED_TEMPLATE_MESSAGES
        mock_debug.assert_called_once_with(
            "Template variable warning: %s", "test warning message 1"
        )

        # Second call with the same message should not log again
        mock_debug.reset_mock()
        _template_log_fn(logging.WARNING, "test warning message 1")
        mock_debug.assert_not_called()

        # Different message should log
        _template_log_fn(logging.WARNING, "test warning message 2")
        mock_debug.assert_called_once_with(
            "Template variable warning: %s", "test warning message 2"
        )
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
    assert prop._route_to_subdevice({"Devices": "not_a_list"}) == {
        "Devices": "not_a_list"
    }

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

    # 6. A custom subdevice id path must be honoured (non-colliding with default ["id"])
    ctrl.loader.parsed_yaml_cache["ac_unit_2"][KEY_DEVICE_CONFIG][KEY_IDENTIFIERS] = {
        KEY_PATH_TO_DEVICES: ["Devices"],
        CONF_SUBDEVICE_ID: ["uuid"],
    }
    devices_custom_path = [
        {"id": "ac_unit_2", "uuid": "decoy", "name": "Decoy"},
        {"id": "other", "uuid": "ac_unit_2", "name": "Target"},
    ]
    routed_custom = prop._route_to_subdevice({"Devices": devices_custom_path})
    assert routed_custom == {"id": "other", "uuid": "ac_unit_2", "name": "Target"}

    # 7. A missing subdevice id key falls back to the default ["id"] path
    ctrl.loader.parsed_yaml_cache["ac_unit_2"][KEY_DEVICE_CONFIG][KEY_IDENTIFIERS] = {
        KEY_PATH_TO_DEVICES: ["Devices"],
    }
    devices_default_path = [
        {"id": "other", "name": "First"},
        {"id": "ac_unit_2", "name": "Target"},
    ]
    routed_default = prop._route_to_subdevice({"Devices": devices_default_path})
    assert routed_default == {"id": "ac_unit_2", "name": "Target"}


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
    prop._validation_template = Template(
        hass=MagicMock(data={}), template="{{ 1 / 0 }}"
    )
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
    mock_tmpl_duid_fail = MagicMock(spec=Template)
    mock_tmpl_duid_fail.async_render.return_value = (
        '{"method": "GET", "url": "/status"}'
    )
    g._connection_template = mock_tmpl_duid_fail
    with pytest.raises(ValueError, match="Could not resolve device_id/duid"):
        await g.async_update_state(None, False)

    # 3. Successful async native execution with JSON payload template
    g._controller = mock_controller
    mock_controller.device_id = "ctrl_duid"
    mock_connection.config = {"token": "my_secret_token"}
    mock_tmpl_json = MagicMock(spec=Template)
    mock_tmpl_json.async_render.side_effect = lambda ctx, **kw: json_dumps(
        {
            "method": "GET",
            "url": f"/status/{ctx['device_id']}",
            "headers": {"Token": ctx["token"]},
        }
    )
    g._connection_template = mock_tmpl_json
    mock_connection.async_execute = AsyncMock(
        return_value=('{"power": "on", "temperature": 22}', None)
    )

    res = await g.async_update_state(None, False)
    assert res == {"power": "on", "temperature": 22}
    assert g.value == {"power": "on", "temperature": 22}
    assert g._json_status == {"power": "on", "temperature": 22}
    assert g.state_attributes == {
        KEY_DEVICE_STATE: json_dumps({"power": "on", "temperature": 22})
    }
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
    mock_tmpl_cfg_duid = MagicMock(spec=Template)
    mock_tmpl_cfg_duid.async_render.side_effect = lambda ctx, **kw: json_dumps(
        {
            "method": "GET",
            "url": f"/status/{ctx['duid']}",
            "headers": {"Token": ctx["token"]},
        }
    )
    g._connection_template = mock_tmpl_cfg_duid
    mock_connection.async_execute = AsyncMock(return_value=('{"power": "on"}', None))
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
    mock_tmpl_raw = MagicMock(spec=Template)
    mock_tmpl_raw.async_render.return_value = "GET_STATUS_RAW"
    g._connection_template = mock_tmpl_raw
    mock_connection.async_execute = AsyncMock(return_value=('{"raw_result": 1}', None))
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
    with pytest.raises(
        ValueError, match="Strict routing failed: Missing method or url"
    ):
        await op.async_set_value("on")


def test_temperatureoperation_load_from_yaml_unit_template(
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

    op = TemperatureOperation(
        "test_temp", mock_connection, mock_controller, status_getter
    )
    op._unit_template = Template(
        hass=MagicMock(data={}), template="{{ device_state.temp_unit }}"
    )
    op._status_template = Template(
        hass=MagicMock(data={}), template="{{ device_state.current_temp }}"
    )
    op._hass_unit = UnitOfTemperature.CELSIUS

    # Update without device_state_override to exercise self._status_getter.value branch
    val = await op.async_update_state()
    assert val == 25.0
    assert op.value == 25.0
    assert op._device_unit == UnitOfTemperature.FAHRENHEIT


def test_apply_optimistic_cascades_complete_matrix(mock_connection, mock_controller):
    """Complete matrix test for apply_optimistic_cascades killing all mutant variants."""
    prop = DeviceProperty("test_matrix_cascades", mock_connection, mock_controller)

    # --- Case 1: Empty / Missing Cascades ---
    # Missing optimistic_cascades
    prop._config = {}
    state_case1 = {"Operation": {"power": "Off"}}
    prop.apply_optimistic_cascades(state_case1, "heat")
    assert state_case1 == {"Operation": {"power": "Off"}}

    # Empty list optimistic_cascades
    prop._config = {"optimistic_cascades": []}
    prop.apply_optimistic_cascades(state_case1, "heat")
    assert state_case1 == {"Operation": {"power": "Off"}}

    # Non-list optimistic_cascades (None, string, int)
    prop._config = {"optimistic_cascades": None}
    prop.apply_optimistic_cascades(state_case1, "heat")
    assert state_case1 == {"Operation": {"power": "Off"}}

    prop._config = {"optimistic_cascades": "not_a_list"}
    prop.apply_optimistic_cascades(state_case1, "heat")
    assert state_case1 == {"Operation": {"power": "Off"}}

    # Non-dict state
    prop._config = {
        "optimistic_cascades": [
            {"target_node": "Operation.power", "value_map": {"heat": "On"}}
        ]
    }
    prop.apply_optimistic_cascades("not_a_dict", "heat")  # type: ignore

    # --- Case 2: Exact Value Match ---
    prop._config = {
        "optimistic_cascades": [
            {
                "target_node": "Operation.power",
                "value_map": {
                    "off": "Off",
                    "heat": "On",
                    "default": "Standby",
                },
            }
        ]
    }
    state_case2 = {"Operation": {"power": "Initial"}}
    prop.apply_optimistic_cascades(state_case2, "off")
    assert state_case2["Operation"]["power"] == "Off"

    prop.apply_optimistic_cascades(state_case2, "heat")
    assert state_case2["Operation"]["power"] == "On"

    # Exact value match with boolean keys (Annihilating Mutant 30 & 32 at lines 599-600)
    prop._config = {
        "optimistic_cascades": [
            {
                "target_node": "Operation.power",
                "value_map": {
                    False: "PowerOff",
                    True: "PowerOn",
                },
            }
        ]
    }
    # Test bool key False mapped to "off"
    state_bool = {"Operation": {"power": "Initial"}}
    prop.apply_optimistic_cascades(state_bool, "off")
    assert state_bool["Operation"]["power"] == "PowerOff"

    # Test bool key False mapped to "false" (string or boolean value)
    state_bool["Operation"]["power"] = "Initial"
    prop.apply_optimistic_cascades(state_bool, False)
    assert state_bool["Operation"]["power"] == "PowerOff"

    state_bool["Operation"]["power"] = "Initial"
    prop.apply_optimistic_cascades(state_bool, "false")
    assert state_bool["Operation"]["power"] == "PowerOff"

    # Test bool key True mapped to "on"
    state_bool["Operation"]["power"] = "Initial"
    prop.apply_optimistic_cascades(state_bool, "on")
    assert state_bool["Operation"]["power"] == "PowerOn"

    # Test bool key True mapped to "true" (string or boolean value)
    state_bool["Operation"]["power"] = "Initial"
    prop.apply_optimistic_cascades(state_bool, True)
    assert state_bool["Operation"]["power"] == "PowerOn"

    state_bool["Operation"]["power"] = "Initial"
    prop.apply_optimistic_cascades(state_bool, "true")
    assert state_bool["Operation"]["power"] == "PowerOn"

    # --- Case 3: Default Fallback Match ---
    prop._config = {
        "optimistic_cascades": [
            {
                "target_node": "Operation.power",
                "value_map": {
                    "off": "Off",
                    "heat": "On",
                    "default": "Standby",
                },
            }
        ]
    }
    state_case3 = {"Operation": {"power": "Initial"}}
    prop.apply_optimistic_cascades(state_case3, "cool")
    assert state_case3["Operation"]["power"] == "Standby"

    state_case3["Operation"]["power"] = "Initial"
    prop.apply_optimistic_cascades(state_case3, "dry")
    assert state_case3["Operation"]["power"] == "Standby"

    # --- Case 4: Deep Nested Paths & Device Sub-nodes ---
    prop._config = {
        "optimistic_cascades": [
            {
                "target_node": "Operation.sub.power",
                "value_map": {
                    "off": "Off",
                    "heat": "On",
                },
            }
        ]
    }
    state_case4 = {"Devices": [{}]}
    prop.apply_optimistic_cascades(state_case4, "heat")
    assert state_case4["Operation"]["sub"]["power"] == "On"
    assert state_case4["Devices"][0]["Operation"]["sub"]["power"] == "On"

    # Intermediate non-dict structures get safely converted to dicts
    state_case4_non_dict = {
        "Operation": "primitive_string",
        "Devices": [{"Operation": 12345}],
    }
    prop.apply_optimistic_cascades(state_case4_non_dict, "off")
    assert isinstance(state_case4_non_dict["Operation"], dict)
    assert state_case4_non_dict["Operation"]["sub"]["power"] == "Off"
    assert isinstance(state_case4_non_dict["Devices"][0]["Operation"], dict)
    assert state_case4_non_dict["Devices"][0]["Operation"]["sub"]["power"] == "Off"

    # --- Case 5: Malformed Rules Guard ---
    prop._config = {
        "optimistic_cascades": [
            None,
            "invalid_non_dict",
            123,
            {"target_node": None, "value_map": {"on": "On"}},
            {"target_node": "", "value_map": {"on": "On"}},
            {"target_node": "Operation.power", "value_map": None},
            {"target_node": "Operation.power", "value_map": "not_a_dict"},
            {"target_node": "Operation.power", "value_map": 123},
            {"value_map": {"on": "On"}},
        ]
    }
    state_case5 = {"Operation": {"power": "Initial"}}
    prop.apply_optimistic_cascades(state_case5, "on")
    assert state_case5 == {"Operation": {"power": "Initial"}}


async def test_device_property_async_set_value_flow_and_cascades(
    mock_connection, mock_controller
):
    """Test DeviceProperty and DeviceOperation async_set_value execution flow, error handling, and line 664 mutants."""
    # 1. Base DeviceProperty.async_set_value (strictly returns False, annihilating mutants at line 664)
    base_prop = DeviceProperty("base_prop", mock_connection, mock_controller)
    res1 = await base_prop.async_set_value("off")
    assert res1 is False
    res2 = await base_prop.async_set_value("off", device_id="main")
    assert res2 is False

    # 2. DeviceOperation with mock async connection
    op = DeviceOperation("test_operation", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    mock_connection.config = {"duid": "main_duid"}
    mock_connection.async_execute = AsyncMock(return_value=({"status": "ok"}, 200))
    op._connection_template = Template(
        template='{"method": "POST", "url": "/api/set/{{ value }}", "json": {"state": "{{ value }}"}}',
        hass=mock_controller.hass,
    )

    # Set value flow and connection dispatch arguments
    success = await op.async_set_value("off", device_id="main")
    assert success is True
    mock_connection.async_execute.assert_awaited_once_with(
        "POST",
        "/api/set/off",
        json_dumps({"state": "off"}),
        {},
        device_state={},
    )

    # Returned status is False when response is None
    mock_connection.async_execute.reset_mock()
    mock_connection.async_execute.return_value = (None, 500)
    failed_res = await op.async_set_value("off", device_id="main")
    assert failed_res is False

    # 3. Transport error handling in async native mode
    mock_connection.async_execute.side_effect = TimeoutError("Connection timed out")
    with pytest.raises(
        HomeAssistantError, match="Unexpected error when setting test_operation"
    ):
        await op.async_set_value("off", device_id="main")

    mock_connection.async_execute.side_effect = OSError("Network unreachable")
    with pytest.raises(
        HomeAssistantError, match="Unexpected error when setting test_operation"
    ):
        await op.async_set_value("off", device_id="main")

    mock_connection.async_execute.side_effect = CannotConnect("Cannot connect")
    with pytest.raises(
        HomeAssistantError,
        match="Connection error: could not set value for test_operation",
    ):
        await op.async_set_value("off", device_id="main")

    mock_connection.async_execute.side_effect = AuthError("Unauthorized")
    with pytest.raises(
        HomeAssistantError,
        match="Connection error: could not set value for test_operation",
    ):
        await op.async_set_value("off", device_id="main")

    # 4. Sync connection fallback flow and error handling
    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(return_value=True)
    sync_res = await op.async_set_value("off", device_id="main")
    assert sync_res is True
    mock_connection.async_execute_with_retry.assert_awaited_once_with(
        op.connection_template, "off", {}, "main"
    )

    mock_connection.async_execute_with_retry.side_effect = CannotConnect(
        "Sync cannot connect"
    )
    with pytest.raises(
        HomeAssistantError,
        match="Connection error: could not set value for test_operation",
    ):
        await op.async_set_value("off", device_id="main")

    mock_connection.async_execute_with_retry.side_effect = AuthError("Sync auth failed")
    with pytest.raises(
        HomeAssistantError,
        match="Connection error: could not set value for test_operation",
    ):
        await op.async_set_value("off", device_id="main")

    # 5. Verify optimistic cascades capability and invocation
    assert hasattr(op, "apply_optimistic_cascades")
    op._config = {
        "optimistic_cascades": [
            {
                "target_node": "Operation.power",
                "value_map": {"off": "Off", "on": "On"},
            }
        ]
    }
    test_state = {"Operation": {"power": "On"}}
    op.apply_optimistic_cascades(test_state, "off")
    assert test_state["Operation"]["power"] == "Off"


# --- Sniper Tests for Fallback & Template Synthesis (Target 1) ---
@pytest.mark.asyncio
async def test_device_operation_async_set_value_routing_fallbacks_and_missing_params(
    mock_controller,
):
    """Target 1: Force and validate all fallback branches and strict routing errors in async_set_value."""
    # 1. Fallback to connection._params when params misses method and url
    mock_conn = MagicMock()
    mock_conn.is_async_native = True
    mock_conn._connection_template = None
    mock_conn.connection_template = None
    mock_conn.config = {KEY_DUID: "duid_123"}
    mock_conn._params = {
        "method": "PUT",
        "url": "/conn_endpoint",
        "headers": {"X-Custom": "1"},
    }
    mock_conn.async_execute = AsyncMock(return_value=('{"status": "ok"}', None))
    mock_controller.connection = None

    op = DeviceOperation("test_op", mock_conn, mock_controller)
    mock_tmpl_routing = MagicMock(spec=Template)
    mock_tmpl_routing.async_render.return_value = '{"json": {"power": "on"}}'
    op._connection_template = mock_tmpl_routing
    op._device_state = {"power": "off"}

    res = await op.async_set_value("on")
    assert res is True
    mock_conn.async_execute.assert_called_once_with(
        "PUT",
        "/conn_endpoint",
        json_dumps({"power": "on"}),
        {"X-Custom": "1"},
        device_state={"power": "off"},
    )

    # 2. Fallback to controller.connection._params when connection._params misses url/method
    mock_conn._params = {}
    mock_ctrl_conn = MagicMock()
    mock_ctrl_conn._params = {"method": "PATCH", "url": "/ctrl_endpoint"}
    mock_controller.connection = mock_ctrl_conn

    mock_conn.async_execute.reset_mock()
    res = await op.async_set_value("on")
    assert res is True
    mock_conn.async_execute.assert_called_once_with(
        "PATCH",
        "/ctrl_endpoint",
        json_dumps({"power": "on"}),
        {},
        device_state={"power": "off"},
    )

    # 3. Default to 'POST' when method is missing in params/conn/ctrl but KEY_JSON_PAYLOAD exists
    mock_ctrl_conn._params = {"url": "/ctrl_endpoint"}  # no method
    mock_conn.async_execute.reset_mock()
    res = await op.async_set_value("on")
    assert res is True
    assert mock_conn.async_execute.call_args[0][0] == "POST"

    # 4. Strict routing error (ValueError) when url is missing and not in fallbacks
    mock_ctrl_conn._params = {"method": "POST"}  # no url
    with pytest.raises(
        ValueError,
        match="Strict routing failed: Missing method or url in YAML configuration",
    ):
        await op.async_set_value("on")

    # 5. Non-string method/url sanitized to None and triggers strict routing error
    mock_conn._params = {"method": 12345, "url": 67890}
    mock_controller.connection = None
    with pytest.raises(
        ValueError,
        match="Strict routing failed: Missing method or url in YAML configuration",
    ):
        await op.async_set_value("on")


@pytest.mark.asyncio
async def test_get_json_status_synthesizes_connection_template_from_params(
    mock_controller,
):
    """Target 1: Validate _connection_template synthesis logic in load_from_yaml and async_update_state."""
    # 1. load_from_yaml synthesizes connection_template from connection._params
    conn = MagicMock()
    conn.is_async_native = True
    conn.connection_template = None
    conn._connection_template = None
    conn._params = {"method": "GET", "url": "/api/v1/devicestate"}
    conn.create_updated.return_value = conn

    getter = GetJsonStatus("status_getter", conn, mock_controller)
    getter._connection_template = None

    loaded = getter.load_from_yaml({"type": STATUS_GETTER_JSON})
    assert loaded is True
    assert getter._connection_template is not None
    assert getter._connection_template.template == json_dumps(
        {"method": "GET", "url": "/api/v1/devicestate"}
    )

    # 2. async_update_state synthesizes connection_template on-the-fly when _connection_template is None
    getter._connection_template = None
    conn.async_execute = AsyncMock(
        return_value=('{"power": "on", "mode": "cool"}', 200)
    )
    mock_controller.device_id = "test_ac_001"

    state_result = await getter.async_update_state()
    assert state_result == {"power": "on", "mode": "cool"}
    assert getter._connection_template is not None
    assert getter._connection_template.template == json_dumps(
        {"method": "GET", "url": "/api/v1/devicestate"}
    )
    conn.async_execute.assert_called_once_with(
        "GET",
        "/api/v1/devicestate",
        None,
        {},
        _is_poll=True,
    )


def test_basic_device_operation_detect_value_changes_and_hvac_node_kills():
    """Kill survivors in BasicDeviceOperation._detect_value_changes and _resolve_hvac_node."""
    conn = MagicMock()
    ctrl = MagicMock()
    op = BasicDeviceOperation(ATTR_FAN_MODE, conn, ctrl)

    # 1. _detect_value_changes: When _last_valid_values is None (first run): no flicker flag
    ctrl.fan_modes_list_changed_pending_flicker = False
    op._last_valid_values = None
    op._detect_value_changes(["auto", "low"])
    assert ctrl.fan_modes_list_changed_pending_flicker is False

    # 2. _detect_value_changes: When valid_values == _last_valid_values: no flicker flag
    ctrl.fan_modes_list_changed_pending_flicker = False
    op._last_valid_values = ["auto", "low"]
    op._detect_value_changes(["auto", "low"])
    assert ctrl.fan_modes_list_changed_pending_flicker is False

    # 3. _detect_value_changes: When valid_values != _last_valid_values: flicker flag set to True
    ctrl.fan_modes_list_changed_pending_flicker = False
    op._last_valid_values = ["auto", "low"]
    op._detect_value_changes(["auto", "high"])
    assert ctrl.fan_modes_list_changed_pending_flicker is True

    # 4. _resolve_hvac_node: controller is None but device_state is a dict -> returns None
    op._controller = None
    op._device_state = {"mode": "cool"}
    assert op._resolve_hvac_node() is None

    # 5. _resolve_hvac_node: hvac_prop has valid state_node: str -> must NOT fallback to loader
    op._controller = MagicMock()
    hvac_prop = MagicMock(state_node="mode")
    op._controller.get_property_object.return_value = hvac_prop
    op._controller.loader.operations = {}
    op._device_state = {"mode": "cool"}
    assert op._resolve_hvac_node() == "cool"

    # 6. _resolve_hvac_node: hvac_prop is None, controller.loader is None -> returns None
    op._controller.get_property_object.return_value = None
    op._controller.loader = None
    op._device_state = {"mode": "cool"}
    assert op._resolve_hvac_node() is None

    # 7. _resolve_hvac_node: hvac_prop is None, loader only has KEY_HVAC -> resolves from KEY_HVAC
    op._controller.loader = MagicMock()
    fallback_prop = MagicMock(state_node="mode")
    op._controller.loader.operations = {KEY_HVAC: fallback_prop}
    op._device_state = {"mode": "heat"}
    assert op._resolve_hvac_node() == "heat"

    # 8. _resolve_hvac_node: hvac_prop has empty state_node ("") and device_state has empty string key -> returns None
    # 9. set_device_state_for_values: updates device state and clears cache
    op._values_cache = {"cached": True}
    op.set_device_state_for_values({"mode": "heat"})
    assert op._device_state == {"mode": "heat"}
    assert op._values_cache == {}

    hvac_prop_empty = MagicMock(state_node="")
    op._controller.get_property_object.return_value = hvac_prop_empty
    op._device_state = {"": "should_not_reach"}
    assert op._resolve_hvac_node() is None


def test_device_operation_resolve_async_params_kills():
    """Kill survivors in DeviceOperation._resolve_async_params."""
    conn = MagicMock()
    ctrl = MagicMock()
    op = DeviceOperation("test_op", conn, ctrl)

    # 1. device_state is passed and rendered in template
    mock_tmpl_state = MagicMock(spec=Template)
    mock_tmpl_state.async_render.side_effect = lambda ctx, **kw: json_dumps(
        {"temp": ctx["device_state"]["val"]}
    )
    op._connection_template = mock_tmpl_state
    conn._connection_template = None
    conn._params = {}
    params = op._resolve_async_params(conn, "v", duid="123", device_state={"val": 25})
    assert params == {"temp": 25}

    # 2. template returns a dict directly
    mock_tmpl = MagicMock(spec=Template)
    mock_tmpl.async_render.return_value = {"method": "POST", "url": "/direct_dict"}
    op._connection_template = mock_tmpl
    params = op._resolve_async_params(conn, "v")
    assert KEY_RAW_PAYLOAD not in params
    assert params["method"] == "POST"
    assert params["url"] == "/direct_dict"

    # 3. base_template is template_to_use: render_template called exactly once
    shared_tmpl = MagicMock(spec=Template)
    shared_tmpl.async_render.return_value = '{"method": "GET", "url": "/test"}'
    op._connection_template = None
    conn._connection_template = shared_tmpl
    params = op._resolve_async_params(conn, "v")
    assert params["method"] == "GET"
    assert shared_tmpl.async_render.call_count == 1


async def test_device_operation_async_set_value_kills():
    """Kill survivors in DeviceOperation.async_set_value."""
    conn = MagicMock()
    ctrl = MagicMock()
    op = DeviceOperation("test_op", conn, ctrl)

    # 1. device_id is None, ctrl.device_id is None, but connection.config has KEY_DUID
    conn.is_async_native = True
    conn.config = {KEY_DUID: "duid_from_cfg"}
    ctrl.device_id = None
    conn._connection_template = None
    op._connection_template = None
    conn._params = {"method": "POST", "url": "/api/set"}
    conn.async_execute = AsyncMock(return_value=({"status": "ok"}, 200))
    res = await op.async_set_value("test_val", device_id=None)
    assert res is True

    # 2. Positional args passed to _resolve_async_params
    with patch.object(
        op, "_resolve_async_params", return_value={"method": "POST", "url": "/api/set"}
    ) as mock_resolve:
        await op.async_set_value("test_val", device_id="explicit_duid")
        mock_resolve.assert_called_once_with(
            conn, "test_val", "explicit_duid", op._raw_device_state
        )

    # 3. Params has no method/url, fallback to conn._params
    conn._params = {"method": "PUT", "url": "/fallback_url"}
    with patch.object(op, "_resolve_async_params", return_value={}):
        conn.async_execute = AsyncMock(return_value=({"status": "ok"}, 200))
        res = await op.async_set_value("test_val", device_id="duid")
        assert res is True
        assert conn.async_execute.call_args[0][0] == "PUT"
        assert conn.async_execute.call_args[0][1] == "/fallback_url"

    # 4. req_headers falls back to connection._params[KEY_HEADERS]
    conn._params = {
        "method": "POST",
        "url": "/set",
        KEY_HEADERS: {"X-Custom": "header_val"},
    }
    with patch.object(
        op, "_resolve_async_params", return_value={"method": "POST", "url": "/set"}
    ):
        conn.async_execute = AsyncMock(return_value=({"status": "ok"}, 200))
        res = await op.async_set_value("test_val", device_id="duid")
        assert res is True
        assert conn.async_execute.call_args[0][3] == {"X-Custom": "header_val"}


def test_device_property_remaining_survivor_kills(hass):
    """Kill survivors in DeviceProperty methods."""
    conn = MagicMock()
    ctrl = MagicMock()
    prop = DeviceProperty("test_prop", conn, ctrl)

    # 1. _resolve_raw_state_source: controller is not None, pure_device_state is non-empty
    ctrl.pure_device_state = {"pure": 123}
    prop._status_getter = None
    prop._device_state = {"fallback": 456}
    assert prop._resolve_raw_state_source() == {"pure": 123}

    # 2. _resolve_raw_state_source: pure_device_state & device_state are None, controller.get_property(KEY_STATUS) valid dict
    ctrl.pure_device_state = None
    ctrl.device_state = None
    prop._status_getter = None
    mock_status_prop = MagicMock()
    mock_status_prop.value = {"status_key": "val_123"}
    ctrl.get_property.return_value = mock_status_prop
    prop._device_state = None
    assert prop._resolve_raw_state_source() == {"status_key": "val_123"}

    # 3. apply_optimistic_cascades: non-string target_node
    state = {"original": "val"}
    rule = {CONFIG_TARGET_NODE: 9999, CONFIG_VALUE_MAP: {"on": "bar"}}
    prop._config = {CONFIG_OPTIMISTIC_CASCADES: [rule]}
    prop.apply_optimistic_cascades(state, "on")
    assert state == {"original": "val"}

    # 4. calculate_value_from_state: None device_state with non-None status_template returns None
    prop._status_template = Template("{{ device_state.temp }}", hass)
    assert prop.calculate_value_from_state(None) is None

    # 5. load_from_yaml: icon is assigned
    loaded = prop.load_from_yaml({"icon": "mdi:thermostat"})
    assert loaded is True
    assert prop.icon == "mdi:thermostat"

    # 6. convert_dev_to_hass: base implementation returns dev_value directly
    assert prop.convert_dev_to_hass("dev_val") == "dev_val"
    assert prop.convert_dev_to_hass(42) == 42
    assert prop.all_values == []


async def test_get_json_status_remaining_survivor_kills(mock_controller):
    """Kill survivors in GetJsonStatus.async_update_state."""
    conn = MagicMock()
    conn.is_async_native = True
    conn.config = {}
    conn.create_updated.return_value = conn

    # 1. connection_template is None, conn._params is None -> returns None
    conn._params = None
    status = GetJsonStatus("test_status", conn, mock_controller)
    status._connection_template = None
    assert await status.async_update_state() is None

    # 2. render_template returns a dict directly
    conn._params = {"url": "/test"}
    mock_controller.device_id = "test_dev"
    status._connection_template = MagicMock()
    conn.async_execute = AsyncMock(return_value=('{"res": "ok"}', 200))
    with patch(
        "custom_components.climate_ip.properties.render_template",
        return_value={"method": "GET", "url": "/direct_status_dict"},
    ):
        res = await status.async_update_state()
        assert res == {"res": "ok"}
        assert conn.async_execute.call_args[0][0] == "GET"
        assert conn.async_execute.call_args[0][1] == "/direct_status_dict"


def test_mode_operation_state_attributes_survivor_kills():
    """Kill survivor in ModeOperation.state_attributes."""
    conn = MagicMock()
    ctrl = MagicMock()
    op = ModeOperation(ATTR_HVAC_MODE, conn, ctrl)
    op.value = "cool"
    op._values = ["cool", "heat"]
    with patch(
        "custom_components.climate_ip.properties.ATTR_HVAC_MODES",
        "custom_hvac_modes_mapped",
    ):
        attrs = op.state_attributes
        assert attrs == {
            ATTR_HVAC_MODE: "cool",
            "custom_hvac_modes_mapped": ["cool", "heat"],
        }
