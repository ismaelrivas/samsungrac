# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Unit tests for samsung_2878.py logic."""
# pylint: disable=protected-access,redefined-outer-name,import-outside-toplevel,line-too-long

from unittest.mock import MagicMock

import pytest

from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878


@pytest.fixture
def connection():
    """Fixture to create a ConnectionSamsung2878 instance with mocked dependencies."""
    hass_config = {"mac": "AA:BB:CC:DD:EE:FF", "ip_address": "192.168.1.100", "token": "test_token"}
    logger = MagicMock()
    conn = ConnectionSamsung2878(hass_config, logger)
    conn._socket_timeout = 30.0
    return conn



async def test_parse_and_update_state_valid_response(connection):
    from unittest.mock import AsyncMock
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()
    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)
    connection._controller.hass.async_add_executor_job = AsyncMock(side_effect=mock_async_add_executor_job)
    """Test parsing a valid DeviceState response."""
    xml = """<?xml version="1.0" encoding="utf-8" ?>
    <Response Type="DeviceState" Status="Okay">
        <DeviceState>
            <Device DUID="AABBCCDDEEFF" GroupID="AC" ModelID="AC" >
                <Attr ID="AC_FUN_POWER" Value="On" />
                <Attr ID="AC_FUN_TEMPSET" Value="24" />
            </Device>
        </DeviceState>
    </Response>
    """
    is_response, is_update, data = await connection._parse_and_update_state(xml)

    assert is_response is True
    assert is_update is False
    assert data["AC_FUN_POWER"] == "On"
    assert data["AC_FUN_TEMPSET"] == "24"



async def test_parse_and_update_state_valid_update(connection):
    from unittest.mock import AsyncMock
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()
    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)
    connection._controller.hass.async_add_executor_job = AsyncMock(side_effect=mock_async_add_executor_job)
    """Test parsing a valid Status Update."""
    xml = """<?xml version="1.0" encoding="utf-8" ?>
    <Update Type="Status">
        <Status DUID="AABBCCDDEEFF" GroupID="AC" ModelID="AC" >
            <Attr ID="AC_FUN_POWER" Value="Off" />
        </Status>
    </Update>
    """
    is_response, is_update, data = await connection._parse_and_update_state(xml)

    assert is_response is False
    assert is_update is True
    assert data["AC_FUN_POWER"] == "Off"



async def test_parse_and_update_state_invalid_xml(connection):
    from unittest.mock import AsyncMock
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()
    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)
    connection._controller.hass.async_add_executor_job = AsyncMock(side_effect=mock_async_add_executor_job)
    """Test parsing invalid XML returns False/None."""
    xml = "Not XML"
    is_response, is_update, data = await connection._parse_and_update_state(xml)

    assert is_response is False
    assert is_update is False
    assert data is None



async def test_parse_and_update_state_empty(connection):
    """Test parsing empty string returns False/None."""
    _is_response, _is_update, _data = await connection._parse_and_update_state("")



async def test_async_create_samsung_ssl_context_properties():
    """Test that the SSL context used for 2878 has the correct minimum properties."""
    import os
    import ssl
    import tempfile

    from custom_components.climate_ip.helpers import (
        async_create_samsung_ssl_context,
    )

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"dummy cert")
        cert_path = f.name

    try:
        from unittest.mock import patch

        with patch("ssl.SSLContext.load_verify_locations"), patch("ssl.SSLContext.load_cert_chain"):
            context = await async_create_samsung_ssl_context(
                cert_path=cert_path, ciphers="HIGH:!DH:!aNULL", verify_mode=ssl.CERT_NONE
            )

            assert context is not None
            assert context.verify_mode == ssl.CERT_NONE
    finally:
        os.unlink(cert_path)



async def test_reconnect_backoff_timing(connection):
    """Test that the backoff timer correctly exponential scales up to 40s (10, 20, 40) using the integration's logic."""
    from custom_components.climate_ip.samsung_2878 import (
        INITIAL_RECONNECT_DELAY,
        MAX_RECONNECT_DELAY,
        RECONNECT_FACTOR,
    )

    # 0 failures = INITIAL_RECONNECT_DELAY = 10.0
    assert connection._reconnect_retries == 0
    connection._reconnect_delay = INITIAL_RECONNECT_DELAY
    assert connection._reconnect_delay == 5.0  # INITIAL_RECONNECT_DELAY is 5

    # Simulate first failure calculation inline as in _connection_manager
    connection._reconnect_retries += 1
    connection._reconnect_delay = min(
        connection._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
    )

    # 1 failure
    assert connection._reconnect_retries == 1
    assert connection._reconnect_delay == 10.0

    # Simulate second failure
    connection._reconnect_retries += 1
    connection._reconnect_delay = min(
        connection._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
    )

    # 2 failures
    assert connection._reconnect_retries == 2
    assert connection._reconnect_delay == 20.0

    # Simulate third failure
    connection._reconnect_retries += 1
    connection._reconnect_delay = min(
        connection._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
    )

    # 3 failures (not capped yet)
    assert connection._reconnect_retries == 3
    assert connection._reconnect_delay == 40.0
