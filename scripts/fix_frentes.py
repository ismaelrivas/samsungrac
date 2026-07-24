with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "r") as f:
    content = f.read()

# Fix FRENTE O
content = content.replace(
    'with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={}):',
    'with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={"dummy": "data"}):'
)

# Fix FRENTE D
# 1. Add mock_async_add_executor_job
content = content.replace(
    '''    mock_controller._yaml = "/test_d.yaml"''',
    '''    mock_controller._yaml = "/test_d.yaml"
    async def mock_async_add_executor_job(*args, **kwargs):
        return {}
    mock_controller.hass.async_add_executor_job = mock_async_add_executor_job'''
)

# 2. Fix the assert_called_once_with to use the module _LOGGER
content = content.replace(
    '''                    mock_conn_class.assert_called_once_with(
                        mock_controller._config,
                        loader._logger,
                        hass=mock_controller.hass
                    )''',
    '''                    from custom_components.climate_ip.controller_yaml_config import _LOGGER
                    mock_conn_class.assert_called_once_with(
                        mock_controller._config,
                        _LOGGER,
                        hass=mock_controller.hass
                    )'''
)

with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "w") as f:
    f.write(content)

print("Fixed FRENTE O and D!")
