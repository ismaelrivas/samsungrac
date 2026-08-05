"""Tests for ConfigFlowDiscoveryMixin in config_flow_discovery.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.const import CONF_MAC

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONF_DISCOVERED_DEVICES,
    CONF_NAME,
    CONF_SELECTED_DEVICES,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_8888,
)
from custom_components.climate_ip.exceptions import InvalidHeaderError


@pytest.mark.asyncio
async def test_mim_h03_discovery_processing():
    """Test MIM-H03 discovery processing for internal coordinator and indoor units."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}

    discovered = [
        {"id": "0", "uuid": "COORD_UUID_123", "name": "Main Coordinator"},
        {"id": "1", "uuid": "UNIT_UUID_1", "name": "Living Room", "Mode": True},
        {"id": "2", "uuid": "UNIT_UUID_2", "name": "Bedroom", "Mode": True},
    ]

    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock) as mock_set_uid,
        patch.object(flow, "async_step_select_devices", new_callable=AsyncMock) as mock_select,
    ):
        mock_select.return_value = {"type": FlowResultType.FORM, "step_id": "select_devices"}

        result = await flow._async_process_mim_h03(discovered)

        mock_set_uid.assert_called_once_with("COORD_UUID_123", raise_on_progress=False)
        assert flow.flow_data[CONF_DEVICE_ID] == "0"
        assert flow.flow_data["unique_id"] == "COORD_UUID_123"
        assert len(flow.flow_data[CONF_DISCOVERED_DEVICES]) == 2


@pytest.mark.asyncio
async def test_samsung_8888_discovery_processing():
    """Test 8888 device discovery processing."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_MAC: "001122334455"}

    discovered = [{"uuid": "SAMSUNG_8888_UUID"}]

    with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

        result = await flow._async_process_samsung_8888_discovery(discovered)

        assert flow.flow_data[CONF_DEVICE_ID] == "SAMSUNG_8888_UUID"
        assert flow.flow_data[CONF_NAME] == "Samsung AC 001122334455"
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_init_discovery_controller_failure_and_invalid_header():
    """Test _async_init_discovery_controller handling initialization failure and InvalidHeaderError."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    with patch("custom_components.climate_ip.controller_yaml.YamlController") as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=False)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})
        assert res is None
        mock_ctrl.async_shutdown.assert_called_once()

    with patch("custom_components.climate_ip.controller_yaml.YamlController") as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(side_effect=InvalidHeaderError("bad header"))
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        with pytest.raises(InvalidHeaderError):
            await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})
        mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_process_generic_discovery():
    """Test _async_process_generic_discovery."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {}

    discovered = [
        {"id": "1", "uuid": "u1", "name": "Device 1"},
        {"id": "2", "uuid": "u2", "name": "Device 2"},
    ]

    with patch.object(flow, "async_step_select_devices", new_callable=AsyncMock) as mock_select:
        mock_select.return_value = {"type": FlowResultType.FORM, "step_id": "select_devices"}
        result = await flow._async_process_generic_discovery(discovered)
        assert len(flow.flow_data[CONF_DISCOVERED_DEVICES]) == 2
        mock_select.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_raw_discovery():
    """Test _async_fallback_raw_discovery success and failure."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {}

    with patch("custom_components.climate_ip.controller_yaml.YamlController") as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            res = await flow._async_fallback_raw_discovery({})
            assert res["type"] == FlowResultType.CREATE_ENTRY


@pytest.mark.asyncio
async def test_async_step_discover_uuid_blind_device():
    """Test async_step_discover_uuid when no indoor units are discovered (blind device)."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    flow.reauth_entry = None
    flow.source = "user"

    with patch.object(flow, "_async_init_discovery_controller") as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = "BLIND_UNIQUE_123"
        mock_ctrl.device_id = "BLIND_DEV_123"
        mock_init.return_value = mock_ctrl

        with (
            patch.object(flow, "async_set_unique_id", new_callable=AsyncMock) as mock_set_uid,
            patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
            patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            res = await flow.async_step_discover_uuid()
            assert res["type"] == FlowResultType.CREATE_ENTRY
            mock_set_uid.assert_called_once_with("BLIND_UNIQUE_123", raise_on_progress=False)
            mock_abort_if.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_select_devices_flow():
    """Test async_step_select_devices rendering form and completing entry creation."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [
            {"id": "1", "name": "Unit 1"},
            {"id": "2", "name": "Unit 2"},
        ],
        "unique_id": "MAIN_UID",
    }
    flow.reauth_entry = None
    flow.source = "user"

    # Step 1: Initial call (no user_input -> return form)
    res_form = await flow.async_step_select_devices()
    assert res_form["type"] == FlowResultType.FORM
    assert res_form["step_id"] == "select_devices"

    # Step 2: Submit with selected devices
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res_submit = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
        assert res_submit["type"] == FlowResultType.CREATE_ENTRY
        assert len(flow.flow_data[CONF_DEVICES]) == 1
        assert flow.flow_data[CONF_DEVICES][0]["id"] == "1"
        mock_set_uid.assert_called_once_with("MAIN_UID", raise_on_progress=False)

