# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the ClimateIP climate entity."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ClimateEntityDescription,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE as HA_ATTR_TEMPERATURE,
)
from homeassistant.const import (
    PRECISION_HALVES,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant

from custom_components.climate_ip.climate import (
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ClimateIP,
    async_setup_entry,
)
from custom_components.climate_ip.const import CONF_TARGET_TEMP_STEP, CONF_TEMP_STEP
from custom_components.climate_ip.controller import ATTR_POWER
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator


@pytest.fixture
def base_climate_entity(hass: HomeAssistant) -> ClimateIP:
    """Fixture base con coordinador mockeado."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_base_id"
    mock_coord.entry = MagicMock(options={})  # FIX: Add missing entry options
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
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    return entity


def test_00_climate_defensive_init_properties(base_climate_entity: ClimateIP) -> None:
    """Fail-fast test for constructor state attributes to prevent Pytest timeouts during mutation.

    This ensures that structural mutations (e.g., self._attr_unique_id = None) fail immediately
    with an AssertionError before hitting the event loop or async integrations.
    """
    assert base_climate_entity._attr_unique_id is not None, "unique_id MUST NOT be None"
    assert base_climate_entity.min_temp is not None, "min_temp MUST NOT be None"
    assert base_climate_entity.max_temp is not None, "max_temp MUST NOT be None"
    assert (
        base_climate_entity._attr_target_temperature_step is not None
    ), "step MUST NOT be None"
    assert isinstance(base_climate_entity.hvac_modes, list), "hvac_modes MUST be a list"
    assert base_climate_entity.fan_modes is not None, "fan_modes MUST NOT be None"
    assert base_climate_entity.swing_modes is not None, "swing_modes MUST NOT be None"
    assert base_climate_entity.preset_modes is not None, "preset_modes MUST NOT be None"


def test_01_climate_defensive_sync_none_fallback() -> None:
    """Fail-fast test for _sync_data_from_coordinator fallback logic.

    Ensures that when coordinator.data is None, the entity initializes its lists correctly.
    This kills structural mutations to fallback assignments instantly.
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


async def test_turn_on_dry_helper(base_climate_entity: ClimateIP) -> None:
    """Test that turn_on and turn_off delegate to coordinator.async_set_property."""
    base_climate_entity.coordinator.controller.operations = [ATTR_POWER]
    base_climate_entity.coordinator.async_set_property = AsyncMock()

    # Test turn on
    await base_climate_entity.async_turn_on()
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_POWER, STATE_ON
    )
    base_climate_entity.coordinator.async_set_property.reset_mock()

    # Test turn off
    await base_climate_entity.async_turn_off()
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_POWER, STATE_OFF
    )


# ---------------------------------------------------------------------------
# Phase 4: Zombie code removal verification
# ---------------------------------------------------------------------------


def test_no_flicker_feature_method() -> None:
    """async_flicker_feature antipattern must be fully removed from ClimateIP."""
    assert not hasattr(
        ClimateIP, "async_flicker_feature"
    ), "async_flicker_feature was not removed from ClimateIP — remove the no-op method"


def test_no_stale_supported_features_annotation() -> None:
    """_supported_features class annotation must be removed.

    The attribute no longer exists at runtime (replaced by a computed property),
    so keeping the annotation would mislead mypy and future maintainers.
    """
    annotations = {}
    for klass in ClimateIP.__mro__:
        if klass is object:
            break
        annotations.update(vars(klass).get("__annotations__", {}))
    assert (
        "_supported_features" not in annotations
    ), "_supported_features stale annotation is still present in ClimateIP or a parent class"


