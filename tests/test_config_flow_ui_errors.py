import pytest
import voluptuous as vol
from unittest.mock import patch, MagicMock, AsyncMock
from homeassistant.data_entry_flow import AbortFlow, FlowResultType
from homeassistant.config_entries import SOURCE_RECONFIGURE
from custom_components.climate_ip.config_flow import (
    ClimateIpConfigFlow,
    OptionsFlowHandler,
    CONF_DEVICE_ID,
    CONF_DISCOVERED_DEVICES,
    CONF_SELECTED_DEVICES,
)

from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    CONF_CERT,
    DOMAIN,
    CONF_POLL_INTERVAL,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

# Import schema validator helper
from .test_config_flow_schemas import get_schema_marker


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
    assert isinstance(
        mac_key, vol.Required
    )  # If mutant inyecta False o cambia el string, esto falla

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
        assert isinstance(mac_key, vol.Optional)  # If mutant anula req_mac_err, fallará

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
        ],  # Dispositivo 1 sin nombre
    }

    # 1. Name parsing mutants (M10-M12) y default schemas (M23, M35-M39)
    result = await flow.async_step_select_devices()
    schema = result["data_schema"]
    sel_key, _ = get_schema_marker(schema, CONF_SELECTED_DEVICES)
    assert sel_key.default() == ["1", "2"]  # Si def_keys = None, falla

    # Verificamos que el fallback del nombre "Indoor Unit X" se asignó bien (M10-M12)
    options = schema.schema[sel_key].options
    assert options["1"] == "Indoor Unit 1"
    assert options["2"] == "Zone 2"

    # 2. Mutantes de Fallback del unique_id (M59-M63)
    flow.reauth_entry = MagicMock()  # Evitamos abort
    with (
        patch.object(flow, "async_set_unique_id") as mock_set_uid,
        patch.object(flow, "_create_entry"),
    ):
        # Forzamos la selección para pasar la validación
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
        mock_abort.assert_not_called()  # En reconfigure NO se debe abortar


