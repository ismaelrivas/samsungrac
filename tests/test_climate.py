# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Orthogonal canonical test suite for the ClimateIP climate entity."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.climate import (
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ClimateIP,
    async_setup_entry,
)
from custom_components.climate_ip.const import (
    ATTR_POWER,
    CONF_TARGET_TEMP_STEP,
    DEFAULT_CLIMATE_IP_TEMP_MAX,
    DEFAULT_CLIMATE_IP_TEMP_MIN,
    DEFAULT_TARGET_TEMP_STEP,
)
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE as HA_ATTR_TEMPERATURE,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def base_climate_entity() -> ClimateIP:
    """Fixture base con coordinador mockeado y hass ligero en memoria."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_base_id"
    mock_coord.entry = MagicMock(options={})
    mock_coord.async_predict_and_correct = AsyncMock(return_value=({}, {}))
    mock_coord.async_set_property = AsyncMock()
    mock_coord.async_request_refresh = AsyncMock()
    mock_coord.device_info = MagicMock()
    mock_coord.data = MagicMock()
    mock_coord.controller = MagicMock()
    mock_coord.controller.operations = []
    mock_coord.controller.state_attributes = {}
    mock_coord.controller.get_property_object.return_value = None

    desc = ClimateEntityDescription(key="samsung_ac", translation_key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coord, description=desc)

    mock_hass = MagicMock()
    mock_hass.config.units.temperature_unit = "°C"
    entity.hass = mock_hass
    entity.async_write_ha_state = MagicMock()
    return entity


async def test_turn_on_dry_helper(base_climate_entity: ClimateIP) -> None:
    """Test that turn_on and turn_off delegate to coordinator.async_set_property."""
    base_climate_entity.coordinator.controller.operations = [ATTR_POWER]
    base_climate_entity.coordinator.async_set_property = AsyncMock()

    await base_climate_entity.async_turn_on()
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_POWER, STATE_ON
    )
    base_climate_entity.coordinator.async_set_property.reset_mock()

    await base_climate_entity.async_turn_off()
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_POWER, STATE_OFF
    )


def test_no_flicker_feature_method() -> None:
    """async_flicker_feature antipattern must be fully removed from ClimateIP."""
    assert not hasattr(ClimateIP, "async_flicker_feature"), (
        "async_flicker_feature was not removed from ClimateIP — remove the no-op method"
    )


def test_no_stale_supported_features_annotation() -> None:
    """_supported_features class annotation must be removed."""
    annotations = {}
    for klass in ClimateIP.__mro__:
        if klass is object:
            break
        annotations.update(vars(klass).get("__annotations__", {}))
    assert "_supported_features" not in annotations, (
        "_supported_features stale annotation is still present in ClimateIP or a parent class"
    )


def test_climate_translation_key_and_device_info() -> None:
    """Test that ClimateIP correctly maps translation_key and device_info."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_unique_id"
    mock_coordinator.controller = MagicMock()
    mock_coordinator.controller.operations = ["power"]
    mock_coordinator.controller.state_attributes = {}
    mock_coordinator.log_prefix = "[TEST]"
    mock_coordinator.data = MagicMock()
    mock_coordinator.device_info = {"identifiers": {("climate_ip", "test_unique_id")}}
    mock_coordinator.entry = MagicMock(options={})

    description = ClimateEntityDescription(
        key="samsung_ac",
        translation_key="samsung_ac",
    )
    climate = ClimateIP(coordinator=mock_coordinator, description=description)

    assert climate.translation_key == "samsung_ac"
    assert climate.device_info == {"identifiers": {("climate_ip", "test_unique_id")}}
    assert climate._attr_device_info == {
        "identifiers": {("climate_ip", "test_unique_id")}
    }


def test_climate_init_options_priority_and_halves() -> None:
    """Verify that entry options have priority and configure step=0.5."""
    mock_coordinator = MagicMock()
    mock_coordinator.entry.options = {CONF_TARGET_TEMP_STEP: 0.5}
    mock_coordinator.entry.data = {CONF_TARGET_TEMP_STEP: 1.0}

    description = ClimateEntityDescription(key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coordinator, description=description)

    assert entity.target_temperature_step == 0.5, (
        "Entry options priority was not respected"
    )
    assert entity.precision == PRECISION_HALVES, (
        "Precision was not adjusted to half degrees"
    )

    # Fallback to entry.data when entry.options is empty
    mock_fallback_coord = MagicMock()
    mock_fallback_coord.entry.options = {}
    mock_fallback_coord.entry.data = {CONF_TARGET_TEMP_STEP: 0.5}
    entity_fallback = ClimateIP(
        coordinator=mock_fallback_coord, description=description
    )
    assert entity_fallback.target_temperature_step == 0.5
    assert entity_fallback.precision == PRECISION_HALVES


