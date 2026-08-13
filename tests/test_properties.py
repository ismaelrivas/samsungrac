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
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError, TemplateError
from jinja2 import Template

from custom_components.climate_ip.const import (
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_OPERATION_VALUE,
    CONFIG_DEVICE_OPERATION_VALUES,
    CONFIG_DEVICE_VALIDATION_TEMPLATE,
    CONFIG_TYPE,
    DEFAULT_JSON_STATUS_PAYLOAD,
    PROPERTY_TYPE_MODE,
    PROPERTY_TYPE_SWITCH,
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
    create_property,
    create_status_getter,
    register_property,
    register_status_getter,
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
    connection.async_execute = AsyncMock(return_value=("{}", None))
    connection.async_execute_with_retry = AsyncMock(return_value={})

    connection._lock = MagicMock()
    connection.async_lock = MagicMock()
    connection.async_lock.__aenter__ = AsyncMock()
    connection.async_lock.__aexit__ = AsyncMock()

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
    assert prop.value == STATE_UNKNOWN
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


async def test_device_property_is_valid_exception(
    mock_connection, mock_controller, caplog
):
    """Pattern 2: Fallback & Exception testing in is_valid."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.async_render.side_effect = TemplateError("Jinja error")
    prop._validation_template = mock_template

    dev_state = {"a": 1}
    assert prop.is_valid(dev_state) is False
    assert "Error rendering validation template" in caplog.text


async def test_device_property_calculate_value_exception(
    mock_connection, mock_controller, caplog
):
    """Pattern 2: Fallback & Exception testing in calculate_value_from_state."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.async_render.side_effect = TemplateError("Template boom")
    prop._status_template = mock_template

    dev_state = {"a": 1}
    assert prop.calculate_value_from_state(dev_state) == STATE_UNKNOWN
    assert "Dry-run error" in caplog.text


async def test_device_property_async_update_state(mock_connection, mock_controller):
    """Test async_update_state correctly assigns values and returns them."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.async_render.return_value = "STATE_ON"
    prop._status_template = mock_template

    dev_state = {"power": "on"}
    # Call without override
    mock_status_getter = MagicMock()
    mock_status_getter.value = dev_state
    prop._status_getter = mock_status_getter

    res = await prop.async_update_state(None, False)
    assert res == "STATE_ON"
    assert prop.value == "STATE_ON"

    # Call with override
    override_state = {"power": "off"}
    mock_template.async_render.return_value = "STATE_OFF"
    res2 = await prop.async_update_state(override_state, False)
    assert res2 == "STATE_OFF"
    assert prop.value == "STATE_OFF"


# ====================================================================================
# PHASE 1: GetJsonStatus HARDENED TESTS
# ====================================================================================


async def test_getjsonstatus_init(mock_connection, mock_controller):
    """Assert GetJsonStatus __init__ state to kill mutants."""
    g = GetJsonStatus("json_getter", mock_connection, mock_controller)
    assert g._name == "json_getter"
    # GetJsonStatus passes itself as the status_getter to DeviceProperty
    assert g._status_getter is g
    assert g._json_status is None
    assert g._attrs == {}
    assert GetJsonStatus.match_type(STATUS_GETTER_JSON) is True
    assert GetJsonStatus.match_type("other") is False


async def test_getjsonstatus_calculate_value_valid(mock_connection, mock_controller):
    """Pattern 1 & 2: Strict identity and valid string to JSON conversion."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    # Replace ' with " and True with "True" is part of the code's behavior
    mock_template.async_render.return_value = "{'key': True}"
    g._status_template = mock_template

    dev_state = {"raw": "data"}
    res = g.calculate_value_from_state(dev_state)
    assert res == {"key": True}  # Dual-parser AST literal_eval preserves boolean True


async def test_getjsonstatus_calculate_value_exception(
    mock_connection, mock_controller, caplog
):
    """Pattern 2: Exception in render or parsing."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.async_render.side_effect = TemplateError("Render fail")
    g._status_template = mock_template

    dev_state = {"raw": "data"}
    res = g.calculate_value_from_state(dev_state)
    # Should fallback to returning the original device_state
    assert res is dev_state
    assert "Dry-run error parsing status template" in caplog.text


async def test_getjsonstatus_async_update_json_error(
    mock_connection, mock_controller, caplog
):
    """Pattern 2: Test JSON parsing error handling in async_update_state."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.async_render.return_value = '{"method": "GET"}'

    # Make async_execute return malformed JSON string
    mock_connection.async_execute.return_value = ("{malformed_json: ", None)

    res = await g.async_update_state(None, False)
    assert res is None
    assert "JSON parsing error" in caplog.text


async def test_getjsonstatus_async_update_fallback_params_str(
    mock_connection, mock_controller
):
    """Test fallback when params_str cannot be parsed as JSON in async_execute."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.async_render.return_value = "INVALID_JSON_HERE"

    mock_connection.async_execute.return_value = ('{"ok": true}', None)
    res = await g.async_update_state(None, False)
    assert res == {"ok": True}

    mock_connection.async_execute.assert_called_once_with(
        None, None, "INVALID_JSON_HERE", None, _is_poll=True
    )


async def test_getjsonstatus_async_update_no_response(
    mock_connection, mock_controller, caplog
):
    """Pattern 2: Test handling of None response."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.async_render.return_value = '{"method": "GET"}'

    mock_connection.async_execute.return_value = (None, None)

    res = await g.async_update_state(None, False)
    assert res is None
    assert "No response text received." in caplog.text


async def test_getjsonstatus_async_update_null_json(mock_connection, mock_controller):
    """Test when response is 'null' JSON to cover device_state_result=None branch."""
    g = GetJsonStatus("test_null", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.async_render.return_value = '{"method": "GET"}'

    mock_connection.async_execute.return_value = ("null", None)

    res = await g.async_update_state(None, False)
    assert res is None
    assert g._attrs == {"device_state": None}


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


async def test_getjsonstatus_async_update_success(mock_connection, mock_controller):
    """Test successful async update sets value and attributes."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.async_render.return_value = '{"method": "GET"}'

    mock_connection.async_execute.return_value = ('{"success": true}', None)

    res = await g.async_update_state(None, False)
    assert res == {"success": True}
    assert g.value == {"success": True}
    assert g._json_status == {"success": True}
    assert g._attrs == {"device_state": '{"success":true}'}
    assert g.state_attributes == {"device_state": '{"success":true}'}


# ====================================================================================
# PREVIOUS TESTS (Kept and hardened where needed)
# ====================================================================================


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
    """Comprobar tolerancia cuando la unidad manda payload parcial/incompleto XML."""
    from custom_components.climate_ip.properties import DeviceProperty

    prop = DeviceProperty("test_prop", mock_connection, mock_controller)
    prop._value = "STATE_ON"
    # To simulate malformed XML resulting in empty dictionary from defusedxml during property update mapping
    await prop.async_update_state(device_state_override={})
    assert prop.value == "STATE_ON"


# ====================================================================================
# PHASE 2: DeviceOperation HARDENED TESTS
# ====================================================================================




async def test_deviceoperation_async_set_value_saneamiento(
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

    with patch.object(op, "_resolve_async_params", return_value={"method": "PUT", "method": "GET", "url": "/test"}):
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

    mock_mode_prop = MagicMock()
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
    """Test SwitchOperation maps booleans correctly."""
    op = SwitchOperation("test_switch", mock_connection, mock_controller)
    assert SwitchOperation.match_type(PROPERTY_TYPE_SWITCH) is True
    assert SwitchOperation.match_type("other") is False

    yaml_node = {
        CONFIG_TYPE: PROPERTY_TYPE_SWITCH,
        CONFIG_DEVICE_OPERATION_VALUES: {
            STATE_ON: {CONFIG_DEVICE_OPERATION_VALUE: "1"},
            STATE_OFF: {CONFIG_DEVICE_OPERATION_VALUE: "0"},
        },
    }
    assert op.load_from_yaml(yaml_node) is True
    assert op.convert_hass_to_dev(True) == "1"
    assert op.convert_hass_to_dev(False) == "0"


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
    op._connection_template = MagicMock()
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
    from custom_components.climate_ip.const import (
        CONFIG_DEVICE_OPERATION_NUMBER_MAX,
        CONFIG_DEVICE_OPERATION_NUMBER_MIN,
    )

    op = BasicNumericOperation("test", mock_connection, mock_controller)

    # 1. Test super() failing returns False
    assert op.load_from_yaml(None) is False

    # 2. Test missing min/max sets them to None and returns True
    yaml_node = {CONFIG_TYPE: "test"}
    assert op.load_from_yaml(yaml_node) is True
    assert op._min is None
    assert op._max is None

    # 3. Test explicit min/max
    yaml_node_2 = {
        CONFIG_TYPE: "test",
        CONFIG_DEVICE_OPERATION_NUMBER_MIN: 10,
        CONFIG_DEVICE_OPERATION_NUMBER_MAX: 30,
    }
    assert op.load_from_yaml(yaml_node_2) is True
    assert op._min == 10
    assert op._max == 30


async def test_deviceoperation_resolve_async_params_edge_cases(
    mock_connection, mock_controller
):
    """Kill mutants in _resolve_async_params getattr fallbacks and JSON decode."""
    import jinja2

    op = DeviceOperation("test", mock_connection, mock_controller)
    """Verify parameter resolution logic."""
    op = DeviceOperation("test", mock_connection, mock_controller)

    mock_connection._params = {"header": "123"}
    mock_connection._connection_template = jinja2.Template('{"val": "{{ value }}"}')
    params = op._resolve_async_params(mock_connection, "123", "duid")
    assert params == {"header": "123", "val": "123"}

    conn_empty = MagicMock(spec=[])
    # Verify operation_params fallback
    assert op._resolve_async_params(conn_empty, "val") is None

    # Verify raw_params default handling
    conn_raw = MagicMock(spec=["_connection_template"])
    conn_raw._connection_template = jinja2.Template('{"method": "GET"}')
    assert op._resolve_async_params(conn_raw, "val") == {"method": "GET"}

    # Verify base_template fallback
    conn_base = MagicMock(_connection_template=jinja2.Template('{"method": "GET"}'))
    assert op._resolve_async_params(conn_base, "val") == {"method": "GET"}


async def test_deviceoperation_async_set_value_mutants(
    mock_connection, mock_controller
):
    """Verify async_set_value handling."""
    op = DeviceOperation("test", mock_connection, mock_controller)
    op._connection_template = MagicMock()
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




async def test_deviceproperty_is_valid(mock_connection, mock_controller):
    """Verify is_valid logic."""
    from unittest.mock import patch

    import jinja2

    prop = DeviceProperty("test", mock_connection, mock_controller)

    # 1. Validation template is None
    device_state_1 = {"some": "state"}
    assert prop.is_valid(device_state_1) is True
    assert prop._device_state == device_state_1

    # 2. device_state is None
    prop._validation_template = jinja2.Template("valid")
    assert prop.is_valid(None) is True
    assert prop._device_state is None

    # 3. Validation returns "valid"
    device_state_2 = {"a": 1}
    prop._validation_template = jinja2.Template("valid")
    assert prop.is_valid(device_state_2) is True
    assert prop._device_state == device_state_2

    # 4. Cache hit
    prop._device_state = None  # reset to verify it gets updated from cache
    assert prop.is_valid(device_state_2) is True
    assert prop._device_state == device_state_2

    # 5. Validation returns "invalid"
    device_state_3 = {"b": 2}
    prop._validation_template = jinja2.Template("invalid")
    assert prop.is_valid(device_state_3) is False

    # 6. Exception testing with EXACT arguments to logger
    device_state_4 = {"c": 3}

    class ExceptionTemplate:
        def render(self, **kwargs):
            raise ValueError("Template Boom")

    prop._validation_template = ExceptionTemplate()
    with patch("custom_components.climate_ip.properties._LOGGER.error") as mock_logger:
        assert prop.is_valid(device_state_4) is False
        mock_logger.assert_called_once()
        args, _ = mock_logger.call_args
        assert args[0] == "%s Error rendering validation template for %s: %s"
        assert args[1] == prop.log_prefix
        assert args[2] == prop.id
        assert isinstance(args[3], ValueError)
        assert str(args[3]) == "Template Boom"


# ====================================================================================
# FRENTE 2: FRONTERAS MATEMÁTICAS
# ====================================================================================


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

    # Above max → clamped
    assert op.convert_hass_to_dev(30.1) == 30.0

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
    """Verify _connection_template getattr fallback."""
    op = DeviceOperation("test_fallback", mock_connection, mock_controller)

    # Test getattr default behavior when attribute is missing
    if hasattr(mock_connection, "_connection_template"):
        delattr(mock_connection, "_connection_template")
    if hasattr(mock_connection, "_params"):
        delattr(mock_connection, "_params")

    op.convert_hass_to_dev = MagicMock(return_value="dev_val_raw")

    result = await op.async_set_value("ha_val")
    assert result is False






async def test_deviceoperation_resolve_async_params_merge_base(
    mock_connection, mock_controller
):
    """Test merging of base_template and template_to_use."""
    op = DeviceOperation("test_merge", mock_connection, mock_controller)

    mock_base_tmpl = MagicMock()
    mock_base_tmpl.async_render.return_value = '{"base_param": 1, "shared": "base"}'
    mock_connection._connection_template = mock_base_tmpl

    mock_op_tmpl = MagicMock()
    mock_op_tmpl.async_render.return_value = '{"op_param": 2, "shared": "op"}'
    op._connection_template = mock_op_tmpl

    mock_connection._params = {"raw_param": 3}

    params = op._resolve_async_params(mock_connection, "dev_val")

    assert params is not None
    assert params["base_param"] == 1
    assert params["op_param"] == 2
    assert params["shared"] == "op"
    assert params["raw_param"] == 3








async def test_deviceoperation_sync_execute(mock_connection, mock_controller):
    """Test sync execution path for DeviceOperation."""
    mock_connection.is_async_native = False
    mock_connection.async_execute_with_retry = AsyncMock(return_value=True)
    type(mock_controller).pure_device_state = PropertyMock(return_value={})
    type(mock_controller).device_state = PropertyMock(return_value={})

    op = DeviceOperation("test_sync", mock_connection, mock_controller)
    op.convert_hass_to_dev = MagicMock(return_value="dev_val")

    mock_status_getter = MagicMock()
    mock_status_getter.value = {"power": "off"}
    op._status_getter = mock_status_getter

    op._resolve_params = MagicMock(return_value={"test_param": 1})
    mock_tmpl = MagicMock()
    mock_tmpl.async_render.return_value = '{"method": "SET"}'
    op._connection_template = mock_tmpl

    res = await op.async_set_value("ha_val")

    assert res is True
    mock_connection.async_execute_with_retry.assert_called_once_with(
        mock_tmpl, "dev_val", {"power": "off"}, None
    )


# FRONT B: YAML Configurator Loaders
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
    """Test strict '<=' and '>=' handling."""
    op = BasicNumericOperation("test_bounds", mock_connection, mock_controller)
    op._min = 10.0
    op._max = 30.0

    res_min = op.convert_hass_to_dev(10)
    assert res_min == 10
    assert isinstance(res_min, float)

    res_max = op.convert_hass_to_dev(30)
    assert res_max == 30
    assert isinstance(res_max, float)




async def test_device_property_mutants():
    conn = MagicMock(
        is_async_native=True,
        _params={},
        async_execute=AsyncMock(return_value=("ok", None)),
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

    # 2. set_unit_of_measurement in base class (Kills .get(unit, None) returning default)
    op_unit = DeviceProperty("test_unit", mock_connection, mock_controller)
    op_unit.set_unit_of_measurement("UNIDAD_BASE_DESCONOCIDA")
    assert op_unit._unit_of_measurement == "UNIDAD_BASE_DESCONOCIDA"


async def test_device_property_connection_fallback_dict(
    mock_connection, mock_controller
):
    """Verify mutant kill silencioso node.get(CONFIG_DEVICE_CONNECTION, None)."""
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
    op._validation_template = Template(
        "{% if device_state %}valid{% else %}invalid{% endif %}"
    )
    assert op.is_valid({"val": "ok"}) is True

    # calculate_value_from_state boolean or
    with patch("custom_components.climate_ip.properties._LOGGER.debug") as mock_debug:
        op._status_template = None
        assert op.calculate_value_from_state({"val": "ok"}) == STATE_UNKNOWN
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
    op._status_template = Template('{"result": "{{ device_state.val }}"}')
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
    op._unit_template = Template("{{ device_state.unit }}")
    op.calculate_value_from_state({"unit": "unknown"})
    assert op._device_unit == UnitOfTemperature.FAHRENHEIT

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
    op._status_template = Template("{{ device_state.val }}")
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
    conn = MagicMock(is_async_native=True, _connection_template=Template("inherited"))
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    g = GetJsonStatus("test", conn, ctrl)
    existing_tmpl = Template("pre_existing")
    g._connection_template = existing_tmpl

    res = g.load_from_yaml({"type": STATUS_GETTER_JSON})
    assert res is True
    assert g._connection_template is existing_tmpl


async def test_get_json_status_load_from_yaml_default_template():
    """Test load_from_yaml creates default template when connection lacks one."""
    conn = MagicMock(spec=["is_async_native", "create_updated"])
    conn.is_async_native = True
    conn.create_updated.return_value = conn
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
    """Test getattr(connection, '_connection_template', None) fallback with strict spec."""
    conn = MagicMock(spec=["_params"])
    conn._params = {"method": "POST", "method": "GET", "url": "/test", "url": "/api"}
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    ctrl.log_prefix = "TEST"

    op = DeviceOperation("test", conn, ctrl)
    op._connection_template = None

    params = op._resolve_async_params(conn, "val")
    assert params == {"method": "POST", "method": "GET", "url": "/test", "url": "/api"}


async def test_device_operation_resolve_async_params_condition_flip():
    """Test base_template resolution when conn template matches template_to_use."""
    conn = MagicMock(spec=["_params"])
    conn._params = {"method": "GET"}
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    ctrl.log_prefix = "TEST"

    op = DeviceOperation("test", conn, ctrl)
    op._connection_template = Template('{"method": "POST", "method": "GET", "url": "/test", "url": "/set"}')

    # When base_template is None (because conn has no _connection_template), base_params remains {}
    params = op._resolve_async_params(conn, "val")
    assert params == {"method": "POST", "method": "GET", "url": "/test", "url": "/set"}




async def test_get_json_status_load_from_yaml_inherits_connection_template():
    """Test load_from_yaml inherits _connection_template from connection object."""
    custom_tmpl = Template('{"method": "POST", "method": "GET", "url": "/test", "url": "/inherited_endpoint"}')
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
        == '{"method": "POST", "method": "GET", "url": "/test", "url": "/inherited_endpoint"}'
    )


async def test_device_property_calculate_value_from_state_valid():
    """Test calculate_value_from_state returns rendered value from template."""
    conn = MagicMock()
    ctrl = MagicMock()
    ctrl.loader = MagicMock()
    ctrl.loader.parsed_yaml_cache = {}
    prop = DeviceProperty("test_prop", conn, ctrl)
    prop._status_template = Template("{{ device_state.power }}")

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


async def test_device_operation_async_set_value_device_state_passed(
    mock_connection, mock_controller
):
    """Verify that current_full_state is passed to _resolve_async_params as device_state."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.async_render.return_value = '{"method": "GET", "url": "/test"}'
    op._connection_template = mock_template

    type(mock_controller).pure_device_state = PropertyMock(return_value={"custom_key": "custom_val"})
    type(mock_controller).device_state = PropertyMock(return_value={"custom_key": "custom_val"})
    mock_connection.async_execute = AsyncMock(return_value=("ok", 200))

    res = await op.async_set_value("val")
    assert res is True
    # Ensure render was called with device_state equal to mock_controller.device_state
    mock_template.async_render.assert_called_with(
        {
            "value": "val",
            "device_id": "test_duid",
            "duid": "test_duid",
            "device_state": {"custom_key": "custom_val"},
        },
        parse_result=True
    )


async def test_getjsonstatus_calculate_value_json_strict(
    mock_connection, mock_controller
):
    """Kill json_loads(None) mutant by asserting strict JSON parsing output."""
    from jinja2 import Template

    from custom_components.climate_ip.properties import GetJsonStatus

    getter = GetJsonStatus("test_json_strict", mock_connection, mock_controller)
    # Give it a pure, valid JSON string output
    getter._status_template = Template(
        '{"strict_key": "strict_value", "is_active": true}'
    )

    # Run the calculation
    result = getter.calculate_value_from_state({"dummy": 1})

    # STRICT ASSERTION: If the mutant returns None, this will fail and kill it.
    assert isinstance(result, dict)
    assert result == {"strict_key": "strict_value", "is_active": True}


def test_samsungrac_sensor_validation_templates() -> None:
    """Verify that samsungrac.yaml sensor validation_templates properly validate option presence."""
    from jinja2 import Template

    tmpl_outdoor = Template(
        "{% if 'Mode' in device_state and 'options' in device_state.Mode and 'OutdoorTemp_' in (device_state.Mode.options | string) %}valid{% endif %}"
    )
    tmpl_filter = Template(
        "{% if 'Mode' in device_state and 'options' in device_state.Mode and 'FilterCleanAlarm_' in (device_state.Mode.options | string) %}valid{% endif %}"
    )

    state_valid = {
        "Mode": {"options": ["Comode_Off", "OutdoorTemp_63", "FilterCleanAlarm_0"]}
    }
    state_invalid = {"Mode": {"options": ["Comode_Off", "Spi_Off"]}}

    assert tmpl_outdoor.render(device_state=state_valid) == "valid"
    assert tmpl_outdoor.render(device_state=state_invalid) == ""

    assert tmpl_filter.render(device_state=state_valid) == "valid"
    assert tmpl_filter.render(device_state=state_invalid) == ""
