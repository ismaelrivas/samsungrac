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
