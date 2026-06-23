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
        
    # No debería haber explotado y el estado debe mantenerse consistente usando la caché
    assert len(loader.operations) == ops_count
