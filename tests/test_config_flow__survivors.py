# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,too-many-locals,too-many-statements,broad-exception-caught
"""Tests designed to kill mutmut Ultra survivors in config_flow.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_DEVICE_ID, CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant
import pytest

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
)


async def test_kill_auth_file_not_found(hass):
    """Kill ValueError(None) and get("device", None) mutants."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    # 1. Test missing "auth_flow_file" key in "device"
    with patch(
        "custom_components.climate_ip.config_flow.load_yaml",
        return_value={"device": {}},
    ):
        with pytest.raises(ValueError, match="No 'auth_flow_file' found in"):
            await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)

    # 2. Test missing "device" key entirely
    with patch("custom_components.climate_ip.config_flow.load_yaml", return_value={}):
        with pytest.raises(ValueError, match="No 'auth_flow_file' found in"):
            await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)


async def test_kill_create_entry_device_id(hass):
    """Kill if dev_id in ("0", ...) mutant."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.async_create_entry = MagicMock(side_effect=lambda title, data: {"data": data})
    flow.async_abort = MagicMock(return_value={"aborted": True})

    # Passing a valid device_id should NOT be deleted
    flow.flow_data = {
        CONF_DEVICE_ID: "valid_id",
        "other": "data",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }
    entry = await flow._create_entry()
    assert entry["data"].get(CONF_DEVICE_ID) == "valid_id"

    # Passing an invalid device_id should be deleted
    flow.flow_data = {
        CONF_DEVICE_ID: "0",
        "other": "data",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }
    entry2 = await flow._create_entry()
    assert CONF_DEVICE_ID not in entry2["data"]


async def test_kill_acquirer_auth_flow_dict_process_samsung(hass):
    """Kill auth_flow_dict = None mutant in _async_process_samsung_device_step."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }

    auth_dict = {"mock_auth": "yes"}
    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._load_auth_flow_config",
            return_value=auth_dict,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acquirer,
    ):
        await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input={"dummy": "input"}
        )

        # Verify 3rd argument is exactly auth_dict
        mock_acquirer.assert_called_with(
            hass, ip_address="192.168.1.100", auth_config=auth_dict, cert_path=None
        )


async def test_kill_acquirer_auth_flow_dict_initiate_pairing(hass):
    """Kill auth_flow_dict = None mutant in async_step_initiate_pairing."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.acquirer = MagicMock(async_close=AsyncMock())
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }

    auth_dict = {"mock_auth": "yes"}
    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._load_auth_flow_config",
            return_value=auth_dict,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acquirer,
    ):
        fut = asyncio.Future()
        fut.set_result({"ok": False, "error": "test"})
        flow.task = fut

        await flow.async_step_initiate_pairing()
        mock_acquirer.assert_called_with(hass, "192.168.1.100", auth_dict, None)


async def test_kill_acquirer_auth_flow_dict_reconfigure_confirm(hass):
    """Kill auth_flow_dict = None mutant in async_step_reconfigure_confirm."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    mock_entry = MagicMock()
    mock_entry.unique_id = "AABBCCDDEEFF"
    mock_entry.data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }

    flow.reauth_entry = mock_entry
    flow.flow_data = mock_entry.data.copy()
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    auth_dict = {"mock_auth": "yes"}
    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._load_auth_flow_config",
            return_value=auth_dict,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_validate_cert_path",
            return_value=True,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow.async_step_initiate_pairing",
            return_value={},
        ),
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acquirer,
    ):
        try:
            await flow.async_step_reconfigure_confirm(
                {CONF_IP_ADDRESS: "192.168.1.100"}
            )
        except Exception:
            pass

        mock_acquirer.assert_called_with(hass, "192.168.1.100", auth_dict, None)


