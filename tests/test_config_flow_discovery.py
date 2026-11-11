# pylint: disable=protected-access,line-too-long,trailing-newlines,too-many-lines
"""Canonical orthogonal tests for ConfigFlowDiscoveryMixin in config_flow_discovery.py."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_MAC
from homeassistant.data_entry_flow import AbortFlow, FlowResultType

# ============================================================================
# Group 1: _async_init_discovery_controller
# ============================================================================


@pytest.mark.asyncio
async def test_init_discovery_controller_success():
    """Test _async_init_discovery_controller returns ready controller when init and status succeed."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_cls,
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ),
    ):
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
async def test_init_discovery_controller_failures():
    """Test _async_init_discovery_controller returns None and shuts down controller if init or status fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_cls,
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ),
    ):
        # Case A: initialize fails
        mock_ctrl_init = MagicMock()
        mock_ctrl_init.initialize = AsyncMock(return_value=False)
        mock_ctrl_init.async_get_status = AsyncMock(return_value=True)
        mock_ctrl_init.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl_init

        res_init = await flow._async_init_discovery_controller(
            {"ip_address": "1.1.1.1"}
        )
        assert res_init is None
        mock_ctrl_init.initialize.assert_called_once()
        mock_ctrl_init.async_shutdown.assert_called_once()

        # Case B: async_get_status fails
        mock_ctrl_status = MagicMock()
        mock_ctrl_status.initialize = AsyncMock(return_value=True)
        mock_ctrl_status.async_get_status = AsyncMock(return_value=False)
        mock_ctrl_status.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl_status

        res_status = await flow._async_init_discovery_controller(
            {"ip_address": "1.1.1.1"}
        )
        assert res_status is None
        mock_ctrl_status.initialize.assert_called_once()
        mock_ctrl_status.async_get_status.assert_called_once()
        mock_ctrl_status.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_init_discovery_controller_exceptions():
    """Test _async_init_discovery_controller shuts down controller and propagates exceptions."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_cls,
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ),
    ):
        # Case A: InvalidHeaderError
        mock_ctrl_hdr = MagicMock()
        mock_ctrl_hdr.initialize = AsyncMock(
            side_effect=InvalidHeaderError("bad header")
        )
        mock_ctrl_hdr.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl_hdr

        with pytest.raises(InvalidHeaderError):
            await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})
        mock_ctrl_hdr.async_shutdown.assert_called_once()

        # Case B: generic RuntimeError
        mock_ctrl_err = MagicMock()
        mock_ctrl_err.initialize = AsyncMock(
            side_effect=RuntimeError("connection drop")
        )
        mock_ctrl_err.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl_err

        with pytest.raises(RuntimeError):
            await flow._async_init_discovery_controller({"ip_address": "1.1.1.1"})
        mock_ctrl_err.async_shutdown.assert_called_once()


# ============================================================================
# Group 2: _async_fallback_raw_discovery
# ============================================================================


@pytest.mark.asyncio
async def test_fallback_raw_discovery_failures():
    """Test _async_fallback_raw_discovery aborts with cannot_connect and shuts down when init or status fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {}
    flow.context = {"source": SOURCE_USER}

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_cls,
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ),
    ):
        # Case A: init fails
        mock_ctrl_init = MagicMock()
        mock_ctrl_init.initialize = AsyncMock(return_value=False)
        mock_ctrl_init.async_get_status = AsyncMock(return_value=True)
        mock_ctrl_init.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl_init

        res_init = await flow._async_fallback_raw_discovery({"ip_address": "1.1.1.1"})
        assert res_init["type"] == FlowResultType.ABORT
        assert res_init["reason"] == "cannot_connect"
        assert flow.flow_data[CONF_CONN_METHOD] == CONN_METHOD_RAW
        mock_ctrl_init.async_shutdown.assert_called_once()

        # Case B: status fails
        mock_ctrl_status = MagicMock()
        mock_ctrl_status.initialize = AsyncMock(return_value=True)
        mock_ctrl_status.async_get_status = AsyncMock(return_value=False)
        mock_ctrl_status.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl_status

        res_status = await flow._async_fallback_raw_discovery({"ip_address": "1.1.1.1"})
        assert res_status["type"] == FlowResultType.ABORT
        assert res_status["reason"] == "cannot_connect"
        mock_ctrl_status.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_raw_discovery_exception():
    """Test _async_fallback_raw_discovery handles unexpected controller exception and aborts."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {}
    flow.context = {"source": SOURCE_USER}

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_cls,
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ),
    ):
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(side_effect=RuntimeError("raw socket error"))
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._async_fallback_raw_discovery({"ip_address": "1.1.1.1"})

        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "cannot_connect"
        mock_ctrl.async_shutdown.assert_called_once()


