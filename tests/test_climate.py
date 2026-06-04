# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the ClimateIP climate entity."""
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate import HVACMode
from custom_components.climate_ip.climate import (
    ClimateIP,
    ClimateIPEntityDescription,
)
from custom_components.climate_ip.controller import ATTR_POWER
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant


async def test_turn_on_dry_helper(hass: HomeAssistant) -> None:
    """Test that turn_on and turn_off use the DRY helper _async_set_climate_mode."""

    # Mock the coordinator and its necessary attributes
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_unique_id"
    mock_coordinator.operations = [ATTR_POWER]
    mock_coordinator.data = MagicMock()
    mock_coordinator.log_prefix = "[TEST]"
    mock_coordinator.device_info = MagicMock()

    # Initialize the entity with description
    # pylint: disable=import-outside-toplevel,unexpected-keyword-arg
    description = ClimateIPEntityDescription(
        key="samsung_ac",
        translation_key="samsung_ac",
    )
    entity = ClimateIP(coordinator=mock_coordinator, description=description, config={})
    entity.hass = hass

    # Patch the helper function we want to verify is called
    with patch.object(entity, "_async_set_climate_mode", new_callable=AsyncMock) as mock_helper:

        # Test turn on
        await entity.async_turn_on()
        mock_helper.assert_awaited_once_with(ATTR_POWER, STATE_ON, None)
        mock_helper.reset_mock()

        # Test turn off
        await entity.async_turn_off()
        assert entity._attr_hvac_mode == HVACMode.OFF  # pylint: disable=import-outside-toplevel,protected-access
        mock_helper.assert_awaited_once_with(ATTR_POWER, STATE_OFF, None)



async def test_optimistic_turn_off(hass: HomeAssistant) -> None:
    """Verify that turning off predicts state immediately (predict and correct)."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_unique_id"
    mock_coordinator.operations = [ATTR_POWER]
    mock_coordinator.data = MagicMock()
    mock_coordinator.log_prefix = "[TEST]"
    mock_coordinator.device_info = MagicMock()

    # Setup mock for predict and correct
    mock_coordinator.async_predict_and_correct = AsyncMock(
        return_value=({"power": "off"}, {"power": "off"})
    )

    # pylint: disable=import-outside-toplevel,unexpected-keyword-arg
    description = ClimateIPEntityDescription(
        key="samsung_ac",
        translation_key="samsung_ac",
    )
    entity = ClimateIP(coordinator=mock_coordinator, description=description, config={})
    entity.hass = hass
    entity.entity_id = "climate.test_ac"
    entity._attr_hvac_mode = HVACMode.COOL  # Set initial state  # pylint: disable=import-outside-toplevel,protected-access

    # Use context manager for patch to bypass HA Core frame guard
    with patch.object(entity, "async_write_ha_state"):
        # Execute the method without patching _async_set_climate_mode
        # to evaluate the actual path
        await entity.async_turn_off()

    # The entity state should be instantly updated
    assert entity.hvac_mode == HVACMode.OFF



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


def test_climate_translation_key_and_device_info() -> None:
    """Test that ClimateIP correctly maps translation_key and device_info."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_unique_id"
    mock_coordinator.operations = ["power"]
    mock_coordinator.log_prefix = "[TEST]"
    mock_coordinator.data = MagicMock()
    mock_coordinator.device_info = {"identifiers": {("climate_ip", "test_unique_id")}}

    # pylint: disable=import-outside-toplevel,unexpected-keyword-arg
    description = ClimateIPEntityDescription(
        key="samsung_ac",
        translation_key="samsung_ac",
    )
    climate = ClimateIP(coordinator=mock_coordinator, description=description, config={})

    # Test Translation Key comes from description
    assert climate.translation_key == "samsung_ac"

    # Test Device Info matches Coordinator (Parent linkage)
    assert climate.device_info == mock_coordinator.device_info


