# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ClimateIPDeviceState strict typing and Fail-Fast validation."""

from dataclasses import FrozenInstanceError

from custom_components.climate_ip.state import ClimateIPDeviceState
import pytest

from homeassistant.components.climate import HVACMode


def test_climate_ip_state_valid_types():
    """Test creating ClimateIPDeviceState with strictly valid types and immutable tuples."""
    state = ClimateIPDeviceState(
        hvac_mode=HVACMode.COOL,
        target_temperature=24.5,
        current_temperature=25.0,
        fan_mode="auto",
        swing_mode="vertical",
        preset_mode="quiet",
        # Notice we use tuples () instead of lists [] to enforce immutability
        hvac_modes=(HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT),
        fan_modes=("auto", "low", "high"),
        swing_modes=("off", "vertical"),
        preset_modes=("none", "quiet"),
    )

    assert state.hvac_mode == HVACMode.COOL
    assert state.target_temperature == 24.5
    assert state.fan_modes == ("auto", "low", "high")


def test_climate_ip_state_invalid_types_raise():
    """Test that the Fail-Fast doctrine actively rejects malformed data."""

    # 1. Reject invalid temperature (String instead of float/int)
    with pytest.raises(TypeError, match="Target temperature must be numeric"):
        ClimateIPDeviceState(target_temperature="24.5")  # type: ignore[arg-type]

    # 2. Reject invalid HVAC Mode (String instead of HVACMode Enum)
    with pytest.raises(TypeError, match="Expected HVACMode instance"):
        ClimateIPDeviceState(hvac_mode="cool")  # type: ignore[arg-type]

    # 3. Reject invalid HVAC Mode inside the supported modes collection
    with pytest.raises(TypeError, match="must be valid HVACMode instances"):
        # Passing a string instead of an HVACMode Enum in the tuple
        ClimateIPDeviceState(hvac_modes=(HVACMode.OFF, "cool"))  # type: ignore[arg-type]

    # 4. Reject invalid current temperature (String instead of float/int)
    with pytest.raises(TypeError, match="Current temperature must be numeric"):
        ClimateIPDeviceState(current_temperature="25.0")  # type: ignore[arg-type]


def test_climate_ip_state_immutability():
    """Test that the state object cannot be mutated after creation."""
    state = ClimateIPDeviceState(hvac_mode=HVACMode.HEAT, target_temperature=22.0)

    # Attempting to mutate a frozen dataclass must raise a FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        state.target_temperature = 25.0  # type: ignore[misc]
