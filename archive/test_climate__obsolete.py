# pylint: disable=all
"""Archived test functions from climate test suite.

Quarantined 12 completely shadowed tests with zero unique mutant kills
and zero unique line coverage to accelerate mutmut and pytest execution.
Their functional contracts and historical test scenarios are preserved here.
"""

from unittest.mock import MagicMock, patch

from custom_components.climate_ip.climate import ClimateIP, async_setup_entry
from custom_components.climate_ip.const import (
    DEFAULT_CLIMATE_IP_TEMP_MAX,
    DEFAULT_CLIMATE_IP_TEMP_MIN,
)
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
import pytest

from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import PRECISION_WHOLE
from homeassistant.exceptions import ServiceValidationError


def test_00_climate_defensive_init_properties(base_climate_entity: ClimateIP) -> None:
    """Fail-fast test for constructor state attributes.

    Shadowed 100% by test_climate_translation_key_and_device_info, test_climate_unique_id,
    and test_climate_edge_cases_precision_and_boundary.
    """
    assert base_climate_entity._attr_unique_id is not None, "unique_id MUST NOT be None"
    assert base_climate_entity._attr_device_info is not None, (
        "device_info MUST NOT be None"
    )
    assert (
        base_climate_entity._attr_device_info
        == base_climate_entity.coordinator.device_info
    )
    assert base_climate_entity._attr_precision == PRECISION_WHOLE
    assert base_climate_entity.min_temp is not None, "min_temp MUST NOT be None"
    assert base_climate_entity.max_temp is not None, "max_temp MUST NOT be None"
    assert base_climate_entity._attr_target_temperature_step is not None, (
        "step MUST NOT be None"
    )
    assert isinstance(base_climate_entity.hvac_modes, list), "hvac_modes MUST be a list"
    assert base_climate_entity.fan_modes is not None, "fan_modes MUST NOT be None"
    assert base_climate_entity.swing_modes is not None, "swing_modes MUST NOT be None"
    assert base_climate_entity.preset_modes is not None, "preset_modes MUST NOT be None"


def test_01_climate_defensive_sync_none_fallback() -> None:
    """Fail-fast test for fallback logic when coordinator.data is None.

    Shadowed 100% by test_climate_hvac_modes_append_off_and_temp_unit.
    """
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.data = None
    mock_coord.unique_id = "defensive_id"
    mock_coord.entry = MagicMock(options={})
    mock_coord.device_info = MagicMock()
    mock_coord.controller = MagicMock()
    mock_coord.controller.operations = []
    mock_coord.controller.state_attributes = {}
    desc = ClimateEntityDescription(key="samsung_ac", translation_key="samsung_ac")

    entity = ClimateIP(coordinator=mock_coord, description=desc)

    assert isinstance(entity.hvac_modes, list), "hvac_modes MUST be a list"
    assert isinstance(entity.fan_modes, list), "fan_modes MUST be a list"
    assert isinstance(entity.swing_modes, list), "swing_modes MUST be a list"
    assert isinstance(entity.preset_modes, list), "preset_modes MUST be a list"


def test_climate_available_last_update_failed(base_climate_entity: ClimateIP) -> None:
    """Verify available returns False when last_update_success is False.

    Obsolete in climate test suite: ClimateIP inherits available from CoordinatorEntity.
    """
    base_climate_entity.coordinator.last_update_success = False
    assert base_climate_entity.available is False


def test_climate_available_success(base_climate_entity: ClimateIP) -> None:
    """Verify available returns True when last_update_success is True.

    Obsolete in climate test suite: ClimateIP inherits available from CoordinatorEntity.
    """
    base_climate_entity.coordinator.last_update_success = True
    assert base_climate_entity.available is True


def test_climate_min_temp_fallback_on_none_prop(base_climate_entity: ClimateIP) -> None:
    """Kill mutants in min_temp when get_property_object returns None.

    Shadowed 100% by test_climate_edge_cases_precision_and_boundary.
    """
    base_climate_entity.coordinator.controller.get_property_object.return_value = None
    assert base_climate_entity.min_temp == float(DEFAULT_CLIMATE_IP_TEMP_MIN)


