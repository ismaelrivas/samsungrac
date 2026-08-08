# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for Samsung8888Client protocol implementation."""

from __future__ import annotations

import asyncio
import json
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.protocol_8888 import (
    AuthError,
    CannotConnect,
    Samsung8888Client,
)


@pytest.fixture
def mock_reader():
    """Create a mock asyncio StreamReader."""
    reader = AsyncMock(spec=asyncio.StreamReader)
    return reader


@pytest.fixture
def mock_writer():
    """Create a mock asyncio StreamWriter."""
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    writer.close = MagicMock()
    return writer


@pytest.fixture
async def client():
    """Create a Samsung8888Client instance with guaranteed async teardown."""
    c = Samsung8888Client("192.168.1.100")
    try:
        yield c
    finally:
        await c.close()


@pytest.fixture
def anyio_backend():
    """Use asyncio as the anyio backend."""
    return "asyncio"


@patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context")
async def test_connect_success(mock_create_ssl, client, mock_reader, mock_writer):
    """Test successful connection and EXACT mock arguments to kill mutants."""
    mock_ctx = MagicMock(spec=ssl.SSLContext)
    mock_ctx.maximum_version = 0
    mock_ctx.minimum_version = 0
    mock_create_ssl.return_value = mock_ctx

    with patch(
        "asyncio.open_connection", return_value=(mock_reader, mock_writer)
    ) as mock_open:
        await client.connect()

        # Mutant Killers: Strict argument assertions
        mock_create_ssl.assert_called_once_with(
            ciphers="ALL:@SECLEVEL=0", verify_mode=ssl.CERT_NONE
        )
        mock_open.assert_called_once_with("192.168.1.100", 8888, ssl=mock_ctx)

        assert client._reader is mock_reader
        assert client._writer is mock_writer
        assert client._reader is not None
        assert client._writer is not None


async def test_connect_failure(client):
    """Test connection failure with strict message matching."""
    with patch("asyncio.open_connection", side_effect=OSError("Connection refused")):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            with pytest.raises(
                CannotConnect, match="Connection error: Connection refused"
            ):
                await client.connect()


async def test_request_success_and_payload_structure(client, mock_reader, mock_writer):
    """Test successful request and EXACT binary payload generation."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Type: application/json\r\n",
                b"Content-Length: 16\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b'{"result": "ok"}'
            mock_reader._waiter = None

            # Execute with body and headers to test the full formatting tree
            body_dict = {"turn": "on"}
            headers_dict = {"Custom-Header": "TestValue"}

            response, error = await client.request(
                "POST", "/api/test", body=body_dict, headers=headers_dict
            )

            assert response == '{"result": "ok"}'
            assert error is None
            mock_reader.readexactly.assert_called_with(16)

            # Mutant Killer: Byte-for-byte exact payload assertion
            mock_writer.write.assert_called_once()
            written_bytes = mock_writer.write.call_args[0][0]

            expected_payload = (
                b"POST /api/test HTTP/1.1\r\n"
                b"Host: 192.168.1.100:8888\r\n"
                b"Connection: keep-alive\r\n"
                b"Custom-Header: TestValue\r\n"
                b"Content-Length: 13\r\n\r\n"
                b'{"turn":"on"}'
            )
            assert (
                written_bytes == expected_payload
            ), "Payload string mutation detected!"


async def test_request_chunked_fallback(client, mock_reader, mock_writer):
    """Test fallback to chunked reading when Content-Length is missing."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Type: application/json\r\n",
                b"\r\n",
            ]
            mock_reader.read.side_effect = [b'{"res', b'ult": ', b'"ok"}', b""]
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")

            assert response == '{"result": "ok"}'
            assert error is None


