# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test DataUpdateCoordinator and state polling behaviors."""
# pylint: disable=redefined-outer-name,protected-access,import-outside-toplevel

from unittest.mock import AsyncMock, MagicMock, patch

import asyncio
import pytest

from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.exceptions import AuthError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed


async def test_token_auto_recovery_smartthings(hass: HomeAssistant) -> None:
    """Test that a 401 error triggers token refresh via SmartThings OAuth."""
    # Create a mock controller facade
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.token = "old_token"
    mock_controller.config = {"device_type": "smartthings_hvac"}
    mock_controller.hass = hass
    mock_controller.debug = False
    mock_controller.loader.is_fully_initialized = True

    # Mock the state getter to fail with 401 Unauthorized on the first try,
    # then succeed with fake data on the second try.
    # FIX: Use MagicMock instead of AsyncMock for the object itself,
    # and only make the async_update_state method an AsyncMock.
    mock_state_getter = MagicMock()
    mock_state_getter.async_update_state = AsyncMock(
        side_effect=[AuthError("401 Unauthorized"), {"DeviceState": "OK"}]
    )
    mock_controller.loader.state_getter = mock_state_getter

    poller = YamlStatePoller(mock_controller)

    # Patch the SmartThings specific token refresh mechanism
    with patch.object(
        poller, "_refresh_smartthings_token", return_value="new_fresh_token_123"
    ) as mock_refresh:
        # Trigger an update
        await poller.async_update_state()

        # Ensure the token refresh logic was executed due to the 401
        mock_refresh.assert_awaited_once()

        # Verify the controller received the new token seamlessly
        assert mock_controller.token == "new_fresh_token_123"


