# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ConnectionAiohttp8888."""

# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name
import logging
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONFIG_DEVICE_CONNECTION_PARAMS,
)
from custom_components.climate_ip.exceptions import AuthError, CannotConnect
from homeassistant.const import CONF_TOKEN


@pytest.fixture
def mock_logger():
    """Return a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def mock_hass():
    """Return a mock HomeAssistant instance."""
    hass = MagicMock()

    async def async_add_executor_job(target, *args):
        return target(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=async_add_executor_job)
    return hass


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


async def test_create_ssl_context(
    connection_config, mock_logger, mock_hass, mock_session
):
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


async def test_execute_request_success(
    connection_config, mock_logger, mock_hass, mock_session
):
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
        assert kwargs["url"] == "https://192.168.1.100:8888/test", (
            "La URL fue mutada o generada incorrectamente"
        )

        # 2. Asertar Payload
        assert "data" in kwargs, "El mutante eliminó el kwarg data"
        assert kwargs["data"] is None, "El payload fue mutado"

        # 3. Asertar SSL Context
        assert "ssl" in kwargs, "El mutante eliminó el kwarg ssl"
        assert kwargs["ssl"] is conn._shared_state.ssl_context, (
            "El contexto SSL inyectado es incorrecto o None"
        )

        # 4. Asertar Timeout estricto
        assert "timeout" in kwargs, "El mutante eliminó el kwarg timeout"
        timeout = kwargs["timeout"]
        assert timeout.total == 10, (
            f"El mutante alteró el timeout.total a {timeout.total}"
        )

        # Blindaje de mutantes 45-56 (Cabeceras)
        req_headers = kwargs.get("headers", {})
        assert "Authorization" in req_headers, "Falta la cabecera Authorization"
        assert req_headers["Authorization"] == f"Bearer {conn._token}", (
            "Token incorrecto"
        )
        assert "Content-Type" in req_headers, "Falta la cabecera Content-Type"
        assert req_headers["Content-Type"] == "application/json", (
            "Content-Type incorrecto"
        )


async def test_execute_request_auth_error(
    connection_config, mock_logger, mock_hass, mock_session
):
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

        mock_session.request.side_effect = aiohttp.ClientConnectorError(
            MagicMock(), MagicMock()
        )

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

    conn = ConnectionAiohttp8888(
        config, logging.getLogger(), mock_hass, mock_session, "192.168.1.100"
    )

    # 1. Aserciones de Inicialización (Kills mutants que alteran None, False o diccionarios)
    assert conn._force_close_connection is False
    assert conn._connection_template is None
    assert conn._ssl_context is None
    assert conn._embedded_command is None
    assert hasattr(conn._shared_state, "local_session")
    assert conn._shared_state.local_session is None

    # 2. Diagnóstico Estricto (Kills mutants de .get("initialized", False))
    diag = conn.get_diagnostics()
    assert diag["is_connected"] is False
    assert diag["force_close_connection"] is False
    assert diag["keep_alive_enabled"] is False

    # 3. Cierre y purga (Kills mutants que alteran "initialized" = False en el reset)
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = "FAKE_SSL"
    conn._shared_state.local_session = AsyncMock()  # Simulamos una sesión local
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

    config = {
        "token": "base_token",
        "host": "192.168.1.50",
        "port": "9999",
        "use_http": True,
    }
    conn = ConnectionAiohttp8888(
        config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1"
    )
    conn._params = {"mac": "AA:BB", "host": "192.168.1.50"}

    mock_controller = MagicMock()
    mock_controller.device_id = "dev_123"
    mock_controller._config = {"token": "ctrl_token"}
    conn.set_controller_ref(mock_controller)

    # 1. URL Completa: Reemplazo de puerto, downgrade HTTP, y placeholders
    # Kills mutants que alteran ":8888/" a "XX:8888/XX" o eliminan "use_http"
    url_base = (
        "https://__CLIMATE_IP_HOST__:8888/devices/__DEVICE_ID__?mac=__CLIMATE_IP_MAC__"
    )
    res = conn._format_url(url_base)
    assert res == "http://10.0.0.1:9999/devices/dev_123?mac=AA:BB"

    # 2. Fallbacks de variables (Kills mutants de getattr y .get)
    conn._ip_address = None  # Forzamos fallback a CONF_HOST
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
    conn = ConnectionAiohttp8888(
        config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1"
    )
    conn._keep_alive = False

    _NS = "custom_components.climate_ip.connection_aiohttp.aiohttp"
    with (
        patch(f"{_NS}.TCPConnector") as mock_connector,
        patch(f"{_NS}.ClientSession") as mock_session,
    ):
        await conn._get_session()

        # Verify strict arguments to kill limit/timeout mutants
        mock_connector.assert_called_with(keepalive_timeout=75, limit=1)
        _, session_kwargs = mock_session.call_args
        assert session_kwargs["timeout"].total == 30
        assert session_kwargs["timeout"].connect == 10

        # Verify ssl context passes through
        config["use_http"] = False
        conn._shared_state.ssl_context = "TEST_SSL_CTX"
        conn._shared_state.local_session = None  # Force recreation

        await conn._get_session()
        mock_connector.assert_called_with(
            keepalive_timeout=75, ssl="TEST_SSL_CTX", limit=1
        )


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
    conn = ConnectionAiohttp8888(
        config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1"
    )

    with patch(
        "custom_components.climate_ip.connection_aiohttp.async_create_samsung_ssl_context"
    ) as mock_ssl:
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
    conn = ConnectionAiohttp8888(
        config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1"
    )
    conn._params = {"base": 1}

    yaml_node = {
        CONFIG_DEVICE_CONNECTION: {
            "params": {"child": 2},
            "condition_template": "{{ True }}",
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


async def test_adaptive_keep_alive_fallback(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Prueba que el motor añade Connection: close si el flag de force_close está activo."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import AsyncMock

    conn = ConnectionAiohttp8888(
        config=connection_config,
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="192.168.1.100",
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

    # Inject el estado forzado (simulando que en el pasado falló)
    conn._force_close_connection = True

    # Al ejecutar, DEBE inyectar el header de cierre
    await conn._async_execute_request(
        "GET", "https://192.168.1.100:8888/test", None, {}
    )

    _, kwargs = mock_session.request.call_args
    actual_headers = kwargs.get("headers", {})

    assert "Connection" in actual_headers, "El mutante borró el header de Connection"
    assert actual_headers["Connection"] == "close", (
        "El mutante alteró el valor de Connection: close"
    )


def test_format_url_strict_evaluations():
    """Valida los mutantes que atacan la formación de URLs, HTTP fallback y reemplazo de puertos."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import MagicMock
    import logging

    config = {
        "host": "192.168.1.50",
        "mac": "AA:BB:CC:DD",
        "token": "tok123",
        "port": "9999",  # Puerto custom para pillar al mutante
        "use_http": True,  # Activa HTTP para pillar al mutante
    }

    # Constructor mockeado
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=None,
        ip_address=None,
    )
    conn._params = config

    # 1. Test básico de placeholders
    url_base = "https://__CLIMATE_IP_HOST__/devices/__CLIMATE_IP_MAC__"
    formatted = conn._format_url(url_base)

    # Validamos el reemplazo y el cambio a HTTP
    assert "http://192.168.1.50/devices/AA:BB:CC:DD" in formatted, (
        "Mutante sobrevivió alterando la inyección de host/mac o el fallback HTTP"
    )

    # 2. Test del puerto custom (:8888/ -> :9999/) y fallback HTTP estricto
    url_port = "https://192.168.1.50:8888/devices/__CLIMATE_IP_MAC__"
    formatted_port = conn._format_url(url_port)

    # ASERCIONES ESTRICTAS (Matan mutantes 33, 42, 53, 56)
    assert formatted_port == "http://192.168.1.50:9999/devices/AA:BB:CC:DD", (
        "Fallo en reemplazo de puerto o protocolo"
    )


