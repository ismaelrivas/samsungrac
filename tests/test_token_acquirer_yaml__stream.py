# pylint: disable=protected-access,redefined-outer-name,unused-argument,not-context-manager,invalid-name,line-too-long
"""Tests for GenericYamlTokenAcquirer in stream mode (2878 pairing)."""

import ssl
from unittest.mock import AsyncMock, MagicMock, call, patch
import pytest

from custom_components.climate_ip.exceptions import (
    AuthTurnedOffError,
    CannotConnect,
    TokenAcquisitionError,
)
from custom_components.climate_ip.token_acquirer_yaml import GenericYamlTokenAcquirer
from .test_token_acquirer_yaml__common import mock_hass, stream_config


@pytest.fixture
def acquirer(mock_hass, stream_config):
    """Create a stream mode acquirer instance."""
    return GenericYamlTokenAcquirer(mock_hass, "192.168.1.100", stream_config, cert_path=None)


async def test_cert_not_found(acquirer, caplog):
    """Test that a CertNotFound error is gracefully caught and logs properly if all strategies fail."""
    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
        side_effect=FileNotFoundError("missing cert"),
    ):
        with pytest.raises(CannotConnect) as exc_info:
            await acquirer.async_initiate_pairing()
        assert "All YAML TLS strategies failed" in str(exc_info.value)


async def test_connect_cert_path_kwarg_propagation(mock_hass, stream_config):
    """Test that cert_path is correctly propagated as a kwarg."""
    acq = GenericYamlTokenAcquirer(mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem")
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
    assert config is not None


async def test_connect_fallback_success_on_second_attempt(acquirer, mock_hass, stream_config):
    """Test that if the first attempt fails, it continues to the second attempt and succeeds."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_ssl_context = MagicMock()

    acq = GenericYamlTokenAcquirer(mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem")

    call_count = 0

    async def mock_create_ssl(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FileNotFoundError("missing cert")
        return mock_ssl_context

    with patch(
        "custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context",
        side_effect=mock_create_ssl,
    ):
        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                config = await acq._connect_stream()

    assert config is not None
    assert call_count == 2
    assert config.get("cert") == "ac14k_m.pem"
    assert config.get("verify_mode") == ssl.CERT_NONE


async def test_connection_refused_fallback(acquirer):
    """Test that ConnectionRefusedError bubbles up."""
    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=MagicMock()),
        patch("asyncio.open_connection", side_effect=ConnectionRefusedError("Refused")),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(CannotConnect, match="All YAML TLS strategies failed"):
            await acquirer.async_initiate_pairing()


async def test_timeout_fallback(acquirer):
    """Test that TimeoutError during open_connection bubbles up."""
    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=MagicMock()),
        patch("asyncio.open_connection", side_effect=TimeoutError("Timeout")),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(CannotConnect, match="All YAML TLS strategies failed"):
            await acquirer.async_initiate_pairing()


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
        with patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=MagicMock()):
            with patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout", return_value=mock_timeout_ctx) as mock_timeout:
                config = await acquirer.async_initiate_pairing()
                mock_writer.write.assert_called_with(b'<Request Type="GetToken" />\r\n')

                token = await acquirer.async_wait_for_token()
                assert token == "11112222-3333-4444-5555-666677778888"
                assert mock_reader.read.call_args_list == [
                    call(4096),
                    call(4096),
                    call(4096),
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
    mock_reader.read.return_value = b""
    acquirer._reader = mock_reader

    with pytest.raises(TokenAcquisitionError, match="Connection closed by device."):
        await acquirer.async_wait_for_token()


async def test_auth_turned_off_error(acquirer):
    """Test ErrorCode 301 parsing."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'<Update Type="Authenticate" Status="Fail" ErrorCode="301" />'
    acquirer._reader = mock_reader

    with pytest.raises(AuthTurnedOffError, match="device is turned off"):
        await acquirer.async_wait_for_token()


async def test_generic_auth_error(acquirer):
    """Test extraction failure generic error."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'<Update Type="Authenticate" Status="Fail" ErrorCode="404" />'
    acquirer._reader = mock_reader

    with pytest.raises(TokenAcquisitionError, match="Regex failed to extract token"):
        await acquirer.async_wait_for_token()


async def test_initiate_pairing_not_ready(acquirer):
    """Test when unit does not return Ready."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    acquirer._reader = mock_reader
    acquirer._writer = mock_writer

    mock_reader.read.return_value = b'<Response Type="GetToken" Status="Error"/>'

    with patch.object(acquirer, "_connect_stream", return_value={"cert": None}):
        with pytest.raises(TokenAcquisitionError, match="Device did not accept pairing."):
            await acquirer.async_initiate_pairing()


async def test_initiate_pairing_invalidate_account(acquirer):
    """Test that a response containing 'InvalidateAccount' is treated as valid."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    acquirer._reader = mock_reader
    acquirer._writer = mock_writer

    mock_reader.read.return_value = b'<Response Type="GetToken" InvalidateAccount="true"/>'

    with patch.object(acquirer, "_connect_stream", return_value={"cert": None, "verify_mode": 0}):
        config = await acquirer.async_initiate_pairing()
        assert config is not None
        assert config.get("verify_mode") == 0


async def test_initiate_pairing_timeout_ready(acquirer):
    """Test when wait for Ready times out."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    acquirer._reader = mock_reader
    acquirer._writer = mock_writer

    mock_reader.read.side_effect = TimeoutError()

    with patch.object(acquirer, "_connect_stream", return_value={"cert": None}):
        with pytest.raises(TokenAcquisitionError, match="Timeout waiting for 'Ready'"):
            await acquirer.async_initiate_pairing()


async def test_handshake_timeout_non_fatal(acquirer):
    """Test that a timeout during the initial handshake is non-fatal."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    mock_reader.read.side_effect = TimeoutError()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=MagicMock()):
            # _connect_stream should not raise! It should ignore timeout.
            res = await acquirer._connect_stream()
            assert res is not None