async def test_kill_auth_flow_dict_extraction(hass):
    """Kill get('auth_flow', {}) mutants in _load_auth_flow_config."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    # 1. Validar que extrae la sección 'auth_flow' correctamente
    mock_yaml_main = {"device": {"auth_flow_file": "auth.yaml"}}
    mock_yaml_auth = {"auth_flow": {"expected_key": "expected_val"}, "other": "ignored"}

    with patch(
        "custom_components.climate_ip.config_flow.load_yaml",
        side_effect=[mock_yaml_main, mock_yaml_auth],
    ):
        res = await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)
        assert res == {"expected_key": "expected_val"}
        assert res.get("expected_key") == "expected_val"

    # 2. Validar que el fallback {} actúa si 'auth_flow' no existe
    mock_yaml_no_auth = {"other_section": 123}
    with patch(
        "custom_components.climate_ip.config_flow.load_yaml",
        side_effect=[mock_yaml_main, mock_yaml_no_auth],
    ):
        res_empty = await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)
        assert res_empty == {}
        assert isinstance(res_empty, dict)


async def test_kill_process_samsung_device_type_fallback(hass):
    """Kill device_type fallback mutant (fallback to None) in _async_process_samsung_device_step."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }
    # Notice CONF_DEVICE_TYPE is NOT in flow.flow_data

    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._load_auth_flow_config",
            return_value={"mock": "auth"},
        ) as mock_load,
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch("custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"),
    ):
        # 1. Test is_8888=True -> should pass DEVICE_TYPE_SAMSUNG_8888
        await flow._async_process_samsung_device_step(
            "samsung_8888", is_8888=True, user_input={"dummy": "1"}
        )
        mock_load.assert_called_with(DEVICE_TYPE_SAMSUNG_8888)

        # 2. Test is_8888=False -> should pass DEVICE_TYPE_SAMSUNG_2878
        mock_load.reset_mock()
        await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input={"dummy": "2"}
        )
        mock_load.assert_called_with(DEVICE_TYPE_SAMSUNG_2878)

        # 3. Test when CONF_DEVICE_TYPE is present in flow_data (kills 'None' fallback mutant)
        mock_load.reset_mock()
        flow.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_MIM_H03
        await flow._async_process_samsung_device_step(
            "samsung_8888", is_8888=True, user_input={"dummy": "3"}
        )
        mock_load.assert_called_with(DEVICE_TYPE_MIM_H03)


