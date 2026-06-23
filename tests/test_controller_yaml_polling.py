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
    mock_controller.debug = False
    
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
    mock_controller.debug = False
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
# FRENTE F: AUTOPSIA EXHAUSTIVA DE FACTORÍAS JSON (El Abismo Absoluto)
# ====================================================================================

async def test_build_device_state_from_props_samsung_2878_exhaustive():
    """Barre todas las ramificaciones de alias y estados para el protocolo 2878."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from custom_components.climate_ip.const import DEVICE_TYPE_SAMSUNG_2878
    from homeassistant.components.climate.const import ATTR_HVAC_MODE, ATTR_FAN_MODE
    from homeassistant.const import ATTR_TEMPERATURE
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = DEVICE_TYPE_SAMSUNG_2878
    mock_controller.loader.state_getter.value = {"_is_not_falsy": True}
    
    def create_op(op_id, value):
        op = MagicMock()
        op.id = op_id
        op.value = value
        op.convert_hass_to_dev.return_value = value
        return op
        
    poller = YamlStatePoller(mock_controller)
    poller._get_cached_device_key_from_prop = MagicMock(return_value="CUSTOM_KEY")

    # BARRIDO 1: Estado OFF con alias nativos
    mock_controller.loader.operations = {
        "hvac": create_op("hvac", "Off"),
        "temp": create_op("temperature", 22.0),
        "fan": create_op("fan", "Auto"),
        "swing": create_op("swing", "Up") # Debe usar fallback a CUSTOM_KEY
    }
    
    res_off = await poller._build_device_state_from_props()
    assert res_off["AC_FUN_OPMODE"] == "Off"
    assert res_off["AC_FUN_POWER"] == "Off"
    assert res_off["AC_FUN_TEMPSET"] == "22.0"
    assert res_off["AC_FUN_WINDLEVEL"] == "Auto"
    assert res_off["CUSTOM_KEY"] == "Up"

    # BARRIDO 2: Estado ON con alias de Home Assistant y alias alternos
    mock_controller.loader.operations = {
        "hvac_ha": create_op(ATTR_HVAC_MODE, "Cool"),
        "hvac_alt": create_op("hvac_mode", "Heat"),  # Sobrescribirá a Cool, asertamos "Heat"
        "temp_ha": create_op(ATTR_TEMPERATURE, 25.5),
        "fan_ha": create_op(ATTR_FAN_MODE, "Low"),
        "fan_alt": create_op("fan_mode", "High")     # Sobrescribirá a Low, asertamos "High"
    }
    
    res_on = await poller._build_device_state_from_props()
    assert res_on["AC_FUN_OPMODE"] == "Heat"
    assert res_on["AC_FUN_POWER"] == "On"
    assert res_on["AC_FUN_TEMPSET"] == "25.5"
    assert res_on["AC_FUN_WINDLEVEL"] == "High"


async def test_build_device_state_from_props_rest_api_exhaustive():
    """Barre todas las ramificaciones de alias y estados para el protocolo REST (Puerto 8888)."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from homeassistant.components.climate.const import ATTR_HVAC_MODE, ATTR_FAN_MODE, ATTR_SWING_MODE, ATTR_PRESET_MODE
    from homeassistant.const import ATTR_TEMPERATURE
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST_API"
    
    def create_op(op_id, value):
        op = MagicMock()
        op.id = op_id
        op.value = value
        op.convert_hass_to_dev.return_value = value
        return op

    poller = YamlStatePoller(mock_controller)

    # BARRIDO 1: Generación inicial desde 0 y estado OFF
    mock_controller.loader.state_getter.value = {"Devices": [{}]}
    mock_controller.loader.operations = {
        "hvac": create_op("hvac", "Off"),
        "temp": create_op("temperature", 21.0),
        "fan": create_op("fan", "Auto"), # string para saltar isdigit()
        "fan_max": create_op("fan_max", "3"), # string numérico para testear isdigit()
        "swing": create_op("swing", "Up"),
        "preset": create_op("preset_mode", "Eco"),
        "sleep": create_op("good_sleep", 1.0)
    }
    
    res_off = await poller._build_device_state_from_props()
    dev_off = res_off["Devices"][0]
    
    assert dev_off["Operation"]["power"] == "Off"
    assert dev_off["Temperatures"][0]["desired"] == 21.0
    assert dev_off["Wind"]["speedLevel"] == "Auto"
    assert dev_off["Wind"]["maxSpeedLevel"] == 3 # Debe asertarse como int puro
    assert dev_off["Wind"]["direction"] == "Up"
    assert dev_off["Mode"]["options"] == ["Eco", "Sleep_1"] # preset y sleep fusionados

    # BARRIDO 2: Mutación de JSON pre-existente y estado ON con alias de HA
    mock_controller.loader.state_getter.value = {
        "Devices": [{
            "Operation": {"power": "Off"},
            "Temperatures": [{"desired": 18.0}, {"desired": 99.0}],
            "Mode": {"options": ["OldPreset", "OldSleep"]}
        }]
    }
    mock_controller.loader.operations = {
        "hvac_ha": create_op(ATTR_HVAC_MODE, "Dry"),
        "temp_ha": create_op(ATTR_TEMPERATURE, 26.5),
        "fan_ha": create_op(ATTR_FAN_MODE, "Low"),
        "swing_ha": create_op(ATTR_SWING_MODE, "All"),
        "preset_ha": create_op(ATTR_PRESET_MODE, "Quiet"),
        "sleep_alt": create_op("good_sleep", 2.0)
    }

    res_on = await poller._build_device_state_from_props()
    dev_on = res_on["Devices"][0]

    assert dev_on["Operation"]["power"] == "On"
    assert dev_on["Mode"]["modes"] == ["Dry"]
    assert dev_on["Temperatures"][0]["desired"] == 26.5
    assert dev_on["Wind"]["speedLevel"] == "Low"
    assert dev_on["Wind"]["direction"] == "All"
    assert dev_on["Mode"]["options"][0] == "Quiet"
    assert dev_on["Mode"]["options"][1] == "Sleep_2"