async def test_coordinator_transient_failure(hass: HomeAssistant) -> None:
    """Test that transient network errors are handled without dropping the entity state."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.name = "Test AC"
    # Ensure there's some initial data
    mock_controller.last_poll_data = {"status": "ok"}

    # 1. State getter throws OSError once (transient network error)
    # 2. Then succeeds on the next poll
    mock_state_getter = MagicMock()
    mock_state_getter.async_update_state = AsyncMock(
        side_effect=[OSError("Connection reset by peer"), {"DeviceState": "OK"}]
    )
    mock_controller.loader.state_getter = mock_state_getter
    mock_controller.poller = YamlStatePoller(mock_controller)
    mock_controller.async_get_status = AsyncMock(
        side_effect=[OSError("Connection reset by peer"), {"DeviceState": "OK"}]
    )

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    # The first update should throw UpdateFailed because YamlStatePoller simulates strikes inside async_update_state
    # We simulate this by making async_get_status raise an exception
    with pytest.raises(UpdateFailed, match="Network error"):
        await coordinator._async_update_data()

    # Second update should succeed and return the device state object
    data = await coordinator._async_update_data()
    assert data is not None


async def test_flicker_removed(hass: HomeAssistant) -> None:  # pylint: disable=unused-argument
    """Test that the UI flicker antipattern has been removed."""
    assert not hasattr(SamsungClimateCoordinator, "_async_flicker_ui"), (
        "_async_flicker_ui antipattern should be removed from SamsungClimateCoordinator"
    )


async def test_coordinator_strike_1_and_2_return_stale_data(
    hass: HomeAssistant,
) -> None:
    """Verify that strike 1 and 2 return last known data instead of failing.

    This ensures the entities don't transition to 'unavailable' on transient skips.
    """
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.name = "Test AC"

    # Initial data
    stale_data = MagicMock()
    stale_data.hvac_mode = "cool"

    # 1. First poll succeeds
    # 2. Second poll fails (Strike 1)
    # 3. Third poll fails (Strike 2)
    from custom_components.climate_ip.exceptions import CannotConnect

    mock_state_getter = MagicMock()
    mock_state_getter.async_update_state = AsyncMock(
        side_effect=[
            {"power": "on"},
            CannotConnect("Timeout"),
            CannotConnect("Connection refused"),
        ]
    )
    mock_controller.loader.state_getter = mock_state_getter
    mock_controller.poller = YamlStatePoller(mock_controller)
    mock_controller.async_get_status = mock_controller.poller.async_update_state

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    # 1. First poll succeeds
    await coordinator._async_update_data()

    # Strike 1: should return stale_data
    result1 = await coordinator._async_update_data()
    assert result1 is mock_controller.climate_state

    # Strike 2: should still return stale_data
    result2 = await coordinator._async_update_data()
    assert result2 is mock_controller.climate_state

    # Strike 3 (handled by existing test_coordinator_transient_failure) reaching 3
    # would throw UpdateFailed if we called it again.


async def test_auth_error_raises_config_entry_auth_failed(hass: HomeAssistant) -> None:
    """Verify that AuthError is translated to ConfigEntryAuthFailed."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    mock_controller = MagicMock()
    mock_controller.log_prefix = "[AuthTest]"
    mock_controller.async_get_status = AsyncMock(
        side_effect=AuthError("401 Unauthorized")
    )
    mock_controller.climate_state = MagicMock()

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_push_update_triggers_entity_refresh(hass: HomeAssistant) -> None:
    """Verify that push updates merge state and notify listeners."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[PushTest]"
    mock_controller.async_merge_device_state = AsyncMock()
    mock_controller.climate_state = MagicMock(hvac_mode="cool")

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    # Track listener calls
    listener_called = []
    coordinator.async_add_listener(lambda: listener_called.append(True))

    # Simulate a push update from the device
    await coordinator.async_handle_push_update({"AC_FUN_POWER": "On"})

    # Verify coordinator state was updated
    mock_controller.async_merge_device_state.assert_awaited_once_with(
        {"AC_FUN_POWER": "On"}
    )
    assert len(listener_called) == 1


async def test_coordinator_handles_503_transient_smartthings(
    hass: HomeAssistant,
) -> None:
    """Test that 503/Timeout transient errors in SmartThings don't drop the entity state."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[ST-Test]"
    mock_controller.config = {"device_type": "smartthings_hvac"}
    mock_controller.name = "Smart AC"

    # 1. Setup states
    success_state_1 = MagicMock(spec=["power"])
    success_state_1.power = "on"
    success_state_2 = MagicMock(spec=["power"])
    success_state_2.power = "off"

    # Initially return success_state_1
    mock_controller.climate_state = success_state_1

    # Sequence of responses for the network call:
    # 1. Success (Setup initial cache)
    # 2. Failure: TimeoutError (Strike 1) -> Returns cached data
    # 3. Failure: TimeoutError (Strike 2) -> Returns cached data
    # 4. Success (Recovery) -> Returns new climate_state
    from custom_components.climate_ip.exceptions import CannotConnect

    mock_state_getter = MagicMock()
    mock_state_getter.async_update_state = AsyncMock(
        side_effect=[
            {"status": "ok"},  # Success
            CannotConnect("503 Service Unavailable"),
            CannotConnect("503 Service Unavailable"),
            {"status": "ok_recovered"},  # Success recovery
        ]
    )
    mock_controller.loader.state_getter = mock_state_getter
    mock_controller.poller = YamlStatePoller(mock_controller)
    mock_controller.async_get_status = mock_controller.poller.async_update_state

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    # Stage 0: Initial fetch (Success)
    data0 = await coordinator._async_update_data()
    assert data0 == success_state_1

    # Stage 1: Strike 1 (Transient Failure)
    # Should return PREVIOUSLY cached data0 instead of failing
    data1 = await coordinator._async_update_data()
    assert data1 is data0

    # Stage 2: Strike 2 (Transient Failure)
    # Should still return PREVIOUSLY cached data0
    data2 = await coordinator._async_update_data()
    assert data2 is data0

    # Stage 3: Recovery (Success)
    # Update controller state before recovery poll
    mock_controller.climate_state = success_state_2
    data3 = await coordinator._async_update_data()
    assert data3 == success_state_2


# ---------------------------------------------------------------------------
# Test Plan - Case 4: Optimistic Update + State Revert (Audit v8 §D)
# ---------------------------------------------------------------------------


async def test_optimistic_state_reverts_on_device_failure(hass: HomeAssistant) -> None:
    """Verify async_request_refresh is called when the controller rejects a command.

    When async_set_property returns False (device rejected the command), the
    coordinator must request a refresh to revert any optimistic state changes.
    """
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[OptimisticTest]"
    mock_controller.async_set_property = AsyncMock(return_value=False)
    mock_controller.climate_state = MagicMock(hvac_mode="cool")

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    coordinator.data = mock_controller.climate_state
    coordinator.async_request_refresh = AsyncMock()

    # Device rejects the "dry" command; coordinator must revert state via refresh
    await coordinator.async_set_property("hvac_mode", "dry")

    coordinator.async_request_refresh.assert_awaited_once()


async def test_flicker_antipattern_absent(hass: HomeAssistant) -> None:  # pylint: disable=unused-argument
    """Verify that the _async_flicker_ui antipattern is absent from the coordinator."""
    assert not hasattr(SamsungClimateCoordinator, "_async_flicker_ui"), (
        "_async_flicker_ui antipattern must not exist in SamsungClimateCoordinator"
    )


