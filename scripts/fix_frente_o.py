with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "r") as f:
    content = f.read()

# Fix indentation around line 699
content = content.replace(
"""with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={}):
        with patch("custom_components.climate_ip.connection_request.ConnectionRequest.load_from_yaml", return_value=True):
        with patch("custom_components.climate_ip.controller_yaml_config.create_status_getter", return_value=MagicMock()):""",
"""    with patch("custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={}):
        with patch("custom_components.climate_ip.connection_request.ConnectionRequest.load_from_yaml", return_value=True):
            with patch("custom_components.climate_ip.controller_yaml_config.create_status_getter", return_value=MagicMock()):""")

with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py", "w") as f:
    f.write(content)

print("Fixed!")
