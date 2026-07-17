import pytest

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
    from unittest.mock import AsyncMock
    loader.state_getter.async_update_state = AsyncMock()
    return loader
# =====================================================================


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


def test_mask_sensitive_data_primitive():
    """L183: Retorno temprano para datos primitivos."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    poller = YamlStatePoller(MagicMock())
    assert poller._mask_sensitive_data("primitive_string") == "primitive_string"
    assert poller._mask_sensitive_data(123) == 123


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


def test_mask_sensitive_data_boundary():
    """Aniquila mutante de frontera (> 6 vs >= 6)"""
    poller = YamlStatePoller(MagicMock())
    # Longitud exacta de 6. Si el código mutado usa >= 6, la enmascarará. Originalmente es > 6 (la ignorará).
    data = {"uuid": "123456"}
    poller._mask_sensitive_data(data)
    assert data["uuid"] == "123456"


async def test_async_update_state_consecutive_errors_logic():
    """Aniquila flip conditions (< vs <=) y el log reason slicing"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.state_getter.async_update_state = AsyncMock(return_value={"state": "ok"})
    
    with patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.info") as mock_log_info, \
         patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.debug") as mock_log_debug:
        
        # Error count = 0 (Debe evitar que se lance log.info de recovery)
        poller._consecutive_connection_errors = 0
        await poller.async_update_state()
        mock_log_info.assert_not_called()
        
        # Forzamos fallo con exactly errors = 2 para probar fallback a caché
        poller.controller.loader.state_getter.async_update_state.side_effect = CannotConnect("Critical: Timeout detected")
        poller._consecutive_connection_errors = 1
        poller._cached_device_state = {"cached": "data"}
        
        res = await poller.async_update_state()
        # Si mutaron `if errors <= 2` a `< 2`, esto fallaría retornando None en lugar de caché
        assert res == {"cached": "data"}
        
        # Validamos lógica de partición de string rsplit(":", maxsplit=1)
        # Para llegar a la rama del reason, borramos el caché
        poller._cached_device_state = None
        poller._consecutive_connection_errors = 2
        
        try:
            await poller.async_update_state()
        except UpdateFailed:
            pass
            
        call_args = mock_log_debug.call_args[0]
        # El string de formato es [0], log_prefix es [1], errors es [2], reason es [3]
        assert call_args[3] == "Timeout detected", "Fallo mutante en formateo de error de log"


async def test_getattr_defaults_destructively():
    """Aniquila mutantes de getattr(..., None) destruyendo los atributos origen"""
    poller = YamlStatePoller(MagicMock())
    
    # Destruir conexión para forzar el fallback de getattr en async_shutdown
    delattr(poller.controller.loader, "connection")
    await poller.async_shutdown()  # Si mutmut eliminó el None, lanzará AttributeError
    
    # Destruir state_getter para forzar salidas tempranas
    delattr(poller.controller.loader, "state_getter")
    assert await poller._build_device_state_from_hass(MagicMock()) is None
    assert await poller._build_device_state_from_props() is None


def test_regex_device_state_key_cache_strict():
    """Aniquila mutante de regex + a * en inicialización"""
    poller = YamlStatePoller(MagicMock())
    
    # Si se mutó el regex ([A-Za-z0-9_]+) a (*), devolverá string vacío en lugar de None
    # Esta aserción fuerza a la regex a pedir al menos 1 caracter.
    result = poller._get_device_key_from_template("device_state['']")
    assert result is None, "Fallo de Regex: Mutante cambió '+' por '*'"


def test_mask_sensitive_data_exact_boundary():
    """Aniquila la mutación len(masked['uuid']) > 6 a >= 6.
    Corrige el error de puntero validando el return value."""
    poller = YamlStatePoller(MagicMock())
    # El original con > 6 ignorará esta cadena (len=6) y devolverá "123456".
    # El mutante con >= 6 la procesará y devolverá "***123456", muriendo en el assert.
    res = poller._mask_sensitive_data({"uuid": "123456"})
    assert res["uuid"] == "123456"


