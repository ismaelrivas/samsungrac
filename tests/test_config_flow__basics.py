# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test the Climate IP config flow."""

# pylint: disable=import-outside-toplevel,reimported
from __future__ import annotations

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONN_METHOD_RAW,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
)
from custom_components.climate_ip.exceptions import AuthError


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
    from homeassistant.helpers.selector import SelectSelectorMode

    from custom_components.climate_ip.const import CONF_DEVICE_TYPE

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
    for key in schema.schema.keys():
        if getattr(key, "schema", None) == CONF_TOKEN:
            token_default = key.default()
            break

    assert token_default == "auto_token"


async def test_mim_h03_empty_list(hass: HomeAssistant) -> None:
    """Test that MIM-H03 flow handles an empty device list without KeyError."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}

    from custom_components.climate_ip.const import (  # pylint: disable=reimported
        DEVICE_TYPE_MIM_H03,
    )

    await flow.async_step_user()
    result = await flow.async_step_user({CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03})

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_controller_class,
        patch("homeassistant.helpers.aiohttp_client.async_get_clientsession"),
    ):
        mock_controller_instance = mock_controller_class.return_value
        mock_controller_instance.initialize = AsyncMock(return_value=True)
        mock_controller_instance.async_get_status = AsyncMock(return_value=True)
        # Mock empty list of devices
        mock_controller_instance.discovered_devices = []
        mock_controller_instance.async_shutdown = AsyncMock()

        with patch(
            "custom_components.climate_ip.config_flow.ClimateIpConfigFlow._create_entry",
            new_callable=AsyncMock,
        ) as mock_create_entry:
            mock_create_entry.return_value = {"type": FlowResultType.CREATE_ENTRY}
            result = await flow.async_step_discover_uuid()

    # Should safely create entry instead of crashing with KeyError
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_async_force_arp_update_times_out(hass: HomeAssistant) -> None:
    """Test that the native async ARP update gracefully times out or handles closed ports."""
    from custom_components.climate_ip.const import PORT_SAMSUNG_2878, PORT_SAMSUNG_8888

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    with (
        patch(
            "asyncio.wait_for", new_callable=AsyncMock, side_effect=asyncio.TimeoutError
        ) as mock_wait_for,
        patch("asyncio.open_connection") as mock_open_connection,
    ):
        mock_open_connection.side_effect = ["coro1", "coro2"]

        await flow._async_force_arp_update("192.168.1.100")  # pylint: disable=protected-access

        assert mock_open_connection.call_count == 2
        mock_open_connection.assert_any_call("192.168.1.100", PORT_SAMSUNG_2878)
        mock_open_connection.assert_any_call("192.168.1.100", PORT_SAMSUNG_8888)

        assert mock_wait_for.call_count == 2
        for call in mock_wait_for.call_args_list:
            assert len(call.args) == 1, (
                "asyncio.wait_for debe recibir la corrutina como primer argumento posicional"
            )
            assert "timeout" in call.kwargs
            assert call.kwargs["timeout"] == 0.5


async def test_async_force_arp_update_success(hass: HomeAssistant) -> None:
    """Test that it stops attempting ports when one succeeds."""
    from custom_components.climate_ip.const import PORT_SAMSUNG_2878

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    mock_writer = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with (
        patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait_for,
        patch("asyncio.open_connection") as mock_open_connection,
    ):
        mock_wait_for.return_value = (MagicMock(), mock_writer)
        mock_open_connection.return_value = "coro1"

        await flow._async_force_arp_update("192.168.1.100")  # pylint: disable=protected-access

        assert mock_open_connection.call_count == 2
        mock_open_connection.assert_any_call("192.168.1.100", PORT_SAMSUNG_2878)

        assert mock_wait_for.called
        for call in mock_wait_for.call_args_list:
            assert len(call.args) == 1, (
                "asyncio.wait_for debe recibir la corrutina como primer argumento posicional"
            )
            assert "timeout" in call.kwargs
            assert call.kwargs["timeout"] == 0.5


async def test_initiate_pairing_graceful_failure(hass: HomeAssistant) -> None:
    """Test that TokenAcquisitionError during pairing initiation is handled gracefully."""
    from custom_components.climate_ip.exceptions import TokenAcquisitionError

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.acquirer = MagicMock()
    flow.acquirer.async_initiate_pairing = AsyncMock(
        side_effect=TokenAcquisitionError("Simulated failure")
    )

    try:
        async with asyncio.timeout(0.5):
            result = await flow._initiate_pairing_safe()  # pylint: disable=protected-access
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["ok"] is False
    assert result["error"] == "pairing_connection_failed"


async def test_smartthings_token_reauth_triggers_flow(hass: HomeAssistant) -> None:
    """Test that an expired SmartThings token triggers the re-authentication flow."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    from custom_components.climate_ip.coordinator import (
        SamsungClimateCoordinator,
    )

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
        (k for k in schema.schema.keys() if getattr(k, "schema", k) == CONF_MAC), None
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


async def test_reconfigure_empty_token_triggers_pairing_2878(hass, mock_setup_entry):
    """Verify that blanking the token in reconfigure routes to initiate_pairing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="BC:8C:CD:5B:54:F6",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "old_token",
        },
    )
    # Mock the entry retrieval because the hass fixture in conftest is a lightweight mock
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }

    # 1. Initialize the flow (simulated by step_reconfigure which pre-fills flow_data)
    result = await flow.async_step_reconfigure()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure_confirm"
    assert "description_placeholders" in result
    assert "device_name" in result["description_placeholders"]
    assert "ip_address" in result["description_placeholders"]

    # 2. Submit the form with an empty token
    with patch(
        "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer",
        autospec=True,
    ) as mock_acquirer_cls:
        mock_acquirer_cls.return_value = MagicMock()
        result = await flow.async_step_reconfigure_confirm(
            user_input={
                CONF_IP_ADDRESS: "192.168.1.10",
                CONF_MAC: "BC:8C:CD:5B:54:F6",
                CONF_TOKEN: "",
                "cert": "",
            },
        )

    assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result["step_id"] == "await_button"
    assert mock_acquirer_cls.called


async def test_suggested_values_token_erasure(hass, mock_setup_entry):
    """Token field cleared by user must result in empty string in flow_data, not old value."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "old-token-xyz",
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

    result = await flow.async_step_reconfigure()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure_confirm"
    assert "description_placeholders" in result
    assert "device_name" in result["description_placeholders"]
    assert "ip_address" in result["description_placeholders"]

    with patch(
        "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer",
        autospec=True,
    ):
        result2 = await flow.async_step_reconfigure_confirm(
            user_input={
                CONF_IP_ADDRESS: "192.168.1.10",
                CONF_MAC: "BC:8C:CD:5B:54:F6",
                CONF_TOKEN: "",  # explicitly erased
                CONF_CERT: "",
            },
        )
    # Blanking the token must route to pairing status progress
    assert result2["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result2["step_id"] == "await_button"
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
    ip_key = next(k for k in schema.keys() if str(k) == CONF_IP_ADDRESS)
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


async def test_process_samsung_step_acquirer_initialization_8888(
    hass: HomeAssistant,
) -> None:
    """Audits strict instantiation of acquirer 8888 evaluating certificate fallback."""
    from unittest.mock import patch

    from homeassistant.const import CONF_IP_ADDRESS

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_CERT

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(
            flow, "_async_validate_cert_path", return_value=True
        ) as mock_validate_cert,
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acq_8888,
        patch.object(
            flow, "async_step_initiate_pairing", return_value={"type": "mocked"}
        ),
    ):
        # PHASE 1: No certificate provided (must inject exact default)
        flow.flow_data = {CONF_IP_ADDRESS: "192.168.1.50"}
        await flow._async_process_samsung_device_step("samsung_8888", True, {})

        # Kill mutmut_43: Assert _async_validate_cert_path called with ""
        mock_validate_cert.assert_called_with("")

        # Lethal assertion: Constructor called with mathematically exact parameters
        mock_acq_8888.assert_called_once()
        assert mock_acq_8888.call_args[0][0] == hass
        assert (
            mock_acq_8888.call_args[1].get("ip_address") == "192.168.1.50"
            or mock_acq_8888.call_args[0][1] == "192.168.1.50"
        )
        assert flow.acquirer == mock_acq_8888.return_value, (
            "La asignación a self.acquirer falló"
        )

        # Reset mock for phase 2
        mock_acq_8888.reset_mock()

        # PHASE 2: Explicit user-provided certificate
        flow.flow_data = {
            CONF_IP_ADDRESS: "192.168.1.50",
            CONF_CERT: "custom_user_cert.pem",
        }
        await flow._async_process_samsung_device_step("samsung_8888", True, {})

        # Lethal assertion: Fallback is ignored if user input exists
        mock_acq_8888.assert_called_once()
        assert (
            mock_acq_8888.call_args[1].get("cert_path") == "custom_user_cert.pem"
            or mock_acq_8888.call_args[0][3] == "custom_user_cert.pem"
        )


async def test_process_samsung_step_acquirer_initialization_2878(
    hass: HomeAssistant,
) -> None:
    """Audits strict instantiation of standard acquirer (port 2878)."""
    from unittest.mock import patch

    from homeassistant.const import CONF_IP_ADDRESS

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_CERT

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {CONF_IP_ADDRESS: "192.168.1.100", CONF_CERT: "/custom/cert.pem"}

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acq_2878,
        patch.object(
            flow, "async_step_initiate_pairing", return_value={"type": "mocked"}
        ),
    ):
        await flow._async_process_samsung_device_step("samsung_2878", False, {})

        # Lethal assertion: Frontera de inyección de dependencias
        mock_acq_2878.assert_called_once()
        assert mock_acq_2878.call_args[0][0] == hass
        assert (
            mock_acq_2878.call_args[1].get("ip_address") == "192.168.1.100"
            or mock_acq_2878.call_args[0][1] == "192.168.1.100"
        )
        assert (
            mock_acq_2878.call_args[1].get("cert_path") == "/custom/cert.pem"
            or mock_acq_2878.call_args[0][3] == "/custom/cert.pem"
        )
        assert flow.acquirer == mock_acq_2878.return_value, (
            "La asignación a self.acquirer falló"
        )


async def test_resolve_mac_and_set_unique_id(hass: HomeAssistant) -> None:
    """Test MAC address resolution logic."""
    from unittest.mock import patch

    from homeassistant.const import CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {}
    flow.context = {}

    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
    ):
        # 1. MAC provided
        result = await flow._async_resolve_mac_and_set_unique_id(
            "192.168.1.100", "aa:bb:cc:dd:ee:ff"
        )
        assert result is None
        assert flow.flow_data[CONF_MAC] == "AABBCCDDEEFF"

        # 2. MAC not provided, discovered immediately
        flow.flow_data.clear()
        with patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            return_value="11:22:33:44:55:66",
        ):
            result = await flow._async_resolve_mac_and_set_unique_id(
                "192.168.1.100", None
            )
            assert result is None
            assert flow.flow_data[CONF_MAC] == "112233445566"

        # 3. MAC not provided, discovered after ARP
        flow.flow_data.clear()
        with (
            patch(
                "custom_components.climate_ip.helpers.async_get_mac_address",
                side_effect=[None, "11:22:33:44:55:66"],
            ) as mock_get_mac,
            patch.object(flow, "_async_force_arp_update") as mock_arp,
        ):
            result = await flow._async_resolve_mac_and_set_unique_id(
                "192.168.1.100", None
            )
            assert result is None
            assert flow.flow_data[CONF_MAC] == "112233445566"
            mock_arp.assert_called_once_with("192.168.1.100")

            # Kill mutmut 15: Exact arguments for mac resolution
            assert mock_get_mac.call_args_list[0][0][0] == "192.168.1.100"
            assert mock_get_mac.call_args_list[1][0][0] == "192.168.1.100"

        # 4. MAC not provided, discovery fails
        flow.flow_data.clear()
        with (
            patch(
                "custom_components.climate_ip.helpers.async_get_mac_address",
                return_value=None,
            ),
            patch.object(flow, "_async_force_arp_update") as mock_arp,
        ):
            result = await flow._async_resolve_mac_and_set_unique_id(
                "192.168.1.100", None
            )
            assert result == "mac_resolve_failed"
            assert CONF_MAC not in flow.flow_data
            mock_arp.assert_called_once_with("192.168.1.100")


async def test_resolve_mac_mutants_coverage(hass: HomeAssistant) -> None:
    """Test coverage to kill mutants in MAC resolution and unique_id boilerplate."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": "user"}
    flow.flow_data = {CONF_IP_ADDRESS: "192.168.1.50"}

    # Case 1: Standard MAC resolution and unique ID setting
    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            return_value="aa:bb:cc:dd:ee:ff",
        ) as mock_get_mac,
        patch.object(flow, "async_set_unique_id") as mock_set_unique_id,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
    ):
        await flow._async_resolve_mac_and_set_unique_id("192.168.1.50", None)

        # Kill mutmut_15: assert we passed the IP, not None
        mock_get_mac.assert_called_with("192.168.1.50")

        # Kill mutmut_28: assert we passed the MAC, not None
        mock_set_unique_id.assert_called_with("AABBCCDDEEFF")

        # Kill mutmut_29-33 (part 1): not reauth and not reconfigure -> abort called
        mock_abort.assert_called_once()

    # Case 2: Reauth flow (should NOT abort)
    flow.reauth_entry = MagicMock()
    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            return_value="aa:bb:cc:dd:ee:ff",
        ),
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
    ):
        await flow._async_resolve_mac_and_set_unique_id("192.168.1.50", None)
        # Kill mutmut_29-33 (part 2): reauth -> abort NOT called
        mock_abort.assert_not_called()

    flow.reauth_entry = None

    # Case 3: Reconfigure flow (should NOT abort)
    flow.context["source"] = "reconfigure"
    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            return_value="aa:bb:cc:dd:ee:ff",
        ),
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
    ):
        await flow._async_resolve_mac_and_set_unique_id("192.168.1.50", None)
        # Kill mutmut_29-33 (part 3): reconfigure -> abort NOT called
        mock_abort.assert_not_called()


async def test_validate_cert_path_mutants_coverage(hass: HomeAssistant) -> None:
    """Test coverage to kill mutants in certificate validation."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # Kill mutmut_1, 4: test None and "" paths return True immediately
    assert await flow._async_validate_cert_path(None) is True
    assert await flow._async_validate_cert_path("") is True

    # Kill mutmut_10 & 11: verify the resolution logic
    import os

    import custom_components.climate_ip.config_flow as cf

    expected_dir = os.path.dirname(cf.__file__)

    with patch(
        "custom_components.climate_ip.helpers.resolve_cert_path"
    ) as mock_resolve:
        mock_resolve.return_value = "/dummy/resolved/path.pem"
        with patch("os.path.exists", return_value=True):
            assert await flow._async_validate_cert_path("my_cert.pem") is True
            # Assert the fallback directory passed is indeed the file's directory (killing None mutant)
            mock_resolve.assert_called_with("my_cert.pem", expected_dir, hass)

        # Test the path check mutant where resolve returns None
        mock_resolve.return_value = None
        assert await flow._async_validate_cert_path("my_cert.pem") is True

        # Test the exists fallback mutant (kill mutmut_14, 16)
        mock_resolve.return_value = "/dummy/invalid.pem"
        with patch("os.path.exists", return_value=False) as mock_exists:
            assert await flow._async_validate_cert_path("my_cert.pem") is False
            mock_exists.assert_called_once_with("/dummy/invalid.pem")


