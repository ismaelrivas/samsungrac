"""Test config flow UI error steps to kill mutants."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow, FlowResultType

from custom_components.climate_ip.config_flow import (
    ClimateIpConfigFlow,
    OptionsFlowHandler,
)
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DISCOVERED_DEVICES,
    CONF_POLL_INTERVAL,
    CONF_SELECTED_DEVICES,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
)
from custom_components.climate_ip.exceptions import (
    AuthError,
    AuthTurnedOffError,
    CannotConnect,
    TokenAcquisitionError,
)

# Import schema validator helper
from .test_config_flow__schemas import get_schema_marker


@pytest.mark.asyncio
async def test_handle_error_mac_required_mutants():
    """Kills mutants 25-31 y 38: Verifica el booleano req_mac_err y la regeneración del esquema."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        "error_key": "mac_resolve_failed",
    }

    # 1. Si el error es mac_resolve_failed, la MAC debe ser obligatoria
    result = await flow.async_step_handle_error()
    mac_key, _ = get_schema_marker(result["data_schema"], CONF_MAC)
    assert isinstance(mac_key, vol.Required)

    # 2. Si el error es cualquier otro, la MAC debe ser opcional
    flow.flow_data["error_key"] = "cannot_connect"
    result2 = await flow.async_step_handle_error()
    mac_key2, _ = get_schema_marker(result2["data_schema"], CONF_MAC)
    assert isinstance(mac_key2, vol.Optional)


@pytest.mark.asyncio
async def test_process_samsung_device_step_error_flags():
    """Kills mutants 40, 48, 97, 98, 105: Banderas req_mac_err = False en errores intermedios."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {CONF_IP_ADDRESS: "1.1.1.1"}

    # Error por intervalo de polling inválido
    with patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None):
        result = await flow._async_process_samsung_device_step(
            "samsung_2878", False, {CONF_POLL_INTERVAL: "invalid"}
        )
        mac_key, _ = get_schema_marker(result["data_schema"], CONF_MAC)
        assert isinstance(mac_key, vol.Optional)

    # Error por certificado no encontrado
    flow.flow_data = {
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_POLL_INTERVAL: 300,
        CONF_CERT: "bad.pem",
    }
    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=False),
    ):
        result2 = await flow._async_process_samsung_device_step(
            "samsung_2878", False, None
        )
        mac_key2, _ = get_schema_marker(result2["data_schema"], CONF_MAC)
        assert isinstance(mac_key2, vol.Optional)


@pytest.mark.asyncio
async def test_select_devices_parsing_and_fallbacks():
    """Kills mutants 10, 11, 12, 23, 35, 37, 39, 59, 60, 62, 63, 70."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_MAC: "AA:BB:CC",
        CONF_DISCOVERED_DEVICES: [
            {"id": "1"},
            {"id": "2", "name": "Zone 2"},
        ],
    }

    # 1. Name parsing mutants (M10-M12) y default schemas (M23, M35-M39)
    result = await flow.async_step_select_devices()
    schema = result["data_schema"]
    sel_key, _ = get_schema_marker(schema, CONF_SELECTED_DEVICES)
    assert sel_key.default() == ["1", "2"]

    options = schema.schema[sel_key].options
    assert options["1"] == "Indoor Unit 1"
    assert options["2"] == "Zone 2"

    # 2. Mutantes de Fallback del unique_id (M59-M63)
    flow.reauth_entry = MagicMock()
    with (
        patch.object(flow, "async_set_unique_id") as mock_set_uid,
        patch.object(flow, "_create_entry"),
    ):
        await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
        mock_set_uid.assert_called_once_with("AA:BB:CC", raise_on_progress=False)

    # 3. Mutante de Reconfiguración (M70: or en lugar de and)
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_RECONFIGURE}
    flow.flow_data = {CONF_MAC: "AA:BB:CC", CONF_DISCOVERED_DEVICES: [{"id": "1"}]}
    with (
        patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
        patch.object(flow, "_create_entry"),
    ):
        await flow.async_step_select_devices({CONF_SELECTED_DEVICES: ["1"]})
        mock_abort.assert_not_called()


