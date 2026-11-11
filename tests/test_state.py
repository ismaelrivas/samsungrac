"""Tests for ClimateIPDeviceState strict typing, immutability, and contracts."""

from dataclasses import FrozenInstanceError

import pytest

from custom_components.climate_ip.state import ClimateIPDeviceState
from homeassistant.components.climate import HVACMode


@pytest.fixture(autouse=True)
def force_task_cancellation() -> None:
    """No-op override of async teardown fixture to eliminate event loop overhead."""
    return


@pytest.fixture(autouse=True)
def auto_clear_yaml_cache() -> None:
    """No-op override of yaml cache fixture for pure state unit tests."""
    return


def test_state_default_initialization() -> None:
    """Test creating ClimateIPDeviceState with default values."""
    state = ClimateIPDeviceState()

    assert state.hvac_mode is None
    assert state.target_temperature is None
    assert state.current_temperature is None
    assert state.fan_mode is None
    assert state.swing_mode is None
    assert state.preset_mode is None
    assert state.hvac_modes == ()
    assert state.fan_modes == ()
    assert state.swing_modes == ()
    assert state.preset_modes == ()


def test_state_valid_full_initialization() -> None:
    """Test creating ClimateIPDeviceState with valid full attributes and immutable tuples."""
    state = ClimateIPDeviceState(
        hvac_mode=HVACMode.COOL,
        target_temperature=24.5,
        current_temperature=25.0,
        fan_mode="auto",
        swing_mode="vertical",
        preset_mode="quiet",
        hvac_modes=(HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT),
        fan_modes=("auto", "low", "high"),
        swing_modes=("off", "vertical"),
        preset_modes=("none", "quiet"),
    )

    assert state.hvac_mode == HVACMode.COOL
    assert state.target_temperature == 24.5
    assert state.current_temperature == 25.0
    assert state.fan_mode == "auto"
    assert state.swing_mode == "vertical"
    assert state.preset_mode == "quiet"
    assert state.hvac_modes == (HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT)
    assert state.fan_modes == ("auto", "low", "high")
    assert state.swing_modes == ("off", "vertical")
    assert state.preset_modes == ("none", "quiet")


def test_state_valid_integer_temperatures() -> None:
    """Test that integer temperatures are accepted as valid numeric values."""
    state = ClimateIPDeviceState(
        target_temperature=22,
        current_temperature=21,
    )

    assert state.target_temperature == 22
    assert state.current_temperature == 21


def test_state_immutability_target_temperature() -> None:
    """Test that target_temperature attribute cannot be mutated after creation."""
    state = ClimateIPDeviceState(target_temperature=22.0)

    with pytest.raises(FrozenInstanceError):
        state.target_temperature = 25.0  # type: ignore[misc]


def test_state_immutability_hvac_mode() -> None:
    """Test that hvac_mode attribute cannot be mutated after creation."""
    state = ClimateIPDeviceState(hvac_mode=HVACMode.HEAT)

    with pytest.raises(FrozenInstanceError):
        state.hvac_mode = HVACMode.COOL  # type: ignore[misc]


def test_state_immutability_modes_tuple() -> None:
    """Test that modes tuples cannot be replaced after creation."""
    state = ClimateIPDeviceState(hvac_modes=(HVACMode.OFF,))

    with pytest.raises(FrozenInstanceError):
        state.hvac_modes = (HVACMode.HEAT,)  # type: ignore[misc]


def test_state_invalid_target_temperature_string() -> None:
    """Test that non-numeric string for target_temperature raises TypeError."""
    with pytest.raises(TypeError, match="Target temperature must be numeric"):
        ClimateIPDeviceState(target_temperature="24.5")  # type: ignore[arg-type]


def test_state_invalid_target_temperature_object() -> None:
    """Test that dict object for target_temperature raises TypeError."""
    with pytest.raises(TypeError, match="Target temperature must be numeric"):
        ClimateIPDeviceState(target_temperature={"temp": 24})  # type: ignore[arg-type]


def test_state_invalid_current_temperature_string() -> None:
    """Test that non-numeric string for current_temperature raises TypeError."""
    with pytest.raises(TypeError, match="Current temperature must be numeric"):
        ClimateIPDeviceState(current_temperature="25.0")  # type: ignore[arg-type]


def test_state_invalid_current_temperature_object() -> None:
    """Test that list object for current_temperature raises TypeError."""
    with pytest.raises(TypeError, match="Current temperature must be numeric"):
        ClimateIPDeviceState(current_temperature=[25.0])  # type: ignore[arg-type]


def test_state_invalid_hvac_mode_string() -> None:
    """Test that string instead of HVACMode enum for hvac_mode raises TypeError."""
    with pytest.raises(TypeError, match="Expected HVACMode instance"):
        ClimateIPDeviceState(hvac_mode="cool")  # type: ignore[arg-type]


def test_state_invalid_hvac_mode_int() -> None:
    """Test that int instead of HVACMode enum for hvac_mode raises TypeError."""
    with pytest.raises(TypeError, match="Expected HVACMode instance"):
        ClimateIPDeviceState(hvac_mode=1)  # type: ignore[arg-type]


def test_state_invalid_hvac_modes_mixed_tuple() -> None:
    """Test that mixed tuple with invalid item raises TypeError."""
    with pytest.raises(TypeError, match="must be valid HVACMode instances"):
        ClimateIPDeviceState(hvac_modes=(HVACMode.OFF, "cool"))  # type: ignore[arg-type]


def test_state_invalid_hvac_modes_all_invalid() -> None:
    """Test that tuple with all invalid items raises TypeError."""
    with pytest.raises(TypeError, match="must be valid HVACMode instances"):
        ClimateIPDeviceState(hvac_modes=("off", "cool"))  # type: ignore[arg-type]


def test_state_empty_hvac_modes_valid() -> None:
    """Test that empty hvac_modes tuple is valid."""
    state = ClimateIPDeviceState(hvac_modes=())
    assert state.hvac_modes == ()


def test_state_single_hvac_mode_valid() -> None:
    """Test that single HVACMode tuple is valid."""
    state = ClimateIPDeviceState(hvac_modes=(HVACMode.AUTO,))
    assert state.hvac_modes == (HVACMode.AUTO,)


def test_state_equality() -> None:
    """Test equality and inequality comparison between instances."""
    state1 = ClimateIPDeviceState(hvac_mode=HVACMode.HEAT, target_temperature=21.0)
    state2 = ClimateIPDeviceState(hvac_mode=HVACMode.HEAT, target_temperature=21.0)
    state3 = ClimateIPDeviceState(hvac_mode=HVACMode.COOL, target_temperature=21.0)

    assert state1 == state2
    assert state1 != state3


def test_state_hashable() -> None:
    """Test that frozen ClimateIPDeviceState instances are hashable in sets and dicts."""
    state1 = ClimateIPDeviceState(hvac_mode=HVACMode.HEAT, target_temperature=21.0)
    state2 = ClimateIPDeviceState(hvac_mode=HVACMode.HEAT, target_temperature=21.0)
    state3 = ClimateIPDeviceState(hvac_mode=HVACMode.COOL, target_temperature=21.0)

    state_set = {state1, state2, state3}
    assert len(state_set) == 2
    assert state1 in state_set
