from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import CannotConnect


# =====================================================================
# UTILIDADES TÁCTICAS RESCATADAS DEL MONOLITO
# =====================================================================
class NakedObj:
    """Objeto estéril sin magia de Mocks para evitar side-effects."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class DummyController(NakedObj):
    """Controlador simulado resistente a AttributeErrors."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Prevención de AttributeErrors comunes en el poller
        if not hasattr(self, "config"):
            self.config = {}
        if not hasattr(self, "log_prefix"):
            self.log_prefix = "TEST"
        if not hasattr(self, "ip_address"):
            self.ip_address = "127.0.0.1"
        if not hasattr(self, "loader"):
            self.loader = create_valid_loader()


def create_valid_loader():
    """Crea un loader mínimo para evadir validaciones tempranas."""
    from unittest.mock import MagicMock

    loader = MagicMock()
    loader.is_fully_initialized = True
    loader.operations = {}
    loader.properties = {}
    loader.sensors = {}
    loader.state_getter = NakedObj(value={})
    from unittest.mock import AsyncMock

    loader.state_getter.async_update_state = AsyncMock()
    return loader


# =====================================================================


@patch("custom_components.climate_ip.controller_yaml_polling.async_create_issue")
def test_try_create_repair_issue_flow(mock_async_create_issue):
    """Test control flow of _try_create_repair_issue without checking cosmetic strings."""
    mock_controller = MagicMock()
    mock_controller.hass = MagicMock()
    mock_controller.ip_address = "192.168.1.100"
    mock_controller.name = "Test AC"

    poller = YamlStatePoller(mock_controller)

    # Call with hass object available
    poller._try_create_repair_issue()
    assert mock_async_create_issue.called
    assert mock_async_create_issue.call_count == 1

    # Call without hass object (tests 3rd arg default 'None' of getattr)
    mock_async_create_issue.reset_mock()
    poller.controller = MagicMock(spec=[])
    poller._try_create_repair_issue()
    assert not mock_async_create_issue.called


async def test_async_update_state_early_exits_and_ping():
    """Aserta que la falta de getter o el fallo de ping abortan la petición de red."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # 1. Sin state_getter (Mata mutantes en `if not self.controller.loader.state_getter`)
    mock_controller.loader.state_getter = None
    with pytest.raises(UpdateFailed, match="State getter is not initialized"):
        await poller.async_update_state()

    # 2. Ping ICMP fallido para dispositivos no-2878
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.config.get.return_value = (
        "rest_api"  # Falsa la guardia de DEVICE_TYPE_SAMSUNG_2878
    )
    mock_controller.ip_address = "192.168.1.100"

    # Simulamos que la red no es alcanzable
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        return_value=False,
    ) as mock_ping:
        with pytest.raises(CannotConnect, match="Host unreachable"):
            await poller.async_update_state()

        # Aserciones estrictas del pre-check (Frente de Red)
        mock_controller.config.get.assert_called_with("device_type")
        mock_ping.assert_called_once_with("192.168.1.100", mock_controller.log_prefix)

        # Mata mutantes en la matemática del contador (ej. += 2 en lugar de += 1)
        assert poller._consecutive_connection_errors == 1

    # 3. Cortocircuito de Reachability por ip_address = None (Mata mutante and -> or)
    mock_controller.ip_address = None
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        return_value=False,
    ) as mock_ping_none:
        # Hacemos que state_getter falle para terminar la función, o que devuelva None
        mock_controller.loader.state_getter.async_update_state.return_value = None
        with pytest.raises(UpdateFailed):
            await poller.async_update_state()
        mock_ping_none.assert_not_called()


async def test_async_update_state_network_failures_and_cache():
    """Valida que un CannotConnect devuelve la caché interna si los reintentos son <= 2."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # Esquivamos el ping para ir directo a la red
    mock_controller.config.get.return_value = "samsung_2878"
    mock_controller.loader.state_getter = AsyncMock()

    # Mockeamos el resto de dependencias para evitar ruido
    poller.async_update_properties_from_state = AsyncMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False

    # Simulamos que ya tenemos una caché válida de un estado anterior
    poller._cached_device_state = {"power": "on"}
    poller._consecutive_connection_errors = 0

    # Inyectamos una excepción de conexión
    mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect(
        "Timeout HTTP"
    )

    result = await poller.async_update_state()

    # Asertamos que no explotó y devolvió el estado rescatado
    assert result == {"power": "on"}
    # Asertamos que el contador de errores subió en la rama `else`
    assert poller._consecutive_connection_errors == 1

    # Inyectamos el límite fatal (3 errores)
    poller._consecutive_connection_errors = 2
    poller._try_create_repair_issue = MagicMock()

    with pytest.raises(UpdateFailed, match="Device unreachable: Timeout HTTP"):
        await poller.async_update_state()

    # Asertamos que intentó crear el issue al llegar a 3
    poller._try_create_repair_issue.assert_called_once()

    # Validamos la resolución del Issue (Cuando la conexión se recupera)
    poller._consecutive_connection_errors = 1
    mock_controller.loader.state_getter.async_update_state.side_effect = None
    mock_controller.loader.state_getter.async_update_state.return_value = {
        "power": "on"
    }
    mock_controller.loader.state_getter.value = {"power": "on"}
    mock_controller.ip_address = "192.168.1.100"

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
    ) as mock_delete_issue:
        await poller.async_update_state()
        # Verificación estricta de que se borró el issue con los parámetros correctos
        mock_delete_issue.assert_called_once_with(
            mock_controller.hass, "climate_ip", "connection_failed_192.168.1.100"
        )


