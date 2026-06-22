# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for DeviceProperty, GetJsonStatus, ModeOperation and TemperatureOperation."""

import logging
from unittest.mock import MagicMock, patch, AsyncMock
import json

import pytest

from custom_components.climate_ip.const import (
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_OPERATION_VALUE,
    CONFIG_DEVICE_OPERATION_VALUES,
    CONFIG_DEVICE_VALIDATION_TEMPLATE,
    CONFIG_TYPE,
    STATUS_GETTER_JSON,
    PROPERTY_TYPE_SWITCH,
)
from custom_components.climate_ip.properties import (
    DeviceProperty,
    GetJsonStatus,
    ModeOperation,
    TemperatureOperation,
    DeviceOperation,
    BasicDeviceOperation,
    BasicNumericOperation,
    SwitchOperation,
    create_property,
    create_status_getter,
    register_property,
    register_status_getter,
    CLIMATE_IP_PROPERTIES,
    CLIMATE_IP_STATUS_GETTER,
)
from custom_components.climate_ip.exceptions import CannotConnect, AuthError
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import UnitOfTemperature, STATE_UNKNOWN, STATE_ON, STATE_OFF
from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
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
    controller.device_id = "test_duid"
    return controller


@pytest.fixture
def mock_connection():
    """Create a mock connection."""
    connection = MagicMock()
    connection.create_updated.return_value = connection
    connection.is_async_native = True
    
    # Ensure async_execute is awaitable
    connection.async_execute = AsyncMock(return_value=("{}", None))
    
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
    assert prop._is_valid_cache == (None, None)
    assert prop._friendly_name is None
    assert prop._device_class is None
    assert prop._unit_of_measurement is None
    assert prop._state_class is None
    assert prop._entity_category is None
    assert prop._feature_flag is None
    assert prop.log_prefix == "[TestController]"
    assert prop.all_values == []
    assert prop.values == []

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

async def test_device_property_load_state_class_exception(mock_connection, mock_controller):
    """Pattern 2: Exception when loading state_class."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    yaml_node = {"state_class": "invalid_class"}
    with pytest.raises(ValueError, match="Invalid state_class 'invalid_class' in YAML"):
         prop.load_from_yaml(yaml_node)

async def test_device_property_is_valid_cache(mock_connection, mock_controller):
    """Pattern 3: Internal Cache Freezing for is_valid."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.render.return_value = "VaLid" # case insensitive match
    prop._validation_template = mock_template
    
    dev_state = {"a": 1}
    # Call 1
    assert prop.is_valid(dev_state) is True
    # Verify cache
    state_id = id(dev_state)
    assert prop._is_valid_cache == (state_id, True)
    
    # Call 2 with same dict
    mock_template.render.reset_mock()
    assert prop.is_valid(dev_state) is True
    mock_template.render.assert_not_called() # Cache hit

async def test_device_property_is_valid_exception(mock_connection, mock_controller, caplog):
    """Pattern 2: Fallback & Exception testing in is_valid."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.render.side_effect = Exception("Jinja error")
    prop._validation_template = mock_template
    
    dev_state = {"a": 1}
    assert prop.is_valid(dev_state) is False
    assert "Error rendering validation template" in caplog.text

async def test_device_property_calculate_value_exception(mock_connection, mock_controller, caplog):
    """Pattern 2: Fallback & Exception testing in calculate_value_from_state."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.render.side_effect = Exception("Template boom")
    prop._status_template = mock_template
    
    dev_state = {"a": 1}
    assert prop.calculate_value_from_state(dev_state) == STATE_UNKNOWN
    assert "Dry-run error" in caplog.text

async def test_device_property_async_update_state(mock_connection, mock_controller):
    """Test async_update_state correctly assigns values and returns them."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.render.return_value = "STATE_ON"
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
    mock_template.render.return_value = "STATE_OFF"
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
    mock_template.render.return_value = "{'key': True}"
    g._status_template = mock_template
    
    dev_state = {"raw": "data"}
    res = g.calculate_value_from_state(dev_state)
    assert res == {"key": "True"} # Strict match

async def test_getjsonstatus_calculate_value_exception(mock_connection, mock_controller, caplog):
    """Pattern 2: Exception in render or parsing."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.render.side_effect = Exception("Render fail")
    g._status_template = mock_template
    
    dev_state = {"raw": "data"}
    res = g.calculate_value_from_state(dev_state)
    # Should fallback to returning the original device_state
    assert res is dev_state
    assert "Dry-run error parsing status template" in caplog.text

async def test_getjsonstatus_async_update_json_error(mock_connection, mock_controller, caplog):
    """Pattern 2: Test JSON parsing error handling in async_update_state."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.render.return_value = '{"method": "GET"}'
    
    # Make async_execute return malformed JSON string
    mock_connection.async_execute.return_value = ("{malformed_json: ", None)
    
    res = await g.async_update_state(None, False)
    assert res is None
    assert "JSON parsing error" in caplog.text

async def test_getjsonstatus_async_update_fallback_params_str(mock_connection, mock_controller):
    """Test fallback when params_str cannot be parsed as JSON in async_execute."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.render.return_value = 'INVALID_JSON_HERE'
    
    mock_connection.async_execute.return_value = ('{"ok": true}', None)
    res = await g.async_update_state(None, False)
    assert res == {"ok": True}
    
    mock_connection.async_execute.assert_called_once_with(
        None,
        None,
        'INVALID_JSON_HERE',
        None,
        _is_poll=True
    )