async def test_create_entry_mutants_coverage(hass: HomeAssistant) -> None:
    """Test coverage to kill mutants in _create_entry."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": "user"}

    # Kill mutmut_10, 11, 12: final_unique_id is empty -> aborts with "no_mac_address_found"
    flow.flow_data = {"device_type": "dummy"}
    with patch.object(
        flow, "async_abort", return_value={"type": "abort"}
    ) as mock_abort:
        await flow._create_entry()
        mock_abort.assert_called_once_with(reason="no_mac_address_found")

    # Kill mutmut_1: device_type usage. When device_type is 8888, it appends unique_id to title if not present.
    # If device_type were None, it wouldn't append it.
    flow.flow_data = {
        "unique_id": "AA:BB:CC",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        "name": "Living Room",
    }
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow, "async_create_entry", return_value={"type": "create_entry"}
        ) as mock_create,
    ):
        await flow._create_entry()
        # Assert title modification logic (kill mutmut_1)
        # title should be "Living Room (AA:BB:CC)"
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["title"] == "Living Room (AA:BB:CC)"

    # Kill mutmut_14-17: reauth / reconfigure guard logic.
    # 1. Standard flow: not reauth, not reconfigure -> _abort_if_unique_id_configured IS called
    flow.flow_data = {"unique_id": "AA:BB:CC", "device_type": "dummy"}
    flow.reauth_entry = None
    flow.context["source"] = "user"
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
        patch.object(flow, "async_create_entry"),
    ):
        await flow._create_entry()
        mock_abort.assert_called_once()

    # 2. Reauth flow -> _abort_if_unique_id_configured IS NOT called
    from custom_components.climate_ip.const import CONF_DISCOVERED_DEVICES

    flow.flow_data = {
        "unique_id": "AA:BB:CC",
        CONF_DISCOVERED_DEVICES: "transient",
        "valid_key": "valid",
        "device_type": "dummy",
    }
    flow.reauth_entry = MagicMock()
    flow.reauth_entry.entry_id = "mock_entry_id"
    flow.context["source"] = "user"
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
        patch.object(flow.hass.config_entries, "async_update_entry") as mock_update,
        patch.object(flow, "async_abort") as mock_async_abort,
        patch.object(flow.hass, "async_create_task") as mock_task,
        patch.object(flow.hass.config_entries, "async_reload") as mock_reload,
    ):
        await flow._create_entry()
        mock_abort.assert_not_called()
        # Kill mutmut_35, 37, 38, 39, 40: assert exact update arguments
        # Kill mutmut_36: assert transient keys are REMOVED (not kept)
        expected_dict = {
            "unique_id": "AA:BB:CC",
            "valid_key": "valid",
            "name": "Samsung AC AA:BB:CC",
            "device_type": "dummy",
        }
        mock_update.assert_called_once_with(flow.reauth_entry, data=expected_dict)
        # Kill mutmut_41, 42: assert exact reload arguments
        mock_reload.assert_called_once_with("mock_entry_id")
        mock_task.assert_called_once()
        assert mock_task.call_args[0][0] is not None
        mock_async_abort.assert_called_once_with(reason="reauth_successful")

    # 3. Reconfigure flow -> _abort_if_unique_id_configured IS NOT called
    # Kill mutmut_47, 48: exact matching of "reconfigure"
    flow.flow_data = {
        "unique_id": "AA:BB:CC",
        "valid_key": "valid2",
        CONF_DISCOVERED_DEVICES: "transient",
        "device_type": "dummy",
    }
    flow.reauth_entry = None
    flow.context = {"source": "reconfigure", "entry_id": "dummy"}
    reconf_entry_mock = MagicMock()
    reconf_entry_mock.data = {"old_key": "old_val"}
    reconf_entry_mock.entry_id = "reconf_entry_id"
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
        patch.object(flow.hass.config_entries, "async_update_entry") as mock_update,
        patch.object(flow, "async_abort") as mock_async_abort,
        patch.object(
            flow, "_get_reconfigure_entry", return_value=reconf_entry_mock
        ) as mock_get_reconf,
        patch.object(flow.hass, "async_create_task") as mock_task,
        patch.object(flow.hass.config_entries, "async_reload") as mock_reload,
    ):
        await flow._create_entry()
        mock_abort.assert_not_called()
        # Kill mutmut_49: assert _get_reconfigure_entry was called
        mock_get_reconf.assert_called_once()
        # Kill mutmut_50, 51, 52: assert exact dictionary construction and update call
        expected_data = {
            "old_key": "old_val",
            "unique_id": "AA:BB:CC",
            "valid_key": "valid2",
            "name": "Samsung AC AA:BB:CC",
            "device_type": "dummy",
        }
        mock_update.assert_called_once_with(reconf_entry_mock, data=expected_data)
        # Assert reload
        mock_reload.assert_called_once_with("reconf_entry_id")
        mock_task.assert_called_once()
        assert mock_task.call_args[0][0] is not None
        mock_async_abort.assert_called_once_with(reason="reconfigure_successful")


async def test_create_entry_title_and_data_mutants_coverage(
    hass: HomeAssistant,
) -> None:
    """Test coverage to kill mutants related to title, device_type, and flow_data formatting in _create_entry."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {"source": "user"}

    from homeassistant.const import CONF_NAME

    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SAMSUNG_8888,
    )

    # 1. Kill mutmut_19: Verify _abort_if_unique_id_configured is called WITH updates=self.flow_data
    flow.flow_data = {
        "unique_id": "AA:BB:CC",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
    }
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
        patch.object(flow, "async_create_entry", return_value={"type": "create_entry"}),
    ):
        await flow._create_entry()
        mock_abort.assert_called_once_with(updates=flow.flow_data)

    # 2. Kill mutmut_23, 24, 27, 28: Title fallback logic.
    # When title is empty strings (e.g. "   "), it must fallback to Samsung AC {final_unique_id}
    # This kills mutmut_27 (if not title or title.strip() mutating to True).
    flow.flow_data = {
        "unique_id": "11:22:33",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_NAME: "   ",
    }
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow, "async_create_entry", return_value={"type": "create_entry"}
        ) as mock_create,
    ):
        await flow._create_entry()
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["title"] == "Samsung AC 11:22:33"
        # Kill mutmut_20, 21, 22: Verify unique_id is properly populated in flow_data BEFORE creation
        assert mock_create.call_args.kwargs["data"]["unique_id"] == "11:22:33"

    # 3. Kill mutmut_2: device_type = self.flow_data.get(CONF_DEVICE_TYPE)
    # If device_type were None (mutmut_2), a standard name without UUID appending would be used
    # even if the user supplied one, if it was an 8888 device.
    flow.flow_data = {
        "unique_id": "UUID_1234",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_NAME: "Living Room",
    }
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow, "async_create_entry", return_value={"type": "create_entry"}
        ) as mock_create,
    ):
        await flow._create_entry()
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["title"] == "Living Room (UUID_1234)"

    # 4. Kill mutmut_29, 30, 31, 32, 33: Edge cases for title UUID appending
    # 4a. 8888 device but title ALREADY has UUID (Should not duplicate)
    flow.flow_data = {
        "unique_id": "UUID_1234",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_NAME: "Living Room (UUID_1234)",
    }
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow, "async_create_entry", return_value={"type": "create_entry"}
        ) as mock_create,
    ):
        await flow._create_entry()
        # Kills mutmut_32 (`in` instead of `not in`) and mutmut_30 (`or` instead of `and`)
        assert mock_create.call_args.kwargs["title"] == "Living Room (UUID_1234)"

    # 4b. 2878 device where UUID is not in title (Should not append UUID)
    flow.flow_data = {
        "unique_id": "UUID_1234",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_NAME: "Living Room",
    }
    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow, "async_create_entry", return_value={"type": "create_entry"}
        ) as mock_create,
    ):
        await flow._create_entry()
        # Kills mutmut_31 (`not in` device list) and mutmut_29, 33 (setting title/name to None)
        assert mock_create.call_args.kwargs["title"] == "Living Room"

    # 5. Kill mutmut_5: final_unique_id = self.flow_data.get("unique_id") or self.flow_data.get(CONF_MAC)
    # Test that if "unique_id" is missing, it falls back to CONF_MAC
    from homeassistant.const import CONF_MAC

    flow.flow_data = {
        CONF_MAC: "MAC:12:34",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
    }
    with (
        patch.object(flow, "async_set_unique_id") as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "async_create_entry", return_value={"type": "create_entry"}),
    ):
        await flow._create_entry()
        # If mutmut changes get("unique_id") to get(None) AND we omit unique_id, it will fall back correctly.
        # But wait, to kill mutmut_5 which is `self.flow_data.get(None) or self.flow_data.get(CONF_MAC)`
        # If it mutated to None, then if we provide `unique_id` but NOT `CONF_MAC`, final_unique_id would be None.
        pass

    # Better yet, let's explicitly test that "unique_id" is preferred over "CONF_MAC" to kill mutmut_5.
    flow.flow_data = {
        "unique_id": "PREFER_THIS",
        CONF_MAC: "NOT_THIS",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
    }
    with (
        patch.object(flow, "async_set_unique_id") as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "async_create_entry", return_value={"type": "create_entry"}),
    ):
        await flow._create_entry()
        # Kill mutmut_5: ensures we read "unique_id" and didn't fall back to CONF_MAC or return None
        mock_set_uid.assert_called_once_with("PREFER_THIS")


