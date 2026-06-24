# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the ClimateIP climate entity."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from homeassistant.components.climate import HVACMode, ATTR_HVAC_MODE, ATTR_FAN_MODE
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    PRECISION_HALVES,
    PRECISION_WHOLE,
    PRECISION_TENTHS,
    ATTR_TEMPERATURE as HA_ATTR_TEMPERATURE,
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.helpers.issue_registry import IssueSeverity

from custom_components.climate_ip.climate import (
    ClimateIP,
    ClimateIPEntityDescription,
    ATTR_SWING_MODE,
    ATTR_PRESET_MODE,
    async_setup_entry,
    async_setup_platform,
    DOMAIN,
    CONF_DEVICES,
)
from custom_components.climate_ip.const import CONF_TARGET_TEMP_STEP, CONF_TEMP_STEP
from custom_components.climate_ip.controller import ATTR_POWER
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator


@pytest.fixture
def base_climate_entity(hass: HomeAssistant) -> ClimateIP:
    """Fixture base con coordinador mockeado."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_base_id"
    mock_coord.async_predict_and_correct = AsyncMock(return_value=({}, {}))
    mock_coord.async_set_property = AsyncMock()
    mock_coord.async_request_refresh = AsyncMock()
    mock_coord.device_info = MagicMock()
    mock_coord.data = MagicMock()

    desc = ClimateIPEntityDescription(key="samsung_ac", translation_key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coord, description=desc, config={})
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    return entity



async def test_turn_on_dry_helper(base_climate_entity: ClimateIP) -> None:
    """Test that turn_on and turn_off use the DRY helper _async_set_climate_mode."""
    base_climate_entity.coordinator.operations = [ATTR_POWER]

    # Patch the helper function we want to verify is called
    with patch.object(base_climate_entity, "_async_set_climate_mode", new_callable=AsyncMock) as mock_helper:
        # Test turn on
        await base_climate_entity.async_turn_on()
        mock_helper.assert_awaited_once_with(ATTR_POWER, STATE_ON, None)
        mock_helper.reset_mock()

        # Test turn off
        await base_climate_entity.async_turn_off()
        assert base_climate_entity._attr_hvac_mode == HVACMode.OFF
        mock_helper.assert_awaited_once_with(ATTR_POWER, STATE_OFF, None)


async def test_optimistic_turn_off(base_climate_entity: ClimateIP) -> None:
    """Verify that turning off predicts state immediately (predict and correct)."""
    base_climate_entity.coordinator.operations = [ATTR_POWER]
    base_climate_entity.coordinator.async_predict_and_correct = AsyncMock(
        return_value=({"power": "off"}, {"power": "off"})
    )
    base_climate_entity.entity_id = "climate.test_ac"
    base_climate_entity._attr_hvac_mode = HVACMode.COOL

    with patch.object(base_climate_entity, "async_write_ha_state"):
        await base_climate_entity.async_turn_off()

    assert base_climate_entity.hvac_mode == HVACMode.OFF


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


def test_climate_translation_key_and_device_info(base_climate_entity: ClimateIP) -> None:
    """Test that ClimateIP correctly maps translation_key and device_info."""
    assert base_climate_entity.translation_key == "samsung_ac"
    assert base_climate_entity.device_info is base_climate_entity.coordinator.device_info


async def test_auto_mode_correction_revert(base_climate_entity: ClimateIP) -> None:
    """Test that a PUSH update correctly reverts an incorrect optimistic state."""
    # This test ensures that if HA predicts "low" but the device says "auto",
    # the state machine eventually converges on the device truth.
    mock_data = MagicMock()
    mock_data.fan_mode = "auto"
    mock_data.fan_modes = ["auto", "low", "medium", "high"]
    mock_data.hvac_mode = HVACMode.COOL
    mock_data.hvac_modes = [HVACMode.COOL, HVACMode.OFF]
    mock_data.target_temperature = 24
    mock_data.current_temperature = 22
    mock_data.swing_mode = None
    mock_data.swing_modes = []
    mock_data.preset_mode = None
    mock_data.preset_modes = []
    base_climate_entity.coordinator.data = mock_data
    base_climate_entity.coordinator.unique_id = "test_flicker"
    base_climate_entity.coordinator.operations = ["fan"]
    base_climate_entity.coordinator.log_prefix = "[FLICKER]"
    base_climate_entity.coordinator.last_update_success = True

    base_climate_entity.entity_id = "climate.flicker_ac"
    base_climate_entity._attr_fan_mode = "low"
    base_climate_entity.coordinator.async_set_property.return_value = True

    with patch.object(base_climate_entity, "async_write_ha_state"):
        await base_climate_entity.async_set_fan_mode("low")

    # Verify optimistic prediction
    assert base_climate_entity.fan_mode == "low"
    assert base_climate_entity._attr_fan_mode == "low"

    # 3. Device PUSH/POLL update arrives: It says "auto" (Hardware truth)
    mock_data.fan_mode = "auto"

    # Trigger entity update
    with patch.object(base_climate_entity, "async_write_ha_state") as mock_write:
        base_climate_entity._handle_coordinator_update()

    # 4. Verify Reconstruction: It should have reverted to "auto"
    assert base_climate_entity.fan_mode == "auto"
    assert base_climate_entity._attr_fan_mode == "auto"
    mock_write.assert_called()




async def test_climate_init_options_priority_and_halves(hass: HomeAssistant) -> None:
    """Verify that entry options have priority and configure step=0.5."""
    mock_coordinator = MagicMock()
    # Inject options (Priority 1) with 0.5
    mock_coordinator.entry.options = {CONF_TARGET_TEMP_STEP: 0.5}
    
    # Inject config (Priority 2 and 3) with different values to verify they are ignored
    config = {CONF_TARGET_TEMP_STEP: 1.0, CONF_TEMP_STEP: 2.0}
    description = ClimateIPEntityDescription(key="samsung_ac")

    entity = ClimateIP(coordinator=mock_coordinator, description=description, config=config)

    # Lethal Assertions
    assert entity.target_temperature_step == 0.5, "Entry options priority was not respected"
    assert entity.precision == PRECISION_HALVES, "Precision was not adjusted to half degrees"

async def test_climate_init_config_priority_and_integer_cast(hass: HomeAssistant) -> None:
    """Verify that without options, it reads config directly, and that floats representing integers are cast to int."""
    mock_coordinator = MagicMock()
    mock_coordinator.entry = None  # Force the branch where there is no entry or options

    # CONF_TARGET_TEMP_STEP (Priority 2) is 2.0. CONF_TEMP_STEP (Priority 3) is 3.0.
    config = {CONF_TARGET_TEMP_STEP: 2.0, CONF_TEMP_STEP: 3.0}
    description = ClimateIPEntityDescription(key="samsung_ac")

    entity = ClimateIP(coordinator=mock_coordinator, description=description, config=config)

    # Lethal Assertions: Must be 2, and MUST be of type int (not float 2.0)
    assert entity.target_temperature_step == 2, "Config priority was not respected"
    assert isinstance(entity.target_temperature_step, int), "Integer cast failed (1.0 vs 1)"
    assert entity.precision == PRECISION_WHOLE, "Integer precision is incorrect"

async def test_climate_init_legacy_config_priority(hass: HomeAssistant) -> None:
    """Verify fallback to the legacy CONF_TEMP_STEP key."""
    mock_coordinator = MagicMock()
    mock_coordinator.entry = None

    # Only inject the legacy key
    config = {CONF_TEMP_STEP: 0.1}
    description = ClimateIPEntityDescription(key="samsung_ac")

    entity = ClimateIP(coordinator=mock_coordinator, description=description, config=config)

    # Lethal Assertion
    assert entity.target_temperature_step == 0.1, "Legacy temp_step key was not respected"
    assert entity.precision == PRECISION_TENTHS, "Precision was not adjusted to tenths"

async def test_climate_main_unique_id_fallback(hass: HomeAssistant) -> None:
    """Verify that _main_unique_id uses the provided value or falls back safely to the coordinator's unique_id."""
    mock_coordinator = MagicMock()
    mock_coordinator.unique_id = "coord_id_123"
    description = ClimateIPEntityDescription(key="samsung_ac")

    # Case 1: main_unique_id is provided explicitly
    entity_explicit = ClimateIP(coordinator=mock_coordinator, description=description, config={}, main_unique_id="explicit_id_456")
    assert entity_explicit._main_unique_id == "explicit_id_456", "Explicit main_unique_id was not respected"

    # Case 2: Not provided (None), must perform fallback
    entity_fallback = ClimateIP(coordinator=mock_coordinator, description=description, config={}, main_unique_id=None)
    assert entity_fallback._main_unique_id == "coord_id_123", "Fallback to coordinator.unique_id failed"
    assert entity_fallback.unique_id == "coord_id_123", "The unique_id property does not match the coordinator"
