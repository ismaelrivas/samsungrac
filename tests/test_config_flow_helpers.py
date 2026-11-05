# pylint: disable=protected-access,too-many-locals,line-too-long,too-many-statements,too-many-arguments,redefined-outer-name
"""Tests for ConfigFlowHelpersMixin in config_flow_helpers.py."""

import asyncio
import inspect
import os
import ssl
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DISCOVERED_DEVICES,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONFIG_DEVICE_NAME,
    DEVICE_TYPE_INTESISBOX,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPE_TO_CONFIG_FILE,
    PORT_SAMSUNG_2878,
    PORT_SAMSUNG_8888,
)
from custom_components.climate_ip.exceptions import (
    AuthError,
    AuthTurnedOffError,
    CannotConnect,
    TokenAcquisitionError,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.data_entry_flow import AbortFlow, FlowResultType
from homeassistant.util.yaml import load_yaml


@pytest.fixture
def hass_mock():
    """Mock Home Assistant object."""
    return MagicMock()


# -----------------------------------------------------------------------------
# 1. Tests for _async_force_arp_update (Kills Mutants 3, 4, 7, 8)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_force_arp_update_success(hass_mock):
    """Test _async_force_arp_update opens connections to both ports and closes writers."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    mock_writer = AsyncMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with (
        patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(MagicMock(), mock_writer),
        ) as mock_open,
        patch("asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait_for,
    ):
        await flow._async_force_arp_update("1.2.3.4")

        assert mock_open.call_count == 2
        # Assert exact destination tuple (ip_address, port) for both ports
        called_args = {c.args for c in mock_open.call_args_list}
        assert called_args == {
            ("1.2.3.4", PORT_SAMSUNG_2878),
            ("1.2.3.4", PORT_SAMSUNG_8888),
        }

        assert mock_writer.close.call_count == 2
        assert mock_writer.wait_closed.call_count == 2

        assert mock_wait_for.call_count == 2
        for call in mock_wait_for.call_args_list:
            assert len(call.args) == 1
            assert call.kwargs.get("timeout") == 0.5


@pytest.mark.asyncio
async def test_async_force_arp_update_handles_oserror_and_timeout(hass_mock):
    """Test _async_force_arp_update catches TimeoutError and OSError gracefully."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    with patch(
        "asyncio.open_connection", side_effect=[TimeoutError(), OSError("Port closed")]
    ) as mock_open:
        await flow._async_force_arp_update("10.0.0.1")
        assert mock_open.call_count == 2


# -----------------------------------------------------------------------------
# 2. Tests for _async_resolve_mac_and_set_unique_id (Kills Mutants 10, 11, 15-18)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_mac_skips_arp_if_in_cache(hass_mock):
    """Test that _async_resolve_mac_and_set_unique_id skips force_arp if MAC is already cached."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}
    flow.context = {"source": "user"}
    flow.reauth_entry = None

    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            new_callable=AsyncMock,
        ) as mock_get_mac,
        patch.object(
            flow, "_async_force_arp_update", new_callable=AsyncMock
        ) as mock_force_arp,
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
        patch.object(
            flow, "_abort_if_unique_id_configured"
        ) as mock_abort_if_configured,
    ):
        mock_get_mac.return_value = "00:11:22:33:44:55"

        result = await flow._async_resolve_mac_and_set_unique_id("1.1.1.1", None)

        assert result is None
        assert flow.flow_data[CONF_MAC] == "001122334455"
        mock_force_arp.assert_not_called()
        mock_get_mac.assert_called_once_with("1.1.1.1")
        mock_set_id.assert_called_once_with("001122334455")
        mock_abort_if_configured.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_mac_forces_arp_if_not_in_cache(hass_mock):
    """Test that _async_resolve_mac_and_set_unique_id forces ARP if initial attempt fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}
    flow.context = {"source": "user"}
    flow.reauth_entry = None

    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            new_callable=AsyncMock,
        ) as mock_get_mac,
        patch.object(
            flow, "_async_force_arp_update", new_callable=AsyncMock
        ) as mock_force_arp,
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
        patch.object(
            flow, "_abort_if_unique_id_configured"
        ) as mock_abort_if_configured,
    ):
        mock_get_mac.side_effect = [None, "aa:bb:cc:11:22:33"]

        result = await flow._async_resolve_mac_and_set_unique_id("192.168.1.50", None)

        assert result is None
        assert flow.flow_data[CONF_MAC] == "AABBCC112233"
        mock_force_arp.assert_called_once_with("192.168.1.50")
        assert mock_get_mac.call_count == 2
        mock_get_mac.assert_has_calls([call("192.168.1.50"), call("192.168.1.50")])
        mock_set_id.assert_called_once_with("AABBCC112233")
        mock_abort_if_configured.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_mac_provided_by_user(hass_mock):
    """Test that _async_resolve_mac_and_set_unique_id formats and uses a provided MAC."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}
    flow.context = {"source": "user"}
    flow.reauth_entry = None

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
        patch.object(
            flow, "_abort_if_unique_id_configured"
        ) as mock_abort_if_configured,
    ):
        result = await flow._async_resolve_mac_and_set_unique_id(
            "1.1.1.1", "aa:bb:cc:dd:ee:ff"
        )

        assert result is None
        assert flow.flow_data[CONF_MAC] == "AABBCCDDEEFF"
        mock_set_id.assert_called_once_with("AABBCCDDEEFF")
        mock_abort_if_configured.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_mac_discovery_failed_returns_error(hass_mock):
    """Test that discovery returning None before and after ARP returns mac_resolve_failed."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}
    flow.context = {"source": "user"}
    flow.reauth_entry = None

    with (
        patch(
            "custom_components.climate_ip.helpers.async_get_mac_address",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_get_mac,
        patch.object(
            flow, "_async_force_arp_update", new_callable=AsyncMock
        ) as mock_force_arp,
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
    ):
        result = await flow._async_resolve_mac_and_set_unique_id("1.1.1.1", None)

        assert result == "mac_resolve_failed"
        mock_force_arp.assert_called_once_with("1.1.1.1")
        assert mock_get_mac.call_count == 2
        mock_set_id.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_mac_reauth_and_reconfigure_source_skips_abort(hass_mock):
    """Test that reauth or SOURCE_RECONFIGURE skips _abort_if_unique_id_configured."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
    ):
        # Case 1: reauth_entry is not None
        flow.reauth_entry = MagicMock()
        flow.context = {"source": "user"}
        await flow._async_resolve_mac_and_set_unique_id("1.1.1.1", "11:22:33:44:55:66")
        mock_abort.assert_not_called()

        # Case 2: source is SOURCE_RECONFIGURE
        flow.reauth_entry = None
        flow.context = {"source": SOURCE_RECONFIGURE}
        await flow._async_resolve_mac_and_set_unique_id("1.1.1.1", "11:22:33:44:55:66")
        mock_abort.assert_not_called()


# -----------------------------------------------------------------------------
# 3. Tests for _async_validate_cert_path (Kills Mutants 1, 3)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_cert_path_empty_and_none(hass_mock):
    """Test that validating None or empty cert path returns True immediately."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    assert await flow._async_validate_cert_path(None) is True
    assert await flow._async_validate_cert_path("") is True


@pytest.mark.asyncio
async def test_validate_cert_path_none_resolved(hass_mock):
    """Test _async_validate_cert_path returns True when resolve_cert_path returns None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    with patch(
        "custom_components.climate_ip.helpers.resolve_cert_path", return_value=None
    ):
        assert await flow._async_validate_cert_path("invalid_path") is True


@pytest.mark.asyncio
async def test_validate_cert_path_disk_existence(hass_mock):
    """Test _async_validate_cert_path verifies file existence on disk via executor."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    # File exists on disk
    hass_mock.async_add_executor_job = AsyncMock(return_value=True)
    with patch(
        "custom_components.climate_ip.helpers.resolve_cert_path",
        return_value="/certs/cert.pem",
    ):
        res_exists = await flow._async_validate_cert_path("/certs/cert.pem")
        assert res_exists is True
        hass_mock.async_add_executor_job.assert_called_with(
            os.path.exists, "/certs/cert.pem"
        )

    # File does NOT exist on disk
    hass_mock.async_add_executor_job = AsyncMock(return_value=False)
    with patch(
        "custom_components.climate_ip.helpers.resolve_cert_path",
        return_value="/certs/missing.pem",
    ):
        res_missing = await flow._async_validate_cert_path("/certs/missing.pem")
        assert res_missing is False


# -----------------------------------------------------------------------------
# 4. Tests for _initiate_pairing_safe & _wait_token_safe (Kills Mutant 7 + Exceptions)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiate_pairing_safe_and_wait_token_safe_null_acquirer(hass_mock):
    """Test _initiate_pairing_safe and _wait_token_safe when acquirer is None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.acquirer = None
    flow.flow_data = {}

    res1 = await flow._initiate_pairing_safe()
    assert res1 == {"ok": False, "error": "unknown_error"}

    res2 = await flow._wait_token_safe()
    assert res2 == {"ok": False, "error": "unknown_error"}


@pytest.mark.asyncio
async def test_initiate_pairing_safe_and_wait_token_safe_success(hass_mock):
    """Test _initiate_pairing_safe and _wait_token_safe when acquirer succeeds."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    mock_acquirer = MagicMock()
    mock_acquirer.async_initiate_pairing = AsyncMock(return_value={"port": 8888})
    mock_acquirer.async_wait_for_token = AsyncMock(return_value="token123")
    flow.acquirer = mock_acquirer
    flow.flow_data = {}

    res1 = await flow._initiate_pairing_safe()
    assert res1 == {"ok": True, "config": {"port": 8888}}

    res2 = await flow._wait_token_safe()
    assert res2 == {"ok": True, "token": "token123"}


@pytest.mark.asyncio
async def test_initiate_pairing_safe_exceptions(hass_mock):
    """Test exception branches in _initiate_pairing_safe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_IP_ADDRESS: "1.2.3.4"}
    mock_acquirer = MagicMock()
    flow.acquirer = mock_acquirer

    # CannotConnect
    mock_acquirer.async_initiate_pairing = AsyncMock(
        side_effect=CannotConnect("refused")
    )
    res = await flow._initiate_pairing_safe()
    assert res["ok"] is False
    assert res["error"] == "pairing_connection_failed"
    assert "refused" in res["error_details"]

    # AuthError
    mock_acquirer.async_initiate_pairing = AsyncMock(side_effect=AuthError("bad auth"))
    res = await flow._initiate_pairing_safe()
    assert res["ok"] is False
    assert res["error"] == "pairing_connection_failed"

    # TokenAcquisitionError
    mock_acquirer.async_initiate_pairing = AsyncMock(
        side_effect=TokenAcquisitionError("bad token")
    )
    res = await flow._initiate_pairing_safe()
    assert res["ok"] is False
    assert res["error"] == "pairing_connection_failed"

    # TimeoutError
    mock_acquirer.async_initiate_pairing = AsyncMock(side_effect=TimeoutError())
    res = await flow._initiate_pairing_safe()
    assert res["ok"] is False
    assert res["error"] == "timeout_connect"

    # AbortFlow
    mock_acquirer.async_initiate_pairing = AsyncMock(
        side_effect=AbortFlow("already_configured")
    )
    with pytest.raises(AbortFlow):
        await flow._initiate_pairing_safe()

    # Generic Exception
    mock_acquirer.async_initiate_pairing = AsyncMock(
        side_effect=RuntimeError("unexpected")
    )
    res = await flow._initiate_pairing_safe()
    assert res == {"ok": False, "error": "unknown_error"}


@pytest.mark.asyncio
async def test_wait_token_safe_exceptions(hass_mock):
    """Test exception branches in _wait_token_safe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_IP_ADDRESS: "1.2.3.4"}
    mock_acquirer = MagicMock()
    flow.acquirer = mock_acquirer

    # TimeoutError
    mock_acquirer.async_wait_for_token = AsyncMock(side_effect=TimeoutError())
    res = await flow._wait_token_safe()
    assert res["ok"] is False
    assert res["error"] == "timeout_connect"

    # TokenAcquisitionError
    mock_acquirer.async_wait_for_token = AsyncMock(
        side_effect=TokenAcquisitionError("error")
    )
    res = await flow._wait_token_safe()
    assert res == {"ok": False, "error": "token_acquisition_failed"}

    # AuthTurnedOffError
    mock_acquirer.async_wait_for_token = AsyncMock(
        side_effect=AuthTurnedOffError("auth off")
    )
    res = await flow._wait_token_safe()
    assert res == {"ok": False, "error": "token_acquisition_failed"}

    # AbortFlow
    mock_acquirer.async_wait_for_token = AsyncMock(side_effect=AbortFlow("aborted"))
    with pytest.raises(AbortFlow):
        await flow._wait_token_safe()

    # Generic Exception
    mock_acquirer.async_wait_for_token = AsyncMock(side_effect=RuntimeError("crash"))
    res = await flow._wait_token_safe()
    assert res == {"ok": False, "error": "unknown_error"}


