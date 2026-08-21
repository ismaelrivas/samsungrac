# pylint: disable=protected-access,line-too-long,trailing-newlines,too-many-lines
"""Tests for ConfigFlowDiscoveryMixin in config_flow_discovery.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_MAC
from homeassistant.data_entry_flow import FlowResultType

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_CONN_METHOD,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONF_DISCOVERED_DEVICES,
    CONF_NAME,
    CONF_SELECTED_DEVICES,
    CONN_METHOD_RAW,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_TO_CONFIG_FILE,
)
from custom_components.climate_ip.exceptions import InvalidHeaderError

# ============================================================================
# Group 1: _async_init_discovery_controller
# ============================================================================


@pytest.mark.asyncio
async def test_init_discovery_controller_success():
    """Test _async_init_discovery_controller returns ready controller when init and status succeed."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})

        assert res is mock_ctrl
        mock_ctrl.initialize.assert_called_once()
        mock_ctrl.async_get_status.assert_called_once()
        mock_ctrl.async_shutdown.assert_not_called()


@pytest.mark.asyncio
async def test_init_discovery_controller_initialize_fails():
    """Test _async_init_discovery_controller returns None and shuts down controller if initialize fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=False)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})

        assert res is None
        mock_ctrl.initialize.assert_called_once()
        mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_init_discovery_controller_status_fails():
    """Test _async_init_discovery_controller returns None and shuts down controller if async_get_status fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=False)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})

        assert res is None
        mock_ctrl.initialize.assert_called_once()
        mock_ctrl.async_get_status.assert_called_once()
        mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_init_discovery_controller_invalid_header_error():
    """Test _async_init_discovery_controller shuts down controller and propagates InvalidHeaderError."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(side_effect=InvalidHeaderError("bad header"))
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        with pytest.raises(InvalidHeaderError):
            await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})

        mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_init_discovery_controller_generic_exception():
    """Test _async_init_discovery_controller shuts down controller and propagates generic exceptions."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(side_effect=RuntimeError("connection drop"))
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        with pytest.raises(RuntimeError):
            await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})

        mock_ctrl.async_shutdown.assert_called_once()


# ============================================================================
# Group 2: _async_fallback_raw_discovery
# ============================================================================


@pytest.mark.asyncio
async def test_fallback_raw_discovery_success():
    """Test _async_fallback_raw_discovery sets raw conn method, creates entry, and shuts down."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER, "unique_id": "FALLBACK_UID"}
    flow.flow_data = {}

    config_data = {"ip_address": "1.1.1.1"}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

            res = await flow._async_fallback_raw_discovery(config_data)

            assert res["type"] == FlowResultType.CREATE_ENTRY
            assert flow.flow_data[CONF_CONN_METHOD] == CONN_METHOD_RAW
            assert config_data[CONF_CONN_METHOD] == CONN_METHOD_RAW
            mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_raw_discovery_init_fails():
    """Test _async_fallback_raw_discovery aborts with cannot_connect when init returns False."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=False)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

            res = await flow._async_fallback_raw_discovery({})

            assert res["type"] == FlowResultType.ABORT
            assert res["reason"] == "cannot_connect"
            mock_ctrl.async_shutdown.assert_called_once()
            mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_raw_discovery_status_fails():
    """Test _async_fallback_raw_discovery aborts with cannot_connect when status returns False."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=False)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

            res = await flow._async_fallback_raw_discovery({})

            assert res["type"] == FlowResultType.ABORT
            assert res["reason"] == "cannot_connect"
            mock_ctrl.async_shutdown.assert_called_once()
            mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_raw_discovery_exception():
    """Test _async_fallback_raw_discovery aborts with cannot_connect on raw controller exception."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(side_effect=Exception("raw failure"))
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._async_fallback_raw_discovery({})

        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "cannot_connect"
        mock_ctrl.async_shutdown.assert_called_once()


# ============================================================================
# Group 3: _async_process_samsung_8888_discovery
# ============================================================================