async def test_adaptive_keep_alive_on_timeout_recovery(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Testea que el motor cambia a force_close y reintenta tras un ClientError."""
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from unittest.mock import AsyncMock
    import aiohttp

    conn = ConnectionAiohttp8888(
        config=connection_config,
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="192.168.1.100",
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
        mock_context,  # Segunda vez funciona
    ]

    await conn._async_execute_request("GET", "https://192.168.1.100:8888/test", None, {})

    # Verificamos que reintentó
    assert mock_session.request.call_count == 2

    # Verificamos que el segundo intento llevaba la cabecera salvavidas
    retry_kwargs = mock_session.request.call_args_list[1][1]
    assert "Connection" in retry_kwargs["headers"]
    assert retry_kwargs["headers"]["Connection"] == "close"

    # Y que el estado interno se actualizó para persistir el cierre en subsecuentes llamadas
    assert conn._force_close_connection is True


async def test_close_closes_local_session(
    connection_config, mock_logger, mock_hass, mock_session
):
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.local_session = mock_session

        mock_session.closed = False
        await conn.close()
        assert mock_session.close.call_count == 1


def test_create_updated_preserves_memory_references(
    connection_config, mock_logger, mock_hass, mock_session
):
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

    with patch("os.path.exists", return_value=True):
        base_conn = ConnectionAiohttp8888(
            config={"keep_alive": True, "token": "base"},
            logger=mock_logger,
            hass=mock_hass,
            session=mock_session,
            ip_address="192.168.1.100",
        )
        base_conn._controller = "MockControllerRef"

        # Create un clon con nuevos parámetros
        new_conn = base_conn.create_updated({"keep_alive": False})

        # ASERCIONES ESTRICTAS DE MEMORIA
        assert new_conn._controller == "MockControllerRef", (
            "Perdió la referencia al controlador"
        )
        assert new_conn._shared_state is base_conn._shared_state, (
            "Perdió el estado compartido"
        )
        assert new_conn._keep_alive is False, "No actualizó el parámetro hijo"


async def test_execution_uses_controller_token_priority(
    connection_config, mock_logger, mock_hass, mock_session
):
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

    with patch("os.path.exists", return_value=True):
        # Conexión con un token base
        conn = ConnectionAiohttp8888(
            config={"token": "TOKEN_BASE"},
            logger=mock_logger,
            hass=mock_hass,
            session=mock_session,
            ip_address="192.168.1.100",
        )
        conn._shared_state.initialized = True
        conn._shared_state.ssl_context = None

        # Inject el controlador con un token dominante
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

        await conn._async_execute_request("GET", "https://192.168.1.100:8888/test", None, {})

        # ASERCIÓN ESTRICTA
        _, kwargs = mock_session.request.call_args
        actual_headers = kwargs.get("headers", {})

        assert actual_headers["Authorization"] == "Bearer TOKEN_DOMINANTE", (
            "No usó el token del controlador"
        )


async def test_http_1_0_forces_connection_close(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Prueba que un servidor antiguo fuerza el cierre de la conexión."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.version = MagicMock(major=1, minor=0)  # SIMULAMOS HTTP 1.0
        mock_response.headers = {}
        mock_response.text.return_value = "{}"
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        await conn._async_execute_request("GET", "https://192.168.1.100:8888/test", None, {})

        assert conn._force_close_connection is True, (
            "El mutante alteró la validación minor >= 1 de HTTP"
        )


async def test_absolute_url_skips_base_url_formatting(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Prueba que una URL absoluta ignora el formateo base y SSL."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.text.return_value = "{}"
        mock_response.raise_for_status = MagicMock()
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        await conn._async_execute_request(
            "GET", "http://external-api.com/path", None, {}
        )

        _, kwargs = mock_session.request.call_args
        assert kwargs["url"] == "http://external-api.com/path", (
            "El mutante rompió la detección startswith('http')"
        )
        assert kwargs["ssl"] is False, "El mutante usó SSL en una conexión plana HTTP"


async def test_async_execute_request_respects_custom_headers(
    mock_session, mock_logger, mock_hass
):
    """Garantiza que las cabeceras inyectadas manualmente no son sobrescritas."""
    conn = ConnectionAiohttp8888(
        config={"token": "TOKEN_BASE"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
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
        "Content-Type": "text/xml",
    }

    await conn._async_execute_request("GET", "https://1.1.1.1:8888/test", None, headers=custom_headers)

    _, kwargs = mock_session.request.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer TOKEN_CUSTOM", (
        "El mutante sobrescribió la cabecera Auth"
    )
    assert kwargs["headers"]["Content-Type"] == "text/xml", (
        "El mutante sobrescribió el Content-Type"
    )


async def test_retry_request_kwargs_strict(mock_session, mock_logger, mock_hass):
    """Exige que el reintento tras un fallo pase EXACTAMENTE los mismos parámetros a la red."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )

    # Simulamos fallo en el 1er intento, éxito en el 2do
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {}
    mock_response.text.return_value = "{}"

    mock_context_success = AsyncMock()
    mock_context_success.__aenter__.return_value = mock_response

    mock_session.request.side_effect = [
        aiohttp.ClientConnectorError(None, OSError("mock error")),
        mock_context_success,
    ]

    await conn._async_execute_request("POST", "https://1.1.1.1:8888/test", "payload_secreto", {"H": "1"})

    assert mock_session.request.call_count == 2
    retry_args, retry_kwargs = mock_session.request.call_args_list[1]

    # ASERCIONES MILIMÉTRICAS DEL REINTENTO
    assert retry_args[0] == "POST"
    assert "https://1.1.1.1:8888/test" in retry_args[1]
    assert retry_kwargs["data"] == "payload_secreto"
    assert retry_kwargs["headers"]["H"] == "1"
    assert retry_kwargs["headers"]["Connection"] == "close"
    assert retry_kwargs["timeout"].total == 10


async def test_async_execute_default_poll_is_false(
    mock_session, mock_logger, mock_hass
):
    """Prueba que _is_poll es estrictamente False por defecto, evitando el cierre de sesiones locales."""
    conn = ConnectionAiohttp8888(
        config={"keep_alive": False, "token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
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

    # If mutmut cambió el default a True, la sesión se cerrará y el test fallará
    mock_local.close.assert_not_called()


async def test_async_execute_embedded_command_kwargs_strict(
    mock_session, mock_logger, mock_hass
):
    """Valida la delegación exacta de argumentos al comando embebido anidado."""
    from homeassistant.helpers.json import json_dumps

    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )

    embed_mock = AsyncMock()
    embed_mock.params = {}
    embed_mock.check_execute_condition.return_value = True
    # Simulamos un template que devuelve un JSON configurador
    embed_mock.connection_template.async_render = MagicMock(
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
    assert kwargs["data"] == json_dumps(
        {"key": "val"}
    )  # Verify mutant kill de json_dumps
    assert kwargs["headers"] == {"X": "Y"}
    assert kwargs["device_state"] == {"state": "on"}


async def test_async_execute_delegates_to_request_strictly(mock_logger, mock_hass):
    """Asegura que async_execute pasa intactos los parámetros a _async_execute_request."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=None,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True

    with patch.object(
        conn, "_async_execute_request", new_callable=AsyncMock
    ) as mock_req:
        await conn.async_execute("PATCH", "/main", "payload", {"H": "1"}, _is_poll=True)

        mock_req.assert_called_once_with(
            "PATCH", "https://1.1.1.1:8888/main", "payload", {"H": "1"}
        )


async def test_controller_fallback_to_base_token(mock_session, mock_logger, mock_hass):
    """Prueba que si el controlador no tiene token, se usa el de la conexión base."""
    conn = ConnectionAiohttp8888(
        config={"token": "BASE_TOKEN"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
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

    await conn._async_execute_request("GET", "https://192.168.1.100:8888/test", None, {})

    _, kwargs = mock_session.request.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer BASE_TOKEN"


# ====================================================================================
# TÁCTICA 1: LA TRAMPA DE LOS dict.get() — Validación estricta de extracción de claves
# ====================================================================================


def test_format_url_strict_dict_extraction():
    """Valida que _format_url extrae exactamente las claves configuradas (no variaciones de string).

    Mutmut sobrevive cambiando self._params.get(CONF_MAC) a self._params.get(None)
    o self._ip_address or self._params.get(CONF_HOST) a variantes. Este test
    usa valores asimétricos e irrepetibles para que cualquier alteración de clave falle.
    """
    from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, CONF_TOKEN
    import logging

    # Valores ASIMÉTRICOS: cada uno es único e irrepetible para detectar swaps
    config = {
        CONF_HOST: "10.0.0.1",
        CONF_MAC: "00:11:22:33:44:55",
        CONF_PORT: "7777",
        "use_http": False,
        CONF_TOKEN: "tok_BASE_unique",
    }

    # IP Address explícito: fuerza la precedencia sobre CONF_HOST en _resolved_target
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="192.168.1.100",
    )
    # _params simula lo que create_updated() inyectaría desde el YAML
    conn._params = {
        CONF_HOST: "10.0.0.1",
        CONF_MAC: "00:11:22:33:44:55",
    }

    # Controller con token dominante y device_id
    mock_controller = MagicMock()
    mock_controller.device_id = "device_xyz"
    mock_controller._config = {CONF_TOKEN: "tok_CONTROLLER_dominant"}
    conn.set_controller_ref(mock_controller)

    # URL con TODOS los placeholders reales
    base_url = (
        "https://__CLIMATE_IP_HOST__:8888"
        "/api/__CLIMATE_IP_MAC__"
        "/token/__CLIMATE_IP_TOKEN__"
        "/device/__DEVICE_ID__"
    )

    formatted = conn._format_url(base_url)

    # ASERCIÓN EXTREMA: Cada segmento debe coincidir al milímetro
    # - Host: IP address (192.168.1.100) tiene PRECEDENCIA sobre config host (10.0.0.1)
    # - Port: :8888/ → :7777/ por el reemplazo de CONF_PORT
    # - Mac: directamente de _params[CONF_MAC]
    # - Token: del controlador (tok_CONTROLLER_dominant) NO del config (tok_BASE_unique)
    # - Device ID: del controlador device_id
    expected_url = (
        "https://192.168.1.100:7777"
        "/api/00:11:22:33:44:55"
        "/token/tok_CONTROLLER_dominant"
        "/device/device_xyz"
    )

    assert formatted == expected_url, (
        f"El formateo mutado falló.\n"
        f"  Esperado:  {expected_url}\n"
        f"  Recibido:  {formatted}"
    )


def test_resolved_target_ip_precedence_over_config_host():
    """Valida la propiedad _resolved_target: ip_address SIEMPRE gana sobre params[CONF_HOST]."""
    from homeassistant.const import CONF_HOST, CONF_MAC
    import logging

    config = {CONF_HOST: "SHOULD_NOT_APPEAR"}
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="WINNER_IP",
    )
    conn._params = {CONF_HOST: "ALSO_SHOULD_NOT_APPEAR", CONF_MAC: "MAC_VALUE"}

    host, mac = conn._resolved_target

    assert host == "WINNER_IP", f"ip_address no tuvo precedencia: host={host}"
    assert mac == "MAC_VALUE", f"MAC no se extrajo correctamente: mac={mac}"


def test_resolved_target_fallback_to_params_host():
    """Valida que si ip_address es None, _resolved_target cae a _params[CONF_HOST]."""
    from homeassistant.const import CONF_HOST, CONF_MAC
    import logging

    conn = ConnectionAiohttp8888(
        config={},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address=None,  # Sin IP → debe usar params
    )
    conn._params = {CONF_HOST: "FALLBACK_HOST", CONF_MAC: "FB:MA:CC"}

    host, mac = conn._resolved_target

    assert host == "FALLBACK_HOST", f"No cayó al fallback de CONF_HOST: host={host}"
    assert mac == "FB:MA:CC", f"MAC corrupta: mac={mac}"


def test_resolved_target_missing_keys_return_empty_strings():
    """Valida que claves ausentes en _params devuelven cadenas vacías, NO None."""
    import logging

    conn = ConnectionAiohttp8888(
        config={},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address=None,
    )
    conn._params = {}  # Diccionario vacío → todo debe ser ""

    host, mac = conn._resolved_target

    assert host == "", f"Host debería ser '' pero es {host!r}"
    assert mac == "", f"MAC debería ser '' pero es {mac!r}"
    assert isinstance(host, str), "Host debe ser str, no None"
    assert isinstance(mac, str), "MAC debe ser str, no None"


def test_format_url_port_replacement_only_on_8888():
    """Valida que el reemplazo de puerto SOLO ocurre cuando ':8888/' está presente en la URL."""
    import logging

    config = {CONF_TOKEN: "tok", "port": "9999"}
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="1.2.3.4",
    )

    # URL SIN :8888/ → el puerto NO debe cambiar
    url_no_port = "https://1.2.3.4:1234/devices"
    result = conn._format_url(url_no_port)
    assert ":1234/" in result, f"El puerto fue reemplazado cuando no debía: {result}"
    assert ":9999/" not in result, f"Reemplazo espurio de puerto: {result}"

    # URL CON :8888/ → el puerto DEBE cambiar a 9999
    url_with_port = "https://1.2.3.4:8888/devices"
    result2 = conn._format_url(url_with_port)
    assert ":9999/" in result2, f"El puerto 8888 no fue reemplazado: {result2}"
    assert ":8888/" not in result2, f"Quedó el puerto viejo: {result2}"


def test_format_url_strict_defaults_and_http_downgrade():
    """Valida los defaults puros: Puerto 8888 por defecto y degradación a HTTP."""
    import logging

    # 1. CONFIG VACÍA: Forzamos al código a usar sus .get(clave, DEFAULT)
    conn = ConnectionAiohttp8888(
        config={},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="192.168.1.100",
    )
    conn._params = {}

    base_url = "https://192.168.1.100:8888/test"
    formatted = conn._format_url(base_url)

    # ASERCIÓN DE DEFAULTS: Verify mutant kill que cambian "8888" o "False"
    assert formatted.startswith("https://"), (
        "Mutante alteró el default de use_http (False)"
    )
    assert ":8888/" in formatted, "Mutante alteró el puerto por defecto (8888)"

    # 2. CONFIG HTTP: Validamos el downgrade explícito
    conn._config["use_http"] = True
    formatted_http = conn._format_url(base_url)

    # Mata al mutante que rompe la lógica de reemplazo "https://" -> "http://"
    assert formatted_http.startswith("http://"), (
        "Mutante rompió el downgrade a HTTP plano"
    )


# ====================================================================================
# TÁCTICA 2: TIMEOUT DEL TCPCONNECTOR Y CREACIÓN DE SESIÓN (_get_session)
# ====================================================================================


@pytest.mark.asyncio
async def test_get_session_strict_creation_parameters_https():
    """Valida los parámetros exactos de TCPConnector, ClientTimeout y ClientSession para HTTPS."""
    import logging

    config = {"use_http": False, "keep_alive": False}
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="10.0.0.1",
    )
    conn._keep_alive = False
    conn._shared_state.local_session = None  # Forzar creación

    fake_ssl_ctx = MagicMock(name="FAKE_SSL_CTX")
    conn._shared_state.ssl_context = fake_ssl_ctx

    _NS = "custom_components.climate_ip.connection_aiohttp.aiohttp"
    with (
        patch(f"{_NS}.TCPConnector") as mock_connector,
        patch(f"{_NS}.ClientTimeout") as mock_timeout,
        patch(f"{_NS}.ClientSession") as mock_session_cls,
    ):
        mock_timeout.return_value = "mocked_timeout_obj"
        mock_connector.return_value = "mocked_connector_obj"
        mock_session_cls.return_value = AsyncMock()

        await conn._get_session()

        # ASERCIONES MILIMÉTRICAS — HTTPS branch (ssl= presente)
        mock_connector.assert_called_once_with(
            keepalive_timeout=75,
            ssl=fake_ssl_ctx,
            limit=1,
        )
        mock_timeout.assert_called_once_with(total=30, connect=10)
        mock_session_cls.assert_called_once_with(
            connector="mocked_connector_obj",
            timeout="mocked_timeout_obj",
        )


@pytest.mark.asyncio
async def test_get_session_strict_creation_parameters_http():
    """Valida que en modo HTTP plano, TCPConnector se crea SIN el parámetro ssl."""
    import logging

    config = {"use_http": True, "keep_alive": False}
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="10.0.0.1",
    )
    conn._keep_alive = False
    conn._shared_state.local_session = None
    conn._shared_state.ssl_context = MagicMock(name="SHOULD_NOT_BE_USED")

    _NS = "custom_components.climate_ip.connection_aiohttp.aiohttp"
    with (
        patch(f"{_NS}.TCPConnector") as mock_connector,
        patch(f"{_NS}.ClientTimeout") as mock_timeout,
        patch(f"{_NS}.ClientSession") as mock_session_cls,
    ):
        mock_timeout.return_value = "mocked_timeout_obj"
        mock_connector.return_value = "mocked_connector_obj"
        mock_session_cls.return_value = AsyncMock()

        await conn._get_session()

        # HTTP branch: NO debe pasar ssl=
        mock_connector.assert_called_once_with(
            keepalive_timeout=75,
            limit=1,
        )
        # Timeout y Session idénticos en ambos branches
        mock_timeout.assert_called_once_with(total=30, connect=10)
        mock_session_cls.assert_called_once_with(
            connector="mocked_connector_obj",
            timeout="mocked_timeout_obj",
        )


@pytest.mark.asyncio
async def test_get_session_returns_shared_session_when_keep_alive():
    """Valida que keep_alive=True con sesión inyectada devuelve la sesión compartida sin crear nada."""
    import logging

    injected_session = MagicMock(name="INJECTED_HA_SESSION")
    conn = ConnectionAiohttp8888(
        config={"keep_alive": True},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=injected_session,
        ip_address="10.0.0.1",
    )
    conn._keep_alive = True

    _NS = "custom_components.climate_ip.connection_aiohttp.aiohttp"
    with (
        patch(f"{_NS}.TCPConnector") as mock_connector,
        patch(f"{_NS}.ClientSession") as mock_session_cls,
    ):
        result = await conn._get_session()

        # DEBE devolver la sesión inyectada, NO crear una nueva
        assert result is injected_session, "No devolvió la sesión compartida de HA"
        mock_connector.assert_not_called()
        mock_session_cls.assert_not_called()


@pytest.mark.asyncio
async def test_get_session_recreates_on_closed_session():
    """Valida que si la sesión local está cerrada, se crea una nueva."""
    import logging

    conn = ConnectionAiohttp8888(
        config={"keep_alive": False},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="10.0.0.1",
    )
    conn._keep_alive = False

    # Simulamos una sesión cerrada
    closed_session = MagicMock()
    closed_session.closed = True
    conn._shared_state.local_session = closed_session

    _NS = "custom_components.climate_ip.connection_aiohttp.aiohttp"
    with (
        patch(f"{_NS}.TCPConnector") as mock_connector,
        patch(f"{_NS}.ClientTimeout") as mock_timeout,
        patch(f"{_NS}.ClientSession") as mock_session_cls,
    ):
        fresh_session = AsyncMock(name="FRESH_SESSION")
        mock_session_cls.return_value = fresh_session
        mock_connector.return_value = "new_connector"
        mock_timeout.return_value = "new_timeout"

        await conn._get_session()

        # DEBE haber creado una nueva sesión porque la anterior estaba cerrada
        mock_session_cls.assert_called_once()
        assert conn._shared_state.local_session is fresh_session, (
            "No reemplazó la sesión cerrada"
        )


@pytest.mark.asyncio
async def test_get_session_reuses_open_local_session():
    """Valida que si la sesión local ya existe y está abierta, se reutiliza sin crear una nueva."""
    import logging

    conn = ConnectionAiohttp8888(
        config={"keep_alive": False},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="10.0.0.1",
    )
    conn._keep_alive = False

    # Simulamos una sesión local SANA Y ABIERTA
    healthy_session = MagicMock()
    healthy_session.closed = False
    conn._shared_state.local_session = healthy_session

    _NS = "custom_components.climate_ip.connection_aiohttp.aiohttp"
    with (
        patch(f"{_NS}.TCPConnector") as mock_connector,
        patch(f"{_NS}.ClientTimeout") as mock_timeout,
        patch(f"{_NS}.ClientSession") as mock_session_cls,
    ):
        result = await conn._get_session()

        # ASERCIÓN: Debe devolver la sesión existente y no haber llamado a las clases de aiohttp
        assert result is healthy_session, "No reutilizó la sesión local sana"
        mock_connector.assert_not_called()
        mock_timeout.assert_not_called()
        mock_session_cls.assert_not_called()


@pytest.mark.asyncio
async def test_get_session_fallback_when_shared_session_is_none():
    """Valida el fallback defensivo: keep_alive=True pero session=None."""
    import logging

    # Configuramos keep_alive=True pero omitimos intencionalmente la sesión
    conn = ConnectionAiohttp8888(
        config={"keep_alive": True},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=None,  # <--- ¡LA TRAMPA PARA MUTMUT!
        ip_address="10.0.0.1",
    )
    conn._shared_state.local_session = None

    # Parcheamos la creación para verificar que el fallback local se activa
    _NS = "custom_components.climate_ip.connection_aiohttp.aiohttp"
    with (
        patch(f"{_NS}.TCPConnector"),
        patch(f"{_NS}.ClientTimeout"),
        patch(f"{_NS}.ClientSession") as mock_session_cls,
    ):
        # Usamos el truco de trazabilidad en memoria
        mock_session_cls.return_value = "fallback_local_session_obj"

        result = await conn._get_session()

        # ASERCIÓN EXTREMA: A pesar de keep_alive=True, tuvo que crear una sesión local
        mock_session_cls.assert_called_once()
        assert result == "fallback_local_session_obj", (
            "El fallback a sesión local falló"
        )


# ====================================================================================
# TÁCTICA 3: LA BATALLA DEL COMANDO EMBEBIDO — Fallback a _params directos
# ====================================================================================


@pytest.mark.asyncio
async def test_embedded_command_without_template_uses_params_directly(
    mock_session, mock_logger, mock_hass
):
    """Testea la ejecución de un comando embebido que usa _params directos (sin template).

    Verify mutant kill que alteran:
    - embedded_params.get("method", method)  → clave "method" o default
    - embedded_params.get("url", url)        → clave "url" o default
    - embedded_params.get("json")            → clave "json" para el payload
    - embedded_params.get("headers", headers)→ clave "headers" o default
    - bool(embedded_params) is True          → el guard del branch
    """
    from homeassistant.helpers.json import json_dumps

    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True

    # Preparar la sesión principal para el comando principal
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    # Embebido: SIN template, CON _params directos
    # Valores ASIMÉTRICOS para detectar cualquier swap de clave
    embed_mock = AsyncMock()
    embed_mock.check_execute_condition.return_value = True
    embed_mock.connection_template = None  # <--- Activa el branch _params
    embed_mock.params = {
        "method": "DELETE",  # Valor distinto al "GET" del main → swap detectable
        "url": "/override_url",  # Valor distinto al "/main" → swap detectable
        "json": {"override": "yes"},  # Clave "json" → se serializa con json_dumps
        "headers": {"Custom": "Header"},  # Clave "headers" → sustituye las del main
    }
    conn._embedded_command = embed_mock

    await conn.async_execute("GET", "/main", None, {}, device_state={"state": "on"})

    # Verificamos los kwargs exactos pasados al motor del comando embebido
    embed_mock.async_execute.assert_called_once()
    kwargs = embed_mock.async_execute.call_args[1]

    # ASERCIONES MILIMÉTRICAS — mata mutantes que alteran las claves de .get()
    assert kwargs["method"] == "DELETE", (
        f"El mutante alteró la clave 'method' en .get(): recibido {kwargs['method']}"
    )
    assert kwargs["url"] == "/override_url", (
        f"El mutante alteró la clave 'url' en .get(): recibido {kwargs['url']}"
    )
    assert kwargs["data"] == json_dumps({"override": "yes"}), (
        f"El mutante alteró la clave 'json' o el json_dumps: recibido {kwargs['data']}"
    )
    assert kwargs["headers"] == {"Custom": "Header"}, (
        f"El mutante alteró la clave 'headers' en .get(): recibido {kwargs['headers']}"
    )
    assert kwargs["device_state"] == {"state": "on"}, (
        "El mutante alteró la propagación de device_state al embebido"
    )


@pytest.mark.asyncio
async def test_embedded_command_without_template_and_empty_params_skips(
    mock_session, mock_logger, mock_hass
):
    """Valida que si el embebido no tiene template NI params, embedded_params=None y NO se ejecuta.

    Kills mutants que alteran `bool(embedded_params) is True` → cambiando `is True` a `is False`
    o `True` a `False`, haciendo que el código tome el branch equivocado.
    """
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    embed_mock = AsyncMock()
    embed_mock.check_execute_condition.return_value = True
    embed_mock.connection_template = None
    embed_mock.params = {}  # <--- Vacío → bool({}) is False → entra al else: embedded_params = None
    conn._embedded_command = embed_mock

    await conn.async_execute("GET", "/main", None, {}, device_state={"state": "on"})

    # El embebido NO debe haberse ejecutado porque params estaba vacío
    embed_mock.async_execute.assert_not_called()


@pytest.mark.asyncio
async def test_embedded_command_method_and_url_fallback_to_main(
    mock_session, mock_logger, mock_hass
):
    """Valida el fallback de method y url cuando el embebido no los define explícitamente.

    Kills mutants que eliminan el segundo argumento de .get("method", method)
    o .get("url", url) — haciendo que devuelva None en lugar del valor del comando principal.
    """
    from homeassistant.helpers.json import json_dumps

    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    embed_mock = AsyncMock()
    embed_mock.check_execute_condition.return_value = True
    embed_mock.connection_template = None
    # _params SIN "method" ni "url" → deben heredarse del comando principal
    embed_mock.params = {"json": {"action": "toggle"}}
    conn._embedded_command = embed_mock

    await conn.async_execute("PUT", "/main_url", None, {}, device_state={"state": "on"})

    embed_mock.async_execute.assert_called_once()
    kwargs = embed_mock.async_execute.call_args[1]

    # FALLBACK: Si el embebido no define method ni url, usa los del comando principal
    assert kwargs["method"] == "PUT", (
        f"El fallback de 'method' está roto: recibido {kwargs['method']}"
    )
    assert kwargs["url"] == "/main_url", (
        f"El fallback de 'url' está roto: recibido {kwargs['url']}"
    )
    assert kwargs["data"] == json_dumps({"action": "toggle"}), (
        f"El json_dumps del payload del embebido falló: {kwargs['data']}"
    )


# ====================================================================================
# TÁCTICA 3 — MEJORA 1: Vacío Absoluto (Kills mutants de 'json' ausente y headers)
# ====================================================================================


@pytest.mark.asyncio
async def test_embedded_command_strict_fallbacks_to_main(
    mock_session, mock_logger, mock_hass
):
    """Valida el fallback de method, url, data=None y headers cuando el embebido NO los define.

    Verify mutant kill que alteran:
    - `else None` en `json_dumps(...) if "json" in embedded_params else None`
    - `.get("headers", headers)` → si muta a None, el assert falla
    """
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    embed_mock = AsyncMock()
    embed_mock.check_execute_condition.return_value = True
    embed_mock.connection_template = None

    # TRUCO: clave irrelevante para que bool(_params) sea True
    # pero omitimos 'method', 'url', 'json' y 'headers' intencionalmente
    embed_mock.params = {"dummy_key": "force_execution"}
    conn._embedded_command = embed_mock

    # Ejecutamos el main con cabeceras NO vacías → si el fallback muta a None el test falla
    main_headers = {"Main-Header": "Present"}
    await conn.async_execute(
        "PUT",
        "/main_url",
        "main_data_ignored",
        main_headers,
        device_state={"state": "on"},
    )

    embed_mock.async_execute.assert_called_once()
    kwargs = embed_mock.async_execute.call_args[1]

    # ASERCIONES EXTREMAS DE FALLBACK
    assert kwargs["method"] == "PUT", (
        f"Mutante rompió fallback de method: {kwargs['method']}"
    )
    assert kwargs["url"] == "/main_url", (
        f"Mutante rompió fallback de url: {kwargs['url']}"
    )
    assert kwargs["headers"] == {"Main-Header": "Present"}, (
        f"Mutante rompió fallback de headers: {kwargs['headers']}"
    )
    # "json" no está en _params → el `else None` debe producir data=None
    assert kwargs["data"] is None, (
        f"Mutante alteró el 'else None' cuando falta 'json' en _params: {kwargs['data']}"
    )


# ====================================================================================
# TÁCTICA 3 — MEJORA 2: Tabla de la Verdad de _is_poll (Kills mutants 134-137)
# ====================================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_poll,keep_alive,should_close",
    [
        (True, False, True),  # CASO 1: Es poll y no hay keep_alive → DEBE cerrar
        (True, True, False),  # CASO 2: Es poll pero keep_alive=True → NO cierra
        (False, False, False),  # CASO 3: No es poll → NO cierra
        (False, True, False),  # CASO 4: Camino feliz normal → NO cierra
    ],
)
async def test_async_execute_periodic_reset_truth_table(
    mock_session, mock_logger, mock_hass, is_poll, keep_alive, should_close
):
    """Verify mutant kill lógicos (and/or/not) en la evaluación del cierre periódico por poll."""
    conn = ConnectionAiohttp8888(
        config={"keep_alive": keep_alive, "token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._keep_alive = keep_alive

    # Sesión local ABIERTA para que el cierre sea observable
    mock_local = AsyncMock()
    mock_local.closed = False
    conn._shared_state.local_session = mock_local

    # Mock de sesión principal para que _async_execute_request no explote
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_response.version = None
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx
    # También preparamos la sesión local para el request que sigue al cierre
    mock_local.request.return_value = mock_ctx

    # Parcheo _async_execute_request para aislar sólo la lógica de _is_poll
    with patch.object(
        conn, "_async_execute_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = ("{}", {})

        await conn.async_execute("GET", "/test", None, {}, _is_poll=is_poll)

        if should_close:
            # CASO 1: debe haber llamado a close() y reseteado local_session a None
            mock_local.close.assert_called_once()
            assert conn._shared_state.local_session is None, (
                f"Estado no reseteado a None (is_poll={is_poll}, keep_alive={keep_alive})"
            )
        else:
            # CASOS 2, 3, 4: NO debe haber cerrado nada
            mock_local.close.assert_not_called()
            assert conn._shared_state.local_session is mock_local, (
                f"Sesión local borrada indebidamente (is_poll={is_poll}, keep_alive={keep_alive})"
            )


# ====================================================================================
# TÁCTICA 4: EXTERMINIO FINAL — _try_connection y _async_execute_request
# ====================================================================================


@pytest.mark.asyncio
async def test_try_connection_strict_http_mode(mock_logger, mock_hass):
    """Prueba que use_http=True puentea SSL, usa protocolo 'http' y ssl=False en la probe.

    Kills mutants que alteran:
    - `if not self._config.get("use_http", False)` → quitan el `not`
    - `protocol = "http" if ... else "https"` → invierten las ramas
    - `test_ssl_ctx = False if protocol == "http"` → cambian False por None
    - `aiohttp.ClientTimeout(total=10, sock_read=5)` → alteran los valores
    """
    conn = ConnectionAiohttp8888(
        config={"use_http": True, "port": "1234", "token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=None,
        ip_address="192.168.1.50",
    )

    # Inject sesión local para que _get_session la devuelva sin crear una nueva.
    # IMPORTANTE: MagicMock (no AsyncMock) porque `async with session.request(...)` espera
    # un context manager directo, no una corutina.
    mock_local_session = MagicMock()
    mock_local_session.closed = (
        False  # CRÍTICO: evita que _get_session intente crear una nueva
    )
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.connection = None  # Evita AttributeError en el TLS log
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_local_session.request.return_value = mock_ctx
    conn._shared_state.local_session = mock_local_session
    conn._shared_state.ssl_context = None

    # NO parcheamos _create_ssl_context: si la lógica intenta crearlo el test fallará
    with patch.object(
        conn, "_create_ssl_context", new_callable=AsyncMock
    ) as mock_ssl_create:
        await conn._try_connection()

        # SSL NO debe haberse creado en modo HTTP
        mock_ssl_create.assert_not_called()

    mock_local_session.request.assert_called_once()
    args, kwargs = mock_local_session.request.call_args

    # ASERCIONES MILIMÉTRICAS
    assert args[1] == "http://192.168.1.50:1234", (
        f"Mutante alteró el protocolo o el puerto: {args[1]}"
    )
    assert kwargs["ssl"] is False, (
        f"Mutante alteró ssl=False para HTTP: {kwargs['ssl']}"
    )
    assert conn._shared_state.ssl_context is None, (
        "El mutante ignoró el `if not use_http` y creó el contexto SSL"
    )

    # Aserción del timeout de la probe (total=10, sock_read=5)
    timeout_obj = kwargs.get("timeout")
    assert timeout_obj is not None, "Mutante eliminó el argumento timeout de la probe"
    assert timeout_obj.total == 10, (
        f"Mutante alteró timeout.total en _try_connection: {timeout_obj.total}"
    )
    assert timeout_obj.sock_read == 5, (
        f"Mutante alteró timeout.sock_read en _try_connection: {timeout_obj.sock_read}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "major,minor,start_forced,expected_forced",
    [
        (1, 1, True, False),  # HTTP/1.1 → Re-habilita Keep-Alive (fuerza cierre=False)
        (1, 0, False, True),  # HTTP/1.0 → Activa fuerza cierre
        (2, 0, True, True),  # HTTP/2.0 con minor=0 → No es HTTP/1.x → mantiene True
    ],
)
async def test_async_execute_request_http_version_detection(
    mock_session, mock_logger, mock_hass, major, minor, start_forced, expected_forced
):
    """Verify mutant kill que alteran `major == 1 and minor >= 1` en la detección de versión HTTP."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._force_close_connection = start_forced

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_response.version = MagicMock(major=major, minor=minor)
    mock_response.raise_for_status = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    await conn._async_execute_request("GET", "https://1.1.1.1:8888/test", None, {})

    assert conn._force_close_connection is expected_forced, (
        f"Fallo en HTTP/{major}.{minor} (start_forced={start_forced}): "
        f"esperado {expected_forced}, recibido {conn._force_close_connection}"
    )


@pytest.mark.asyncio
async def test_async_execute_request_strict_kwargs(
    mock_session, mock_logger, mock_hass
):
    """Verify mutant kill que alteran los kwargs de session.request en _async_execute_request.

    Cubre: method posicional, url, data, headers, ssl y timeout.total==10.
    """
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = MagicMock(name="FAKE_SSL")

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = '{"ok": true}'
    mock_response.headers = {"X-Result": "ok"}
    mock_response.version = MagicMock(major=1, minor=1)
    mock_response.raise_for_status = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    await conn._async_execute_request(
        "PATCH", "https://1.1.1.1:8888/strict_url", "strict_payload", {"Header": "Strict"}
    )

    mock_session.request.assert_called_once()
    args, kwargs = mock_session.request.call_args

    # Método posicional
    assert args[0] == "PATCH", f"Mutante alteró el método: {args[0]}"
    # URL construida correctamente
    assert kwargs["url"] == "https://1.1.1.1:8888/strict_url", (
        f"Mutante alteró la URL: {kwargs['url']}"
    )
    # Payload
    assert kwargs["data"] == "strict_payload", (
        f"Mutante alteró el payload: {kwargs['data']}"
    )
    # Cabecera custom preservada
    assert kwargs["headers"]["Header"] == "Strict", (
        f"Mutante alteró la cabecera: {kwargs['headers']}"
    )
    # SSL inyectado correctamente
    assert kwargs["ssl"] is conn._shared_state.ssl_context, (
        f"Mutante alteró el ssl context: {kwargs['ssl']}"
    )

    # ASERCIÓN MILIMÉTRICA DEL TIMEOUT (total=10, sin sock_read)
    timeout_obj = kwargs.get("timeout")
    assert timeout_obj is not None, "Mutante eliminó el argumento timeout"
    assert isinstance(timeout_obj, aiohttp.ClientTimeout), (
        f"Mutante cambió el tipo de timeout: {type(timeout_obj)}"
    )
    assert timeout_obj.total == 10, (
        f"Mutante alteró timeout.total: esperado 10, recibido {timeout_obj.total}"
    )


@pytest.mark.asyncio
async def test_async_execute_request_none_http_version(
    mock_session, mock_logger, mock_hass
):
    """Verify mutant kill que alteran `and response.version` validando el silencio del logger."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._force_close_connection = False  # Para que pase la primera condición del if

    mock_response = AsyncMock(status=200, headers={})
    mock_response.text.return_value = "{}"
    mock_response.version = None  # ¡LA TRAMPA PARA MUTMUT!

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    await conn._async_execute_request("GET", "https://1.1.1.1:8888/test", None, {})

    # ASERCIÓN MILIMÉTRICA
    assert conn._force_close_connection is True, (
        "Debería forzar cierre si no hay versión"
    )
    # Verificamos que el logger.debug NO se llamó con el mensaje de versión
    for call in mock_logger.debug.call_args_list:
        assert "Server speaks HTTP" not in call[0][0], (
            "El mutante evaluó True en `and response.version` cuando era None"
        )


@pytest.mark.asyncio
async def test_async_execute_request_absolute_url(mock_session, mock_logger, mock_hass):
    """Prueba que si se pasa una URL absoluta, se ignora el base_url y se usa tal cual."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = MagicMock()

    mock_response = AsyncMock(status=200, headers={})
    mock_response.text.return_value = "{}"
    mock_response.version = MagicMock(major=1, minor=1)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    # Pass una URL absoluta
    absolute_url = "http://external-api.local:9999/status"
    await conn._async_execute_request("GET", absolute_url, None, {})

    mock_session.request.assert_called_once()
    _, kwargs = mock_session.request.call_args

    # ASERCIÓN ESTRICTA: La URL debe ser exactamente la absoluta, sin concatenar la IP base
    assert kwargs["url"] == absolute_url, (
        f"El mutante rompió startswith('http'): {kwargs['url']}"
    )
    # Como es http://, el ssl debe desactivarse automáticamente al final
    assert kwargs["ssl"] is False, "El mutante no desactivó SSL para una URL http plana"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 405])
async def test_try_connection_strict_error_handling(
    mock_logger, mock_hass, status_code
):
    """Asierta que los códigos de error específicos se manejan sin lanzar CannotConnect.
    Verify mutant kill que eliminan 401, 403 o 405 de la tupla (200, 401, 403, 405) en _try_connection.
    """
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=None,
        ip_address="1.1.1.1",
    )

    mock_local_session = MagicMock()
    mock_local_session.closed = False
    mock_response = AsyncMock(status=status_code)
    mock_response.connection = None
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_local_session.request.return_value = mock_ctx
    conn._shared_state.local_session = mock_local_session
    conn._shared_state.ssl_context = None

    with patch.object(
        conn, "_create_ssl_context", new_callable=AsyncMock
    ) as mock_ssl_create:
        mock_ssl_create.return_value = MagicMock()
        # If mutmut elimina el código de la tupla, esto lanzará CannotConnect y el test fallará
        result = await conn._try_connection()
        assert result is None, f"Se esperaba None para el status {status_code}"