def test_climate_unique_id() -> None:
    """Verify that unique_id correctly reflects the coordinator's unique_id."""
    mock_coordinator = MagicMock()
    mock_coordinator.unique_id = "coord_id_123"
    description = ClimateEntityDescription(key="samsung_ac")

    entity = ClimateIP(
        coordinator=mock_coordinator,
        description=description,
    )
    assert entity.unique_id == "coord_id_123"
    assert entity._attr_unique_id == "coord_id_123"


def test_hvac_action_dynamic_auto_heuristic(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify dynamic temperature heuristic for hvac_action in AUTO / HEAT_COOL mode."""
    # When data is None -> OFF
    base_climate_entity.coordinator.data = None
    assert base_climate_entity.hvac_action == HVACAction.OFF

    state = MagicMock()
    state.hvac_mode = HVACMode.AUTO
    base_climate_entity.coordinator.data = state

    # Current < Target - 0.5 -> HEATING (test 20.0 and 21.0 to kill target - 1.5 mutant)
    state.current_temperature = 20.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING
    state.current_temperature = 21.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING

    # Current > Target + 0.5 -> COOLING (test 24.0 and 23.0 to kill target + 1.5 mutant)
    state.current_temperature = 24.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.COOLING
    state.current_temperature = 23.0
    assert base_climate_entity.hvac_action == HVACAction.COOLING

    # Within deadband (22.0 vs 22.0) -> IDLE
    state.current_temperature = 22.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.IDLE

    # Deadband exact edges: current == target - 0.5 and current == target + 0.5 -> IDLE
    state.current_temperature = 21.5
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    state.current_temperature = 22.5
    assert base_climate_entity.hvac_action == HVACAction.IDLE

    # AUTO mode with None temperature values -> IDLE
    state.current_temperature = None
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    state.current_temperature = 22.0
    state.target_temperature = None
    assert base_climate_entity.hvac_action == HVACAction.IDLE

    # Repeat for HEAT_COOL mode
    state.hvac_mode = HVACMode.HEAT_COOL
    state.current_temperature = 20.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING
    state.current_temperature = 21.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING
    state.current_temperature = 24.0
    assert base_climate_entity.hvac_action == HVACAction.COOLING
    state.current_temperature = 23.0
    assert base_climate_entity.hvac_action == HVACAction.COOLING
    state.current_temperature = 21.5
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    state.current_temperature = 22.5
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    state.current_temperature = None
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    state.current_temperature = 22.0
    state.target_temperature = None
    assert base_climate_entity.hvac_action == HVACAction.IDLE

    # OFF mode -> OFF
    state.hvac_mode = HVACMode.OFF
    assert base_climate_entity.hvac_action == HVACAction.OFF

    # COOL mode: active when current > target - 0.5, idle otherwise
    state.hvac_mode = HVACMode.COOL
    state.current_temperature = 25.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.COOLING
    # Current between target - 0.5 (21.5) and target + 0.5 (22.5) -> COOLING (kills target + 0.5 mutant)
    state.current_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.COOLING
    state.current_temperature = 21.0
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    # COOL boundary exact deadband edge (21.5 == 22.0 - 0.5) -> IDLE
    state.current_temperature = 21.5
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    # Target None in COOL mode -> COOLING
    state.current_temperature = 25.0
    state.target_temperature = None
    assert base_climate_entity.hvac_action == HVACAction.COOLING

    # HEAT mode: active when current < target + 0.5, idle otherwise
    state.hvac_mode = HVACMode.HEAT
    state.current_temperature = 19.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING
    # Current between target - 0.5 (21.5) and target + 0.5 (22.5) -> HEATING (kills target - 0.5 mutant)
    state.current_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING
    state.current_temperature = 23.0
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    # HEAT boundary exact deadband edge (22.5 == 22.0 + 0.5) -> IDLE
    state.current_temperature = 22.5
    assert base_climate_entity.hvac_action == HVACAction.IDLE
    # Current None in HEAT mode -> HEATING
    state.current_temperature = None
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING
    # Target None in HEAT mode -> HEATING
    state.current_temperature = 20.0
    state.target_temperature = None
    assert base_climate_entity.hvac_action == HVACAction.HEATING

    # DRY & FAN_ONLY modes
    state.hvac_mode = HVACMode.DRY
    assert base_climate_entity.hvac_action == HVACAction.DRYING
    state.hvac_mode = HVACMode.FAN_ONLY
    assert base_climate_entity.hvac_action == HVACAction.FAN

    # Fallback to static mapping when temperature is None
    state.current_temperature = None
    state.hvac_mode = HVACMode.COOL
    assert base_climate_entity.hvac_action == HVACAction.COOLING


async def test_public_async_set_hvac_mode_behavior(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify network output of the HVAC delegator and validation error on invalid mode."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.hvac_modes = [HVACMode.COOL]

    # Valid mode
    await base_climate_entity.async_set_hvac_mode(HVACMode.COOL)
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_HVAC_MODE, HVACMode.COOL
    )

    # Invalid mode raises ServiceValidationError
    with pytest.raises(
        ServiceValidationError, match="Requested HVAC mode 'heat' is not available"
    ):
        await base_climate_entity.async_set_hvac_mode(HVACMode.HEAT)


async def test_public_async_set_fan_mode_behavior(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify network output of the Fan delegator and validation on invalid mode."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.fan_modes = ["low", "high"]

    await base_climate_entity.async_set_fan_mode("high")
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_FAN_MODE, "high"
    )

    with pytest.raises(
        ServiceValidationError, match="Requested fan mode 'turbo' is not available"
    ):
        await base_climate_entity.async_set_fan_mode("turbo")


async def test_async_set_temperature(base_climate_entity: ClimateIP) -> None:
    """Verify temperature and hvac_mode settings and mutual exclusivity validation."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.hvac_modes = [HVACMode.COOL]

    # 1. Valid temperature only
    await base_climate_entity.async_set_temperature(temperature=21.0)
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        HA_ATTR_TEMPERATURE, 21.0
    )
    base_climate_entity.coordinator.async_set_property.reset_mock()

    # 2. HVAC mode only
    await base_climate_entity.async_set_temperature(hvac_mode=HVACMode.COOL)
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_HVAC_MODE, HVACMode.COOL
    )
    base_climate_entity.coordinator.async_set_property.reset_mock()

    # 3. Both temperature and HVAC mode
    await base_climate_entity.async_set_temperature(
        hvac_mode=HVACMode.COOL, temperature=22.0
    )
    base_climate_entity.coordinator.async_set_property.assert_any_call(
        ATTR_HVAC_MODE, HVACMode.COOL
    )
    base_climate_entity.coordinator.async_set_property.assert_any_call(
        HA_ATTR_TEMPERATURE, 22.0
    )

    # 4. Both missing raises ServiceValidationError
    with pytest.raises(
        ServiceValidationError, match="No temperature or HVAC mode provided"
    ):
        await base_climate_entity.async_set_temperature()


