# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for optimized ARP discovery logic in config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow


@pytest.fixture
def hass_mock():
    """Mock Home Assistant object."""
    hass = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_resolve_mac_skips_arp_if_in_cache(hass_mock):
    """Test that _async_resolve_mac_and_set_unique_id skips force_arp if MAC is already found."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            new_callable=AsyncMock,
        ) as mock_get_mac,
        patch.object(
            flow, "_async_force_arp_update", new_callable=AsyncMock
        ) as mock_force_arp,
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
    ):
        # Simulate MAC found on first attempt
        mock_get_mac.return_value = "00:11:22:33:44:55"

        result = await flow._async_resolve_mac_and_set_unique_id("1.1.1.1", None)

        assert result is None
        assert flow.flow_data["mac"] == "001122334455"

        # Verify force_arp was NOT called
        mock_force_arp.assert_not_called()
        # Verify async_get_mac_address was called only once
        mock_get_mac.assert_called_once_with("1.1.1.1")
        mock_set_id.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_mac_forces_arp_if_not_in_cache(hass_mock):
    """Test that _async_resolve_mac_and_set_unique_id forces ARP if initial attempt fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            new_callable=AsyncMock,
        ) as mock_get_mac,
        patch.object(
            flow, "_async_force_arp_update", new_callable=AsyncMock
        ) as mock_force_arp,
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
    ):
        # Simulate MAC NOT found on first attempt, but found on second attempt
        mock_get_mac.side_effect = [None, "00:11:22:33:44:55"]

        result = await flow._async_resolve_mac_and_set_unique_id("1.1.1.1", None)

        assert result is None
        assert flow.flow_data["mac"] == "001122334455"

        # Verify force_arp WAS called
        mock_force_arp.assert_called_once_with("1.1.1.1")
        # Verify async_get_mac_address was called twice
        assert mock_get_mac.call_count == 2
        mock_set_id.assert_called_once()