async def test_request_auth_error(client, mock_reader, mock_writer):
    """Test 401 Unauthorized response strictly."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 401 Unauthorized\r\n",
                b"\r\n",
            ]
            mock_reader.read.return_value = b""
            mock_reader._waiter = None

            with pytest.raises(AuthError, match="401 Unauthorized"):
                await client.request("GET", "/test")


async def test_request_connection_reset_retry(client, mock_reader, mock_writer):
    """Test retry logic on connection reset."""
    with patch(
        "asyncio.open_connection", return_value=(mock_reader, mock_writer)
    ) as mock_open:
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                ConnectionResetError("Reset"),  # 1st attempt fails
                b"HTTP/1.1 200 OK\r\n",  # 2nd attempt succeeds
                b"Content-Length: 2\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"{}"
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")

            assert response == "{}"
            assert error is None
            assert mock_open.call_count == 2


async def test_fragmented_stream_json_parsing(client) -> None:
    """Test that the RAW reader safely extracts JSON from a fragmented TCP stream."""
    client._writer = MagicMock()
    client._writer.drain = AsyncMock()
    client._writer.wait_closed = AsyncMock()

    client._reader = AsyncMock()
    client._reader._waiter = None

    client._reader.readline.side_effect = [
        b"HTTP/1.1 200 OK\r\n",
        b"Content-Type: application/json\r\n",
        b"\r\n",
    ]
    client._reader.read.side_effect = [
        b'{"DeviceState": ',
        b'{"Device": {"Power": "On"}}}}',
        b"",
    ]

    with patch.object(client, "connect", new_callable=AsyncMock):
        body, err = await client.request("GET", "/devices")

    assert err is None
    assert body is not None
    parsed_json = json.loads(body)
    assert parsed_json == {"DeviceState": {"Device": {"Power": "On"}}}


async def test_request_http_error_500(client, mock_reader, mock_writer):
    """Kills the mutant that modifies the HTTP status condition."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 500 Internal Server Error\r\n",
                b"Content-Length: 9\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"Server KO"
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")

            assert response is None
            assert error == "HTTP 500: Server KO"


async def test_request_timeout_reading_headers(client, mock_reader, mock_writer):
    """Kills the mutant that swallows TimeoutError during header reading."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                TimeoutError("Timeout headers"),
            ]
            mock_reader._waiter = None

            with pytest.raises(CannotConnect) as exc_info:
                await client.request("GET", "/test")
            assert str(exc_info.value) == "Timeout reading headers"
            assert exc_info.value.__cause__ is not None


@pytest.mark.parametrize(
    "malformed_header",
    [
        b"Content-Length: NOT_A_NUMBER\r\n",
        b"MalformedHeaderWithoutColon\r\n",
        b"Content-Length: 999999\r\n",
    ],
)
async def test_request_malformed_headers(
    client, mock_reader, mock_writer, malformed_header
):
    """Verify mutant kill parsing mutant by injecting malformed header data."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                malformed_header,
                b"\r\n",
            ]
            mock_reader.read.return_value = b""  # EOF para el fallback
            mock_reader.readexactly.return_value = b""
            mock_reader._waiter = None

            resp, err = await client.request("GET", "/test")
            assert resp == ""
            assert err is None


async def test_request_payload_non_ascii_utf8_bytes(client):
    """Test payload with non-ASCII characters calculates Content-Length using UTF-8 byte length."""
    from homeassistant.helpers.json import json_dumps

    body = {"mode": "cool", "sensor": "21°C"}
    payload_str = json_dumps(body)
    payload_bytes = payload_str.encode("utf-8")
    assert len(payload_bytes) > len(payload_str)

    req_bytes = client._build_request_bytes("POST", "/api/control", body=body)
    expected_cl = f"Content-Length: {len(payload_bytes)}\r\n".encode()
    assert expected_cl in req_bytes
    assert req_bytes.endswith(payload_bytes)


