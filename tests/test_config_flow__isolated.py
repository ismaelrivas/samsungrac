"""Test config flow isolated steps to kill mutants."""

from __future__ import annotations

import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.data_entry_flow import FlowResultType

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
)


@pytest.mark.asyncio
async def test_samsung_device_type_routing_mutants():
    """Kills mutants 2 y 9: Verifica que el ruteo pasa el flag is_8888 estricto."""
    flow = ClimateIpConfigFlow()

    with patch.object(flow, "_async_process_samsung_device_step") as mock_process:
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_samsung_2878({"dummy": "data"})
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        mock_process.assert_called_once_with(
            step_id="samsung_2878", is_8888=False, user_input={"dummy": "data"}
        )

    flow = ClimateIpConfigFlow()
    with patch.object(flow, "_async_process_samsung_device_step") as mock_process:
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_samsung_8888({"dummy": "data"})
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
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
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_reconfigure(test_input)
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
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
            "custom_components.climate_ip.config_flow_helpers.ssl.create_default_context"
        ) as mock_ssl,
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession"
        ) as mock_session,
    ):
        mock_context = MagicMock()
        mock_ssl.return_value = mock_context

        mock_get = AsyncMock()
        mock_get.__aenter__.return_value.status = 200
        mock_session.return_value.get.return_value = mock_get

        try:
            async with asyncio.timeout(0.5):
                await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

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
    flow.task.done.return_value = False

    try:
        async with asyncio.timeout(0.5):
            result = await flow.async_step_test_connection()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["type"] == FlowResultType.SHOW_PROGRESS
    assert result["progress_task"] is flow.task

    # 2. Matar M47, M48 (Fallback de error)
    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": False}

    try:
        async with asyncio.timeout(0.5):
            result_done = await flow.async_step_test_connection()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result_done["type"] == FlowResultType.SHOW_PROGRESS_DONE
    assert result_done["step_id"] == "handle_error"
    assert flow.flow_data["error_key"] == "cannot_connect"


@pytest.mark.asyncio
async def test_await_button_fallbacks():
    """Kills mutants 29, 31, 34, 89, 91, 92."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}

    flow.task = MagicMock()
    flow.task.done.return_value = False
    try:
        async with asyncio.timeout(0.5):
            result = await flow.async_step_await_button()
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
    assert result["description_placeholders"]["ip_address"] == ""

    flow.task.done.return_value = True
    flow.task.result.return_value = {"ok": True}

    with patch(
        "custom_components.climate_ip.helpers.sanitize_token", return_value=False
    ):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_await_button()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        assert flow.flow_data["error_key"] == "token_acquisition_failed"


@pytest.mark.asyncio
async def test_mim_h03_discovery_fallbacks():
    """Kills mutants 11 y 92 en _async_process_mim_h03."""
    flow = ClimateIpConfigFlow()
    flow.reauth_entry = MagicMock()

    discovered = [{"uuid": "test_uuid"}]

    with (
        patch.object(flow, "async_set_unique_id"),
        patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
    ):
        try:
            async with asyncio.timeout(0.5):
                await flow._async_process_mim_h03(discovered)
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert flow.flow_data[CONF_DEVICE_ID] == ""


@pytest.mark.asyncio
async def test_fallback_raw_discovery_controller_mutant(hass):
    """Kills mutant 8: controller = ''."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {}

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController",
        side_effect=Exception("Boom"),
    ):
        try:
            async with asyncio.timeout(0.5):
                result = await flow._async_fallback_raw_discovery({})
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"


