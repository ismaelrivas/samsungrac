# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for SamsungTokenAcquirer (2878 pairing)."""

from unittest.mock import AsyncMock, MagicMock, patch, call
import ssl
import pytest

from custom_components.climate_ip.token_acquirer import SamsungTokenAcquirer
from custom_components.climate_ip.exceptions import (
    CannotConnect,
    TokenAcquisitionError,
    AuthTurnedOffError,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock()


@pytest.fixture
def acquirer(mock_hass):
    """Create a SamsungTokenAcquirer instance and verify initial state."""
    acq = SamsungTokenAcquirer(mock_hass, "192.168.1.100", cert_path=None)
    # These assertions inside the fixture ensure that ANY test using this
    # fixture will fail if mutmut mutates __init__ assignments.
    # This forces TIA to kill __init__ mutants regardless of which test is selected.
    assert acq._hass is mock_hass
    assert acq._ip_address == "192.168.1.100"
    return acq


def test_initialization(mock_hass):
    """Test that the acquirer initializes state variables correctly."""
    acq_no_cert = SamsungTokenAcquirer(mock_hass, "192.168.1.100", cert_path=None)
    assert acq_no_cert._hass is mock_hass
    assert acq_no_cert._hass is not None
    assert acq_no_cert._ip_address == "192.168.1.100"
    assert len(acq_no_cert._ip_address) > 0
    assert acq_no_cert._user_cert_path is None
    assert acq_no_cert._resolved_cert_path is None
    assert acq_no_cert._resolved_cert_path != ""
    assert acq_no_cert._reader is None
    assert acq_no_cert._writer is None

    acq_cert = SamsungTokenAcquirer(
        mock_hass, "192.168.1.100", cert_path="/path/to/my_cert.pem"
    )
    assert acq_cert._user_cert_path == "/path/to/my_cert.pem"
    assert acq_cert._user_cert_path is not None
    assert acq_cert._resolved_cert_path == "/path/to/my_cert.pem"
    assert acq_cert._resolved_cert_path != ""


async def test_init_state_propagates_to_connect(mock_hass):
    """Test that __init__ state variables are correctly used by _connect.

    Forces mutmut's coverage engine to map __init__ lines to this test,
    killing the None Fallback on self._hass and Empty String on self._ip_address.
    """
    acquirer = SamsungTokenAcquirer(mock_hass, "192.168.1.100", cert_path=None)
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with patch(
        "asyncio.open_connection", return_value=(mock_reader, mock_writer)
    ) as mock_open:
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            config = await acquirer._connect()

    # If self._ip_address was mutated to "", this assertion fails
    mock_open.assert_called_with(
        "192.168.1.100", 2878, ssl=mock_open.call_args.kwargs["ssl"]
    )
    assert config is not None
    # Verify the hass object was preserved (used downstream)
    assert acquirer._hass is mock_hass


async def test_init_path_resolution(mock_hass):
    """Test the certificate path resolution logic in __init__."""
    # Absolute path
    acq1 = SamsungTokenAcquirer(
        mock_hass, "1.1.1.1", cert_path="/absolute/path/cert.pem"
    )
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
        # Verify the exception message and cause
        assert "All connection attempts failed" in str(exc_info.value)
        # Verify that the logs accurately capture the CertNotFound error for all attempts
        assert "CertNotFound" in caplog.text
        # Verify the __cause__ chain: CannotConnect <- last_error
        # The CertNotFound branch does `continue`, so the last_error won't be set
        # from CertNotFound. But if ALL strategies use cert, the final error will trace back.


async def test_connect_cert_path_kwarg_propagation(mock_hass):
    """Test that cert_path is correctly propagated as a kwarg to async_create_samsung_ssl_context.

    This kills the None Fallback mutant on L137 (cert_path=cert_path -> cert_path=None).
    """
    acquirer = SamsungTokenAcquirer(
        mock_hass, "192.168.1.100", cert_path="/my/cert.pem"
    )
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ) as mock_ssl:
            config = await acquirer._connect()

    # The FIRST call should use the user cert path (not None)
    first_call_kwargs = mock_ssl.call_args_list[0].kwargs
    assert first_call_kwargs["cert_path"] == "/my/cert.pem", (
        f"cert_path was {first_call_kwargs['cert_path']!r}, expected '/my/cert.pem'. "
        "Mutmut may have mutated cert_path=cert_path to cert_path=None."
    )
    assert config is not None


