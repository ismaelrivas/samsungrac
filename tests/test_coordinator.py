"""Unit tests for SamsungClimateCoordinator and PropertyDebouncer (coordinator.py)."""

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.climate_ip.const import (
    ATTR_POWER,
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_SSL_CONFIG_KEY,
    CONF_SUBDEVICE_ID,
    CONN_METHOD_RAW,
    DEFAULT_DEBOUNCE_DELAY,
    DEFAULT_DEVICE_NAME_PREFIX,
    DEFAULT_INTESISBOX_NAME_PREFIX,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SUBDEVICE_NAME,
    DEVICE_TYPE_INTESISBOX,
    DOMAIN,
    ERR_AUTO_HEALING_RAW_IN_PROGRESS,
    ERR_DEVICE_OFFLINE_PREFIX,
    ERR_PERSISTENT_CONNECTION_FAILURE,
    HARDWARE_BREATHING_ROOM_SEC,
    ISSUE_AUTO_HEALING_RAW,
    MANUFACTURER_INTESIS,
    MANUFACTURER_SAMSUNG,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    NETWORK_POLL_TIMEOUT,
)
from custom_components.climate_ip.coordinator import (
    DEBOUNCE_QUEUED,
    PropertyDebouncer,
    SamsungClimateCoordinator,
)
from custom_components.climate_ip.exceptions import (
    AuthError,
    CannotConnect,
    InvalidHeaderError,
)
from homeassistant.components.climate import ATTR_HVAC_MODE, HVACMode
from homeassistant.const import CONF_MAC, CONF_TOKEN
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed


def _make_bare_coordinator(
    hass: Any = None,
    controller: Any = None,
    entry: Any = None,
) -> SamsungClimateCoordinator:
    """Create a bare SamsungClimateCoordinator without invoking __init__."""
    coord: SamsungClimateCoordinator = object.__new__(SamsungClimateCoordinator)
    coord.hass = hass if hass is not None else MagicMock()
    if controller is None:
        controller = MagicMock(
            spec=[
                "unique_id",
                "log_prefix",
                "climate_state",
                "async_get_status",
                "clear_state_cache",
                "async_merge_device_state",
                "is_property_superseded",
                "async_set_property",
                "async_predict_and_correct_state",
                "async_clear_pending_updates",
                "async_shutdown",
            ]
        )
        controller.unique_id = "uid_default"
        controller.log_prefix = "[uid_default]"
    coord.controller = controller
    coord.config_entry = (
        entry
        if entry is not None
        else MagicMock(options={}, data={}, unique_id="entry_uid", entry_id="entry_id")
    )
    coord.devices = {}
    coord._global_network_lock = asyncio.Lock()
    coord.device_info = {"name": "Test AC"}
    coord.data = None
    coord.last_update_success = True
    return coord


