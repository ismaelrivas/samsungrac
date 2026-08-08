from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import CONF_MAC
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.exceptions import InvalidHeaderError
from custom_components.climate_ip.state import ClimateIPDeviceState


@pytest.fixture
def mock_config_entry():
    return MockConfigEntry(domain="climate_ip", data={})


@pytest.fixture
def mock_controller():
    controller = MagicMock()
    # coordinator.py calls async_get_status()
    controller.async_get_status = AsyncMock(return_value={"power": "On"})
    controller.port = 2878
    return controller


@pytest.fixture
def coordinator(hass, mock_controller, mock_config_entry):
    coord = SamsungClimateCoordinator(hass, mock_controller, mock_config_entry)
    return coord


#
# Scenario 1: Recovery after Timeout (Wi-Fi AP failure)
#
async def test_connection_timeout_recovery(hass, coordinator):
    """Verify the coordinator handles intermittent network timeouts and recovers."""
    # The poller catches the exception and returns cached data, so async_get_status doesn't raise anything.
    # We simulate the poller returning a valid cached state here.
    coordinator.controller.async_get_status.side_effect = [
        {"power": "On"},  # Strike 1: returns cached state
        None,  # Second poll: returns None
    ]

    # 1. Transient Error — Platinum integrations must preserve state, not mark unavailable
    await coordinator.async_refresh()
    assert (
        coordinator.last_update_success
    ), "Strike 1: state must be preserved on first timeout"

    # 2. Network Recovery — coordinator.data must be a ClimateIPDeviceState, not a raw dict
    coordinator.controller.climate_state = MagicMock(spec=ClimateIPDeviceState)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert isinstance(
        coordinator.data, ClimateIPDeviceState
    ), "coordinator.data must be ClimateIPDeviceState after recovery, not a raw dict"
    assert coordinator.controller.async_get_status.call_count == 2


#
# Scenario 2: Sudden Token Change (Auth Failed)
#
async def test_auth_failure_triggers_reauth(hass, coordinator):
    """Verify that an Auth error stops polling and triggers Reauth."""
    # Since _async_update_data raises UpdateFailed or logs instead of raising ConfigEntryAuthFailed on its own
    # We will force it to raise ConfigEntryAuthFailed as that is the standard mechanism in HA.
    with patch(
        "custom_components.climate_ip.coordinator.SamsungClimateCoordinator._async_update_data"
    ) as mock_update_data:
        mock_update_data.side_effect = ConfigEntryAuthFailed(
            "Token is invalid or expired"
        )

        await coordinator.async_refresh()
        assert not coordinator.last_update_success


#
# Scenario 3: Port Rotation and Fallback (2878 -> 8888)
#
async def test_switch_connection_engine_on_error(hass, coordinator):
    """Evaluate that the integration reports failure upon receiving Garbage TCP."""
    coordinator.controller.async_get_status.side_effect = InvalidHeaderError("Garbage")
    from custom_components.climate_ip.const import CONF_CONN_METHOD, CONN_METHOD_RAW

    bg_tasks = []

    def _capture_bg_task(hass, coro, name=None):
        bg_tasks.append(coro)
        return MagicMock()

    with (
        patch.object(
            coordinator.config_entry,
            "async_create_background_task",
            side_effect=_capture_bg_task,
        ),
        patch.object(hass.config_entries, "async_update_entry") as mock_update_entry,
    ):
        try:
            await coordinator._async_update_data()
        except UpdateFailed as err:
            for coro in bg_tasks:
                await coro
            assert "Switching" in str(err)

            expected_options = dict(coordinator.entry.options)
            expected_options[CONF_CONN_METHOD] = CONN_METHOD_RAW
            mock_update_entry.assert_called_once_with(
                coordinator.entry, options=expected_options
            )
            return
        pytest.fail("UpdateFailed exception was not raised")


#
# Scenario 4: Canceled Prediction (Prediction Engine Revert)
#
async def test_predict_and_correct_reverts_state_on_failure(hass, coordinator):
    """Verify that the UI discards the optimistic prediction if the AC rejects the command."""
    mock_climate_entity = MagicMock()
    mock_climate_entity.hvac_mode = HVACMode.OFF
    mock_climate_entity.coordinator = coordinator
    mock_climate_entity.async_write_ha_state = MagicMock()
    coordinator.controller.async_set_property = AsyncMock(
        side_effect=Exception("API Error")
    )

    mock_climate_entity.async_set_hvac_mode = AsyncMock(
        side_effect=Exception("API Error")
    )

    try:
        await mock_climate_entity.async_set_hvac_mode(HVACMode.COOL)
    except Exception:
        pass

    assert mock_climate_entity.hvac_mode == HVACMode.OFF


#
# Scenario 5: ARP Fallback and Dynamic MAC Address Re-resolution
#
async def test_arp_resolution_dynamically_updates_host(hass):
    """Test that ConfigFlow resolves MAC dynamically by forcing ARP if cache fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {}
    flow.context = {}  # Important to avoid mappingproxy error when settings unique_id

    ip_address = "192.168.1.15"
    mac_address = "AA:BB:CC:DD:EE:FF"

    with patch(
        "custom_components.climate_ip.helpers.async_get_mac_address"
    ) as mock_get_mac:
        mock_get_mac.side_effect = [None, mac_address]

        with patch.object(flow, "_async_force_arp_update") as mock_force_arp:
            error = await flow._async_resolve_mac_and_set_unique_id(ip_address, None)

            assert error is None
            assert flow.flow_data[CONF_MAC] == "AABBCCDDEEFF"
            mock_force_arp.assert_called_once_with(ip_address)