@pytest.mark.asyncio
async def test_samsung_8888_discovery_with_uuid():
    """Test 8888 device discovery processing when device provides uuid."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {CONF_MAC: "001122334455"}

    discovered = [{"uuid": "SAMSUNG_8888_UUID"}]

    with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

        res = await flow._async_process_samsung_8888_discovery(discovered)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data[CONF_DEVICE_ID] == "SAMSUNG_8888_UUID"
        assert flow.flow_data[CONF_NAME] == "Samsung AC 001122334455"
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_samsung_8888_discovery_fallback_to_id():
    """Test 8888 device discovery processing when uuid is missing and fallback to id is used."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {CONF_MAC: "AABBCCDDEEFF"}

    discovered = [{"id": "DEV_ID_8888", "uuid": ""}]

    with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

        res = await flow._async_process_samsung_8888_discovery(discovered)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data[CONF_DEVICE_ID] == "DEV_ID_8888"
        assert flow.flow_data[CONF_NAME] == "Samsung AC AABBCCDDEEFF"
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_samsung_8888_discovery_fails_no_uuid_no_id():
    """Test 8888 device discovery processing aborts when neither uuid nor id are present."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {CONF_MAC: "AABBCCDDEEFF"}

    discovered = [{}]

    res = await flow._async_process_samsung_8888_discovery(discovered)

    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "discovery_failed"


# ============================================================================
# Group 4: _async_process_generic_discovery
# ============================================================================


@pytest.mark.asyncio
async def test_process_generic_discovery_detailed_mapping():
    """Test _async_process_generic_discovery parses devices with full dictionary structure and defaults."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {}

    discovered = [
        None,
        123,
        {"id": "1", "uuid": "u1", "name": "Device 1", "description": "Custom Desc 1"},
        {"id": "2", "name": "Device 2"},
        {"uuid": "u3", "description": "Desc 3"},
        {"id": "4"},
    ]

    with patch.object(
        flow, "async_step_select_devices", new_callable=AsyncMock
    ) as mock_select:
        mock_select.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "select_devices",
        }

        res = await flow._async_process_generic_discovery(discovered)

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "select_devices"
        assert len(flow.flow_data[CONF_DISCOVERED_DEVICES]) == 4
        assert flow.flow_data[CONF_DISCOVERED_DEVICES] == [
            {
                "id": "1",
                "uuid": "u1",
                "name": "Device 1",
                "description": "Custom Desc 1",
            },
            {
                "id": "2",
                "uuid": "",
                "name": "Device 2",
                "description": "Device 2",
            },
            {
                "id": "{'uuid': 'u3', 'description': 'Desc 3'}",
                "uuid": "u3",
                "name": "Indoor Unit {'uuid': 'u3', 'description': 'Desc 3'}",
                "description": "Desc 3",
            },
            {
                "id": "4",
                "uuid": "",
                "name": "Indoor Unit 4",
                "description": "Indoor Unit 4",
            },
        ]
        mock_select.assert_called_once()


@pytest.mark.asyncio
async def test_process_generic_discovery_empty_creates_entry():
    """Test _async_process_generic_discovery creates entry directly if no valid devices found."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {}

    discovered = [None, "invalid_str"]

    with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

        res = await flow._async_process_generic_discovery(discovered)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_create.assert_called_once()


# ============================================================================
# Group 5: _async_process_mim_h03
# ============================================================================


@pytest.mark.asyncio
async def test_mim_h03_discovery_full_success_with_ac_units():
    """Test MIM-H03 discovery processing for internal coordinator and indoor units."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    discovered = [
        "not_a_dict",
        {"id": "0", "uuid": "COORD_UUID_123", "name": "Main Coordinator"},
        {
            "id": "1",
            "uuid": "UNIT_UUID_1",
            "name": "Living Room",
            "description": "Living AC",
            "Mode": True,
        },
        {"id": "2", "Mode": True},
    ]

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(
            flow, "async_step_select_devices", new_callable=AsyncMock
        ) as mock_select,
    ):
        mock_select.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "select_devices",
        }

        res = await flow._async_process_mim_h03(discovered)

        assert res["type"] == FlowResultType.FORM
        mock_set_uid.assert_called_once_with("COORD_UUID_123", raise_on_progress=False)
        assert flow.flow_data[CONF_DEVICE_ID] == "0"
        assert flow.flow_data["unique_id"] == "COORD_UUID_123"
        assert flow.flow_data[CONF_NAME] == "Main Coordinator COORD_UUID_123"
        assert flow.flow_data[CONF_DISCOVERED_DEVICES] == [
            {
                "id": "1",
                "uuid": "UNIT_UUID_1",
                "name": "ID 1 (Living Room)",
                "description": "Living AC",
            },
            {
                "id": "2",
                "uuid": "",
                "name": "ID 2 (Indoor Unit 2)",
                "description": "Indoor Unit 2",
            },
        ]
        mock_abort_if.assert_called_once_with(updates=flow.flow_data)
        mock_select.assert_called_once()


