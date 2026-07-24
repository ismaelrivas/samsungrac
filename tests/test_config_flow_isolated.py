"""Test config flow isolated steps to kill mutants."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from homeassistant.data_entry_flow import FlowResultType
from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    CONF_DEVICE_ID,
)
from homeassistant.const import CONF_IP_ADDRESS
import ssl


@pytest.mark.asyncio
async def test_samsung_device_type_routing_mutants():
    """Kills mutants 2 y 9: Verifica que el ruteo pasa el flag is_8888 estricto."""
    flow = ClimateIpConfigFlow()

    with patch.object(flow, "_async_process_samsung_device_step") as mock_process:
        await flow.async_step_samsung_2878({"dummy": "data"})
        # Mata el Mutante 2 (is_8888=None) y 9 (is_8888=True en vez de False)
        mock_process.assert_called_once_with(
            step_id="samsung_2878", is_8888=False, user_input={"dummy": "data"}
        )

    flow = ClimateIpConfigFlow()
    with patch.object(flow, "_async_process_samsung_device_step") as mock_process:
        await flow.async_step_samsung_8888({"dummy": "data"})
        # Verify mutant kill análogos para 8888
        mock_process.assert_called_once_with(
            step_id="samsung_8888", is_8888=True, user_input={"dummy": "data"}
        )


@pytest.mark.asyncio
async def test_reconfigure_arguments_mutants():
    """Kills mutants 5 y 6: Verifica que user_input no se convierte en None."""
    flow = ClimateIpConfigFlow()
    flow._get_reconfigure_entry = MagicMock(return_value=MagicMock(data={}))

    with patch.object(flow, "async_step_reconfigure_confirm") as mock_confirm:
        test_input = {CONF_IP_ADDRESS: "1.1.1.1"}
        await flow.async_step_reconfigure(test_input)
        # If mutant cambia u_input = None, esta aserción reventará
        mock_confirm.assert_called_once_with(test_input)


@pytest.mark.asyncio
async def test_connection_safe_ssl_mutant(hass):
    """Kills mutant 41: Asegura que check_hostname es estrictamente False."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "192.168.1.100",
    }

    with (
        patch(
            "custom_components.climate_ip.config_flow.ssl.create_default_context"
        ) as mock_ssl,
        patch(
            "custom_components.climate_ip.config_flow.async_get_clientsession"
        ) as mock_session,
    ):
        mock_context = MagicMock()
        mock_ssl.return_value = mock_context

        mock_get = AsyncMock()
        mock_get.__aenter__.return_value.status = 200
        mock_session.return_value.get.return_value = mock_get

        await flow._test_connection_safe()

        # Verify mutant M41 kill: Si es None en vez de False, esto falla
        assert mock_context.check_hostname is False
        assert mock_context.verify_mode == ssl.CERT_NONE


@pytest.mark.asyncio
async def test_test_connection_fallbacks_and_progress():
    """Kills mutants 47, 48, 60, 63, 67."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
    }

    # 1. Matar M60, M63, M67 (Tareas de progreso a None)
    flow.task = MagicMock()
    flow.task.done.return_value = False  # Simulamos que la tarea está pendiente

    result = await flow.async_step_test_connection()
    assert result["type"] == FlowResultType.SHOW_PROGRESS
    # If mutant anula p_task, esto falla
    assert result["progress_task"] is flow.task

    # 2. Matar M47, M48 (Fallback de error)
    flow.task.done.return_value = True
    # Simulamos error sin "error" key para forzar el fallback "cannot_connect"
    flow.task.result.return_value = {"ok": False}

    result_done = await flow.async_step_test_connection()
    assert result_done["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result_done["step_id"] == "handle_error"
    # If mutant usa "XXcannot_connectXX", esto falla
    assert flow.flow_data["error_key"] == "cannot_connect"


@pytest.mark.asyncio
async def test_await_button_fallbacks():
    """Kills mutants 29, 31, 34, 89, 91, 92."""
    flow = ClimateIpConfigFlow()
    # Sin IP configurada para forzar el fallback en description_placeholders
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}

    # 1. Matar M89, M91, M92 (Fallback de IP a "")
    flow.task = MagicMock()
    flow.task.done.return_value = False
    result = await flow.async_step_await_button()
    assert (
        result["description_placeholders"]["ip_address"] == ""
    )  # If mutmut puso "XXXX", falla

    # 2. Matar M29, 31, 34 (Fallback de Token a "")
    flow.task.done.return_value = True
    # Devolvemos ok: True pero sin token en el diccionario
    flow.task.result.return_value = {"ok": True}

    with patch(
        "custom_components.climate_ip.config_flow.sanitize_token", return_value=False
    ):
        await flow.async_step_await_button()
        assert flow.flow_data["error_key"] == "token_acquisition_failed"
        # Esto mata indirectamente a los mutantes del token porque validamos el flujo exacto


@pytest.mark.asyncio
async def test_mim_h03_discovery_fallbacks():
    """Kills mutants 11 y 92 en _async_process_mim_h03."""
    flow = ClimateIpConfigFlow()
    flow.reauth_entry = MagicMock()  # Evitar chequeos de abort

    # Pass un dispositivo sin "id" y sin "Mode" para forzar que sea coordinador y el fallback a ""
    discovered = [{"uuid": "test_uuid"}]

    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
    ):
        await flow._async_process_mim_h03(discovered)

        # Verify mutant M11 kill y M92: If mutant inyectó "XXXX" en el or "", esto falla
        assert flow.flow_data[CONF_DEVICE_ID] == ""


@pytest.mark.asyncio
async def test_fallback_raw_discovery_controller_mutant(hass):
    """Kills mutant 8: controller = ''."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {}

    # Forzamos una excepción en la inicialización de YamlController
    with patch(
        "custom_components.climate_ip.config_flow.YamlController",
        side_effect=Exception("Boom"),
    ):
        result = await flow._async_fallback_raw_discovery({})

        # Debe atrapar la excepción y abortar graciosamente.
        # If mutant 8 puso controller="", el bloque finally hará "".async_shutdown()
        # lanzando AttributeError y fallando este test con un error no controlado.
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"