# ====================================================================================
# FRENTE G: EL MONO DEL CAOS (Aserciones de Tipado Defensivo y Longitudes)
# ====================================================================================

async def test_build_device_state_chaos_monkey_guards():
    """Fuerza cargas corruptas para matar mutantes de isinstance(), len() y duck-typing."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST_API"
    poller = YamlStatePoller(mock_controller)

    def setup_ops(op_id, val):
        op = MagicMock()
        op.id = op_id
        op.value = val
        op.convert_hass_to_dev.return_value = val
        mock_controller.loader.operations = {"op": op}
        mock_controller.loader.properties = {}
        mock_controller.loader.sensors = {}

    # --- CASO 1: 'Devices' NO es una lista (Mata isinstance(device_list, list)) ---
    setup_ops("hvac", "Cool")
    mock_controller.loader.state_getter.value = {"Devices": "ESTO_ES_UN_STRING"}
    res = await poller._build_device_state_from_props()
    # Si la guardia está, ignora la actualización y no explota.
    assert res["Devices"] == "ESTO_ES_UN_STRING"

    # --- CASO 2: 'Devices' es lista vacía (Mata len(device_list) > 0) ---
    mock_controller.loader.state_getter.value = {"Devices": []}
    res = await poller._build_device_state_from_props()
    assert res["Devices"] == []

    # --- CASO 3: El interior de 'Devices' no es un dict (Mata isinstance(device_obj, dict)) ---
    mock_controller.loader.state_getter.value = {"Devices": ["ESTO_NO_ES_UN_DICT"]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"] == ["ESTO_NO_ES_UN_DICT"]

    # --- CASO 4: Array 'Temperatures' vacío (Mata len(...) > 0 en temperatura) ---
    setup_ops("temperature", 22.0)
    mock_controller.loader.state_getter.value = {"Devices": [{"Temperatures": []}]}
    res = await poller._build_device_state_from_props()
    # La lógica original ignora listas vacías si ya existe la clave. 
    # Si mutmut cambia > 0 por >= 0, dará IndexError al intentar acceder a [0].
    assert res["Devices"][0]["Temperatures"] == [] 

    # --- CASO 5: Arrays 'options' de Mode (Mata mutantes de len == 1, len > 1) ---
    setup_ops("good_sleep", 1.0)
    
    # Longitud 0: No debe hacer nada (Mata si cambian a >= 1 -> IndexError)
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": []}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == []

    # Longitud 1: Debe hacer append (Mata si cambian len == 1 a != 1)
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": ["Eco"]}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == ["Eco", "Sleep_1"]

    # Longitud > 1: Debe sobrescribir el índice [1] (Mata si mutan el índice estricto)
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": ["Eco", "Sleep_Old", "Extra"]}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == ["Eco", "Sleep_1", "Extra"]

    # --- CASO 6: op_value nulo (Mata 'if op_value is None: continue') ---
    setup_ops("hvac", None)
    mock_controller.loader.state_getter.value = {"Devices": [{}]}
    res = await poller._build_device_state_from_props()
    # No debe haber añadido "Operation" porque la propiedad era None
    assert "Operation" not in res["Devices"][0]


# ====================================================================================
# FRENTE H: CORTOCIRCUITO DE RENDIMIENTO (Dirty Check)
# ====================================================================================

async def test_async_update_properties_dirty_check():
    """Aserta que la evaluación de estado idéntico bloquea la propagación a menos que se fuerce."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    import time
    from unittest.mock import MagicMock
    
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.debug = False
    mock_controller.loader._parsed_yaml_cache = {}
    poller = YamlStatePoller(mock_controller)
    
    fake_state = {"power": "on"}
    poller._last_device_state = fake_state
    
    # 1. Estado idéntico, sin forzar, sin pendientes (Mata mutaciones en if not force_update and...)
    # NO PASAMOS los kwargs explícitamente para matar los mutantes de valores por defecto (is_prediction=True, force_update=True)
    result = await poller.async_update_properties_from_state(fake_state)
    assert result == {}
    
    # 2. Estado idéntico, pero con force_update=True (Mata if no respeta force_update)
    # Debe pasar el cortocircuito y devolver dict (aunque sea vacío si no hay correcciones)
    from unittest.mock import AsyncMock
    mock_prop = MagicMock()
    mock_prop.id = "hvac"
    mock_prop.template = None
    mock_prop.status_template = None
    mock_prop.async_update_state = AsyncMock()
    mock_controller.loader.operations = {"hvac": mock_prop}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}
    
    result_forced = await poller.async_update_properties_from_state(fake_state, is_prediction=False, force_update=True)
    assert isinstance(result_forced, dict)
    mock_prop.async_update_state.assert_called_once()
    
    # 3. Estado idéntico, force_update=False, pero con pending_updates activas
    mock_prop.reset_mock()
    poller._pending_updates = {"hvac": ("val", time.time())}
    result_pending = await poller.async_update_properties_from_state(fake_state, is_prediction=False, force_update=False)
    assert isinstance(result_pending, dict)
    mock_prop.async_update_state.assert_not_called()

