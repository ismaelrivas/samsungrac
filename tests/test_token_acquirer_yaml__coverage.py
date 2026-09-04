# ruff: noqa: F811, F401, F841
# pylint: disable=protected-access,redefined-outer-name,unused-import
"""Coverage tests for GenericYamlTokenAcquirer."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.climate_ip.exceptions import TokenAcquisitionError
from custom_components.climate_ip.token_acquirer_yaml import GenericYamlTokenAcquirer

from .test_token_acquirer_yaml__common import listener_config, mock_hass, stream_config


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
        # Do not set _reader or _writer, simulating connection failure or early exit
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
    with patch.object(acq, "async_close", new_callable=AsyncMock):
        with pytest.raises(
            TokenAcquisitionError, match="Unsupported authentication mode"
        ):
            await acq.async_wait_for_token()