@pytest.mark.asyncio
async def test_connection_safe_unique_id_empty_fallback():
    """Kills mutants 73-77: unique_id fallback a ''."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
    }  # Sin MAC ni UUID

    with patch("custom_components.climate_ip.config_flow.YamlController") as mock_yaml:
        mock_ctrl = mock_yaml.return_value
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)

        await flow._test_connection_safe()
        args, kwargs = mock_yaml.call_args
        # If mutant puso None o "XXXX", esto falla
        assert kwargs["config"]["unique_id"] == ""
        # M77: Verificar que se inyectó el config_file
        from custom_components.climate_ip.const import (
            CONF_CONFIG_FILE,
            DEVICE_TYPE_TO_CONFIG_FILE,
        )

        assert (
            kwargs["config"].get(CONF_CONFIG_FILE)
            == DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_SAMSUNG_2878]
        )


@pytest.mark.asyncio
async def test_await_button_token_missing_fallback():
    """Kills mutants 29, 31, 34: raw_token = get('token', '')."""
    flow = ClimateIpConfigFlow()
    flow.task = MagicMock()
    flow.task.done.return_value = True
    # Devolvemos un dicccionario SIN "token"
    flow.task.result.return_value = {"ok": True}

    with patch("custom_components.climate_ip.config_flow.sanitize_token") as mock_san:
        mock_san.return_value = False
        await flow.async_step_await_button()
        # Original lee "", mutante lee None o "XXXX"
        mock_san.assert_called_once_with("")


@pytest.mark.asyncio
async def test_select_devices_error_schema_default_keys():
    """Kills mutants 23, 35, 37, 39: def_keys y schema al enviar selección vacía."""
    from custom_components.climate_ip.const import (
        CONF_DISCOVERED_DEVICES,
        CONF_SELECTED_DEVICES,
    )

    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [
            {"id": "dev1", "name": "Indoor Unit 1"},
            {"id": "dev2", "name": "Indoor Unit 2"},
        ]
    }

    # Simula submit con selección vacía — activa la rama de error con def_keys
    result = await flow.async_step_select_devices(
        user_input={CONF_SELECTED_DEVICES: []}
    )

    assert result["errors"] == {"base": "no_devices_selected"}
    schema = result["data_schema"]

    # Encontrar el campo CONF_SELECTED_DEVICES en el schema
    sel_key = None
    for key in schema.schema:
        if hasattr(key, "schema") and key.schema == CONF_SELECTED_DEVICES:
            sel_key = key
            break

    assert sel_key is not None, "CONF_SELECTED_DEVICES no encontrado en el schema"

    # M35/M37: default debe ser la lista de IDs reales, no None
    default_val = sel_key.default()
    assert default_val == ["dev1", "dev2"], (
        f"Expected ['dev1', 'dev2'], got {default_val}"
    )

    # M23: verificar que los valores de default son los IDs, no None
    assert None not in default_val

    # M39: verificar que las opciones del selector son las correctas (no None)
    selector = schema.schema[sel_key]
    assert hasattr(selector, "options"), "El selector debe tener opciones"
    assert selector.options is not None, (
        "El mutante asignó None a las opciones del selector"
    )


@pytest.mark.asyncio
async def test_select_devices_unique_id_from_device_id():
    """Kills mutants 62, 63: tercer nivel del fallback de unique_id (CONF_DEVICE_ID)."""
    from custom_components.climate_ip.const import (
        CONF_DISCOVERED_DEVICES,
        CONF_SELECTED_DEVICES,
    )

    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DISCOVERED_DEVICES: [{"id": "dev_abc", "name": "Unit ABC"}],
        CONF_DEVICE_ID: "dev_abc",
        # Sin "unique_id" ni CONF_MAC — fuerza el tercer nivel de fallback
    }

    with (
        patch.object(flow, "async_set_unique_id") as mock_set_uid,
        patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
    ):
        await flow.async_step_select_devices(
            user_input={CONF_SELECTED_DEVICES: ["dev_abc"]}
        )

        # M62: si el mutante pone main_unique_id = None, no se llama async_set_unique_id
        # M63: si pone flow_data.get(None), tampoco lo encontrará
        mock_set_uid.assert_called_once_with("dev_abc", raise_on_progress=False)


@pytest.mark.asyncio
async def test_discover_uuid_controller_init_none_is_correct_start():
    """Kills mutant 15: controller = None al inicio (no controller = '')."""

    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    flow.hass = MagicMock()

    with patch(
        "custom_components.climate_ip.config_flow.YamlController",
        side_effect=Exception("Constructor Crash"),
    ):
        result = await flow.async_step_discover_uuid()
        # If mutant puso controller="" en vez de None,
        # al hacer if controller is not None en el finally, intentará "".async_shutdown()
        # y explotará con AttributeError en lugar de retornar el FlowResult.
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "unknown_error"


@pytest.mark.asyncio
async def test_discover_uuid_hasattr_exact_attribute_name():
    """Kills mutants 39, 40: hasattr debe buscar exactamente 'discovered_devices'."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    flow.hass = MagicMock()
    # unique_id del flow es solo-lectura; lo que importa aquí es el del mock_ctrl

    with patch("custom_components.climate_ip.config_flow.YamlController") as mock_yaml:
        mock_ctrl = MagicMock(
            spec=[
                "initialize",
                "async_get_status",
                "async_shutdown",
                "discovered_devices",
                "unique_id",
                "device_id",
            ]
        )
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)
        mock_ctrl.async_shutdown = AsyncMock()
        # Solo tiene el atributo 'discovered_devices' (no 'XXdiscovered_devicesXX')
        mock_ctrl.discovered_devices = [{"uuid": "abc123", "id": "1"}]
        mock_ctrl.unique_id = "test_uid"
        mock_ctrl.device_id = "1"
        mock_yaml.return_value = mock_ctrl

        with patch.object(
            flow,
            "_async_process_samsung_8888_discovery",
            return_value={"type": "create_entry"},
        ) as mock_proc:
            await flow.async_step_discover_uuid()
            # M39/M40: si el hasattr busca "XXdiscovered_devicesXX" o "DISCOVERED_DEVICES",
            # raw_devs quedará None y mock_proc recibirá [] en vez de la lista real.
            mock_proc.assert_called_once()
            called_devices = mock_proc.call_args[0][0]
            assert len(called_devices) == 1
            assert called_devices[0]["uuid"] == "abc123"


