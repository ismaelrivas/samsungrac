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
    with patch("custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability", return_value=False) as mock_ping:
        with pytest.raises(CannotConnect, match="Host unreachable"):
            await poller.async_update_state()
            
        # Aserciones estrictas del pre-check (Frente de Red)
        mock_controller.config.get.assert_called_with("device_type")
        mock_ping.assert_called_once()
        
        # Mata mutantes en la matemática del contador (ej. += 2 en lugar de += 1)
        assert poller._consecutive_connection_errors == 1

    # 3. Cortocircuito de Reachability por ip_address = None (Mata mutante and -> or)
    mock_controller.ip_address = None
    with patch("custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability", return_value=False) as mock_ping_none:
        # Hacemos que state_getter falle para terminar la función, o que devuelva None
        mock_controller.loader.state_getter.async_update_state.return_value = None
        with pytest.raises(UpdateFailed):
            await poller.async_update_state()
        mock_ping_none.assert_not_called()

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
    
    # Validamos la resolución del Issue (Cuando la conexión se recupera)
    poller._consecutive_connection_errors = 1
    mock_controller.loader.state_getter.async_update_state.side_effect = None
    mock_controller.loader.state_getter.async_update_state.return_value = {"power": "on"}
    mock_controller.loader.state_getter.value = {"power": "on"}
    mock_controller.ip_address = "192.168.1.100"
    
    with patch("custom_components.climate_ip.controller_yaml_polling.async_delete_issue") as mock_delete_issue:
        await poller.async_update_state()
        # Verificación estricta de que se borró el issue con los parámetros correctos
        mock_delete_issue.assert_called_once_with(mock_controller.hass, "climate_ip", "connection_failed_192.168.1.100")

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
    mock_controller.debug = False
    
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
            
            # Simulamos que venimos de un error de conexión para asertar el reseteo
            poller._consecutive_connection_errors = 2
            
            result = await poller.async_update_state()
            
            # 1. Asertamos que el controlador recibió la nueva credencial
            assert mock_controller.token == "NEW_TOKEN_999"
            
            # 2. Asertamos que se emitió la orden de actualizar las conexiones hijas
            mock_update_dispatch.assert_called_once_with("NEW_TOKEN_999")
            
            # 3. Asertamos que el callback del usuario se llamó (Mata mutante and -> or)
            mock_controller.on_token_refreshed.assert_called_once_with("NEW_TOKEN_999")
            
            # 4. Asertamos que el contador de errores se reseteó a 0 estrictamente
            assert poller._consecutive_connection_errors == 0
            
            # 5. Asertamos que state_getter se llamó con los argumentos exactos (Mata debug = False -> True)
            mock_controller.loader.state_getter.async_update_state.assert_called_with(None, False)
            
            # 6. Asertamos que la ejecución retornó el valor exitoso tras el retry
            assert result == {"status": "ok"}
            
    # Validamos que on_token_refreshed no se llama si es None (mutante AttributeError)
    mock_controller.on_token_refreshed = None
    mock_controller.token = "OLD_TOKEN"
    mock_controller.loader.state_getter.async_update_state.side_effect = [AuthError("401"), {"status": "ok"}]
    with patch.object(poller, "_refresh_smartthings_token", return_value="NEW_TOKEN_999"):
        with patch.object(poller, "_update_all_connections_token"):
            await poller.async_update_state()
            # Si intenta llamar a None, lanzará TypeError y fallará el test

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
    
    # Longitud 0: Ahora sí debe inicializarse porque mejoramos la estructura
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": []}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == ["Comode_Off", "Sleep_1"]

    # Longitud 1: Debe hacer append (Mata si cambian len == 1 a != 1)
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": ["Eco"]}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == ["Eco", "Sleep_1"]

    # Longitud > 1: Debe sobrescribir el índice [1] (Mata si mutan el índice estricto)
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": ["Eco", "Sleep_Old", "Extra"]}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == ["Eco", "Sleep_1", "Extra"]

    # --- CASO 6: 'preset_mode' inicialización y reescritura ---
    setup_ops("preset_mode", "Turbo")
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": []}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == ["Turbo"]

    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": ["OldMode"]}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == ["Turbo"]

    # --- CASO 7: op_value nulo (Mata 'if op_value is None: continue') ---
    setup_ops("hvac", None)
    mock_controller.loader.state_getter.value = {"Devices": [{}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"] == [{}]
    # No debe haber añadido "Operation" porque la propiedad era None
    assert "Operation" not in res["Devices"][0]

async def test_build_device_state_early_returns():
    """Fuerza las salidas tempranas de _build_device_state_from_props (Líneas 655, 659)."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    mock_controller.loader.state_getter = None
    poller = YamlStatePoller(mock_controller)

    # st_getter es nulo
    assert await poller._build_device_state_from_props() is None

    # state_getter.value es nulo
    mock_controller.loader.state_getter = MagicMock()
    mock_controller.loader.state_getter.value = None
    assert await poller._build_device_state_from_props() == {}
# ====================================================================================
# FRENTE H: CORTOCIRCUITO DE RENDIMIENTO (Dirty Check)
# ====================================================================================

async def test_async_update_properties_dirty_check():
    """Aserta que la evaluación de estado idéntico bloquea la propagación a menos que se fuerce."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    import time
    from unittest.mock import MagicMock, AsyncMock
    
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.loader._parsed_yaml_cache = {}
    
    mock_prop = MagicMock()
    mock_prop.id = "hvac"
    mock_prop.template = None
    mock_prop.status_template = None
    mock_prop.async_update_state = AsyncMock()
    mock_controller.loader.operations = {"hvac": mock_prop}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    poller = YamlStatePoller(mock_controller)
    
    fake_state = {"power": "on"}
    poller._last_device_state = fake_state
    
    # 1. Estado idéntico, sin forzar, sin pendientes (Mata mutaciones en if not force_update and...)
    # NO PASAMOS los kwargs explícitamente para matar los mutantes de valores por defecto (is_prediction=True, force_update=True)
    result = await poller.async_update_properties_from_state(fake_state)
    assert result == {}
    mock_prop.async_update_state.assert_not_called()
    
    # 1.5 Estado idéntico, pero con is_prediction=True (Mata el if not is_prediction)
    # Debe pasar el cortocircuito y procesar
    result_pred = await poller.async_update_properties_from_state(fake_state, is_prediction=True, force_update=False)
    assert isinstance(result_pred, dict)
    mock_prop.async_update_state.assert_called_once()
    mock_prop.reset_mock()
    
    # 2. Estado idéntico, pero con force_update=True (Mata if no respeta force_update)
    # Debe pasar el cortocircuito y procesar
    result_forced = await poller.async_update_properties_from_state(fake_state, is_prediction=False, force_update=True)
    assert isinstance(result_forced, dict)
    mock_prop.async_update_state.assert_called_once()
    mock_prop.reset_mock()
    
    # 3. Estado idéntico, force_update=False, pero con pending_updates activas
    poller._pending_updates = {"hvac": ("val", time.time())}
    result_pending = await poller.async_update_properties_from_state(fake_state, is_prediction=False, force_update=False)
    assert isinstance(result_pending, dict)
    mock_prop.async_update_state.assert_not_called()

    # 4. Fallback de Atributo y Aislamiento de Memoria (Deepcopy vs Copy)
    # Borramos _last_device_state para forzar que getattr pase por el default None y no levante AttributeError
    # (El init de YamlStatePoller lo setea a None, así que hay que borrarlo con del)
    del poller._last_device_state
    poller._pending_updates = {}
    
    nested_state = {"Operation": {"power": "On"}}
    # Llamamos a la función: no debe entrar al dirty check porque None != nested_state.
    # Seteará poller._last_device_state = copy.deepcopy(nested_state)
    result_new_state = await poller.async_update_properties_from_state(nested_state)
    
    # Mutamos el estado original
    nested_state["Operation"]["power"] = "Off"
    
    # Si Mutmut inyectó copy.copy en lugar de copy.deepcopy, el diccionario anidado también será "Off"
    assert poller._last_device_state["Operation"]["power"] == "On"

# ====================================================================================
# FRENTE I: ENRUTAMIENTO MULTI-DISPOSITIVO (Sub-device Selector)
# ====================================================================================

async def test_async_update_properties_sniper_signature_and_flags():
    """
    Sniper: Valida explícitamente las variaciones de is_prediction y force_update.
    Mata los mutantes de la firma y asegura el cortocircuito dirty-check.
    """
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock

    # Usamos un DummyController estricto para evitar trampas de MagicMock
    class DummyProp:
        def __init__(self, name):
            self.id = name
            self.name = name
            self.async_update_state = AsyncMock()

    class DummyLoader:
        def __init__(self):
            self.is_fully_initialized = True
            self.operations = {}
            self.properties = {"test_prop": DummyProp("test_prop")}
            self.sensors = {}
            self._parsed_yaml_cache = {}

    class DummyController:
        def __init__(self):
            self.log_prefix = "SNIPER"
            self.loader = DummyLoader()
            self.device_id = "test_dev"
            self.debug = False

    controller = DummyController()
    poller = YamlStatePoller(controller)
    mock_prop = controller.loader.properties["test_prop"]

    # =========================================================================
    # ESCENARIO 1: Comportamiento por defecto (is_prediction=False, force_update=False)
    # =========================================================================
    fake_state = {"power": "ON"}
    
    # 1.1: Si el estado ES DIFERENTE, _last_device_state se actualiza y avanza
    poller._last_device_state = {"power": "OFF"}
    await poller.async_update_properties_from_state(fake_state)
    assert poller._last_device_state == fake_state
    mock_prop.async_update_state.assert_called_once()
    
    # 1.2: Si el estado ES IDÉNTICO, hace cortocircuito (Dirty Check) y devuelve {}
    mock_prop.async_update_state.reset_mock()
    result = await poller.async_update_properties_from_state(fake_state)
    assert result == {}
    mock_prop.async_update_state.assert_not_called()

    # =========================================================================
    # ESCENARIO 2: Mutación a is_prediction=True
    # =========================================================================
    # Si is_prediction=True, SE SALTA el dirty-check. 
    # _last_device_state NO se actualiza, pero las propiedades SÍ se evalúan.
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state = {"power": "OLD"}
    
    await poller.async_update_properties_from_state(fake_state, is_prediction=True)
    
    # _last_device_state no debe haber sido tocado
    assert poller._last_device_state == {"power": "OLD"}
    mock_prop.async_update_state.assert_called_once()

    # =========================================================================
    # ESCENARIO 3: Mutación a force_update=True
    # =========================================================================
    # Si force_update=True, SE SALTA el dirty-check aunque el estado sea idéntico.
    # _last_device_state SE actualiza (con deepcopy), y las propiedades SÍ se evalúan.
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state = {"power": "ON"}  # Idéntico al fake_state
    
    await poller.async_update_properties_from_state(fake_state, force_update=True)
    
    # Como saltó el Dirty Check, llegó al final y actualizó propiedades
    mock_prop.async_update_state.assert_called_once()

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
    
    prop_no_convert = FakeProp("no_convert_prop")
    del prop_no_convert.convert_hass_to_dev

    # El orden de la lista es CRÍTICO para capturar el cortocircuito del bucle
    all_props_list = [prop_active, prop_stale, prop_no_convert, prop_standard]
    mock_controller.loader.operations = {p.id: p for p in all_props_list}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    # Configuramos las actualizaciones pendientes (una viva, una muerta por TTL)
    now = time.time()
    poller._pending_updates = {
        "active_prop": ("ha_active", now - 2.0),  # Activa (<15s)
        "stale_prop": ("ha_stale", now - 20.0),   # Caducada (>15s)
        "no_convert_prop": ("ha_no_convert", now - 2.0)
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

# ====================================================================================
# FRENTE S: EL FLAG DE PARPADEO DEL UI (fan_modes_list_changed_pending_flicker)
# ====================================================================================

async def test_async_update_properties_fan_flicker_flag():
    """Mata los mutantes que alteran el flag del ventilador durante la degradación de estado."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from homeassistant.components.climate import ClimateEntityFeature
    
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)
    
    # Utilizamos el patrón Stub que descubriste para evitar la auto-generación de Mocks
    class FakeFanProp:
        def __init__(self):
            self.id = "fan_prop"
            self.value = "EstadoInvalido" # Forzamos la degradación
            self.values = ["Auto", "High"]
            self.feature_flag = ClimateEntityFeature.FAN_MODE
            
        def is_valid(self, state):
            return True
            
        def set_device_state_for_values(self, state):
            pass
            
    fake_fan = FakeFanProp()
    mock_controller.loader.operations = {"fan_prop": fake_fan}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}
    
    # 1. Aseguramos el estado inicial en False (Mata mutantes que lo inicializan en True/None)
    poller.fan_modes_list_changed_pending_flicker = False
    
    # Ejecutamos el despachador
    await poller.async_update_properties_from_state({"raw": "data"}, force_update=True)
    
    # 2. Aserción de degradación: el valor inválido cayó al primer elemento permitido
    assert fake_fan.value == "Auto"
    
    # 3. Aserción de Estado Secundario: El flag DEBE activarse (Mata != FAN_MODE, = False, = None)
    assert poller.fan_modes_list_changed_pending_flicker is True

# --- FRENTE 1: Refresco de Token SmartThings ---

@patch("custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.OAuth2Session")
@patch("custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.async_get_config_entry_implementation")
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
    mock_oauth_session.assert_called_once_with(mock_controller.hass, mock_entry, mock_get_impl.return_value)
    mock_session_instance.async_ensure_token_valid.assert_awaited_once()
    assert result == "nuevo_token_refrescado"

@patch("custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.OAuth2Session")
@patch("custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.async_get_config_entry_implementation")
@patch("custom_components.climate_ip.controller_yaml_polling._LOGGER")
async def test_refresh_smartthings_token_sniper_failures(mock_logger, mock_get_impl, mock_oauth_session):
    """Sniper: Test token refresh failure paths strictly checking loggers and missing attributes."""
    # Dummy estricto para evitar MagicMocks donde testeamos hasattr/getattr
    class DummyController:
        def __init__(self):
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
    mock_session_instance.async_ensure_token_valid.side_effect = Exception("Auth Server Down")
    mock_oauth_session.return_value = mock_session_instance
    
    assert await poller._refresh_smartthings_token() is None
    # Debe loguear un error con la excepción
    mock_logger.error.assert_called_once()
    mock_logger.debug.assert_not_called()

# --- FRENTE 2: Bloques de Fusión Atómica y Predicción ---

async def test_evict_invalidated_pending_updates():
    """Test that pushed updates evict stale pending commands."""
    mock_controller = MagicMock()
    mock_op = MagicMock()
    mock_op.id = "hvac_mode"
    mock_op.status_template = "{{ device_state.hvac_mode }}"
    mock_controller.loader.operations = {"hvac_mode": mock_op}
    
    poller = YamlStatePoller(mock_controller)
    # Populate pending
    poller._pending_updates["hvac_mode"] = ("heat", 123456789.0)
    
    # 1. Evict via direct device key
    poller._evict_invalidated_pending_updates({"hvac_mode": "cool"})
    assert len(poller._pending_updates) == 0
    
    # 2. Evict via AC_FUN_POWER="Off"
    poller._pending_updates["hvac_mode"] = ("heat", 123456789.0)
    poller._evict_invalidated_pending_updates({"AC_FUN_POWER": "Off"})
    assert len(poller._pending_updates) == 0

async def test_async_merge_device_state():
    """Test that partial state updates from push notifications merge correctly."""
    mock_controller = MagicMock()
    mock_controller.get_current_state_callback.return_value = MagicMock()
    mock_getter = MagicMock()
    mock_getter.value = {"temperature": 20.0}
    mock_controller.loader.state_getter = mock_getter
    
    poller = YamlStatePoller(mock_controller)
    
    # Patch _calculate_structured_state and async_update_properties_from_state
    with patch.object(poller, "_calculate_structured_state", return_value={"temp": 22.0}), \
         patch.object(poller, "async_update_properties_from_state", new_callable=AsyncMock) as mock_update, \
         patch.object(poller, "_build_device_state_from_hass", new_callable=AsyncMock, return_value={"temperature": 20.0}):
        
        result = await poller.async_merge_device_state({"temperature": 22.0}, False, False)
        
        assert result is True
        mock_update.assert_awaited_once()
        # Verify the merge
        assert mock_getter.value == {"temperature": 22.0}

async def test_async_predict_and_correct_state():
    """Test state prediction returns expected corrections without mutating main state directly."""
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    
    # Setup mock current_hass_state
    current_hass_state = MagicMock()
    current_hass_state.hvac_mode = "cool"
    
    mock_getter = MagicMock()
    mock_getter.value = {"AC_FUN_POWER": "On"}
    mock_controller.loader.state_getter = mock_getter
    
    mock_op = MagicMock()
    mock_op.id = "hvac_mode"
    mock_op.value = "cool"
    mock_controller.loader.operations = {"hvac_mode": mock_op}
    mock_controller.loader.properties = {}
    
    poller = YamlStatePoller(mock_controller)
    poller._get_hass_attr_for_op_id = MagicMock(return_value="hvac_mode")
    
    # Patch _build_device_state_from_props and async_update_properties_from_state
    with patch.object(poller, "_build_device_state_from_props", new_callable=AsyncMock, return_value={"AC_FUN_OPMODE": "Heat"}), \
         patch.object(poller, "async_update_properties_from_state", new_callable=AsyncMock, return_value={"hvac_mode": "heat"}):
             
        feature, corrections = await poller.async_predict_and_correct_state(current_hass_state, "hvac_mode", "heat")
        
        assert corrections == {"hvac_mode": "heat"}
        # The mock operation should be updated locally
        assert mock_op.value == "heat"

# --- FRENTE 3: Recuperación de Errores ---

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

# --- FRENTE 4: Cierre y Apagado ---

async def test_async_shutdown():
    """Test that shutdown closes connections cleanly."""
    mock_controller = MagicMock()
    mock_connection = AsyncMock()
    mock_controller.loader.connection = mock_connection
    
    poller = YamlStatePoller(mock_controller)
    
    await poller.async_shutdown()
    
    # The connection should have been told to close
    mock_connection.close.assert_called_once()

# --- FRENTE 5: Cobertura Extrema (Edge Cases) ---

def test_update_all_connections_token():
    """Test propagating new token to all connections."""
    mock_controller = MagicMock()
    
    mock_conn1 = MagicMock()
    mock_conn1.update_auth_token = MagicMock()
    
    mock_prop1 = MagicMock()
    mock_prop1.get_connection.return_value = mock_conn1
    
    mock_conn2 = MagicMock() # No update_auth_token method
    del mock_conn2.update_auth_token
    
    mock_prop2 = MagicMock()
    mock_prop2.get_connection.return_value = mock_conn2

    poller = YamlStatePoller(mock_controller)
    poller._all_props = MagicMock(return_value=[mock_prop1, mock_prop2, None])
    
    poller._update_all_connections_token("nuevo_token")
    mock_conn1.update_auth_token.assert_called_once_with("nuevo_token")

def test_mask_sensitive_data():
    """Test recursive masking of sensitive data."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    payload = {
        "uuid": "1234567890abcdef",
        "nested": {
            "uuid": "short", # Shouldn't be masked
            "list_val": [{"uuid": "1234567890abcdef"}]
        }
    }
    
    masked = poller._mask_sensitive_data(payload)
    assert masked["uuid"] == "***abcdef"
    assert masked["nested"]["uuid"] == "short"
    assert masked["nested"]["list_val"][0]["uuid"] == "***abcdef"

async def test_async_merge_device_state_edge_cases():
    """Test edge cases in async_merge_device_state."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    # Empty data
    assert await poller.async_merge_device_state({}, False, False) is False
    
    # No state getter
    mock_controller.get_current_state_callback.return_value = None
    mock_controller.loader.state_getter = None
    assert await poller.async_merge_device_state({"k": "v"}, False, False) is False
    
    # State getter has no value
    mock_controller.loader.state_getter = MagicMock(spec=[])
    assert await poller.async_merge_device_state({"k": "v"}, False, False) is False
    
    # Calculate structured returns None
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.value = {"k": "v"}
    with patch.object(poller, "_calculate_structured_state", return_value=None):
        assert await poller.async_merge_device_state({"k2": "v2"}, False, False) is False

async def test_async_predict_and_correct_state_edge_cases():
    """Test edge cases in async_predict_and_correct_state."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    poller._get_hass_attr_for_op_id = MagicMock(return_value="mock_attr")
    
    # Not fully initialized
    mock_controller.loader.is_fully_initialized = False
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "k", "v")
    assert c == {}
    
    # No last real state
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter = MagicMock(spec=[])
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "k", "v")
    assert c == {}
    
    # Property not found
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.value = {"x": "y"}
    mock_controller.loader.operations = {}
    mock_controller.loader.properties = {}
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "k", "v")
    assert c == {}
    
    # Future state is empty
    mock_op = MagicMock()
    mock_controller.loader.operations = {"k": mock_op}
    with patch.object(poller, "_build_device_state_from_props", new_callable=AsyncMock, return_value={}):
        f, c = await poller.async_predict_and_correct_state(MagicMock(), "k", "v")
        assert c == {}

