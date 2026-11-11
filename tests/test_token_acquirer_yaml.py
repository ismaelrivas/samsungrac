"""Canonical, orthogonal test suite for GenericYamlTokenAcquirer."""

import asyncio
import re
import ssl
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.climate_ip.exceptions import (
    AuthTurnedOffError,
    CannotConnect,
    TokenAcquisitionError,
)
from custom_components.climate_ip.token_acquirer_yaml import (
    GenericYamlTokenAcquirer,
    _encode_stream_payload,
    _extract_token,
)


def test_encode_stream_payload_bytes() -> None:
    """Test encoding bytes directly returns raw payload."""
    raw = b"raw_bytes"
    assert _encode_stream_payload(raw) is raw


class MockStreamReader:
    """Concrete mock for asyncio.StreamReader."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.idx = 0
        self.last_read_size = None

    async def read(self, n: int = -1) -> bytes:
        self.last_read_size = n
        if self.idx < len(self.chunks):
            chunk = self.chunks[self.idx]
            self.idx += 1
            return chunk
        return b""


class MockStreamWriter:
    """Concrete mock for asyncio.StreamWriter."""

    def __init__(self) -> None:
        self.written_data = b""
        self.closed = False
        self.wait_closed_called = False

    def write(self, data: bytes) -> None:
        self.written_data += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.wait_closed_called = True


def make_mock_timeout_cm() -> MagicMock:
    """Construct canonical AsyncMock context manager for asyncio.timeout."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock()
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.api.local_ip = "192.168.1.100"
    hass.config.path.side_effect = lambda *args: "/".join(args)
    return hass


@pytest.fixture
def stream_config() -> dict[str, Any]:
    """Mock config for stream mode (2878)."""
    return {
        "mode": "stream",
        "buffer_size": 4096,
        "reconnect_delay": 0.01,
        "tls_config": {
            "strategies": [
                {"cert": "__user_cert__", "verify_mode": "CERT_REQUIRED"},
                {"cert": "__default_cert__", "verify_mode": "CERT_NONE"},
            ],
            "ciphers": ["HIGH:!DH:!aNULL:@SECLEVEL=0"],
            "default_cert": "ac14k_m.pem",
        },
        "request_pairing": {
            "port": 2878,
            "payload": '<Request Type="GetToken" />\r\n',
            "success_template": {
                "match": 'Status="Ready"',
                "fallback_match": 'InvalidateAccount="true"',
            },
        },
        "wait_token": {"timeout_seconds": 45},
        "error_template": {"match": 'ErrorCode="301"'},
        "extract_template": {"regex": r'Token="(.*?)"'},
    }


@pytest.fixture
def listener_config() -> dict[str, Any]:
    """Mock config for listener mode (8888)."""
    return {
        "mode": "listener",
        "buffer_size": 4096,
        "listener": {
            "port": 8889,
            "timeout_seconds": 60,
            "success_response": "HTTP/1.1 200 OK\r\n\r\n",
            "error_response": "HTTP/1.1 400 Bad Request\r\n\r\n",
        },
        "tls_config": {
            "ciphers": ["HIGH:!aNULL:!MD5:@SECLEVEL=0"],
            "default_cert": "ac14k_m.pem",
        },
        "request_pairing": {
            "port": 8888,
            "path": "/devicetoken/request",
            "headers": {"Content-Type": "application/json"},
            "payload": '{"DeviceToken":"xxxxxxxxxxx"}',
        },
        "extract_template": {"regex": r'DeviceToken[\s"\':]*([a-zA-Z0-9_\-]+)'},
    }


@pytest.fixture
def listener_acquirer(mock_hass, listener_config) -> GenericYamlTokenAcquirer:
    """Create a listener mode acquirer instance."""
    return GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, cert_path="ac14k_m.pem"
    )


@pytest.fixture
def stream_acquirer(mock_hass, stream_config) -> GenericYamlTokenAcquirer:
    """Create a stream mode acquirer instance."""
    return GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )


def test_initialization(mock_hass, stream_config):
    """Test that the acquirer initializes state variables correctly."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    assert acq.hass is mock_hass
    assert acq.ip_address == "192.168.1.100"
    assert acq.auth_config == stream_config
    assert acq.user_cert_path is None

    # Verify initial listener state
    assert not acq._token_received_event.is_set()
    assert acq._received_token is None
    assert acq._server is None

    # Verify initial stream state
    assert acq._reader is None
    assert acq._writer is None


def test_resolve_cert_path(mock_hass, stream_config):
    """Test the certificate path resolution logic thoroughly."""
    # None and empty sentinel
    acq_empty = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    assert acq_empty._resolve_cert_path(None) is None
    assert acq_empty._resolve_cert_path("") == ""

    # User cert path (Sentinel)
    acq1 = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="/my/user/cert.pem"
    )
    assert acq1._resolve_cert_path("__user_cert__") == "/my/user/cert.pem"

    # User cert sentinel when user_cert_path is None
    assert acq_empty._resolve_cert_path("__user_cert__") is None

    # Default cert path (Sentinel) with valid tls_config
    acq2 = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    res = acq2._resolve_cert_path("__default_cert__")
    assert res is not None
    assert res.endswith("ac14k_m.pem")
    assert "/" in res  # Should be joined with __file__

    # Default cert sentinel when auth_config has empty/no tls_config (kills get(None, {}) / get("tls_config", None))
    acq_no_tls = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", {}, cert_path=None
    )
    assert acq_no_tls._resolve_cert_path("__default_cert__") is None

    # Absolute Unix path directly (has /)
    assert acq2._resolve_cert_path("/absolute/path.pem") == "/absolute/path.pem"

    # Windows absolute path (has \)
    assert acq2._resolve_cert_path("C:\\windows\\path.pem") == "C:\\windows\\path.pem"

    # Relative path with Unix subfolder (has /) -> must NOT be joined
    assert acq2._resolve_cert_path("certs/relative.pem") == "certs/relative.pem"

    # Relative path with Windows subfolder (has \) -> must NOT be joined
    assert acq2._resolve_cert_path("certs\\relative.pem") == "certs\\relative.pem"

    # Relative filename without any slashes -> MUST be joined with __file__.parent
    res_simple = acq2._resolve_cert_path("standalone_cert.pem")
    assert res_simple is not None
    assert res_simple.endswith("standalone_cert.pem")
    assert "/" in res_simple
    assert res_simple != "standalone_cert.pem"


async def test_async_close(mock_hass, stream_config):
    """Test closing active server and calling close on None."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    # Closing when server/writer are None (no-op)
    await acq.async_close()
    assert acq._server is None
    assert acq._writer is None

    # Closing with active server and writer
    mock_server = AsyncMock()
    mock_writer = AsyncMock()
    acq._server = mock_server
    acq._writer = mock_writer

    await acq.async_close()

    mock_server.close.assert_called_once()
    mock_server.wait_closed.assert_called_once()
    mock_writer.close.assert_called_once()
    mock_writer.wait_closed.assert_called_once()

    assert acq._server is None
    assert acq._writer is None