async def test_kill_create_entry_more_cases(hass):
    """Kill mutants in _create_entry for title formatting, missing mac, reauth and reconfigure."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.async_create_entry = MagicMock(
        side_effect=lambda title, data: {"title": title, "data": data}
    )
    flow.async_abort = MagicMock(
        side_effect=lambda reason: {"aborted": True, "reason": reason}
    )
    flow.async_set_unique_id = AsyncMock()

    # 1. Missing both unique_id and CONF_MAC -> abort reason="no_mac_address_found"
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    res_no_mac = await flow._create_entry()
    assert res_no_mac == {"aborted": True, "reason": "no_mac_address_found"}

    # 2. Title generation: 8888 device where unique_id is NOT in title -> title is formatted with (unique_id)
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_MAC: "11:22:33:44:55:66",
        "name": "Living Room AC",
    }
    res_8888 = await flow._create_entry()
    assert res_8888["title"] == "Living Room AC (11:22:33:44:55:66)"
    assert res_8888["data"]["name"] == "Living Room AC"

    # 3. Title generation: 8888 device where unique_id IS in title -> title is NOT double formatted
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_MAC: "11:22:33:44:55:66",
        "name": "Samsung AC 11:22:33:44:55:66",
    }
    res_8888_dup = await flow._create_entry()
    assert res_8888_dup["title"] == "Samsung AC 11:22:33:44:55:66"

    # 4. Title generation: 2878 device where unique_id is NOT in title -> title is NOT formatted with (unique_id)
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "11:22:33:44:55:66",
        "name": "Living Room AC",
    }
    res_2878 = await flow._create_entry()
    assert res_2878["title"] == "Living Room AC"

    # 5. Title generation: MIM_H03 device where unique_id is NOT in title -> title is formatted with (unique_id)
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_MAC: "11:22:33:44:55:66",
        "name": "Heat Pump",
    }
    res_mim = await flow._create_entry()
    assert res_mim["title"] == "Heat Pump (11:22:33:44:55:66)"

    # 6. Title generation: empty name -> defaults to "Samsung AC {final_unique_id}"
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "11:22:33:44:55:66",
        "name": "",
    }
    res_empty_name = await flow._create_entry()
    assert res_empty_name["title"] == "Samsung AC 11:22:33:44:55:66"

    # 7. Reauth entry update
    mock_reauth_entry = MagicMock()
    mock_reauth_entry.entry_id = "reauth_123"
    flow.reauth_entry = mock_reauth_entry
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "11:22:33:44:55:66",
        "name": "Reauth AC",
        "discovered_devices": ["temp"],
        "selected_devices": ["temp"],
        CONF_TOKEN: "new_token",
    }
    with patch.object(
        flow,
        "async_update_reload_and_abort",
        return_value={"aborted": True, "reason": "reauth_successful"},
    ) as mock_update_reload_and_abort:
        res_reauth = await flow._create_entry()
        assert res_reauth == {"aborted": True, "reason": "reauth_successful"}
        mock_update_reload_and_abort.assert_called_once()
        assert mock_update_reload_and_abort.call_args[0][0] == mock_reauth_entry
        assert (
            "discovered_devices"
            not in mock_update_reload_and_abort.call_args.kwargs["data"]
        )
        assert (
            "selected_devices"
            not in mock_update_reload_and_abort.call_args.kwargs["data"]
        )
        assert (
            mock_update_reload_and_abort.call_args.kwargs["data"][CONF_TOKEN]
            == "new_token"
        )
        assert (
            mock_update_reload_and_abort.call_args.kwargs["reason"]
            == "reauth_successful"
        )

    # 8. Reconfigure source update
    flow.reauth_entry = None
    flow.context["source"] = SOURCE_RECONFIGURE
    mock_reconfig_entry = MagicMock()
    mock_reconfig_entry.entry_id = "reconfig_123"
    mock_reconfig_entry.data = {"old_key": "old_val", CONF_IP_ADDRESS: "1.1.1.1"}
    flow._get_reconfigure_entry = MagicMock(return_value=mock_reconfig_entry)
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "11:22:33:44:55:66",
        CONF_IP_ADDRESS: "2.2.2.2",
    }
    with patch.object(
        flow,
        "async_update_reload_and_abort",
        return_value={"aborted": True, "reason": "reconfigure_successful"},
    ) as mock_update_reload_and_abort:
        res_reconfig = await flow._create_entry()
        assert res_reconfig == {"aborted": True, "reason": "reconfigure_successful"}
        mock_update_reload_and_abort.assert_called_once()
        assert mock_update_reload_and_abort.call_args[0][0] == mock_reconfig_entry
        assert (
            mock_update_reload_and_abort.call_args.kwargs["data"][CONF_IP_ADDRESS]
            == "2.2.2.2"
        )
        assert (
            mock_update_reload_and_abort.call_args.kwargs["data"]["old_key"]
            == "old_val"
        )
        assert (
            mock_update_reload_and_abort.call_args.kwargs["reason"]
            == "reconfigure_successful"
        )

    # 9. Additional dev_id values: "main", "", "None" deleted; valid kept
    flow.context["source"] = "user"
    for invalid_id in ("main", "", "None"):
        flow.flow_data = {
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_MAC: "11:22:33:44:55:66",
            CONF_DEVICE_ID: invalid_id,
        }
        res_dev = await flow._create_entry()
        assert CONF_DEVICE_ID not in res_dev["data"]


async def test_kill_async_step_user_mutants(hass):
    """Kill mutants in async_step_user (not_implemented reason, schema options, step_id)."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    # 1. user_input=None -> show_form step_id="user" with all 5 device type options
    res_form = await flow.async_step_user(None)
    assert res_form["type"] == "form"
    assert res_form["step_id"] == "user"
    schema = res_form["data_schema"]
    selector_config = schema.schema[CONF_DEVICE_TYPE].config
    options = selector_config["options"]
    assert DEVICE_TYPE_SAMSUNG_2878 in options
    assert DEVICE_TYPE_SAMSUNG_8888 in options
    assert DEVICE_TYPE_MIM_H03 in options
    assert DEVICE_TYPE_SMARTTHINGS_HVAC in options
    assert DEVICE_TYPE_SMARTTHINGS_DHW in options

    # 2. user_input with unsupported device type -> abort reason="not_implemented"
    res_unsupported = await flow.async_step_user({CONF_DEVICE_TYPE: "unsupported_type"})
    assert res_unsupported["type"] == "abort"
    assert res_unsupported["reason"] == "not_implemented"