async def test_auto_mode_correction_revert(hass: HomeAssistant) -> None:
    """Test that a PUSH update correctly reverts an incorrect optimistic state."""
    # This test ensures that if HA predicts "low" but the device says "auto",
    # the state machine eventually converges on the device truth.
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_flicker"
    mock_coordinator.operations = ["fan"]
    mock_coordinator.log_prefix = "[FLICKER]"
    mock_coordinator.device_info = MagicMock()
    mock_coordinator.last_update_success = True

    # 1. Hardware Truth: Fan is in "auto"
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
    mock_coordinator.data = mock_data

    # Mock async_predict_and_correct to return (predicted_data, corrections)
    mock_coordinator.async_predict_and_correct = AsyncMock(
        return_value=({}, {})
    )

    # pylint: disable=import-outside-toplevel,unexpected-keyword-arg
    description = ClimateIPEntityDescription(
        key="samsung_ac",
        translation_key="samsung_ac",
    )
    entity = ClimateIP(coordinator=mock_coordinator, description=description, config={})
    entity.hass = hass
    entity.entity_id = "climate.flicker_ac"

    # 2. User sets "low" (Optimistic Update)
    mock_coordinator.async_set_property = AsyncMock(return_value=True)

    with patch.object(entity, "async_write_ha_state"):
        await entity.async_set_fan_mode("low")

    # Verify optimistic prediction
    assert entity.fan_mode == "low"
    assert entity._attr_fan_mode == "low"  # pylint: disable=import-outside-toplevel,protected-access

    # 3. Device PUSH/POLL update arrives: It says "auto" (Hardware truth)
    # We update the coordinator data to reflect the real hardware state
    mock_data.fan_mode = "auto"

    # Trigger entity update
    with patch.object(entity, "async_write_ha_state") as mock_write:
        entity._handle_coordinator_update()  # pylint: disable=import-outside-toplevel,protected-access

    # 4. Verify Reconstruction: It should have reverted to "auto"
    assert entity.fan_mode == "auto"
    assert entity._attr_fan_mode == "auto"  # pylint: disable=import-outside-toplevel,protected-access
    mock_write.assert_called()




async def test_climate_init_options_priority_and_halves(hass: HomeAssistant) -> None:
    """Verify that entry options have priority and configure step=0.5."""
    from custom_components.climate_ip.climate import ClimateIP, ClimateIPEntityDescription
    from custom_components.climate_ip.const import CONF_TARGET_TEMP_STEP, CONF_TEMP_STEP
    from homeassistant.const import PRECISION_HALVES
    from unittest.mock import MagicMock

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
    from custom_components.climate_ip.climate import ClimateIP, ClimateIPEntityDescription
    from custom_components.climate_ip.const import CONF_TARGET_TEMP_STEP, CONF_TEMP_STEP
    from homeassistant.const import PRECISION_WHOLE
    from unittest.mock import MagicMock

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
    from custom_components.climate_ip.climate import ClimateIP, ClimateIPEntityDescription
    from custom_components.climate_ip.const import CONF_TEMP_STEP
    from unittest.mock import MagicMock

    mock_coordinator = MagicMock()
    mock_coordinator.entry = None

    # Only inject the legacy key
    config = {CONF_TEMP_STEP: 0.1}
    description = ClimateIPEntityDescription(key="samsung_ac")

    entity = ClimateIP(coordinator=mock_coordinator, description=description, config=config)

    from homeassistant.const import PRECISION_TENTHS
    # Lethal Assertion
    assert entity.target_temperature_step == 0.1, "Legacy temp_step key was not respected"
    assert entity.precision == PRECISION_TENTHS, "Precision was not adjusted to tenths"

async def test_climate_main_unique_id_fallback(hass: HomeAssistant) -> None:
    """Verify that _main_unique_id uses the provided value or falls back safely to the coordinator's unique_id."""
    from custom_components.climate_ip.climate import ClimateIP, ClimateIPEntityDescription
    from unittest.mock import MagicMock

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


