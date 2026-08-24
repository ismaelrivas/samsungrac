# ruff: noqa: F811, F401, F841
# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,missing-function-docstring,too-few-public-methods
"""Tests for GenericYamlTokenAcquirer in listener mode (8888 pairing)."""

import asyncio
import json
import ssl
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.climate_ip.exceptions import CannotConnect, TokenAcquisitionError
from custom_components.climate_ip.token_acquirer_yaml import GenericYamlTokenAcquirer

from .test_token_acquirer_yaml__common import listener_config, mock_hass


# --- Concrete Mocks to prevent AsyncMock coroutine leaks ---
class MockStreamReader:
    """Concrete mock for asyncio.StreamReader."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.idx = 0
        self.last_read_size = None

    async def read(self, n=-1):
        self.last_read_size = n
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


async def mock_wait_for(coro, timeout_seconds=None, **kwargs):
    return await coro


@pytest.fixture
def acquirer(mock_hass, listener_config):
    """Create a listener mode acquirer instance."""
    return GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, cert_path="ac14k_m.pem"
    )


async def test_start_listener_server_success(acquirer):
    """Test custom TCP server starting successfully with resolved cert and ciphers."""
    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_create_ssl,
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


async def test_start_listener_server_custom_port_and_ciphers(
    mock_hass, listener_config
):
    """Test listener server startup with custom port and ciphers in config."""
    listener_config["listener"]["port"] = 9999
    listener_config["tls_config"]["ciphers"] = ["CUSTOM-CIPHER-SUITE"]
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, cert_path="ac14k_m.pem"
    )

    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_create_ssl,
        patch("asyncio.start_server", return_value=mock_server) as mock_start_server,
    ):
        await acq._start_listener_server()
        assert mock_start_server.call_args[0][2] == 9999
        mock_create_ssl.assert_called_once_with(
            cert_path=acq._resolve_cert_path("ac14k_m.pem"),
            ciphers="CUSTOM-CIPHER-SUITE",
            is_server=True,
        )


async def test_start_listener_server_fallback_bind_ip(mock_hass, listener_config):
    """Test bind_ip falling back to 0.0.0.0 when local_ip is empty."""
    mock_hass.config.api.local_ip = None
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, "ac14k_m.pem"
    )

    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ),
        patch("asyncio.start_server", return_value=mock_server) as mock_start_server,
    ):
        await acq._start_listener_server()
        assert mock_start_server.call_args[0][1] == "0.0.0.0"


async def test_initiate_pairing_success(acquirer):
    """Test a successful pairing initiation sending the request with complete assertions."""
    mock_ssl_ctx = MagicMock()
    captured_timeouts = []

    async def spy_wait_for(coro, timeout_seconds=None, **kwargs):
        captured_timeouts.append(kwargs.get("timeout", timeout_seconds))
        return await coro

    with (
        patch.object(
            acquirer, "_start_listener_server", new_callable=AsyncMock
        ) as mock_start,
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_ssl,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
            side_effect=spy_wait_for,
        ),
    ):
        mock_reader = MockStreamReader([b"HTTP/1.1 200 OK\r\n\r\n"])
        mock_writer = MockStreamWriter()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        res = await acquirer.async_initiate_pairing()

        assert captured_timeouts == [5.0]
        mock_start.assert_called_once()
        mock_ssl.assert_called_once_with(
            cert_path=acquirer._resolve_cert_path("ac14k_m.pem"),
            ciphers="HIGH:!aNULL:!MD5:@SECLEVEL=0",
            verify_mode=ssl.CERT_NONE,
        )
        mock_open_connection.assert_called_once_with(
            "192.168.1.50", 8888, ssl=mock_ssl_ctx
        )
        assert mock_reader.last_read_size == 4096
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True

        written_text = mock_writer.written_data.decode("utf-8")
        assert written_text.startswith("POST /devicetoken/request HTTP/1.1\r\n")
        assert "Host: 192.168.1.100:8889\r\n" in written_text
        assert "Content-Type: application/json\r\n" in written_text
        assert "Content-Length: 29\r\n" in written_text
        assert '{"DeviceToken":"xxxxxxxxxxx"}' in written_text

        assert res == {"ok": True, "config": "listener_started"}


async def test_initiate_pairing_listener_defaults_when_config_empty(mock_hass):
    """Test initiate pairing fallbacks when request_pairing and tls_config are completely omitted."""
    acq = GenericYamlTokenAcquirer(
        mock_hass,
        "192.168.1.50",
        {"mode": "listener", "listener": {"port": 8889}},
        cert_path=None,
    )
    mock_ssl_ctx = MagicMock()

    with (
        patch.object(
            acq, "_start_listener_server", new_callable=AsyncMock
        ) as mock_start,
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_ssl,
    ):
        mock_reader = MockStreamReader([b"HTTP/1.1 200 OK\r\n\r\n"])
        mock_writer = MockStreamWriter()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        res = await acq.async_initiate_pairing()

        mock_start.assert_called_once()
        mock_ssl.assert_called_once_with(
            cert_path=None,
            ciphers="HIGH",
            verify_mode=ssl.CERT_NONE,
        )
        mock_open_connection.assert_called_once_with(
            "192.168.1.50", 8888, ssl=mock_ssl_ctx
        )
        assert mock_reader.last_read_size == 4096
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True

        written_text = mock_writer.written_data.decode("utf-8")
        assert written_text.startswith("POST /devicetoken/request HTTP/1.1\r\n")
        assert "Host: 192.168.1.100:8889\r\n" in written_text
        # No payload or headers configured -> ends with empty line and empty body
        assert written_text.endswith("\r\n\r\n")
        assert "Content-Length" not in written_text

        assert res == {"ok": True, "config": "listener_started"}


async def test_initiate_pairing_listener_read_response_timeout_swallowed(acquirer):
    """Test that timeout during initial fire-and-forget response read is swallowed."""
    mock_ssl_ctx = MagicMock()

    with (
        patch.object(acquirer, "_start_listener_server", new_callable=AsyncMock),
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ),
    ):
        mock_reader = MockStreamReader([])

        async def mock_read_timeout(*args, **kwargs):
            raise TimeoutError("Initial response read timed out")

        mock_reader.read = mock_read_timeout

        mock_writer = MockStreamWriter()
        mock_open_connection.return_value = (mock_reader, mock_writer)

        res = await acquirer.async_initiate_pairing()
        assert res == {"ok": True, "config": "listener_started"}
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True


async def test_initiate_pairing_listener_body_bytes_and_custom_headers(
    mock_hass, listener_config
):
    """Test initiate pairing with byte payload, custom path and existing Content-Length."""
    listener_config["request_pairing"]["path"] = "/custom/devicetoken"
    listener_config["request_pairing"]["port"] = 7777
    listener_config["request_pairing"]["payload"] = b'{"DeviceToken":"bytes_token"}'
    listener_config["request_pairing"]["headers"] = {
        "Content-Type": "application/json",
        "Content-Length": "28",
    }
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, cert_path="ac14k_m.pem"
    )

    with (
        patch.object(acq, "_start_listener_server", new_callable=AsyncMock),
        patch("asyncio.open_connection") as mock_open,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
    ):
        mock_reader = MockStreamReader([b"HTTP/1.1 200 OK\r\n\r\n"])
        mock_writer = MockStreamWriter()
        mock_open.return_value = (mock_reader, mock_writer)

        res = await acq.async_initiate_pairing()
        mock_open.assert_called_once_with(
            "192.168.1.50", 7777, ssl=mock_open.call_args.kwargs["ssl"]
        )

        written_text = mock_writer.written_data.decode("utf-8")
        assert "POST /custom/devicetoken HTTP/1.1\r\n" in written_text
        assert "Content-Length: 28\r\n" in written_text
        assert '{"DeviceToken":"bytes_token"}' in written_text
        assert res == {"ok": True, "config": "listener_started"}


async def test_wait_for_token_success(acquirer):
    """Test successfully waiting for and receiving a token."""
    acquirer._received_token = "new_secret_token"
    mock_timeout_ctx = make_mock_timeout_cm()

    async def mock_wait():
        pass

    acquirer._token_received_event.wait = mock_wait

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=mock_timeout_ctx,
        ) as mock_timeout,
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        token = await acquirer.async_wait_for_token()
        assert token == "new_secret_token"
        assert mock_timeout.call_args_list == [call(60)]
        mock_close.assert_called_once()


async def test_wait_for_token_custom_timeout(mock_hass, listener_config):
    """Test wait_for_token with custom timeout_seconds in listener config."""
    listener_config["listener"]["timeout_seconds"] = 120
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, "ac14k_m.pem"
    )
    acq._received_token = "custom_timeout_token"

    async def mock_wait():
        pass

    acq._token_received_event.wait = mock_wait
    mock_timeout_ctx = make_mock_timeout_cm()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=mock_timeout_ctx,
        ) as mock_timeout,
        patch.object(acq, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        token = await acq.async_wait_for_token()
        assert token == "custom_timeout_token"
        mock_timeout.assert_called_once_with(120)
        mock_close.assert_called_once()


async def test_wait_for_token_timeout(acquirer):
    """Test waiting for a token timing out."""
    mock_timeout_ctx = make_mock_timeout_cm()

    async def mock_wait():
        raise TimeoutError

    acquirer._token_received_event.wait = mock_wait

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=mock_timeout_ctx,
        ),
        patch.object(acquirer, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        with pytest.raises(TimeoutError):
            await acquirer.async_wait_for_token()
        mock_close.assert_called_once()


async def test_handle_client_chunk_accumulation_and_regex(acquirer):
    """Test TCP client handler extracting token via regex and sending default 200 OK response."""
    chunk = b'HTTP/1.1 200 OK\r\nDeviceToken: "chunked_token_123"\r\n}'
    mock_reader = MockStreamReader([chunk])
    mock_writer = MockStreamWriter()

    captured_timeouts = []

    async def spy_wait_for(coro, timeout_seconds=None, **kwargs):
        captured_timeouts.append(kwargs.get("timeout", timeout_seconds))
        return await coro

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=spy_wait_for,
    ):
        await acquirer._handle_client(mock_reader, mock_writer)

        assert captured_timeouts == [10.0]
        assert mock_reader.last_read_size == 4096
        assert acquirer._received_token == "chunked_token_123"
        assert acquirer._token_received_event.is_set()
        assert mock_writer.written_data == b"HTTP/1.1 200 OK\r\n\r\n"
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True


async def test_handle_client_custom_buffer_size(mock_hass, listener_config):
    """Test TCP client handler using configured buffer_size from auth_config."""
    listener_config["buffer_size"] = 1024
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, "ac14k_m.pem"
    )
    mock_reader = MockStreamReader([b'HTTP/1.1 200 OK\r\nDeviceToken: "buf_token"\r\n'])
    mock_writer = MockStreamWriter()

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        await acq._handle_client(mock_reader, mock_writer)
        assert mock_reader.last_read_size == 1024
        assert acq._received_token == "buf_token"


async def test_handle_client_explicit_utf8_decoding(mock_hass, listener_config):
    """Test that client handler decodes payload with explicit utf-8 and ignore errors."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, "ac14k_m.pem"
    )
    mock_data = MagicMock(spec=bytes)
    mock_data.decode.return_value = 'DeviceToken: "explicit_utf8_tok"'

    mock_reader = AsyncMock()
    mock_reader.read.return_value = mock_data
    mock_writer = MockStreamWriter()

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        await acq._handle_client(mock_reader, mock_writer)
        mock_data.decode.assert_called_once_with("utf-8", errors="ignore")
        assert acq._received_token == "explicit_utf8_tok"