async def test_request_content_length_1(client, mock_reader, mock_writer):
    """Kills the content_length > 1 mutant."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 1\r\n",  # Longitud exacta de 1 byte
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"A"
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")
            assert response == "A"
            assert error is None


@patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context")
async def test_create_ssl_context_options(mock_create_ssl, client):
    """Kills the bitwise OR (|=) mutants in SSL context creation."""
    mock_ctx = MagicMock(spec=ssl.SSLContext)
    mock_ctx.options = 0
    mock_create_ssl.return_value = mock_ctx

    ctx = await client._create_ssl_context()

    # Verify bits were accumulated (OR) and not overwritten (=)
    expected_options = getattr(ssl, "OP_NO_TICKET", 0) | getattr(
        ssl, "OP_NO_COMPRESSION", 0
    )
    assert ctx.options == expected_options


def test_init_attributes():
    """Kills __init__ None / empty string / fallback mutants."""
    client1 = Samsung8888Client("192.168.1.100")
    assert client1.host == "192.168.1.100"
    assert client1.port == 8888
    assert client1.cert_path is None
    assert client1.log_prefix == "[192.168.1.100]"
    assert client1._ssl_context is None
    assert client1._reader is None
    assert client1._writer is None

    client2 = Samsung8888Client(
        "10.0.0.1", port=8889, cert_path="/c.pem", log_prefix="[Custom]"
    )
    assert client2.host == "10.0.0.1"
    assert client2.port == 8889
    assert client2.cert_path == "/c.pem"
    assert client2.log_prefix == "[Custom]"


async def test_connect_already_connected(client, mock_writer):
    """Test connect does nothing if _writer already exists."""
    client._writer = mock_writer
    with patch(
        "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context"
    ) as mock_ssl:
        await client.connect()
        mock_ssl.assert_not_called()
        assert client._writer == mock_writer


@patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context")
async def test_create_ssl_context_with_cert_path(mock_create_ssl, client):
    """Test loading cert chain when cert_path is supplied."""
    client.cert_path = "/path/to/cert.pem"
    mock_ctx = MagicMock(spec=ssl.SSLContext)
    mock_create_ssl.return_value = mock_ctx

    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        ctx = await client._create_ssl_context()
        assert ctx == mock_ctx
        mock_to_thread.assert_called_once_with(
            mock_ctx.load_cert_chain, "/path/to/cert.pem"
        )


@patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context")
async def test_create_ssl_context_cert_error_handled(mock_create_ssl, client):
    """Test loading cert chain error is safely caught and logged."""
    client.cert_path = "/invalid/cert.pem"
    mock_ctx = MagicMock(spec=ssl.SSLContext)
    mock_create_ssl.return_value = mock_ctx

    with patch("asyncio.to_thread", side_effect=ssl.SSLError("Invalid cert")):
        ctx = await client._create_ssl_context()
        assert ctx == mock_ctx


async def test_connect_timeout(client):
    """Test timeout error during connect raises CannotConnect with exact string."""
    with patch(
        "asyncio.open_connection", side_effect=TimeoutError("Connection timed out")
    ):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            with pytest.raises(CannotConnect) as exc_info:
                await client.connect()
            assert str(exc_info.value) == "Connection timed out to 192.168.1.100:8888"
            assert exc_info.value.__cause__ is not None


async def test_close_without_writer(client, mock_reader):
    """Test close cleans up reader when writer is None."""
    client._reader = mock_reader
    client._writer = None
    await client.close()
    assert client._reader is None
    assert client._writer is None


async def test_close_wait_closed_timeout(client, mock_writer):
    """Test timeout waiting for socket close forces abort and verifies timeout context."""
    client._writer = mock_writer
    mock_writer.wait_closed.side_effect = TimeoutError("Timeout waiting close")
    mock_transport = MagicMock()
    mock_writer.transport = mock_transport

    mock_timeout_ctx = MagicMock()
    mock_timeout_ctx.__aenter__ = AsyncMock()
    mock_timeout_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "custom_components.climate_ip.protocol_8888.asyncio.timeout",
        return_value=mock_timeout_ctx,
    ) as mock_timeout:
        await client.close()
        mock_timeout.assert_called_once_with(2.0)
        mock_transport.abort.assert_called_once()
        assert client._writer is None
        assert client._reader is None


async def test_close_wait_closed_exception(client, mock_writer):
    """Test exception waiting for socket close forces abort."""
    client._writer = mock_writer
    mock_writer.wait_closed.side_effect = OSError("Socket error")
    mock_transport = MagicMock()
    mock_writer.transport = mock_transport

    await client.close()
    mock_transport.abort.assert_called_once()
    assert client._writer is None
    assert client._reader is None


async def test_close_writer_close_exception(client, mock_writer):
    """Test error closing writer is safely handled."""
    client._writer = mock_writer
    mock_writer.close.side_effect = OSError("Close error")

    await client.close()
    assert client._writer is None
    assert client._reader is None


async def test_build_request_bytes_helper(client):
    """Directly test _build_request_bytes helper method."""
    req_bytes = client._build_request_bytes(
        "GET", "/test", headers={"X-Header": "Val"}, body={"key": "val"}
    )
    assert req_bytes.startswith(b"GET /test HTTP/1.1\r\n")
    assert b"Host: 192.168.1.100:8888\r\n" in req_bytes
    assert b"X-Header: Val\r\n" in req_bytes
    assert b"Content-Length: 13\r\n" in req_bytes
    assert req_bytes.endswith(b'{"key":"val"}')


async def test_request_close_before_retry(client, mock_reader, mock_writer):
    """Test that close is called before retry on connection reset."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 2\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"{}"
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")
            assert response == "{}"
            assert error is None