async def test_optimistic_refresh_on_network_error(hass: HomeAssistant) -> None:
    """Verify that a CannotConnect during set_property triggers a state refresh.

    The coordinator must call async_request_refresh even after a network exception
    to ensure any optimistic entity state changes are reverted.
    """
    from custom_components.climate_ip.exceptions import CannotConnect
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_controller = MagicMock()
    mock_controller.log_prefix = "[NetErrTest]"
    mock_controller.async_set_property = AsyncMock(
        side_effect=CannotConnect("Device unreachable")
    )
    mock_controller.climate_state = MagicMock(hvac_mode="cool")

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    coordinator.data = mock_controller.climate_state
    coordinator.async_request_refresh = AsyncMock()

    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_property("hvac_mode", "dry")

    # Even on exception the coordinator must refresh to reconcile the real state
    coordinator.async_request_refresh.assert_awaited_once()


async def test_coordinator_timeout_recovery(hass: HomeAssistant) -> None:
    """Test that the coordinator effectively recovers from TimeoutErrors."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_controller = MagicMock()
    mock_controller.log_prefix = "[RecoverTest]"
    mock_controller.name = "Test AC"

    from custom_components.climate_ip.exceptions import CannotConnect

    mock_state_getter = MagicMock()
    mock_state_getter.async_update_state = AsyncMock(
        side_effect=[
            {"power": "on"},  # Initial success to populate cache
            CannotConnect("Timeout first"),
            CannotConnect("Timeout second"),
            CannotConnect("Timeout third"),
            {"power": "on"},
        ]
    )
    mock_controller.loader = MagicMock()
    mock_controller.loader.state_getter = mock_state_getter
    mock_controller.poller = YamlStatePoller(mock_controller)
    mock_controller.async_get_status = mock_controller.poller.async_update_state

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    coordinator.data = MagicMock()
    coordinator.data.power = "off"

    res0 = await coordinator._async_update_data()  # Success
    assert res0 is mock_controller.climate_state

    res1 = await coordinator._async_update_data()  # Strike 1
    assert res1 is mock_controller.climate_state

    res2 = await coordinator._async_update_data()  # Strike 2
    assert res2 is mock_controller.climate_state

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    mock_controller.climate_state = MagicMock()
    mock_controller.climate_state.power = "on"
    res4 = await coordinator._async_update_data()
    assert res4.power == "on"


# ---------------------------------------------------------------------------
# Fix 1 regression: corrections must be dispatched to the controller
# ---------------------------------------------------------------------------


async def test_corrections_are_dispatched_to_controller(hass: HomeAssistant) -> None:
    """Verify that corrections are sent to the controller as individual commands.

    Regression test for the bug where a guard condition inside the
    async_set_property loop caused all entries in the ``corrections`` dict to be
    silently skipped before reaching the controller.

    Scenario: setting hvac_mode=COOL forces fan_mode=auto (COOL is incompatible
    with turbo fan speed).  The coordinator must fire one controller command per
    property — two total: 'hvac_mode' first, then 'fan_mode'.
    """
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[CorrectionTest]"
    # Every async_set_property call succeeds
    mock_controller.async_set_property = AsyncMock(return_value=True)
    mock_controller.climate_state = MagicMock(hvac_mode="cool")

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    hass.loop.call_later.side_effect = lambda delay, callback: callback()
    hass.async_create_task.side_effect = lambda coro, **kw: asyncio.create_task(coro)
    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    coordinator.data = mock_controller.climate_state

    corrections = {"fan_mode": "auto"}
    await coordinator.async_set_property("hvac_mode", "cool", corrections=corrections)
    await asyncio.sleep(0)

    # The controller must have been called exactly twice:
    #   call 1 → ("hvac_mode", "cool", None)
    #   call 2 → ("fan_mode", "auto", None)
    assert mock_controller.async_set_property.await_count == 2, (
        f"Expected 2 controller calls (main + correction), "
        f"got {mock_controller.async_set_property.await_count}"
    )

    # Verify the specific calls and their order (dict insertion order is stable in Python 3.7+)
    call_args_list = mock_controller.async_set_property.await_args_list
    first_call_prop, first_call_val, _ = call_args_list[0].args
    second_call_prop, second_call_val, _ = call_args_list[1].args

    assert first_call_prop == "hvac_mode", (
        f"First command must be the main property 'hvac_mode', got '{first_call_prop}'"
    )
    assert first_call_val == "cool"

    assert second_call_prop == "fan_mode", (
        f"Second command must be the correction 'fan_mode', got '{second_call_prop}'"
    )
    assert second_call_val == "auto"


async def test_save_new_token_updates_config_entry(hass: HomeAssistant) -> None:
    """Verify that the _save_new_token callback properly updates the ConfigEntry.

    This ensures we do not hit a TypeError if entry.data is null, and that the
    mock_update_entry is called correctly with the new token.
    """
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[TokenTest]"
    mock_entry = MagicMock()
    mock_entry.data = {"host": "192.168.1.10", "token": "old_token"}
    mock_entry.options = {}

    hass.loop.call_soon_threadsafe.side_effect = lambda f, *a, **kw: f(*a, **kw)
    SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    with (
        patch.object(hass.config_entries, "async_update_entry") as mock_update_entry,
        patch("custom_components.climate_ip.coordinator._LOGGER.info") as mock_info,
    ):
        # Trigger the callback injected into the controller
        mock_controller.on_token_refreshed("new_token_2878")

        # Rigorous assertion of the final state (kills the null initialization mutant)
        mock_update_entry.assert_called_once_with(
            mock_entry, data={"host": "192.168.1.10", "token": "new_token_2878"}
        )
        mock_info.assert_called_once_with(
            "%s Persisted new network token to Config Entry.", "[TokenTest]"
        )


async def test_save_new_token_async_flow(hass: HomeAssistant) -> None:
    """Verify that the token refresh flow works when emitted asynchronously."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[TokenAsyncTest]"
    mock_entry = MagicMock()
    mock_entry.data = {"host": "192.168.1.10", "token": "old_token"}
    mock_entry.options = {}

    hass.loop.call_soon_threadsafe.side_effect = lambda f, *a, **kw: f(*a, **kw)
    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    task_executed = False
    task_error = None

    with patch.object(hass.config_entries, "async_update_entry") as mock_update_entry:

        async def network_task_emit():
            nonlocal task_executed, task_error
            try:
                # Sleep briefly to ensure this runs as a separate tick
                await asyncio.sleep(0.001)
                task_executed = True
                coordinator.controller.on_token_refreshed("new_token_async")
            except Exception as e:
                task_error = e

        # Emits the event asynchronously by scheduling it natively as an asyncio task
        # avoiding hass.async_create_task since it evaluates to a MagicMock in this suite
        task = asyncio.create_task(network_task_emit())

        # Yield control to the event loop
        await hass.async_block_till_done()

        # Alternatively, ensure the task itself is fully complete
        await task

    if task_error:
        raise RuntimeError(f"Background task failed: {task_error}") from task_error

    if not task_executed:
        raise RuntimeError("Background task was NEVER executed by the event loop!")

    mock_update_entry.assert_called_once_with(
        mock_entry, data={"host": "192.168.1.10", "token": "new_token_async"}
    )