def test_climate_min_temp_fallback_on_invalid_value(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants when min_t_prop.value is invalid string.

    Shadowed 100% by test_climate_edge_cases_precision_and_boundary.
    """
    mock_prop = MagicMock()
    mock_prop.value = "invalid_number"
    base_climate_entity.coordinator.controller.get_property_object.return_value = (
        mock_prop
    )
    assert base_climate_entity.min_temp == float(DEFAULT_CLIMATE_IP_TEMP_MIN)


def test_climate_max_temp_fallback_on_none_prop(base_climate_entity: ClimateIP) -> None:
    """Kill mutants in max_temp when get_property_object returns None.

    Shadowed 100% by test_climate_edge_cases_precision_and_boundary.
    """
    base_climate_entity.coordinator.controller.get_property_object.return_value = None
    assert base_climate_entity.max_temp == float(DEFAULT_CLIMATE_IP_TEMP_MAX)


async def test_climate_sync_data_full(base_climate_entity: ClimateIP) -> None:
    """Verify synchronization when coordinator.data is fully populated.

    Shadowed 100% by test_climate_hvac_modes_append_off_and_temp_unit and property tests.
    """
    mock_state = MagicMock()
    mock_state.hvac_mode = "heat"
    mock_state.target_temperature = 25.0
    mock_state.current_temperature = 22.0
    mock_state.fan_mode = "high"
    mock_state.swing_mode = "vertical"
    mock_state.preset_mode = "boost"
    mock_state.hvac_modes = ["heat", "off"]
    mock_state.fan_modes = ["high", "low"]
    mock_state.swing_modes = ["vertical", "horizontal"]
    mock_state.preset_modes = ["boost", "eco"]

    base_climate_entity.coordinator.data = mock_state

    assert base_climate_entity.hvac_mode == HVACMode.HEAT
    assert type(base_climate_entity.hvac_mode) is HVACMode
    assert base_climate_entity.hvac_mode is HVACMode.HEAT
    assert base_climate_entity.target_temperature == 25.0
    assert base_climate_entity.current_temperature == 22.0
    assert base_climate_entity.fan_mode == "high"
    assert base_climate_entity.swing_mode == "vertical"
    assert base_climate_entity.preset_mode == "boost"
    assert base_climate_entity.hvac_modes == [HVACMode.HEAT, HVACMode.OFF]
    assert all(type(m) is HVACMode for m in base_climate_entity.hvac_modes)
    assert base_climate_entity.fan_modes == ["high", "low"]
    assert base_climate_entity.swing_modes == ["vertical", "horizontal"]
    assert base_climate_entity.preset_modes == ["boost", "eco"]


async def test_climate_sync_data_none(base_climate_entity: ClimateIP) -> None:
    """Verify fallback when coordinator.data is None.

    Shadowed 100% by test_climate_hvac_modes_append_off_and_temp_unit.
    """
    base_climate_entity.coordinator.unique_id = "test_sync_none"
    base_climate_entity.coordinator.data = None

    assert base_climate_entity.hvac_mode is None
    assert base_climate_entity.target_temperature is None
    assert base_climate_entity.current_temperature is None
    assert base_climate_entity.fan_mode is None
    assert base_climate_entity.swing_mode is None
    assert base_climate_entity.preset_mode is None
    assert base_climate_entity.hvac_modes == []
    assert base_climate_entity.fan_modes == []
    assert base_climate_entity.swing_modes == []
    assert base_climate_entity.preset_modes == []


async def test_async_service_set_property_invalid_key_raises(
    base_climate_entity: ClimateIP,
) -> None:
    """Consolidated into canonical test_async_service_set_property."""
    base_climate_entity.coordinator.controller.operations = ["beep"]
    with pytest.raises(ServiceValidationError, match="is not a valid operation"):
        await base_climate_entity.async_service_set_property("invalid_key", "on")


async def test_async_set_hvac_mode_invalid_raises_service_validation_error(
    base_climate_entity: ClimateIP,
) -> None:
    """Consolidated into canonical test_public_async_set_hvac_mode_behavior."""
    base_climate_entity.coordinator.data.hvac_modes = [HVACMode.HEAT]
    with pytest.raises(
        ServiceValidationError, match="Requested HVAC mode 'cool' is not available"
    ):
        await base_climate_entity.async_set_hvac_mode(HVACMode.COOL)


@pytest.mark.asyncio
async def test_modern_async_setup_entry_empty() -> None:
    """Consolidated into canonical test_modern_async_setup_entry_success."""
    entry = MagicMock()
    entry.runtime_data = {}
    async_add_entities = MagicMock()

    with patch("custom_components.climate_ip.climate._LOGGER.error") as mock_logger:
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    async_add_entities.assert_not_called()
    mock_logger.assert_called_once_with(
        "No valid entities could be initialized from the provided coordinators."
    )