# ====================================================================================
# FRENTE I: ENRUTAMIENTO MULTI-DISPOSITIVO (Sub-device Selector)
# ====================================================================================

async def test_async_update_properties_sub_device_routing():
    """Verifica que el poller extrae el sub-diccionario correcto en arrays de dispositivos."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.device_id = "TARGET_ID"
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)
    
    # Configuramos el id_map de la caché simulada
    mock_controller.loader._parsed_yaml_cache = {
        "TARGET_ID": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"]
                }
            }
        }
    }
    
    # Payload con múltiples dispositivos. El target está en la segunda posición.
    full_payload = {
        "Devices": [
            {"id": "WRONG_ID", "power": "off"},
            {"id": "TARGET_ID", "power": "on"},
            {"id": "ANOTHER_ID", "power": "standby"}
        ]
    }
    
    from unittest.mock import AsyncMock
    mock_prop = MagicMock()
    mock_prop.template = None
    mock_prop.status_template = None
    mock_prop.async_update_state = AsyncMock()
    mock_controller.loader.operations = {"test": mock_prop}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}
    
    # Ejecutamos forzando la actualización
    await poller.async_update_properties_from_state(full_payload, force_update=True)
    
    # ASERCIÓN CRÍTICA: La propiedad debió recibir exclusivamente el sub-diccionario del TARGET_ID
    # Mata mutantes de la iteración `next(...)` y la comparación `== str(...)`
    mock_prop.async_update_state.assert_called_once_with(
        {"id": "TARGET_ID", "power": "on"}, 
        False
    )
    
    # Test Fallback: Si el ID no existe en la lista, debe usar el índice [0]
    mock_prop.async_update_state.reset_mock()
    
    # El dispositivo es TARGET_ID, pero el payload ya no lo incluye.
    payload_without_target = {
        "Devices": [
            {"id": "WRONG_ID", "power": "off"},
            {"id": "ANOTHER_ID", "power": "standby"}
        ]
    }
    
    await poller.async_update_properties_from_state(payload_without_target, force_update=True)
    mock_prop.async_update_state.assert_called_once_with(
        {"id": "WRONG_ID", "power": "off"}, 
        False
    )

# ====================================================================================
# FRENTE J: DEFAULTS Y CHAOS CACHE EN ENRUTAMIENTO MULTI-DISPOSITIVO
# ====================================================================================

async def test_async_update_properties_defaults_and_chaos_cache():
    """Mata mutantes que alteran parámetros por defecto y diccionarios faltantes en la caché."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock

    class FakeController:
        def __init__(self):
            self.loader = MagicMock()
            self.debug = False
            self.log_prefix = "test"
            # device_id is deliberately missing

    mock_controller = FakeController()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    
    # 1. Caché completamente vacía (Mata los .get(CONFIG_DEVICE, {}) -> None)
    mock_controller.loader._parsed_yaml_cache = {}
    
    poller = YamlStatePoller(mock_controller)
    
    mock_prop = MagicMock()
    mock_prop.template = None
    mock_prop.status_template = None
    mock_prop.async_update_state = AsyncMock()
    mock_controller.loader.operations = {"test": mock_prop}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    fake_payload = {"some": "data"}
    
    # 2. Llamada SIN is_prediction ni force_update, confiando en los DEFAULTS
    # Mata a: is_prediction=True, force_update=True
    # Como force_update es False (default) y pending_updates es vacío, si el estado cambia, procesará.
    # Necesitamos asegurar que pase el cortocircuito dirty-check
    poller._last_device_state_str = "different_state"

    await poller.async_update_properties_from_state(fake_payload)
    mock_prop.async_update_state.assert_called_once_with({"some": "data"}, False)

    # 1.5. Test de `force_update=True` mutation (Mata Mutante 2)
    # Llamamos de nuevo con el MISMO payload (no ha cambiado el estado)
    mock_prop.async_update_state.reset_mock()
    await poller.async_update_properties_from_state(fake_payload)
    # Al no haber cambiado el estado, y ser force_update=False por defecto, no debe llamarse
    mock_prop.async_update_state.assert_not_called()
    
    # 1.7. Test de falta de `_parsed_yaml_cache` para matar defaults en getattr
    # Reemplazamos `loader` por un mock estricto que lanzará AttributeError real
    # al no tener `_parsed_yaml_cache`
    class StrictLoader:
        is_fully_initialized = True
        operations = {"test": mock_prop}
        properties = {}
        sensors = {}
        # NO tiene _parsed_yaml_cache

    mock_controller.loader = StrictLoader()
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state_str = "different_state_2"
    await poller.async_update_properties_from_state({"some": "new_data"})
    mock_prop.async_update_state.assert_called_once_with({"some": "new_data"}, False)

    # 1.8 Test de Exception en el bloque try (Mata mutantes en el bloque except)
    # Asignar None hace que cache.get lance AttributeError
    mock_controller.loader._parsed_yaml_cache = None
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state_str = "different_state_exc"
    await poller.async_update_properties_from_state({"some": "exc_data"})
    mock_prop.async_update_state.assert_called_once_with({"some": "exc_data"}, False)

    # 1.9 Test del dirty check (Mata mutantes de is_prediction y condiciones del dirty check)
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state = {"some": "dirty_data"}
    poller._last_device_state_str = "{'some': 'dirty_data'}"
    res = await poller.async_update_properties_from_state({"some": "dirty_data"})
    assert res == {}
    mock_prop.async_update_state.assert_not_called()

    # Restauramos para el siguiente test
    mock_controller.loader = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.loader.operations = {"test": mock_prop}

    # Al no haber id_map, `device_to_process` NUNCA DEBE SER REASIGNADO,
    # con lo cual si el mutante puso `device_to_process = None`, el mock recibirá None en lugar del payload real.
    # 2. Test del default device_id en la caché (Mata Mutante 41)
    mock_prop.async_update_state.reset_mock()
    
    # Creamos un caché donde la clave es "XXXX", que es el default de getattr(..., "device_id", "XXXX")
    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"]
                }
            }
        }
    }
    # Pasamos DOS dispositivos en la lista. El primero tiene id "WRONG", el segundo id "".
    # Así, si el `getattr` con el default "" es mutado (ej. a None o "XXXX"), el match fallará.
    # Al fallar el match, el código hará fallback a `devices_list[0]` ("WRONG"),
    # con lo cual la aserción sobre mock_prop fallará porque esperaba el de id "".
    payload_list_2 = {"Devices": [
        {"id": "WRONG", "power": "on"},
        {"id": "", "power": "off"}
    ]}

    await poller.async_update_properties_from_state(payload_list_2)
    mock_prop.async_update_state.assert_called_once_with({"id": "", "power": "off"}, False)

    # 3. Test de current_hass_state default (Mata Mutante 11)
    mock_prop.async_update_state.reset_mock()
    poller._build_device_state_from_hass = AsyncMock(return_value={"power": "on"})
    await poller.async_update_properties_from_state(None, current_hass_state="FAKE_HASS_STATE")
    poller._build_device_state_from_hass.assert_called_once_with("FAKE_HASS_STATE")
    mock_prop.async_update_state.assert_called_once_with({"power": "on"}, False)

