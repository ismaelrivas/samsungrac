# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,too-many-lines,too-many-locals,use-implicit-booleaness-not-comparison,missing-function-docstring,too-many-arguments,too-many-positional-arguments,too-few-public-methods,missing-class-docstring
"""Tests for ConnectionAiohttp8888."""

from http import HTTPStatus
import logging
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import (
    AuthError,
    CannotConnect,
    InvalidHeaderError,
)
from homeassistant.const import CONF_TOKEN


class StubHass:
    def __init__(self):
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
        self.closed = False
        self.request = MagicMock(spec=["__call__", "return_value"])
        self.close = AsyncMock(spec=["__call__", "return_value"])

    def __repr__(self):
        return "<SafeSession>"

    def __dir__(self):
        return ["closed", "request", "close"]


@pytest.fixture
def mock_logger():
    """Return a mock Logger instance."""
    return logging.getLogger("test_logger")


@pytest.fixture
def mock_hass():
    """Return a mock HomeAssistant instance."""
    return StubHass()


@pytest.fixture
def mock_session():
    """Return a mock aiohttp ClientSession."""
    return StubSession()


@pytest.fixture
def connection_config():
    """Return a basic connection config dict."""
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}


async def test_aiohttp_initialization(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test connection initialization."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        assert conn._ip_address == "192.168.1.100"
        assert conn._token == "test_token"
        assert conn._raw_cert_path == "cert.pem"
        assert conn._shared_state.initialized is False
        assert conn.async_lock is not None  # Verify parent created lock
        assert ConnectionAiohttp8888.match_type("samsung_8888_aiohttp") is True
        assert ConnectionAiohttp8888.match_type("invalid_type") is False


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
        conn._force_close_connection = True

        conn_err = aiohttp.ClientConnectorError(
            aiohttp.client_reqrep.ConnectionKey(
                "192.168.1.100", 8888, False, False, None, None, None
            ),
            OSError("Connection refused"),
        )
        mock_session.request.side_effect = conn_err

        with pytest.raises(CannotConnect) as exc_info:
            await conn.async_execute("GET", "/test", None, None)

        assert "Cannot connect to 192.168.1.100:8888 (Connection refused)" in str(
            exc_info.value
        )


async def test_aiohttp_create_updated(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test create_updated method thoroughly across all branches."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._params = {"test": "param"}
        conn._force_close_connection = True
        conn._cert_path = "/path/to/cert.pem"

        # 1. Test with None node
        new_conn_none = conn.create_updated(None)
        assert isinstance(new_conn_none, ConnectionAiohttp8888)
        assert new_conn_none is not conn
        assert new_conn_none._params == {"test": "param"}
        assert new_conn_none._force_close_connection is True
        assert new_conn_none._cert_path == "/path/to/cert.pem"
        assert new_conn_none._shared_state is conn._shared_state

        # 2. Test with empty node
        new_conn = conn.create_updated({})
        assert isinstance(new_conn, ConnectionAiohttp8888)
        assert new_conn is not conn
        assert new_conn._params == {"test": "param"}
        assert new_conn._hass is mock_hass
        assert new_conn._session is mock_session
        assert new_conn._logger is mock_logger
        assert new_conn._ip_address == "192.168.1.100"

        # 3. Test with keep_alive override
        new_conn_ka = conn.create_updated({"keep_alive": False})
        assert new_conn_ka._keep_alive is False

        # 4. Test with params
        yaml_node = {"params": {"new": "value"}}
        new_conn_params = conn.create_updated(yaml_node)
        assert new_conn_params._params == {"test": "param", "new": "value"}

        # 5. Test with params as None (explicit fallback)
        yaml_node_p_none = {"params": None}
        new_conn_p_none = conn.create_updated(yaml_node_p_none)
        assert new_conn_p_none._params == {"test": "param"}

        # 6. Test with connection_template
        yaml_node_tmpl = {"connection_template": "{{ test }}"}
        new_conn_tmpl = conn.create_updated(yaml_node_tmpl)
        assert new_conn_tmpl._connection_template is not None
        assert new_conn_tmpl._connection_template.template == "{{ test }}"
        assert new_conn_tmpl._connection_template.hass is mock_hass

        # 7. Test with nested embedded connection AND condition_template
        yaml_node_nested = {
            "connection": {
                "params": {"nested": "val"},
                "condition_template": "{{ is_state('climate.ac', 'off') }}",
            }
        }
        new_conn_nested = conn.create_updated(yaml_node_nested)
        assert new_conn_nested._embedded_command is not None
        assert isinstance(new_conn_nested._embedded_command, ConnectionAiohttp8888)
        assert new_conn_nested._embedded_command._params == {
            "test": "param",
            "nested": "val",
        }
        assert new_conn_nested._embedded_command.condition_template is not None
        assert (
            new_conn_nested._embedded_command.condition_template.template
            == "{{ is_state('climate.ac', 'off') }}"
        )
        assert new_conn_nested._embedded_command.condition_template.hass is mock_hass

        # 8. Test with nested embedded connection WITHOUT condition_template
        yaml_node_nested_no_cond = {
            "connection": {
                "params": {"nested2": "val2"},
            }
        }
        new_conn_nested_no_cond = conn.create_updated(yaml_node_nested_no_cond)
        assert new_conn_nested_no_cond._embedded_command is not None
        assert new_conn_nested_no_cond._embedded_command.condition_template is None


def test_prepare_request_headers_unit(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Direct unit test for _prepare_request_headers to instantly kill all header mutants."""
    conn = ConnectionAiohttp8888(
        connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )

    # 1. Standard headers with None input
    headers = conn._prepare_request_headers(
        headers=None,
        current_token="my_token",
        host="192.168.1.100",
        dev_id="dev123",
        mac="AA:BB:CC:DD:EE:FF",
    )
    assert headers["Authorization"] == "Bearer my_token"
    assert headers["Content-Type"] == "application/json"
    assert "Connection" not in headers

    # 2. Force close connection active
    conn._force_close_connection = True
    headers_close = conn._prepare_request_headers(
        headers={"Custom": "Header"},
        current_token="my_token",
        host="192.168.1.100",
        dev_id="dev123",
        mac="AA:BB:CC:DD:EE:FF",
    )
    assert headers_close["Authorization"] == "Bearer my_token"
    assert headers_close["Content-Type"] == "application/json"
    assert headers_close["Custom"] == "Header"
    assert headers_close["Connection"] == "close"

    # 3. Missing token raises AuthError
    with pytest.raises(AuthError):
        conn._prepare_request_headers(
            headers=None,
            current_token=None,
            host="192.168.1.100",
            dev_id="dev123",
            mac="AA:BB:CC:DD:EE:FF",
        )


# ====================================================================================
# SECTION A: LIFECYCLE AND SHARED STATE (__init__, close, get_diagnostics)
# ====================================================================================


@pytest.mark.asyncio
async def test_aiohttp_lifecycle_and_shared_state():
    """Validate default states, diagnostics, and atomic session teardown."""
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

    # 2. Strict diagnostics (Kills mutants on .get("initialized", False))
    diag = conn.get_diagnostics()
    assert diag["is_connected"] is False
    assert diag["force_close_connection"] is False
    assert diag["keep_alive_enabled"] is False

    # 3. Shutdown and purge (Kills mutants altering "initialized" = False on reset)
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = "FAKE_SSL"
    conn._shared_state.local_session = AsyncMock()  # Simulate a local session
    conn._shared_state.local_session.closed = False
    conn._force_close_connection = True

    await conn.close()

    assert conn._shared_state.initialized is False
    assert conn._shared_state.ssl_context is None
    assert conn._shared_state.local_session is None
    assert conn._force_close_connection is False


# ====================================================================================
# SECTION B: URL FORMATTING AND REPLACEMENT (_format_url)
# ====================================================================================


# ====================================================================================
# SECTION C: SESSION GENERATION (_get_session)
# ====================================================================================


@pytest.mark.asyncio
async def test_get_session_args():
    """Validate exact arguments passed to aiohttp.TCPConnector."""
    import logging
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888

    config = {"use_http": True, CONF_TOKEN: "test_token"}
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
# SECTION D: CLONING AND CRYPTOGRAPHY (create_updated and _create_ssl_context)
# ====================================================================================


@pytest.mark.asyncio
async def test_create_ssl_context_strict():
    """Validate security flags, cert resolution, and strict ciphers."""
    import logging
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.connection_aiohttp import (
        DEFAULT_SSL_CIPHERS,
        ConnectionAiohttp8888,
    )

    # 1. Insecure SSL mode on local host
    config = {"insecure_ssl": True, CONF_TOKEN: "test_token"}
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

    # 2. Remote host without cert and insecure_ssl=False returns None
    conn_remote = ConnectionAiohttp8888(
        {CONF_TOKEN: "test_token"},
        logging.getLogger(),
        MagicMock(),
        MagicMock(),
        "8.8.8.8",
    )
    assert await conn_remote._create_ssl_context() is None

    # 3. Remote host with cert resolves path and passes it to async_create_samsung_ssl_context
    mock_hass = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock(return_value="/resolved/my_cert.pem")
    conn_cert = ConnectionAiohttp8888(
        {CONF_TOKEN: "test_token", CONF_CERT: "my_cert.pem"},
        logging.getLogger(),
        mock_hass,
        MagicMock(),
        "8.8.8.8",
    )
    with patch(
        "custom_components.climate_ip.connection_aiohttp.async_create_samsung_ssl_context"
    ) as mock_ssl_cert:
        mock_ctx = MagicMock(spec=ssl.SSLContext)
        mock_ssl_cert.return_value = mock_ctx
        res_ctx = await conn_cert._create_ssl_context()
        assert res_ctx is mock_ctx
        assert conn_cert._cert_path == "/resolved/my_cert.pem"
        mock_ssl_cert.assert_called_once_with(
            cert_path="/resolved/my_cert.pem",
            ciphers=DEFAULT_SSL_CIPHERS,
            verify_mode=ssl.CERT_NONE,
        )

    # 4. Localhost string marker requires lower() matching to be recognized as local
    conn_localhost = ConnectionAiohttp8888(
        {CONF_TOKEN: "test_token"},
        logging.getLogger(),
        mock_hass,
        MagicMock(),
        "localhost",
    )
    with patch(
        "custom_components.climate_ip.connection_aiohttp.async_create_samsung_ssl_context"
    ) as mock_ssl_local:
        mock_ssl_local.return_value = MagicMock(spec=ssl.SSLContext)
        assert await conn_localhost._create_ssl_context() is not None

    # 5. Remote host with insecure_ssl=True creates SSL context via CONF_INSECURE_SSL key
    conn_insecure_remote = ConnectionAiohttp8888(
        {"insecure_ssl": True, CONF_TOKEN: "test_token"},
        logging.getLogger(),
        mock_hass,
        MagicMock(),
        "8.8.8.8",
    )
    with patch(
        "custom_components.climate_ip.connection_aiohttp.async_create_samsung_ssl_context"
    ) as mock_ssl_insecure:
        mock_insecure_ctx = MagicMock(spec=ssl.SSLContext)
        mock_ssl_insecure.return_value = mock_insecure_ctx
        assert await conn_insecure_remote._create_ssl_context() is mock_insecure_ctx


def test_aiohttp_create_updated_strict():
    """Validates strict cloning and condition templates."""
    import logging
    from unittest.mock import MagicMock

    from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
    from custom_components.climate_ip.const import CONFIG_DEVICE_CONNECTION

    config = {CONF_TOKEN: "test_token"}
    conn = ConnectionAiohttp8888(
        config, logging.getLogger(), MagicMock(), MagicMock(), "10.0.0.1"
    )
    conn._params = {"base": 1}

    yaml_node = {
        "connection_template": "{{ top_level }}",
        "keep_alive": True,
        CONFIG_DEVICE_CONNECTION: {
            "params": {"child": 2},
            "condition_template": "{{ True }}",
        },
    }

    new_conn = conn.create_updated(yaml_node)

    # Must preserve the base parameter but NOT leak the child parameter to the root
    assert new_conn._params == {"base": 1}
    assert new_conn._keep_alive is True
    assert new_conn._connection_template is not None
    assert new_conn._connection_template.template == "{{ top_level }}"

    # The embedded command must receive the child parameter since it lacks connection_template
    assert new_conn._embedded_command is not None
    assert new_conn._embedded_command._params == {"base": 1, "child": 2}
    assert new_conn._embedded_command._connection_template is None

    # Check condition template was compiled with exact template string
    assert new_conn._embedded_command.condition_template is not None
    assert new_conn._embedded_command.condition_template.template == "{{ True }}"


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
    assert actual_headers["Connection"] == "close", (
        "The mutant altered Connection: close value"
    )


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
    assert "http://192.168.1.50/devices/AA:BB:CC:DD" in formatted, (
        "Mutant survived altering host/mac injection or HTTP fallback"
    )

    # 2. Custom port test (:8888/ -> :9999/) and strict HTTP fallback
    url_port = "https://192.168.1.50:8888/devices/__CLIMATE_IP_MAC__"
    formatted_port = conn._build_full_url(url_port)

    # STRICT ASSERTIONS (Kill mutants 33, 42, 53, 56)
    assert formatted_port == "http://192.168.1.50:9999/devices/AA:BB:CC:DD", (
        "Port or protocol replacement failure"
    )


async def test_adaptive_keep_alive_on_timeout_recovery(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test that engine switches to force_close and retries after a ClientError."""
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

    fake_ssl = MagicMock()
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = fake_ssl

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = '{"retry": "success"}'
    mock_response.headers = {}
    mock_response.raise_for_status = AsyncMock()
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response

    # Make mock fail first time and succeed second time
    mock_session.request.side_effect = [
        aiohttp.ClientConnectorError(None, OSError("Mocked Error")),
        mock_context,  # Segunda vez funciona
    ]

    res_text, _ = await conn._async_execute_request(
        "GET", "https://192.168.1.100:8888/test", None, {}
    )
    assert res_text == '{"retry": "success"}'

    # Verify retry occurred
    assert mock_session.request.call_count == 2

    # Verify second attempt carried lifeline header and ssl
    retry_kwargs = mock_session.request.call_args_list[1][1]
    assert "Connection" in retry_kwargs["headers"]
    assert retry_kwargs["headers"]["Connection"] == "close"
    assert "ssl" in retry_kwargs
    assert retry_kwargs["ssl"] is fake_ssl

    # And internal state updated to persist closure on subsequent calls
    assert conn._force_close_connection is True

    # Also verify that when retry fails, force_close_connection remains True
    mock_session.request.side_effect = [
        aiohttp.ClientError("First drop"),
        aiohttp.ClientError("Second drop"),
    ]
    conn._force_close_connection = False
    with pytest.raises(CannotConnect) as exc_info:
        await conn._async_execute_request(
            "GET", "https://192.168.1.100:8888/test", None, {}
        )
    assert "unexpected error response during retry" in str(exc_info.value)
    assert conn._force_close_connection is True


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
        mock_controller.config = {"token": "TOKEN_DOMINANTE"}
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

        assert actual_headers["Authorization"] == "Bearer TOKEN_DOMINANTE", (
            "Did not use controller token"
        )


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
        assert kwargs["url"] == "http://external-api.com/path", (
            "The mutant broke startswith('http') detection"
        )
        assert kwargs["ssl"] is False, "The mutant used SSL in a plain HTTP connection"


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

    # MILLIMETRIC RETRY ASSERTIONS
    assert retry_args[0] == "POST"
    assert "https://1.1.1.1:8888/test" in retry_args[1]
    assert retry_kwargs["data"] == "payload_secreto"
    assert retry_kwargs["headers"]["H"] == "1"
    assert retry_kwargs["headers"]["Connection"] == "close"
    assert retry_kwargs["timeout"].total == 10


async def test_async_execute_embedded_command_kwargs_strict(
    mock_session, mock_logger, mock_hass
):
    """Validate exact argument delegation to nested embedded command."""
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
    conn._shared_state.ssl_context = MagicMock()

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
    """Ensure async_execute passes intact parameters to _async_execute_request."""
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
    conn._shared_state.ssl_context = MagicMock()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = "{}"
    mock_response.headers = {}
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context

    mock_controller = MagicMock()
    mock_controller.config = {}  # Empty dict, forces fallback to BASE_TOKEN
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
    mock_controller.config = {CONF_TOKEN: "tok_CONTROLLER_dominant"}
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


def test_resolved_target_uses_ip_address_directly():
    """Validates that _resolved_target uses ip_address directly."""
    import logging

    from homeassistant.const import CONF_MAC

    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "test_token"},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="192.168.1.100",
    )
    conn._params = {CONF_MAC: "FB:MA:CC"}

    host, mac = conn._resolved_target

    assert host == "192.168.1.100"
    assert mac == "FB:MA:CC"


# ====================================================================================
# TACTIC 2: TCPCONNECTOR TIMEOUT AND SESSION CREATION (_get_session)
# ====================================================================================


@pytest.mark.asyncio
async def test_get_session_strict_creation_parameters_https():
    """Validate exact parameters of TCPConnector, ClientTimeout, and ClientSession for HTTPS."""
    import logging

    config = {"use_http": False, "keep_alive": False, CONF_TOKEN: "test_token"}
    conn = ConnectionAiohttp8888(
        config=config,
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="10.0.0.1",
    )
    conn._keep_alive = False
    conn._shared_state.local_session = None  # Force creation

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

        # MILLIMETRIC ASSERTIONS — HTTPS branch (ssl= present)
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


# ====================================================================================
# TACTIC 3: EMBEDDED COMMAND BATTLE — Fallback to direct _params
# ====================================================================================


@pytest.mark.asyncio
async def test_embedded_command_without_template_and_empty_params_skips(
    mock_session, mock_logger, mock_hass
):
    """Validate that if embedded command has no template NOR params, embedded_params=None and does NOT execute.

    Kills mutants que alteran `bool(embedded_params) is True` → cambiando `is True` a `is False`
    or `True` to `False`, making code take wrong branch.
    """
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = MagicMock()

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
    embed_mock.params = {}  # <--- Empty -> bool({}) is False -> enters else: embedded_params = None
    conn._embedded_command = embed_mock

    await conn.async_execute("GET", "/main", None, {}, device_state={"state": "on"})

    # Embedded MUST NOT have executed because params was empty
    embed_mock.async_execute.assert_not_called()


# ====================================================================================
# TACTIC 3 — IMPROVEMENT 1: Absolute Empty (Kills mutants on absent 'json' and headers)
# ====================================================================================


@pytest.mark.asyncio
async def test_embedded_command_strict_fallbacks_to_main(
    mock_session, mock_logger, mock_hass
):
    """Validate fallback of method, url, data=None, and headers when embedded command does NOT define them.

    Verify mutant kill altering:
    - `else None` en `json_dumps(...) if "json" in embedded_params else None`
    - `.get("headers", headers)` -> if mutated to None, assert fails
    """
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = MagicMock()

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
    assert kwargs["method"] == "PUT", (
        f"Mutant broke method fallback: {kwargs['method']}"
    )
    assert kwargs["url"] == "/main_url", f"Mutant broke url fallback: {kwargs['url']}"
    assert kwargs["headers"] == {"Main-Header": "Present"}, (
        f"Mutant broke headers fallback: {kwargs['headers']}"
    )
    # "json" is not in _params → `else None` must produce data=None
    assert kwargs["data"] is None, (
        f"Mutant altered 'else None' when 'json' is missing in _params: {kwargs['data']}"
    )


# ====================================================================================
# TACTIC 3 — IMPROVEMENT 2: _is_poll Truth Table (Kills mutants 134-137)
# ====================================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_poll", "keep_alive", "should_close"),
    [
        (True, False, True),  # CASE 1: is poll and no keep_alive -> MUST close
        (True, True, False),  # CASE 2: is poll but keep_alive=True -> does NOT close
        (False, False, False),  # CASE 3: not poll -> does NOT close
        (False, True, False),  # CASO 4: Camino feliz normal → NO cierra
    ],
)
async def test_async_execute_periodic_reset_truth_table(
    mock_session, mock_logger, mock_hass, is_poll, keep_alive, should_close
):
    """Verify mutant kill for logical operators (and/or/not) in periodic poll close evaluation."""
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
            # CASE 1: must have called close() and reset local_session to None
            mock_local.close.assert_called_once()
            assert conn._shared_state.local_session is None, (
                f"Estado no reseteado a None (is_poll={is_poll}, keep_alive={keep_alive})"
            )
        else:
            # CASES 2, 3, 4: must NOT have closed anything
            mock_local.close.assert_not_called()
            assert conn._shared_state.local_session is mock_local, (
                f"Local session improperly deleted (is_poll={is_poll}, keep_alive={keep_alive})"
            )