def test_extract_token_helper():
    """Test pure protocol helper _extract_token."""
    assert _extract_token("", r"Token: (\S+)") is None
    assert _extract_token("text", None) is None
    assert _extract_token("No match here", r"Token: (\S+)") is None

    # Test default strip_quotes=False preserves surrounding quotes (kills strip_quotes=True mutant)
    res = _extract_token('Token: "SECRET"', r"Token: (\S+)")
    assert res == '"SECRET"'

    # Test strip_quotes=True strips quotes
    res_stripped = _extract_token('Token: "SECRET"', r"Token: (\S+)", strip_quotes=True)
    assert res_stripped == "SECRET"


@pytest.mark.asyncio
async def test_wait_closed_exception_in_listener(mock_hass, listener_config):
    """Cover lines 303-304: Exception during writer.wait_closed() in listener mode."""
    acq = GenericYamlTokenAcquirer(mock_hass, "1.2.3.4", listener_config)

    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'DeviceToken="1234"'
    mock_writer = AsyncMock()
    mock_writer.wait_closed.side_effect = Exception("Intentional exception")

    with patch.object(acq, "_start_listener_server", return_value=None):
        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            res = await acq.async_initiate_pairing()
            assert res["ok"] is True


@pytest.mark.asyncio
async def test_stream_mode_no_connection(mock_hass, stream_config):
    """Cover line 321: _writer or _reader is None in stream mode."""
    acq = GenericYamlTokenAcquirer(mock_hass, "1.2.3.4", stream_config)
    with patch.object(acq, "_connect_stream", return_value={"ok": True}):
        # Both None
        with pytest.raises(
            TokenAcquisitionError, match="Connection stream not established"
        ):
            await acq.async_initiate_pairing()

        # writer is set, reader is None (kills 'or' -> 'and' mutant)
        acq._writer = AsyncMock()
        acq._reader = None
        with pytest.raises(
            TokenAcquisitionError, match="Connection stream not established"
        ):
            await acq.async_initiate_pairing()

        # writer is None, reader is set (kills 'or' -> 'and' mutant)
        acq._writer = None
        acq._reader = AsyncMock()
        with pytest.raises(
            TokenAcquisitionError, match="Connection stream not established"
        ):
            await acq.async_initiate_pairing()


@pytest.mark.asyncio
async def test_unsupported_mode_initiate(mock_hass):
    """Cover line 347: unsupported mode in async_initiate_pairing."""
    acq = GenericYamlTokenAcquirer(mock_hass, "1.2.3.4", {"mode": "invalid"})
    with pytest.raises(TokenAcquisitionError, match="Unsupported authentication mode"):
        await acq.async_initiate_pairing()


@pytest.mark.asyncio
async def test_listener_wait_token_is_none(mock_hass, listener_config):
    """Cover line 361: wait finishes but token is still None."""
    acq = GenericYamlTokenAcquirer(mock_hass, "1.2.3.4", listener_config)

    async def mock_wait():
        return True

    acq._token_received_event.wait = mock_wait
    # _received_token is None by default
    with patch.object(acq, "async_close", new_callable=AsyncMock):
        with pytest.raises(TokenAcquisitionError, match="Token was not received"):
            await acq.async_wait_for_token()


@pytest.mark.asyncio
async def test_unsupported_mode_wait(mock_hass):
    """Cover line 402: unsupported mode in async_wait_for_token."""
    acq = GenericYamlTokenAcquirer(mock_hass, "1.2.3.4", {"mode": "invalid"})
    with (
        patch.object(acq, "async_close", new_callable=AsyncMock),
        pytest.raises(TokenAcquisitionError, match="Unsupported authentication mode"),
    ):
        await acq.async_wait_for_token()


