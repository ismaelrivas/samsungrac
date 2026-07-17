import pytest


import time
import inspect

from unittest.mock import MagicMock, AsyncMock, patch
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.const import STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.const import DEVICE_TYPE_MIM_H03, DEVICE_TYPE_SAMSUNG_2878
from custom_components.climate_ip.exceptions import CannotConnect, AuthError
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.update_coordinator import UpdateFailed


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
        if not hasattr(self, 'config'):
            self.config = {}
        if not hasattr(self, 'log_prefix'):
            self.log_prefix = "TEST"
        if not hasattr(self, 'ip_address'):
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
# =====================================================================
# OPERACIÓN "CERO ABSOLUTO" - SNIPER TESTS PARA ASYNC_UPDATE_PROPERTIES
# =====================================================================

async def test_update_properties_strict_subdevice_routing_and_logs():
    """
    Sniper 1: Aniquila los 10+ mutantes atrincherados en los fallbacks de los diccionarios, 
    id_map, getattr("XXXX"), getattr("",) y getattr(prop, "name", "unknown").
    """
    mock_controller = DummyController(log_prefix="TEST")
    # Forzamos la desaparición de device_id para activar getattr(..., "XXXX") y getattr(..., "")
    if hasattr(mock_controller, "device_id"):
        delattr(mock_controller, "device_id")
        
    loader = create_valid_loader()
    mock_controller.loader = loader
    
    # 1. Configurar la caché para que el ruteo dependa exactamente de los fallbacks
    loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["List"],
                    "id": ["dev_id"]
                }
            }
        }
    }
    
    # 2. Estado de red: el dispositivo correcto tiene "dev_id" vacío
    full_state = {
        "List": [
            {"dev_id": "other", "value": "bad"},
            {"dev_id": "", "value": "target_hit"},  # str(getattr(..., "device_id", "")) evaluará a ""
        ],
        "value": "missed_root"
    }
    
    # 3. Propiedad purgada que además forzará una excepción
    prop = NakedObj(id="test_prop", value="old")
    # Si borramos el nombre, activamos getattr(prop, "name", "unknown")
    if hasattr(prop, "name"):
        delattr(prop, "name")
        
    prop.async_update_state = AsyncMock(side_effect=Exception("Boom"))
    loader.properties = {"test_prop": prop}
    
    poller = YamlStatePoller(mock_controller)
    
    with patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.error") as mock_err:
        await poller.async_update_properties_from_state(full_state)
        
        # ASERCIÓN 1: El sub-device fue ruteado a la perfección a pesar de los getattr vacíos
        # Además validamos que debug false (el 2do argumento) sobrevivió al getattr(..., "debug", False)
        prop.async_update_state.assert_awaited_once_with({"dev_id": "", "value": "target_hit"}, False)
        
        # ASERCIÓN 2: La excepción se disparó y el logger usó el fallback "unknown"
        mock_err.assert_called_once()
        log_args = mock_err.call_args[0]
        assert "unknown" in log_args, "Mutante detectado: El fallback de getattr(name) fue alterado."


async def test_update_properties_dirty_check_logic_mutants():
    """
    Sniper 2: Destruye las mutaciones booleanas (and/or), alteraciones de is_prediction, 
    force_update y el fallback de _last_device_state en el Dirty Check.
    """
    mock_controller = DummyController(log_prefix="TEST")
    loader = create_valid_loader()
    mock_controller.loader = loader
    poller = YamlStatePoller(mock_controller)
    poller._rebuild_attributes = MagicMock()
    
    state_a = {"val": 1}
    state_b = {"val": 2}
    
    # Setup inicial
    poller._last_device_state = state_a.copy()
    
    # CASO 1: Cortocircuito perfecto (devuelve {} y no llama a atributos)
    res1 = await poller.async_update_properties_from_state(state_a.copy())
    assert res1 == {}
    poller._rebuild_attributes.assert_not_called()
    
    # CASO 2: Mutación 'force_update'
    await poller.async_update_properties_from_state(state_a.copy(), force_update=True)
    poller._rebuild_attributes.assert_called_once()
    
    # CASO 3: Mutación 'is_prediction'
    poller._rebuild_attributes.reset_mock()
    await poller.async_update_properties_from_state(state_a.copy(), is_prediction=True)
    poller._rebuild_attributes.assert_called_once()

    # CASO 4: Mutación '_last_device_state'
    poller._rebuild_attributes.reset_mock()
    await poller.async_update_properties_from_state(state_b.copy())
    poller._rebuild_attributes.assert_called_once()
    
    # CASO 5: Mutación 'pending_updates'
    poller._last_device_state = state_a.copy()
    poller._pending_updates = {"fake": ("val", time.time())}
    poller._rebuild_attributes.reset_mock()
    await poller.async_update_properties_from_state(state_a.copy())
    poller._rebuild_attributes.assert_called_once()


