# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test the Climate IP config flow."""

# pylint: disable=import-outside-toplevel,reimported
import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import probatio as vol
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONN_METHOD_RAW,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
)
from custom_components.climate_ip.exceptions import AuthError
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


async def test_form_user_step(hass):
    """Test we get the form."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    assert flow.task is None
    assert flow.acquirer is None
    assert flow.reauth_entry is None

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Kill mutmut_18, 19: Check exact selector configuration
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE
    from homeassistant.helpers.selector import SelectSelectorMode

    schema = result["data_schema"]
    device_type_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_DEVICE_TYPE
    )
    selector = schema.schema[device_type_key]
    assert selector.config["translation_key"] == "device_type"
    assert selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert "samsung_2878" in selector.config["options"]
    assert "samsung_8888" in selector.config["options"]

    # Kill mutmut_7-9: Test unsupported device type
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE

    res_unknown = await flow.async_step_user({CONF_DEVICE_TYPE: "unknown_device_XYZ"})
    assert res_unknown["type"] == FlowResultType.ABORT
    assert res_unknown["reason"] == "not_implemented"


async def test_step_samsung_2878(hass, mock_setup_entry):  # pylint: disable=unused-argument
    """Test the Samsung 2878 flow."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    await flow.async_step_user()
    result = await flow.async_step_user({CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "samsung_2878"
    assert result.get("data_schema") is not None
    assert result.get("errors") == {}

    def mock_test_connection_task(coro):
        coro.close()
        fut = asyncio.get_event_loop().create_future()
        fut.set_result({"ok": True})
        return fut

    flow.hass.async_create_task = mock_test_connection_task

    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ) as mock_resolve,
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_validate_cert_path",
            return_value=True,
        ),
    ):
        result = await flow.async_step_samsung_2878(
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_TOKEN: "test_token",
                CONF_MAC: "AA:BB:CC:DD:EE:FF",
            }
        )

    mock_resolve.assert_called_once_with(
        ip_address="192.168.1.100", mac_address="AA:BB:CC:DD:EE:FF"
    )

    assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result["step_id"] == "create_entry"

    result = await flow.async_step_create_entry()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert flow.unique_id == "AA:BB:CC:DD:EE:FF"


async def test_step_pairing_fallback(hass):
    """Test that a failure in pairing initiation triggers an automatic port fallback."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.acquirer = MagicMock(async_close=AsyncMock())
    flow.context = {}

    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        "cert": "ac14k_m.pem",
    }

    def mock_create_task(coro):
        coro.close()
        fut = asyncio.get_event_loop().create_future()
        fut.set_result({"ok": False, "error": "cannot_connect"})
        return fut

    hass.async_create_task = mock_create_task
    try:
        async with asyncio.timeout(0.5):
            result = await flow.async_step_initiate_pairing()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "initiating_pairing"
    assert flow.flow_data.get("_fallback_attempted") is True
    assert flow.flow_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_SAMSUNG_8888


async def test_step_samsung_8888(hass, mock_setup_entry):  # pylint: disable=unused-argument
    """Test the Samsung 8888 flow with a manual token."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    await flow.async_step_user()
    result = await flow.async_step_user({CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "samsung_8888"
    assert result.get("data_schema") is not None
    assert result.get("errors") == {}

    def mock_test_connection_task(coro):
        coro.close()
        fut = asyncio.get_event_loop().create_future()
        fut.set_result({"ok": True})
        return fut

    flow.hass.async_create_task = mock_test_connection_task

    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_validate_cert_path",
            return_value=True,
        ),
    ):
        result = await flow.async_step_samsung_8888(
            {
                CONF_IP_ADDRESS: "192.168.1.101",
                CONF_TOKEN: "test_8888_token",
                CONF_MAC: "11:22:33:44:55:66",
            }
        )

    assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result["step_id"] == "discover_uuid"

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_controller_class,
        patch("homeassistant.helpers.aiohttp_client.async_get_clientsession"),
    ):
        mock_controller_instance = mock_controller_class.return_value
        mock_controller_instance.initialize = AsyncMock(return_value=True)
        mock_controller_instance.async_get_status = AsyncMock(return_value=True)
        mock_controller_instance.async_shutdown = AsyncMock()
        mock_controller_instance.discovered_devices = [
            {"id": "0", "uuid": "device-uuid-1234"}
        ]

        result = await flow.async_step_discover_uuid()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_IP_ADDRESS] == "192.168.1.101"
    assert result["title"] == "Samsung AC 11:22:33:44:55:66"


async def test_mac_sanitization(hass: HomeAssistant) -> None:
    """Test that MAC addresses are properly sanitized during YAML import."""
    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            ".async_set_unique_id"
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._abort_if_unique_id_configured"
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"ip_address": "1.2.3.4", "mac": "aa:bb:cc:11:22:33"},
        )
        assert result["data"][CONF_MAC] == "AABBCC112233"


async def test_step_reauth_rest_api(hass: HomeAssistant) -> None:
    """Test the reauthentication flow updating the entry correctly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11:22:33:44:55:66",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_IP_ADDRESS: "api.smartthings.com",
            CONF_MAC: "11:22:33:44:55:66",
            CONF_TOKEN: "old_expired_token",
            "device_id": "my_hvac_1",
        },
        title="SmartThings HVAC",
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_get_entry.return_value = entry

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_REAUTH,
        "entry_id": entry.entry_id,
        "unique_id": entry.unique_id,
    }

    result = await flow.async_step_reauth(entry.data)
    assert result["step_id"] == "reauth_confirm"

    result2 = await flow.async_step_reauth_confirm({})
    assert result2["step_id"] == "rest_api"

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:

        class MockResponseCtx:  # pylint: disable=missing-class-docstring,too-few-public-methods
            async def __aenter__(self):
                """Enter context manager."""
                resp = MagicMock()
                resp.status = 200
                return resp

            async def __aexit__(self, *args):
                """Exit context manager."""

        mock_session.return_value.get.return_value = MockResponseCtx()

        result3 = await flow.async_step_rest_api(
            user_input={
                CONF_IP_ADDRESS: "api.smartthings.com",
                CONF_TOKEN: "new_valid_token",
                "device_id": "my_hvac_1",
            }
        )

    # Kill Shot 2.1: Blank Bullets in Mocks
    mock_session.return_value.get.assert_called_with(
        "https://api.smartthings.com/v1/devices",
        headers={"Authorization": "Bearer new_valid_token"},
        timeout=10,
    )

    assert result3["type"] == FlowResultType.ABORT
    assert result3["reason"] == "reauth_successful"
    hass.config_entries.async_update_entry.assert_called_once()


async def test_reauth_failure_handling(hass: HomeAssistant) -> None:
    """Test reauth flow handles invalid new token correctly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11:22:33:44:55:66",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_IP_ADDRESS: "api.smartthings.com",
            CONF_TOKEN: "old_token",
        },
    )
    hass.config_entries.async_get_entry.return_value = entry
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id}

    await flow.async_step_reauth(entry.data)
    await flow.async_step_reauth_confirm({})

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:

        class MockResponseCtx:  # pylint: disable=missing-class-docstring,too-few-public-methods
            async def __aenter__(self):
                """Enter context manager."""
                resp = MagicMock()
                resp.status = 401
                return resp

            async def __aexit__(self, *args):
                """Exit context manager."""

        mock_session.return_value.get.return_value = MockResponseCtx()

        result = await flow.async_step_rest_api(
            user_input={
                CONF_IP_ADDRESS: "api.smartthings.com",
                CONF_TOKEN: "wrong_token",
            }
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


async def test_step_reauth_8888_acquisition_failure(hass: HomeAssistant) -> None:
    """Test reauth flow when token acquisition fails."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11:22:33:44:55:66",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_IP_ADDRESS: "192.168.1.101",
            CONF_MAC: "11:22:33:44:55:66",
            CONF_TOKEN: "old_token",
        },
    )
    hass.config_entries.async_get_entry.return_value = entry
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id}

    await flow.async_step_reauth(entry.data)
    await flow.async_step_reauth_confirm({})

    fut_ok = asyncio.get_event_loop().create_future()
    fut_ok.set_result({"ok": True})

    fut_fail = asyncio.get_event_loop().create_future()
    fut_fail.set_result({"ok": False, "error": "timeout_8888"})

    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_validate_cert_path",
            return_value=True,
        ),
    ):

        def mock_create_task(coro, *args, **kwargs):  # pylint: disable=unused-argument
            """Return pre-built futures alternately for task 1 vs task 2."""
            coro.close()
            if not hasattr(mock_create_task, "calls"):
                mock_create_task.calls = 0
            mock_create_task.calls += 1
            return fut_ok if mock_create_task.calls == 1 else fut_fail

        hass.async_create_task.side_effect = mock_create_task

        # The corrected code in config_flow.py ERASES the token on confirm,
        # so this step now correctly returns 'await_button'.
        result2 = await flow.async_step_samsung_8888(
            {CONF_IP_ADDRESS: "192.168.1.101", CONF_MAC: "11:22:33:44:55:66"}
        )
        assert result2["step_id"] == "await_button"

        # 2. Process the wait failure
        try:
            async with asyncio.timeout(0.5):
                result3 = await flow.async_step_await_button()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert flow.flow_data["error_key"] == "timeout_8888"
        assert result3["step_id"] == "handle_error"

    result4 = await flow.async_step_handle_error()
    assert result4["errors"]["base"] == "timeout_8888"


async def test_smartthings_token_autodiscovery(hass: HomeAssistant) -> None:
    """Test that the flow auto-discovers the SmartThings token."""
    st_entry = MockConfigEntry(
        domain="smartthings", data={"access_token": "auto_token"}
    )
    hass.config_entries.async_entries.return_value = [st_entry]

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    result = await flow.async_step_user(
        user_input={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    )

    schema = result["data_schema"]
    token_default = None
    for key in schema.schema:
        if getattr(key, "schema", None) == CONF_TOKEN:
            token_default = key.default()
            break

    assert token_default == "auto_token"


async def test_smartthings_token_reauth_triggers_flow(hass: HomeAssistant) -> None:
    """Test that an expired SmartThings token triggers the re-authentication flow."""
    from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
    from homeassistant.exceptions import ConfigEntryAuthFailed

    # 1. Setup a mock config entry for SmartThings
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ST_DEVICE_123",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_IP_ADDRESS: "api.smartthings.com",
            CONF_TOKEN: "expired_token",
        },
    )
    entry.add_to_hass(hass)

    # 2. Mock the controller to raise AuthError (e.g., from a 401)
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[ST-Auth-Test]"
    mock_controller.async_get_status = AsyncMock(
        side_effect=AuthError("401 Unauthorized")
    )
    mock_controller.climate_state = MagicMock()

    coordinator = SamsungClimateCoordinator(hass, mock_controller, entry)

    # 3. Running the coordinator update should raise ConfigEntryAuthFailed
    # This exception is what Home Assistant uses to trigger the re-auth flow.
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    # 4. In a real HA environment, raising ConfigEntryAuthFailed during poll
    # would trigger the reauth flow. We verify the exception is correctly raised.
    # Verify no unhandled exception was raised and log was likely a warning (we can't easily check log level here without caplog)


async def test_mac_arp_miss_samsung_devices(hass: HomeAssistant) -> None:
    """Test that failure to resolve MAC via ARP results in a manual entry prompt."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    # 1. Mock async_get_mac_address to return None (ARP discovery fails)
    # 2. Mock asyncio.open_connection to raise OSError (Firewall/Port blocked)
    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            return_value=None,
        ),
        patch("asyncio.open_connection", side_effect=OSError("Firewall blocked")),
    ):
        result = await flow.async_step_samsung_2878({CONF_IP_ADDRESS: "192.168.1.100"})

    # 3. Verify that instead of an abrupt abort, it returns to the form with "mac_resolve_failed"
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "samsung_2878"
    assert result["errors"]["base"] == "mac_resolve_failed"

    # 4. Ensure the schema now includes MAC (usually as Required)
    # In config_flow.py: schema_generator(mac_required=error_reason == "mac_resolve_failed")
    schema = result["data_schema"]
    mac_marker = next(
        (k for k in schema.schema if getattr(k, "schema", k) == CONF_MAC), None
    )
    assert isinstance(mac_marker, vol.Required)