# -----------------------------------------------------------------------------
# 5. Tests for _build_ssl_context
# -----------------------------------------------------------------------------


def test_build_ssl_context_empty_and_valid():
    """Test _build_ssl_context with empty cert and resolved cert file."""
    # 1. Empty cert_path
    ctx_empty = ClimateIpConfigFlow._build_ssl_context("")
    assert ctx_empty.check_hostname is False
    assert ctx_empty.verify_mode == ssl.CERT_NONE

    # 2. Valid existing cert_path
    with (
        patch(
            "custom_components.climate_ip.helpers.resolve_cert_path",
            return_value="/path/to/cert.pem",
        ),
        patch("os.path.exists", return_value=True),
        patch.object(ssl.SSLContext, "load_verify_locations") as mock_load,
    ):
        ctx_cert = ClimateIpConfigFlow._build_ssl_context("cert.pem")
        assert isinstance(ctx_cert, ssl.SSLContext)
        mock_load.assert_called_once_with(cafile="/path/to/cert.pem")

    # 3. Non-existent resolved cert_path
    with (
        patch(
            "custom_components.climate_ip.helpers.resolve_cert_path",
            return_value=None,
        ),
        patch.object(ssl.SSLContext, "load_verify_locations") as mock_load,
    ):
        ctx_none = ClimateIpConfigFlow._build_ssl_context("nonexistent.pem")
        assert isinstance(ctx_none, ssl.SSLContext)
        mock_load.assert_not_called()


# -----------------------------------------------------------------------------
# 6. Tests for _test_connection_safe (Kills Mutants 5, 8, 9, 12-23, 27, 28)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_connection_safe_8888_success(hass_mock):
    """Test _test_connection_safe for 8888 device type with correct headers, url and ssl."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_TOKEN: "tok8888",
        CONF_CERT: "ca.pem",
    }

    mock_ssl_ctx = MagicMock()
    hass_mock.async_add_executor_job = AsyncMock(return_value=mock_ssl_ctx)

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__.return_value = mock_response

        mock_get = MagicMock(return_value=mock_response)
        mock_sess.return_value.get = mock_get

        res = await flow._test_connection_safe()

        assert res == {"ok": True}
        hass_mock.async_add_executor_job.assert_called_once_with(
            flow._build_ssl_context, "ca.pem"
        )
        mock_get.assert_called_once()
        assert mock_get.call_args.args[0] == "https://1.1.1.1:8888/devices"
        assert mock_get.call_args.kwargs["ssl"] is mock_ssl_ctx
        assert mock_get.call_args.kwargs["headers"] == {
            "Authorization": "Bearer tok8888",
            "Content-Type": "application/json",
        }


@pytest.mark.asyncio
async def test_test_connection_safe_8888_status_failure(hass_mock):
    """Test _test_connection_safe for 8888 device type when HTTP status is not 200."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    hass_mock.async_add_executor_job = AsyncMock(return_value=None)

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.__aenter__.return_value = mock_response
        mock_sess.return_value.get.return_value = mock_response

        res = await flow._test_connection_safe()
        assert res == {"ok": False, "error": "cannot_connect"}


@pytest.mark.asyncio
async def test_test_connection_safe_2878_full_injection(hass_mock):
    """Test _test_connection_safe for 2878 with unique_id and config_file auto-injection."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }

    with (
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession",
            return_value="mock_session",
        ),
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_cls,
    ):
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.loader = MagicMock()
        mock_ctrl.loader.state_getter = MagicMock()
        mock_ctrl.loader.state_getter.async_update_state = AsyncMock(
            return_value={"state": "on"}
        )
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._test_connection_safe()

        assert res == {"ok": True}
        mock_ctrl_cls.assert_called_once()
        assert "logger" in mock_ctrl_cls.call_args.kwargs
        assert mock_ctrl_cls.call_args.kwargs["logger"] is not None
        passed_config = mock_ctrl_cls.call_args.kwargs["config"]
        assert passed_config["unique_id"] == "AA:BB:CC:DD:EE:FF"
        assert (
            passed_config[CONF_CONFIG_FILE]
            == DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_SAMSUNG_2878]
        )
        assert mock_ctrl._session == "mock_session"
        assert mock_ctrl.hass is hass_mock
        mock_ctrl.initialize.assert_called_once()
        mock_ctrl.loader.state_getter.async_update_state.assert_called_once_with(
            None, False
        )
        mock_ctrl.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_safe_2878_fallback_empty_mac_and_logger(hass_mock):
    """Test 2878 fallback when CONF_MAC is missing and assert logger injection (Kills M17, M19, M20, M28)."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        # CONF_MAC absent, unique_id absent
    }

    with (
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession",
            return_value="mock_session",
        ),
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_cls,
    ):
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.loader = MagicMock()
        mock_ctrl.loader.state_getter = MagicMock()
        mock_ctrl.loader.state_getter.async_update_state = AsyncMock(
            return_value={"state": "on"}
        )
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._test_connection_safe()

        assert res == {"ok": True}
        mock_ctrl_cls.assert_called_once()
        assert "logger" in mock_ctrl_cls.call_args.kwargs
        assert mock_ctrl_cls.call_args.kwargs["logger"] is not None
        passed_config = mock_ctrl_cls.call_args.kwargs["config"]
        assert passed_config["unique_id"] == ""
        assert isinstance(passed_config["unique_id"], str)
        assert (
            passed_config[CONF_CONFIG_FILE]
            == DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_SAMSUNG_2878]
        )


@pytest.mark.asyncio
async def test_test_connection_safe_2878_custom_unique_id_and_config_file(hass_mock):
    """Test _test_connection_safe preserves existing unique_id and custom config_file."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        "unique_id": "custom_unique_id",
        CONF_CONFIG_FILE: "custom_ac.yaml",
    }

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.loader = MagicMock()
        mock_ctrl.loader.state_getter = MagicMock()
        mock_ctrl.loader.state_getter.async_update_state = AsyncMock(
            return_value={"state": "on"}
        )
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._test_connection_safe()

        assert res == {"ok": True}
        assert "logger" in mock_ctrl_cls.call_args.kwargs
        passed_config = mock_ctrl_cls.call_args.kwargs["config"]
        assert passed_config["unique_id"] == "custom_unique_id"
        assert passed_config[CONF_CONFIG_FILE] == "custom_ac.yaml"


@pytest.mark.asyncio
async def test_test_connection_safe_2878_state_none_and_init_false(hass_mock):
    """Test _test_connection_safe returns False when state_data is None or init fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
    }

    # 1. State getter returns None -> ok is False
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.loader = MagicMock()
        mock_ctrl.loader.state_getter = MagicMock()
        mock_ctrl.loader.state_getter.async_update_state = AsyncMock(return_value=None)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res = await flow._test_connection_safe()
        assert res == {"ok": False}

    # 2. Initialize returns False -> ok is False, error cannot_connect
    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(return_value=False)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        res2 = await flow._test_connection_safe()
        assert res2 == {"ok": False, "error": "cannot_connect"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flow_data",
    [
        {CONF_DEVICE_TYPE: "unknown_future_device"},
        {CONF_DEVICE_TYPE: "nonexistent_type", CONF_IP_ADDRESS: "1.1.1.1"},
    ],
)
async def test_test_connection_safe_unknown_device_type(hass_mock, flow_data):
    """Test _test_connection_safe returns error on unknown device type."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = flow_data

    res = await flow._test_connection_safe()
    assert res == {"ok": False, "error": "cannot_connect"}
    assert res["ok"] is False
    assert res["error"] == "cannot_connect"


@pytest.mark.asyncio
async def test_test_connection_safe_exceptions(hass_mock):
    """Test exception handling in _test_connection_safe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
    }

    # CannotConnect
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=CannotConnect("network down"),
    ):
        res = await flow._test_connection_safe()
        assert res["ok"] is False
        assert res["error"] == "pairing_connection_failed"
        assert "network down" in res["error_details"]

    # TimeoutError
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=TimeoutError(),
    ):
        res = await flow._test_connection_safe()
        assert res["ok"] is False
        assert res["error"] == "timeout_connect"

    # AuthError
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=AuthError("bad token"),
    ):
        res = await flow._test_connection_safe()
        assert res["ok"] is False
        assert res["error"] == "invalid_auth"
        assert "bad token" in res["error_details"]

    # AbortFlow
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=AbortFlow("reauth_successful"),
    ):
        with pytest.raises(AbortFlow):
            await flow._test_connection_safe()

    # Generic Exception
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=RuntimeError("unexpected crash"),
    ):
        res = await flow._test_connection_safe()
        assert res == {"ok": False, "error": "cannot_connect"}


