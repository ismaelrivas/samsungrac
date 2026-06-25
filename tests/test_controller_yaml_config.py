import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from custom_components.climate_ip.controller_yaml_config import (
    YamlConfigLoader,
    clear_yaml_cache,
)

from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_CONN_METHOD,
    CONN_METHOD_RAW,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_TEMP_UNIT,
    CONFIG_DEVICE_POLL,
    DEVICE_TYPE_SAMSUNG_2878,
)
from homeassistant.const import ATTR_TEMPERATURE


class StrictMock(MagicMock):
    def __getattr__(self, name):
        # We only strictly enforce attributes that the controller uses in getattr() calls
        if name in ("_yaml", "device_id", "_config", "config", "hass", "unique_id", "_session", "ip_address", "id", "config_validation_type", "device_class"):
            # MagicMock stores mocked children in _mock_children or __dict__ depending on how they are set
            if name not in self.__dict__ and name not in self._mock_children:
                raise AttributeError(f"StrictMock: Attribute '{name}' not set!")
        return super().__getattr__(name)
from homeassistant.const import ATTR_ENTITY_ID

# ====================================================================================
# FRENTE A: AUTORIDAD PRIMITIVA (Mata los 8 mutantes de __init__)
# ====================================================================================

def test_yaml_config_initial_state():
    """Valida el estado base estricto y la inmunidad del esquema de validación."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader, CONST_CONTROLLER_TYPE
    
    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    loader = YamlConfigLoader(mock_controller)
    
    # Mata mutantes 5, 10, 11, 12, 13, 14, 16 (Asignaciones a None, "", etc.)
    assert loader.name == CONST_CONTROLLER_TYPE
    assert loader.state_getter is None
    assert loader.connection is None
    assert loader.poll is None
    assert loader.is_fully_initialized is False
    assert loader._parsed_yaml_config is None
    assert isinstance(loader.properties_list, list)
    assert loader.properties_list == []
    
    # Mata el Mutante 9 (vol.Optional(None) en lugar de ATTR_ENTITY_ID)
    schema_keys = list(loader.service_schema_map.keys())
    assert len(schema_keys) > 0
    # vol.Optional envuelve el valor en la propiedad .schema
    assert schema_keys[0].schema == ATTR_ENTITY_ID

# ====================================================================================
# FRENTE B: RESILIENCIA A YAML FRAGMENTADO (Mata mutantes de fallback en .get)
# ====================================================================================

async def test_yaml_config_fragmented_payloads():
    """Fuerza la evaluación de los diccionarios por defecto .get(..., {})."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    
    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "target_dev"
    mock_controller.unique_id = "target_dev"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    
    # Inyectamos un YAML que carece de switches, sensors, attributes y operations
    loader._parsed_yaml_config = {
        "target_dev": {
            "device": {
                # Solo pasamos la raíz, forzando a que fallen todos los ac.get()
            }
        }
    }
    
    # Mockeamos create_property para atrapar cualquier intento de creación
    with patch("custom_components.climate_ip.controller_yaml_config.create_property") as mock_create:
        
        # Si un mutante cambia .get(CONFIG_DEVICE_SWITCHES, {}) a None,
        # el bucle for op_key in nodes.keys() explotará con AttributeError
        try:
            await loader.async_finish_initialization()
        except AttributeError:
            pytest.fail("Fallback roto: Mutante provocó AttributeError en iterador.")
            
        # Asertamos que no se intentó crear ninguna propiedad fantasma
        mock_create.assert_not_called()

# ====================================================================================
# FRENTE C: INYECCIÓN DE LA CACHÉ Y RUTAS DE INICIALIZACIÓN
# ====================================================================================

