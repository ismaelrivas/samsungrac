# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for SamsungTokenAcquirer (2878 pairing)."""
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import ssl
import pytest

from custom_components.climate_ip.token_acquirer import SamsungTokenAcquirer
from custom_components.climate_ip.exceptions import (
    CannotConnect,
    CertNotFound,
    TokenAcquisitionError,
    AuthTurnedOffError,
)

@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock()

@pytest.fixture
def acquirer(mock_hass):
    """Create a SamsungTokenAcquirer instance."""
    return SamsungTokenAcquirer(mock_hass, "192.168.1.100", cert_path=None)

async def test_init_path_resolution(mock_hass):
    """Test the certificate path resolution logic in __init__."""
    # Absolute path
    acq1 = SamsungTokenAcquirer(mock_hass, "1.1.1.1", cert_path="/absolute/path/cert.pem")
    assert acq1._resolved_cert_path == "/absolute/path/cert.pem"
    
    # Relative path without directory
    acq2 = SamsungTokenAcquirer(mock_hass, "1.1.1.1", cert_path="cert.pem")
    assert "cert.pem" in acq2._resolved_cert_path
    assert acq2._resolved_cert_path.endswith("cert.pem")
    assert "/" in acq2._resolved_cert_path  # Should have been joined with __file__

async def test_cert_not_found(acquirer, caplog):
    """Test that a CertNotFound error is gracefully caught and logs properly if all strategies fail."""
    with patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        side_effect=FileNotFoundError("missing cert"),
    ):
        with pytest.raises(CannotConnect) as exc_info:
            await acquirer.async_initiate_pairing()
        
        # Verify the exception message doesn't mask the error
        assert "All connection attempts failed" in str(exc_info.value)
        # Verify that the logs accurately capture the CertNotFound error for all attempts
        assert "CertNotFound" in caplog.text

async def test_connection_refused_fallback(acquirer):
    """Test that ConnectionRefusedError bubbles up to CannotConnect."""
    with patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        return_value=MagicMock(),
    ), patch("asyncio.open_connection", side_effect=ConnectionRefusedError("Refused")), patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(CannotConnect) as exc_info:
            await acquirer.async_initiate_pairing()
        assert "ConnectionRefusedError" in str(exc_info.value) or "Refused" in str(exc_info.value)

async def test_timeout_fallback(acquirer):
    """Test that TimeoutError during open_connection bubbles up."""
    with patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        return_value=MagicMock(),
    ), patch("asyncio.open_connection", side_effect=TimeoutError("Timeout")), patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(CannotConnect) as exc_info:
            await acquirer.async_initiate_pairing()
        assert "Timeout" in str(exc_info.value)

async def test_successful_pairing_and_token(acquirer):
    """Test a successful token acquisition flow."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    mock_reader.read.side_effect = [
        b'<Response Type="Initial" />',
        b'<Response Type="GetToken" Status="Ready"/>',
        b'<Update Type="Authenticate" Status="Success" Token="11112222-3333-4444-5555-666677778888"/>',
    ]

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            config = await acquirer.async_initiate_pairing()
            assert config is not None
            mock_writer.write.assert_called_with(b'<Request Type="GetToken" />\r\n')
            
            token = await acquirer.async_wait_for_token()
            assert token == "11112222-3333-4444-5555-666677778888"

async def test_wait_for_token_timeout(acquirer):
    """Test timeout in async_wait_for_token."""
    mock_reader = AsyncMock()
    mock_reader.read.side_effect = TimeoutError()
    acquirer._reader = mock_reader
    
    with pytest.raises(TokenAcquisitionError, match="Token not received"):
        await acquirer.async_wait_for_token()

async def test_wait_for_token_closed(acquirer):
    """Test connection closed by device during wait."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b""  # Empty byte string means closed
    acquirer._reader = mock_reader
    
    with pytest.raises(TokenAcquisitionError, match="Connection closed by device"):
        await acquirer.async_wait_for_token()

async def test_auth_turned_off_error(acquirer):
    """Test ErrorCode 301 parsing."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'<Update Type="Authenticate" Status="Fail" ErrorCode="301" />'
    acquirer._reader = mock_reader
    
    with pytest.raises(AuthTurnedOffError):
        await acquirer.async_wait_for_token()

async def test_generic_auth_error(acquirer):
    """Test other ErrorCode parsing."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'<Update Type="Authenticate" Status="Fail" ErrorCode="404" />'
    acquirer._reader = mock_reader
    
    with pytest.raises(TokenAcquisitionError, match="ErrorCode 404"):
        await acquirer.async_wait_for_token()