def test_extract_and_validate_poll_interval():
    """Test _extract_and_validate_poll_interval variations and error handling."""
    flow = ClimateIpConfigFlow()

    # 1. Valid poll interval
    flow.flow_data = {}
    errors: dict[str, str] = {}
    flow._extract_and_validate_poll_interval(
        {CONF_POLL_INTERVAL: "0:01:30"}, errors, store_when_empty=True
    )
    assert errors == {}
    assert flow.flow_data[CONF_POLL_INTERVAL] == 90

    # 2. Invalid poll interval raising ValueError
    flow.flow_data = {}
    errors = {}
    flow._extract_and_validate_poll_interval(
        {CONF_POLL_INTERVAL: "invalid_time"}, errors, store_when_empty=True
    )
    assert errors == {CONF_POLL_INTERVAL: "invalid_poll_interval"}
    assert CONF_POLL_INTERVAL not in flow.flow_data

    # 3. Empty string with store_when_empty=True
    flow.flow_data = {}
    errors = {}
    flow._extract_and_validate_poll_interval(
        {CONF_POLL_INTERVAL: ""}, errors, store_when_empty=True
    )
    assert errors == {}
    assert CONF_POLL_INTERVAL in flow.flow_data
    assert flow.flow_data[CONF_POLL_INTERVAL] is None

    # 4. Empty string with store_when_empty=False
    flow.flow_data = {}
    errors = {}
    flow._extract_and_validate_poll_interval(
        {CONF_POLL_INTERVAL: ""}, errors, store_when_empty=False
    )
    assert errors == {}
    assert CONF_POLL_INTERVAL not in flow.flow_data


# -----------------------------------------------------------------------------
# 7. Tests for _load_auth_flow_config
# -----------------------------------------------------------------------------


@pytest.fixture
def auth_flow_cache():
    """Provide direct access to _AUTH_FLOW_CACHE and clean up after."""
    from custom_components.climate_ip.config_flow_helpers import _AUTH_FLOW_CACHE

    _AUTH_FLOW_CACHE.clear()
    yield _AUTH_FLOW_CACHE
    _AUTH_FLOW_CACHE.clear()


@pytest.mark.asyncio
async def test_cf_helpers_load_auth_flow_config_cached(hass_mock, auth_flow_cache):
    """Test _load_auth_flow_config returns cached dictionary without disk access."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    auth_flow_cache["cached_dev"] = {"flow": "cached_flow"}
    res = await flow._load_auth_flow_config("cached_dev")
    assert res == {"flow": "cached_flow"}
    hass_mock.async_add_executor_job.assert_not_called()


@pytest.mark.asyncio
async def test_cf_helpers_load_auth_flow_config_unknown_device_type(
    hass_mock, auth_flow_cache
):
    """Test _load_auth_flow_config raises ValueError when device type has no config file mapping."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    with pytest.raises(
        ValueError, match="No configuration file mapping found for device_type"
    ):
        await flow._load_auth_flow_config("nonexistent_device_type")


@pytest.mark.asyncio
async def test_cf_helpers_load_auth_flow_config_main_config_not_dict(
    hass_mock, auth_flow_cache
):
    """Test _load_auth_flow_config raises ValueError when main yaml does not parse to dict."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    hass_mock.async_add_executor_job = AsyncMock(return_value="not_a_dict")
    with pytest.raises(ValueError, match="Invalid YAML configuration loaded from"):
        await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)


@pytest.mark.asyncio
async def test_cf_helpers_load_auth_flow_config_missing_auth_flow_file(
    hass_mock, auth_flow_cache
):
    """Test _load_auth_flow_config raises ValueError when main yaml has no auth_flow_file."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    # Case A: device not a dict
    hass_mock.async_add_executor_job = AsyncMock(return_value={"device": None})
    with pytest.raises(ValueError, match="No 'auth_flow_file' found in"):
        await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)

    # Case B: device is dict, but auth_flow_file missing or empty
    hass_mock.async_add_executor_job = AsyncMock(
        return_value={"device": {"auth_flow_file": ""}}
    )
    with pytest.raises(ValueError, match="No 'auth_flow_file' found in"):
        await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)


@pytest.mark.asyncio
async def test_cf_helpers_load_auth_flow_config_auth_config_not_dict(
    hass_mock, auth_flow_cache
):
    """Test _load_auth_flow_config raises ValueError when auth yaml does not parse to dict."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    hass_mock.async_add_executor_job = AsyncMock(
        side_effect=[
            {"device": {"auth_flow_file": "samsung_auth.yaml"}},
            "invalid_auth_yaml",
        ]
    )
    with pytest.raises(ValueError, match="Invalid YAML configuration loaded from"):
        await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)


@pytest.mark.asyncio
async def test_cf_helpers_load_auth_flow_config_success_and_fallback(
    hass_mock, auth_flow_cache
):
    """Test _load_auth_flow_config returns auth_flow dict or empty dict fallback and caches result."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    # 1. Success with dict auth_flow
    hass_mock.async_add_executor_job = AsyncMock(
        side_effect=[
            {"device": {"auth_flow_file": "samsung_2878_auth.yaml"}},
            {"auth_flow": {"pairing": "step1"}},
        ]
    )
    res = await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)
    assert res == {"pairing": "step1"}
    assert auth_flow_cache[DEVICE_TYPE_SAMSUNG_2878] == {"pairing": "step1"}
    assert hass_mock.async_add_executor_job.call_args_list[0][0][0] is load_yaml
    assert hass_mock.async_add_executor_job.call_args_list[0][0][1].endswith(
        "samsung_2878.yaml"
    )
    assert hass_mock.async_add_executor_job.call_args_list[1][0][0] is load_yaml
    assert hass_mock.async_add_executor_job.call_args_list[1][0][1].endswith(
        "samsung_2878_auth.yaml"
    )

    # 2. Success with non-dict auth_flow fallback to empty dict
    hass_mock.async_add_executor_job = AsyncMock(
        side_effect=[
            {"device": {"auth_flow_file": "samsung_8888_auth.yaml"}},
            {"auth_flow": None},
        ]
    )
    res2 = await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_8888)
    assert res2 == {}
    assert auth_flow_cache[DEVICE_TYPE_SAMSUNG_8888] == {}
    assert hass_mock.async_add_executor_job.call_args_list[0][0][0] is load_yaml
    assert hass_mock.async_add_executor_job.call_args_list[0][0][1].endswith(
        "samsungrac.yaml"
    )
    assert hass_mock.async_add_executor_job.call_args_list[1][0][0] is load_yaml
    assert hass_mock.async_add_executor_job.call_args_list[1][0][1].endswith(
        "samsung_8888_auth.yaml"
    )


# -----------------------------------------------------------------------------
# 8. Tests for _consume_completed_task
# -----------------------------------------------------------------------------


def test_cf_helpers_consume_completed_task_success():
    """Test _consume_completed_task extracts result and resets flow.task."""
    flow = ClimateIpConfigFlow()
    mock_task = MagicMock()
    mock_task.result.return_value = {"ok": True, "token": "tok"}
    flow.task = mock_task

    res = flow._consume_completed_task()
    assert res == {"ok": True, "token": "tok"}
    assert flow.task is None
    mock_task.result.assert_called_once()


def test_cf_helpers_consume_completed_task_cancelled():
    """Test _consume_completed_task re-raises asyncio.CancelledError."""
    flow = ClimateIpConfigFlow()
    mock_task = MagicMock()
    mock_task.result.side_effect = asyncio.CancelledError()
    flow.task = mock_task

    with pytest.raises(asyncio.CancelledError):
        flow._consume_completed_task()


def test_cf_helpers_consume_completed_task_exception():
    """Test _consume_completed_task catches exceptions and returns unknown_error."""
    flow = ClimateIpConfigFlow()
    mock_task = MagicMock()
    mock_task.result.side_effect = RuntimeError("task crash")
    flow.task = mock_task

    res = flow._consume_completed_task()
    assert res == {"ok": False, "error": "unknown_error"}
    assert flow.task is None


