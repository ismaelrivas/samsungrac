# pylint: disable=protected-access,redefined-outer-name,duplicate-code,import-outside-toplevel,missing-docstring,line-too-long
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_TOKEN

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.const import CONF_CERT


class StubHass:
    def __init__(self):
        from unittest.mock import AsyncMock

        self.async_add_executor_job = AsyncMock(
            spec=["__call__", "return_value"],
            side_effect=lambda func, *args: func(*args),
        )

    def __repr__(self):
        return "<SafeHass>"

    def __dir__(self):
        return ["async_add_executor_job"]


class StubSession:
    def __init__(self):
        from unittest.mock import AsyncMock, MagicMock

        self.closed = False
        self.request = MagicMock(spec=["__call__", "return_value"])
        self.close = AsyncMock(spec=["__call__", "return_value"])

    def __repr__(self):
        return "<SafeSession>"

    def __dir__(self):
        return ["closed", "request", "close"]


@pytest.fixture
def connection_config():
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}


@pytest.fixture
def mock_logger():
    return logging.getLogger("test_logger")


@pytest.fixture
def mock_hass():
    return StubHass()


async def test_get_diagnostics(connection_config, mock_logger, mock_hass):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        # 1. State with ssl_context None
        conn._shared_state.initialized = False
        conn._shared_state.ssl_context = None
        conn._force_close_connection = False

        diag_initial = conn.get_diagnostics()
        assert isinstance(diag_initial, dict)
        assert diag_initial["is_connected"] is False
        assert diag_initial["force_close_connection"] is False
        assert diag_initial["keep_alive_enabled"] is True
        assert diag_initial["has_ssl_context"] is False

        # 2. State with ssl_context present and force_close True
        conn._shared_state.initialized = True
        conn._shared_state.ssl_context = MagicMock()
        conn._force_close_connection = True

        diag = conn.get_diagnostics()
        assert isinstance(diag, dict)
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
