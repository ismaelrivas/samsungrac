# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ClimateIPDeviceState strict typing."""

import pytest

from homeassistant.components.climate import HVACMode
from custom_components.climate_ip.state import ClimateIPDeviceState


def test_climate_ip_state_valid_types():
    """Test creating ClimateIPDeviceState with valid types."""
    state = ClimateIPDeviceState(
        hvac_mode=HVACMode.COOL,
        target_temperature=24.5,
        current_temperature=25.0,
        fan_mode="auto",
        swing_mode="vertical",
        preset_mode="quiet",
        hvac_modes=[HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT],
        fan_modes=["auto", "low", "high"],
        swing_modes=["off", "vertical"],
        preset_modes=["none", "quiet"],
    )

    assert state.hvac_mode == HVACMode.COOL
    assert state.target_temperature == 24.5
    assert state.fan_modes == ["auto", "low", "high"]


def test_climate_ip_state_coercion():
    """Test that ClimateIPDeviceState coerces valid string/int values."""
    state = ClimateIPDeviceState(
        hvac_mode="cool",
        target_temperature="24.5",
        current_temperature=25,
        hvac_modes=["off", "cool"],
    )

    assert state.hvac_mode == HVACMode.COOL
    assert state.target_temperature == 24.5
    assert state.current_temperature == 25.0
    assert state.hvac_modes == [HVACMode.OFF, HVACMode.COOL]


def test_climate_ip_state_invalid_types_raise():
    """Test that malformed data raises TypeError or ValueError."""
    with pytest.raises((TypeError, ValueError)):
        # Invalid target temperature string that cannot be cast to float
        ClimateIPDeviceState(target_temperature="abc")

    with pytest.raises((TypeError, ValueError)):
        # Invalid HVAC mode string
        ClimateIPDeviceState(hvac_mode="invalid_mode")