@pytest.mark.asyncio
async def test_options_init_error_mutants(hass):
    """Kills mutants 9, 10, 12, 13, 15, 16 en el flujo de opciones."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass

    # Pass intervalo inválido. Debe retornar form con step_id "init" y el error exacto
    result = await flow.async_step_init({CONF_POLL_INTERVAL: "invalid"})
    assert result["step_id"] == "init"  # Mutantes 15, 16 inyectan "XXinitXX" o "INIT"
    assert result["errors"] == {CONF_POLL_INTERVAL: "invalid_poll_interval"}
    assert result["data_schema"] is not None  # Mutantes 10, 12 borran el data_schema


@pytest.mark.asyncio
async def test_initiate_pairing_and_discover_uuid_mutants():
    """Kills mutants 15, 39, 40, 62, 95, 97, 100, 101."""
    # 1. Fallback de pairing (M95-M101 y M62)
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
        "_fallback_attempted": True,  # Evitamos el intento de fallback de puerto
    }

    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {
        "ok": False
    }  # Sin key "error", fuerza el default "unknown_error"

    await flow.async_step_initiate_pairing()
    assert (
        flow.flow_data["error_key"] == "unknown_error"
    )  # If mutant inyecta "XXXX", falla

    # 2. Reseteamos para probar M62 (asignación del certificado en fallback)
    flow.flow_data.pop("error_key", None)
    flow.flow_data["_fallback_attempted"] = False
    flow.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_2878
    flow.task = MagicMock()
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": False}
    with patch.object(flow, "_async_process_samsung_device_step"):
        await flow.async_step_initiate_pairing()
        assert (
            flow.flow_data[CONF_CERT] == "ac14k_m.pem"
        )  # Mutante 62 anula esto a None

    # 3. Discover UUID (M39, M40, M62 de exception)
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    flow.context = {"unique_id": "test"}

    with patch(
        "custom_components.climate_ip.config_flow.YamlController"
    ) as mock_ctrl_cls:
        mock_ctrl = mock_ctrl_cls.return_value
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        # Mock dispositivos descubiertos
        mock_ctrl.discovered_devices = [{"id": "1", "uuid": "uuid1"}]

        with patch.object(flow, "_async_process_samsung_8888_discovery") as mock_proc:
            await flow.async_step_discover_uuid()
            # Si hasattr usa "XXdiscovered_devicesXX" (M39/M40), la lista cae vacía y no llama a esto
            mock_proc.assert_called_once()

    # M62 en discover_uuid: Verificamos shutdown en catch de InvalidHeaderError
    from custom_components.climate_ip.exceptions import InvalidHeaderError

    with (
        patch(
            "custom_components.climate_ip.config_flow.YamlController"
        ) as mock_ctrl_cls,
        patch.object(
            flow, "_async_fallback_raw_discovery", new_callable=AsyncMock
        ) as mock_fallback,
    ):
        mock_ctrl = mock_ctrl_cls.return_value
        mock_ctrl.initialize = AsyncMock(side_effect=InvalidHeaderError("Bad HTTP"))
        mock_ctrl.async_shutdown = AsyncMock()

        await flow.async_step_discover_uuid()
        # If mutant cambió "if controller is not None:" a "is None", esto no se llamará y fallará
        mock_ctrl.async_shutdown.assert_called_once()
        mock_fallback.assert_called_once()


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
    # Si req_mac = None, _get_base_samsung_schema lanza TypeError (por nuestra barrera)
    # Si req_mac = False (correcto), MAC es vol.Optional
    assert isinstance(mac_key, vol.Optional)


def test_options_schema_temp_target_from_options():
    """Kills mutants 71, 72: opt_targ = options.get(CONF_TEMP_NATIVE_TARGET)."""
    from custom_components.climate_ip.const import CONF_TEMP_NATIVE_TARGET
    from unittest.mock import MagicMock
    from homeassistant.const import UnitOfTemperature

    mock_entry = MagicMock()
    mock_entry.data = {CONF_DEVICE_TYPE: "smartthings_hvac"}
    # Cuando options tiene CONF_TEMP_NATIVE_TARGET, debe usarlo
    mock_entry.options = {CONF_TEMP_NATIVE_TARGET: UnitOfTemperature.FAHRENHEIT}

    handler = OptionsFlowHandler(mock_entry)
    schema = handler._get_options_schema()

    # Encontrar el campo CONF_TEMP_NATIVE_TARGET en el schema
    targ_key = None
    for key in schema.schema:
        if hasattr(key, "schema") and key.schema == CONF_TEMP_NATIVE_TARGET:
            targ_key = key
            break

    assert targ_key is not None
    # M71: si opt_targ = None (mutante), el default caería a DEFAULT_CONF_TEMP_UNIT en lugar de °F
    assert targ_key.default() == UnitOfTemperature.FAHRENHEIT


def test_options_schema_temp_target_fallback_to_default():
    """Kills mutant 72: cuando options está vacío, usa DEFAULT_CONF_TEMP_UNIT."""
    from custom_components.climate_ip.const import (
        CONF_TEMP_NATIVE_TARGET,
        DEFAULT_CONF_TEMP_UNIT,
    )

    mock_entry = MagicMock()
    mock_entry.data = {}
    mock_entry.options = {}  # Sin CONF_TEMP_NATIVE_TARGET

    handler = OptionsFlowHandler(mock_entry)
    schema = handler._get_options_schema()

    targ_key = None
    for key in schema.schema:
        if hasattr(key, "schema") and key.schema == CONF_TEMP_NATIVE_TARGET:
            targ_key = key
            break

    assert targ_key is not None
    # Sin nada en options, debe usar el fallback DEFAULT_CONF_TEMP_UNIT
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT


def test_options_schema_temp_step_from_data():
    """Kills mutants 82, 83: opt_step = data.get(CONF_TARGET_TEMP_STEP) as secondary fallback."""
    from custom_components.climate_ip.const import CONF_TARGET_TEMP_STEP

    mock_entry = MagicMock()
    # options missing step but data contains it — triggers secondary fallback
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
    # M82: si opt_step = None, caería al tercer nivel (DEFAULT_TARGET_TEMP_STEP)
    # M83: si usa data.get(None), tampoco encontraría 0.5
    assert step_key.default() == "0.5"


def test_options_schema_temp_step_data_fallback_default():
    """Kills mutants 82, 83 (variante): cuando ni options ni data tienen el step."""
    from custom_components.climate_ip.const import (
        CONF_TARGET_TEMP_STEP,
        DEFAULT_TARGET_TEMP_STEP,
    )

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}  # Tampoco en data — activa el tercer nivel DEFAULT_TARGET_TEMP_STEP

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
    # M11: Para que no aborte en no_coordinator_found, añadimos un coordinator válido.
    # Second device has id=None. Default fallback yields empty string..
    devices = [{"id": "0", "uuid": "coord_uuid"}, {"id": None, "Mode": "cool"}]

    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
        patch.object(flow, "async_step_select_devices", return_value={"type": "form"}),
    ):
        result = await flow._async_process_mim_h03(devices)

        assert result["type"] == FlowResultType.FORM
        # Original: or "" -> "id": ""
        # Mutant M11: or "XXXX" -> "id": "XXXX"
        assert flow.flow_data[CONF_DISCOVERED_DEVICES][0]["id"] == ""


@pytest.mark.asyncio
async def test_rest_api_aborts_if_already_configured_normal_flow(hass):
    """Verify mutant M92 kill: Flujo normal aborta si el dispositivo ya existe."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    flow.context = {}

    with patch(
        "custom_components.climate_ip.config_flow.async_get_clientsession"
    ) as mock_session:
        mock_get = AsyncMock()
        mock_get.__aenter__.return_value.status = 200
        mock_session.return_value.get.return_value = mock_get

        # Mock _abort_if_unique_id_configured para que lance el abort garantizado
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
                # Si Pytest llega a esta línea, significa que el Mutante 92
                # cambió "if self.reauth_entry is None:" por "is not None",
                # saltándose la validación. ¡BOOM!
                pytest.fail(
                    "Mutante 92 sobrevive: No se llamó a _abort_if_unique_id_configured"
                )
            except AbortFlow as e:
                # El código original lanza el abort correctamente, cazando al mutante
                assert e.reason == "already_configured"
