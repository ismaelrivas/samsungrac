# pylint: disable=protected-access,too-many-locals,line-too-long,too-many-statements,too-many-arguments,redefined-outer-name
"""Tests for ConfigFlowHelpersMixin in config_flow_helpers.py."""

from __future__ import annotations

import os
import ssl
from unittest.mock import AsyncMock, MagicMock, call, patch

from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.data_entry_flow import AbortFlow
import pytest

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
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


@pytest.fixture
def hass_mock():
    """Mock Home Assistant object."""
    hass = MagicMock()
    return hass


# -----------------------------------------------------------------------------
# 1. Tests for _async_force_arp_update (Kills Mutants 3, 4, 7, 8)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_force_arp_update_success(hass_mock):
    """Test _async_force_arp_update opens connections to both ports and closes writers."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock

    mock_writer = AsyncMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with patch(
        "asyncio.open_connection",
        new_callable=AsyncMock,
        return_value=(MagicMock(), mock_writer),
    ) as mock_open:
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
async def test_test_connection_safe_unknown_device_type(hass_mock):
    """Test _test_connection_safe returns error on unknown device type."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass_mock
    flow.flow_data = {CONF_DEVICE_TYPE: "unknown_future_device"}

    res = await flow._test_connection_safe()
    assert res == {"ok": False, "error": "cannot_connect"}


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