@pytest.mark.asyncio
async def test_01_debouncer_primitives_immediate_and_turn_off() -> None:
    """Verify PropertyDebouncer init, helpers, validation, turn-off bypasses, and window boundaries."""
    mock_coord = MagicMock()
    mock_coord.hass = MagicMock()
    mock_coord.hass.loop.time.return_value = 100.0
    mock_coord.controller.async_clear_pending_updates = AsyncMock()
    mock_coord.async_request_refresh = AsyncMock()

    debouncer = PropertyDebouncer(mock_coord)
    assert debouncer.coordinator is mock_coord
    assert debouncer.delay == DEFAULT_DEBOUNCE_DELAY
    assert debouncer.hass is mock_coord.hass
    assert debouncer._timers == {}
    assert debouncer._pending_payloads == {}
    assert debouncer._last_activities == {}
    assert debouncer._generation == 0
    assert debouncer.is_active is False
    assert debouncer.has_pending("temp") is False

    custom_debouncer = PropertyDebouncer(mock_coord, delay=5.5)
    assert custom_debouncer.delay == 5.5

    # _cancel_timer with active timer vs missing timer
    unsub = MagicMock()
    debouncer._timers["temp"] = unsub
    assert debouncer.is_active is True
    assert debouncer.has_pending("temp") is False
    debouncer._cancel_timer("temp")
    unsub.assert_called_once_with()
    assert "temp" not in debouncer._timers
    assert debouncer.is_active is False
    debouncer._cancel_timer("nonexistent")

    # has_pending & cancel_all across multiple calls
    unsub_1 = MagicMock()
    unsub_2 = MagicMock()
    debouncer._timers["p1"] = unsub_1
    debouncer._timers["p2"] = unsub_2
    debouncer._pending_payloads["p1"] = (AsyncMock(), (), {}, 0)
    debouncer._last_activities["p1"] = 42.0
    assert debouncer.is_active is True
    assert debouncer.has_pending("p1") is True

    debouncer.cancel_all()
    assert debouncer._generation == 1
    unsub_1.assert_called_once_with()
    unsub_2.assert_called_once_with()
    assert debouncer._timers == {}
    assert debouncer._pending_payloads == {}
    assert debouncer._last_activities == {}
    assert debouncer.is_active is False

    debouncer.cancel_all()
    assert debouncer._generation == 2

    # _async_handle_delayed_failure
    await debouncer._async_handle_delayed_failure("target_temp")
    mock_coord.controller.async_clear_pending_updates.assert_awaited_once_with(
        ["target_temp"]
    )
    mock_coord.async_request_refresh.assert_awaited_once_with()

    # async_execute: 1. Missing val raises ValueError
    debouncer = PropertyDebouncer(mock_coord, delay=3.0)
    with pytest.raises(
        ValueError, match="async_execute requires an explicit 'val' keyword argument."
    ):
        await debouncer.async_execute("temp", AsyncMock())

    # 2. Turn-off immediate bypasses even when inside active trailing window
    turn_off_cases: list[tuple[str, Any, bool]] = [
        (ATTR_HVAC_MODE, HVACMode.OFF, True),
        (ATTR_HVAC_MODE, "off", False),
        (ATTR_POWER, False, True),
        (ATTR_POWER, 0, True),
        (ATTR_POWER, "false", True),
        (ATTR_POWER, "FALSE", True),
        (ATTR_POWER, "off", True),
    ]
    for prop, val, expected_ret in turn_off_cases:
        debouncer._last_activities[prop] = 99.5
        stale_timer = MagicMock()
        debouncer._timers["other"] = stale_timer
        debouncer._pending_payloads["other"] = (AsyncMock(), (), {}, 0)
        gen_before = debouncer._generation
        cmd = AsyncMock(return_value=expected_ret)

        res = await debouncer.async_execute(prop, cmd, "pos1", val=val, extra_kw="kw1")
        assert res is expected_ret
        cmd.assert_awaited_once_with("pos1", extra_kw="kw1")
        stale_timer.assert_called_once_with()
        assert debouncer._generation == gen_before + 1
        assert debouncer._pending_payloads == {}
        assert debouncer._last_activities == {prop: 100.0}

    # 3. Non-turn-off commands inside trailing window MUST queue (not bypass!)
    with patch(
        "custom_components.climate_ip.coordinator.async_call_later",
        return_value=MagicMock(),
    ):
        non_off_cases: list[tuple[str, Any]] = [
            (ATTR_HVAC_MODE, HVACMode.COOL),
            (ATTR_HVAC_MODE, "cool"),
            ("target_temp", HVACMode.OFF),
            ("target_temp", "off"),
            (ATTR_POWER, True),
            (ATTR_POWER, 1),
            (ATTR_POWER, "on"),
            (ATTR_POWER, "true"),
            ("target_temp", False),
            ("target_temp", 0),
            ("target_temp", "false"),
        ]
        for prop, val in non_off_cases:
            debouncer._timers.clear()
            debouncer._pending_payloads.clear()
            debouncer._last_activities[prop] = 99.0
            cmd = AsyncMock(return_value=True)

            res = await debouncer.async_execute(prop, cmd, val=val)
            assert res is DEBOUNCE_QUEUED
            cmd.assert_not_awaited()
            assert prop in debouncer._pending_payloads

    # 4. Immediate execution when property has no prior activity or window elapsed (>= delay)
    debouncer.cancel_all()
    stale_unsub = MagicMock()
    debouncer._timers["fan_mode"] = stale_unsub
    debouncer._pending_payloads["fan_mode"] = (AsyncMock(), (), {}, 0)
    mock_coord.hass.loop.time.return_value = 200.0

    cmd_first = AsyncMock(return_value=False)
    res_first = await debouncer.async_execute(
        "fan_mode", cmd_first, "arg_a", val="high", kw="v"
    )
    assert res_first is False
    cmd_first.assert_awaited_once_with("arg_a", kw="v")
    stale_unsub.assert_called_once_with()
    assert "fan_mode" not in debouncer._pending_payloads
    assert debouncer._last_activities["fan_mode"] == 200.0

    # Exact boundary: 203.0 - 200.0 == 3.0 (>= delay -> immediate)
    mock_coord.hass.loop.time.return_value = 203.0
    cmd_boundary = AsyncMock(return_value=True)
    res_boundary = await debouncer.async_execute(
        "fan_mode", cmd_boundary, "arg_b", val="low", kw="v2"
    )
    assert res_boundary is True
    cmd_boundary.assert_awaited_once_with("arg_b", kw="v2")
    assert "fan_mode" not in debouncer._pending_payloads
    assert debouncer._last_activities["fan_mode"] == 203.0