async def test_start_listener_server_success(listener_acquirer):
    """Test custom TCP server starting successfully with resolved cert and ciphers."""
    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_create_ssl,
        patch("asyncio.start_server", return_value=mock_server) as mock_start_server,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml._LOGGER"
        ) as mock_logger,
    ):
        await listener_acquirer._start_listener_server()

        assert listener_acquirer._server == mock_server
        mock_create_ssl.assert_called_once_with(
            cert_path=listener_acquirer._resolve_cert_path("ac14k_m.pem"),
            ciphers="HIGH:!aNULL:!MD5:@SECLEVEL=0",
            is_server=True,
        )
        mock_start_server.assert_called_once_with(
            listener_acquirer._handle_client, "192.168.1.100", 8889, ssl=mock_ssl_ctx
        )
        mock_logger.info.assert_not_called()


async def test_start_listener_server_cleans_up_lingering_server(listener_acquirer):
    """Test that any lingering server from a previous attempt is closed and awaited."""
    mock_lingering_server = AsyncMock()
    listener_acquirer._server = mock_lingering_server

    mock_ssl_ctx = MagicMock()
    mock_new_server = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ),
        patch("asyncio.start_server", return_value=mock_new_server),
    ):
        await listener_acquirer._start_listener_server()

        mock_lingering_server.close.assert_called_once()
        mock_lingering_server.wait_closed.assert_awaited_once()
        assert listener_acquirer._server == mock_new_server


async def test_start_listener_server_retry_on_eaddrinuse_success(listener_acquirer):
    """Test retrying on next consecutive port when initial port is already in use (EADDRINUSE)."""
    mock_ssl_ctx = MagicMock()
    mock_server = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ),
        patch(
            "asyncio.start_server",
            side_effect=[OSError(98, "Address already in use"), mock_server],
        ) as mock_start_server,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml._LOGGER"
        ) as mock_logger,
    ):
        await listener_acquirer._start_listener_server()

        assert listener_acquirer._server == mock_server
        assert mock_start_server.call_count == 2
        assert mock_start_server.call_args_list == [
            call(
                listener_acquirer._handle_client,
                "192.168.1.100",
                8889,
                ssl=mock_ssl_ctx,
            ),
            call(
                listener_acquirer._handle_client,
                "192.168.1.100",
                8890,
                ssl=mock_ssl_ctx,
            ),
        ]
        # offset > 0 triggered logger info exactly once
        mock_logger.info.assert_called_once_with(
            "Listener port %s was busy, successfully bound to fallback port %s",
            8889,
            8890,
        )
        mock_logger.debug.assert_called_once_with(
            "Port %s already in use, trying next port", 8889
        )
        assert listener_acquirer.auth_config["listener"]["port"] == 8890


async def test_start_listener_server_eaddrinuse_exhaustion_raises(listener_acquirer):
    """Test that exhaustion of all retry attempts due to EADDRINUSE raises the final OSError."""
    mock_ssl_ctx = MagicMock()
    addr_in_use_error = OSError(98, "Address already in use")

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ),
        patch(
            "asyncio.start_server",
            side_effect=addr_in_use_error,
        ) as mock_start_server,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml._LOGGER"
        ) as mock_logger,
    ):
        with pytest.raises(OSError) as exc_info:
            await listener_acquirer._start_listener_server()

        assert exc_info.value is addr_in_use_error
        assert exc_info.value.errno == 98
        assert mock_start_server.call_count == listener_acquirer.MAX_PORT_RETRIES
        assert mock_start_server.call_args_list == [
            call(
                listener_acquirer._handle_client,
                "192.168.1.100",
                8889 + i,
                ssl=mock_ssl_ctx,
            )
            for i in range(listener_acquirer.MAX_PORT_RETRIES)
        ]
        assert mock_logger.debug.call_count == listener_acquirer.MAX_PORT_RETRIES
        assert mock_logger.debug.call_args_list == [
            call("Port %s already in use, trying next port", 8889 + i)
            for i in range(listener_acquirer.MAX_PORT_RETRIES)
        ]
        mock_logger.info.assert_not_called()
        assert listener_acquirer._server is None


async def test_start_listener_server_unexpected_oserror_propagates_immediately(
    listener_acquirer,
):
    """Test that unexpected OSErrors (errno != 98) are raised immediately without retries."""
    mock_ssl_ctx = MagicMock()
    perm_error = OSError(13, "Permission denied")

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ),
        patch(
            "asyncio.start_server",
            side_effect=perm_error,
        ) as mock_start_server,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml._LOGGER"
        ) as mock_logger,
    ):
        with pytest.raises(OSError) as exc_info:
            await listener_acquirer._start_listener_server()

        assert exc_info.value is perm_error
        assert exc_info.value.errno == 13
        mock_start_server.assert_called_once_with(
            listener_acquirer._handle_client, "192.168.1.100", 8889, ssl=mock_ssl_ctx
        )
        mock_logger.debug.assert_not_called()
        mock_logger.info.assert_not_called()


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