async def test_climate_optimistic_side_effects(base_climate_entity: ClimateIP) -> None:
    """Verify that _apply_optimistic_corrections applies side effects correctly."""
    base_climate_entity.coordinator.unique_id = "coord_side_effects"
    
    # Simulate that when turning on, the device also corrects the fan_mode to "auto"
    base_climate_entity.coordinator.async_predict_and_correct = AsyncMock(
        return_value=({}, {"fan_mode": "auto"})
    )
    
    # Initial state
    base_climate_entity._attr_fan_mode = "low"
    
    with patch.object(base_climate_entity, "async_write_ha_state"):
        await base_climate_entity.async_set_hvac_mode(HVACMode.COOL)
        
    # Lethal Assertion for Mutant 1 and 10: The side effect MUST be applied
    assert base_climate_entity.fan_mode == "auto", "Optimistic corrections were not applied"

    # Lethal Assertion for Mutants 2-5 and 15-20: Exact arguments AND await execution MUST be present
    base_climate_entity.coordinator.async_predict_and_correct.assert_awaited_once_with(
        base_climate_entity.coordinator.data, "hvac_mode", HVACMode.COOL
    )
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        "hvac_mode", HVACMode.COOL, {"fan_mode": "auto"}
    )

async def test_climate_init_precision_whole(hass: HomeAssistant) -> None:
    """Verify that a step > 0.5 (like 1.0) explicitly assigns PRECISION_WHOLE."""
    mock_coordinator = MagicMock()
    mock_coordinator.entry = None

    config = {CONF_TARGET_TEMP_STEP: 1.0}
    description = ClimateIPEntityDescription(key="samsung_ac")

    entity = ClimateIP(coordinator=mock_coordinator, description=description, config=config)

    assert entity.target_temperature_step == 1.0, "Step was not configured to 1.0"
    assert entity.precision == PRECISION_WHOLE, "Step 1.0 did not assign PRECISION_WHOLE"

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
    
    # Entity __init__ calls _sync_data_from_coordinator, but let's call it explicitly to be sure
    base_climate_entity._sync_data_from_coordinator()

    # Lethal Assertions for Mutants 2, 11, 12
    assert base_climate_entity.hvac_mode == HVACMode.HEAT, "hvac_mode was not synchronized"
    assert base_climate_entity.target_temperature == 25.0, "target_temperature was not synchronized"
    assert base_climate_entity.current_temperature == 22.0, "current_temperature was not synchronized"
    assert base_climate_entity.fan_mode == "high", "fan_mode was not synchronized"
    assert base_climate_entity.swing_mode == "vertical", "swing_mode was not synchronized"
    assert base_climate_entity.preset_mode == "boost", "preset_mode was not synchronized"
    assert base_climate_entity.hvac_modes == [HVACMode.HEAT, HVACMode.OFF], "hvac_modes was not synchronized"
    assert base_climate_entity.fan_modes == ["high", "low"], "fan_modes was not synchronized"
    assert base_climate_entity.swing_modes == ["vertical", "horizontal"], "swing_modes was not synchronized"
    assert base_climate_entity.preset_modes == ["boost", "eco"], "preset_modes was not synchronized"