@pytest.mark.asyncio
async def test_03_debouncer_async_execute_delayed_and_zombies() -> None:
    """Verify PropertyDebouncer queued timer firing, anti-zombie shield, and error handlers."""
    mock_coord = MagicMock()
    mock_coord.hass.loop.time.return_value = 100.0
    mock_coord.safe_unique_id = "uid_123"
    mock_coord.controller.async_clear_pending_updates = AsyncMock()
    mock_coord.async_request_refresh = AsyncMock()

    created_tasks: list[tuple[Any, Any, str]] = []

    def _capture_bg_task(hass_arg: Any, coro: Any, *, name: str) -> MagicMock:
        created_tasks.append((hass_arg, coro, name))
        return MagicMock()

    mock_coord.config_entry.async_create_background_task.side_effect = _capture_bg_task
    debouncer = PropertyDebouncer(mock_coord, delay=3.0)

    with patch(
        "custom_components.climate_ip.coordinator.async_call_later"
    ) as mock_call_later:
        unsub_handle = MagicMock()
        mock_call_later.return_value = unsub_handle

        # Seed active window + previous timer to verify _cancel_timer on rapid re-queue
        prev_timer = MagicMock()
        debouncer._timers["temp"] = prev_timer
        debouncer._last_activities["temp"] = 99.0
        mock_coord.hass.loop.time.return_value = 100.5

        cmd_ok = AsyncMock(return_value=True)
        res = await debouncer.async_execute(
            "temp", cmd_ok, "p_arg", val=22.0, kw_arg="k"
        )
        assert res is True
        prev_timer.assert_called_once_with()
        assert debouncer._last_activities["temp"] == 100.5
        assert debouncer._timers["temp"] is unsub_handle
        assert debouncer._pending_payloads["temp"] == (
            cmd_ok,
            ("p_arg",),
            {"kw_arg": "k"},
            0,
        )
        mock_call_later.assert_called_once()
        assert mock_call_later.call_args.args[0] is mock_coord.hass
        assert mock_call_later.call_args.args[1] == 3.0
        fire_cb = mock_call_later.call_args.args[2]

        # 1. Fire delayed command that returns True -> no failure revert
        mock_coord.hass.loop.time.return_value = 103.5
        fire_cb()
        assert "temp" not in debouncer._timers
        assert "temp" not in debouncer._pending_payloads
        assert debouncer._last_activities["temp"] == 103.5
        assert len(created_tasks) == 1
        hass_arg, coro, task_name = created_tasks.pop()
        assert hass_arg is mock_coord.hass
        assert task_name == f"{DOMAIN}_uid_123_debouncer_temp"
        await coro
        cmd_ok.assert_awaited_once_with("p_arg", kw_arg="k")
        mock_coord.controller.async_clear_pending_updates.assert_not_awaited()
        mock_coord.async_request_refresh.assert_not_awaited()

        # Orphan fire when payload is already popped -> no-op
        fire_cb()
        assert created_tasks == []

        # 2. Zombie task (generation incremented after _fire_delayed scheduled task)
        debouncer._last_activities["temp"] = 103.5
        cmd_zombie = AsyncMock(return_value=True)
        await debouncer.async_execute("temp", cmd_zombie, val=23.0)
        fire_zombie = mock_call_later.call_args.args[2]
        fire_zombie()
        _, zombie_coro, _ = created_tasks.pop()
        debouncer.cancel_all()
        await zombie_coro
        cmd_zombie.assert_not_awaited()

        # 3. Delayed command returns False -> triggers _async_handle_delayed_failure
        debouncer._last_activities["temp"] = 103.5
        cmd_false = AsyncMock(return_value=False)
        await debouncer.async_execute("temp", cmd_false, "x", val=24.0)
        mock_call_later.call_args.args[2]()
        _, false_coro, _ = created_tasks.pop()
        await false_coro
        mock_coord.controller.async_clear_pending_updates.assert_awaited_once_with(
            ["temp"]
        )
        mock_coord.async_request_refresh.assert_awaited_once_with()
        mock_coord.controller.async_clear_pending_updates.reset_mock()
        mock_coord.async_request_refresh.reset_mock()

        # 4. Delayed command raises network error (CannotConnect) and generic Exception (RuntimeError)
        for err in (CannotConnect("offline"), RuntimeError("boom")):
            debouncer._last_activities["temp"] = 103.5
            cmd_err = AsyncMock(side_effect=err)
            await debouncer.async_execute("temp", cmd_err, val=25.0)
            mock_call_later.call_args.args[2]()
            _, err_coro, _ = created_tasks.pop()
            await err_coro
            mock_coord.controller.async_clear_pending_updates.assert_awaited_once_with(
                ["temp"]
            )
            mock_coord.async_request_refresh.assert_awaited_once_with()
            mock_coord.controller.async_clear_pending_updates.reset_mock()
            mock_coord.async_request_refresh.reset_mock()

        # 5. config_entry is None when _fire_delayed runs -> closes coroutine cleanly
        debouncer._last_activities["temp"] = 103.5
        cmd_no_entry = AsyncMock(return_value=True)
        await debouncer.async_execute("temp", cmd_no_entry, val=26.0)
        mock_coord.config_entry = None
        mock_call_later.call_args.args[2]()
        assert created_tasks == []
        cmd_no_entry.assert_not_awaited()