async def test_getjsonstatus_async_update_no_response(mock_connection, mock_controller, caplog):
    """Pattern 2: Test handling of None response."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.render.return_value = '{"method": "GET"}'
    
    mock_connection.async_execute.return_value = (None, None)
    
    res = await g.async_update_state(None, False)
    assert res is None
    assert "No response text received." in caplog.text

async def test_getjsonstatus_async_update_null_json(mock_connection, mock_controller):
    """Test when response is 'null' JSON to cover device_state_result=None branch."""
    g = GetJsonStatus("test_null", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.render.return_value = '{"method": "GET"}'
    
    mock_connection.async_execute.return_value = ('null', None)
    
    res = await g.async_update_state(None, False)
    assert res is None
    assert g._attrs == {"device_state": None}
    
async def test_getjsonstatus_async_update_sync_success(mock_connection, mock_controller):
    """Test happy path for sync connection to kill break->return mutant."""
    g = GetJsonStatus("test_sync_success", mock_connection, mock_controller)
    mock_connection.is_async_native = False
    g._connection_template = MagicMock()
    g._connection_template.render.return_value = '{"method": "GET"}'
    
    async def _mock_add_job(*args, **kwargs):
        return {"ok": True}
        
    mock_controller.hass.async_add_executor_job = AsyncMock(side_effect=_mock_add_job)
    mock_connection.async_lock = AsyncMock()
    
    res = await g.async_update_state(None, False)
    assert res == {"ok": True}
    assert g.value == {"ok": True}

async def test_getjsonstatus_no_cfg_and_no_config(mock_connection, mock_controller):
    """Test when connection has neither _cfg nor config to kill AttributeError mutant."""
    del mock_connection._cfg
    del mock_connection.config
    mock_connection.is_async_native = True
    
    g = GetJsonStatus("test_no_cfg_config", mock_connection, mock_controller)
    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "GET"}'
    g._connection_template = mock_tmpl
    mock_connection.async_execute.return_value = ('{"ok": true}', None)
    
    await g.async_update_state(None, False)
    assert True # Should not raise AttributeError

async def test_getjsonstatus_fallback_config(mock_connection, mock_controller):
    """Test GetJsonStatus async_update_state fallback to .config when ._cfg is missing."""
    del mock_controller.device_id # Kills getattr(..., "device_id", ) mutation
    del mock_connection._cfg
    
    class DummyCfg:
        duid = "fallback_duid"
        token = "fallback_token"
    
    mock_cfg = DummyCfg()
    mock_connection.config = mock_cfg
    mock_connection._params = {}
    mock_connection.is_async_native = True

    g = GetJsonStatus("test_fallback_config", mock_connection, mock_controller)
    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "GET"}'
    g._connection_template = mock_tmpl

    mock_connection.async_execute.return_value = ('{"ok": true}', None)
    res = await g.async_update_state(None, False)
    assert res == {"ok": True}
    
    # Assert payload autopsy
    rendered_dict = mock_tmpl.render.call_args[1]
    assert rendered_dict.get("duid") == "fallback_duid"
    assert rendered_dict.get("token") == "fallback_token"

async def test_getjsonstatus_async_update_sync_retry(mock_connection, mock_controller, caplog):
    """Pattern 2: Test 5 retries in sync connection and final CannotConnect."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = False
    
    class RetryNextAttempt(Exception):
        pass
    
    async def _mock_add_job(*args, **kwargs):
        raise RetryNextAttempt("Simulated timeout")
        
    mock_controller.hass.async_add_executor_job = AsyncMock(side_effect=_mock_add_job)
    
    # We must patch asyncio.sleep to not hang the test, but we also need connection.async_lock to be async context manager.
    mock_connection.async_lock = AsyncMock()
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(CannotConnect, match="Connection failed after 5 retries"):
            await g.async_update_state(None, False)
            
        assert mock_sleep.call_count == 4 # Attempt 1 to 4 trigger sleep, 5th throws CannotConnect