async def test_update_properties_operation_validation_fallbacks():
    """
    Sniper 3: Limpia los fallbacks de _value, values, feature_flag, id "unknown"
    y las inversiones condicionales (!= STATE_UNKNOWN) en la validación final.
    """
    mock_controller = DummyController(log_prefix="TEST")
    loader = create_valid_loader()
    mock_controller.loader = loader
    poller = YamlStatePoller(mock_controller)
    
    # OP 1: Forzamos el uso exclusivo de atributos ocultos (_) y disparamos la autocorrección.
    # Eliminamos el 'id' para forzar corrections["unknown"].
    op1 = NakedObj(_value="invalid_mode", values=["auto", "cool"], _feature_flag=ClimateEntityFeature.FAN_MODE)
    op1.is_valid = MagicMock(return_value=True)
    
    loader.operations = {"op1": op1}
    full_state = {"a": 1}
    
    corrections = await poller.async_update_properties_from_state(full_state, force_update=True)
    
    # El valor "invalid_mode" no está en values, por lo que asume values[0] -> "auto"
    assert corrections == {"unknown": "auto"}, "Mutante de getattr('id', 'unknown') sobrevivió."
    assert op1._value == "auto"
    assert poller.fan_modes_list_changed_pending_flicker is True, "Mutante de _feature_flag sobrevivió."
    
    # OP 2: Prevención condicional (STATE_UNKNOWN)
    poller.fan_modes_list_changed_pending_flicker = False
    op2 = NakedObj(value=STATE_UNKNOWN, values=["auto"])
    op2.is_valid = MagicMock(return_value=True)
    loader.operations = {"op2": op2}
    
    corrections2 = await poller.async_update_properties_from_state(full_state, force_update=True)
    
    # Al ser STATE_UNKNOWN, no debe intentar auto-corregir
    assert corrections2 == {}, "Mutante en op_value != STATE_UNKNOWN sobrevivió."
    assert op2.value == STATE_UNKNOWN



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


def test_get_hass_attr_for_op_id_unmocked():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    assert poller._get_hass_attr_for_op_id("hvac") == "hvac_mode"
    assert poller._get_hass_attr_for_op_id("unknown_op") == "unknown_op"


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
    assert mock_controller.loader.state_getter.value == expected_state
    
    # Check deepcopy: modifying the new state should not affect the original state
    mock_controller.loader.state_getter.value["Untouched"]["nested"] = "Hacked"
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


async def test_async_update_properties_from_state_strict_logger():
    """Aniquila mutantes de exc_info=False, timewindow y param debug fallbacks"""
    poller = YamlStatePoller(MagicMock())
    
    # Provocamos un fallo en la lógica de selección de sub-dispositivo
    poller.controller.loader._parsed_yaml_cache = MagicMock()
    poller.controller.loader._parsed_yaml_cache.get.side_effect = Exception("Inyección balística")
    
    with patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.error") as mock_log:
        await poller.async_update_properties_from_state({"Devices": [{}]})
        
        # Aserción destructiva: validamos que el logger se llamó con exc_info=True obligatoriamente.
        # Mutmut sobrevive si se cambia a False porque ignoramos la validación en tests viejos.
        assert mock_log.call_args.kwargs.get("exc_info") is True
    
    # Test ventana de tiempo (15.0 segundos)
    # Si la condición es <= 15.0, procesará el evento. Si es < 15.0 lo ignorará.
    op_mock = MagicMock(id="test_op")
    op_mock.async_update_state = AsyncMock()
    poller._pending_updates = {"test_op": ("val", time.time() - 15.0)}
    poller.controller.loader.properties = {"test_op": op_mock}
    poller._get_cached_device_key_from_prop = MagicMock(return_value=None)
    
    # Para la llamada interna a prop.async_update_state, nos aseguramos de que controle debug flag explícito
    poller.controller.debug = False
    
    await poller.async_update_properties_from_state({"Devices": [{}]})
    
    # Al ser 15.0 exactos, DEBE llamar a async_update_state si la lógica es estricta (< 15.0).
    # Porque < 15.0 es False, no hace continue, y se procesa.
    op_mock.async_update_state.assert_called_once()