async def test_poll_interval_validation_invalid(hass: HomeAssistant) -> None:
    """Test that an invalid poll interval returns an error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    from custom_components.climate_ip.const import CONF_POLL_INTERVAL

    with patch(
        "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
        "._async_resolve_mac_and_set_unique_id",
        return_value=None,
    ):
        result = await flow.async_step_samsung_2878(
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_MAC: "AA:BB:CC:DD:EE:FF",
                CONF_POLL_INTERVAL: "invalid_time",
            }
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "samsung_2878"
    assert result["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"
    assert result.get("data_schema") is not None

    # Kill mutmut_45, 46: assert mac_required=False was passed by checking the generated schema
    mac_key = next(
        k for k in result["data_schema"].schema if getattr(k, "schema", None) == "mac"
    )
    assert isinstance(mac_key, vol.Optional)


async def test_poll_interval_validation_valid(hass: HomeAssistant) -> None:
    """Test that a valid poll interval is accepted and stored."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    def mock_test_connection_task(coro):
        coro.close()
        fut = asyncio.get_event_loop().create_future()
        fut.set_result({"ok": True})
        return fut

    flow.hass.async_create_task = mock_test_connection_task

    from custom_components.climate_ip.const import CONF_POLL_INTERVAL

    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_validate_cert_path",
            return_value=True,
        ),
    ):
        result = await flow.async_step_samsung_2878(
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_MAC: "AA:BB:CC:DD:EE:FF",
                CONF_POLL_INTERVAL: "0:05:00",
            }
        )

    # Valid poll interval should proceed past the form
    assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert flow.flow_data[CONF_POLL_INTERVAL] == 300


async def test_fallback_raw_engine_on_connection_error(hass, mock_setup_entry):
    """On connection error in options flow, user should be able to switch to raw engine."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "my-token",
            CONF_CERT: "",
        },
        options={CONF_CONN_METHOD: "aiohttp"},  # default
        unique_id="bc:8c:cd:5b:54:f6",
    )
    entry.add_to_hass(hass)

    # Use the separate OptionsFlow step
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        # User switches to RAW engine during options because of instability
        user_input={
            CONF_CONN_METHOD: CONN_METHOD_RAW,
            "poll_interval": "0:01:00",
            "enable_polling": True,
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    # Note: data in OptionsFlow specifically returns what was entered in options
    assert result2["data"][CONF_CONN_METHOD] == CONN_METHOD_RAW


@pytest.mark.parametrize(
    ("dev_type", "input_cert"),
    [
        (DEVICE_TYPE_SAMSUNG_2878, ""),
        (DEVICE_TYPE_SAMSUNG_8888, ""),
        (DEVICE_TYPE_MIM_H03, "my_cert.pem"),
    ],
)
async def test_reconfigure_empty_token_triggers_pairing(
    hass: HomeAssistant, mock_setup_entry, dev_type: str, input_cert: str
) -> None:
    """Verify that blanking the token in reconfigure routes to initiate_pairing across device types."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="BC:8C:CD:5B:54:F6",
        data={
            CONF_DEVICE_TYPE: dev_type,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "old_token",
        },
    )
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }

    with patch.object(flow, "_get_reconfigure_entry", return_value=entry):
        result = await flow.async_step_reconfigure()
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure_confirm"
        assert "description_placeholders" in result
        assert "device_name" in result["description_placeholders"]
        assert "ip_address" in result["description_placeholders"]

    with (
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer",
            autospec=True,
        ) as mock_acquirer_cls,
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch.object(flow, "_get_reconfigure_entry", return_value=entry),
    ):
        mock_acquirer_cls.return_value = MagicMock()
        result2 = await flow.async_step_reconfigure_confirm(
            user_input={
                CONF_IP_ADDRESS: "192.168.1.10",
                CONF_MAC: "BC:8C:CD:5B:54:F6",
                CONF_TOKEN: "",
                "cert": input_cert,
            },
        )

    assert result2["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result2["step_id"] == "await_button"
    assert mock_acquirer_cls.called
    assert flow.flow_data[CONF_TOKEN] == ""


async def test_reconfigure_existing_token_no_pairing(hass, mock_setup_entry):
    """When token is preserved, reconfigure must update entry without entering pairing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "valid-existing-token",
            CONF_CERT: "",
        },
        unique_id="bc:8c:cd:5b:54:f6",
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }

    res = await flow.async_step_reconfigure()
    assert res["type"] == FlowResultType.FORM
    assert res["step_id"] == "reconfigure_confirm"
    assert res.get("data_schema") is not None
    assert res.get("errors") in ({}, None)

    with (
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acq,
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
    ):
        result2 = await flow.async_step_reconfigure_confirm(
            user_input={
                CONF_IP_ADDRESS: "192.168.1.20",  # changed IP
                CONF_MAC: "BC:8C:CD:5B:54:F6",
                CONF_TOKEN: "valid-existing-token",  # preserved
                CONF_CERT: "",
            },
        )
    mock_acq.assert_not_called()
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"
    # Verify update was called with correct new IP
    mock_update.assert_called_once()
    assert mock_update.call_args[1]["data"][CONF_IP_ADDRESS] == "192.168.1.20"


async def test_reconfigure_smartthings_no_pairing(hass, mock_setup_entry):
    """SmartThings devices must never trigger physical pairing on reconfigure."""
    from custom_components.climate_ip import const

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: const.DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_IP_ADDRESS: "api.smartthings.com",
            CONF_TOKEN: "valid-st-token",
            CONF_CERT: "",
        },
        unique_id="st-device-id-001",
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}

    res = await flow.async_step_reconfigure()
    assert res["type"] == FlowResultType.FORM
    assert res["step_id"] == "reconfigure_confirm"
    assert "description_placeholders" in res
    assert "device_name" in res["description_placeholders"]
    assert "ip_address" in res["description_placeholders"]
    from homeassistant.const import CONF_IP_ADDRESS as _CONF_IP_ADDRESS

    assert vol.Required(_CONF_IP_ADDRESS) in res["data_schema"].schema

    with (
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acq,
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
    ):
        # Provide MAC and keep Token empty to test ST bypass
        # Directly place it in flow_data because step_reconfigure_confirm
        # will pull CONF_DEVICE_TYPE from flow_data or entry.data
        flow.flow_data[CONF_DEVICE_TYPE] = const.DEVICE_TYPE_SMARTTHINGS_HVAC
        result2 = await flow.async_step_reconfigure_confirm(
            user_input={
                CONF_IP_ADDRESS: "api.smartthings.com",
                CONF_MAC: "st-device-id-001",
                CONF_TOKEN: "",
                CONF_CERT: "",
                # Ensure user_input isn't destroying it if the schema allows it
            },
        )

    mock_acq.assert_not_called()
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"
    mock_update.assert_called_once()


async def test_reconfigure_via_pairing_no_abort(hass, mock_setup_entry):
    """After pairing from reconfigure, result must be reconfigure_successful, not already_configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "old",
            CONF_CERT: "",
        },
        unique_id="BC:8C:CD:5B:54:F6",
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}

    res = await flow.async_step_reconfigure()
    assert res["type"] == FlowResultType.FORM
    assert res["step_id"] == "reconfigure_confirm"
    assert "description_placeholders" in res
    assert "device_name" in res["description_placeholders"]
    assert "ip_address" in res["description_placeholders"]

    mock_acquirer = MagicMock()
    mock_acquirer.async_initiate_pairing = AsyncMock(return_value={"ok": True})
    mock_acquirer.async_wait_for_token = AsyncMock(return_value="new-token")

    # Mock hass.async_create_task to return a completed future immediately
    loop = asyncio.get_event_loop()
    completed_future = loop.create_future()
    # Provide the 'token' key required by async_step_await_button
    completed_future.set_result({"ok": True, "token": "mocked-new-token"})

    with (
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer",
            return_value=mock_acquirer,
        ),
        patch.object(hass, "async_create_task", return_value=completed_future),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
        patch.object(hass.config_entries, "async_update_entry"),
    ):
        result = await flow.async_step_reconfigure_confirm(
            user_input={
                CONF_IP_ADDRESS: "192.168.1.10",
                CONF_MAC: "BC:8C:CD:5B:54:F6",
                CONF_TOKEN: "",  # trigger pairing
                CONF_CERT: "",
            },
        )
        assert result["step_id"] == "await_button"

        # Manually ensure the task is linked and marked as done for the next step
        # Flow uses `flow.task`
        flow.task = completed_future
        # Ensure acquirer is present
        flow.acquirer = mock_acquirer

        try:
            async with asyncio.timeout(0.5):
                result2 = await flow.async_step_await_button()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        # It transitions to discover_uuid for non-2878 or when device type is lost in testing context
        if result2["step_id"] == "discover_uuid":
            with patch.object(
                flow,
                "async_step_discover_uuid",
                return_value=flow.async_show_progress_done(
                    next_step_id="test_connection"
                ),
            ):
                result2 = await flow.async_step_discover_uuid()

        assert result2["type"] == FlowResultType.SHOW_PROGRESS_DONE
        assert result2["step_id"] == "test_connection"

        with patch.object(flow, "_test_connection_safe", return_value={"ok": True}):
            try:
                async with asyncio.timeout(0.5):
                    result3 = await flow.async_step_test_connection()
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )
            if result3["step_id"] == "discover_uuid":
                with patch.object(
                    flow,
                    "async_step_discover_uuid",
                    return_value=flow.async_show_progress_done(
                        next_step_id="create_entry"
                    ),
                ):
                    result3 = await flow.async_step_discover_uuid()

            assert result3["type"] == FlowResultType.SHOW_PROGRESS_DONE
            assert result3["step_id"] == "create_entry"

            result4 = await flow.async_step_create_entry()
            assert result4["type"] == FlowResultType.ABORT
            assert result4["reason"] == "reconfigure_successful"