async def test_getjsonstatus_async_update_success(mock_connection, mock_controller):
    """Test successful async update sets value and attributes."""
    g = GetJsonStatus("test", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    g._connection_template = MagicMock()
    g._connection_template.render.return_value = '{"method": "GET"}'
    
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
    await prop.async_update_state(device_state_override={}, _debug=False)
    assert prop.value == "STATE_ON"


# ====================================================================================
# PHASE 2: DeviceOperation HARDENED TESTS
# ====================================================================================

async def test_deviceoperation_resolve_async_params_raw(mock_connection, mock_controller):
    """Test resolution with fallback and raw parsing."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_template = MagicMock()
    mock_template.render.return_value = "{malformed"
    op._connection_template = mock_template
    
    res = op._resolve_async_params(mock_connection, "val_str")
    assert res == {"_raw": "{malformed"}
    
    # Assert render context to kill dict key mutants
    mock_template.render.assert_called_once_with(value="val_str", device_id=None, duid=None)

async def test_deviceoperation_async_set_value_saneamiento(mock_connection, mock_controller, caplog):
    """Test front-end sanitization logic."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    
    with patch.object(op, 'convert_hass_to_dev', side_effect=ValueError("Invalid value")):
        res = await op.async_set_value("bad_value")
        assert res is False
        assert "Comando descartado" in caplog.text

async def test_deviceoperation_async_set_value_async_native_raw(mock_connection, mock_controller):
    """Test async native set value with raw payload."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    
    with patch.object(op, '_resolve_async_params', return_value={"_raw": "payload"}):
        res = await op.async_set_value("val")
        assert res is True
        mock_connection.async_execute.assert_called_once_with(None, None, "payload", None)

async def test_deviceoperation_async_set_value_async_native_json(mock_connection, mock_controller):
    """Test async native set value with JSON payload."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    
    with patch.object(op, '_resolve_async_params', return_value={"method": "PUT", "url": "/set", "json": {"k": "v"}}):
        mock_connection.async_execute.return_value = (True, None)
        res = await op.async_set_value("val")
        assert res is True
        mock_connection.async_execute.assert_called_once()
        args, kwargs = mock_connection.async_execute.call_args
        assert args[0] == "PUT"
        assert args[1] == "/set"
        assert args[2] == '{"k":"v"}'

async def test_deviceoperation_async_set_value_async_native_exceptions(mock_connection, mock_controller):
    """Test async native AuthError -> HomeAssistantError conversion."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = True
    
    with patch.object(op, '_resolve_async_params', return_value={"method": "PUT"}):
        mock_connection.async_execute.side_effect = AuthError("Token expired")
        with pytest.raises(HomeAssistantError, match="Connection error"):
            await op.async_set_value("val")

async def test_deviceoperation_async_set_value_sync_success(mock_connection, mock_controller):
    """Test sync execution wraps properly."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = False
    
    mock_controller.hass.async_add_executor_job = AsyncMock(return_value=True)
    res = await op.async_set_value("val")
    assert res is True
    mock_controller.hass.async_add_executor_job.assert_called_once()

async def test_deviceoperation_async_set_value_sync_retry(mock_connection, mock_controller, caplog):
    """Test sync RetryNextAttempt mechanism loops and finally raises CannotConnect."""
    op = DeviceOperation("test_op", mock_connection, mock_controller)
    mock_connection.is_async_native = False
    
    class RetryNextAttempt(Exception):
        pass
        
    async def _mock_job(*args, **kwargs):
        raise RetryNextAttempt("try again")
    
    mock_controller.hass.async_add_executor_job = AsyncMock(side_effect=_mock_job)
    
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(CannotConnect, match="Connection failed after 5 retries"):
            await op.async_set_value("val")
        assert mock_sleep.call_count == 4


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
                CONFIG_DEVICE_CONNECTION: {"type": "on_conn"}
            },
            "off": {
                CONFIG_DEVICE_OPERATION_VALUE: "0"
            }
        }
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
                CONFIG_DEVICE_VALIDATION_TEMPLATE: "{% if device_state.p == 1 %}valid{% endif %}"
            },
            "off": {
                CONFIG_DEVICE_OPERATION_VALUE: "0",
                CONFIG_DEVICE_VALIDATION_TEMPLATE: "valid"
            }
        }
    }
    
    op.load_from_yaml(yaml_node)
    
    mock_mode_prop = MagicMock()
    mock_mode_prop.__str__.return_value = "cool"
    mock_controller.get_property.return_value = mock_mode_prop
    
    op._device_state = {"p": 1}
    # Both are valid
    vals = op.values
    assert vals == ["on", "off"]
    assert op._values_cache["cool"] == ["on", "off"]
    
    # Change state to make 'on' invalid, but since we use the same mock mode "cool", it should use cache!
    op._device_state = {"p": 0}
    vals2 = op.values
    assert vals2 == ["on", "off"] # Cache hit
    
    # Change cache key to bypass cache
    mock_mode_prop.__str__.return_value = "heat"
    vals3 = op.values
    assert vals3 == ["off"] # Cache miss, recalculates, 'on' is invalid
    assert op._values_cache["heat"] == ["off"]

    # Kill fallback map mutants
    assert op.convert_hass_to_dev("unmapped_ha") == "unmapped_ha"
    assert op.convert_dev_to_hass("unmapped_dev") == "unmapped_dev"


# ====================================================================================
# PHASE 3: Typed Operations HARDENED TESTS
# ====================================================================================

async def test_typed_operations_strict_init(mock_connection, mock_controller):
    """Kill __init__ mutants for all typed operations."""
    # BasicNumericOperation
    op_num = BasicNumericOperation("test_num", mock_connection, mock_controller, "getter1")
    assert op_num._name == "test_num"
    assert op_num._connection == mock_connection
    assert op_num._controller == mock_controller
    assert op_num._status_getter == "getter1"
    assert op_num._min is None
    assert op_num._max is None
    assert op_num._value is None

    # TemperatureOperation
    op_temp = TemperatureOperation("test_temp", mock_connection, mock_controller, "getter2")
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
            STATE_OFF: {CONFIG_DEVICE_OPERATION_VALUE: "0"}
        }
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

    with patch.object(op, 'convert_hass_to_dev', return_value=23.5):
        assert op.match_value(23.5) is True
    
    with patch.object(op, 'convert_hass_to_dev', side_effect=ValueError):
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