async def test_initiate_pairing_success(listener_acquirer):
    """Test a successful pairing initiation sending the request with complete assertions."""
    mock_ssl_ctx = MagicMock()
    captured_timeouts = []

    async def spy_wait_for(coro, timeout_seconds=None, **kwargs):
        captured_timeouts.append(kwargs.get("timeout", timeout_seconds))
        return await coro

    with (
        patch.object(
            listener_acquirer, "_start_listener_server", new_callable=AsyncMock
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

        res = await listener_acquirer.async_initiate_pairing()

        assert captured_timeouts == [5.0]
        mock_start.assert_called_once()
        mock_ssl.assert_called_once_with(
            cert_path=listener_acquirer._resolve_cert_path("ac14k_m.pem"),
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


async def test_initiate_pairing_raw_socket_write_exception(listener_acquirer):
    """Test exception when writing/draining to raw socket during initiate pairing raises CannotConnect and closes."""
    mock_ssl_ctx = MagicMock()

    with (
        patch.object(
            listener_acquirer, "_start_listener_server", new_callable=AsyncMock
        ) as mock_start,
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ),
        patch.object(
            listener_acquirer, "async_close", new_callable=AsyncMock
        ) as mock_close,
    ):
        mock_reader = MockStreamReader([])
        mock_writer = MockStreamWriter()
        drain_error = OSError("Raw socket write/drain failed")
        mock_writer.drain = AsyncMock(side_effect=drain_error)
        mock_open_connection.return_value = (mock_reader, mock_writer)

        with pytest.raises(CannotConnect) as exc_info:
            await listener_acquirer.async_initiate_pairing()

        assert exc_info.value.__cause__ is drain_error
        assert (
            str(exc_info.value)
            == "Failed to connect to device via raw socket (192.168.1.50:8888): Raw socket write/drain failed"
        )
        mock_start.assert_called_once()
        mock_close.assert_called_once()
        assert mock_writer.closed is True
        assert mock_writer.wait_closed_called is True


async def test_initiate_pairing_raw_socket_timeout_custom_port(
    mock_hass, listener_config
):
    """Test TimeoutError on custom port raises CannotConnect with custom port and calls async_close."""
    listener_config["request_pairing"]["port"] = 7777
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.50", listener_config, "ac14k_m.pem"
    )

    with (
        patch.object(acq, "_start_listener_server", new_callable=AsyncMock),
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch.object(acq, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        timeout_err = TimeoutError("Connection timed out")
        mock_open_connection.side_effect = timeout_err

        with pytest.raises(CannotConnect) as exc_info:
            await acq.async_initiate_pairing()

        assert exc_info.value.__cause__ is timeout_err
        assert (
            str(exc_info.value)
            == "Failed to connect to device via raw socket (192.168.1.50:7777): Connection timed out"
        )
        mock_close.assert_called_once()


async def test_initiate_pairing_raw_socket_connection_error_default_port(mock_hass):
    """Test ConnectionError when request_pairing has no port specified (fallback to 8888)."""
    acq = GenericYamlTokenAcquirer(
        mock_hass,
        "192.168.1.50",
        {"mode": "listener", "listener": {"port": 8889}},
        cert_path=None,
    )

    with (
        patch.object(acq, "_start_listener_server", new_callable=AsyncMock),
        patch("asyncio.open_connection") as mock_open_connection,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch.object(acq, "async_close", new_callable=AsyncMock) as mock_close,
    ):
        conn_err = ConnectionError("Connection refused by peer")
        mock_open_connection.side_effect = conn_err

        with pytest.raises(CannotConnect) as exc_info:
            await acq.async_initiate_pairing()

        assert exc_info.value.__cause__ is conn_err
        assert (
            str(exc_info.value)
            == "Failed to connect to device via raw socket (192.168.1.50:8888): Connection refused by peer"
        )
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


async def test_handle_client_timeout_value(listener_acquirer):
    """Test that client handler uses exactly 10.0 seconds timeout."""
    mock_timeout_ctx = make_mock_timeout_cm()
    mock_reader = MockStreamReader([b'DeviceToken: "tok_123"'])
    mock_writer = MockStreamWriter()

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
        return_value=mock_timeout_ctx,
    ) as mock_timeout:
        await listener_acquirer._handle_client(mock_reader, mock_writer)
        mock_timeout.assert_called_once_with(10.0)
        assert listener_acquirer._received_token == "tok_123"


async def test_handle_client_chunk_accumulation_concatenation(listener_acquirer):
    """Test TCP client handler concatenating chunks across boundary where single chunks do not match regex."""
    chunk1 = b'POST / HTTP/1.1\r\nHost: 192.168.1.100\r\n\r\n{"DeviceTok'
    chunk2 = b'en": "accumulated_split_12345"}'
    mock_reader = MockStreamReader([chunk1, chunk2])
    mock_writer = MockStreamWriter()

    await listener_acquirer._handle_client(mock_reader, mock_writer)

    assert listener_acquirer._received_token == "accumulated_split_12345"
    assert listener_acquirer._token_received_event.is_set()
    assert b"200 OK" in mock_writer.written_data


async def test_handle_client_chunk_accumulation_and_regex(listener_acquirer):
    """Test TCP client handler extracting token via regex and sending default 200 OK response."""
    chunk = b'HTTP/1.1 200 OK\r\nDeviceToken: "chunked_token_123"\r\n}'
    mock_reader = MockStreamReader([chunk])
    mock_writer = MockStreamWriter()

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml._extract_token",
        wraps=_extract_token,
    ) as mock_extract:
        await listener_acquirer._handle_client(mock_reader, mock_writer)
        assert mock_extract.call_count == 1

    assert mock_reader.last_read_size == 4096
    assert listener_acquirer._received_token == "chunked_token_123"
    assert listener_acquirer._token_received_event.is_set()
    assert mock_writer.written_data == b"HTTP/1.1 200 OK\r\n\r\n"
    assert mock_writer.closed is True
    assert mock_writer.wait_closed_called is True


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
    await acq._handle_client(mock_reader_succ, mock_writer_succ)
    assert acq._received_token == "valid_token_abc"
    assert mock_writer_succ.written_data == b"HTTP/1.1 200 CUSTOM_OK\r\n\r\n"

    # Reset token
    acq._received_token = None
    acq._token_received_event.clear()

    # Error branch (no token present)
    mock_reader_err = MockStreamReader([b'{"NoToken": "here"}'])
    mock_writer_err = MockStreamWriter()
    await acq._handle_client(mock_reader_err, mock_writer_err)
    assert acq._received_token is None
    assert not acq._token_received_event.is_set()
    assert mock_writer_err.written_data == b"HTTP/1.1 400 CUSTOM_BAD\r\n\r\n"


async def test_handle_client_fallback_extraction_strips_quotes(listener_acquirer):
    """Test that fallback token extraction strictly extracts group(1) and strips quotes."""
    listener_acquirer.auth_config["extract_template"]["regex"] = r"Token[\s:]*([^\s]+)"
    data_payload = b'Token: "quoted_fallback_token"'
    mock_reader = MockStreamReader([data_payload])
    mock_writer = MockStreamWriter()

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.re.search",
        side_effect=[
            None,
            re.search(r"Token[\s:]*([^\s]+)", data_payload.decode("utf-8")),
        ],
    ):
        await listener_acquirer._handle_client(mock_reader, mock_writer)

        assert listener_acquirer._received_token == "quoted_fallback_token"
        assert listener_acquirer._token_received_event.is_set()
        assert b"200 OK" in mock_writer.written_data


