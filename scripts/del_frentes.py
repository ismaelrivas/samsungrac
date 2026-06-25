with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "r") as f:
    content = f.read()

index = content.find("# FRENTE O:")
if index != -1:
    content = content[:index]

with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "w") as f:
    f.write(content)