# --- FRENTE 6: _build_device_state_from_hass ---

async def test_build_device_state_from_hass_early_exits():
    """Test early exits in _build_device_state_from_hass."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    # 1. Not fully initialized
    mock_controller.loader.is_fully_initialized = False
    assert await poller._build_device_state_from_hass(MagicMock()) is None
    
    # 2. No state getter
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter = None
    assert await poller._build_device_state_from_hass(MagicMock()) is None
    
    # 3. state_getter has no value
    mock_controller.loader.state_getter = MagicMock(spec=[])
    assert await poller._build_device_state_from_hass(MagicMock()) == {}

async def test_build_device_state_from_hass_reconstruction():
    """Test full reconstruction in _build_device_state_from_hass."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.value = {"dev_mode": "old_dev"}
    
    # Setup op
    mock_op = MagicMock()
    mock_op.id = "hvac_mode"
    mock_op.convert_hass_to_dev = MagicMock(return_value="new_dev")
    
    # Another op without ID
    mock_op_no_id = MagicMock()
    del mock_op_no_id.id
    
    # Property op
    mock_prop = MagicMock()
    mock_prop.id = "temperature"
    mock_prop.convert_hass_to_dev = MagicMock(return_value=23)
    
    mock_controller.loader.operations = {"hvac": mock_op, "no_id": mock_op_no_id}
    mock_controller.loader.properties = {"temp": mock_prop}
    
    # We mock _get_hass_attr_for_op_id
    poller._get_hass_attr_for_op_id = MagicMock(side_effect=lambda x: x)
    # We mock _get_cached_device_key_from_prop
    poller._get_cached_device_key_from_prop = MagicMock(side_effect=lambda op: "dev_mode" if op == mock_op else "dev_temp")
    
    # Setup HASS state input
    hass_state = MagicMock()
    hass_state.hvac_mode = "cool"
    hass_state.temperature = 23
    
    res = await poller._build_device_state_from_hass(hass_state)
    
    # Since dev_temp is not in reconstructed_state originally, it shouldn't be added!
    # "dev_mode" is in reconstructed_state, so it should be modified.
    assert res == {"dev_mode": "new_dev"}
    mock_op.convert_hass_to_dev.assert_called_once_with("cool")
    mock_prop.convert_hass_to_dev.assert_called_once_with(23)


