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


@pytest.fixture
def mock_session():
    import aiohttp

    return MagicMock(spec=aiohttp.ClientSession)


async def test_async_execute_with_embedded_command_condition_met(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        # Mock main command execution
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.version = MagicMock(major=1, minor=1)

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        # Setup embedded command
        embedded_mock = AsyncMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=True)
        embedded_mock._params = {"url": "/embedded", "method": "GET"}
        embedded_mock._connection_template = None
        embedded_mock.async_execute = AsyncMock()

        conn._embedded_command = embedded_mock

        await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        embedded_mock.async_execute.assert_called_once()


async def test_async_execute_with_embedded_command_condition_not_met(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.version = MagicMock(major=1, minor=1)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        embedded_mock = AsyncMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=False)
        conn._embedded_command = embedded_mock

        await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        embedded_mock.async_execute.assert_not_called()


async def test_async_execute_with_embedded_command_no_condition(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.version = MagicMock(major=1, minor=1)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        embedded_mock = MagicMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=True)
        embedded_mock._params = {"url": "/embedded"}
        embedded_mock._connection_template = None
        embedded_mock.async_execute = AsyncMock()
        conn._embedded_command = embedded_mock

        await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        embedded_mock.async_execute.assert_called_once()


async def test_async_execute_main_condition_not_met(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        conn.check_execute_condition = MagicMock(return_value=False)

        res_text, headers = await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        assert res_text == "{}"
        assert headers == {}


async def test_async_execute_embedded_command_strict(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        # Main mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.version = MagicMock(major=1, minor=1)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        # Create embedded command
        embed_conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        embed_conn._params = {
            "method": "POST",
            "url": "/embedded_endpoint",
            "json": {"action": "test"},
        }
        embed_conn.async_execute = AsyncMock(
            return_value=('{"result": "embedded"}', {})
        )
        embed_conn.check_execute_condition = MagicMock(return_value=True)

        # Attach embedded command with a condition that always evaluates to True
        conn._embedded_command = embed_conn
        embed_conn.condition_template = MagicMock()
        embed_conn.condition_template.async_render = AsyncMock(return_value="True")

        await conn.async_execute("GET", "/main", None, {}, device_state={})

        # Verificar que async_execute del embebido se llamó con SUS parámetros exactos
        embed_conn.async_execute.assert_called_once_with(
            method="POST",
            url="/embedded_endpoint",
            data='{"action":"test"}',
            headers={},
            device_state={},
        )