async def test_climate_sync_data_none(base_climate_entity: ClimateIP) -> None:
    """Verify that _sync_data_from_coordinator falls back correctly when state is None."""
    base_climate_entity.coordinator.unique_id = "test_sync_none"
    base_climate_entity.coordinator.data = None
    
    # Force initial values to non-None/non-empty to test the reset
    base_climate_entity._attr_hvac_mode = "dummy"
    base_climate_entity._attr_target_temperature = 99.0
    base_climate_entity._attr_current_temperature = 99.0
    base_climate_entity._attr_fan_mode = "dummy"
    base_climate_entity._attr_swing_mode = "dummy"
    base_climate_entity._attr_preset_mode = "dummy"
    base_climate_entity._attr_hvac_modes = ["dummy"]
    base_climate_entity._attr_fan_modes = ["dummy"]
    base_climate_entity._attr_swing_modes = ["dummy"]
    base_climate_entity._attr_preset_modes = ["dummy"]
    
    # Trigger the fallback block
    base_climate_entity._sync_data_from_coordinator()

    # Lethal Assertions for Mutants 13-19: Must be strictly None or []
    assert base_climate_entity.hvac_mode is None, "hvac_mode did not reset to None"
    assert base_climate_entity.target_temperature is None, "target_temperature did not reset to None"
    assert base_climate_entity.current_temperature is None, "current_temperature did not reset to None"
    assert base_climate_entity.fan_mode is None, "fan_mode did not reset to None"
    assert base_climate_entity.swing_mode is None, "swing_mode did not reset to None"
    assert base_climate_entity.preset_mode is None, "preset_mode did not reset to None"
    assert base_climate_entity.hvac_modes == [], "hvac_modes did not reset to []"
    assert base_climate_entity.fan_modes == [], "fan_modes did not reset to []"
    assert base_climate_entity.swing_modes == [], "swing_modes did not reset to []"
    assert base_climate_entity.preset_modes == [], "preset_modes did not reset to []"