async def test_yaml_config_cache_hit_and_miss():
    """Garantiza que la caché del YAML funciona y se puebla correctamente."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    
    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "test_dev_1"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    
    fake_yaml_data = {"device": {"id": "test_dev_1"}}
    loader._parsed_yaml_config = fake_yaml_data
    
    # 1. Ejecutamos un Cache Miss
    with patch("custom_components.climate_ip.controller_yaml_config.create_property"):
        await loader.async_finish_initialization()
        
    # Asertamos que se guardó en la caché con la clave correcta (Mata mutantes de self._parsed_yaml_cache[dev_id])
    assert "test_dev_1" in loader._parsed_yaml_cache
    assert loader._parsed_yaml_cache["test_dev_1"] == fake_yaml_data
    
    # 2. Corrompemos el YAML base original pero hacemos un Cache Hit
    loader._parsed_yaml_config = {"device": {"ESTADO_CORRUPTO": True}}
    
    # Almacenamos el estado previo de las operaciones
    ops_count = len(loader.operations)
    
    # Volvemos a inicializar
    with patch("custom_components.climate_ip.controller_yaml_config.create_property"):
        await loader.async_finish_initialization()
        
    assert len(loader.operations) == ops_count

# ====================================================================================
# FRENTE D: ASERCIÓN ESTRICTA DE ARGUMENTOS DE CONEXIÓN
# ====================================================================================

async def test_async_initialize_connection_instantiation_args():
    """Valida que los motores de red se instancien con los argumentos exactos requeridos."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader, _YAML_FILE_CACHE
    from unittest.mock import MagicMock, AsyncMock, patch

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.log_prefix = "[Test]"
    
    mock_hass = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock()
    mock_controller.hass = mock_hass
    
    mock_controller._session = "SESSION_INSTANCE"
    mock_controller.ip_address = "192.168.1.100"
    mock_controller._yaml = "/test.yaml"
    # Forzamos la rama `else` del tipo de conexión (generic/REST)
    mock_controller._config = {"device_type": "UNKNOWN_GENERIC"} 

    loader = YamlConfigLoader(mock_controller)
    yaml_data = {
        "device": {"connection": {"type": "test_conn_type"}}
    }
    loader._parsed_yaml_config = yaml_data
    _YAML_FILE_CACHE["/test.yaml"] = yaml_data

    # Creamos un interceptor estricto que no sea un MagicMock permisivo
    class InterceptorConnection:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
        
        @staticmethod
        def match_type(conn_type):
            return conn_type == "test_conn_type"
            
        def load_from_yaml(self, node, state_getter):
            return True

    # Inyectamos nuestra clase de conexión para auditar los argumentos
    with patch("custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS", [InterceptorConnection]):
        await loader.async_initialize()

        # Autopsia de la instanciación (Mata mutantes que omiten hass, config, o cambian argumentos)
        assert loader.connection is not None
        assert loader.connection.args[0] == mock_controller._config
        assert loader.connection.kwargs.get("hass") == mock_hass

# ====================================================================================
# FRENTE E: CORTAFUEGOS DE UNIDADES TERMODINÁMICAS (Fallbacks de Temperatura)
# ====================================================================================

async def test_async_finish_initialization_temperature_fallbacks():
    """Fuerza la ausencia de dependencias HASS para asertar el uso de unidades por defecto."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from custom_components.climate_ip.const import DEFAULT_CONF_TEMP_UNIT
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "temp_device_test"
    # 1. Eliminamos el objeto hass por completo
    if hasattr(mock_controller, "hass"):
        delattr(mock_controller, "hass")
    
    mock_controller._config = {}

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    # Inyectamos un YAML simulado
    loader._parsed_yaml_config = {
        "device": {
            "operations": {
                "target_temp": {"type": "temperature"}
            }
        }
    }

    # Creamos un mock de la propiedad que registre las llamadas de unidades
    mock_prop = StrictMock()
    mock_prop.id = "temperature"
    mock_prop.device_class = "temperature" # Forzamos el chequeo is_temp

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", return_value=mock_prop):
        await loader.async_finish_initialization()

        # Al no haber HASS ni config_entries, el código DEBE usar DEFAULT_CONF_TEMP_UNIT
        # Esto destruye a los mutantes que alteran la asignación inicial de `configured_unit`
        # y `native_target_unit`
        mock_prop.set_hass_unit.assert_called_once_with(DEFAULT_CONF_TEMP_UNIT)
        mock_prop.set_device_unit.assert_called_with(DEFAULT_CONF_TEMP_UNIT)

# ====================================================================================
# FRENTE F: ASERCIÓN ESTRICTA DE FACTORÍAS Y DEDUPLICACIÓN
# ====================================================================================

async def test_async_finish_initialization_strict_factory_args():
    """Valida que create_property recibe sus 5 argumentos intactos y aserta listas únicas."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "test_dev"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    
    loader.connection = "STRICT_CONN"
    loader.state_getter = "STRICT_GETTER"

    # YAML malicioso: Pasamos 'target_op' en operations Y attributes para forzar colisión de IDs
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"target_op": {"type": "A"}},
            "attributes": {"target_op": {"type": "B"}}, # Duplicado intencional
            "sensors": {"target_sensor": {"type": "C"}}
        }
    }

    # Interceptor estricto para simular la creación de la propiedad
    def fake_create(key, node, conn, ctrl, getter):
        prop = MagicMock()
        prop.id = key
        prop.config_validation_type = str
        return prop

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", side_effect=fake_create) as mock_create:
        await loader.async_finish_initialization()

        # 1. ASERCIÓN RÍGIDA DE ARGUMENTOS (Mata Mutantes 32 al 118)
        # Si mutmut cambia `self.state_getter` a `None` en el código de producción, esto explotará
        mock_create.assert_any_call("target_op", {"type": "A"}, "STRICT_CONN", mock_controller, "STRICT_GETTER")
        mock_create.assert_any_call("target_sensor", {"type": "C"}, "STRICT_CONN", mock_controller, "STRICT_GETTER")

        # 2. ASERCIÓN DE DEDUPLICACIÓN DE LISTAS
        # Si mutmut cambia `if op_id not in self.operations_list` por `in`, habrá duplicados o faltarán
        assert loader.operations_list.count("target_op") == 1
        assert "target_sensor" in loader.sensors_list

