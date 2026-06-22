"""Tests for YamlStatePoller."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.exceptions import CannotConnect, AuthError
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

def test_yaml_state_poller_initial_state():
    """Test that all properties are strictly initialized to None/zero to prevent silent mutant survival."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # Strict None assertions (kills None -> "" mutations)
    assert poller._cached_device_state is None
    assert poller._last_device_state is None
    
    # Strict value assertions
    assert poller._last_state_fetch_time == 0.0
    assert poller._consecutive_connection_errors == 0
    assert isinstance(poller._pending_updates, dict)
    assert len(poller._pending_updates) == 0
    assert isinstance(poller._prop_template_key_cache, dict)
    assert len(poller._prop_template_key_cache) == 0
    assert poller.fan_modes_list_changed_pending_flicker is False

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
    
    # Call without hass object (should return early)
    mock_async_create_issue.reset_mock()
    mock_controller.hass = None
    poller._try_create_repair_issue()
    assert not mock_async_create_issue.called

# ====================================================================================
# FRENTE A: CORTOCIRCUITOS Y DIAGNÓSTICO DE RED (Ping ICMP)
# ====================================================================================

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
    mock_controller.config.get.return_value = "rest_api" # Falsa la guardia de DEVICE_TYPE_SAMSUNG_2878
    mock_controller.ip_address = "192.168.1.100"
    
    # Simulamos que la red no es alcanzable
    with patch("custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability", return_value=False):
        with pytest.raises(CannotConnect, match="Host unreachable"):
            await poller.async_update_state()
        
        # Mata mutantes en la matemática del contador (ej. += 2 en lugar de += 1)
        assert poller._consecutive_connection_errors == 1

# ====================================================================================
# FRENTE B: TOLERANCIA A FALLOS (RequestException) Y RESCATE DE CACHÉ
# ====================================================================================

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
    
    # Simulamos que ya tenemos una caché válida de un estado anterior
    poller._cached_device_state = {"power": "on"}
    poller._consecutive_connection_errors = 0
    
    # Inyectamos una excepción de conexión
    mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect("Timeout HTTP")
    
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

# ====================================================================================
# FRENTE C: EL HORNO DE AUTENTICACIÓN (AuthError y OAuth2)
# ====================================================================================

async def test_async_update_state_auth_refresh_flow():
    """Verifica el flujo de recuperación automática cuando el token expira (401)."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    mock_controller.config.get.return_value = "samsung_2878"
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.token = "OLD_TOKEN"
    
    # Configuración de Side Effects: Falla por Auth la primera vez, tiene éxito la segunda
    mock_controller.loader.state_getter.async_update_state.side_effect = [
        AuthError("401 Unauthorized"),
        {"status": "ok"}
    ]
    
    # El método final retorna el '.value' del state_getter
    mock_controller.loader.state_getter.value = {"status": "ok"}
    poller.async_update_properties_from_state = AsyncMock()
    
    # Interceptamos la obtención del nuevo token y el despachador
    with patch.object(poller, "_refresh_smartthings_token", return_value="NEW_TOKEN_999"):
        with patch.object(poller, "_update_all_connections_token") as mock_update_dispatch:
            
            result = await poller.async_update_state()
            
            # 1. Asertamos que el controlador recibió la nueva credencial
            assert mock_controller.token == "NEW_TOKEN_999"
            
            # 2. Asertamos que se emitió la orden de actualizar las conexiones hijas
            mock_update_dispatch.assert_called_once_with("NEW_TOKEN_999")
            
            # 3. Asertamos que el callback del usuario se llamó
            mock_controller.on_token_refreshed.assert_called_once_with("NEW_TOKEN_999")
            
            # 4. Asertamos que la ejecución retornó el valor exitoso tras el retry
            assert result == {"status": "ok"}