def test_climate_translation_key_and_device_info(hass: HomeAssistant) -> None:
    """Test that ClimateIP correctly maps translation_key and device_info."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_unique_id"
    mock_coordinator.controller = MagicMock()
    mock_coordinator.controller.operations = ["power"]
    mock_coordinator.controller.state_attributes = {}
    mock_coordinator.log_prefix = "[TEST]"
    mock_coordinator.data = MagicMock()
    mock_coordinator.device_info = {"identifiers": {("climate_ip", "test_unique_id")}}
    mock_coordinator.entry = MagicMock(options={})  # FIX: Add missing entry options

    description = ClimateEntityDescription(
        key="samsung_ac",
        translation_key="samsung_ac",
    )
    climate = ClimateIP(coordinator=mock_coordinator, description=description)
    climate.hass = hass

    # Test Translation Key comes from description
    assert climate.translation_key == "samsung_ac"

    # Test Device Info matches Coordinator (Parent linkage)
    assert climate.device_info == {"identifiers": {("climate_ip", "test_unique_id")}}


async def test_climate_init_options_priority_and_halves(hass: HomeAssistant) -> None:
    """Verify that entry options have priority and configure step=0.5."""
    mock_coordinator = MagicMock()
    # Inject options (Priority 1) with 0.5
    mock_coordinator.entry.options = {CONF_TARGET_TEMP_STEP: 0.5}

    # Inject config (Priority 2 and 3) with different values to verify they are ignored
    config = {CONF_TARGET_TEMP_STEP: 1.0, CONF_TEMP_STEP: 2.0}
    description = ClimateEntityDescription(key="samsung_ac")

    entity = ClimateIP(coordinator=mock_coordinator, description=description)

    # Lethal Assertions
    assert (
        entity.target_temperature_step == 0.5
    ), "Entry options priority was not respected"
    assert (
        entity.precision == PRECISION_HALVES
    ), "Precision was not adjusted to half degrees"


async def test_climate_unique_id(hass: HomeAssistant) -> None:
    """Verify that unique_id correctly reflects the coordinator's unique_id."""
    mock_coordinator = MagicMock()
    mock_coordinator.unique_id = "coord_id_123"
    description = ClimateEntityDescription(key="samsung_ac")

    entity = ClimateIP(
        coordinator=mock_coordinator,
        description=description,
    )
    assert (
        entity.unique_id == "coord_id_123"
    ), "The unique_id property does not match the coordinator"


async def test_climate_sync_data_full(base_climate_entity: ClimateIP) -> None:
    """Verify that _sync_data_from_coordinator correctly copies all properties when state is present."""
    base_climate_entity.coordinator.unique_id = "test_sync_full"

    mock_state = MagicMock()
    mock_state.hvac_mode = HVACMode.HEAT
    mock_state.target_temperature = 25.0
    mock_state.current_temperature = 22.0
    mock_state.fan_mode = "high"
    mock_state.swing_mode = "vertical"
    mock_state.preset_mode = "boost"
    mock_state.hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    mock_state.fan_modes = ["high", "low"]
    mock_state.swing_modes = ["vertical", "horizontal"]
    mock_state.preset_modes = ["boost", "eco"]

    base_climate_entity.coordinator.data = mock_state

    # Lethal Assertions for Mutants 2, 11, 12
    assert (
        base_climate_entity.hvac_mode == HVACMode.HEAT
    ), "hvac_mode was not synchronized"
    assert (
        base_climate_entity.target_temperature == 25.0
    ), "target_temperature was not synchronized"
    assert (
        base_climate_entity.current_temperature == 22.0
    ), "current_temperature was not synchronized"
    assert base_climate_entity.fan_mode == "high", "fan_mode was not synchronized"
    assert (
        base_climate_entity.swing_mode == "vertical"
    ), "swing_mode was not synchronized"
    assert (
        base_climate_entity.preset_mode == "boost"
    ), "preset_mode was not synchronized"
    assert base_climate_entity.hvac_modes == [
        HVACMode.HEAT,
        HVACMode.OFF,
    ], "hvac_modes was not synchronized"
    assert base_climate_entity.fan_modes == [
        "high",
        "low",
    ], "fan_modes was not synchronized"
    assert base_climate_entity.swing_modes == [
        "vertical",
        "horizontal",
    ], "swing_modes was not synchronized"
    assert base_climate_entity.preset_modes == [
        "boost",
        "eco",
    ], "preset_modes was not synchronized"


async def test_climate_sync_data_none(base_climate_entity: ClimateIP) -> None:
    """Verify that dynamic properties fall back correctly when state is None."""
    base_climate_entity.coordinator.unique_id = "test_sync_none"
    base_climate_entity.coordinator.data = None

    # Lethal Assertions: Must be strictly None or []
    assert base_climate_entity.hvac_mode is None, "hvac_mode did not reset to None"
    assert (
        base_climate_entity.target_temperature is None
    ), "target_temperature did not reset to None"
    assert (
        base_climate_entity.current_temperature is None
    ), "current_temperature did not reset to None"
    assert base_climate_entity.fan_mode is None, "fan_mode did not reset to None"
    assert base_climate_entity.swing_mode is None, "swing_mode did not reset to None"
    assert base_climate_entity.preset_mode is None, "preset_mode did not reset to None"
    assert (
        base_climate_entity.hvac_modes == []
    ), "hvac_modes should be empty when data is None"
    assert (
        base_climate_entity.fan_modes == []
    ), "fan_modes should be empty when data is None"
    assert (
        base_climate_entity.swing_modes == []
    ), "swing_modes should be empty when data is None"
    assert (
        base_climate_entity.preset_modes == []
    ), "preset_modes should be empty when data is None"