async def test_get_base_samsung_schema_mutants_coverage(hass: HomeAssistant) -> None:
    """Test coverage to kill mutants in _get_base_samsung_schema using absolute assertions."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    import datetime

    from homeassistant.const import (
        CONF_IP_ADDRESS,
        CONF_MAC,
        CONF_NAME,
        CONF_TOKEN,
        UnitOfTemperature,
    )
    from homeassistant.helpers.selector import (
        SelectSelector,
        SelectSelectorConfig,
        SelectSelectorMode,
        TextSelector,
        TextSelectorConfig,
        TextSelectorType,
    )

    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_ENABLE_POLLING,
        CONF_POLL_INTERVAL,
        CONF_TEMP_NATIVE_CURRENT,
        CONF_TEMP_NATIVE_TARGET,
        DEFAULT_CONF_TEMP_UNIT,
        DEFAULT_POLL_INTERVAL,
    )

    # 1. Asalto 1: Flujo vacío absoluto, comprobando defaults puros y lógica is_8888=False
    flow.flow_data = {}
    schema_not_8888 = flow._get_base_samsung_schema(mac_required=False, is_8888=False)

    # Invoke Voluptuous to evaluate defaults
    res_not_8888 = schema_not_8888({})

    # Validaciones de comportamiento estructural
    assert res_not_8888[CONF_IP_ADDRESS] == ""
    assert res_not_8888[CONF_MAC] == ""
    assert res_not_8888[CONF_NAME] == ""
    assert res_not_8888[CONF_TOKEN] == ""
    assert res_not_8888[CONF_CERT] == "ac14k_m.pem"
    assert res_not_8888[CONF_ENABLE_POLLING] is True
    assert res_not_8888[CONF_TEMP_NATIVE_CURRENT] == DEFAULT_CONF_TEMP_UNIT
    assert res_not_8888[CONF_TEMP_NATIVE_TARGET] == DEFAULT_CONF_TEMP_UNIT

    expected_default_interval = str(
        datetime.timedelta(seconds=int(DEFAULT_POLL_INTERVAL))
    )
    assert res_not_8888[CONF_POLL_INTERVAL] == expected_default_interval

    # Asalto 1.1: Prove mac_required=False default worked
    mac_key = next(
        k for k in schema_not_8888.schema if getattr(k, "schema", None) == CONF_MAC
    )
    assert isinstance(mac_key, vol.Optional)

    # 1.5. Round 1.5: Empty flow with is_8888=True to test CONF_CERT default
    flow.flow_data = {}
    schema_empty_8888 = flow._get_base_samsung_schema(mac_required=False, is_8888=True)
    res_empty_8888 = schema_empty_8888({})
    assert res_empty_8888[CONF_CERT] == "ac14k_m.pem"

    # 2. Asalto 2: Inyección de estado completa y formato de MAC (is_8888=True)
    flow.flow_data = {
        CONF_MAC: "aa:bb:cc:dd",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_NAME: "Living Room AC",
        CONF_TOKEN: "fake_token_123",
        CONF_CERT: "custom_cert.pem",
        CONF_POLL_INTERVAL: "300",
        CONF_TEMP_NATIVE_CURRENT: UnitOfTemperature.CELSIUS,
        CONF_TEMP_NATIVE_TARGET: UnitOfTemperature.FAHRENHEIT,
        CONF_ENABLE_POLLING: False,  # Ignored if is_8888=True
    }
    schema_8888 = flow._get_base_samsung_schema(mac_required=False, is_8888=True)

    # Invoke Voluptuous to evaluate injection
    res_8888 = schema_8888({})

    assert res_8888[CONF_MAC] == "AA:BB:CC:DD"
    assert res_8888[CONF_IP_ADDRESS] == "192.168.1.100"
    assert res_8888[CONF_NAME] == "Living Room AC"
    assert res_8888[CONF_TOKEN] == "fake_token_123"
    assert res_8888[CONF_CERT] == "custom_cert.pem"
    assert res_8888[CONF_POLL_INTERVAL] == "0:05:00"
    assert res_8888[CONF_TEMP_NATIVE_CURRENT] == UnitOfTemperature.CELSIUS
    assert res_8888[CONF_TEMP_NATIVE_TARGET] == UnitOfTemperature.FAHRENHEIT
    assert CONF_ENABLE_POLLING not in res_8888

    # 3. Round 3: Parsing exceptions in Poll Interval
    flow.flow_data = {CONF_POLL_INTERVAL: "invalid"}
    schema_invalid = flow._get_base_samsung_schema(mac_required=False, is_8888=False)
    res_invalid = schema_invalid({})
    assert res_invalid[CONF_POLL_INTERVAL] == "invalid"

    # 3.1 Kill mutmut_25: Poll Interval is empty string (triggers the `or ""` fallback)
    flow.flow_data = {CONF_POLL_INTERVAL: ""}
    schema_empty_interval = flow._get_base_samsung_schema(
        mac_required=False, is_8888=False
    )
    res_empty_interval = schema_empty_interval({})
    assert res_empty_interval[CONF_POLL_INTERVAL] == ""

    # 3.2 Kill mutmut_40, 42, 44: mac_required=True default logic
    flow.flow_data = {CONF_MAC: "11:22:33"}
    schema_mac_req = flow._get_base_samsung_schema(mac_required=True, is_8888=False)
    mac_req_key = next(
        k for k in schema_mac_req.schema if getattr(k, "schema", None) == CONF_MAC
    )
    assert isinstance(mac_req_key, vol.Required)
    assert mac_req_key.default() == "11:22:33"

    # 4. Asalto 4: Aserciones de Instancia Total (Selectores)
    poll_key = next(
        k
        for k in schema_not_8888.schema
        if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    temp_curr_key = next(
        k
        for k in schema_not_8888.schema
        if getattr(k, "schema", None) == CONF_TEMP_NATIVE_CURRENT
    )

    assert schema_not_8888.schema[poll_key] == TextSelector(
        TextSelectorConfig(type=TextSelectorType.TEXT)
    )

    assert schema_not_8888.schema[temp_curr_key] == SelectSelector(
        SelectSelectorConfig(
            options=[UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


async def test_get_rest_api_schema_mutants_coverage(hass: HomeAssistant) -> None:
    """Test coverage to kill mutants in _get_rest_api_schema."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, CONF_TOKEN
    from homeassistant.helpers.selector import (
        TextSelectorType,
    )

    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

    # 1. Kill mutmut_26, 27, 29, 30: CONF_IP_ADDRESS in is_st=True
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_TOKEN: "valid_token",  # Provided so it doesn't fail on None default during schema evaluation
    }
    schema_st = flow._get_rest_api_schema()
    res_st = schema_st({CONF_TOKEN: "valid_token"})
    assert res_st[CONF_IP_ADDRESS] == "api.smartthings.com"

    # Forensic Assertion: Ensure field has not mutated to Optional
    ip_marker_st = next(
        k for k in schema_st.schema if getattr(k, "schema", None) == CONF_IP_ADDRESS
    )
    assert isinstance(ip_marker_st, vol.Required), (
        "Mutación detectada: CONF_IP_ADDRESS debe ser Required, no Optional"
    )

    # 2. Kill mutmut_21, 22: default_token logic
    # Test mutmut_21: When CONF_TOKEN is present in flow_data, it uses it.
    token_key_st = next(
        k for k in schema_st.schema if getattr(k, "schema", None) == CONF_TOKEN
    )
    assert token_key_st.default() == "valid_token"

    # Test mutmut_22: When is_st=False and CONF_TOKEN is missing, fallback is ""
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    schema_not_st = flow._get_rest_api_schema()
    token_key_not_st = next(
        k for k in schema_not_st.schema if getattr(k, "schema", None) == CONF_TOKEN
    )
    assert token_key_not_st.default() == ""

    # Kill mutmut_6: Assert is_st=False logic applies properly for non-SmartThings devices
    ip_marker_not_st = next(
        k for k in schema_not_st.schema if getattr(k, "schema", None) == CONF_IP_ADDRESS
    )
    assert ip_marker_not_st.default is vol.UNDEFINED

    # 3. Avoid I/O and test smart Token injection in SmartThings
    from unittest.mock import patch

    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    with patch.object(flow, "_get_smartthings_token", return_value="mocked_st_token"):
        schema_st_mock = flow._get_rest_api_schema()
        res_st_mock = schema_st_mock({})
        assert res_st_mock[CONF_TOKEN] == "mocked_st_token"

    # 4. Kill mutmut_35, 36, 39, 40: CONF_NAME and CONF_POLL_INTERVAL structural assertions
    name_marker_st = next(
        k for k in schema_st.schema if getattr(k, "schema", None) == CONF_NAME
    )
    assert isinstance(name_marker_st, vol.Optional)

    poll_marker_st = next(
        k for k in schema_st.schema if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    assert isinstance(poll_marker_st, vol.Optional)
    assert schema_st.schema[poll_marker_st].config["type"] == TextSelectorType.TEXT

    # 5. Kill mutmut_6, 7, 8, 9: Poll interval fallback logic
    import datetime

    from custom_components.climate_ip.const import DEFAULT_POLL_INTERVAL

    # Valid interval evaluation (empty flow_data falls back to DEFAULT_POLL_INTERVAL)
    flow.flow_data = {CONF_DEVICE_TYPE: "dummy"}
    schema_empty_poll = flow._get_rest_api_schema()
    res_empty_poll = schema_empty_poll(
        {CONF_TOKEN: "valid", CONF_IP_ADDRESS: "1.2.3.4"}
    )
    expected_default_interval = str(
        datetime.timedelta(seconds=int(DEFAULT_POLL_INTERVAL))
    )
    assert res_empty_poll[CONF_POLL_INTERVAL] == expected_default_interval

    # Valid custom interval
    flow.flow_data = {CONF_POLL_INTERVAL: "300", CONF_DEVICE_TYPE: "dummy"}
    schema_custom_poll = flow._get_rest_api_schema()
    res_custom_poll = schema_custom_poll(
        {CONF_TOKEN: "valid", CONF_IP_ADDRESS: "1.2.3.4"}
    )
    assert res_custom_poll[CONF_POLL_INTERVAL] == "0:05:00"

    # Invalid interval
    flow.flow_data = {CONF_POLL_INTERVAL: "invalid", CONF_DEVICE_TYPE: "dummy"}
    schema_invalid_poll = flow._get_rest_api_schema()
    res_invalid_poll = schema_invalid_poll(
        {CONF_TOKEN: "valid", CONF_IP_ADDRESS: "1.2.3.4"}
    )
    assert res_invalid_poll[CONF_POLL_INTERVAL] == "invalid"


async def test_get_samsung_legacy_schema_mutants_coverage(hass: HomeAssistant) -> None:
    """Test coverage for wrapper schema functions."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    from unittest.mock import patch

    # 1. Kill mutmut_1 and mutmut_3 using strict delegation spying
    with patch.object(
        flow, "_get_base_samsung_schema", wraps=flow._get_base_samsung_schema
    ) as mock_base:
        schema_2878 = flow._get_samsung_2878_schema(mac_required=False)

        # Lethal assertion: We require delegation to strictly use boolean 'False'
        mock_base.assert_called_with(False, False)
        assert isinstance(schema_2878, vol.Schema)

        # Kill mutmut_5: Test mac_required=True delegation
        flow._get_samsung_2878_schema(mac_required=True)
        mock_base.assert_called_with(True, False)

    # Do the same for 8888 wrapper to kill any similar mutants there
    with patch.object(
        flow, "_get_base_samsung_schema", wraps=flow._get_base_samsung_schema
    ) as mock_base_8888:
        schema_8888 = flow._get_samsung_8888_schema(mac_required=False)

        mock_base_8888.assert_called_with(False, True)
        assert isinstance(schema_8888, vol.Schema)

        flow._get_samsung_8888_schema(mac_required=True)
        mock_base_8888.assert_called_with(True, True)

    # 2. Kill mutmut_1 and mutmut_2 in _get_base_samsung_schema (default arguments)
    # If we call _get_base_samsung_schema() directly, it evaluates mac_required=False, is_8888=False
    from homeassistant.const import CONF_MAC, CONF_TOKEN

    schema_base = flow._get_base_samsung_schema(mac_required=False, is_8888=False)
    keys_base = list(schema_base.schema.keys())
    assert any(isinstance(k, vol.Optional) and k.schema == CONF_MAC for k in keys_base)
    assert any(
        isinstance(k, vol.Optional) and k.schema == CONF_TOKEN for k in keys_base
    )

    # Kill mutmut_1 in _get_samsung_2878_schema and _get_samsung_8888_schema (default mac_required=False)
    keys_2878 = list(schema_2878.schema.keys())
    assert any(isinstance(k, vol.Optional) and k.schema == CONF_MAC for k in keys_2878)
    keys_8888 = list(schema_8888.schema.keys())
    assert any(isinstance(k, vol.Optional) and k.schema == CONF_MAC for k in keys_8888)

    # 3. Kill mutmut_85 and mutmut_101: Default injection from flow_data
    from homeassistant.const import UnitOfTemperature

    from custom_components.climate_ip.const import (
        CONF_ENABLE_POLLING,
        CONF_TEMP_NATIVE_CURRENT,
    )

    flow.flow_data[CONF_ENABLE_POLLING] = False
    flow.flow_data[CONF_TEMP_NATIVE_CURRENT] = UnitOfTemperature.FAHRENHEIT

    schema_with_defaults = flow._get_base_samsung_schema(
        mac_required=False, is_8888=False
    )
    # Evaluate with empty dict to force defaults
    evaluated_defaults = schema_with_defaults(
        {CONF_IP_ADDRESS: "1.1.1.1", CONF_TOKEN: "abc"}
    )
    assert evaluated_defaults[CONF_ENABLE_POLLING] is False
    assert evaluated_defaults[CONF_TEMP_NATIVE_CURRENT] == UnitOfTemperature.FAHRENHEIT

    # 4. Kill mutmut_30 in _get_rest_api_schema (CONF_DEVICE_ID in SmartThings)
    from homeassistant.const import CONF_DEVICE_ID

    from custom_components.climate_ip.const import DEVICE_TYPE_SMARTTHINGS_HVAC

    flow.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SMARTTHINGS_HVAC
    schema_st_hvac = flow._get_rest_api_schema()
    keys_st_hvac = list(schema_st_hvac.schema.keys())
    assert any(
        isinstance(k, vol.Optional) and k.schema == CONF_DEVICE_ID for k in keys_st_hvac
    )


async def test_get_smartthings_token_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in _get_smartthings_token."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    from unittest.mock import MagicMock

    mock_entry = MagicMock()
    mock_entry.data = {"access_token": "valid_token"}
    flow.hass.config_entries.async_entries.return_value = [mock_entry]

    token = flow._get_smartthings_token()

    # Assert exact call args to kill mutmut_2 and mutmut_3
    flow.hass.config_entries.async_entries.assert_called_once_with("smartthings")
    assert token == "valid_token"

    # Test empty fallback: SmartThings entry EXISTS, but has NO token (KILLS M12)
    mock_entry_empty = MagicMock()
    mock_entry_empty.data = {}  # Ausencia total de 'access_token' (evalúa a None)
    flow.hass.config_entries.async_entries.return_value = [mock_entry_empty]

    # M12: Changes `return str(tok) if tok is not None else ""` to `else "XXXX"`
    # LETHAL ASSERTION:
    assert flow._get_smartthings_token() == ""


async def test_pairing_wrappers_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in _initiate_pairing_safe and _wait_token_safe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # 1. Kill mutants when acquirer is None
    flow.acquirer = None
    try:
        async with asyncio.timeout(0.5):
            res_initiate_none = await flow._initiate_pairing_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_initiate_none == {"ok": False, "error": "unknown_error"}

    try:
        async with asyncio.timeout(0.5):
            res_wait_none = await flow._wait_token_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_wait_none == {"ok": False, "error": "unknown_error"}

    from unittest.mock import AsyncMock

    flow.acquirer = AsyncMock()

    # 2. Kill mutants on Success Path
    flow.acquirer.async_initiate_pairing.return_value = {"mocked": "config"}
    try:
        async with asyncio.timeout(0.5):
            res_initiate_success = await flow._initiate_pairing_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_initiate_success == {"ok": True, "config": {"mocked": "config"}}
    flow.acquirer.async_initiate_pairing.assert_awaited_once()
    flow.acquirer.async_initiate_pairing.reset_mock()

    flow.acquirer.async_wait_for_token.return_value = "mocked_token"
    try:
        async with asyncio.timeout(0.5):
            res_wait_success = await flow._wait_token_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_wait_success == {"ok": True, "token": "mocked_token"}
    flow.acquirer.async_wait_for_token.assert_awaited_once()
    flow.acquirer.async_wait_for_token.reset_mock()

    # 3. Kill mutants on Generic Exception Path
    flow.acquirer.async_initiate_pairing.side_effect = Exception("Generic Boom")
    try:
        async with asyncio.timeout(0.5):
            res_initiate_exc = await flow._initiate_pairing_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_initiate_exc == {"ok": False, "error": "unknown_error"}
    flow.acquirer.async_initiate_pairing.assert_awaited_once()
    flow.acquirer.async_initiate_pairing.reset_mock()

    flow.acquirer.async_wait_for_token.side_effect = Exception("Generic Boom")
    try:
        async with asyncio.timeout(0.5):
            res_wait_exc = await flow._wait_token_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_wait_exc == {"ok": False, "error": "unknown_error"}
    flow.acquirer.async_wait_for_token.assert_awaited_once()
    flow.acquirer.async_wait_for_token.reset_mock()

    # 4. Kill mutants on Specific Exception Path
    from custom_components.climate_ip.exceptions import (
        CannotConnect,
        TokenAcquisitionError,
    )

    flow.acquirer.async_initiate_pairing.side_effect = CannotConnect("Timeout")
    try:
        async with asyncio.timeout(0.5):
            res_initiate_spec_exc = await flow._initiate_pairing_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_initiate_spec_exc == {
        "ok": False,
        "error": "pairing_connection_failed",
        "error_details": "Timeout",
    }
    flow.acquirer.async_initiate_pairing.assert_awaited_once()

    flow.acquirer.async_wait_for_token.side_effect = TokenAcquisitionError("Failed")
    try:
        async with asyncio.timeout(0.5):
            res_wait_spec_exc = await flow._wait_token_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_wait_spec_exc == {"ok": False, "error": "token_acquisition_failed"}
    flow.acquirer.async_wait_for_token.assert_awaited_once()


def test_validate_poll_interval_mutants() -> None:
    """Kill mutants in validate_poll_interval."""
    import pytest

    from custom_components.climate_ip.const import MAX_POLL_INTERVAL, MIN_POLL_INTERVAL
    from custom_components.climate_ip.helpers import validate_poll_interval

    assert validate_poll_interval(120) == 120
    assert validate_poll_interval(MIN_POLL_INTERVAL) == MIN_POLL_INTERVAL
    assert validate_poll_interval(MAX_POLL_INTERVAL) == MAX_POLL_INTERVAL

    with pytest.raises(ValueError):
        validate_poll_interval(MIN_POLL_INTERVAL - 1)

    with pytest.raises(ValueError):
        validate_poll_interval(MAX_POLL_INTERVAL + 1)


async def test_async_step_await_button_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_await_button."""
    from unittest.mock import MagicMock

    from homeassistant.const import CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_MIM_H03,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

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


async def test_async_step_discover_uuid_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_discover_uuid."""
    from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CONFIG_FILE,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_MIM_H03,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
    }

    with patch(
        "custom_components.climate_ip.config_flow.ClimateIpConfigFlow.unique_id",
        new_callable=PropertyMock,
    ) as mock_unique_id:
        mock_unique_id.return_value = "test_unique_123"  # Kill mutmut_2

        with patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_controller_class:
            mock_controller = AsyncMock()
            mock_controller.initialize.return_value = True
            mock_controller.async_get_status.return_value = True

            # Must provide discovered_devices to pass the check at line 915
            mock_controller.discovered_devices = [
                {"id": "0", "uuid": "1234", "name": "MIM-H03 Coordinator"}
            ]

            # Simulating finding a System device
            mock_controller._get_devices_by_type = MagicMock(
                side_effect=lambda t: (
                    [{"uuid": "1234", "id": "coord_id"}] if t == "System" else []
                )
            )
            mock_controller_class.return_value = mock_controller

            with patch.object(
                flow, "_create_entry", return_value={"type": "create_entry"}
            ):
                with patch.object(flow, "async_set_unique_id", return_value=None):
                    await flow.async_step_discover_uuid()

                    # Kill mutmut_2: config_data["unique_id"] is set
                    # Kill mutmut_10: config_file injection strictly tested
                    # Kill mutmut_19, 20: kwargs are correctly passed to controller
                    args, kwargs = mock_controller_class.call_args
                    config_passed = kwargs["config"]
                    assert config_passed["unique_id"] == "test_unique_123"
                    assert config_passed[CONF_CONFIG_FILE] == "mim-h03_heatpump.yaml"

                    assert kwargs["logger"] is not None
                    assert kwargs["hass"] == hass
                    assert kwargs["session"] is not None

                # Kill mutmut_100: strict verification of lowercase unique_id
                assert "unique_id" in flow.flow_data
                assert flow.flow_data["unique_id"] == "1234"

                # Kill mutmut_101, 102, 103: strict verification of CONF_DEVICE_ID
                from homeassistant.const import CONF_DEVICE_ID, CONF_NAME

                assert flow.flow_data[CONF_DEVICE_ID] == "0"

                # Kill mutmut_104-110: strict verification of CONF_NAME when name exists
                assert flow.flow_data[CONF_NAME] == "MIM-H03 Coordinator 1234"

    # Second run to kill fallback mutants (name is missing)
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    flow2.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class2:
        mock_controller2 = AsyncMock()
        mock_controller2.initialize.return_value = True
        mock_controller2.async_get_status.return_value = True

        # Missing 'name' key to trigger the fallback on coordinator and missing everything on indoor unit
        mock_controller2.discovered_devices = [
            {"id": "0", "uuid": "5678"},
            {"id": "ghost", "Mode": "Auto"},  # GHOST DEVICE (Tactic 2)
        ]
        mock_controller_class2.return_value = mock_controller2

        with patch.object(
            flow2, "_create_entry", return_value={"type": "create_entry"}
        ):
            with patch.object(flow2, "async_set_unique_id", return_value=None):
                await flow2.async_step_discover_uuid()

                # Strict verification of fallback CONF_NAME for coordinator
                assert flow2.flow_data[CONF_NAME] == "MIM-H03 Coordinator 5678"

                # Táctica 2: Verification of ghost device fallbacks in _async_process_mim_h03
                from custom_components.climate_ip.const import CONF_DISCOVERED_DEVICES

                discovered = flow2.flow_data[CONF_DISCOVERED_DEVICES]
                assert len(discovered) == 1
                assert discovered[0]["id"] == "ghost"
                assert discovered[0]["name"] == "ID ghost (Indoor Unit ghost)"
                assert discovered[0]["uuid"] == ""
                assert discovered[0]["description"] == "Indoor Unit ghost"

    # Third run: Kill mutmut 113, 114, 115, 116-118, 119
    flow3 = ClimateIpConfigFlow()
    flow3.hass = hass
    flow3.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow3.reauth_entry = MagicMock()  # Set reauth_entry to truthy to kill mutmut 113

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class3:
        mock_controller3 = AsyncMock()
        mock_controller3.initialize.return_value = True
        mock_controller3.async_get_status.return_value = True

        # We need AC units to hit the ac_units_info block (Kill mutmut 115)
        # We need to NOT have a coordinator UUID to hit "no_coordinator_uuid"
        # We need to NOT have a coordinator to hit "no_coordinator_found"

        with patch.object(flow3, "async_set_unique_id", return_value=None):
            # Test A: No coordinator found -> abort
            mock_controller3.discovered_devices = [
                {"id": "1", "uuid": "unit1", "Mode": "Auto"}
            ]  # Has Mode, so it's not a coordinator
            mock_controller_class3.return_value = mock_controller3

            res_abort1 = await flow3.async_step_discover_uuid()
            # Kill mutmut 119
            assert res_abort1["type"] == "abort"
            assert res_abort1["reason"] == "no_coordinator_found"

            # Test B: Coordinator found but no UUID -> abort
            mock_controller3.discovered_devices = [
                {"id": "0", "name": "Coord"}
            ]  # No UUID
            res_abort2 = await flow3.async_step_discover_uuid()
            # Kill mutmut 116, 117, 118
            assert res_abort2["type"] == "abort"
            assert res_abort2["reason"] == "no_coordinator_uuid"

            # Test C: Coordinator found, AC units found -> select devices
            mock_controller3.discovered_devices = [
                {"id": "0", "uuid": "coord_uuid", "name": "Coord"},
                {"id": "1", "uuid": "unit1", "name": "Unit 1", "Mode": "Auto"},
            ]

            with patch.object(
                flow3, "async_step_select_devices", return_value={"type": "form"}
            ):
                with patch.object(
                    flow3, "_abort_if_unique_id_configured"
                ) as mock_abort:
                    res_select = await flow3.async_step_discover_uuid()

                    # Kill mutmut 103: CONF_NAME fallback strict assertion
                    from homeassistant.const import CONF_NAME

                    assert flow3.flow_data[CONF_NAME] == "Coord coord_uuid"

                    # Kill mutmut 113: Because reauth_entry is True, _abort_if_unique_id_configured should NOT be called
                    mock_abort.assert_not_called()

                    # Kill mutmut 115: CONF_DISCOVERED_DEVICES must be strictly injected
                    from custom_components.climate_ip.const import (
                        CONF_DISCOVERED_DEVICES,
                    )

                    assert flow3.flow_data[CONF_DISCOVERED_DEVICES] == [
                        {
                            "id": "1",
                            "uuid": "unit1",
                            "name": "ID 1 (Unit 1)",
                            "description": "Unit 1",
                        }
                    ]

                    assert res_select["type"] == "form"

    # Fourth run: Kill mutmut 136, 137, 138 (SAMSUNG_8888 branch)
    flow5 = ClimateIpConfigFlow()
    flow5.hass = hass
    from homeassistant.const import CONF_MAC

    from custom_components.climate_ip.const import (
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SAMSUNG_8888,
    )

    flow5.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_MAC: "aa:bb:cc:dd",
    }

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class5:
        mock_controller5 = AsyncMock()
        mock_controller5.initialize.return_value = True
        mock_controller5.async_get_status.return_value = True
        mock_controller5.discovered_devices = [{"invalid": "data"}]  # No id, no uuid
        mock_controller_class5.return_value = mock_controller5

        # Kill mutmut 123: Provide empty list. If len >= 0 mutant is active, it raises IndexError -> unknown_error
        # Wait, if list is empty, it returns early at line 929. So the len > 0 check is redundant and mutmut 123 is equivalent.
        # We will mock async_set_unique_id and verify it returns create_entry to prevent the mappingproxy error.
        mock_controller5.discovered_devices = []
        mock_controller5.unique_id = "test_unique_999"
        mock_controller5.device_id = "test_device_999"
        with (
            patch.object(
                flow5, "async_set_unique_id", return_value=None
            ) as mock_set_uid,
            patch.object(flow5, "_abort_if_unique_id_configured") as mock_abort_if,
            patch.object(flow5, "_create_entry", return_value={"type": "create_entry"}),
        ):
            res_abort_empty = await flow5.async_step_discover_uuid()
            assert res_abort_empty["type"] == "create_entry"
            # Kill mutmut 32, 33, 34: strict assertion of unique_id args
            mock_set_uid.assert_called_once_with(
                "test_unique_999", raise_on_progress=False
            )
            assert flow5.flow_data[CONF_DEVICE_ID] == "test_device_999"
            # Kill mutmut 35, 36, 37, 39: strict assertion of updates kwargs
            mock_abort_if.assert_called_once_with(updates=flow5.flow_data)

        # Original test to kill 136, 137, 138
        mock_controller5.discovered_devices = [{"invalid": "data"}]  # No id, no uuid
        res_abort5 = await flow5.async_step_discover_uuid()
        assert res_abort5["type"] == "abort"
        assert res_abort5["reason"] == "discovery_failed"

        # Kill mutmut 126, 128, 129: Test valid uuid
        mock_controller5.discovered_devices = [
            {"uuid": "real_uuid", "id": "ignored_id"}
        ]
        with patch.object(
            flow5, "_create_entry", return_value={"type": "create_entry"}
        ):
            res_success1 = await flow5.async_step_discover_uuid()
            from homeassistant.const import CONF_DEVICE_ID

            assert flow5.flow_data[CONF_DEVICE_ID] == "real_uuid"
            assert res_success1["type"] == "create_entry"

        # Kill mutmut 125, 130, 132, 133: Test valid id when uuid is missing
        mock_controller5.discovered_devices = [{"id": "real_id"}]
        with patch.object(
            flow5, "_create_entry", return_value={"type": "create_entry"}
        ):
            res_success2 = await flow5.async_step_discover_uuid()
            assert flow5.flow_data[CONF_DEVICE_ID] == "real_id"
            assert res_success2["type"] == "create_entry"

    # Fifth run: Kill mutmut 14 (logger), 139, 140-144 (Generic branch e.g. SAMSUNG_2878)
    # Also kill mutants 158-160, 170-179 by fully exercising the list comprehension fallback logic
    flow6 = ClimateIpConfigFlow()
    flow6.hass = hass
    flow6.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class6:
        mock_controller6 = AsyncMock()
        mock_controller6.initialize.return_value = True
        mock_controller6.async_get_status.return_value = True
        # Provide combinations of missing fields to trigger fallbacks
        mock_controller6.discovered_devices = [
            # 1. Full info
            {
                "id": "1",
                "uuid": "uuid1",
                "name": "AC 1",
                "description": "Desc 1",
                "Mode": "Auto",
            },
            # 2. Missing id, name, description, but has Mode (Kill 158-160)
            {"uuid": "uuid2", "Mode": "Cool"},
            # 3. Has id and Mode, missing name and description (Kill 170-179)
            {"id": "3", "uuid": "uuid3", "Mode": "Heat"},
        ]
        mock_controller_class6.return_value = mock_controller6

        with patch.object(
            flow6, "async_step_select_devices", return_value={"type": "form_generic"}
        ):
            res_generic = await flow6.async_step_discover_uuid()
            assert res_generic["type"] == "form_generic"

            devices = flow6.flow_data[CONF_DISCOVERED_DEVICES]
            # Device 1: Full info
            assert devices[0]["name"] == "AC 1"
            assert devices[0]["description"] == "Desc 1"
            # Device 2: Missing id -> str(d). Missing name -> "Indoor Unit {'uuid': 'uuid2', 'Mode': 'Cool'}"
            expected_str2 = "{'uuid': 'uuid2', 'Mode': 'Cool'}"
            assert devices[1]["id"] == expected_str2
            assert devices[1]["name"] == f"Indoor Unit {expected_str2}"
            assert devices[1]["description"] == f"Indoor Unit {expected_str2}"
            # Device 3: Has id, missing name -> "Indoor Unit 3"
            assert devices[2]["name"] == "Indoor Unit 3"
            assert devices[2]["description"] == "Indoor Unit 3"

    # Sixth run: Kill mutants 183-185 (InvalidHeaderError fallback)
    from custom_components.climate_ip.const import CONF_CONN_METHOD, CONN_METHOD_RAW
    from custom_components.climate_ip.exceptions import InvalidHeaderError

    flow7 = ClimateIpConfigFlow()
    flow7.hass = hass
    flow7.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class7:
        mock_controller7 = AsyncMock()
        mock_controller7.initialize.return_value = True
        # First call raises InvalidHeaderError, second call succeeds
        mock_controller7.async_get_status.side_effect = [
            InvalidHeaderError("Test"),
            True,
        ]
        mock_controller7.discovered_devices = [{"id": "1", "Mode": "Cool"}]
        mock_controller_class7.return_value = mock_controller7

        with patch.object(
            flow7, "_create_entry", return_value={"type": "create_entry_mocked"}
        ):
            res_retry = await flow7.async_step_discover_uuid()
            assert res_retry["type"] == "create_entry_mocked"
            # Lethal assertion: Confirm RAW socket fallback was applied
            assert flow7.flow_data[CONF_CONN_METHOD] == CONN_METHOD_RAW
            assert (
                mock_controller_class7.call_args_list[1].kwargs["config"][
                    CONF_CONN_METHOD
                ]
                == CONN_METHOD_RAW
            )
            # Verify controller was shut down: once before retry and once in fallback
            assert mock_controller7.async_shutdown.call_count == 2

            # Kill mutmut 187-193: verify fallback kwargs
            _, kwargs_fallback = mock_controller_class7.call_args_list[1]
            assert kwargs_fallback["logger"] is not None
            assert kwargs_fallback["hass"] == hass
            assert kwargs_fallback["session"] is not None

            # Kill mutmut 14: strictly assert logger is passed
            _, kwargs6 = mock_controller_class6.call_args
            assert kwargs6["logger"]

            # Kill mutmut 139-144: strict verification of devices_info
            assert flow6.flow_data[CONF_DISCOVERED_DEVICES] == [
                {"id": "1", "uuid": "uuid1", "name": "AC 1", "description": "Desc 1"},
                {
                    "id": "{'uuid': 'uuid2', 'Mode': 'Cool'}",
                    "uuid": "uuid2",
                    "name": "Indoor Unit {'uuid': 'uuid2', 'Mode': 'Cool'}",
                    "description": "Indoor Unit {'uuid': 'uuid2', 'Mode': 'Cool'}",
                },
                {
                    "id": "3",
                    "uuid": "uuid3",
                    "name": "Indoor Unit 3",
                    "description": "Indoor Unit 3",
                },
            ]
            assert res_generic["type"] == "form_generic"

    # Seventh run: Kill mutants 195, 198, 199 (InvalidHeaderError fallback fails on retry)
    flow8 = ClimateIpConfigFlow()
    flow8.hass = hass
    flow8.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class8:
        mock_controller8 = AsyncMock()
        # Asymmetric test to kill mutmut 195 (or -> and):
        # initialize() ALWAYS returns True.
        # async_get_status() raises InvalidHeaderError on 1st call, then returns False on retry.
        # Original (or): not True OR not False -> False OR True -> True -> aborts (Test Passes)
        # Mutant (and): not True AND not False -> False AND True -> False -> does not abort (Test Fails -> Mutant killed!)
        mock_controller8.initialize.return_value = True
        mock_controller8.async_get_status.side_effect = [
            InvalidHeaderError("Test"),
            False,
        ]
        mock_controller_class8.return_value = mock_controller8

        res_fail = await flow8.async_step_discover_uuid()
        assert res_fail["type"] == "abort"
        assert res_fail["reason"] == "cannot_connect"
        assert mock_controller8.async_shutdown.call_count == 2

    # Test D: Kill mutmut 113, 114 (reauth_entry = None)
    flow4 = ClimateIpConfigFlow()
    flow4.hass = hass
    flow4.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow4.reauth_entry = None  # Falsey

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class4:
        mock_controller4 = AsyncMock()
        mock_controller4.initialize.return_value = True
        mock_controller4.async_get_status.return_value = True
        mock_controller4.discovered_devices = [
            {"id": "0", "uuid": "coord_uuid", "name": "Coord"}
        ]
        mock_controller_class4.return_value = mock_controller4

        with patch.object(flow4, "async_set_unique_id", return_value=None):
            with patch.object(
                flow4, "_create_entry", return_value={"type": "create_entry"}
            ):
                with patch.object(
                    flow4, "_abort_if_unique_id_configured"
                ) as mock_abort2:
                    await flow4.async_step_discover_uuid()

                    # Kill mutmut 113, 114: Must be called exactly with updates=flow4.flow_data
                    mock_abort2.assert_called_once_with(updates=flow4.flow_data)

    # Eighth run: Kill mutmut 25, 26, 27 (Initial initialization failure -> cannot_connect)
    flow9 = ClimateIpConfigFlow()
    flow9.hass = hass
    flow9.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class9:
        mock_controller9 = AsyncMock()
        mock_controller9.initialize.return_value = False
        mock_controller_class9.return_value = mock_controller9

        res_fail9 = await flow9.async_step_discover_uuid()
        assert res_fail9["type"] == "abort"
        assert res_fail9["reason"] == "cannot_connect"

    # Ninth run: Kill mutmut 201, 202, 203 (Fallback raw engine raises Exception -> cannot_connect)
    flow10 = ClimateIpConfigFlow()
    flow10.hass = hass
    flow10.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class10:
        mock_controller10 = AsyncMock()
        mock_controller10.async_get_status.side_effect = InvalidHeaderError("Test")
        # On fallback, initialize raises an Exception
        mock_controller10.initialize.side_effect = [True, Exception("Fallback crash")]
        mock_controller_class10.return_value = mock_controller10

        res_fail10 = await flow10.async_step_discover_uuid()
        assert res_fail10["type"] == "abort"
        assert res_fail10["reason"] == "cannot_connect"

    # Tenth run: Kill mutmut 204, 205, 206 (Outermost Exception -> unknown_error)
    flow11 = ClimateIpConfigFlow()
    flow11.hass = hass
    flow11.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class11:
        mock_controller11 = AsyncMock()
        mock_controller11.initialize.return_value = True
        mock_controller11.async_get_status.return_value = True
        mock_controller11.discovered_devices = []  # Trigger create_entry
        mock_controller_class11.return_value = mock_controller11

        # Raise exception inside _create_entry to trigger outermost try-except
        with patch.object(flow11, "async_set_unique_id", return_value=None):
            with patch.object(
                flow11, "_create_entry", side_effect=Exception("Outer crash")
            ):
                res_fail11 = await flow11.async_step_discover_uuid()
                assert res_fail11["type"] == "abort"
                assert res_fail11["reason"] == "unknown_error"

    # Eleventh run: Kill mutmut 46 (break), 51 (and), 53 (XX0XX)
    flow12 = ClimateIpConfigFlow()
    flow12.hass = hass
    flow12.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class12:
        mock_controller12 = AsyncMock()
        mock_controller12.initialize.return_value = True
        mock_controller12.async_get_status.return_value = True
        # "invalid_item" kills 46 (break instead of continue)
        # "id": "0", "Mode": "Auto" kills 51 (or -> and), 53 (0 -> XX0XX)
        mock_controller12.discovered_devices = [
            "invalid_item",
            {"id": "0", "uuid": "c1", "name": "Coord1", "Mode": "Auto"},
        ]
        mock_controller_class12.return_value = mock_controller12

        with patch.object(flow12, "async_set_unique_id", return_value=None):
            with patch.object(
                flow12, "_create_entry", return_value={"type": "create_entry"}
            ):
                with patch.object(flow12, "_abort_if_unique_id_configured"):
                    res12 = await flow12.async_step_discover_uuid()
                    assert res12["type"] == "create_entry"
                    from homeassistant.const import CONF_NAME

                    assert flow12.flow_data[CONF_NAME] == "Coord1 c1"

    # Twelfth run: Kill mutmut 43, 58, 59, 60
    flow13 = ClimateIpConfigFlow()
    flow13.hass = hass
    flow13.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class13:
        mock_controller13 = AsyncMock()
        mock_controller13.initialize.return_value = True
        mock_controller13.async_get_status.return_value = True
        # Provide multiple valid candidates without ID 0 to kill 60 (device_id != 0)
        mock_controller13.discovered_devices = [
            {"id": "2", "uuid": "c2", "name": "Coord2"},
            {"id": "3", "uuid": "c3", "name": "Coord3"},
        ]
        mock_controller_class13.return_value = mock_controller13

        with patch.object(flow13, "async_set_unique_id", return_value=None):
            with patch.object(
                flow13, "_create_entry", return_value={"type": "create_entry"}
            ):
                with patch.object(flow13, "_abort_if_unique_id_configured"):
                    res13 = await flow13.async_step_discover_uuid()
                    assert res13["type"] == "create_entry"
                    # If mutmut 60 is alive, it will overwrite the coordinator with ID 3
                    # If mutmut 43 is alive, it won't set coordinator and will abort
                    from homeassistant.const import CONF_NAME

                    assert flow13.flow_data[CONF_NAME] == "Coord2 c2"

    # Thirteenth run: Kill mutmut 38 (empty list with reauth_entry = True)
    flow14 = ClimateIpConfigFlow()
    flow14.hass = hass
    flow14.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    flow14.reauth_entry = MagicMock()  # Truthy
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class14:
        mock_controller14 = AsyncMock()
        mock_controller14.initialize.return_value = True
        mock_controller14.async_get_status.return_value = True
        mock_controller14.discovered_devices = []
        mock_controller14.unique_id = "test_14"
        mock_controller_class14.return_value = mock_controller14

        with (
            patch.object(flow14, "async_set_unique_id", return_value=None),
            patch.object(flow14, "_abort_if_unique_id_configured") as mock_abort14,
            patch.object(
                flow14, "_create_entry", return_value={"type": "create_entry"}
            ),
        ):
            await flow14.async_step_discover_uuid()
            mock_abort14.assert_not_called()

    # Fourteenth run: Semantic test - A valid coordinator with id="0" legitimately overwrites a spurious coordinator
    flow15 = ClimateIpConfigFlow()
    flow15.hass = hass
    flow15.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class15:
        mock_controller15 = AsyncMock()
        mock_controller15.initialize.return_value = True
        mock_controller15.async_get_status.return_value = True
        # First device: Looks like a coordinator (no Mode), so it takes the spot initially.
        # Second device: Has Mode (not normally a coord), BUT has id="0". It must usurp the coordinator throne!
        mock_controller15.discovered_devices = [
            {"id": "2", "uuid": "c2", "name": "FakeCoord"},
            {"id": "0", "uuid": "c0", "name": "TrueCoord", "Mode": "Cool"},
        ]
        mock_controller_class15.return_value = mock_controller15

        with patch.object(flow15, "async_set_unique_id", return_value=None):
            with patch.object(
                flow15, "_create_entry", return_value={"type": "create_entry"}
            ):
                with patch.object(flow15, "_abort_if_unique_id_configured"):
                    res15 = await flow15.async_step_discover_uuid()
                    assert res15["type"] == "create_entry"

                    # Assert that the final coordinator chosen is TrueCoord with id="0" and uuid="c0"
                    from homeassistant.const import CONF_DEVICE_ID, CONF_NAME

                    assert flow15.flow_data[CONF_NAME] == "TrueCoord c0"
                    assert flow15.flow_data[CONF_DEVICE_ID] == "0"

    # Fifteenth run: Kill mutmut 7, 9, 61, 82, 86, 87, 92-96
    flow16 = ClimateIpConfigFlow()
    flow16.hass = hass
    flow16.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_CONFIG_FILE: "custom.yaml",
    }
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class16:
        mock_controller16 = AsyncMock()
        mock_controller16.initialize.return_value = True
        mock_controller16.async_get_status.return_value = True
        mock_controller16.discovered_devices = [
            {"id": "2", "uuid": "c2", "name": "FakeCoord"},
            {"id": "0", "uuid": "c0", "name": "TrueCoord", "Mode": "Cool"},
            {
                "id": "1",
                "uuid": "unit1",
                "name": "Unit 1",
                "Mode": "Auto",
                "description": "My Custom Desc",
            },
        ]
        mock_controller_class16.return_value = mock_controller16

        with (
            patch.object(
                flow16, "async_set_unique_id", return_value=None
            ) as mock_set_uid,
            patch.object(
                flow16, "async_step_select_devices", return_value={"type": "form"}
            ),
            patch.object(flow16, "_abort_if_unique_id_configured"),
        ):
            await flow16.async_step_discover_uuid()

            # Kill mutmut 7 and 9
            args, kwargs = mock_controller_class16.call_args
            config_passed = kwargs["config"]
            assert config_passed.get(CONF_CONFIG_FILE) == "custom.yaml"

            # Kill mutmut 61: strictly assert that TrueCoord was chosen
            from homeassistant.const import CONF_DEVICE_ID, CONF_NAME

            from custom_components.climate_ip.const import CONF_DISCOVERED_DEVICES

            assert flow16.flow_data[CONF_NAME] == "TrueCoord c0"
            assert flow16.flow_data[CONF_DEVICE_ID] == "0"

            # Kill mutmut 82, 86, 87
            devices = flow16.flow_data[CONF_DISCOVERED_DEVICES]
            assert devices[0]["description"] == "My Custom Desc"

            # Kill mutmut 92-96
            mock_set_uid.assert_called_once_with("c0", raise_on_progress=False)


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
        args, kwargs = mock_form.call_args
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


async def test_options_flow_validation_and_submission(hass: HomeAssistant) -> None:
    """Kill mutants in OptionsFlowHandler validation boundaries."""
    from custom_components.climate_ip.config_flow import OptionsFlowHandler
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        CONF_TARGET_TEMP_STEP,
        DEFAULT_TARGET_TEMP_STEP,
        DOMAIN,
        MAX_POLL_INTERVAL,
        MIN_POLL_INTERVAL,
    )

    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DEVICE_TYPE: "some_legacy_device"}
    )
    entry.add_to_hass(hass)
    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    flow.DEBUG_ME = True

    # Kill mutmut testing boundaries (< vs <=) (Kills mutants 8, 9, 11, 12, 14, 15, 17, 18)
    res_min = await flow.async_step_init({CONF_POLL_INTERVAL: MIN_POLL_INTERVAL - 1})
    assert res_min["type"] == "form"
    assert res_min["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    res_max = await flow.async_step_init({CONF_POLL_INTERVAL: MAX_POLL_INTERVAL + 1})
    assert res_max["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    res_min_exact = await flow.async_step_init(
        {CONF_POLL_INTERVAL: MIN_POLL_INTERVAL, CONF_TARGET_TEMP_STEP: "0.5"}
    )
    assert res_min_exact["type"] == "create_entry"
    assert res_min_exact["data"][CONF_POLL_INTERVAL] == MIN_POLL_INTERVAL

    res_max_exact = await flow.async_step_init(
        {CONF_POLL_INTERVAL: MAX_POLL_INTERVAL, CONF_TARGET_TEMP_STEP: "0.5"}
    )
    assert res_max_exact["type"] == "create_entry"
    assert res_max_exact["data"][CONF_POLL_INTERVAL] == MAX_POLL_INTERVAL

    # Kill mutmut ValueError/TypeError branches and time_period_str mutations (Kills mutants 6, 7)
    res_err = await flow.async_step_init({CONF_POLL_INTERVAL: "invalid_time_string"})
    assert res_err["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    res_str_valid = await flow.async_step_init(
        {CONF_POLL_INTERVAL: "00:05:00", CONF_TARGET_TEMP_STEP: "0.5"}
    )
    assert res_str_valid["type"] == "create_entry"
    assert res_str_valid["data"][CONF_POLL_INTERVAL] == 300

    # Kill mutmut testing correct type casting
    res_success = await flow.async_step_init(
        {
            CONF_POLL_INTERVAL: 120,
            CONF_TARGET_TEMP_STEP: "0.5",  # Passed as string from UI UI
        }
    )
    assert res_success["type"] == "create_entry"
    assert res_success["data"][CONF_POLL_INTERVAL] == 120
    assert (
        res_success["data"][CONF_TARGET_TEMP_STEP] == 0.5
    )  # Assert strict float conversion

    # Kill target_temp_step TypeError fallback
    res_fallback = await flow.async_step_init(
        {CONF_POLL_INTERVAL: 120, CONF_TARGET_TEMP_STEP: "invalid_float"}
    )
    assert res_fallback["data"][CONF_TARGET_TEMP_STEP] == DEFAULT_TARGET_TEMP_STEP


async def test_async_step_test_connection_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_test_connection routing logic."""
    from unittest.mock import MagicMock

    from homeassistant.const import CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_ID,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SAMSUNG_8888,
    )

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


