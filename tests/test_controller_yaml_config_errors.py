import pytest
from unittest.mock import MagicMock, patch
from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader, clear_yaml_cache

class NakedObj:
    """Objeto estrictamente vacío para aniquilar duck-typing (hasattr/getattr)."""
    pass

@pytest.fixture
def mock_controller_errors():
    ctrl = MagicMock()
    ctrl.log_prefix = "[Test]"
    ctrl.device_id = "dev_error"
    ctrl.unique_id = "uid_error"
    return ctrl

@pytest.mark.asyncio
async def test_async_initialize_early_exits_bombardment(mock_controller_errors):
    """Mata los 15 mutantes Untested forzando todos los return False lícitos."""
    
    # 1. Fallo: Archivo no especificado (None)
    mock_controller_errors._yaml = None
    loader = YamlConfigLoader(mock_controller_errors)
    assert await loader.async_initialize() is False

    # 2. Fallo: Excepción al leer YAML
    mock_controller_errors._yaml = "test.yaml"
    clear_yaml_cache()
    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", side_effect=Exception("Explosión YAML")):
        assert await loader.async_initialize() is False

    # 3. Fallo: YAML vacío
    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={}):
        assert await loader.async_initialize() is False

    # 4. Fallo: Falta nodo 'device'
    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"wrong_node": {}}):
        assert await loader.async_initialize() is False

    # 5. Fallo: Sin unique_id
    mock_controller_errors.unique_id = None
    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"device": {}}):
        assert await loader.async_initialize() is False
    mock_controller_errors.unique_id = "uid_error" # Restaurar

    # 6. Fallo: Falla al crear la conexión (ConnectionMatch falla o load_from_yaml devuelve False)
    mock_conn_class = MagicMock()
    mock_conn_class.match_type.return_value = True # Coincide tipo...
    mock_conn_instance = MagicMock()
    mock_conn_instance.load_from_yaml.return_value = False # ...pero rechaza la carga
    mock_conn_class.return_value = mock_conn_instance
    
    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"device": {"connection": {"type": "mock"}}}):
        with patch("custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS", [mock_conn_class]):
            assert await loader.async_initialize() is False

    # 7. Fallo: Falta 'status' node en el YAML (create_status_getter devuelve None)
    mock_conn_instance.load_from_yaml.return_value = True # Ahora pasa la conexión
    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"device": {"connection": {}}}):
        with patch("custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS", [mock_conn_class]):
            with patch("custom_components.climate_ip.controller_yaml_config.create_status_getter", return_value=None):
                assert await loader.async_initialize() is False


@pytest.mark.asyncio
async def test_async_finish_initialization_duck_typing_snipers(mock_controller_errors):
    """Mata Mutantes 42, 98, 111 aislando hasattr y getattr con NakedObjs."""
    loader = YamlConfigLoader(mock_controller_errors)
    loader.is_fully_initialized = False
    
    # Preparamos un YAML válido para que corra el bucle
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"op_key_fallback": {}},
            "attributes": {"attr_duck": {}}
        }
    }
    loader._parsed_yaml_cache = {"dev_error": loader._parsed_yaml_config}
    
    # 1. MATA TARGET 42: Objeto sin atributo "id" para forzar fallback a "op_key_fallback"
    naked_op = NakedObj() 
    naked_op.config_validation_type = str
    
    # 2. MATA TARGET 98: TemperatureOperation asimétrica (solo tiene un método en lugar de dos)
    naked_attr = NakedObj()
    naked_attr.id = "attr_duck"
    naked_attr.device_class = "temperature"
    naked_attr.set_hass_unit = MagicMock()
    # INTENCIONALMENTE NO TIENE set_device_unit. 
    # Si mutmut cambia 'and' por 'or', entrará al bloque y lanzará AttributeError.
    
    def fake_create(key, node, conn, ctrl, getter):
        if key == "op_key_fallback": return naked_op
        if key == "attr_duck": return naked_attr
        return None

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", side_effect=fake_create):
        try:
            await loader.async_finish_initialization()
        except AttributeError as e:
            pytest.fail(f"Mutante vivo: Intentó usar un método no validado por hasattr/getattr de manera insegura: {e}")

        # Aserción Letal para Target 42:
        # Como naked_op no tenía "id", DEBIÓ usar "op_key_fallback"
        assert "op_key_fallback" in loader.operations

        # Aserción Letal para Target 98:
        # Al faltarle 'set_device_unit', el 'and' evaluó False, y NO debió ejecutar 'set_hass_unit'
        naked_attr.set_hass_unit.assert_not_called()