async def test_connect_iterates_all_attempts(mock_hass):
    """Test that _connect iterates through all_attempts, not a None.

    This kills the None Fallback mutant on L125 (for attempt in all_attempts -> None).
    If the list is mutated to None, a TypeError will be raised.
    """
    acquirer = SamsungTokenAcquirer(mock_hass, "192.168.1.100", cert_path=None)
    call_count = 0

    def mock_create_ssl(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return MagicMock()

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            side_effect=mock_create_ssl,
        ):
            config = await acquirer._connect()

    # If all_attempts was mutated to None, we'd never reach here
    assert config is not None
    # Verify the SSL context factory was actually called (iteration happened)
    assert call_count >= 1


async def test_connect_fallback_success_on_second_attempt(acquirer):
    """Test that if the first attempt fails (e.g. CertNotFound), it continues to the second attempt and succeeds."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_ssl_context = MagicMock()

    # Create a side_effect function that fails on the first call but succeeds on the second
    call_count = 0

    async def mock_create_ssl(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FileNotFoundError("missing cert")
        return mock_ssl_context

    with patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        side_effect=mock_create_ssl,
    ):
        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                config = await acquirer._connect()

    # Verify that it succeeded (config is not None)
    assert config is not None
    # Verify that it took exactly 2 attempts
    assert call_count == 2
    # Verify the fallback recorded the failure of the first attempt correctly
    assert config.get("cert") is None


async def test_connect_broad_exception(acquirer):
    """Test that a generic unexpected exception in _connect is caught by the broad except block.

    This kills the 2 Untested (No Coverage) mutants on lines 207-209.
    """
    call_count = 0

    def mock_create_ssl(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Unexpected explosion")

    with (
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            side_effect=mock_create_ssl,
        ),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(CannotConnect) as exc_info:
            await acquirer.async_initiate_pairing()
        # Verify the broad except was hit and the error propagated
        assert "All connection attempts failed" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert "Unexpected explosion" in str(exc_info.value.__cause__)
        # Verify it tried all strategies (no short-circuit)
        assert call_count > 1


async def test_connection_refused_fallback(acquirer):
    """Test that ConnectionRefusedError bubbles up to CannotConnect."""
    with (
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.open_connection", side_effect=ConnectionRefusedError("Refused")),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(CannotConnect) as exc_info:
            await acquirer.async_initiate_pairing()

        assert "All connection attempts failed" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, ssl.SSLError) or "Refused" in str(
            exc_info.value
        )


async def test_timeout_fallback(acquirer):
    """Test that TimeoutError during open_connection bubbles up."""
    with (
        patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ),
        patch("asyncio.open_connection", side_effect=TimeoutError("Timeout")),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(CannotConnect) as exc_info:
            await acquirer.async_initiate_pairing()
        assert "Timeout" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TimeoutError)


async def test_successful_pairing_and_token(acquirer):
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

    mock_timeout_ctx = MagicMock()
    mock_timeout_ctx.__aenter__ = AsyncMock()
    mock_timeout_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            with patch(
                "custom_components.climate_ip.token_acquirer.asyncio.timeout",
                return_value=mock_timeout_ctx,
            ) as mock_timeout:
                config = await acquirer.async_initiate_pairing()
                assert config == {"cert": None, "verify_mode": ssl.CERT_NONE}
                mock_writer.write.assert_called_with(b'<Request Type="GetToken" />\r\n')

                token = await acquirer.async_wait_for_token()
                assert token == "11112222-3333-4444-5555-666677778888"
                assert mock_reader.read.call_args_list == [
                    call(4096),
                    call(4096),
                    call(4096),
                ]
                assert mock_timeout.call_args_list == [
                    call(15.0),
                    call(15.0),
                    call(15.0),
                    call(45.0),
                ]


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

    with pytest.raises(TokenAcquisitionError) as exc_info:
        await acquirer.async_wait_for_token()
    assert str(exc_info.value) == "Connection closed by device."


async def test_auth_turned_off_error(acquirer):
    """Test ErrorCode 301 parsing."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = (
        b'<Update Type="Authenticate" Status="Fail" ErrorCode="301" />'
    )
    acquirer._reader = mock_reader

    with pytest.raises(AuthTurnedOffError) as exc_info:
        await acquirer.async_wait_for_token()
    assert (
        str(exc_info.value)
        == "Authentication failed: The device was likely turned off instead of on (ErrorCode 301)."
    )