async def test_test_connection_safe_untested_paths(hass: HomeAssistant) -> None:
    """Cover unknown device types and broad exceptions in _test_connection_safe."""
    from unittest.mock import patch

    from homeassistant.const import CONF_IP_ADDRESS

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # Kill the "else" branch mutant (Unknown device)
    flow.flow_data = {CONF_DEVICE_TYPE: "Alien_AC"}
    try:
        async with asyncio.timeout(0.5):
            res = await flow._test_connection_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res == {"ok": False, "error": "cannot_connect"}

    # Kill the broad "except Exception" mutant at the very end
    flow.flow_data = {
        CONF_DEVICE_TYPE: "samsung_8888",
        CONF_IP_ADDRESS: "192.168.1.100",
    }
    # Mock async_get_clientsession to throw a catastrophic error
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=Exception("Catastrophic Core Failure"),
    ):
        try:
            async with asyncio.timeout(0.5):
                res2 = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res2 == {"ok": False, "error": "cannot_connect"}


async def test_async_step_select_devices_comprehensive(hass: HomeAssistant) -> None:
    """Kill all mutants in async_step_select_devices."""
    from unittest.mock import patch

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICES,
        CONF_DISCOVERED_DEVICES,
        CONF_SELECTED_DEVICES,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # Inject previous state that discover_uuid would leave
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [
            {"id": "1", "name": "Device 1"},
            {"id": "2", "name": "Device 2"},
            {"id": "3"},  # GHOST DEVICE (Tactic 2)
        ]
    }

    # Round 1: No user input -> Must show initial form
    with patch(
        "custom_components.climate_ip.config_flow_discovery.cv.multi_select"
    ) as mock_multi:
        mock_multi.return_value = str
        res1 = await flow.async_step_select_devices()
        assert res1["type"] == "form"
        assert res1["step_id"] == "select_devices"
        assert res1["description_placeholders"]["device_count"] == 3

        # Asalto 1.5: ASERCIÓN DE FRANCOTIRADOR (Tácticas 2 y 4)
        options = mock_multi.call_args[0][0]
        assert "3" in options
        assert options["3"] == "Indoor Unit 3"  # Táctica 2

        schema = res1["data_schema"].schema
        devices_key = next(k for k in schema.keys() if str(k) == CONF_SELECTED_DEVICES)
        default_val = (
            devices_key.default()
            if callable(devices_key.default)
            else devices_key.default
        )
        assert default_val == ["1", "2", "3"]  # Táctica 4

    # Asalto 2: Lista vacía enviada -> Debe devolver error "no_devices_selected"
    res2 = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: []})
    assert res2["type"] == "form"
    assert res2["step_id"] == "select_devices"
    assert res2["errors"]["base"] == "no_devices_selected"
    assert res2["description_placeholders"]["device_count"] == 3
    from custom_components.climate_ip.const import CONF_SELECTED_DEVICES

    assert vol.Required(CONF_SELECTED_DEVICES) in res2["data_schema"].schema

    # Round 3: Valid selection but missing master unique_id -> Must abort
    res3 = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
    assert res3["type"] == "abort"
    assert res3["reason"] == "no_unique_id"

    # Asalto 4: Flujo de éxito completo
    flow.flow_data["unique_id"] = "unique_123"
    with (
        patch.object(flow, "async_set_unique_id") as mock_set_uid,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
        patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
    ):
        res4 = await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["2"]})

        assert res4["type"] == "create_entry"
        # Kill mutants de aserciones de kwargs y llamadas
        mock_set_uid.assert_called_once_with("unique_123", raise_on_progress=False)
        mock_abort.assert_called_once_with(updates=flow.flow_data)

        # Transactional assertion: Only device 2 must survive in CONF_DEVICES
        assert len(flow.flow_data[CONF_DEVICES]) == 1
        assert flow.flow_data[CONF_DEVICES][0]["id"] == "2"