async def test_evict_invalidated_updates_break_mutation():
    """Aniquila la sustitución de continue por break en bucles for"""
    poller = YamlStatePoller(MagicMock())
    
    poller.controller.loader.operations = {"op1": None}
    prop_mock = MagicMock()
    poller.controller.loader.properties = {"prop2": prop_mock}
    
    # Elemento inválido primero, luego uno válido.
    poller._pending_updates = {"op1": ("val", 0), "prop2": ("val", 0)}
    poller._get_cached_device_key_from_prop = MagicMock(return_value="ValidKey")
    
    # Forzamos la invalidación del segundo
    push_data = {"ValidKey": "trigger"}
    poller._evict_invalidated_pending_updates(push_data)
    
    # Si el mutante cambió el continue por un break (al evaluar if not prop:), prop2 no se procesará
    assert "prop2" not in poller._pending_updates, "El bucle sufrió un break prematuro"


def test_evict_invalidated_pending_updates_strict_logic():
    """Aniquila 'or' mutado y 'break' prematuro en los bucles de caché"""
    poller = YamlStatePoller(MagicMock())
    
    prop1 = MagicMock()
    prop2 = MagicMock()
    poller.controller.loader.operations = {"op1": prop1, "op2": prop2}
    poller.controller.loader.properties = {}
    
    # 2 operaciones pendientes
    poller._pending_updates = {"op1": ("v", 0), "op2": ("v", 0)}
    
    # Prop1 no está en push_data, Prop2 sí lo está.
    poller._get_cached_device_key_from_prop = MagicMock(side_effect=["Key1", "Key2"])
    
    push_data = {"Key2": "updated"}  # SOLO op2 debe ser evictado
    
    poller._evict_invalidated_pending_updates(push_data)
    
    # Si mutmut puso 'or' en `if device_key or device_key in push...`, op1 se borra (Falso positivo)
    assert "op1" in poller._pending_updates, "Fallo lógico: Mutación 'or' evaluó true prematuramente"
    # Si mutmut puso 'break', el bucle muere en op1 y op2 nunca se evalúa
    assert "op2" not in poller._pending_updates, "Fallo estructural: Mutación 'break' rompió el loop"


async def test_async_merge_device_state_strict_args():
    """Aniquila mutaciones booleanas explícitas de argumentos (force_update=False)"""
    poller = YamlStatePoller(MagicMock())
    
    st_getter = MagicMock()
    st_getter.value = {"base": "data"}
    poller.controller.loader.state_getter = st_getter
    poller.controller.get_current_state_callback = MagicMock(return_value="mock_hass_state")
    
    # Usamos patch directamente en lugar de mocker para evadir problemas de plugins
    with patch.object(poller, "async_update_properties_from_state", new_callable=AsyncMock) as mock_update_props:
        res = await poller.async_merge_device_state({"new": "data"}, False, False)
        assert res is True
        
        # Aserción destructiva: validamos todos los kwargs. Si force_update se mutó a False, falla.
        mock_update_props.assert_called_once_with(
            {"base": "data", "new": "data"},
            force_update=True,
            current_hass_state="mock_hass_state"
        )