@pytest.mark.asyncio
async def test_mim_h03_discovery_coordinator_default_name_and_no_ac_units():
    """Test MIM-H03 discovery creates entry directly when coordinator has no name and no AC units exist."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    discovered = [{"id": "0", "uuid": "COORD_UUID_999"}]

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

        res = await flow._async_process_mim_h03(discovered)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_set_uid.assert_called_once_with("COORD_UUID_999", raise_on_progress=False)
        assert flow.flow_data[CONF_NAME] == "MIM-H03 Coordinator COORD_UUID_999"
        assert flow.flow_data[CONF_DEVICE_ID] == "0"
        mock_abort_if.assert_called_once_with(updates=flow.flow_data)
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_mim_h03_discovery_single_non_mode_coordinator_selected():
    """Test MIM-H03 selects a non-mode device as coordinator when internal_coordinator is None and id is not 0."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    discovered = [{"id": "9", "name": "Solo NonMode Coord", "uuid": "SOLO_NON_MODE_UUID"}]

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

        res = await flow._async_process_mim_h03(discovered)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_set_uid.assert_called_once_with("SOLO_NON_MODE_UUID", raise_on_progress=False)
        assert flow.flow_data[CONF_DEVICE_ID] == "9"
        assert flow.flow_data["unique_id"] == "SOLO_NON_MODE_UUID"
        assert flow.flow_data[CONF_NAME] == "Solo NonMode Coord SOLO_NON_MODE_UUID"
        mock_abort_if.assert_called_once_with(updates=flow.flow_data)
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_mim_h03_discovery_coordinator_precedence_and_mode_checks():
    """Test MIM-H03 coordinator selection precedence: id 0 overwrites prior non-mode candidates."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    discovered = [
        {"id": "9", "name": "Fallback Coord", "uuid": "FB_UUID"},
        {"id": "8", "name": "Second NonMode", "uuid": "SECOND_FB"},
        {"id": "0", "Mode": True, "uuid": "ZERO_UUID"},
    ]

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

        res = await flow._async_process_mim_h03(discovered)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_set_uid.assert_called_once_with("ZERO_UUID", raise_on_progress=False)
        assert flow.flow_data["unique_id"] == "ZERO_UUID"


@pytest.mark.asyncio
async def test_mim_h03_discovery_abort_no_coordinator():
    """Test MIM-H03 discovery aborts with no_coordinator_found if no coordinator device is present."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}

    res = await flow._async_process_mim_h03([{"id": "1", "Mode": True}])

    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "no_coordinator_found"


@pytest.mark.asyncio
async def test_mim_h03_discovery_abort_no_coordinator_uuid():
    """Test MIM-H03 discovery aborts with no_coordinator_uuid if coordinator has empty or missing uuid."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}

    res = await flow._async_process_mim_h03([{"id": "0", "name": "Coord No UUID"}])

    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "no_coordinator_uuid"


@pytest.mark.asyncio
async def test_mim_h03_discovery_reconfigure_and_reauth_skip_abort():
    """Test MIM-H03 discovery does not check _abort_if_unique_id_configured during reconfigure or reauth."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}

    discovered = [{"id": "0", "uuid": "COORD_UUID_123"}]

    # 1. During RECONFIGURE
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_RECONFIGURE}
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res = await flow._async_process_mim_h03(discovered)
        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_abort_if.assert_not_called()

    # 2. During REAUTH
    flow.reauth_entry = MagicMock()
    flow.context = {"source": SOURCE_USER}
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res = await flow._async_process_mim_h03(discovered)
        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_abort_if.assert_not_called()