# -----------------------------------------------------------------------------
# 9. Tests for _async_process_import
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_process_import_no_mac_aborts(hass_mock):
    """Test _async_process_import aborts when no MAC address is provided."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    res = await flow._async_process_import({CONF_IP_ADDRESS: "1.2.3.4"})
    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "no_mac_address_found"


@pytest.mark.asyncio
async def test_cf_helpers_process_import_success_with_inferred_device_type(hass_mock):
    """Test _async_process_import formats MAC, infers device type, tests connection, and creates entry."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(
            flow, "_test_connection_safe", new_callable=AsyncMock
        ) as mock_test_conn,
    ):
        mock_test_conn.return_value = {"ok": True}

        user_input = {
            CONF_IP_ADDRESS: "10.0.0.5",
            CONF_MAC: "aa:bb:cc:dd:ee:ff",
            CONF_CONFIG_FILE: "samsung_2878.yaml",
            CONFIG_DEVICE_NAME: "Living AC",
        }
        res = await flow._async_process_import(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert res["title"] == "Living AC"
        assert res["data"][CONF_MAC] == "AA:BB:CC:DD:EE:FF"
        assert res["data"][CONF_DEVICE_TYPE] == DEVICE_TYPE_SAMSUNG_2878
        mock_set_id.assert_called_once_with("AA:BB:CC:DD:EE:FF")
        mock_abort_if.assert_called_once()
        mock_test_conn.assert_called_once()


@pytest.mark.asyncio
async def test_cf_helpers_process_import_unknown_config_file_and_default_title(
    hass_mock,
):
    """Test _async_process_import handles unknown config file and sets default device title."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow, "_test_connection_safe", new_callable=AsyncMock
        ) as mock_test_conn,
    ):
        mock_test_conn.return_value = {"ok": True}

        user_input = {
            CONF_IP_ADDRESS: "10.0.0.6",
            CONF_MAC: "11:22:33:44:55:66",
            CONF_CONFIG_FILE: "custom_unmapped.yaml",
        }
        res = await flow._async_process_import(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert res["title"] == "Climate 11:22:33:44:55:66"
        assert CONF_DEVICE_TYPE not in res["data"]
        mock_test_conn.assert_not_called()


@pytest.mark.asyncio
async def test_cf_helpers_process_import_connection_fails_aborts(hass_mock):
    """Test _async_process_import aborts when connection test returns not ok."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow, "_test_connection_safe", new_callable=AsyncMock
        ) as mock_test_conn,
    ):
        mock_test_conn.return_value = {"ok": False}

        user_input = {
            CONF_IP_ADDRESS: "10.0.0.7",
            CONF_MAC: "11:22:33:44:55:66",
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        }
        res = await flow._async_process_import(user_input)

        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "cannot_connect"


# -----------------------------------------------------------------------------
# 10. Tests for _async_process_samsung_device_step
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_none_input(hass_mock):
    """Test _async_process_samsung_device_step returns form when user_input is None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow, "_get_samsung_2878_schema", return_value="schema_2878"
        ) as mock_2878,
        patch.object(
            flow, "_get_samsung_8888_schema", return_value="schema_8888"
        ) as mock_8888,
    ):
        res_2878 = await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input=None
        )
        assert res_2878["type"] == FlowResultType.FORM
        assert res_2878["step_id"] == "samsung_2878"
        assert res_2878["errors"] == {}
        mock_2878.assert_called_once_with(mac_required=False)

        res_8888 = await flow._async_process_samsung_device_step(
            "samsung_8888", is_8888=True, user_input=None
        )
        assert res_8888["type"] == FlowResultType.FORM
        assert res_8888["step_id"] == "samsung_8888"
        assert res_8888["errors"] == {}
        mock_8888.assert_called_once_with(mac_required=False)


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_mac_resolve_failed(hass_mock):
    """Test _async_process_samsung_device_step shows form with required MAC when resolution fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value="mac_resolve_failed",
        ) as mock_resolve,
        patch.object(
            flow, "_get_samsung_2878_schema", return_value="schema_2878"
        ) as mock_schema,
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_MAC: "AA:BB:CC:DD:EE:FF"}
        res = await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input=user_input
        )

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "samsung_2878"
        assert res["errors"] == {"base": "mac_resolve_failed"}
        mock_resolve.assert_called_once_with(
            ip_address="1.2.3.4", mac_address="AA:BB:CC:DD:EE:FF"
        )
        mock_schema.assert_called_once_with(mac_required=True)


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_mac_other_error(hass_mock):
    """Test _async_process_samsung_device_step shows form with mac_required=False on other resolve error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value="cannot_connect",
        ),
        patch.object(
            flow, "_get_samsung_2878_schema", return_value="schema_2878"
        ) as mock_schema,
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4"}
        res = await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input=user_input
        )

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "samsung_2878"
        assert res["errors"] == {"base": "cannot_connect"}
        mock_schema.assert_called_once_with(mac_required=False)


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_poll_interval_error(hass_mock):
    """Test _async_process_samsung_device_step returns form on invalid poll interval."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow, "_get_samsung_2878_schema", return_value="schema_2878"
        ) as mock_schema,
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_POLL_INTERVAL: "invalid"}
        res = await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input=user_input
        )

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "samsung_2878"
        assert res["data_schema"] == "schema_2878"
        assert res["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"
        mock_schema.assert_called_once_with(mac_required=False)


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_token_present(hass_mock):
    """Test _async_process_samsung_device_step advances to test connection when token is provided."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow, "async_step_test_connection", new_callable=AsyncMock
        ) as mock_test_step,
    ):
        mock_test_step.return_value = {
            "type": FlowResultType.SHOW_PROGRESS,
            "step_id": "test_connection",
        }
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_TOKEN: "tok123"}
        res = await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input=user_input
        )

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        mock_test_step.assert_called_once()


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_invalid_cert(hass_mock):
    """Test _async_process_samsung_device_step returns form with cert_not_found error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow,
            "_async_validate_cert_path",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_val_cert,
        patch.object(
            flow, "_get_samsung_8888_schema", return_value="schema_8888"
        ) as mock_schema,
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_CERT: "missing.pem"}
        res = await flow._async_process_samsung_device_step(
            "samsung_8888", is_8888=True, user_input=user_input
        )

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "samsung_8888"
        assert res["data_schema"] == "schema_8888"
        assert res["errors"] == {"base": "cert_not_found"}
        mock_val_cert.assert_called_once_with("missing.pem")
        mock_schema.assert_called_once_with(mac_required=False)


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_pairing_init(hass_mock):
    """Test _async_process_samsung_device_step configures acquirer and advances to pairing."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow, "_async_validate_cert_path", new_callable=AsyncMock, return_value=True
        ),
        patch.object(
            flow,
            "_load_auth_flow_config",
            new_callable=AsyncMock,
            return_value={"auth": "cfg"},
        ) as mock_load_auth,
        patch.object(
            flow, "async_step_initiate_pairing", new_callable=AsyncMock
        ) as mock_pair_step,
    ):
        mock_pair_step.return_value = {
            "type": FlowResultType.SHOW_PROGRESS,
            "step_id": "initiate_pairing",
        }
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_CERT: "valid.pem"}
        res = await flow._async_process_samsung_device_step(
            "samsung_8888", is_8888=True, user_input=user_input
        )

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        mock_pair_step.assert_called_once()
        mock_load_auth.assert_called_once_with(DEVICE_TYPE_SAMSUNG_8888)
        assert flow.acquirer is not None
        assert flow.acquirer.user_cert_path == "valid.pem"
        assert flow.acquirer.auth_config == {"auth": "cfg"}
        assert flow.acquirer.ip_address == "1.2.3.4"
        assert flow.acquirer.hass is hass_mock


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_pairing_init_2878(hass_mock):
    """Test _async_process_samsung_device_step configures 2878 acquirer without cert."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow,
            "_load_auth_flow_config",
            new_callable=AsyncMock,
            return_value={"auth": "2878_cfg"},
        ) as mock_load_auth,
        patch.object(
            flow, "async_step_initiate_pairing", new_callable=AsyncMock
        ) as mock_pair_step,
    ):
        mock_pair_step.return_value = {
            "type": FlowResultType.SHOW_PROGRESS,
            "step_id": "initiate_pairing",
        }
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_POLL_INTERVAL: ""}
        res = await flow._async_process_samsung_device_step(
            "samsung_2878", is_8888=False, user_input=user_input
        )

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        mock_pair_step.assert_called_once()
        mock_load_auth.assert_called_once_with(DEVICE_TYPE_SAMSUNG_2878)
        assert flow.acquirer is not None
        assert flow.acquirer.user_cert_path is None
        assert flow.acquirer.auth_config == {"auth": "2878_cfg"}
        assert flow.flow_data[CONF_POLL_INTERVAL] is None


@pytest.mark.asyncio
async def test_cf_helpers_process_samsung_device_step_pairing_init_custom_device_type(
    hass_mock,
):
    """Test _async_process_samsung_device_step uses existing CONF_DEVICE_TYPE from flow_data."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: "custom_samsung_type"}

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow,
            "_load_auth_flow_config",
            new_callable=AsyncMock,
            return_value={"auth": "custom_cfg"},
        ) as mock_load_auth,
        patch.object(
            flow, "async_step_initiate_pairing", new_callable=AsyncMock
        ) as mock_pair_step,
    ):
        mock_pair_step.return_value = {
            "type": FlowResultType.SHOW_PROGRESS,
            "step_id": "initiate_pairing",
        }
        user_input = {CONF_IP_ADDRESS: "1.2.3.4"}
        res = await flow._async_process_samsung_device_step(
            "samsung_8888", is_8888=True, user_input=user_input
        )

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        mock_pair_step.assert_called_once()
        mock_load_auth.assert_called_once_with("custom_samsung_type")


# -----------------------------------------------------------------------------
# 11. Tests for _async_process_intesisbox_input
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_process_intesisbox_input_poll_interval_error(hass_mock):
    """Test _async_process_intesisbox_input returns form on poll interval error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with patch.object(flow, "_get_intesisbox_schema", return_value="schema_intesis"):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_POLL_INTERVAL: "invalid"}
        res = await flow._async_process_intesisbox_input(user_input)

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "intesisbox"
        assert res["data_schema"] == "schema_intesis"
        assert res["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"


@pytest.mark.asyncio
async def test_cf_helpers_process_intesisbox_input_probe_cannot_connect(hass_mock):
    """Test _async_process_intesisbox_input sets error when async_probe raises CannotConnect."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.connection_intesisbox.ConnectionIntesisBox.async_probe",
            side_effect=CannotConnect("fail"),
        ),
        patch.object(flow, "_get_intesisbox_schema", return_value="schema_intesis"),
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4"}
        res = await flow._async_process_intesisbox_input(user_input)

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "intesisbox"
        assert res["data_schema"] == "schema_intesis"
        assert res["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_cf_helpers_process_intesisbox_input_resolve_mac_error(hass_mock):
    """Test _async_process_intesisbox_input returns error when MAC resolution fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.connection_intesisbox.ConnectionIntesisBox.async_probe",
            return_value="00:11:22:33:44:55",
        ),
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value="mac_resolve_failed",
        ),
        patch.object(flow, "_get_intesisbox_schema", return_value="schema_intesis"),
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4"}
        res = await flow._async_process_intesisbox_input(user_input)

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "intesisbox"
        assert res["data_schema"] == "schema_intesis"
        assert res["errors"]["base"] == "mac_resolve_failed"