# --- FRENTE 7: async_update_state edge cases ---

@patch("custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability", new_callable=AsyncMock)
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
    poller.controller.loader.state_getter.async_update_state = AsyncMock(return_value={"recovered": True})
    poller.controller.loader.state_getter.value = {"recovered": True}
    
    with patch("custom_components.climate_ip.controller_yaml_polling.async_delete_issue") as mock_del:
        res = await poller.async_update_state()
        assert res == {"recovered": True}
        assert poller._consecutive_connection_errors == 0
        mock_del.assert_called_once()

@patch("custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability", new_callable=AsyncMock)
async def test_async_update_state_network_diagnostics_exceptions(mock_reachability):
    """Test when reachability throws non-CannotConnect exceptions."""
    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = "192.168.1.100"
    poller = YamlStatePoller(mock_controller)
    
    # Reachability throws a ValueError
    mock_reachability.side_effect = ValueError("Some weird DNS error")
    
    # The error should be swallowed and we attempt to poll anyway!
    poller.controller.loader.state_getter.async_update_state = AsyncMock(return_value={"polled": True})
    poller.controller.loader.state_getter.value = {"polled": True}
    res = await poller.async_update_state()
    assert res == {"polled": True}

async def test_async_update_state_auth_refresh_exception_handling():
    """Test AuthError refresh exception flow."""
    from custom_components.climate_ip.exceptions import AuthError
    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = None # Bypass network check
    
    poller = YamlStatePoller(mock_controller)
    
    # 1. async_update_state throws AuthError
    poller.controller.loader.state_getter.async_update_state = AsyncMock(side_effect=AuthError)
    
    # 2. Refresh succeeds
    poller._refresh_smartthings_token = AsyncMock(return_value=True)
    
    # 3. But post-refresh state fetch throws ANOTHER exception
    # (Since we mock it statically here, it will always throw. Let's make it throw a different error)
    poller.controller.loader.state_getter.async_update_state.side_effect = [AuthError("err"), ValueError("Post refresh crash")]
    
    from homeassistant.helpers.update_coordinator import UpdateFailed
    with pytest.raises(UpdateFailed, match="Retry after token refresh failed"):
        await poller.async_update_state()

