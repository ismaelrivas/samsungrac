# pylint: disable=all
# flake8: noqa
"""Archived test functions from connection_aiohttp test suite.

Quarantined 41 completely shadowed tests with zero unique mutant kills
and zero unique line coverage to accelerate mutmut and pytest execution.
Their functional contracts and historical test scenarios are preserved here.
"""

import asyncio
from http import HTTPStatus
import logging
import ssl
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.climate_ip.connection_aiohttp import (
    DEFAULT_HTTP_METHOD,
    ConnectionAiohttp8888,
)
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import (
    AuthError,
    CannotConnect,
    InvalidHeaderError,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, CONF_TOKEN
from homeassistant.helpers.json import json_dumps


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
def connection_config():
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}


@pytest.fixture
def mock_logger():
    return logging.getLogger("test_logger")


@pytest.fixture
def mock_hass():
    return StubHass()


@pytest.fixture
def mock_session():
    return StubSession()


# --- Archived from test_connection_aiohttp__basics.py: test_execute_request_success ---
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

        # Extreme White-Box Assertions
        mock_session.request.assert_called_once()
        args, kwargs = mock_session.request.call_args

        # 1. Assert URL and Method
        assert args[0] == "GET", "HTTP method was mutated"
        assert kwargs["url"] == "https://192.168.1.100:8888/test", (
            "La URL fue mutada o generada incorrectamente"
        )

        # 2. Assert Payload
        assert "data" in kwargs, "The mutant removed kwarg data"
        assert kwargs["data"] is None, "Payload was mutated"

        # 3. Assert SSL Context
        assert "ssl" in kwargs, "The mutant removed kwarg ssl"
        assert kwargs["ssl"] is conn._shared_state.ssl_context, (
            "Injected SSL context is incorrect or None"
        )

        # 4. Assert Strict Timeout
        assert "timeout" in kwargs, "The mutant removed kwarg timeout"
        timeout = kwargs["timeout"]
        assert timeout.total == 10, (
            f"The mutant altered timeout.total to {timeout.total}"
        )

        # Shielding mutants 45-56 (Headers)
        req_headers = kwargs.get("headers", {})
        assert "Authorization" in req_headers, "Missing Authorization header"
        assert req_headers["Authorization"] == f"Bearer {conn._token}", (
            "Token incorrecto"
        )
        assert "Content-Type" in req_headers, "Missing Content-Type header"
        assert req_headers["Content-Type"] == "application/json", (
            "Content-Type incorrecto"
        )