# ====================================================================================
# FRENTE G: LA CASCADA INFERNAL DE FALLBACKS (.get y getattr)
# ====================================================================================

async def test_async_initialize_fallback_cascades():
    """Fuerza atributos y diccionarios inexistentes para evaluar los fallback a {}."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock
    import pytest

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    
    # Destruimos los atributos de configuración de forma atómica
    if hasattr(mock_controller, "_config"): delattr(mock_controller, "_config")
    if hasattr(mock_controller, "config"): delattr(mock_controller, "config")
    
    loader = YamlConfigLoader(mock_controller)
    
    # YAML vacío en su raíz (Mata mutaciones de `ac = yaml_device.get(CONFIG_DEVICE, {})`)
    loader._parsed_yaml_config = {}

    try:
        # Si un mutante mutó los `{}` por `None`, fallará estrepitosamente aquí
        await loader.async_initialize()
    except AttributeError as e:
        pytest.fail(f"La cascada de fallbacks fue corrompida por un mutante: {e}")

# ====================================================================================
# FRENTE H: DUCK-TYPING VS HERENCIA (El Motor Termodinámico)
# ====================================================================================

async def test_async_finish_initialization_apply_unit_polymorphism():
    """Aserta que apply_unit distingue correctamente mediante isinstance y device_class."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from custom_components.climate_ip.properties import TemperatureOperation
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = {"device": {}}

    # Propiedad 1: Basura (No debe recibir unidades)
    prop_other = StrictMock()
    prop_other.device_class = "power"
    prop_other.id = "power_switch"

    # Propiedad 2: Temperatura por Duck-Typing (Mata mutación de == "temperature")
    prop_duck = StrictMock()
    prop_duck.device_class = "temperature"
    prop_duck.id = "target_temperature"

    # Propiedad 3: Temperatura por Herencia Estricta (Mata mutación de isinstance)
    prop_isinstance = StrictMock(spec=TemperatureOperation)
    prop_isinstance.id = "current_temperature"

    # Inyectamos en el loader saltándonos el parseo YAML
    loader.properties = {"p1": prop_other, "p2": prop_duck, "p3": prop_isinstance}

    with patch("custom_components.climate_ip.controller_yaml_config.create_property"): # Silenciamos llamadas externas
        await loader.async_finish_initialization()

    # Aserciones de precisión (El método apply_unit debió haber iterado sobre loader.properties)
    prop_other.set_hass_unit.assert_not_called()
    prop_duck.set_hass_unit.assert_called_once()
    prop_isinstance.set_hass_unit.assert_called_once()

# ====================================================================================
# FRENTE I: LA TRAMPA DE LA IDENTIDAD ASIMÉTRICA (op_key vs op.id)
# ====================================================================================

async def test_async_finish_initialization_asymmetric_id_fallback():
    """Valida que si op.id existe, NO se use op_key. Mata mutantes de getattr('id')."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    
    # Inyectamos diccionarios con llaves YAML que son DIFERENTES al ID real de la propiedad
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"yaml_op_key": {"type": "A"}},
            "switches": {"yaml_switch_key": {"type": "B"}},
            "attributes": {"yaml_attr_key": {"type": "C"}},
            "sensors": {"yaml_sensor_key": {"type": "D"}} # Sensors usa la variable 'name'
        }
    }
    loader._parsed_yaml_cache = {"": loader._parsed_yaml_config}

    def fake_create(key, node, conn, ctrl, getter):
        prop = MagicMock()
        # El ID interno es diferente a la clave del YAML
        prop.id = f"real_id_for_{key}" 
        return prop

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", side_effect=fake_create):
        await loader.async_finish_initialization()

        # Si mutmut cambia getattr(op, "id", op_key) por getattr(op, "XXidXX", op_key), 
        # las listas registrarán "yaml_op_key" en lugar de "real_id_for_yaml_op_key", y el test explotará.
        assert "real_id_for_yaml_op_key" in loader.operations
        assert "yaml_op_key" not in loader.operations
        
        assert "real_id_for_yaml_switch_key" in loader.operations
        assert "real_id_for_yaml_attr_key" in loader.properties

# ====================================================================================
# FRENTE J: INYECCIÓN PROFUNDA DE CONFIG ENTRIES (Opciones HASS)
# ====================================================================================

async def test_async_finish_initialization_config_entry_options():
    """Fuerza la evaluación de unidades y motores de red mediante entry.options."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from custom_components.climate_ip.const import CONF_CONN_METHOD, CONF_TEMP_NATIVE_CURRENT, CONF_TEMP_NATIVE_TARGET
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    # Inyectamos el entry_id
    mock_controller._config = {"entry_id": "test_entry_777", "device_type": "samsung_8888"}
    
    # Preparamos el Mock de Home Assistant para devolver un ConfigEntry
    mock_entry = MagicMock()
    mock_entry.options = {
        CONF_CONN_METHOD: "raw",
        CONF_TEMP_NATIVE_CURRENT: "Kelvin",
        CONF_TEMP_NATIVE_TARGET: "Fahrenheit"
    }
    mock_controller.hass.config_entries.async_get_entry.return_value = mock_entry

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"temp_op": {"type": "temperature"}}, # Gatilla TemperatureOperation
            "connection": {}
        }
    }
    loader._parsed_yaml_cache = {"": loader._parsed_yaml_config}

    mock_temp_prop = StrictMock()
    mock_temp_prop.device_class = "temperature"
    mock_temp_prop.id = "temperature"

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", return_value=mock_temp_prop):
        await loader.async_finish_initialization()
        
        # 1. Validación de Unidades (Mata mutantes de entry.options.get(CONF_TEMP...))
        mock_temp_prop.set_device_unit.assert_called_with("Fahrenheit")
        
    # Validamos la parte de conexión ejecutando async_initialize
    class DummySamsungConn:
        def __init__(self, *args, **kwargs):
            pass
        @staticmethod
        def match_type(conn_type):
            return conn_type == "samsung_8888_raw"
        def load_from_yaml(self, node, state_getter):
            return True

    with patch("custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS", [DummySamsungConn]):
        # Prevent load_yaml check failing by using absolute path or mocking cache
        mock_controller._yaml = "/test_j.yaml"
        from custom_components.climate_ip.controller_yaml_config import _YAML_FILE_CACHE
        _YAML_FILE_CACHE["/test_j.yaml"] = loader._parsed_yaml_config
        
        await loader.async_initialize()
        # Debe haber extraído "raw" de las opciones del ConfigEntry y creado la conexión
        assert isinstance(loader.connection, DummySamsungConn)

