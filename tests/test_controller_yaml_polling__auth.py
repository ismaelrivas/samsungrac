from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import AuthError


# =====================================================================
# UTILITY HELPERS FOR YAML POLLING TESTS
# =====================================================================
class NakedObj:
    """Sterile object without mock overhead to prevent side-effects."""

    def __init__(self, **kwargs):
        self.debug = False
        self.name = "TestName"
        self.ip_address = "1.2.3.4"
        self.available = True
        self.device_id = "XXXX"
        self.hass = __import__("unittest.mock").mock.MagicMock()
        self.__dict__.update(kwargs)


class DummyController(NakedObj):
    """Simulated controller resistant to AttributeErrors."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Prevention of common AttributeErrors in poller
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
    return loader


# =====================================================================


async def test_async_update_state_auth_refresh_flow():
    """Verifica el flujo de recuperación automática cuando el token expira (401)."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    mock_controller.config.get.return_value = "samsung_2878"
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.token = "OLD_TOKEN"
    mock_controller.debug = False

    # Configuración de Side Effects: Falla por Auth la primera vez, tiene éxito la segunda
    mock_controller.loader.state_getter.async_update_state.side_effect = [
        AuthError("401 Unauthorized"),
        {"status": "ok"},
    ]

    # El método final retorna el '.value' del state_getter
    mock_controller.loader.state_getter.value = {"status": "ok"}
    poller.async_update_properties_from_state = AsyncMock()

    # Interceptamos la obtención del nuevo token y el despachador
    with patch.object(
        poller, "_refresh_smartthings_token", return_value="NEW_TOKEN_999"
    ):
        with patch.object(
            poller, "_update_all_connections_token"
        ) as mock_update_dispatch:
            # Simulamos que venimos de un error de conexión para asertar el reseteo
            poller._consecutive_connection_errors = 2

            result = await poller.async_update_state()

            # 1. We assert que el controlador recibió la nueva credencial
            assert mock_controller.token == "NEW_TOKEN_999"

            # 2. We assert que se emitió la orden de actualizar las conexiones hijas
            mock_update_dispatch.assert_called_once_with("NEW_TOKEN_999")

            # 3. We assert que el callback del usuario se llamó (Kills mutant and -> or)
            mock_controller.on_token_refreshed.assert_called_once_with("NEW_TOKEN_999")

            # 4. We assert que el contador de errores se reseteó a 0 estrictamente
            assert poller._consecutive_connection_errors == 0

            # 5. We assert que state_getter se llamó con los argumentos exactos (Mata debug = False -> True)
            mock_controller.loader.state_getter.async_update_state.assert_called_with(
                None, False
            )

            # 6. We assert que la ejecución retornó el valor exitoso tras el retry
            assert result == {"status": "ok"}

    # Validamos que on_token_refreshed no se llama si es None (mutante AttributeError)
    mock_controller.on_token_refreshed = None
    mock_controller.token = "OLD_TOKEN"
    mock_controller.loader.state_getter.async_update_state.side_effect = [
        AuthError("401"),
        {"status": "ok"},
    ]
    with patch.object(
        poller, "_refresh_smartthings_token", return_value="NEW_TOKEN_999"
    ):
        with patch.object(poller, "_update_all_connections_token"):
            await poller.async_update_state()


@patch(
    "custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.OAuth2Session"
)
@patch(
    "custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.async_get_config_entry_implementation"
)
async def test_refresh_smartthings_token_success(mock_get_impl, mock_oauth_session):
    """Test successful refresh of SmartThings token."""
    mock_controller = MagicMock()
    mock_controller.hass = MagicMock()
    mock_controller.log_prefix = "[AuthTest]"

    # 1. Mock de las config_entries
    mock_entry = MagicMock()
    mock_controller.hass.config_entries.async_entries.return_value = [mock_entry]

    # 2. Mock del Session y token
    mock_session_instance = AsyncMock()
    mock_session_instance.token = {"access_token": "nuevo_token_refrescado"}
    mock_oauth_session.return_value = mock_session_instance

    poller = YamlStatePoller(mock_controller)

    # Ejecutamos el método
    result = await poller._refresh_smartthings_token()

    # Aserciones estrictas
    mock_controller.hass.config_entries.async_entries.assert_called_with("smartthings")
    mock_get_impl.assert_awaited_once_with(mock_controller.hass, mock_entry)
    mock_oauth_session.assert_called_once_with(
        mock_controller.hass, mock_entry, mock_get_impl.return_value
    )
    mock_session_instance.async_ensure_token_valid.assert_awaited_once()
    assert result == "nuevo_token_refrescado"


