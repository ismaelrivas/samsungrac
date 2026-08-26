from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
import voluptuous as vol

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_POLL_INTERVAL,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPE_TO_CONFIG_FILE,
    GLOBAL_HTTP_TIMEOUT,
)


@pytest.mark.asyncio
async def test_rest_api_device_mapping_mutants():
    """Kills mutants del mapeo de configuración (M26, M27, M28, M29)"""
    flow = ClimateIpConfigFlow()

    # M26/M27: Void device_type reading to None
    # M28: Invert "if device_type in DEVICE_TYPE_TO_CONFIG_FILE" to "not in"
    # M29: Set assignment to None instead of dict
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_TOKEN: "valid_token",
    }

    # Mock validate_poll to skip directly to REST check
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        # Mock HTTP 200 to avoid CannotConnect exception
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_session.return_value.get.return_value = mock_get

        # Mock unique ID fallback
        with (
            patch.object(flow, "async_set_unique_id"),
            patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
        ):
            await flow.async_step_rest_api(
                {CONF_IP_ADDRESS: "1.1.1.1", CONF_DEVICE_ID: "dev_1"}
            )

            # Comprobación letal:
            assert (
                flow.flow_data[CONF_CONFIG_FILE]
                == DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_SMARTTHINGS_HVAC]
            )


@pytest.mark.asyncio
async def test_rest_api_unique_id_logic_mutants():
    """Kills mutants de extracción de MAC/Device ID (M76, M77, M78, M80, M81, M82, M83, M91)"""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_IP_ADDRESS: "1.1.1.1",
        CONF_TOKEN: "valid_token",
        CONF_MAC: "AA:BB:CC",
        CONF_DEVICE_ID: "dev_123",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_session.return_value.get.return_value = mock_get

        # 1. Prioridad: Device ID (M78, M80)
        with patch.object(flow, "async_set_unique_id") as mock_set:
            with patch.object(
                flow, "_create_entry", return_value={"type": "create_entry"}
            ):
                await flow.async_step_rest_api({CONF_IP_ADDRESS: "1.1.1.1"})
                # M78 (if dev_id is None) / M80 (str(None)) fallarán aquí
                mock_set.assert_called_once_with("dev_123")

        # 2. Secundario: MAC ID (M76, M77, M81, M82, M83)
        flow.flow_data.pop(
            CONF_DEVICE_ID
        )  # Quitamos el dev_id para forzar fallback a MAC
        with patch.object(flow, "async_set_unique_id") as mock_set2:
            with patch.object(
                flow, "_create_entry", return_value={"type": "create_entry"}
            ):
                await flow.async_step_rest_api({CONF_IP_ADDRESS: "1.1.1.1"})
                # M76/M77 (mac_id = None), M81 (elif mac_id is None), M82/M83 (unique_id = None)
                mock_set2.assert_called_once_with("AA:BB:CC")

        # 3. Abort Reauth (M91)
        flow.reauth_entry = MagicMock()
        # If mutant 91 changes `if self.reauth_entry is None` to `is not None`,
        # it will call _abort_if_unique_id_configured and trigger abort exception.
        # Force _abort_if_unique_id_configured to raise Exception("MataM91")
        with patch.object(
            flow, "_abort_if_unique_id_configured", side_effect=Exception("MataM91")
        ):
            with patch.object(
                flow, "_create_entry", return_value={"type": "create_entry"}
            ):
                try:
                    await flow.async_step_rest_api({CONF_IP_ADDRESS: "1.1.1.1"})
                except Exception as e:
                    if str(e) == "MataM91":
                        pytest.fail(
                            "Mutant 91 survived: Called _abort_if_unique_id_configured with active reauth"
                        )


# Assuming you have this magnifying glass in your helper or schema test
def get_schema_marker(schema: vol.Schema, key_name: str):
    for key, value_type in schema.schema.items():
        if key.schema == key_name:
            return key, value_type
    return None, None