# ============================================================================
# Group 6: async_step_discover_uuid
# ============================================================================


@pytest.mark.asyncio
async def test_async_step_discover_uuid_propagates_existing_unique_id():
    """Test async_step_discover_uuid propagates flow.unique_id into config_data."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER, "unique_id": "EXISTING_UID_555"}

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = None
        mock_ctrl.device_id = None
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

            res = await flow.async_step_discover_uuid()

            assert res["type"] == FlowResultType.CREATE_ENTRY
            mock_init.assert_called_once()
            passed_config = mock_init.call_args[0][0]
            assert passed_config["unique_id"] == "EXISTING_UID_555"


@pytest.mark.asyncio
async def test_async_step_discover_uuid_config_file_mapping():
    """Test async_step_discover_uuid maps device type to config file when not explicitly set."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    # Case A: Default mapping from DEVICE_TYPE_TO_CONFIG_FILE
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = None
        mock_ctrl.device_id = None
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            await flow.async_step_discover_uuid()
            passed_cfg = mock_init.call_args[0][0]
            assert (
                passed_cfg[CONF_CONFIG_FILE]
                == DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_MIM_H03]
            )

    # Case B: Preserves existing CONF_CONFIG_FILE
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_CONFIG_FILE: "custom_mim.yaml",
    }
    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = None
        mock_ctrl.device_id = None
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            await flow.async_step_discover_uuid()
            passed_cfg = mock_init.call_args[0][0]
            assert passed_cfg[CONF_CONFIG_FILE] == "custom_mim.yaml"

    # Case C: Unknown device type does not set CONF_CONFIG_FILE
    flow.flow_data = {CONF_DEVICE_TYPE: "non_existent_type"}
    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = None
        mock_ctrl.device_id = None
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            await flow.async_step_discover_uuid()
            passed_cfg = mock_init.call_args[0][0]
            assert CONF_CONFIG_FILE not in passed_cfg