# --- Archived from test_connection_aiohttp__basics.py: test_handle_http_version_fallback_unit ---
def test_handle_http_version_fallback_unit(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Direct unit test for _handle_http_version_fallback."""
    conn = ConnectionAiohttp8888(
        connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )

    # 1. Server speaks HTTP/1.1 -> resets force_close_connection to False
    conn._force_close_connection = True
    mock_resp_11 = MagicMock()
    mock_resp_11.version = aiohttp.HttpVersion(1, 1)
    conn._handle_http_version_fallback(mock_resp_11)
    assert conn._force_close_connection is False

    # 2. Server speaks HTTP/1.0 -> sets force_close_connection to True
    mock_resp_10 = MagicMock()
    mock_resp_10.version = aiohttp.HttpVersion(1, 0)
    conn._handle_http_version_fallback(mock_resp_10)
    assert conn._force_close_connection is True

    # 3. Server provides None version -> sets force_close_connection to True
    conn._force_close_connection = False
    mock_resp_none = MagicMock()
    mock_resp_none.version = None
    conn._handle_http_version_fallback(mock_resp_none)
    assert conn._force_close_connection is True


# --- Archived from test_connection_aiohttp__basics.py: test_http_1_0_forces_connection_close ---
async def test_http_1_0_forces_connection_close(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Tests that an old server forces connection closure."""
    with (
        patch("os.path.exists", return_value=True),
        patch(
            "custom_components.climate_ip.helpers.create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
    ):
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

        assert conn._force_close_connection is True, (
            "The mutant altered HTTP minor >= 1 validation"
        )


# --- Archived from test_connection_aiohttp__basics.py: test_async_execute_request_respects_custom_headers ---
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
    assert kwargs["headers"]["Authorization"] == "Bearer TOKEN_CUSTOM", (
        "The mutant overwrote Auth header"
    )
    assert kwargs["headers"]["Content-Type"] == "text/xml", (
        "The mutant overwrote the Content-Type"
    )


# --- Archived from test_connection_aiohttp__basics.py: test_async_execute_default_poll_is_false ---
async def test_async_execute_default_poll_is_false(
    mock_session, mock_logger, mock_hass
):
    """Test that _is_poll is strictly False by default, preventing local session teardown."""
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


# --- Archived from test_connection_aiohttp__basics.py: test_resolved_target_ip_precedence_over_config_host ---
def test_resolved_target_ip_precedence_over_config_host():
    """Validates property _resolved_target: ip_address ALWAYS wins over params[CONF_HOST]."""
    import logging

    from homeassistant.const import CONF_HOST, CONF_MAC

    config = {CONF_HOST: "SHOULD_NOT_APPEAR", CONF_TOKEN: "test_token"}
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


# --- Archived from test_connection_aiohttp__basics.py: test_resolved_target_missing_keys_return_empty_strings ---
def test_resolved_target_missing_keys_return_empty_strings():
    """Validates that missing keys in _params return empty strings, NOT None."""
    import logging

    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "test_token"},
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


# --- Archived from test_connection_aiohttp__basics.py: test_format_url_port_replacement_only_on_8888 ---
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


# --- Archived from test_connection_aiohttp__basics.py: test_format_url_strict_defaults_and_http_downgrade ---
def test_format_url_strict_defaults_and_http_downgrade():
    """Validates pure defaults: Port 8888 by default and downgrade to HTTP."""
    import logging

    # 1. EMPTY CONFIG: Force code to use .get(key, DEFAULT)
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "test_token"},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=MagicMock(),
        ip_address="192.168.1.100",
    )
    conn._params = {}

    base_url = "https://192.168.1.100:8888/test"
    formatted = conn._format_url(base_url)

    # DEFAULTS ASSERTION: Verify mutant kill changing "8888" or "False"
    assert formatted.startswith("https://"), "Mutant altered use_http default (False)"
    assert ":8888/" in formatted, "Mutant altered default port (8888)"

    # 2. HTTP CONFIG: Validate explicit downgrade
    conn._config["use_http"] = True
    formatted_http = conn._build_full_url(base_url)

    # Kills mutant breaking replacement logic "https://" -> "http://"
    assert formatted_http.startswith("http://"), "Mutant broke downgrade to plain HTTP"


# --- Archived from test_connection_aiohttp__basics.py: test_get_session_strict_creation_parameters_http ---
@pytest.mark.asyncio
async def test_get_session_strict_creation_parameters_http():
    """Validates that in plain HTTP mode, TCPConnector is created WITHOUT the ssl parameter."""
    import logging

    config = {"use_http": True, "keep_alive": False, CONF_TOKEN: "test_token"}
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

        # HTTP branch: must NOT pass ssl=
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


