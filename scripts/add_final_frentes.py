
with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "a") as f:
    f.write("""
# ====================================================================================
# FRENTE O: LA PARADOJA DE LA CACHÉ FANTASMA
# ====================================================================================
async def test_async_initialize_frente_o():
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch, StrictMock

    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller._yaml = "/test_o.yaml"
    mock_controller.device_id = "target_dev"
    mock_controller.unique_id = "target_dev"
    mock_controller.hass = MagicMock()
    async def mock_async_add_executor_job(*args, **kwargs):
        return args[0](*args[1:], **kwargs)
    mock_controller.hass.async_add_executor_job = mock_async_add_executor_job

    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_cache = {"target_dev": {"device": {"connection": "request", "token": "test"}}}
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
    from unittest.mock import MagicMock, patch, StrictMock

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

    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"device": {}}):
        with patch("custom_components.climate_ip.controller_yaml_config.create_status_getter", return_value=MagicMock()):
            with patch("custom_components.climate_ip.connection_aiohttp.ConnectionAiohttp8888") as mock_conn_class:
                mock_conn_class.match_type.return_value = True
                await loader.async_initialize()

                from custom_components.climate_ip.controller_yaml_config import _LOGGER
                mock_conn_class.assert_called_once_with(
                    mock_controller._config, 
                    _LOGGER, 
                    hass=mock_controller.hass
                )

# ====================================================================================
# FRENTE P: VALIDACIÓN CV.STRING Y CASCADAS SECUNDARIAS
# ====================================================================================
async def test_async_finish_initialization_frente_p():
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch, StrictMock

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
        assert "real_sen1" in loader.sensors_list

# ====================================================================================
# FRENTE R: CASCADAS DE CONFIGURATION HASS UNITS Y ENTRY.OPTIONS
# ====================================================================================
async def test_async_finish_initialization_frente_r():
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader
    from unittest.mock import MagicMock, patch, StrictMock
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
        mock_op.set_device_unit.assert_called_once_with("OptionsTarget")

""")
