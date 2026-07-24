# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the Samsung 8888 token acquirer."""

import json
import ssl
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.climate_ip.exceptions import CannotConnect, TokenAcquisitionError
from custom_components.climate_ip.token_acquirer_8888 import (
    SamsungTokenAcquirer8888,
)


# --- Concrete Mocks to prevent AsyncMock coroutine leaks ---
class MockStreamReader:
    """Concrete mock for asyncio.StreamReader."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.idx = 0
        self.read_count = 0

    async def read(self, n=-1):
        """Return next chunk or empty bytes."""
        if n != -1:
            assert n == 4096, f"Expected read(4096), got read({n})"
        self.read_count += 1
        if self.read_count > 20:
            raise RuntimeError("Infinite loop detected in MockStreamReader.read()")
        if self.idx < len(self.chunks):
            chunk = self.chunks[self.idx]
            self.idx += 1
            return chunk
        return b""


class MockStreamWriter:
    """Concrete mock for asyncio.StreamWriter."""

    def __init__(self):
        self.written_data = b""
        self.closed = False
        self.wait_closed_called = False

    def write(self, data: bytes):
        """Write bytes to the internal buffer."""
        self.written_data += data

    async def drain(self):
        """Drain the write buffer."""

    def close(self):
        """Close the stream."""
        self.closed = True

    async def wait_closed(self):
        """Wait for the stream to close."""
        self.wait_closed_called = True

    def get_extra_info(self, _name):
        """Return mock peer address."""
        return ("127.0.0.1", 12345)


# Helper for creating asyncio.timeout mock context manager
def make_mock_timeout_cm():
    """Construct canonical AsyncMock context manager for asyncio.timeout."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock()
    ctx.__aexit__ = AsyncMock(
        return_value=False
    )  # CRITICAL: Do NOT swallow inner exceptions!
    return ctx


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.api.local_ip = "192.168.1.100"
    hass.config.path.side_effect = lambda *args: "/".join(args)
    return hass


@pytest.fixture
def acquirer(mock_hass):
    """Create a token acquirer instance."""
    return SamsungTokenAcquirer8888(mock_hass, "192.168.1.50", "ac14k_m.pem")


# --- Initialization Tests ---


def test_init_attributes(mock_hass):
    """Test acquirer initialization attributes and certificate resolution paths."""
    acquirer_rel = SamsungTokenAcquirer8888(mock_hass, "192.168.1.50", "ac14k_m.pem")
    assert acquirer_rel._hass == mock_hass
    assert acquirer_rel._ac_ip == "192.168.1.50"
    assert acquirer_rel._listener_ip == "192.168.1.100"
    assert acquirer_rel._listener_port == 8889
    assert acquirer_rel._ac_port == 8888
    assert acquirer_rel._server is None
    assert acquirer_rel._received_token is None
    assert acquirer_rel._cert_path.endswith("custom_components/climate_ip/ac14k_m.pem")

    # Absolute cert path
    acquirer_abs = SamsungTokenAcquirer8888(
        mock_hass, "192.168.1.50", "/etc/ssl/cert.pem"
    )
    assert acquirer_abs._cert_path == "/etc/ssl/cert.pem"

    # Empty cert path
    acquirer_empty = SamsungTokenAcquirer8888(mock_hass, "192.168.1.50", "")
    assert acquirer_empty._cert_path == ""


# --- Server Lifecycle Tests (_start_listener_server & async_close) ---


async def test_start_listener_server_success(acquirer):
    """Test custom TCP server starting successfully."""
    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_create_ssl,
        patch("asyncio.start_server", return_value=mock_server) as mock_start_server,
    ):
        result = await acquirer._start_listener_server()

        assert result is True
        assert acquirer._server == mock_server
        mock_create_ssl.assert_called_once_with(
            cert_path=acquirer._cert_path,
            ciphers="HIGH:!aNULL:!MD5:@SECLEVEL=0",
            is_server=True,
        )
        mock_start_server.assert_called_once_with(
            acquirer._handle_client, "192.168.1.100", 8889, ssl=mock_ssl_ctx
        )