@pytest.mark.asyncio
async def test_cf_helpers_process_intesisbox_input_success(hass_mock):
    """Test _async_process_intesisbox_input sets config and creates entry on success."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.connection_intesisbox.ConnectionIntesisBox.async_probe",
            return_value="00:11:22:33:44:55",
        ) as mock_probe,
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_resolve,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
    ):
        user_input = {CONF_IP_ADDRESS: "192.168.1.80", CONF_POLL_INTERVAL: ""}
        res = await flow._async_process_intesisbox_input(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert res["title"] == "IntesisBox (192.168.1.80)"
        assert flow.flow_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_INTESISBOX
        assert (
            flow.flow_data[CONF_CONFIG_FILE]
            == DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_INTESISBOX]
        )
        assert flow.flow_data[CONF_NAME] == "IntesisBox (192.168.1.80)"
        assert flow.flow_data[CONF_POLL_INTERVAL] == ""
        mock_probe.assert_called_once_with("192.168.1.80")
        mock_resolve.assert_called_once_with(
            ip_address="192.168.1.80", mac_address="00:11:22:33:44:55"
        )
        mock_abort_if.assert_called_once()


@pytest.mark.asyncio
async def test_cf_helpers_process_intesisbox_input_with_provided_mac(hass_mock):
    """Test _async_process_intesisbox_input uses provided MAC and does not overwrite it with probed MAC."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.connection_intesisbox.ConnectionIntesisBox.async_probe",
            return_value="00:11:22:33:44:55",
        ) as mock_probe,
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_resolve,
        patch.object(flow, "_abort_if_unique_id_configured"),
    ):
        user_input = {CONF_IP_ADDRESS: "192.168.1.80", CONF_MAC: "AA:BB:CC:DD:EE:FF"}
        res = await flow._async_process_intesisbox_input(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_probe.assert_called_once_with("192.168.1.80")
        mock_resolve.assert_called_once_with(
            ip_address="192.168.1.80", mac_address="AA:BB:CC:DD:EE:FF"
        )
        assert CONF_POLL_INTERVAL not in flow.flow_data
        assert flow.flow_data[CONF_TOKEN] == "AA:BB:CC:DD:EE:FF"


@pytest.mark.asyncio
async def test_cf_helpers_process_intesisbox_input_no_mac_fallback_token(hass_mock):
    """Test _async_process_intesisbox_input falls back to 'intesisbox' as token when no MAC available."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.connection_intesisbox.ConnectionIntesisBox.async_probe",
            return_value=None,
        ),
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_resolve,
        patch.object(flow, "_abort_if_unique_id_configured"),
    ):
        user_input = {CONF_IP_ADDRESS: "192.168.1.80", CONF_POLL_INTERVAL: ""}
        res = await flow._async_process_intesisbox_input(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_resolve.assert_called_once_with(
            ip_address="192.168.1.80", mac_address=None
        )
        assert flow.flow_data[CONF_TOKEN] == "intesisbox"
        assert flow.flow_data[CONF_POLL_INTERVAL] == ""


# -----------------------------------------------------------------------------
# 12. Tests for _async_process_rest_api_input
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_invalid_token(hass_mock):
    """Test _async_process_rest_api_input shows form on invalid token format."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch("custom_components.climate_ip.helpers.sanitize_token", return_value=""),
        patch.object(flow, "_get_rest_api_schema", return_value="schema_rest"),
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_TOKEN: "invalid_tok"}
        res = await flow._async_process_rest_api_input(user_input)

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "rest_api"
        assert res["data_schema"] == "schema_rest"
        assert res["errors"][CONF_TOKEN] == "invalid_token_format"


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_poll_interval_error(hass_mock):
    """Test _async_process_rest_api_input shows form on invalid poll interval."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.helpers.sanitize_token",
            return_value="cleantok",
        ),
        patch.object(flow, "_get_rest_api_schema", return_value="schema_rest"),
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.2.3.4",
            CONF_TOKEN: "cleantok",
            CONF_POLL_INTERVAL: "invalid",
        }
        res = await flow._async_process_rest_api_input(user_input)

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "rest_api"
        assert res["data_schema"] == "schema_rest"
        assert res["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_st_discovered_device_id(hass_mock):
    """Test _async_process_rest_api_input sets discovered device_id and creates entry."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    flow.reauth_entry = None

    with (
        patch(
            "custom_components.climate_ip.connection_aiohttp.ConnectionAiohttp8888.async_validate_rest_device",
            new_callable=AsyncMock,
            return_value="st_disc_id",
        ) as mock_val,
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ) as mock_create,
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.2.3.4",
            CONF_TOKEN: "validtok123",
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_POLL_INTERVAL: "",
        }
        res = await flow._async_process_rest_api_input(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data[CONF_DEVICE_ID] == "st_disc_id"
        assert flow.flow_data["unique_id"] == "st_disc_id"
        assert (
            flow.flow_data[CONF_CONFIG_FILE]
            == DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_SMARTTHINGS_HVAC]
        )
        assert flow.flow_data[CONF_POLL_INTERVAL] is None
        mock_val.assert_called_once_with(
            hass_mock, "1.2.3.4", "validtok123", fetch_device_id=True
        )
        mock_set_id.assert_called_once_with("st_disc_id")
        mock_abort_if.assert_called_once()
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_st_unique_id_fallback(hass_mock):
    """Test _async_process_rest_api_input generates unique_id fallback from token suffix."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW}
    flow.reauth_entry = None

    with (
        patch(
            "custom_components.climate_ip.connection_aiohttp.ConnectionAiohttp8888.async_validate_rest_device",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ),
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.2.3.4",
            CONF_TOKEN: "12345678tok",
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW,
        }
        res = await flow._async_process_rest_api_input(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data["unique_id"] == f"{DEVICE_TYPE_SMARTTHINGS_DHW}_45678tok"


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_st_with_existing_device_id_skips_fetch(
    hass_mock,
):
    """Test _async_process_rest_api_input passes fetch_device_id=False when device_id already in flow_data."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_ID: "already_have_dev_id"}
    flow.reauth_entry = None

    with (
        patch(
            "custom_components.climate_ip.connection_aiohttp.ConnectionAiohttp8888.async_validate_rest_device",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_val,
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ),
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.2.3.4",
            CONF_TOKEN: "validtok123",
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_POLL_INTERVAL: "",
        }
        res = await flow._async_process_rest_api_input(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_val.assert_called_once_with(
            hass_mock, "1.2.3.4", "validtok123", fetch_device_id=False
        )


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_non_st_no_mac_aborts(hass_mock):
    """Test _async_process_rest_api_input aborts when non-ST device has no MAC or device_id."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with patch(
        "custom_components.climate_ip.connection_aiohttp.ConnectionAiohttp8888.async_validate_rest_device",
        new_callable=AsyncMock,
        return_value=None,
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.2.3.4",
            CONF_TOKEN: "validtok123",
            CONF_DEVICE_TYPE: "generic_rest",
        }
        res = await flow._async_process_rest_api_input(user_input)

        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "no_mac_address_found"


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_non_st_with_mac_creates_entry(
    hass_mock,
):
    """Test _async_process_rest_api_input succeeds for non-ST device when MAC is provided."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW}
    flow.reauth_entry = None

    with (
        patch(
            "custom_components.climate_ip.connection_aiohttp.ConnectionAiohttp8888.async_validate_rest_device",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(
            flow,
            "_create_entry",
            new_callable=AsyncMock,
            return_value={"type": FlowResultType.CREATE_ENTRY},
        ) as mock_create,
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.2.3.4",
            CONF_TOKEN: "validtok123",
            CONF_MAC: "00:11:22:33:44:55",
            CONF_DEVICE_TYPE: "generic_rest",
        }
        res = await flow._async_process_rest_api_input(user_input)

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data["unique_id"] == "00:11:22:33:44:55"
        mock_set_id.assert_called_once_with("00:11:22:33:44:55")
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_cannot_connect_shows_form(hass_mock):
    """Test _async_process_rest_api_input shows form with cannot_connect on CannotConnect."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with (
        patch(
            "custom_components.climate_ip.connection_aiohttp.ConnectionAiohttp8888.async_validate_rest_device",
            side_effect=CannotConnect("down"),
        ),
        patch.object(flow, "_get_rest_api_schema", return_value="schema_rest"),
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_TOKEN: "validtok"}
        res = await flow._async_process_rest_api_input(user_input)

        assert res["type"] == FlowResultType.FORM
        assert res["step_id"] == "rest_api"
        assert res["data_schema"] == "schema_rest"
        assert res["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_cf_helpers_process_rest_api_input_abort_flow_reraised(hass_mock):
    """Test _async_process_rest_api_input re-raises AbortFlow directly."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with patch(
        "custom_components.climate_ip.connection_aiohttp.ConnectionAiohttp8888.async_validate_rest_device",
        side_effect=AbortFlow("already_configured"),
    ):
        user_input = {CONF_IP_ADDRESS: "1.2.3.4", CONF_TOKEN: "validtok"}
        with pytest.raises(AbortFlow):
            await flow._async_process_rest_api_input(user_input)


# -----------------------------------------------------------------------------
# 13. Tests for _async_run_progress_step
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_run_progress_step_starts_task_and_shows_progress(hass_mock):
    """Test _async_run_progress_step creates background task and returns show_progress."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.task = None

    mock_task = MagicMock()
    mock_task.done.return_value = False
    hass_mock.async_create_task.return_value = mock_task

    async def sample_coro():
        return {"ok": True}

    res = await flow._async_run_progress_step(
        step_id="step_x",
        progress_action="acting_x",
        coro_factory=sample_coro,
        on_complete=AsyncMock(),
        description_placeholders=lambda: {"k": "v"},
    )

    assert res["type"] == FlowResultType.SHOW_PROGRESS
    assert res["step_id"] == "step_x"
    assert res["progress_action"] == "acting_x"
    assert res["description_placeholders"] == {"k": "v"}
    hass_mock.async_create_task.assert_called_once()
    passed_coro = hass_mock.async_create_task.call_args[0][0]
    assert inspect.iscoroutine(passed_coro)
    await passed_coro


@pytest.mark.asyncio
async def test_cf_helpers_run_progress_step_done_task_consumes_and_calls_complete(
    hass_mock,
):
    """Test _async_run_progress_step calls on_complete when task is done."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    mock_task = MagicMock()
    mock_task.done.return_value = True
    flow.task = mock_task

    mock_on_complete = AsyncMock(return_value={"type": FlowResultType.CREATE_ENTRY})

    with patch.object(
        flow, "_consume_completed_task", return_value={"ok": True}
    ) as mock_consume:
        res = await flow._async_run_progress_step(
            step_id="step_y",
            progress_action="acting_y",
            coro_factory=AsyncMock(),
            on_complete=mock_on_complete,
            description_placeholders={"k": "v"},
        )

        assert res["type"] == FlowResultType.CREATE_ENTRY
        mock_consume.assert_called_once()
        mock_on_complete.assert_called_once_with({"ok": True})


# -----------------------------------------------------------------------------
# 14. Tests for async step wrappers (_async_step_initiate_pairing, _async_step_await_button, _async_step_test_connection)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_step_initiate_pairing_no_acquirer_aborts(hass_mock):
    """Test _async_step_initiate_pairing aborts if acquirer is None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.acquirer = None

    res = await flow._async_step_initiate_pairing()
    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "flow_state_lost"


@pytest.mark.asyncio
async def test_cf_helpers_step_initiate_pairing_delegates(hass_mock):
    """Test _async_step_initiate_pairing runs progress step with initiate_pairing_safe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.acquirer = MagicMock()

    with patch.object(
        flow, "_async_run_progress_step", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = {"type": FlowResultType.SHOW_PROGRESS}
        res = await flow._async_step_initiate_pairing()

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        mock_run.assert_called_once_with(
            step_id="initiate_pairing",
            progress_action="initiating_pairing",
            coro_factory=flow._initiate_pairing_safe,
            on_complete=flow._async_handle_initiate_pairing_result,
        )


@pytest.mark.asyncio
async def test_cf_helpers_step_await_button_no_acquirer_aborts(hass_mock):
    """Test _async_step_await_button aborts if acquirer is None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.acquirer = None

    res = await flow._async_step_await_button()
    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "flow_state_lost"


@pytest.mark.asyncio
async def test_cf_helpers_step_await_button_delegates(hass_mock):
    """Test _async_step_await_button runs progress step with wait_token_safe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.acquirer = MagicMock()
    flow.flow_data = {CONF_IP_ADDRESS: "1.2.3.4"}

    with patch.object(
        flow, "_async_run_progress_step", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = {"type": FlowResultType.SHOW_PROGRESS}
        res = await flow._async_step_await_button()

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["step_id"] == "await_button"
        assert mock_run.call_args.kwargs["progress_action"] == "awaiting_button_press"
        ph_func = mock_run.call_args.kwargs["description_placeholders"]
        assert ph_func() == {"ip_address": "1.2.3.4"}
        flow.flow_data.clear()
        assert ph_func() == {"ip_address": ""}


@pytest.mark.asyncio
async def test_cf_helpers_step_test_connection_delegates(hass_mock):
    """Test _async_step_test_connection runs progress step with test_connection_safe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_IP_ADDRESS: "10.0.0.1"}

    with patch.object(
        flow, "_async_run_progress_step", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = {"type": FlowResultType.SHOW_PROGRESS}
        res = await flow._async_step_test_connection()

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["step_id"] == "test_connection"
        assert mock_run.call_args.kwargs["progress_action"] == "testing_connection"
        ph_func = mock_run.call_args.kwargs["description_placeholders"]
        assert ph_func() == {"ip_address": "10.0.0.1"}
        flow.flow_data.clear()
        assert ph_func() == {"ip_address": ""}


# -----------------------------------------------------------------------------
# 15. Tests for _async_handle_initiate_pairing_result and _async_attempt_pairing_fallback
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_handle_initiate_pairing_result_success(hass_mock):
    """Test _async_handle_initiate_pairing_result advances to await_button on success."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    result = {"ok": True, "config": {"port": 8888}}
    res = await flow._async_handle_initiate_pairing_result(result)

    assert res["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert res["step_id"] == "await_button"
    assert flow.flow_data["preferred_connection"] == {"port": 8888}


@pytest.mark.asyncio
async def test_cf_helpers_handle_initiate_pairing_result_calls_fallback(hass_mock):
    """Test _async_handle_initiate_pairing_result calls fallback when result is not ok."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    with patch.object(
        flow, "_async_attempt_pairing_fallback", new_callable=AsyncMock
    ) as mock_fb:
        mock_fb.return_value = {
            "type": FlowResultType.SHOW_PROGRESS_DONE,
            "step_id": "handle_error",
        }
        res = await flow._async_handle_initiate_pairing_result(
            {"ok": False, "error": "conn_fail"}
        )

        assert res["step_id"] == "handle_error"
        mock_fb.assert_called_once_with({"ok": False, "error": "conn_fail"})


@pytest.mark.asyncio
async def test_cf_helpers_attempt_pairing_fallback_from_2878_to_8888(hass_mock):
    """Test _async_attempt_pairing_fallback switches from 2878 to 8888 and recreates acquirer."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.2.3.4",
        CONF_CERT: "user_cert.pem",
    }
    mock_acquirer = AsyncMock()
    flow.acquirer = mock_acquirer

    with (
        patch.object(
            flow,
            "_load_auth_flow_config",
            new_callable=AsyncMock,
            return_value={"auth": "8888"},
        ) as mock_load_auth,
        patch.object(flow, "_initiate_pairing_safe", new_callable=AsyncMock),
    ):
        mock_task = MagicMock()
        hass_mock.async_create_task.return_value = mock_task

        res = await flow._async_attempt_pairing_fallback({"ok": False})

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        assert res["step_id"] == "initiate_pairing"
        assert flow.flow_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_SAMSUNG_8888
        assert flow.flow_data[CONF_CERT] == "user_cert.pem"
        assert flow.flow_data["_fallback_attempted"] is True
        mock_acquirer.async_close.assert_called_once()
        mock_load_auth.assert_called_once_with(DEVICE_TYPE_SAMSUNG_8888)
        assert flow.acquirer is not None
        assert flow.acquirer.hass is hass_mock
        assert flow.acquirer.auth_config == {"auth": "8888"}
        assert flow.acquirer.user_cert_path == "user_cert.pem"


@pytest.mark.asyncio
async def test_cf_helpers_attempt_pairing_fallback_from_8888_to_2878(hass_mock):
    """Test _async_attempt_pairing_fallback switches from 8888 to 2878."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.2.3.4",
        CONF_CERT: "custom_cert.pem",
    }
    flow.acquirer = None

    with (
        patch.object(
            flow,
            "_load_auth_flow_config",
            new_callable=AsyncMock,
            return_value={"auth": "2878"},
        ) as mock_load_auth,
        patch.object(flow, "_initiate_pairing_safe", new_callable=AsyncMock),
    ):
        mock_task = MagicMock()
        hass_mock.async_create_task.return_value = mock_task

        res = await flow._async_attempt_pairing_fallback({"ok": False})

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        assert flow.flow_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_SAMSUNG_2878
        assert flow.flow_data["_fallback_attempted"] is True
        mock_load_auth.assert_called_once_with(DEVICE_TYPE_SAMSUNG_2878)
        assert flow.acquirer is not None
        assert flow.acquirer.hass is hass_mock
        assert flow.acquirer.auth_config == {"auth": "2878"}
        assert flow.acquirer.user_cert_path == "custom_cert.pem"


@pytest.mark.asyncio
async def test_cf_helpers_attempt_pairing_fallback_already_attempted(hass_mock):
    """Test _async_attempt_pairing_fallback routes to handle_error when fallback already attempted."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {"_fallback_attempted": True}

    res = await flow._async_attempt_pairing_fallback(
        {
            "ok": False,
            "error": "pairing_connection_failed",
            "error_details": "port unreachable",
        }
    )

    assert res["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert res["step_id"] == "handle_error"
    assert flow.flow_data["error_key"] == "pairing_connection_failed"
    assert flow.flow_data["error_details"] == "port unreachable"

    # Also test when result does not contain "error"
    res_no_err = await flow._async_attempt_pairing_fallback({"ok": False})
    assert res_no_err["step_id"] == "handle_error"
    assert flow.flow_data["error_key"] == "unknown_error"


# -----------------------------------------------------------------------------
# 16. Tests for _async_handle_acquired_token and _async_handle_test_connection_result
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_handle_acquired_token_rejected_by_sanitizer(hass_mock):
    """Test _async_handle_acquired_token routes to handle_error if token sanitizer rejects token."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    with patch("custom_components.climate_ip.helpers.sanitize_token", return_value=""):
        res = await flow._async_handle_acquired_token(
            {"ok": True, "token": "malformed_token"}
        )

        assert res["type"] == FlowResultType.SHOW_PROGRESS_DONE
        assert res["step_id"] == "handle_error"
        assert flow.flow_data["error_key"] == "token_acquisition_failed"


@pytest.mark.asyncio
async def test_cf_helpers_handle_acquired_token_2878_advances_to_test_connection(
    hass_mock,
):
    """Test _async_handle_acquired_token routes 2878 to test_connection."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    res = await flow._async_handle_acquired_token(
        {"ok": True, "token": "valid_token_123"}
    )

    assert res["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert res["step_id"] == "test_connection"
    assert flow.flow_data[CONF_TOKEN] == "valid_token_123"

    # Also test empty/missing token routes to handle_error and passes empty string to sanitize_token
    with patch(
        "custom_components.climate_ip.helpers.sanitize_token", return_value=""
    ) as mock_sanitize:
        res_empty = await flow._async_handle_acquired_token({"ok": True})
        assert res_empty["step_id"] == "handle_error"
        assert flow.flow_data["error_key"] == "token_acquisition_failed"
        mock_sanitize.assert_called_once_with("")


@pytest.mark.asyncio
async def test_cf_helpers_handle_acquired_token_8888_advances_to_discover_uuid(
    hass_mock,
):
    """Test _async_handle_acquired_token routes 8888 to discover_uuid."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}

    res = await flow._async_handle_acquired_token(
        {"ok": True, "token": "valid_token_123"}
    )

    assert res["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert res["step_id"] == "discover_uuid"
    assert flow.flow_data[CONF_TOKEN] == "valid_token_123"


@pytest.mark.asyncio
async def test_cf_helpers_handle_acquired_token_error(hass_mock):
    """Test _async_handle_acquired_token sets error details on failure."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {}

    res = await flow._async_handle_acquired_token(
        {
            "ok": False,
            "error": "token_timeout",
            "error_details": "button was not pressed",
        }
    )

    assert res["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert res["step_id"] == "handle_error"
    assert flow.flow_data["error_key"] == "token_timeout"
    assert flow.flow_data["error_details"] == "button was not pressed"


@pytest.mark.asyncio
async def test_cf_helpers_handle_test_connection_result_ok(hass_mock):
    """Test _async_handle_test_connection_result routes correctly on success."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    # 1. Non-2878 without device_id -> discover_uuid
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    res1 = await flow._async_handle_test_connection_result({"ok": True})
    assert res1["step_id"] == "discover_uuid"

    # 2. Non-2878 with device_id -> create_entry
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        "device_id": "uuid_dev",
    }
    res2 = await flow._async_handle_test_connection_result({"ok": True})
    assert res2["step_id"] == "create_entry"

    # 3. 2878 -> create_entry
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    res3 = await flow._async_handle_test_connection_result({"ok": True})
    assert res3["step_id"] == "create_entry"


@pytest.mark.asyncio
async def test_cf_helpers_handle_test_connection_result_failure(hass_mock):
    """Test _async_handle_test_connection_result clears token and routes to handle_error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_TOKEN: "invalid_tok"}

    res = await flow._async_handle_test_connection_result(
        {"ok": False, "error": "invalid_auth"}
    )
    assert res["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert res["step_id"] == "handle_error"
    assert flow.flow_data["error_key"] == "invalid_auth"
    assert CONF_TOKEN not in flow.flow_data

    # Also test when CONF_TOKEN is absent from flow_data and result has no error
    flow.flow_data = {}
    res2 = await flow._async_handle_test_connection_result({"ok": False})
    assert res2["step_id"] == "handle_error"
    assert flow.flow_data["error_key"] == "cannot_connect"
    assert CONF_TOKEN not in flow.flow_data


# -----------------------------------------------------------------------------
# 17. Tests for _async_build_error_step_result
# -----------------------------------------------------------------------------


def test_cf_helpers_build_error_step_result_pairing_connection_failed_aborts():
    """Test _async_build_error_step_result aborts on fatal pairing_connection_failed."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        "error_key": "pairing_connection_failed",
        "error_details": "Connection refused",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.10",
    }

    res = flow._async_build_error_step_result()
    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "pairing_connection_failed"
    assert res["description_placeholders"] == {
        "ip_address": "192.168.1.10",
        "error_details": "Connection refused",
    }


def test_cf_helpers_build_error_step_result_mim_h03_and_samsung_8888():
    """Test _async_build_error_step_result shows correct step_id and schema for 8888/mim_h03."""
    flow = ClimateIpConfigFlow()

    # 1. MIM-H03 with mac_resolve_failed
    flow.flow_data = {
        "error_key": "mac_resolve_failed",
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
    }
    with patch.object(
        flow, "_get_samsung_8888_schema", return_value="schema_8888"
    ) as mock_schema:
        res1 = flow._async_build_error_step_result()
        assert res1["type"] == FlowResultType.FORM
        assert res1["step_id"] == "mim_h03"
        assert res1["errors"]["base"] == "mac_resolve_failed"
        mock_schema.assert_called_once_with(mac_required=True)

    # 2. Samsung 8888 with timeout_connect
    flow.flow_data = {
        "error_key": "timeout_connect",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "10.0.0.2",
    }
    with patch.object(
        flow, "_get_samsung_8888_schema", return_value="schema_8888"
    ) as mock_8888:
        res2 = flow._async_build_error_step_result()
        assert res2["type"] == FlowResultType.FORM
        assert res2["step_id"] == "samsung_8888"
        assert res2["errors"][CONF_IP_ADDRESS] == "timeout_connect"
        mock_8888.assert_called_once_with(mac_required=False)

    # 3. Samsung 2878 with invalid_auth
    flow.flow_data = {
        "error_key": "invalid_auth",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
    }
    with patch.object(
        flow, "_get_samsung_2878_schema", return_value="schema_2878"
    ) as mock_2878:
        res3 = flow._async_build_error_step_result()
        assert res3["type"] == FlowResultType.FORM
        assert res3["step_id"] == "samsung_2878"
        assert res3["errors"]["base"] == "invalid_auth"
        mock_2878.assert_called_once_with(mac_required=False)
        assert res3["errors"]["base"] == "invalid_auth"

    # 4. Samsung 2878 with fallback error_key
    flow.flow_data = {
        "error_key": "unknown_failure",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
    }
    with patch.object(flow, "_get_samsung_2878_schema", return_value="schema_2878"):
        res4 = flow._async_build_error_step_result()
        assert res4["type"] == FlowResultType.FORM
        assert res4["step_id"] == "samsung_2878"
        assert res4["errors"]["base"] == "unknown_failure"


# -----------------------------------------------------------------------------
# 18. Tests for _create_entry
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_create_entry_no_unique_id_non_st_aborts():
    """Test _create_entry aborts with no_mac_address_found when unique_id is missing for standard AC."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    res = await flow._create_entry()
    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "no_mac_address_found"


@pytest.mark.asyncio
async def test_cf_helpers_create_entry_st_generates_unique_id_and_title():
    """Test _create_entry generates unique_id and title for SmartThings devices."""
    flow = ClimateIpConfigFlow()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort_if,
    ):
        flow.flow_data = {
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_DEVICE_ID: "st_custom_id",
            CONF_DISCOVERED_DEVICES: ["temp_dev"],
        }
        res = await flow._create_entry()

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert res["title"] == "Samsung Smartthings Hvac"
        assert (
            flow.flow_data["unique_id"]
            == f"{DEVICE_TYPE_SMARTTHINGS_HVAC}_st_custom_id"
        )
        assert CONF_DISCOVERED_DEVICES not in res["data"]
        mock_set_id.assert_called_once_with(
            f"{DEVICE_TYPE_SMARTTHINGS_HVAC}_st_custom_id"
        )
        mock_abort_if.assert_called_once()


@pytest.mark.asyncio
async def test_cf_helpers_create_entry_st_fallback_token_and_default():
    """Test _create_entry fallbacks for SmartThings unique_id from token suffix or ip or default."""
    flow = ClimateIpConfigFlow()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured"),
    ):
        # Case 1: from token with length exactly 8
        flow.flow_data = {
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW,
            CONF_TOKEN: "12345678",
        }
        await flow._create_entry()
        assert flow.flow_data["unique_id"] == f"{DEVICE_TYPE_SMARTTHINGS_DHW}_12345678"

        # Case 2: from ip
        flow.flow_data = {
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW,
            CONF_IP_ADDRESS: "10.0.0.9",
        }
        await flow._create_entry()
        assert flow.flow_data["unique_id"] == f"{DEVICE_TYPE_SMARTTHINGS_DHW}_10.0.0.9"

        # Case 3: default
        flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW}
        await flow._create_entry()
        assert flow.flow_data["unique_id"] == f"{DEVICE_TYPE_SMARTTHINGS_DHW}_default"


@pytest.mark.asyncio
async def test_cf_helpers_create_entry_preexisting_unique_id():
    """Test _create_entry uses existing unique_id from flow_data instead of generating one."""
    flow = ClimateIpConfigFlow()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with (
        patch.object(
            flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_id,
        patch.object(flow, "_abort_if_unique_id_configured"),
    ):
        flow.flow_data = {
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
            "unique_id": "preexisting_uid_123",
            CONF_MAC: "001122334455",
        }
        res = await flow._create_entry()
        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.flow_data["unique_id"] == "preexisting_uid_123"
        mock_set_id.assert_called_once_with("preexisting_uid_123")


@pytest.mark.asyncio
async def test_cf_helpers_create_entry_8888_appends_mac_to_title():
    """Test _create_entry appends unique_id to title for 8888 and MIM_H03."""
    flow = ClimateIpConfigFlow()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured"),
    ):
        flow.flow_data = {
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_MAC: "001122334455",
            "name": "Custom Name",
        }
        res = await flow._create_entry()

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert res["title"] == "Custom Name (001122334455)"


@pytest.mark.asyncio
async def test_cf_helpers_create_entry_deletes_device_id_zero_or_main():
    """Test _create_entry removes device_id if it is 0, main, None, or empty."""
    flow = ClimateIpConfigFlow()
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_USER}

    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_abort_if_unique_id_configured"),
    ):
        for val in ("0", "main", "", "None"):
            flow.flow_data = {
                CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
                CONF_MAC: "112233445566",
                CONF_DEVICE_ID: val,
            }
            res = await flow._create_entry()
            assert CONF_DEVICE_ID not in res["data"]