async def test_async_update_state_persistently_offline():
    """Verifica que el error 'persistently offline' asigna exactamente 2 al contador."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from custom_components.climate_ip.exceptions import CannotConnect
    from homeassistant.helpers.update_coordinator import UpdateFailed
    import pytest
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.config.get.return_value = "REST_API"

    # 1. Fallo "persistently offline" (Mata mutantes en `if "persistently offline" in str(e)`)
    mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect(
        "Host unreachable (ICMP ping failed). Device is persistently offline."
    )

    with pytest.raises(UpdateFailed):
        await poller.async_update_state()

    assert poller._consecutive_connection_errors == 2

    # 2. Fallo de red genérico (Debe sumar 1, en lugar de igualar a 2)
    poller._consecutive_connection_errors = 0
    mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect(
        "Timeout"
    )

    with pytest.raises(UpdateFailed):
        await poller.async_update_state()

    assert poller._consecutive_connection_errors == 1


@patch("custom_components.climate_ip.controller_yaml_polling.async_create_issue")
def test_try_create_repair_issue_exception_handling(mock_create_issue):
    """Test that _try_create_repair_issue handles exceptions silently and gracefully."""
    mock_controller = MagicMock()
    mock_controller.hass = MagicMock()

    # 1. Simulate an exception in the core HA component
    mock_create_issue.side_effect = Exception("Simulated Core Drop")

    poller = YamlStatePoller(mock_controller)

    # This should not raise an exception
    poller._try_create_repair_issue()

    # Verify the exception was swallowed and flow continued
    assert mock_create_issue.called


async def test_async_shutdown():
    """Test that shutdown closes connections cleanly."""
    mock_controller = MagicMock()
    mock_connection = AsyncMock()
    mock_controller.loader.connection = mock_connection

    poller = YamlStatePoller(mock_controller)

    await poller.async_shutdown()

    # The connection should have been told to close
    mock_connection.close.assert_called_once()


@patch(
    "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
    new_callable=AsyncMock,
)
async def test_async_update_state_network_failures_thresholds(mock_reachability):
    """Test the thresholds for consecutive network failures."""
    from custom_components.climate_ip.exceptions import CannotConnect

    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = "192.168.1.100"
    poller = YamlStatePoller(mock_controller)
    poller._try_create_repair_issue = MagicMock()

    mock_reachability.return_value = False

    # 1st failure -> Exception, issue NOT created
    with pytest.raises(CannotConnect, match="Host unreachable"):
        await poller.async_update_state()
    assert poller._consecutive_connection_errors == 1
    poller._try_create_repair_issue.assert_not_called()

    # 2nd failure -> Exception (persistently offline)
    with pytest.raises(CannotConnect, match="persistently offline"):
        await poller.async_update_state()
    assert poller._consecutive_connection_errors == 2
    poller._try_create_repair_issue.assert_not_called()

    # 3rd failure -> Exception (persistently offline) + creates issue
    with pytest.raises(CannotConnect, match="persistently offline"):
        await poller.async_update_state()
    assert poller._consecutive_connection_errors == 3
    poller._try_create_repair_issue.assert_called_once()

    # Recovery on 4th call!
    mock_reachability.return_value = True
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"recovered": True}
    )
    poller.controller.loader.state_getter.value = {"recovered": True}

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
    ) as mock_del:
        res = await poller.async_update_state()
        assert res == {"recovered": True}
        assert poller._consecutive_connection_errors == 0
        mock_del.assert_called_once()


@patch(
    "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
    new_callable=AsyncMock,
)
async def test_async_update_state_network_diagnostics_exceptions(mock_reachability):
    """Test when reachability throws non-CannotConnect exceptions."""
    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = "192.168.1.100"
    poller = YamlStatePoller(mock_controller)

    # Reachability throws a ValueError
    mock_reachability.side_effect = ValueError("Some weird DNS error")

    # The error should be swallowed and we attempt to poll anyway!
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"polled": True}
    )
    poller.controller.loader.state_getter.value = {"polled": True}
    res = await poller.async_update_state()
    assert res == {"polled": True}


async def test_async_shutdown_no_connection():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    mock_controller.loader.connection = None

    # Should not throw, should just sleep and return
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        await poller.async_shutdown()
        mock_sleep.assert_called_once_with(1.0)


async def test_async_shutdown_stop_listening_exception():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    conn = MagicMock()
    conn.stop_listening = AsyncMock(side_effect=ValueError("Boom"))
    mock_controller.loader.connection = conn

    # Bypass the others
    del mock_controller.close_shared_client
    del mock_controller._shared_raw_client
    del conn.close

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await poller.async_shutdown()  # Should not raise
    conn.stop_listening.assert_called_once()
    assert mock_controller.loader.connection is None


async def test_async_shutdown_close_shared_client():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    conn = MagicMock()
    del conn.stop_listening
    del conn.close
    mock_controller.loader.connection = conn

    mock_controller.close_shared_client = AsyncMock(side_effect=ValueError("Boom"))

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await poller.async_shutdown()  # Should not raise
    mock_controller.close_shared_client.assert_called_once()
    assert mock_controller.loader.connection is None


async def test_async_shutdown_shared_raw_client():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    conn = MagicMock()
    del conn.stop_listening
    del conn.close
    mock_controller.loader.connection = conn

    del mock_controller.close_shared_client

    raw_client = MagicMock()
    raw_client.close = AsyncMock(side_effect=ValueError("Boom"))
    mock_controller._shared_raw_client = raw_client

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await poller.async_shutdown()  # Should not raise
    raw_client.close.assert_called_once()
    assert mock_controller._shared_raw_client is None
    assert mock_controller.loader.connection is None


async def test_async_shutdown_conn_close():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    conn = MagicMock()
    del conn.stop_listening
    conn.close = AsyncMock(side_effect=ValueError("Boom"))
    mock_controller.loader.connection = conn

    del mock_controller.close_shared_client
    del mock_controller._shared_raw_client

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await poller.async_shutdown()  # Should not raise
    conn.close.assert_called_once()
    assert mock_controller.loader.connection is None


async def test_update_state_repair_issue_delete_exception():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"a": 1}
    )
    mock_controller.loader.state_getter.value = {"a": 1}
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.discovered_devices = [{"id": "dev1"}]

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue",
        side_effect=Exception("Boom"),
    ):
        res = await poller.async_update_state()
    assert res == {"a": 1}


async def test_update_state_invalid_header_error():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    from custom_components.climate_ip.exceptions import InvalidHeaderError

    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=InvalidHeaderError("Bad header")
    )
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.discovered_devices = [{"id": "dev1"}]

    with pytest.raises(InvalidHeaderError):
        await poller.async_update_state()


async def test_update_state_api_error_cached_fallback():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    from custom_components.climate_ip.exceptions import CannotConnect

    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=CannotConnect("API Failure")
    )
    mock_controller.loader.state_getter.value = {"cached": True}
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.discovered_devices = [{"id": "dev1"}]

    # With cache
    poller._cached_device_state = {"cached": True}
    res = await poller.async_update_state()
    assert res == {"cached": True}

    # Without cache -> raises UpdateFailed
    poller._cached_device_state = None
    from homeassistant.helpers.update_coordinator import UpdateFailed

    with pytest.raises(UpdateFailed):
        await poller.async_update_state()


async def test_update_state_delete_issue_exception():
    """L260-261: Captura de excepción en async_delete_issue."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.ip_address = "1.2.3.4"
    mock_controller.hass = MagicMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"a": 1}
    )

    poller = YamlStatePoller(mock_controller)
    poller._consecutive_connection_errors = 1
    poller._build_device_state_from_hass = AsyncMock(return_value={"a": 1})
    poller.async_update_properties_from_state = AsyncMock()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue",
        side_effect=Exception("Test Error"),
    ):
        # No debe crashear
        await poller.async_update_state()