async def test_request_no_writer_after_connect(client):
    """Test request raises CannotConnect if connect leaves writer as None."""
    with patch.object(client, "connect", new_callable=AsyncMock):
        with pytest.raises(CannotConnect, match="No connection established"):
            await client.request("GET", "/test")


async def test_request_payload_no_body(client, mock_reader, mock_writer):
    """Test GET request without body formats Content-Length: 0 exact payload."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 0\r\n",
                b"\r\n",
            ]
            mock_reader._waiter = None

            response, error = await client.request("GET", "/api/status")

            assert response == ""
            assert error is None
            mock_writer.write.assert_called_once()
            expected_payload = (
                b"GET /api/status HTTP/1.1\r\n"
                b"Host: 192.168.1.100:8888\r\n"
                b"Connection: keep-alive\r\n"
                b"Content-Length: 0\r\n\r\n"
            )
            assert mock_writer.write.call_args[0][0] == expected_payload


async def test_request_timeout_sending_drain(client, mock_reader, mock_writer):
    """Test TimeoutError during writer.drain raises CannotConnect."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_writer.drain.side_effect = TimeoutError("Drain timeout")
            mock_reader._waiter = None

            with pytest.raises(CannotConnect) as exc_info:
                await client.request("POST", "/test", body={"a": 1})
            assert (
                str(exc_info.value) == "Timeout sending request or reading status line"
            )
            assert exc_info.value.__cause__ is not None


async def test_request_empty_status_line_retries(client, mock_reader, mock_writer):
    """Test empty status line triggers ConnectionResetError and retry."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [b"", b""]
            mock_reader._waiter = None

            with pytest.raises(CannotConnect) as exc_info:
                await client.request("GET", "/test")
            assert str(exc_info.value) == "Unstable connection"
            assert str(exc_info.value.__cause__) == "Remote closure"


async def test_request_invalid_status_line_format(client, mock_reader, mock_writer):
    """Test malformed status line raises CannotConnect."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [b"INVALID_STATUS_LINE\r\n"]
            mock_reader._waiter = None

            with pytest.raises(
                CannotConnect, match="Invalid status format: 'INVALID_STATUS_LINE'"
            ):
                await client.request("GET", "/test")


async def test_request_content_length_zero_no_read(client, mock_reader, mock_writer):
    """Test explicitly Content-Length: 0 skips reading body."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"content-length: 0\r\n",
                b"\r\n",
            ]
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")
            assert response == ""
            assert error is None
            mock_reader.readexactly.assert_not_called()
            mock_reader.read.assert_not_called()


async def test_request_content_length_timeout_body(client, mock_reader, mock_writer):
    """Test timeout during body readexactly raises CannotConnect."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 10\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.side_effect = TimeoutError("Body timeout")
            mock_reader._waiter = None

            with pytest.raises(CannotConnect) as exc_info:
                await client.request("GET", "/test")
            assert str(exc_info.value) == "Timeout reading response body"
            assert exc_info.value.__cause__ is not None


async def test_request_content_length_exception_body(client, mock_reader, mock_writer):
    """Test non-timeout exception during body readexactly yields empty string."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 10\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.side_effect = asyncio.IncompleteReadError(
                b"partial", 10
            )
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")
            assert response == ""
            assert error is None


async def test_request_status_204_no_content(client, mock_reader, mock_writer):
    """Test HTTP 204 response returns empty string response and None error."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 204 No Content\r\n",
                b"Content-Length: 0\r\n",
                b"\r\n",
            ]
            mock_reader._waiter = None

            response, error = await client.request("POST", "/test")
            assert response == ""
            assert error is None


