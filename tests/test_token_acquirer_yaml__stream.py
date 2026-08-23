# ruff: noqa: F811, F401, F841
# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,missing-function-docstring,too-few-public-methods
"""Tests for GenericYamlTokenAcquirer in stream mode (2878 pairing)."""

import asyncio
import ssl
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.climate_ip.exceptions import (
    AuthTurnedOffError,
    CannotConnect,
    TokenAcquisitionError,
)
from custom_components.climate_ip.token_acquirer_yaml import GenericYamlTokenAcquirer

from .test_token_acquirer_yaml__common import mock_hass, stream_config


def make_mock_timeout_cm():
    """Construct canonical AsyncMock context manager for asyncio.timeout."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock()
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


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
    assert first_call_kwargs["ciphers"] == "HIGH:!DH:!aNULL:@SECLEVEL=0"
    assert first_call_kwargs["verify_mode"] == ssl.CERT_REQUIRED
    assert config == {"cert": "/my/cert.pem", "verify_mode": ssl.CERT_REQUIRED}


async def test_connect_stream_config_extraction_and_sleep_delay(mock_hass, stream_config):
    """Test complete extraction of TLS strategies, ciphers, timeouts, and sleep delay."""
    acq = GenericYamlTokenAcquirer(mock_hass, "192.168.1.100", stream_config, cert_path="/my/cert.pem")
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
        patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", side_effect=mock_create_ssl),
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_open,
        patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout", return_value=mock_timeout_ctx) as mock_timeout,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        config = await acq._connect_stream()

        # Check sleep was called with exactly reconnect_delay (0.01)
        mock_sleep.assert_called_once_with(0.01)
        # Check open_connection called with host and port from config
        mock_open.assert_called_once_with("192.168.1.100", 2878, ssl=mock_open.call_args.kwargs["ssl"])
        # Check timeouts: open connection (15.0) and handshake (5.0)
        assert mock_timeout.call_args_list == [call(15.0), call(5.0)]
        assert mock_reader.read.call_args_list == [call(4096)]
        assert config is not None


async def test_connect_stream_skips_user_cert_when_missing(acquirer, mock_hass, stream_config):
    """Test that when user_cert_path is None, user_cert strategy is skipped cleanly."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_ssl_ctx = MagicMock()

    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=mock_ssl_ctx) as mock_ssl,
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
    ):
        config = await acquirer._connect_stream()
        # Only strategy 2 (default cert) should be executed
        assert mock_ssl.call_count == 1
        assert config["cert"] == "ac14k_m.pem"
        assert config["verify_mode"] == ssl.CERT_NONE


async def test_connect_stream_default_cert_normalization(mock_hass, stream_config):
    """Test that when cert_path matches default_cert name, saved_cert is the default cert name."""
    # Modify default cert to be custom name and ensure Path(cert_path).name matching works
    stream_config["tls_config"]["default_cert"] = "custom_cert.pem"
    stream_config["tls_config"]["strategies"] = [{"cert": "/etc/ssl/custom_cert.pem", "verify_mode": "CERT_NONE"}]
    acq = GenericYamlTokenAcquirer(mock_hass, "192.168.1.100", stream_config, cert_path=None)

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with (
        patch("custom_components.climate_ip.token_acquirer_yaml.async_create_samsung_ssl_context", return_value=MagicMock()),
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
    ):
        config = await acq._connect_stream()
        assert config["cert"] == "custom_cert.pem"


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

    mock_timeout_ctx = make_mock_timeout_cm()

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


async def test_initiate_pairing_raw_payload_bytes(acquirer, mock_hass, stream_config):
    """Test initiate pairing with byte payload instead of string."""
    stream_config["request_pairing"]["payload"] = b'<Request Type="GetToken" />\r\n'
    acq = GenericYamlTokenAcquirer(mock_hass, "192.168.1.100", stream_config, cert_path=None)

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_reader.read.side_effect = [b'<Response Type="GetToken" Status="Ready"/>']

    with (
        patch.object(acq, "_connect_stream", return_value={"cert": None, "verify_mode": 0}),
        patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout", return_value=make_mock_timeout_cm()),
    ):
        acq._reader = mock_reader
        acq._writer = mock_writer
        config = await acq.async_initiate_pairing()
        mock_writer.write.assert_called_with(b'<Request Type="GetToken" />\r\n')
        assert config == {"cert": None, "verify_mode": 0}


async def test_wait_for_token_no_reader(acquirer):
    """Test wait_for_token when reader is not established."""
    acquirer._reader = None
    with pytest.raises(TokenAcquisitionError, match="Connection not established."):
        await acquirer.async_wait_for_token()


async def test_wait_for_token_timeout(acquirer):
    """Test timeout in async_wait_for_token."""
    mock_reader = AsyncMock()
    mock_reader.read.side_effect = TimeoutError()
    acquirer._reader = mock_reader

    with pytest.raises(TokenAcquisitionError, match="Token not received within timeout window."):
        await acquirer.async_wait_for_token()


async def test_wait_for_token_timeout_value(acquirer):
    """Test that wait_for_token uses exact timeout_seconds value."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'<Update Type="Authenticate" Status="Success" Token="secret_token_123"/>'
    acquirer._reader = mock_reader

    mock_timeout_ctx = make_mock_timeout_cm()

    with patch("custom_components.climate_ip.token_acquirer_yaml.asyncio.timeout", return_value=mock_timeout_ctx) as mock_timeout:
        token = await acquirer.async_wait_for_token()
        assert token == "secret_token_123"
        mock_timeout.assert_called_once_with(45)


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

    with pytest.raises(AuthTurnedOffError, match="Authentication failed: device is turned off or busy."):
        await acquirer.async_wait_for_token()


async def test_generic_auth_error(acquirer):
    """Test extraction failure generic error."""
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b'<Update Type="Authenticate" Status="Fail" ErrorCode="404" />'
    acquirer._reader = mock_reader

    with pytest.raises(TokenAcquisitionError, match="Regex failed to extract token from stream."):
        await acquirer.async_wait_for_token()


async def test_initiate_pairing_not_ready(acquirer):
    """Test when unit does not return Ready and fallback does not match."""
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
        with pytest.raises(TokenAcquisitionError, match="Timeout waiting for 'Ready' response"):
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