async def test_update_properties_from_state_break_mutation():
    """Aniquila sustitución de continue por break en loop de validación.
    El loop en línea 552 itera operations: si is_valid() es False -> continue.
    Si mutmut cambia continue por break, op_valid jamás será evaluada."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader._parsed_yaml_cache = {}
    
    # Operación 1: Inválida (debería disparar continue en línea 554)
    op_invalid = MagicMock()
    op_invalid.is_valid.return_value = False
    op_invalid.async_update_state = AsyncMock()
    op_invalid.id = "invalid_op"
    
    # Operación 2: Válida, pero con valor FUERA de su lista -> fuerza corrección
    op_valid = MagicMock()
    op_valid.is_valid.return_value = True
    op_valid.async_update_state = AsyncMock()
    op_valid.id = "target_op"
    op_valid.value = "Turbo"      # valor actual
    op_valid.values = ["Low", "High"]  # "Turbo" NOT IN -> genera corrección
    
    poller.controller.loader.operations = {"op1": op_invalid, "op2": op_valid}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}
    poller._pending_updates = {}
    poller._rebuild_attributes = MagicMock()
    
    corrections = await poller.async_update_properties_from_state({"Devices": [{}]})
    
    # Si 'continue' se mutó a 'break', op_valid jamás será evaluada -> corrections vacío
    assert "target_op" in corrections
    assert corrections["target_op"] == "Low"  # op_values[0]


async def test_async_update_properties_from_state_attribute_crashes():
    """Mata los mutantes de getattr sin default mediante borrado físico de atributos."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    
    # Inyectamos un objeto que NO tiene el atributo. 
    # El código original tiene getattr(..., None). El mutante lo elimina.
    # Si el mutante sobrevive, lanzará AttributeError.
    obj = MagicMock()
    delattr(obj, "_parsed_yaml_cache") 
    poller.controller.loader._parsed_yaml_cache = None # Necesario para evitar otros efectos
    
    # Si mutmut eliminó el None, esta línea disparará el error.
    await poller.async_update_properties_from_state({"Devices": []})


@patch("time.time", return_value=100.0)
async def test_update_properties_time_exact_boundary(mock_time):
    """Mata mutante < 15.0 mutado a <= 15.0 fijando el tiempo EXACTAMENTE en el borde"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    
    # Marca de tiempo en 85.0. Diferencia exacta: 15.0.
    poller._pending_updates = {"test_op": ("pending_val", 85.0)}
    
    op = MagicMock(id="test_op")
    op.convert_hass_to_dev = MagicMock()
    poller.controller.loader.operations = {"test_op": op}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}
    poller._get_cached_device_key_from_prop = MagicMock(return_value="Key")
    
    # ORIGINAL: 15.0 < 15.0 es False -> NO procesa.
    # MUTANTE: 15.0 <= 15.0 es True -> Procesa y llamaría a convert_hass_to_dev.
    await poller.async_update_properties_from_state({"Key": "old_val"}, is_prediction=False)
    op.convert_hass_to_dev.assert_not_called()


def test_evict_invalidated_pending_updates_loop_mutations():
    """Mata mutantes de 'break' (en lugar de continue) y el 'or' defectuoso."""
    poller = YamlStatePoller(MagicMock())
    
    op1 = MagicMock(id="prop1")
    op2 = MagicMock(id="prop2")
    op_hvac = MagicMock(id="hvac_mode")
    poller.controller.loader.operations = {"prop1": op1, "prop2": op2, "hvac_mode": op_hvac}
    poller.controller.loader.properties = {}
    
    # Definimos las claves para forzar flujos específicos
    def mock_get_key(prop):
        return {"prop1": "Key1", "prop2": "Key2", "hvac_mode": "KeyHVAC"}.get(prop.id)
    poller._get_cached_device_key_from_prop = MagicMock(side_effect=mock_get_key)
    
    # Inyectamos 3 elementos en la cola
    poller._pending_updates = {
        "prop1": ("v", 0),      # Será evictado por Key1
        "prop2": ("v", 0),      # Será evictado por Key2. (Si op1 hizo 'break', op2 SOBREVIVE erróneamente)
        "hvac_mode": ("v", 0)   # Power es On. Original: NO lo evicta. Mutante 'or': SÍ lo evicta.
    }
    
    push_data = {"Key1": "data", "Key2": "data", "AC_FUN_POWER": "On"}
    poller._evict_invalidated_pending_updates(push_data)
    
    # 1. Matar 'break' prematuro: Ambos prop1 y prop2 deben haber sido procesados.
    assert "prop2" not in poller._pending_updates, "Fallo: Mutante 'break' detuvo el bucle antes de prop2"
    
    # 2. Matar 'or' en chequeo de AC_FUN_POWER == 'Off' AND prop_id in (...)
    assert "hvac_mode" in poller._pending_updates, "Fallo: Mutante 'or' evaluó true ignorando el estado de Power"


async def test_async_merge_device_state_missing_getter():
    """Mata mutante de getattr sin fallback para 'state_getter' (L854)"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.get_current_state_callback = MagicMock(return_value=None)
    
    # DESTRUCCIÓN FÍSICA
    delattr(poller.controller.loader, "state_getter")
    
    # Si mutmut quitó el None, lanza AttributeError
    res = await poller.async_merge_device_state({"new": "data"}, False, False)
    assert res is False