async def test_async_update_state_auth_refresh_fails_permanently():
    """Test AuthError where token refresh itself fails."""
    from custom_components.climate_ip.exceptions import AuthError
    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = None
    
    poller = YamlStatePoller(mock_controller)
    
    poller.controller.loader.state_getter.async_update_state = AsyncMock(side_effect=AuthError)
    poller._refresh_smartthings_token = AsyncMock(return_value=False)
    
    from homeassistant.exceptions import ConfigEntryAuthFailed
    with pytest.raises(ConfigEntryAuthFailed, match="Authentication failed"):
        await poller.async_update_state()



# --- FRENTE 8: async_predict_and_correct_state ---

async def test_predict_and_correct_early_exits():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    # 1. state_getter = None
    mock_controller.loader.state_getter = None
    mock_controller.loader.is_fully_initialized = True
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f == 0 and c == {}
    
    # 2. is_fully_initialized = False
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.is_fully_initialized = False
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f == 0 and c == {}
    
    # 3. last_real_state = None
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.value = None
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f == 0 and c == {}
    
    # 4. prop_to_change is None
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_op = MagicMock()
    mock_op.id = "some_op"
    mock_controller.loader.operations = {"other_prop": mock_op}
    mock_controller.loader.properties = {}
    poller._get_hass_attr_for_op_id = MagicMock(return_value="some_attr")
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f == 0 and c == {}

async def test_predict_and_correct_op_and_prop_values():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_controller.loader.is_fully_initialized = True
    
    # Setup op with value
    op_value = MagicMock()
    op_value.id = "op_val"
    op_value.value = "old"
    
    # Setup op with _value
    op_uvalue = MagicMock()
    op_uvalue.id = "op_uval"
    del op_uvalue.value
    op_uvalue._value = "old"
    
    # Setup prop with value
    prop_value = MagicMock()
    prop_value.id = "prop_val"
    prop_value.value = "old"
    
    # Setup prop with _value
    prop_uvalue = MagicMock()
    prop_uvalue.id = "prop_uval"
    del prop_uvalue.value
    prop_uvalue._value = "old"
    
    mock_controller.loader.operations = {"op1": op_value, "op2": op_uvalue}
    mock_controller.loader.properties = {"prop1": prop_value, "prop2": prop_uvalue}
    
    poller._get_hass_attr_for_op_id = MagicMock(side_effect=lambda x: f"hass_{x}")
    
    hass_state = MagicMock()
    hass_state.hass_op_val = "new1"
    hass_state.hass_op_uval = "new2"
    hass_state.hass_prop_val = "new3"
    hass_state.hass_prop_uval = "new4"
    
    poller._build_device_state_from_props = AsyncMock(return_value={}) # Will trigger future_state = empty early exit
    
    f, c = await poller.async_predict_and_correct_state(hass_state, "op1", "new1")
    
    assert op_value.value == "new1"
    assert op_uvalue._value == "new2"
    assert prop_value.value == "new3"
    assert prop_uvalue._value == "new4"

async def test_predict_and_correct_full_flow():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_controller.loader.is_fully_initialized = True
    
    poller._pending_updates = {"target_prop": 123}
    
    target_op = MagicMock()
    target_op.id = "target"
    del target_op.value
    target_op._value = "old"
    
    mock_controller.loader.operations = {"target_prop": target_op}
    mock_controller.loader.properties = {}
    
    poller._get_hass_attr_for_op_id = MagicMock(return_value="hass_target")
    hass_state = MagicMock()
    hass_state.hass_target = "old"
    
    poller._build_device_state_from_props = AsyncMock(return_value={"built": "yes"})
    poller.async_update_properties_from_state = AsyncMock(return_value={"correction": "done"})
    
    f, c = await poller.async_predict_and_correct_state(hass_state, "target_prop", "predicted_val")
    
    assert "target_prop" not in poller._pending_updates
    assert target_op._value == "predicted_val"
    assert c == {"correction": "done"}
    poller.async_update_properties_from_state.assert_called_once_with({"built": "yes"}, is_prediction=True, current_hass_state=hass_state)


# --- FRENTE 9: async_shutdown ---