# ============================================================================
# Group 3: _async_process_samsung_8888_discovery
# ============================================================================


@pytest.mark.asyncio
async def test_samsung_8888_discovery_success_uuid_or_id():
    """Test Samsung 8888 discovery resolves uuid or falls back to device id and creates entry."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_USER}

    # Case A: device has uuid
    flow.flow_data = {CONF_MAC: "AA:BB:CC:DD:EE:FF"}
    discovered_uuid = [{"uuid": "SAMSUNG_UUID_123", "id": "SAMSUNG_ID_999"}]
    with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res_uuid = await flow._async_process_samsung_8888_discovery(discovered_uuid)
        assert res_uuid["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data[CONF_DEVICE_ID] == "SAMSUNG_UUID_123"
        assert flow.flow_data[CONF_NAME] == "Samsung AC AA:BB:CC:DD:EE:FF"
        mock_create.assert_called_once()

    # Case B: device has no uuid, falls back to id
    flow.flow_data = {CONF_MAC: "11:22:33:44:55:66"}
    discovered_id = [{"uuid": "", "id": "FALLBACK_ID_789"}]
    with patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res_id = await flow._async_process_samsung_8888_discovery(discovered_id)
        assert res_id["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data[CONF_DEVICE_ID] == "FALLBACK_ID_789"
        assert flow.flow_data[CONF_NAME] == "Samsung AC 11:22:33:44:55:66"
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_samsung_8888_discovery_fails_no_uuid_no_id():
    """Test Samsung 8888 discovery aborts with discovery_failed when neither uuid nor id are found."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_MAC: "AA:BB:CC:DD:EE:FF"}
    flow.context = {"source": SOURCE_USER}

    discovered = [{"uuid": None, "id": None}]
    res = await flow._async_process_samsung_8888_discovery(discovered)

    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "discovery_failed"


# ============================================================================
# Group 4: _async_process_generic_discovery
# ============================================================================


