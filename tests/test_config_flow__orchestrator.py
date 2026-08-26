"""Tests for ClimateIpConfigFlow main orchestrator in config_flow.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
)


@pytest.mark.asyncio
async def test_step_samsung_2878_routing(hass: HomeAssistant) -> None:
    """Test routing in async_step_samsung_2878."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    with patch.object(
        flow, "_async_process_samsung_device_step", new_callable=AsyncMock
    ) as mock_process:
        mock_process.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "samsung_2878",
        }
        _ = await flow.async_step_samsung_2878({"ip_address": "192.168.1.50"})
        mock_process.assert_called_once_with(
            step_id="samsung_2878",
            is_8888=False,
            user_input={"ip_address": "192.168.1.50"},
        )


@pytest.mark.asyncio
async def test_step_samsung_8888_routing(hass: HomeAssistant) -> None:
    """Test routing in async_step_samsung_8888."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}

    with patch.object(
        flow, "_async_process_samsung_device_step", new_callable=AsyncMock
    ) as mock_process:
        mock_process.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "samsung_8888",
        }
        _ = await flow.async_step_samsung_8888({"ip_address": "192.168.1.51"})
        mock_process.assert_called_once_with(
            step_id="samsung_8888",
            is_8888=True,
            user_input={"ip_address": "192.168.1.51"},
        )


@pytest.mark.asyncio
async def test_step_mim_h03_routing(hass: HomeAssistant) -> None:
    """Test routing in async_step_mim_h03."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}

    with patch.object(
        flow, "_async_process_samsung_device_step", new_callable=AsyncMock
    ) as mock_process:
        mock_process.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "mim_h03",
        }
        _ = await flow.async_step_mim_h03({"ip_address": "192.168.1.52"})
        mock_process.assert_called_once_with(
            step_id="mim_h03",
            is_8888=True,
            user_input={"ip_address": "192.168.1.52"},
        )


@pytest.mark.asyncio
async def test_step_reauth_confirm_mim_h03_routing(hass: HomeAssistant) -> None:
    """Test reauth confirm routing for MIM-H03."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    mock_entry = AsyncMock()
    mock_entry.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    mock_entry.title = "MIM H03 Device"
    flow.reauth_entry = mock_entry
    flow.flow_data = dict(mock_entry.data)

    with patch.object(
        flow, "async_step_mim_h03", new_callable=AsyncMock
    ) as mock_step_mim:
        mock_step_mim.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "mim_h03",
        }
        _ = await flow.async_step_reauth_confirm(user_input={})
        mock_step_mim.assert_called_once()


@pytest.mark.asyncio
async def test_is_matching_ip_and_mac(hass: HomeAssistant) -> None:
    """Test is_matching method comparing IP and MAC addresses."""
    flow1 = ClimateIpConfigFlow()
    flow1.flow_data = {CONF_IP_ADDRESS: "192.168.1.10", CONF_MAC: "AABBCCDDEEFF"}

    flow2 = ClimateIpConfigFlow()
    flow2.flow_data = {CONF_IP_ADDRESS: "192.168.1.10", CONF_MAC: "112233445566"}

    assert flow1.is_matching(flow2) is False

    flow3 = ClimateIpConfigFlow()
    flow3.flow_data = {CONF_IP_ADDRESS: "192.168.1.11", CONF_MAC: "aabbccddeeff"}

    assert flow1.is_matching(flow3) is True


def test_is_matching_asymmetric_inputs() -> None:
    """Kill 'and' to 'or' logic flips in is_matching."""
    flow1 = ClimateIpConfigFlow()
    flow1.flow_data = {CONF_MAC: "AA:BB:CC"}
    flow2 = ClimateIpConfigFlow()
    flow2.flow_data = {CONF_IP_ADDRESS: "1.1.1.1"}  # Missing MAC

    # If 'and' was flipped to 'or', this would throw AttributeError on None.upper()
    assert flow1.is_matching(flow2) is False
