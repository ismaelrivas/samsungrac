"""Tests for YamlStatePoller."""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.const import STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.const import DEVICE_TYPE_MIM_H03, DEVICE_TYPE_SAMSUNG_2878
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

# ====================================================================================
# FRENTE D: AUTOPSIA DE DESCUBRIMIENTO (Device Discovery)
# ====================================================================================

async def test_async_update_state_device_discovery():
    """Aserta la extracción del device_id usando el mapa de la caché YAML (MIM-H03)."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    # Configuramos para forzar el bloque de descubrimiento
    mock_controller.loader.is_fully_initialized = False
    mock_controller.config.get.return_value = DEVICE_TYPE_MIM_H03
    mock_controller.device_id = "0" # "0" fuerza la actualización
    
    # Simulamos la caché del loader
    mock_controller.loader._parsed_yaml_cache = {
        "0": { # device_id en config es "0", así que la caché debe usar "0"
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"]
                }
            }
        }
    }
    
    # Payload que devuelve el dispositivo
    fake_full_state = {
        "Devices": [
            {"id": "0", "Mode": "Ignorado"}, # Debe ser ignorado por != "0"
            {"id": "12345", "Mode": "Target"} # Debe ser seleccionado
        ]
    }
    
    # Mockeamos la red y las propiedades
    mock_controller.loader.state_getter.async_update_state = AsyncMock(return_value=fake_full_state)
    mock_controller.loader.async_finish_initialization = AsyncMock()
    poller.async_update_properties_from_state = AsyncMock()
    
    await poller.async_update_state()
    
    print(f"DEBUG device_id after discovery: {mock_controller.device_id}")
    print(f"DEBUG discovered_devices: {mock_controller.discovered_devices}")
    
    # Asertamos rígidamente que saltó el ID "0" y capturó el "12345"
    assert mock_controller.device_id == "12345"
    mock_controller.loader.async_finish_initialization.assert_called_once()

# ====================================================================================
# FRENTE E: RELOJ DE ARENA Y ESCUDO DE DEGRADACIÓN (async_update_properties_from_state)
# ====================================================================================

async def test_async_update_properties_pending_ttl_and_degradation():
    """Verifica el TTL de 15 segundos y la degradación de estados inválidos a UNKNOWN."""
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    poller = YamlStatePoller(mock_controller)
    
    # Propiedad 1: TTL válido (< 15s)
    mock_prop_valid = MagicMock()
    mock_prop_valid.id = "prop_valid"
    mock_prop_valid.convert_hass_to_dev.return_value = "dev_val_valid"
    poller._get_cached_device_key_from_prop = MagicMock(return_value="raw_key")
    
    # Propiedad 2: TTL caducado (> 15s)
    mock_prop_stale = MagicMock()
    mock_prop_stale.id = "prop_stale"
    
    # Propiedad 3: Degradación de estado inválido
    mock_prop_deg = MagicMock()
    mock_prop_deg.id = "prop_deg"
    mock_prop_deg.is_valid.return_value = True
    mock_prop_deg.value = "EstadoFalso"
    mock_prop_deg.values = ["Auto", "Cool"] # "EstadoFalso" no está en la lista
    
    mock_controller.loader.operations = {
        "prop_valid": mock_prop_valid, 
        "prop_stale": mock_prop_stale,
        "prop_deg": mock_prop_deg
    }
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}
    
    now = time.time()
    poller._pending_updates = {
        "prop_valid": ("ha_val_valid", now - 5.0),  # Hace 5 segundos (ACTIVO)
        "prop_stale": ("ha_val_stale", now - 20.0)  # Hace 20 segundos (CADUCADO)
    }
    
    fake_state = {"raw_key": "old_val"}
    
    corrections = await poller.async_update_properties_from_state(fake_state)
    
    # 1. Autopsia del TTL
    assert "prop_stale" not in poller._pending_updates # El obsoleto fue borrado
    assert fake_state["raw_key"] == "dev_val_valid"    # El activo sobrescribió el estado
    
    # 2. Autopsia de Degradación (cayó al índice 0 de la lista)
    assert mock_prop_deg.value == "Auto"
    assert corrections["prop_deg"] == "Auto"

# ====================================================================================
# FRENTE F: RECONSTRUCCIÓN MASIVA DE JSON (El laberinto de diccionarios)
# ====================================================================================

async def test_build_device_state_from_props_samsung_rest():
    """Autopsia de la generación de diccionarios para la API REST (no 2878)."""
    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST_API" # is_2878 = False
    
    # Simulamos el último estado real
    mock_controller.loader.state_getter.value = {"Devices": [{"id": "1", "Operation": {"power": "Off"}}]}
    
    # Creamos mocks de operaciones que obliguen a ejecutar todas las ramas complejas
    def create_mock_op(op_id, value):
        op = MagicMock()
        op.id = op_id
        op.value = value
        op.convert_hass_to_dev.return_value = value
        return op
    
    mock_controller.loader.operations = {
        "hvac": create_mock_op("hvac", "Cool"),
        "temp": create_mock_op("temperature", 22.0),
        "fan": create_mock_op("fan", "3"), # .isdigit() test
        "swing": create_mock_op("swing", "Up"),
        "preset": create_mock_op("preset_mode", "Eco"),
        "sleep": create_mock_op("good_sleep", 1.5) # float(device_value) test
    }
    mock_controller.loader.properties = {}
    
    poller = YamlStatePoller(mock_controller)
    reconstructed = await poller._build_device_state_from_props()
    
    assert reconstructed is not None
    device_obj = reconstructed["Devices"][0]
    
    # Aserciones estrictas contra mutaciones de claves de diccionarios ("Wind", "Mode", etc.)
    assert device_obj["Operation"]["power"] == "On"
    assert device_obj["Mode"]["modes"] == ["Cool"]
    assert device_obj["Temperatures"][0]["desired"] == 22.0
    assert device_obj["Wind"]["speedLevel"] == 3 # Casteado a int por isdigit()
    assert device_obj["Wind"]["direction"] == "Up"
    assert device_obj["Mode"]["options"][0] == "Eco"
    
    # good_sleep test ("Sleep_1")
    assert "Sleep_1" in device_obj["Mode"]["options"]

async def test_build_device_state_from_props_2878():
    """Autopsia de la generación de diccionarios para la API del puerto 2878."""
    mock_controller = MagicMock()
    mock_controller.config.get.return_value = DEVICE_TYPE_SAMSUNG_2878
    mock_controller.loader.state_getter.value = {"_is_not_falsy": True} # Evita el return temprano por if not last_real_state
    
    op = MagicMock()
    op.id = "hvac"
    op.value = "Heat"
    op.convert_hass_to_dev.return_value = "Heat"
    
    mock_controller.loader.operations = {"hvac": op}
    mock_controller.loader.properties = {}
    
    poller = YamlStatePoller(mock_controller)
    reconstructed = await poller._build_device_state_from_props()
    
    assert reconstructed is not None
    assert reconstructed["AC_FUN_OPMODE"] == "Heat"
    assert reconstructed["AC_FUN_POWER"] == "On"