def test_04_coordinator_init_polling_and_device_info(hass: Any) -> None:
    """Verify SamsungClimateCoordinator.__init__ polling interval math and DeviceInfo branches."""
    mock_ctrl = MagicMock()
    mock_ctrl.unique_id = "ac_main"
    mock_ctrl.log_prefix = "[ac_main]"
    mock_ctrl.poll = True

    with patch.object(
        SamsungClimateCoordinator, "_async_cleanup_auto_healing_issue_if_ignored"
    ) as mock_cleanup:
        # 1. Default polling (True, 60s), standalone Samsung device with valid MAC and options name override
        entry = MagicMock(
            options={CONF_NAME: "  Living Room AC  "},
            data={CONF_MAC: " aa:bb:cc:dd:ee:ff ", CONF_NAME: "Fallback Name"},
            unique_id="entry_uid",
            entry_id="entry_id",
        )
        coord = SamsungClimateCoordinator(hass, mock_ctrl, entry)
        assert coord.controller is mock_ctrl
        assert coord.devices == {}
        assert isinstance(coord.debouncer, PropertyDebouncer)
        assert coord.debouncer.coordinator is coord
        assert coord.debouncer.delay == DEFAULT_DEBOUNCE_DELAY
        assert isinstance(coord._global_network_lock, asyncio.Lock)
        assert coord.config_entry is entry
        mock_ctrl.register_token_callback.assert_called_once_with(
            coord._async_save_new_token
        )
        assert mock_ctrl.on_push_update_callback == coord.async_handle_push_update
        assert mock_ctrl.on_ssl_config_updated == coord._async_save_ssl_config
        assert mock_ctrl.request_refresh_callback == coord.async_request_refresh
        assert (
            mock_ctrl.on_connection_failed_callback == coord._async_on_connection_failed
        )
        assert mock_ctrl.on_offline_callback == coord._async_handle_persistent_offline
        assert coord.update_interval == timedelta(seconds=DEFAULT_POLL_INTERVAL)
        assert coord.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": "Living Room AC",
            "manufacturer": MANUFACTURER_SAMSUNG,
            "connections": {(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        }
        mock_cleanup.assert_called_once_with()

        # 2. String enable_polling ("True" vs "False"), interval clamping & invalid interval fallback
        entry_str_true = MagicMock(
            options={CONF_ENABLE_POLLING: "True", CONF_POLL_INTERVAL: "5"},
            data={},
        )
        coord_min = SamsungClimateCoordinator(hass, mock_ctrl, entry_str_true)
        assert coord_min.update_interval == timedelta(seconds=MIN_POLL_INTERVAL)

        entry_max = MagicMock(
            options={
                CONF_ENABLE_POLLING: "yes",
                CONF_POLL_INTERVAL: MAX_POLL_INTERVAL + 100,
            },
            data={},
        )
        coord_max = SamsungClimateCoordinator(hass, mock_ctrl, entry_max)
        assert coord_max.update_interval == timedelta(seconds=MAX_POLL_INTERVAL)

        entry_bad_int = MagicMock(
            options={CONF_ENABLE_POLLING: True, CONF_POLL_INTERVAL: "invalid"},
            data={},
        )
        coord_bad_int = SamsungClimateCoordinator(hass, mock_ctrl, entry_bad_int)
        assert coord_bad_int.update_interval == timedelta(seconds=DEFAULT_POLL_INTERVAL)

        entry_str_false = MagicMock(
            options={CONF_ENABLE_POLLING: "False", CONF_POLL_INTERVAL: 30},
            data={CONF_ENABLE_POLLING: True},
        )
        coord_off = SamsungClimateCoordinator(hass, mock_ctrl, entry_str_false)
        assert coord_off.update_interval is None

        entry_data_false = MagicMock(
            options={},
            data={CONF_ENABLE_POLLING: False, CONF_POLL_INTERVAL: 30},
        )
        coord_data_off = SamsungClimateCoordinator(hass, mock_ctrl, entry_data_false)
        assert coord_data_off.update_interval is None

        mock_ctrl.poll = False
        coord_no_poll = SamsungClimateCoordinator(hass, mock_ctrl, entry_bad_int)
        assert coord_no_poll.update_interval is None
        mock_ctrl.poll = True

        # 3. Standalone IntesisBox with whitespace options name, data name fallback, empty MAC, and malformed MAC
        entry_data_name = MagicMock(
            options={CONF_NAME: "   "},
            data={CONF_NAME: "  Data Name AC  "},
        )
        coord_data_name = SamsungClimateCoordinator(hass, mock_ctrl, entry_data_name)
        assert coord_data_name.device_info["name"] == "Data Name AC"

        entry_intesis = MagicMock(
            options={CONF_NAME: "   "},
            data={CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX, CONF_MAC: "   "},
        )
        coord_intesis = SamsungClimateCoordinator(hass, mock_ctrl, entry_intesis)
        assert coord_intesis.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": f"{DEFAULT_INTESISBOX_NAME_PREFIX} ac_main",
            "manufacturer": MANUFACTURER_INTESIS,
            "connections": set(),
        }

        entry_samsung_default = MagicMock(
            options={},
            data={CONF_MAC: "bad_mac"},
        )
        with patch(
            "custom_components.climate_ip.coordinator.dr.format_mac",
            side_effect=ValueError("bad mac"),
        ):
            coord_bad_mac = SamsungClimateCoordinator(
                hass, mock_ctrl, entry_samsung_default
            )
        assert coord_bad_mac.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": f"{DEFAULT_DEVICE_NAME_PREFIX} ac_main",
            "manufacturer": MANUFACTURER_SAMSUNG,
            "connections": set(),
        }

        # 4. Sub-device branches (with/without parent_unique_id, with/without redundant prefix, missing name/id)
        coord_sub_parent = SamsungClimateCoordinator(
            hass,
            mock_ctrl,
            entry,
            device_info={CONF_SUBDEVICE_ID: "0", CONF_NAME: "  Bedroom  "},
            parent_unique_id="gateway_uid",
        )
        assert coord_sub_parent.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": "ID 0 (Bedroom)",
            "manufacturer": MANUFACTURER_SAMSUNG,
            "via_device": (DOMAIN, "gateway_uid"),
        }

        coord_sub_redundant = SamsungClimateCoordinator(
            hass,
            mock_ctrl,
            entry,
            device_info={CONF_SUBDEVICE_ID: "0", CONF_NAME: "ID 0 (Bedroom)"},
            parent_unique_id=None,
        )
        assert coord_sub_redundant.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": "ID 0 (Bedroom)",
            "manufacturer": MANUFACTURER_SAMSUNG,
        }

        coord_sub_unnamed = SamsungClimateCoordinator(
            hass,
            mock_ctrl,
            entry,
            device_info={CONF_SUBDEVICE_ID: None, CONF_NAME: "   "},
        )
        assert coord_sub_unnamed.device_info["name"] == DEFAULT_SUBDEVICE_NAME