async def test_handle_client_exception_during_write(listener_acquirer):
    """Test exception during client handling is caught and writer is closed."""
    payload = b'DeviceToken: "token_abc"\r\n}'
    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()
    mock_writer.write = MagicMock(side_effect=RuntimeError("Socket write error"))

    await listener_acquirer._handle_client(mock_reader, mock_writer)

    assert mock_writer.closed is True
    assert mock_writer.wait_closed_called is True


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
    await acq._handle_client(mock_reader, mock_writer)
    assert mock_writer.written_data == b"HTTP/1.1 400 Bad Request\r\n\r\n"
    assert acq._received_token is None


async def test_yaml_cert_not_found(stream_acquirer, caplog):
    """Test that a CertNotFound error is gracefully caught and logs properly if all strategies fail."""
    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
        side_effect=FileNotFoundError("missing cert"),
    ):
        with pytest.raises(CannotConnect) as exc_info:
            await stream_acquirer.async_initiate_pairing()
        assert "All YAML TLS strategies failed" in str(exc_info.value)


async def test_connect_cert_path_kwarg_propagation(mock_hass, stream_config):
    """Test that cert_path is correctly propagated as a kwarg."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem"
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ) as mock_ssl:
            config = await acq._connect_stream()

    first_call_kwargs = mock_ssl.call_args_list[0].kwargs
    assert first_call_kwargs["cert_path"] == "/my/cert.pem"
    assert first_call_kwargs["ciphers"] == "HIGH:!DH:!aNULL:@SECLEVEL=0"
    assert first_call_kwargs["verify_mode"] == ssl.CERT_REQUIRED
    assert config == {"cert": "/my/cert.pem", "verify_mode": ssl.CERT_REQUIRED}


async def test_connect_stream_config_extraction_and_sleep_delay(
    mock_hass, stream_config
):
    """Test complete extraction of TLS strategies, ciphers, timeouts, and sleep delay."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem"
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    call_count = 0

    async def mock_create_ssl(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ssl.SSLError("Mock failure to trigger sleep delay")
        return MagicMock()

    mock_timeout_ctx = make_mock_timeout_cm()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            side_effect=mock_create_ssl,
        ),
        patch(
            "asyncio.open_connection", return_value=(mock_reader, mock_writer)
        ) as mock_open,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=mock_timeout_ctx,
        ) as mock_timeout,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        config = await acq._connect_stream()

        # Check sleep was called with exactly reconnect_delay (0.01)
        mock_sleep.assert_called_once_with(0.01)
        # Check open_connection called with host and port from config
        mock_open.assert_called_once_with(
            "192.168.1.100", 2878, ssl=mock_open.call_args.kwargs["ssl"]
        )
        # Check timeouts: open connection (15.0) and handshake (5.0)
        assert mock_timeout.call_args_list == [call(15.0), call(5.0)]
        assert mock_reader.read.call_args_list == [call(4096)]
        assert config is not None


async def test_connect_stream_missing_ciphers_raises_cannot_connect(
    mock_hass, stream_config
):
    """Test _connect_stream when tls_config has no ciphers key raises CannotConnect cleanly."""
    stream_config["tls_config"]["strategies"] = [{"cert": "/my/cert.pem"}]
    stream_config["tls_config"].pop("ciphers", None)
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem"
    )

    with pytest.raises(CannotConnect, match="All YAML TLS strategies failed"):
        await acq._connect_stream()


async def test_connect_stream_default_reconnect_delay(mock_hass, stream_config):
    """Test _connect_stream falling back to default 1.5 reconnect_delay."""
    stream_config.pop("reconnect_delay", None)
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem"
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    call_count = 0

    async def mock_create_ssl(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ssl.SSLError("Mock SSL failure")
        return MagicMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            side_effect=mock_create_ssl,
        ),
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        await acq._connect_stream()
        mock_sleep.assert_called_once_with(1.5)


async def test_connect_stream_strategy_default_verify_mode(mock_hass, stream_config):
    """Test _connect_stream default verify_mode CERT_NONE when strategy omits verify_mode."""
    stream_config["tls_config"]["strategies"] = [{"cert": "/my/cert.pem"}]
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem"
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_ssl_mod = MagicMock()
    mock_ssl_mod.CERT_NONE = 99999

    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.ssl", mock_ssl_mod),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ) as mock_ssl,
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
    ):
        await acq._connect_stream()
        assert mock_ssl.call_args_list[0].kwargs["verify_mode"] == 99999