# --- Archived from test_connection_aiohttp__basics.py: test_get_session_returns_shared_session_when_keep_alive ---
@pytest.mark.asyncio
async def test_get_session_returns_shared_session_when_keep_alive():
    """Validate keep_alive=True with injected session returns shared session without creating new one."""
    import logging

    injected_session = MagicMock(name="INJECTED_HA_SESSION")
    conn = ConnectionAiohttp8888(
        config={"keep_alive": True, CONF_TOKEN: "test_token"},
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
        assert result is injected_session, "Did not return HA shared session"
        mock_connector.assert_not_called()
        mock_session_cls.assert_not_called()


# --- Archived from test_connection_aiohttp__basics.py: test_get_session_recreates_on_closed_session ---
@pytest.mark.asyncio
async def test_get_session_recreates_on_closed_session():
    """Validate that if local session is closed, a new one is created."""
    import logging

    conn = ConnectionAiohttp8888(
        config={"keep_alive": False, CONF_TOKEN: "test_token"},
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
        assert conn._shared_state.local_session is fresh_session, (
            "Did not replace closed session"
        )


# --- Archived from test_connection_aiohttp__basics.py: test_get_session_reuses_open_local_session ---
@pytest.mark.asyncio
async def test_get_session_reuses_open_local_session():
    """Validate that if local session exists and is open, it is reused without creating a new one."""
    import logging

    conn = ConnectionAiohttp8888(
        config={"keep_alive": False, CONF_TOKEN: "test_token"},
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
        assert result is healthy_session, "Did not reuse healthy local session"
        mock_connector.assert_not_called()
        mock_timeout.assert_not_called()
        mock_session_cls.assert_not_called()


# --- Archived from test_connection_aiohttp__basics.py: test_get_session_fallback_when_shared_session_is_none ---
@pytest.mark.asyncio
async def test_get_session_fallback_when_shared_session_is_none():
    """Validate defensive fallback: keep_alive=True but session=None."""
    import logging

    # Configure keep_alive=True but intentionally omit session
    conn = ConnectionAiohttp8888(
        config={"keep_alive": True, CONF_TOKEN: "test_token"},
        logger=logging.getLogger(),
        hass=MagicMock(),
        session=None,  # <--- MUTMUT TRAP
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
        assert result == "fallback_local_session_obj", (
            "Fallback to local session failed"
        )


# --- Archived from test_connection_aiohttp__basics.py: test_embedded_command_without_template_uses_params_directly ---
@pytest.mark.asyncio
async def test_embedded_command_without_template_uses_params_directly(
    mock_session, mock_logger, mock_hass
):
    """Test execution of embedded command using direct _params (without template).

    Verify mutant kill altering:
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
    assert kwargs["method"] == "DELETE", (
        f"The mutant altered key 'method' in .get(): received {kwargs['method']}"
    )
    assert kwargs["url"] == "/override_url", (
        f"The mutant altered key 'url' in .get(): received {kwargs['url']}"
    )
    assert kwargs["data"] == json_dumps({"override": "yes"}), (
        f"The mutant altered key 'json' or json_dumps: received {kwargs['data']}"
    )
    assert kwargs["headers"] == {"Custom": "Header"}, (
        f"The mutant altered key 'headers' in .get(): received {kwargs['headers']}"
    )
    assert kwargs["device_state"] == {"state": "on"}, (
        "The mutant altered device_state propagation to embedded"
    )


# --- Archived from test_connection_aiohttp__basics.py: test_embedded_command_method_and_url_fallback_to_main ---
@pytest.mark.asyncio
async def test_embedded_command_method_and_url_fallback_to_main(
    mock_session, mock_logger, mock_hass
):
    """Validate fallback of method and url when embedded command does not define them explicitly.

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
    assert kwargs["method"] == "PUT", (
        f"Fallback for 'method' is broken: received {kwargs['method']}"
    )
    assert kwargs["url"] == "/main_url", (
        f"Fallback for 'url' is broken: received {kwargs['url']}"
    )
    assert kwargs["data"] == json_dumps({"action": "toggle"}), (
        f"json_dumps of embedded payload failed: {kwargs['data']}"
    )


# --- Archived from test_connection_aiohttp__basics.py: test_async_execute_request_none_http_version ---
@pytest.mark.asyncio
async def test_async_execute_request_none_http_version(
    mock_session, mock_logger, mock_hass, caplog
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

    caplog.set_level(logging.DEBUG)
    await conn._async_execute_request("GET", "https://1.1.1.1:8888/test", None, {})

    # MILLIMETRIC ASSERTION
    assert conn._force_close_connection is True, "Should force close if no version"
    # Verify logger.debug was NOT called with version message
    assert not any(
        "Server speaks HTTP" in record.message for record in caplog.records
    ), "The mutant evaluated True on `and response.version` when it was None"


# --- Archived from test_connection_aiohttp__basics.py: test_try_connection_strict_error_handling ---
@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 405])
async def test_try_connection_strict_error_handling(
    mock_logger, mock_hass, status_code
):
    """Assert specific error codes are handled without raising CannotConnect.
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
        assert result is None, f"Expected None for status {status_code}"


# --- Archived from test_connection_aiohttp__basics.py: test_load_from_yaml_annihilation ---
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


# --- Archived from test_connection_aiohttp__basics.py: test_prepare_request_headers_no_token_raises_auth_error ---
def test_prepare_request_headers_no_token_raises_auth_error(
    mock_logger, mock_hass, mock_session
):
    """Test _prepare_request_headers raises AuthError when current_token is None or empty."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    with pytest.raises(AuthError) as exc_info:
        conn._prepare_request_headers(None, None, "1.1.1.1", None, "AA:BB")
    assert "Token not configured" in str(exc_info.value)


# --- Archived from test_connection_aiohttp__basics.py: test_async_execute_request_already_forced_close_fails ---
@pytest.mark.asyncio
async def test_async_execute_request_already_forced_close_fails(
    mock_logger, mock_hass, mock_session
):
    """Test _async_execute_request raises CannotConnect immediately if already force_close_connection."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    conn._force_close_connection = True

    mock_context = AsyncMock()
    mock_context.__aenter__.side_effect = TimeoutError("Unreachable socket")
    mock_session.request.return_value = mock_context

    with pytest.raises(CannotConnect) as exc_info:
        await conn._async_execute_request("GET", "http://1.1.1.1:8888/test", None, {})
    assert "Connection error" in str(exc_info.value)


# --- Archived from test_connection_aiohttp__basics.py: test_connection_template_setter ---
def test_connection_template_setter(mock_logger, mock_hass, mock_session):
    """Test connection_template property setter."""
    conn = ConnectionAiohttp8888(
        config={CONF_TOKEN: "valid_token"},
        logger=mock_logger,
        hass=mock_hass,
        session=mock_session,
        ip_address="1.1.1.1",
    )
    tmpl = MagicMock()
    conn.connection_template = tmpl
    assert conn.connection_template is tmpl


# --- Archived from test_connection_aiohttp__basics.py: test_build_8888_ssl_context_with_cert_load_exception ---
def test_build_8888_ssl_context_with_cert_load_exception():
    """Test build_8888_ssl_context suppresses exceptions during load_verify_locations."""
    import os

    import custom_components.climate_ip.connection_aiohttp as conn_mod

    expected_dir = os.path.dirname(conn_mod.__file__)

    with patch.dict(
        sys.modules, {"custom_components.climate_ip.config_flow_helpers": None}
    ):
        with patch(
            "custom_components.climate_ip.helpers.resolve_cert_path",
            return_value="/resolved/ca.pem",
        ) as mock_resolve:
            with patch("os.path.exists", return_value=True):
                with patch("ssl.create_default_context") as mock_create_ctx:
                    mock_ctx = MagicMock(spec=ssl.SSLContext)
                    mock_ctx.load_verify_locations.side_effect = ssl.SSLError(
                        "Failed to load CA"
                    )
                    mock_create_ctx.return_value = mock_ctx
                    res = ConnectionAiohttp8888.build_8888_ssl_context("ca.pem")
                    mock_resolve.assert_called_once_with("ca.pem", expected_dir)
                    mock_ctx.load_verify_locations.assert_called_once_with(
                        cafile="/resolved/ca.pem"
                    )
                    assert res is mock_ctx


# --- Archived from test_connection_aiohttp__basics.py: test_async_validate_rest_device_hosts_and_ssl ---
@pytest.mark.asyncio
async def test_async_validate_rest_device_hosts_and_ssl():
    """Test async_validate_rest_device host formatting and ssl=False detection."""
    mock_hass = MagicMock()
    mock_session = MagicMock()

    mock_resp = AsyncMock()
    mock_resp.status = HTTPStatus.OK
    cm = AsyncMock()
    cm.__aenter__.return_value = mock_resp
    mock_session.get.return_value = cm

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        return_value=mock_session,
    ):
        # 1. Remote host (e.g. api.smartthings.com) -> ssl not in kwargs
        await ConnectionAiohttp8888.async_validate_rest_device(
            mock_hass, "api.smartthings.com", "remote_tok"
        )
        call_url, call_kwargs = (
            mock_session.get.call_args[0][0],
            mock_session.get.call_args[1],
        )
        assert call_url == "https://api.smartthings.com/v1/devices"
        assert "ssl" not in call_kwargs
        assert call_kwargs["headers"] == {"Authorization": "Bearer remote_tok"}

        # 2. IPv6 unbracketed
        await ConnectionAiohttp8888.async_validate_rest_device(
            mock_hass, "fe80::1::2", "tok"
        )
        call_url = mock_session.get.call_args[0][0]
        assert call_url == "https://[fe80::1::2]/v1/devices"

        # 3. IPv6 bracketed [::1] -> wraps once, ssl=False
        await ConnectionAiohttp8888.async_validate_rest_device(
            mock_hass, "[::1]", "tok"
        )
        call_url, call_kwargs = (
            mock_session.get.call_args[0][0],
            mock_session.get.call_args[1],
        )
        assert call_url == "https://[::1]/v1/devices"
        assert call_kwargs.get("ssl") is False

        # 4. Local patterns: localhost, 127.0.0.1, 192.168., 10., 172., .local
        for local_host in [
            "localhost",
            "127.0.0.1",
            "192.168.1.25",
            "10.0.0.5",
            "172.16.0.2",
            "mydevice.local",
        ]:
            await ConnectionAiohttp8888.async_validate_rest_device(
                mock_hass, local_host, "tok"
            )
            assert mock_session.get.call_args[1].get("ssl") is False


# --- Archived from test_connection_aiohttp__embed.py: test_async_execute_with_embedded_command_condition_met ---
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
        embedded_mock.params = {"url": "/embedded", "method": "GET"}
        embedded_mock.connection_template = None
        embedded_mock.async_execute = AsyncMock()

        conn._embedded_command = embedded_mock

        await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        embedded_mock.async_execute.assert_called_once()


# --- Archived from test_connection_aiohttp__session.py: test_get_session_keep_alive_no_session ---
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


# --- Archived from test_connection_aiohttp__session.py: test_get_session_use_http ---
async def test_get_session_use_http(connection_config, mock_logger, mock_hass):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, None, "192.168.1.100"
        )
        conn._config["use_http"] = True

        session = await conn._get_session()
        assert session is not None
        assert hasattr(conn._shared_state, "local_session")


# --- Archived from test_connection_aiohttp__try.py: test_try_connection_invalid_header ---
async def test_try_connection_invalid_header(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_session.request.side_effect = aiohttp.http_exceptions.InvalidHeader(
            "Invalid header token: b'X-API-Version : v1.0.0'"
        )

        with pytest.raises(InvalidHeaderError):
            await conn._try_connection()


# --- Archived from test_connection_aiohttp__try.py: test_try_connection_generic_error ---
async def test_try_connection_generic_error(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_session.request.side_effect = RuntimeError("Some generic error")

        with pytest.raises(RuntimeError):
            await conn._try_connection()


# --- Archived from test_connection_aiohttp__try.py: test_try_connection_already_initialized ---
async def test_try_connection_already_initialized(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True

        res = await conn._try_connection()
        assert res is None


# --- Archived from test_connection_aiohttp__try.py: test_try_connection_https_failure_clears_ssl_and_raises ---
async def test_try_connection_https_failure_clears_ssl_and_raises(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Kill mutants at L496 (ssl_context cleared to None) and L503 (error_msg passed)."""
    with (
        patch("os.path.exists", return_value=True),
        patch(
            "custom_components.climate_ip.connection_aiohttp._LOGGER"
        ) as mock_module_logger,
    ):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        fake_ssl = MagicMock()
        conn._shared_state.ssl_context = fake_ssl
        conn._create_ssl_context = AsyncMock(return_value=fake_ssl)

        mock_session.request.side_effect = aiohttp.ClientError("SSL handshake failure")

        with pytest.raises(CannotConnect) as exc_info:
            await conn._try_connection()

        assert "Connection initialization failed (HTTPS)" in str(exc_info.value)
        assert conn._shared_state.ssl_context is None
        mock_module_logger.warning.assert_called_with(
            "%s [aiohttp_probe] Initial probe with HTTPS (mTLS) failed: %s.",
            conn.log_prefix,
            mock_session.request.side_effect,
            exc_info=True,
        )


# --- Archived from test_connection_aiohttp__try.py: test_try_connection_http_probe_passes_ssl_false ---
async def test_try_connection_http_probe_passes_ssl_false(
    mock_logger, mock_hass, mock_session
):
    """Test _try_connection passes ssl=False and preserves absolute URL when probe url starts with http://."""
    conn = ConnectionAiohttp8888(
        {"token": "tok", "use_http": True},
        mock_logger,
        mock_hass,
        mock_session,
        "192.168.1.100",
    )
    conn._params = {"url": "http://192.168.1.100:8888/custom_devices"}

    mock_response = AsyncMock(status=200)
    mock_response.text.return_value = '{"probe": "ok"}'
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context

    res = await conn._try_connection()
    assert res == '{"probe": "ok"}'
    mock_session.request.assert_called_once()
    args, kwargs = mock_session.request.call_args
    assert args[0] == "GET"
    assert args[1] == "http://192.168.1.100:8888/custom_devices"
    assert kwargs["ssl"] is False


# --- Archived from test_connection_aiohttp__try.py: test_is_http_protocol_violation_wrapped_tp6x_error ---
def test_is_http_protocol_violation_wrapped_tp6x_error():
    """The real-world wrapped chain must be classified as a protocol violation."""
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(_make_tp6x_wrapped_error())
        is True
    )


# --- Archived from test_connection_aiohttp__try.py: test_is_http_protocol_violation_response_error_genuine_http_errors ---
@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "Bad Request"),
        (500, _TP6X_PARSER_MESSAGE),
        (401, "Unauthorized"),
        (404, "header token"),
    ],
)
def test_is_http_protocol_violation_response_error_genuine_http_errors(status, message):
    """Genuine HTTP error replies (raise_for_status) must NOT trigger the raw fallback."""
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            _make_response_error(status, message)
        )
        is False
    )


