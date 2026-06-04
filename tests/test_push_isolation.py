# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Simplified tests for atomic push update isolation."""
# pylint: disable=import-outside-toplevel
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.climate import HVACMode


# Mocking the entire coordinator and controller to test the interaction
@pytest.mark.asyncio
async def test_valid_push_update_commits():
    """Test that valid push calls set_updated_data."""
    mock_hass = MagicMock()
    mock_controller = MagicMock()
    # MUST be AsyncMock for awaited methods
    mock_controller.async_merge_device_state = AsyncMock(return_value=True)

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    with patch("custom_components.climate_ip.coordinator.DataUpdateCoordinator.__init__", return_value=None):
        from custom_components.climate_ip.coordinator import (
            SamsungClimateCoordinator,
        )
        coordinator = SamsungClimateCoordinator(mock_hass, mock_controller, mock_entry)
        coordinator.async_set_updated_data = MagicMock()
        coordinator._create_device_state = MagicMock(return_value="new_state")

        await coordinator.async_handle_push_update({"power": "on"})

        mock_controller.async_merge_device_state.assert_called_once()
        coordinator.async_set_updated_data.assert_called_once_with("new_state")

@pytest.mark.asyncio
async def test_junk_push_update_ignored():
    """Test that junk push is ignored."""
    mock_hass = MagicMock()
    mock_controller = MagicMock()
    # MUST be AsyncMock for awaited methods
    mock_controller.async_merge_device_state = AsyncMock(return_value=False)

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    with patch("custom_components.climate_ip.coordinator.DataUpdateCoordinator.__init__", return_value=None):
        from custom_components.climate_ip.coordinator import (
            SamsungClimateCoordinator,
        )
        coordinator = SamsungClimateCoordinator(mock_hass, mock_controller, mock_entry)
        coordinator.async_set_updated_data = MagicMock()

        await coordinator.async_handle_push_update({"junk": "data"})

        mock_controller.async_merge_device_state.assert_called_once()
        coordinator.async_set_updated_data.assert_not_called()

@pytest.mark.asyncio
async def test_dry_run_logic_isolation():
    """Test the dry-run logic in YamlStatePoller directly."""
    from custom_components.climate_ip.controller_yaml_polling import (
        YamlStatePoller,
    )

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.log_prefix = "[Test]"

    prop = MagicMock()
    prop.id = "hvac_mode"
    prop.calculate_value_from_state.return_value = HVACMode.COOL

    mock_controller.loader.operations = {"hvac_mode": prop}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    poller = YamlStatePoller(mock_controller)
    raw_state = {"power": "on"}

    with patch("custom_components.climate_ip.controller_yaml_polling.ClimateIPDeviceState") as MockState:
        res = poller._calculate_structured_state(raw_state)

        assert res == MockState.return_value
        prop.calculate_value_from_state.assert_called_once_with(raw_state)
        # Ensure async_update_state was NOT called (no side effects)
        assert not prop.async_update_state.called
