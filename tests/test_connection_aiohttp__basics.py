# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ConnectionAiohttp8888."""

# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name
import logging
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.const import CONF_TOKEN

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONFIG_DEVICE_CONNECTION_PARAMS,
)
from custom_components.climate_ip.exceptions import AuthError, CannotConnect


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
        assert (
            kwargs["url"] == "https://192.168.1.100:8888/test"
        ), "La URL fue mutada o generada incorrectamente"

        # 2. Assert Payload
        assert "data" in kwargs, "The mutant removed kwarg data"
        assert kwargs["data"] is None, "Payload was mutated"

        # 3. Assert SSL Context
        assert "ssl" in kwargs, "The mutant removed kwarg ssl"
        assert (
            kwargs["ssl"] is conn._shared_state.ssl_context
        ), "Injected SSL context is incorrect or None"

        # 4. Assert Strict Timeout
        assert "timeout" in kwargs, "The mutant removed kwarg timeout"
        timeout = kwargs["timeout"]
        assert (
            timeout.total == 10
        ), f"The mutant altered timeout.total to {timeout.total}"

        # Blindaje de mutantes 45-56 (Cabeceras)
        req_headers = kwargs.get("headers", {})
        assert "Authorization" in req_headers, "Falta la cabecera Authorization"
        assert (
            req_headers["Authorization"] == f"Bearer {conn._token}"
        ), "Token incorrecto"
        assert "Content-Type" in req_headers, "Falta la cabecera Content-Type"
        assert (
            req_headers["Content-Type"] == "application/json"
        ), "Content-Type incorrecto"


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

    # 1. Initialization Assertions (Kills mutants altering None, False, or dictionaries)
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

    # 3. Shutdown and purge (Kills mutants altering "initialized" = False on reset)
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
    import logging
    from unittest.mock import MagicMock

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

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

    # 1. Full URL: Port replacement, HTTP downgrade, and placeholders
    # Kills mutants altering ":8888/" to "XX:8888/XX" or removing "use_http"
    url_base = (
        "https://__CLIMATE_IP_HOST__:8888/devices/__DEVICE_ID__?mac=__CLIMATE_IP_MAC__"
    )
    res = conn._build_full_url(url_base)
    assert res == "http://10.0.0.1:9999/devices/dev_123?mac=AA:BB"

    # 2. Host variable and placeholder replacement in _build_full_url
    conn._ip_address = "192.168.1.50"
    res2 = conn._build_full_url("https://__CLIMATE_IP_HOST__/status")
    assert res2 == "http://192.168.1.50/status"


# ====================================================================================
# FRENTE C: GENERACION DE SESIONES (_get_session)
# ====================================================================================


@pytest.mark.asyncio
async def test_get_session_args():
    """Valida los argumentos exactos pasados a aiohttp.TCPConnector."""
    import logging
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

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
    import logging
    import ssl
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

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
    """Validates strict cloning and condition templates."""
    import logging
    from unittest.mock import MagicMock

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from custom_components.climate_ip.const import CONFIG_DEVICE_CONNECTION

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
    """Tests that the engine adds Connection: close if force_close flag is active."""
    from unittest.mock import AsyncMock

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

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

    # Inject forced state (simulating previous failure)
    conn._force_close_connection = True

    # Upon execution, MUST inject close header
    await conn._async_execute_request(
        "GET", "https://192.168.1.100:8888/test", None, {}
    )

    _, kwargs = mock_session.request.call_args
    actual_headers = kwargs.get("headers", {})

    assert "Connection" in actual_headers, "The mutant deleted Connection header"
    assert (
        actual_headers["Connection"] == "close"
    ), "The mutant altered Connection: close value"