@pytest.mark.asyncio
async def test_async_update_properties_ttl():
    """Mata mutantes de time.time() y el umbral de 15.0s en async_update_properties_from_state."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock

    class MockProp:
        id = "wind_speed"
        value = "low"
        async_update_state = AsyncMock()
        convert_hass_to_dev = MagicMock(return_value="high_dev")

    mock_prop = MockProp()

    class FakeController:
        def __init__(self):
            class FakeLoader:
                is_fully_initialized = True
                operations = {"wind": mock_prop}
                properties = {}
                sensors = {}
                # _parsed_yaml_cache deliberately missing
            self.loader = FakeLoader()
            self.debug = False
            self.log_prefix = "test"

    mock_controller = FakeController()
    poller = YamlStatePoller(mock_controller)
    
    # Simulamos que _get_cached_device_key_from_prop retorna "WindLevel"
    poller._get_cached_device_key_from_prop = MagicMock(return_value="WindLevel")

    device_payload = {"WindLevel": "low_dev"}

    # CASO 1: TTL Válido (< 15.0)
    # mock_prop.value debe ser "high" y mock_prop.convert_hass_to_dev debe ser llamado
    # Además el device_payload debe inyectarse con "high_dev"
    with patch("time.time", return_value=100.0):
        poller._pending_updates = {"wind_speed": ("high", 86.0)} # Delta 14.0s
        poller._last_device_state_str = "dirty"
        await poller.async_update_properties_from_state(device_payload)
        
        assert mock_prop.value == "high"
        # En el primer bucle se inyecta en el payload, y en el segundo bucle el continue salta
        # el `async_update_state`
        mock_prop.async_update_state.assert_not_called()
        assert "wind_speed" in poller._pending_updates

    # CASO 2: TTL Expirado (>= 15.0)
    mock_prop.async_update_state.reset_mock()
    with patch("time.time", return_value=100.0):
        poller._pending_updates = {"wind_speed": ("high", 85.0)} # Delta 15.0s
        poller._last_device_state_str = "dirty2"
        await poller.async_update_properties_from_state(device_payload)
        
        # Debe llamar a async_update_state porque expiró y no saltó con continue
        mock_prop.async_update_state.assert_called_once()
        # Debe haber eliminado el pending update
        assert "wind_speed" not in poller._pending_updates

@pytest.mark.asyncio
async def test_async_get_status_cache_ttl():
    """Mata mutantes de time.time() y < 2.0 en async_get_status."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock, patch

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    poller.async_update_state = AsyncMock(return_value={"power": "on"})
    poller._cached_device_state = {"power": "on"}
    poller._last_state_fetch_time = 100.0

    # 1. Exactamente 2.0s de diferencia (mata < 2.0 mutado a <= 2.0)
    # Al no ser ESTRICTAMENTE menor, el caché caduca y llama a async_update_state
    with patch("time.time", return_value=102.0):
        await poller.async_get_status()
        poller.async_update_state.assert_called_once()

    # 2. Exactamente 1.99s (mata < 2.0 mutado a False)
    # Al ser menor, usa la caché
    poller.async_update_state.reset_mock()
    with patch("time.time", return_value=101.99):
        await poller.async_get_status()
        poller.async_update_state.assert_not_called()