@pytest.mark.asyncio
async def test_reconfigure_confirm_schema_fallbacks():
    """Kills mutants M21, M25, M37, M40: Fallbacks iniciales de schema en reconfiguración."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.10",
        # INTENTIONALLY omit MAC, TOKEN, and CERT to force dictionary fallbacks
    }

    # Mock reconfiguration entry
    mock_entry = MagicMock()
    mock_entry.data = flow.flow_data
    mock_entry.title = "Test AC"
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    result = await flow.async_step_reconfigure_confirm()
    schema = result["data_schema"]

    mac_key, _ = get_schema_marker(schema, CONF_MAC)
    cert_key, _ = get_schema_marker(schema, CONF_CERT)

    # If mutmut changed fallback to "XXXX" or None, these assertions liquidate it
    assert mac_key.description.get("suggested_value") == ""
    assert cert_key.description.get("suggested_value") == "ac14k_m.pem"


@pytest.mark.asyncio
async def test_reconfigure_confirm_mac_error_rebuild():
    """Mata a la legión de mutantes (M68-M77, M87-M115, M142-M174) que alteran la reconstrucción del schema en errores."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "10.0.0.1",
    }
    mock_entry = MagicMock(data={})
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    # Input intentionally lacking optional fields to trigger internal defaults
    user_input = {CONF_IP_ADDRESS: "10.0.0.1"}

    # Simulate MAC resolution failure
    with patch.object(
        flow, "_async_resolve_mac_and_set_unique_id", return_value="mac_resolve_failed"
    ) as mock_resolve:
        result = await flow.async_step_reconfigure_confirm(user_input)

        # M68-M77: Verify arguments passed to resolve MAC were exact
        mock_resolve.assert_called_once_with(ip_address="10.0.0.1", mac_address="")

        assert result["errors"]["base"] == "mac_resolve_failed"
        schema = result["data_schema"]

        # M87-M115 and M142-M174: If mutant injects "XXXX" or None in error fallbacks, this fails
        ip_key, _ = get_schema_marker(schema, CONF_IP_ADDRESS)
        mac_key, _ = get_schema_marker(schema, CONF_MAC)
        token_key, _ = get_schema_marker(schema, CONF_TOKEN)
        cert_key, _ = get_schema_marker(schema, CONF_CERT)

        assert ip_key.description.get("suggested_value") == "10.0.0.1"
        assert mac_key.description.get("suggested_value") == ""
        assert token_key.description.get("suggested_value") == ""
        assert (
            cert_key.description.get("suggested_value") == ""
        )  # En 8888 no hay cert por defecto en fallback vacío


@pytest.mark.asyncio
async def test_reconfigure_confirm_cert_error_rebuild():
    """Kills certificate failure mutants (M146-M177) and MAC formatting mutants (M128, M131)."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "10.0.0.1",
        # BULLET FOR M128/M131: Inject lowercase MAC
        CONF_MAC: "aa:bb:cc:dd:ee:ff",
    }
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )

    # User submits same lowercase MAC in input
    user_input = {
        CONF_IP_ADDRESS: "10.0.0.1",
        CONF_CERT: "invalid.pem",
        CONF_MAC: "aa:bb:cc:dd:ee:ff",
    }

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=False),
    ):
        result = await flow.async_step_reconfigure_confirm(user_input)
        assert result["errors"]["base"] == "cert_not_found"

        schema = result["data_schema"]
        ip_key, _ = get_schema_marker(schema, CONF_IP_ADDRESS)
        mac_key, _ = get_schema_marker(schema, CONF_MAC)
        token_key, _ = get_schema_marker(schema, CONF_TOKEN)
        cert_key, _ = get_schema_marker(schema, CONF_CERT)

        assert ip_key.description.get("suggested_value") == "10.0.0.1"

        # CRITICAL IMPACT M131: We require reconstructed form to be in UPPERCASE
        assert mac_key.description.get("suggested_value") == "AA:BB:CC:DD:EE:FF"

        assert token_key.description.get("suggested_value") == ""
        assert cert_key.description.get("suggested_value") == "invalid.pem"


@pytest.mark.asyncio
async def test_rest_api_schema_invalid_poll_interval_except_branch():
    """Kills mutants 18, 20, 21: fallback '' en rama except de _get_rest_api_schema.

    Para activar la rama except, DEFAULT_POLL_INTERVAL debe ser inválido.
    Para activar el fallback '', CONF_POLL_INTERVAL debe estar AUSENTE de flow_data,
    de forma que .get(CONF_POLL_INTERVAL, "") devuelva exactamente "".
    """
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.hass.config_entries.async_entries.return_value = []
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        # CONF_POLL_INTERVAL missing: except will use fallback ""
    }

    # Patch DEFAULT_POLL_INTERVAL to invalid value to force except
    with patch(
        "custom_components.climate_ip.config_flow_schemas.DEFAULT_POLL_INTERVAL",
        "invalid",
    ):
        schema = flow._get_rest_api_schema()

    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)

    # M18/M20/M21: if fallback is None or omitted, str(None)="None" ≠ ""
    # Correct value is "" because CONF_POLL_INTERVAL is not in flow_data
    assert poll_key.default() == ""


def test_rest_api_schema_non_st_with_existing_ip():
    """Kills mutants 53-57: rama else:if ip_default en _get_rest_api_schema (non-SmartThings)."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.hass.config_entries.async_entries.return_value = []
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.50",  # Previous IP — activates if ip_default branch:
    }

    schema = flow._get_rest_api_schema()
    ip_key, ip_val = get_schema_marker(schema, CONF_IP_ADDRESS)

    # If mutmut sets default=None, pre-filled IP disappears from form
    assert ip_key.default() == "192.168.1.50"
    assert ip_val is str