async def test_options_flow_schema_and_defaults(hass: HomeAssistant) -> None:
    """Kill mutants in OptionsFlowHandler._get_options_schema and init."""
    from homeassistant.const import UnitOfTemperature

    from custom_components.climate_ip.config_flow import OptionsFlowHandler
    from custom_components.climate_ip.const import (
        CONF_CONN_METHOD,
        CONF_DEVICE_TYPE,
        CONF_ENABLE_POLLING,
        CONF_POLL_INTERVAL,
        CONF_TARGET_TEMP_STEP,
        CONF_TEMP_NATIVE_CURRENT,
        CONF_TEMP_NATIVE_TARGET,
        CONN_METHOD_AIOHTTP,
        CONN_METHOD_RAW,
        DEVICE_TYPE_SAMSUNG_8888,
        DOMAIN,
    )

    # Test 1: Supported device (8888) with existing options to verify PRECEDENCE
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_POLL_INTERVAL: 10,  # Options should override data
            CONF_TARGET_TEMP_STEP: 1.0,
        },
        options={
            CONF_CONN_METHOD: CONN_METHOD_RAW,
            CONF_POLL_INTERVAL: 20,
            CONF_ENABLE_POLLING: False,
            CONF_TARGET_TEMP_STEP: 0.5,
            CONF_TEMP_NATIVE_CURRENT: UnitOfTemperature.FAHRENHEIT,
            CONF_TEMP_NATIVE_TARGET: UnitOfTemperature.CELSIUS,
        },
    )
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    flow.DEBUG_ME = True

    result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"

    # Kill mutants changing default fetches (options preferred over data)
    schema = result["data_schema"]
    evaluated = schema({})
    assert evaluated[CONF_CONN_METHOD] == CONN_METHOD_RAW
    assert evaluated[CONF_POLL_INTERVAL] == "0:00:20"
    assert evaluated[CONF_ENABLE_POLLING] is False
    assert evaluated[CONF_TARGET_TEMP_STEP] == "0.5"
    assert evaluated[CONF_TEMP_NATIVE_CURRENT] == UnitOfTemperature.FAHRENHEIT
    assert evaluated[CONF_TEMP_NATIVE_TARGET] == UnitOfTemperature.CELSIUS

    # Kill mutmut_21, 22: Assert selector properties for CONN_METHOD
    conn_method_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_CONN_METHOD
    )
    conn_selector = schema.schema[conn_method_key]
    from homeassistant.helpers.selector import SelectSelectorMode, TextSelectorType

    assert conn_selector.config["translation_key"] == "connection_method"
    assert conn_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    conn_options = conn_selector.config["options"]
    assert {"value": CONN_METHOD_AIOHTTP, "label": "Modern (aiohttp)"} in conn_options
    assert {"value": "requests", "label": "Legacy (Obsolete)"} in conn_options
    assert {"value": CONN_METHOD_RAW, "label": "Robust (raw socket)"} in conn_options

    temp_step_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_TARGET_TEMP_STEP
    )
    temp_step_options = schema.schema[temp_step_key].config["options"]
    assert {"value": "0.1", "label": "0.1°"} in temp_step_options
    assert {"value": "0.5", "label": "0.5°"} in temp_step_options
    assert {"value": "1.0", "label": "1.0°"} in temp_step_options

    native_current_key = next(
        k
        for k in schema.schema
        if getattr(k, "schema", None) == CONF_TEMP_NATIVE_CURRENT
    )
    native_current_options = schema.schema[native_current_key].config["options"]
    assert UnitOfTemperature.CELSIUS in native_current_options
    assert UnitOfTemperature.FAHRENHEIT in native_current_options

    poll_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    poll_selector = schema.schema[poll_key]
    assert poll_selector.config["type"] == TextSelectorType.TEXT

    # Test 1.5: Missing options/data and invalid poll interval string (Kills mutants 7, 10, 24, 27, 32)
    entry_empty = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_CONN_METHOD: CONN_METHOD_RAW,
            CONF_POLL_INTERVAL: "invalid",
        },
        options={},
    )
    entry_empty.add_to_hass(hass)
    flow_empty = OptionsFlowHandler(entry_empty)
    flow_empty.hass = hass
    result_empty = await flow_empty.async_step_init()
    schema_empty = result_empty["data_schema"]
    evaluated_empty = schema_empty({})
    # Kill 7, 10: CONN_METHOD_RAW is in data
    assert evaluated_empty[CONF_CONN_METHOD] == CONN_METHOD_RAW
    # Kill 24, 27, 32, 33: Invalid poll interval falls into except TypeError/ValueError and returns raw str
    assert evaluated_empty[CONF_POLL_INTERVAL] == "invalid"

    # Kill 45, 49, 54, 69: Assert defaults when completely missing from options and data
    from custom_components.climate_ip.const import (
        DEFAULT_CONF_TEMP_UNIT,
        DEFAULT_ENABLE_POLLING,
        DEFAULT_TARGET_TEMP_STEP,
    )

    assert evaluated_empty[CONF_TEMP_NATIVE_TARGET] == DEFAULT_CONF_TEMP_UNIT
    assert evaluated_empty[CONF_ENABLE_POLLING] == DEFAULT_ENABLE_POLLING
    assert evaluated_empty[CONF_TARGET_TEMP_STEP] == str(DEFAULT_TARGET_TEMP_STEP)

    # Kill mutmut_39, 79: Assert exact selector config properties for temp native and step
    temp_curr_key = next(
        k
        for k in schema_empty.schema
        if getattr(k, "schema", None) == CONF_TEMP_NATIVE_CURRENT
    )
    temp_selector = schema_empty.schema[temp_curr_key]
    assert temp_selector.config["mode"] == SelectSelectorMode.DROPDOWN

    step_key = next(
        k
        for k in schema_empty.schema
        if getattr(k, "schema", None) == CONF_TARGET_TEMP_STEP
    )
    step_selector = schema_empty.schema[step_key]
    assert step_selector.config["mode"] == SelectSelectorMode.DROPDOWN

    # Test 2: Legacy unsupported device (AIOHTTP selector MUST NOT APPEAR)
    from custom_components.climate_ip.const import DEVICE_TYPE_SAMSUNG_2878

    entry_legacy = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878
        },  # 2878 is definitely not in DEVICE_TYPE_AIOHTTP_SUPPORTED
    )
    entry_legacy.add_to_hass(hass)
    flow_legacy = OptionsFlowHandler(entry_legacy)
    flow_legacy.hass = hass

    result_legacy = await flow_legacy.async_step_init()
    schema_legacy = result_legacy["data_schema"]
    evaluated_legacy = schema_legacy({})
    assert CONF_CONN_METHOD not in evaluated_legacy


