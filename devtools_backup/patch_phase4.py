import re

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'r') as f:
    content = f.read()

# First, remove all existing test_async_execute_* methods to start fresh
content = re.sub(r'async def test_async_execute_.*?\(.*?\):\n(?:    .*?\n)*', '', content)
# Also remove test_8888_raw_all_placeholders_replaced which tests async_execute
content = re.sub(r'async def test_8888_raw_all_placeholders_replaced.*?\(.*?\):\n(?:    .*?\n)*', '', content)

new_tests = """
async def test_async_execute_embedded_command(connection_config, mock_logger, mock_hass):
    \"\"\"Test execution of embedded commands.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._host = "1.2.3.4"
        
        # 1. Condition True
        mock_emb = MagicMock()
        mock_emb.check_execute_condition.return_value = True
        mock_emb._params = {"url": "/emb_{mac}", "method": "POST", "json": {"auth": "{token}"}, "headers": {"X-Emb": "{dev_id}"}}
        mock_emb._connection_template = None
        mock_emb.async_execute = AsyncMock()
        conn._embedded_command = mock_emb
        
        mock_client = AsyncMock()
        mock_client.request.return_value = ('{"ok": 1}', None)
        
        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client", return_value=mock_client), \\
             patch.object(conn, "async_get_client", return_value=mock_client):
            await conn.async_execute("GET", "/main", {"data": "main"}, None, device_state={"state": "on"})
            
            # Verify embedded was called with replaced placeholders
            mock_emb.check_execute_condition.assert_called_once_with({"state": "on"})
            mock_emb.async_execute.assert_called_once()
            _, kwargs = mock_emb.async_execute.call_args
            assert kwargs["method"] == "POST"
            assert kwargs["url"] == "/emb_" # Since mac is ""
            assert kwargs["data"] == '{"auth": "test_token"}'
            assert kwargs["headers"] == {"X-Emb": "{dev_id}"} # dev_id is None by default
            
        # 2. Condition False
        mock_emb.check_execute_condition.return_value = False
        mock_emb.async_execute.reset_mock()
        with patch.object(conn, "async_get_client", return_value=mock_client):
            await conn.async_execute("GET", "/main", None, None, device_state={"state": "off"})
            mock_emb.async_execute.assert_not_called()
            
        # 3. Exceptions in embedded
        mock_emb.check_execute_condition.return_value = True
        mock_emb.async_execute.side_effect = CannotConnect("emb err")
        with patch.object(conn, "async_get_client", return_value=mock_client):
            with pytest.raises(CannotConnect, match="emb err"):
                await conn.async_execute("GET", "/main", None, None, device_state={"state": "on"})

async def test_async_execute_poll_and_keep_alive(connection_config, mock_logger, mock_hass):
    \"\"\"Test closing of socket when polling with keep_alive False.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        mock_client.request.return_value = ("ok", None)
        
        with patch.object(conn, "async_get_client", return_value=mock_client):
            # _is_poll=True, _keep_alive=False -> Closes connection
            conn._keep_alive = False
            conn._client = AsyncMock()
            client_to_close = conn._client
            await conn.async_execute("GET", "/poll", None, None, _is_poll=True)
            client_to_close.close.assert_called_once()
            assert conn._client is None
            
            # With shared client
            mock_controller = MagicMock()
            mock_controller._shared_raw_client = AsyncMock()
            shared_to_close = mock_controller._shared_raw_client
            conn.set_controller_ref(mock_controller)
            await conn.async_execute("GET", "/poll2", None, None, _is_poll=True)
            shared_to_close.close.assert_called_once()
            assert mock_controller._shared_raw_client is None
            
            # _is_poll=False -> Does NOT close
            conn._client = AsyncMock()
            client_not_to_close = conn._client
            await conn.async_execute("POST", "/write", None, None, _is_poll=False)
            client_not_to_close.close.assert_not_called()
            
            # _keep_alive=True -> Does NOT close
            conn._keep_alive = True
            await conn.async_execute("GET", "/poll3", None, None, _is_poll=True)
            client_not_to_close.close.assert_not_called()

async def test_async_execute_placeholders_and_request(connection_config, mock_logger, mock_hass):
    \"\"\"Test payload formatting and main request execution.\"\"\"
    config = connection_config.copy()
    config[CONF_IP_ADDRESS] = "192.168.1.100"
    config["token"] = "TOKEN123"
    config["mac"] = "AA:BB"
    
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(config, mock_logger, mock_hass, None, None)
        mock_controller = MagicMock()
        mock_controller.device_id = "DEV456"
        mock_controller.token = "CTRL_TOKEN"
        conn.set_controller_ref(mock_controller)
        
        mock_client = AsyncMock()
        mock_client.request.return_value = ('{"ok": 1}', None)
        
        with patch.object(conn, "async_get_client", return_value=mock_client):
            # Execute with placeholders
            headers_in = {"Custom": "{mac}"}
            data_in = {"payload": "{dev_id}", "tok": "{token}"}
            resp, err = await conn.async_execute("PUT", "/path/{token}", data_in, headers_in)
            
            assert resp == '{"ok": 1}'
            assert err is None
            
            # Check what was passed to request
            mock_client.request.assert_called_once()
            c_method, c_path, c_body, c_headers = mock_client.request.call_args[0]
            
            assert c_method == "PUT"
            assert c_path == "/path/CTRL_TOKEN"
            assert c_body == {"payload": "DEV456", "tok": "CTRL_TOKEN"}
            assert c_headers["Custom"] == "AA:BB"
            assert c_headers["Authorization"] == "Bearer CTRL_TOKEN"
            assert c_headers["Content-Type"] == "application/json"

async def test_async_execute_exceptions(connection_config, mock_logger, mock_hass):
    \"\"\"Test that exceptions from request are handled properly.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        
        with patch.object(conn, "async_get_client", return_value=mock_client):
            # ConnectionRefused
            mock_client.request.side_effect = LibConnError("Connection refused")
            with pytest.raises(CannotConnect, match="Connection refused \\(device unreachable or offline\\)"):
                await conn.async_execute("GET", "/x", None, None)
            mock_client.close.assert_called_once()
            
            # Timeout
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Operation timed out")
            with pytest.raises(CannotConnect, match="Connection timed out"):
                await conn.async_execute("GET", "/x", None, None)
                
            # DNS Error
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Name or service not known")
            with pytest.raises(CannotConnect, match="Host not found \\(DNS error\\)"):
                await conn.async_execute("GET", "/x", None, None)
                
            # Other Error
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Other weird error")
            with pytest.raises(CannotConnect, match="Connection error: Other weird error"):
                await conn.async_execute("GET", "/x", None, None)
                
            # Probe suppresses error
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Connection refused")
            resp, err = await conn.async_execute("GET", "/x", None, None, _is_probe=True)
            assert resp is None and err is None
            
            # API Error return
            mock_client.close.reset_mock()
            mock_client.request.side_effect = None
            mock_client.request.return_value = (None, "Some API Error")
            with pytest.raises(CannotConnect, match="API Error: Some API Error"):
                await conn.async_execute("GET", "/x", None, None)

"""

# Append new tests
content += "\n" + new_tests

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'w') as f:
    f.write(content)

print("Phase 4 tests patched!")