@pytest.mark.asyncio
async def test_reconfigure_confirm_initial_schema_all_empty_fallbacks():
    """Kills mutants 20, 41, 44: fallbacks del schema inicial cuando flow_data está vacío."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        # Without IP, MAC, TOKEN, CERT — forces all fallbacks to default values
    }
    mock_entry = MagicMock()
    mock_entry.data = flow.flow_data
    mock_entry.title = "Test AC"
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    result = await flow.async_step_reconfigure_confirm()
    schema = result["data_schema"]

    ip_key, _ = get_schema_marker(schema, CONF_IP_ADDRESS)
    mac_key, _ = get_schema_marker(schema, CONF_MAC)
    cert_key, _ = get_schema_marker(schema, CONF_CERT)

    # M20: ip_def must be "" (not "XXXX")
    assert ip_key.description.get("suggested_value") == ""
    # M41: cert_def must use CONF_CERT from flow_data — non-existent → fallback "ac14k_m.pem"
    assert cert_key.description.get("suggested_value") == "ac14k_m.pem"
    # M44: mac_def must be "" (not "XXXX") when MAC is missing
    assert mac_key.description.get("suggested_value") == ""


@pytest.mark.asyncio
async def test_reconfigure_mac_error_with_empty_flow_data():
    """Kills mutants 91-119 (bloque error MAC): fallbacks cuando flow_data carece de campos."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
        # Sin MAC, TOKEN, CERT intencionalmente
    }
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )

    with patch.object(
        flow, "_async_resolve_mac_and_set_unique_id", return_value="mac_resolve_failed"
    ):
        result = await flow.async_step_reconfigure_confirm({CONF_IP_ADDRESS: "1.1.1.1"})

    assert result["errors"]["base"] == "mac_resolve_failed"
    schema = result["data_schema"]

    ip_key, _ = get_schema_marker(schema, CONF_IP_ADDRESS)
    mac_key, _ = get_schema_marker(schema, CONF_MAC)
    token_key, _ = get_schema_marker(schema, CONF_TOKEN)
    cert_key, _ = get_schema_marker(schema, CONF_CERT)

    # M91-M94: ip_err_def debe ser "1.1.1.1"
    assert ip_key.description.get("suggested_value") == "1.1.1.1"
    # M98-M101: raw_mac_err default="" → mac_err_def=""
    assert mac_key.description.get("suggested_value") == ""
    # M109-M112: token_err_def debe ser "" (no None/"XXXX")
    assert token_key.description.get("suggested_value") == ""
    # M116-M119: cert_err_def debe ser ""
    assert cert_key.description.get("suggested_value") == ""


@pytest.mark.asyncio
async def test_reconfigure_token_acquirer_ip_empty_fallback():
    """Kills mutant 209: ip_val debe ser '' (no 'XXXX') cuando no hay IP en flow_data."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        # Without CONF_IP_ADDRESS — forces fallback ip_val = ""
        CONF_CERT: "test.pem",
    }
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )

    user_input = {CONF_CERT: "test.pem"}  # Without IP or token

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acquirer,
        patch.object(
            flow, "async_step_initiate_pairing", return_value={"type": "form"}
        ),
    ):
        await flow.async_step_reconfigure_confirm(user_input)

        # M209: ip_val must be "" when CONF_IP_ADDRESS is missing from flow_data
        # If mutant sets "XXXX", acquirer receives "XXXX" instead of ""
        mock_acquirer.assert_called_once()
        assert mock_acquirer.call_args[0][1] == ""
        assert (
            mock_acquirer.call_args[1].get("cert_path") == "test.pem"
            or mock_acquirer.call_args[0][3] == "test.pem"
        )


def test_get_base_samsung_schema_rejects_none_mac_required():
    """Kills mutants 46 and 101 (Equivalent): type barrier in _get_base_samsung_schema."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}

    # If mac_required=None passes silently, the mutant is equivalent to False.
    # TypeError barrier makes them distinguishable.
    with pytest.raises(TypeError):
        flow._get_base_samsung_schema(mac_required=None, is_8888=False)

    with pytest.raises(TypeError):
        flow._get_base_samsung_schema(mac_required=None, is_8888=True)

    # With strict bool must work without error
    schema_false = flow._get_base_samsung_schema(mac_required=False, is_8888=False)
    assert schema_false is not None
    schema_true = flow._get_base_samsung_schema(mac_required=True, is_8888=False)
    assert schema_true is not None