async def test_request_status_201_created(client, mock_reader, mock_writer):
    """Test status code non-200/204 returns error string."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 201 Created\r\n",
                b"Content-Length: 6\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"body201"
            mock_reader._waiter = None

            response, error = await client.request("POST", "/test")
            assert response is None
            assert error == "HTTP 201: body201"


async def test_request_retry_on_broken_pipe_success(client, mock_reader, mock_writer):
    """Test BrokenPipeError triggers retry and succeeds on 2nd attempt."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                BrokenPipeError("Pipe broken"),
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 2\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"{}"
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")
            assert response == "{}"
            assert error is None


async def test_request_cancelled_error(client, mock_reader, mock_writer):
    """Test asyncio.CancelledError closes socket and re-raises."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = asyncio.CancelledError()
            mock_reader._waiter = None

            with patch.object(client, "close", new_callable=AsyncMock) as mock_close:
                with pytest.raises(asyncio.CancelledError):
                    await client.request("GET", "/test")
                mock_close.assert_called_once()


async def test_request_ssl_exception(client, mock_reader, mock_writer):
    """Test SSL exception converted to CannotConnect with Error SSL prefix."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = ssl.SSLError("SSL verification failed")
            mock_reader._waiter = None

            with pytest.raises(
                CannotConnect, match=r"Error SSL:.*SSL verification failed"
            ):
                await client.request("GET", "/test")