async def test_climate_optimistic_side_effects(hass: HomeAssistant) -> None:
    """Verify that _apply_optimistic_corrections applies side effects correctly."""
    from custom_components.climate_ip.climate import ClimateIP, ClimateIPEntityDescription
    from homeassistant.components.climate import HVACMode
    from unittest.mock import MagicMock, AsyncMock, patch

    mock_coordinator = MagicMock()
    mock_coordinator.unique_id = "coord_side_effects"
    mock_coordinator.async_set_property = AsyncMock()
    
    # Simulate that when turning on, the device also corrects the fan_mode to "auto"
    mock_coordinator.async_predict_and_correct = AsyncMock(
        return_value=({}, {"fan_mode": "auto"})
    )
    
    description = ClimateIPEntityDescription(key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coordinator, description=description, config={})
    entity.hass = hass
    
    # Initial state
    entity._attr_fan_mode = "low"
    
    with patch.object(entity, "async_write_ha_state"):
        await entity.async_set_hvac_mode(HVACMode.COOL)
        
    # Lethal Assertion for Mutant 1 and 10: The side effect MUST be applied
    assert entity.fan_mode == "auto", "Optimistic corrections were not applied"

    # Lethal Assertion for Mutants 2-5 and 15-20: Exact arguments AND await execution MUST be present
    mock_coordinator.async_predict_and_correct.assert_awaited_once_with(
        mock_coordinator.data, "hvac_mode", HVACMode.COOL
    )
    mock_coordinator.async_set_property.assert_awaited_once_with(
        "hvac_mode", HVACMode.COOL, {"fan_mode": "auto"}
    )

async def test_climate_init_precision_whole(hass: HomeAssistant) -> None:
    """Verify that a step > 0.5 (like 1.0) explicitly assigns PRECISION_WHOLE."""
    from custom_components.climate_ip.climate import ClimateIP, ClimateIPEntityDescription
    from custom_components.climate_ip.const import CONF_TARGET_TEMP_STEP
    from homeassistant.const import PRECISION_WHOLE
    from unittest.mock import MagicMock

    mock_coordinator = MagicMock()
    mock_coordinator.entry = None

    config = {CONF_TARGET_TEMP_STEP: 1.0}
    description = ClimateIPEntityDescription(key="samsung_ac")

    entity = ClimateIP(coordinator=mock_coordinator, description=description, config=config)

    assert entity.target_temperature_step == 1.0, "Step was not configured to 1.0"
    assert entity.precision == PRECISION_WHOLE, "Step 1.0 did not assign PRECISION_WHOLE"

async def test_climate_sync_data_full(hass: HomeAssistant) -> None:
    """Verify that _sync_data_from_coordinator correctly copies all properties when state is present."""
    from custom_components.climate_ip.climate import ClimateIP, ClimateIPEntityDescription
    from homeassistant.components.climate import HVACMode
    from unittest.mock import MagicMock

    mock_coordinator = MagicMock()
    mock_coordinator.unique_id = "test_sync_full"
    
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
    
    mock_coordinator.data = mock_state

    description = ClimateIPEntityDescription(key="samsung_ac")
    entity = ClimateIP(coordinator=mock_coordinator, description=description, config={})
    entity.hass = hass
    
    # Entity __init__ calls _sync_data_from_coordinator, but let's call it explicitly to be sure
    entity._sync_data_from_coordinator()

    # Lethal Assertions for Mutants 2, 11, 12
    assert entity.hvac_mode == HVACMode.HEAT, "hvac_mode was not synchronized"
    assert entity.target_temperature == 25.0, "target_temperature was not synchronized"
    assert entity.current_temperature == 22.0, "current_temperature was not synchronized"
    assert entity.fan_mode == "high", "fan_mode was not synchronized"
    assert entity.swing_mode == "vertical", "swing_mode was not synchronized"
    assert entity.preset_mode == "boost", "preset_mode was not synchronized"
    assert entity.hvac_modes == [HVACMode.HEAT, HVACMode.OFF], "hvac_modes was not synchronized"
    assert entity.fan_modes == ["high", "low"], "fan_modes was not synchronized"
    assert entity.swing_modes == ["vertical", "horizontal"], "swing_modes was not synchronized"
    assert entity.preset_modes == ["boost", "eco"], "preset_modes was not synchronized"