@pytest.mark.asyncio
async def test_connection_safe_unique_id_empty_fallback():
    """Kills mutants 73-77: unique_id fallback a ''."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)
    flow.hass.async_add_executor_job = mock_async_add_executor_job
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "1.1.1.1",
    }

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_yaml:
        mock_ctrl = mock_yaml.return_value
        mock_ctrl.initialize = AsyncMock(return_value=True)
        mock_ctrl.async_get_status = AsyncMock(return_value=True)

        try:
            async with asyncio.timeout(0.5):
                await flow._test_connection_safe()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
        args, kwargs = mock_yaml.call_args
        assert kwargs["config"]["unique_id"] == ""

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
    flow.task.result.return_value = {"ok": True}

    with patch("custom_components.climate_ip.helpers.sanitize_token") as mock_san:
        mock_san.return_value = False
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_await_button()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
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

    try:
        async with asyncio.timeout(0.5):
            result = await flow.async_step_select_devices(
                user_input={CONF_SELECTED_DEVICES: []}
            )
    except TimeoutError:
        pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

    assert result["errors"] == {"base": "no_devices_selected"}
    schema = result["data_schema"]

    sel_key = None
    for key in schema.schema:
        if hasattr(key, "schema") and key.schema == CONF_SELECTED_DEVICES:
            sel_key = key
            break

    assert sel_key is not None, "CONF_SELECTED_DEVICES no encontrado en el schema"

    default_val = sel_key.default()
    assert default_val == [
        "dev1",
        "dev2",
    ], f"Expected ['dev1', 'dev2'], got {default_val}"

    assert None not in default_val

    selector = schema.schema[sel_key]
    assert hasattr(selector, "options"), "El selector debe tener opciones"
    assert (
        selector.options is not None
    ), "The mutant assigned None to selector options"


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
    }

    with (
        patch.object(flow, "async_set_unique_id") as mock_set_uid,
        patch.object(flow, "_create_entry", return_value={"type": "create_entry"}),
    ):
        try:
            async with asyncio.timeout(0.5):
                await flow.async_step_select_devices(
                    user_input={CONF_SELECTED_DEVICES: ["dev_abc"]}
                )
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")

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
    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)
    flow.hass.async_add_executor_job = mock_async_add_executor_job

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController",
        side_effect=Exception("Constructor Crash"),
    ):
        try:
            async with asyncio.timeout(0.5):
                result = await flow.async_step_discover_uuid()
        except TimeoutError:
            pytest.fail("MUTANT KILLED: Asynchronous deadlock detected in flow step.")
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
    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)
    flow.hass.async_add_executor_job = mock_async_add_executor_job

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_yaml:
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
        mock_ctrl.discovered_devices = [{"uuid": "abc123", "id": "1"}]
        mock_ctrl.unique_id = "test_uid"
        mock_ctrl.device_id = "1"
        mock_yaml.return_value = mock_ctrl

        with patch.object(
            flow,
            "_async_process_samsung_8888_discovery",
            return_value={"type": "create_entry"},
        ) as mock_proc:
            try:
                async with asyncio.timeout(0.5):
                    await flow.async_step_discover_uuid()
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )
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
    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)
    flow.hass.async_add_executor_job = mock_async_add_executor_job

    with patch(
        "custom_components.climate_ip.controller_yaml.YamlController"
    ) as mock_yaml:
        mock_ctrl = MagicMock()
        mock_ctrl.initialize = AsyncMock(side_effect=InvalidHeaderError("bad header"))
        mock_ctrl.async_shutdown = AsyncMock()
        mock_yaml.return_value = mock_ctrl

        with patch.object(
            flow,
            "_async_fallback_raw_discovery",
            return_value={"type": "abort", "reason": "cannot_connect"},
        ) as mock_fallback:
            manager = MagicMock()
            manager.attach_mock(mock_ctrl.async_shutdown, "shutdown")
            manager.attach_mock(mock_fallback, "fallback")

            try:
                async with asyncio.timeout(0.5):
                    await flow.async_step_discover_uuid()
            except TimeoutError:
                pytest.fail(
                    "MUTANT KILLED: Asynchronous deadlock detected in flow step."
                )

            expected_calls = [manager.mock_calls[0], manager.mock_calls[1]]
            assert (
                expected_calls[0][0] == "shutdown"
            ), "Shutdown debe llamarse antes del fallback"
            assert expected_calls[1][0] == "fallback"
