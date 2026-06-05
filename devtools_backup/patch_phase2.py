import re

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'r') as f:
    content = f.read()

# Patch test_create_updated
create_updated_replacement = """async def test_create_updated(connection_config, mock_logger, mock_hass):
    \"\"\"Test create_updated method.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._params = {"test": "param"}
        conn._keep_alive = True

        # Test with empty node
        new_conn = conn.create_updated({})
        assert isinstance(new_conn, ConnectionRaw8888)
        assert new_conn is not conn
        assert new_conn._params == {"test": "param"}
        assert new_conn._keep_alive is True

        # Test with None
        new_conn_none = conn.create_updated(None)
        assert isinstance(new_conn_none, ConnectionRaw8888)
        assert new_conn_none is not conn

        # pylint: disable=import-outside-toplevel,duplicate-code
        # Test with params and keep_alive
        yaml_node = {"params": {"new": "value"}, "keep_alive": False}
        new_conn_params = conn.create_updated(yaml_node)
        assert new_conn_params._params == {"test": "param", "new": "value"}
        assert new_conn_params._keep_alive is False

        # Test with connection_template
        yaml_node_tmpl = {"connection_template": "{{ test }}"}
        new_conn_tmpl = conn.create_updated(yaml_node_tmpl)
        assert new_conn_tmpl._connection_template is not None
        assert new_conn_tmpl._connection_template.hass == mock_hass

        # Test with embedded command and condition template
        yaml_node_embedded = {
            "connection": {
                "condition_template": "{{ condition }}"
            }
        }
        new_conn_embedded = conn.create_updated(yaml_node_embedded)
        assert new_conn_embedded._embedded_command is not None
        assert new_conn_embedded._embedded_command.condition_template is not None
        assert new_conn_embedded._embedded_command.condition_template.hass == mock_hass
        # pylint: enable=duplicate-code
"""

content = re.sub(
    r'async def test_create_updated.*?\s+# pylint: enable=duplicate-code\n',
    create_updated_replacement,
    content,
    flags=re.DOTALL
)

# Patch test_get_diagnostics
get_diagnostics_replacement = """async def test_get_diagnostics(connection_config, mock_logger, mock_hass):
    \"\"\"Test get_diagnostics.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        
        # Test defaults
        diag = conn.get_diagnostics()
        assert diag == {
            "is_connected": False,
            "reconnect_retries": 0,
            "engine": "raw_socket"
        }
        
        # Test custom values
        conn._is_connected = True
        conn._reconnect_retries = 5
        diag_custom = conn.get_diagnostics()
        assert diag_custom == {
            "is_connected": True,
            "reconnect_retries": 5,
            "engine": "raw_socket"
        }
"""

content = re.sub(
    r'async def test_get_diagnostics.*?assert "is_connected" in diag\n',
    get_diagnostics_replacement,
    content,
    flags=re.DOTALL
)

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'w') as f:
    f.write(content)

print("Phase 2 Patched!")