async def test_climate_sync_data_none(hass: HomeAssistant) -> None:
    """Verify that _sync_data_from_coordinator falls back correctly when state is None."""
    from custom_components.climate_ip.climate import ClimateIP, ClimateIPEntityDescription
    from unittest.mock import MagicMock

    mock_coordinator = MagicMock()
    mock_coordinator.unique_id = "test_sync_none"
    mock_coordinator.data = None

    description = ClimateIPEntityDescription(key="samsung_ac")
    
    # Initialize with a state to ensure it resets
    entity = ClimateIP(coordinator=mock_coordinator, description=description, config={})
    entity.hass = hass
    
    # Force initial values to non-None/non-empty to test the reset
    entity._attr_hvac_mode = "dummy"
    entity._attr_target_temperature = 99.0
    entity._attr_current_temperature = 99.0
    entity._attr_fan_mode = "dummy"
    entity._attr_swing_mode = "dummy"
    entity._attr_preset_mode = "dummy"
    entity._attr_hvac_modes = ["dummy"]
    entity._attr_fan_modes = ["dummy"]
    entity._attr_swing_modes = ["dummy"]
    entity._attr_preset_modes = ["dummy"]
    
    # Trigger the fallback block
    entity._sync_data_from_coordinator()

    # Lethal Assertions for Mutants 13-19: Must be strictly None or []
    assert entity.hvac_mode is None, "hvac_mode did not reset to None"
    assert entity.target_temperature is None, "target_temperature did not reset to None"
    assert entity.current_temperature is None, "current_temperature did not reset to None"
    assert entity.fan_mode is None, "fan_mode did not reset to None"
    assert entity.swing_mode is None, "swing_mode did not reset to None"
    assert entity.preset_mode is None, "preset_mode did not reset to None"
    assert entity.hvac_modes == [], "hvac_modes did not reset to []"
    assert entity.fan_modes == [], "fan_modes did not reset to []"
    assert entity.swing_modes == [], "swing_modes did not reset to []"
    assert entity.preset_modes == [], "preset_modes did not reset to []"

async def test_public_async_set_hvac_mode_behavior(hass: HomeAssistant) -> None:
    """Verify local state change and network output of the HVAC delegator."""
    from custom_components.climate_ip.climate import ClimateIP
    from homeassistant.components.climate import ATTR_HVAC_MODE, HVACMode
    from unittest.mock import AsyncMock, MagicMock
    
    mock_coord = MagicMock()
    # Simulate that the async predictor does not require additional corrections
    mock_coord.async_predict_and_correct = AsyncMock(return_value=({}, {}))
    mock_coord.async_set_property = AsyncMock()
    
    entity = ClimateIP(coordinator=mock_coord, description=MagicMock(), config={})
    entity.async_write_ha_state = MagicMock()
    
    # Establish an initial state
    entity._attr_hvac_mode = HVACMode.OFF
    
    # Execute the public API just as Home Assistant would
    await entity.async_set_hvac_mode(HVACMode.COOL)
    
    # LETHAL ASSERTIONS (Mutants 7 and 8)
    # 1. Verify that the local string ("_attr_hvac_mode") was applied correctly:
    assert entity._attr_hvac_mode == HVACMode.COOL, "Local state was not updated (leak in local_attr variable)"
    
    # 2. Verify that the network output uses the appropriate constant and correct values:
    mock_coord.async_set_property.assert_awaited_once_with(ATTR_HVAC_MODE, HVACMode.COOL, {})

async def test_public_async_set_fan_mode_behavior(hass: HomeAssistant) -> None:
    """Verify local state change and network output of the Fan delegator."""
    from custom_components.climate_ip.climate import ClimateIP
    from homeassistant.components.climate import ATTR_FAN_MODE 
    from unittest.mock import AsyncMock, MagicMock
    
    mock_coord = MagicMock()
    mock_coord.async_predict_and_correct = AsyncMock(return_value=({}, {}))
    mock_coord.async_set_property = AsyncMock()
    
    entity = ClimateIP(coordinator=mock_coord, description=MagicMock(), config={})
    entity.async_write_ha_state = MagicMock()
    
    # Prerequisite: The mode must exist in available options or the function's guard will abort
    entity._attr_fan_modes = ["low", "high"]
    entity._attr_fan_mode = "low"
    
    # Execute the public API
    await entity.async_set_fan_mode("high")
    
    # LETHAL ASSERTIONS (Mutant 2)
    # 1. Check state update
    assert entity._attr_fan_mode == "high", "Local fan state was not updated."
    
    # 2. Rigorously check the async signature towards the coordinator
    mock_coord.async_set_property.assert_awaited_once_with(ATTR_FAN_MODE, "high", {})