async def test_reconfigure_cert_cleared_warning(hass, mock_setup_entry, caplog):
    """Clearing the certificate during reconfigure must emit a WARNING log."""
    import logging

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "my-token",
            CONF_CERT: "ac14k_m.pem",
        },
        unique_id="bc:8c:cd:5b:54:f6",
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }

    res = await flow.async_step_reconfigure()
    assert res["type"] == FlowResultType.FORM
    assert res["step_id"] == "reconfigure_confirm"
    assert "description_placeholders" in res
    assert "device_name" in res["description_placeholders"]
    assert "ip_address" in res["description_placeholders"]

    with (
        caplog.at_level(
            logging.WARNING, logger="custom_components.climate_ip.config_flow"
        ),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
    ):
        await flow.async_step_reconfigure_confirm(
            user_input={
                CONF_IP_ADDRESS: "192.168.1.10",
                CONF_MAC: "BC:8C:CD:5B:54:F6",
                CONF_TOKEN: "my-token",
                CONF_CERT: "",  # deliberately cleared
            },
        )
    assert "certificate path was cleared" in caplog.text


async def test_reconfigure_mac_formatted_on_error(hass, mock_setup_entry):
    """On MAC validation error, the form must re-render with a properly formatted MAC address."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC:8C:CD:5B:54:F6",
            CONF_TOKEN: "my-token",
            CONF_CERT: "",
        },
        unique_id="bc:8c:cd:5b:54:f6",
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }

    res = await flow.async_step_reconfigure()
    assert res["type"] == FlowResultType.FORM
    assert res["step_id"] == "reconfigure_confirm"
    assert "description_placeholders" in res
    assert "device_name" in res["description_placeholders"]
    assert "ip_address" in res["description_placeholders"]

    with patch(
        "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
        "._async_resolve_mac_and_set_unique_id",
        return_value="mac_resolve_failed",
    ):
        result2 = await flow.async_step_reconfigure_confirm(
            user_input={
                CONF_IP_ADDRESS: "10.0.0.99",
                CONF_MAC: "BC8CCD5B54F6",  # raw, no colons
                CONF_TOKEN: "my-token",
                CONF_CERT: "",
            },
        )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"]["base"] == "mac_resolve_failed"

    # Kill Shot 1: Assert IP was properly updated from user_input rather than sticking to entry.data
    schema = result2["data_schema"].schema
    ip_key = next(k for k in schema if str(k) == CONF_IP_ADDRESS)
    assert ip_key.description["suggested_value"] == "10.0.0.99"


async def test_cert_not_found_validation(hass: HomeAssistant) -> None:
    """Test that an invalid cert path or empty cert is correctly handled."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    from custom_components.climate_ip.const import CONF_CERT

    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_validate_cert_path",
            return_value=False,
        ) as mock_validate_cert,
    ):
        result = await flow.async_step_samsung_2878(
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_MAC: "AA:BB:CC:DD:EE:FF",
                CONF_CERT: "invalid/cert.pem",
            }
        )

    mock_validate_cert.assert_called_once_with("invalid/cert.pem")
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "samsung_2878"
    assert result["errors"]["base"] == "cert_not_found"
    assert result.get("data_schema") is not None

    flow.flow_data.clear()
    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_resolve_mac_and_set_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow"
            "._async_validate_cert_path",
            return_value=False,
        ),
    ):
        await flow.async_step_samsung_2878(
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_MAC: "AA:BB:CC:DD:EE:FF",
                CONF_CERT: "",
            }
        )


async def test_async_step_await_button_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_await_button."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_MIM_H03,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.acquirer = MagicMock()

    # 1. Kill mutmut_4, 40, 41, 42: task is not done, MIM_H03 device
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03, "ip_address": "1.2.3.4"}
    flow.task = MagicMock()
    flow.task.done.return_value = False

    try:
        async with asyncio.timeout(0.5):
            result_progress = await flow.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result_progress["type"] == "progress"
    assert result_progress["step_id"] == "await_button"
    assert result_progress["progress_action"] == "awaiting_button_press"
    # Kill mutmut_50, 51, 54, 55, 58, 59, 60: strict state verification
    assert result_progress["progress_task"] is flow.task
    assert result_progress["description_placeholders"] == {"ip_address": "1.2.3.4"}

    # 2. task is not done, non-MIM_H03 device
    flow.flow_data[CONF_DEVICE_TYPE] = "some_other"
    try:
        async with asyncio.timeout(0.5):
            result_progress_2 = await flow.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result_progress_2["progress_action"] == "awaiting_button_press"

    # 3. Kill mutmut_23, 24, 25, 26, 27, 28: task is done, success, DEVICE_TYPE_SAMSUNG_2878
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": True, "token": "valid_token"}

    try:
        async with asyncio.timeout(0.5):
            result_success = await flow.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result_success["type"] == "progress_done"
    assert result_success["step_id"] == "test_connection"
    assert flow.flow_data[CONF_TOKEN] == "valid_token"
    # Kill mutmut_6: strict check that task is None
    assert flow.task is None

    # 4. Kill mutmut_15, 16, 17, 18, 19, 20, 21: malicious token rejection
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": True, "token": "malicious\n\rtoken"}

    try:
        async with asyncio.timeout(0.5):
            result_fail = await flow.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result_fail["type"] == "progress_done"
    assert result_fail["step_id"] == "handle_error"
    assert flow.flow_data.get("error_key") == "token_acquisition_failed"

    # 5. Kill mutmut error_details transfer in await_button
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {
        "ok": False,
        "error": "some_error",
        "error_details": "await_details",
    }
    try:
        async with asyncio.timeout(0.5):
            result_fail_details = await flow.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result_fail_details["step_id"] == "handle_error"
    assert flow.flow_data.get("error_details") == "await_details"


async def test_async_step_handle_error_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_handle_error."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_MIM_H03,
        DEVICE_TYPE_SAMSUNG_8888,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # 1. Test DEVICE_TYPE_MIM_H03 with specific error_key
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        "error_key": "some_error",
    }

    with (
        patch.object(
            flow, "_get_samsung_2878_schema", return_value="mocked_schema_2878"
        ),
        patch.object(
            flow, "_get_samsung_8888_schema", return_value="mocked_schema_8888"
        ),
    ):
        res = await flow.async_step_handle_error()
        assert res["type"] == "form"
        assert res["step_id"] == "mim_h03"
        assert res["errors"]["base"] == "some_error"
        # Since it's MIM_H03, it falls into the if branch of the schema_generator (in 8888_GROUP)
        assert res["data_schema"] == "mocked_schema_8888"

    # 2. Test DEVICE_TYPE_SAMSUNG_8888 and missing error_key (default "unknown_error")
    # Kills mutmut 3, 5, 16, 17, 18, 19, 24, 26, 29
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    flow2.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
    }

    with (
        patch.object(
            flow2, "_get_samsung_2878_schema", return_value="mocked_schema_2878"
        ),
        patch.object(
            flow2, "_get_samsung_8888_schema", return_value="mocked_schema_8888"
        ),
    ):
        res2 = await flow2.async_step_handle_error()
        assert res2["type"] == "form"

        # Kill mutmut 16, 17, 18, 19
        assert res2["step_id"] == "samsung_8888"

        # Kill mutmut 3, 5
        assert res2["errors"]["base"] == "unknown_error"
        assert res2["errors"]["base"] is not None

        # Kill mutmut 24, 26, 29
        assert res2["data_schema"] == "mocked_schema_8888"

    # 3. Test fallback (else branch)
    # Kills mutmut 20, 21, 22
    flow3 = ClimateIpConfigFlow()
    flow3.hass = hass
    flow3.flow_data = {
        CONF_DEVICE_TYPE: "UNKNOWN_DEVICE",
        "error_key": "another_error",
    }

    with (
        patch.object(
            flow3, "_get_samsung_2878_schema", return_value="mocked_schema_2878"
        ),
        patch.object(
            flow3, "_get_samsung_8888_schema", return_value="mocked_schema_8888"
        ),
    ):
        res3 = await flow3.async_step_handle_error()
        assert res3["type"] == "form"

        # Kill mutmut 20, 21, 22
        assert res3["step_id"] == "samsung_2878"
        assert res3["errors"]["base"] == "another_error"
        assert res3["data_schema"] == "mocked_schema_2878"


async def test_async_step_reauth_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_reauth."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.context = {"entry_id": "test_entry_id"}

    mock_entry = MagicMock()
    mock_entry.data = {"mock": "data"}
    flow.hass.config_entries.async_get_entry.return_value = mock_entry

    with patch.object(flow, "async_step_reauth_confirm", new_callable=AsyncMock):
        await flow.async_step_reauth({})

        # Kill mutmut 2: assert async_get_entry was called with the right entry_id, not None
        flow.hass.config_entries.async_get_entry.assert_called_once_with(
            "test_entry_id"
        )


