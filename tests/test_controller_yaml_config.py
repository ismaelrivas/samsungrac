import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from homeassistant.const import ATTR_ENTITY_ID

# ====================================================================================
# FRENTE A: AUTORIDAD PRIMITIVA (Mata los 8 mutantes de __init__)
# ====================================================================================

def test_yaml_config_initial_state():
    """Valida el estado base estricto y la inmunidad del esquema de validación."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader, CONST_CONTROLLER_TYPE
    
    mock_controller = MagicMock()
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
    
    mock_controller = MagicMock()
    mock_controller.device_id = "target_dev"
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
    
    mock_controller = MagicMock()
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

    mock_controller = MagicMock()
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

    mock_controller = MagicMock()
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
    mock_prop = MagicMock()
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

    mock_controller = MagicMock()
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

    mock_controller = MagicMock()
    
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

    mock_controller = MagicMock()
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = {"device": {}}

    # Propiedad 1: Basura (No debe recibir unidades)
    prop_other = MagicMock()
    prop_other.device_class = "power"
    prop_other.id = "power_switch"

    # Propiedad 2: Temperatura por Duck-Typing (Mata mutación de == "temperature")
    prop_duck = MagicMock()
    prop_duck.device_class = "temperature"
    prop_duck.id = "target_temperature"

    # Propiedad 3: Temperatura por Herencia Estricta (Mata mutación de isinstance)
    prop_isinstance = MagicMock(spec=TemperatureOperation)
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

    mock_controller = MagicMock()
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

    mock_controller = MagicMock()
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

    mock_temp_prop = MagicMock()
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

async def test_async_finish_initialization_early_exits():
    """Aserción dura de los condicionales de salida prematura (Mata el mutante de 'or/and')."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock

    loader = YamlConfigLoader(MagicMock())
    
    # 1. Ya inicializado (debe abortar sin tocar nada)
    loader.is_fully_initialized = True
    loader._parsed_yaml_config = {"device": {"operations": {"a": "b"}}}
    await loader.async_finish_initialization()
    assert len(loader.operations) == 0 # Abortó
    
    # 2. Sin YAML parseado (debe abortar)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = None
    await loader.async_finish_initialization()
    assert len(loader.operations) == 0 # Abortó
