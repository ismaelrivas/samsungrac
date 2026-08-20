# pylint: disable=protected-access,redefined-outer-name,duplicate-code,import-outside-toplevel,missing-docstring,line-too-long
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

class StubHass:
    def __init__(self):
        from unittest.mock import AsyncMock
        self.async_add_executor_job = AsyncMock(spec=["__call__", "return_value"], side_effect=lambda func, *args: func(*args))
    def __repr__(self): return "<SafeHass>"
    def __dir__(self): return ["async_add_executor_job"]

class StubSession:
    def __init__(self):
        from unittest.mock import AsyncMock, MagicMock
        self.closed = False
        self.request = MagicMock(spec=["__call__", "return_value"])
        self.close = AsyncMock(spec=["__call__", "return_value"])
    def __repr__(self): return "<SafeSession>"
    def __dir__(self): return ["closed", "request", "close"]

from homeassistant.const import CONF_TOKEN

from custom_components.climate_ip.connection_aiohttp import (
    ConnectionAiohttp8888,
)
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import CannotConnect, InvalidHeaderError


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


async def test_try_connection_success(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )

        # Mock create_ssl_context
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        res = await conn._try_connection()
        assert res == '{"result": "ok"}'
        assert conn._shared_state.initialized is True

        # WHITE-BOX ASSERTIONS: try_connection timeout
        mock_session.request.assert_called_once()
        _, kwargs = mock_session.request.call_args
        actual_timeout = kwargs.get("timeout")
        assert actual_timeout is not None, "The mutant deleted timeout"
        assert (
            actual_timeout.total == 10
        ), f"The mutant changed total timeout: {actual_timeout.total}"
        assert (
            getattr(actual_timeout, "sock_read", None) == 5
        ), "The mutant deleted or altered probe sock_read"