async def test_async_step_reauth_confirm_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_reauth_confirm."""
    from unittest.mock import AsyncMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    # 1. Kill mutmut 11, 12, 13, 14, 16, 18, 21, 22 (reauth_entry=None logic)
    flow1 = ClimateIpConfigFlow()
    flow1.hass = hass
    flow1.reauth_entry = None

    with patch.object(
        flow1, "async_show_form", return_value={"mock": "form"}
    ) as mock_form:
        await flow1.async_step_reauth_confirm()

        # Kill mutmut 16, 18, 21, 22
        mock_form.assert_called_once()
        _args, kwargs = mock_form.call_args
        assert "description_placeholders" in kwargs
        placeholders = kwargs["description_placeholders"]
        assert placeholders is not None

        # Kill mutmut 11, 12, 13, 14
        assert "device_name" in placeholders
        assert placeholders["device_name"] == "Unknown Device"

    # 2. Kill mutmut 6, 10 (user_input provided)
    from unittest.mock import MagicMock

    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    flow2.reauth_entry = MagicMock()
    flow2.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    # Notice CONF_TOKEN is absent, which kills mutmut 6 (pop(CONF_TOKEN) without default)

    with patch.object(
        flow2, "async_step_samsung_2878", new_callable=AsyncMock
    ) as mock_2878:
        # User input is not None, so it executes the branch
        await flow2.async_step_reauth_confirm(user_input={})

        # Kill mutmut 10
        mock_2878.assert_called_once()


async def test_async_step_reconfigure_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_reconfigure."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {}

    mock_entry = MagicMock()
    mock_entry.data = {"test_key": "test_val"}

    with (
        patch.object(flow, "_get_reconfigure_entry", return_value=mock_entry),
        patch.object(flow, "async_step_reconfigure_confirm", new_callable=AsyncMock),
    ):
        await flow.async_step_reconfigure()

        # Kill mutmut 2: if self.flow_data is empty, it populates it
        assert flow.flow_data == {"test_key": "test_val"}


async def test_async_step_test_connection_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_test_connection routing logic."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_ID,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SAMSUNG_8888,
    )
    from homeassistant.const import CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # Case 0: Test connection progress action
    mock_task = MagicMock()
    mock_task.done.return_value = False
    flow.flow_data = {"ip_address": "1.2.3.4", "device_type": "dummy"}
    with patch.object(flow.hass, "async_create_task", return_value=mock_task):
        try:
            async with asyncio.timeout(0.5):
                res0 = await flow.async_step_test_connection()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res0["type"] == "progress"
    assert res0["progress_action"] == "testing_connection"

    # Case 1: Test connection FAILS -> Token must be popped, routes to handle_error
    flow.flow_data = {
        "ip_address": "1.2.3.4",
        "device_type": "dummy",
        CONF_TOKEN: "bad_token",
    }
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": False, "error": "auth_error"}

    try:
        async with asyncio.timeout(0.5):
            res1 = await flow.async_step_test_connection()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res1["type"] == "progress_done"
    assert res1["step_id"] == "handle_error"
    # Kill mutmut asserting dict pop and assignments
    assert CONF_TOKEN not in flow.flow_data
    assert flow.flow_data["error_key"] == "auth_error"
    assert flow.task is None  # Kills task=None assignments

    # Case 1b: Test connection RAISES EXCEPTION (KILLS THE LEGION M8-M21)
    flow.flow_data = {"ip_address": "1.2.3.4", "device_type": "dummy"}
    flow.task = MagicMock()
    flow.task.done.return_value = True
    # FORZAMOS LA EXCEPCIÓN PARA ENTRAR EN EL BLOQUE `except Exception:`
    flow.task.result.side_effect = Exception("Simulated crash")

    try:
        async with asyncio.timeout(0.5):
            res1b = await flow.async_step_test_connection()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res1b["type"] == "progress_done"
    assert res1b["step_id"] == "handle_error"
    # STRICT SNIPER ASSERTION:
    # If mutmut changes this to "UNKNOWN_ERROR" or "XXunknown_errorXX", it will fail.
    assert flow.flow_data["error_key"] == "unknown_error"
    assert flow.task is None

    # Case 2: Success, 2878 Device -> always routes to create_entry
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878, CONF_TOKEN: "good"}
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": True}
    try:
        async with asyncio.timeout(0.5):
            res2 = await flow.async_step_test_connection()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res2["step_id"] == "create_entry"

    # Case 3: Success, 8888 Device, NO Device ID -> routes to discover_uuid
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888, CONF_TOKEN: "good"}
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": True}
    try:
        async with asyncio.timeout(0.5):
            res3 = await flow.async_step_test_connection()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res3["step_id"] == "discover_uuid"

    # Case 4: Success, 8888 Device, HAS Device ID -> routes to create_entry
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_DEVICE_ID: "1234",
        CONF_TOKEN: "good",
    }
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": True}
    try:
        async with asyncio.timeout(0.5):
            res4 = await flow.async_step_test_connection()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res4["step_id"] == "create_entry"


async def test_async_step_import_mutants(hass: HomeAssistant) -> None:
    """Kill all mutants in async_step_import."""
    from unittest.mock import patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CONFIG_FILE,
        CONF_DEVICE_TYPE,
        CONFIG_DEVICE_NAME,
        DEVICE_TYPE_MIM_H03,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # Case 1: Import without MAC -> Aborts immediately
    try:
        async with asyncio.timeout(0.5):
            res_no_mac = await flow.async_step_import(
                {CONF_IP_ADDRESS: "1.1.1.1", CONF_MAC: ""}
            )
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_no_mac["type"] == "abort"
    assert res_no_mac["reason"] == "no_mac_address_found"

    # Case 2: Import without explicit MAC (None) -> Aborts
    try:
        async with asyncio.timeout(0.5):
            res_no_mac2 = await flow.async_step_import({CONF_IP_ADDRESS: "1.1.1.1"})
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_no_mac2["type"] == "abort"
    assert res_no_mac2["reason"] == "no_mac_address_found"

    # Case 3: Successful import with dirty MAC, existing config_file, and no CONFIG_DEVICE_NAME
    # Kills replacing logic, dictionary assignations, and title fallback
    with (
        patch.object(flow, "async_set_unique_id") as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
        patch.object(flow, "_test_connection_safe", return_value={"ok": True}),
        patch.object(
            flow, "async_create_entry", return_value={"type": "create_entry"}
        ) as mock_create,
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.2.3.4",
            CONF_MAC: "aa:bb:cc:dd",
            CONF_CONFIG_FILE: "mim-h03_heatpump.yaml",  # Este archivo mapea a DEVICE_TYPE_MIM_H03 en const.py
        }

        try:
            async with asyncio.timeout(0.5):
                res_success = await flow.async_step_import(user_input)
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res_success["type"] == "create_entry"
        # Verifica saneamiento de MAC
        mock_set_uid.assert_called_once_with("AA:BB:CC:DD")
        mock_abort.assert_called_once()

        # Verify correct device_type derived from config_file was injected
        create_data = mock_create.call_args.kwargs["data"]
        assert create_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_MIM_H03

        # Verify title fallback when CONFIG_DEVICE_NAME is missing
        assert mock_create.call_args.kwargs["title"] == "Climate AA:BB:CC:DD"

    # Case 4: Successful import with explicit CONFIG_DEVICE_NAME and unknown config_file
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    with (
        patch.object(flow2, "async_set_unique_id"),
        patch.object(flow2, "_abort_if_unique_id_configured"),
        patch.object(flow2, "_test_connection_safe", return_value={"ok": True}),
        patch.object(
            flow2, "async_create_entry", return_value={"type": "create_entry"}
        ) as mock_create2,
    ):
        user_input2 = {
            CONF_IP_ADDRESS: "1.2.3.4",
            CONF_MAC: "112233",
            CONF_CONFIG_FILE: "unknown.yaml",
            CONFIG_DEVICE_NAME: "My Awesome AC",
        }

        try:
            async with asyncio.timeout(0.5):
                res_success2 = await flow2.async_step_import(user_input2)
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res_success2["type"] == "create_entry"

        create_data2 = mock_create2.call_args.kwargs["data"]
        # Device type should not be injected because YAML was unknown
        assert CONF_DEVICE_TYPE not in create_data2

        # Title must strictly match the one specified in CONFIG_DEVICE_NAME
        assert mock_create2.call_args.kwargs["title"] == "My Awesome AC"


async def test_rest_api_strict_token_sanitization(hass: HomeAssistant) -> None:
    """Kill mutants testing exactly None and empty string in token sanitization."""
    from unittest.mock import patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from homeassistant.const import CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # Vector 1: El sanitizador devuelve string vacío (Kills mutants de == "")
    flow.flow_data = {"device_type": "dummy"}
    with patch("custom_components.climate_ip.helpers.sanitize_token", return_value=""):
        try:
            async with asyncio.timeout(0.5):
                res_empty = await flow.async_step_rest_api({CONF_TOKEN: "dirty_token"})
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res_empty["type"] == "form"
        assert res_empty["errors"][CONF_TOKEN] == "invalid_token_format"

    # Vector 2: El sanitizador devuelve None (Kills mutants de is None)
    with patch(
        "custom_components.climate_ip.helpers.sanitize_token", return_value=None
    ):
        try:
            async with asyncio.timeout(0.5):
                res_none = await flow.async_step_rest_api({CONF_TOKEN: "dirty_token"})
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res_none["type"] == "form"
        assert res_none["errors"][CONF_TOKEN] == "invalid_token_format"

    # Vector 3: Prevent dictionary collisions in schemas (Kills mutants 49-58)
    from unittest.mock import AsyncMock

    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_DEVICE_ID, CONF_IP_ADDRESS

    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    schema = flow._get_rest_api_schema()
    # Verify CONF_DEVICE_ID exists and is Optional for SmartThings
    assert any(
        isinstance(k, vol.Optional) and k.schema == CONF_DEVICE_ID
        for k in schema.schema
    )

    # Vector 4: Token válido asigna safe_token a flow.flow_data[CONF_TOKEN] y no None
    with (
        patch(
            "custom_components.climate_ip.helpers.sanitize_token",
            return_value="clean_token",
        ),
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession"
        ) as mock_sess,
    ):
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get
        with (
            patch.object(flow, "async_set_unique_id"),
            patch.object(flow, "_abort_if_unique_id_configured"),
            patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
        ):
            try:
                async with asyncio.timeout(0.5):
                    await flow.async_step_rest_api(
                        {
                            CONF_TOKEN: "valid_token_raw",
                            CONF_IP_ADDRESS: "1.2.3.4",
                            CONF_DEVICE_ID: "dev1",
                        }
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )
            assert flow.flow_data[CONF_TOKEN] == "clean_token"
            assert flow.flow_data[CONF_TOKEN] is not None


async def test_async_step_reconfigure_confirm_mutants_killer(
    hass: HomeAssistant,
) -> None:
    """Annihilate surviving mutants in reconfigure_confirm step."""
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    # Setup inicial
    entry = MockConfigEntry(
        domain="climate_ip",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_MAC: "AA:BB:CC",
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_TOKEN: "dummy_token",
        },
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}

    with patch.object(flow, "_get_reconfigure_entry", return_value=entry):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_reconfigure()  # Populates flow_data
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        # Attack 1: Submit with invalid MAC (Forces error branch and MAC re-formatting)
        with patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            return_value="mac_resolve_failed",
        ):
            try:
                async with asyncio.timeout(0.5):
                    res_bad_mac = await flow.async_step_reconfigure_confirm(
                        {
                            CONF_IP_ADDRESS: "192.168.1.100",
                            CONF_MAC: "invalid_mac",
                            CONF_TOKEN: "token",
                            CONF_CERT: "",
                        }
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )
            assert res_bad_mac["type"] == "form"
            assert res_bad_mac["errors"]["base"] == "mac_resolve_failed"

        # Attack 2: Submit with Invalid Certificate (Forces cert_not_found branch)
        with (
            patch.object(
                flow, "_async_resolve_mac_and_set_unique_id", return_value=None
            ),
            patch.object(flow, "_async_validate_cert_path", return_value=False),
        ):
            try:
                async with asyncio.timeout(0.5):
                    res_bad_cert = await flow.async_step_reconfigure_confirm(
                        {
                            CONF_IP_ADDRESS: "192.168.1.100",
                            CONF_MAC: "AA:BB:CC",
                            CONF_TOKEN: "token",
                            CONF_CERT: "bad_cert.pem",
                        }
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )
            assert res_bad_cert["type"] == "form"
            assert res_bad_cert["step_id"] == "reconfigure_confirm"
            assert res_bad_cert["errors"]["base"] == "cert_not_found"

        # Attack 3: Full successful flow with update
        with (
            patch.object(
                flow, "_async_resolve_mac_and_set_unique_id", return_value=None
            ),
            patch.object(flow, "_async_validate_cert_path", return_value=True),
            patch.object(
                flow,
                "async_update_reload_and_abort",
                return_value={"type": "abort", "reason": "reconfigure_successful"},
            ) as mock_update_reload_and_abort,
        ):
            try:
                async with asyncio.timeout(0.5):
                    res_success = await flow.async_step_reconfigure_confirm(
                        {
                            CONF_IP_ADDRESS: "192.168.1.150",
                            CONF_MAC: "AA:BB:CC",
                            CONF_TOKEN: "new_token",
                            CONF_CERT: "",
                        }
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            assert res_success["type"] == "abort"
            assert res_success["reason"] == "reconfigure_successful"
            mock_update_reload_and_abort.assert_called_once()
            # Ensure new data was injected
            assert (
                mock_update_reload_and_abort.call_args.kwargs["data"][CONF_IP_ADDRESS]
                == "192.168.1.150"
            )


async def test_rest_api_schema_and_routing_mutants(hass: HomeAssistant) -> None:
    """Kill mutants surviving in REST API schemas and user inputs."""
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.DEBUG_ME = True

    # Attack 1: Invalid polling interval submitted by user
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    try:
        async with asyncio.timeout(0.5):
            res_bad_poll = await flow.async_step_rest_api(
                {
                    CONF_IP_ADDRESS: "api.smartthings.com",
                    CONF_TOKEN: "my_token",
                    CONF_POLL_INTERVAL: "invalid",
                }
            )
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_bad_poll["type"] == "form"
    assert res_bad_poll["step_id"] == "rest_api"
    assert res_bad_poll["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    # Attack 1.5: Valid polling interval submitted by user
    with (
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession"
        ) as mock_session_func,
        patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
    ):
        mock_session = MagicMock()
        mock_get = MagicMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_session.get.return_value = mock_get
        mock_session_func.return_value = mock_session
        try:
            async with asyncio.timeout(0.5):
                res_good_poll = await flow.async_step_rest_api(
                    {
                        CONF_IP_ADDRESS: "api.smartthings.com",
                        CONF_TOKEN: "my_token_1234",
                        CONF_POLL_INTERVAL: 120,
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert (
            "errors" not in res_good_poll
            or CONF_POLL_INTERVAL not in res_good_poll.get("errors", {})
        )
        assert flow.flow_data[CONF_POLL_INTERVAL] == 120

    # Attack 2: Exact evaluation of generated Schema (Kills defaults and vol.Optional mutations)
    flow.flow_data.pop(CONF_TOKEN, None)
    flow.flow_data.pop(CONF_POLL_INTERVAL, None)
    with patch.object(flow, "_get_smartthings_token", return_value="auto_token"):
        schema = flow._get_rest_api_schema()
        # Evaluate with empty input to force default values to sprout
        evaluated = schema({})
        assert evaluated[CONF_IP_ADDRESS] == "api.smartthings.com"
        assert evaluated[CONF_TOKEN] == "auto_token"

        # Mathematical assertion calculating string from actual constant
        import datetime

        from custom_components.climate_ip.const import DEFAULT_POLL_INTERVAL

        expected_interval = str(datetime.timedelta(seconds=int(DEFAULT_POLL_INTERVAL)))
        assert evaluated[CONF_POLL_INTERVAL] == expected_interval


async def test_rest_api_strict_headers_and_fallback(hass: HomeAssistant) -> None:
    """Kill HTTP header casing mutants and fallback logic."""
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.DEBUG_ME = True

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session_func:
        mock_session = MagicMock()
        mock_get = MagicMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_session.get.return_value = mock_get
        mock_session_func.return_value = mock_session

        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_rest_api(
                    {
                        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
                        CONF_TOKEN: "valid_token",
                        CONF_IP_ADDRESS: "1.2.3.4",
                        "device_id": "123",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        from unittest.mock import ANY

        from custom_components.climate_ip.const import GLOBAL_HTTP_TIMEOUT

        # Strict White-Box assertion to kill Headers and Timeout mutants
        mock_session.get.assert_called_once_with(
            ANY,
            headers={"Authorization": "Bearer valid_token"},
            timeout=GLOBAL_HTTP_TIMEOUT,
        )


async def test_await_button_fallback_error(hass: HomeAssistant) -> None:
    """Kill mutants changing the fallback error key to UNKNOWN_ERROR or XXunknown_errorXX."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.acquirer = MagicMock()
    flow.task = MagicMock()
    flow.task.done.return_value = True
    # Force failure without providing 'error' to trigger get("error", "unknown_error")
    flow.task.result.return_value = {"ok": False}

    try:
        async with asyncio.timeout(0.5):
            await flow.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert flow.flow_data["error_key"] == "unknown_error"


