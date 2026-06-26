# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for Samsung8888Client protocol implementation."""
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
def client():
    """Create a Samsung8888Client instance."""
    return Samsung8888Client("192.168.1.100")

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

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_open:
        await client.connect()

        # Mutant Killers: Strict argument assertions
        mock_create_ssl.assert_called_once_with(ciphers="ALL:@SECLEVEL=0", verify_mode=ssl.CERT_NONE)
        mock_open.assert_called_once_with("192.168.1.100", 8888, ssl=mock_ctx)
        
        assert client._reader == mock_reader
        assert client._writer == mock_writer


async def test_connect_failure(client):
    """Test connection failure with strict message matching."""
    with patch("asyncio.open_connection", side_effect=OSError("Connection refused")):
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
            with pytest.raises(CannotConnect, match="Connection error: Connection refused"):
                await client.connect()


async def test_request_success_and_payload_structure(client, mock_reader, mock_writer):
    """Test successful request and EXACT binary payload generation."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
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
            
            response, error = await client.request("POST", "/api/test", body=body_dict, headers=headers_dict)

            assert response == '{"result": "ok"}'
            assert error is None

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
            assert written_bytes == expected_payload, "Payload string mutation detected!"


async def test_request_chunked_fallback(client, mock_reader, mock_writer):
    """Test fallback to chunked reading when Content-Length is missing."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
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
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
            mock_reader.readline.side_effect = [b"HTTP/1.1 401 Unauthorized\r\n", b"\r\n"]
            mock_reader.read.return_value = b""
            mock_reader._waiter = None

            with pytest.raises(AuthError, match="401 Unauthorized"):
                await client.request("GET", "/test")


async def test_request_connection_reset_retry(client, mock_reader, mock_writer):
    """Test retry logic on connection reset."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_open:
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
            mock_reader.readline.side_effect = [
                ConnectionResetError("Reset"),  # 1st attempt fails
                b"HTTP/1.1 200 OK\r\n",         # 2nd attempt succeeds
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
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
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
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                TimeoutError("Timeout headers")
            ]
            mock_reader._waiter = None

            with pytest.raises(CannotConnect, match="Timeout reading headers"):
                await client.request("GET", "/test")


@pytest.mark.parametrize("malformed_header", [
    b"Content-Length: NOT_A_NUMBER\r\n",
    b"MalformedHeaderWithoutColon\r\n",
    b"Content-Length: 999999\r\n",
])
async def test_request_malformed_headers(client, mock_reader, mock_writer, malformed_header):
    """Mata a los mutantes de parseo inyectando basura en las cabeceras."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
            mock_reader.readline.side_effect = [
                b"HTTP/1.1 200 OK\r\n",
                malformed_header,
                b"\r\n",
            ]
            mock_reader.read.return_value = b"" # EOF para el fallback
            mock_reader._waiter = None
            
            try:
                await client.request("GET", "/test")
            except (CannotConnect, ValueError):
                pass

async def test_close_handles_task_exceptions(client, mock_writer):
    """Kills the return_exceptions=True mutant in close()."""
    client._writer = mock_writer
    
    async def failing_task():
        raise ValueError("Background failure")
        
    client._track_task(failing_task())
    
    # Si return_exceptions=False (el mutante), esto lanzará la excepción y fallará el test.
    await client.close()
    assert len(client._active_tasks) == 0

async def test_request_content_length_1(client, mock_reader, mock_writer):
    """Kills the content_length > 1 mutant."""
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("custom_components.climate_ip.protocol_8888.async_create_samsung_ssl_context", return_value=MagicMock()):
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
    
    # Verificamos que se acumularon los bits (OR) y no se sobrescribieron (=)
    expected_options = getattr(ssl, "OP_NO_TICKET", 0) | getattr(ssl, "OP_NO_COMPRESSION", 0)
    assert ctx.options == expected_options