@pytest.mark.asyncio
async def test_async_step_discover_uuid_init_returns_none_aborts():
    """Test async_step_discover_uuid aborts with cannot_connect if controller init returns None."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock, return_value=None
    ):
        res = await flow.async_step_discover_uuid()

        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "cannot_connect"


@pytest.mark.asyncio
async def test_async_step_discover_uuid_blind_device():
    """Test async_step_discover_uuid when no indoor units are discovered (blind device)."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = "BLIND_UNIQUE_123"
        mock_ctrl.device_id = "BLIND_DEV_123"
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with (
            patch.object(
                flow, "async_set_unique_id", new_callable=AsyncMock
            ) as mock_set_uid,
            patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
            patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

            res = await flow.async_step_discover_uuid()

            assert res["type"] == FlowResultType.CREATE_ENTRY
            mock_set_uid.assert_called_once_with(
                "BLIND_UNIQUE_123", raise_on_progress=False
            )
            assert flow.flow_data[CONF_DEVICE_ID] == "BLIND_DEV_123"
            mock_abort_if.assert_called_once_with(updates=flow.flow_data)
            mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_blind_device_no_unique_id():
    """Test async_step_discover_uuid for blind device without unique_id on controller."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = None
        mock_ctrl.device_id = None
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with (
            patch.object(
                flow, "async_set_unique_id", new_callable=AsyncMock
            ) as mock_set_uid,
            patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

            res = await flow.async_step_discover_uuid()

            assert res["type"] == FlowResultType.CREATE_ENTRY
            mock_set_uid.assert_not_called()
            mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_blind_device_reauth_and_reconfigure():
    """Test blind device skips _abort_if_unique_id_configured on reconfigure and reauth."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}

    # 1. SOURCE_RECONFIGURE
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_RECONFIGURE}
    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = "BLIND_UID"
        mock_ctrl.device_id = "BLIND_DID"
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with (
            patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
            patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
            patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            res = await flow.async_step_discover_uuid()
            assert res["type"] == FlowResultType.CREATE_ENTRY
            mock_abort_if.assert_not_called()

    # 2. REAUTH
    flow.reauth_entry = MagicMock()
    flow.context = {"source": SOURCE_USER}
    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = []
        mock_ctrl.unique_id = "BLIND_UID"
        mock_ctrl.device_id = "BLIND_DID"
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with (
            patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
            patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
            patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            res = await flow.async_step_discover_uuid()
            assert res["type"] == FlowResultType.CREATE_ENTRY
            mock_abort_if.assert_not_called()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_routes_to_mim_h03():
    """Test async_step_discover_uuid routes to _async_process_mim_h03 when device_type is MIM_H03."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    discovered = [
        {"id": "0", "name": "Coordinator", "uuid": "c_uuid"},
        {"id": "1", "name": "AC 1", "Mode": True},
    ]

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = discovered
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with patch.object(
            flow, "_async_process_mim_h03", new_callable=AsyncMock
        ) as mock_process_mim:
            mock_process_mim.return_value = {
                "type": FlowResultType.FORM,
                "step_id": "select_devices",
            }

            res = await flow.async_step_discover_uuid()

            assert res["type"] == FlowResultType.FORM
            mock_process_mim.assert_called_once_with(discovered)
            mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_routes_to_samsung_8888():
    """Test async_step_discover_uuid routes to _async_process_samsung_8888_discovery when device_type is SAMSUNG_8888."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    discovered = [{"uuid": "SAMSUNG_8888_UUID"}]

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = discovered
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with patch.object(
            flow, "_async_process_samsung_8888_discovery", new_callable=AsyncMock
        ) as mock_process_8888:
            mock_process_8888.return_value = {"type": FlowResultType.CREATE_ENTRY}

            res = await flow.async_step_discover_uuid()

            assert res["type"] == FlowResultType.CREATE_ENTRY
            mock_process_8888.assert_called_once_with(discovered)
            mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_routes_to_generic_discovery():
    """Test async_step_discover_uuid routes to _async_process_generic_discovery for generic device types."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    discovered = [
        {"id": "1", "name": "AC Unit 1"},
        {"id": "2", "name": "AC Unit 2"},
    ]

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock
    ) as mock_init:
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = discovered
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl

        with patch.object(
            flow, "_async_process_generic_discovery", new_callable=AsyncMock
        ) as mock_process_generic:
            mock_process_generic.return_value = {
                "type": FlowResultType.FORM,
                "step_id": "select_devices",
            }

            res = await flow.async_step_discover_uuid()

            assert res["type"] == FlowResultType.FORM
            mock_process_generic.assert_called_once_with(discovered)
            mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_invalid_header_shutdown_and_fallback():
    """Test that InvalidHeaderError shuts down controller before delegating to fallback raw discovery."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    mock_ctrl = MagicMock()
    mock_ctrl.discovered_devices = [{"id": "0", "name": "Coordinator"}]
    mock_ctrl.async_shutdown = AsyncMock()

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock, return_value=mock_ctrl
    ):
        with patch.object(
            flow,
            "_async_process_mim_h03",
            side_effect=InvalidHeaderError("Malformed header"),
        ):
            with patch.object(
                flow, "_async_fallback_raw_discovery", new_callable=AsyncMock
            ) as mock_fallback:
                async def verify_shutdown_before_fallback(_cfg):
                    mock_ctrl.async_shutdown.assert_called_once()
                    return {"type": FlowResultType.CREATE_ENTRY}

                mock_fallback.side_effect = verify_shutdown_before_fallback

                res = await flow.async_step_discover_uuid()

                assert res["type"] == FlowResultType.CREATE_ENTRY
                mock_ctrl.async_shutdown.assert_called_once()
                mock_fallback.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_generic_exception():
    """Test async_step_discover_uuid catches unexpected Exception and aborts with unknown_error."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    mock_ctrl = MagicMock()
    mock_ctrl.discovered_devices = [{"id": "0", "name": "Coordinator"}]
    mock_ctrl.async_shutdown = AsyncMock()

    with patch.object(
        flow, "_async_init_discovery_controller", new_callable=AsyncMock, return_value=mock_ctrl
    ):
        with patch.object(
            flow,
            "_async_process_mim_h03",
            side_effect=RuntimeError("unexpected discovery crash"),
        ):
            res = await flow.async_step_discover_uuid()

            assert res["type"] == FlowResultType.ABORT
            assert res["reason"] == "unknown_error"
            mock_ctrl.async_shutdown.assert_called()


# ============================================================================
# Group 7: async_step_select_devices
# ============================================================================


@pytest.mark.asyncio
async def test_async_step_select_devices_form_rendering():
    """Test async_step_select_devices renders form with correct schema and device count."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [
            {"id": "1", "name": "Living Room"},
            {"id": "2"},  # default name: Indoor Unit 2
        ],
    }

    res = await flow.async_step_select_devices()

    assert res["type"] == FlowResultType.FORM
    assert res["step_id"] == "select_devices"
    assert res["description_placeholders"] == {"device_count": 2}
    assert res["data_schema"] is not None

    schema_dict = res["data_schema"].schema
    found_field = False
    for marker, validator in schema_dict.items():
        if getattr(marker, "schema", None) == CONF_SELECTED_DEVICES:
            found_field = True
            assert marker.default() == ["1", "2"]
            assert getattr(validator, "options", None) == {
                "1": "Living Room",
                "2": "Indoor Unit 2",
            }
    assert found_field is True