async def test_deviceoperation_async_set_value_config_fallbacks(mock_connection, mock_controller):
    """Kill mutants in async_set_value related to cfg and duid fallback."""
    op = DeviceOperation("test", mock_connection, mock_controller)
    op._connection_template = MagicMock()
    op.convert_hass_to_dev = MagicMock(return_value="val")
    
    # 1. No device_id, No cfg, No config
    mock_controller.device_id = None
    del mock_connection._cfg
    del mock_connection.config
    
    mock_connection.is_async_native = False
    mock_connection.execute.return_value = {"success": True}
    
    async def _mock_add_job(*args, **kwargs):
        func = args[0]
        return func(*args[1:])
        
    mock_controller.hass.async_add_executor_job = AsyncMock(side_effect=_mock_add_job)
    
    await op.async_set_value("val")
    args, _ = mock_connection.execute.call_args
    assert args[3] is None  # device_id/duid is None
    
    # 2. No duid attribute on cfg
    mock_cfg = MagicMock(spec=[])
    mock_connection._cfg = mock_cfg
    await op.async_set_value("val")
    args, _ = mock_connection.execute.call_args
    assert args[3] is None

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
    prop = create_property("test_prop", node, mock_connection, mock_controller, "my_getter")
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

async def test_basicdeviceoperation_load_from_yaml_edge_cases(mock_connection, mock_controller):
    """Kill mutants related to load_from_yaml fallbacks, empty values, feature flags."""
    from homeassistant.components.climate import ClimateEntityFeature
    
    with patch.dict(
        "custom_components.climate_ip.properties.YAML_NAME_TO_HA_FEATURE",
        {"test_flag_op": ClimateEntityFeature.FAN_MODE},
        clear=True
    ):
        op = BasicDeviceOperation("test_flag_op", mock_connection, mock_controller)
        
        # 1. Test empty values dict returns False
        assert op.load_from_yaml({CONFIG_TYPE: "op", CONFIG_DEVICE_OPERATION_VALUES: {}}) is False
        
        # 1b. Test missing CONFIG_DEVICE_OPERATION_VALUES uses fallback {} and returns False
        assert op.load_from_yaml({CONFIG_TYPE: "op"}) is False
        
        # 4. Test missing CONFIG_DEVICE_CONNECTION in node uses whole node
        mock_connection.create_updated.reset_mock()
        yaml_node = {
            CONFIG_TYPE: "op",
            CONFIG_DEVICE_OPERATION_VALUES: {
                "on": {"some_other_key": "val"}
            }
        }
        assert op.load_from_yaml(yaml_node) is True
        
        # 2. Test feature flag assignment securely patched
        assert op._feature_flag is ClimateEntityFeature.FAN_MODE
        
        # Verify create_updated was called with the whole node '{"some_other_key": "val"}' because CONFIG_DEVICE_CONNECTION was missing.
        mock_connection.create_updated.assert_called_with({"some_other_key": "val"})

    # 3. Test get_connection fallback (None returns default)
    assert op.get_connection(None) == mock_connection

async def test_basicdeviceoperation_is_value_valid_edge_cases(mock_connection, mock_controller):
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
    from custom_components.climate_ip.const import CONFIG_DEVICE_OPERATION_NUMBER_MIN, CONFIG_DEVICE_OPERATION_NUMBER_MAX
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
        CONFIG_DEVICE_OPERATION_NUMBER_MAX: 30
    }
    assert op.load_from_yaml(yaml_node_2) is True
    assert op._min == 10
    assert op._max == 30

async def test_deviceoperation_resolve_async_params_edge_cases(mock_connection, mock_controller):
    """Kill mutants in _resolve_async_params getattr fallbacks and JSON decode."""
    import jinja2
    op = DeviceOperation("test", mock_connection, mock_controller)
    
    # Kill mutant 8: operation_params = None
    mock_connection._params = {"header": "123"}
    mock_connection._connection_template = jinja2.Template('{"val": "{{ value }}"}')
    params = op._resolve_async_params(mock_connection, "123", "duid")
    assert params == {"header": "123", "val": "123"}
    
    # Kill mutant 51/54: raw_params default {} vs None/missing
    del mock_connection._params
    params = op._resolve_async_params(mock_connection, "123", "duid")
    assert params == {"val": "123"}
    
    # Kill mutant 41: base_template getattr fallback
    del mock_connection._connection_template
    params_empty = op._resolve_async_params(mock_connection, "123", "duid")
    assert params_empty is None

async def test_deviceoperation_async_set_value_mutants(mock_connection, mock_controller):
    """Kill mutants in async_set_value."""
    op = DeviceOperation("test", mock_connection, mock_controller)
    op._connection_template = MagicMock()
    op.convert_hass_to_dev = MagicMock(return_value="val")
    
    # Kill mutant 6: current_full_state = None vs ""
    del mock_controller.device_state
    mock_connection.is_async_native = False
    mock_connection.execute.return_value = {"success": True}
    
    async def _mock_add_job(*args, **kwargs):
        # execute is args[0]
        func = args[0]
        return func(*args[1:])
        
    mock_controller.hass.async_add_executor_job = AsyncMock(side_effect=_mock_add_job)
    
    await op.async_set_value("val")
    args, _ = mock_connection.execute.call_args
    assert args[2] is None  # args[2] is current_full_state (0:template, 1:dev_value, 2:current_full_state, 3:device_id)

async def test_basicdeviceoperation_init_and_get_conn(mock_connection, mock_controller):
    """Kill mutants in BasicDeviceOperation __init__ and get_connection."""
    op = BasicDeviceOperation("test", mock_connection, mock_controller)
    assert op._feature_flag is None
    
    op._value_connections_map = {"on": "mock_on_conn"}
    assert op.get_connection("on") == "mock_on_conn"
    assert op.get_connection("off") == mock_connection

async def test_basicnumericoperation_match_value(mock_connection, mock_controller):
    """Kill mutant in BasicNumericOperation match_value."""
    op = BasicNumericOperation("test", mock_connection, mock_controller)
    # default convert_hass_to_dev just returns the float if no map
    assert op.match_value(10.0) is True
    # Testing ValueError path
    assert op.match_value("invalid_str") is False