async def test_connect_stream_default_buffer_size(mock_hass, stream_config):
    """Test _connect_stream handshake defaults to 4096 when buffer_size is omitted in config."""
    stream_config.pop("buffer_size", None)
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem"
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
    ):
        await acq._connect_stream()
        assert mock_reader.read.call_args_list == [call(4096)]


async def test_connect_stream_user_cert_relative_preserves_user_cert_path(
    mock_hass, stream_config
):
    """Test that __user_cert__ strategy restores original user_cert_path even if relative."""
    stream_config["tls_config"]["strategies"] = [
        {"cert": "__user_cert__", "verify_mode": "CERT_NONE"}
    ]
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="relative_user.pem"
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
    ):
        config = await acq._connect_stream()
        assert config["cert"] == "relative_user.pem"


async def test_connect_stream_skips_user_cert_when_missing(
    stream_acquirer, mock_hass, stream_config
):
    """Test that when user_cert_path is None, user_cert strategy is skipped cleanly."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_ssl_ctx = MagicMock()

    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=mock_ssl_ctx,
        ) as mock_ssl,
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
    ):
        config = await stream_acquirer._connect_stream()
        # Only strategy 2 (default cert) should be executed
        assert mock_ssl.call_count == 1
        assert config["cert"] == "ac14k_m.pem"
        assert config["verify_mode"] == ssl.CERT_NONE


async def test_successful_pairing_and_token(stream_acquirer):
    """Test a successful token acquisition flow."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    mock_reader.read.side_effect = [
        b'<Response Type="Initial" />',
        b'<Response Type="GetToken" Status="Ready"/>',
        b'<Update Type="Authenticate" Status="Success" Token="11112222-3333-4444-5555-666677778888"/>',
    ]

    mock_timeout_ctx = make_mock_timeout_cm()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            with patch(
                "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
                return_value=mock_timeout_ctx,
            ) as mock_timeout:
                config = await stream_acquirer.async_initiate_pairing()
                mock_writer.write.assert_called_with(b'<Request Type="GetToken" />\r\n')

                token = await stream_acquirer.async_wait_for_token()
                assert token == "11112222-3333-4444-5555-666677778888"
                assert config is not None
                assert mock_timeout.called
                assert mock_reader.read.call_args_list == [
                    call(4096),
                    call(4096),
                    call(4096),
                ]


async def test_wait_for_token_no_reader(stream_acquirer):
    """Test wait_for_token when reader is not established."""
    stream_acquirer._reader = None
    with pytest.raises(TokenAcquisitionError, match="Connection not established."):
        await stream_acquirer.async_wait_for_token()


async def test_stream_wait_for_token_timeout(stream_acquirer):
    """Test timeout in async_wait_for_token."""
    mock_reader = AsyncMock()
    mock_reader.read.side_effect = TimeoutError()
    stream_acquirer._reader = mock_reader

    with pytest.raises(
        TokenAcquisitionError, match="Token not received within timeout window."
    ):
        await stream_acquirer.async_wait_for_token()


async def test_wait_for_token_closed(stream_acquirer):
    """Test connection closed by device during wait."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b""
    stream_acquirer._reader = mock_reader

    with pytest.raises(TokenAcquisitionError, match="Connection closed by device."):
        await stream_acquirer.async_wait_for_token()


async def test_initiate_pairing_not_ready(stream_acquirer):
    """Test when unit does not return Ready and fallback does not match."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    stream_acquirer._reader = mock_reader
    stream_acquirer._writer = mock_writer

    mock_reader.read.return_value = b'<Response Type="GetToken" Status="Error"/>'

    with patch.object(stream_acquirer, "_connect_stream", return_value={"cert": None}):
        with pytest.raises(
            TokenAcquisitionError, match="Device did not accept pairing."
        ):
            await stream_acquirer.async_initiate_pairing()