@pytest.mark.asyncio
async def test_async_step_select_devices_empty_selection_shows_form_with_error():
    """Test async_step_select_devices with empty selection returns form with error."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [
            {"id": "1", "name": "Unit 1"},
            {"id": "2", "name": "Unit 2"},
        ],
    }

    res = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: []})

    assert res["type"] == FlowResultType.FORM
    assert res["step_id"] == "select_devices"
    assert res["errors"] == {"base": "no_devices_selected"}
    assert res["description_placeholders"] == {"device_count": 2}


@pytest.mark.asyncio
async def test_async_step_select_devices_submit_filters_devices():
    """Test async_step_select_devices filters CONF_DEVICES based on user selection."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [
            {"id": "1", "name": "Unit 1"},
            {"id": "2", "name": "Unit 2"},
            {"id": "3", "name": "Unit 3"},
        ],
        "unique_id": "MAIN_UID",
    }
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}

        res = await flow.async_step_select_devices(
            {CONF_SELECTED_DEVICES: ["2", "3"]}
        )

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data[CONF_DEVICES] == [
            {"id": "2", "name": "Unit 2"},
            {"id": "3", "name": "Unit 3"},
        ]
        mock_set_uid.assert_called_once_with("MAIN_UID", raise_on_progress=False)
        mock_abort_if.assert_called_once_with(updates=flow.flow_data)
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_select_devices_unique_id_cascades():
    """Test fallback cascades of unique_id in select_devices (unique_id -> CONF_MAC -> CONF_DEVICE_ID -> abort)."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    # 1. Fallback to CONF_MAC when unique_id is missing
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [{"id": "1", "name": "Unit 1"}],
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }
    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_set_uid.assert_called_once_with(
            "AA:BB:CC:DD:EE:FF", raise_on_progress=False
        )

    # 2. Fallback to CONF_DEVICE_ID when both unique_id and CONF_MAC are missing
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [{"id": "1", "name": "Unit 1"}],
        CONF_DEVICE_ID: "DEV_FALLBACK_123",
    }
    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_set_uid.assert_called_once_with(
            "DEV_FALLBACK_123", raise_on_progress=False
        )

    # 3. Abort when no unique_id can be resolved
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [{"id": "1", "name": "Unit 1"}],
    }
    res = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "no_unique_id"


@pytest.mark.asyncio
async def test_async_step_select_devices_reauth_and_reconfigure_skip_abort():
    """Test select_devices does not invoke _abort_if_unique_id_configured during reconfigure or reauth."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [{"id": "1", "name": "Unit 1"}],
        "unique_id": "MAIN_UID",
    }

    # 1. SOURCE_RECONFIGURE
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_RECONFIGURE}
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_abort_if.assert_not_called()

    # 2. REAUTH
    flow.reauth_entry = MagicMock()
    flow.context = {"source": SOURCE_USER}
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_abort_if.assert_not_called()