# ====================================================================================
# TACTIC 4: FINAL EXTIRPATION — _try_connection and _async_execute_request
# ====================================================================================


@pytest.mark.asyncio
async def test_try_connection_strict_http_mode(mock_logger, mock_hass):
    """Test that use_http=True bypasses SSL, uses 'http' protocol and ssl=False in probe.

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
        False  # CRITICAL: prevents _get_session from attempting to create new session
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
    assert args[1] == "http://192.168.1.50:1234", (
        f"Mutant altered protocol or port: {args[1]}"
    )
    assert kwargs["ssl"] is False, f"Mutant altered ssl=False for HTTP: {kwargs['ssl']}"
    assert conn._shared_state.ssl_context is None, (
        "The mutant ignored `if not use_http` and created SSL context"
    )

    # Assertion of probe timeout (total=10, sock_read=5)
    timeout_obj = kwargs.get("timeout")
    assert timeout_obj is not None, "Mutant removed probe timeout argument"
    assert timeout_obj.total == 10, (
        f"Mutant altered timeout.total in _try_connection: {timeout_obj.total}"
    )
    assert timeout_obj.sock_read == 5, (
        f"Mutant altered timeout.sock_read in _try_connection: {timeout_obj.sock_read}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("major", "minor", "start_forced", "expected_forced"),
    [
        (1, 1, True, False),  # HTTP/1.1 -> Re-enables Keep-Alive (force_close=False)
        (1, 0, False, True),  # HTTP/1.0 -> Activates force_close
        (2, 0, True, True),  # HTTP/2.0 with minor=0 -> Not HTTP/1.x -> maintains True
    ],
)
async def test_async_execute_request_http_version_detection(
    mock_session, mock_logger, mock_hass, major, minor, start_forced, expected_forced
):
    """Verify mutant kill altering `major == 1 and minor >= 1` in HTTP version detection."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = MagicMock()
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
    """Verify mutant kill altering session.request kwargs in _async_execute_request.

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
    conn._shared_state.ssl_context = MagicMock()
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
    assert kwargs["url"] == "https://1.1.1.1:8888/strict_url", (
        f"Mutant altered URL: {kwargs['url']}"
    )
    # Payload
    assert kwargs["data"] == "strict_payload", (
        f"Mutant altered payload: {kwargs['data']}"
    )
    # Custom header preserved
    assert kwargs["headers"]["Header"] == "Strict", (
        f"Mutant altered header: {kwargs['headers']}"
    )
    # SSL correctly injected
    assert kwargs["ssl"] is conn._shared_state.ssl_context, (
        f"Mutant altered ssl context: {kwargs['ssl']}"
    )

    # MILLIMETRIC TIMEOUT ASSERTION (total=10, without sock_read)
    timeout_obj = kwargs.get("timeout")
    assert timeout_obj is not None, "Mutant removed timeout argument"
    assert isinstance(timeout_obj, aiohttp.ClientTimeout), (
        f"Mutant changed timeout type: {type(timeout_obj)}"
    )
    assert timeout_obj.total == 10, (
        f"Mutant altered timeout.total: expected 10, received {timeout_obj.total}"
    )


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
    assert kwargs["url"] == absolute_url, (
        f"The mutant broke startswith('http'): {kwargs['url']}"
    )
    # As it is http://, ssl must automatically disable at end
    assert kwargs["ssl"] is False, "The mutant did not disable SSL for plain http URL"


@pytest.mark.asyncio
async def test_try_connection_strict_token_and_port(
    mock_session, mock_logger, mock_hass
):
    """Kills mutants in controller token extraction and probe ports."""
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
    mock_ctrl.config = {"token": "CTRL_TOK"}
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
    assert kwargs["headers"]["Authorization"] == "Bearer CTRL_TOK", (
        "Mutant broke controller token fallback"
    )
    assert args[1] == "https://1.1.1.1:7777", "Mutant broke port in _try_connection"


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
    mock_ctrl.config = {}
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
    assert kwargs["headers"]["X-Dev"] == "DEV_123", (
        "Mutant broke placeholder {device_id}"
    )
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
        assert res1 == "REQ_OK", "The mutant wrongly activated optimization for POST"
        mock_req.assert_called_with("POST", "https://1.1.1.1:8888", None, {})

        mock_req.reset_mock()

        # Case 2: Incorrect URL (/other instead of /devices)
        res2, _ = await conn.async_execute("GET", "/other", None, {})
        assert res2 == "REQ_OK", (
            "The mutant wrongly activated optimization for different URL"
        )
        mock_req.assert_called_with("GET", "https://1.1.1.1:8888/other", None, {})


@pytest.mark.asyncio
async def test_async_execute_optimization_with_params_url(
    mock_session, mock_logger, mock_hass
):
    """Kill mutant in probe_url_path = self._params.get('probe_url') or self._params.get('url') or '' at L959."""
    conn = ConnectionAiohttp8888(
        config={"token": "tok"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._params = {"url": "/devices"}

    with (
        patch.object(conn, "_try_connection", new_callable=AsyncMock) as mock_try,
        patch.object(
            conn, "_async_execute_request", new_callable=AsyncMock
        ) as mock_req,
    ):
        mock_try.return_value = "PROBE_OK"

        res, headers = await conn.async_execute("GET", "/devices", None, {})
        assert res == "PROBE_OK"
        assert headers is None
        mock_req.assert_not_called()


# ====================================================================================
# UNTESTED MUTANTS ANNIHILATION
# ====================================================================================


def test_load_from_yaml_connection_base_and_params_strict(
    mock_logger, mock_hass, mock_session
):
    """Target 3: Kills mutants in ConnectionAiohttp8888.load_from_yaml (Lines 302, 309, 310)."""
    from custom_components.climate_ip.const import CONFIG_DEVICE_CONNECTION_PARAMS

    conn = ConnectionAiohttp8888(
        {CONF_TOKEN: "tok"}, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    conn._params = {"initial": "val"}

    # 1. Line 302: connection_base is not None and hasattr(connection_base, "_params")
    # Base without _params (e.g. bare object) -> hasattr is False, _params is unchanged
    base_no_params = object()
    res = conn.load_from_yaml(None, base_no_params)
    assert res is True
    assert conn._params == {"initial": "val"}

    # Base with _params -> params copied and updated
    base_with_params = MagicMock()
    base_with_params._params = {"base_key": "base_val"}
    res = conn.load_from_yaml(None, base_with_params)
    assert res is True
    assert conn._params == {"initial": "val", "base_key": "base_val"}

    # 2. Line 309 & 310: if CONFIG_DEVICE_CONNECTION_PARAMS in node and isinstance(node_params, dict)
    # node with CONFIG_DEVICE_CONNECTION_PARAMS as a valid dict
    res = conn.load_from_yaml(
        {CONFIG_DEVICE_CONNECTION_PARAMS: {"node_k": "node_v"}}, None
    )
    assert res is True
    assert conn._params["node_k"] == "node_v"

    # node with CONFIG_DEVICE_CONNECTION_PARAMS as non-dict (string, None, list)
    conn._params = {"clean": "yes"}
    res = conn.load_from_yaml(
        {CONFIG_DEVICE_CONNECTION_PARAMS: "string_not_dict"}, None
    )
    assert res is True
    assert conn._params == {"clean": "yes"}

    res = conn.load_from_yaml({CONFIG_DEVICE_CONNECTION_PARAMS: None}, None)
    assert res is True
    assert conn._params == {"clean": "yes"}

    res = conn.load_from_yaml({CONFIG_DEVICE_CONNECTION_PARAMS: [1, 2, 3]}, None)
    assert res is True
    assert conn._params == {"clean": "yes"}


def test_is_async_native_and_is_push_supported(mock_logger, mock_hass, mock_session):
    """Kill mutants in is_async_native and is_push_supported properties."""
    conn = ConnectionAiohttp8888(
        {CONF_TOKEN: "tok"}, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    assert conn.is_async_native is True
    assert conn.is_push_supported is False


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
        def __init__(self):
            self.last_parse_result = None

        def async_render(self, parse_result=False, **kwargs):
            self.last_parse_result = parse_result
            return '{"method": "POST", "url": "/sync_embed", "json": {"a": 1}}'

    tmpl = SyncTemplate()
    embed_cmd._connection_template = tmpl
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

    assert tmpl.last_parse_result is False
    embed_cmd.async_execute.assert_called_once()
    call_kwargs = embed_cmd.async_execute.call_args[1]
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["url"] == "/sync_embed"
    assert call_kwargs["data"] == '{"a":1}'


@pytest.mark.parametrize("invalid_token", [None, "", "   "])
def test_aiohttp_init_without_token_raises_auth_error(
    invalid_token, mock_logger, mock_hass, mock_session
):
    """Test __init__ immediately raises AuthError when token is missing or empty."""
    config = {} if invalid_token is None else {CONF_TOKEN: invalid_token}
    with (
        patch(
            "custom_components.climate_ip.connection_aiohttp._LOGGER.error"
        ) as mock_log_error,
        pytest.raises(
            AuthError,
            match=r"\[aiohttp_init\] aiohttp engine started without a token\.",
        ),
    ):
        ConnectionAiohttp8888(
            config=config,
            logger=mock_logger,
            hass=mock_hass,
            session=mock_session,
            ip_address="192.168.1.100",
        )
    mock_log_error.assert_called_once_with(
        "[aiohttp_init] aiohttp engine started without a token. This will fail."
    )


@pytest.mark.asyncio
async def test_async_execute_request_server_error_500(
    mock_logger, mock_hass, mock_session
):
    """Test _async_execute_request raises CannotConnect when device returns 500 on both initial and retry attempts."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    mock_response = AsyncMock()
    mock_response.status = 500
    mock_response.text.return_value = "Internal Server Error"
    mock_response.headers = {"Content-Type": "text/plain"}
    mock_response.raise_for_status = MagicMock(
        side_effect=aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=500, message="Internal Error"
        )
    )
    mock_response.version = MagicMock(major=1, minor=1)

    first_context = AsyncMock()
    first_context.__aenter__.return_value = mock_response

    # Retry also fails with 500
    retry_context = AsyncMock()
    retry_context.__aenter__.side_effect = aiohttp.ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=500,
        message="Internal Error on retry",
    )

    mock_session.request.side_effect = [first_context, retry_context]

    with pytest.raises(CannotConnect) as exc_info:
        await conn._async_execute_request("GET", "http://1.1.1.1:8888/error", None, {})
    assert "unexpected error response during retry" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_execute_request_retry_protocol_violation(
    mock_logger, mock_hass, mock_session
):
    """Test _async_execute_request raises InvalidHeaderError if protocol violation happens on retry."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._force_close_connection = False

    # First request: TimeoutError
    first_context = AsyncMock()
    first_context.__aenter__.side_effect = TimeoutError("Initial timeout")

    # Retry request: ClientPayloadError (protocol violation)
    retry_context = AsyncMock()
    retry_context.__aenter__.side_effect = aiohttp.ClientPayloadError(
        "Corrupt payload response"
    )

    mock_session.request.side_effect = [first_context, retry_context]

    with pytest.raises(InvalidHeaderError) as exc_info:
        await conn._async_execute_request("GET", "http://1.1.1.1:8888/test", None, {})
    assert "HTTP header/protocol error during retry" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_execute_request_parsing_error(
    mock_logger, mock_hass, mock_session
):
    """Test _async_execute_request raises CannotConnect on UnicodeDecodeError/ValueError."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    mock_response = AsyncMock()
    mock_response.text.side_effect = UnicodeDecodeError(
        "utf-8", b"\xff", 0, 1, "invalid start byte"
    )
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context

    with pytest.raises(CannotConnect) as exc_info:
        await conn._async_execute_request("GET", "http://1.1.1.1:8888/test", None, {})
    assert "Unexpected data parsing error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_execute_periodic_reset_close_error(
    mock_logger, mock_hass, mock_session
):
    """Test periodic reset handles session close error gracefully without raising."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token", "keep_alive": False},
        logger=mock_logger,
        hass=mock_hass,
        session=None,
        ip_address="1.1.1.1",
    )
    conn._shared_state.initialized = True
    conn._try_connection = AsyncMock(return_value=None)

    for exc in (
        aiohttp.ClientError("Close failure"),
        TimeoutError("Close timeout"),
        OSError("Close os error"),
    ):
        local_session = MagicMock()
        local_session.closed = False
        local_session.close = AsyncMock(side_effect=exc)
        conn._shared_state.local_session = local_session

        with patch.object(
            conn, "_async_execute_request", new_callable=AsyncMock
        ) as mock_req:
            mock_req.return_value = ("{}", {})
            res, _ = await conn.async_execute("GET", "/test", None, {}, _is_poll=True)
            assert res == "{}"
            local_session.close.assert_called_once()


def test_format_url_host_with_colon_and_8888_port(mock_logger, mock_hass, mock_session):
    """Test _format_url preserves port 8888 when host already has a colon and CONF_PORT is set."""
    from custom_components.climate_ip.const import CONF_USE_HTTP
    from homeassistant.const import CONF_PORT

    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token", CONF_PORT: 7777, CONF_USE_HTTP: True},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="192.168.1.50:8888",
    )
    url = conn._build_full_url("/test")
    assert url == "http://192.168.1.50:8888/test"


@pytest.mark.asyncio
async def test_async_execute_request_creates_ssl_context_when_none(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test _async_execute_request creates SSL context when https and ssl_context is None."""
    conn = ConnectionAiohttp8888(
        connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = None
    sentinel_ssl = MagicMock(spec=ssl.SSLContext)
    conn._create_ssl_context = AsyncMock(return_value=sentinel_ssl)

    mock_response = AsyncMock(status=200, headers={})
    mock_response.text.return_value = "{}"
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context

    await conn._async_execute_request(
        "GET", "https://192.168.1.100:8888/test", None, {}
    )
    conn._create_ssl_context.assert_awaited_once()
    assert mock_session.request.call_args.kwargs["ssl"] is sentinel_ssl


def test_auth_context_property(connection_config, mock_logger, mock_hass, mock_session):
    """Test centralized resolution of active token and device_id."""
    from custom_components.climate_ip.const import CONF_DEVICE_ID, MAIN_DEVICE_ID

    conn = ConnectionAiohttp8888(
        connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    # 1. No controller -> returns (token, None)
    assert conn._auth_context == ("test_token", None)

    # 2. Controller with sub-device ID
    ctrl = MagicMock()
    ctrl.config = {CONF_TOKEN: "ctrl_token", CONF_DEVICE_ID: "sub_1"}
    ctrl.device_id = "ctrl_dev"
    conn._controller = ctrl
    assert conn._auth_context == ("ctrl_token", "sub_1")

    # 3. Controller with MAIN_DEVICE_ID -> falls back to controller.device_id
    ctrl.config = {CONF_TOKEN: "ctrl_token", CONF_DEVICE_ID: MAIN_DEVICE_ID}
    ctrl.device_id = "ctrl_dev"
    assert conn._auth_context == ("ctrl_token", "ctrl_dev")

    # 4. Controller with MAIN_DEVICE_ID and no controller.device_id -> returns MAIN_DEVICE_ID
    ctrl.device_id = None
    assert conn._auth_context == ("ctrl_token", MAIN_DEVICE_ID)


def test_probe_url_path_explicit_probe_url(mock_logger, mock_hass, mock_session):
    """Test _probe_url_path returns probe_url when present in params."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._params = {"probe_url": "/api/custom_probe"}
    assert conn._probe_url_path == "/api/custom_probe"


def test_get_url_host_with_port(mock_logger, mock_hass, mock_session):
    """Test _build_full_url formats correctly when host already contains port."""
    from custom_components.climate_ip.const import CONF_USE_HTTP

    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token", CONF_USE_HTTP: True},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1:9999",
    )
    url = conn._build_full_url("/api/status")
    assert url == "http://1.1.1.1:9999/api/status"


@pytest.mark.asyncio
async def test_create_ssl_context_failure_raises_cannot_connect(
    mock_logger, mock_hass, mock_session
):
    """Test _create_ssl_context raises CannotConnect when SSL context creation fails."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="192.168.1.100",
    )
    with patch(
        "custom_components.climate_ip.connection_aiohttp.async_create_samsung_ssl_context",
        side_effect=ssl.SSLError("Invalid cert"),
    ):
        with pytest.raises(CannotConnect, match="SSL context creation failed"):
            await conn._create_ssl_context()


@pytest.mark.asyncio
async def test_async_probe_ssl_version_attribute_error(
    mock_logger, mock_hass, mock_session
) -> None:
    """Test _try_connection catches AttributeError when inspecting negotiated SSL version."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._shared_state.ssl_context = MagicMock()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value="OK")
    mock_transport = MagicMock()
    mock_ssl = MagicMock()
    del mock_ssl.version
    mock_transport.get_extra_info.return_value = mock_ssl
    mock_response.connection.transport = mock_transport
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context

    with patch.object(conn, "_get_session", AsyncMock(return_value=mock_session)):
        res = await conn._try_connection()
    assert res == "OK"


def test_resolve_8888_cert_file():
    """Test resolve_8888_cert_file returns only existing resolved certificate files."""
    import os

    import custom_components.climate_ip.connection_aiohttp as conn_mod

    expected_dir = os.path.dirname(conn_mod.__file__)

    # 1. Empty cert_path
    assert ConnectionAiohttp8888.resolve_8888_cert_file("") is None

    # 2. Resolved path that exists
    with (
        patch(
            "custom_components.climate_ip.helpers.resolve_cert_path",
            return_value="/resolved/ca.pem",
        ) as mock_resolve,
        patch("os.path.exists", return_value=True),
    ):
        assert ConnectionAiohttp8888.resolve_8888_cert_file("ca.pem") == (
            "/resolved/ca.pem"
        )
        mock_resolve.assert_called_once_with("ca.pem", expected_dir)

    # 3. Resolved path missing on disk
    with (
        patch(
            "custom_components.climate_ip.helpers.resolve_cert_path",
            return_value="/nonexistent/ca.pem",
        ),
        patch("os.path.exists", return_value=False),
    ):
        assert ConnectionAiohttp8888.resolve_8888_cert_file("ca.pem") is None

    # 4. Unresolvable cert_path
    with patch(
        "custom_components.climate_ip.helpers.resolve_cert_path", return_value=None
    ):
        assert ConnectionAiohttp8888.resolve_8888_cert_file("ca.pem") is None


def test_build_8888_ssl_context_matches_runtime_context():
    """Test build_8888_ssl_context builds the same context as _create_ssl_context."""
    from custom_components.climate_ip.connection_aiohttp import DEFAULT_SSL_CIPHERS

    with (
        patch.object(
            ConnectionAiohttp8888,
            "resolve_8888_cert_file",
            return_value="/resolved/ca.pem",
        ),
        patch(
            "custom_components.climate_ip.helpers.create_samsung_ssl_context"
        ) as mock_create,
    ):
        res = ConnectionAiohttp8888.build_8888_ssl_context("ca.pem")
        assert res is mock_create.return_value
        mock_create.assert_called_once_with(
            cert_path="/resolved/ca.pem",
            ciphers=DEFAULT_SSL_CIPHERS,
            verify_mode=ssl.CERT_NONE,
        )

    with patch(
        "custom_components.climate_ip.helpers.create_samsung_ssl_context"
    ) as mock_create:
        ConnectionAiohttp8888.build_8888_ssl_context("")
        assert mock_create.call_args.kwargs["cert_path"] is None


def test_build_8888_ssl_context_real_context_is_legacy_compatible():
    """Test the real context accepts TLSv1, skips verification and loads the client cert."""
    with (
        patch.object(ssl.SSLContext, "load_cert_chain") as mock_chain,
        patch.object(ssl.SSLContext, "load_verify_locations"),
        patch.object(
            ConnectionAiohttp8888,
            "resolve_8888_cert_file",
            return_value="/resolved/ca.pem",
        ),
    ):
        ctx = ConnectionAiohttp8888.build_8888_ssl_context("ca.pem")

    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1
    mock_chain.assert_called_once_with("/resolved/ca.pem")

    ctx_empty = ConnectionAiohttp8888.build_8888_ssl_context("")
    assert ctx_empty.check_hostname is False
    assert ctx_empty.verify_mode == ssl.CERT_NONE


@pytest.mark.asyncio
async def test_async_test_8888_connection_statuses():
    """Test async_test_8888_connection for 200, 401, and 201 statuses."""
    mock_hass = MagicMock()
    mock_ssl = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock(return_value=mock_ssl)
    mock_session = MagicMock()

    # 1. 200 OK -> True
    mock_resp_200 = AsyncMock()
    mock_resp_200.status = 200
    cm_200 = AsyncMock()
    cm_200.__aenter__.return_value = mock_resp_200
    mock_session.get.return_value = cm_200

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        return_value=mock_session,
    ):
        res_200 = await ConnectionAiohttp8888.async_test_8888_connection(
            mock_hass, "192.168.1.100", "valid_tok", "cert.pem"
        )
        assert res_200 is True
        mock_hass.async_add_executor_job.assert_called_once_with(
            ConnectionAiohttp8888.build_8888_ssl_context, "cert.pem"
        )
        mock_session.get.assert_called_once_with(
            "https://192.168.1.100:8888/devices",
            headers={
                "Authorization": "Bearer valid_tok",
                "Content-Type": "application/json",
            },
            ssl=mock_ssl,
            timeout=10,
        )

    # 2. 401 Unauthorized -> False
    mock_resp_401 = AsyncMock()
    mock_resp_401.status = 401
    cm_401 = AsyncMock()
    cm_401.__aenter__.return_value = mock_resp_401
    mock_session.get.return_value = cm_401

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        return_value=mock_session,
    ):
        res_401 = await ConnectionAiohttp8888.async_test_8888_connection(
            mock_hass, "192.168.1.100", "invalid_tok", "cert.pem"
        )
        assert res_401 is False

    # 3. 201 Created -> False (only 200 returns True)
    mock_resp_201 = AsyncMock()
    mock_resp_201.status = 201
    cm_201 = AsyncMock()
    cm_201.__aenter__.return_value = mock_resp_201
    mock_session.get.return_value = cm_201

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        return_value=mock_session,
    ):
        res_201 = await ConnectionAiohttp8888.async_test_8888_connection(
            mock_hass, "192.168.1.100", "tok", "cert.pem"
        )
        assert res_201 is False


@pytest.mark.asyncio
async def test_async_validate_rest_device_status_error():
    """Test async_validate_rest_device raises CannotConnect on non-200 HTTP status."""
    mock_hass = MagicMock()
    mock_session = MagicMock()

    mock_resp = AsyncMock()
    mock_resp.status = HTTPStatus.BAD_REQUEST
    cm = AsyncMock()
    cm.__aenter__.return_value = mock_resp
    mock_session.get.return_value = cm

    with (
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession",
            return_value=mock_session,
        ),
        pytest.raises(CannotConnect, match="HTTP Status Error"),
    ):
        await ConnectionAiohttp8888.async_validate_rest_device(
            mock_hass, "192.168.1.5", "tok"
        )


@pytest.mark.asyncio
async def test_async_validate_rest_device_fetch_device_id():
    """Test fetch_device_id branches: extraction, empty items, malformed JSON, and exceptions."""
    mock_hass = MagicMock()
    mock_session = MagicMock()

    # 1. Successful extraction
    mock_resp = AsyncMock()
    mock_resp.status = HTTPStatus.OK
    mock_resp.json = AsyncMock(return_value={"items": [{"deviceId": "dev-uuid-12345"}]})
    cm = AsyncMock()
    cm.__aenter__.return_value = mock_resp
    mock_session.get.return_value = cm

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        return_value=mock_session,
    ):
        # fetch_device_id=True returns device ID
        dev_id = await ConnectionAiohttp8888.async_validate_rest_device(
            mock_hass, "192.168.1.5", "tok", fetch_device_id=True
        )
        assert dev_id == "dev-uuid-12345"

        # fetch_device_id=False returns None
        dev_id_none = await ConnectionAiohttp8888.async_validate_rest_device(
            mock_hass, "192.168.1.5", "tok", fetch_device_id=False
        )
        assert dev_id_none is None

        # 2. Empty items list
        mock_resp.json = AsyncMock(return_value={"items": []})
        assert (
            await ConnectionAiohttp8888.async_validate_rest_device(
                mock_hass, "192.168.1.5", "tok", fetch_device_id=True
            )
            is None
        )

        # 3. Items without deviceId key
        mock_resp.json = AsyncMock(return_value={"items": [{"otherKey": "value"}]})
        assert (
            await ConnectionAiohttp8888.async_validate_rest_device(
                mock_hass, "192.168.1.5", "tok", fetch_device_id=True
            )
            is None
        )

        # 4. Items not a list
        mock_resp.json = AsyncMock(return_value={"items": "not_a_list"})
        assert (
            await ConnectionAiohttp8888.async_validate_rest_device(
                mock_hass, "192.168.1.5", "tok", fetch_device_id=True
            )
            is None
        )

        # 5. json() raises ValueError
        mock_resp.json = AsyncMock(side_effect=ValueError("Invalid JSON"))
        assert (
            await ConnectionAiohttp8888.async_validate_rest_device(
                mock_hass, "192.168.1.5", "tok", fetch_device_id=True
            )
            is None
        )

        # 6. json() raises TypeError
        mock_resp.json = AsyncMock(side_effect=TypeError("Type error"))
        assert (
            await ConnectionAiohttp8888.async_validate_rest_device(
                mock_hass, "192.168.1.5", "tok", fetch_device_id=True
            )
            is None
        )

        # 7. json() raises KeyError
        mock_resp.json = AsyncMock(side_effect=KeyError("Missing key"))
        assert (
            await ConnectionAiohttp8888.async_validate_rest_device(
                mock_hass, "192.168.1.5", "tok", fetch_device_id=True
            )
            is None
        )

        # 8. json() raises ClientPayloadError
        mock_resp.json = AsyncMock(
            side_effect=aiohttp.ClientPayloadError("Payload corrupted")
        )
        assert (
            await ConnectionAiohttp8888.async_validate_rest_device(
                mock_hass, "192.168.1.5", "tok", fetch_device_id=True
            )
            is None
        )


@pytest.mark.asyncio
async def test_async_validate_rest_device_connection_exceptions():
    """Test async_validate_rest_device handles TimeoutError and ClientError."""
    mock_hass = MagicMock()
    mock_session = MagicMock()

    # 1. TimeoutError
    mock_session.get.side_effect = TimeoutError("Request timed out")
    with (
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession",
            return_value=mock_session,
        ),
        pytest.raises(CannotConnect, match="REST API connection error"),
    ):
        await ConnectionAiohttp8888.async_validate_rest_device(
            mock_hass, "192.168.1.5", "tok"
        )

    # 2. ClientError
    mock_session.get.side_effect = aiohttp.ClientError("Failed network")
    with (
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession",
            return_value=mock_session,
        ),
        pytest.raises(CannotConnect, match="REST API connection error"),
    ):
        await ConnectionAiohttp8888.async_validate_rest_device(
            mock_hass, "192.168.1.5", "tok"
        )


def test_connection_aiohttp_log_prefix_branches(mock_logger, mock_hass, mock_session):
    """Test log_prefix branches with controller unique_id, ip_address, and fallback."""
    conn = ConnectionAiohttp8888(
        {CONF_TOKEN: "tok"}, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    # 1. No controller -> uses ip_address
    assert conn.log_prefix == "[192.168.1.100]"

    # 2. Controller with unique_id -> delegates to controller.log_prefix
    mock_ctrl = MagicMock()
    mock_ctrl.unique_id = "ac_test_123"
    mock_ctrl.log_prefix = "[ac_test_123] "
    conn.set_controller_ref(mock_ctrl)
    assert conn.log_prefix == "[ac_test_123] "

    # 3. Controller with unique_id is None -> falls back to ip_address
    mock_ctrl.unique_id = None
    assert conn.log_prefix == "[192.168.1.100]"

    # 4. No IP or empty IP -> falls back to [NO_IP]
    conn._ip_address = ""
    conn._controller = None
    assert conn.log_prefix == "[NO_IP]"
    conn._ip_address = None
    assert conn.log_prefix == "[NO_IP]"