async def test_request_unexpected_exception(client, mock_reader, mock_writer):
    """Test generic exception is re-raised directly (fail-fast, not masked as CannotConnect)."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = RuntimeError("Unknown error")
            mock_reader._waiter = None

            with pytest.raises(RuntimeError, match="Unknown error"):
                await client.request("GET", "/test")


async def test_canonical_timeout_mocking(client, mock_reader, mock_writer):
    """Kills timeout mutants by enforcing canonical asyncio.timeout mock pattern."""
    mock_timeout_ctx = MagicMock()
    mock_timeout_ctx.__aenter__ = AsyncMock()
    mock_timeout_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            with patch(
                "custom_components.climate_ip.protocol_8888.asyncio.timeout",
                return_value=mock_timeout_ctx,
            ) as mock_timeout:
                mock_reader.readline.side_effect = [
                    b"HTTP/1.1 200 OK\r\n",
                    b"Content-Length: 2\r\n",
                    b"\r\n",
                ]
                mock_reader.readexactly.return_value = b"{}"
                mock_reader._waiter = None

                await client.request("POST", "/test", body={"x": 1})

                from unittest.mock import call

                assert mock_timeout.call_args_list == [
                    call(10.0),
                    call(5.0),
                    call(10.0),
                    call(5.0),
                    call(5.0),
                    call(10.0),
                ]


@patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context")
async def test_create_ssl_context_options_exception(mock_create_ssl, client):
    """Test exception when setting options is safely ignored."""
    mock_ctx = MagicMock(spec=ssl.SSLContext)
    type(mock_ctx).options = property(
        fget=MagicMock(side_effect=AttributeError("No options attribute"))
    )
    mock_create_ssl.return_value = mock_ctx
    ctx = await client._create_ssl_context()
    assert ctx == mock_ctx


async def test_request_fallback_raw_json_incremental_chunks(
    client, mock_reader, mock_writer
):
    """Test fallback raw reader handling whitespace and incomplete JSON chunks."""
    mock_timeout_ctx = MagicMock()
    mock_timeout_ctx.__aenter__ = AsyncMock()
    mock_timeout_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            with patch(
                "custom_components.climate_ip.protocol_8888.asyncio.timeout",
                return_value=mock_timeout_ctx,
            ) as mock_timeout:
                mock_reader.readline.side_effect = [
                    b"HTTP/1.1 200 OK\r\n",
                    b"\r\n",
                ]
                mock_reader.read.side_effect = [
                    b"   \r\n",
                    b'{"key":',
                    b' "val"}',
                    b"",
                ]
                mock_reader._waiter = None

                response, error = await client.request("GET", "/test")

                assert response == '{"key": "val"}'
                assert error is None

                # Mutant Killer: Assert the exact fallback timeout threshold was used
                from unittest.mock import call

                assert (
                    call(5.0) in mock_timeout.call_args_list
                ), "Fallback timeout mutation detected!"


async def test_read_response_headers_and_body_helpers(client, mock_reader):
    """Directly test _read_response_headers and _read_response_body helper methods."""
    mock_reader.readline.side_effect = [
        b"HTTP/1.1 200 OK\r\n",
        b"Content-Length: 14\r\n",
        b"Content-Type: application/json\r\n",
        b"\r\n",
    ]
    mock_reader.readexactly.return_value = b'{"status":"ok"}'

    (
        status_code,
        content_length,
        has_cl,
        content_type,
        headers,
    ) = await client._read_response_headers(mock_reader)

    assert status_code == 200
    assert content_length == 14
    assert has_cl is True
    assert content_type == "application/json"
    assert len(headers) == 2

    body = await client._read_response_body(mock_reader, content_length, has_cl)
    assert body == '{"status":"ok"}'


def test_log_masked_response_helper(client):
    """Directly test _log_masked_response helper with valid JSON and non-JSON string."""
    with patch(
        "custom_components.climate_ip.protocol_8888._LOGGER.debug"
    ) as mock_debug:
        client._log_masked_response('{\n"token": "secret123"\n}')
        mock_debug.assert_called_once()
        log_arg = mock_debug.call_args[0][2]
        assert "secret123" not in log_arg or "*" in log_arg or "token" in log_arg

    with patch(
        "custom_components.climate_ip.protocol_8888._LOGGER.debug"
    ) as mock_debug:
        client._log_masked_response("plain non-json text\r\n")
        mock_debug.assert_called_once()
        assert mock_debug.call_args[0][2] == "plain non-json text"


async def test_request_writer_or_reader_none(client, mock_reader, mock_writer):
    """Kills 'if writer is None and reader is None' mutant."""
    client._writer = mock_writer
    client._reader = None
    with patch.object(client, "connect", new_callable=AsyncMock):
        with pytest.raises(CannotConnect, match="No connection established"):
            await client.request("GET", "/test")

    client._writer = None
    client._reader = mock_reader
    with patch.object(client, "connect", new_callable=AsyncMock):
        with pytest.raises(CannotConnect, match="No connection established"):
            await client.request("GET", "/test")


async def test_request_invalid_utf8_in_status_line_and_headers(
    client, mock_reader, mock_writer
):
    """Kills decode('utf-8') without 'ignore' mutants in status line, headers, and body."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK \xff\xfe\r\n",
                b"X-Custom-Header: val \xff\xfe\r\n",
                b"Content-Type: text/plain \xff\xfe\r\n",
                b"Content-Length: 7\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"body\xff\xfe!"
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")
            assert response == "body!"
            assert error is None


async def test_request_content_type_header_matching(client, mock_reader, mock_writer):
    """Kills 'elif key != content-type' and content_type = None mutants."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            with patch(
                "custom_components.climate_ip.protocol_8888._LOGGER.debug"
            ) as mock_debug:
                mock_reader.readline.side_effect = [
                    b"HTTP/1.1 200 OK\r\n",
                    b"X-Other-Header: text/html\r\n",
                    b"Content-Type: application/json\r\n",
                    b"Content-Length: 2\r\n",
                    b"\r\n",
                ]
                mock_reader.readexactly.return_value = b"{}"
                mock_reader._waiter = None

                response, error = await client.request("GET", "/test")
                assert response == "{}"
                assert error is None
                mock_debug.assert_any_call(
                    "%s Content-Length: %d, Content-Type: %s",
                    client.log_prefix,
                    2,
                    "application/json",
                )


async def test_request_invalid_utf8_in_body_content_length(
    client, mock_reader, mock_writer
):
    """Kills mutant that removes 'ignore' from body decode in content-length path."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 4\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"\x80abc"
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")
            assert response == "abc"
            assert error is None


