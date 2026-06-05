import re

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'r') as f:
    content = f.read()

# Patch test_initialization
init_replacement = """async def test_initialization(connection_config, mock_logger, mock_hass):
    \"\"\"Test connection initialization.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn._config is connection_config
        assert conn._logger is mock_logger
        assert conn._hass is mock_hass
        assert conn._host == "192.168.1.100"
        assert conn._cert.endswith("cert.pem")
        assert conn._keep_alive is True
        assert conn._params == {}
        assert conn._controller is None
        assert conn._connection_template is None
        assert conn._embedded_command is None
        assert conn._client is None
"""
content = re.sub(
    r'async def test_initialization.*?assert conn\._cert\.endswith\("cert\.pem"\)\n',
    init_replacement,
    content,
    flags=re.DOTALL
)

# Patch test_set_controller_ref
set_ctrl_replacement = """async def test_set_controller_ref(connection_config, mock_logger, mock_hass):
    \"\"\"Test setting controller ref and shared client.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_controller = MagicMock()
        mock_controller._shared_raw_client = None
        conn.set_controller_ref(mock_controller, {"mock": "config"})
        assert conn._controller == mock_controller
        assert conn._controller_yaml_config == {"mock": "config"}
"""
content = re.sub(
    r'async def test_set_controller_ref.*?assert conn\._controller == mock_controller\n',
    set_ctrl_replacement,
    content,
    flags=re.DOTALL
)

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'w') as f:
    f.write(content)

print("Tests patched!")
