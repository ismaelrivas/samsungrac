# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for DeviceProperty, ModeOperation and TemperatureOperation."""
# pylint: disable=protected-access,redefined-outer-name,import-outside-toplevel
import logging
from unittest.mock import MagicMock

import pytest

from custom_components.climate_ip.const import (
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_OPERATION_VALUE,
    CONFIG_DEVICE_OPERATION_VALUES,
    CONFIG_TYPE,
)
from custom_components.climate_ip.properties import (
    DeviceProperty,
    ModeOperation,
    TemperatureOperation,
)
from homeassistant.const import UnitOfTemperature


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
    return controller


@pytest.fixture
def mock_connection():
    """Create a mock connection."""
    connection = MagicMock()
    connection.create_updated.return_value = connection
    return connection



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
    assert prop.unit_of_measurement == UnitOfTemperature.CELSIUS



async def test_temperature_operation_conversion(mock_connection, mock_controller):
    """Test TemperatureOperation conversion logic."""
    temp_op = TemperatureOperation("target_temp", mock_connection, mock_controller)
    temp_op.set_device_unit(UnitOfTemperature.FAHRENHEIT)
    temp_op.set_hass_unit(UnitOfTemperature.CELSIUS)

    # Test conversion from device (F) to HA (C)
    # 68 F = 20 C
    assert temp_op.convert_dev_to_hass(68) == 20.0

    # Test conversion from HA (C) to device (F)
    # 20 C = 68 F
    assert temp_op.convert_hass_to_dev(20) == 68.0



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