@pytest.mark.asyncio
async def test_options_init_error_mutants(hass):
    """Kills mutants 9, 10, 12, 13, 15, 16 en el flujo de opciones."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init({CONF_POLL_INTERVAL: "invalid"})
    assert result["step_id"] == "init"
    assert result["errors"] == {CONF_POLL_INTERVAL: "invalid_poll_interval"}
    assert result["data_schema"] is not None


@pytest.mark.asyncio
async def test_initiate_pairing_and_discover_uuid_mutants():
    """Kills mutants 15, 39, 40, 62, 95, 97, 100, 101."""
    # 1. Fallback de pairing (M95-M101 y M62)
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
        "_fallback_attempted": True,
    }

    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": False}

    try:
        async with asyncio.timeout(0.5):
            await flow.async_step_initiate_pairing()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert flow.flow_data["error_key"] == "unknown_error"

    # 2. Reseteamos para probar M62 (asignación del certificado en fallback)
    flow.flow_data.pop("error_key", None)
    flow.flow_data["_fallback_attempted"] = False
    flow.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_2878
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": False}
    with patch.object(flow, "_async_process_samsung_device_step"):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_initiate_pairing()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert flow.flow_data[CONF_CERT] == "ac14k_m.pem"

    # 3. Discover UUID (M39, M40, M62 de exception)
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    flow.context = {"unique_id": "test"}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = mock_ctrl_cls.return_value
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl.discovered_devices = [{"id": "1", "uuid": "uuid1"}]

        with patch.object(flow, "_async_process_samsung_8888_discovery") as mock_proc:
            await flow.async_step_discover_uuid()
            mock_proc.assert_called_once()

    # M62 en discover_uuid: Verificamos shutdown en catch de InvalidHeaderError
    from custom_components.climate_ip.exceptions import InvalidHeaderError

    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController"
        ) as mock_ctrl_cls,
        patch.object(
            flow, "_async_fallback_raw_discovery", new_callable=AsyncMock
        ) as mock_fallback,
    ):
        mock_ctrl = mock_ctrl_cls.return_value
        mock_ctrl.initialize = AsyncMock(side_effect=InvalidHeaderError("Bad HTTP"))
        mock_ctrl.async_shutdown = AsyncMock()

        await flow.async_step_discover_uuid()
        mock_ctrl.async_shutdown.assert_called_once()
        mock_fallback.assert_called_once()


@pytest.mark.asyncio
async def test_discover_uuid_missing_discovered_devices_attr(hass: HomeAssistant) -> None:
    """Kill mutant on getattr default [] fallback."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = mock_ctrl_cls.return_value
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        mock_ctrl.unique_id = None
        mock_ctrl.device_id = None

        del mock_ctrl.discovered_devices

        with patch.object(
            flow, "_create_entry", return_value={"type": "create_entry"}
        ) as mock_create:
            result = await flow.async_step_discover_uuid()

            mock_create.assert_called_once()
            assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_handle_error_req_mac_is_false_not_none():
    """Kills mutant 25: req_mac = False (no None) para errores distintos de mac_resolve_failed."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        "error_key": "cannot_connect",
    }

    result = await flow.async_step_handle_error()

    mac_key, _ = get_schema_marker(result["data_schema"], CONF_MAC)
    assert isinstance(mac_key, vol.Optional)


def test_options_schema_temp_target_from_options():
    """Kills mutants 71, 72: opt_targ = options.get(CONF_TEMP_NATIVE_TARGET)."""
    from homeassistant.const import UnitOfTemperature

    from custom_components.climate_ip.const import CONF_TEMP_NATIVE_TARGET

    mock_entry = MagicMock()
    mock_entry.data = {CONF_DEVICE_TYPE: "smartthings_hvac"}
    mock_entry.options = {CONF_TEMP_NATIVE_TARGET: UnitOfTemperature.FAHRENHEIT}

    handler = OptionsFlowHandler(mock_entry)
    schema = handler._get_options_schema()

    targ_key = None
    for key in schema.schema:
        if hasattr(key, "schema") and key.schema == CONF_TEMP_NATIVE_TARGET:
            targ_key = key
            break

    assert targ_key is not None
    assert targ_key.default() == UnitOfTemperature.FAHRENHEIT


def test_options_schema_temp_target_fallback_to_default():
    """Kills mutant 72: cuando options está vacío, usa DEFAULT_CONF_TEMP_UNIT."""
    from custom_components.climate_ip.const import (
        CONF_TEMP_NATIVE_TARGET,
        DEFAULT_CONF_TEMP_UNIT,
    )

    mock_entry = MagicMock()
    mock_entry.data = {}
    mock_entry.options = {}

    handler = OptionsFlowHandler(mock_entry)
    schema = handler._get_options_schema()

    targ_key = None
    for key in schema.schema:
        if hasattr(key, "schema") and key.schema == CONF_TEMP_NATIVE_TARGET:
            targ_key = key
            break

    assert targ_key is not None
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT


def test_options_schema_temp_step_from_data():
    """Kills mutants 82, 83: opt_step = data.get(CONF_TARGET_TEMP_STEP) as secondary fallback."""
    from custom_components.climate_ip.const import CONF_TARGET_TEMP_STEP

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {CONF_TARGET_TEMP_STEP: 0.5}

    handler = OptionsFlowHandler(mock_entry)
    schema = handler._get_options_schema()

    step_key = None
    for key in schema.schema:
        if hasattr(key, "schema") and key.schema == CONF_TARGET_TEMP_STEP:
            step_key = key
            break

    assert step_key is not None
    assert step_key.default() == "0.5"


def test_options_schema_temp_step_data_fallback_default():
    """Kills mutants 82, 83 (variante): cuando ni options ni data tienen el step."""
    from custom_components.climate_ip.const import (
        CONF_TARGET_TEMP_STEP,
        DEFAULT_TARGET_TEMP_STEP,
    )

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    handler = OptionsFlowHandler(mock_entry)
    schema = handler._get_options_schema()

    step_key = None
    for key in schema.schema:
        if hasattr(key, "schema") and key.schema == CONF_TARGET_TEMP_STEP:
            step_key = key
            break

    assert step_key is not None
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)


@pytest.mark.asyncio
async def test_mim_h03_device_id_str_fallback():
    """Kills mutant 11: device_id = str(device.get('id') or '') — no str(None) ni 'XXXX'."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {}
    devices = [{"id": "0", "uuid": "coord_uuid"}, {"id": None, "Mode": "cool"}]

    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
        patch.object(flow, "async_step_select_devices", return_value={"type": "form"}),
    ):
        result = await flow._async_process_mim_h03(devices)

        assert result["type"] == FlowResultType.FORM
        assert flow.flow_data[CONF_DISCOVERED_DEVICES][0]["id"] == ""