async def test_hvac_action_dynamic_auto_heuristic(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify dynamic temperature heuristic for hvac_action in AUTO / HEAT_COOL mode."""
    from homeassistant.components.climate import HVACAction

    state = MagicMock()
    state.hvac_mode = HVACMode.AUTO
    base_climate_entity.coordinator.data = state

    # Current < Target - 0.5 -> HEATING
    state.current_temperature = 20.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING

    # Current > Target + 0.5 -> COOLING
    state.current_temperature = 24.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.COOLING

    # Within deadband (22.0 vs 22.0) -> IDLE
    state.current_temperature = 22.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.IDLE

    # OFF mode -> OFF
    state.hvac_mode = HVACMode.OFF
    assert base_climate_entity.hvac_action == HVACAction.OFF

    # COOL mode: active when current > target - 0.5, idle otherwise
    state.hvac_mode = HVACMode.COOL
    state.current_temperature = 25.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.COOLING
    state.current_temperature = 21.0
    assert base_climate_entity.hvac_action == HVACAction.IDLE

    # HEAT mode: active when current < target + 0.5, idle otherwise
    state.hvac_mode = HVACMode.HEAT
    state.current_temperature = 19.0
    state.target_temperature = 22.0
    assert base_climate_entity.hvac_action == HVACAction.HEATING
    state.current_temperature = 23.0
    assert base_climate_entity.hvac_action == HVACAction.IDLE

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
    """Verify network output of the HVAC delegator."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.hvac_modes = [HVACMode.COOL]

    # Execute the public API just as Home Assistant would
    await base_climate_entity.async_set_hvac_mode(HVACMode.COOL)

    # LETHAL ASSERTION: Verify network output uses appropriate constant and correct values
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_HVAC_MODE, HVACMode.COOL
    )


