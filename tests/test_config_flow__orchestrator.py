"""Tests for ClimateIpConfigFlow main orchestrator in config_flow.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_ip.config_flow import (
    ClimateIpConfigFlow,
    OptionsFlowHandler,
)
from custom_components.climate_ip.const import (
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONF_POLL_INTERVAL,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
)
from homeassistant.const import CONF_DEVICE_ID, CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


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
async def test_user_step_mim_h03_routing(hass: HomeAssistant) -> None:
    """Kill mutant in async_step_user routing to mim_h03."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    result = await flow.async_step_user({CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mim_h03"


@pytest.mark.asyncio
async def test_step_reauth_confirm_mim_h03_routing() -> None:
    """Test reauth confirm routing for MIM-H03."""
    flow = ClimateIpConfigFlow()
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
async def test_reauth_unknown_entry_abort() -> None:
    """Kill reason=None mutant in async_step_reauth when entry is missing."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"entry_id": "ghost_entry"}
    flow.hass.config_entries.async_get_entry = MagicMock(return_value=None)

    res = await flow.async_step_reauth({})
    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "unknown_entry"


@pytest.mark.asyncio
async def test_reauth_confirm_mutants_and_routing() -> None:
    """Kill mutants in async_step_reauth_confirm placeholders and device routing."""
    flow = ClimateIpConfigFlow()

    # 1. user_input is None with reauth_entry -> show_form step_id="reauth_confirm", device_name placeholder
    mock_entry = MagicMock()
    mock_entry.title = "Master Bedroom AC"
    flow.reauth_entry = mock_entry
    res_form = await flow.async_step_reauth_confirm(None)
    assert res_form["type"] == FlowResultType.FORM
    assert res_form["step_id"] == "reauth_confirm"
    assert res_form["description_placeholders"]["device_name"] == "Master Bedroom AC"

    # 2. user_input is None with no reauth_entry -> device_name placeholder "Unknown Device"
    flow.reauth_entry = None
    res_form_none = await flow.async_step_reauth_confirm(None)
    assert res_form_none["description_placeholders"]["device_name"] == "Unknown Device"

    # 3. user_input provided: route to SMARTTHINGS_HVAC
    flow.reauth_entry = mock_entry
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_TOKEN: "old_tok",
    }
    with patch.object(
        flow, "async_step_rest_api", return_value={"step": "rest_api"}
    ) as mock_rest:
        res = await flow.async_step_reauth_confirm({})
        assert res == {"step": "rest_api"}
        assert CONF_TOKEN not in flow.flow_data
        mock_rest.assert_called_once()

    # 4. user_input provided: route to SMARTTHINGS_DHW
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW,
        CONF_TOKEN: "old_tok",
    }
    with patch.object(
        flow, "async_step_rest_api", return_value={"step": "rest_api_dhw"}
    ) as mock_rest:
        res = await flow.async_step_reauth_confirm({})
        assert res == {"step": "rest_api_dhw"}
        mock_rest.assert_called_once()

    # 5. user_input provided: route to SAMSUNG_2878
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878, CONF_TOKEN: "old_tok"}
    with patch.object(
        flow, "async_step_samsung_2878", return_value={"step": "samsung_2878"}
    ) as mock_2878:
        res = await flow.async_step_reauth_confirm({})
        assert res == {"step": "samsung_2878"}
        mock_2878.assert_called_once()

    # 6. user_input provided: route to SAMSUNG_8888
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888, CONF_TOKEN: "old_tok"}
    with patch.object(
        flow, "async_step_samsung_8888", return_value={"step": "samsung_8888"}
    ) as mock_8888:
        res = await flow.async_step_reauth_confirm({})
        assert res == {"step": "samsung_8888"}
        mock_8888.assert_called_once()


@pytest.mark.asyncio
async def test_progress_steps_flow_state_lost_abort(hass: HomeAssistant) -> None:
    """Kill reason=None mutants in acquirer None checks."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.acquirer = None  # Force state loss

    res1 = await flow.async_step_initiate_pairing()
    assert res1["type"] == FlowResultType.ABORT
    assert res1["reason"] == "flow_state_lost"

    res2 = await flow.async_step_await_button()
    assert res2["type"] == FlowResultType.ABORT
    assert res2["reason"] == "flow_state_lost"