@pytest.mark.asyncio
async def test_reconfigure_token_acquirer_routing():
    """Verify mutant M205 kill y M214-M219: Argumentos exactos pasados al Token Acquirer."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,  # To use base acquirer
        CONF_IP_ADDRESS: "192.168.1.50",
        # Intentionally without token
    }
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )

    user_input = {CONF_IP_ADDRESS: "192.168.1.50", CONF_CERT: "test.pem"}

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch(
            "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
        ) as mock_acquirer,
        patch.object(
            flow, "async_step_initiate_pairing", return_value={"type": "init_pairing"}
        ),
    ):
        await flow.async_step_reconfigure_confirm(user_input)

        # M205: GenericYamlTokenAcquirer receives hass, ip_val, auth_flow_dict, target_cert
        mock_acquirer.assert_called_once()
        args = mock_acquirer.call_args[0]
        assert args[0] == flow.hass
        assert args[1] == "192.168.1.50"
        assert (
            mock_acquirer.call_args[1].get("cert_path") == "test.pem"
            or mock_acquirer.call_args[0][3] == "test.pem"
        )


@pytest.mark.asyncio
async def test_reconfigure_success_fallbacks():
    """Verify mutant M234 kill, M242, M246: UI Fallbacks on success."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.hass.config_entries.async_reload = AsyncMock()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_TOKEN: "valid_token",  # Skips token acquirer
        CONF_IP_ADDRESS: "10.0.0.1",
    }

    mock_entry = MagicMock()
    # Omit IP in mock data to force desc_ip = "" fallback
    mock_entry.data = {}
    mock_entry.title = "Living Room AC"
    mock_entry.unique_id = "AABBCCDDEEFF"
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    user_input = {CONF_IP_ADDRESS: "10.0.0.1", CONF_TOKEN: "valid_token"}

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=True),
        patch.object(
            flow,
            "async_update_reload_and_abort",
            return_value={
                "type": FlowResultType.ABORT,
                "reason": "reconfigure_successful",
            },
        ),
    ):
        result = await flow.async_step_reconfigure_confirm(user_input)

        # M242, 246: errors must be empty dict or not null
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"

        # To test confirmation/error screen explicitly (Force rendered return)
        # Make validator raise ValueError or simulate clean return without args.
        flow.flow_data = {
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_IP_ADDRESS: "10.0.0.1",
        }  # Reset
        res_form = await flow.async_step_reconfigure_confirm()
        # M234: Verify desc_ip fell to empty string and not "XXXX" on missing IP
        assert res_form["description_placeholders"]["ip_address"] == ""
        # M242, 246: Verify errors is passed explicitly empty {} and not None
        assert res_form["errors"] == {}


@pytest.mark.asyncio
async def test_reconfigure_confirm_totally_empty_fallbacks():
    """Kills mutants 142-173: Fallbacks en errores cuando el diccionario está vacío."""
    flow = ClimateIpConfigFlow()
    # Flow data completamente vacío
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )

    # Simulamos error de MAC
    with patch.object(
        flow, "_async_resolve_mac_and_set_unique_id", return_value="mac_resolve_failed"
    ):
        result = await flow.async_step_reconfigure_confirm({CONF_IP_ADDRESS: "1.1.1.1"})

        schema = result["data_schema"]
        ip_key, _ = get_schema_marker(schema, CONF_IP_ADDRESS)
        mac_key, _ = get_schema_marker(schema, CONF_MAC)
        token_key, _ = get_schema_marker(schema, CONF_TOKEN)

        # If mutant inyecta None o "XXXX", estas aserciones fallan
        assert ip_key.description.get("suggested_value") == "1.1.1.1"
        assert mac_key.description.get("suggested_value") == ""
        assert token_key.description.get("suggested_value") == ""