@pytest.mark.asyncio
async def test_try_connection_strict_token_and_port(
    mock_session, mock_logger, mock_hass
):
    """Kills mutants de extracción de token del controlador y puertos en la probe."""
    # 1. Configuramos custom port
    conn = ConnectionAiohttp8888(
        config={"port": "7777", "token": "BASE_TOK"},
        logger=mock_logger,
        hass=mock_hass,
        session=None,
        ip_address="1.1.1.1",
    )

    # 2. Configuramos Controller con Token dominante
    mock_ctrl = MagicMock()
    mock_ctrl._config = {"token": "CTRL_TOK"}
    conn.set_controller_ref(mock_ctrl)

    # Setup mock session
    mock_session.closed = False
    mock_ctx = AsyncMock()
    mock_response = AsyncMock(status=200, version=None)
    mock_response.headers = {}
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx
    conn._shared_state.local_session = mock_session
    conn._shared_state.ssl_context = False  # skip ssl creation for speed

    await conn._try_connection()

    mock_session.request.assert_called_once()
    args, kwargs = mock_session.request.call_args

    # ASERCIONES MILIMÉTRICAS
    assert kwargs["headers"]["Authorization"] == "Bearer CTRL_TOK", (
        "Mutante rompió fallback del controller token"
    )
    assert args[1] == "https://1.1.1.1:7777", (
        "Mutante rompió el puerto en _try_connection"
    )