@pytest.mark.asyncio
async def test_cf_helpers_create_entry_reauth_and_reconfigure():
    """Test _create_entry handles reauth and reconfigure sources via async_update_reload_and_abort."""
    flow = ClimateIpConfigFlow()

    # 1. Reauth
    mock_reauth = MagicMock()
    flow.reauth_entry = mock_reauth
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "112233445566",
        CONF_TOKEN: "new_token",
        CONF_DISCOVERED_DEVICES: ["transient"],
    }
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "async_update_reload_and_abort") as mock_update,
    ):
        mock_update.return_value = {
            "type": FlowResultType.ABORT,
            "reason": "reauth_successful",
        }
        res1 = await flow._create_entry()

        assert res1["reason"] == "reauth_successful"
        mock_update.assert_called_once()
        assert mock_update.call_args.args[0] is mock_reauth
        assert mock_update.call_args.kwargs["reason"] == "reauth_successful"
        passed_data = mock_update.call_args.kwargs["data"]
        assert CONF_DISCOVERED_DEVICES not in passed_data
        assert passed_data[CONF_TOKEN] == "new_token"

    # 2. Reconfigure
    flow.reauth_entry = None
    flow.context = {"source": SOURCE_RECONFIGURE}
    mock_rec_entry = MagicMock()
    mock_rec_entry.data = {"old_setting": True}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_MAC: "112233445566",
        CONF_TOKEN: "reconfig_token",
    }
    with (
        patch.object(flow, "async_set_unique_id", new_callable=AsyncMock),
        patch.object(flow, "_get_reconfigure_entry", return_value=mock_rec_entry),
        patch.object(flow, "async_update_reload_and_abort") as mock_update2,
    ):
        mock_update2.return_value = {
            "type": FlowResultType.ABORT,
            "reason": "reconfigure_successful",
        }
        res2 = await flow._create_entry()

        assert res2["reason"] == "reconfigure_successful"
        mock_update2.assert_called_once()
        assert mock_update2.call_args.args[0] is mock_rec_entry
        assert mock_update2.call_args.kwargs["reason"] == "reconfigure_successful"
        passed_data2 = mock_update2.call_args.kwargs["data"]
        assert passed_data2["old_setting"] is True
        assert passed_data2[CONF_TOKEN] == "reconfig_token"


