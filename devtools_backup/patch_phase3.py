import re

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'r') as f:
    content = f.read()

# Let's just remove the second test_async_get_client_port_parsing
content = re.sub(
    r'async def test_async_get_client_port_parsing\(connection_config, mock_logger, mock_hass\):\s+"""Test dynamic port parsing in async_get_client."""\s+.*?assert client4\.port == 80\n\n',
    '',
    content,
    flags=re.DOTALL
)

# Replace the first test_async_get_client_port_parsing and add comprehensive ones
async_get_client_replacement = """
async def test_async_get_client(connection_config, mock_logger, mock_hass):
    \"\"\"Test all paths of async_get_client.\"\"\"
    with patch("os.path.exists", return_value=True):
        # 1. Standalone client (no controller)
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._params = {"url": "https://test.com/path"}
        
        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client") as mock_client_cls:
            client = await conn.async_get_client()
            mock_client_cls.assert_called_once_with("192.168.1.100", 443, "cert.pem", log_prefix=conn.log_prefix)
            assert conn._client is not None
            
            # Requesting again should return cached client
            mock_client_cls.reset_mock()
            client_cached = await conn.async_get_client()
            assert client_cached == client
            mock_client_cls.assert_not_called()
            
        # 2. Standalone client, no host raises CannotConnect
        conn2 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn2._host = None
        with pytest.raises(CannotConnect):
            await conn2.async_get_client()

        # 3. Shared client (with controller)
        conn3 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn3._params = {"url": "http://test.com:1234/path"}
        mock_controller = MagicMock()
        del mock_controller._shared_raw_client # Ensure it does not exist
        conn3.set_controller_ref(mock_controller)
        
        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client") as mock_client_cls:
            client = await conn3.async_get_client()
            mock_client_cls.assert_called_once_with("192.168.1.100", 1234, "cert.pem", log_prefix=conn3.log_prefix)
            assert mock_controller._shared_raw_client == client
            
            # Requesting again should return cached shared client
            mock_client_cls.reset_mock()
            client_cached = await conn3.async_get_client()
            assert client_cached == client
            mock_client_cls.assert_not_called()

        # 4. Shared client, no host raises CannotConnect
        conn4 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_controller2 = MagicMock()
        del mock_controller2._shared_raw_client
        conn4.set_controller_ref(mock_controller2)
        conn4._host = None
        with pytest.raises(CannotConnect):
            await conn4.async_get_client()

async def test_close(connection_config, mock_logger, mock_hass):
    \"\"\"Test all paths of close.\"\"\"
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        
        # 1. Close internal embedded command
        conn._embedded_command = MagicMock()
        conn._embedded_command.close = AsyncMock()
        await conn.close()
        conn._embedded_command.close.assert_called_once()
        
        # 2. Close local client
        mock_client = AsyncMock()
        conn._client = mock_client
        await conn.close()
        mock_client.close.assert_called_once()
        assert conn._client is None
        
        # 3. Close shared client
        mock_controller = MagicMock()
        mock_shared_client = AsyncMock()
        mock_controller._shared_raw_client = mock_shared_client
        conn.set_controller_ref(mock_controller)
        await conn.close()
        mock_shared_client.close.assert_called_once()
        assert mock_controller._shared_raw_client is None
        
        # 4. Handle exceptions during close
        mock_client2 = AsyncMock()
        mock_client2.close.side_effect = TimeoutError("timeout")
        conn._client = mock_client2
        
        mock_shared_client2 = AsyncMock()
        mock_shared_client2.close.side_effect = TimeoutError("timeout")
        mock_controller._shared_raw_client = mock_shared_client2
        
        conn._embedded_command.close.side_effect = TimeoutError("timeout")
        
        # Should not raise
        await conn.close()
        assert conn._client is None
        assert mock_controller._shared_raw_client is None
"""

content = re.sub(
    r'async def test_async_get_client_port_parsing\(connection_config, mock_logger, mock_hass\):\s+"""Test URL port parsing in async_get_client."""\s+.*?assert conn\._client is None\n',
    async_get_client_replacement,
    content,
    flags=re.DOTALL
)

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'w') as f:
    f.write(content)

print("Phase 3 Patched!")