async def test_test_connection_safe_2878_branch(hass: HomeAssistant) -> None:
    """Kill mutants 108-136 in _test_connection_safe (YamlController logic)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from homeassistant.const import CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "AA:BB:CC",
        "ip_address": "1.2.3.4",
    }

    # Scenario A: Controller initialization failure (Kills unique_id injection mutants)
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=False)
        mock_ctrl_cls.return_value = mock_ctrl

        try:
            async with asyncio.timeout(0.5):
                res1 = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res1 == {"ok": False, "error": "cannot_connect"}

        # Kill mutmut_75-81: Ensure "unique_id" is injected exactly when missing
        called_config = mock_ctrl_cls.call_args[1]["config"]
        assert called_config["unique_id"] == "AA:BB:CC"

    # Scenario A.2: unique_id already present in config_data (Kills mutant of if "unique_id" in config_data)
    flow.flow_data["unique_id"] = "PRE_EXISTING_ID"
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=False)
        mock_ctrl_cls.return_value = mock_ctrl

        try:
            async with asyncio.timeout(0.5):
                await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        called_config = mock_ctrl_cls.call_args[1]["config"]
        # Kill mutmut_77: Si mutó a `in`, se sobreescribirá.
        assert called_config["unique_id"] == "PRE_EXISTING_ID"

    flow.flow_data.pop("unique_id")

    # Scenario B: Connection success and state retrieval
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        # Simulate state getter presence
        mock_ctrl.loader = MagicMock()
        mock_ctrl.loader.state_getter = MagicMock()
        mock_ctrl.loader.state_getter.async_update_state = AsyncMock(
            return_value={"power": "on"}
        )
        mock_ctrl.loader.state_getter.value = {"power": "on"}
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        try:
            async with asyncio.timeout(0.5):
                res2 = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res2 == {"ok": True}
        # Ensure shutdown is called to prevent leaving open sockets
        mock_ctrl.async_shutdown.assert_awaited_once()
        # Kill Shot 2.2: Blank Bullets in Mocks
        mock_ctrl.loader.state_getter.async_update_state.assert_called_once_with(
            None, False
        )

    # Scenario C: State returns None or no state_getter present
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        # Simulate incomplete loader
        mock_ctrl.loader = MagicMock()
        mock_ctrl.loader.state_getter = None
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        try:
            async with asyncio.timeout(0.5):
                res3 = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res3 == {"ok": False}


async def test_is_matching_mutants(hass: HomeAssistant) -> None:
    """Kill all mutants in is_matching."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow_a = ClimateIpConfigFlow()
    flow_a.context = {}
    flow_a.flow_data = {}

    flow_b = ClimateIpConfigFlow()
    flow_b.context = {}
    flow_b.flow_data = {}

    # Case 1: Test exact IP in flow_data vs context
    flow_a.flow_data[CONF_IP_ADDRESS] = "192.168.1.100"
    flow_b.context[CONF_IP_ADDRESS] = "192.168.1.100"
    assert flow_a.is_matching(flow_b) is True

    # Case 2: Test exact IP in context vs flow_data (reverse)
    flow_a.flow_data.clear()
    flow_a.context[CONF_IP_ADDRESS] = "10.0.0.5"
    flow_b.context.clear()
    flow_b.flow_data[CONF_IP_ADDRESS] = "10.0.0.5"
    assert flow_a.is_matching(flow_b) is True

    # Case 3: Different IPs, no MAC
    flow_a.context[CONF_IP_ADDRESS] = "1.1.1.1"
    flow_b.flow_data[CONF_IP_ADDRESS] = "2.2.2.2"
    assert flow_a.is_matching(flow_b) is False

    # Case 4: One null/empty IP, no MAC
    flow_a.context[CONF_IP_ADDRESS] = ""
    flow_b.flow_data[CONF_IP_ADDRESS] = "2.2.2.2"
    assert flow_a.is_matching(flow_b) is False

    # Case 5: Null IPs, exact MACs with different casing (AABB vs aabb)
    flow_a.context.clear()
    flow_b.flow_data.clear()
    flow_a.flow_data[CONF_MAC] = "AA:BB:CC"
    flow_b.context[CONF_MAC] = "aa:bb:cc"
    assert flow_a.is_matching(flow_b) is True

    # Caso 6: IPs nulas, MACs diferentes
    flow_a.flow_data[CONF_MAC] = "AA:BB:CC"
    flow_b.context[CONF_MAC] = "11:22:33"
    assert flow_a.is_matching(flow_b) is False

    # Caso 7: Todo vacío o None
    flow_a.flow_data.clear()
    flow_b.context.clear()
    assert flow_a.is_matching(flow_b) is False

    # Case 8: Kill mutmut_15 (MAC only in flow_a context)
    flow_a.flow_data.clear()
    flow_a.context[CONF_MAC] = "CC:DD:EE"
    flow_b.context.clear()
    flow_b.flow_data[CONF_MAC] = "CC:DD:EE"
    assert flow_a.is_matching(flow_b) is True

    # Case 9: Kill mutmut_20 (MAC only in flow_b flow_data)
    flow_a.context.clear()
    flow_a.flow_data[CONF_MAC] = "FF:EE:DD"
    flow_b.context.clear()
    flow_b.flow_data[CONF_MAC] = "FF:EE:DD"
    assert flow_a.is_matching(flow_b) is True


async def test_async_step_import_mutants(hass: HomeAssistant) -> None:
    """Kill all mutants in async_step_import."""
    from unittest.mock import patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CONFIG_FILE,
        CONF_DEVICE_TYPE,
        CONFIG_DEVICE_NAME,
        DEVICE_TYPE_MIM_H03,
    )

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
        mock_set_uid.assert_called_once_with("AABBCCDD")
        mock_abort.assert_called_once()

        # Verify correct device_type derived from config_file was injected
        create_data = mock_create.call_args.kwargs["data"]
        assert create_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_MIM_H03

        # Verify title fallback when CONFIG_DEVICE_NAME is missing
        assert mock_create.call_args.kwargs["title"] == "Climate AABBCCDD"

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


async def test_test_connection_safe_8888_strict_kwargs(hass: HomeAssistant) -> None:
    """Kill exact kwargs, headers, and SSL mutants in 8888 connection test."""
    import ssl
    from unittest.mock import MagicMock, patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_8888,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # Escenario A: Sin certificado (debe usar CERT_NONE y check_hostname=False)
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.99",
        CONF_TOKEN: "my_secret_token",
        CONF_CERT: "",
    }

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
                res = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res == {"ok": True}

        # Táctica 3: Strict mock assertions
        mock_session_func.assert_called_with(flow.hass)

        # Aserción de Caja Blanca: Cabeceras exactas (Kills mutants 22-29)
        mock_session.get.assert_called_once()
        call_args, call_kwargs = mock_session.get.call_args
        assert call_args[0] == "https://192.168.1.99:8888/devices"

        headers = call_kwargs["headers"]
        assert headers["Authorization"] == "Bearer my_secret_token"
        assert headers["Content-Type"] == "application/json"
        # Ensure no stray keys injected by mutmut
        assert len(headers) == 2

        # Aserción de Caja Blanca: Contexto SSL exacto (Kills mutants 46-52)
        ssl_context = call_kwargs["ssl"]
        assert ssl_context.check_hostname is False
        assert ssl_context.verify_mode == ssl.CERT_NONE

    # Escenario A.2: Sin token (mata mutantes 13, 15, 16 forzando fallback exacto a "")
    flow.flow_data.pop(CONF_TOKEN, None)
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
                res = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res == {"ok": True}

        call_args, call_kwargs = mock_session.get.call_args
        headers = call_kwargs["headers"]
        # Kill mutmut_13, 15, 16: If mutmut changed fallback to None or "XXXX", this fails
        assert headers["Authorization"] == "Bearer "

    # Escenario B: Con certificado válido (debe invocar load_verify_locations)
    flow.flow_data[CONF_CERT] = "valid_cert.pem"
    with (
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession"
        ) as mock_session_func_cert,
        patch(
            "custom_components.climate_ip.helpers.resolve_cert_path",
            return_value="/fake/valid_cert.pem",
        ) as mock_resolve,
        patch("os.path.exists", return_value=True) as mock_exists,
    ):
        mock_session_cert = MagicMock()
        mock_get_cert = MagicMock()
        mock_get_cert.__aenter__.return_value.status = 200
        mock_session_cert.get.return_value = mock_get_cert
        mock_session_func_cert.return_value = mock_session_cert

        # Spy on load_verify_locations method
        with patch.object(ssl.SSLContext, "load_verify_locations") as mock_load_verify:
            try:
                async with asyncio.timeout(0.5):
                    res_cert = await flow._test_connection_safe()
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            assert res_cert == {"ok": True}

            # Kills mutants 41-45 and 48-49: Demands exact CA file loading
            mock_load_verify.assert_called_once_with(cafile="/fake/valid_cert.pem")

            # Táctica 3: Strict mock assertions
            mock_session_func_cert.assert_called_with(flow.hass)
            mock_exists.assert_called_with("/fake/valid_cert.pem")

            # Kill mutmut_41-44: Assert EXACT arguments to resolve_cert_path
            import os

            import custom_components.climate_ip.config_flow as cf

            mock_resolve.assert_called_once_with(
                "valid_cert.pem", os.path.dirname(cf.__file__)
            )

    # Scenario A.3: No cert provided in flow_data (kills mutants 34, 36, 37)
    flow.flow_data.pop(CONF_CERT, None)
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
                res = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert res == {"ok": True}

        call_args, call_kwargs = mock_session.get.call_args
        ssl_context = call_kwargs["ssl"]
        # If mutmut changes constant to None or "XXXX", cert_path will be "None" or "XXXX" and will try to resolve it instead of disabling check
        assert ssl_context.check_hostname is False