async def test_public_async_set_hvac_mode_behavior(base_climate_entity: ClimateIP) -> None:
    """Verify local state change and network output of the HVAC delegator."""
    # Simulate that the async predictor does not require additional corrections
    base_climate_entity.coordinator.async_predict_and_correct = AsyncMock(return_value=({}, {}))
    
    # Establish an initial state
    base_climate_entity._attr_hvac_mode = HVACMode.OFF
    
    # Execute the public API just as Home Assistant would
    await base_climate_entity.async_set_hvac_mode(HVACMode.COOL)
    
    # LETHAL ASSERTIONS (Mutants 7 and 8)
    # 1. Verify that the local string ("_attr_hvac_mode") was applied correctly:
    assert base_climate_entity._attr_hvac_mode == HVACMode.COOL, "Local state was not updated (leak in local_attr variable)"
    
    # 2. Verify that the network output uses the appropriate constant and correct values:
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(ATTR_HVAC_MODE, HVACMode.COOL, {})

async def test_public_async_set_fan_mode_behavior(base_climate_entity: ClimateIP) -> None:
    """Verify local state change and network output of the Fan delegator."""
    # Simulate that the async predictor does not require additional corrections
    base_climate_entity.coordinator.async_predict_and_correct = AsyncMock(return_value=({}, {}))
    
    # Prerequisite: The mode must exist in available options or the function's guard will abort
    base_climate_entity._attr_fan_modes = ["low", "high"]
    base_climate_entity._attr_fan_mode = "low"
    
    # Execute the public API
    await base_climate_entity.async_set_fan_mode("high")
    
    # LETHAL ASSERTIONS (Mutant 2)
    # 1. Check state update
    assert base_climate_entity._attr_fan_mode == "high", "Local fan state was not updated."
    
    # 2. Rigorously check the async signature towards the coordinator
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(ATTR_FAN_MODE, "high", {})


# ============================================================
# PRECISION SIEGE TESTS — Batch 2: Kills 122 non-redundant mutants
# ============================================================

# --- async_set_temperature (11 mutants) ---

async def test_async_set_temperature_with_valid_temp_kills_mutants(base_climate_entity: ClimateIP) -> None:
    """Kill mutants 1-11 in async_set_temperature.

    Mutants alter: kwargs lookup key, the 'is not None' guard, and all three
    positional arguments passed to _async_set_climate_mode.
    A strict assert_awaited_once_with covers all argument-swap variants.
    """
    # -- Path: temperature value is present → helper must be called exactly once --
    await base_climate_entity.async_set_temperature(temperature=21.0)

    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        HA_ATTR_TEMPERATURE, 21.0, {}
    )
    # Also verify the local attribute was updated (kills local_attr=None mutant)
    assert base_climate_entity._attr_target_temperature == 21.0


async def test_async_set_temperature_no_temp_kwarg_is_noop(base_climate_entity: ClimateIP) -> None:
    """Kill mutant 3 (is None inversion): when no temperature is passed the
    helper must NOT be called at all."""
    # Called with a keyword that is NOT ATTR_TEMPERATURE → no-op
    await base_climate_entity.async_set_temperature(hvac_mode=HVACMode.COOL)

    base_climate_entity.coordinator.async_set_property.assert_not_awaited()


# --- async_set_swing_mode (8 mutants) ---