async def test_async_update_state_sniper_network_ping():
    """Sniper: Dispositivos REST fallan temprano (burbujea CannotConnect de red)."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    # Asignamos ip_address expresamente, pero omitimos otros atributos para forzar getattr fallbacks.
    mock_controller = DummyController(ip_address="192.168.1.100")
    mock_controller.config = {"device_type": "REST"}

    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    poller._consecutive_connection_errors = 1
    poller._cached_device_state = {"a": 1}

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        new_callable=AsyncMock,
    ) as mock_ping:
        # 1. Ping falla
        mock_ping.return_value = False

        with pytest.raises(
            CannotConnect,
            match="^Host unreachable \\(ICMP ping failed\\). Device is persistently offline.$",
        ):
            await poller.async_update_state()

        mock_ping.assert_called_once_with("192.168.1.100", mock_controller.log_prefix)
        assert poller._consecutive_connection_errors == 2

        # 2. Ping falla de nuevo (colapso)
        mock_ping.reset_mock()
        with patch.object(poller, "_try_create_repair_issue") as mock_repair:
            with pytest.raises(
                CannotConnect,
                match="^Host unreachable \\(ICMP ping failed\\). Device is persistently offline.$",
            ):
                await poller.async_update_state()
            assert poller._consecutive_connection_errors == 3
            mock_repair.assert_called_once()

        # 3. Ping lanza excepción pero se captura como diagnóstico, delegando luego a state_getter
        mock_ping.side_effect = Exception("Ping error")
        mock_controller.loader.state_getter.async_update_state.return_value = {
            "state": "ping_failed_but_recovered"
        }
        mock_controller.loader.state_getter.value = {
            "state": "ping_failed_but_recovered"
        }

        res = await poller.async_update_state()
        assert res == {"state": "ping_failed_but_recovered"}


@patch("custom_components.climate_ip.controller_yaml_polling.async_create_issue")
def test_try_create_repair_issue_missing_hass(mock_create_issue):
    """Aniquila mutante de `getattr(self.controller, 'hass', None) -> getattr(...)`"""
    poller = YamlStatePoller(MagicMock(spec=[]))
    poller._try_create_repair_issue()
    mock_create_issue.assert_not_called()


async def test_async_shutdown_raw_client_circuit():
    """Aniquila flip if raw_client and hasattr() a or hasattr()"""
    poller = YamlStatePoller(MagicMock())
    delattr(poller.controller, "close_shared_client")

    # Inyectamos objeto sin 'close', si usa 'or' fallará en runtime al hacer close().
    # El and actúa de circuito cortador seguro.
    class DummyClient:
        pass

    poller.controller._shared_raw_client = DummyClient()

    await poller.async_shutdown()
    assert poller.controller._shared_raw_client is None


async def test_async_update_state_force_connection_errors():
    """Aniquila mutantes de rsplit/split y validación de UpdateFailed."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.config = {"device_type": "Other"}

    # Mockeamos el getter
    poller.controller.loader.state_getter = AsyncMock()

    # Inyectamos CannotConnect. El poller debe capturarlo y relanzar UpdateFailed
    poller.controller.loader.state_getter.async_update_state.side_effect = (
        CannotConnect("Prefix:TargetReason")
    )
    poller._consecutive_connection_errors = 2
    poller._cached_device_state = None

    with pytest.raises(UpdateFailed) as exc:
        await poller.async_update_state()

    assert "TargetReason" in str(exc.value)


async def test_shutdown_raw_client_missing():
    """Mata el mutante de getattr sin fallback en _shared_raw_client (L1049)"""
    poller = YamlStatePoller(MagicMock())
    # DESTRUCCIÓN FÍSICA
    if hasattr(poller.controller, "_shared_raw_client"):
        delattr(poller.controller, "_shared_raw_client")

    # Si mutmut eliminó el None, lanzará AttributeError al evaluar la variable temporal.
    await poller.async_shutdown()