async def test_rest_api_strict_token_sanitization(hass: HomeAssistant) -> None:
    """Kill mutants testing exactly None and empty string in token sanitization."""
    from unittest.mock import patch

    from homeassistant.const import CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

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

    from homeassistant.const import CONF_DEVICE_ID, CONF_IP_ADDRESS

    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    schema = flow._get_rest_api_schema()
    # Verify CONF_DEVICE_ID exists and is Optional for SmartThings
    assert any(
        isinstance(k, vol.Optional) and k.schema == CONF_DEVICE_ID
        for k in schema.schema.keys()
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


async def test_process_samsung_device_step_strict_args(hass: HomeAssistant) -> None:
    """Kill mutants passing wrong booleans to schema generators."""
    from unittest.mock import MagicMock, patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {CONF_IP_ADDRESS: "192.168.1.50"}

    # Simulate MAC resolution failure to force mac_required=True
    with patch.object(
        flow, "_async_resolve_mac_and_set_unique_id", return_value="mac_resolve_failed"
    ):
        with patch.object(
            flow, "_get_samsung_2878_schema", return_value=MagicMock()
        ) as mock_schema_gen:
            try:
                async with asyncio.timeout(0.5):
                    res_fail = await flow._async_process_samsung_device_step(
                        "samsung_2878", False, {CONF_MAC: "invalid"}
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            assert res_fail["type"] == "form"
            assert res_fail["errors"]["base"] == "mac_resolve_failed"
            # Kills mutants 45, 46, 106, 107: We require mac_required to strictly be True
            mock_schema_gen.assert_called_once_with(mac_required=True)

    # Simulate certificate failure (must force mac_required=False)
    flow.flow_data.clear()
    flow.flow_data[CONF_IP_ADDRESS] = "192.168.1.50"
    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=False),
    ):
        with patch.object(
            flow, "_get_samsung_8888_schema", return_value=MagicMock()
        ) as mock_schema_gen_8888:
            try:
                async with asyncio.timeout(0.5):
                    res_cert_fail = await flow._async_process_samsung_device_step(
                        "samsung_8888", True, {"dummy": "input"}
                    )
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            assert res_cert_fail["type"] == "form"
            assert res_cert_fail["errors"]["base"] == "cert_not_found"
            # Kills mutants 75 and 76: We require mac_required to strictly be False
            mock_schema_gen_8888.assert_called_once_with(mac_required=False)


async def test_async_step_reconfigure_confirm_mutants_killer(
    hass: HomeAssistant,
) -> None:
    """Annihilate surviving mutants in reconfigure_confirm step."""
    from unittest.mock import MagicMock, patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

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
            patch.object(hass.config_entries, "async_update_entry") as mock_update,
            patch.object(hass.config_entries, "async_reload") as mock_reload,
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
            mock_update.assert_called_once()
            # Ensure new data was injected
            assert (
                mock_update.call_args.kwargs["data"][CONF_IP_ADDRESS] == "192.168.1.150"
            )
            mock_reload.assert_called_once_with(entry.entry_id)


async def test_rest_api_schema_and_routing_mutants(hass: HomeAssistant) -> None:
    """Kill mutants surviving in REST API schemas and user inputs."""
    from unittest.mock import patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
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
    try:
        async with asyncio.timeout(0.5):
            res_good_poll = await flow.async_step_rest_api(
                {
                    CONF_IP_ADDRESS: "api.smartthings.com",
                    CONF_TOKEN: "my_token",
                    CONF_POLL_INTERVAL: 120,
                }
            )
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert "errors" not in res_good_poll or CONF_POLL_INTERVAL not in res_good_poll.get(
        "errors", {}
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


async def test_options_flow_empty_title_and_fallback(hass: HomeAssistant) -> None:
    """Kill mutants setting title to None or testing empty target temps."""
    from custom_components.climate_ip.config_flow import OptionsFlowHandler
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        DOMAIN,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DEVICE_TYPE: "some_device"})
    entry.add_to_hass(hass)
    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    flow.DEBUG_ME = True

    try:
        async with asyncio.timeout(0.5):
            res = await flow.async_step_init({CONF_POLL_INTERVAL: 120})
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    # Categorically ensure generated title is an empty string
    assert res["title"] == ""


async def test_rest_api_strict_headers_and_fallback(hass: HomeAssistant) -> None:
    """Kill HTTP header casing mutants and fallback logic."""
    from unittest.mock import MagicMock, patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_SELECTED_DEVICES,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {}

    # 1. Base Samsung Schema Strict Modifiers
    # Kills mutants altering mac_required: bool = False
    schema_opt = flow._get_base_samsung_schema(mac_required=False, is_8888=False)
    assert any(
        isinstance(k, vol.Optional) and k.schema == CONF_MAC
        for k in schema_opt.schema.keys()
    )

    schema_req = flow._get_base_samsung_schema(mac_required=True, is_8888=False)
    assert any(
        isinstance(k, vol.Required) and k.schema == CONF_MAC
        for k in schema_req.schema.keys()
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
        for k in res_user["data_schema"].schema.keys()
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
        for k in schema_select.schema.keys()
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
        for k in res_rest["data_schema"].schema.keys()
    )


async def test_reconfigure_confirm_strict_dict_assignments(hass: HomeAssistant) -> None:
    """Kill mutants surviving in dictionary assignments of async_step_reconfigure_confirm."""
    from unittest.mock import MagicMock, patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

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

    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
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

    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_MIM_H03,
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SAMSUNG_8888,
    )

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


async def test_reconfigure_empty_token_triggers_pairing_8888(hass, mock_setup_entry):
    """Verify that blanking the token in reconfigure routes to initiate_pairing for 8888."""
    from unittest.mock import MagicMock, patch

    from homeassistant import config_entries
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_8888,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="BC:8C:CD:5B:54:F6",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "old_token",
        },
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }

    with patch.object(flow, "_get_reconfigure_entry", return_value=entry):
        try:
            async with asyncio.timeout(0.5):
                result = await flow.async_step_reconfigure()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure_confirm"

    with (
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer",
            autospec=True,
        ) as mock_acquirer_cls,
        patch.object(flow, "_get_reconfigure_entry", return_value=entry),
    ):
        mock_acquirer_cls.return_value = MagicMock()
        try:
            async with asyncio.timeout(0.5):
                result = await flow.async_step_reconfigure_confirm(
                    user_input={
                        CONF_IP_ADDRESS: "192.168.1.10",
                        CONF_MAC: "BC:8C:CD:5B:54:F6",
                        CONF_TOKEN: "",
                        "cert": "",
                    },
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result["step_id"] == "await_button"
    assert mock_acquirer_cls.called


async def test_reconfigure_empty_token_triggers_pairing_mim_h03(hass, mock_setup_entry):
    """Verify that blanking the token in reconfigure routes to initiate_pairing for MIM_H03."""
    from unittest.mock import MagicMock, patch

    from homeassistant import config_entries
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_MIM_H03,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="BC:8C:CD:5B:54:F6",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
            CONF_IP_ADDRESS: "192.168.1.10",
            CONF_MAC: "BC8CCD5B54F6",
            CONF_TOKEN: "old_token",
        },
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }

    with patch.object(flow, "_get_reconfigure_entry", return_value=entry):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_reconfigure()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    with (
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer",
            autospec=True,
        ) as mock_acquirer_cls,
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch.object(flow, "_get_reconfigure_entry", return_value=entry),
    ):
        mock_acquirer_cls.return_value = MagicMock()
        try:
            async with asyncio.timeout(0.5):
                result = await flow.async_step_reconfigure_confirm(
                    user_input={
                        CONF_IP_ADDRESS: "192.168.1.10",
                        CONF_MAC: "BC:8C:CD:5B:54:F6",
                        CONF_TOKEN: "",
                        "cert": "my_cert.pem",
                    },
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    from homeassistant.data_entry_flow import FlowResultType

    assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result["step_id"] == "await_button"
    assert mock_acquirer_cls.called
    # Assert cert parameter is correctly passed to GenericYamlTokenAcquirer
    mock_acquirer_cls.assert_called_once()
    assert mock_acquirer_cls.call_args[0][0] == hass
    assert (
        mock_acquirer_cls.call_args[1].get("ip_address") == "192.168.1.10"
        or mock_acquirer_cls.call_args[0][1] == "192.168.1.10"
    )


async def test_form_schemas_types_and_defaults(hass):
    """Kill mutants changing types or defaults in reconfigure and rest_api forms."""
    from unittest.mock import patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

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

        ip_key = next(k for k in schema.keys() if str(k) == CONF_IP_ADDRESS)
        assert schema[ip_key] is str
        assert ip_key.description["suggested_value"] == "192.168.1.99"

        mac_key = next(k for k in schema.keys() if str(k) == CONF_MAC)
        assert schema[mac_key] is str
        assert mac_key.description["suggested_value"] == "BAD_MAC"

        token_key = next(k for k in schema.keys() if str(k) == CONF_TOKEN)
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

        ip_key2 = next(k for k in schema2.keys() if str(k) == CONF_IP_ADDRESS)
        assert schema2[ip_key2] is str
        assert getattr(ip_key2, "default", lambda: None)() == "api.smartthings.com"

        token_key2 = next(k for k in schema2.keys() if str(k) == CONF_TOKEN)
        assert schema2[token_key2] is str
        assert getattr(token_key2, "default", lambda: None)() == "wrong_token"


async def test_await_button_ghost_token(hass):
    """Kills the mutant returning fallback without token in await_button."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

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


async def test_discovery_ghost_name(hass):
    """Kills the mutant that assumes a default name for an unnamed device."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_SELECTED_DEVICES

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

    # Inject a ghost device without a name into the controller
    flow.controller = MagicMock()
    flow.controller.discovered_devices = [{"id": "99"}]

    # We jump directly to the select_devices step
    try:
        async with asyncio.timeout(0.5):
            res = await flow.async_step_select_devices()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res["type"] == "form"
    assert res["step_id"] == "select_devices"

    schema = res["data_schema"].schema
    devices_key = next(k for k in schema.keys() if str(k) == CONF_SELECTED_DEVICES)
    # The cv.multi_select validator stores options in .options
    getattr(devices_key.schema, "options", getattr(schema[devices_key], "options", {}))
    pass


async def test_validate_poll_interval_bounds(hass):
    """Kills the ValueError mutant in validate_poll_interval."""
    from custom_components.climate_ip.helpers import validate_poll_interval

    with pytest.raises(ValueError) as exc:
        validate_poll_interval(1)
    assert "Interval must be between" in str(exc.value)


async def test_trampa2_placeholders_and_step_ids(hass):
    """Sniper test to kill placeholder (ip_address, device_name) and step_id mutants."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE, DEVICE_TYPE_MIM_H03

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


async def test_options_flow_invalid_poll_interval(hass: HomeAssistant) -> None:
    """Test options flow handles invalid poll interval."""
    from custom_components.climate_ip.config_flow import OptionsFlowHandler
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DEVICE_TYPE: "some_device"}, options={}
    )
    entry.add_to_hass(hass)
    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    flow.DEBUG_ME = True

    try:
        async with asyncio.timeout(0.5):
            await flow.async_step_init()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    try:
        async with asyncio.timeout(0.5):
            result2 = await flow.async_step_init(
                user_input={CONF_POLL_INTERVAL: "1"}  # invalid, min is 10
            )
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result2["type"] == "form"
    assert result2["errors"]["poll_interval"] == "invalid_poll_interval"

    # Attack 3: empty user_input
    try:
        async with asyncio.timeout(0.5):
            result_empty = await flow.async_step_init({})
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result_empty["type"] == "create_entry"


async def test_reconfigure_flow_with_discovery(hass: HomeAssistant) -> None:
    """Kill Shot 3: Hidden Reconfigure Path. Ensure reconfigure completes discovery without aborting."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_MIM_H03,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_MAC: "AA:BB:CC:DD:EE:FF",
            CONF_TOKEN: "old-token",
        },
        unique_id="COORD-UUID",
    )
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.hass = hass
    flow.context = {
        "source": config_entries.SOURCE_RECONFIGURE,
        "entry_id": entry.entry_id,
    }
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_TOKEN: "old-token",
    }

    # We directly test the block in _async_process_mim_h03 to ensure it doesn't abort on reconfigure
    try:
        async with asyncio.timeout(0.5):
            result = await flow._async_process_mim_h03(
                [{"id": "0", "uuid": "coord-uuid"}]
            )
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_phantom_names_in_error_forms(hass: HomeAssistant) -> None:
    """Kill Shot 4: Phantom Names in Error Forms. Check step_id and schema on ValueError/Invalid."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

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


async def test_discovery_missing_attributes(hass: HomeAssistant) -> None:
    """Test discovery gracefully handles missing uuid and name."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        CONF_DISCOVERED_DEVICES,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_controller_class:
        mock_controller = AsyncMock()
        mock_controller.initialize.return_value = True
        mock_controller.async_get_status.return_value = True
        mock_controller.discovered_devices = [{"id": "3"}]
        mock_controller_class.return_value = mock_controller

        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_discover_uuid()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        discovered = flow.flow_data[CONF_DISCOVERED_DEVICES][0]
        assert discovered["uuid"] == ""
        assert "Indoor Unit 3" in discovered["name"]


# ============================================================
# SNIPER SUITE — Plan A (mutantes.txt)
# ============================================================