@pytest.mark.asyncio
async def test_async_execute_request_header_placeholders(
    mock_session, mock_logger, mock_hass
):
    """Kills mutants de format_placeholders aplicados a las cabeceras."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._params = {"mac": "AA:BB"}
    mock_ctrl = MagicMock()
    mock_ctrl.device_id = "DEV_123"
    mock_ctrl._config = {}
    conn.set_controller_ref(mock_ctrl)

    mock_session.closed = False
    mock_ctx = AsyncMock()
    mock_response = AsyncMock(status=200, version=None)
    mock_response.headers = {}
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    # Inject placeholders puros en las cabeceras
    custom_headers = {
        "X-Mac": "__CLIMATE_IP_MAC__",
        "X-Dev": "__DEVICE_ID__",
        "X-Tok": "__CLIMATE_IP_TOKEN__",
    }

    await conn._async_execute_request("GET", "https://1.1.1.1:8888/test", None, custom_headers)

    _, kwargs = mock_session.request.call_args
    assert kwargs["headers"]["X-Mac"] == "AA:BB", "Mutante rompió placeholder {mac}"
    assert kwargs["headers"]["X-Dev"] == "DEV_123", (
        "Mutante rompió placeholder {device_id}"
    )
    assert kwargs["headers"]["X-Tok"] == "tok", "Mutante rompió placeholder {token}"


@pytest.mark.asyncio
async def test_async_execute_skips_optimization_on_mismatch(
    mock_session, mock_logger, mock_hass
):
    """Kills mutants del 'if probe_response_text and method == GET and url == /devices'."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )

    with (
        patch.object(conn, "_try_connection", new_callable=AsyncMock) as mock_try,
        patch.object(
            conn, "_async_execute_request", new_callable=AsyncMock
        ) as mock_req,
    ):
        mock_try.return_value = "PROBE_OK"
        mock_req.return_value = ("REQ_OK", {})

        # Caso 1: Method incorrecto (POST en lugar de GET)
        res1, _ = await conn.async_execute("POST", "", None, {})
        assert res1 == "REQ_OK", (
            "El mutante activó la optimización erróneamente para POST"
        )
        mock_req.assert_called_with("POST", "https://1.1.1.1:8888", None, {})

        mock_req.reset_mock()

        # Caso 2: URL incorrecta (/other en lugar de /devices)
        res2, _ = await conn.async_execute("GET", "/other", None, {})
        assert res2 == "REQ_OK", (
            "El mutante activó la optimización erróneamente para URL distinta"
        )
        mock_req.assert_called_with("GET", "https://1.1.1.1:8888/other", None, {})


