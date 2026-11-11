"""Unit and regression tests for Debouncer Burst & Command Coalescence.

Verifies the exact burst simulation sequence across properties:
  temp=25°C -> 24°C -> fan_only -> 22°C -> dry -> 20°C -> heat -> 18°C -> heat_cool -> 16°C -> (>=10s) -> off

Validates:
  1. Leading-edge immediate execution for the first touch of each independent property.
  2. Coalescence of rapid intermediate values in memory without dispatching to hardware.
  3. Trailing-edge consolidated execution of the final accumulated target.
  4. Immediate turn-off bypass purging all pending debounced commands.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.const import ATTR_POWER
from custom_components.climate_ip.coordinator import DEBOUNCE_QUEUED, PropertyDebouncer
from homeassistant.components.climate import HVACMode


def _make_mock_coordinator(hass: Any = None) -> MagicMock:
    """Create a mock coordinator with full debouncer harness."""
    coord = MagicMock()
    coord.hass = hass if hass is not None else MagicMock()
    coord.safe_unique_id = "uid_test_burst"
    coord.config_entry = MagicMock()
    coord.controller = MagicMock()
    coord.controller.async_clear_pending_updates = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    return coord


@pytest.mark.asyncio
async def test_01_burst_sequence_coalescence_and_metrics() -> None:
    """Verify the 11-step burst sequence coalesces down to exactly 5 wire dispatches."""
    mock_coord = _make_mock_coordinator()
    debouncer = PropertyDebouncer(mock_coord, delay=3.0)

    # Track dispatches that actually reach the "wire"
    wire_dispatches: list[tuple[str, Any]] = []

    async def _wire_sink(prop: str, val: Any) -> bool:
        wire_dispatches.append((prop, val))
        return True

    # Capture background tasks spawned by debouncer
    bg_tasks: list[tuple[str, Any]] = []

    def _capture_bg_task(hass_arg: Any, coro: Any, *, name: str) -> MagicMock:
        bg_tasks.append((name, coro))
        return MagicMock()

    mock_coord.config_entry.async_create_background_task.side_effect = _capture_bg_task

    # Mock async_call_later to capture scheduled timers
    def _mock_call_later(hass: Any, delay: float, action: Any) -> MagicMock:
        timer_handle = MagicMock()

        def _cancel() -> None:
            timer_handle.cancelled = True

        timer_handle.cancel.side_effect = _cancel
        timer_handle.cancelled = False
        timer_handle.action = action
        timer_handle.delay = delay
        return timer_handle

    current_time = 100.0
    mock_coord.hass.loop.time.side_effect = lambda: current_time

    with patch(
        "custom_components.climate_ip.coordinator.async_call_later",
        side_effect=_mock_call_later,
    ):
        # Step 1 (T+0s): temp=25°C -> Immediate execution (first of 'temperature')
        current_time = 100.0
        r1 = await debouncer.async_execute(
            "temperature", _wire_sink, "temperature", 25.0, val=25.0
        )
        assert r1 is True
        assert wire_dispatches == [("temperature", 25.0)]

        # Step 2 (T+1s): temp=24°C -> Queued into debounce
        current_time = 101.0
        r2 = await debouncer.async_execute(
            "temperature", _wire_sink, "temperature", 24.0, val=24.0
        )
        assert r2 is DEBOUNCE_QUEUED
        assert wire_dispatches == [("temperature", 25.0)]  # No new wire call
        assert debouncer.has_pending("temperature")

        # Step 3 (T+2s): mode=fan_only -> Immediate execution (first of 'hvac_mode'!)
        current_time = 102.0
        r3 = await debouncer.async_execute(
            "hvac_mode", _wire_sink, "hvac_mode", "fan_only", val="fan_only"
        )
        assert r3 is True
        assert wire_dispatches == [
            ("temperature", 25.0),
            ("hvac_mode", "fan_only"),
        ]

        # Step 4 (T+3s): temp=22°C -> Supersedes 24°C in debounce queue
        current_time = 103.0
        r4 = await debouncer.async_execute(
            "temperature", _wire_sink, "temperature", 22.0, val=22.0
        )
        assert r4 is DEBOUNCE_QUEUED
        assert debouncer._pending_payloads["temperature"][1] == ("temperature", 22.0)

        # Step 5 (T+4s): mode=dry -> Queued into debounce for hvac_mode
        current_time = 104.0
        r5 = await debouncer.async_execute(
            "hvac_mode", _wire_sink, "hvac_mode", "dry", val="dry"
        )
        assert r5 is DEBOUNCE_QUEUED
        assert debouncer.has_pending("hvac_mode")

        # Step 6 (T+5s): temp=20°C -> Supersedes 22°C
        current_time = 105.0
        r6 = await debouncer.async_execute(
            "temperature", _wire_sink, "temperature", 20.0, val=20.0
        )
        assert r6 is DEBOUNCE_QUEUED
        assert debouncer._pending_payloads["temperature"][1] == ("temperature", 20.0)

        # Step 7 (T+6s): mode=heat -> Supersedes dry
        current_time = 106.0
        r7 = await debouncer.async_execute(
            "hvac_mode", _wire_sink, "hvac_mode", "heat", val="heat"
        )
        assert r7 is DEBOUNCE_QUEUED
        assert debouncer._pending_payloads["hvac_mode"][1] == ("hvac_mode", "heat")

        # Step 8 (T+7s): temp=18°C -> Supersedes 20°C
        current_time = 107.0
        r8 = await debouncer.async_execute(
            "temperature", _wire_sink, "temperature", 18.0, val=18.0
        )
        assert r8 is DEBOUNCE_QUEUED
        assert debouncer._pending_payloads["temperature"][1] == ("temperature", 18.0)

        # Step 9 (T+8s): mode=heat_cool -> Supersedes heat
        current_time = 108.0
        r9 = await debouncer.async_execute(
            "hvac_mode", _wire_sink, "hvac_mode", "heat_cool", val="heat_cool"
        )
        assert r9 is DEBOUNCE_QUEUED
        assert debouncer._pending_payloads["hvac_mode"][1] == ("hvac_mode", "heat_cool")

        # Step 10 (T+9s): temp=16°C -> Supersedes 18°C
        current_time = 109.0
        r10 = await debouncer.async_execute(
            "temperature", _wire_sink, "temperature", 16.0, val=16.0
        )
        assert r10 is DEBOUNCE_QUEUED
        assert debouncer._pending_payloads["temperature"][1] == ("temperature", 16.0)

        # At this point, exactly 2 dispatches have occurred on the wire!
        assert len(wire_dispatches) == 2

        # Step 10b: Advance time to T+13s (> 3.0s delay after last command) and fire active timers
        current_time = 113.0
        # Fire hvac_mode timer (delayed consolidated value)
        mode_timer = debouncer._timers.get("hvac_mode")
        assert mode_timer is not None
        debouncer._timers["hvac_mode"].action()

        # Fire temperature timer (delayed consolidated value)
        temp_timer = debouncer._timers.get("temperature")
        assert temp_timer is not None
        debouncer._timers["temperature"].action()

        # Execute both background tasks
        assert len(bg_tasks) == 2
        for _, coro in bg_tasks:
            await coro

        # Exactly 4 wire dispatches now:
        # [25.0, fan_only, heat_cool, 16.0]
        assert wire_dispatches == [
            ("temperature", 25.0),
            ("hvac_mode", "fan_only"),
            ("hvac_mode", "heat_cool"),
            ("temperature", 16.0),
        ]

        # Step 11: Rest period >= 10s (T+25s) then mode=off
        current_time = 125.0
        r11 = await debouncer.async_execute(
            "hvac_mode", _wire_sink, "hvac_mode", "off", val=HVACMode.OFF
        )
        assert r11 is True

        # Total wire dispatches MUST be exactly 5!
        assert wire_dispatches == [
            ("temperature", 25.0),
            ("hvac_mode", "fan_only"),
            ("hvac_mode", "heat_cool"),
            ("temperature", 16.0),
            ("hvac_mode", "off"),
        ]

        # All queues and timers must be empty and clean
        assert debouncer.is_active is False
        assert debouncer.has_pending("temperature") is False
        assert debouncer.has_pending("hvac_mode") is False


@pytest.mark.asyncio
async def test_02_burst_in_flight_slow_bus_coalescence() -> None:
    """Verify that a slow in-flight command holds trailing payloads until wire completion."""
    mock_coord = _make_mock_coordinator()
    debouncer = PropertyDebouncer(mock_coord, delay=2.0)

    wire_calls: list[float] = []
    wire_event = asyncio.Event()

    async def _slow_wire_command(val: float) -> bool:
        wire_calls.append(val)
        await wire_event.wait()
        return True

    current_time = 50.0
    mock_coord.hass.loop.time.side_effect = lambda: current_time

    # Background task capture for flushed payload
    bg_tasks: list[Any] = []
    mock_coord.config_entry.async_create_background_task.side_effect = (
        lambda hass, coro, name: bg_tasks.append(coro)
    )

    with patch(
        "custom_components.climate_ip.coordinator.async_call_later"
    ) as mock_call_later:
        mock_timer_unsub = MagicMock()
        mock_call_later.return_value = mock_timer_unsub

        # Spawn first slow command on wire
        t1 = asyncio.create_task(
            debouncer.async_execute("temperature", _slow_wire_command, 25.0, val=25.0)
        )
        await asyncio.sleep(0)

        assert "temperature" in debouncer._in_flight
        assert wire_calls == [25.0]

        # While in-flight, rapid commands arrive
        current_time = 50.5
        r2 = await debouncer.async_execute(
            "temperature", _slow_wire_command, 24.0, val=24.0
        )
        assert r2 is DEBOUNCE_QUEUED

        current_time = 51.0
        r3 = await debouncer.async_execute(
            "temperature", _slow_wire_command, 22.0, val=22.0
        )
        assert r3 is DEBOUNCE_QUEUED

        current_time = 51.5
        r4 = await debouncer.async_execute(
            "temperature", _slow_wire_command, 16.0, val=16.0
        )
        assert r4 is DEBOUNCE_QUEUED

        # Only 16.0 is held in _pending_payloads
        assert debouncer._pending_payloads["temperature"][1] == (16.0,)

        # Timer callback captured from async_call_later
        timer_cb = mock_call_later.call_args.args[2]

        # Timer expires while slow wire is still running
        current_time = 54.0
        # Fire timer callback: noticing in-flight, it holds payload
        timer_cb()
        # Payload must still be held because property is in_flight!
        assert "temperature" in debouncer._pending_payloads
        assert "temperature" not in debouncer._timers
        assert len(bg_tasks) == 0

        # Now wire completes
        wire_event.set()
        await t1

        # Flushed payload is popped and spawned as new in-flight background task
        assert len(bg_tasks) == 1
        assert "temperature" in debouncer._in_flight
        assert debouncer.has_pending("temperature") is False

        # Run flushed task (wire_event is already set)
        await bg_tasks[0]
        assert wire_calls == [25.0, 16.0]
        assert "temperature" not in debouncer._in_flight
        assert debouncer.is_active is False


@pytest.mark.asyncio
async def test_03_burst_mid_stream_turn_off_purges_everything() -> None:
    """Verify that an immediate turn-off in the middle of a burst purges all pending targets."""
    mock_coord = _make_mock_coordinator()
    debouncer = PropertyDebouncer(mock_coord, delay=3.0)

    wire_calls: list[tuple[str, Any]] = []

    async def _wire_command(prop: str, val: Any) -> bool:
        wire_calls.append((prop, val))
        return True

    current_time = 200.0
    mock_coord.hass.loop.time.side_effect = lambda: current_time

    # Send first temp
    await debouncer.async_execute(
        "temperature", _wire_command, "temperature", 25.0, val=25.0
    )

    # Queue rapid changes for temp and mode
    current_time = 201.0
    await debouncer.async_execute(
        "temperature", _wire_command, "temperature", 24.0, val=24.0
    )
    await debouncer.async_execute(
        "hvac_mode", _wire_command, "hvac_mode", "cool", val="cool"
    )

    current_time = 201.5
    await debouncer.async_execute(
        "temperature", _wire_command, "temperature", 22.0, val=22.0
    )
    await debouncer.async_execute(
        "hvac_mode", _wire_command, "hvac_mode", "dry", val="dry"
    )

    assert debouncer.has_pending("temperature")
    assert debouncer.has_pending("hvac_mode")

    gen_before = debouncer._generation

    # User abruptly turns off the AC
    current_time = 202.0
    r_off = await debouncer.async_execute(
        ATTR_POWER, _wire_command, ATTR_POWER, 0, val=0
    )
    assert r_off is True

    # Generation must increment and all queues must be poisoned & cleared
    assert debouncer._generation == gen_before + 1
    assert debouncer.has_pending("temperature") is False
    assert debouncer.has_pending("hvac_mode") is False
    assert len(debouncer._timers) == 0

    # Only 25.0 and the turn-off command reached the wire!
    assert wire_calls == [
        ("temperature", 25.0),
        ("hvac_mode", "cool"),  # cool was first of hvac_mode
        (ATTR_POWER, 0),  # immediate turn-off
    ]