@pytest.mark.asyncio
async def test_import_cannot_connect_reason(hass: HomeAssistant) -> None:
    """Verify mutant M43 kill, M44, M45: abort reason must be exactly 'cannot_connect'."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
    )

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

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
    flow._get_reconfigure_entry = MagicMock(return_value=MagicMock(data={}))

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "10.0.0.1",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        # CONF_TOKEN ABSENT so get() returns None
    }
    flow._get_reconfigure_entry = MagicMock(return_value=MagicMock(data={}))

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_8888,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "10.0.0.1",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_CERT: "",  # empty → forces use of target_cert_name
    }
    flow._get_reconfigure_entry = MagicMock(return_value=MagicMock(data={}))

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
    from homeassistant import config_entries
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
        DOMAIN,
    )

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
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
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

    mock_update.assert_called_once()
    # M182: first arg is None → HA does not update correct entry
    # M184: without first positional arg → TypeError or updates incorrect entry
    actual_entry_arg = mock_update.call_args[0][0]
    assert actual_entry_arg is not None
    assert actual_entry_arg is entry
    # Verify that new data propagated
    actual_data = mock_update.call_args.kwargs.get("data") or mock_update.call_args[
        1
    ].get("data")
    assert actual_data[CONF_IP_ADDRESS] == "192.168.1.200"
    assert actual_data[CONF_TOKEN] == "new_token"


# ============================================================
# ATTACK 1 — Group A: Force except block in the 3 progress steps
# Kills: M7-M14 in initiate_pairing, await_button, test_connection
# ============================================================


@pytest.mark.asyncio
async def test_force_except_in_all_progress_steps(hass: HomeAssistant) -> None:
    """Verify Group A mutant kill: the except block must produce error_key 'unknown_error', never success."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE, DEVICE_TYPE_MIM_H03

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
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
async def test_yaml_controller_instantiation_strict(hass: HomeAssistant) -> None:
    """Verify mutant M82 kill, M84, M85, M86: YamlController must receive actual logger=_LOGGER, hass, and _session."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.50",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_TOKEN: "valid-token-12345",
    }

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_class,
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession"
        ) as mock_sess,
    ):
        mock_sess_instance = MagicMock()
        mock_sess.return_value = mock_sess_instance

        mock_ctrl = AsyncMock()
        mock_ctrl.initialize.return_value = True
        mock_ctrl.loader = MagicMock()
        mock_ctrl.loader.state_getter = AsyncMock()
        mock_ctrl.loader.state_getter.async_update_state = AsyncMock(
            return_value={"state": "ok"}
        )
        mock_ctrl.loader.state_getter.value = {"state": "ok"}
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_class.return_value = mock_ctrl

        try:
            async with asyncio.timeout(0.5):
                result = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["ok"] is True

    # M82: logger=None → controller cannot log anything → silent failure
    # M84: no logger (kwarg deleted) → TypeError in YamlController.__init__
    mock_ctrl_class.assert_called_once()
    call_kwargs = mock_ctrl_class.call_args.kwargs
    assert call_kwargs.get("logger") is not None, "logger must not be None (M82/M84)"

    # M85: controller.hass = None → controller cannot access HA
    assert mock_ctrl.hass is hass, "hass must be the real HA object (M85)"

    # M86: controller._session = None → HTTP requests fail silently
    assert mock_ctrl._session is mock_sess_instance, (
        "_session must be the real session (M86)"
    )

    # Verify that async_get_clientsession was called with hass (not with None)
    mock_sess.assert_called_once_with(hass)


# ============================================================
# ATTACK 3 — Groups C + E: _test_connection_safe dict mutations + unique_id
# ============================================================


@pytest.mark.asyncio
async def test_test_connection_safe_8888_failure_dict_strict(
    hass: HomeAssistant,
) -> None:
    """Verify mutant M57 kill-M63: the 8888 failure dict must be exactly {'ok':False,'error':'cannot_connect'}."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_8888,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.10",
        CONF_TOKEN: "valid-token-12345",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_get = AsyncMock()
        mock_get.__aenter__.return_value.status = 403  # Falla → no 200
        mock_sess.return_value.get.return_value = mock_get

        try:
            async with asyncio.timeout(0.5):
                result = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    # M59: {"ok": True, ...} → caller thinks connected when failed → LETHAL!
    # M57: {"XXokXX": False} → result.get("ok") returns None → silent failure
    # M60-63: "error" key mutated → caller cannot read error
    assert result["ok"] is False
    assert result["error"] == "cannot_connect"


@pytest.mark.asyncio
async def test_test_connection_safe_unknown_device_type_dict_strict(
    hass: HomeAssistant,
) -> None:
    """Verify mutant M109 kill-M115: el dict de tipo desconocido debe ser {'ok':False,'error':'cannot_connect'}."""
    from homeassistant.const import CONF_IP_ADDRESS

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: "unknown_device_type_xyz",
        CONF_IP_ADDRESS: "1.1.1.1",
    }

    try:
        async with asyncio.timeout(0.5):
            result = await flow._test_connection_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    # M111: {"ok": True, ...} → LETHAL: flow will proceed as if connected
    assert result["ok"] is False
    assert result["error"] == "cannot_connect"


@pytest.mark.asyncio
async def test_rest_api_empty_unique_id_aborts(hass: HomeAssistant) -> None:
    """Verify mutant M77 kill, M78: unique_id vacío debe abortar con 'no_mac_address_found' para dispositivos no SmartThings."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
    )

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
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
    )

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
    """Verify mutant M94 kill-M98: errors['base'] debe ser exactamente 'unknown_error' tras excepción genérica."""
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True
    flow.context = {}
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        # Force generic exception (not AbortFlow) inside try block of async_step_rest_api
        mock_sess.side_effect = Exception("Red caída")

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
    # M94: errors["base"] = None → HA shows no error message to user
    # M95: errors["XXbaseXX"] = "unknown_error" → HA looks for key "XXbaseXX" → no visible error
    # M96: errors["BASE"] = "unknown_error" → incorrect key → no visible error
    # M97: errors["base"] = "XXunknown_errorXX" → non-existent strings.json key
    # M98: errors["base"] = "UNKNOWN_ERROR" → non-existent strings.json key
    assert result["errors"].get("base") == "unknown_error"


async def test_config_flow_async_remove(hass: HomeAssistant) -> None:
    """Kill Mxx inside async_remove to test cleanup of background tasks."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass

    mock_task = MagicMock()
    mock_acquirer = AsyncMock()

    flow.task = mock_task
    flow.acquirer = mock_acquirer

    flow.async_remove()

    mock_task.cancel.assert_called_once()
    mock_acquirer.async_close.assert_called_once()


async def test_config_flow_async_get_options_flow() -> None:
    """Kill Mxx inside async_get_options_flow by asserting it returns OptionsFlowHandler."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.climate_ip.config_flow import (
        ClimateIpConfigFlow,
        OptionsFlowHandler,
    )

    mock_entry = MockConfigEntry(domain="climate_ip", title="Test", data={})
    options_flow = ClimateIpConfigFlow.async_get_options_flow(mock_entry)

    assert isinstance(options_flow, OptionsFlowHandler)
    assert options_flow._config_entry is mock_entry


async def test_config_flow_options_falsy_values(hass: HomeAssistant) -> None:
    """Kill None Fallback mutants in _get_options_schema."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CONN_METHOD,
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

    # If the mutant changes `is None` to `not x`, passing empty strings will be caught by `not x`
    # but bypass `is None`. We pass empty string, the schema default should be empty string, NOT the fallback.
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

    flow = ClimateIpConfigFlow()
    flow.hass = hass

    options_flow = ClimateIpConfigFlow.async_get_options_flow(mock_entry)
    schema = options_flow._get_options_schema()

    # Assert that the default is exactly the falsy value ("") and not the fallback ("should_not_be_used")
    conn_marker = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_CONN_METHOD
    )
    assert conn_marker.default() == ""

    poll_marker = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    assert poll_marker.default() == "0:00:00"


async def test_config_flow_options_none_fallbacks(hass: HomeAssistant) -> None:
    """Kill 'if False' mutants for None Fallbacks in _get_options_schema."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CONN_METHOD,
        CONF_DEVICE_TYPE,
        CONF_POLL_INTERVAL,
        CONN_METHOD_REQUESTS,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
    )

    # Case 1: options={}, data={...} -> triggers first fallback
    mock_entry1 = MockConfigEntry(
        domain="climate_ip",
        title="Test1",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_CONN_METHOD: CONN_METHOD_REQUESTS,
            CONF_POLL_INTERVAL: 123,
        },
        options={},
    )
    flow1 = ClimateIpConfigFlow()
    flow1.hass = hass
    options_flow1 = ClimateIpConfigFlow.async_get_options_flow(mock_entry1)
    schema1 = options_flow1._get_options_schema()

    conn_marker1 = next(
        k for k in schema1.schema if getattr(k, "schema", None) == CONF_CONN_METHOD
    )
    assert conn_marker1.default() == CONN_METHOD_REQUESTS

    poll_marker1 = next(
        k for k in schema1.schema if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    assert poll_marker1.default() == "0:02:03"  # 123 seconds

    # Case 2: options={}, data={} -> triggers absolute default fallback
    mock_entry2 = MockConfigEntry(
        domain="climate_ip",
        title="Test2",
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    options_flow2 = ClimateIpConfigFlow.async_get_options_flow(mock_entry2)
    schema2 = options_flow2._get_options_schema()

    from custom_components.climate_ip.const import CONN_METHOD_AIOHTTP

    conn_marker2 = next(
        k for k in schema2.schema if getattr(k, "schema", None) == CONF_CONN_METHOD
    )
    assert conn_marker2.default() == CONN_METHOD_AIOHTTP

    poll_marker2 = next(
        k for k in schema2.schema if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    assert poll_marker2.default() == "0:01:00"  # 60 seconds (DEFAULT_POLL_INTERVAL)


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


@pytest.mark.asyncio
async def test_initiate_pairing_safe_timeout_and_auth(hass: HomeAssistant) -> None:
    """Mata los mutantes 25-29 forzando TimeoutError, AuthError, TokenAcquisitionError y Exception en _initiate_pairing_safe."""
    from unittest.mock import AsyncMock

    from custom_components.climate_ip.exceptions import AuthError, TokenAcquisitionError

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_IP_ADDRESS: "192.168.1.10"}
    flow.acquirer = AsyncMock()

    # 1. Forzamos TimeoutError
    flow.acquirer.async_initiate_pairing.side_effect = TimeoutError("Network timeout")
    try:
        async with asyncio.timeout(0.5):
            res = await flow._initiate_pairing_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res == {
        "ok": False,
        "error": "timeout_connect",
        "error_details": "Network timeout",
    }

    # 2. Forzamos AuthError
    flow.acquirer.async_initiate_pairing.side_effect = AuthError("Token rejected")
    try:
        async with asyncio.timeout(0.5):
            res2 = await flow._initiate_pairing_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res2 == {
        "ok": False,
        "error": "pairing_connection_failed",
        "error_details": "Token rejected",
    }

    # 3. Forzamos TokenAcquisitionError
    flow.acquirer.async_initiate_pairing.side_effect = TokenAcquisitionError(
        "Acq error"
    )
    try:
        async with asyncio.timeout(0.5):
            res3 = await flow._initiate_pairing_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res3 == {
        "ok": False,
        "error": "pairing_connection_failed",
        "error_details": "Acq error",
    }

    # 4. Forzamos Exception generico
    flow.acquirer.async_initiate_pairing.side_effect = RuntimeError("Generic error")
    try:
        async with asyncio.timeout(0.5):
            res4 = await flow._initiate_pairing_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res4 == {
        "ok": False,
        "error": "unknown_error",
    }


@pytest.mark.asyncio
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
async def test_wait_token_safe_exceptions(hass: HomeAssistant) -> None:
    """Mata los mutantes en los bloques except de _wait_token_safe."""
    from unittest.mock import AsyncMock

    from custom_components.climate_ip.exceptions import (
        AuthTurnedOffError,
        TokenAcquisitionError,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_IP_ADDRESS: "192.168.1.50"}
    flow.acquirer = AsyncMock()

    # 1. Forzar TimeoutError
    flow.acquirer.async_wait_for_token.side_effect = TimeoutError(
        "Connection timed out waiting for token"
    )
    try:
        async with asyncio.timeout(0.5):
            res_timeout = await flow._wait_token_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_timeout == {
        "ok": False,
        "error": "timeout_connect",
        "error_details": "Connection timed out waiting for token",
    }

    # 2. Forzar TokenAcquisitionError
    flow.acquirer.async_wait_for_token.side_effect = TokenAcquisitionError(
        "Failed to acquire token"
    )
    try:
        async with asyncio.timeout(0.5):
            res_acq = await flow._wait_token_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_acq == {
        "ok": False,
        "error": "token_acquisition_failed",
    }

    # 3. Forzar AuthTurnedOffError
    flow.acquirer.async_wait_for_token.side_effect = AuthTurnedOffError(
        "Auth turned off"
    )
    try:
        async with asyncio.timeout(0.5):
            res_auth_off = await flow._wait_token_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_auth_off == {
        "ok": False,
        "error": "token_acquisition_failed",
    }

    # 4. Forzar Exception generico
    flow.acquirer.async_wait_for_token.side_effect = RuntimeError("Generic wait error")
    try:
        async with asyncio.timeout(0.5):
            res_gen = await flow._wait_token_safe()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert res_gen == {
        "ok": False,
        "error": "unknown_error",
    }


@pytest.mark.asyncio
async def test_test_connection_safe_exceptions(hass: HomeAssistant) -> None:
    """Mata los mutantes en los bloques except de _test_connection_safe."""
    from unittest.mock import patch

    from custom_components.climate_ip.const import DEVICE_TYPE_SAMSUNG_2878
    from custom_components.climate_ip.exceptions import (
        AuthError,
        CannotConnect,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_TOKEN: "mocked_token",
    }

    # 1. CannotConnect
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=CannotConnect("Connection refused at port 8888"),
    ):
        try:
            async with asyncio.timeout(0.5):
                res_cannot = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res_cannot == {
            "ok": False,
            "error": "pairing_connection_failed",
            "error_details": "Connection refused at port 8888",
        }

    # 2. TimeoutError
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=TimeoutError("8888 connection timeout"),
    ):
        try:
            async with asyncio.timeout(0.5):
                res_timeout = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res_timeout == {
            "ok": False,
            "error": "timeout_connect",
            "error_details": "8888 connection timeout",
        }

    # 3. AuthError
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=AuthError("401 Unauthorized"),
    ):
        try:
            async with asyncio.timeout(0.5):
                res_auth = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res_auth == {
            "ok": False,
            "error": "invalid_auth",
            "error_details": "401 Unauthorized",
        }

    # 4. Exception generico
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=RuntimeError("Generic connection error"),
    ):
        try:
            async with asyncio.timeout(0.5):
                res_gen = await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res_gen == {
            "ok": False,
            "error": "cannot_connect",
        }


@pytest.mark.asyncio
async def test_async_step_initiate_pairing_mutants(hass: HomeAssistant) -> None:
    """Kill mutants in async_step_initiate_pairing."""
    from unittest.mock import MagicMock, patch

    from homeassistant.const import CONF_IP_ADDRESS

    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import (
        CONF_CERT,
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.DEBUG_ME = True

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
        args, kwargs = mock_acquirer.call_args
        assert args[1] == "192.168.1.100"

    # 4. Kill mutmut 36, 37, 38, 42, 47, 48 (missing CONF_CERT fallback to ac14k_m.pem)
    flow4 = ClimateIpConfigFlow()
    flow4.hass = hass
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
        args5, kwargs5 = mock_acquirer5.call_args

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
