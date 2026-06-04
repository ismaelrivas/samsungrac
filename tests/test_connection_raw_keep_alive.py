# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ConnectionRaw8888 keep-alive logic."""
# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.climate_ip.connection_raw import ConnectionRaw8888


@pytest.fixture
def mock_client():
    """Create a mock Samsung8888Client."""
    client = AsyncMock()
    client.request = AsyncMock(return_value=('{"result": "ok"}', None))
    client.close = AsyncMock()
    return client



async def test_periodic_reset_logic(mock_client):
    """Test that connection is closed before poll if keep_alive is False."""
    config = {"keep_alive": False, "ip_address": "1.2.3.4", "token": "mock_token"}
    conn = ConnectionRaw8888(config, MagicMock(), MagicMock(), MagicMock(), "1.2.3.4")

    # Mock async_get_client to return our mock
    conn.async_get_client = AsyncMock(return_value=mock_client)

    # Simulate existing connection
    conn._client = mock_client

    # Execute with _is_poll=True
    await conn.async_execute("GET", "/test", None, {}, _is_poll=True)

    # Verify close() was called because keep_alive is False and it's a poll
    mock_client.close.assert_called_once()



async def test_no_reset_on_command(mock_client):
    """Test that connection is NOT closed on command if keep_alive is False."""
    config = {"keep_alive": False, "ip_address": "1.2.3.4", "token": "mock_token"}
    conn = ConnectionRaw8888(config, MagicMock(), MagicMock(), MagicMock(), "1.2.3.4")
    conn.async_get_client = AsyncMock(return_value=mock_client)
    conn._client = mock_client

    # Execute with _is_poll=False (default)
    await conn.async_execute("GET", "/test", None, {})

    # Verify close() was NOT called
    mock_client.close.assert_not_called()



async def test_no_reset_if_keep_alive_true(mock_client):
    """Test that connection is NOT closed if keep_alive is True."""
    config = {"keep_alive": True, "ip_address": "1.2.3.4", "token": "mock_token"}
    conn = ConnectionRaw8888(config, MagicMock(), MagicMock(), MagicMock(), "1.2.3.4")
    conn.async_get_client = AsyncMock(return_value=mock_client)
    conn._client = mock_client

    # Execute with _is_poll=True
    await conn.async_execute("GET", "/test", None, {}, _is_poll=True)

    # Verify close() was NOT called
    mock_client.close.assert_not_called()