async def test_start_listener_server_fallback_bind_ip(mock_hass):
    """Test bind_ip falling back to 0.0.0.0 when local_ip is empty."""
    mock_hass.config.api.local_ip = None
    acquirer_no_ip = SamsungTokenAcquirer8888(mock_hass, "192.168.1.50", "ac14k_m.pem")

    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ),
        patch("asyncio.start_server", return_value=mock_server) as mock_start_server,
    ):
        result = await acquirer_no_ip._start_listener_server()

        assert result is True
        assert mock_start_server.call_args[0][1] == "0.0.0.0"


async def test_start_listener_server_bind_oserror(acquirer):
    """Test handling OSError when binding to listener port."""
    with (
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.start_server", side_effect=OSError("Address already in use")),
    ):
        with pytest.raises(
            TokenAcquisitionError, match="Cannot bind to 192.168.1.100:8889"
        ):
            await acquirer._start_listener_server()


async def test_start_listener_server_generic_exception(acquirer):
    """Test handling generic exception during listener server startup."""
    with patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        side_effect=RuntimeError("SSL Context Failed"),
    ):
        result = await acquirer._start_listener_server()
        assert result is False


async def test_async_close(acquirer):
    """Test closing active server and calling close on None."""
    # Closing when server is None (no-op)
    await acquirer.async_close()
    assert acquirer._server is None

    # Closing with active server
    mock_server = AsyncMock()
    acquirer._server = mock_server

    await acquirer.async_close()
    mock_server.close.assert_called_once()
    mock_server.wait_closed.assert_called_once()
    assert acquirer._server is None


# --- Pairing Initiation Tests (async_initiate_pairing) ---


async def test_initiate_pairing_success(acquirer):
    """Test a successful pairing initiation with exact raw HTTP socket checks."""
    mock_timeout_ctx = make_mock_timeout_cm()
    mock_ssl_ctx = MagicMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
            return_value=True,
        ),
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_create_ssl,
        patch("asyncio.timeout", return_value=mock_timeout_ctx) as mock_timeout,
    ):
        # Split response into multiple chunks to test response_data += chunk
        mock_reader = MockStreamReader(
            [b"HTTP/1.1 200 ", b"OK\r\nConnection: close\r\n\r\nOK"]
        )
        mock_writer = MockStreamWriter()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        await acquirer.async_initiate_pairing()

        # Assert exact keyword arguments passed to async_create_samsung_ssl_context
        mock_create_ssl.assert_called_once_with(
            cert_path=acquirer._cert_path,
            ciphers="HIGH:!aNULL:!MD5:@SECLEVEL=0",
            verify_mode=ssl.CERT_NONE,
        )

        # Assert numeric timeout value call
        assert mock_timeout.call_args_list == [call(30.0)]
        mock_open_connection.assert_called_once_with(
            "192.168.1.50", 8888, ssl=mock_ssl_ctx
        )
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True

        written_text = mock_writer.written_data.decode("utf-8")
        assert written_text.startswith("POST /devicetoken/request HTTP/1.1\r\n")
        assert "Host: 192.168.1.100:8889\r\n" in written_text
        assert "Content-Type: application/json\r\n" in written_text
        assert "Content-Length: 29\r\n" in written_text
        assert '{"DeviceToken":"xxxxxxxxxxx"}' in written_text


async def test_initiate_pairing_server_failure(acquirer):
    """Test pairing initiation when local server fails to start."""
    with patch(
        "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
        return_value=False,
    ):
        with pytest.raises(
            TokenAcquisitionError, match="Failed to start the local listener server"
        ):
            await acquirer.async_initiate_pairing()


async def test_initiate_pairing_http_failure(acquirer):
    """Test pairing initiation when AC returns non-200 HTTP status."""
    mock_timeout_ctx = make_mock_timeout_cm()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
            return_value=True,
        ),
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
    ):
        mock_reader = MockStreamReader([b"HTTP/1.1 403 Forbidden\r\n\r\n"])
        mock_writer = MockStreamWriter()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        with pytest.raises(
            TokenAcquisitionError, match="AC responded with non-200 status"
        ):
            await acquirer.async_initiate_pairing()


async def test_initiate_pairing_empty_response(acquirer):
    """Test pairing initiation when AC returns empty response."""
    mock_timeout_ctx = make_mock_timeout_cm()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
            return_value=True,
        ),
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
    ):
        mock_reader = MockStreamReader([b""])
        mock_writer = MockStreamWriter()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        with pytest.raises(TokenAcquisitionError, match="<empty response>"):
            await acquirer.async_initiate_pairing()


