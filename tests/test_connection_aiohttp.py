# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ConnectionAiohttp8888."""
# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name
import logging
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import AuthError, CannotConnect
from homeassistant.const import CONF_TOKEN


@pytest.fixture
def mock_logger():
    """Return a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def mock_hass():
    """Return a mock HomeAssistant instance."""
    return MagicMock()


@pytest.fixture
def mock_session():
    """Return a mock aiohttp ClientSession."""
    return MagicMock(spec=aiohttp.ClientSession)


@pytest.fixture
def connection_config():
    """Return a basic connection config dict."""
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}






async def test_initialization(connection_config, mock_logger, mock_hass, mock_session):
    """Test connection initialization."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        assert conn._ip_address == "192.168.1.100"
        assert conn._token == "test_token"
        assert conn._shared_state["initialized"] is False



async def test_create_ssl_context(connection_config, mock_logger, mock_hass, mock_session):
    """Test SSL context creation."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )

        with patch(
            "custom_components.climate_ip.helpers.create_samsung_ssl_context"
        ) as mock_ssl_context:
            mock_context_instance = MagicMock()
            mock_ssl_context.return_value = mock_context_instance

            context = await conn._create_ssl_context()

            assert context is not None
            mock_ssl_context.assert_called_with(
                cert_path=conn._cert_path,
                ciphers="ALL:@SECLEVEL=0",
                verify_mode=ssl.CERT_NONE,
                is_server=False,
            )



async def test_execute_request_success(connection_config, mock_logger, mock_hass, mock_session):
    """Test successful request execution."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )

        # Mock shared state to avoid actual probe
        conn._shared_state["initialized"] = True
        conn._shared_state["ssl_context"] = MagicMock()

        # pylint: disable=import-outside-toplevel,duplicate-code
        # Mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.raise_for_status = MagicMock()

        # Correctly mock async context manager native to AsyncMock
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context
        # pylint: enable=duplicate-code

        response_text, headers = await conn.async_execute("GET", "/test", None, None)

        assert response_text == '{"result": "ok"}'
        assert headers == {"Content-Type": "application/json"}



async def test_execute_request_auth_error(connection_config, mock_logger, mock_hass, mock_session):
    """Test request execution with auth error."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )

        conn._shared_state["initialized"] = True
        conn._shared_state["ssl_context"] = MagicMock()

        mock_response = AsyncMock()
        mock_response.status = 401

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        with pytest.raises(AuthError):
            await conn.async_execute("GET", "/test", None, None)



async def test_execute_request_connection_error(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test request execution with connection error."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )

        conn._shared_state["initialized"] = True
        conn._shared_state["ssl_context"] = MagicMock()

        mock_session.request.side_effect = aiohttp.ClientConnectorError(MagicMock(), MagicMock())

        with pytest.raises(CannotConnect):
            await conn.async_execute("GET", "/test", None, None)



async def test_create_updated(connection_config, mock_logger, mock_hass, mock_session):
    """Test create_updated method."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._params = {"test": "param"}

        # Test with empty node
        new_conn = conn.create_updated({})
        assert isinstance(new_conn, ConnectionAiohttp8888)
        assert new_conn is not conn
        assert new_conn._params == {}  # Should be empty as per implementation

        # pylint: disable=import-outside-toplevel,duplicate-code
        # Test with params
        yaml_node = {"params": {"new": "value"}}
        new_conn_params = conn.create_updated(yaml_node)
        assert new_conn_params._params == {"test": "param", "new": "value"}

        # Test with connection_template
        yaml_node_tmpl = {"connection_template": "{{ test }}"}
        new_conn_tmpl = conn.create_updated(yaml_node_tmpl)
        assert new_conn_tmpl._connection_template is not None
        # pylint: enable=duplicate-code

def test_dummy_mutmut():
    from custom_components.climate_ip.connection_aiohttp import dummy_mutmut_test
    assert dummy_mutmut_test() == 42


# ====================================================================================
# FRENTE A: CICLO DE VIDA Y ESTADO COMPARTIDO (__init__, close, get_diagnostics)
# ====================================================================================

@pytest.mark.asyncio
async def test_aiohttp_lifecycle_and_shared_state():
    """Valida los estados por defecto, el diagnóstico y el cierre atómico de sesiones."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    
    mock_session = MagicMock()
    mock_hass = MagicMock()
    config = {"keep_alive": False, "token": "test_token"}
    
    conn = ConnectionAiohttp8888(config, logging.getLogger(), mock_hass, mock_session, "192.168.1.100")
    
    # 1. Aserciones de Inicialización (Mata mutantes que alteran None, False o diccionarios)
    assert conn._force_close_connection is False
    assert conn._connection_template is None
    assert conn._ssl_context is None
    assert conn._embedded_command is None
    assert "local_session" in conn._shared_state
    assert conn._shared_state["local_session"] is None
    
    # 2. Diagnóstico Estricto (Mata mutantes de .get("initialized", False))
    diag = conn.get_diagnostics()
    assert diag["is_connected"] is False
    assert diag["force_close_connection"] is False
    assert diag["keep_alive_enabled"] is False
    
    # 3. Cierre y purga (Mata mutantes que alteran "initialized" = False en el reset)
    conn._shared_state["initialized"] = True
    conn._shared_state["ssl_context"] = "FAKE_SSL"
    conn._shared_state["local_session"] = AsyncMock() # Simulamos una sesión local
    conn._shared_state["local_session"].closed = False
    
    await conn.close()
    
    assert conn._shared_state["initialized"] is False
    assert conn._shared_state["ssl_context"] is None
    assert conn._shared_state["local_session"] is None


