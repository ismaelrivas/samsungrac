# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Simplified tests for atomic push update isolation."""

# pylint: disable=import-outside-toplevel
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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

    def fake_init(self, *args, **kwargs):
        self.config_entry = kwargs.get("config_entry", mock_entry)

    with patch(
        "custom_components.climate_ip.coordinator.DataUpdateCoordinator.__init__",
        fake_init,
    ):
        from custom_components.climate_ip.coordinator import (
            SamsungClimateCoordinator,
        )

        coordinator = SamsungClimateCoordinator(mock_hass, mock_controller, mock_entry)
        coordinator.last_update_success = True
        coordinator.data = None
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

    def fake_init(self, *args, **kwargs):
        self.config_entry = kwargs.get("config_entry", mock_entry)

    with patch(
        "custom_components.climate_ip.coordinator.DataUpdateCoordinator.__init__",
        fake_init,
    ):
        from custom_components.climate_ip.coordinator import (
            SamsungClimateCoordinator,
        )

        coordinator = SamsungClimateCoordinator(mock_hass, mock_controller, mock_entry)
        coordinator.last_update_success = True
        coordinator.data = None
        coordinator.async_set_updated_data = MagicMock()

        await coordinator.async_handle_push_update({"junk": "data"})

        mock_controller.async_merge_device_state.assert_called_once()
        coordinator.async_set_updated_data.assert_not_called()
