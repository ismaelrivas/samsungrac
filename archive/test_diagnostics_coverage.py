"""Supplementary tests for complete diagnostics coverage."""

from unittest.mock import MagicMock

from custom_components.climate_ip.diagnostics import _extract_raw_device_state


def test_extract_raw_device_state_subdevice_attribute_errors() -> None:
    """Test _extract_raw_device_state when a subdevice raises AttributeError on raw_state and device_state."""
    coordinator = MagicMock()
    # subdevice has neither raw_state nor device_state
    subdevice = object()
    coordinator.devices = {"sub_1": subdevice}
    coordinator.controller = MagicMock()
    coordinator.controller.raw_state = {"power": "on"}
    state = _extract_raw_device_state(coordinator)
    assert state == {"main": {"power": "on"}}