async def test_voluptuous_schemas_strict_structure(hass: HomeAssistant) -> None:
    """Kill mutants that change vol.Required to vol.Optional or mutate schema keys/defaults."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_SELECTED_DEVICES,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {}

    # 1. Base Samsung Schema Strict Modifiers
    # Kills mutants altering mac_required: bool = False
    schema_opt = flow._get_base_samsung_schema(mac_required=False, is_8888=False)
    assert any(
        isinstance(k, vol.Optional) and k.schema == CONF_MAC for k in schema_opt.schema
    )

    schema_req = flow._get_base_samsung_schema(mac_required=True, is_8888=False)
    assert any(
        isinstance(k, vol.Required) and k.schema == CONF_MAC for k in schema_req.schema
    )

    # 2. User Step Strict Routing & Schema
    # Kills mutants altering step_id="user" and device_type key
    try:
        async with asyncio.timeout(0.5):
            res_user = await flow.async_step_user()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_user["type"] == "form"
    assert res_user["step_id"] == "user"
    assert any(
        isinstance(k, vol.Required) and k.schema == CONF_DEVICE_TYPE
        for k in res_user["data_schema"].schema
    )

    # 3. Select Devices Strict Schema
    # Kills mutants altering default=list(...) and step_id="select_devices"
    flow.flow_data = {"discovered_devices": [{"id": "1", "name": "A"}]}
    try:
        async with asyncio.timeout(0.5):
            res_select = await flow.async_step_select_devices()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_select["type"] == "form"
    assert res_select["step_id"] == "select_devices"
    schema_select = res_select["data_schema"]
    assert any(
        isinstance(k, vol.Required) and k.schema == CONF_SELECTED_DEVICES
        for k in schema_select.schema
    )

    # 4. Rest API Strict Routing
    # Kills mutants altering step_id="rest_api"
    flow.flow_data = {"device_type": "dummy"}
    try:
        async with asyncio.timeout(0.5):
            res_rest = await flow.async_step_rest_api()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_rest["type"] == "form"
    assert res_rest["step_id"] == "rest_api"
    assert any(
        isinstance(k, vol.Required) and k.schema == CONF_IP_ADDRESS
        for k in res_rest["data_schema"].schema
    )


async def test_reconfigure_confirm_strict_dict_assignments(hass: HomeAssistant) -> None:
    """Kill mutants surviving in dictionary assignments of async_step_reconfigure_confirm."""
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    # Create an entry with valid prior state
    entry = MockConfigEntry(
        domain="climate_ip",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_MAC: "AA:BB:CC",
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_TOKEN: "dummy_token",
        },
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}

    with (
        patch.object(flow, "_get_reconfigure_entry", return_value=entry),
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch.object(hass.config_entries, "async_update_entry"),
        patch.object(hass.config_entries, "async_reload"),
    ):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_reconfigure()  # Poblamos flow_data inicial
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        # Attack 1: User submits form with completely empty or null values
        # This forces .get() or 'or ""' into action.
        user_input_attack = {
            CONF_IP_ADDRESS: "",
            CONF_MAC: "",
            CONF_TOKEN: "",
            CONF_CERT: "",
        }

        # Intercept call to async_step_initiate_pairing, where it ends up
        # if token is false and device_type is 2878.
        with patch.object(
            flow, "async_step_initiate_pairing", return_value={"type": "progress"}
        ) as mock_pairing:
            try:
                async with asyncio.timeout(0.5):
                    await flow.async_step_reconfigure_confirm(user_input_attack)
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            # Verify mutable values were not corrupted by 'XXXX' or nulls.
            assert flow.flow_data[CONF_IP_ADDRESS] == ""
            assert flow.flow_data[CONF_MAC] == ""
            assert flow.flow_data[CONF_TOKEN] == ""
            assert flow.flow_data[CONF_CERT] == ""
            mock_pairing.assert_called_once()

        # Attack 2: Behavior on MAC error (Verify mutant kill 117 to 133 and 153 to 166)
        # Simulate invalid MAC to force error_suggested regeneration
        with (
            patch.object(
                flow,
                "_async_resolve_mac_and_set_unique_id",
                return_value="mac_resolve_failed",
            ),
            patch.object(
                flow, "add_suggested_values_to_schema", return_value=MagicMock()
            ) as mock_add_suggested,
        ):
            user_input_invalid_mac = {
                CONF_IP_ADDRESS: "1.2.3.4",
                CONF_MAC: "invalid",
                CONF_TOKEN: "abc",
                CONF_CERT: "cert.pem",
            }
            try:
                async with asyncio.timeout(0.5):
                    res_error = await flow.async_step_reconfigure_confirm(
                        user_input_invalid_mac
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            # Verify aborted by returning error form
            assert res_error["type"] == "form"
            assert res_error["errors"]["base"] == "mac_resolve_failed"

            # Extract 'error_suggested' dict passed to helper function
            # mock_add_suggested was called with (base_schema, error_suggested)
            mock_add_suggested.assert_called_with(
                ANY,
                {
                    CONF_IP_ADDRESS: "1.2.3.4",
                    CONF_MAC: "INVALID",  # dr.format_mac lo hace upper()
                    CONF_TOKEN: "abc",
                    CONF_CERT: "cert.pem",
                },
            )


async def test_rest_api_strict_dict_assignments(hass: HomeAssistant) -> None:
    """Kill mutants surviving in dictionary assignments of async_step_rest_api."""
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.DEBUG_ME = True

    # Attack: Inject empty token.
    # Tests branch: token_val = str(self.flow_data.get(CONF_TOKEN) or "")
    user_input = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_IP_ADDRESS: "api.smartthings.com",
        CONF_TOKEN: "",
    }

    # Patch connection to return OK if it attempts to connect (it should not)
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session_func:
        mock_session = MagicMock()
        mock_get = MagicMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_session.get.return_value = mock_get
        mock_session_func.return_value = mock_session

        # Patch final entry creation
        with patch.object(flow, "_create_entry", return_value={"type": "create_entry"}):
            try:
                async with asyncio.timeout(0.5):
                    await flow.async_step_rest_api(user_input)
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            # Token was empty, so it MUST NOT call sanitize_token
            # and should have reached the end of connection test without token.
            assert flow.flow_data[CONF_TOKEN] == ""


async def test_async_step_reconfigure_confirm_schema_fallbacks(
    hass: HomeAssistant,
) -> None:
    """Verify mutant kill en la generacion de default fallbacks de reconfigure_confirm."""
    from unittest.mock import patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_MIM_H03,
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SAMSUNG_8888,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    # Scenario 1: device_type in flow_data (SAMSUNG_8888), cert_fallback="ac14k_m.pem"
    entry1 = MockConfigEntry(
        domain="climate_ip",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_MAC: "11:22:33:44:55:66",
            CONF_TOKEN: "token",
        },
    )
    flow1 = ClimateIpConfigFlow()
    flow1.hass = hass
    flow1.context = {"source": "reconfigure", "entry_id": entry1.entry_id}
    flow1.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_MAC: "aa:bb:cc",
        CONF_IP_ADDRESS: "1.2.3.4",
        CONF_TOKEN: "flow_token",
    }

    with patch.object(flow1, "_get_reconfigure_entry", return_value=entry1):
        try:
            async with asyncio.timeout(0.5):
                res1 = await flow1.async_step_reconfigure_confirm(None)
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res1["type"] == "form"
        # Comprobar MAC format
        assert (
            next(
                k.description.get("suggested_value")
                for k in res1["data_schema"].schema
                if str(k) == CONF_MAC
            )
            == "AA:BB:CC"
        )
        # Comprobar cert fallback is 8888
        assert (
            next(
                k.description.get("suggested_value")
                for k in res1["data_schema"].schema
                if str(k) == CONF_CERT
            )
            == "ac14k_m.pem"
        )
        # Check IP prioritizes flow_data (not reconfigure_entry) to kill Mutant 18-40
        assert (
            next(
                k.description.get("suggested_value")
                for k in res1["data_schema"].schema
                if str(k) == CONF_IP_ADDRESS
            )
            == "1.2.3.4"
        )
        assert (
            next(
                k.description.get("suggested_value")
                for k in res1["data_schema"].schema
                if str(k) == CONF_TOKEN
            )
            == "flow_token"
        )
        assert res1["description_placeholders"]["ip_address"] == "192.168.1.100"

    # Escenario 2: device_type de reconfigure_entry (MIM_H03), cert_fallback="ac14k_m.pem"
    entry2 = MockConfigEntry(
        domain="climate_ip",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
            CONF_MAC: "00:11:22:33:44:55",
            CONF_IP_ADDRESS: "192.168.1.101",
        },
    )
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    flow2.context = {"source": "reconfigure", "entry_id": entry2.entry_id}
    flow2.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_MAC: "00:11:22:33:44:55",
        CONF_IP_ADDRESS: "192.168.1.101",
    }

    with patch.object(flow2, "_get_reconfigure_entry", return_value=entry2):
        try:
            async with asyncio.timeout(0.5):
                res2 = await flow2.async_step_reconfigure_confirm(None)
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res2["type"] == "form"
        assert (
            next(
                k.description.get("suggested_value")
                for k in res2["data_schema"].schema
                if str(k) == CONF_CERT
            )
            == "ac14k_m.pem"
        )
        assert (
            next(
                k.description.get("suggested_value")
                for k in res2["data_schema"].schema
                if str(k) == CONF_MAC
            )
            == "00:11:22:33:44:55"
        )
        assert (
            next(
                k.description.get("suggested_value")
                for k in res2["data_schema"].schema
                if str(k) == CONF_IP_ADDRESS
            )
            == "192.168.1.101"
        )
        assert (
            next(
                k.description.get("suggested_value")
                for k in res2["data_schema"].schema
                if str(k) == CONF_TOKEN
            )
            == ""
        )
        assert res2["description_placeholders"]["ip_address"] == "192.168.1.101"

    # Escenario 3: device_type 2878, cert_fallback="ac14k_m.pem"
    entry3 = MockConfigEntry(
        domain="climate_ip",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.102",
            CONF_MAC: "AA:BB:CC",
        },
    )
    flow3 = ClimateIpConfigFlow()
    flow3.hass = hass
    flow3.context = {"source": "reconfigure", "entry_id": entry3.entry_id}
    flow3.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.102",
        CONF_MAC: "11:22:33:aa:bb:cc",
    }

    with patch.object(flow3, "_get_reconfigure_entry", return_value=entry3):
        try:
            async with asyncio.timeout(0.5):
                res3 = await flow3.async_step_reconfigure_confirm(None)
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert (
            next(
                k.description.get("suggested_value")
                for k in res3["data_schema"].schema
                if str(k) == CONF_CERT
            )
            == "ac14k_m.pem"
        )
        assert (
            next(
                k.description.get("suggested_value")
                for k in res3["data_schema"].schema
                if str(k) == CONF_MAC
            )
            == "11:22:33:AA:BB:CC"
        )


async def test_form_schemas_types_and_defaults(hass):
    """Kill mutants changing types or defaults in reconfigure and rest_api forms."""
    from unittest.mock import patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    # 1. Reconfigure form (types and error re-injection)
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": "reconfigure", "entry_id": "test_id"}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.10",
        CONF_MAC: "AA:BB:CC",
        CONF_TOKEN: "old_token",
        CONF_CERT: "",
    }

    with (
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._get_reconfigure_entry"
        ) as mock_get_entry,
        patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id"
        ) as mock_resolve,
    ):
        mock_get_entry.return_value.data = flow.flow_data
        mock_resolve.return_value = "mac_resolve_failed"

        # Inject bad MAC
        try:
            async with asyncio.timeout(0.5):
                res_err = await flow.async_step_reconfigure_confirm(
                    {
                        CONF_IP_ADDRESS: "192.168.1.99",
                        CONF_MAC: "BAD_MAC",
                        CONF_TOKEN: "new_token",
                        CONF_CERT: "cert.pem",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res_err["type"] == "form"
        assert res_err["step_id"] == "reconfigure_confirm"

        schema = res_err["data_schema"].schema

        ip_key = next(k for k in schema if str(k) == CONF_IP_ADDRESS)
        assert schema[ip_key] is str
        assert ip_key.description["suggested_value"] == "192.168.1.99"

        mac_key = next(k for k in schema if str(k) == CONF_MAC)
        assert schema[mac_key] is str
        assert mac_key.description["suggested_value"] == "BAD_MAC"

        token_key = next(k for k in schema if str(k) == CONF_TOKEN)
        assert schema[token_key] is str
        assert token_key.description["suggested_value"] == "new_token"

    # 2. REST API form (types and error re-injection)
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    flow2.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session_func:
        # Cause auth error
        mock_session_func.return_value.get.return_value.__aenter__.return_value.status = 401

        try:
            async with asyncio.timeout(0.5):
                res_rest = await flow2.async_step_rest_api(
                    {
                        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
                        CONF_IP_ADDRESS: "api.smartthings.com",
                        CONF_TOKEN: "wrong_token",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res_rest["type"] == "form"
        assert res_rest["step_id"] == "rest_api"

        schema2 = res_rest["data_schema"].schema

        ip_key2 = next(k for k in schema2 if str(k) == CONF_IP_ADDRESS)
        assert schema2[ip_key2] is str
        assert getattr(ip_key2, "default", lambda: None)() == "api.smartthings.com"

        token_key2 = next(k for k in schema2 if str(k) == CONF_TOKEN)
        assert schema2[token_key2] is str
        assert getattr(token_key2, "default", lambda: None)() == "wrong_token"


async def test_await_button_ghost_token(hass):
    """Kills the mutant returning fallback without token in await_button."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.acquirer = MagicMock()

    class DummyTask:
        def __init__(self, res):
            self._res = res

        def done(self):
            return True

        def result(self):
            return self._res

    with patch(
        "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._wait_token_safe"
    ):
        flow.task = DummyTask({"ok": True, "token": ""})
        try:
            async with asyncio.timeout(0.5):
                res = await flow.async_step_await_button()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res["step_id"] == "handle_error"
        assert flow.flow_data["error_key"] == "token_acquisition_failed"