async def test_kill_async_step_handle_error_mutants(hass):
    """Kill mutants in async_step_handle_error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    # 1. pairing_connection_failed lethal abort with error_details placeholder
    flow.flow_data = {
        "error_key": "pairing_connection_failed",
        "error_details": "Socket timed out on port 8888",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.50",
    }
    res_abort = await flow.async_step_handle_error()
    assert res_abort["type"] == "abort"
    assert res_abort["reason"] == "pairing_connection_failed"
    assert res_abort["description_placeholders"]["ip_address"] == "192.168.1.50"
    assert (
        res_abort["description_placeholders"]["error_details"]
        == "Socket timed out on port 8888"
    )

    # 2. Recoverable error routing for MIM_H03
    flow.flow_data = {
        "error_key": "timeout_connect",
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_IP_ADDRESS: "192.168.1.51",
    }
    res_mim = await flow.async_step_handle_error()
    assert res_mim["type"] == "form"
    assert res_mim["step_id"] == "mim_h03"
    assert res_mim["errors"][CONF_IP_ADDRESS] == "timeout_connect"

    # 3. Recoverable error routing for SAMSUNG_8888
    flow.flow_data = {
        "error_key": "invalid_auth",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.52",
    }
    res_8888 = await flow.async_step_handle_error()
    assert res_8888["type"] == "form"
    assert res_8888["step_id"] == "samsung_8888"
    assert res_8888["errors"]["base"] == "invalid_auth"

    # 4. Recoverable error routing for SAMSUNG_2878 with mac_resolve_failed
    flow.flow_data = {
        "error_key": "mac_resolve_failed",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.53",
    }
    res_2878 = await flow.async_step_handle_error()
    assert res_2878["type"] == "form"
    assert res_2878["step_id"] == "samsung_2878"
    assert res_2878["errors"]["base"] == "mac_resolve_failed"
    assert CONF_MAC in res_2878["data_schema"].schema


async def test_kill_async_step_reauth_confirm_mutants(hass):
    """Kill mutants in async_step_reauth_confirm."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    # 1. user_input is None with reauth_entry -> show_form step_id="reauth_confirm", device_name placeholder
    mock_entry = MagicMock()
    mock_entry.title = "Master Bedroom AC"
    flow.reauth_entry = mock_entry
    res_form = await flow.async_step_reauth_confirm(None)
    assert res_form["type"] == "form"
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