def test_format_url_strict_evaluations():
    """Validates mutants targeting URL formation, HTTP fallback, and port replacement."""
    import logging
    from unittest.mock import MagicMock

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

    config = {
        "host": "192.168.1.50",
        "mac": "AA:BB:CC:DD",
        "token": "tok123",
        "port": "9999",  # Custom port to catch the mutant
        "use_http": True,  # Enables HTTP to catch the mutant
    }

    # Mocked constructor
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=None,
        ip_address="192.168.1.50",
    )
    conn._params = config

    # 1. Basic placeholders test
    url_base = "https://__CLIMATE_IP_HOST__/devices/__CLIMATE_IP_MAC__"
    formatted = conn._build_full_url(url_base)

    # Validate replacement and change to HTTP
    assert (
        "http://192.168.1.50/devices/AA:BB:CC:DD" in formatted
    ), "Mutant survived altering host/mac injection or HTTP fallback"

    # 2. Custom port test (:8888/ -> :9999/) and strict HTTP fallback
    url_port = "https://192.168.1.50:8888/devices/__CLIMATE_IP_MAC__"
    formatted_port = conn._build_full_url(url_port)

    # ASERCIONES ESTRICTAS (Matan mutantes 33, 42, 53, 56)
    assert (
        formatted_port == "http://192.168.1.50:9999/devices/AA:BB:CC:DD"
    ), "Port or protocol replacement failure"