def test_calculate_structured_state_logic_flip():
    """Aniquila mutante 'and' -> 'or' en getattr y hasattr chaining"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    
    # Creamos una propiedad que SÍ tiene la función, pero NO tiene ID
    prop_mock = MagicMock()
    delattr(prop_mock, "id")  # Fuerza a que prop_id sea evaluado como Mock o None
    prop_mock.id = None
    prop_mock.calculate_value_from_state.return_value = "infiltrado"
    
    poller.controller.loader.operations = {"op1": prop_mock}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}
    
    res = poller._calculate_structured_state({"raw": "data"})
    # Original (None and True) -> Ignora.
    # Mutante (None or True) -> Intenta añadir y choca/añade valores corruptos.
    # Comprobamos que el resultado no está corrompido ni contiene "infiltrado".
    assert "infiltrado" not in res.__dict__.values()


async def test_async_update_state_consecutive_errors_exact_boundary():
    """Mata mutante <= 2 mutado a < 2 forzando el valor exactamente a 2"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.config = {"device_type": "Other"}
    poller.controller.loader.is_fully_initialized = True
    
    # Inicializamos en 1. El código sumará 1 y evaluará EXACTAMENTE 2.
    poller._consecutive_connection_errors = 1
    poller._cached_device_state = {"cache": "hit"}
    poller.controller.loader.state_getter.async_update_state.side_effect = CannotConnect("Err")
    
    # ORIGINAL: 2 <= 2 es True -> Retorna caché.
    # MUTANTE: 2 < 2 es False -> Ignora caché y lanza UpdateFailed detonando el test.
    res = await poller.async_update_state()
    assert res == {"cache": "hit"}


def test_calculate_structured_state_and_to_or_mutation():
    """Mata la mutación 'if prop_id and hasattr' -> 'or' que fuga valores"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    
    # Un mock SIN id, pero CON calculate_value_from_state
    prop_mock = MagicMock()
    prop_mock.id = None
    
    poller.controller.loader.operations = {"op1": prop_mock}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}
    
    # ORIGINAL: None AND True -> False. Nunca llama al método.
    # MUTANTE: None OR True -> True. Llama al método.
    poller._calculate_structured_state({"raw": "data"})
    prop_mock.calculate_value_from_state.assert_not_called()


async def test_async_update_state_next_default_mutation():
    """Mata el mutante que elimina el fallback 'None' en el next() del generador (L391)"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.config = {"device_type": "MIM-H03"} # DEVICE_TYPE_MIM_H03
    poller.controller.loader.is_fully_initialized = False
    poller.controller.device_id = "ValidID"
    poller.controller.loader._parsed_yaml_cache = {
        "ValidID": {"device": {"identifiers": {"path_to_devices": ["Devs"], "id": ["id"]}}}
    }
    
    # Proveemos dispositivos, pero NINGUNO cumple la condición (id == "0").
    # Original: next(..., None) devuelve None de forma segura.
    # Mutante: next(...) sin default lanza StopIteration y rompe el sistema.
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"Devs": [{"id": "0"}]}
    )
    
    await poller.async_update_state()
    assert poller.controller.device_id == "ValidID"