async def test_async_set_swing_mode_strict_args_kills_mutants(base_climate_entity: ClimateIP) -> None:
    """Kill mutants 1-8 in async_set_swing_mode.

    Every mutant swaps one of the three positional arguments passed to
    _async_set_climate_mode (attr_name, mode_value, local_attr). The strict
    assert_called_once_with fires on any deviation.
    """
    base_climate_entity._attr_swing_modes = ["vertical", "horizontal"]

    await base_climate_entity.async_set_swing_mode("vertical")

    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_SWING_MODE, "vertical", {}
    )
    # Local attribute update must match the literal string "_attr_swing_mode"
    assert base_climate_entity._attr_swing_mode == "vertical"


# --- async_set_preset_mode (8 mutants) ---

async def test_async_set_preset_mode_strict_args_kills_mutants(base_climate_entity: ClimateIP) -> None:
    """Kill mutants 1-8 in async_set_preset_mode.

    Same pattern as swing: every mutant swaps one positional argument.
    """
    await base_climate_entity.async_set_preset_mode("sleep")

    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with(
        ATTR_PRESET_MODE, "sleep", {}
    )
    # Local attribute must carry the preset value
    assert base_climate_entity._attr_preset_mode == "sleep"


# --- async_service_set_property (4 mutants) ---

async def test_async_service_set_property_valid_key_kills_mutants(base_climate_entity: ClimateIP) -> None:
    """Kill mutants 1-4 in async_service_set_property.

    Mutants alter the literal 'key' string used in kwargs.get(), replace it
    with None, or with mangled variants. Providing the exact key and asserting
    both coordinator calls fires on any lookup deviation.
    """
    await base_climate_entity.async_service_set_property(key="beep", value="on")

    # Both downstream calls must fire with the exact extracted values
    base_climate_entity.coordinator.async_set_property.assert_awaited_once_with("beep", "on", {})
    base_climate_entity.coordinator.async_request_refresh.assert_awaited_once()


async def test_async_service_set_property_missing_key_is_noop(base_climate_entity: ClimateIP) -> None:
    """Complementary guard: when key is absent (None) the function must abort
    before calling coordinator. Kills any mutant that removes the 'if not key' guard."""
    await base_climate_entity.async_service_set_property(value="on")  # no 'key' kwarg

    base_climate_entity.coordinator.async_set_property.assert_not_awaited()
    base_climate_entity.coordinator.async_request_refresh.assert_not_awaited()


# --- async_setup_entry — multi-device path (mutants 1-38) ---

async def test_async_setup_entry_multi_device_kills_mutants() -> None:
    """Kill mutants 1-38 in async_setup_entry (multi-device branch).

    Critical checks:
    - coordinators comes from entry.runtime_data (mutant 1 replaces it with None)
    - device_info lookup uses CONF_DEVICES, 'd.get("id") == device_id' comparison (mutants 3-14)
    - ClimateIP receives the exact 5-tuple of arguments (mutants 15-33)
    - async_add_entities is called with update_before_add=True (mutants 34-38)
    """
    entry = MagicMock()
    entry.data = {
        CONF_DEVICES: [
            {"id": "dev1", "ip": "192.168.0.10"},
            {"id": "dev2", "ip": "192.168.0.20"},
        ]
    }
    entry.unique_id = "main_unique_id"

    mock_coord_1 = MagicMock()
    mock_coord_2 = MagicMock()
    entry.runtime_data = {"dev1": mock_coord_1, "dev2": mock_coord_2}

    async_add_entities = MagicMock()

    with patch("custom_components.climate_ip.climate.ClimateIP") as mock_climate_class:
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    # Two entities must have been created — one per device
    assert mock_climate_class.call_count == 2, "Expected exactly 2 ClimateIP instances"

    # --- Device 1 assertions ---
    c1_args = mock_climate_class.call_args_list[0].args
    coordinator_1, desc_1, data_1, device_info_1, uid_1 = c1_args
    assert coordinator_1 is mock_coord_1, "Coordinator mismatch for dev1 (mutant 1/23)"
    assert desc_1.key == "samsung_ac_dev1", "Key mismatch for dev1 (mutant 16/18)"
    assert desc_1.translation_key == "samsung_ac", "translation_key mismatch (mutant 17/20/21)"
    assert data_1 == dict(entry.data), "Data dict mismatch (mutant 25/33)"
    assert device_info_1 == {"id": "dev1", "ip": "192.168.0.10"}, (
        "device_info mismatch — device lookup filter is broken (mutants 3-14)"
    )
    assert uid_1 == "main_unique_id", "unique_id mismatch (mutant 27)"

    # --- Device 2 assertions (different coordinator / device_info) ---
    c2_args = mock_climate_class.call_args_list[1].args
    coordinator_2, desc_2, data_2, device_info_2, uid_2 = c2_args
    assert coordinator_2 is mock_coord_2, "Coordinator mismatch for dev2"
    assert desc_2.key == "samsung_ac_dev2"
    assert device_info_2 == {"id": "dev2", "ip": "192.168.0.20"}

    # --- async_add_entities must be called with update_before_add=True (mutants 34-38) ---
    async_add_entities.assert_called_once()
    call_args, call_kwargs = async_add_entities.call_args
    assert call_kwargs.get("update_before_add") is True, (
        "update_before_add must be True (mutant 35/38)"
    )
    assert len(call_args[0]) == 2, "Expected 2 entities in the list (mutant 34/36)"