async def test_coordinator_injected_callbacks(hass: HomeAssistant) -> None:
    """Test that coordinator correctly injects callbacks into the controller."""
    mock_controller = MagicMock()
    mock_entry = MagicMock()
    mock_entry.data = {}
    mock_entry.options = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    # Check get_current_state_callback
    assert mock_controller.get_current_state_callback is not None
    coordinator.data = {"test_state": "active"}
    assert mock_controller.get_current_state_callback() == {"test_state": "active"}

    # Check on_push_update_callback
    assert (
        mock_controller.on_push_update_callback == coordinator.async_handle_push_update
    )

    # Check request_refresh_callback
    assert mock_controller.request_refresh_callback is not None
    with patch.object(coordinator, "async_request_refresh") as mock_refresh:
        await mock_controller.request_refresh_callback()
        mock_refresh.assert_awaited_once()

    # Check on_connection_failed_callback
    assert mock_controller.on_connection_failed_callback is not None
    coordinator.last_update_success = True
    with patch.object(coordinator, "async_update_listeners") as mock_listeners:
        mock_controller.on_connection_failed_callback()
        assert coordinator.last_update_success is False
        mock_listeners.assert_called_once()


async def test_offline_callback_forces_update_error(hass: HomeAssistant) -> None:
    """Test that the offline callback correctly triggers an update error."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[OfflineTest]"

    mock_entry = MagicMock()
    mock_entry.data = {}
    mock_entry.options = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    assert mock_controller.on_offline_callback is not None

    with (
        patch("custom_components.climate_ip.coordinator._LOGGER.debug") as mock_debug,
        patch.object(coordinator, "async_set_update_error") as mock_set_error,
    ):
        mock_controller.on_offline_callback("Ping failed")

        mock_debug.assert_called_once_with(
            "%s Network layer declared device offline. Forcing UpdateFailed.",
            "[OfflineTest]",
        )

        mock_set_error.assert_called_once()
        error_arg = mock_set_error.call_args[0][0]
        assert isinstance(error_arg, UpdateFailed)
        assert str(error_arg) == "Device offline: Ping failed"


async def test_save_ssl_config_updates_entry(hass: HomeAssistant) -> None:
    """Test that _save_ssl_config updates the ConfigEntry with new SSL config."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[SSLTest]"
    mock_entry = MagicMock()
    mock_entry.data = {"host": "192.168.1.10"}
    mock_entry.options = {}

    hass.loop.call_soon_threadsafe.side_effect = lambda f, *a, **kw: f(*a, **kw)
    SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    with (
        patch.object(hass.config_entries, "async_update_entry") as mock_update_entry,
        patch("custom_components.climate_ip.coordinator._LOGGER.info") as mock_info,
    ):
        # Call the injected callback
        mock_controller.on_ssl_config_updated({"cert": "new_cert"})

        # Verify entry was updated
        mock_update_entry.assert_called_once_with(
            mock_entry,
            data={"host": "192.168.1.10", "_ssl_config_2878": {"cert": "new_cert"}},
        )
        mock_info.assert_called_once_with(
            "%s Persisted SSL config to ConfigEntry data.", "[SSLTest]"
        )

    # Second call with same config shouldn't trigger update
    with patch.object(hass.config_entries, "async_update_entry") as mock_update_entry_2:
        mock_entry.data = {
            "host": "192.168.1.10",
            "_ssl_config_2878": {"cert": "new_cert"},
        }
        mock_controller.on_ssl_config_updated({"cert": "new_cert"})
        mock_update_entry_2.assert_not_called()