@pytest.mark.asyncio
async def test_rest_api_empty_token_and_reauth_abort():
    """Kills mutants 8 y 91 en REST API."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    # 1. Verify mutant M8 kill (Token vacío fallback a "XXXX")
    # If mutmut changes raw_token = "" to "XXXX", 'if raw_token:' is satisfied and calls sanitize.
    with patch("custom_components.climate_ip.helpers.sanitize_token") as mock_sanitize:
        await flow.async_step_rest_api({})
        # Original code has raw_token="", so MUST NOT call sanitize_token
        mock_sanitize.assert_not_called()

    # 2. Verify mutant M91 kill (Inverts reauth logic in REST)
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    flow.reauth_entry = MagicMock()  # Is in reauth (NOT None)

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_session.return_value.get.return_value = mock_get
        with (
            patch.object(flow, "_abort_if_unique_id_configured") as mock_abort,
            patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
        ):
            await flow.async_step_rest_api({CONF_DEVICE_ID: "dev1"})
            # Mutant 91 does if self.reauth_entry is not None: abort(). Here it MUST NOT be called.
            mock_abort.assert_not_called()


def test_rest_api_schema_poll_interval_empty():
    """Kills mutants 18-21 y 53-57 de schemas REST vacíos."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.hass.config_entries.async_entries.return_value = []
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}

    schema = flow._get_rest_api_schema()
    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == "0:01:00"  # Verify mutant M18 kill, M20, M21

    ip_key, _ = get_schema_marker(schema, CONF_IP_ADDRESS)
    assert ip_key.default() == "api.smartthings.com"  # Verify mutant M53 kill-M57


@pytest.mark.asyncio
async def test_reconfigure_confirm_non_samsung_cert_fallback():
    """Kills mutant 44: Fallback de cert_def para dispositivos no-Samsung debe ser string vacío '' y no 'XXXX'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        # Explicitly using a device that is NOT Samsung!
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
    }

    mock_entry = MagicMock()
    mock_entry.data = flow.flow_data
    mock_entry.title = "Test REST AC"
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    # Loaded initial reconfiguration form
    result = await flow.async_step_reconfigure_confirm()
    schema = result["data_schema"]

    cert_key, _ = get_schema_marker(schema, CONF_CERT)

    # M44: If mutant changed 'else ""' to 'else "XXXX"' in certificate assignment,
    # this assertion will fail instantly.
    assert cert_key.description.get("suggested_value") == ""


# === KILLS M38 AND M40 ===
@pytest.mark.asyncio
async def test_reconfigure_confirm_cert_preserved_from_flow_data():
    """M38/M40: If cert already saved in flow_data, schema must show it (not fallback)."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_CERT: "my_custom.pem",  # Saved cert
    }
    mock_entry = MagicMock()
    mock_entry.data = flow.flow_data
    mock_entry.title = "Test AC"
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    result = await flow.async_step_reconfigure_confirm()
    schema = result["data_schema"]
    cert_key, _ = get_schema_marker(schema, CONF_CERT)

    # Original code preserves "my_custom.pem"
    assert cert_key.description.get("suggested_value") == "my_custom.pem"


