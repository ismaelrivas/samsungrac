from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
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
    return MagicMock()


async def test_get_session_keep_alive_no_session(
    connection_config, mock_logger, mock_hass
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        conn._keep_alive = True

        session = await conn._get_session()
        assert session is not None
        assert session == conn._shared_state.local_session


async def test_get_session_use_http(connection_config, mock_logger, mock_hass):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        conn._config["use_http"] = True

        session = await conn._get_session()
        assert session is not None
        assert hasattr(conn._shared_state, "local_session")


async def test_get_session_reuse_local_session(
    connection_config, mock_logger, mock_hass
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        conn._keep_alive = False

        session1 = await conn._get_session()
        session2 = await conn._get_session()

        assert session1 is session2


async def test_get_session_recreate_closed_local_session(
    connection_config, mock_logger, mock_hass
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        conn._keep_alive = False

        session1 = await conn._get_session()

        # Simulate closed session
        from unittest.mock import PropertyMock

        with patch.object(
            type(session1), "closed", new_callable=PropertyMock, return_value=True
        ):
            session2 = await conn._get_session()

        assert session1 is not session2


async def test_close_local_session_exception(connection_config, mock_logger, mock_hass):
    """Test that exceptions during local session closure are logged correctly to kill Mutant 25."""
    with patch(
        "custom_components.climate_ip.connection_aiohttp._LOGGER"
    ) as mock_module_logger:
        # 1. Initialize connection forcing a local session
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        conn._keep_alive = False

        # 2. Trigger creation of the local session
        local_session = await conn._get_session()

        # 3. Mock the session's close method to raise a network exception
        mock_error = aiohttp.ClientError("Simulated network drop during close")
        local_session.close = AsyncMock(side_effect=mock_error)

        # 4. Execute the connection close
        await conn.close()

        # 5. THE KILL SHOT: Assert the exact string was sent to the logger
        mock_module_logger.error.assert_any_call(
            "%s [aiohttp] Error closing local session: %s", conn.log_prefix, mock_error
        )

        # 6. Verify state was still cleaned up despite the error
        assert conn._shared_state.local_session is None