async def test_coordinator_update_interval_enable_polling_options(
    hass: HomeAssistant,
) -> None:
    """Test update_interval logic with enable_polling in options."""
    mock_controller = MagicMock()
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {"enable_polling": False, "poll_interval": 10}
    mock_entry.data = {"enable_polling": True, "poll_interval": 20}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    assert coordinator.update_interval is None


async def test_coordinator_super_init_attributes(hass: HomeAssistant) -> None:
    """Test that coordinator correctly passes parameters to super().__init__."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[SuperTest]"
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {"enable_polling": True, "poll_interval": 33}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    from datetime import timedelta

    assert coordinator.name == "Samsung Climate [SuperTest]"
    assert coordinator.update_interval == timedelta(seconds=33)
    assert coordinator.always_update is True
    assert coordinator.config_entry is mock_entry


async def test_coordinator_device_info_with_name_and_id(hass: HomeAssistant) -> None:
    """Test device_info parsing when both name and id are provided."""
    mock_controller = MagicMock()
    mock_controller.unique_id = "test_sub_device_1"

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    device_info = {"id": "1", "name": "Living Room AC"}

    coordinator = SamsungClimateCoordinator(
        hass, mock_controller, mock_entry, device_info=device_info
    )
    assert coordinator.device_info["name"] == "ID 1 (Living Room AC)"


async def test_coordinator_device_info_without_name(hass: HomeAssistant) -> None:
    """Test device_info parsing when name is missing."""
    mock_controller = MagicMock()
    mock_controller.unique_id = "test_sub_device_2"

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    device_info = {"id": "2"}

    coordinator = SamsungClimateCoordinator(
        hass, mock_controller, mock_entry, device_info=device_info
    )
    assert coordinator.device_info["name"] == "ID 2 (Unknown Unit)"


async def test_coordinator_device_info_without_id(hass: HomeAssistant) -> None:
    """Test device_info parsing when id is missing."""
    mock_controller = MagicMock()
    mock_controller.unique_id = "test_sub_device_3"

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    device_info = {"name": "Only Name AC"}

    coordinator = SamsungClimateCoordinator(
        hass, mock_controller, mock_entry, device_info=device_info
    )
    assert coordinator.device_info["name"] == "Only Name AC"


async def test_coordinator_device_info_redundant_name(hass: HomeAssistant) -> None:
    """Test device_info parsing when name already includes the ID."""
    mock_controller = MagicMock()
    mock_controller.unique_id = "test_sub_device_4"

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    device_info = {"id": "1", "name": "ID 1 (Living Room)"}

    coordinator = SamsungClimateCoordinator(
        hass, mock_controller, mock_entry, device_info=device_info
    )
    # Shouldn't wrap it again with ID 1
    assert coordinator.device_info["name"] == "ID 1 (Living Room)"


async def test_coordinator_device_info_complete_attributes(hass: HomeAssistant) -> None:
    """Test all attributes of device_info for a sub-device."""
    mock_controller = MagicMock()
    mock_controller.unique_id = "test_sub_device_5"

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    device_info = {"id": "1", "name": "Test AC"}

    from custom_components.climate_ip.const import DOMAIN

    coordinator = SamsungClimateCoordinator(
        hass,
        mock_controller,
        mock_entry,
        device_info=device_info,
        parent_unique_id="parent_mac_123",
    )

    assert coordinator.device_info["name"] == "ID 1 (Test AC)"
    assert coordinator.device_info["identifiers"] == {(DOMAIN, "test_sub_device_5")}
    assert coordinator.device_info["manufacturer"] == "Samsung"
    assert coordinator.device_info["via_device"] == (DOMAIN, "parent_mac_123")


async def test_coordinator_standalone_device_info(hass: HomeAssistant) -> None:
    """Test device_info parsing for a standalone device (no sub-devices)."""
    mock_controller = MagicMock()
    mock_controller.unique_id = "standalone_ac_123"

    from homeassistant.const import CONF_MAC
    from custom_components.climate_ip.const import CONF_NAME, DOMAIN
    import homeassistant.helpers.device_registry as dr

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {CONF_MAC: "00:11:22:33:44:55", CONF_NAME: "My Awesome AC"}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    assert coordinator.device_info is not None
    assert coordinator.device_info["identifiers"] == {(DOMAIN, "standalone_ac_123")}
    assert coordinator.device_info["name"] == "My Awesome AC"
    assert coordinator.device_info["manufacturer"] == "Samsung"
    assert coordinator.device_info["connections"] == {
        (dr.CONNECTION_NETWORK_MAC, "00:11:22:33:44:55")
    }


async def test_coordinator_standalone_device_info_no_mac_no_name(
    hass: HomeAssistant,
) -> None:
    """Test device_info fallback logic when MAC and Name are missing."""
    mock_controller = MagicMock()
    mock_controller.unique_id = "standalone_ac_456"

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    assert coordinator.device_info["name"] == "Samsung AC standalone_ac_456"
    assert coordinator.device_info["connections"] == set()


async def test_fallback_to_raw_engine_on_http_header_error(hass: HomeAssistant) -> None:
    """Verify async_update_entry is called before raising UpdateFailed on header errors."""
    from homeassistant.helpers.update_coordinator import UpdateFailed
    from custom_components.climate_ip.const import CONF_CONN_METHOD, CONN_METHOD_RAW
    from custom_components.climate_ip.exceptions import InvalidHeaderError
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock, patch

    mock_controller = MagicMock()
    mock_controller.log_prefix = "[Fallback]"
    mock_controller.name = "Test AC"

    # Simulate current ConfigEntry with pre-existing option
    mock_entry = MagicMock()
    mock_entry.options = {"existing_opt": "value"}
    mock_entry.data = {}

    # Force the specific error that triggers HTTP header fallback
    mock_state_getter = MagicMock()
    mock_state_getter.async_update_state = AsyncMock(
        side_effect=InvalidHeaderError("Malformed headers")
    )
    mock_controller.loader.state_getter = mock_state_getter
    mock_controller.poller = YamlStatePoller(mock_controller)
    mock_controller.async_get_status = mock_controller.poller.async_update_state

    # Import SamsungClimateCoordinator here as assumed at the top of the file
    from custom_components.climate_ip.coordinator import SamsungClimateCoordinator

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    with patch.object(hass.config_entries, "async_update_entry") as mock_update_entry:
        # The test demands the coordinator to abort cleanly
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        # THIS ASSERTION KILLS MUTANT 24
        # Verify that before aborting, it modified config to use RAW
        mock_update_entry.assert_called_once_with(
            mock_entry,
            options={"existing_opt": "value", CONF_CONN_METHOD: CONN_METHOD_RAW},
        )


async def test_coordinator_initialization_logging(hass: HomeAssistant) -> None:
    """Test that coordinator logs its initialization with the correct parameters."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[InitLogTest]"
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {"enable_polling": True, "poll_interval": 25}
    mock_entry.data = {}

    from datetime import timedelta

    expected_interval = timedelta(seconds=25)

    with patch("custom_components.climate_ip.coordinator._LOGGER.debug") as mock_debug:
        SamsungClimateCoordinator(hass, mock_controller, mock_entry)

        mock_debug.assert_any_call(
            "%s Initializing coordinator with update interval: %s",
            "[InitLogTest]",
            expected_interval,
        )