async def test_handle_client_default_success_response(mock_hass):
    """Test client handler sending default HTTP/1.1 200 OK when listener config has no success_response."""
    acq = GenericYamlTokenAcquirer(
        mock_hass,
        "192.168.1.50",
        {
            "mode": "listener",
            "extract_template": {"regex": r'DeviceToken:\s*"([^"]+)"'},
        },
        cert_path=None,
    )
    mock_reader = MockStreamReader([b'DeviceToken: "default_succ_token"'])
    mock_writer = MockStreamWriter()

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        await acq._handle_client(mock_reader, mock_writer)
        assert mock_reader.last_read_size == 4096
        assert acq._received_token == "default_succ_token"
        assert acq._token_received_event.is_set()
        assert mock_writer.written_data == b"HTTP/1.1 200 OK\r\n\r\n"


async def test_handle_client_custom_success_and_error_responses(
    mock_hass, listener_config
):
    """Test custom success and error response strings with line-ending normalization."""
    listener_config["listener"]["success_response"] = "HTTP/1.1 200 CUSTOM_OK\n\n"
    listener_config["listener"]["error_response"] = "HTTP/1.1 400 CUSTOM_BAD\n\n"
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, "ac14k_m.pem"
    )

    # Success branch (token present)
    mock_reader_succ = MockStreamReader([b'DeviceToken: "valid_token_abc"'])
    mock_writer_succ = MockStreamWriter()
    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        await acq._handle_client(mock_reader_succ, mock_writer_succ)
        assert acq._received_token == "valid_token_abc"
        assert mock_writer_succ.written_data == b"HTTP/1.1 200 CUSTOM_OK\r\n\r\n"

    # Reset token
    acq._received_token = None
    acq._token_received_event.clear()

    # Error branch (no token present)
    mock_reader_err = MockStreamReader([b'{"NoToken": "here"}'])
    mock_writer_err = MockStreamWriter()
    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        await acq._handle_client(mock_reader_err, mock_writer_err)
        assert acq._received_token is None
        assert not acq._token_received_event.is_set()
        assert mock_writer_err.written_data == b"HTTP/1.1 400 CUSTOM_BAD\r\n\r\n"