async def test_async_setup_entry_multi_device_skips_unmatched_device_info() -> None:
    """Extra siege: when a coordinator's device_id has no matching entry in
    CONF_DEVICES, the entity must NOT be created.

    Kills mutants 3-5 that short-circuit the 'next()' generator to always
    return a truthy value or to skip the id-equality filter.
    """
    entry = MagicMock()
    entry.data = {
        CONF_DEVICES: [{"id": "known_device", "ip": "10.0.0.1"}]
    }
    entry.unique_id = "siege_uid"
    entry.runtime_data = {
        "known_device": MagicMock(),
        "unknown_device": MagicMock(),  # no match in CONF_DEVICES
    }

    async_add_entities = MagicMock()
    with patch("custom_components.climate_ip.climate.ClimateIP") as MockClimateIP:
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    # Only 1 entity may be created (the matched one)
    assert MockClimateIP.call_count == 1, (
        "Unmatched device_id must not produce an entity (mutants 3-14)"
    )


# --- async_setup_entry: CONF_DEVICES fallback boundary (mutants 8 and 10) ---

async def test_async_setup_entry_multi_device_missing_conf_fallback() -> None:
    """Kill mutants 8 and 10 in async_setup_entry.

    Both mutants corrupt the fallback argument of entry.data.get(CONF_DEVICES, []):
      - Mutant 8: changes [] to None  → generator crashes: TypeError: 'NoneType' not iterable
      - Mutant 10: removes the arg entirely → same crash

    The fix: inject an entry.data dict that does NOT contain CONF_DEVICES at all,
    forcing Python to evaluate the fallback.  The generator then yields no items,
    next() returns its default (None), and device_info is None — so no ClimateIP
    entity is created for that coordinator.  Any mutation of the fallback causes a
    TypeError that kills the mutant.
    """
    entry = MagicMock()
    # Deliberately omit CONF_DEVICES so the .get(CONF_DEVICES, []) fallback fires
    entry.data = {"other_irrelevant_key": "value"}
    entry.unique_id = "main_id"

    mock_coord_1 = MagicMock()
    entry.runtime_data = {"dev1": mock_coord_1}

    async_add_entities = MagicMock()

    with patch("custom_components.climate_ip.climate.ClimateIP") as mock_climate_class:
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    # No matching device_info → entity must NOT be created
    assert mock_climate_class.call_count == 0, (
        "No entity should be created when CONF_DEVICES is absent from entry.data "
        "(fallback must be [] not None — mutants 8/10)"
    )


# --- async_setup_entry — single-device path (mutants 39-59) ---

async def test_async_setup_entry_single_device_kills_mutants() -> None:
    """Kill mutants 39-59 in async_setup_entry (single-device fallback branch).

    The coordinator is taken directly from runtime_data (not iterated).
    Description must use the literal key 'samsung_ac' and translation_key 'samsung_ac'.
    device_info must be None.  unique_id comes from entry.unique_id.
    """
    entry = MagicMock()
    entry.data = {"ip": "10.0.0.5"}
    entry.unique_id = "single_uid_abc"
    mock_coord = MagicMock()
    entry.runtime_data = mock_coord  # not a dict → triggers else-branch

    async_add_entities = MagicMock()
    with patch("custom_components.climate_ip.climate.ClimateIP") as mock_climate_class:
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    assert mock_climate_class.call_count == 1

    coordinator, desc, data, device_info, uid = mock_climate_class.call_args.args
    assert coordinator is mock_coord, "Coordinator must be runtime_data directly (mutant 39)"
    assert desc.key == "samsung_ac", "key must be literal 'samsung_ac' (mutants 41/43/45/46)"
    assert desc.translation_key == "samsung_ac", (
        "translation_key must be 'samsung_ac' (mutants 42/44/47/48)"
    )
    assert data == dict(entry.data), "data must be a fresh dict copy (mutants 52/59)"
    assert device_info is None, "device_info must be None for single-device (mutant 26 analog)"
    assert uid == "single_uid_abc", "uid must come from entry.unique_id (mutants 53)"

    # async_add_entities must receive a single-element list (mutants 49-58)
    async_add_entities.assert_called_once()
    entities_arg = async_add_entities.call_args[0][0]
    assert len(entities_arg) == 1, "Must add exactly one entity (mutant 49)"