def test_05_coordinator_callbacks_and_auto_healing_switch() -> None:
    """Verify issue cleanup, token/SSL persistence callbacks, failure callbacks, and RAW switch."""
    hass = MagicMock()
    hass.loop.call_soon.side_effect = lambda fn, *a: fn(*a)
    entry = MagicMock(
        options={"keep": 1},
        data={
            "host": "192.168.1.10",
            CONF_TOKEN: "tok_1",
            CONF_SSL_CONFIG_KEY: {"c": 1},
        },
        unique_id="u1",
        entry_id="e1",
    )
    coord = _make_bare_coordinator(hass=hass, entry=entry)
    coord.debouncer = MagicMock()
    coord.async_set_update_error = MagicMock()

    # 1. _async_cleanup_auto_healing_issue_if_ignored
    mock_registry = MagicMock()
    with (
        patch(
            "custom_components.climate_ip.coordinator.ir.async_get",
            return_value=mock_registry,
        ) as mock_get_reg,
        patch(
            "custom_components.climate_ip.coordinator.ir.async_delete_issue"
        ) as mock_del_issue,
    ):
        # Issue missing -> no delete
        mock_registry.async_get_issue.return_value = None
        coord._async_cleanup_auto_healing_issue_if_ignored()
        mock_get_reg.assert_called_once_with(hass)
        mock_registry.async_get_issue.assert_called_once_with(
            DOMAIN, f"{ISSUE_AUTO_HEALING_RAW}_uid_default"
        )
        mock_del_issue.assert_not_called()

        # Issue present but not dismissed -> no delete
        mock_registry.async_get_issue.return_value = MagicMock(dismissed_version=None)
        coord._async_cleanup_auto_healing_issue_if_ignored()
        mock_del_issue.assert_not_called()

        # Issue present and dismissed -> deleted
        mock_registry.async_get_issue.return_value = MagicMock(
            dismissed_version="2026.10.0"
        )
        coord._async_cleanup_auto_healing_issue_if_ignored()
        mock_del_issue.assert_called_once_with(
            hass, DOMAIN, f"{ISSUE_AUTO_HEALING_RAW}_uid_default"
        )

    # 2. _async_save_new_token (same token vs new token)
    coord._async_save_new_token("tok_1")
    hass.config_entries.async_update_entry.assert_not_called()

    coord._async_save_new_token("tok_2")
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            "host": "192.168.1.10",
            CONF_TOKEN: "tok_2",
            CONF_SSL_CONFIG_KEY: {"c": 1},
        },
    )
    hass.config_entries.async_update_entry.reset_mock()

    # 3. _async_save_ssl_config (same config vs new config)
    coord._async_save_ssl_config({"c": 1})
    hass.config_entries.async_update_entry.assert_not_called()

    coord._async_save_ssl_config({"c": 2})
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            "host": "192.168.1.10",
            CONF_TOKEN: "tok_1",
            CONF_SSL_CONFIG_KEY: {"c": 2},
        },
    )
    hass.config_entries.async_update_entry.reset_mock()

    # 4. _async_on_connection_failed & _async_handle_persistent_offline
    coord._async_on_connection_failed()
    coord.debouncer.cancel_all.assert_called_once_with()
    coord.controller.clear_state_cache.assert_called_once_with()
    err_conn = coord.async_set_update_error.call_args.args[0]
    assert isinstance(err_conn, UpdateFailed)
    assert str(err_conn) == ERR_PERSISTENT_CONNECTION_FAILURE

    coord.debouncer.reset_mock()
    coord.controller.clear_state_cache.reset_mock()
    coord.async_set_update_error.reset_mock()

    coord._async_handle_persistent_offline("ARP lost")
    coord.debouncer.cancel_all.assert_called_once_with()
    coord.controller.clear_state_cache.assert_called_once_with()
    err_off = coord.async_set_update_error.call_args.args[0]
    assert isinstance(err_off, UpdateFailed)
    assert str(err_off) == f"{ERR_DEVICE_OFFLINE_PREFIX}: ARP lost"

    # 5. _async_switch_to_raw_engine (with device_info name and fallback to safe_unique_id)
    with patch(
        "custom_components.climate_ip.coordinator.ir.async_create_issue"
    ) as mock_create_issue:
        coord.device_info = {"name": "Kitchen AC"}
        coord._async_switch_to_raw_engine()
        hass.config_entries.async_update_entry.assert_called_once_with(
            entry, options={"keep": 1, CONF_CONN_METHOD: CONN_METHOD_RAW}
        )
        mock_create_issue.assert_called_once_with(
            hass,
            DOMAIN,
            f"{ISSUE_AUTO_HEALING_RAW}_uid_default",
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_AUTO_HEALING_RAW,
            translation_placeholders={"device_name": "Kitchen AC"},
            data={"device_name": "Kitchen AC"},
        )

        mock_create_issue.reset_mock()
        coord.device_info = {}
        coord._async_switch_to_raw_engine()
        mock_create_issue.assert_called_once_with(
            hass,
            DOMAIN,
            f"{ISSUE_AUTO_HEALING_RAW}_uid_default",
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_AUTO_HEALING_RAW,
            translation_placeholders={"device_name": "uid_default"},
            data={"device_name": "uid_default"},
        )


@pytest.mark.asyncio
async def test_06_coordinator_async_update_data() -> None:
    """Verify _async_update_data polling timeout, auto-healing switch, and exception translations."""
    coord = _make_bare_coordinator()
    sentinel_state = MagicMock(name="climate_state")
    coord.controller.climate_state = sentinel_state
    coord.controller.async_get_status = AsyncMock()

    # 1. Success path with timeout check
    with patch(
        "custom_components.climate_ip.coordinator.asyncio.timeout"
    ) as mock_timeout:
        mock_timeout.return_value.__aenter__ = AsyncMock()
        mock_timeout.return_value.__aexit__ = AsyncMock(return_value=None)
        res = await coord._async_update_data()
        assert res is sentinel_state
        mock_timeout.assert_called_once_with(NETWORK_POLL_TIMEOUT)
        coord.controller.async_get_status.assert_awaited_once_with()

    # 2. InvalidHeaderError when not RAW -> triggers _async_switch_to_raw_engine
    coord.config_entry.options = {CONF_CONN_METHOD: "aiohttp"}
    coord.controller.async_get_status = AsyncMock(
        side_effect=InvalidHeaderError("bad header")
    )
    with patch.object(coord, "_async_switch_to_raw_engine") as mock_switch:
        with pytest.raises(UpdateFailed, match=ERR_AUTO_HEALING_RAW_IN_PROGRESS):
            await coord._async_update_data()
        mock_switch.assert_called_once_with()

    # 3. InvalidHeaderError when already RAW -> does NOT switch, raises RAW parsing failure
    coord.config_entry.options = {CONF_CONN_METHOD: CONN_METHOD_RAW}
    with patch.object(coord, "_async_switch_to_raw_engine") as mock_switch_raw:
        with pytest.raises(
            UpdateFailed, match="Data parsing failed on RAW engine: bad header"
        ):
            await coord._async_update_data()
        mock_switch_raw.assert_not_called()

    # 4. ConfigEntryAuthFailed -> clears cache and re-raises
    coord.controller.clear_state_cache.reset_mock()
    coord.controller.async_get_status = AsyncMock(
        side_effect=ConfigEntryAuthFailed("expired")
    )
    with pytest.raises(ConfigEntryAuthFailed, match="expired"):
        await coord._async_update_data()
    coord.controller.clear_state_cache.assert_called_once_with()

    # 5. AuthError -> clears cache and raises ConfigEntryAuthFailed
    coord.controller.clear_state_cache.reset_mock()
    coord.controller.async_get_status = AsyncMock(
        side_effect=AuthError("401 unauthorized")
    )
    with pytest.raises(
        ConfigEntryAuthFailed, match="Authentication failed: 401 unauthorized"
    ):
        await coord._async_update_data()
    coord.controller.clear_state_cache.assert_called_once_with()

    # 6. UpdateFailed -> re-raises directly without clearing cache
    coord.controller.clear_state_cache.reset_mock()
    coord.controller.async_get_status = AsyncMock(
        side_effect=UpdateFailed("direct failure")
    )
    with pytest.raises(UpdateFailed, match="direct failure"):
        await coord._async_update_data()
    coord.controller.clear_state_cache.assert_not_called()

    # 7. Network errors (TimeoutError, CannotConnect, OSError), Data errors (ValueError, TypeError, KeyError), Fatal Exception
    error_matrix: list[tuple[Exception, str]] = [
        (TimeoutError("timed out"), "Network error during update: timed out"),
        (CannotConnect("refused"), "Network error during update: refused"),
        (OSError("unreach"), "Network error during update: unreach"),
        (ValueError("bad val"), "Data parsing error: bad val"),
        (TypeError("bad type"), "Data parsing error: bad type"),
        (KeyError("missing_k"), "Data parsing error: 'missing_k'"),
        (RuntimeError("unexpected"), "Fatal error: unexpected"),
    ]
    for exc, expected_msg in error_matrix:
        coord.controller.clear_state_cache.reset_mock()
        coord.controller.async_get_status = AsyncMock(side_effect=exc)
        with pytest.raises(UpdateFailed, match=expected_msg):
            await coord._async_update_data()
        coord.controller.clear_state_cache.assert_called_once_with()