async def test_async_set_swing_mode(base_climate_entity: ClimateIP) -> None:
    """Kill mutants in async_set_swing_mode and verify invalid mode rejection."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.swing_modes = ["vertical", "horizontal"]

    await base_climate_entity.async_set_swing_mode("vertical")
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_SWING_MODE, "vertical"
    )

    with pytest.raises(
        ServiceValidationError, match="Requested swing mode 'invalid' is not available"
    ):
        await base_climate_entity.async_set_swing_mode("invalid")


async def test_async_set_preset_mode(base_climate_entity: ClimateIP) -> None:
    """Kill mutants in async_set_preset_mode and verify invalid mode rejection."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.preset_modes = ["sleep"]

    await base_climate_entity.async_set_preset_mode("sleep")
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_PRESET_MODE, "sleep"
    )

    with pytest.raises(
        ServiceValidationError, match="Requested preset mode 'invalid' is not available"
    ):
        await base_climate_entity.async_set_preset_mode("invalid")


async def test_async_service_set_property(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants in async_service_set_property for valid key, unapproved key, and bad type."""
    base_climate_entity.coordinator.controller.operations = ["beep"]
    base_climate_entity.coordinator.async_set_property = AsyncMock()

    # Valid call
    await base_climate_entity.async_service_set_property("beep", "on")
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        "beep", "on"
    )

    # Invalid key raises ServiceValidationError
    with pytest.raises(ServiceValidationError, match="is not a valid operation"):
        await base_climate_entity.async_service_set_property("invalid_key", "on")

    # Invalid value type raises ServiceValidationError
    with pytest.raises(ServiceValidationError, match="Invalid value type 'list'"):
        await base_climate_entity.async_service_set_property(
            "beep", ["invalid", "list"]
        )


def test_climate_invalid_temp_step_fallback(
    base_climate_entity: ClimateIP, caplog: pytest.LogCaptureFixture
) -> None:
    """Kill mutants in __init__ for invalid temp step configuration."""
    base_climate_entity.coordinator.entry.options = {
        CONF_TARGET_TEMP_STEP: "invalid_string"
    }
    base_climate_entity.coordinator.entry.data = {}

    with caplog.at_level(logging.WARNING):
        entity = ClimateIP(
            base_climate_entity.coordinator,
            base_climate_entity.entity_description,
        )
        assert entity.target_temperature_step == float(DEFAULT_TARGET_TEMP_STEP)
        assert "Invalid temp step configured" in caplog.text


def test_climate_supported_features_accumulation_and_power(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants in __init__ for bitwise accumulation and power turn_on_off flags."""
    # 1. Set exactly two features that map through the dynamic loop
    base_climate_entity.coordinator.controller.operations = [
        ATTR_PRESET_MODE,
        HA_ATTR_TEMPERATURE,
    ]
    entity = ClimateIP(
        base_climate_entity.coordinator,
        base_climate_entity.entity_description,
    )

    expected_features = (
        ClimateEntityFeature.PRESET_MODE | ClimateEntityFeature.TARGET_TEMPERATURE
    )
    assert entity.supported_features == expected_features
    assert not (entity.supported_features & ClimateEntityFeature.TURN_ON)
    assert not (entity.supported_features & ClimateEntityFeature.TURN_OFF)

    # Without TURN_OFF, HVACMode.OFF is not injected
    entity.coordinator.data = MagicMock()
    entity.coordinator.data.hvac_modes = [HVACMode.COOL]
    assert entity.hvac_modes == [HVACMode.COOL]
    assert HVACMode.OFF not in entity.hvac_modes

    # 2. Power adds TURN_ON | TURN_OFF
    base_climate_entity.coordinator.controller.operations = [
        ATTR_POWER,
        ATTR_PRESET_MODE,
    ]
    entity_power = ClimateIP(
        base_climate_entity.coordinator,
        base_climate_entity.entity_description,
    )
    assert entity_power.supported_features == (
        ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    assert entity_power.supported_features & ClimateEntityFeature.TURN_ON
    assert entity_power.supported_features & ClimateEntityFeature.TURN_OFF


def test_climate_extra_state_attributes_filtering(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants in extra_state_attributes filtering out core attributes."""
    base_climate_entity.coordinator.controller.state_attributes = {
        HA_ATTR_TEMPERATURE: 22.0,
        ATTR_HVAC_MODE: HVACMode.COOL,
        "custom_attribute_1": "value1",
        "custom_attribute_2": 42,
    }

    extra_attrs = base_climate_entity.extra_state_attributes
    assert extra_attrs == {
        "custom_attribute_1": "value1",
        "custom_attribute_2": 42,
    }


def test_climate_temperature_boundaries() -> None:
    """Kill mutants in min_temp and max_temp extraction and fallbacks."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_boundary_id"
    mock_coord.entry = MagicMock(options={})
    mock_coord.device_info = MagicMock()
    mock_coord.controller = MagicMock()
    mock_coord.controller.operations = []

    # Valid property values
    mock_min_prop = MagicMock(value="17.5")
    mock_max_prop = MagicMock(value="31.0")
    mock_coord.controller.get_property_object.side_effect = lambda key: (
        mock_min_prop
        if key == ATTR_MIN_TEMP
        else mock_max_prop
        if key == ATTR_MAX_TEMP
        else None
    )

    desc = ClimateEntityDescription(key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coord, description=desc)
    assert entity.min_temp == 17.5
    assert entity.max_temp == 31.0

    # Fallback to defaults when get_property_object returns None
    mock_coord.controller.get_property_object.side_effect = None
    mock_coord.controller.get_property_object.return_value = None
    entity_fallback = ClimateIP(coordinator=mock_coord, description=desc)
    assert entity_fallback.min_temp == float(DEFAULT_CLIMATE_IP_TEMP_MIN)
    assert entity_fallback.max_temp == float(DEFAULT_CLIMATE_IP_TEMP_MAX)

    # Fallback when property value is invalid string
    mock_invalid = MagicMock(value="invalid_str")
    mock_coord.controller.get_property_object.return_value = mock_invalid
    entity_invalid = ClimateIP(coordinator=mock_coord, description=desc)
    assert entity_invalid.min_temp == float(DEFAULT_CLIMATE_IP_TEMP_MIN)
    assert entity_invalid.max_temp == float(DEFAULT_CLIMATE_IP_TEMP_MAX)


def test_climate_edge_cases_precision_and_boundary() -> None:
    """Test precision tenths, whole precision, and step fallback."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_step_id"
    mock_coord.device_info = MagicMock()
    mock_coord.entry = MagicMock(options={CONF_TARGET_TEMP_STEP: 0.1})
    mock_coord.controller = MagicMock()
    mock_coord.controller.operations = []
    mock_coord.controller.state_attributes = {}
    mock_coord.controller.get_property_object.return_value = None

    desc = ClimateEntityDescription(key="samsung_ac", translation_key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coord, description=desc)

    # Precision tenths (< 0.5)
    assert entity.precision == PRECISION_TENTHS
    assert entity.min_temp == 8.0

    # Default step (None) -> 1, precision whole
    mock_coord.entry.options = {}
    mock_coord.entry.data = {}
    entity_default_step = ClimateIP(coordinator=mock_coord, description=desc)
    assert entity_default_step.target_temperature_step == 1
    assert entity_default_step._attr_precision == PRECISION_WHOLE
    assert entity_default_step.precision == PRECISION_WHOLE

    # Fallback to entry.data when options is empty
    mock_coord.entry.options = {}
    mock_coord.entry.data = {CONF_TARGET_TEMP_STEP: 0.5}
    entity_data_step = ClimateIP(coordinator=mock_coord, description=desc)
    assert entity_data_step.target_temperature_step == 0.5
    assert entity_data_step.precision == PRECISION_HALVES


def test_climate_hvac_modes_append_off_and_temp_unit(
    base_climate_entity: ClimateIP,
) -> None:
    """Test HVACMode enum conversions, temperature_unit property, and None fallbacks."""
    # Configure coordinator data with raw strings to verify conversion to HVACMode enum
    base_climate_entity.coordinator.data.hvac_modes = ["cool", "heat"]
    base_climate_entity._attr_supported_features = ClimateEntityFeature.TURN_OFF

    modes = base_climate_entity.hvac_modes
    assert HVACMode.OFF in modes
    assert modes == [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]
    assert all(type(m) is HVACMode for m in modes)

    # Verify hvac_mode conversion when raw string is provided
    base_climate_entity.coordinator.data.hvac_mode = "cool"
    assert type(base_climate_entity.hvac_mode) is HVACMode
    assert base_climate_entity.hvac_mode is HVACMode.COOL

    # Verify temperature_unit L281
    assert (
        base_climate_entity.temperature_unit
        == base_climate_entity.hass.config.units.temperature_unit
    )
    assert base_climate_entity.temperature_unit == "°C"

    # Verify coordinator.data is None dynamic fallbacks
    base_climate_entity.coordinator.data = None
    assert base_climate_entity.hvac_modes == []
    assert base_climate_entity.fan_modes == []
    assert base_climate_entity.swing_modes == []
    assert base_climate_entity.preset_modes == []
    assert base_climate_entity.hvac_mode is None
    assert base_climate_entity.current_temperature is None
    assert base_climate_entity.target_temperature is None
    assert base_climate_entity.fan_mode is None
    assert base_climate_entity.swing_mode is None
    assert base_climate_entity.preset_mode is None


@pytest.mark.asyncio
async def test_modern_async_setup_entry() -> None:
    """Verify async_setup_entry for empty runtime_data and multi-device initialization."""
    # 1. Empty runtime_data aborts safely
    entry_empty = MagicMock(runtime_data={})
    async_add_empty = MagicMock()
    with patch("custom_components.climate_ip.climate._LOGGER.error") as mock_logger:
        await async_setup_entry(MagicMock(), entry_empty, async_add_empty)
    async_add_empty.assert_not_called()
    mock_logger.assert_called_once_with(
        "No valid entities could be initialized from the provided coordinators"
    )

    # 2. Multi-device path
    entry = MagicMock()
    entry.data = {"conf_key": "conf_val"}
    entry.unique_id = "main_entry_id"

    coord_1 = MagicMock(spec=SamsungClimateCoordinator)
    coord_1.unique_id = "dev_1"
    coord_1.device_info = MagicMock()
    coord_1.entry = MagicMock(options={})

    coord_2 = MagicMock(spec=SamsungClimateCoordinator)
    coord_2.unique_id = "dev_2"
    coord_2.device_info = MagicMock()
    coord_2.entry = MagicMock(options={})

    entry.runtime_data = {"dev_1": coord_1, "dev_2": coord_2}
    async_add_entities = MagicMock()

    with patch("custom_components.climate_ip.climate.ClimateIP") as mock_climate_class:
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    assert mock_climate_class.call_count == 2
    first_call_args = mock_climate_class.call_args_list[0].args
    assert len(first_call_args) == 2
    assert first_call_args[0] == coord_1
    assert first_call_args[1].key == "samsung_ac"
    async_add_entities.assert_called_once()
    assert len(async_add_entities.call_args[0][0]) == 2