@pytest.mark.asyncio
async def test_process_generic_discovery_detailed_mapping():
    """Test generic multi-split discovery properly maps id, uuid, name, and description."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {}
    flow.context = {"source": SOURCE_USER}

    discovered = [
        "invalid_device_string",
        {"id": "1", "uuid": "GEN_UUID_1", "name": "Living Unit"},
        {"id": "2", "uuid": "", "description": "Custom Bedroom"},
        {"id": "3"},
        {"uuid": "GEN_UUID_4"},
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
        assert flow.flow_data[CONF_DISCOVERED_DEVICES] == [
            {
                "id": "1",
                "uuid": "GEN_UUID_1",
                "name": "Living Unit",
                "description": "Living Unit",
            },
            {
                "id": "2",
                "uuid": "",
                "name": "Indoor Unit 2",
                "description": "Custom Bedroom",
            },
            {
                "id": "3",
                "uuid": "",
                "name": "Indoor Unit 3",
                "description": "Indoor Unit 3",
            },
            {
                "id": "{'uuid': 'GEN_UUID_4'}",
                "uuid": "GEN_UUID_4",
                "name": "Indoor Unit {'uuid': 'GEN_UUID_4'}",
                "description": "Indoor Unit {'uuid': 'GEN_UUID_4'}",
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
async def test_mim_h03_discovery_coordinator_selection_and_precedence():
    """Test MIM-H03 selects non-mode candidate and enforces id 0 precedence over non-mode devices."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    # Case A: Solo non-mode device candidate when id is not 0
    discovered_solo = [
        {"id": "9", "name": "Solo NonMode Coord", "uuid": "SOLO_NON_MODE_UUID"}
    ]
    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
    ):
        mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
        res_solo = await flow._async_process_mim_h03(discovered_solo)
        assert res_solo["type"] == FlowResultType.CREATE_ENTRY
        mock_set_uid.assert_called_once_with(
            "SOLO_NON_MODE_UUID", raise_on_progress=False
        )
        assert flow.flow_data[CONF_DEVICE_ID] == "9"
        assert flow.flow_data["unique_id"] == "SOLO_NON_MODE_UUID"
        assert flow.flow_data[CONF_NAME] == "Solo NonMode Coord SOLO_NON_MODE_UUID"
        mock_abort_if.assert_called_once_with(updates=flow.flow_data)
        mock_create.assert_called_once()

    # Case B: Precedence where id 0 overwrites prior non-mode candidates
    discovered_prec = [
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
        res_prec = await flow._async_process_mim_h03(discovered_prec)
        assert res_prec["type"] == FlowResultType.CREATE_ENTRY
        mock_set_uid.assert_called_once_with("ZERO_UUID", raise_on_progress=False)
        assert flow.flow_data["unique_id"] == "ZERO_UUID"


@pytest.mark.asyncio
async def test_mim_h03_discovery_abort_conditions():
    """Test MIM-H03 discovery aborts when no coordinator or coordinator uuid is found."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    # Case A: No coordinator found
    res_no_coord = await flow._async_process_mim_h03([])
    assert res_no_coord["type"] == FlowResultType.ABORT
    assert res_no_coord["reason"] == "no_coordinator_found"

    # Case B: Coordinator has empty uuid
    res_no_uuid = await flow._async_process_mim_h03([{"id": "0", "uuid": ""}])
    assert res_no_uuid["type"] == FlowResultType.ABORT
    assert res_no_uuid["reason"] == "no_coordinator_uuid"

    # Case C: Coordinator dict missing uuid key completely
    res_missing_uuid = await flow._async_process_mim_h03([{"id": "0"}])
    assert res_missing_uuid["type"] == FlowResultType.ABORT
    assert res_missing_uuid["reason"] == "no_coordinator_uuid"


@pytest.mark.asyncio
async def test_mim_h03_discovery_reconfigure_and_reauth_skip_abort() -> None:
    """Test that MIM-H03 discovery does not abort on existing unique_id during reconfigure or reauth."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}

    discovered = [
        {"id": "0", "name": "MIM Coordinator", "uuid": "COORD_UUID_123"},
        {"id": "1", "name": "AC 1", "Mode": True},
    ]

    # 1. SOURCE_RECONFIGURE skips _abort_if_unique_id_configured
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_RECONFIGURE}
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
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
        mock_abort_if.assert_not_called()

    # 2. REAUTH skips _abort_if_unique_id_configured
    flow.reauth_entry = MagicMock()
    flow.context = {"source": SOURCE_USER}
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
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
        mock_abort_if.assert_not_called()


# ============================================================================
# Group 6: async_step_discover_uuid
# ============================================================================


@pytest.mark.asyncio
async def test_async_step_discover_uuid_config_and_unique_id_prep():
    """Test async_step_discover_uuid propagates flow.unique_id and maps device type to config file."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER, "unique_id": "EXISTING_UID_555"}

    # Case A: Default mapping from DEVICE_TYPE_TO_CONFIG_FILE and propagated unique_id
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
            assert passed_cfg["unique_id"] == "EXISTING_UID_555"
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
    """Test async_step_discover_uuid aborts with cannot_connect when discovery controller init fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with patch.object(
        flow,
        "_async_init_discovery_controller",
        new_callable=AsyncMock,
        return_value=None,
    ):
        res = await flow.async_step_discover_uuid()

        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "cannot_connect"