@pytest.mark.asyncio
async def test_initiate_pairing_closes_existing_acquirer(hass: HomeAssistant) -> None:
    """Kill condition flip mutant ensuring old acquirer is closed on fallback."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    flow.acquirer = MagicMock(async_close=AsyncMock())
    old_acquirer = flow.acquirer
    flow.task = MagicMock(done=lambda: True, result=lambda: {"ok": False})

    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._load_auth_flow_config",
            return_value={},
        ),
        patch("custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"),
    ):
        await flow.async_step_initiate_pairing()

    old_acquirer.async_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconfigure_user_input_forwarding(hass: HomeAssistant) -> None:
    """Kill mutant in async_step_reconfigure replacing user_input with None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    mock_entry = MagicMock()
    mock_entry.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    mock_entry.unique_id = "AABBCCDDEEFF"

    test_input = {CONF_IP_ADDRESS: "10.0.0.1", CONF_MAC: "AA:BB:CC:DD:EE:FF"}

    with (
        patch.object(flow, "_get_reconfigure_entry", return_value=mock_entry),
        patch.object(
            flow, "async_step_reconfigure_confirm", new_callable=AsyncMock
        ) as mock_confirm,
    ):
        mock_confirm.return_value = {"type": FlowResultType.CREATE_ENTRY}
        await flow.async_step_reconfigure(test_input)
        mock_confirm.assert_awaited_once_with(test_input)