async def test_deviceproperty_set_unit_of_measurement(mock_connection, mock_controller):
    """Kill mutants in set_unit_of_measurement."""
    prop = DeviceProperty("test", mock_connection, mock_controller)
    
    from custom_components.climate_ip.properties import UNIT_MAP
    import unittest.mock as mock
    
    with mock.patch.dict(UNIT_MAP, {"TEST_ALIAS": "TEST_UNIT"}):
        prop.set_unit_of_measurement("TEST_ALIAS")
        assert prop._unit_of_measurement == "TEST_UNIT"

async def test_deviceproperty_is_valid(mock_connection, mock_controller):
    """Kill mutants in is_valid."""
    import jinja2
    from unittest.mock import patch
    
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
    """Frente 2: Exact boundary testing for BasicNumericOperation.convert_hass_to_dev.

    Kills mutants that swap < for <=, > for >=, or break float() casting.
    """
    op = BasicNumericOperation("test_bounds", mock_connection, mock_controller)
    op._min = 10.0
    op._max = 30.0

    # Exact lower boundary: v == min → must pass through (kills v < min vs v <= min)
    assert op.convert_hass_to_dev(10.0) == 10.0

    # Exact upper boundary: v == max → must pass through (kills v > max vs v >= max)
    assert op.convert_hass_to_dev(30.0) == 30.0

    # Just below min → clamped to min
    assert op.convert_hass_to_dev(9.9) == 10.0

    # Just above max → clamped to max
    assert op.convert_hass_to_dev(30.1) == 30.0

    # Middle of range → passes through unchanged
    assert op.convert_hass_to_dev(20.0) == 20.0

    # None with limits set → TypeError caught, returns ha_value unchanged (passthrough)
    # This kills the float(None) → None mutation because the except branch returns ha_value
    assert op.convert_hass_to_dev(None) is None

    # "unknown" with limits set → float("unknown") fails → returns "unknown" (passthrough)
    assert op.convert_hass_to_dev("unknown") == "unknown"

    # Only min set, no max → value above min passes through
    op._min = 5.0
    op._max = None
    assert op.convert_hass_to_dev(5.0) == 5.0
    assert op.convert_hass_to_dev(4.9) == 5.0
    assert op.convert_hass_to_dev(100.0) == 100.0  # no max clamping

    # Only max set, no min → value below max passes through
    op._min = None
    op._max = 50.0
    assert op.convert_hass_to_dev(50.0) == 50.0
    assert op.convert_hass_to_dev(50.1) == 50.0
    assert op.convert_hass_to_dev(0.0) == 0.0  # no min clamping

    # Neither min nor max → raw passthrough (kills and/or swap in guard)
    op._min = None
    op._max = None
    assert op.convert_hass_to_dev("unknown") == "unknown"
    assert op.convert_hass_to_dev(42.0) == 42.0


async def test_temperature_boundaries_exact(mock_connection, mock_controller):
    """Frente 2: Exact boundary testing for TemperatureOperation.convert_hass_to_dev.

    Same boundary pattern but with unit conversion applied after clamping.
    Kills v < min → v <= min, v = self._min → None, and ValueError(None) mutations.
    """
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

    # None → ValueError (kills float(None) and ValueError(None) mutations)
    with pytest.raises(ValueError, match="Payload inválido"):
        op.convert_hass_to_dev(None)

    # "unknown" → ValueError
    with pytest.raises(ValueError, match="Payload inválido"):
        op.convert_hass_to_dev("unknown")


# ====================================================================================
# FRENTE 3: AUTOPSIA DEL PAYLOAD ASÍNCRONO
# ====================================================================================

async def test_getattr_fallback_connection_template(mock_connection, mock_controller):
    """Frente 3: Verify _connection_template getattr fallback doesn't raise AttributeError.

    If mutmut removes the None default from getattr(connection, "_connection_template", None),
    and the mock doesn't have the attribute, the code must not crash.
    This kills the getattr(obj, attr) → AttributeError family of mutants.
    """
    op = DeviceOperation("test_fallback", mock_connection, mock_controller)

    # Remove _connection_template so getattr without default would raise
    if hasattr(mock_connection, "_connection_template"):
        delattr(mock_connection, "_connection_template")
    # Also remove _params so the fallback path in _resolve_async_params is exercised
    if hasattr(mock_connection, "_params"):
        delattr(mock_connection, "_params")

    op.convert_hass_to_dev = MagicMock(return_value="dev_val_raw")

    # Without any template, _resolve_async_params returns None (no params available)
    # async_set_value should return False (could not resolve)
    result = await op.async_set_value("ha_val")
    assert result is False


async def test_resolve_async_params_uses_connection_template_fallback(mock_connection, mock_controller):
    """Frente 3: Verify _resolve_async_params falls back to connection._connection_template.

    When the operation has no template but the connection does, it must use the
    connection's template. Kills conn_tmpl = None and getattr(None, ...) mutations.
    """
    op = DeviceOperation("test_tmpl_fallback", mock_connection, mock_controller)
    op._connection_template = None  # operation has no template

    mock_conn_tmpl = MagicMock()
    mock_conn_tmpl.render.return_value = '{"method": "POST", "url": "/fallback"}'
    mock_connection._connection_template = mock_conn_tmpl

    result = op._resolve_async_params(mock_connection, "val", "duid_123")
    assert result is not None
    assert result["method"] == "POST"
    assert result["url"] == "/fallback"

    # Verify template was called with correct render context
    render_kwargs = mock_conn_tmpl.render.call_args[1]
    assert render_kwargs["value"] == "val"
    assert render_kwargs["duid"] == "duid_123"
    assert render_kwargs["device_id"] == "duid_123"