async def test_initiate_pairing_connection_error(acquirer):
    """Test pairing initiation when AC is unreachable."""
    mock_timeout_ctx = make_mock_timeout_cm()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
            return_value=True,
        ),
        patch(
            "asyncio.open_connection", side_effect=ConnectionError("Connection refused")
        ),
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        with pytest.raises(
            CannotConnect, match="Failed to connect to AC via raw socket"
        ):
            await acquirer.async_initiate_pairing()
        mock_close.assert_called_once()


async def test_initiate_pairing_unexpected_exception(acquirer):
    """Test pairing initiation encountering unexpected generic exception."""
    mock_timeout_ctx = make_mock_timeout_cm()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
            return_value=True,
        ),
        patch(
            "asyncio.open_connection",
            side_effect=RuntimeError("Unexpected socket crash"),
        ),
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        with pytest.raises(
            TokenAcquisitionError, match="Unexpected error during pairing request"
        ):
            await acquirer.async_initiate_pairing()
        mock_close.assert_called_once()


# --- Token Waiting Tests (async_wait_for_token) ---


async def test_wait_for_token_success(acquirer):
    """Test successfully waiting for and receiving a token."""
    acquirer._received_token = "new_secret_token"
    mock_timeout_ctx = make_mock_timeout_cm()

    async def mock_wait():
        pass

    acquirer._token_received_event.wait = mock_wait

    with (
        patch("asyncio.timeout", return_value=mock_timeout_ctx) as mock_timeout,
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        token = await acquirer.async_wait_for_token()
        assert token == "new_secret_token"
        assert mock_timeout.call_args_list == [call(60.0)]
        mock_close.assert_called_once()


async def test_wait_for_token_event_set_no_token(acquirer):
    """Test event being set but no token stored."""
    acquirer._received_token = None
    mock_timeout_ctx = make_mock_timeout_cm()

    async def mock_wait():
        pass

    acquirer._token_received_event.wait = mock_wait

    with (
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        with pytest.raises(
            TokenAcquisitionError, match="Event was set but no token was stored"
        ):
            await acquirer.async_wait_for_token()
        mock_close.assert_called_once()


async def test_wait_for_token_timeout(acquirer):
    """Test waiting for a token timing out."""
    mock_timeout_ctx = make_mock_timeout_cm()

    async def mock_wait():
        raise TimeoutError

    acquirer._token_received_event.wait = mock_wait

    with (
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        with pytest.raises(TokenAcquisitionError, match="Timed out waiting for the AC"):
            await acquirer.async_wait_for_token()
        mock_close.assert_called_once()


# --- Client Handler Tests (_handle_client) ---


async def test_handle_client_chunk_accumulation_and_regex(acquirer):
    """Test TCP client handler accumulating multiple data chunks and extracting token via regex."""
    mock_timeout_ctx = make_mock_timeout_cm()

    # Split JSON payload across chunks to test accumulation data += chunk
    chunk1 = b"HTTP/1.1 200 OK\r\nDeviceToken: "
    chunk2 = b'"chunked_token_123"\r\n}'
    mock_reader = MockStreamReader([chunk1, chunk2])
    mock_writer = MockStreamWriter()

    with patch("asyncio.timeout", return_value=mock_timeout_ctx) as mock_timeout:
        await acquirer._handle_client(mock_reader, mock_writer)

        assert mock_timeout.call_args_list == [call(10.0)]
        assert acquirer._received_token == "chunked_token_123"
        assert acquirer._token_received_event.is_set()
        assert b"200 OK" in mock_writer.written_data
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True


async def test_handle_client_empty_data(acquirer):
    """Test TCP client handler when reader receives empty data."""
    mock_timeout_ctx = make_mock_timeout_cm()
    mock_reader = MockStreamReader([b""])
    mock_writer = MockStreamWriter()

    with patch("asyncio.timeout", return_value=mock_timeout_ctx):
        await acquirer._handle_client(mock_reader, mock_writer)

        assert acquirer._received_token is None
        assert not acquirer._token_received_event.is_set()
        assert mock_writer.written_data == b""
        assert mock_writer.closed is True


async def test_handle_client_json_fallback_parsed(acquirer):
    """Test TCP client handler using Strategy 2 (JSON parsing) when Regex fails."""
    mock_timeout_ctx = make_mock_timeout_cm()
    payload = b'HEADER_PREFIX\r\n\r\n{"DeviceToken": "strategy2_json_token"}'
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    with (
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
        patch(
            "custom_components.climate_ip.token_acquirer_8888.DEVICE_TOKEN_RE"
        ) as mock_re,
    ):
        mock_re.search.return_value = None
        await acquirer._handle_client(mock_reader, mock_writer)

        assert acquirer._received_token == "strategy2_json_token"
        assert acquirer._token_received_event.is_set()
        assert b"200 OK" in mock_writer.written_data


async def test_handle_client_json_fallback_rfind_check(acquirer):
    """Test Strategy 2 find('{') vs rfind('{') by placing nested '{' inside JSON string value."""
    mock_timeout_ctx = make_mock_timeout_cm()
    payload = b'HEADER {"DeviceToken": "val{ue"}'
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    with (
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
        patch(
            "custom_components.climate_ip.token_acquirer_8888.DEVICE_TOKEN_RE"
        ) as mock_re,
    ):
        mock_re.search.return_value = None
        await acquirer._handle_client(mock_reader, mock_writer)

        assert acquirer._received_token == "val{ue"
        assert acquirer._token_received_event.is_set()


async def test_handle_client_json_fallback_index_1(acquirer):
    """Test Strategy 2 when JSON starts at index 1 to kill json_start != +1 mutant."""
    mock_timeout_ctx = make_mock_timeout_cm()
    payload = b' {"DeviceToken": "index1_json_token"}'
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    with (
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
        patch(
            "custom_components.climate_ip.token_acquirer_8888.DEVICE_TOKEN_RE"
        ) as mock_re,
    ):
        mock_re.search.return_value = None
        await acquirer._handle_client(mock_reader, mock_writer)

        assert acquirer._received_token == "index1_json_token"
        assert acquirer._token_received_event.is_set()


async def test_handle_client_json_fallback_invalid_json(acquirer):
    """Test Strategy 2 when JSON is malformed and fails parsing."""
    mock_timeout_ctx = make_mock_timeout_cm()
    payload = b"HEADER_PREFIX { invalid_json_here"
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    with (
        patch("asyncio.timeout", return_value=mock_timeout_ctx),
        patch(
            "custom_components.climate_ip.token_acquirer_8888.DEVICE_TOKEN_RE"
        ) as mock_re,
    ):
        mock_re.search.return_value = None
        await acquirer._handle_client(mock_reader, mock_writer)

        assert acquirer._received_token is None
        assert not acquirer._token_received_event.is_set()
        assert b"400 Bad Request" in mock_writer.written_data


async def test_handle_client_no_token(acquirer):
    """Test TCP client handler receiving valid payload without a DeviceToken."""
    mock_timeout_ctx = make_mock_timeout_cm()
    payload = json.dumps({"OtherData": "No token here"}).encode("utf-8")
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    with patch("asyncio.timeout", return_value=mock_timeout_ctx):
        await acquirer._handle_client(mock_reader, mock_writer)

        assert acquirer._received_token is None
        assert not acquirer._token_received_event.is_set()
        assert b"400 Bad Request" in mock_writer.written_data


async def test_handle_client_exception_during_write(acquirer):
    """Test exception during client handling is logged and connection closed cleanly."""
    mock_timeout_ctx = make_mock_timeout_cm()
    payload = b'DeviceToken: "token_abc"\r\n}'
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()
    mock_writer.write = MagicMock(side_effect=RuntimeError("Socket write error"))

    with patch("asyncio.timeout", return_value=mock_timeout_ctx):
        await acquirer._handle_client(mock_reader, mock_writer)

        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True


async def test_handle_client_wait_closed_exception(acquirer):
    """Test client handler swallowing exception in wait_closed."""
    mock_timeout_ctx = make_mock_timeout_cm()
    payload = b'DeviceToken: "token_abc"\r\n}'
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    async def mock_wait_closed_error():
        raise ConnectionError("Stream closed error")

    mock_writer.wait_closed = mock_wait_closed_error

    with patch("asyncio.timeout", return_value=mock_timeout_ctx):
        await acquirer._handle_client(mock_reader, mock_writer)

        assert acquirer._received_token == "token_abc"
        assert mock_writer.closed is True