# ====================================================================================
# FRENTE K: CORTOCIRCUITOS Y EARLY EXITS
# ====================================================================================

@pytest.mark.asyncio
async def test_async_finish_initialization_early_exits(mock_controller) -> None:
    """Aniquila la Familia B (Mutante 1) con lógica condicional excluyente."""
    loader = YamlConfigLoader(mock_controller)
    
    # 1. Sale temprano si ya está inicializado (PERO hay config válida)
    loader.is_fully_initialized = True
    loader._parsed_yaml_config = {"device": {"mock": "config"}}
    await loader.async_finish_initialization()
    # Si el mutante 'and' sobrevive, la ejecución continuará y lanzará una excepción
    # porque el yaml_device de este mock no tiene estructura de conexión válida.
    
    # 2. Sale temprano si NO hay config válida (PERO no está inicializado)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = None
    await loader.async_finish_initialization()

    # 3. Comprueba el uso seguro de getattr en device_id mutado a "XXXX"
    del mock_controller.device_id
    loader._parsed_yaml_config = {"device": {}}
    loader._parsed_yaml_cache = {"": {"device": {"name": "cached_device"}}}
    await loader.async_finish_initialization()

@pytest.mark.asyncio
async def test_async_finish_initialization_idempotency(mock_controller) -> None:
    """Aniquila la Familia A (Mutantes 49, 50, 88, 89...) forzando aserciones de duplicados."""
    loader = YamlConfigLoader(mock_controller)
    
    # Le inyectamos dos operaciones, pero el ID final de la segunda va a colisionar
    loader._parsed_yaml_config = {
        "device": {
            "operations": {
                "first_op": {},
                "colliding_op": {}
            }
        }
    }
    loader._parsed_yaml_cache = {"dev_123": loader._parsed_yaml_config}
    loader.connection = MagicMock()
    loader.state_getter = MagicMock()
    
    mock_prop_1 = MagicMock()
    mock_prop_1.id = "shared_id"  # Forzamos a que ambas operaciones terminen con el mismo ID
    mock_prop_2 = MagicMock()
    mock_prop_2.id = "shared_id"
    
    # Usamos side_effect para devolver mocks diferentes en cada llamada a create_property
    with patch("custom_components.climate_ip.controller_yaml_config.create_property", side_effect=[mock_prop_1, mock_prop_2]):
        await loader.async_finish_initialization()
        
        # Aserción letal: La lista solo debe tener un elemento a pesar de haberse procesado dos operaciones
        assert loader.operations_list == ["shared_id"], "Falló la protección contra IDs duplicados."
        # Aserción adicional: El diccionario debió sobreescribirse con la última propiedad evaluada
        assert loader.operations["shared_id"] is mock_prop_2

