import logging
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
import pytest

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.exceptions import CannotConnect, InvalidHeaderError
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

@pytest.fixture
def mock_session():
    return MagicMock(spec=aiohttp.ClientSession)

async def test_try_connection_success(connection_config, mock_logger, mock_hass, mock_session):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100")
        
        # Mock create_ssl_context
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context
        
        res = await conn._try_connection()
        assert res == '{"result": "ok"}'
        assert conn._shared_state["initialized"] is True

async def test_try_connection_success_no_body(connection_config, mock_logger, mock_hass, mock_session):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100")
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        
        mock_response = AsyncMock()
        mock_response.status = 401
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context
        
        res = await conn._try_connection()
        assert res is None
        assert conn._shared_state["initialized"] is True

async def test_try_connection_unexpected_status(connection_config, mock_logger, mock_hass, mock_session):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100")
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        
        mock_response = AsyncMock()
        mock_response.status = 500
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context
        
        with pytest.raises(CannotConnect):
            await conn._try_connection()

async def test_try_connection_client_connector_error(connection_config, mock_logger, mock_hass, mock_session):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100")
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        
        mock_session.request.side_effect = aiohttp.ClientConnectorError(MagicMock(), MagicMock())
        
        with pytest.raises(CannotConnect):
            await conn._try_connection()

async def test_try_connection_timeout_error(connection_config, mock_logger, mock_hass, mock_session):
    import asyncio
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100")
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        
        mock_session.request.side_effect = asyncio.TimeoutError()
        
        with pytest.raises(InvalidHeaderError):
            await conn._try_connection()

async def test_try_connection_invalid_header(connection_config, mock_logger, mock_hass, mock_session):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100")
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        
        mock_session.request.side_effect = ValueError("Invalid header token")
        
        with pytest.raises(InvalidHeaderError):
            await conn._try_connection()

async def test_try_connection_generic_error(connection_config, mock_logger, mock_hass, mock_session):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100")
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        
        mock_session.request.side_effect = RuntimeError("Some generic error")
        
        with pytest.raises(CannotConnect):
            await conn._try_connection()

async def test_try_connection_already_initialized(connection_config, mock_logger, mock_hass, mock_session):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100")
        conn._shared_state["initialized"] = True
        
        res = await conn._try_connection()
        assert res is None
