# pylint: disable=protected-access,redefined-outer-name,duplicate-code,import-outside-toplevel,missing-docstring,line-too-long

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import CannotConnect, InvalidHeaderError
from homeassistant.const import CONF_TOKEN


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

        sentinel_ssl = MagicMock()
        conn._create_ssl_context = AsyncMock(return_value=sentinel_ssl)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        res = await conn._try_connection()
        assert res == '{"result": "ok"}'
        assert conn._shared_state.initialized is True
        assert conn._shared_state.ssl_context is sentinel_ssl

        # WHITE-BOX ASSERTIONS: try_connection timeout and ssl
        mock_session.request.assert_called_once()
        _, kwargs = mock_session.request.call_args
        assert kwargs["ssl"] is sentinel_ssl
        actual_timeout = kwargs.get("timeout")
        assert actual_timeout is not None, "The mutant deleted timeout"
        assert actual_timeout.total == 10, (
            f"The mutant changed total timeout: {actual_timeout.total}"
        )
        assert actual_timeout.sock_read == 5
        assert isinstance(actual_timeout.sock_read, int), (
            "sock_read must be an int, not float"
        )


async def test_try_connection_ssl_context_none_passes_ssl_true(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test _try_connection passes ssl=True when _create_ssl_context returns None on HTTPS."""
    conn = ConnectionAiohttp8888(
        connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
    )
    conn._create_ssl_context = AsyncMock(return_value=None)
    mock_response = AsyncMock(status=200)
    mock_response.text.return_value = "{}"
    mock_context = AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
    mock_session.request.return_value = mock_context

    await conn._try_connection()
    mock_session.request.assert_called_once()
    _, kwargs = mock_session.request.call_args
    assert kwargs["ssl"] is True


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

        with pytest.raises(CannotConnect):
            await conn._try_connection()


def test_is_http_protocol_violation_line_too_long():
    """Verify structural exception matching for HTTP parser and protocol violations."""
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            aiohttp.http_exceptions.LineTooLong("Line too long", 8190, 4096)
        )
        is True
    )
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            aiohttp.http_exceptions.InvalidHeader("invalid header")
        )
        is True
    )
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            aiohttp.http_exceptions.BadHttpMessage("bad http message")
        )
        is True
    )
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            aiohttp.ClientPayloadError("malformed payload")
        )
        is True
    )
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            ValueError("invalid header character")
        )
        is True
    )
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            ConnectionError("socket aborted")
        )
        is True
    )
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            Exception("some standard network timeout")
        )
        is False
    )


def test_resolve_and_verify_cert_none(
    connection_config, mock_logger, mock_hass, mock_session
):
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
        aiohttp.client_reqrep.ConnectionKey(
            "127.0.0.1", 8888, False, False, None, None, None
        ),
        OSError("Connection refused"),
    )
    assert ConnectionAiohttp8888._is_http_protocol_violation(conn_err) is False


def test_is_http_protocol_violation_str_exception():
    """Test _is_http_protocol_violation handles exceptions whose __str__ raises an error."""

    class BrokenStrException(Exception):
        def __str__(self):
            raise RuntimeError("Broken __str__")

    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(BrokenStrException()) is False
    )


async def test_try_connection_logs_negotiated_tls_version(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test that negotiated TLS version is logged when available on response transport."""
    with (
        patch("os.path.exists", return_value=True),
        patch(
            "custom_components.climate_ip.connection_aiohttp._LOGGER"
        ) as mock_module_logger,
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
        mock_transport.get_extra_info.assert_called_with("ssl_object")


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


def test_resolve_cert_path_delegates(
    connection_config, mock_logger, mock_hass, mock_session
):
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
            await conn._async_execute_request(
                "GET", "https://192.168.1.100:8888/devices", None, None
            )


# ============================================================================
# Wrapped parser violations (ClientResponseError chained from HttpProcessingError)
# ============================================================================

_TP6X_PARSER_MESSAGE = (
    "Invalid header token:\n\n  b'X-API-Version : v1.0.0'\n                 ^"
)


def _make_response_error(
    status: int, message: str, cause: BaseException | None = None
) -> aiohttp.ClientResponseError:
    err = aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=status, message=message
    )
    err.__cause__ = cause
    return err


def _make_tp6x_wrapped_error() -> aiohttp.ClientResponseError:
    """Replicate the exact exception chain raised by aiohttp 3.13 for TP6X_RAC_17K firmware.

    ClientResponseError(400) -> HttpProcessingError -> BadHttpMessage
    """
    bad_msg = aiohttp.http_exceptions.BadHttpMessage(_TP6X_PARSER_MESSAGE)
    processing = aiohttp.http_exceptions.HttpProcessingError(
        code=400, message=_TP6X_PARSER_MESSAGE
    )
    processing.__cause__ = bad_msg
    return _make_response_error(400, _TP6X_PARSER_MESSAGE, processing)


@pytest.mark.parametrize(
    "message",
    [
        _TP6X_PARSER_MESSAGE,
        "INVALID HEADER value",
        "Bad header token found",
    ],
)
def test_is_http_protocol_violation_response_error_message_markers(message):
    """Status 400 plus either marker (case-insensitive) is a violation, even without cause."""
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            _make_response_error(400, message)
        )
        is True
    )


def test_is_http_protocol_violation_response_error_nested_cause():
    """The parser exception is found deeper in the __cause__ chain."""
    middle = RuntimeError("wrapper")
    middle.__cause__ = aiohttp.http_exceptions.BadHttpMessage("x")
    assert (
        ConnectionAiohttp8888._is_http_protocol_violation(
            _make_response_error(0, "", middle)
        )
        is True
    )


def test_is_http_protocol_violation_response_error_non_str_message():
    """A non-string message attribute is tolerated and treated as empty."""
    err = _make_response_error(400, "")
    err.message = None  # type: ignore[assignment]
    assert ConnectionAiohttp8888._is_http_protocol_violation(err) is False


async def test_try_connection_wrapped_invalid_header_raises_invalid_header_error(
    connection_config, mock_logger, mock_hass, mock_session
):
    """The wrapped TP6X error during the probe raises InvalidHeaderError (not plain CannotConnect)."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._create_ssl_context = AsyncMock(return_value=MagicMock())
        wrapped = _make_tp6x_wrapped_error()
        mock_session.request.side_effect = wrapped

        with pytest.raises(InvalidHeaderError) as exc_info:
            await conn._try_connection()

        assert exc_info.value.__cause__ is wrapped
        assert "Protocol violation during probe" in str(exc_info.value)
        assert conn._shared_state.initialized is False