# --- Archived from test_connection_aiohttp__try.py: test_is_http_protocol_violation_response_error_parser_cause ---
@pytest.mark.parametrize(
    "cause",
    [
        aiohttp.http_exceptions.HttpProcessingError(code=400, message="x"),
        aiohttp.http_exceptions.BadHttpMessage("x"),
        aiohttp.http_exceptions.InvalidHeader("x"),
        aiohttp.http_exceptions.LineTooLong("x", 8190, 4096),
    ],
)
def test_is_http_protocol_violation_response_error_parser_cause(cause):
    """A parser exception in __cause__ is a violation regardless of status/message."""
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            _make_response_error(0, "", cause)
        )
        is True
    )


# --- Archived from test_connection_aiohttp__try.py: test_is_http_protocol_violation_response_error_context_only ---
def test_is_http_protocol_violation_response_error_context_only():
    """Implicit chaining (__context__ without __cause__) is also inspected."""
    err = _make_response_error(0, "")
    err.__context__ = aiohttp.http_exceptions.BadHttpMessage("x")
    assert ConnectionAiohttp8888._is_http_protocol_violation(err) is True


# --- Archived from test_connection_aiohttp__try.py: test_is_http_protocol_violation_response_error_non_parser_cause ---
def test_is_http_protocol_violation_response_error_non_parser_cause():
    """A non-parser cause chain must not be classified as a violation."""
    middle = RuntimeError("wrapper")
    middle.__cause__ = TimeoutError()
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            _make_response_error(0, "", middle)
        )
        is False
    )