@pytest.mark.asyncio
async def test_reconfigure_unique_id_mismatch(hass: HomeAssistant) -> None:
    """Test reconfigure aborts with unique_id_mismatch when MAC does not match existing unique_id."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    mock_entry = MagicMock()
    mock_entry.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    mock_entry.unique_id = "112233445566"
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    with (
        patch.object(flow, "_get_reconfigure_entry", return_value=mock_entry),
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
    ):
        result = await flow.async_step_reconfigure_confirm(
            user_input={CONF_IP_ADDRESS: "192.168.1.100", CONF_MAC: "AABBCCDDEEFF"}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"


@pytest.mark.asyncio
async def test_async_step_rest_api_device_id_extraction(hass: HomeAssistant) -> None:
    """Test extracting deviceId from SmartThings items array in async_step_rest_api."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_TOKEN: "valid-smartthings-token-12345",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"items": [{"deviceId": "test-st-device-123"}]}
        )
        mock_response.__aenter__.return_value = mock_response
        mock_session.return_value.get.return_value = mock_response

        with (
            patch.object(
                flow, "async_set_unique_id", new_callable=AsyncMock
            ) as mock_set_uid,
            patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            result = await flow.async_step_rest_api(
                {CONF_IP_ADDRESS: "api.smartthings.com"}
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert flow.flow_data[CONF_DEVICE_ID] == "test-st-device-123"
            mock_set_uid.assert_awaited_once_with("test-st-device-123")


@pytest.mark.asyncio
async def test_rest_api_invalid_token_returns_form_step_id(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_rest_api where step_id or data_schema is None or omitted on token error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    with patch("custom_components.climate_ip.helpers.sanitize_token", return_value=""):
        result = await flow.async_step_rest_api(
            {CONF_TOKEN: "   ", CONF_IP_ADDRESS: "192.168.1.10"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "rest_api"
        assert result["errors"] == {CONF_TOKEN: "invalid_token_format"}
        assert result["data_schema"] is not None
        schema_keys = [getattr(k, "schema", k) for k in result["data_schema"].schema]
        assert CONF_IP_ADDRESS in schema_keys
        assert CONF_TOKEN in schema_keys


@pytest.mark.asyncio
async def test_rest_api_smartthings_token_exact_8_chars_suffix(
    hass: HomeAssistant,
) -> None:
    """Kill mutant in async_step_rest_api checking len(token_str) >= 8 vs > 8."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_TOKEN: "12345678",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"items": []})
        mock_response.__aenter__.return_value = mock_response
        mock_session.return_value.get.return_value = mock_response

        with (
            patch.object(
                flow, "async_set_unique_id", new_callable=AsyncMock
            ) as mock_set_uid,
            patch.object(flow, "_create_entry", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = {"type": FlowResultType.CREATE_ENTRY}
            result = await flow.async_step_rest_api({CONF_IP_ADDRESS: "192.168.1.99"})

            assert result["type"] == FlowResultType.CREATE_ENTRY
            mock_set_uid.assert_awaited_once_with("smartthings_hvac_12345678")


@pytest.mark.asyncio
async def test_rest_api_empty_errors_dict(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_rest_api mutating or omitting errors={}."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    with patch.object(
        flow, "async_show_form", wraps=flow.async_show_form
    ) as spy_show_form:
        result = await flow.async_step_rest_api(None)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "rest_api"
        assert result["errors"] == {}
        assert result["errors"] is not None
        assert "errors" in spy_show_form.call_args.kwargs
        assert spy_show_form.call_args.kwargs["errors"] == {}
        assert spy_show_form.call_args.kwargs["errors"] is not None


def test_is_matching_ip_and_mac() -> None:
    """Test is_matching method comparing IP and MAC addresses across flow_data and context."""
    flow1 = ClimateIpConfigFlow()
    flow1.flow_data = {CONF_IP_ADDRESS: "192.168.1.10", CONF_MAC: "AABBCCDDEEFF"}

    flow2 = ClimateIpConfigFlow()
    flow2.flow_data = {CONF_IP_ADDRESS: "192.168.1.10", CONF_MAC: "112233445566"}
    assert flow1.is_matching(flow2) is False

    flow3 = ClimateIpConfigFlow()
    flow3.flow_data = {CONF_IP_ADDRESS: "192.168.1.11", CONF_MAC: "aabbccddeeff"}
    assert flow1.is_matching(flow3) is True

    # Test pure IP matching (no MAC) across flow_data
    flow_ip1 = ClimateIpConfigFlow()
    flow_ip1.flow_data = {CONF_IP_ADDRESS: "192.168.1.50"}
    flow_ip2 = ClimateIpConfigFlow()
    flow_ip2.flow_data = {CONF_IP_ADDRESS: "192.168.1.50"}
    assert flow_ip1.is_matching(flow_ip2) is True

    flow_ip3 = ClimateIpConfigFlow()
    flow_ip3.flow_data = {CONF_IP_ADDRESS: "192.168.1.51"}
    assert flow_ip1.is_matching(flow_ip3) is False

    # Test context vs flow_data matching (both directions)
    flow_ctx = ClimateIpConfigFlow()
    flow_ctx.context = {CONF_IP_ADDRESS: "10.0.0.5"}
    flow_data_match = ClimateIpConfigFlow()
    flow_data_match.flow_data = {CONF_IP_ADDRESS: "10.0.0.5"}
    assert flow_ctx.is_matching(flow_data_match) is True
    assert flow_data_match.is_matching(flow_ctx) is True

    flow_ctx_mac = ClimateIpConfigFlow()
    flow_ctx_mac.context = {CONF_MAC: "AA:BB:CC:DD:EE:FF"}
    flow_data_mac = ClimateIpConfigFlow()
    flow_data_mac.flow_data = {CONF_MAC: "aa:bb:cc:dd:ee:ff"}
    assert flow_ctx_mac.is_matching(flow_data_mac) is True
    assert flow_data_mac.is_matching(flow_ctx_mac) is True

    # Test empty flows return False
    empty1 = ClimateIpConfigFlow()
    empty2 = ClimateIpConfigFlow()
    assert empty1.is_matching(empty2) is False


def test_is_matching_asymmetric_inputs() -> None:
    """Kill 'and' to 'or' logic flips in is_matching."""
    flow1 = ClimateIpConfigFlow()
    flow1.flow_data = {CONF_MAC: "AA:BB:CC"}
    flow2 = ClimateIpConfigFlow()
    flow2.flow_data = {CONF_IP_ADDRESS: "1.1.1.1"}  # Missing MAC

    # If 'and' was flipped to 'or', this would throw AttributeError on None.upper()
    assert flow1.is_matching(flow2) is False


async def test_config_flow_async_remove(hass: HomeAssistant) -> None:
    """Kill mutants inside async_remove by asserting task cancellation and acquirer cleanup."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    mock_task = MagicMock()
    mock_acquirer = AsyncMock()

    flow.task = mock_task
    flow.acquirer = mock_acquirer

    flow.async_remove()

    mock_task.cancel.assert_called_once()
    mock_acquirer.async_close.assert_called_once()

    flow.hass.async_create_task.assert_called_once()
    _, task_kwargs = flow.hass.async_create_task.call_args
    assert task_kwargs.get("name") == "climate_ip_config_flow_acquirer_close"
    assert task_kwargs.get("eager_start") is True


async def test_config_flow_async_get_options_flow() -> None:
    """Assert async_get_options_flow returns OptionsFlowHandler bound to entry."""
    mock_entry = MockConfigEntry(domain="climate_ip", title="Test", data={})
    options_flow = ClimateIpConfigFlow.async_get_options_flow(mock_entry)

    assert isinstance(options_flow, OptionsFlowHandler)
    assert options_flow._config_entry is mock_entry


async def test_config_flow_options_falsy_values(hass: HomeAssistant) -> None:
    """Kill None fallback mutants in _get_options_schema."""
    mock_entry = MockConfigEntry(
        domain="climate_ip",
        title="Test",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_CONN_METHOD: "should_not_be_used",
            CONF_POLL_INTERVAL: 999,
        },
        options={CONF_CONN_METHOD: "", CONF_POLL_INTERVAL: 0},
    )

    options_flow = ClimateIpConfigFlow.async_get_options_flow(mock_entry)
    schema = options_flow._get_options_schema()

    conn_marker = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_CONN_METHOD
    )
    assert conn_marker.default() == ""

    poll_marker = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    assert poll_marker.default() == "0:00:00"