# ====================================================================================
# FRENTE K: _calculate_structured_state (El Mapeo Estricto de Estado)
# ====================================================================================

async def test_calculate_structured_state_exhaustive():
    """Aserta el mapeo rígido de las propiedades de HA al objeto ClimateIPDeviceState."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from homeassistant.components.climate.const import ATTR_HVAC_MODE, ATTR_FAN_MODE, ATTR_SWING_MODE, ATTR_PRESET_MODE
    from homeassistant.const import ATTR_TEMPERATURE
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)

    def create_op(op_id, calc_val):
        op = MagicMock()
        op.id = op_id
        op.calculate_value_from_state.return_value = calc_val
        return op

    # Inyectamos exactamente las claves que la función busca internamente
    mock_controller.loader.operations = {
        "hvac": create_op(ATTR_HVAC_MODE, "Cool"),
        "temp": create_op(ATTR_TEMPERATURE, 22.5),
        "fan": create_op(ATTR_FAN_MODE, "High"),
        "swing": create_op(ATTR_SWING_MODE, "Off"),
        "preset": create_op(ATTR_PRESET_MODE, "Eco"),
        "cur_temp": create_op("current_temperature", 24.0)
    }
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    raw_state = {"dummy": "data"}
    state_obj = poller._calculate_structured_state(raw_state)

    # 1. Aserciones Estrictas de Mapeo (Mata mutantes que cambian "hvac_mode" por "XXhvac_modeXX" o None)
    assert state_obj is not None
    if hasattr(state_obj.hvac_mode, "value"):
        assert state_obj.hvac_mode.value == "cool"
    else:
        assert str(state_obj.hvac_mode).lower() == "cool"
    assert state_obj.target_temperature == 22.5
    assert state_obj.current_temperature == 24.0
    assert state_obj.fan_mode == "High"
    assert state_obj.swing_mode == "Off"
    assert state_obj.preset_mode == "Eco"

    # 2. Cortocircuitos de Inicialización y Excepciones
    mock_controller.loader.is_fully_initialized = False
    assert poller._calculate_structured_state(raw_state) is None

    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.loader.operations["hvac"].calculate_value_from_state.side_effect = Exception("Boom")
    # Si explota el cálculo, el método debe tragar la excepción y retornar None (Mata except: pass)
    assert poller._calculate_structured_state(raw_state) is None

# ====================================================================================
# FRENTE L: REGEX Y EXTRACCIÓN DE PLANTILLAS (_get_device_key_from_template)
# ====================================================================================

def test_device_key_from_template_regex():
    """Mata mutantes que alteran el patrón Regex de búsqueda de estado."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    class FakeTemplate:
        def __init__(self, text):
            self.template = text

    # Prueba 1: Sintaxis de corchetes con comillas simples (Mata mutación de group)
    tmpl_bracket = FakeTemplate("{{ device_state['Operation'] }}")
    assert poller._get_device_key_from_template(tmpl_bracket) == "Operation"

    # Prueba 2: Sintaxis de punto
    tmpl_dot = FakeTemplate("{{ device_state.power_level }}")
    assert poller._get_device_key_from_template(tmpl_dot) == "power_level"

    # Prueba 3: Objeto vacío o patrón sin coincidencia
    assert poller._get_device_key_from_template(None) is None
    assert poller._get_device_key_from_template(FakeTemplate("{{ otra_cosa['val'] }}")) is None

