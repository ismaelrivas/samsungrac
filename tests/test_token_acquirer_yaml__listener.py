# pylint: disable=protected-access,redefined-outer-name,unused-argument,not-context-manager,invalid-name,line-too-long
"""Tests for GenericYamlTokenAcquirer in listener mode (8888 pairing)."""

import json
import ssl
from unittest.mock import AsyncMock, MagicMock, call, patch
import pytest

from custom_components.climate_ip.exceptions import CannotConnect, TokenAcquisitionError
from custom_components.climate_ip.token_acquirer_yaml import GenericYamlTokenAcquirer
from .test_token_acquirer_yaml__common import mock_hass, listener_config


# --- Concrete Mocks to prevent AsyncMock coroutine leaks ---
class MockStreamReader:
    """Concrete mock for asyncio.StreamReader."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.idx = 0

    async def read(self, n=-1):
        if n != -1:
            assert n == 4096, f"Expected read(4096), got read({n})"
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
        self.written_data += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.wait_closed_called = True


def make_mock_timeout_cm():
    """Construct canonical AsyncMock context manager for asyncio.timeout."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock()
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx

async def mock_wait_for(coro, timeout=None):
    return await coro


@pytest.fixture
def acquirer(mock_hass, listener_config):
    """Create a listener mode acquirer instance."""
    return GenericYamlTokenAcquirer(mock_hass, "192.168.1.50", listener_config, cert_path="ac14k_m.pem")


async def test_start_listener_server_success(acquirer):
    """Test custom TCP server starting successfully."""
    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=mock_ssl_ctx) as mock_create_ssl,
        patch("asyncio.start_server", return_value=mock_server) as mock_start_server,
    ):
        await acquirer._start_listener_server()

        assert acquirer._server == mock_server
        mock_create_ssl.assert_called_once_with(
            cert_path=acquirer._resolve_cert_path("ac14k_m.pem"),
            ciphers="HIGH:!aNULL:!MD5:@SECLEVEL=0",
            is_server=True,
        )
        mock_start_server.assert_called_once_with(
            acquirer._handle_client, "192.168.1.100", 8889, ssl=mock_ssl_ctx
        )


async def test_start_listener_server_fallback_bind_ip(mock_hass, listener_config):
    """Test bind_ip falling back to 0.0.0.0 when local_ip is empty."""
    mock_hass.config.api.local_ip = None
    acq = GenericYamlTokenAcquirer(mock_hass, "192.168.1.50", listener_config, "ac14k_m.pem")

    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=mock_ssl_ctx),
        patch("asyncio.start_server", return_value=mock_server) as mock_start_server,
    ):
        await acq._start_listener_server()
        assert mock_start_server.call_args[0][1] == "0.0.0.0"


async def test_initiate_pairing_success(acquirer):
    """Test a successful pairing initiation sending the request."""
    mock_ssl_ctx = MagicMock()

    with (
        patch.object(acquirer, "_start_listener_server", new_callable=AsyncMock),
        patch("asyncio.open_connection") as mock_open_connection,
        patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=mock_ssl_ctx),
    ):
        mock_reader = MockStreamReader([b"HTTP/1.1 200 OK\r\n\r\n"])
        mock_writer = MockStreamWriter()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        res = await acquirer.async_initiate_pairing()

        mock_open_connection.assert_called_once_with(
            "192.168.1.50", 8888, ssl=mock_ssl_ctx
        )
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True

        written_text = mock_writer.written_data.decode("utf-8")
        assert written_text.startswith("POST /devicetoken/request HTTP/1.1\r\n")
        assert "Host: 192.168.1.100:8889\r\n" in written_text
        assert "Content-Type: application/json\r\n" in written_text
        assert '{"DeviceToken":"xxxxxxxxxxx"}' in written_text
        
        assert res == {"ok": True, "config": "listener_started"}


async def test_wait_for_token_success(acquirer):
    """Test successfully waiting for and receiving a token."""
    acquirer._received_token = "new_secret_token"
    mock_timeout_ctx = make_mock_timeout_cm()

    async def mock_wait():
        pass

    acquirer._token_received_event.wait = mock_wait

    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout", return_value=mock_timeout_ctx) as mock_timeout,
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        token = await acquirer.async_wait_for_token()
        assert token == "new_secret_token"
        assert mock_timeout.call_args_list == [call(60)]
        mock_close.assert_called_once()


async def test_wait_for_token_timeout(acquirer):
    """Test waiting for a token timing out."""
    mock_timeout_ctx = make_mock_timeout_cm()

    async def mock_wait():
        raise TimeoutError

    acquirer._token_received_event.wait = mock_wait

    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout", return_value=mock_timeout_ctx),
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        with pytest.raises(TimeoutError):
            await acquirer.async_wait_for_token()
        mock_close.assert_called_once()


async def test_handle_client_chunk_accumulation_and_regex(acquirer):
    """Test TCP client handler extracting token via regex."""
    mock_timeout_ctx = make_mock_timeout_cm()

    chunk = b'HTTP/1.1 200 OK\r\nDeviceToken: "chunked_token_123"\r\n}'
    mock_reader = MockStreamReader([chunk])
    mock_writer = MockStreamWriter()

    with patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for", side_effect=mock_wait_for):
        await acquirer._handle_client(mock_reader, mock_writer)

        assert acquirer._received_token == "chunked_token_123"
        assert acquirer._token_received_event.is_set()
        assert b"200 OK" in mock_writer.written_data
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True


async def test_handle_client_no_token(acquirer):
    """Test TCP client handler receiving valid payload without a DeviceToken."""
    mock_timeout_ctx = make_mock_timeout_cm()
    payload = json.dumps({"OtherData": "No token here"}).encode("utf-8")
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    with patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for", side_effect=mock_wait_for):
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

    with patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for", side_effect=mock_wait_for):
        await acquirer._handle_client(mock_reader, mock_writer)

        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True
