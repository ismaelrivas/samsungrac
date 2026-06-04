# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the Samsung 8888 token acquirer."""
# pylint: disable=protected-access,redefined-outer-name,too-few-public-methods,line-too-long,import-outside-toplevel

import json
from unittest.mock import MagicMock, patch

import pytest

from custom_components.climate_ip.exceptions import TokenAcquisitionError
from custom_components.climate_ip.token_acquirer_8888 import (
    SamsungTokenAcquirer8888,
)


# --- Concrete Mocks to prevent AsyncMock coroutine leaks ---
class MockClientResponse:
    """Bulletproof mock for aiohttp.ClientResponse."""

    def __init__(self, status: int, text_data: str = "OK"):
        self.status = status
        self._text_data = text_data
        self.connection = MagicMock()

    async def text(self):
        """Return mock text response."""
        return self._text_data

    async def __aenter__(self):
        """Enter context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""


class MockStreamReader:
    """Concrete mock for asyncio.StreamReader."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.idx = 0

    async def read(self, _n=-1):
        """Return next chunk or empty bytes."""
        if self.idx < len(self.chunks):
            chunk = self.chunks[self.idx]
            self.idx += 1
            return chunk
        return b""


class MockStreamWriter:
    """Concrete mock for asyncio.StreamWriter."""

    def __init__(self):
        self.written_data = b""

    def write(self, data: bytes):
        """Write bytes to the internal buffer."""
        self.written_data += data

    async def drain(self):
        """Drain the write buffer."""

    def close(self):
        """Close the stream."""

    async def wait_closed(self):
        """Wait for the stream to close."""

    def get_extra_info(self, _name):
        """Return mock peer address."""
        return ("127.0.0.1", 12345)


# -----------------------------------------------------------


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.api.local_ip = "192.168.1.100"  # pylint: disable=no-member
    # Mock hass.config.path to return a joined path
    hass.config.path.side_effect = lambda *args: "/".join(args)
    return hass


@pytest.fixture
def acquirer(mock_hass):
    """Create a token acquirer instance."""
    return SamsungTokenAcquirer8888(mock_hass, "192.168.1.50", "ac14k_m.pem")



async def test_initiate_pairing_success(acquirer):
    """Test a successful pairing initiation."""
    with patch(
        "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
        return_value=True,
    ), patch("asyncio.open_connection") as mock_open_connection, patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        return_value=MagicMock()
    ):

        # Use concrete mocks defined above
        mock_reader = MockStreamReader([b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n"])
        mock_writer = MockStreamWriter()

        mock_open_connection.return_value = (mock_reader, mock_writer)

        # Execute the function
        await acquirer.async_initiate_pairing()

        # Verify that our raw socket was actually used
        mock_open_connection.assert_called_once()
        assert len(mock_writer.written_data) > 0



async def test_initiate_pairing_server_failure(acquirer):
    """Test pairing initiation when the local server fails to start."""
    with patch(
        "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
        return_value=False,
    ):
        with pytest.raises(
            TokenAcquisitionError, match="Failed to start the local listener server"
        ):
            await acquirer.async_initiate_pairing()



async def test_initiate_pairing_http_failure(acquirer):
    """Test pairing initiation when the AC rejects the request."""
    with patch(
        "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
        return_value=True,
    ), patch("asyncio.open_connection") as mock_open_connection, patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        return_value=MagicMock()
    ):

        # Use concrete mocks defined above
        mock_reader = MockStreamReader([b"HTTP/1.1 403 Forbidden\r\n\r\n"])
        mock_writer = MockStreamWriter()

        mock_open_connection.return_value = (mock_reader, mock_writer)

        with pytest.raises(TokenAcquisitionError, match="AC responded with non-200 status"):
            await acquirer.async_initiate_pairing()



async def test_initiate_pairing_connection_error(acquirer):
    """Test pairing initiation when the AC is unreachable."""
    with patch(
        "custom_components.climate_ip.token_acquirer_8888.SamsungTokenAcquirer8888._start_listener_server",
        return_value=True,
    ), patch("asyncio.open_connection", side_effect=ConnectionError("Connection refused")), patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        return_value=MagicMock()
    ):
        from custom_components.climate_ip.exceptions import CannotConnect
        with pytest.raises(CannotConnect, match="Failed to connect to AC via raw socket"):
            await acquirer.async_initiate_pairing()



async def test_wait_for_token_success(acquirer):
    """Test successfully waiting for and receiving a token."""
    acquirer._received_token = "new_secret_token"

    # Safely mock the wait method to prevent real waiting
    async def mock_wait():
        pass

    acquirer._token_received_event.wait = mock_wait

    token = await acquirer.async_wait_for_token()
    assert token == "new_secret_token"



async def test_wait_for_token_timeout(acquirer):
    """Test waiting for a token timing out."""

    async def mock_wait():
        raise TimeoutError

    acquirer._token_received_event.wait = mock_wait

    with pytest.raises(TokenAcquisitionError, match="Timed out waiting for the AC"):
        await acquirer.async_wait_for_token()



async def test_handle_client_valid_json(acquirer):
    """Test the raw TCP server handling a valid JSON payload with the token."""
    payload = json.dumps({"DeviceToken": "json_extracted_token"}).encode("utf-8")

    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    await acquirer._handle_client(mock_reader, mock_writer)

    assert acquirer._received_token == "json_extracted_token"
    assert acquirer._token_received_event.is_set()
    assert b"200 OK" in mock_writer.written_data



async def test_handle_client_regex_fallback(acquirer):
    """Test the raw TCP server extracting the token via regex from malformed headers."""
    payload = b"HTTP/1.1 200 OK\r\nDeviceToken: malformed_header_token\r\n\r\n"

    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    await acquirer._handle_client(mock_reader, mock_writer)

    assert acquirer._received_token == "malformed_header_token"
    assert acquirer._token_received_event.is_set()



async def test_handle_client_no_token(acquirer):
    """Test the raw TCP server handling a request without a token."""
    payload = json.dumps({"OtherData": "No token here"}).encode("utf-8")

    mock_reader = MockStreamReader([payload])
    mock_writer = MockStreamWriter()

    await acquirer._handle_client(mock_reader, mock_writer)

    assert acquirer._received_token is None
    assert not acquirer._token_received_event.is_set()
    assert b"400 Bad Request" in mock_writer.written_data