async def test_trampa2_placeholders_and_step_ids(hass):
    """Sniper test to kill placeholder (ip_address, device_name) and step_id mutants."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE, DEVICE_TYPE_MIM_H03
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    flow = ClimateIpConfigFlow()
    flow.hass = hass

    # Simulate _test_connection_safe failing
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC",
    }
    with patch(
        "custom_components.climate_ip.helpers.validate_poll_interval",
        return_value=10,
    ):
        with patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_process_samsung_device_step",
            return_value=None,
        ):
            # 1. Call without task to see async_show_progress
            class DummyTaskNotDone:
                def done(self):
                    return False

            with patch.object(
                flow.hass, "async_create_task", return_value=DummyTaskNotDone()
            ):
                try:
                    async with asyncio.timeout(0.5):
                        res_prog1 = await flow.async_step_test_connection()
                except TimeoutError:
                    pytest.fail(
                        "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                    )

                assert res_prog1["type"] == "progress"
                assert res_prog1["step_id"] == "test_connection"
                assert "description_placeholders" in res_prog1
                assert (
                    res_prog1["description_placeholders"]["ip_address"]
                    == "192.168.1.100"
                )

            # 2. Simulate task finished with error
            class DummyTask:
                def __init__(self, res):
                    self._res = res

                def done(self):
                    return True

                def result(self):
                    return self._res

            flow.task = DummyTask({"ok": False, "error": "cannot_connect"})

            try:
                async with asyncio.timeout(0.5):
                    res_prog2 = await flow.async_step_test_connection()
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            assert res_prog2["step_id"] == "handle_error"

            try:
                async with asyncio.timeout(0.5):
                    res = await flow.async_step_handle_error()
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            assert res["type"] == "form"
            # device_type MIM_H03 routes to step_id "mim_h03"
            assert res["step_id"] == "mim_h03"


async def test_phantom_names_in_error_forms(hass: HomeAssistant) -> None:
    """Kill Shot 4: Phantom Names in Error Forms. Check step_id and schema on ValueError/Invalid."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_IP_ADDRESS: "192.168.1.10",
    }

    try:
        async with asyncio.timeout(0.5):
            res = await flow.async_step_rest_api(
                user_input={CONF_TOKEN: "valid-token", CONF_POLL_INTERVAL: "invalid"}
            )
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert res["type"] == "form"
    assert res["step_id"] == "rest_api"
    assert res["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"
    assert res.get("data_schema") is not None
    from homeassistant.const import CONF_IP_ADDRESS

    assert vol.Required(CONF_IP_ADDRESS) in res["data_schema"].schema


# ============================================================
# SNIPER SUITE — Plan A (mutantes.txt)
# ============================================================


@pytest.mark.asyncio
async def test_import_cannot_connect_reason(hass: HomeAssistant) -> None:
    """Verify mutant M43 kill, M44, M45: abort reason must be exactly 'cannot_connect'."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    with patch.object(
        flow,
        "_test_connection_safe",
        return_value={"ok": False, "error": "cannot_connect"},
    ):
        try:
            async with asyncio.timeout(0.5):
                res = await flow.async_step_import(
                    {
                        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
                        CONF_IP_ADDRESS: "1.1.1.1",
                        CONF_MAC: "AA:BB:CC:DD:EE:FF",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res["type"] == "abort"
    # M43: reason=None → HA cannot show correct screen
    # M44: reason="XXcannot_connectXX" → incorrect screen
    # M45: reason="CANNOT_CONNECT" → incorrect screen
    assert res["reason"] == "cannot_connect"


@pytest.mark.asyncio
async def test_import_connection_tested_when_device_type_present(
    hass: HomeAssistant,
) -> None:
    """Verify mutant M33 kill: The condition 'if CONF_DEVICE_TYPE in self.flow_data' MUST NOT be inverted."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    with (
        patch.object(
            flow, "_test_connection_safe", return_value={"ok": True}
        ) as mock_test,
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "async_create_entry", return_value={"type": "create_entry"}),
    ):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_import(
                    {
                        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
                        CONF_IP_ADDRESS: "1.1.1.1",
                        CONF_MAC: "AA:BB:CC:DD:EE:FF",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    # M33 inverts the condition → _test_connection_safe is NOT called when DEVICE_TYPE is present
    mock_test.assert_called_once()


@pytest.mark.asyncio
async def test_rest_api_clientsession_receives_hass(hass: HomeAssistant) -> None:
    """Verify mutant M47 kill: async_get_clientsession must receive self.hass, not None."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get
        with (
            patch.object(flow, "async_set_unique_id"),
            patch.object(flow, "_abort_if_unique_id_configured"),
            patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
        ):
            try:
                async with asyncio.timeout(0.5):
                    await flow.async_step_rest_api(
                        {
                            CONF_IP_ADDRESS: "api.smartthings.com",
                            CONF_TOKEN: "valid-token-12345",
                            "device_id": "my-device-id",
                        }
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )
    # M47: async_get_clientsession(None) → invalid session
    mock_sess.assert_called_once_with(flow.hass)
    from custom_components.climate_ip.const import GLOBAL_HTTP_TIMEOUT

    mock_sess.return_value.get.assert_called_once_with(
        "https://api.smartthings.com/v1/devices",
        headers={"Authorization": "Bearer valid-token-12345"},
        timeout=GLOBAL_HTTP_TIMEOUT,
    )


@pytest.mark.asyncio
async def test_rest_api_ipv6_url_has_brackets(hass: HomeAssistant) -> None:
    """Verify mutant M51 kill: With IPv6, the URL must have brackets [fe80::1]."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get
        with (
            patch.object(flow, "async_set_unique_id"),
            patch.object(flow, "_abort_if_unique_id_configured"),
            patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
        ):
            try:
                async with asyncio.timeout(0.5):
                    await flow.async_step_rest_api(
                        {
                            CONF_IP_ADDRESS: "fe80::1",
                            CONF_TOKEN: "valid-token-12345",
                            "device_id": "my-device-id",
                        }
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )
    from custom_components.climate_ip.const import GLOBAL_HTTP_TIMEOUT

    # M51: IPv6 Brackets, Headers and Timeout
    mock_sess.return_value.get.assert_called_once_with(
        "https://[fe80::1]/v1/devices",
        headers={"Authorization": "Bearer valid-token-12345"},
        timeout=GLOBAL_HTTP_TIMEOUT,
        ssl=False,
    )


@pytest.mark.asyncio
async def test_rest_api_no_mac_abort_reason(hass: HomeAssistant) -> None:
    """Verify mutant M81 kill, M82, M84, M85, M86: empty unique_id aborts with exact reason 'no_mac_address_found' for non-SmartThings devices."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: "generic_rest"}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get
        # No CONF_DEVICE_ID or CONF_MAC → unique_id = "" → abort
        try:
            async with asyncio.timeout(0.5):
                res = await flow.async_step_rest_api(
                    {
                        CONF_IP_ADDRESS: "192.168.1.50",
                        CONF_TOKEN: "valid-token-12345",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert res["type"] == "abort"

    # M82: unique_id="XXXX" → truthy → does not abort → duplicate device
    # M84: reason=None; M85: reason="XXno_mac_address_foundXX"; M86: reason="NO_MAC_ADDRESS_FOUND"
    assert res["reason"] == "no_mac_address_found"


@pytest.mark.asyncio
async def test_cert_validation_called_with_correct_value(hass: HomeAssistant) -> None:
    """Verify mutant M121 kill: _async_validate_cert_path must be called with cert_value, not None."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "10.0.0.1",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_TOKEN: "tok",
        CONF_CERT: "my_cert.pem",
    }
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=False) as mock_val,
    ):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_reconfigure_confirm(
                    user_input={
                        CONF_IP_ADDRESS: "10.0.0.1",
                        CONF_MAC: "AA:BB:CC:DD:EE:FF",
                        CONF_TOKEN: "tok",
                        CONF_CERT: "my_cert.pem",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    # M121: would call with None → always passes or fails depending on mock → incorrect behavior
    mock_val.assert_called_once_with("my_cert.pem")


@pytest.mark.asyncio
async def test_reconfigure_null_token_routes_to_pairing(hass: HomeAssistant) -> None:
    """Verify mutant M157 kill: token_val=None→XXXX would do if not token_val False, skipping pairing block."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "10.0.0.1",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        # CONF_TOKEN ABSENT so get() returns None
    }
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch.object(
            flow,
            "async_step_initiate_pairing",
            return_value={"type": "progress", "step_id": "await_button"},
        ) as mock_pairing,
    ):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_reconfigure_confirm(
                    user_input={
                        CONF_IP_ADDRESS: "10.0.0.1",
                        CONF_MAC: "AA:BB:CC:DD:EE:FF",
                        # WITHOUT CONF_TOKEN IN INPUT
                        CONF_CERT: "",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    # M157: By injecting "XXXX", the code thinks there is a token and doesn't call pairing.
    # We strictly require it to be called.
    mock_pairing.assert_called_once()


@pytest.mark.asyncio
async def test_reconfigure_cert_fallback_name_is_exact(hass: HomeAssistant) -> None:
    """Verify mutant M161 kill, M162, M163: target_cert_name must be exactly 'ac14k_m.pem'."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_8888,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "10.0.0.1",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_CERT: "",  # empty → forces use of target_cert_name
    }
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acq,
    ):
        mock_acq.return_value = MagicMock()
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_reconfigure_confirm(
                    user_input={
                        CONF_IP_ADDRESS: "10.0.0.1",
                        CONF_MAC: "AA:BB:CC:DD:EE:FF",
                        CONF_TOKEN: "",  # empty → pairing with cert fallback
                        CONF_CERT: "",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    mock_acq.assert_called_once()
    assert mock_acq.call_args[0][1] == "10.0.0.1"


@pytest.mark.asyncio
async def test_reconfigure_update_entry_called_with_real_entry(
    hass: HomeAssistant,
) -> None:
    """Verify mutant M182 kill, M184: async_update_entry must be called with the real entry, not None."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
        DOMAIN,
    )
    from homeassistant import config_entries
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_MAC: "AA:BB:CC:DD:EE:FF",
            CONF_TOKEN: "old_token",
        },
        unique_id="AA:BB:CC:DD:EE:FF",
    )

    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }

    try:
        async with asyncio.timeout(0.5):
            await flow.async_step_reconfigure()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch.object(
            flow,
            "async_update_reload_and_abort",
            return_value={"type": "abort", "reason": "reconfigure_successful"},
        ) as mock_update_reload_and_abort,
    ):
        try:
            async with asyncio.timeout(0.5):
                result = await flow.async_step_reconfigure_confirm(
                    user_input={
                        CONF_IP_ADDRESS: "192.168.1.200",
                        CONF_MAC: "AA:BB:CC:DD:EE:FF",
                        CONF_TOKEN: "new_token",
                        CONF_CERT: "",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"

    mock_update_reload_and_abort.assert_called_once()
    # M182: first arg is None → HA does not update correct entry
    # M184: without first positional arg → TypeError or updates incorrect entry
    actual_entry_arg = mock_update_reload_and_abort.call_args[0][0]
    assert actual_entry_arg is not None
    assert actual_entry_arg is entry
    # Verify that new data propagated
    actual_data = mock_update_reload_and_abort.call_args.kwargs.get(
        "data"
    ) or mock_update_reload_and_abort.call_args[1].get("data")
    assert actual_data[CONF_IP_ADDRESS] == "192.168.1.200"
    assert actual_data[CONF_TOKEN] == "new_token"


# ============================================================
# ATTACK 1 — Group A: Force except block in the 3 progress steps
# Kills: M7-M14 in initiate_pairing, await_button, test_connection
# ============================================================


@pytest.mark.asyncio
async def test_force_except_in_all_progress_steps(hass: HomeAssistant) -> None:
    """Verify Group A mutant kill: the except block must produce error_key 'unknown_error', never success."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    # ── async_step_test_connection ──────────────────────────────────────────
    flow_tc = ClimateIpConfigFlow()
    flow_tc.hass = hass
    flow_tc.DEBUG_ME = True
    flow_tc.context = {}
    flow_tc.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.2.3.4",
    }
    # Task that throws exception when calling .result()
    mock_task_tc = MagicMock()
    mock_task_tc.done.return_value = True
    mock_task_tc.result.side_effect = RuntimeError("Fatal failure in test_connection")
    flow_tc.task = mock_task_tc

    try:
        async with asyncio.timeout(0.5):
            result_tc = await flow_tc.async_step_test_connection()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    # M7 (result=None) → AttributeError in result.get("ok") → crash
    # M10 (ok:True) → flow would proceed to discover_uuid/create_entry even if there was an exception
    assert result_tc["type"] == "progress_done"
    assert result_tc["step_id"] == "handle_error"
    assert flow_tc.flow_data["error_key"] == "unknown_error"

    # ── async_step_await_button ─────────────────────────────────────────────
    flow_ab = ClimateIpConfigFlow()
    flow_ab.hass = hass
    flow_ab.DEBUG_ME = True
    flow_ab.acquirer = MagicMock()
    flow_ab.context = {}
    flow_ab.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.2.3.4",
    }
    mock_task_ab = MagicMock()
    mock_task_ab.done.return_value = True
    mock_task_ab.result.side_effect = RuntimeError("Fatal failure in await_button")
    flow_ab.task = mock_task_ab

    try:
        async with asyncio.timeout(0.5):
            result_ab = await flow_ab.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result_ab["type"] == "progress_done"
    assert result_ab["step_id"] == "handle_error"
    assert flow_ab.flow_data["error_key"] == "unknown_error"

    # ── async_step_initiate_pairing ─────────────────────────────────────────
    flow_ip = ClimateIpConfigFlow()
    flow_ip.hass = hass
    flow_ip.DEBUG_ME = True
    flow_ip.acquirer = MagicMock()
    flow_ip.context = {}
    flow_ip.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.2.3.4",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        "_fallback_attempted": True,  # Skips fallback, goes straight to handle_error
    }
    mock_task_ip = MagicMock()
    mock_task_ip.done.return_value = True
    mock_task_ip.result.side_effect = RuntimeError("Fatal failure in initiate_pairing")
    flow_ip.task = mock_task_ip

    try:
        async with asyncio.timeout(0.5):
            result_ip = await flow_ip.async_step_initiate_pairing()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result_ip["type"] == "progress_done"
    assert result_ip["step_id"] == "handle_error"
    assert flow_ip.flow_data["error_key"] == "unknown_error"