# ====================================================================================
# UNTESTED MUTANTS ANNIHILATION
# ====================================================================================


def test_match_type_annihilation():
    """Kill mutant 1 in match_type (type_str == CONNECTION_TYPE_AIOHTTP_8888)."""
    assert ConnectionAiohttp8888.match_type("samsung_8888_aiohttp") is True
    assert ConnectionAiohttp8888.match_type("other_connection_type") is False


def test_load_from_yaml_annihilation(mock_logger, mock_hass, mock_session):
    """Kill mutants 1, 2, 3, 4, 5 in load_from_yaml."""
    conn = ConnectionAiohttp8888(
        {"keep_alive": True, CONF_TOKEN: "tok"},
        mock_logger,
        mock_hass,
        mock_session,
        "192.168.1.100",
    )
    # 1. node is None -> returns True, _keep_alive unchanged
    res_none = conn.load_from_yaml(None, None)
    assert res_none is True
    assert conn._keep_alive is True

    # 2. node is empty dict -> returns True, _keep_alive unchanged
    res_empty = conn.load_from_yaml({}, None)
    assert res_empty is True
    assert conn._keep_alive is True

    # 3. node has "keep_alive": False -> returns True, _keep_alive becomes False
    res_false = conn.load_from_yaml({"keep_alive": False}, None)
    assert res_false is True
    assert conn._keep_alive is False

    # 4. node has "keep_alive": True -> returns True, _keep_alive becomes True
    res_true = conn.load_from_yaml({"keep_alive": True}, None)
    assert res_true is True
    assert conn._keep_alive is True