# ====================================================================================
# FRENTE M: _rebuild_attributes Y FORMATOS DE FECHA
# ====================================================================================

@patch("custom_components.climate_ip.controller_yaml_polling.dt_util.now")
def test_rebuild_attributes_exact_strings(mock_now):
    """Aserta el formato exacto de fecha y las claves del diccionario de atributos."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    import datetime

    # Fijamos el tiempo para evitar condiciones de carrera y asertar el formato %Y-%m-%d %H:%M:%S
    fake_time = datetime.datetime(2026, 6, 7, 15, 30, 0)
    mock_now.return_value = fake_time

    mock_controller = MagicMock()
    mock_controller.name = "TestAC"
    poller = YamlStatePoller(mock_controller)

    # Creamos una propiedad que inyecte un atributo extra
    mock_prop = MagicMock()
    mock_prop.state_attributes = {"custom_attr": "value"}
    mock_controller.loader.operations = {"prop": mock_prop}
    mock_controller.loader.properties = {}

    poller._rebuild_attributes()

    # Interceptamos cómo se guardaron los atributos en el controlador (Mata "XXlast_syncXX" o formatos rotos)
    saved_attrs = mock_controller.update_state_attributes.call_args[0][0]
    
    from homeassistant.const import ATTR_NAME
    assert saved_attrs[ATTR_NAME] == "TestAC" # ATTR_NAME
    assert saved_attrs["custom_attr"] == "value"
    assert saved_attrs["last_sync"] == "2026-06-07 15:30:00"


# ====================================================================================
# FRENTE N: INTEGRACIÓN DE HASS Y COORDINATOR (get_current_state_callback)
# ====================================================================================

async def test_async_update_state_coordinator_callback():
    """Aserta el paso del estado del HASS al despachador de propiedades."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock, patch
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter.async_update_state = AsyncMock(return_value={"raw": "data"})
    
    # 1. Rama SIN callback (Mata mutantes que alteran if hasattr(..., 'get_current_state_callback'))
    if hasattr(mock_controller, "get_current_state_callback"):
        delattr(mock_controller, "get_current_state_callback")
    
    with patch.object(poller, "async_update_properties_from_state") as mock_dispatch:
        await poller.async_update_state()
        mock_dispatch.assert_called_once_with({"raw": "data"}, current_hass_state=None)
        
    # 2. Rama CON callback (Mata mutaciones de asignación current_state = None)
    mock_controller.get_current_state_callback = MagicMock(return_value="HASS_STATE_OBJECT")
    
    with patch.object(poller, "async_update_properties_from_state") as mock_dispatch:
        await poller.async_update_state()
        mock_dispatch.assert_called_once_with({"raw": "data"}, current_hass_state="HASS_STATE_OBJECT")