async def test_coordinator_update_interval_enable_polling_data(
    hass: HomeAssistant,
) -> None:
    """Test update_interval logic with enable_polling in data."""
    mock_controller = MagicMock()
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {"enable_polling": True, "poll_interval": 42}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    from datetime import timedelta

    assert coordinator.update_interval == timedelta(seconds=42)


async def test_coordinator_update_interval_enable_polling_default(
    hass: HomeAssistant,
) -> None:
    """Test update_interval logic with enable_polling default."""
    mock_controller = MagicMock()
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    from datetime import timedelta

    assert coordinator.update_interval == timedelta(seconds=60)


async def test_coordinator_update_interval_poll_interval_options(
    hass: HomeAssistant,
) -> None:
    """Test that poll_interval is pulled from options."""
    mock_controller = MagicMock()
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {"enable_polling": True, "poll_interval": 15}
    mock_entry.data = {"enable_polling": True, "poll_interval": 20}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    from datetime import timedelta

    assert coordinator.update_interval == timedelta(seconds=15)


async def test_coordinator_update_interval_poll_interval_data(
    hass: HomeAssistant,
) -> None:
    """Test that poll_interval is pulled from data when options is missing it."""
    mock_controller = MagicMock()
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {"enable_polling": True}
    mock_entry.data = {"enable_polling": True, "poll_interval": 42}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    from datetime import timedelta

    assert coordinator.update_interval == timedelta(seconds=42)