async def test_initiate_pairing_timeout_ready(stream_acquirer):
    """Test when wait for Ready times out."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    stream_acquirer._reader = mock_reader
    stream_acquirer._writer = mock_writer

    mock_reader.read.side_effect = TimeoutError()

    with patch.object(stream_acquirer, "_connect_stream", return_value={"cert": None}):
        with pytest.raises(
            TokenAcquisitionError, match="Timeout waiting for 'Ready' response"
        ):
            await stream_acquirer.async_initiate_pairing()


async def test_stream_mode_defaults_when_config_empty(mock_hass):
    """Test stream mode behavior when auth_config is minimal (testing all default fallbacks)."""
    acq = GenericYamlTokenAcquirer(
        mock_hass,
        "192.168.1.100",
        {"mode": "stream", "request_pairing": {"port": 2878}},
        cert_path=None,
    )

    # 1. _connect_stream with empty strategies/ciphers -> raises CannotConnect cleanly without crashing on None
    with pytest.raises(CannotConnect, match="All YAML TLS strategies failed"):
        await acq._connect_stream()

    # 2. wait_for_token default timeout 45 and buffer size 4096 when error_template match triggers AuthTurnedOffError
    acq.auth_config["error_template"] = {"match": "device response"}
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"Some device response"
    acq._reader = mock_reader

    mock_timeout_ctx = make_mock_timeout_cm()
    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
        return_value=mock_timeout_ctx,
    ) as mock_timeout:
        with pytest.raises(
            AuthTurnedOffError,
            match="Authentication failed: device is turned off or busy.",
        ):
            await acq.async_wait_for_token()
        mock_timeout.assert_called_once_with(45)
        mock_reader.read.assert_called_once_with(4096)

    # 3. wait_for_token with non-matching error_template and non-matching extract_template raises TokenAcquisitionError
    acq._reader = mock_reader
    acq.auth_config["error_template"] = {"match": "NOT_PRESENT"}
    acq.auth_config["extract_template"] = {"regex": r"Token: (.*)"}
    with (
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
        pytest.raises(
            TokenAcquisitionError, match="Regex failed to extract token from stream."
        ),
    ):
        await acq.async_wait_for_token()


async def test_initiate_pairing_stream_missing_payload(mock_hass, stream_config):
    """Test initiate pairing in stream mode when request_pairing has no payload."""
    stream_config["request_pairing"].pop("payload", None)
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_reader.read.side_effect = [b'<Response Type="GetToken" Status="Ready"/>']

    with (
        patch.object(
            acq, "_connect_stream", return_value={"cert": None, "verify_mode": 0}
        ),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
    ):
        acq._reader = mock_reader
        acq._writer = mock_writer
        config = await acq.async_initiate_pairing()
        mock_writer.write.assert_called_with(b"")
        assert config == {"cert": None, "verify_mode": 0}


async def test_initiate_pairing_stream_timeout_and_custom_buffer(
    mock_hass, stream_config
):
    """Test initiate pairing in stream mode with custom buffer_size and exact 15.0 timeout."""
    stream_config["buffer_size"] = 1024
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_reader.read.return_value = b'<Response Type="GetToken" Status="Ready"/>'
    acq._reader = mock_reader
    acq._writer = mock_writer

    mock_timeout_ctx = make_mock_timeout_cm()

    with (
        patch.object(
            acq, "_connect_stream", return_value={"cert": None, "verify_mode": 0}
        ),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=mock_timeout_ctx,
        ) as mock_timeout,
    ):
        config = await acq.async_initiate_pairing()
        mock_timeout.assert_called_once_with(15.0)
        mock_reader.read.assert_called_once_with(1024)
        assert config == {"cert": None, "verify_mode": 0}


async def test_initiate_pairing_stream_match_and_fallback_extraction(
    mock_hass, stream_config
):
    """Test that match and fallback_match are extracted using exact default empty strings."""
    mock_succ_cfg = MagicMock()
    mock_succ_cfg.get.side_effect = lambda k, default: (
        'Status="Ready"' if k == "match" else ""
    )
    stream_config["request_pairing"]["success_template"] = mock_succ_cfg
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_reader.read.return_value = b'<Response Type="GetToken" Status="Ready"/>'
    acq._reader = mock_reader
    acq._writer = mock_writer

    with (
        patch.object(
            acq, "_connect_stream", return_value={"cert": None, "verify_mode": 0}
        ),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
    ):
        config = await acq.async_initiate_pairing()
        mock_succ_cfg.get.assert_has_calls(
            [call("match", ""), call("fallback_match", "")]
        )
        assert config == {"cert": None, "verify_mode": 0}


async def test_initiate_pairing_stream_explicit_utf8_decoding(mock_hass, stream_config):
    """Test initiate pairing in stream mode explicitly decodes response with utf-8."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    mock_data = MagicMock(spec=bytes)
    mock_data.__len__.return_value = 50
    mock_data.decode.return_value = '<Response Type="GetToken" Status="Ready"/>'

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_reader.read.return_value = mock_data
    acq._reader = mock_reader
    acq._writer = mock_writer

    with (
        patch.object(
            acq, "_connect_stream", return_value={"cert": None, "verify_mode": 0}
        ),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
    ):
        await acq.async_initiate_pairing()
        mock_data.decode.assert_called_once_with("utf-8", errors="ignore")


async def test_initiate_pairing_stream_no_success_template(mock_hass, stream_config):
    """Test initiate pairing when request_pairing has no success_template key."""
    stream_config["request_pairing"].pop("success_template", None)
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_reader.read.return_value = b'<Response Type="Any"/>'
    acq._reader = mock_reader
    acq._writer = mock_writer

    with (
        patch.object(
            acq, "_connect_stream", return_value={"cert": None, "verify_mode": 0}
        ),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
    ):
        config = await acq.async_initiate_pairing()
        assert config == {"cert": None, "verify_mode": 0}


async def test_initiate_pairing_stream_fallback_match_success(mock_hass, stream_config):
    """Test initiate pairing succeeds when primary match fails but fallback_match is present."""
    stream_config["request_pairing"]["success_template"] = {
        "match": "PrimaryMatchRequired",
        "fallback_match": "SecondaryAccepted",
    }
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_reader.read.return_value = (
        b'<Response Type="GetToken" SecondaryAccepted="true"/>'
    )
    acq._reader = mock_reader
    acq._writer = mock_writer

    with (
        patch.object(
            acq, "_connect_stream", return_value={"cert": None, "verify_mode": 0}
        ),
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            return_value=make_mock_timeout_cm(),
        ),
    ):
        config = await acq.async_initiate_pairing()
        assert config == {"cert": None, "verify_mode": 0}


async def test_wait_for_token_custom_timeout_and_custom_buffer(
    mock_hass, stream_config
):
    """Test wait_for_token using custom timeout_seconds and custom buffer_size in stream mode."""
    stream_config["wait_token"] = {"timeout_seconds": 99}
    stream_config["buffer_size"] = 1024
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    mock_reader = AsyncMock()
    mock_reader.read.return_value = (
        b'<Update Type="Authenticate" Status="Success" Token="custom_99_token"/>'
    )
    acq._reader = mock_reader

    mock_timeout_ctx = make_mock_timeout_cm()

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
        return_value=mock_timeout_ctx,
    ) as mock_timeout:
        token = await acq.async_wait_for_token()
        assert token == "custom_99_token"
        mock_timeout.assert_called_once_with(99)
        mock_reader.read.assert_called_once_with(1024)


