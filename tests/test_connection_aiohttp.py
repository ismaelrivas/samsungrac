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
        assert conn._shared_state.initialized is False
        assert conn.async_lock is not None  # Verificamos que el padre creó el candado



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
        conn._shared_state.initialized = True
        conn._shared_state.ssl_context = MagicMock()

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

        response_text, headers = await conn.async_execute("GET", "/test", None, {})

        assert response_text == '{"result": "ok"}'
        assert headers == {"Content-Type": "application/json"}

        # Aserciones de Caja Blanca Extremas
        mock_session.request.assert_called_once()
        args, kwargs = mock_session.request.call_args
        
        # 1. Asertar URL y Método
        assert args[0] == "GET", "El método HTTP fue mutado"
        assert kwargs["url"] == "https://192.168.1.100:8888/test", "La URL fue mutada o generada incorrectamente"
        
        # 2. Asertar Payload
        assert "data" in kwargs, "El mutante eliminó el kwarg data"
        assert kwargs["data"] is None, "El payload fue mutado"
        
        # 3. Asertar SSL Context
        assert "ssl" in kwargs, "El mutante eliminó el kwarg ssl"
        assert kwargs["ssl"] is conn._shared_state.ssl_context, "El contexto SSL inyectado es incorrecto o None"
        
        # 4. Asertar Timeout estricto
        assert "timeout" in kwargs, "El mutante eliminó el kwarg timeout"
        timeout = kwargs["timeout"]
        assert timeout.total == 10, f"El mutante alteró el timeout.total a {timeout.total}"
        
        # Blindaje de mutantes 45-56 (Cabeceras)
        req_headers = kwargs.get("headers", {})
        assert "Authorization" in req_headers, "Falta la cabecera Authorization"
        assert req_headers["Authorization"] == f"Bearer {conn._token}", "Token incorrecto"
        assert "Content-Type" in req_headers, "Falta la cabecera Content-Type"
        assert req_headers["Content-Type"] == "application/json", "Content-Type incorrecto"