@pytest.mark.asyncio
async def test_07_coordinator_async_handle_push_update() -> None:
    """Verify async_handle_push_update state merging, debounce suppression, flicker guard, and error branches."""
    coord = _make_bare_coordinator()
    coord.debouncer = PropertyDebouncer(coord)
    coord.async_set_updated_data = MagicMock()
    coord.async_set_update_error = MagicMock()
    coord.controller.async_merge_device_state = AsyncMock(return_value=True)

    # 1. new_data is None -> ignored
    await coord.async_handle_push_update(None)
    coord.controller.async_merge_device_state.assert_not_awaited()
    coord.async_set_updated_data.assert_not_called()

    # 2. Controller rejects merge (False) -> ignored
    coord.controller.async_merge_device_state.return_value = False
    await coord.async_handle_push_update({"junk": 1})
    coord.controller.async_merge_device_state.assert_awaited_once_with({"junk": 1})
    coord.async_set_updated_data.assert_not_called()

    # 3. Merge succeeds, but debouncer is active -> suppressed
    coord.controller.async_merge_device_state.return_value = True
    coord.debouncer._pending_payloads["temp"] = (AsyncMock(), (), {}, 0)
    await coord.async_handle_push_update({"power": "on"})
    coord.async_set_updated_data.assert_not_called()
    coord.debouncer._pending_payloads.clear()

    # 4. Debouncer inactive: identical state when last_update_success is True -> suppressed
    coord.controller.climate_state = "state_a"
    coord.data = "state_a"
    coord.last_update_success = True
    await coord.async_handle_push_update({"power": "on"})
    coord.async_set_updated_data.assert_not_called()

    # 5. Identical state when last_update_success is False -> broadcasts recovery!
    coord.last_update_success = False
    await coord.async_handle_push_update({"power": "on"})
    coord.async_set_updated_data.assert_called_once_with("state_a")
    coord.async_set_updated_data.reset_mock()

    # 6. Different state when last_update_success is True -> broadcasts update!
    coord.last_update_success = True
    coord.controller.climate_state = "state_b"
    await coord.async_handle_push_update({"power": "off"})
    coord.async_set_updated_data.assert_called_once_with("state_b")

    # 7. CancelledError -> re-raised cleanly
    coord.controller.async_merge_device_state.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await coord.async_handle_push_update({"power": "on"})

    # 8. AuthError / ConfigEntryAuthFailed -> clears cache, sets error, starts reauth (if config_entry present)
    for auth_exc in (AuthError("bad token"), ConfigEntryAuthFailed("expired")):
        coord.controller.clear_state_cache.reset_mock()
        coord.async_set_update_error.reset_mock()
        coord.config_entry.async_start_reauth.reset_mock()
        coord.controller.async_merge_device_state.side_effect = auth_exc

        await coord.async_handle_push_update({"power": "on"})
        coord.controller.clear_state_cache.assert_called_once_with()
        err_arg = coord.async_set_update_error.call_args.args[0]
        assert isinstance(err_arg, ConfigEntryAuthFailed)
        assert f"Authentication failed: {auth_exc}" in str(err_arg)
        coord.config_entry.async_start_reauth.assert_called_once_with(coord.hass)

    # Auth failure when config_entry is None -> does not fail
    coord.config_entry = None  # type: ignore[assignment]
    coord.controller.async_merge_device_state.side_effect = AuthError("no entry")
    await coord.async_handle_push_update({"power": "on"})

    # 9. Generic Exception -> clears cache and sets UpdateFailed
    coord.controller.clear_state_cache.reset_mock()
    coord.async_set_update_error.reset_mock()
    coord.controller.async_merge_device_state.side_effect = RuntimeError("push boom")
    await coord.async_handle_push_update({"power": "on"})
    coord.controller.clear_state_cache.assert_called_once_with()
    push_err = coord.async_set_update_error.call_args.args[0]
    assert isinstance(push_err, UpdateFailed)
    assert str(push_err) == "Push update failed: push boom"