async def test_wait_for_token_explicit_utf8_decoding(mock_hass, stream_config):
    """Test wait_for_token decodes stream response explicitly with utf-8."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    mock_data = MagicMock(spec=bytes)
    mock_data.__len__.return_value = 50
    mock_data.decode.return_value = (
        '<Update Type="Authenticate" Status="Success" Token="utf8_stream_tok"/>'
    )

    mock_reader = AsyncMock()
    mock_reader.read.return_value = mock_data
    acq._reader = mock_reader

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
        return_value=make_mock_timeout_cm(),
    ):
        token = await acq.async_wait_for_token()
        assert token == "utf8_stream_tok"
        mock_data.decode.assert_called_once_with("utf-8", errors="ignore")


async def test_wait_for_token_stream_extracts_from_initial_stream_data(
    mock_hass, stream_config
):
    """Kill mutants on L396-402: regex extraction from _initial_stream_data."""
    stream_config["extract_template"] = {"regex": r"DeviceToken:\s*([a-zA-Z0-9_-]+)"}
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    mock_reader = AsyncMock()
    acq._reader = mock_reader
    acq._initial_stream_data = "Banner hello DeviceToken: SECRET_TOKEN_1234 trailing"

    token = await acq.async_wait_for_token()
    assert token == "SECRET_TOKEN_1234"
    mock_reader.read.assert_not_called()


async def test_wait_for_token_stream_missing_error_template(mock_hass, stream_config):
    """Verify wait_for_token works when error_template is missing (kills {} -> None mutant)."""
    stream_config.pop("error_template", None)
    stream_config["extract_template"] = {"regex": r"Token: (\d+)"}
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"Some device response with Token: 12345"
    acq._reader = mock_reader
    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
        return_value=make_mock_timeout_cm(),
    ):
        token = await acq.async_wait_for_token()
        assert token == "12345"


async def test_connect_stream_plain_tcp_explicit_enabled_false(
    mock_hass, stream_config
):
    """Kill mutants on L193, L196, L198, L199, L206, L207, L208, L212 for plain TCP stream."""
    stream_config["tls_config"] = {"enabled": False, "strategies": []}
    stream_config["request_pairing"] = {"port": 3310}
    stream_config["buffer_size"] = 2048

    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_reader.read.return_value = b"BannerData"

    with (
        patch(
            "asyncio.open_connection", return_value=(mock_reader, mock_writer)
        ) as mock_open,
        patch(
            "custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout",
            side_effect=asyncio.timeout,
        ) as mock_timeout,
    ):
        res = await acq._connect_stream()

    assert res == {"plain_tcp": True}
    assert res["plain_tcp"] is True
    mock_open.assert_called_once_with("192.168.1.100", 3310, ssl=None)
    assert acq._reader is mock_reader
    assert acq._writer is mock_writer
    mock_reader.read.assert_called_once_with(2048)
    assert any(c.args == (15.0,) for c in mock_timeout.call_args_list)
    assert any(c.args == (1.0,) for c in mock_timeout.call_args_list)


async def test_connect_stream_plain_tcp_method_tcp(mock_hass, stream_config):
    """Kill mutant on L196: req_cfg method == 'tcp' condition."""
    stream_config["tls_config"] = {"enabled": True, "strategies": []}
    stream_config["request_pairing"] = {"method": "tcp", "port": 2878}

    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_reader.read.return_value = b""

    with patch(
        "asyncio.open_connection", return_value=(mock_reader, mock_writer)
    ) as mock_open:
        res = await acq._connect_stream()

    assert res == {"plain_tcp": True}
    mock_open.assert_called_once_with("192.168.1.100", 2878, ssl=None)


async def test_connect_stream_plain_tcp_connection_error_raises_cannot_connect(
    mock_hass, stream_config
):
    """Kill mutant on L213-217: plain TCP open_connection exception closes and raises CannotConnect."""
    stream_config["tls_config"] = {"enabled": False}
    stream_config["request_pairing"] = {"port": 2878}

    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    with patch("asyncio.open_connection", side_effect=OSError("Network unreachable")):
        with pytest.raises(CannotConnect) as exc_info:
            await acq._connect_stream()

    assert (
        "Failed to connect via plain TCP to 192.168.1.100:2878: Network unreachable"
        in str(exc_info.value)
    )
    assert acq._reader is None
    assert acq._writer is None


async def test_connect_stream_plain_tcp_missing_config_keys_use_defaults(
    mock_hass, stream_config
):
    """Test plain TCP defaults when request_pairing and buffer_size are missing.

    Remove request_pairing and buffer_size keys entirely from config.
    The code must fall back to default port 2878 and buffer size 4096.
    """
    stream_config["tls_config"] = {"enabled": False}
    # Remove request_pairing entirely → req_cfg defaults to {}
    stream_config.pop("request_pairing", None)
    # Remove buffer_size entirely → defaults to 4096
    stream_config.pop("buffer_size", None)

    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_reader.read.return_value = b""

    with patch(
        "asyncio.open_connection", return_value=(mock_reader, mock_writer)
    ) as mock_open:
        res = await acq._connect_stream()

    assert res == {"plain_tcp": True}
    # Kill L192 + L193: if req_cfg defaults to None, None.get() raises.
    # If port defaults to None, open_connection gets wrong port.
    mock_open.assert_called_once_with("192.168.1.100", 2878, ssl=None)
    # Kill L208: if buffer_size defaults to None, read(None) is wrong.
    mock_reader.read.assert_called_once_with(4096)
