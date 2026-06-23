import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from homeassistant.const import CONF_TOKEN
from custom_components.climate_ip.const import CONF_CERT

@pytest.fixture
def connection_config():
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}

@pytest.fixture
def mock_logger():
    return MagicMock(spec=logging.Logger)

@pytest.fixture
def mock_hass():
    return MagicMock()

async def test_get_diagnostics(connection_config, mock_logger, mock_hass):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, None, "192.168.1.100")
        conn._shared_state.initialized = True
        conn._shared_state.ssl_context = MagicMock()
        conn._force_close_connection = True
        
        diag = conn.get_diagnostics()
        assert diag["is_connected"] is True
        assert diag["force_close_connection"] is True
        assert diag["keep_alive_enabled"] == conn._keep_alive
        assert diag["has_ssl_context"] is True

async def test_close_connection(connection_config, mock_logger, mock_hass):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, None, "192.168.1.100")
        
        # Setup embedded command
        embedded_mock = AsyncMock()
        conn._embedded_command = embedded_mock
        
        # Setup local session
        local_session_mock = AsyncMock()
        local_session_mock.closed = False
        conn._shared_state.local_session = local_session_mock
        
        await conn.close()
        
        embedded_mock.close.assert_called_once()
        local_session_mock.close.assert_called_once()
        assert conn._shared_state.initialized is False
        assert conn._shared_state.ssl_context is None
        assert conn._shared_state.local_session is None