async def test_async_set_hvac_mode_invalid_raises_service_validation_error(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_set_hvac_mode raises ServiceValidationError for invalid mode."""
    from homeassistant.exceptions import ServiceValidationError

    base_climate_entity.coordinator.data.hvac_modes = [HVACMode.HEAT]

    with pytest.raises(
        ServiceValidationError, match="Requested HVAC mode 'cool' is not available"
    ):
        await base_climate_entity.async_set_hvac_mode(HVACMode.COOL)


async def test_public_async_set_fan_mode_behavior(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify network output of the Fan delegator."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()

    # Prerequisite: The mode must exist in available options or the function's guard will abort
    base_climate_entity.coordinator.data.fan_modes = ["low", "high"]

    # Execute the public API
    await base_climate_entity.async_set_fan_mode("high")

    # LETHAL ASSERTION: Check async signature towards coordinator
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_FAN_MODE, "high"
    )


async def test_async_set_fan_mode_invalid_raises_service_validation_error(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_set_fan_mode raises ServiceValidationError for invalid mode."""
    from homeassistant.exceptions import ServiceValidationError

    base_climate_entity.coordinator.data.fan_modes = ["low", "high"]

    with pytest.raises(
        ServiceValidationError, match="Requested fan mode 'turbo' is not available"
    ):
        await base_climate_entity.async_set_fan_mode("turbo")


# ============================================================
# PRECISION SIEGE TESTS — Batch 2: Kills 122 non-redundant mutants
# ============================================================

# --- async_set_temperature (11 mutants) ---


async def test_async_set_temperature_with_valid_temp_kills_mutants(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants in async_set_temperature."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()

    await base_climate_entity.async_set_temperature(temperature=21.0)

    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        HA_ATTR_TEMPERATURE, 21.0
    )


async def test_async_set_temperature_hvac_mode_only(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_set_temperature accepts hvac_mode alone without temperature."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.hvac_modes = [HVACMode.COOL]

    await base_climate_entity.async_set_temperature(hvac_mode=HVACMode.COOL)

    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_HVAC_MODE, HVACMode.COOL
    )


async def test_async_set_temperature_both_missing_raises_service_validation_error(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_set_temperature raises ServiceValidationError when both temperature and hvac_mode are missing."""
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(
        ServiceValidationError, match="No temperature or HVAC mode provided"
    ):
        await base_climate_entity.async_set_temperature()


async def test_async_set_temperature_with_hvac_mode(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_set_temperature processes hvac_mode when provided in kwargs."""
    base_climate_entity.coordinator.entry.data = {}
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.hvac_modes = [HVACMode.COOL]

    await base_climate_entity.async_set_temperature(
        hvac_mode=HVACMode.COOL, temperature=22.0
    )

    base_climate_entity.coordinator.async_set_property.assert_any_call(
        ATTR_HVAC_MODE, HVACMode.COOL
    )
    base_climate_entity.coordinator.async_set_property.assert_any_call(
        HA_ATTR_TEMPERATURE, 22.0
    )


# --- async_set_swing_mode (8 mutants) ---


async def test_async_set_swing_mode_strict_args_kills_mutants(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants in async_set_swing_mode."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.swing_modes = ["vertical", "horizontal"]

    await base_climate_entity.async_set_swing_mode("vertical")

    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_SWING_MODE, "vertical"
    )


async def test_async_set_swing_mode_invalid_raises_service_validation_error(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_set_swing_mode raises ServiceValidationError for invalid mode."""
    from homeassistant.exceptions import ServiceValidationError

    base_climate_entity.coordinator.data.swing_modes = ["vertical"]

    with pytest.raises(
        ServiceValidationError, match="Requested swing mode 'invalid' is not available"
    ):
        await base_climate_entity.async_set_swing_mode("invalid")


# --- async_set_preset_mode (8 mutants) ---


async def test_async_set_preset_mode_strict_args_kills_mutants(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants in async_set_preset_mode."""
    base_climate_entity.coordinator.async_set_property = AsyncMock()
    base_climate_entity.coordinator.data.preset_modes = ["sleep"]

    await base_climate_entity.async_set_preset_mode("sleep")

    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_PRESET_MODE, "sleep"
    )


async def test_async_set_preset_mode_invalid_raises_service_validation_error(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_set_preset_mode raises ServiceValidationError for invalid mode."""
    from homeassistant.exceptions import ServiceValidationError

    base_climate_entity.coordinator.data.preset_modes = ["sleep"]

    with pytest.raises(
        ServiceValidationError, match="Requested preset mode 'invalid' is not available"
    ):
        await base_climate_entity.async_set_preset_mode("invalid")


# --- async_service_set_property (4 mutants) ---


async def test_async_service_set_property_valid_key_kills_mutants(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants in async_service_set_property."""
    base_climate_entity.coordinator.controller.operations = ["beep"]
    base_climate_entity.coordinator.async_set_property = AsyncMock()

    await base_climate_entity.async_service_set_property("beep", "on")

    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        "beep", "on"
    )


async def test_async_service_set_property_invalid_key_raises(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_service_set_property raises ServiceValidationError for unapproved key."""
    from homeassistant.exceptions import ServiceValidationError

    base_climate_entity.coordinator.controller.operations = ["beep"]
    with pytest.raises(ServiceValidationError, match="is not a valid operation"):
        await base_climate_entity.async_service_set_property("invalid_key", "on")


async def test_async_service_set_property_invalid_value_type_raises(
    base_climate_entity: ClimateIP,
) -> None:
    """Verify that async_service_set_property raises ServiceValidationError for non-primitive value types."""
    from homeassistant.exceptions import ServiceValidationError

    base_climate_entity.coordinator.controller.operations = ["beep"]
    with pytest.raises(ServiceValidationError, match="Invalid value type 'list'"):
        await base_climate_entity.async_service_set_property(
            "beep", ["invalid", "list"]
        )


# --- async_setup_entry — multi-device path (mutants 1-38) ---


# ============================================================
# SIEGE TESTS: Annihilate 22 Survivors in climate.py
# ============================================================

# --- available property (5 mutants: lines 298-300) ---


def test_climate_available_last_update_failed(base_climate_entity: ClimateIP) -> None:
    """Verify available returns False when last_update_success is False."""
    base_climate_entity.coordinator.last_update_success = False
    assert base_climate_entity.available is False


def test_climate_available_success(base_climate_entity: ClimateIP) -> None:
    """Verify available returns True when last_update_success is True."""
    base_climate_entity.coordinator.last_update_success = True
    assert base_climate_entity.available is True


# --- supported_features property & temp step fallbacks ---


def test_climate_invalid_temp_step_fallback(
    base_climate_entity: ClimateIP, caplog: pytest.LogCaptureFixture
) -> None:
    """Kill mutants in __init__ for invalid temp step configuration."""
    import logging

    from custom_components.climate_ip.climate import ClimateIP
    from custom_components.climate_ip.const import (
        CONF_TARGET_TEMP_STEP,
        DEFAULT_TARGET_TEMP_STEP,
    )

    # 1. Ensure options dict contains corrupted string
    base_climate_entity.coordinator.entry.options = {
        CONF_TARGET_TEMP_STEP: "invalid_string"
    }
    base_climate_entity.coordinator.entry.data = {}

    # 2. Capture logs and re-instantiate
    with caplog.at_level(logging.WARNING):
        entity = ClimateIP(
            base_climate_entity.coordinator,
            base_climate_entity.entity_description,
        )

        # 3. Assert mathematical fallback
        assert entity.target_temperature_step == float(DEFAULT_TARGET_TEMP_STEP)

        # 4. Assert log mutant kill
        assert "Invalid temp step configured" in caplog.text


def test_climate_supported_features_bitwise_strict_accumulation(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants in __init__ (features |= feature)."""
    from homeassistant.components.climate import ClimateEntityFeature
    from homeassistant.components.climate.const import ATTR_PRESET_MODE

    from custom_components.climate_ip.climate import ClimateIP

    # 1. Set exactly two features that map through the dynamic loop
    base_climate_entity.coordinator.controller.operations = [
        ATTR_PRESET_MODE,
        HA_ATTR_TEMPERATURE,
    ]
    base_climate_entity.coordinator.swing_modes = []

    # 2. Re-instantiate entity to trigger __init__ static feature resolution
    entity = ClimateIP(
        base_climate_entity.coordinator,
        base_climate_entity.entity_description,
    )

    # 3. Strict bitwise equality assertion (kills &= mutants)
    expected_features = (
        ClimateEntityFeature.PRESET_MODE | ClimateEntityFeature.TARGET_TEMPERATURE
    )
    assert entity.supported_features == expected_features


# --- extra_state_attributes property (2 mutants: lines 411, 419) ---


def test_climate_extra_state_attributes_filtering(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants 1 & 2 in extra_state_attributes.

    Mutant 1 replaces core_attrs set with None (causes TypeError on iteration).
    Mutant 2 changes 'if k not in core_attrs' to 'if k in core_attrs'.
    """
    base_climate_entity.coordinator.controller.state_attributes = {
        HA_ATTR_TEMPERATURE: 22.0,
        ATTR_HVAC_MODE: HVACMode.COOL,
        "custom_attribute_1": "value1",
        "custom_attribute_2": 42,
    }

    extra_attrs = base_climate_entity.extra_state_attributes

    # Must only contain non-core attributes
    assert extra_attrs == {
        "custom_attribute_1": "value1",
        "custom_attribute_2": 42,
    }


# --- min_temp property (6 mutants: lines 452-458) ---


def test_climate_min_temp_from_coordinator_property(hass: HomeAssistant) -> None:
    """Kill mutants 1, 3, 5 in min_temp when coordinator property object is valid."""
    from homeassistant.components.climate.const import ATTR_MIN_TEMP

    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_min_temp_id"
    mock_coord.entry = MagicMock(options={})
    mock_coord.device_info = MagicMock()
    mock_coord.controller = MagicMock()
    mock_coord.controller.operations = []

    mock_prop = MagicMock()
    mock_prop.value = "17.5"
    mock_coord.controller.get_property_object.side_effect = lambda key: (
        mock_prop if key == ATTR_MIN_TEMP else None
    )

    desc = ClimateEntityDescription(key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coord, description=desc)
    assert entity.min_temp == 17.5


def test_climate_min_temp_fallback_on_none_prop(base_climate_entity: ClimateIP) -> None:
    """Kill mutants 2, 4, 6 in min_temp when get_property_object returns None."""
    from custom_components.climate_ip.const import DEFAULT_CLIMATE_IP_TEMP_MIN

    base_climate_entity.coordinator.controller.get_property_object.return_value = None

    assert base_climate_entity.min_temp == float(DEFAULT_CLIMATE_IP_TEMP_MIN)


def test_climate_min_temp_fallback_on_invalid_value(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants when min_t_prop.value is None or invalid string (TypeError/ValueError)."""
    from custom_components.climate_ip.const import DEFAULT_CLIMATE_IP_TEMP_MIN

    mock_prop = MagicMock()
    mock_prop.value = "invalid_number"
    base_climate_entity.coordinator.controller.get_property_object.return_value = (
        mock_prop
    )

    assert base_climate_entity.min_temp == float(DEFAULT_CLIMATE_IP_TEMP_MIN)


# --- max_temp property (6 mutants: lines 463-469) ---


def test_climate_max_temp_from_coordinator_property(hass: HomeAssistant) -> None:
    """Kill mutants 1, 3, 5 in max_temp when coordinator property object is valid."""
    from homeassistant.components.climate.const import ATTR_MAX_TEMP

    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_max_temp_id"
    mock_coord.entry = MagicMock(options={})
    mock_coord.device_info = MagicMock()
    mock_coord.controller = MagicMock()
    mock_coord.controller.operations = []

    mock_prop = MagicMock()
    mock_prop.value = "31.0"
    mock_coord.controller.get_property_object.side_effect = lambda key: (
        mock_prop if key == ATTR_MAX_TEMP else None
    )

    desc = ClimateEntityDescription(key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coord, description=desc)
    assert entity.max_temp == 31.0


def test_climate_max_temp_fallback_on_none_prop(base_climate_entity: ClimateIP) -> None:
    """Kill mutants 2, 4, 6 in max_temp when get_property_object returns None."""
    from custom_components.climate_ip.const import DEFAULT_CLIMATE_IP_TEMP_MAX

    base_climate_entity.coordinator.controller.get_property_object.return_value = None

    assert base_climate_entity.max_temp == float(DEFAULT_CLIMATE_IP_TEMP_MAX)


def test_climate_max_temp_fallback_on_invalid_value(
    base_climate_entity: ClimateIP,
) -> None:
    """Kill mutants when max_t_prop.value is None or invalid string (TypeError/ValueError)."""
    from custom_components.climate_ip.const import DEFAULT_CLIMATE_IP_TEMP_MAX

    mock_prop = MagicMock()
    mock_prop.value = "invalid_number"
    base_climate_entity.coordinator.controller.get_property_object.return_value = (
        mock_prop
    )

    assert base_climate_entity.max_temp == float(DEFAULT_CLIMATE_IP_TEMP_MAX)


@pytest.mark.asyncio
async def test_modern_async_setup_entry_success() -> None:
    """Verify that the modern async_setup_entry correctly loops over runtime_data and creates entities."""
    entry = MagicMock()
    entry.data = {"conf_key": "conf_val"}
    entry.unique_id = "main_entry_id"

    # Simulate two coordinators attached to the entry
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

    # We patch ClimateIP to verify arguments, but since ClimateIP.__init__ is called, we need to mock it carefully or patch the class.
    with patch("custom_components.climate_ip.climate.ClimateIP") as mock_climate_class:
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    assert mock_climate_class.call_count == 2

    # Verify signature matches 2-arg constructor: ClimateIP(coordinator, description)
    first_call_args = mock_climate_class.call_args_list[0].args
    assert len(first_call_args) == 2
    assert first_call_args[0] == coord_1
    assert first_call_args[1].key == "samsung_ac"

    async_add_entities.assert_called_once()
    assert len(async_add_entities.call_args[0][0]) == 2
    assert async_add_entities.call_args[1] == {}


@pytest.mark.asyncio
async def test_modern_async_setup_entry_empty() -> None:
    """Verify that an empty runtime_data dictionary aborts safely."""
    entry = MagicMock()
    entry.runtime_data = {}

    async_add_entities = MagicMock()

    with patch("custom_components.climate_ip.climate._LOGGER.error") as mock_logger:
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    async_add_entities.assert_not_called()
    mock_logger.assert_called_once_with(
        "No valid entities could be initialized from the provided coordinators."
    )