async def test_generic_auth_error(acquirer):
    """Test other ErrorCode parsing."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = (
        b'<Update Type="Authenticate" Status="Fail" ErrorCode="404" />'
    )
    acquirer._reader = mock_reader

    with pytest.raises(TokenAcquisitionError) as exc_info:
        await acquirer.async_wait_for_token()
    assert str(exc_info.value) == "Authentication failed with ErrorCode 404"


async def test_unexpected_payload(acquirer):
    """Test receiving random payload instead of token."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'<Update Type="Status" />'
    acquirer._reader = mock_reader

    with pytest.raises(TokenAcquisitionError) as exc_info:
        await acquirer.async_wait_for_token()
    assert str(exc_info.value) == "Received unexpected data instead of a token"


async def test_initiate_pairing_no_reader(acquirer):
    """Test when reader is missing after connect.

    Uses match= to kill String XX Variation mutants on the error message.
    """
    acquirer._writer = AsyncMock()
    acquirer._writer.drain = AsyncMock()
    with patch.object(acquirer, "_connect", return_value={"cert": None}):
        with pytest.raises(
            TokenAcquisitionError, match="reader not available"
        ) as exc_info:
            await acquirer.async_initiate_pairing()
        # Exact string match kills both None Fallback and String mutations
        assert str(exc_info.value) == "Cannot get token, reader not available."


async def test_initiate_pairing_no_writer(acquirer):
    """Test when writer is missing after connect."""
    mock_reader = AsyncMock()
    acquirer._reader = mock_reader
    acquirer._writer = None
    with patch.object(acquirer, "_connect", return_value={"cert": None}):
        with pytest.raises(TokenAcquisitionError) as exc_info:
            await acquirer.async_initiate_pairing()
        assert str(exc_info.value) == "Connection failed, writer not available."


async def test_wait_for_token_no_reader(acquirer):
    """Test when wait_for_token is called before initiate_pairing."""
    with pytest.raises(TokenAcquisitionError, match="Connection not established"):
        await acquirer.async_wait_for_token()


async def test_initiate_pairing_not_ready(acquirer):
    """Test when unit does not return Ready."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()

    acquirer._reader = mock_reader
    acquirer._writer = mock_writer

    mock_reader.read.return_value = b'<Response Type="GetToken" Status="Error"/>'

    with patch.object(acquirer, "_connect", return_value={"cert": None}):
        with pytest.raises(TokenAcquisitionError, match="Did not receive 'Ready'"):
            await acquirer.async_initiate_pairing()


async def test_initiate_pairing_invalidate_account(acquirer):
    """Test that a response containing 'InvalidateAccount' is treated as valid.

    This kills the String XX Variation and String Case Variation mutants
    on the 'InvalidateAccount' check (line 253).
    """
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()

    acquirer._reader = mock_reader
    acquirer._writer = mock_writer

    # Return a response containing InvalidateAccount instead of Ready
    mock_reader.read.return_value = (
        b'<Response Type="GetToken" InvalidateAccount="true"/>'
    )

    with patch.object(
        acquirer, "_connect", return_value={"cert": None, "verify_mode": 0}
    ):
        config = await acquirer.async_initiate_pairing()
        mock_reader.read.assert_called_once_with(4096)
        assert config is not None
        assert config.get("verify_mode") == 0


async def test_initiate_pairing_timeout_ready(acquirer):
    """Test when wait for Ready times out."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
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
    mock_writer = AsyncMock()

    # Handshake times out!
    mock_reader.read.side_effect = TimeoutError()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            # _connect should not raise! It should just warn and continue.
            res = await acq._connect()
            assert res is not None


