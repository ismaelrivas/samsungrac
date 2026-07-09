# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for SamsungTokenAcquirer (2878 pairing)."""
# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name,line-too-long
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.climate_ip.token_acquirer import SamsungTokenAcquirer


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock()


@pytest.fixture
def acquirer(mock_hass):
    """Create a SamsungTokenAcquirer instance."""
    return SamsungTokenAcquirer(mock_hass, "192.168.1.100", cert_path=None)



async def test_cert_not_found(acquirer):
    """Test that a CertNotFound error is gracefully caught and raises properly if all strategies fail."""
    with patch(
        "custom_components.climate_ip.helpers.async_create_samsung_ssl_context",
        side_effect=FileNotFoundError("missing cert"),
    ):
        with pytest.raises(Exception):
            await acquirer.async_initiate_pairing()



async def test_successful_pairing_and_token(acquirer):
    """Test a successful token acquisition flow."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    # Mock sequence:
    # 1. Initial Handshake inside _connect
    # 2. Response to GetToken inside async_initiate_pairing
    # 3. The token payload broadcast inside async_wait_for_token
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
            # Phase 1
            config = await acquirer.async_initiate_pairing()
            assert config is not None

            # Verify writer was called with GetToken
            mock_writer.write.assert_called_with(b'<Request Type="GetToken" />\r\n')

            # Phase 2
            token = await acquirer.async_wait_for_token()
            assert token == "11112222-3333-4444-5555-666677778888"