# ====================================================================================
# FRENTE O: PARSEO DE OFFLINE PERSISTENTE Y CONTADORES
# ====================================================================================

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
    mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect("Timeout")
    
    with pytest.raises(UpdateFailed):
        await poller.async_update_state()
        
    assert poller._consecutive_connection_errors == 1

# ====================================================================================
# FRENTE P: CACHÉ DE CLAVES DE PLANTILLA (prop_template_key_cache)
# ====================================================================================

def test_get_cached_device_key_from_prop_and_register():
    """Evalúa la caché de plantillas y el registro de pending_updates."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    import time
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    # --- test register_pending_update (Mata la mutación self._pending_updates[...] = None) ---
    poller.register_pending_update("hvac", "Cool")
    assert "hvac" in poller._pending_updates
    val, ts = poller._pending_updates["hvac"]
    assert val == "Cool"
    assert isinstance(ts, float)

    # --- test _get_cached_device_key_from_prop ---
    # 1. Propiedad sin ID (Mata prop_id = getattr(prop, "id", None) -> None)
    assert poller._get_cached_device_key_from_prop(MagicMock(spec=[])) is None
    
    prop = MagicMock()
    prop.id = "target_prop"
    prop.status_template = None
    
    # 2. Propiedad sin template
    assert poller._get_cached_device_key_from_prop(prop) is None
    
    # 3. Primer acceso (Cache Miss)
    prop.id = "target_prop_2"
    prop.status_template = MagicMock()
    prop.status_template.template = "{{ device_state.power }}"
    assert poller._get_cached_device_key_from_prop(prop) == "power"
    assert poller._prop_template_key_cache["target_prop_2"] == "power"
    
    # 4. Segundo acceso (Cache Hit) (Mata iteradores que ignoran la caché)
    prop.status_template.template = "{{ device_state.mode }}" # Mutamos el origen
    # Al estar cacheado, debe seguir devolviendo "power" y NO "mode"
    assert poller._get_cached_device_key_from_prop(prop) == "power"

# ====================================================================================
# FRENTE Q: CADENAS DE FALLBACK .GET() (async_update_properties_from_state)
# ====================================================================================

async def test_async_update_properties_cache_get_chains():
    """Mata mutantes que eliminan el fallback {} de los encadenamientos .get()."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    import pytest
    
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.device_id = "test_device"
    poller = YamlStatePoller(mock_controller)
    
    # Si mutmut cambia .get(CONFIG_DEVICE, {}) a .get(CONFIG_DEVICE, None),
    # el siguiente .get("identifiers") lanzará AttributeError matando al mutante.
    
    # Escenario 1: device_id existe en caché, pero sin CONFIG_DEVICE
    mock_controller.loader._parsed_yaml_cache = {"test_device": {}} 
    
    try:
        res = await poller.async_update_properties_from_state({"raw": "data"})
        assert isinstance(res, dict)
    except AttributeError:
        pytest.fail("Fallback roto: el encadenamiento .get() falló.")
        
    # Escenario 2: device_id ni siquiera existe en caché
    mock_controller.loader._parsed_yaml_cache = {} 
    
    try:
        res2 = await poller.async_update_properties_from_state({"raw": "data"})
        assert isinstance(res2, dict)
    except AttributeError:
        pytest.fail("Fallback roto: el encadenamiento .get() falló en la raíz.")

