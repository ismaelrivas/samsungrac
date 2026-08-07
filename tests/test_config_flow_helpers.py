"""Tests for ConfigFlowHelpersMixin in config_flow_helpers.py."""

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
        mock_get_mac.return_value = "00:11:22:33:44:55"

        result = await flow._async_resolve_mac_and_set_unique_id("1.1.1.1", None)

        assert result is None
        assert flow.flow_data["mac"] == "001122334455"
        mock_force_arp.assert_not_called()
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
        mock_get_mac.side_effect = [None, "00:11:22:33:44:55"]

        result = await flow._async_resolve_mac_and_set_unique_id("1.1.1.1", None)

        assert result is None
        assert flow.flow_data["mac"] == "001122334455"
        mock_force_arp.assert_called_once_with("1.1.1.1")
        assert mock_get_mac.call_count == 2
        mock_set_id.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_mac_provided_by_user(hass_mock):
    """Test that _async_resolve_mac_and_set_unique_id formats and uses a provided MAC."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with patch.object(
        flow, "async_set_unique_id", new_callable=AsyncMock
    ) as mock_set_id:
        result = await flow._async_resolve_mac_and_set_unique_id(
            "1.1.1.1", "aa:bb:cc:dd:ee:ff"
        )

        assert result is None
        assert flow.flow_data["mac"] == "AABBCCDDEEFF"
        mock_set_id.assert_called_once()


@pytest.mark.asyncio
async def test_validate_cert_path_empty_returns_true(hass_mock):
    """Test that validating None/empty cert path returns True immediately."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    assert await flow._async_validate_cert_path(None) is True
    assert await flow._async_validate_cert_path("") is True


@pytest.mark.asyncio
async def test_async_force_arp_update(hass_mock):
    """Test _async_force_arp_update attempts raw connections."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    with patch("asyncio.open_connection", side_effect=OSError("Port closed")):
        await flow._async_force_arp_update("1.2.3.4")


@pytest.mark.asyncio
async def test_initiate_pairing_safe_and_wait_token_safe_null_acquirer(hass_mock):
    """Test _initiate_pairing_safe and _wait_token_safe when acquirer is None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.acquirer = None
    flow.flow_data = {}

    res1 = await flow._initiate_pairing_safe()
    assert res1 == {"ok": False, "error": "unknown_error"}

    res2 = await flow._wait_token_safe()
    assert res2 == {"ok": False, "error": "unknown_error"}


@pytest.mark.asyncio
async def test_initiate_pairing_safe_and_wait_token_safe_success(hass_mock):
    """Test _initiate_pairing_safe and _wait_token_safe when acquirer succeeds."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    mock_acquirer = MagicMock()
    mock_acquirer.async_initiate_pairing = AsyncMock(return_value={"port": 8888})
    mock_acquirer.async_wait_for_token = AsyncMock(return_value="token123")
    flow.acquirer = mock_acquirer
    flow.flow_data = {}

    res1 = await flow._initiate_pairing_safe()
    assert res1 == {"ok": True, "config": {"port": 8888}}

    res2 = await flow._wait_token_safe()
    assert res2 == {"ok": True, "token": "token123"}


@pytest.mark.asyncio
async def test_validate_cert_path_none_resolved_returns_true(hass_mock):
    """Test _async_validate_cert_path returns True when resolve_cert_path returns None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    with patch(
        "custom_components.climate_ip.helpers.resolve_cert_path", return_value=None
    ):
        assert await flow._async_validate_cert_path("invalid_path") is True


@pytest.mark.asyncio
async def test_test_connection_safe_8888_branch_and_2878_branch(hass_mock):
    """Test _test_connection_safe for 8888 and 2878 device types."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    # 1. 8888 Branch
    flow.flow_data = {
        "device_type": "samsung_8888",
        "ip_address": "1.1.1.1",
        "token": "tok8888",
        "cert": "ca.pem",
    }
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get
        hass_mock.async_add_executor_job = AsyncMock(return_value=MagicMock())

        res8888 = await flow._test_connection_safe()
        assert res8888 == {"ok": True}

    # 2. 2878 Branch
    flow.flow_data = {
        "device_type": "samsung_2878",
        "ip_address": "1.1.1.1",
        "mac": "AA:BB:CC:DD:EE:FF",
    }
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.loader = MagicMock()
        mock_ctrl.loader.state_getter = MagicMock()
        mock_ctrl.loader.state_getter.async_update_state = AsyncMock(
            return_value={"state": "on"}
        )
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res2878 = await flow._test_connection_safe()
        assert res2878 == {"ok": True}
        mock_ctrl.initialize.assert_called_once()
        mock_ctrl.async_shutdown.assert_called_once()