# === KILLS M134 ===
@pytest.mark.asyncio
async def test_reconfigure_confirm_cert_error_empty_mac_fallback():
    """M134: With empty MAC in cert error, suggested value must be '' and not 'XXXX'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "10.0.0.1",
        CONF_MAC: "",  # Empty MAC — triggers else "" that the mutant changes to "XXXX"
        CONF_TOKEN: "",
        CONF_CERT: "",
    }
    flow._get_reconfigure_entry = MagicMock(
        return_value=MagicMock(data={}, unique_id="AABBCCDDEEFF")
    )
    user_input = {CONF_IP_ADDRESS: "10.0.0.1", CONF_CERT: "bad.pem", CONF_MAC: ""}

    with (
        patch.object(flow, "_async_resolve_mac_and_set_unique_id", return_value=None),
        patch.object(flow, "_async_validate_cert_path", return_value=False),
    ):
        result = await flow.async_step_reconfigure_confirm(user_input=user_input)

    schema = result["data_schema"]
    mac_key, _ = get_schema_marker(schema, CONF_MAC)

    # M134: mutant puts "XXXX" here when raw_mac_err is empty
    assert mac_key.description.get("suggested_value") == ""


@pytest.mark.asyncio
async def test_test_connection_safe_strict_timeout(hass: HomeAssistant) -> None:
    """Verify mutant M47 kill and M51: Verifies that GLOBAL_HTTP_TIMEOUT is used in the aiohttp connection."""
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
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get

        try:
            async with asyncio.timeout(0.5):
                await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        # 🔥 KILL SHOT: Strict assertion of network kwargs and URL positional argument
        assert mock_sess.return_value.get.called
        call = mock_sess.return_value.get.call_args
        assert len(call.args) == 1, (
            "session.get debe recibir la URL como primer argumento posicional"
        )
        assert (
            call.args[0] == "https://1.1.1.1:8888/api/test" or "1.1.1.1" in call.args[0]
        )
        assert "timeout" in call.kwargs, "Falta el timeout en la llamada de red HTTP"
        assert call.kwargs["timeout"] == GLOBAL_HTTP_TIMEOUT


def test_get_smartthings_token_empty_string(hass: HomeAssistant) -> None:
    """Verify mutant M12 kill: Verifica que devuelve '' cuando tok es None y no 'XXXX'."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    mock_entry = MagicMock()
    # 'access_token' not present -> dict.get() returns None
    mock_entry.data = {}
    flow.hass.config_entries.async_entries.return_value = [mock_entry]

    # Lethal assertion
    assert flow._get_smartthings_token() == ""


@pytest.mark.asyncio
async def test_task_exception_strict_error_handling(hass: HomeAssistant) -> None:
    """Kills legion (M8-M21, etc) in initiate_pairing, await_button and test_connection."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.acquirer = MagicMock(async_close=AsyncMock())

    # 1. KILLS MUTANTS IN initiate_pairing
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
        "_fallback_attempted": True,  # <- THE KEY! Tells it fallback was already attempted
    }
    with patch.object(flow, "task", create=True) as mock_task:
        mock_task.done.return_value = True
        mock_task.result.side_effect = Exception("Boom initiate")
        try:
            async with asyncio.timeout(0.5):
                res1 = await flow.async_step_initiate_pairing()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res1["step_id"] == "handle_error"
        assert flow.flow_data["error_key"] == "unknown_error"

    # 2. KILLS MUTANTS IN await_button
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    with patch.object(flow, "task", create=True) as mock_task:
        mock_task.done.return_value = True
        mock_task.result.side_effect = Exception("Boom await")
        try:
            async with asyncio.timeout(0.5):
                res2 = await flow.async_step_await_button()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res2["step_id"] == "handle_error"
        assert flow.flow_data["error_key"] == "unknown_error"

    # 3. KILLS MUTANTS IN test_connection
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    with patch.object(flow, "task", create=True) as mock_task:
        mock_task.done.return_value = True
        mock_task.result.side_effect = Exception("Boom test_conn")
        try:
            async with asyncio.timeout(0.5):
                res3 = await flow.async_step_test_connection()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert res3["step_id"] == "handle_error"
        assert flow.flow_data["error_key"] == "unknown_error"


@pytest.mark.asyncio
async def test_rest_api_smartthings_custom_port_and_fallback_uid(
    hass: HomeAssistant,
) -> None:
    """Verify SmartThings with custom host:port and fallback unique_id when items empty."""
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow

    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW,
        CONF_IP_ADDRESS: "my-custom-host.local:8443",
        CONF_TOKEN: "my-smartthings-pat-token-9999",
    }

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_sess:
        mock_get = AsyncMock()
        mock_get.status = 200
        mock_get.json = AsyncMock(return_value={"items": []})
        mock_get.__aenter__.return_value = mock_get
        mock_sess.return_value.get.return_value = mock_get

        res = await flow.async_step_rest_api(
            {
                CONF_IP_ADDRESS: "my-custom-host.local:8443",
                CONF_TOKEN: "my-smartthings-pat-token-9999",
            }
        )

        assert res["type"] == FlowResultType.CREATE_ENTRY
        assert flow.unique_id == "smartthings_dhw_ken-9999"
        assert flow.flow_data["name"] == "Samsung Smartthings Dhw"
        mock_sess.return_value.get.assert_called_once_with(
            "https://my-custom-host.local:8443/v1/devices",
            headers={"Authorization": "Bearer my-smartthings-pat-token-9999"},
            ssl=False,
            timeout=10,
        )