@pytest.mark.asyncio
async def test_async_step_discover_uuid_blind_device_lifecycle():
    """Test blind device flow: creates entry, sets unique_id/device_id, and handles reauth/reconfigure."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}

    # Case A: Standard user source invokes _abort_if_unique_id_configured
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

    # Case B: SOURCE_RECONFIGURE skips _abort_if_unique_id_configured
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

    # Case C: Reauth entry skips _abort_if_unique_id_configured
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
async def test_async_step_discover_uuid_routing_delegation():
    """Test async_step_discover_uuid routes to MIM-H03, Samsung 8888, or generic discovery."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    # Case A: MIM_H03 routing
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    discovered_mim = [{"id": "0", "name": "Coordinator", "uuid": "c_uuid"}]
    with (
        patch.object(
            flow, "_async_init_discovery_controller", new_callable=AsyncMock
        ) as mock_init,
        patch.object(
            flow, "_async_process_mim_h03", new_callable=AsyncMock
        ) as mock_mim,
    ):
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = discovered_mim
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl
        mock_mim.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "select_devices",
        }

        res = await flow.async_step_discover_uuid()
        assert res["type"] == FlowResultType.FORM
        mock_mim.assert_called_once_with(discovered_mim)
        mock_ctrl.async_shutdown.assert_called_once()

    # Case B: Samsung 8888 routing
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    discovered_8888 = [{"uuid": "SAMSUNG_8888_UUID"}]
    with (
        patch.object(
            flow, "_async_init_discovery_controller", new_callable=AsyncMock
        ) as mock_init,
        patch.object(
            flow, "_async_process_samsung_8888_discovery", new_callable=AsyncMock
        ) as mock_8888,
    ):
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = discovered_8888
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl
        mock_8888.return_value = {"type": FlowResultType.CREATE_ENTRY}

        res = await flow.async_step_discover_uuid()
        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_8888.assert_called_once_with(discovered_8888)
        mock_ctrl.async_shutdown.assert_called_once()

    # Case C: Generic routing
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    discovered_generic = [{"id": "1", "name": "AC Unit 1"}]
    with (
        patch.object(
            flow, "_async_init_discovery_controller", new_callable=AsyncMock
        ) as mock_init,
        patch.object(
            flow, "_async_process_generic_discovery", new_callable=AsyncMock
        ) as mock_generic,
    ):
        mock_ctrl = MagicMock()
        mock_ctrl.discovered_devices = discovered_generic
        mock_ctrl.async_shutdown = AsyncMock()
        mock_init.return_value = mock_ctrl
        mock_generic.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "select_devices",
        }

        res = await flow.async_step_discover_uuid()
        assert res["type"] == FlowResultType.FORM
        mock_generic.assert_called_once_with(discovered_generic)
        mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_invalid_header_shutdown_and_fallback():
    """Test that InvalidHeaderError shuts down controller and falls back to raw socket engine."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    http_ctrl = MagicMock()
    http_ctrl.initialize = AsyncMock(return_value=True)
    http_ctrl.async_get_status = AsyncMock(return_value={"status": "ok"})
    http_ctrl.discovered_devices = [{"id": "0", "name": "Coordinator"}]
    http_ctrl.async_shutdown = AsyncMock()

    async def _raw_init():
        assert http_ctrl.async_shutdown.await_count == 1
        return True

    raw_ctrl = MagicMock()
    raw_ctrl.initialize = AsyncMock(side_effect=_raw_init)
    raw_ctrl.async_get_status = AsyncMock(return_value={"status": "ok"})
    raw_ctrl.async_shutdown = AsyncMock()

    ctrl_queue = [http_ctrl, raw_ctrl]
    config_snapshots: list[dict[str, Any]] = []

    def _build_controller(**kwargs):
        config_snapshots.append(dict(kwargs["config"]))
        return ctrl_queue.pop(0)

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController",
            side_effect=_build_controller,
        ),
        patch(
            "custom_components.climate_ip.config_flow_discovery.aiohttp_client.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch.object(
            flow,
            "_async_process_samsung_8888_discovery",
            side_effect=InvalidHeaderError("Malformed HTTP response"),
        ),
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ) as mock_create,
    ):
        res = await flow.async_step_discover_uuid()

    assert res["type"] == FlowResultType.CREATE_ENTRY
    assert len(config_snapshots) == 2
    assert config_snapshots[0].get(CONF_CONN_METHOD) != CONN_METHOD_RAW
    assert config_snapshots[1][CONF_CONN_METHOD] == CONN_METHOD_RAW
    assert flow.flow_data[CONF_CONN_METHOD] == CONN_METHOD_RAW
    http_ctrl.async_shutdown.assert_awaited_once()
    raw_ctrl.initialize.assert_awaited_once()
    raw_ctrl.async_get_status.assert_awaited_once()
    raw_ctrl.async_shutdown.assert_awaited_once()
    mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_step_discover_uuid_exceptions():
    """Test async_step_discover_uuid re-raises AbortFlow and catches Exception, shutting down controller."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    mock_ctrl = MagicMock()
    mock_ctrl.discovered_devices = [{"id": "0", "name": "Coordinator"}]
    mock_ctrl.async_shutdown = AsyncMock()

    # Case A: Generic exception aborts with unknown_error
    with (
        patch.object(
            flow,
            "_async_init_discovery_controller",
            new_callable=AsyncMock,
            return_value=mock_ctrl,
        ),
        patch.object(
            flow,
            "_async_process_mim_h03",
            side_effect=RuntimeError("unexpected discovery crash"),
        ),
    ):
        res = await flow.async_step_discover_uuid()
        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "unknown_error"
        mock_ctrl.async_shutdown.assert_called()

    # Case B: AbortFlow is re-raised directly
    mock_ctrl.async_shutdown.reset_mock()
    with (
        patch.object(
            flow,
            "_async_init_discovery_controller",
            new_callable=AsyncMock,
            return_value=mock_ctrl,
        ),
        patch.object(
            flow,
            "_async_process_mim_h03",
            side_effect=AbortFlow("already_configured"),
        ),
    ):
        with pytest.raises(AbortFlow) as exc_info:
            await flow.async_step_discover_uuid()
        assert exc_info.value.reason == "already_configured"
        mock_ctrl.async_shutdown.assert_called()