async def test_kill_process_samsung_token_present_and_cert_forms(hass):
    """Kill mutants in _async_process_samsung_device_step for token presence and cert error form."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    # 1. Token is present in flow_data -> jumps directly to async_step_test_connection
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_TOKEN: "existing_valid_token",
    }
    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(
            flow, "async_step_test_connection", return_value={"type": "test_conn"}
        ) as mock_test_conn,
    ):
        res = await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input={"dummy": "val"}
        )
        assert res == {"type": "test_conn"}
        mock_test_conn.assert_called_once()

    # 2. Token is absent, cert validation fails -> show_form with exact step_id and cert_not_found error
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        "cert": "bad_cert.pem",
    }
    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=False),
    ):
        res_cert_err = await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input={"dummy": "val"}
        )
        assert res_cert_err["type"] == "form"
        assert res_cert_err["step_id"] == "samsung_2878"
        assert res_cert_err["errors"] == {"base": "cert_not_found"}

    # 3. user_input is None -> initial show_form with exact step_id and empty errors
    flow.flow_data = {}
    res_initial = await flow._async_process_samsung_device_step(
        "samsung_2878", is_8888=False, user_input=None
    )
    assert res_initial["type"] == "form"
    assert res_initial["step_id"] == "samsung_2878"
    assert res_initial["errors"] == {}


async def test_kill_reconfigure_confirm_is_8888_mim_h03_flag(hass):
    """Kill mutants in async_step_reconfigure_confirm checking is_8888 logic for MIM-H03 and 2878."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    mock_entry = MagicMock()
    mock_entry.data = {}
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    # 1. MIM-H03: is_8888 is True -> cert_def defaults to "ac14k_m.pem"
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_IP_ADDRESS: "192.168.1.100",
    }
    res_mim = await flow.async_step_reconfigure_confirm(None)
    assert res_mim["type"] == "form"
    assert res_mim["step_id"] == "reconfigure_confirm"

    # 2. SAMSUNG_2878: is_8888 is False, but is_samsung is True -> cert_def defaults to "ac14k_m.pem"
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
    }
    res_2878 = await flow.async_step_reconfigure_confirm(None)
    assert res_2878["type"] == "form"
    assert res_2878["step_id"] == "reconfigure_confirm"

    # 3. SMARTTHINGS_HVAC: is_8888 is False and is_samsung is False -> cert_def defaults to ""
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_IP_ADDRESS: "192.168.1.100",
    }
    res_st = await flow.async_step_reconfigure_confirm(None)
    assert res_st["type"] == "form"
    assert res_st["step_id"] == "reconfigure_confirm"


@pytest.mark.asyncio
async def test_create_entry_smartthings_fallback_unique_id(hass) -> None:
    """Kill mutants generating unique_id from token in _create_entry."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    # Provide a token of EXACTLY 8 characters to kill the `>= 8` vs `> 8` mutant
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_TOKEN: "12345678",
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    flow.async_set_unique_id = AsyncMock()
    with patch.object(
        flow, "async_create_entry", return_value={"type": "create_entry"}
    ):
        await flow._create_entry()
        flow.async_set_unique_id.assert_called_once_with("smartthings_hvac_12345678")


@pytest.mark.asyncio
async def test_progress_steps_flow_state_lost_abort(hass) -> None:
    """Kill reason=None mutants in acquirer None checks."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.acquirer = None  # Force state loss

    res1 = await flow.async_step_initiate_pairing()
    assert res1["type"] == "abort"
    assert res1["reason"] == "flow_state_lost"

    res2 = await flow.async_step_await_button()
    assert res2["type"] == "abort"
    assert res2["reason"] == "flow_state_lost"


@pytest.mark.asyncio
async def test_reauth_unknown_entry_abort(hass) -> None:
    """Kill reason=None mutant in async_step_reauth."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": "ghost_entry"}
    # Force config_entries.async_get_entry to return None
    flow.hass.config_entries.async_get_entry = MagicMock(return_value=None)

    res = await flow.async_step_reauth({})
    assert res["type"] == "abort"
    assert res["reason"] == "unknown_entry"


@pytest.mark.asyncio
async def test_initiate_pairing_closes_existing_acquirer(hass) -> None:
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
async def test_rest_api_items_explicit_none(hass) -> None:
    """Kill mutant assigning None as fallback for items."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_TOKEN: "valid_token_123",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_response = AsyncMock(status=200)
        mock_response.json.return_value = {"items": None}
        mock_response.__aenter__.return_value = mock_response
        mock_sess.return_value.get.return_value = mock_response

        with (
            patch.object(flow, "_abort_if_unique_id_configured"),
            patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
        ):
            await flow.async_step_rest_api({})
            # Should not crash and proceed to create_entry