@pytest.mark.asyncio
async def test_08_coordinator_locked_set_property() -> None:
    """Verify _locked_set_property superseding guards, lock spacing sleep, and strict bool check."""
    coord = _make_bare_coordinator()
    coord.debouncer = PropertyDebouncer(coord)
    coord.controller.is_property_superseded = MagicMock(return_value=False)
    coord.controller.async_set_property = AsyncMock(return_value=True)

    with patch(
        "custom_components.climate_ip.coordinator.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        # 1. Superseded by debouncer.has_pending
        coord.debouncer._pending_payloads["temp"] = (AsyncMock(), (), {}, 0)
        assert await coord._locked_set_property("temp", 22.0, "dev_1") is True
        coord.controller.is_property_superseded.assert_not_called()
        coord.controller.async_set_property.assert_not_awaited()
        mock_sleep.assert_not_awaited()
        coord.debouncer._pending_payloads.clear()

        # 2. Superseded by controller.is_property_superseded
        coord.controller.is_property_superseded.return_value = True
        assert await coord._locked_set_property("temp", 22.0, "dev_1") is True
        coord.controller.is_property_superseded.assert_called_once_with("temp", 22.0)
        coord.controller.async_set_property.assert_not_awaited()
        mock_sleep.assert_not_awaited()

        # 3. Normal execution returning True and False with exact hardware spacing sleep
        coord.controller.is_property_superseded.return_value = False
        assert await coord._locked_set_property("temp", 23.0, "dev_1") is True
        coord.controller.async_set_property.assert_awaited_once_with(
            "temp", 23.0, "dev_1"
        )
        mock_sleep.assert_awaited_once_with(HARDWARE_BREATHING_ROOM_SEC)

        coord.controller.async_set_property.reset_mock()
        mock_sleep.reset_mock()
        coord.controller.async_set_property.return_value = False
        assert await coord._locked_set_property("fan_mode", "low", None) is False
        coord.controller.async_set_property.assert_awaited_once_with(
            "fan_mode", "low", None
        )
        mock_sleep.assert_awaited_once_with(HARDWARE_BREATHING_ROOM_SEC)

        # 4. Non-bool return raises TypeError
        coord.controller.async_set_property.return_value = "invalid_truthy_str"
        with pytest.raises(TypeError, match="expected bool"):
            await coord._locked_set_property("fan_mode", "low")


@pytest.mark.asyncio
async def test_09_coordinator_async_set_property_and_failure_rollback() -> None:
    """Verify async_set_property prediction, Enum unwrapping, corrections, and rollback on all failure types."""
    coord = _make_bare_coordinator()
    coord.debouncer = MagicMock()
    coord.debouncer.async_execute = AsyncMock(return_value=True)
    coord.async_set_updated_data = MagicMock()
    coord.async_request_refresh = AsyncMock()
    coord.controller.async_clear_pending_updates = AsyncMock()

    existing_state = MagicMock(name="existing_state")
    predicted_state = MagicMock(name="predicted_state")
    coord.data = existing_state
    coord.controller.climate_state = predicted_state
    coord.controller.async_predict_and_correct_state = AsyncMock(
        return_value=(None, {"fan_mode": HVACMode.AUTO, "swing": "on"})
    )

    # 1. Success path with existing self.data, Enum new_value, and Enum/str corrections
    await coord.async_set_property(ATTR_HVAC_MODE, HVACMode.COOL, device_id="sub_1")
    coord.controller.async_predict_and_correct_state.assert_awaited_once_with(
        existing_state, ATTR_HVAC_MODE, "cool"
    )
    coord.async_set_updated_data.assert_called_once_with(predicted_state)
    assert coord.debouncer.async_execute.await_args_list == [
        call(
            ATTR_HVAC_MODE,
            coord._locked_set_property,
            ATTR_HVAC_MODE,
            "cool",
            "sub_1",
            val="cool",
        ),
        call(
            "fan_mode",
            coord._locked_set_property,
            "fan_mode",
            "auto",
            "sub_1",
            val="auto",
        ),
        call(
            "swing",
            coord._locked_set_property,
            "swing",
            "on",
            "sub_1",
            val="on",
        ),
    ]
    coord.async_request_refresh.assert_not_awaited()

    # 2. Fallback to _create_device_state() when self.data is None, and partial False result rollback
    coord.data = None
    coord.controller.async_predict_and_correct_state.reset_mock()
    coord.controller.async_predict_and_correct_state.return_value = (
        None,
        {"fan_mode": "high"},
    )
    coord.debouncer.async_execute = AsyncMock(side_effect=[True, False])

    with pytest.raises(
        HomeAssistantError, match="Failed to set property hvac_mode to dry"
    ):
        await coord.async_set_property(ATTR_HVAC_MODE, "dry")

    coord.controller.async_predict_and_correct_state.assert_awaited_once_with(
        predicted_state, ATTR_HVAC_MODE, "dry"
    )
    coord.debouncer.cancel_all.assert_called_once_with()
    coord.controller.async_clear_pending_updates.assert_awaited_once_with(
        [ATTR_HVAC_MODE, "fan_mode"]
    )
    coord.async_request_refresh.assert_awaited_once_with()

    # 3. CannotConnect / OSError label and host resolution fallbacks
    coord.controller.async_predict_and_correct_state.return_value = (None, {})
    label_host_cases: list[
        tuple[dict[str, Any], str | None, str | None, str | None, Exception, str]
    ] = [
        (
            {"name": "Bedroom AC"},
            "CtrlName",
            "192.168.1.50",
            "10.0.0.1",
            CannotConnect("down"),
            "Device 'Bedroom AC' (192.168.1.50) is unreachable. Check power and network connection.",
        ),
        (
            {},
            "CtrlName",
            None,
            "10.0.0.1",
            OSError("net down"),
            "Device 'CtrlName' (10.0.0.1) is unreachable. Check power and network connection.",
        ),
        (
            {},
            None,
            None,
            None,
            CannotConnect("down"),
            "Device 'uid_default' (unknown) is unreachable. Check power and network connection.",
        ),
    ]
    for dev_info, ctrl_name, ip_addr, host, exc, expected_err in label_host_cases:
        coord.device_info = dev_info
        coord.controller.name = ctrl_name
        coord.controller.ip_address = ip_addr
        coord.controller.host = host
        coord.debouncer.cancel_all.reset_mock()
        coord.controller.async_clear_pending_updates.reset_mock()
        coord.async_request_refresh.reset_mock()
        coord.debouncer.async_execute = AsyncMock(side_effect=exc)

        with pytest.raises(
            HomeAssistantError,
            match=r"^" + expected_err.replace("(", r"\(").replace(")", r"\)") + r"$",
        ):
            await coord.async_set_property("temp", 21.0)
        coord.debouncer.cancel_all.assert_called_once_with()
        coord.controller.async_clear_pending_updates.assert_awaited_once_with(["temp"])
        coord.async_request_refresh.assert_awaited_once_with()

    # 4. Data errors (ValueError, TypeError, KeyError), CancelledError, and generic Exception
    for data_exc in (ValueError("bad v"), TypeError("bad t"), KeyError("bad k")):
        coord.debouncer.cancel_all.reset_mock()
        coord.controller.async_clear_pending_updates.reset_mock()
        coord.async_request_refresh.reset_mock()
        coord.debouncer.async_execute = AsyncMock(side_effect=data_exc)
        with pytest.raises(
            HomeAssistantError, match=f"Data error setting property temp: {data_exc}"
        ):
            await coord.async_set_property("temp", 21.0)
        coord.debouncer.cancel_all.assert_called_once_with()
        coord.controller.async_clear_pending_updates.assert_awaited_once_with(["temp"])
        coord.async_request_refresh.assert_awaited_once_with()

    coord.debouncer.cancel_all.reset_mock()
    coord.controller.async_clear_pending_updates.reset_mock()
    coord.async_request_refresh.reset_mock()
    coord.debouncer.async_execute = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await coord.async_set_property("temp", 21.0)
    coord.debouncer.cancel_all.assert_called_once_with()
    coord.controller.async_clear_pending_updates.assert_awaited_once_with(["temp"])
    coord.async_request_refresh.assert_awaited_once_with()

    coord.debouncer.cancel_all.reset_mock()
    coord.controller.async_clear_pending_updates.reset_mock()
    coord.async_request_refresh.reset_mock()
    coord.debouncer.async_execute = AsyncMock(side_effect=RuntimeError("unexpected"))
    with pytest.raises(
        HomeAssistantError, match="Failed to set property temp: unexpected"
    ):
        await coord.async_set_property("temp", 21.0)
    coord.debouncer.cancel_all.assert_called_once_with()
    coord.controller.async_clear_pending_updates.assert_awaited_once_with(["temp"])
    coord.async_request_refresh.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_10_coordinator_properties_and_shutdown() -> None:
    """Verify coordinator identifier/connection properties and async_shutdown error handling."""
    coord = _make_bare_coordinator()
    coord.debouncer = MagicMock()

    # 1. log_prefix, unique_id, safe_unique_id, auto_healing_issue_id
    coord.controller.log_prefix = "[custom_prefix]"
    coord.controller.unique_id = "  ctrl.uid 1  "
    assert coord.log_prefix == "[custom_prefix]"
    assert coord.unique_id == "  ctrl.uid 1  "
    assert coord.safe_unique_id == "ctrl_uid_1"
    assert coord.auto_healing_issue_id == f"{ISSUE_AUTO_HEALING_RAW}_ctrl_uid_1"

    # Fallback when controller.unique_id is None or whitespace
    for empty_ctrl_uid in (None, "   "):
        coord.controller.unique_id = empty_ctrl_uid
        coord.config_entry.unique_id = "  entry.uid 2  "
        assert coord.safe_unique_id == "entry_uid_2"

    # Fallback when config_entry.unique_id is also None or whitespace
    for empty_entry_uid in (None, "   "):
        coord.controller.unique_id = "   "
        coord.config_entry.unique_id = empty_entry_uid
        coord.config_entry.entry_id = "  entry.id 3  "
        assert coord.safe_unique_id == "entry_id_3"

    # 2. connection_method precedence (options > data > None)
    coord.config_entry.options = {CONF_CONN_METHOD: "raw"}
    coord.config_entry.data = {CONF_CONN_METHOD: "aiohttp"}
    assert coord.connection_method == "raw"

    coord.config_entry.options = {}
    assert coord.connection_method == "aiohttp"

    coord.config_entry.data = {}
    assert coord.connection_method is None

    # 3. async_shutdown (normal, tolerated network errors, CancelledError, unexpected Exception)
    with patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.async_shutdown",
        new_callable=AsyncMock,
    ) as mock_super_shutdown:
        coord.controller.async_shutdown = AsyncMock()
        await coord.async_shutdown()
        coord.debouncer.cancel_all.assert_called_once_with()
        mock_super_shutdown.assert_awaited_once_with()
        coord.controller.async_shutdown.assert_awaited_once_with()

        for net_exc in (
            TimeoutError("timeout"),
            CannotConnect("cannot"),
            OSError("os"),
        ):
            coord.controller.async_shutdown = AsyncMock(side_effect=net_exc)
            await coord.async_shutdown()

        coord.controller.async_shutdown = AsyncMock(
            side_effect=asyncio.CancelledError()
        )
        with pytest.raises(asyncio.CancelledError):
            await coord.async_shutdown()

        coord.controller.async_shutdown = AsyncMock(
            side_effect=RuntimeError("shutdown boom")
        )
        await coord.async_shutdown()