@pytest.mark.asyncio
async def test_apply_temperature_units_general_property(mock_controller) -> None:
    """Aniquila la Familia C (Mutantes 132, 133) evaluando propiedades no-térmicas con unidad."""
    loader = YamlConfigLoader(mock_controller)
    
    mock_entry = MagicMock()
    mock_entry.options = {CONF_TEMP_NATIVE_CURRENT: "°F", CONF_TEMP_NATIVE_TARGET: "°K"}
    mock_controller.config = {"entry_id": "123"}
    mock_controller.hass.config_entries.async_get_entry.return_value = mock_entry
    mock_controller.hass.config.units.temperature_unit = "°C"
    
    # Creamos un sensor que NO es temperatura, pero tiene método de seteo
    general_sensor = MagicMock()
    general_sensor.device_class = "humidity"
    general_sensor.id = "humidity_sensor"
    # Este mock interceptará las llamadas a set_unit_of_measurement
    
    loader.sensors = {"humidity_sensor": general_sensor}
    loader._parsed_yaml_config = {"device": {}}
    await loader.async_finish_initialization()
    
    # Aserción Letal: Solo debió llamarse al método general, no a los específicos de temperatura
    general_sensor.set_unit_of_measurement.assert_not_called() # No es temperature, no debe llamarse aquí
    
    # Reiniciamos y engañamos al loader diciendo que SÍ es temperatura, 
    # pero solo expone el método general (como un sensor genérico de T)
    del general_sensor.set_hass_unit
    del general_sensor.set_device_unit
    general_sensor.device_class = "temperature"
    
    loader.is_fully_initialized = False
    await loader.async_finish_initialization()
    
    # Aserción Letal: Ahora SÍ debe haber llamado al método general con el configured_unit (Display)
    general_sensor.set_unit_of_measurement.assert_called_once_with("°C")


# ====================================================================================
# FRENTE L: LA PURGA DE LAS 4 DIMENSIONES (Operations, Switches, Attributes, Sensors)
# ====================================================================================

async def test_async_finish_initialization_all_loops_exhaustive():
    """Fuerza la asimetría de IDs y el parseo en las 4 listas del loader para matar bucles espejo."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "test_dev_loops"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    
    # Inyectamos datos en TODAS las categorías simultáneamente
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"yaml_op": {"type": "A"}},
            "switches": {"yaml_sw": {"type": "B"}},
            "attributes": {"yaml_attr": {"type": "C"}},
            "sensors": {"yaml_sen": {"type": "D"}}
        }
    }
    loader._parsed_yaml_cache = {}

    # Generador asimétrico de propiedades
    def fake_create(key, node, conn, ctrl, getter):
        prop = MagicMock()
        prop.id = f"real_{key}" # Asimetría para matar getattr(..., "id", key)
        prop.config_validation_type = str
        return prop

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", side_effect=fake_create):
        await loader.async_finish_initialization()

        # Aserciones implacables de mapeo y deduplicación (Mata mutantes 42-135)
        assert "real_yaml_op" in loader.operations
        assert "real_yaml_sw" in loader.operations
        assert "real_yaml_attr" in loader.properties
        assert "yaml_sen" in loader.sensors
        
        # Validamos que las listas de deduplicación se llenaron (Mata "if op_id not in...")
        assert "real_yaml_sw" in loader.operations_list
        assert "real_yaml_attr" in loader.properties_list
        assert "yaml_sen" in loader.sensors_list

# ====================================================================================
# FRENTE M: LA CASCADA DE CONFIGURACIÓN PRIVADA/PÚBLICA (_config vs config)
# ====================================================================================

async def test_async_initialize_config_fallback_cascade():
    """Fuerza la ejecución del getattr anidado eliminando _config y usando config."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    # 1. Destruimos el atributo privado para obligar a usar el público
    if hasattr(mock_controller, "_config"):
        delattr(mock_controller, "_config")
    
    # 2. Asignamos el atributo público
    mock_controller.config = {
        CONF_DEVICE_TYPE: "samsung_2878"
    }

    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_config = {"device": {}}
    
    mock_controller._yaml = "/test_m.yaml"
    from custom_components.climate_ip.controller_yaml_config import _YAML_FILE_CACHE
    _YAML_FILE_CACHE["/test_m.yaml"] = loader._parsed_yaml_config
    
    await loader.async_initialize()
    
    # Si mutmut alteró getattr(..., "config", {}), el device_type será None 
    # y no entrará en la rama de samsung_2878, por lo que connection_node fallará.
    assert type(loader.connection).__name__ == "ConnectionSamsung2878"

# ====================================================================================
# FRENTE N: EL RESCATE DE ENTRY.DATA (Unidades Térmicas)
# ====================================================================================