async def test_device_operation_payload_autopsy(mock_connection, mock_controller):
    """Frente 3: Full payload autopsy of DeviceOperation.async_set_value.

    Verifies that duid, device_id, value flow correctly from controller through
    render_context into the final async_execute call. Kills mutations on
    device_id getattr, duid_for_render construction, and params.get("headers").
    """
    mock_controller.device_id = "test_duid_123"
    mock_controller.device_state = {"power": "on"}
    op = DeviceOperation("test_payload", mock_connection, mock_controller)
    op.convert_hass_to_dev = MagicMock(return_value="dev_val")

    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "PUT", "url": "/api/set", "json": {"value": "dev_val"}, "headers": {"Authorization": "Bearer tok"}}'
    op._connection_template = mock_tmpl

    mock_connection.async_execute.return_value = ("ok", None)
    result = await op.async_set_value("ha_val")
    assert result is True

    # Autopsy of the render context (kills device_id/duid mutations)
    render_call_kwargs = mock_tmpl.render.call_args[1]
    assert render_call_kwargs["device_id"] == "test_duid_123"
    assert render_call_kwargs["duid"] == "test_duid_123"
    assert render_call_kwargs["value"] == "dev_val"

    # Autopsy of the async_execute call (kills params.get mutations)
    args, kwargs = mock_connection.async_execute.call_args
    assert args[0] == "PUT"                          # method
    assert args[1] == "/api/set"                     # url
    assert args[2] == '{"value":"dev_val"}'          # data_payload (json_dumps)
    assert args[3] == {"Authorization": "Bearer tok"}  # headers
    assert kwargs.get("device_state") == {"power": "on"}  # device_state kwarg

async def test_deviceoperation_fallback_config(mock_connection, mock_controller):
    """Test GetJsonStatus async_update_state fallback to .config when ._cfg is missing."""
    del mock_controller.device_id # Kills getattr(..., "device_id", ) mutation
    del mock_connection._cfg
    
    class DummyCfg:
        duid = "fallback_duid"
        token = "fallback_token"
    
    mock_cfg = DummyCfg()
    mock_connection.config = mock_cfg
    mock_connection._params = {}
    mock_connection.is_async_native = True

    op = DeviceOperation("test_fallback_config", mock_connection, mock_controller)
    op.convert_hass_to_dev = MagicMock(return_value="dev_val")
    
    mock_status_getter = MagicMock()
    mock_status_getter.value = {"power": "off"}
    op._status_getter = mock_status_getter
    
    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "PUT", "url": "/api/set"}'
    op._connection_template = mock_tmpl

    mock_connection.async_execute.return_value = ("ok", None)
    res = await op.async_set_value("ha_val")
    assert res is True
    
    # Assert payload autopsy
    rendered_dict = mock_tmpl.render.call_args[1]
    assert rendered_dict.get("duid") == "fallback_duid"

async def test_deviceoperation_resolve_async_params_merge_base(mock_connection, mock_controller):
    """Test merging of base_template and template_to_use in _resolve_async_params."""
    op = DeviceOperation("test_merge", mock_connection, mock_controller)
    
    mock_base_tmpl = MagicMock()
    mock_base_tmpl.render.return_value = '{"base_param": 1, "shared": "base"}'
    mock_connection._connection_template = mock_base_tmpl
    
    mock_op_tmpl = MagicMock()
    mock_op_tmpl.render.return_value = '{"op_param": 2, "shared": "op"}'
    op._connection_template = mock_op_tmpl
    
    mock_connection._params = {"raw_param": 3}
    
    params = op._resolve_async_params(mock_connection, "dev_val")
    
    assert params is not None
    # op_param (from op._connection_template) takes precedence over base_param and shared
    assert params["base_param"] == 1
    assert params["op_param"] == 2
    assert params["shared"] == "op"
    assert params["raw_param"] == 3
    
async def test_device_operation_duid_fallback_from_cfg(mock_connection, mock_controller):
    """Frente 3: Verify duid_for_render falls back to cfg.duid when controller has none.

    Kills mutations on the cfg := getattr(...) chain and getattr(cfg, "duid", None).
    """
    # Controller has NO device_id
    del mock_controller.device_id
    op = DeviceOperation("test_cfg_duid", mock_connection, mock_controller)
    op.convert_hass_to_dev = MagicMock(return_value="val")

    mock_cfg = MagicMock()
    mock_cfg.duid = "cfg_duid_456"
    mock_connection._cfg = mock_cfg

    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "GET"}'
    op._connection_template = mock_tmpl

    mock_connection.async_execute.return_value = ("ok", None)
    await op.async_set_value("ha_val", device_id=None)

    render_kwargs = mock_tmpl.render.call_args[1]
    assert render_kwargs["duid"] == "cfg_duid_456"
    assert render_kwargs["device_id"] == "cfg_duid_456"


