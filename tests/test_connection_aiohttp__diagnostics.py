from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_TOKEN

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.const import CONF_CERT


@pytest.fixture
def connection_config():
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}


@pytest.fixture
def mock_logger():
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


async def test_get_diagnostics(connection_config, mock_logger, mock_hass):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
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
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )

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


def test_is_available_property(connection_config, mock_logger, mock_hass):
    """Test is_available property reflects shared state initialized flag."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        assert conn.is_available is False
        conn._shared_state.initialized = True
        assert conn.is_available is True


async def test_close_embedded_command_exception(connection_config, mock_logger, mock_hass):
    """Test that an exception during embedded command close is logged and handled gracefully."""
    import aiohttp

    with (
        patch("os.path.exists", return_value=True),
        patch("custom_components.climate_ip.connection_aiohttp._LOGGER") as mock_module_logger,
    ):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        embedded_mock = AsyncMock()
        mock_err = aiohttp.ClientError("Embedded connection error during close")
        embedded_mock.close.side_effect = mock_err
        conn._embedded_command = embedded_mock

        await conn.close()

        embedded_mock.close.assert_called_once()
        mock_module_logger.warning.assert_called_with(
            "%s [aiohttp] Error closing embedded command: %s",
            conn.log_prefix,
            mock_err,
        )