async def test_async_finish_initialization_entry_data_fallback():
    """Evalúa la extracción de unidades cuando options está vacío pero data existe."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from custom_components.climate_ip.const import CONF_TEMP_NATIVE_CURRENT, CONF_TEMP_NATIVE_TARGET
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller._config = {"entry_id": "test_entry"}
    
    # Opciones vacías, Data lleno (Mata mutantes 200-208)
    mock_entry = MagicMock()
    mock_entry.options = {} 
    mock_entry.data = {
        CONF_TEMP_NATIVE_CURRENT: "Kelvin",
        CONF_TEMP_NATIVE_TARGET: "Rankine"
    }
    mock_controller.hass.config_entries.async_get_entry.return_value = mock_entry

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = {"device": {"operations": {"t": {"type": "temperature"}}}}
    loader._parsed_yaml_cache = {"": loader._parsed_yaml_config}

    mock_prop = StrictMock()
    mock_prop.device_class = "temperature"
    from homeassistant.const import ATTR_TEMPERATURE
    mock_prop.id = ATTR_TEMPERATURE

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", return_value=mock_prop):
        await loader.async_finish_initialization()
        
        # Debe haber extraído los valores del diccionario .data porque .options estaba vacío
        # Si mutmut cambia .data.get(..., def) a None, esta aserción explotará
        mock_prop.set_device_unit.assert_any_call("Rankine")

# ====================================================================================

# ====================================================================================
# FRENTE O: LA PARADOJA DE LA CACHÉ FANTASMA
# ====================================================================================
async def test_async_initialize_frente_o():
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller._yaml = "/test_o.yaml"
    mock_controller.device_id = "target_dev"
    mock_controller.unique_id = "target_dev"
    mock_controller.hass = MagicMock()
    async def mock_async_add_executor_job(*args, **kwargs):
        return args[0](*args[1:], **kwargs)
    mock_controller.hass.async_add_executor_job = mock_async_add_executor_job

    from custom_components.climate_ip.controller_yaml_config import _YAML_FILE_CACHE
    _YAML_FILE_CACHE["/test_o.yaml"] = {"device": {"connection": {"type": "request"}, "token": "test"}}
    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_config = None

    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"device": {"dummy": "data"}}):
        with patch("custom_components.climate_ip.connection_request.ConnectionRequest.load_from_yaml", return_value=True):
            with patch("custom_components.climate_ip.controller_yaml_config.create_status_getter", return_value=MagicMock()):
                await loader.async_initialize()
                assert loader.connection is not None

# ====================================================================================
# FRENTE D: ASERCIÓN ESTRICTA DE ARGUMENTOS DE CONEXIÓN
# ====================================================================================
async def test_async_initialize_connection_instantiation_args_frente_d():
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.hass = MagicMock()
    mock_controller._session = "SESSION_INSTANCE"
    mock_controller.ip_address = "192.168.1.100"
    mock_controller._yaml = "/test_d.yaml"
    mock_controller.unique_id = "test_d"
    mock_controller._config = {"device_type": "samsung_8888"}
    
    async def mock_async_add_executor_job(*args, **kwargs):
        return args[0](*args[1:], **kwargs)
    mock_controller.hass.async_add_executor_job = mock_async_add_executor_job

    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_cache = {}

    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"device": {"connection": {"type": "aiohttp"}}}):
        with patch("custom_components.climate_ip.controller_yaml_config.create_status_getter", return_value=MagicMock()):
            with patch("custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS") as mock_connections:
                mock_conn_class = MagicMock()
                mock_conn_class.__name__ = "ConnectionAiohttp8888"
                mock_conn_class.match_type.return_value = True
                
                # Mock the instance returned by the class
                mock_conn_instance = MagicMock()
                mock_conn_instance.load_from_yaml.return_value = True
                mock_conn_class.return_value = mock_conn_instance
                
                mock_connections.__iter__.return_value = [mock_conn_class]

                await loader.async_initialize()

                from custom_components.climate_ip.controller_yaml_config import _LOGGER
                # In config_aiohttp, the signature is (merged_config, logger, hass, session, ip)
                merged_config = {"device_type": "samsung_8888", "type": "samsung_8888_aiohttp"}
                mock_conn_class.assert_called_once_with(
                    merged_config, 
                    _LOGGER, 
                    mock_controller.hass,
                    mock_controller._session,
                    mock_controller.ip_address
                )

# ====================================================================================
# FRENTE P: VALIDACIÓN CV.STRING Y CASCADAS SECUNDARIAS
# ====================================================================================
async def test_async_finish_initialization_frente_p():
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch

    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.hass = MagicMock()
    mock_controller.device_id = "dev_p"
    
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    
    # Proveemos operaciones, switches, atributos y sensors para que se aserten todos los bucles
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"op1": {}},
            "switches": {"sw1": {}},
            "attributes": {"attr1": {"unit_of_measurement": "custom_unit"}},
            "sensors": {"sen1": {}}
        }
    }
    loader._parsed_yaml_cache = {}

    def fake_create(key, node, conn, ctrl, getter):
        prop = StrictMock()
        # Claves distintas para deduplicar
        prop.id = f"real_{key}"
        prop.config_validation_type = "cv_boolean"
        
        # Soportamos el getattr de device_class
        prop.device_class = "temperature"
        
        if key == "attr1":
            prop.set_unit_of_measurement = MagicMock()
            
        # Soportamos la asignación de unidades
        prop.set_hass_unit = MagicMock()
        prop.set_device_unit = MagicMock()
        return prop

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", side_effect=fake_create):
        await loader.async_finish_initialization()
        
        # 1. Asertamos cv_boolean (mata mutantes 59-60, 97-99)
        from voluptuous import Optional
        # Las claves en service_schema_map son Optional("real_op1"), etc.
        assert loader.service_schema_map[Optional("real_op1")] == "cv_boolean"
        assert loader.service_schema_map[Optional("real_sw1")] == "cv_boolean"
        
        # 2. Asertamos unit_of_measurement method (mata 132-135)
        attr1_mock = loader.properties["real_attr1"]
        attr1_mock.set_unit_of_measurement.assert_called_once_with("custom_unit")
        
        # 3. Asertamos asimetría en operaciones (mata 49-53, 87-94)
        assert "real_sw1" in loader.operations_list
        assert "real_attr1" in loader.properties_list
        assert "sen1" in loader.sensors_list

# ====================================================================================
# FRENTE R: CASCADAS DE CONFIGURATION HASS UNITS Y ENTRY.OPTIONS
# ====================================================================================
async def test_async_finish_initialization_frente_r():
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch
    from custom_components.climate_ip.const import CONF_TEMP_NATIVE_CURRENT, CONF_TEMP_NATIVE_TARGET

    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.device_id = "dev_r"
    mock_controller._config = {"entry_id": "test_entry"}
    
    mock_hass = MagicMock()
    # Para configured_unit = self.controller.hass.config.units.temperature_unit
    mock_hass.config.units.temperature_unit = "Fahrenheit"
    mock_controller.hass = mock_hass
    
    # Mockeamos entry para que devuelva algo distinto en options vs data
    mock_entry = MagicMock()
    mock_entry.options = {
        CONF_TEMP_NATIVE_CURRENT: "OptionsCurrent",
        CONF_TEMP_NATIVE_TARGET: "OptionsTarget"
    }
    mock_hass.config_entries.async_get_entry.return_value = mock_entry

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"temp_op": {}}
        }
    }
    loader._parsed_yaml_cache = {}

    def fake_create(key, node, conn, ctrl, getter):
        prop = StrictMock()
        prop.id = "real_temp_op"
        prop.device_class = "temperature"
        prop.config_validation_type = "cv_string"
        prop.set_hass_unit = MagicMock()
        prop.set_device_unit = MagicMock()
        return prop

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", side_effect=fake_create):
        await loader.async_finish_initialization()
        
        mock_op = loader.operations["real_temp_op"]
        # Asertamos units_temperature_unit
        mock_op.set_hass_unit.assert_called_once_with("Fahrenheit")
        # Asertamos options de native target
        mock_op.set_device_unit.assert_called_once_with("OptionsCurrent")


@pytest.fixture
def mock_controller():
    """Provides a dummy controller to host the YamlConfigLoader."""
    controller = MagicMock()
    controller.config = {CONF_CONFIG_FILE: "test.yaml"}
    controller.log_prefix = "[Test]"
    controller.device_id = "dev_123"
    controller.unique_id = "uid_123"
    controller.hass = MagicMock()
    return controller

@pytest.mark.asyncio
async def test_async_initialize_sync_fallback(mock_controller) -> None:
    """Aniquila mutantes 34-46 comprobando el fallback a load_yaml síncrono si hass es None."""
    mock_controller.hass = None  # Forzamos la rama síncrona
    mock_controller._yaml = "test.yaml"  # El código lee directamente getattr(controller, "_yaml")
    
    loader = YamlConfigLoader(mock_controller)
    
    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml") as mock_load, \
         patch("custom_components.climate_ip.controller_yaml_config.os.path.join", return_value="dummy/path"):
        
        # El YAML debe tener CONFIG_DEVICE (device) y CONFIG_DEVICE_STATUS (status) para no abortar prematuramente
        mock_load.return_value = {"device": {"connection": {"type": "test"}, "status": {}}}
        
        # Mockeamos create_status_getter para no depender de la clase base real
        with patch("custom_components.climate_ip.controller_yaml_config.create_status_getter", return_value=MagicMock()):
            await loader.async_initialize()
            
            # Aserción Letal: load_yaml debió ser llamado directamente, NO a través de un executor
            mock_load.assert_called_once_with("dummy/path")


@pytest.mark.asyncio
async def test_async_initialize_poll_parsing() -> None:
    """Aniquila mutantes 270-294 bombardeando el parser de CONFIG_DEVICE_POLL con aislamiento total."""
    
    test_cases = [
        ("true", True),
        ("True", True),
        ("false", False),
        ("False", False),
        ("auto", None),
        (None, None),
        ("", None),
    ]

    for poll_str, expected_poll in test_cases:
        # Aislamiento Total Nivel 0: Purgar el caché del módulo
        clear_yaml_cache()

        # Aislamiento Total Nivel 1: Nuevo Controlador Mock
        mock_controller = MagicMock()
        mock_controller.config = {CONF_CONFIG_FILE: "test.yaml"}
        mock_controller.log_prefix = "[Test]"
        mock_controller.device_id = "dev_123"
        mock_controller.unique_id = "uid_123"
        mock_controller._yaml = "test.yaml"
        mock_controller.hass = None
        
        # Aislamiento Total Nivel 2: Nuevo Loader
        loader = YamlConfigLoader(mock_controller)
        loader.poll = None # Forzamos reinicio explícito por si acaso
        
        yaml_data = {"device": {"connection": {"type": "test_type"}, "status": {}}}
        if poll_str is not None:
            yaml_data["device"][CONFIG_DEVICE_POLL] = poll_str
            
        mock_conn_class = MagicMock()
        mock_conn_class.match_type.return_value = True
        mock_conn_class.__name__ = "MockConnection"
        
        mock_conn_instance = MagicMock()
        mock_conn_instance.load_from_yaml.return_value = True
        # EVITAMOS que el mock tenga un atributo 'poll' que pueda interferir mágicamente
        del mock_conn_instance.poll 
        mock_conn_class.return_value = mock_conn_instance
        
        with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value=yaml_data), \
             patch("custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS", [mock_conn_class]), \
             patch("custom_components.climate_ip.controller_yaml_config.create_status_getter", return_value=MagicMock()):
            
            result = await loader.async_initialize()
            
            assert result is True, f"Abortado prematuramente para {poll_str}"
            assert loader.poll is expected_poll, f"Falló el parsing para '{poll_str}'. Esperado {expected_poll}, Obtuvo {loader.poll}"

@pytest.mark.asyncio
async def test_async_finish_initialization_property_creation(mock_controller) -> None:
    """Aniquila mutantes 42-120 asertando la firma estricta de create_property y esquemas lógicos."""
    loader = YamlConfigLoader(mock_controller)
    
    # 1. Configurar el caché y el YAML parseado para pasar la barrera inicial
    loader._parsed_yaml_config = {
        "device": {
            "attributes": {  # Usamos atributos porque ese bloque ejecuta el set_unit_of_measurement
                "test_attr": {"unit_of_measurement": "C"}
            }
        }
    }
    loader._parsed_yaml_cache = {"dev_123": loader._parsed_yaml_config}
    
    loader.connection = MagicMock()
    loader.state_getter = MagicMock()
    
    mock_prop = MagicMock()
    # No asignamos mock_prop.id para forzar getattr(prop, "id", key) en tu código
    del mock_prop.id
    # No asignamos config_validation_type para forzar cv.string
    del mock_prop.config_validation_type
    
    # Parcheamos create_property para inyectar nuestro mock cuando evalúe 'attributes'
    with patch("custom_components.climate_ip.controller_yaml_config.create_property", return_value=mock_prop) as mock_create:
        await loader.async_finish_initialization()
        
        # Aserción Letal: Firma estricta de los argumentos de red y delegación
        mock_create.assert_any_call(
            "test_attr", {"unit_of_measurement": "C"}, loader.connection, loader.controller, loader.state_getter
        )
        
        # Aserción Letal: Fallbacks de configuración
        assert "test_attr" in loader.properties, "Falló el fallback getattr de id"
        mock_prop.set_unit_of_measurement.assert_called_once_with("C")

@pytest.mark.asyncio
async def test_apply_temperature_units_logic(mock_controller) -> None:
    """Aniquila mutantes 167-266 forzando la lógica diferencial de ATTR_TEMPERATURE vs Otros."""
    loader = YamlConfigLoader(mock_controller)
    
    # Configuramos el ConfigEntry mockeado para tener options puras
    mock_entry = MagicMock()
    mock_entry.options = {
        CONF_TEMP_NATIVE_CURRENT: "°F",
        CONF_TEMP_NATIVE_TARGET: "°K"
    }
    mock_controller.config = {"entry_id": "123"}
    mock_controller.hass.config_entries.async_get_entry.return_value = mock_entry
    mock_controller.hass.config.units.temperature_unit = "°C"
    
    # 1. Sensor Genérico (Debe recibir native_current_unit)
    generic_temp = MagicMock()
    generic_temp.device_class = "temperature"
    generic_temp.id = "room_temp"
    
    # 2. Operación ATTR_TEMPERATURE (Debe recibir native_target_unit)
    target_temp = MagicMock()
    target_temp.device_class = "temperature"
    target_temp.id = ATTR_TEMPERATURE
    
    loader.sensors = {"room_temp": generic_temp}
    loader.operations = {ATTR_TEMPERATURE: target_temp}
    
    loader._parsed_yaml_config = {"device": {}} # Para permitir que async_finish ejecute
    await loader.async_finish_initialization()
    
    # Aserciones Letales:
    generic_temp.set_hass_unit.assert_called_once_with("°C")
    generic_temp.set_device_unit.assert_called_once_with("°F")  # Current
    
    target_temp.set_hass_unit.assert_called_once_with("°C")
    target_temp.set_device_unit.assert_called_once_with("°K")   # Target