@pytest.mark.asyncio
async def test_rest_api_aborts_if_already_configured_normal_flow(hass):
    """Verify mutant M92 kill: Flujo normal aborta si el dispositivo ya existe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    flow.context = {}

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_session.return_value.get.return_value = mock_get

        with patch.object(
            flow,
            "_abort_if_unique_id_configured",
            side_effect=AbortFlow("already_configured"),
        ):
            try:
                await flow.async_step_rest_api(
                    {
                        CONF_IP_ADDRESS: "1.1.1.1",
                        CONF_TOKEN: "valid_token_123",
                        CONF_DEVICE_ID: "existing_dev_123",
                    }
                )
                pytest.fail(
                    "Mutante 92 sobrevive: No se llamó a _abort_if_unique_id_configured"
                )
            except AbortFlow as e:
                assert e.reason == "already_configured"


# ===========================================================================
# SECTION: Exact error-key assertions for safe wrapper exception branches
# ===========================================================================


@pytest.mark.asyncio
async def test_initiate_pairing_safe_cannot_connect_error_key():
    """CannotConnect → error == 'pairing_connection_failed'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {CONF_IP_ADDRESS: "1.1.1.1"}
    flow.acquirer = MagicMock()
    flow.acquirer.async_initiate_pairing = AsyncMock(
        side_effect=CannotConnect("refused")
    )

    result = await flow._initiate_pairing_safe()

    assert result["ok"] is False
    assert result["error"] == "pairing_connection_failed"
    assert result["error_details"] == "refused"