async def test_execute_request_auth_error(connection_config, mock_logger, mock_hass, mock_session):
    """Test request execution with auth error."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )

        conn._shared_state.initialized = True
        conn._shared_state.ssl_context = MagicMock()

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

        conn._shared_state.initialized = True
        conn._shared_state.ssl_context = MagicMock()

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
    assert hasattr(conn._shared_state, "local_session")
    assert conn._shared_state.local_session is None
    
    # 2. Diagnóstico Estricto (Mata mutantes de .get("initialized", False))
    diag = conn.get_diagnostics()
    assert diag["is_connected"] is False
    assert diag["force_close_connection"] is False
    assert diag["keep_alive_enabled"] is False
    
    # 3. Cierre y purga (Mata mutantes que alteran "initialized" = False en el reset)
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = "FAKE_SSL"
    conn._shared_state.local_session = AsyncMock() # Simulamos una sesión local
    conn._shared_state.local_session.closed = False
    
    await conn.close()
    
    assert conn._shared_state.initialized is False
    assert conn._shared_state.ssl_context is None
    assert conn._shared_state.local_session is None

# ====================================================================================
# FRENTE B: REEMPLAZO Y FORMATEO DE URLs (_format_url)
# ====================================================================================

def test_format_url_variants():
    """Valida el reemplazo de tokens, IPs, puertos y el downgrade a HTTP."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import MagicMock
    import logging
    
    config = {"token": "base_token", "host": "192.168.1.50", "port": "9999", "use_http": True}
    conn = ConnectionAiohttp8888(config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1")
    conn._params = {"mac": "AA:BB", "host": "192.168.1.50"}
    
    mock_controller = MagicMock()
    mock_controller.device_id = "dev_123"
    mock_controller._config = {"token": "ctrl_token"}
    conn.set_controller_ref(mock_controller)

    # 1. URL Completa: Reemplazo de puerto, downgrade HTTP, y placeholders
    # Mata mutantes que alteran ":8888/" a "XX:8888/XX" o eliminan "use_http"
    url_base = "https://__CLIMATE_IP_HOST__:8888/devices/__DEVICE_ID__?mac=__CLIMATE_IP_MAC__"
    res = conn._format_url(url_base)
    assert res == "http://10.0.0.1:9999/devices/dev_123?mac=AA:BB"

    # 2. Fallbacks de variables (Mata mutantes de getattr y .get)
    conn._ip_address = None # Forzamos fallback a CONF_HOST
    res2 = conn._format_url("https://__CLIMATE_IP_HOST__/status")
    assert res2 == "http://192.168.1.50/status"

# ====================================================================================
# FRENTE C: GENERACION DE SESIONES (_get_session)
# ====================================================================================

@pytest.mark.asyncio
async def test_get_session_args():
    """Valida los argumentos exactos pasados a aiohttp.TCPConnector."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import MagicMock, patch
    import logging
    
    config = {"use_http": True}
    conn = ConnectionAiohttp8888(config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1")
    conn._keep_alive = False
    
    with patch("aiohttp.TCPConnector") as mock_connector, \
         patch("aiohttp.ClientSession") as mock_session:
        
        session = await conn._get_session()
        
        # Verify strict arguments to kill limit/timeout mutants
        mock_connector.assert_called_with(keepalive_timeout=75, limit=1)
        
        # Verify ssl context passes through
        config["use_http"] = False
        conn._shared_state.ssl_context = "TEST_SSL_CTX"
        conn._shared_state.local_session = None # Force recreation
        
        await conn._get_session()
        mock_connector.assert_called_with(keepalive_timeout=75, ssl="TEST_SSL_CTX", limit=1)

# ====================================================================================
# FRENTE D: CLONACION Y CRIPTOGRAFIA (create_updated y _create_ssl_context)
# ====================================================================================

@pytest.mark.asyncio
async def test_create_ssl_context_strict():
    """Valida flags de seguridad y ciphers estrictos."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import MagicMock, patch
    import logging
    import ssl
    
    config = {"insecure_ssl": True}
    conn = ConnectionAiohttp8888(config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1")
    
    with patch("custom_components.climate_ip.connection_aiohttp.async_create_samsung_ssl_context") as mock_ssl:
        await conn._create_ssl_context()
        mock_ssl.assert_called_with(
            cert_path=None,
            ciphers="ALL:@SECLEVEL=0",
            verify_mode=ssl.CERT_NONE,
        )
        
def test_create_updated_strict():
    """Valida la clonación estricta y plantillas de condición."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from custom_components.climate_ip.const import CONFIG_DEVICE_CONNECTION
    from unittest.mock import MagicMock
    import logging
    
    config = {}
    conn = ConnectionAiohttp8888(config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1")
    conn._params = {"base": 1}
    
    yaml_node = {
        CONFIG_DEVICE_CONNECTION: {
            "params": {"child": 2},
            "condition_template": "{{ True }}"
        }
    }
    
    new_conn = conn.create_updated(yaml_node)
    
    # Must preserve the base parameter but NOT leak the child parameter to the root
    assert new_conn._params == {}
    
    # The embedded command must receive the child parameter
    assert new_conn._embedded_command is not None
    assert new_conn._embedded_command._params == {"child": 2}
    
    # Check condition template was compiled
    assert new_conn._embedded_command.condition_template is not None


async def test_adaptive_keep_alive_fallback(connection_config, mock_logger, mock_hass, mock_session):
    """Prueba que el motor añade Connection: close si el flag de force_close está activo."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import AsyncMock
    
    conn = ConnectionAiohttp8888(
        config=connection_config, 
        logger=mock_logger, 
        hass=mock_hass, 
        session=mock_session, 
        ip_address="192.168.1.100"
    )
    
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = None
    
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_response.raise_for_status = AsyncMock()

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context
    
    # Inyectamos el estado forzado (simulando que en el pasado falló)
    conn._force_close_connection = True
    
    # Al ejecutar, DEBE inyectar el header de cierre
    await conn._async_execute_request(method="GET", url_path="/test", data=None, headers={}, _is_poll=False)
    
    _, kwargs = mock_session.request.call_args
    actual_headers = kwargs.get("headers", {})
    
    assert "Connection" in actual_headers, "El mutante borró el header de Connection"
    assert actual_headers["Connection"] == "close", "El mutante alteró el valor de Connection: close"

def test_format_url_strict_evaluations():
    """Valida los mutantes que atacan la formación de URLs, HTTP fallback y reemplazo de puertos."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import MagicMock
    import logging
    
    config = {
        "host": "192.168.1.50",
        "mac": "AA:BB:CC:DD",
        "token": "tok123",
        "port": "9999", # Puerto custom para pillar al mutante
        "use_http": True # Activa HTTP para pillar al mutante
    }
    
    # Constructor mockeado
    conn = ConnectionAiohttp8888(config=config, logger=logging.getLogger(), hass=MagicMock(), session=None, ip_address=None)
    conn._params = config
    
    # 1. Test básico de placeholders
    url_base = "https://__CLIMATE_IP_HOST__/devices/__CLIMATE_IP_MAC__"
    formatted = conn._format_url(url_base)
    
    # Validamos el reemplazo y el cambio a HTTP
    assert "http://192.168.1.50/devices/AA:BB:CC:DD" in formatted, "Mutante sobrevivió alterando la inyección de host/mac o el fallback HTTP"

    # 2. Test del puerto custom (:8888/ -> :9999/) y fallback HTTP estricto
    url_port = "https://192.168.1.50:8888/devices/__CLIMATE_IP_MAC__"
    formatted_port = conn._format_url(url_port)
    
    # ASERCIONES ESTRICTAS (Matan mutantes 33, 42, 53, 56)
    assert formatted_port == "http://192.168.1.50:9999/devices/AA:BB:CC:DD", "Fallo en reemplazo de puerto o protocolo"

async def test_adaptive_keep_alive_on_timeout_recovery(connection_config, mock_logger, mock_hass, mock_session):
    """Testea que el motor cambia a force_close y reintenta tras un ClientError."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import AsyncMock
    import aiohttp
    
    conn = ConnectionAiohttp8888(
        config=connection_config, 
        logger=mock_logger, 
        hass=mock_hass, 
        session=mock_session, 
        ip_address="192.168.1.100"
    )
    
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = None
    
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_response.raise_for_status = AsyncMock()
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response

    # Hacemos que el mock falle la primera vez y funcione la segunda
    mock_session.request.side_effect = [
        aiohttp.ClientConnectorError(None, OSError("Mocked Error")),
        mock_context # Segunda vez funciona
    ]
    
    await conn._async_execute_request("GET", "/test", None, {})
    
    # Verificamos que reintentó
    assert mock_session.request.call_count == 2
    
    # Verificamos que el segundo intento llevaba la cabecera salvavidas
    retry_kwargs = mock_session.request.call_args_list[1][1]
    assert "Connection" in retry_kwargs["headers"]
    assert retry_kwargs["headers"]["Connection"] == "close"
    
    # Y que el estado interno se actualizó correctamente
    assert conn._force_close_connection is True

async def test_close_awaits_socket_teardown(connection_config, mock_logger, mock_hass, mock_session):
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.local_session = mock_session
        
        with patch("asyncio.sleep") as mock_sleep:
            mock_session.closed = False
            await conn.close()
            mock_sleep.assert_called_with(0.1)
            assert mock_session.close.call_count == 1

def test_create_updated_preserves_memory_references(connection_config, mock_logger, mock_hass, mock_session):
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    with patch("os.path.exists", return_value=True):
        base_conn = ConnectionAiohttp8888(
            config={"keep_alive": True, "token": "base"}, 
            logger=mock_logger, 
            hass=mock_hass, 
            session=mock_session, 
            ip_address="192.168.1.100"
        )
        base_conn._controller = "MockControllerRef"
        
        # Creamos un clon con nuevos parámetros
        new_conn = base_conn.create_updated({"keep_alive": False})
        
        # ASERCIONES ESTRICTAS DE MEMORIA
        assert new_conn._controller == "MockControllerRef", "Perdió la referencia al controlador"
        assert new_conn._shared_state is base_conn._shared_state, "Perdió el estado compartido"
        assert new_conn._keep_alive is False, "No actualizó el parámetro hijo"

async def test_execution_uses_controller_token_priority(connection_config, mock_logger, mock_hass, mock_session):
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    with patch("os.path.exists", return_value=True):
        # Conexión con un token base
        conn = ConnectionAiohttp8888(
            config={"token": "TOKEN_BASE"}, 
            logger=mock_logger, 
            hass=mock_hass, 
            session=mock_session, 
            ip_address="192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._shared_state.ssl_context = None
        
        # Inyectamos el controlador con un token dominante
        mock_controller = MagicMock()
        mock_controller._config = {"token": "TOKEN_DOMINANTE"}
        mock_controller.device_id = "DEV_123"
        conn._controller = mock_controller
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.raise_for_status = AsyncMock()
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context
        
        await conn._async_execute_request("GET", "/test", None, {})
        
        # ASERCIÓN ESTRICTA
        _, kwargs = mock_session.request.call_args
        actual_headers = kwargs.get("headers", {})
        
        assert actual_headers["Authorization"] == "Bearer TOKEN_DOMINANTE", "No usó el token del controlador"

async def test_http_1_0_forces_connection_close(connection_config, mock_logger, mock_hass, mock_session):
    """Prueba que un servidor antiguo fuerza el cierre de la conexión."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.version = MagicMock(major=1, minor=0) # SIMULAMOS HTTP 1.0
        mock_response.headers = {}
        mock_response.text.return_value = '{}'
        mock_response.raise_for_status = MagicMock()
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context
        
        await conn._async_execute_request("GET", "/test", None, {})
        
        assert conn._force_close_connection is True, "El mutante alteró la validación minor >= 1 de HTTP"

async def test_absolute_url_skips_base_url_formatting(connection_config, mock_logger, mock_hass, mock_session):
    """Prueba que una URL absoluta ignora el formateo base y SSL."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.text.return_value = '{}'
        mock_response.raise_for_status = MagicMock()
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        await conn._async_execute_request("GET", "http://external-api.com/path", None, {})
        
        _, kwargs = mock_session.request.call_args
        assert kwargs["url"] == "http://external-api.com/path", "El mutante rompió la detección startswith('http')"
        assert kwargs["ssl"] is False, "El mutante usó SSL en una conexión plana HTTP"


async def test_async_execute_request_respects_custom_headers(mock_session, mock_logger, mock_hass):
    """Garantiza que las cabeceras inyectadas manualmente no son sobrescritas."""
    conn = ConnectionAiohttp8888(config={"token": "TOKEN_BASE"}, logger=mock_logger, hass=mock_hass, session=mock_session, ip_address="1.1.1.1")
    conn._shared_state.initialized = True
    
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context
    
    custom_headers = {
        "Authorization": "Bearer TOKEN_CUSTOM",
        "Content-Type": "text/xml"
    }
    
    await conn._async_execute_request("GET", "/test", None, headers=custom_headers)
    
    _, kwargs = mock_session.request.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer TOKEN_CUSTOM", "El mutante sobrescribió la cabecera Auth"
    assert kwargs["headers"]["Content-Type"] == "text/xml", "El mutante sobrescribió el Content-Type"


async def test_retry_request_kwargs_strict(mock_session, mock_logger, mock_hass):
    """Exige que el reintento tras un fallo pase EXACTAMENTE los mismos parámetros a la red."""
    conn = ConnectionAiohttp8888(config={"token": "tok"}, logger=mock_logger, hass=mock_hass, session=mock_session, ip_address="1.1.1.1")
    
    # Simulamos fallo en el 1er intento, éxito en el 2do
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {}
    mock_response.text.return_value = "{}"
    
    mock_context_success = AsyncMock()
    mock_context_success.__aenter__.return_value = mock_response
    
    mock_session.request.side_effect = [
        aiohttp.ClientConnectorError(None, OSError("mock error")),
        mock_context_success
    ]
    
    await conn._async_execute_request("POST", "/test", "payload_secreto", {"H": "1"})
    
    assert mock_session.request.call_count == 2
    retry_args, retry_kwargs = mock_session.request.call_args_list[1]
    
    # ASERCIONES MILIMÉTRICAS DEL REINTENTO
    assert retry_args[0] == "POST"
    assert "https://1.1.1.1:8888/test" in retry_args[1]
    assert retry_kwargs["data"] == "payload_secreto"
    assert retry_kwargs["headers"]["H"] == "1"
    assert retry_kwargs["headers"]["Connection"] == "close"
    assert retry_kwargs["timeout"].total == 10


async def test_async_execute_default_poll_is_false(mock_session, mock_logger, mock_hass):
    """Prueba que _is_poll es estrictamente False por defecto, evitando el cierre de sesiones locales."""
    conn = ConnectionAiohttp8888(config={"keep_alive": False, "token": "tok"}, logger=mock_logger, hass=mock_hass, session=mock_session, ip_address="1.1.1.1")
    conn._shared_state.initialized = True
    
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    
    mock_local = MagicMock()
    mock_local.closed = False
    mock_local.close = AsyncMock()
    mock_local.request.return_value = mock_context
    conn._shared_state.local_session = mock_local
    
    # Llamamos SIN el argumento _is_poll
    await conn.async_execute("GET", "/test", None, {})
    
    # Si mutmut cambió el default a True, la sesión se cerrará y el test fallará
    mock_local.close.assert_not_called()


async def test_async_execute_embedded_command_kwargs_strict(mock_session, mock_logger, mock_hass):
    """Valida la delegación exacta de argumentos al comando embebido anidado."""
    from homeassistant.helpers.json import json_dumps
    
    conn = ConnectionAiohttp8888(config={"token": "tok"}, logger=mock_logger, hass=mock_hass, session=mock_session, ip_address="1.1.1.1")
    
    embed_mock = AsyncMock()
    embed_mock.check_execute_condition.return_value = True
    # Simulamos un template que devuelve un JSON configurador
    embed_mock._connection_template.async_render = AsyncMock(
        return_value='{"method": "PUT", "url": "/embed", "json": {"key": "val"}, "headers": {"X": "Y"}}'
    )
    conn._embedded_command = embed_mock
    conn._shared_state.initialized = True
    
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context
    
    await conn.async_execute("GET", "/main", None, {}, device_state={"state": "on"})
    
    # Verificamos qué se le pasó al comando embebido
    embed_mock.async_execute.assert_called_once()
    kwargs = embed_mock.async_execute.call_args[1]
    
    assert kwargs["method"] == "PUT"
    assert kwargs["url"] == "/embed"
    assert kwargs["data"] == json_dumps({"key": "val"})  # Mata a los mutantes de json_dumps
    assert kwargs["headers"] == {"X": "Y"}
    assert kwargs["device_state"] == {"state": "on"}


async def test_async_execute_delegates_to_request_strictly(mock_logger, mock_hass):
    """Asegura que async_execute pasa intactos los parámetros a _async_execute_request."""
    conn = ConnectionAiohttp8888(config={"token": "tok"}, logger=mock_logger, hass=mock_hass, session=None, ip_address="1.1.1.1")
    conn._shared_state.initialized = True
    
    with patch.object(conn, "_async_execute_request", new_callable=AsyncMock) as mock_req:
        await conn.async_execute("PATCH", "/main", "payload", {"H": "1"}, _is_poll=True)
        
        mock_req.assert_called_once_with("PATCH", "/main", "payload", {"H": "1"}, _is_poll=True)


async def test_controller_fallback_to_base_token(mock_session, mock_logger, mock_hass):
    """Prueba que si el controlador no tiene token, se usa el de la conexión base."""
    conn = ConnectionAiohttp8888(config={"token": "BASE_TOKEN"}, logger=mock_logger, hass=mock_hass, session=mock_session, ip_address="1.1.1.1")
    conn._shared_state.initialized = True
    
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context
    
    mock_controller = MagicMock()
    mock_controller._config = {}  # Diccionario vacío, fuerza el fallback a BASE_TOKEN
    conn.set_controller_ref(mock_controller)
    
    await conn._async_execute_request("GET", "/test", None, {})
    
    _, kwargs = mock_session.request.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer BASE_TOKEN"