async def test_handle_client_no_regex_configured(mock_hass, listener_config):
    """Test client handler when extract_template is missing regex."""
    listener_config["extract_template"] = {}
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, "ac14k_m.pem"
    )

    mock_reader = MockStreamReader([b'DeviceToken: "token_123"'])
    mock_writer = MockStreamWriter()

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        await acq._handle_client(mock_reader, mock_writer)
        assert acq._received_token is None
        assert not acq._token_received_event.is_set()
        assert b"400 Bad Request" in mock_writer.written_data


async def test_handle_client_wait_for_timeout(acquirer):
    """Test client handler when asyncio.wait_for raises TimeoutError."""
    mock_reader = MockStreamReader([b""])
    mock_writer = MockStreamWriter()

    async def mock_wait_for_timeout(coro, timeout_seconds=None, **kwargs):
        raise TimeoutError("Read timeout in listener")

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for_timeout,
    ):
        await acquirer._handle_client(mock_reader, mock_writer)
        assert acquirer._received_token is None
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True


async def test_handle_client_exception_during_write(acquirer):
    """Test exception during client handling is caught and writer is closed."""
    payload = b'DeviceToken: "token_abc"\r\n}'
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()
    mock_writer.write = MagicMock(side_effect=RuntimeError("Socket write error"))

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        await acquirer._handle_client(mock_reader, mock_writer)

        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True


