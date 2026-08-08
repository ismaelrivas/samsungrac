"""Tests for ClimateIpConfigFlow main orchestrator in config_flow.py."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    CONF_NAME,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
)


@pytest.mark.asyncio
async def test_form_user_step(hass: HomeAssistant) -> None:
    """Test user step form rendering and selection."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch.object(
        flow, "async_step_samsung_2878", new_callable=AsyncMock
    ) as mock_step:
        mock_step.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "samsung_2878",
        }
        _ = await flow.async_step_user(
            {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
        )
        assert flow.flow_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_SAMSUNG_2878
        mock_step.assert_called_once()


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
async def test_is_matching_ip_and_mac(hass: HomeAssistant) -> None:
    """Test is_matching method comparing IP and MAC addresses."""
    flow1 = ClimateIpConfigFlow()
    flow1.flow_data = {CONF_IP_ADDRESS: "192.168.1.10", CONF_MAC: "AABBCCDDEEFF"}

    flow2 = ClimateIpConfigFlow()
    flow2.flow_data = {CONF_IP_ADDRESS: "192.168.1.10", CONF_MAC: "112233445566"}

    assert flow1.is_matching(flow2) is True

    flow3 = ClimateIpConfigFlow()
    flow3.flow_data = {CONF_IP_ADDRESS: "192.168.1.11", CONF_MAC: "aabbccddeeff"}

    assert flow1.is_matching(flow3) is True


@pytest.mark.asyncio
async def test_create_entry_logic(hass: HomeAssistant) -> None:
    """Test _create_entry builds correct title and entry data."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_MAC: "001122334455",
        CONF_NAME: "Living Room AC",
    }

    with patch.object(flow, "async_set_unique_id", new_callable=AsyncMock):
        result = await flow._create_entry()
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert "Living Room AC" in result["title"]
        assert "001122334455" in result["title"]