@pytest.mark.asyncio
async def test_initiate_pairing_safe_auth_error_key():
    """AuthError → error == 'pairing_connection_failed'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {CONF_IP_ADDRESS: "1.1.1.1"}
    flow.acquirer = MagicMock()
    flow.acquirer.async_initiate_pairing = AsyncMock(
        side_effect=AuthError("bad creds")
    )

    result = await flow._initiate_pairing_safe()

    assert result["ok"] is False
    assert result["error"] == "pairing_connection_failed"
    assert result["error_details"] == "bad creds"


@pytest.mark.asyncio
async def test_initiate_pairing_safe_token_acquisition_error_key():
    """TokenAcquisitionError → error == 'pairing_connection_failed'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {CONF_IP_ADDRESS: "1.1.1.1"}
    flow.acquirer = MagicMock()
    flow.acquirer.async_initiate_pairing = AsyncMock(
        side_effect=TokenAcquisitionError("no token")
    )

    result = await flow._initiate_pairing_safe()

    assert result["ok"] is False
    assert result["error"] == "pairing_connection_failed"


@pytest.mark.asyncio
async def test_initiate_pairing_safe_timeout_error_key():
    """TimeoutError → error == 'timeout_connect'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {CONF_IP_ADDRESS: "10.0.0.1"}
    flow.acquirer = MagicMock()
    flow.acquirer.async_initiate_pairing = AsyncMock(
        side_effect=TimeoutError("timed out")
    )

    result = await flow._initiate_pairing_safe()

    assert result["ok"] is False
    assert result["error"] == "timeout_connect"
    assert "timed out" in result["error_details"]


@pytest.mark.asyncio
async def test_initiate_pairing_safe_unknown_exception_key():
    """Unexpected Exception → error == 'unknown_error'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = MagicMock()
    flow.acquirer.async_initiate_pairing = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    result = await flow._initiate_pairing_safe()

    assert result["ok"] is False
    assert result["error"] == "unknown_error"


@pytest.mark.asyncio
async def test_initiate_pairing_safe_abortflow_propagates():
    """AbortFlow must NOT be swallowed — it must re-raise."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = MagicMock()
    flow.acquirer.async_initiate_pairing = AsyncMock(
        side_effect=AbortFlow("already_configured")
    )

    with pytest.raises(AbortFlow):
        await flow._initiate_pairing_safe()


@pytest.mark.asyncio
async def test_initiate_pairing_safe_null_acquirer_key():
    """acquirer is None → error == 'unknown_error'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = None

    result = await flow._initiate_pairing_safe()

    assert result["ok"] is False
    assert result["error"] == "unknown_error"


@pytest.mark.asyncio
async def test_wait_token_safe_timeout_error_key():
    """TimeoutError → error == 'timeout_connect'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {CONF_IP_ADDRESS: "192.168.1.5"}
    flow.acquirer = MagicMock()
    flow.acquirer.async_wait_for_token = AsyncMock(
        side_effect=TimeoutError("wait expired")
    )

    result = await flow._wait_token_safe()

    assert result["ok"] is False
    assert result["error"] == "timeout_connect"
    assert "wait expired" in result["error_details"]


@pytest.mark.asyncio
async def test_wait_token_safe_token_acquisition_error_key():
    """TokenAcquisitionError → error == 'token_acquisition_failed'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = MagicMock()
    flow.acquirer.async_wait_for_token = AsyncMock(
        side_effect=TokenAcquisitionError("no token returned")
    )

    result = await flow._wait_token_safe()

    assert result["ok"] is False
    assert result["error"] == "token_acquisition_failed"