# ====================================================================================
# FRENTE R: INTEGRIDAD SECUENCIAL DE BUCLES Y DESPACHO ORDENADO (Mata 72 supervivientes)
# ====================================================================================

async def test_async_update_properties_loop_sequences_and_eviction_handling():
    """Garantiza que las mutaciones de flujo (break/continue) destruyan la ejecución multiobjeto."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock
    import time

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)
    poller._get_cached_device_key_from_prop = MagicMock(return_value="power_key")

    # Creamos 3 propiedades distintas para rellenar el bucle secuencial
    # Si mutmut cambia un 'continue' por un 'break', las propiedades posteriores quedarán ciegas
    class FakeProp:
        def __init__(self, id_val):
            self.id = id_val
            self.value = None
            self._value = None
            self.convert_hass_to_dev = MagicMock()
            self.async_update_state = AsyncMock()
            self.set_device_state_for_values = MagicMock()

    prop_active = FakeProp("active_prop")
    prop_active.convert_hass_to_dev.return_value = "dev_active"
    
    prop_stale = FakeProp("stale_prop")
    prop_standard = FakeProp("standard_prop")


    # El orden de la lista es CRÍTICO para capturar el cortocircuito del bucle
    all_props_list = [prop_active, prop_stale, prop_standard]
    mock_controller.loader.operations = {p.id: p for p in all_props_list}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    # Configuramos las actualizaciones pendientes (una viva, una muerta por TTL)
    now = time.time()
    poller._pending_updates = {
        "active_prop": ("ha_active", now - 2.0),  # Activa (<15s)
        "stale_prop": ("ha_stale", now - 20.0)   # Caducada (>15s)
    }

    fake_device_state = {"power_key": "original_value"}

    # Ejecutamos el pipeline forzando la actualización
    await poller.async_update_properties_from_state(fake_device_state, force_update=True)

    # --- ASURACIONES DEL PRIMER BUCLE (Fusión de Claves) ---
    # La propiedad activa debió inyectar su valor en el diccionario de red global
    assert fake_device_state["power_key"] == "dev_active"

    # --- ASERCIONES DEL SEGUNDO BUCLE (Despacho de Valores y Evicción) ---
    # 1. Propiedad Activa: Debe asignar el valor pendiente y saltar con 'continue'
    # Si mutmut cambió 'continue' por 'break', las siguientes dos propiedades jamás se actualizarán
    assert prop_active.value == "ha_active" or prop_active._value == "ha_active"
    prop_active.async_update_state.assert_not_called() # El continue evita la llamada directa de red

    # 2. Propiedad Caducada: El TTL la expulsó del diccionario de pendientes
    assert "stale_prop" not in poller._pending_updates
    # Al no estar activa, debe actualizarse con el flujo normal de red
    prop_stale.async_update_state.assert_called_once_with(fake_device_state, False)

    # 3. Propiedad Estándar: No tiene pendientes, evalúa la salud del final del bucle
    # Si el mutante rompió el bucle en la propiedad 1 o 2, esta aserción explotará
    prop_standard.async_update_state.assert_called_once_with(fake_device_state, False)

    # --- ASERCIONES DEL TERCER BUCLE (set_device_state_for_values) ---
    for p in all_props_list:
        p.set_device_state_for_values.assert_called_once_with(fake_device_state)