# ============================================================================
# Group 7: async_step_select_devices
# ============================================================================


@pytest.mark.asyncio
async def test_async_step_select_devices_form_rendering():
    """Test async_step_select_devices renders schema and placeholders on initial GET."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [
            {"id": "1", "name": "Unit 1"},
            {"id": "2"},  # Fallback to f"Indoor Unit {device['id']}"
        ]
    }
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    mock_schema = MagicMock()
    with (
        patch.object(
            flow, "_get_select_devices_schema", return_value=mock_schema
        ) as mock_schema_gen,
        patch.object(flow, "async_show_form") as mock_show_form,
    ):
        mock_show_form.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "select_devices",
        }

        res = await flow.async_step_select_devices()

        assert res["type"] == FlowResultType.FORM
        mock_schema_gen.assert_called_once_with({"1": "Unit 1", "2": "Indoor Unit 2"})
        mock_show_form.assert_called_once_with(
            step_id="select_devices",
            data_schema=mock_schema,
            description_placeholders={"device_count": 2},
        )


@pytest.mark.asyncio
async def test_async_step_select_devices_empty_selection_shows_form_with_error():
    """Test async_step_select_devices re-renders form with error when no devices are chosen."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [{"id": "1", "name": "Unit 1"}],
    }
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    mock_schema = MagicMock()
    with (
        patch.object(
            flow, "_get_select_devices_schema", return_value=mock_schema
        ) as mock_schema_gen,
        patch.object(flow, "async_show_form") as mock_show_form,
    ):
        mock_show_form.return_value = {
            "type": FlowResultType.FORM,
            "step_id": "select_devices",
        }

        res = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: []})

        assert res["type"] == FlowResultType.FORM
        mock_schema_gen.assert_called_once_with({"1": "Unit 1"})
        mock_show_form.assert_called_once_with(
            step_id="select_devices",
            data_schema=mock_schema,
            errors={"base": "no_devices_selected"},
            description_placeholders={"device_count": 1},
        )


@pytest.mark.asyncio
async def test_async_step_select_devices_submit_filters_devices():
    """Test async_step_select_devices filters selected devices into flow_data and creates entry."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        "unique_id": "MAIN_CONTROLLER_UUID",
        CONF_DISCOVERED_DEVICES: [
            {"id": "1", "name": "Unit 1"},
            {"id": "2", "name": "Unit 2"},
            {"id": "3", "name": "Unit 3"},
        ],
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

        res = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1", "3"]})

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data[CONF_DEVICES] == [
            {"id": "1", "name": "Unit 1"},
            {"id": "3", "name": "Unit 3"},
        ]
        mock_set_uid.assert_called_once_with(
            "MAIN_CONTROLLER_UUID", raise_on_progress=False
        )
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