# --- Archived from test_connection_aiohttp__try.py: test_is_http_protocol_violation_response_error_cyclic_chain ---
def test_is_http_protocol_violation_response_error_cyclic_chain():
    """Cyclic cause chains terminate without a parser match."""
    first = RuntimeError("a")
    second = RuntimeError("b")
    first.__cause__ = second
    second.__cause__ = first
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            _make_response_error(0, "", first)
        )
        is False
    )


# --- Archived from test_connection_aiohttp__try.py: test_try_connection_genuine_400_raises_cannot_connect ---
async def test_try_connection_genuine_400_raises_cannot_connect(
    connection_config, mock_logger, mock_hass, mock_session
):
    """A genuine 400 ClientResponseError during the probe stays a plain CannotConnect."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        mock_session.request.side_effect = _make_response_error(400, "Bad Request")

        with pytest.raises(CannotConnect) as exc_info:
            await conn._try_connection()

        assert not isinstance(exc_info.value, InvalidHeaderError)


# --- Archived from test_connection_aiohttp__try.py: test_async_execute_request_wrapped_invalid_header_raises_invalid_header_error ---
async def test_async_execute_request_wrapped_invalid_header_raises_invalid_header_error(
    connection_config, mock_logger, mock_hass, mock_session
):
    """The wrapped TP6X error during request execution raises InvalidHeaderError without retry."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        wrapped = _make_tp6x_wrapped_error()
        mock_session.request.side_effect = wrapped

        with pytest.raises(InvalidHeaderError) as exc_info:
            await conn._async_execute_request(
                "GET", "https://192.168.1.100:8888/devices", None, None
            )

        assert exc_info.value.__cause__ is wrapped
        mock_session.request.assert_called_once()
        assert conn._force_close_connection is False


# --- Archived from test_connection_aiohttp__try.py: test_async_execute_wrapped_invalid_header_propagates_from_probe ---
async def test_async_execute_wrapped_invalid_header_propagates_from_probe(
    connection_config, mock_logger, mock_hass, mock_session
):
    """async_execute surfaces InvalidHeaderError raised by the initial probe."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        mock_session.request.side_effect = _make_tp6x_wrapped_error()

        with pytest.raises(InvalidHeaderError):
            await conn.async_execute("GET", "/devices", None, None)