@pytest.mark.asyncio
async def test_discover_uuid_invalid_header_controller_shutdown():
    """Kills mutant 62: verifica que controller.async_shutdown se llama en InvalidHeaderError."""
    from custom_components.climate_ip.exceptions import InvalidHeaderError

    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
    }
    flow.hass = MagicMock()
    # unique_id es propiedad de solo lectura — ya es None en un flow nuevo

    with patch("custom_components.climate_ip.config_flow.YamlController") as mock_yaml:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(side_effect=InvalidHeaderError("bad header"))
        mock_ctrl.async_shutdown = AsyncMock()
        mock_yaml.return_value = mock_ctrl

        with patch.object(
            flow,
            "_async_fallback_raw_discovery",
            return_value={"type": "abort", "reason": "cannot_connect"},
        ) as mock_fallback:
            # Create un mock parent para rastrear el orden
            manager = MagicMock()
            manager.attach_mock(mock_ctrl.async_shutdown, "shutdown")
            manager.attach_mock(mock_fallback, "fallback")

            await flow.async_step_discover_uuid()

            # M62: verificar que shutdown se llama ANTES que fallback.
            # If mutant cambia el if a 'is None', el shutdown se salta en el except,
            # el fallback se llama, y luego el finally hace el shutdown.
            # El orden sería [fallback, shutdown]. El código correcto es [shutdown, fallback, shutdown(opcional)].
            expected_calls = [manager.mock_calls[0], manager.mock_calls[1]]
            assert expected_calls[0][0] == "shutdown", (
                "Shutdown debe llamarse antes del fallback"
            )
            assert expected_calls[1][0] == "fallback"