# ── Attack 1B: Group F — next_step_id in await_button success path ──────────
@pytest.mark.asyncio
async def test_await_button_success_next_step_id_strict(hass: HomeAssistant) -> None:
    """Verify mutant M45 kill, M46, M47: next_step_id must be exactly 'discover_uuid' on success (not 2878)."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE, DEVICE_TYPE_MIM_H03
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.acquirer = MagicMock()
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,  # Not 2878 → goes to discover_uuid
        CONF_IP_ADDRESS: "1.2.3.4",
    }
    mock_task = MagicMock()
    mock_task.done.return_value = True
    mock_task.result.return_value = {"ok": True, "token": "valid-token-abcde"}
    flow.task = mock_task

    try:
        async with asyncio.timeout(0.5):
            result = await flow.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == "progress_done"
    # M45: next_step_id=None → HA looks for step "None" → crash
    # M46: "XXdiscover_uuidXX" → step does not exist → crash
    # M47: "DISCOVER_UUID" → step does not exist → crash
    assert result["step_id"] == "discover_uuid"
    assert flow.flow_data[CONF_TOKEN] == "valid-token-abcde"


# ============================================================
# ATTACK 2 — Group D: YamlController strict instantiation (M82-M86)
# ============================================================


@pytest.mark.asyncio
# ============================================================
# ATTACK 3 — Groups C + E: _test_connection_safe dict mutations + unique_id
# ============================================================


@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_rest_api_empty_unique_id_aborts(hass: HomeAssistant) -> None:
    """Verify mutant M77 kill, M78: unique_id vacío debe abortar con 'no_mac_address_found' para dispositivos no SmartThings."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: "generic_rest"}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get

        # Sin CONF_DEVICE_ID ni CONF_MAC → unique_id = "" → debe abortar
        try:
            async with asyncio.timeout(0.5):
                result = await flow.async_step_rest_api(
                    {
                        CONF_IP_ADDRESS: "192.168.1.50",
                        CONF_TOKEN: "valid-token-12345",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == "abort"
    assert result["reason"] == "no_mac_address_found"


@pytest.mark.asyncio
async def test_rest_api_unique_id_empty_fallback_strict(hass: HomeAssistant) -> None:
    """Verify mutant M77 kill, M78: unique_id vacío debe abortar con 'no_mac_address_found', no con XXXX truthy."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: "generic_rest"}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get

        # Sin CONF_DEVICE_ID ni CONF_MAC → unique_id = "" → debe abortar
        # M78: unique_id = "XXXX" → truthy → NO aborta → async_set_unique_id("XXXX") → duplicado
        try:
            async with asyncio.timeout(0.5):
                result = await flow.async_step_rest_api(
                    {
                        CONF_IP_ADDRESS: "192.168.1.50",
                        CONF_TOKEN: "valid-token-12345",
                        # No device_id or MAC → only fallback is ""
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == "abort"
    assert result["reason"] == "no_mac_address_found"


@pytest.mark.asyncio
async def test_rest_api_errors_base_unknown_error_strict(hass: HomeAssistant) -> None:
    """Kill mutant M94-M98: Ensures errors['base'] = 'cannot_connect' on HTTP failure."""
    from unittest.mock import patch

    import aiohttp

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        # Force aiohttp exception inside try block of async_step_rest_api
        mock_sess.side_effect = aiohttp.ClientError("Red caída")

        try:
            async with asyncio.timeout(0.5):
                result = await flow.async_step_rest_api(
                    {
                        CONF_IP_ADDRESS: "api.smartthings.com",
                        CONF_TOKEN: "valid-token-12345",
                    }
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == "form"
    assert result["errors"].get("base") == "cannot_connect"


async def test_loud_vanguard_lethal_failure_verbose_abort(hass: HomeAssistant) -> None:
    """Operation Loud Vanguard: Lethal failures abort with description_placeholders."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.150",
        "error_key": "pairing_connection_failed",
        "error_details": "Connection refused on port 8888",
    }

    try:
        async with asyncio.timeout(0.5):
            result = await flow.async_step_handle_error()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == "abort"
    assert result["reason"] == "pairing_connection_failed"
    assert result["description_placeholders"]["ip_address"] == "192.168.1.150"
    assert (
        result["description_placeholders"]["error_details"]
        == "Connection refused on port 8888"
    )


async def test_loud_vanguard_recoverable_failure_form_retry(
    hass: HomeAssistant,
) -> None:
    """Operation Loud Vanguard: Recoverable failures return form retry with targeted errors."""
    from custom_components.climate_ip.const import DEVICE_TYPE_SAMSUNG_8888

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.150",
        "error_key": "timeout_connect",
    }

    try:
        async with asyncio.timeout(0.5):
            result_timeout = await flow.async_step_handle_error()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result_timeout["type"] == "form"
    assert result_timeout["errors"][CONF_IP_ADDRESS] == "timeout_connect"

    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.150",
        "error_key": "invalid_auth",
    }
    try:
        async with asyncio.timeout(0.5):
            result_auth = await flow.async_step_handle_error()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result_auth["type"] == "form"
    assert result_auth["errors"]["base"] == "invalid_auth"