async def test_unexpected_payload(acquirer):
    """Test receiving random payload instead of token."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'<Update Type="Status" />'
    acquirer._reader = mock_reader
    
    with pytest.raises(TokenAcquisitionError, match="unexpected data"):
        await acquirer.async_wait_for_token()

async def test_initiate_pairing_no_reader(acquirer):
    """Test when reader is missing after connect."""
    acquirer._writer = MagicMock()
    acquirer._writer.drain = AsyncMock()
    with patch.object(acquirer, "_connect", return_value={"cert": None}):
        with pytest.raises(TokenAcquisitionError, match="reader not available"):
            await acquirer.async_initiate_pairing()

async def test_initiate_pairing_no_writer(acquirer):
    """Test when writer is missing after connect."""
    mock_reader = AsyncMock()
    acquirer._reader = mock_reader
    acquirer._writer = None
    with patch.object(acquirer, "_connect", return_value={"cert": None}):
        with pytest.raises(TokenAcquisitionError, match="writer not available"):
            await acquirer.async_initiate_pairing()

async def test_wait_for_token_no_reader(acquirer):
    """Test when wait_for_token is called before initiate_pairing."""
    with pytest.raises(TokenAcquisitionError, match="Connection not established"):
        await acquirer.async_wait_for_token()

async def test_initiate_pairing_not_ready(acquirer):
    """Test when unit does not return Ready."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    
    acquirer._reader = mock_reader
    acquirer._writer = mock_writer
    
    mock_reader.read.return_value = b'<Response Type="GetToken" Status="Error"/>'
    
    with patch.object(acquirer, "_connect", return_value={"cert": None}):
        with pytest.raises(TokenAcquisitionError, match="Did not receive 'Ready'"):
            await acquirer.async_initiate_pairing()

async def test_initiate_pairing_timeout_ready(acquirer):
    """Test when wait for Ready times out."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    
    acquirer._reader = mock_reader
    acquirer._writer = mock_writer
    
    mock_reader.read.side_effect = TimeoutError()
    
    with patch.object(acquirer, "_connect", return_value={"cert": None}):
        with pytest.raises(TokenAcquisitionError, match="Timeout waiting for 'Ready'"):
            await acquirer.async_initiate_pairing()

async def test_handshake_timeout_non_fatal():
    """Test that a timeout during the initial handshake is non-fatal."""
    mock_hass = MagicMock()
    acq = SamsungTokenAcquirer(mock_hass, "1.1.1.1", cert_path=None)
    
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    
    # Handshake times out!
    mock_reader.read.side_effect = TimeoutError()
    
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("custom_components.climate_ip.helpers.async_create_samsung_ssl_context", return_value=MagicMock()):
            # _connect should not raise! It should just warn and continue.
            res = await acq._connect()
            assert res is not None

async def test_close_swallows_errors():
    """Test that async_close handles connection reset errors."""
    mock_hass = MagicMock()
    acq = SamsungTokenAcquirer(mock_hass, "1.1.1.1", cert_path=None)
    mock_writer = MagicMock()
    mock_writer.wait_closed = AsyncMock(side_effect=ConnectionResetError())
    acq._writer = mock_writer
    
    # Should not raise
    await acq.async_close()

async def test_connect_user_cert(acquirer):
    """Test that _connect tries user cert and returns correct config."""
    acquirer._resolved_cert_path = "/tmp/user_cert.pem"
    
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    
    # Return successfully on the first strategy
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_open:
        with patch("custom_components.climate_ip.helpers.async_create_samsung_ssl_context", return_value=MagicMock()) as mock_ssl:
            config = await acquirer._connect()
            
            # Assert correct arguments were passed to open_connection
            mock_open.assert_called_with("192.168.1.100", 2878, ssl=mock_ssl.return_value)
            
            assert config is not None
            assert config.get("cert") == acquirer._user_cert_path
            assert config.get("verify_mode") == ssl.CERT_REQUIRED

async def test_connect_default_cert_fallback(acquirer):
    """Test that _connect falls back to default cert if first strategies fail."""
    # We simulate FileNotFoundError for the first strategy, and success for the fallback.
    def mock_create_ssl(*args, **kwargs):
        if kwargs.get("cert_path") is None:
            raise FileNotFoundError("Mock no cert")
        return MagicMock()
        
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_open:
        with patch("custom_components.climate_ip.helpers.async_create_samsung_ssl_context", side_effect=mock_create_ssl):
            config = await acquirer._connect()
            
            # Should have called open_connection successfully on the second attempt
            assert mock_open.call_count == 1
            # IP and Port must remain intact in fallback attempts
            mock_open.assert_called_with("192.168.1.100", 2878, ssl=mock_open.call_args.kwargs["ssl"])
            
            assert config is not None
            assert config.get("cert") == "ac14k_m.pem"
            assert config.get("verify_mode") == ssl.CERT_NONE

async def test_connect_cipher_fallback(acquirer):
    """Test that _connect tries fallback ciphers if the first one fails."""
    # We simulate SSLError for the first attempt, and success for the second.
    call_count = 0
    def mock_create_ssl(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ssl.SSLError("Cipher mismatch")
        return MagicMock()
        
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_open:
        with patch("custom_components.climate_ip.helpers.async_create_samsung_ssl_context", side_effect=mock_create_ssl):
            config = await acquirer._connect()
            assert config is not None
            # Assert correct arguments were passed to open_connection
            mock_open.assert_called_with("192.168.1.100", 2878, ssl=mock_open.call_args.kwargs["ssl"])
            assert call_count == 2

async def test_connect_timeout_handshake(acquirer):
    """Test that _connect handles a TimeoutError during the initial handshake."""
    # Reader raises TimeoutError on read()
    mock_reader = AsyncMock()
    mock_reader.read.side_effect = TimeoutError()
    mock_writer = MagicMock()
    
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("custom_components.climate_ip.helpers.async_create_samsung_ssl_context", return_value=MagicMock()):
            # The code should catch the TimeoutError, log a warning, and continue to return the config
            config = await acquirer._connect()
            assert config is not None
            assert config.get("cert") is None
            assert config.get("verify_mode") == ssl.CERT_NONE
            # Assert read was called
            mock_reader.read.assert_called_once()
