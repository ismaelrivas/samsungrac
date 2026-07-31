import logging
from unittest.mock import MagicMock, patch
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