@pytest.mark.asyncio
async def test_reconfigure_user_input_forwarding(hass: HomeAssistant) -> None:
    """Kill mutant in async_step_reconfigure replacing u_input with None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    mock_entry = MagicMock()
    mock_entry.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    mock_entry.unique_id = "AABBCCDDEEFF"
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    test_input = {CONF_IP_ADDRESS: "10.0.0.1", CONF_MAC: "AA:BB:CC:DD:EE:FF"}

    with patch.object(
        flow, "async_step_reconfigure_confirm", new_callable=AsyncMock
    ) as mock_confirm:
        mock_confirm.return_value = {"type": "create_entry"}
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
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    with patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None):
        result = await flow.async_step_reconfigure_confirm(
            user_input={CONF_IP_ADDRESS: "192.168.1.100", CONF_MAC: "AABBCCDDEEFF"}
        )

    assert result["type"] == "abort"
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
            mock_create.return_value = {"type": "create_entry"}
            result = await flow.async_step_rest_api(
                {CONF_IP_ADDRESS: "api.smartthings.com"}
            )

            assert result["type"] == "create_entry"
            assert flow.flow_data[CONF_DEVICE_ID] == "test-st-device-123"
            mock_set_uid.assert_awaited_once_with("test-st-device-123")


@pytest.mark.asyncio
async def test_create_entry_smartthings_fallback_to_ip(
    hass: HomeAssistant,
) -> None:
    """Kill mutants in _create_entry SmartThings unique_id fallback to IP (short token, no MAC)."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_TOKEN: "short",
        CONF_IP_ADDRESS: "192.168.1.50",
    }

    flow.async_set_unique_id = AsyncMock()
    with patch.object(
        flow, "async_create_entry", return_value={"type": "create_entry"}
    ):
        await flow._create_entry()
        flow.async_set_unique_id.assert_called_once_with(
            "smartthings_hvac_192.168.1.50"
        )
        assert flow.flow_data["unique_id"] == "smartthings_hvac_192.168.1.50"


@pytest.mark.asyncio
async def test_create_entry_smartthings_prefers_device_id_over_token(
    hass: HomeAssistant,
) -> None:
    """Kill mutant in _create_entry where dev_id is replaced with None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_DEVICE_ID: "st-device-override-id",
        CONF_TOKEN: "valid-long-token-12345678",
        CONF_IP_ADDRESS: "192.168.1.50",
    }

    flow.async_set_unique_id = AsyncMock()
    with patch.object(
        flow, "async_create_entry", return_value={"type": "create_entry"}
    ):
        await flow._create_entry()
        flow.async_set_unique_id.assert_called_once_with(
            "smartthings_hvac_st-device-override-id"
        )
        assert flow.flow_data["unique_id"] == "smartthings_hvac_st-device-override-id"


@pytest.mark.asyncio
async def test_rest_api_invalid_token_returns_form_step_id(
    hass: HomeAssistant,
) -> None:
    """Kill mutants in async_step_rest_api where step_id or data_schema is None or omitted on token error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    with patch("custom_components.climate_ip.helpers.sanitize_token", return_value=""):
        result = await flow.async_step_rest_api(
            {CONF_TOKEN: "   ", CONF_IP_ADDRESS: "192.168.1.10"}
        )
        assert result["type"] == "form"
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
    """Kill mutant 71 in async_step_rest_api checking len(token_str) >= 8 vs > 8."""
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
            mock_create.return_value = {"type": "create_entry"}
            result = await flow.async_step_rest_api({CONF_IP_ADDRESS: "192.168.1.99"})

            assert result["type"] == "create_entry"
            mock_set_uid.assert_awaited_once_with("smartthings_hvac_12345678")
