# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Integration tests for climate_ip against the 8888 emulator."""
# pylint: disable=redefined-outer-name,import-outside-toplevel,line-too-long,unused-import

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.const import (
    CONF_CONN_METHOD,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONN_METHOD_AIOHTTP,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN

pytest_plugins = ("custom_components.climate_ip.tests.conftest_emulator",)


@pytest.fixture
def mock_config_entry(emulator_8888):
    """Create a mock config entry pointing to the emulator."""
    return SimpleNamespace(
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: emulator_8888["port"],
            CONF_TOKEN: "legacy_token",
            CONF_CONN_METHOD: CONN_METHOD_AIOHTTP,
            CONF_DEVICE_ID: "0",
            CONF_DEVICE_TYPE: "samsung_8888",
            "use_http": True,
        },
        entry_id="test_entry_id",
        unique_id="test_unique_id",
        title="test_title",
        options={CONF_CONN_METHOD: CONN_METHOD_AIOHTTP},
        add_update_listener=MagicMock(),
        async_on_unload=MagicMock(),
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )


@patch("homeassistant.helpers.frame.report_usage", return_value=None)
async def test_integration_setup(
    _mock_report_usage,
    hass,
    emulator_8888,
    mock_config_entry,  # pylint: disable=unused-argument
):
    """Test full integration setup against the emulator."""

    # Initialize hass.data since we are using a MagicMock for hass
    hass.data = {}

    # Ensure our hass mock returns the correct mock entry when queried
    hass.config_entries.async_get_entry.return_value = mock_config_entry

    # Make async_forward_entry_setups awaitable
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    # Allow custom sockets for emulator integration
    import pytest_socket

    pytest_socket.enable_socket()

    # 1. Setup the integration
    import aiohttp

    real_session = aiohttp.ClientSession()
    from custom_components.climate_ip import async_setup_entry

    with (
        patch(
            "custom_components.climate_ip.async_get_clientsession",
            return_value=real_session,
        ),
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession",
            return_value=real_session,
        ),
    ):
        assert await async_setup_entry(hass, mock_config_entry)

    # 2. Verify coordinator exists and received data from emulator
    coordinator = mock_config_entry.runtime_data

    # coordinator.data is a ClimateIPDeviceState (not raw JSON).
    # Verify the controller's internal state was populated from the emulator's JSON response.
    # The emulator returns {"Devices": [{"connected": true, "Mode": {"modes": ["Auto","Cool","Dry","Wind"], ...}, ...}]}
    assert coordinator is not None
    controller = coordinator.controller
    hvac_mode = controller.get_property("hvac_mode")
    assert hvac_mode is not None, (
        "HVAC mode property should be populated from emulator state"
    )
    await real_session.close()


@patch("homeassistant.helpers.frame.report_usage", return_value=None)
async def test_control_device(
    _mock_report_usage, hass, emulator_8888, mock_config_entry
):
    """Test controlling the device via integration actions."""

    # Initialize hass.data since we are using a MagicMock for hass
    hass.data = {}

    # Ensure our hass mock returns the correct mock entry when queried
    hass.config_entries.async_get_entry.return_value = mock_config_entry

    # Make async_forward_entry_setups awaitable
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    # Allow custom sockets for emulator integration
    import pytest_socket

    pytest_socket.enable_socket()

    # 1. Setup the integration
    import aiohttp

    real_session = aiohttp.ClientSession()
    from custom_components.climate_ip import async_setup_entry

    with (
        patch(
            "custom_components.climate_ip.async_get_clientsession",
            return_value=real_session,
        ),
        patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession",
            return_value=real_session,
        ),
    ):
        assert await async_setup_entry(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data

    # 2. Change Mode by calling async_set_property on the controller
    success = await coordinator.controller.async_set_property("hvac_mode", "Cool")
    assert success is True

    # 3. Verify emulator received the command
    import asyncio

    queue = emulator_8888["queue"]

    # Wait for the command to hit the queue deterministically with a 2.0s timeout
    try:
        async with asyncio.timeout(2.0):
            while queue.empty():
                await asyncio.sleep(0.01)
    except TimeoutError:
        pass

    assert not queue.empty(), "Emulator should have received a command"
    last_command = None
    while not queue.empty():
        last_command = queue.get()

    assert last_command is not None
    # The mode change should PUT to an operation endpoint
    assert "path" in last_command
    await real_session.close()