def test_is_async_native_and_is_push_supported(mock_logger, mock_hass, mock_session):
    """Kill mutants in is_async_native and is_push_supported properties."""
    conn = ConnectionAiohttp8888(
        {CONF_TOKEN: "tok"}, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    assert conn.is_async_native is True
    assert conn.is_push_supported is False


@pytest.mark.asyncio
async def test_try_connection_absolute_url_probe(mock_logger, mock_hass, mock_session):
    """Kill mutants at lines 272 and 274 in _try_connection for absolute URL probe."""
    conn = ConnectionAiohttp8888(
        {CONF_TOKEN: "tok", "use_http": True},
        mock_logger,
        mock_hass,
        mock_session,
        "192.168.1.100",
    )
    conn._params = {"url": "http://192.168.1.100:8888/custom_devices"}

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = '{"probe": "ok"}'
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context

    result = await conn._try_connection()

    assert result == '{"probe": "ok"}'
    mock_session.request.assert_called_once()
    args, kwargs = mock_session.request.call_args
    assert args[0] == "GET"
    assert args[1] == "http://192.168.1.100:8888/custom_devices"


@pytest.mark.asyncio
async def test_async_execute_embedded_template_sync_render(
    mock_session, mock_logger, mock_hass
):
    """Kill mutant at line 668 in async_execute where render() is called synchronously."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )

    embed_cmd = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )

    class SyncTemplate:
        def async_render(self, parse_result=False):
            return '{"method": "POST", "url": "/sync_embed", "json": {"a": 1}}'

    embed_cmd._connection_template = SyncTemplate()
    embed_cmd.check_execute_condition = MagicMock(return_value=True)
    embed_cmd.async_execute = AsyncMock()

    conn._embedded_command = embed_cmd
    conn._shared_state.initialized = True

    mock_response = AsyncMock(status=200, headers={})
    mock_response.text.return_value = "{}"
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context

    await conn.async_execute("GET", "/main", None, {}, device_state={"state": "on"})

    embed_cmd.async_execute.assert_called_once()
    call_kwargs = embed_cmd.async_execute.call_args[1]
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["url"] == "/sync_embed"
    assert call_kwargs["data"] == '{"a":1}'


def test_create_updated_dict_get_default_none(mock_logger, mock_hass, mock_session):
    """Kill PRUNED mutants at line 204 for Dict get default None in create_updated."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._params = {"existing": "val"}

    new_conn = conn.create_updated(
        {CONFIG_DEVICE_CONNECTION_PARAMS: {"new_param": "new_val"}}
    )

    assert new_conn._params == {"existing": "val", "new_param": "new_val"}