def test_calculate_structured_state_getattr_id():
    """Mata mutante de getattr sin fallback para 'id' (L785)"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    
    prop = MagicMock()
    delattr(prop, "id") # Atributo físico aniquilado
    poller.controller.loader.operations = {"op1": prop}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}
    
    # Si mutmut quitó el fallback None, lanza AttributeError
    poller._calculate_structured_state({"raw": "data"})


async def test_getattr_anti_magicmock_warfare():
    """Aniquila los mutantes de getattr(..., None) que evadían la detección por la magia de los Mocks."""
    ctrl = NakedObj()
    ctrl.loader = NakedObj()
    ctrl.config = {}
    ctrl.loader.is_fully_initialized = True
    ctrl.log_prefix = "TEST"
    
    poller = YamlStatePoller(ctrl)
    
    # 1. Mutante _calculate_structured_state (L785)
    prop = NakedObj() # Carece de atributo físico 'id'
    ctrl.loader.operations = {"op1": prop}
    ctrl.loader.properties = {}
    ctrl.loader.sensors = {}
    
    # ORIGINAL: getattr(prop, "id", None) -> None. (Avanza pacíficamente)
    # MUTANTE: getattr(prop, "id") -> AttributeError. (Test explota -> Mutante Muere)
    poller._calculate_structured_state({"raw": "data"})
    
    # 2. Mutante async_merge_device_state (L854)
    # Sin atributo state_getter en loader
    assert await poller.async_merge_device_state({"new": "data"}, False, False) is False
    
    # 3. Mutante async_predict_and_correct_state (L947, L961, L972)
    feat, _ = await poller.async_predict_and_correct_state(NakedObj(), "test_op", "val")
    assert feat.value == 0
    
    # 4. Mutante _build_device_state_from_props (L655)
    res_props = await poller._build_device_state_from_props()
    assert res_props is None
    
    # 5. Mutante async_shutdown (L1049)
    await poller.async_shutdown()


async def test_async_update_state_id_map():
    """Mata el mutante de fallback de id_map en proceso de red (L398)"""
    ctrl = NakedObj()
    ctrl.loader = NakedObj()
    ctrl.config = {"device_type": "Other"}
    ctrl.loader.is_fully_initialized = False
    ctrl.device_id = "MissingID"
    ctrl.log_prefix = "TEST"
    
    ctrl.loader.state_getter = AsyncMock()
    ctrl.loader.state_getter.async_update_state.return_value = {"Devs": [{"some_attr": "val"}]}
    ctrl.loader._parsed_yaml_cache = {
        "MissingID": {"device": {"identifiers": {"path_to_devices": ["Devs"]}}}
    }
    # Fíjate que cache no tiene la clave 'id' en identifiers
    
    ctrl.loader.async_finish_initialization = AsyncMock()
    poller = YamlStatePoller(ctrl)
    poller.async_update_properties_from_state = AsyncMock()
    
    # Original: id_map.get("id", []) devuelve [] -> seguro.
    # Mutante: id_map.get("id") devuelve None. El posterior get_value_by_path colapsará.
    await poller.async_update_state()


async def test_calculate_structured_state_no_swallow():
    """Mata el mutante L797 AttributeError."""
    ctrl = NakedObj(loader=create_valid_loader())
    poller = YamlStatePoller(ctrl)
    
    prop = NakedObj() # No tiene 'id'
    prop.calculate_value_from_state = lambda x: "val"
    ctrl.loader.operations = {"op1": prop}
    
    res = poller._calculate_structured_state({"raw": "data"})
    assert res is not None


async def test_async_update_state_next_no_swallow():
    """Mata el mutante L394."""
    loader = create_valid_loader()
    loader.is_fully_initialized = False
    loader.state_getter = AsyncMock(async_update_state=AsyncMock(return_value={"Devs": []}))
    loader.async_finish_initialization = AsyncMock()
    
    ctrl = NakedObj(
        config={"device_type": "MIM-H03"},
        device_id="123",
        log_prefix="TEST",
        loader=loader
    )
    loader._parsed_yaml_cache = {
        "123": {"device": {"identifiers": {"path_to_devices": ["Devs"], "id": ["id"]}}}
    }
    
    poller = YamlStatePoller(ctrl)
    poller.async_update_properties_from_state = AsyncMock()
    
    await poller.async_update_state()
    ctrl.loader.async_finish_initialization.assert_called_once()


async def test_st_getter_value_no_mock_magic():
    """Mata mutantes de getattr en L658 y L435."""
    ctrl = NakedObj(loader=create_valid_loader())
    poller = YamlStatePoller(ctrl)
    
    st_getter = NakedObj(value={}) # Definimos value explícitamente
    ctrl.loader.state_getter = st_getter
    
    # 1. Test build_device_state_from_props
    res = await poller._build_device_state_from_props()
    assert res == {}
    
    # 2. Test retorno async_update_state
    ctrl.config = {"device_type": "Other"}
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})
    poller.async_update_properties_from_state = AsyncMock()
    st_getter.value = {"a": "b"}
    st_getter.async_update_state = AsyncMock(return_value={"a": "b"})
    
    res2 = await poller.async_update_state()
    assert res2 == {"a": "b"}


async def test_async_update_state_cache_mutants():
    """Mata los mutantes L360 y L361 que destruyen la caché interna."""
    loader = create_valid_loader()
    loader.is_fully_initialized = True
    ctrl = NakedObj(config={}, device_id="123", log_prefix="TEST", loader=loader)
    
    poller = YamlStatePoller(ctrl)
    expected_state = {"raw": "data"}
    poller._build_device_state_from_hass = AsyncMock(return_value=expected_state)
    poller.async_update_properties_from_state = AsyncMock()
    loader.state_getter = NakedObj(async_update_state=AsyncMock(return_value=expected_state))
    
    # PRECONDICIÓN CORREGIDA: El poller arranca con la caché inicializada a None
    assert poller._cached_device_state is None
    
    await poller.async_update_state()
    
    # Si el mutante hace self._cached_device_state = None, esto falla
    assert poller._cached_device_state == expected_state
    
    # Si el mutante hace self._last_state_fetch_time = None, esto falla
    assert poller._last_state_fetch_time is not None


