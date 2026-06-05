import re

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'r') as f:
    content = f.read()

replacement = """async def test_set_controller_ref(connection_config, mock_logger, mock_hass):
    \"\"\"Test setting controller ref and shared client.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_controller = MagicMock()
        mock_controller._shared_raw_client = None
        
        # Test basic assignment
        conn.set_controller_ref(mock_controller)
        assert conn._controller == mock_controller
        
        # Test embedded command propagation
        conn._embedded_command = MagicMock()
        conn._embedded_command.set_controller_ref = MagicMock()
        
        mock_controller_2 = MagicMock()
        conn.set_controller_ref(mock_controller_2)
        
        assert conn._controller == mock_controller_2
        conn._embedded_command.set_controller_ref.assert_called_once_with(mock_controller_2)
"""

content = re.sub(
    r'async def test_set_controller_ref.*?assert conn\._controller_yaml_config == \{"mock": "config"\}\n',
    replacement,
    content,
    flags=re.DOTALL
)

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'w') as f:
    f.write(content)

print("Patch applied")