async def test_request_invalid_utf8_in_fallback_stream(
    client, mock_reader, mock_writer
):
    """Kills mutant that removes 'ignore' from buffer decode in raw fallback path."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"\r\n",
            ]
            mock_reader.read.side_effect = [
                b"\x80",
                b'{"result": "ok"}',
                b"",
            ]
            mock_reader._waiter = None

            response, error = await client.request("GET", "/test")
            assert response == '{"result": "ok"}'
            assert error is None


async def test_request_non_json_fallback_strict(client, mock_reader, mock_writer):
    """
    Kills logic mutants that break the non-json fallback decoding (e.g. removing 'ignore').
    """
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            # Simulate headers
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"\r\n",  # Chunked fallback
            ]
            # Simulate NON-JSON payload with an invalid UTF-8 byte
            mock_reader.read.side_effect = [
                b"PLAIN\x80TEXT",
                b"",  # EOF
            ]
            mock_reader._waiter = None

            body, error = await client.request("GET", "/test")

            # STRICT ASSERTION: If the mutant alters decoding, it will either crash or return None.
            assert error is None
            assert body == "PLAINTEXT"


# ── WHITE-BOX PROTOCOL & STREAM PARSER TESTS ─────────────────────────────────


async def test_white_box_http_framing_casing_and_crlf(client, mock_reader, mock_writer):
    """Assert HTTP request preserves exact header casing (Content-Length) and CRLF line endings."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 2\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"{}"
            mock_reader._waiter = None

            await client.request(
                "POST",
                "/devices",
                body={"op": "power"},
                headers={"X-Custom-Header": "CustomVal"},
            )

            written_bytes = mock_writer.write.call_args[0][0]
            written_str = written_bytes.decode("utf-8")

            # 1. Assert exact CRLF line endings
            assert "\r\n" in written_str
            assert "\n\n" not in written_str.replace("\r\n", "")

            # 2. Assert exact case-sensitive header naming
            assert "Content-Length: " in written_str
            assert "content-length: " not in written_str
            assert "X-Custom-Header: CustomVal\r\n" in written_str
            assert "POST /devices HTTP/1.1\r\n" in written_str


async def test_header_flag_and_content_length_scenarios(
    client, mock_reader, mock_writer
):
    """Test 3 distinct Content-Length stream scenarios: >0, ==0, and missing (fallback)."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            # Scenario A: Content-Length > 0 -> Uses readexactly
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 13\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b'{"status":"ok"}'
            mock_reader._waiter = None

            body_a, error_a = await client.request("GET", "/test_a")
            assert error_a is None
            assert body_a == '{"status":"ok"}'
            mock_reader.readexactly.assert_called_once_with(13)

            # Scenario B: Content-Length: 0 -> Immediately returns empty string without reading body stream
            client._writer = mock_writer
            client._reader = mock_reader
            mock_reader.readexactly.reset_mock()
            mock_reader.read = AsyncMock()

            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Length: 0\r\n",
                b"\r\n",
            ]

            body_b, error_b = await client.request("GET", "/test_b")
            assert error_b is None
            assert body_b == ""
            mock_reader.readexactly.assert_not_called()
            mock_reader.read.assert_not_called()

            # Scenario C: Missing Content-Length -> Fallback stream reading loop with JSONDecoder.raw_decode
            client._writer = mock_writer
            client._reader = mock_reader
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Type: application/json\r\n",
                b"\r\n",
            ]
            mock_reader.read.side_effect = [
                b'{"device":',
                b' "samsung"}\r\nEXTRA_GARBAGE',
                b"",
            ]

            body_c, error_c = await client.request("GET", "/test_c")
            assert error_c is None
            assert body_c == '{"device": "samsung"}'


async def test_close_transport_abort_on_timeout(client, mock_writer):
    """Test close() aborts transport on timeout waiting closed."""
    client._writer = mock_writer
    mock_writer.wait_closed.side_effect = TimeoutError("Close wait timeout")
    mock_transport = MagicMock()
    mock_writer.transport = mock_transport

    await client.close()

    mock_transport.abort.assert_called_once()
    assert client._writer is None
    assert client._reader is None