async def test_getjsonstatus_payload_autopsy_and_cfg(mock_connection, mock_controller):
    """Frente 3: Autopsy of GetJsonStatus.async_update_state render_context.

    Verifies that device_id, duid (from cfg), and token (from cfg) are injected
    into the render_context correctly. Kills all setdefault key mutations and
    hasattr(cfg, "duid/token") mutations.
    """
    mock_controller.device_id = "controller_duid"
    mock_cfg = MagicMock()
    mock_cfg.duid = "cfg_duid"
    mock_cfg.token = "cfg_token"
    mock_connection._cfg = mock_cfg
    mock_connection._params = {}  # Real dict so .copy() returns a dict
    mock_connection.is_async_native = True

    g = GetJsonStatus("test_get", mock_connection, mock_controller)

    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "GET", "url": "/status", "headers": {"X-Token": "abc"}}'
    g._connection_template = mock_tmpl

    mock_connection.async_execute.return_value = ('{"temperature": 22}', None)

    result = await g.async_update_state(None, False)

    # Autopsy of render_context (kills duid/token/device_id key mutations)
    render_call_kwargs = mock_tmpl.render.call_args[1]
    # duid = controller_duid because setdefault("duid", dev_id) is called FIRST
    # cfg.duid only wins when controller has no device_id (tested in duid_fallback test)
    assert render_call_kwargs["duid"] == "controller_duid"
    assert render_call_kwargs["token"] == "cfg_token"
    assert render_call_kwargs["device_id"] == "controller_duid"

    # Autopsy of the async_execute call (kills params.get and _is_poll mutations)
    args, kwargs = mock_connection.async_execute.call_args
    assert args[0] == "GET"                          # method
    assert args[1] == "/status"                      # url
    assert args[2] is None                           # data (no body for poll)
    assert args[3] == {"X-Token": "abc"}             # headers
    assert kwargs.get("_is_poll") is True            # _is_poll flag

    # Autopsy of _attrs (kills self._attrs = None and key mutations)
    assert g._attrs is not None
    assert "device_state" in g._attrs
    assert g._attrs["device_state"] == '{"temperature":22}'


async def test_getjsonstatus_no_cfg_attributes(mock_connection, mock_controller):
    """Frente 3: Verify GetJsonStatus works when cfg has no duid/token attributes.

    Kills hasattr(cfg, "duid") → hasattr(cfg, "XXduidXX") mutations by proving
    the code path where duid/token are NOT present is correctly handled.
    """
    mock_controller.device_id = "ctrl_duid"
    # cfg exists but has no duid/token attributes
    mock_cfg = MagicMock(spec=[])  # empty spec → no attributes
    mock_connection._cfg = mock_cfg
    mock_connection._params = {}  # Real dict so .copy() returns a dict
    mock_connection.is_async_native = True

    g = GetJsonStatus("test_no_cfg", mock_connection, mock_controller)

    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "GET"}'
    g._connection_template = mock_tmpl

    mock_connection.async_execute.return_value = ('{"ok": true}', None)

    await g.async_update_state(None, False)

    render_call_kwargs = mock_tmpl.render.call_args[1]
    # device_id is still set from controller
    assert render_call_kwargs["device_id"] == "ctrl_duid"
    assert render_call_kwargs["duid"] == "ctrl_duid"
    # token should NOT be in context (cfg has no token)
    assert "token" not in render_call_kwargs

# ====================================================================================
# FINAL EXTERMINATION: FRONT A, B, C, D
# ====================================================================================
from custom_components.climate_ip.properties import SwitchOperation, BasicDeviceOperation, TemperatureOperation, ModeOperation, BasicNumericOperation
from homeassistant.const import UnitOfTemperature

# FRONT A: Synchronous Executor Fallback
async def test_getjsonstatus_sync_execute(mock_connection, mock_controller):
    """Front A: Execute synchronous async_add_executor_job path in GetJsonStatus."""
    mock_connection.is_async_native = False
    g = GetJsonStatus("test_sync", mock_connection, mock_controller)
    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "GET"}'
    g._connection_template = mock_tmpl
    
    mock_controller.device_id = "test_duid"
    mock_controller.hass.async_add_executor_job = AsyncMock(return_value=('{"sync": true}', None))
    await g.async_update_state(None, False)
    
    # Verify exact parameters passed to async_add_executor_job
    mock_controller.hass.async_add_executor_job.assert_called_once_with(
        mock_connection.execute,
        mock_tmpl,
        None,
        "unknown"
    )

async def test_deviceoperation_sync_execute(mock_connection, mock_controller):
    """Frente 1: Test sync execution path for DeviceOperation."""
    mock_connection.is_async_native = False
    mock_connection._lock = MagicMock()
    mock_connection._lock.__aenter__ = AsyncMock()
    mock_connection._lock.__aexit__ = AsyncMock()
    del mock_controller.device_state # Kills mutants 6, 7, 12 in async_set_value
    
    op = DeviceOperation("test_sync", mock_connection, mock_controller)
    op.convert_hass_to_dev = MagicMock(return_value="dev_val")
    
    mock_status_getter = MagicMock()
    mock_status_getter.value = {"power": "off"}
    op._status_getter = mock_status_getter
    
    op._resolve_params = MagicMock(return_value={"test_param": 1})
    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "SET"}'
    op._connection_template = mock_tmpl
    
    mock_controller.device_id = "test_duid"
    mock_controller.hass.async_add_executor_job = AsyncMock(return_value=True)
    res = await op.async_set_value("ha_val")
    
    assert res is True
    mock_controller.hass.async_add_executor_job.assert_called_once_with(
        mock_connection.execute,
        mock_tmpl,
        "dev_val",
        {"power": "off"},
        None
    )