async def test_async_shutdown_no_connection():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    mock_controller.loader.connection = None
    
    # Should not throw, should just sleep and return
    with patch("custom_components.climate_ip.controller_yaml_polling.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
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
    
    with patch("custom_components.climate_ip.controller_yaml_polling.asyncio.sleep", new_callable=AsyncMock):
        await poller.async_shutdown() # Should not raise
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
    
    with patch("custom_components.climate_ip.controller_yaml_polling.asyncio.sleep", new_callable=AsyncMock):
        await poller.async_shutdown() # Should not raise
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
    
    with patch("custom_components.climate_ip.controller_yaml_polling.asyncio.sleep", new_callable=AsyncMock):
        await poller.async_shutdown() # Should not raise
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
    
    with patch("custom_components.climate_ip.controller_yaml_polling.asyncio.sleep", new_callable=AsyncMock):
        await poller.async_shutdown() # Should not raise
    conn.close.assert_called_once()
    assert mock_controller.loader.connection is None


# --- FRENTE 10: async_update_state ---

async def test_update_state_repair_issue_delete_exception():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(return_value={"a": 1})
    mock_controller.loader.state_getter.value = {"a": 1}
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.discovered_devices = [{"id": "dev1"}]
    
    with patch("custom_components.climate_ip.controller_yaml_polling.async_delete_issue", side_effect=Exception("Boom")):
        res = await poller.async_update_state()
    assert res == {"a": 1}

async def test_update_state_invalid_header_error():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    from custom_components.climate_ip.exceptions import InvalidHeaderError
    mock_controller.loader.state_getter.async_update_state = AsyncMock(side_effect=InvalidHeaderError("Bad header"))
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.discovered_devices = [{"id": "dev1"}]
    
    with pytest.raises(InvalidHeaderError):
        await poller.async_update_state()

async def test_update_state_api_error_cached_fallback():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    from custom_components.climate_ip.exceptions import CannotConnect
    mock_controller.loader.state_getter.async_update_state = AsyncMock(side_effect=CannotConnect("API Failure"))
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

async def test_update_state_discovery_fallback():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.connection = None
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(return_value={"a": 1})
    mock_controller.loader.state_getter.value = {"a": 1}
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.loader.is_fully_initialized = False
    mock_controller.ip_address = "1.2.3.4"
    mock_controller.discovered_devices = [{"id": "dev1"}]
    mock_controller.mac_address = "MAC"
    
    mock_controller.loader.create_connection = AsyncMock()
    await poller.async_update_state()

# --- FRENTE 11: async_update_properties_from_state ---

async def test_update_props_not_initialized():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = False
    mock_controller.discovered_devices = [{"id": "dev1"}]
    assert await poller.async_update_properties_from_state({"a": 1}) == {}

async def test_update_props_null_device_state():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.discovered_devices = [{"id": "dev1"}]
    assert await poller.async_update_properties_from_state(None) == {}

async def test_update_props_invalid_dict():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.discovered_devices = [{"id": "dev1"}]
    assert await poller.async_update_properties_from_state(["not", "a", "dict"]) == {}

async def test_update_props_pending_update_uvalue():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.discovered_devices = [{"id": "dev1"}]
    
    class DummyOp: pass
    prop_uvalue = DummyOp()
    prop_uvalue.id = "uprop"
    prop_uvalue._value = "old"
    
    mock_controller.loader.properties = {"uprop": prop_uvalue}
    mock_controller.loader.operations = {}
    
    import time
    poller._pending_updates = {"uprop": ("new_val", time.time())}
    
    await poller.async_update_properties_from_state({"some": "state"})
    assert prop_uvalue._value == "new_val"

# --- FRENTE 12: _build_device_state_from_props ---

async def test_build_device_state_op_not_valid():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    op_invalid = MagicMock()
    op_invalid.is_valid = MagicMock(return_value=False)
    
    mock_controller.loader.operations = {"op": op_invalid}
    mock_controller.loader.properties = {}
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_controller.discovered_devices = [{"id": "dev1"}]
    
    await poller.async_update_properties_from_state({"id": "dev1"})
    op_invalid.is_valid.assert_called_once()

async def test_build_device_state_uvalue_assignment():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    class DummyOp: pass
    op_uvalue = DummyOp()
    op_uvalue.id = "uop"
    op_uvalue.is_valid = lambda x: True
    op_uvalue.values = ["new", "val"]
    op_uvalue._value = "unknown_val"
    
    mock_controller.loader.operations = {"op": op_uvalue}
    mock_controller.loader.properties = {}
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_controller.discovered_devices = [{"id": "dev1"}]
    
    await poller.async_update_properties_from_state({"id": "dev1"})
    assert op_uvalue._value == "new"

def test_get_hass_attr_for_op_id_unmocked():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    assert poller._get_hass_attr_for_op_id("hvac") == "hvac_mode"
    assert poller._get_hass_attr_for_op_id("unknown_op") == "unknown_op"

async def test_build_device_state_from_hass_edge_cases():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.value = {"dev_key": "old"}
    
    op = MagicMock()
    op.id = "hvac"
    op.convert_hass_to_dev = MagicMock(return_value="dev_new")
    
    mock_controller.loader.operations = {"op": op}
    mock_controller.loader.properties = {}
    
    poller._get_cached_device_key_from_prop = MagicMock(return_value=None)
    
    hass_state = MagicMock()
    hass_state.hvac_mode = "hass_new"
    
    res = await poller._build_device_state_from_hass(hass_state)
    assert res == {"dev_key": "old"} 

# --- FRENTE 13: async_merge_device_state ---

async def test_merge_device_state_atomic_merge():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    updates = {"c": 3}
    
    mock_controller.loader.properties = {}
    mock_controller.loader.operations = {}
    mock_controller.loader._parsed_yaml_cache = {}
    
    mock_controller.loader.state_getter = MagicMock()
    mock_controller.loader.state_getter.value = {"a": 1, "b": 2}
    
    hass_state_mock = MagicMock()
    mock_controller.get_current_state_callback = MagicMock(return_value=hass_state_mock)
    
    # 1. Validation fails
    poller._calculate_structured_state = MagicMock(return_value=None)
    res_fail = await poller.async_merge_device_state(updates, _is_response=False, _is_update=True)
    assert res_fail is False
    
    # 2. Validation succeeds
    poller._calculate_structured_state = MagicMock(return_value={"valid": True})
    res_succ = await poller.async_merge_device_state(updates, _is_response=False, _is_update=True)
    assert res_succ is True

async def test_merge_device_state_empty_and_overwrite():
    """Misión Táctica 2: async_merge_device_state empty data and strict dict overwrite"""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    # 1. new_data vacío
    assert await poller.async_merge_device_state({}, False, False) is False
    
    # 2. Strict Overwrite testing & Deepcopy verification
    mock_controller.get_current_state_callback = MagicMock(return_value=None)
    
    base_state = {"Untouched": {"nested": "A"}}
    
    class MockStateGetter:
        value = base_state
        
    mock_controller.loader.state_getter = MockStateGetter()
    poller._calculate_structured_state = MagicMock(return_value={"valid": True})
    poller.async_update_properties_from_state = AsyncMock()
    poller._evict_invalidated_pending_updates = MagicMock()
    
    new_data = {"NewKey": "B"}
    
    res = await poller.async_merge_device_state(new_data, False, False)
    assert res is True
    
    expected_state = {
        "Untouched": {"nested": "A"},
        "NewKey": "B"
    }
    
    # Check that update worked
    assert MockStateGetter.value == expected_state
    
    # Check deepcopy: modifying the new state should not affect the original state
    MockStateGetter.value["Untouched"]["nested"] = "Hacked"
    assert base_state["Untouched"]["nested"] == "A"

async def test_merge_device_state_strict_conditionals():
    """Misión Táctica 2: async_merge_device_state strict mock conditions"""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock
    
    mock_controller = MagicMock()
    # Explicitly removing get_current_state_callback to force hasattr check to fail if mutated
    del mock_controller.get_current_state_callback
    poller = YamlStatePoller(mock_controller)
    
    # 1. No st_getter
    class StrictLoader:
        pass
    mock_controller.loader = StrictLoader()
    
    assert await poller.async_merge_device_state({"a": 1}, False, False) is False
    
    # 2. st_getter sin value
    class LoaderWithGetter:
        class StateGetter:
            pass
        state_getter = StateGetter()
        
    mock_controller.loader = LoaderWithGetter()
    assert await poller.async_merge_device_state({"a": 1}, False, False) is False
    
    # 3. current_hass_state is true -> uses _build_device_state_from_hass
    mock_controller.get_current_state_callback = MagicMock(return_value="mock_hass_state")
    poller._build_device_state_from_hass = AsyncMock(return_value=None)
    
    assert await poller.async_merge_device_state({"a": 1}, False, False) is False
    poller._build_device_state_from_hass.assert_called_once_with("mock_hass_state")

def test_mask_sensitive_data_primitive():
    """L183: Retorno temprano para datos primitivos."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    poller = YamlStatePoller(MagicMock())
    assert poller._mask_sensitive_data("primitive_string") == "primitive_string"
    assert poller._mask_sensitive_data(123) == 123

async def test_update_state_delete_issue_exception():
    """L260-261: Captura de excepción en async_delete_issue."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock, MagicMock, patch
    
    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.ip_address = "1.2.3.4"
    mock_controller.hass = MagicMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(return_value={"a": 1})
    
    poller = YamlStatePoller(mock_controller)
    poller._consecutive_connection_errors = 1
    poller._build_device_state_from_hass = AsyncMock(return_value={"a": 1})
    poller.async_update_properties_from_state = AsyncMock()
    
    with patch("custom_components.climate_ip.controller_yaml_polling.async_delete_issue", side_effect=Exception("Test Error")):
        # No debe crashear
        await poller.async_update_state()

async def test_build_device_state_from_props_other_op():
    """L760-762: Reconstrucción de estado con operaciones no mapeadas estáticamente."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    class MockOp:
        def __init__(self, op_id, val):
            self.id = op_id
            self.value = val

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.loader.state_getter.value = {}
    op_other = MockOp("purify", "On")
    mock_controller.loader.operations = {"purify": op_other}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}
    
    poller = YamlStatePoller(mock_controller)
    poller._get_cached_device_key_from_prop = MagicMock(return_value="PurifierMode")
    
    res = await poller._build_device_state_from_props()
    assert res["PurifierMode"] == "On"

async def test_build_device_state_memory_isolation():
    """Vector 1: Aislamiento de Memoria (Mutación de deepcopy a copy)"""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    last_real_state = {"Mode": {"modes": ["Cool", "Heat"]}}
    mock_controller.loader.state_getter.value = last_real_state
    mock_controller.loader.operations = {}
    mock_controller.loader.properties = {}
    
    res = await poller._build_device_state_from_props()
    # Modificar profundamente el resultado
    res["Mode"]["modes"][0] = "Hacked"
    
    # Asegurar que el estado original NO cambió
    assert mock_controller.loader.state_getter.value["Mode"]["modes"][0] == "Cool"

async def test_build_device_state_loop_control():
    """Vector 2: Control de Bucle (Mutación de continue a break)"""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    mock_controller.loader.state_getter.value = {}
    
    class MockOpNone:
        id = "op_none"
        value = None
        
    class MockOpValid:
        id = "op_valid"
        value = "Valid"
        
    mock_controller.loader.operations = {"op1": MockOpNone(), "op2": MockOpValid()}
    mock_controller.loader.properties = {}
    
    poller._get_cached_device_key_from_prop = MagicMock(return_value="ValidKey")
    mock_controller.config.get.return_value = "REST"
    
    res = await poller._build_device_state_from_props()
    
    # Si muta a break, op2 no será procesado
    assert "ValidKey" in res
    assert res["ValidKey"] == "Valid"

async def test_build_device_state_none_fallbacks():
    """Vector 3: None Fallbacks en Mocks (getattr y config.get)"""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE
    from unittest.mock import MagicMock
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    mock_controller.loader.state_getter.value = {}
    
    class StrictOp:
        value = "val"
        # Sin atributo 'id' para forzar que se evalúe el getattr por defecto
        
    mock_controller.loader.operations = {"op1": StrictOp()}
    mock_controller.loader.properties = {}
    
    res = await poller._build_device_state_from_props()
    
    # Verificar assert_called_once_with
    mock_controller.config.get.assert_called_once_with(CONF_DEVICE_TYPE)

async def test_build_device_state_nested_dicts():
    """Vector 4: Lógica de Diccionarios Anidados (Completo)"""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    class MockOp(object):
        pass

    op = MockOp()
    op.id = "fan"
    op.value = "3"

    mock_controller.loader.operations = {"op1": op}
    mock_controller.loader.properties = {}
    mock_controller.config.get.return_value = "REST"
    
    # Caso 1: device_list vacío
    mock_controller.loader.state_getter.value = {"Devices": []}
    assert await poller._build_device_state_from_props() == {"Devices": []}
    
    # Caso 2: device_list no es lista
    mock_controller.loader.state_getter.value = {"Devices": "NotAList"}
    assert await poller._build_device_state_from_props() == {"Devices": "NotAList"}

    # Caso 3: Happy path asegurando setdefault y enteros
    mock_controller.loader.state_getter.value = {"Devices": [{}]}
    res = await poller._build_device_state_from_props()
    assert res == {"Devices": [{"Wind": {"speedLevel": 3}}]}
    
    # Caso 4: setdefault no sobreescribe si ya existe
    mock_controller.loader.state_getter.value = {"Devices": [{"Wind": {"direction": "Up"}}]}
    res2 = await poller._build_device_state_from_props()
    assert res2 == {"Devices": [{"Wind": {"direction": "Up", "speedLevel": 3}}]}

async def test_build_device_state_naked_dicts():
    """Vector 4: Naked Dicts (Misión Táctica 1)"""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    
    class MockOp(object):
        pass

    op_hvac = MockOp()
    op_hvac.id = "hvac"
    op_hvac.value = "Heat"

    op_fan = MockOp()
    op_fan.id = "fan"
    op_fan.value = "3"
    
    op_preset = MockOp()
    op_preset.id = "preset_mode"
    op_preset.value = "Eco"

    mock_controller.loader.operations = {"op1": op_hvac, "op2": op_fan, "op3": op_preset}
    mock_controller.loader.properties = {}
    mock_controller.config.get.return_value = "REST"
    
    mock_controller.loader.state_getter.value = {"Devices": [{}]}
    
    res = await poller._build_device_state_from_props()
    
    dev_obj = res["Devices"][0]
    assert "Operation" in dev_obj
    assert dev_obj["Operation"]["power"] == "On"
    
    assert "Mode" in dev_obj
    assert dev_obj["Mode"]["modes"] == ["Heat"]
    assert dev_obj["Mode"]["options"][0] == "Eco"
    
    assert "Wind" in dev_obj
    assert dev_obj["Wind"]["speedLevel"] == 3

def test_get_device_key_empty_template():
    """L933: Retorno nulo si el template_string queda vacío."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    poller = YamlStatePoller(MagicMock())
    assert poller._get_device_key_from_template("") is None
    
    class EmptyTemplate:
        template = ""
    assert poller._get_device_key_from_template(EmptyTemplate()) is None

async def test_update_state_full_state_none():
    """Fuerza salidas tempranas (Líneas 347-353) cuando full_device_state es None."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock, MagicMock
    from homeassistant.helpers.update_coordinator import UpdateFailed
    import pytest
    
    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.loader.state_getter.async_update_state = AsyncMock(return_value=None)
    
    poller = YamlStatePoller(mock_controller)
    poller._cached_device_state = {"a": 1}
    
    # Caso 1: Con caché (Línea 347-352)
    res = await poller.async_update_state()
    assert res == {"a": 1}
    
    # Caso 2: Sin caché (Línea 353-355)
    poller._cached_device_state = None
    with pytest.raises(UpdateFailed, match="No data received and no cache available"):
        await poller.async_update_state()

async def test_update_state_discovery_non_2878():
    """Fuerza descubrimiento de dispositivo para no-2878 (Línea 394)."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock, MagicMock
    
    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.device_id = "0"
    mock_controller.loader.is_fully_initialized = False
    mock_controller.loader.state_getter.async_update_state = AsyncMock(return_value={"Devices": [{"id": "123"}]})
    mock_controller.loader._parsed_yaml_cache = {
        "0": {"device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}}
    }
    
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    
    await poller.async_update_state()
    assert mock_controller.device_id == "123"

async def test_update_properties_full_state_none():
    """Fuerza L459 en async_update_properties_from_state."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock, MagicMock
    
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    poller._build_device_state_from_hass = AsyncMock(return_value=None)
    
    # current_hass_state = True, _build_device_state_from_hass devuelve None
    res = await poller.async_update_properties_from_state(None, current_hass_state={"state": "on"})
    assert res == {}

def test_rebuild_attributes_private():
    """Fuerza L597 en _rebuild_attributes usando _attributes."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    class MockCtrl:
        def __init__(self):
            self.name = "TestCtrl"
            self.loader = MagicMock()
            self._attributes = {}
            
    ctrl = MockCtrl()
    poller = YamlStatePoller(ctrl)
    poller._rebuild_attributes()
    assert "last_sync" in ctrl._attributes
async def test_merge_device_state_st_getter_private_value():
    """Fuerza la línea 859-860 donde st_getter no tiene 'value' pero sí '_value'."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock, MagicMock
    
    mock_controller = MagicMock()
    # No hasattr "value", pero sí "_value"
    class MockGetter:
        def __init__(self):
            self._value = {}
            
    mock_controller.loader.state_getter = MockGetter()
    poller = YamlStatePoller(mock_controller)
    poller._build_device_state_from_props = AsyncMock(return_value={"a": 1})
    poller._calculate_structured_state = MagicMock(return_value={"valid": True})
    poller.async_update_properties_from_state = AsyncMock()

    res = await poller.async_merge_device_state({"b": 2}, _is_response=False, _is_update=True)
    assert res is True
    assert mock_controller.loader.state_getter._value == {"b": 2}

def test_evict_invalidated_pending_updates_none_prop():
    """Fuerza la línea 881 donde el prop no se encuentra (None) durante el desalojo."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    
    mock_controller = MagicMock()
    mock_controller.loader.operations = {}
    mock_controller.loader.properties = {}
    
    poller = YamlStatePoller(mock_controller)
    poller._pending_updates = {"missing_prop_id": 12345}
    
    # Esto pasaría y haría un 'continue' sin excepciones
    poller._evict_invalidated_pending_updates({"some_key": "val"})
    assert "missing_prop_id" in poller._pending_updates

# ====================================================================================
# FRENTE SNIPER: async_update_state (Reintentos, Caché, Reparación y Debug)
# ====================================================================================

from custom_components.climate_ip.exceptions import CannotConnect
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from unittest.mock import AsyncMock, patch

class DummyStateGetter:
    def __init__(self):
        self.async_update_state = AsyncMock()
        self.value = None

class DummyLoader:
    def __init__(self):
        self.state_getter = DummyStateGetter()
        self.is_fully_initialized = True
        self._parsed_yaml_cache = {}
        
    async def async_finish_initialization(self):
        pass

class DummyController:
    """Clase Python estándar para sustituir a MagicMock y forzar AttributeErrors reales en getattr."""
    def __init__(self, **kwargs):
        self.log_prefix = "TEST"
        self.config = {}
        self.loader = DummyLoader()
        # Inyectar solo los atributos estrictamente declarados
        for k, v in kwargs.items():
            setattr(self, k, v)

async def test_async_update_state_sniper_retries_and_cache():
    """Sniper: Lógica de reintentos, caché y colapso total (con aserción dura de rsplit)."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    
    mock_controller = DummyController()
    mock_controller.config = {"device_type": "samsung_2878"}
    
    # Excepción con ":" para probar el rsplit(":", maxsplit=1)[-1].strip() de la línea 336
    error_msg = "ConnectionError: Timeout on host"
    
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=[
            CannotConnect(error_msg), # Fallo 1
            CannotConnect(error_msg), # Fallo 2
            {"power": "recovered"}    # Recuperación
        ]
    )
    mock_controller.loader.state_getter.value = {"power": "recovered"}
    
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    poller._cached_device_state = {"power": "cached_on"}
    poller._consecutive_connection_errors = 0
    
    with patch.object(poller, "_try_create_repair_issue") as mock_repair:
        # Fallo 1
        res1 = await poller.async_update_state()
        assert res1 == {"power": "cached_on"}
        assert poller._consecutive_connection_errors == 1
        mock_repair.assert_not_called()
        
        # Fallo 2
        res2 = await poller.async_update_state()
        assert res2 == {"power": "cached_on"}
        assert poller._consecutive_connection_errors == 2
        mock_repair.assert_not_called()
        
        # Recuperación (Fallo 3 no ocurre, se reinician los contadores)
        res3 = await poller.async_update_state()
        assert res3 == {"power": "recovered"}
        assert poller._consecutive_connection_errors == 0
        mock_repair.assert_not_called()
        
        # Colapso total: Forzamos el límite y lanzamos excepción validando el parseo
        mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect(error_msg)
        poller._consecutive_connection_errors = 2
        
        # Validamos aserción FUERTE: ^Device unreachable: Timeout on host$
        with pytest.raises(UpdateFailed, match="^Device unreachable: Timeout on host$"):
            await poller.async_update_state()
            
        assert poller._consecutive_connection_errors == 3
        mock_repair.assert_called_once()

async def test_async_update_state_sniper_debug_and_fallbacks():
    """Sniper: Validación inicial de state_getter y debug con getattr."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    
    # 1. Sin state_getter
    mock_controller = DummyController()
    mock_controller.loader.state_getter = None
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    
    with pytest.raises(UpdateFailed, match="State getter is not initialized"):
        await poller.async_update_state()
        
    # 2. Con debug en True (probando atributo existente)
    mock_controller = DummyController(debug=True)
    mock_controller.config = {"device_type": "samsung_2878"}
    mock_controller.loader.state_getter.async_update_state.return_value = {"power": "on_debug"}
    mock_controller.loader.state_getter.value = {"power": "on_debug"}
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    
    res = await poller.async_update_state()
    assert res == {"power": "on_debug"}
    mock_controller.loader.state_getter.async_update_state.assert_called_once_with(None, True)
    
    # 3. Fallback: sin atributo debug configurado (DummyController lanzará AttributeError si quitan el fallback)
    mock_controller = DummyController() # No tiene 'debug'
    mock_controller.config = {"device_type": "samsung_2878"}
    mock_controller.loader.state_getter.async_update_state.return_value = {"power": "on_nodebug"}
    mock_controller.loader.state_getter.value = {"power": "on_nodebug"}
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    
    res2 = await poller.async_update_state()
    assert res2 == {"power": "on_nodebug"}
    mock_controller.loader.state_getter.async_update_state.assert_called_once_with(None, False)

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
    
    with patch("custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability", new_callable=AsyncMock) as mock_ping:
        # 1. Ping falla
        mock_ping.return_value = False
        
        with pytest.raises(CannotConnect, match="^Host unreachable \\(ICMP ping failed\\). Device is persistently offline.$"):
            await poller.async_update_state()
            
        assert mock_ping.called
        assert poller._consecutive_connection_errors == 2

        # 2. Ping falla de nuevo (colapso)
        mock_ping.reset_mock()
        with patch.object(poller, "_try_create_repair_issue") as mock_repair:
            with pytest.raises(CannotConnect, match="^Host unreachable \\(ICMP ping failed\\). Device is persistently offline.$"):
                await poller.async_update_state()
            assert poller._consecutive_connection_errors == 3
            mock_repair.assert_called_once()

        # 3. Ping lanza excepción pero se captura como diagnóstico, delegando luego a state_getter
        mock_ping.side_effect = Exception("Ping error")
        mock_controller.loader.state_getter.async_update_state.return_value = {"state": "ping_failed_but_recovered"}
        mock_controller.loader.state_getter.value = {"state": "ping_failed_but_recovered"}
        
        res = await poller.async_update_state()
        assert res == {"state": "ping_failed_but_recovered"}

async def test_async_update_state_sniper_discovery():
    """Sniper: Valida la inicialización de estado, fallbacks de diccionario en id_map, y el filtro estricto de discovery."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock
    import pytest

    # Inicializamos el controlador sin device_id para forzar los fallbacks a "XXXX"
    mock_controller = DummyController()
    if hasattr(mock_controller, "device_id"):
        delattr(mock_controller, "device_id")
    mock_controller.config = {"device_type": "mim_h03"}
    mock_controller.loader.is_fully_initialized = False
    
    mock_controller.loader.async_finish_initialization = AsyncMock()
    
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    
    # =========================================================================
    # FASE 1: Romper la Cadena de Diccionarios (Exterminio de None Fallbacks)
    # =========================================================================
    from unittest.mock import patch, PropertyMock
    
    with patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.error") as mock_log_err:
        # Test 1.0: Sin _parsed_yaml_cache
        if hasattr(mock_controller.loader, "_parsed_yaml_cache"):
            delattr(mock_controller.loader, "_parsed_yaml_cache")
        mock_controller.loader.state_getter.async_update_state.return_value = {"root": {}}
        mock_controller.loader.state_getter.value = {"root": {}}
        
        await poller.async_update_state()
        mock_controller.loader.async_finish_initialization.assert_called_once()
        assert getattr(mock_controller, "device_id", "") == ""
        mock_log_err.assert_not_called()
        
        # Test 1.1: Caché vacía
        mock_controller.loader.async_finish_initialization.reset_mock()
        mock_controller.loader._parsed_yaml_cache = {}
        await poller.async_update_state()
        mock_controller.loader.async_finish_initialization.assert_called_once()
        assert getattr(mock_controller, "device_id", "") == ""
        mock_log_err.assert_not_called()
        
        # Test 1.2: Caché con clave "XXXX" pero sin 'device'
        mock_controller.loader.async_finish_initialization.reset_mock()
        mock_controller.loader._parsed_yaml_cache = {"XXXX": {}}
        await poller.async_update_state()
        mock_controller.loader.async_finish_initialization.assert_called_once()
        assert getattr(mock_controller, "device_id", "") == ""
        mock_log_err.assert_not_called()
        
        # Test 1.3: Caché con 'device' pero sin 'identifiers'
        mock_controller.loader.async_finish_initialization.reset_mock()
        mock_controller.loader._parsed_yaml_cache = {"XXXX": {"device": {}}}
        await poller.async_update_state()
        mock_controller.loader.async_finish_initialization.assert_called_once()
        assert getattr(mock_controller, "device_id", "") == ""
        mock_log_err.assert_not_called()

        # Test 1.4: Inyectamos un Mock explosivo para asegurar la Cobertura del Except
        mock_controller.loader.async_finish_initialization.reset_mock()
        mock_cache = AsyncMock()
        mock_cache.get.side_effect = Exception("Fake Error")
        mock_controller.loader._parsed_yaml_cache = mock_cache
        
        await poller.async_update_state()
        assert getattr(mock_controller, "device_id", "") == ""
        mock_log_err.assert_called_once()
        mock_log_err.reset_mock()

    # Test 1.5: Caché con identifiers vacíos (antiguo Test 1.4)
    mock_controller.loader.async_finish_initialization.reset_mock()
    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {
                "identifiers": {}
            }
        }
    }
    await poller.async_update_state()
    mock_controller.loader.async_finish_initialization.assert_called_once()
    assert getattr(mock_controller, "device_id", "") == ""

    # =========================================================================
    # FASE 2: El Filtro Radiactivo (Exterminio de Logic Condition Flips)
    # =========================================================================
    
    # Inyectamos una caché YAML perfectamente válida
    mock_controller.loader.async_finish_initialization.reset_mock()
    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["devices"],
                    "id": ["id"]
                }
            }
        }
    }
    
    # Inyectamos la lista trampa
    mock_controller.loader.state_getter.async_update_state.return_value = {
        "devices": [
            {},                                   # Trampa 1
            {"id": "0", "Mode": "Cool"},          # Trampa 2
            {"id": "valid_1"},                    # Trampa 3
            {"id": "target_id", "Mode": "Heat"}   # OBJETIVO VÁLIDO
        ]
    }
    mock_controller.loader.state_getter.value = mock_controller.loader.state_getter.async_update_state.return_value
    
    await poller.async_update_state()
    
    # =========================================================================
    # LA SENTENCIA FINAL (Fase 2)
    # =========================================================================
    # Al no tener device_id, el fallback "XXXX" permite recuperar el id_map y poblar discovered_devices.
    # Si mutmut cambia el fallback a None, id_map será None y discovered_devices nunca se poblará.
    assert hasattr(mock_controller, "discovered_devices")
    assert len(mock_controller.discovered_devices) == 4
    mock_controller.loader.async_finish_initialization.assert_called_once()

    # =========================================================================
    # FASE 3: Asignación Final y Exterminio de Logic Condition Flips
    # =========================================================================
    # Para poder probar que la condición seleccionó el dispositivo correcto y lo asignó,
    # NECESITAMOS que device_id exista, pero que esté vacío.
    mock_controller.device_id = ""
    # Ahora la caché debe estar bajo la clave "" en lugar de "XXXX"
    mock_controller.loader._parsed_yaml_cache = {
        "": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["devices"],
                    "id": ["id"]
                }
            }
        }
    }
    await poller.async_update_state()
    # Ahora sí podemos verificar que se seleccionó y asignó "target_id"
    # =========================================================================
    # FASE 3: La Prueba del Vacío (The Void Tests)
    # =========================================================================
    from unittest.mock import patch
    
    # 3.1: Borrado de Atributos (ya cubierto en Fase 1, pero rematamos aquí por estructura)
    if hasattr(mock_controller, "device_id"):
        delattr(mock_controller, "device_id")
    if hasattr(mock_controller.loader, "_parsed_yaml_cache"):
        delattr(mock_controller.loader, "_parsed_yaml_cache")
    
    await poller.async_update_state()
    
    # 3.2: Diccionarios Incompletos para forzar el fallback de []
    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {
                # Debe ser truthy para que no salte el "if id_map:"
                "identifiers": {"dummy": "value"}
            }
        }
    }
    
    # Parcheamos get_value_by_path de modo que podamos interceptar si mutmut pasó None en lugar de [].
    # El usuario notó que la iteración lanzaría TypeError en su modelo mental. Al mockearlo verificamos el argumento.
    with patch("custom_components.climate_ip.controller_yaml_polling.get_value_by_path") as mock_get_value:
        mock_get_value.return_value = None
        await poller.async_update_state()
        # Verificamos que get_value_by_path fue llamado con una lista vacía [], y no con None.
        assert mock_get_value.call_count >= 1
        args, _ = mock_get_value.call_args_list[0]
        assert isinstance(args[1], list)
        
    # 3.3: Cazar a los Boolean Flips de los Logs (exc_info=True)
    # Inyectamos algo que va a reventar al intentar usar id_map.get("path_to_devices")
    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {
                # Debe ser truthy para no saltar el "if id_map:" y que sea lista para romper el .get()
                "identifiers": ["dummy"]
            }
        }
    }
    
    with patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.error") as mock_logger_error:
        await poller.async_update_state()
        assert mock_logger_error.called
        # Comprobamos explícitamente que exc_info=True está en los argumentos
        kwargs = mock_logger_error.call_args[1]
        assert kwargs.get("exc_info") is True