@pytest.mark.asyncio
async def test_wait_token_safe_auth_turned_off_error_key():
    """AuthTurnedOffError → error == 'token_acquisition_failed'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = MagicMock()
    flow.acquirer.async_wait_for_token = AsyncMock(
        side_effect=AuthTurnedOffError("auth disabled")
    )

    result = await flow._wait_token_safe()

    assert result["ok"] is False
    assert result["error"] == "token_acquisition_failed"


@pytest.mark.asyncio
async def test_wait_token_safe_unknown_exception_key():
    """Unexpected Exception → error == 'unknown_error'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = MagicMock()
    flow.acquirer.async_wait_for_token = AsyncMock(
        side_effect=ValueError("unexpected")
    )

    result = await flow._wait_token_safe()

    assert result["ok"] is False
    assert result["error"] == "unknown_error"


@pytest.mark.asyncio
async def test_wait_token_safe_abortflow_propagates():
    """AbortFlow must re-raise from _wait_token_safe."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = MagicMock()
    flow.acquirer.async_wait_for_token = AsyncMock(
        side_effect=AbortFlow("already_configured")
    )

    with pytest.raises(AbortFlow):
        await flow._wait_token_safe()


@pytest.mark.asyncio
async def test_wait_token_safe_null_acquirer_key():
    """acquirer is None → error == 'unknown_error'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = None

    result = await flow._wait_token_safe()

    assert result["ok"] is False
    assert result["error"] == "unknown_error"


@pytest.mark.asyncio
async def test_wait_token_safe_success_returns_token():
    """Happy path: returned dict has ok=True and the token value."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    flow.acquirer = MagicMock()
    flow.acquirer.async_wait_for_token = AsyncMock(return_value="ABC123")

    result = await flow._wait_token_safe()

    assert result["ok"] is True
    assert result["token"] == "ABC123"


@pytest.mark.asyncio
async def test_test_connection_safe_cannot_connect_error_key(hass):
    """CannotConnect → error == 'pairing_connection_failed'."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_TOKEN: "tok",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_sess.return_value.get.side_effect = CannotConnect("refused")

        result = await flow._test_connection_safe()

    assert result["ok"] is False
    assert result["error"] == "pairing_connection_failed"


@pytest.mark.asyncio
async def test_test_connection_safe_timeout_error_key(hass):
    """TimeoutError → error == 'timeout_connect'."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_TOKEN: "tok",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_sess.return_value.get.side_effect = TimeoutError("connection timed out")

        result = await flow._test_connection_safe()

    assert result["ok"] is False
    assert result["error"] == "timeout_connect"
    assert "connection timed out" in result["error_details"]


@pytest.mark.asyncio
async def test_test_connection_safe_auth_error_key(hass):
    """AuthError → error == 'invalid_auth'."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_TOKEN: "tok",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_sess.return_value.get.side_effect = AuthError("token rejected")

        result = await flow._test_connection_safe()

    assert result["ok"] is False
    assert result["error"] == "invalid_auth"
    assert "token rejected" in result["error_details"]


@pytest.mark.asyncio
async def test_test_connection_safe_unknown_exception_key(hass):
    """Unexpected Exception → error == 'cannot_connect'."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_TOKEN: "tok",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_sess.return_value.get.side_effect = OSError("network failure")

        result = await flow._test_connection_safe()

    assert result["ok"] is False
    assert result["error"] == "cannot_connect"


@pytest.mark.asyncio
async def test_test_connection_safe_abortflow_propagates(hass):
    """AbortFlow must re-raise from _test_connection_safe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_TOKEN: "tok",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_sess.return_value.get.side_effect = AbortFlow("already_configured")

        with pytest.raises(AbortFlow):
            await flow._test_connection_safe()


@pytest.mark.asyncio
async def test_test_connection_safe_unknown_device_type_key(hass):
    """Unknown device_type → ok=False, error == 'cannot_connect'."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: "nonexistent_type",
        CONF_IP_ADDRESS: "1.1.1.1",
    }

    result = await flow._test_connection_safe()

    assert result["ok"] is False
    assert result["error"] == "cannot_connect"