async def test_close_swallows_errors():
    """Test that async_close handles connection reset errors."""
    mock_hass = MagicMock()
    acq = SamsungTokenAcquirer(mock_hass, "1.1.1.1", cert_path=None)
    mock_writer = AsyncMock()
    mock_writer.wait_closed = AsyncMock(side_effect=ConnectionResetError())
    acq._writer = mock_writer

    # Should not raise
    await acq.async_close()


async def test_connect_user_cert(acquirer):
    """Test that _connect tries user cert and returns correct config."""
    acquirer._user_cert_path = "/tmp/user_cert.pem"
    acquirer._resolved_cert_path = "/tmp/user_cert.pem"

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    # Return successfully on the first strategy
    with patch(
        "asyncio.open_connection", return_value=(mock_reader, mock_writer)
    ) as mock_open:
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ) as mock_ssl:
            config = await acquirer._connect()

            # Assert correct arguments were passed to open_connection and ssl context
            mock_open.assert_called_with(
                "192.168.1.100", 2878, ssl=mock_ssl.return_value
            )
            # Verify cert_path kwarg was NOT mutated to None
            first_call_kwargs = mock_ssl.call_args_list[0].kwargs
            assert first_call_kwargs["cert_path"] == "/tmp/user_cert.pem"
            assert first_call_kwargs["ciphers"] == "HIGH:!DH:!aNULL:@SECLEVEL=0"
            assert first_call_kwargs["verify_mode"] == ssl.CERT_REQUIRED

            assert config == {
                "cert": "/tmp/user_cert.pem",
                "verify_mode": ssl.CERT_REQUIRED,
            }
            assert config["cert"] is not None


async def test_connect_default_cert_fallback(acquirer):
    """Test that _connect falls back to default cert if first strategies fail."""

    # We simulate FileNotFoundError for the first strategy, and success for the fallback.
    def mock_create_ssl(*args, **kwargs):
        if kwargs.get("cert_path") is None:
            raise FileNotFoundError("Mock no cert")
        return MagicMock()

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with patch(
        "asyncio.open_connection", return_value=(mock_reader, mock_writer)
    ) as mock_open:
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            side_effect=mock_create_ssl,
        ):
            config = await acquirer._connect()

            # Should have called open_connection successfully on the second attempt
            assert mock_open.call_count == 1
            # IP and Port must remain intact in fallback attempts
            mock_open.assert_called_with(
                "192.168.1.100", 2878, ssl=mock_open.call_args.kwargs["ssl"]
            )

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
    mock_writer = AsyncMock()

    with patch(
        "asyncio.open_connection", return_value=(mock_reader, mock_writer)
    ) as mock_open:
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            side_effect=mock_create_ssl,
        ):
            config = await acquirer._connect()
            assert config is not None
            # Assert correct arguments were passed to open_connection
            mock_open.assert_called_with(
                "192.168.1.100", 2878, ssl=mock_open.call_args.kwargs["ssl"]
            )
            assert call_count == 2


async def test_connect_timeout_handshake(acquirer):
    """Test that _connect handles a TimeoutError during the initial handshake."""
    # Reader raises TimeoutError on read()
    mock_reader = AsyncMock()
    mock_reader.read.side_effect = TimeoutError()
    mock_writer = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch(
            "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
            return_value=MagicMock(),
        ):
            # The code should catch the TimeoutError, log a warning, and continue to return the config
            config = await acquirer._connect()
            assert config is not None
            assert config.get("cert") is None
            assert config.get("verify_mode") == ssl.CERT_NONE
            # Assert read was called
            mock_reader.read.assert_called_once()