# FRONT B: YAML Configurator Loaders
def test_device_property_load_from_yaml(mock_connection, mock_controller):
    """Front B: load_from_yaml testing on basic properties."""
    prop = DeviceProperty("test_yaml", mock_connection, mock_controller)
    
    # Test None / Empty
    assert prop.load_from_yaml(None) is False
    assert prop.load_from_yaml({}) is True
    
    # Test Values and Status Template
    node = {
        "values": {"ha_on": "dev_1", "ha_off": "dev_0"},
        "status_template": "state.value",
        "connection_template": "conn",
        "validation_template": "val",
        "name": "Test Name",
        "device_class": "temperature",
        "unit_of_measurement": "C",
        "entity_category": "diagnostic",
        "state_class": "measurement"
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
    
@pytest.mark.parametrize("dev_class", ["power", "temperature", "humidity", "voltage", "current"])
def test_device_property_load_from_yaml_state_class(mock_connection, mock_controller, dev_class):
    """Test that default state_class is assigned to specific device classes."""
    prop = DeviceProperty("test_state_class", mock_connection, mock_controller)
    node = {"device_class": dev_class}
    prop.load_from_yaml(node)
    assert prop._state_class is not None
    assert prop._state_class.value == "measurement"

def test_device_property_load_from_yaml_state_class_other(mock_connection, mock_controller):
    """Test that default state_class is NOT assigned to other device classes."""
    prop = DeviceProperty("test_state_class", mock_connection, mock_controller)
    node = {"device_class": "battery"}
    prop.load_from_yaml(node)
    assert prop._state_class is None
    
    # Test BasicDeviceOperation connection load
    b_op = BasicDeviceOperation("test_bop", mock_connection, mock_controller)
    node_bop = {
        "values": {"ha_on": {"connection": {"type": "tcp"}}}
    }
    mock_connection.create_updated.return_value = mock_connection
    assert b_op.load_from_yaml(node_bop) is True
    assert b_op._value_connections_map["ha_on"] == mock_connection
    
    # SwitchOperation specific load
    sw_op = SwitchOperation("test_sw", mock_connection, mock_controller)
    node_sw = {"values": {"ha_on": {"value": "dev_1"}, "ha_off": {"value": "dev_0"}}} # Missing off_values
    assert sw_op.load_from_yaml(node_sw) is True

    # GetJsonStatus specific load
    g = GetJsonStatus("test_yaml_get", mock_connection, mock_controller)
    assert g.load_from_yaml({"status_template": "x"}) is True

# FRONT C: Config Fallback
async def test_device_operation_duid_fallback_config(mock_connection, mock_controller):
    """Front C: Duid extraction fallback to getattr(connection, 'config')."""
    del mock_controller.device_id
    del mock_connection._cfg # No _cfg
    
    mock_config = MagicMock()
    mock_config.duid = "config_duid"
    mock_connection.config = mock_config # Fallback 'config'
    
    op = DeviceOperation("test_fallback", mock_connection, mock_controller)
    op.convert_hass_to_dev = MagicMock(return_value="val")
    mock_tmpl = MagicMock()
    mock_tmpl.render.return_value = '{"method": "SET"}'
    op._connection_template = mock_tmpl
    mock_connection.async_execute.return_value = ("ok", None)
    
    await op.async_set_value("ha_val")
    
    render_kwargs = mock_tmpl.render.call_args[1]
    assert render_kwargs["duid"] == "config_duid"
    assert render_kwargs["device_id"] == "config_duid"

# FRONT D: Small Blindspots
def test_temperature_operation_units(mock_connection, mock_controller):
    """Front D: Temperature operation unit mappings."""
    op = TemperatureOperation("test_temp", mock_connection, mock_controller)
    
    # Test valid unit mapping
    op.set_device_unit("C")
    assert op._device_unit == UnitOfTemperature.CELSIUS
    op.set_hass_unit("F")
    assert op._hass_unit == UnitOfTemperature.FAHRENHEIT
    
    # Test invalid unit fallback
    op.set_device_unit("INVALID_C")
    assert op._device_unit == "INVALID_C"
    op.set_hass_unit("INVALID_F")
    assert op._hass_unit == "INVALID_F"

def test_mode_operation_init(mock_connection, mock_controller):
    """Front D: ModeOperation initialization features."""
    op_hvac = ModeOperation("hvac_mode", mock_connection, mock_controller)
    assert op_hvac._feature_flag is None # Standard behavior without extra features
    
    op_fan = ModeOperation("fan", mock_connection, mock_controller)
    assert op_fan._feature_flag is not None # Maps to ClimateEntityFeature.FAN_MODE

def test_basic_numeric_bounds_strict(mock_connection, mock_controller):
    """Front D: Strict '<=' and '>=' mutations for convert_hass_to_dev."""
    op = BasicNumericOperation("test_bounds", mock_connection, mock_controller)
    op._min = 10.0
    op._max = 30.0
    
    # Kill the `<` -> `<=` mutation. 
    # If it was `<=`, `10 <= 10.0` is True, returns `self._min` which is float(10.0).
    # If `<` (original), `10 < 10.0` is False, falls through, returns int(10).
    res_min = op.convert_hass_to_dev(10)
    assert res_min == 10
    assert type(res_min) is int, "Strict boundary failure on _min"
    
    # Kill the `>` -> `>=` mutation.
    res_max = op.convert_hass_to_dev(30)
    assert res_max == 30
    assert type(res_max) is int, "Strict boundary failure on _max"