async def test_coordinator_update_interval_poll_interval_default(
    hass: HomeAssistant,
) -> None:
    """Test that poll_interval falls back to default."""
    mock_controller = MagicMock()
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {"enable_polling": True}
    mock_entry.data = {"enable_polling": True}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    from datetime import timedelta

    assert coordinator.update_interval == timedelta(seconds=60)


async def test_coordinator_update_interval_no_poll(hass: HomeAssistant) -> None:
    """Test that update_interval is None when controller.poll is False."""
    mock_controller = MagicMock()
    mock_controller.poll = False

    mock_entry = MagicMock()
    mock_entry.options = {"enable_polling": True, "poll_interval": 15}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    assert coordinator.update_interval is None


async def test_coordinator_update_interval_enable_polling_data_false(
    hass: HomeAssistant,
) -> None:
    """Verify that enable_polling=False in data is respected and doesn't fall back to default."""
    from custom_components.climate_ip.const import CONF_ENABLE_POLLING

    mock_controller = MagicMock()
    mock_controller.poll = True

    mock_entry = MagicMock()
    mock_entry.options = {}
    # Assume DEFAULT_ENABLE_POLLING is True. Force the key to False in data.
    mock_entry.data = {CONF_ENABLE_POLLING: False, "poll_interval": 42}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    # Original code will read False and turn off polling (update_interval = None).
    # Mutant will read the 'None' key, fall back to default (True) and assign a timedelta of 42s.
    assert coordinator.update_interval is None, (
        "The coordinator ignored CONF_ENABLE_POLLING from entry.data or fell back to the default value"
    )


async def test_async_set_property_passes_device_id(hass: HomeAssistant) -> None:
    """Verify that async_set_property passes the specific device_id to the controller."""
    mock_controller = MagicMock()
    mock_controller.log_prefix = "[DeviceIDTest]"
    mock_controller.async_set_property = AsyncMock(return_value=True)
    mock_controller.climate_state = MagicMock(hvac_mode="cool")

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    coordinator.data = mock_controller.climate_state

    await coordinator.async_set_property(
        "hvac_mode", "dry", device_id="child_device_123"
    )

    mock_controller.async_set_property.assert_awaited_once_with(
        "hvac_mode", "dry", "child_device_123"
    )


