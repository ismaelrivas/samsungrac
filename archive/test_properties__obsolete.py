# pylint: disable=all
# flake8: noqa
"""Archived test functions from properties test suite.

Quarantined 25 completely shadowed tests with zero unique mutant kills
and zero unique line coverage to accelerate mutmut and pytest execution.
Their functional contracts and historical test scenarios are preserved here.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

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
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.template import Template
import pytest

from custom_components.climate_ip.const import *
from custom_components.climate_ip.exceptions import AuthError, CannotConnect
from custom_components.climate_ip.properties import *


def test_device_property_init(mock_connection, mock_controller):
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


def test_typed_operations_strict_init(mock_connection, mock_controller):
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


def test_set_device_state_for_values(mock_connection, mock_controller):
    """Kill mutants in set_device_state_for_values."""
    op = BasicDeviceOperation("test", mock_connection, mock_controller)
    op.set_device_state_for_values({"test_state": 1})
    assert op._device_state == {"test_state": 1}


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


def test_basic_numeric_operation_match_value(mock_connection, mock_controller):
    """Test BasicNumericOperation match_value."""
    op = BasicNumericOperation("test", mock_connection, mock_controller)
    # default convert_hass_to_dev just returns the float if no map
    assert op.match_value(10.0) is True
    # Testing ValueError path
    assert op.match_value("invalid_str") is False


def test_numeric_boundaries_exact(mock_connection, mock_controller):
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


def test_basic_device_operation_mutants():
    conn = MagicMock()
    conn.create_updated.return_value = conn
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}

    op = BasicDeviceOperation("test_bdo", conn, ctrl)
    op._values_ha_to_dev_map = {"ha_val": {"connection": {"type": "new"}}}
    assert op.load_from_yaml({"type": "test", "values": {"ha_val": {}}}) is True


def test_mode_operation_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = ModeOperation("test_mode", conn, ctrl)

    assert op.load_from_yaml(None) is False

    assert op.id == "test_mode_mode"

    op2 = ModeOperation(ATTR_HVAC_MODE, conn, ctrl)
    assert op2.id == ATTR_HVAC_MODE


def test_switch_operation_mutants():
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


def test_getjsonstatus_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = GetJsonStatus("test_json", conn, ctrl)
    assert op.load_from_yaml({"type": "json"}) is True
    op.calculate_value_from_state(None)


def test_device_property_connection_fallback_dict(mock_connection, mock_controller):
    """Verify mutant kill silencioso node.get(CONFIG_DEVICE_CONNECTION)."""
    from custom_components.climate_ip.properties import DeviceProperty

    op = DeviceProperty("test_conn", mock_connection, mock_controller)

    # Inject YAML missing CONFIG_DEVICE_CONNECTION key
    op.load_from_yaml({"name": "Test"})

    # Strictly assert factory received empty dictionary and not None
    mock_connection.create_updated.assert_called_with({})


def test_basicnumericoperation_remaining_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    BasicNumericOperation("test_bno", conn, ctrl)


def test_switchoperation_remaining_mutants():
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    op = SwitchOperation("test_switch", conn, ctrl)
    assert op.load_from_yaml({"type": "switch"}) is False


def test_create_property_and_status_getter_none_returns():
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


def test_get_json_status_load_from_yaml_existing_template():
    """Test load_from_yaml preserves existing _connection_template."""
    conn = MagicMock(
        is_async_native=True,
        _connection_template=Template(hass=MagicMock(data={}), template="inherited"),
    )
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    g = GetJsonStatus("test", conn, ctrl)
    existing_tmpl = Template(hass=MagicMock(data={}), template="pre_existing")
    g._connection_template = existing_tmpl

    res = g.load_from_yaml({"type": STATUS_GETTER_JSON})
    assert res is True
    assert g._connection_template is existing_tmpl


def test_device_property_calculate_value_from_state_valid():
    """Test calculate_value_from_state returns rendered value from template."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    prop = DeviceProperty("test_prop", conn, ctrl)
    prop._status_template = Template(
        hass=MagicMock(data={}), template="{{ device_state.power }}"
    )

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


def test_getjsonstatus_calculate_value_json_strict(mock_connection, mock_controller):
    """Kill json_loads(None) and render_template parameter mutants."""
    getter = GetJsonStatus("test_json_strict", mock_connection, mock_controller)
    # Give it a template referencing device_state
    getter._status_template = Template(
        hass=MagicMock(data={}),
        template='{"status": "{{ device_state.power }}", "code": {{ device_state.code }}}',
    )

    result = getter.calculate_value_from_state({"power": "active", "code": 100})

    assert isinstance(result, dict)
    assert result == {"status": "active", "code": 100}

    # When status_template is None -> returns device_state directly
    getter._status_template = None
    assert getter.calculate_value_from_state({"raw": 1}) == {"raw": 1}


def test_deviceoperation_resolve_async_params_non_dict_base(
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