@patch(
    "custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.OAuth2Session"
)
@patch(
    "custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.async_get_config_entry_implementation"
)
@patch("custom_components.climate_ip.controller_yaml_polling._LOGGER")
async def test_refresh_smartthings_token_sniper_failures(
    mock_logger, mock_get_impl, mock_oauth_session
):
    """Sniper: Test token refresh failure paths strictly checking loggers and missing attributes."""

    # Dummy estricto para evitar MagicMocks donde testeamos hasattr/getattr
    class DummyController:
        def __init__(self):
            self.debug = False
            self.name = "TestName"
            self.ip_address = "1.2.3.4"
            self.available = True
            self.device_id = "XXXX"
            self.log_prefix = "[AuthTest]"
            # hass no está definido a propósito al inicio

    mock_controller = DummyController()
    poller = YamlStatePoller(mock_controller)

    # 1. Fallo: No hay hass configurado (Atributo inexistente)
    # Originalmente retorna None silenciosamente.
    # Si el mutant cambia el getattr default a "XXXX", pasará, fallará más abajo y lanzará un _LOGGER.error.
    assert await poller._refresh_smartthings_token() is None
    mock_logger.error.assert_not_called()
    mock_logger.debug.assert_not_called()

    # Le ponemos un hass mockeado para las siguientes pruebas
    mock_controller.hass = MagicMock()

    # 2. Fallo: hass es None explícitamente
    mock_controller.hass = None
    assert await poller._refresh_smartthings_token() is None
    mock_logger.error.assert_not_called()
    mock_logger.debug.assert_not_called()

    # Restauramos hass funcional
    mock_controller.hass = MagicMock()

    # 3. Fallo: No hay config entries (Lista vacía)
    mock_logger.reset_mock()
    mock_controller.hass.config_entries.async_entries.return_value = []
    assert await poller._refresh_smartthings_token() is None
    # Debe loguear un debug informando que no hay entries, no un error
    mock_logger.debug.assert_called_once()
    mock_logger.error.assert_not_called()

    # 4. Fallo: Exception explícita en async_ensure_token_valid()
    mock_logger.reset_mock()
    mock_controller.hass.config_entries.async_entries.return_value = [MagicMock()]

    mock_session_instance = AsyncMock()
    mock_session_instance.async_ensure_token_valid.side_effect = Exception(
        "Auth Server Down"
    )
    mock_oauth_session.return_value = mock_session_instance

    assert await poller._refresh_smartthings_token() is None
    # Debe loguear un error con la excepción
    mock_logger.error.assert_called_once()
    mock_logger.debug.assert_not_called()


def test_update_all_connections_token():
    """Test propagating new token to all connections."""
    mock_controller = MagicMock()

    mock_conn1 = MagicMock()
    mock_conn1.update_auth_token = MagicMock()

    mock_prop1 = MagicMock()
    mock_prop1.get_connection.return_value = mock_conn1

    mock_conn2 = MagicMock()  # No update_auth_token method
    del mock_conn2.update_auth_token

    mock_prop2 = MagicMock()
    mock_prop2.get_connection.return_value = mock_conn2

    poller = YamlStatePoller(mock_controller)
    poller._all_props = MagicMock(return_value=[mock_prop1, mock_prop2, None])

    poller._update_all_connections_token("nuevo_token")
    mock_conn1.update_auth_token.assert_called_once_with("nuevo_token")


async def test_async_update_state_auth_refresh_exception_handling():
    """Test AuthError refresh exception flow."""
    from custom_components.climate_ip.exceptions import AuthError

    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = None  # Bypass network check

    mock_controller.token = "OLD"
    mock_controller.debug = False
    mock_controller.loader.state_getter.value = {}

    poller = YamlStatePoller(mock_controller)

    # 1. async_update_state throws AuthError
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=AuthError
    )

    # 2. Refresh succeeds
    poller._refresh_smartthings_token = AsyncMock(return_value=True)

    # 3. But post-refresh state fetch throws ANOTHER exception
    # (Since we mock it statically here, it will always throw. Let's make it throw a different error)
    poller.controller.loader.state_getter.async_update_state.side_effect = [
        AuthError("err"),
        ValueError("Post refresh crash"),
    ]

    with pytest.raises(UpdateFailed, match="Retry after token refresh failed"):
        await poller.async_update_state()


async def test_async_update_state_auth_refresh_fails_permanently():
    """Test AuthError where token refresh itself fails."""
    from custom_components.climate_ip.exceptions import AuthError

    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = None

    mock_controller.token = "OLD"
    mock_controller.debug = False
    mock_controller.loader.state_getter.value = {}

    poller = YamlStatePoller(mock_controller)

    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=AuthError
    )
    poller._refresh_smartthings_token = AsyncMock(return_value=False)

    from homeassistant.exceptions import ConfigEntryAuthFailed

    with pytest.raises(ConfigEntryAuthFailed, match="Authentication failed"):
        await poller.async_update_state()


def test_update_all_connections_token_deduplication():
    """Kills mutants lógicos (and/or flip) y fallback None en get_connection"""
    poller = YamlStatePoller(MagicMock())
    conn_mock = MagicMock()

    # Create dos props que devuelven la MISMA conexión
    prop1 = MagicMock()
    prop1.get_connection.return_value = conn_mock
    prop2 = MagicMock()
    prop2.get_connection.return_value = conn_mock

    poller._all_props = MagicMock(return_value=[prop1, prop2])

    poller._update_all_connections_token("new_token")

    # Aserción hiper-estricta: sólo debe llamarse 1 vez, a pesar de haber 2 propiedades (mata 'or' flip)
    conn_mock.update_auth_token.assert_called_once_with("new_token")
    # Asegura que el fallback a None no se ha corrompido
    prop1.get_connection.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_auth_refresh_token_getattr_missing():
    """Valida que el refresco de token funcione cuando el token actual es explícitamente None (Tipado estricto)."""
    mock_controller = MagicMock()
    mock_controller.token = (
        None  # <-- En lugar de delattr, respetamos la estructura pero vaciamos el valor
    )
    mock_controller.debug = False  # <-- Atributo exigido por tipado estricto

    poller = YamlStatePoller(mock_controller)
    poller.controller.config = {"device_type": "Other"}
    poller.controller.loader.is_fully_initialized = True

    # Mock de actualización de estado y la variable .value requerida al final
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=[AuthError("401"), {"state": "ok"}]
    )
    poller.controller.loader.state_getter.value = {
        "state": "ok"
    }  # <-- Exigido al final de async_update_state

    poller._refresh_smartthings_token = AsyncMock(return_value="NewToken")
    poller.async_update_properties_from_state = AsyncMock()
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})
    poller._update_all_connections_token = MagicMock()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        return_value=True,
    ):
        await poller.async_update_state()

    # Aserción: verificamos que el flujo se completó y despachó el nuevo token
    poller._update_all_connections_token.assert_called_once_with("NewToken")