async def test_try_connection_success_no_body(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_response = AsyncMock()
        mock_response.status = 401

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        res = await conn._try_connection()
        assert res is None
        assert conn._shared_state.initialized is True


async def test_try_connection_unexpected_status(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_response = AsyncMock()
        mock_response.status = 500

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        with pytest.raises(CannotConnect):
            await conn._try_connection()


async def test_try_connection_client_connector_error(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_session.request.side_effect = aiohttp.ClientConnectorError(
            MagicMock(), MagicMock()
        )

        with pytest.raises(CannotConnect):
            await conn._try_connection()


async def test_try_connection_timeout_error(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_session.request.side_effect = TimeoutError()

        with pytest.raises(InvalidHeaderError):
            await conn._try_connection()


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


async def test_async_execute_request_invalid_header(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test that protocol/header violation during request execution raises InvalidHeaderError."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_session.request.side_effect = aiohttp.http_exceptions.InvalidHeader(
            "400, message=\"Invalid header token: b'X-API-Version : v1.0.0'\""
        )

        with pytest.raises(InvalidHeaderError):
            await conn._async_execute_request("GET", "https://192.168.1.100:8888/devices", None, None)


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


def test_is_http_protocol_violation_line_too_long():
    """Verify structural exception matching for HTTP parser and protocol violations."""
    assert ConnectionAiohttp8888._is_http_protocol_violation(aiohttp.http_exceptions.LineTooLong("Line too long", 8190, 4096)) is True
    assert ConnectionAiohttp8888._is_http_protocol_violation(aiohttp.http_exceptions.InvalidHeader("invalid header")) is True
    assert ConnectionAiohttp8888._is_http_protocol_violation(aiohttp.http_exceptions.BadHttpMessage("bad http message")) is True
    assert ConnectionAiohttp8888._is_http_protocol_violation(aiohttp.ClientPayloadError("malformed payload")) is True
    assert ConnectionAiohttp8888._is_http_protocol_violation(ValueError("invalid header character")) is True
    assert ConnectionAiohttp8888._is_http_protocol_violation(ConnectionError("socket aborted")) is True
    assert ConnectionAiohttp8888._is_http_protocol_violation(Exception("some standard network timeout")) is False


async def test_try_connection_https_failure_clears_ssl_and_raises(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Kill mutants at L496 (ssl_context cleared to None) and L503 (error_msg passed)."""
    with (
        patch("os.path.exists", return_value=True),
        patch("custom_components.climate_ip.connection_aiohttp._LOGGER") as mock_module_logger,
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


def test_resolve_and_verify_cert_none(connection_config, mock_logger, mock_hass, mock_session):
    """Test _resolve_and_verify_cert returns None when raw_path is None or empty or file missing."""
    conn = ConnectionAiohttp8888(
        connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    assert conn._resolve_and_verify_cert(None) is None
    assert conn._resolve_and_verify_cert("") is None
    with (
        patch.object(conn, "_resolve_cert_path", return_value="/tmp/test_cert.pem"),
        patch("os.path.exists", return_value=True),
    ):
        assert conn._resolve_and_verify_cert("test_cert.pem") == "/tmp/test_cert.pem"
    with (
        patch.object(conn, "_resolve_cert_path", return_value="/tmp/test_cert.pem"),
        patch("os.path.exists", return_value=False),
    ):
        assert conn._resolve_and_verify_cert("test_cert.pem") is None
    with patch.object(conn, "_resolve_cert_path", return_value=None):
        assert conn._resolve_and_verify_cert("test_cert.pem") is None


def test_is_http_protocol_violation_client_connector_error():
    """Ensure ClientConnectorError is explicitly NOT considered an HTTP protocol violation."""
    conn_err = aiohttp.ClientConnectorError(
        aiohttp.client_reqrep.ConnectionKey("127.0.0.1", 8888, False, False, None, None, None),
        OSError("Connection refused"),
    )
    assert ConnectionAiohttp8888._is_http_protocol_violation(conn_err) is False


def test_is_http_protocol_violation_str_exception():
    """Test _is_http_protocol_violation handles exceptions whose __str__ raises an error."""
    class BrokenStrException(Exception):
        def __str__(self):
            raise RuntimeError("Broken __str__")

    assert ConnectionAiohttp8888._is_http_protocol_violation(BrokenStrException()) is False


async def test_try_connection_logs_negotiated_tls_version(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test that negotiated TLS version is logged when available on response transport."""
    with (
        patch("os.path.exists", return_value=True),
        patch("custom_components.climate_ip.connection_aiohttp._LOGGER") as mock_module_logger,
    ):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())

        mock_ssl_obj = MagicMock()
        mock_ssl_obj.version.return_value = "TLSv1.2"
        mock_transport = MagicMock()
        mock_transport.get_extra_info.return_value = mock_ssl_obj

        mock_conn = MagicMock()
        mock_conn.transport = mock_transport

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"probe": "ok"}'
        mock_response.connection = mock_conn

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        res = await conn._try_connection()
        assert res == '{"probe": "ok"}'
        mock_module_logger.info.assert_called_with(
            "%s [aiohttp] Connection successful. Status: %s. Negotiated TLS: %s",
            conn.log_prefix,
            200,
            "TLSv1.2",
        )


async def test_try_connection_double_check_lock_already_initialized(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test double-check lock inside _try_connection returns None if initialized while waiting."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )

        class MutatingLock:
            async def __aenter__(self):
                conn._shared_state.initialized = True
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        conn._shared_state.lock = MutatingLock()
        res = await conn._try_connection()
        assert res is None


def test_resolve_cert_path_delegates(connection_config, mock_logger, mock_hass, mock_session):
    """Test _resolve_cert_path passes cert_file to resolve_cert_path helper correctly."""
    from unittest.mock import ANY

    conn = ConnectionAiohttp8888(
        connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    with patch(
        "custom_components.climate_ip.connection_aiohttp.resolve_cert_path",
        return_value="/custom/resolved/cert.pem",
    ) as mock_helper:
        res = conn._resolve_cert_path("my_cert.pem")
        assert res == "/custom/resolved/cert.pem"
        mock_helper.assert_called_once_with("my_cert.pem", ANY, mock_hass)


async def test_try_connection_http_probe_passes_ssl_false(
    mock_logger, mock_hass, mock_session
):
    """Test _try_connection passes ssl=False when probe url starts with http://."""
    conn = ConnectionAiohttp8888(
        {"token": "tok", "use_http": True},
        mock_logger,
        mock_hass,
        mock_session,
        "192.168.1.100",
    )
    conn._params = {"url": "http://192.168.1.100:8888/test"}

    mock_response = AsyncMock(status=200)
    mock_response.text.return_value = "{}"
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_session.request.return_value = mock_context

    res = await conn._try_connection()
    assert res == "{}"
    mock_session.request.assert_called_once()
    _, kwargs = mock_session.request.call_args
    assert kwargs["ssl"] is False