# -----------------------------------------------------------------------------
# 19. Tests for _async_process_reconfigure_input
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_mac_resolve_failed(hass_mock):
    """Test _async_process_reconfigure_input shows form on MAC resolve failure."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    rec_entry = MagicMock(unique_id="112233445566")

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value="mac_resolve_failed",
        ),
        patch.object(
            flow, "_current_reconfigure_suggested", return_value={"ip": "1.1.1.1"}
        ),
        patch.object(
            flow,
            "_async_show_reconfigure_form",
            return_value={"type": FlowResultType.FORM},
        ) as mock_form,
    ):
        user_input = {CONF_IP_ADDRESS: "1.1.1.1"}
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["type"] == FlowResultType.FORM
        mock_form.assert_called_once_with(
            {"base": "mac_resolve_failed"}, {"ip": "1.1.1.1"}
        )


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_mac_mismatch_aborts(hass_mock):
    """Test _async_process_reconfigure_input aborts on unique_id mismatch."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    rec_entry = MagicMock(unique_id="112233445566")

    with patch.object(
        flow,
        "_async_resolve_mac_and_set_unique_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        user_input = {CONF_IP_ADDRESS: "1.1.1.1", CONF_MAC: "AABBCCDDEEFF"}
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "unique_id_mismatch"


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_no_mac_does_not_abort_mismatch(hass_mock):
    """Test _async_process_reconfigure_input does not abort with mismatch when entry.unique_id is None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    rec_entry = MagicMock(unique_id=None, title="Test AC", data={"old": "data"})

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow, "_async_validate_cert_path", new_callable=AsyncMock, return_value=True
        ),
        patch.object(
            flow,
            "async_update_reload_and_abort",
            return_value={
                "type": FlowResultType.ABORT,
                "reason": "reconfigure_successful",
            },
        ) as mock_abort_success,
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.1.1.1",
            CONF_MAC: "112233445566",
            CONF_TOKEN: "validtok123",
        }
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["type"] == FlowResultType.ABORT
        assert res["reason"] == "reconfigure_successful"
        mock_abort_success.assert_called_once()


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_cert_not_found(hass_mock):
    """Test _async_process_reconfigure_input shows form when cert validation fails."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    rec_entry = MagicMock(unique_id="112233445566")

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow,
            "_async_validate_cert_path",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(flow, "_current_reconfigure_suggested", return_value={}),
        patch.object(
            flow,
            "_async_show_reconfigure_form",
            return_value={"type": FlowResultType.FORM},
        ) as mock_form,
    ):
        user_input = {
            CONF_IP_ADDRESS: "1.1.1.1",
            CONF_MAC: "112233445566",
            CONF_CERT: "bad.pem",
        }
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["type"] == FlowResultType.FORM
        mock_form.assert_called_once_with({"base": "cert_not_found"}, {})


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_missing_token_triggers_pairing(hass_mock):
    """Test _async_process_reconfigure_input initiates pairing if token is absent."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    rec_entry = MagicMock(unique_id="112233445566")

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow, "_async_validate_cert_path", new_callable=AsyncMock, return_value=True
        ),
        patch.object(
            flow,
            "_load_auth_flow_config",
            new_callable=AsyncMock,
            return_value={"auth": "cfg"},
        ) as mock_load_auth,
        patch.object(
            flow, "async_step_initiate_pairing", new_callable=AsyncMock
        ) as mock_pair,
    ):
        mock_pair.return_value = {"type": FlowResultType.SHOW_PROGRESS}
        user_input = {
            CONF_IP_ADDRESS: "1.1.1.1",
            CONF_MAC: "112233445566",
            CONF_TOKEN: "",
            CONF_CERT: "/path/cert.pem",
        }
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["type"] == FlowResultType.SHOW_PROGRESS
        mock_pair.assert_called_once()
        mock_load_auth.assert_called_once_with(DEVICE_TYPE_SAMSUNG_2878)
        assert flow.flow_data[CONF_IP_ADDRESS] == "1.1.1.1"
        assert flow.flow_data[CONF_CERT] == "/path/cert.pem"
        assert flow.acquirer is not None
        assert flow.acquirer.auth_config == {"auth": "cfg"}
        assert flow.acquirer.hass is hass_mock
        assert flow.acquirer.ip_address == "1.1.1.1"
        assert flow.acquirer.user_cert_path == "/path/cert.pem"


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_success_updates_entry(hass_mock):
    """Test _async_process_reconfigure_input updates entry on success."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    rec_entry = MagicMock(
        unique_id="112233445566", title="Test AC", data={"old": "val"}
    )

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            flow, "_async_validate_cert_path", new_callable=AsyncMock, return_value=True
        ),
        patch.object(flow, "async_update_reload_and_abort") as mock_update,
    ):
        mock_update.return_value = {
            "type": FlowResultType.ABORT,
            "reason": "reconfigure_successful",
        }
        user_input = {
            CONF_IP_ADDRESS: "1.1.1.1",
            CONF_MAC: "112233445566",
            CONF_TOKEN: "valid_token",
        }
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["reason"] == "reconfigure_successful"
        mock_update.assert_called_once()
        passed_data = mock_update.call_args.kwargs["data"]
        assert passed_data["old"] == "val"
        assert passed_data[CONF_TOKEN] == "valid_token"


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_mac_matches_case_insensitive(hass_mock):
    """Test _async_process_reconfigure_input normalizes MAC and unique_id case."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    rec_entry = MagicMock(
        unique_id="AA:BB:CC:DD:EE:FF", title="Test AC", data={"old": "val"}
    )

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_resolve,
        patch.object(
            flow, "_async_validate_cert_path", new_callable=AsyncMock, return_value=True
        ),
        patch.object(flow, "async_update_reload_and_abort") as mock_update,
    ):
        mock_update.return_value = {
            "type": FlowResultType.ABORT,
            "reason": "reconfigure_successful",
        }
        user_input = {
            CONF_IP_ADDRESS: "1.1.1.1",
            CONF_MAC: "aa:bb:cc:dd:ee:ff",
            CONF_TOKEN: "valid_token",
        }
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["reason"] == "reconfigure_successful"
        mock_resolve.assert_called_once_with(
            ip_address="1.1.1.1", mac_address="aa:bb:cc:dd:ee:ff"
        )
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_empty_cert_clears_and_warns(hass_mock):
    """Test _async_process_reconfigure_input logs warning when cert is cleared."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    rec_entry = MagicMock(
        unique_id="112233445566", title="Test AC", data={"old": "val"}
    )

    with (
        patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(flow, "async_update_reload_and_abort") as mock_update,
        patch("logging.Logger.warning") as mock_warn,
    ):
        mock_update.return_value = {
            "type": FlowResultType.ABORT,
            "reason": "reconfigure_successful",
        }
        user_input = {
            CONF_IP_ADDRESS: "1.1.1.1",
            CONF_MAC: "112233445566",
            CONF_TOKEN: "valid_token",
            CONF_CERT: "",
        }
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["reason"] == "reconfigure_successful"
        mock_warn.assert_any_call("Reconfigure: certificate path was cleared")


@pytest.mark.asyncio
async def test_cf_helpers_process_reconfigure_smartthings_skips_mac_resolution(
    hass_mock,
):
    """Test _async_process_reconfigure_input skips MAC resolution for SmartThings."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    rec_entry = MagicMock(unique_id="st_uid_123", title="ST AC", data={"old": "val"})

    with (
        patch.object(
            flow, "_async_resolve_mac_and_set_unique_id", new_callable=AsyncMock
        ) as mock_resolve,
        patch.object(flow, "async_update_reload_and_abort") as mock_update,
    ):
        mock_update.return_value = {
            "type": FlowResultType.ABORT,
            "reason": "reconfigure_successful",
        }
        user_input = {CONF_IP_ADDRESS: "1.1.1.1", CONF_TOKEN: "valid_token"}
        res = await flow._async_process_reconfigure_input(rec_entry, user_input)

        assert res["reason"] == "reconfigure_successful"
        mock_resolve.assert_not_called()