async def test_handle_client_wait_closed_exception_swallowed(acquirer):
    """Test that exceptions during writer.wait_closed are cleanly swallowed."""
    payload = b'DeviceToken: "token_abc"\r\n}'
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()
    mock_writer.wait_closed = AsyncMock(side_effect=ssl.SSLError("SSL close failure"))

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        # Should not raise exception
        await acquirer._handle_client(mock_reader, mock_writer)
        assert mock_writer.closed is True


async def test_listener_mode_defaults_when_config_empty(mock_hass):
    """Test listener mode behavior when auth_config is minimal (testing all default fallbacks)."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", {"mode": "listener"}, cert_path=None
    )

    # 1. Test _start_listener_server default port and ciphers
    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()
    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_create_ssl,
        patch("asyncio.start_server", return_value=mock_server) as mock_start_server,
    ):
        await acq._start_listener_server()
        assert mock_start_server.call_args[0][2] == 8889
        mock_create_ssl.assert_called_once_with(
            cert_path=None,
            ciphers="HIGH:!aNULL:!MD5:@SECLEVEL=0",
            is_server=True,
        )

    # 2. Test wait_for_token default timeout 60
    acq._received_token = "token_from_defaults"
    acq._token_received_event.set()
    mock_timeout_ctx = make_mock_timeout_cm()
    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=mock_timeout_ctx,
        ) as mock_timeout,
        patch.object(acq, "async_close", new_callable=AsyncMock),
    ):
        token = await acq.async_wait_for_token()
        assert token == "token_from_defaults"
        mock_timeout.assert_called_once_with(60)

    # 3. Test _handle_client default error response (since no extract_regex is in minimal config)
    acq._received_token = None
    mock_reader = MockStreamReader([b'DeviceToken: "extracted_123"'])
    mock_writer = MockStreamWriter()
    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.wait_for",
        side_effect=mock_wait_for,
    ):
        await acq._handle_client(mock_reader, mock_writer)
        assert mock_writer.written_data == b"HTTP/1.1 400 Bad Request\r\n\r\n"
        assert acq._received_token is None
