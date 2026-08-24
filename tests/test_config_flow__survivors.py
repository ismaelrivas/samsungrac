# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,too-many-locals,too-many-statements,broad-exception-caught
"""Tests designed to kill mutmut Ultra survivors in config_flow.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_DEVICE_ID, CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
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
    with (
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
        patch.object(hass.config_entries, "async_reload") as mock_reload,
    ):
        res_reauth = await flow._create_entry()
        assert res_reauth == {"aborted": True, "reason": "reauth_successful"}
        mock_update.assert_called_once()
        assert mock_update.call_args[0][0] == mock_reauth_entry
        assert "discovered_devices" not in mock_update.call_args[1]["data"]
        assert "selected_devices" not in mock_update.call_args[1]["data"]
        assert mock_update.call_args[1]["data"][CONF_TOKEN] == "new_token"
        mock_reload.assert_called_once_with("reauth_123")

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
    with (
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
        patch.object(hass.config_entries, "async_reload") as mock_reload,
    ):
        res_reconfig = await flow._create_entry()
        assert res_reconfig == {"aborted": True, "reason": "reconfigure_successful"}
        mock_update.assert_called_once()
        assert mock_update.call_args[0][0] == mock_reconfig_entry
        assert mock_update.call_args[1]["data"][CONF_IP_ADDRESS] == "2.2.2.2"
        assert mock_update.call_args[1]["data"]["old_key"] == "old_val"
        mock_reload.assert_called_once_with("reconfig_123")

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


async def test_kill_rest_api_token_invalid_form(hass):
    """Kill mutants in async_step_rest_api for invalid token formatting."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    # Invalid token (e.g. spaces only) -> returns form with step_id="rest_api" and error on CONF_TOKEN
    with patch("custom_components.climate_ip.helpers.sanitize_token", return_value=""):
        res = await flow.async_step_rest_api(
            {CONF_TOKEN: "   ", CONF_IP_ADDRESS: "192.168.1.50"}
        )
        assert res["type"] == "form"
        assert res["step_id"] == "rest_api"
        assert res["errors"] == {CONF_TOKEN: "invalid_token_format"}


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