# --- async_setup_platform (32 mutants) ---

async def test_async_setup_platform_fresh_install_kills_mutants(
    hass: "HomeAssistant",
) -> None:
    """Kill mutants 1-40 in async_setup_platform.

    Verifies:
    - async_create_issue is called with the exact 8-field signature (mutants 1-20)
    - async_create_task is called with the exact task name (mutants 28/39/40)
    - async_init is called with DOMAIN, context={'source': SOURCE_IMPORT},
      data=config (mutants 31-38)

    NOTE: async_init is replaced by a plain MagicMock (not AsyncMock) so its
    return value passes directly to async_create_task without coroutine wrapping.
    This lets us do strict identity comparison on the payload.

    NOTE on patch target: async_create_issue is imported locally inside
    async_setup_platform via 'from homeassistant.helpers.issue_registry import ...'.
    The patch must target the function at its definition site, not on climate.py.
    """
    config = {"ip_address": "192.168.1.100"}

    # Plain MagicMock: return_value is the literal string, not a coroutine wrapper
    mock_flow_init = MagicMock(return_value="sentinel_task_payload")
    hass.config_entries.flow.async_init = mock_flow_init
    hass.config_entries.async_entries.return_value = []
    hass.async_create_task = MagicMock()

    with patch(
        "homeassistant.helpers.issue_registry.async_create_issue"
    ) as mock_issue:
        await async_setup_platform(hass, config, MagicMock())

    # -- Issue creation: all 8 kwargs must be exact (mutants 1-20) --
    mock_issue.assert_called_once_with(
        hass,
        DOMAIN,
        "deprecated_yaml",
        breaks_in_ha_version="2026.0.0",
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
    )

    # -- Flow init: correct domain, context key, and config payload (mutants 31-38) --
    mock_flow_init.assert_called_once_with(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=config
    )

    # -- Task creation: exact payload + name (mutants 27-30, 39-40) --
    hass.async_create_task.assert_called_once_with(
        "sentinel_task_payload", name="climate_ip_yaml_import"
    )

    # Aserción Transaccional: Mutante 24 (Blindaje del Anti-loop guard)
    # Exige que la consulta al registro de configuraciones use exactamente DOMAIN
    hass.config_entries.async_entries.assert_called_once_with(DOMAIN)


async def test_async_setup_platform_already_imported_skips_task(
    hass: "HomeAssistant",
) -> None:
    """Kill mutants that remove or invert the SOURCE_IMPORT anti-loop guard.

    When an existing SOURCE_IMPORT entry exists, async_create_task must NOT
    be called (early return path).
    """
    existing_entry = MagicMock()
    existing_entry.source = SOURCE_IMPORT

    with (
        patch("homeassistant.helpers.issue_registry.async_create_issue"),
        patch.object(hass, "async_create_task") as mock_create_task,
    ):
        hass.config_entries.async_entries.return_value = [existing_entry]
        await async_setup_platform(hass, {}, MagicMock())

    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_async_set_property_strict_args(base_climate_entity: ClimateIP):
    """
    Aniquila mutantes 1-4 en async_set_property.
    Asegura la delegación exacta de clave/valor al coordinador y la escritura de estado.
    """
    # Inyectamos valores específicos para evitar falsos positivos con defaults
    await base_climate_entity.async_set_property("power_mode", "turbo")
    
    # Asertamos la firma exacta hacia el coordinador
    base_climate_entity.coordinator.async_set_property.assert_called_once_with("power_mode", "turbo")
    
    # Asertamos la actualización síncrona en el core de HA
    base_climate_entity.async_write_ha_state.assert_called_once()
