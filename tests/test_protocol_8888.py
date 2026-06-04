# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for Samsung8888Client protocol implementation."""
# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name,line-too-long
import asyncio
import json
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
def client():
    """Create a Samsung8888Client instance."""
    return Samsung8888Client("192.168.1.100")


@pytest.fixture
def anyio_backend():
    """Use asyncio as the anyio backend."""
    return "asyncio"



async def test_connect_success(client, mock_reader, mock_writer):
    """Test successful connection."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_open:
        with patch("ssl.SSLContext") as _mock_ssl_context:
            await client.connect()

            mock_open.assert_called_once()
            assert client._reader == mock_reader
            assert client._writer == mock_writer



async def test_connect_failure(client):
    """Test connection failure."""
    with patch("asyncio.open_connection", side_effect=OSError("Connection refused")):
        with patch("ssl.SSLContext"):
            with pytest.raises(CannotConnect):
                await client.connect()



async def test_request_success(client, mock_reader, mock_writer):
    """Test successful request and response."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("ssl.SSLContext"):
            # Mock response: Status line, headers, body
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Type: application/json\r\n",
                b"Content-Length: 16\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b'{"result": "ok"}'
            mock_reader._waiter = None  # Prevent concurrency guard

            response, error = await client.request("GET", "/test")

            assert response == '{"result": "ok"}'
            assert error is None

            # Verify request was written
            mock_writer.write.assert_called()
            args, _ = mock_writer.write.call_args
            request_bytes = args[0]
            assert b"GET /test HTTP/1.1" in request_bytes
            assert b"Host: 192.168.1.100:8888" in request_bytes



async def test_request_chunked_fallback(client, mock_reader, mock_writer):
    """Test fallback to chunked reading when Content-Length is missing."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("ssl.SSLContext"):
            # Mock response: Status line, headers (no content-length), body chunks
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Type: application/json\r\n",
                b"\r\n",
            ]

            # Mock read() for fallback loop
            mock_reader.read.side_effect = [b'{"res', b'ult": ', b'"ok"}', b""]  # EOF
            mock_reader._waiter = None  # Prevent concurrency guard

            response, error = await client.request("GET", "/test")

            assert response == '{"result": "ok"}'
            assert error is None



async def test_request_auth_error(client, mock_reader, mock_writer):
    """Test 401 Unauthorized response."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("ssl.SSLContext"):
            mock_reader.readline.side_effect = [b"HTTP/1.1 401 Unauthorized\r\n", b"\r\n"]
            # Ensure read returns EOF to prevent infinite loop if it tries to read
            mock_reader.read.return_value = b""
            mock_reader._waiter = None  # Prevent concurrency guard

            with pytest.raises(AuthError):
                await client.request("GET", "/test")



async def test_request_connection_reset_retry(client, mock_reader, mock_writer):
    """Test retry logic on connection reset."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_open:
        with patch("ssl.SSLContext"):
            # First attempt fails with ConnectionResetError
            # Second attempt succeeds

            mock_reader.readline.side_effect = [
                ConnectionResetError("Reset"),  # 1st attempt
                b"HTTP/1.1 200 OK\r\n",  # 2nd attempt
                b"Content-Length: 2\r\n",
                b"\r\n",
            ]
            mock_reader.readexactly.return_value = b"{}"
            mock_reader._waiter = None  # Prevent concurrency guard

            response, error = await client.request("GET", "/test")

            assert response == "{}"
            assert error is None
            assert mock_open.call_count == 2  # Reconnected



async def test_fragmented_stream_json_parsing() -> None:
    """Test that the RAW reader safely extracts JSON from a fragmented TCP stream."""
    client = Samsung8888Client("127.0.0.1", 8888)

    # Proper mock for a StreamWriter (write and close are sync, drain and wait_closed are async)
    client._writer = MagicMock()
    client._writer.drain = AsyncMock()
    client._writer.wait_closed = AsyncMock()

    client._reader = AsyncMock()
    # PREVENT CONCURRENCY GUARD: Mock _waiter to None so it doesn't instantly close our mocked connection
    client._reader._waiter = None

    # Simulate HTTP headers
    client._reader.readline.side_effect = [
        b"HTTP/1.1 200 OK\r\n",
        b"Content-Type: application/json\r\n",
        b"\r\n",
    ]

    # Simulate fragmented body chunks arriving slowly over TCP.
    # Note how the JSON is split across multiple arbitrary byte reads.
    client._reader.read.side_effect = [
        b'{"DeviceState": ',
        b'{"Device": {"Power": "On"}}}}',
        b"",  # EOF indicator
    ]

    # Bypass the actual network connection logic and jump straight to request execution
    with patch.object(client, "connect", new_callable=AsyncMock):
        body, err = await client.request("GET", "/devices")

    assert err is None
    assert body is not None

    # Verify that the JSONDecoder.raw_decode correctly stitched the chunks
    # and extracted the exact valid JSON object.
    parsed_json = json.loads(body)
    assert parsed_json == {"DeviceState": {"Device": {"Power": "On"}}}