@pytest.mark.asyncio
async def test_async_finish_initialization_default_schema(mock_controller_errors):
    """Aniquila el mutante de cv.string por defecto (Target 39)."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    import homeassistant.helpers.config_validation as cv
    import voluptuous as vol
    from unittest.mock import patch

    loader = YamlConfigLoader(mock_controller_errors)
    loader._parsed_yaml_config = {"device": {"operations": {"test_op": {}}}}
    # CLAVE: Usamos 'dev_error' que es el device_id definido en la fixture mock_controller_errors
    loader._parsed_yaml_cache = {"dev_error": loader._parsed_yaml_config}
    
    class NakedProp:
        id = "test_op"
        # INTENCIONALMENTE SIN config_validation_type

    with patch("custom_components.climate_ip.controller_yaml_config.create_property", return_value=NakedProp()):
        await loader.async_finish_initialization()
    
    # Aserción Letal: Debe haber usado el cv.string por defecto
    assert loader.service_schema_map[vol.Optional("test_op")] == cv.string

@pytest.mark.asyncio
async def test_async_finish_initialization_config_fallback(mock_controller_errors):
    """Aniquila el getattr(None, 'config') forzando la ausencia de _config (Target 64)."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock
    
    # Destruimos el atributo privado
    if hasattr(mock_controller_errors, "_config"):
        delattr(mock_controller_errors, "_config")
    
    # Dejamos solo el público
    mock_controller_errors.config = {"entry_id": "fallback_entry_id"}
    mock_controller_errors.hass.config_entries.async_get_entry = MagicMock()
    
    loader = YamlConfigLoader(mock_controller_errors)
    loader._parsed_yaml_config = {"device": {}}
    loader._parsed_yaml_cache = {"dev_error": loader._parsed_yaml_config}
    
    await loader.async_finish_initialization()
    
    # Aserción Letal: Si el fallback falló, async_get_entry no se llamará con este ID
    mock_controller_errors.hass.config_entries.async_get_entry.assert_called_once_with("fallback_entry_id")

@pytest.mark.asyncio
async def test_async_initialize_config_entry_fetch(mock_controller_errors):
    """Aniquila la mutación async_get_entry(None) auditando el parámetro (Target 70)."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE
    from unittest.mock import patch, MagicMock
    
    # Inyección táctica con constantes
    mock_controller_errors._config = {"entry_id": "TARGET_ENTRY_ID", CONF_DEVICE_TYPE: "samsung_8888"}
    mock_controller_errors.config = mock_controller_errors._config # Sincronizamos fallbacks
    mock_controller_errors._yaml = "test.yaml"
    mock_controller_errors.hass.config_entries.async_get_entry = MagicMock()
    
    # [!] FIX: Inyectamos una corrutina real para simular el executor de Home Assistant y evitar el crash
    async def mock_async_add_executor_job(*args, **kwargs):
        return args[0](*args[1:], **kwargs)
    mock_controller_errors.hass.async_add_executor_job = mock_async_add_executor_job
    
    loader = YamlConfigLoader(mock_controller_errors)
    loader._parsed_yaml_cache = {}
    
    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"device": {"connection": {"type": "mock"}, "status": {}}}), \
         patch("custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS"), \
         patch("custom_components.climate_ip.controller_yaml_config.create_status_getter"):
        await loader.async_initialize()
        
    # Aserción Letal: El framework debió ser consultado con el ID exacto, no con None
    mock_controller_errors.hass.config_entries.async_get_entry.assert_called_once_with("TARGET_ENTRY_ID")

@pytest.mark.asyncio
async def test_apply_temperature_units_simple_sensor_fallback(mock_controller_errors):
    """Aniquila el mutante final (Target 83) forzando la rama 'elif' de temperatura."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    
    loader = YamlConfigLoader(mock_controller_errors)
    loader.is_fully_initialized = False
    
    class SimpleTempSensor:
        def __init__(self):
            self.id = "simple_temp_sensor"
            self.device_class = "temperature"
            self.unit_applied = None
        
        # [!] INTENCIONALMENTE OMITIMOS set_hass_unit y set_device_unit
        # Esto forzará al código de producción a fallar el primer 'if' y caer al 'elif'
        
        def set_unit_of_measurement(self, unit):
            self.unit_applied = unit

    # Inyectamos el objeto crudo (NO un MagicMock)
    strict_sensor = SimpleTempSensor()
    loader.sensors = {"simple_temp": strict_sensor}
    
    loader._parsed_yaml_config = {"device": {}}
    loader._parsed_yaml_cache = {mock_controller_errors.device_id: loader._parsed_yaml_config}
    
    # Configuramos la unidad esperada (fallback)
    mock_controller_errors.hass.config.units.temperature_unit = "°F"
    
    await loader.async_finish_initialization()
    
    # Aserción Letal: El motor DEBIÓ caer en el 'elif' y aplicar la unidad
    assert strict_sensor.unit_applied == "°F", "El bloque 'elif hasattr' de fallback de temperatura no se ejecutó."