async def test_adaptive_keep_alive_on_timeout_recovery(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Testea que el motor cambia a force_close y reintenta tras un ClientError."""
    from unittest.mock import AsyncMock

    import aiohttp

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

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

    # Make mock fail first time and succeed second time
    mock_session.request.side_effect = [
        aiohttp.ClientConnectorError(None, OSError("Mocked Error")),
        mock_context,  # Segunda vez funciona
    ]

    await conn._async_execute_request(
        "GET", "https://192.168.1.100:8888/test", None, {}
    )

    # Verify retry occurred
    assert mock_session.request.call_count == 2

    # Verify second attempt carried lifeline header
    retry_kwargs = mock_session.request.call_args_list[1][1]
    assert "Connection" in retry_kwargs["headers"]
    assert retry_kwargs["headers"]["Connection"] == "close"

    # And internal state updated to persist closure on subsequent calls
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

        # Create clone with new parameters
        new_conn = base_conn.create_updated({"keep_alive": False})

        # ASERCIONES ESTRICTAS DE MEMORIA
        assert (
            new_conn._controller == "MockControllerRef"
        ), "Perdió la referencia al controlador"
        assert (
            new_conn._shared_state is base_conn._shared_state
        ), "Perdió el estado compartido"
        assert new_conn._keep_alive is False, "No actualizó el parámetro hijo"


async def test_execution_uses_controller_token_priority(
    connection_config, mock_logger, mock_hass, mock_session
):
    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

    with patch("os.path.exists", return_value=True):
        # Connection with a base token
        conn = ConnectionAiohttp8888(
            config={"token": "TOKEN_BASE"},
            logger=mock_logger,
            hass=mock_hass,
            session=mock_session,
            ip_address="192.168.1.100",
        )
        conn._shared_state.initialized = True
        conn._shared_state.ssl_context = None

        # Inject controller with dominant token
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

        await conn._async_execute_request(
            "GET", "https://192.168.1.100:8888/test", None, {}
        )

        # STRICT ASSERTION
        _, kwargs = mock_session.request.call_args
        actual_headers = kwargs.get("headers", {})

        assert (
            actual_headers["Authorization"] == "Bearer TOKEN_DOMINANTE"
        ), "Did not use controller token"


async def test_http_1_0_forces_connection_close(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Tests that an old server forces connection closure."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.version = MagicMock(major=1, minor=0)  # SIMULATE HTTP 1.0
        mock_response.headers = {}
        mock_response.text.return_value = "{}"
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        await conn._async_execute_request(
            "GET", "https://192.168.1.100:8888/test", None, {}
        )

        assert (
            conn._force_close_connection is True
        ), "The mutant altered HTTP minor >= 1 validation"


async def test_absolute_url_skips_base_url_formatting(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Tests that an absolute URL ignores base formatting and SSL."""
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
        assert (
            kwargs["url"] == "http://external-api.com/path"
        ), "The mutant broke startswith('http') detection"
        assert kwargs["ssl"] is False, "The mutant used SSL in a plain HTTP connection"


async def test_async_execute_request_respects_custom_headers(
    mock_session, mock_logger, mock_hass
):
    """Guarantees manually injected headers are not overwritten."""
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

    await conn._async_execute_request(
        "GET", "https://1.1.1.1:8888/test", None, headers=custom_headers
    )

    _, kwargs = mock_session.request.call_args
    assert (
        kwargs["headers"]["Authorization"] == "Bearer TOKEN_CUSTOM"
    ), "The mutant overwrote Auth header"
    assert (
        kwargs["headers"]["Content-Type"] == "text/xml"
    ), "The mutant overwrote the Content-Type"


async def test_retry_request_kwargs_strict(mock_session, mock_logger, mock_hass):
    """Requires that retry after failure passes EXACTLY the same parameters to the network."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )

    # Simulate failure on 1st attempt, success on 2nd
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

    await conn._async_execute_request(
        "POST", "https://1.1.1.1:8888/test", "payload_secreto", {"H": "1"}
    )

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

    # Call WITHOUT _is_poll argument
    await conn.async_execute("GET", "/test", None, {})

    # If mutmut changed default to True, session will close and test will fail
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
    # Simulate template returning config JSON
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

    # Verify what was passed to embedded command
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
    """Tests that if the controller has no token, the base connection token is used."""
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

    await conn._async_execute_request(
        "GET", "https://192.168.1.100:8888/test", None, {}
    )

    _, kwargs = mock_session.request.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer BASE_TOKEN"


# ====================================================================================
# TACTIC 1: THE dict.get() TRAP — Strict key extraction validation
# ====================================================================================


def test_format_url_strict_dict_extraction():
    """Validates that _format_url extracts exactly configured keys (not string variations).

    Mutmut survives changing self._params.get(CONF_MAC) to self._params.get(None)
    or self._ip_address or self._params.get(CONF_HOST) to variants. This test
    uses asymmetric and unrepeatable values so any key alteration fails.
    """
    import logging

    from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, CONF_TOKEN

    # ASYMMETRIC values: each is unique and unrepeatable to detect swaps
    config = {
        CONF_HOST: "10.0.0.1",
        CONF_MAC: "00:11:22:33:44:55",
        CONF_PORT: "7777",
        "use_http": False,
        CONF_TOKEN: "tok_BASE_unique",
    }

    # Explicit IP Address: forces precedence over CONF_HOST in _resolved_target
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="192.168.1.100",
    )
    # _params simulates what create_updated() would inject from YAML
    conn._params = {
        CONF_HOST: "10.0.0.1",
        CONF_MAC: "00:11:22:33:44:55",
    }

    # Controller with dominant token and device_id
    mock_controller = MagicMock()
    mock_controller.device_id = "device_xyz"
    mock_controller._config = {CONF_TOKEN: "tok_CONTROLLER_dominant"}
    conn.set_controller_ref(mock_controller)

    # URL with ALL real placeholders
    base_url = (
        "https://__CLIMATE_IP_HOST__:8888"
        "/api/__CLIMATE_IP_MAC__"
        "/token/__CLIMATE_IP_TOKEN__"
        "/device/__DEVICE_ID__"
    )

    formatted = conn._format_url(base_url)

    # EXTREME ASSERTION: Each segment must match to the millimeter
    # - Host: IP address (192.168.1.100) HAS PRECEDENCE over config host (10.0.0.1)
    # - Port: :8888/ → :7777/ due to CONF_PORT replacement
    # - Mac: directly from _params[CONF_MAC]
    # - Token: from controller (tok_CONTROLLER_dominant) NOT from config (tok_BASE_unique)
    # - Device ID: from controller device_id
    expected_url = (
        "https://192.168.1.100:7777"
        "/api/00:11:22:33:44:55"
        "/token/tok_CONTROLLER_dominant"
        "/device/device_xyz"
    )

    assert formatted == expected_url, (
        f"Mutated formatting failed.\n"
        f"  Expected:  {expected_url}\n"
        f"  Received:  {formatted}"
    )


def test_resolved_target_ip_precedence_over_config_host():
    """Validates property _resolved_target: ip_address ALWAYS wins over params[CONF_HOST]."""
    import logging

    from homeassistant.const import CONF_HOST, CONF_MAC

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

    assert host == "WINNER_IP", f"ip_address had no precedence: host={host}"
    assert mac == "MAC_VALUE", f"MAC was not extracted correctly: mac={mac}"


def test_resolved_target_uses_ip_address_directly():
    """Validates that _resolved_target uses ip_address directly."""
    import logging

    from homeassistant.const import CONF_MAC

    conn = ConnectionAiohttp8888(
        config={},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="192.168.1.100",
    )
    conn._params = {CONF_MAC: "FB:MA:CC"}

    host, mac = conn._resolved_target

    assert host == "192.168.1.100"
    assert mac == "FB:MA:CC"


def test_resolved_target_missing_keys_return_empty_strings():
    """Validates that missing keys in _params return empty strings, NOT None."""
    import logging

    conn = ConnectionAiohttp8888(
        config={},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address=None,
    )
    conn._params = {}  # Empty dictionary → everything must be ""

    host, mac = conn._resolved_target

    assert host == "", f"Host should be '' but is {host!r}"
    assert mac == "", f"MAC should be '' but is {mac!r}"
    assert isinstance(host, str), "Host must be str, not None"
    assert isinstance(mac, str), "MAC must be str, not None"


def test_format_url_port_replacement_only_on_8888():
    """Validates port replacement ONLY occurs when ':8888/' is present in URL."""
    import logging

    config = {CONF_TOKEN: "tok", "port": "9999"}
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="1.2.3.4",
    )

    # URL WITHOUT :8888/ → port MUST NOT change
    url_no_port = "https://1.2.3.4:1234/devices"
    result = conn._format_url(url_no_port)
    assert ":1234/" in result, f"Port was replaced when it should not be: {result}"
    assert ":9999/" not in result, f"Spurious port replacement: {result}"

    # URL WITH :8888/ → port MUST change to 9999
    url_with_port = "https://1.2.3.4:8888/devices"
    result2 = conn._format_url(url_with_port)
    assert ":9999/" in result2, f"Port 8888 was not replaced: {result2}"
    assert ":8888/" not in result2, f"Old port remained: {result2}"


def test_format_url_strict_defaults_and_http_downgrade():
    """Validates pure defaults: Port 8888 by default and downgrade to HTTP."""
    import logging

    # 1. EMPTY CONFIG: Force code to use .get(key, DEFAULT)
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

    # DEFAULTS ASSERTION: Verify mutant kill changing "8888" or "False"
    assert formatted.startswith(
        "https://"
    ), "Mutant altered use_http default (False)"
    assert ":8888/" in formatted, "Mutant altered default port (8888)"

    # 2. HTTP CONFIG: Validate explicit downgrade
    conn._config["use_http"] = True
    formatted_http = conn._build_full_url(base_url)

    # Kills mutant breaking replacement logic "https://" -> "http://"
    assert formatted_http.startswith(
        "http://"
    ), "Mutant broke downgrade to plain HTTP"


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
    """Validates that in plain HTTP mode, TCPConnector is created WITHOUT the ssl parameter."""
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
        # Timeout and Session identical in both branches
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

        # MUST return injected session, NOT create a new one
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

    # Simulate closed session
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

        # MUST have created new session because previous was closed
        mock_session_cls.assert_called_once()
        assert (
            conn._shared_state.local_session is fresh_session
        ), "No reemplazó la sesión cerrada"


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

    # Simulate HEALTHY AND OPEN local session
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

        # ASSERTION: Must return existing session without calling aiohttp classes
        assert result is healthy_session, "No reutilizó la sesión local sana"
        mock_connector.assert_not_called()
        mock_timeout.assert_not_called()
        mock_session_cls.assert_not_called()


@pytest.mark.asyncio
async def test_get_session_fallback_when_shared_session_is_none():
    """Valida el fallback defensivo: keep_alive=True pero session=None."""
    import logging

    # Configure keep_alive=True but intentionally omit session
    conn = ConnectionAiohttp8888(
        config={"keep_alive": True},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=None,  # <--- ¡LA TRAMPA PARA MUTMUT!
        ip_address="10.0.0.1",
    )
    conn._shared_state.local_session = None

    # Patch creation to verify local fallback triggers
    _NS = "custom_components.climate_ip.connection_aiohttp.aiohttp"
    with (
        patch(f"{_NS}.TCPConnector"),
        patch(f"{_NS}.ClientTimeout"),
        patch(f"{_NS}.ClientSession") as mock_session_cls,
    ):
        # Use in-memory traceability trick
        mock_session_cls.return_value = "fallback_local_session_obj"

        result = await conn._get_session()

        # EXTREME ASSERTION: Despite keep_alive=True, had to create local session
        mock_session_cls.assert_called_once()
        assert (
            result == "fallback_local_session_obj"
        ), "El fallback a sesión local falló"


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

    # Prepare main session for main command
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    # Embedded: WITHOUT template, WITH direct _params
    # ASYMMETRIC values to detect any key swapping
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

    # Verify exact kwargs passed to embedded command engine
    embed_mock.async_execute.assert_called_once()
    kwargs = embed_mock.async_execute.call_args[1]

    # MILLIMETRIC ASSERTIONS — kills mutants altering .get() keys
    assert (
        kwargs["method"] == "DELETE"
    ), f"The mutant altered key 'method' in .get(): received {kwargs['method']}"
    assert (
        kwargs["url"] == "/override_url"
    ), f"The mutant altered key 'url' in .get(): received {kwargs['url']}"
    assert kwargs["data"] == json_dumps(
        {"override": "yes"}
    ), f"The mutant altered key 'json' or json_dumps: received {kwargs['data']}"
    assert kwargs["headers"] == {
        "Custom": "Header"
    }, f"The mutant altered key 'headers' in .get(): received {kwargs['headers']}"
    assert kwargs["device_state"] == {
        "state": "on"
    }, "The mutant altered device_state propagation to embedded"


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

    # Embedded MUST NOT have executed because params was empty
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
    # _params WITHOUT "method" or "url" → must inherit from main command
    embed_mock.params = {"json": {"action": "toggle"}}
    conn._embedded_command = embed_mock

    await conn.async_execute("PUT", "/main_url", None, {}, device_state={"state": "on"})

    embed_mock.async_execute.assert_called_once()
    kwargs = embed_mock.async_execute.call_args[1]

    # FALLBACK: If embedded defines neither method nor url, uses main command's
    assert (
        kwargs["method"] == "PUT"
    ), f"El fallback de 'method' está roto: recibido {kwargs['method']}"
    assert (
        kwargs["url"] == "/main_url"
    ), f"El fallback de 'url' está roto: recibido {kwargs['url']}"
    assert kwargs["data"] == json_dumps(
        {"action": "toggle"}
    ), f"El json_dumps del payload del embebido falló: {kwargs['data']}"


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

    # TRICK: Irrelevant key so bool(_params) is True
    # but intentionally omit 'method', 'url', 'json', and 'headers'
    embed_mock.params = {"dummy_key": "force_execution"}
    conn._embedded_command = embed_mock

    # Execute main with NON-empty headers → if fallback mutates to None, test fails
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

    # EXTREME FALLBACK ASSERTIONS
    assert (
        kwargs["method"] == "PUT"
    ), f"Mutant broke method fallback: {kwargs['method']}"
    assert (
        kwargs["url"] == "/main_url"
    ), f"Mutant broke url fallback: {kwargs['url']}"
    assert kwargs["headers"] == {
        "Main-Header": "Present"
    }, f"Mutant broke headers fallback: {kwargs['headers']}"
    # "json" is not in _params → `else None` must produce data=None
    assert (
        kwargs["data"] is None
    ), f"Mutant altered 'else None' when 'json' is missing in _params: {kwargs['data']}"


# ====================================================================================
# TACTIC 3 — IMPROVEMENT 2: _is_poll Truth Table (Kills mutants 134-137)
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

    # OPEN local session so closure is observable
    mock_local = AsyncMock()
    mock_local.closed = False
    conn._shared_state.local_session = mock_local

    # Main session mock so _async_execute_request doesn't blow up
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_response.version = None
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx
    # Also prepare local session for request following closure
    mock_local.request.return_value = mock_ctx

    # Patch _async_execute_request to isolate _is_poll logic only
    with patch.object(
        conn, "_async_execute_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = ("{}", {})

        await conn.async_execute("GET", "/test", None, {}, _is_poll=is_poll)

        if should_close:
            # CASO 1: debe haber llamado a close() y reseteado local_session a None
            mock_local.close.assert_called_once()
            assert (
                conn._shared_state.local_session is None
            ), f"Estado no reseteado a None (is_poll={is_poll}, keep_alive={keep_alive})"
        else:
            # CASOS 2, 3, 4: NO debe haber cerrado nada
            mock_local.close.assert_not_called()
            assert (
                conn._shared_state.local_session is mock_local
            ), f"Sesión local borrada indebidamente (is_poll={is_poll}, keep_alive={keep_alive})"


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

    # Inject local session so _get_session returns it without creating a new one.
    # IMPORTANT: MagicMock (not AsyncMock) because `async with session.request(...)` expects
    # a direct context manager, not a coroutine.
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

    # DO NOT patch _create_ssl_context: if logic tries to create it, test will fail
    with patch.object(
        conn, "_create_ssl_context", new_callable=AsyncMock
    ) as mock_ssl_create:
        await conn._try_connection()

        # SSL MUST NOT have been created in HTTP mode
        mock_ssl_create.assert_not_called()

    mock_local_session.request.assert_called_once()
    args, kwargs = mock_local_session.request.call_args

    # MILLIMETRIC ASSERTIONS
    assert (
        args[1] == "http://192.168.1.50:1234"
    ), f"Mutant altered protocol or port: {args[1]}"
    assert (
        kwargs["ssl"] is False
    ), f"Mutant altered ssl=False for HTTP: {kwargs['ssl']}"
    assert (
        conn._shared_state.ssl_context is None
    ), "The mutant ignored `if not use_http` and created SSL context"

    # Assertion of probe timeout (total=10, sock_read=5)
    timeout_obj = kwargs.get("timeout")
    assert timeout_obj is not None, "Mutant removed probe timeout argument"
    assert (
        timeout_obj.total == 10
    ), f"Mutant altered timeout.total in _try_connection: {timeout_obj.total}"
    assert (
        timeout_obj.sock_read == 5
    ), f"Mutant altered timeout.sock_read in _try_connection: {timeout_obj.sock_read}"


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
        f"Failure in HTTP/{major}.{minor} (start_forced={start_forced}): "
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
        "PATCH",
        "https://1.1.1.1:8888/strict_url",
        "strict_payload",
        {"Header": "Strict"},
    )

    mock_session.request.assert_called_once()
    args, kwargs = mock_session.request.call_args

    # Positional method
    assert args[0] == "PATCH", f"Mutant altered method: {args[0]}"
    # Correctly built URL
    assert (
        kwargs["url"] == "https://1.1.1.1:8888/strict_url"
    ), f"Mutant altered URL: {kwargs['url']}"
    # Payload
    assert (
        kwargs["data"] == "strict_payload"
    ), f"Mutant altered payload: {kwargs['data']}"
    # Custom header preserved
    assert (
        kwargs["headers"]["Header"] == "Strict"
    ), f"Mutant altered header: {kwargs['headers']}"
    # SSL correctly injected
    assert (
        kwargs["ssl"] is conn._shared_state.ssl_context
    ), f"Mutant altered ssl context: {kwargs['ssl']}"

    # MILLIMETRIC TIMEOUT ASSERTION (total=10, without sock_read)
    timeout_obj = kwargs.get("timeout")
    assert timeout_obj is not None, "Mutant removed timeout argument"
    assert isinstance(
        timeout_obj, aiohttp.ClientTimeout
    ), f"Mutant changed timeout type: {type(timeout_obj)}"
    assert (
        timeout_obj.total == 10
    ), f"Mutant altered timeout.total: expected 10, received {timeout_obj.total}"


@pytest.mark.asyncio
async def test_async_execute_request_none_http_version(
    mock_session, mock_logger, mock_hass
):
    """Verify mutant kill altering `and response.version` validating logger silence."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._force_close_connection = False  # So that first condition of if passes

    mock_response = AsyncMock(status=200, headers={})
    mock_response.text.return_value = "{}"
    mock_response.version = None  # THE TRAP FOR MUTMUT!

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_ctx

    await conn._async_execute_request("GET", "https://1.1.1.1:8888/test", None, {})

    # MILLIMETRIC ASSERTION
    assert (
        conn._force_close_connection is True
    ), "Should force close if no version"
    # Verify logger.debug was NOT called with version message
    for call in mock_logger.debug.call_args_list:
        assert (
            "Server speaks HTTP" not in call[0][0]
        ), "The mutant evaluated True on `and response.version` when it was None"


@pytest.mark.asyncio
async def test_async_execute_request_absolute_url(mock_session, mock_logger, mock_hass):
    """Tests that passing an absolute URL ignores base_url and is used as is."""
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

    # Pass an absolute URL
    absolute_url = "http://external-api.local:9999/status"
    await conn._async_execute_request("GET", absolute_url, None, {})

    mock_session.request.assert_called_once()
    _, kwargs = mock_session.request.call_args

    # STRICT ASSERTION: URL must be strictly absolute, without concatenating base IP
    assert (
        kwargs["url"] == absolute_url
    ), f"The mutant broke startswith('http'): {kwargs['url']}"
    # As it is http://, ssl must automatically disable at end
    assert kwargs["ssl"] is False, "The mutant did not disable SSL for plain http URL"


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
        # If mutmut removes tuple code, this raises CannotConnect and test fails
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

    # 2. Configure Controller with dominant Token
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

    # MILLIMETRIC ASSERTIONS
    assert (
        kwargs["headers"]["Authorization"] == "Bearer CTRL_TOK"
    ), "Mutant broke controller token fallback"
    assert (
        args[1] == "https://1.1.1.1:7777"
    ), "Mutant broke port in _try_connection"


@pytest.mark.asyncio
async def test_async_execute_request_header_placeholders(
    mock_session, mock_logger, mock_hass
):
    """Kills mutants of format_placeholders applied to headers."""
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

    # Inject pure placeholders in headers
    custom_headers = {
        "X-Mac": "__CLIMATE_IP_MAC__",
        "X-Dev": "__DEVICE_ID__",
        "X-Tok": "__CLIMATE_IP_TOKEN__",
    }

    await conn._async_execute_request(
        "GET", "https://1.1.1.1:8888/test", None, custom_headers
    )

    _, kwargs = mock_session.request.call_args
    assert kwargs["headers"]["X-Mac"] == "AA:BB", "Mutant broke placeholder {mac}"
    assert (
        kwargs["headers"]["X-Dev"] == "DEV_123"
    ), "Mutant broke placeholder {device_id}"
    assert kwargs["headers"]["X-Tok"] == "tok", "Mutant broke placeholder {token}"


@pytest.mark.asyncio
async def test_async_execute_skips_optimization_on_mismatch(
    mock_session, mock_logger, mock_hass
):
    """Kills mutants of 'if probe_response_text and method == GET and url == /devices'."""
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

        # Case 1: Incorrect Method (POST instead of GET)
        res1, _ = await conn.async_execute("POST", "", None, {})
        assert (
            res1 == "REQ_OK"
        ), "The mutant wrongly activated optimization for POST"
        mock_req.assert_called_with("POST", "https://1.1.1.1:8888", None, {})

        mock_req.reset_mock()

        # Case 2: Incorrect URL (/other instead of /devices)
        res2, _ = await conn.async_execute("GET", "/other", None, {})
        assert (
            res2 == "REQ_OK"
        ), "The mutant wrongly activated optimization for different URL"
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