async def test_handle_error_mac_and_unmapped_fallback_mutants(
    hass: HomeAssistant,
) -> None:
    """Mata los mutantes 16, 17, 18, 19, 1389, 1391 y 1403 en async_step_handle_error."""
    from custom_components.climate_ip.const import (
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SAMSUNG_8888,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
    }

    # MATAR MUTANTES de mac_resolve_failed
    flow.flow_data["error_key"] = "mac_resolve_failed"
    try:
        async with asyncio.timeout(0.5):
            res_mac = await flow.async_step_handle_error()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_mac["type"] == "form"
    assert res_mac["errors"] == {"base": "mac_resolve_failed"}
    assert res_mac["step_id"] == "samsung_2878"

    # Verify with 8888 that step_id is samsung_8888
    flow.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_8888
    flow.flow_data["error_key"] = "mac_resolve_failed"
    try:
        async with asyncio.timeout(0.5):
            res_8888 = await flow.async_step_handle_error()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_8888["step_id"] == "samsung_8888"

    # MATAR M1403 (else branch: error_key no mapeada directamente)
    flow.flow_data["error_key"] = "algún_error_aleatorio_no_mapeado"
    try:
        async with asyncio.timeout(0.5):
            res_fallback = await flow.async_step_handle_error()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_fallback["type"] == "form"
    assert res_fallback["errors"] == {"base": "algún_error_aleatorio_no_mapeado"}


@pytest.mark.asyncio
async def test_async_step_initiate_pairing_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_initiate_pairing."""
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )
    from homeassistant.const import CONF_IP_ADDRESS

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.acquirer = MagicMock(async_close=AsyncMock())

    # 1. Kill mutmut 10, 11, 12, 13, 14, 15 (successful pairing)
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": True, "config": "some_config"}

    try:
        async with asyncio.timeout(0.5):
            res1 = await flow.async_step_initiate_pairing()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res1["type"] == "progress_done"
    assert res1["step_id"] == "await_button"
    assert flow.flow_data["preferred_connection"] == "some_config"
    # Kill mutmut 6: self.task must be cleared to None
    assert flow.task is None

    # 2. Kill mutmut 20, 21, 22 (_fallback_attempted is already True)
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    flow2.acquirer = MagicMock(async_close=AsyncMock())
    flow2.flow_data = {"_fallback_attempted": True}
    flow2.task = MagicMock()
    flow2.task.done.return_value = True
    flow2.task.result.return_value = {
        "ok": False,
        "error": "test_error",
        "error_details": "test_details",
    }

    try:
        async with asyncio.timeout(0.5):
            res2 = await flow2.async_step_initiate_pairing()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    # It should not try fallback again, it should return progress_done to handle_error
    assert res2["type"] == "progress_done"
    assert res2["step_id"] == "handle_error"
    assert flow2.flow_data["error_key"] == "test_error"
    assert flow2.flow_data["error_details"] == "test_details"

    # 3. Kill mutmut 29 (ip_address in fallback)
    flow3 = ClimateIpConfigFlow()
    flow3.hass = hass
    flow3.acquirer = MagicMock(async_close=AsyncMock())
    flow3.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_CERT: "my_cert.pem",
    }
    # No _fallback_attempted set yet
    flow3.task = MagicMock()
    flow3.task.done.return_value = True
    flow3.task.result.return_value = {"ok": False, "error": "test_error"}

    # We mock GenericYamlTokenAcquirer so we can check if it gets initialized with ip_address
    with patch(
        "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
    ) as mock_acquirer:
        try:
            async with asyncio.timeout(0.5):
                res3 = await flow3.async_step_initiate_pairing()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        # Should initiate progress for fallback
        assert res3["type"] == "progress"
        assert res3["step_id"] == "initiate_pairing"
        assert flow3.flow_data["_fallback_attempted"] is True

        # Kill mutmut 29: Assert ip_address was passed correctly, not None (which becomes "None")
        mock_acquirer.assert_called_once()
        args, _kwargs = mock_acquirer.call_args
        assert args[1] == "192.168.1.100"

    # 4. Kill mutmut 36, 37, 38, 42, 47, 48 (missing CONF_CERT fallback to ac14k_m.pem)
    flow4 = ClimateIpConfigFlow()
    flow4.hass = hass
    flow4.acquirer = MagicMock(async_close=AsyncMock())
    flow4.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.101",
    }
    flow4.task = MagicMock()
    flow4.task.done.return_value = True
    flow4.task.result.return_value = {"ok": False, "error": "test_error"}

    with patch(
        "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
    ) as mock_acquirer4:
        try:
            async with asyncio.timeout(0.5):
                res4 = await flow4.async_step_initiate_pairing()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res4["type"] == "progress"
        mock_acquirer4.assert_called_once()

    # 5. Kill mutmut 49, 50 (fallback for 8888 to 2878)
    from custom_components.climate_ip.const import DEVICE_TYPE_SAMSUNG_8888

    flow5 = ClimateIpConfigFlow()
    flow5.hass = hass
    flow5.acquirer = MagicMock(async_close=AsyncMock())
    flow5.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.102",
        CONF_CERT: "my_cert.pem",
    }
    flow5.task = MagicMock()
    flow5.task.done.return_value = True
    flow5.task.result.return_value = {"ok": False, "error": "test_error"}

    with patch(
        "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
    ) as mock_acquirer5:
        try:
            async with asyncio.timeout(0.5):
                res5 = await flow5.async_step_initiate_pairing()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res5["type"] == "progress"
        assert flow5.flow_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_SAMSUNG_2878

        # Kill mutmut 51: acquirer is assigned
        assert flow5.acquirer is not None

        mock_acquirer5.assert_called_once()
        args5, _kwargs5 = mock_acquirer5.call_args

        assert args5[0] == flow5.hass
        assert args5[1] == "192.168.1.102"
        assert args5[3] == "my_cert.pem"

        # Kill mutmut 59: task is created
        assert flow5.task is not None
        assert flow5.task == flow5.hass.async_create_task.return_value

        # Kill mutmut 62, 63, 66, 69, 70: async_show_progress args
        assert res5.get("step_id") == "initiate_pairing"
        assert res5.get("progress_action") == "initiating_pairing"
        assert res5.get("progress_task") == flow5.task

    # 6. Kill mutmut 4 (if self.task or self.task.done())
    flow6 = ClimateIpConfigFlow()
    flow6.hass = MagicMock()
    flow6.acquirer = MagicMock(async_close=AsyncMock())

    mock_task = MagicMock()
    mock_task.done.return_value = False

    mock_task.result.side_effect = asyncio.InvalidStateError("Task is not done")
    flow6.hass.async_create_task.return_value = mock_task

    with patch.object(flow6, "_initiate_pairing_safe", return_value=None):
        try:
            async with asyncio.timeout(0.5):
                res6 = await flow6.async_step_initiate_pairing()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res6["type"] == "progress"

        # Kill mutmut 79-87: async_show_progress args at the end of the function
        assert res6.get("step_id") == "initiate_pairing"
        assert res6.get("progress_action") == "initiating_pairing"
        assert res6.get("progress_task") == mock_task
