with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "r") as f:
    content = f.read()

content = content.replace(
"""    mock_controller.unique_id = "target_dev"
    mock_controller.hass = MagicMock()
    
    loader = YamlConfigLoader(mock_controller)""",
"""    mock_controller.unique_id = "target_dev"
    mock_controller.hass = MagicMock()
    async def mock_async_add_executor_job(*args, **kwargs):
        return {}
    mock_controller.hass.async_add_executor_job = mock_async_add_executor_job
    
    loader = YamlConfigLoader(mock_controller)""")

with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "w") as f:
    f.write(content)

print("Fixed!")