async def test_async_set_property_raises_update_failed_on_exception_with_message(
    hass: HomeAssistant,
) -> None:
    """Verify that a generic exception during async_set_property raises UpdateFailed with the correct message."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_controller = MagicMock()
    mock_controller.log_prefix = "[ExcMsgTest]"
    mock_controller.async_set_property = AsyncMock(
        side_effect=Exception("Simulated unexpected failure")
    )
    mock_controller.climate_state = MagicMock(hvac_mode="cool")

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    coordinator.data = mock_controller.climate_state
    coordinator.async_request_refresh = AsyncMock()

    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(
        HomeAssistantError,
        match="Failed to set property hvac_mode: Simulated unexpected failure",
    ):
        await coordinator.async_set_property("hvac_mode", "dry")


async def test_coordinator_enforces_strict_timeout(hass: HomeAssistant) -> None:
    """Verify that the coordinator enforces a 30.0 second timeout on device polling."""
    from unittest.mock import MagicMock, patch
    from custom_components.climate_ip.const import NETWORK_POLL_TIMEOUT
    from custom_components.climate_ip.coordinator import SamsungClimateCoordinator

    mock_controller = MagicMock()
    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    # Intercept asyncio.wait_for directly in the coordinator module
    with patch(
        "custom_components.climate_ip.coordinator.asyncio.wait_for"
    ) as mock_wait:
        await coordinator._async_update_data()

        # Validate that it was called with the exact timeout
        mock_wait.assert_called_once()
        assert mock_wait.call_args.kwargs.get("timeout") == NETWORK_POLL_TIMEOUT, (
            "The network timeout was altered"
        )


async def test_coordinator_unwraps_hvac_enum_before_sending(
    hass: HomeAssistant,
) -> None:
    """Verify that Enums are unwrapped to their primitive values before dispatching."""
    from homeassistant.components.climate import HVACMode
    from unittest.mock import MagicMock, AsyncMock
    from custom_components.climate_ip.coordinator import SamsungClimateCoordinator

    mock_controller = MagicMock()
    mock_controller.async_set_property = AsyncMock(return_value=True)

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    # Send a Home Assistant Enum object
    await coordinator.async_set_property("hvac_mode", HVACMode.COOL)

    # The controller MUST receive the primitive (string), not the Enum
    mock_controller.async_set_property.assert_awaited_once_with(
        "hvac_mode", "cool", None
    )


async def test_coordinator_requests_refresh_on_partial_failure(
    hass: HomeAssistant,
) -> None:
    """Verify that a partial command failure triggers a state refresh to revert UI."""
    from unittest.mock import MagicMock, AsyncMock
    from custom_components.climate_ip.coordinator import SamsungClimateCoordinator

    mock_controller = MagicMock()
    # Simulate that sending the command fails
    mock_controller.async_set_property = AsyncMock(return_value=False)

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    coordinator.async_request_refresh = AsyncMock()

    # Attempt to set a property (which will fail internally)
    await coordinator.async_set_property("fan_mode", "high")

    # Upon failure, success becomes False and must force a refresh
    coordinator.async_request_refresh.assert_awaited_once()


async def test_coordinator_success_path_no_refresh(hass: HomeAssistant) -> None:
    """Verify that a successful command execution does NOT trigger a state refresh."""
    from unittest.mock import MagicMock, AsyncMock
    from custom_components.climate_ip.coordinator import SamsungClimateCoordinator

    mock_controller = MagicMock()
    # Simulate that the command SUCCEEDS (returns True)
    mock_controller.async_set_property = AsyncMock(return_value=True)

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}

    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)
    coordinator.async_request_refresh = AsyncMock()

    # Execute the command
    await coordinator.async_set_property("fan_mode", "high")

    # LETHAL ASSERTION: If success mutated to False or None, this will fail.
    coordinator.async_request_refresh.assert_not_awaited()


async def test_async_predict_and_correct_supported(hass: HomeAssistant) -> None:
    """Test state prediction when supported by controller."""
    from homeassistant.components.climate import HVACMode
    from unittest.mock import MagicMock, AsyncMock, patch

    mock_controller = MagicMock()
    mock_controller.async_predict_and_correct_state = AsyncMock(
        return_value=("fake_flags", {"temp": 24})
    )
    mock_controller.climate_state = MagicMock()

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}
    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    with patch.object(coordinator, "async_set_updated_data") as mock_set:
        flags, corrections = await coordinator.async_predict_and_correct(
            {"fake": "state"}, "hvac_mode", HVACMode.HEAT
        )

        # Verify enum unwrapped
        mock_controller.async_predict_and_correct_state.assert_awaited_once_with(
            {"fake": "state"}, "hvac_mode", "heat"
        )

        # Verify coordinator pushed state
        mock_set.assert_called_once_with(mock_controller.climate_state)

        assert flags == "fake_flags"
        assert corrections == {"temp": 24}


async def test_async_predict_and_correct_unsupported(hass: HomeAssistant) -> None:
    """Test state prediction when not supported by controller."""
    from homeassistant.components.climate.const import ClimateEntityFeature
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    # Explicitly remove the method from the mock
    del mock_controller.async_predict_and_correct_state
    mock_controller.log_prefix = "[Test]"

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}
    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    with pytest.raises(AttributeError):
        await coordinator.async_predict_and_correct(
            {"fake": "state"}, "hvac_mode", "heat"
        )


async def test_coordinator_getters(hass: HomeAssistant) -> None:
    """Test get_property and get_property_object getters."""
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    mock_controller.get_property.return_value = "property_value"
    mock_controller.get_property_object.return_value = {"object": "value"}

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}
    coordinator = SamsungClimateCoordinator(hass, mock_controller, mock_entry)

    assert coordinator.get_property("some_prop") == "property_value"
    mock_controller.get_property.assert_called_once_with("some_prop")

    assert coordinator.get_property_object("some_obj") == {"object": "value"}
    mock_controller.get_property_object.assert_called_once_with("some_obj")
