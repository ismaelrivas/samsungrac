"""Unit tests for SamsungClimateCoordinator and PropertyDebouncer (coordinator.py)."""

import asyncio
from collections.abc import Callable, Iterator
from datetime import timedelta
import logging
from typing import Any
from unittest.mock import patch

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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed


@pytest.fixture(autouse=True)
def auto_clear_yaml_cache() -> None:
    """No-op override of yaml cache fixture for isolated coordinator unit tests."""
    return


@pytest.fixture(autouse=True)
def force_task_cancellation() -> None:
    """No-op override of async teardown fixture; event_loop handles task cleanup."""
    return


@pytest.fixture(autouse=True)
def auto_mock_network() -> None:
    """No-op override of network patch fixture for isolated coordinator unit tests."""
    return


@pytest.fixture(autouse=True)
def ruthless_aiohttp_teardown() -> None:
    """No-op override of aiohttp teardown fixture for isolated coordinator unit tests."""
    return


@pytest.fixture(autouse=True)
def block_unmocked_network_io() -> None:
    """No-op override of global network monkeypatch for isolated coordinator tests."""
    return


@pytest.fixture(autouse=True)
def _silence_coordinator_logger() -> Iterator[None]:
    """Skip expensive traceback formatting in non-log coordinator tests."""
    logger = logging.getLogger("custom_components.climate_ip.coordinator")
    prev_level = logger.level
    logger.setLevel(logging.CRITICAL + 1)
    try:
        yield
    finally:
        logger.setLevel(prev_level)


class _StubLoop:
    """Lightweight event loop double supporting time() and immediate call_soon()."""

    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def time(self) -> float:
        return self.now

    def call_soon(self, callback: Callable[..., Any], *args: Any) -> None:
        callback(*args)


class _StubConfigEntries:
    """Lightweight config_entries manager recording async_update_entry calls."""

    def __init__(self) -> None:
        self.updates: list[
            tuple[Any, dict[str, Any] | None, dict[str, Any] | None]
        ] = []

    def async_update_entry(
        self,
        entry: Any,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.updates.append((entry, data, options))


class _StubHass:
    """Minimal in-memory HomeAssistant double."""

    def __init__(self, now: float = 100.0) -> None:
        self.loop = _StubLoop(now)
        self.config_entries = _StubConfigEntries()


class _StubEntry:
    """Minimal in-memory ConfigEntry double."""

    def __init__(
        self,
        *,
        options: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        unique_id: str | None = "entry_uid",
        entry_id: str = "entry_id",
    ) -> None:
        self.options: dict[str, Any] = {} if options is None else options
        self.data: dict[str, Any] = {} if data is None else data
        self.unique_id = unique_id
        self.entry_id = entry_id
        self.unload_callbacks: list[Any] = []
        self.bg_tasks: list[tuple[Any, Any, str]] = []
        self.reauth_calls: list[Any] = []

    def async_on_unload(self, func: Any) -> None:
        self.unload_callbacks.append(func)

    def async_create_background_task(self, hass: Any, coro: Any, *, name: str) -> str:
        self.bg_tasks.append((hass, coro, name))
        return "bg_task"

    def async_start_reauth(self, hass: Any) -> None:
        self.reauth_calls.append(hass)


class _StubController:
    """Minimal in-memory ControllerInterface double with explicit typed attributes."""

    def __init__(self) -> None:
        self.unique_id: str | None = "uid_default"
        self.log_prefix = "[uid_default]"
        self.poll = True
        self.climate_state: Any = None
        self.name: str | None = None
        self.ip_address: str | None = None
        self.host: str | None = None
        self.on_push_update_callback: Any = None
        self.on_ssl_config_updated: Any = None
        self.request_refresh_callback: Any = None
        self.on_connection_failed_callback: Any = None
        self.on_offline_callback: Any = None
        self.token_callbacks: list[Any] = []
        self.clear_cache_calls = 0
        self.superseded_calls: list[tuple[str, Any]] = []
        self.superseded_result = False
        self.get_status_calls = 0
        self.get_status_exc: BaseException | None = None
        self.merge_calls: list[dict[str, Any]] = []
        self.merge_result = True
        self.merge_exc: BaseException | None = None
        self.set_prop_calls: list[tuple[str, Any, str | None]] = []
        self.set_prop_result: Any = True
        self.predict_calls: list[tuple[Any, str, Any]] = []
        self.predict_corrections: dict[str, Any] = {}
        self.cleared_pending: list[list[str]] = []
        self.shutdown_calls = 0
        self.shutdown_exc: BaseException | None = None

    def register_token_callback(self, callback: Any) -> None:
        self.token_callbacks.append(callback)

    def clear_state_cache(self) -> None:
        self.clear_cache_calls += 1

    def is_property_superseded(self, prop: str, val: Any) -> bool:
        self.superseded_calls.append((prop, val))
        return self.superseded_result

    async def async_get_status(self) -> None:
        self.get_status_calls += 1
        if self.get_status_exc is not None:
            raise self.get_status_exc

    async def async_merge_device_state(self, data: dict[str, Any]) -> bool:
        self.merge_calls.append(data)
        if self.merge_exc is not None:
            raise self.merge_exc
        return self.merge_result

    async def async_set_property(
        self, prop: str, val: Any, device_id: str | None = None
    ) -> Any:
        self.set_prop_calls.append((prop, val, device_id))
        return self.set_prop_result

    async def async_predict_and_correct_state(
        self, state: Any, prop: str, val: Any
    ) -> tuple[None, dict[str, Any]]:
        self.predict_calls.append((state, prop, val))
        return None, self.predict_corrections

    async def async_clear_pending_updates(self, props: list[str]) -> None:
        self.cleared_pending.append(props)

    async def async_shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.shutdown_exc is not None:
            raise self.shutdown_exc


class _StubDebouncer:
    """Lightweight debouncer double for coordinator command tests."""

    def __init__(self) -> None:
        self.cancel_calls = 0
        self.execute_calls: list[tuple[str, Any, tuple[Any, ...], dict[str, Any]]] = []
        self.outcomes: list[Any] = []

    def cancel_all(self) -> None:
        self.cancel_calls += 1

    async def async_execute(
        self, prop: str, func: Any, *args: Any, **kwargs: Any
    ) -> Any:
        self.execute_calls.append((prop, func, args, kwargs))
        outcome = self.outcomes.pop(0) if self.outcomes else True
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _StubDebouncerCoord:
    """Lightweight coordinator double for PropertyDebouncer unit tests."""

    def __init__(self, now: float = 100.0) -> None:
        self.hass = _StubHass(now)
        self.safe_unique_id = "uid_123"
        self.config_entry: _StubEntry | None = _StubEntry()
        self.controller = _StubController()
        self.refresh_calls = 0

    async def async_request_refresh(self) -> None:
        self.refresh_calls += 1


class _StubCmd:
    """Fast async command recorder replacing AsyncMock in debouncer loops."""

    def __init__(self, result: bool = True, exc: BaseException | None = None) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> bool:
        self.calls.append((args, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.result


class _StubTimer:
    """Fast timer unsubscribe recorder replacing MagicMock."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


class _StubTimeout:
    """Lightweight asyncio.timeout context manager double."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, delay: float) -> _StubTimeout:
        self.delays.append(delay)
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _LogCapture(logging.Handler):
    """Lightweight in-memory log handler avoiding caplog fixture overhead."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class _StubIssue:
    """Minimal issue object with dismissed_version attribute."""

    def __init__(self, dismissed_version: str | None) -> None:
        self.dismissed_version = dismissed_version


class _StubRegistry:
    """Minimal issue registry double."""

    def __init__(self) -> None:
        self.issue: _StubIssue | None = None
        self.queries: list[tuple[str, str]] = []

    def async_get_issue(self, domain: str, issue_id: str) -> _StubIssue | None:
        self.queries.append((domain, issue_id))
        return self.issue


def _make_bare_coordinator(
    hass: _StubHass | None = None,
    controller: _StubController | None = None,
    entry: _StubEntry | None = None,
) -> SamsungClimateCoordinator:
    """Create a bare SamsungClimateCoordinator without invoking __init__."""
    coord: SamsungClimateCoordinator = object.__new__(SamsungClimateCoordinator)
    coord.hass = hass if hass is not None else _StubHass()  # type: ignore[assignment]
    coord.controller = controller if controller is not None else _StubController()  # type: ignore[assignment]
    coord.config_entry = entry if entry is not None else _StubEntry()  # type: ignore[assignment]
    coord.devices = {}
    coord._global_network_lock = asyncio.Lock()
    coord.device_info = {"name": "Test AC"}
    coord.data = None  # type: ignore[assignment]
    coord.last_update_success = True
    return coord


async def test_01_debouncer_primitives_immediate_and_turn_off() -> None:
    """Verify PropertyDebouncer init, helpers, validation, turn-off bypasses, and window boundaries."""
    coord = _StubDebouncerCoord(now=100.0)
    debouncer = PropertyDebouncer(coord)  # type: ignore[arg-type]
    assert debouncer.coordinator is coord
    assert debouncer.delay == DEFAULT_DEBOUNCE_DELAY
    assert debouncer.hass is coord.hass
    assert debouncer._timers == {}
    assert debouncer._pending_payloads == {}
    assert debouncer._last_activities == {}
    assert debouncer._generation == 0
    assert debouncer.is_active is False
    assert debouncer.has_pending("temp") is False

    custom_debouncer = PropertyDebouncer(coord, delay=5.5)  # type: ignore[arg-type]
    assert custom_debouncer.delay == 5.5

    # _cancel_timer with active timer vs missing timer
    unsub = _StubTimer()
    debouncer._timers["temp"] = unsub
    assert debouncer.is_active is True
    assert debouncer.has_pending("temp") is False
    debouncer._cancel_timer("temp")
    assert unsub.calls == 1
    assert "temp" not in debouncer._timers
    assert debouncer.is_active is False
    debouncer._cancel_timer("nonexistent")

    # is_active solo branches (_pending_payloads alone and _in_flight alone)
    debouncer._pending_payloads["temp"] = (_StubCmd(), (), {}, 0)
    assert debouncer.is_active is True
    debouncer._pending_payloads.clear()
    assert debouncer.is_active is False

    debouncer._in_flight.add("temp")
    assert debouncer.is_active is True
    debouncer._in_flight.clear()
    assert debouncer.is_active is False

    # has_pending & cancel_all across multiple calls
    unsub_1 = _StubTimer()
    unsub_2 = _StubTimer()
    debouncer._timers["p1"] = unsub_1
    debouncer._timers["p2"] = unsub_2
    debouncer._pending_payloads["p1"] = (_StubCmd(), (), {}, 0)
    debouncer._last_activities["p1"] = 42.0
    assert debouncer.is_active is True
    assert debouncer.has_pending("p1") is True

    debouncer.cancel_all()
    assert debouncer._generation == 1
    assert unsub_1.calls == 1
    assert unsub_2.calls == 1
    assert debouncer._timers == {}
    assert debouncer._pending_payloads == {}
    assert debouncer._last_activities == {}
    assert debouncer.is_active is False

    debouncer.cancel_all()
    assert debouncer._generation == 2

    # _async_handle_delayed_failure
    await debouncer._async_handle_delayed_failure("target_temp")
    assert coord.controller.cleared_pending == [["target_temp"]]
    assert coord.refresh_calls == 1

    # async_execute: 1. Missing val raises ValueError
    debouncer = PropertyDebouncer(coord, delay=3.0)  # type: ignore[arg-type]
    with pytest.raises(
        ValueError, match="async_execute requires an explicit 'val' keyword argument."
    ):
        await debouncer.async_execute("temp", _StubCmd())

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
    dummy_pending = (_StubCmd(), (), {}, 0)
    for prop, val, expected_ret in turn_off_cases:
        debouncer._last_activities[prop] = 99.5
        stale_timer = _StubTimer()
        debouncer._timers["other"] = stale_timer
        debouncer._pending_payloads["other"] = dummy_pending
        gen_before = debouncer._generation
        cmd = _StubCmd(result=expected_ret)

        res = await debouncer.async_execute(prop, cmd, "pos1", val=val, extra_kw="kw1")
        assert res is expected_ret
        assert cmd.calls == [(("pos1",), {"extra_kw": "kw1"})]
        assert stale_timer.calls == 1
        assert debouncer._generation == gen_before + 1
        assert debouncer._pending_payloads == {}
        assert debouncer._last_activities == {prop: 100.0}

    # 3. Non-turn-off commands inside trailing window MUST queue (not bypass)
    def _fake_call_later(_hass: Any, _delay: float, _cb: Any) -> _StubTimer:
        return _StubTimer()

    with patch(
        "custom_components.climate_ip.coordinator.async_call_later",
        new=_fake_call_later,
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
            cmd = _StubCmd(result=True)

            res = await debouncer.async_execute(prop, cmd, val=val)
            assert res is DEBOUNCE_QUEUED
            assert cmd.calls == []
            assert prop in debouncer._pending_payloads

    # 4. Immediate execution when property has no prior activity or window elapsed (>= delay)
    debouncer.cancel_all()
    stale_unsub = _StubTimer()
    debouncer._timers["fan_mode"] = stale_unsub
    debouncer._pending_payloads["fan_mode"] = dummy_pending
    coord.hass.loop.now = 200.0

    cmd_first = _StubCmd(result=False)
    res_first = await debouncer.async_execute(
        "fan_mode", cmd_first, "arg_a", val="high", kw="v"
    )
    assert res_first is False
    assert cmd_first.calls == [(("arg_a",), {"kw": "v"})]
    assert stale_unsub.calls == 1
    assert "fan_mode" not in debouncer._pending_payloads
    assert debouncer._last_activities["fan_mode"] == 200.0

    # Exact boundary: 203.0 - 200.0 == 3.0 (>= delay -> immediate)
    coord.hass.loop.now = 203.0
    cmd_boundary = _StubCmd(result=True)
    res_boundary = await debouncer.async_execute(
        "fan_mode", cmd_boundary, "arg_b", val="low", kw="v2"
    )
    assert res_boundary is True
    assert cmd_boundary.calls == [(("arg_b",), {"kw": "v2"})]
    assert "fan_mode" not in debouncer._pending_payloads
    assert debouncer._last_activities["fan_mode"] == 203.0


async def test_02_debouncer_in_flight_completion_and_burst_coalescence() -> None:
    """Verify in-flight completion truth table, superseded queue, and multi-property burst coalescence."""
    coord = _StubDebouncerCoord(now=100.0)
    debouncer = PropertyDebouncer(coord, delay=3.0)  # type: ignore[arg-type]

    # 1. _on_in_flight_completed generation mismatch vs match & truth table
    debouncer._generation = 10
    debouncer._last_activities["temp"] = 50.0
    debouncer._in_flight.add("temp")
    pending_cmd = _StubCmd()
    debouncer._pending_payloads["temp"] = (pending_cmd, (), {}, 10)

    dispatch_calls: list[str] = []

    def _record_dispatch(prop: str) -> None:
        dispatch_calls.append(prop)

    with patch.object(debouncer, "_dispatch_pending_payload", new=_record_dispatch):
        # 1A: Generation mismatch
        debouncer._on_in_flight_completed("temp", captured_generation=9)
        assert "temp" not in debouncer._in_flight
        assert debouncer._last_activities["temp"] == 50.0
        assert "temp" in debouncer._pending_payloads
        assert dispatch_calls == []

        # 1B: Generation match while timer still ticking
        debouncer._in_flight.add("temp")
        coord.hass.loop.now = 110.0
        debouncer._timers["temp"] = _StubTimer()
        debouncer._on_in_flight_completed("temp", captured_generation=10)
        assert "temp" not in debouncer._in_flight
        assert debouncer._last_activities["temp"] == 110.0
        assert dispatch_calls == []

        # 2. Truth table for "if prop in self._pending_payloads and prop not in self._timers:"
        debouncer._generation = 1

        # Case A: in _pending_payloads AND in _timers
        debouncer._pending_payloads["temp"] = (pending_cmd, (), {}, 1)
        debouncer._timers["temp"] = _StubTimer()
        debouncer._in_flight.add("temp")
        debouncer._on_in_flight_completed("temp", 1)
        assert dispatch_calls == []
        assert "temp" in debouncer._pending_payloads

        # Case B: NOT in _pending_payloads AND NOT in _timers
        debouncer._pending_payloads.clear()
        debouncer._timers.clear()
        debouncer._in_flight.add("temp")
        debouncer._on_in_flight_completed("temp", 1)
        assert dispatch_calls == []

        # Case C: in _pending_payloads AND NOT in _timers (timer expired during flight)
        debouncer._pending_payloads["temp"] = (pending_cmd, (), {}, 1)
        debouncer._timers.clear()
        debouncer._in_flight.add("temp")
        debouncer._on_in_flight_completed("temp", 1)
        assert dispatch_calls == ["temp"]
        dispatch_calls.clear()

        # Case D: NOT in _pending_payloads AND in _timers
        debouncer._pending_payloads.clear()
        debouncer._timers["temp"] = _StubTimer()
        debouncer._in_flight.add("temp")
        debouncer._on_in_flight_completed("temp", 1)
        assert dispatch_calls == []

    # 3. End-to-end slow in-flight coalescence and superseded queue
    debouncer.cancel_all()
    assert coord.config_entry is not None
    coord.config_entry.bg_tasks.clear()
    timer_callbacks: list[Callable[[], None]] = []

    def _capture_call_later(_hass: Any, _delay: float, cb: Any) -> _StubTimer:
        timer_callbacks.append(cb)
        return _StubTimer()

    coord_logger = logging.getLogger("custom_components.climate_ip.coordinator")
    log_cap = _LogCapture()
    prev_level = coord_logger.level
    coord_logger.setLevel(logging.DEBUG)
    coord_logger.addHandler(log_cap)
    try:
        with patch(
            "custom_components.climate_ip.coordinator.async_call_later",
            new=_capture_call_later,
        ):
            coord.hass.loop.now = 200.0
            event_wire = asyncio.Event()

            async def _wire_command(*_args: Any, **_kwargs: Any) -> bool:
                await event_wire.wait()
                return True

            task1 = asyncio.create_task(
                debouncer.async_execute("fan_mode", _wire_command, val="low")
            )
            await asyncio.sleep(0)
            assert "fan_mode" in debouncer._in_flight
            assert "fan_mode" not in debouncer._pending_payloads

            cmd_queued1 = _StubCmd(result=True)
            res_q1 = await debouncer.async_execute(
                "fan_mode", cmd_queued1, "arg1", val="medium"
            )
            assert res_q1 is DEBOUNCE_QUEUED
            assert "fan_mode" in debouncer._pending_payloads
            assert not any(
                "[Debouncer] Command for 'fan_mode' was superseded" in msg
                for msg in log_cap.messages
            )

            cmd_queued2 = _StubCmd(result=True)
            res_q2 = await debouncer.async_execute(
                "fan_mode", cmd_queued2, "arg2", val="high"
            )
            assert res_q2 is DEBOUNCE_QUEUED
            assert any(
                "[Debouncer] Command for 'fan_mode' was superseded in debounce queue by new value=high"
                in msg
                for msg in log_cap.messages
            )
            queued_payload = debouncer._pending_payloads["fan_mode"]
            assert queued_payload[0] is cmd_queued2
            assert queued_payload[1] == ("arg2",)

            # Timer fires while fan_mode is STILL in-flight -> holds payload
            timer_callbacks[-1]()
            assert "fan_mode" not in debouncer._timers
            assert "fan_mode" in debouncer._pending_payloads
            assert any(
                "[Debouncer] Timer expired for 'fan_mode' while previous command is still in-flight; holding payload for coalescence"
                in msg
                for msg in log_cap.messages
            )
            assert coord.config_entry.bg_tasks == []

            # Wire command finishes -> flushes held payload
            event_wire.set()
            await task1
            assert "fan_mode" in debouncer._in_flight
            assert "fan_mode" not in debouncer._pending_payloads
            assert len(coord.config_entry.bg_tasks) == 1
            _, bg_coro, bg_name = coord.config_entry.bg_tasks.pop()
            assert bg_name == f"{DOMAIN}_uid_123_debouncer_fan_mode"
            await bg_coro
            assert "fan_mode" not in debouncer._in_flight
            assert cmd_queued2.calls == [(("arg2",), {})]
            assert cmd_queued1.calls == []
    finally:
        coord_logger.removeHandler(log_cap)
        coord_logger.setLevel(prev_level)

    # 4. Multi-property burst coalescence & mid-stream turn-off purge
    debouncer.cancel_all()
    coord.config_entry.bg_tasks.clear()
    wire_dispatches: list[tuple[str, Any]] = []
    prop_timers: dict[str, Callable[[], None]] = {}

    async def _wire_sink(prop: str, val: Any) -> bool:
        wire_dispatches.append((prop, val))
        return True

    def _capture_prop_timer(_hass: Any, _delay: float, cb: Any) -> _StubTimer:
        prop_timers[f"t{len(prop_timers)}"] = cb
        return _StubTimer()

    with patch(
        "custom_components.climate_ip.coordinator.async_call_later",
        new=_capture_prop_timer,
    ):
        burst_steps: list[tuple[float, str, Any, Any]] = [
            (300.0, "temperature", 25.0, True),
            (301.0, "temperature", 24.0, DEBOUNCE_QUEUED),
            (302.0, "hvac_mode", "fan_only", True),
            (303.0, "temperature", 22.0, DEBOUNCE_QUEUED),
            (304.0, "hvac_mode", "dry", DEBOUNCE_QUEUED),
            (305.0, "temperature", 20.0, DEBOUNCE_QUEUED),
            (306.0, "hvac_mode", "heat", DEBOUNCE_QUEUED),
            (307.0, "temperature", 18.0, DEBOUNCE_QUEUED),
            (308.0, "hvac_mode", "heat_cool", DEBOUNCE_QUEUED),
            (309.0, "temperature", 16.0, DEBOUNCE_QUEUED),
        ]
        for ts, prop, val, expected in burst_steps:
            coord.hass.loop.now = ts
            assert (
                await debouncer.async_execute(prop, _wire_sink, prop, val, val=val)
                is expected
            )
        assert len(wire_dispatches) == 2

        coord.hass.loop.now = 313.0
        # Last two scheduled callbacks belong to hvac_mode (308.0) and temperature (309.0)
        cb_list = list(prop_timers.values())
        cb_list[-2]()
        cb_list[-1]()
        assert len(coord.config_entry.bg_tasks) == 2
        for _, coro, _ in coord.config_entry.bg_tasks:
            await coro
        coord.config_entry.bg_tasks.clear()

        coord.hass.loop.now = 325.0
        assert (
            await debouncer.async_execute(
                "hvac_mode", _wire_sink, "hvac_mode", "off", val=HVACMode.OFF
            )
            is True
        )
        assert wire_dispatches == [
            ("temperature", 25.0),
            ("hvac_mode", "fan_only"),
            ("hvac_mode", "heat_cool"),
            ("temperature", 16.0),
            ("hvac_mode", "off"),
        ]
        assert debouncer.is_active is False

        # Mid-stream turn-off purges multiple queued properties simultaneously
        coord.hass.loop.now = 400.0
        await debouncer.async_execute(
            "temperature", _wire_sink, "temperature", 25.0, val=25.0
        )
        coord.hass.loop.now = 401.0
        await debouncer.async_execute(
            "temperature", _wire_sink, "temperature", 22.0, val=22.0
        )
        await debouncer.async_execute(
            "hvac_mode", _wire_sink, "hvac_mode", "cool", val="cool"
        )
        await debouncer.async_execute(
            "hvac_mode", _wire_sink, "hvac_mode", "dry", val="dry"
        )
        assert debouncer.has_pending("temperature") is True
        assert debouncer.has_pending("hvac_mode") is True
        gen_before = debouncer._generation
        coord.hass.loop.now = 402.0
        assert (
            await debouncer.async_execute(ATTR_POWER, _wire_sink, ATTR_POWER, 0, val=0)
            is True
        )
        assert debouncer._generation == gen_before + 1
        assert debouncer.has_pending("temperature") is False
        assert debouncer.has_pending("hvac_mode") is False
        assert debouncer._timers == {}


async def test_03_debouncer_async_execute_delayed_and_zombies() -> None:
    """Verify PropertyDebouncer queued timer firing, anti-zombie shield, and error handlers."""
    coord = _StubDebouncerCoord(now=100.0)
    assert coord.config_entry is not None
    debouncer = PropertyDebouncer(coord, delay=3.0)  # type: ignore[arg-type]

    timer_calls: list[tuple[Any, float, Any]] = []
    unsub_handle = _StubTimer()

    def _capture_call_later(hass_arg: Any, delay_arg: float, cb: Any) -> _StubTimer:
        timer_calls.append((hass_arg, delay_arg, cb))
        return unsub_handle

    with patch(
        "custom_components.climate_ip.coordinator.async_call_later",
        new=_capture_call_later,
    ):
        # Seed active window + previous timer to verify _cancel_timer on rapid re-queue
        prev_timer = _StubTimer()
        debouncer._timers["temp"] = prev_timer
        debouncer._last_activities["temp"] = 99.0
        coord.hass.loop.now = 100.5

        cmd_ok = _StubCmd(result=True)
        res = await debouncer.async_execute(
            "temp", cmd_ok, "p_arg", val=22.0, kw_arg="k"
        )
        assert res is True
        assert prev_timer.calls == 1
        assert debouncer._last_activities["temp"] == 100.5
        assert debouncer._timers["temp"] is unsub_handle
        assert debouncer._pending_payloads["temp"] == (
            cmd_ok,
            ("p_arg",),
            {"kw_arg": "k"},
            0,
        )
        assert len(timer_calls) == 1
        assert timer_calls[0][0] is coord.hass
        assert timer_calls[0][1] == 3.0
        fire_cb = timer_calls[0][2]

        # 1. Fire delayed command that returns True -> no failure revert
        coord.hass.loop.now = 103.5
        fire_cb()
        assert "temp" not in debouncer._timers
        assert "temp" not in debouncer._pending_payloads
        assert debouncer._last_activities["temp"] == 103.5
        assert len(coord.config_entry.bg_tasks) == 1
        hass_arg, coro, task_name = coord.config_entry.bg_tasks.pop()
        assert hass_arg is coord.hass
        assert task_name == f"{DOMAIN}_uid_123_debouncer_temp"
        await coro
        assert cmd_ok.calls == [(("p_arg",), {"kw_arg": "k"})]
        assert coord.controller.cleared_pending == []
        assert coord.refresh_calls == 0

        # Orphan fire when payload is already popped -> no-op
        fire_cb()
        assert coord.config_entry.bg_tasks == []

        # 2. Zombie task (generation incremented after _fire_delayed scheduled task)
        debouncer._last_activities["temp"] = 103.5
        cmd_zombie = _StubCmd(result=True)
        await debouncer.async_execute("temp", cmd_zombie, val=23.0)
        timer_calls[-1][2]()
        _, zombie_coro, _ = coord.config_entry.bg_tasks.pop()
        debouncer.cancel_all()
        await zombie_coro
        assert cmd_zombie.calls == []
        assert "temp" not in debouncer._last_activities

        # 3. Delayed command returns False -> triggers _async_handle_delayed_failure
        debouncer._last_activities["temp"] = 103.5
        cmd_false = _StubCmd(result=False)
        await debouncer.async_execute("temp", cmd_false, "x", val=24.0)
        timer_calls[-1][2]()
        _, false_coro, _ = coord.config_entry.bg_tasks.pop()
        await false_coro
        assert coord.controller.cleared_pending == [["temp"]]
        assert coord.refresh_calls == 1
        coord.controller.cleared_pending.clear()
        coord.refresh_calls = 0

        # 4. Delayed command raises CannotConnect and RuntimeError
        for err in (CannotConnect("offline"), RuntimeError("boom")):
            debouncer._last_activities["temp"] = 103.5
            cmd_err = _StubCmd(exc=err)
            await debouncer.async_execute("temp", cmd_err, val=25.0)
            timer_calls[-1][2]()
            _, err_coro, _ = coord.config_entry.bg_tasks.pop()
            await err_coro
            assert coord.controller.cleared_pending == [["temp"]]
            assert coord.refresh_calls == 1
            coord.controller.cleared_pending.clear()
            coord.refresh_calls = 0

        # 5. config_entry is None when _fire_delayed runs -> closes coroutine cleanly
        debouncer._last_activities["temp"] = 103.5
        cmd_no_entry = _StubCmd(result=True)
        await debouncer.async_execute("temp", cmd_no_entry, val=26.0)
        saved_entry = coord.config_entry
        coord.config_entry = None
        timer_calls[-1][2]()
        assert saved_entry.bg_tasks == []
        assert cmd_no_entry.calls == []


def test_04_coordinator_init_polling() -> None:
    """Verify SamsungClimateCoordinator.__init__ callback wiring and polling interval math."""
    hass = _StubHass()
    ctrl = _StubController()
    ctrl.unique_id = "ac_main"
    ctrl.log_prefix = "[ac_main]"
    cleanup_calls = 0

    def _fake_cleanup(_self: Any) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    with patch.object(
        SamsungClimateCoordinator,
        "_async_cleanup_auto_healing_issue_if_ignored",
        new=_fake_cleanup,
    ):
        # 1. Default polling (60s), callback injection, and standalone DeviceInfo
        entry = _StubEntry(
            options={CONF_NAME: "  Living Room AC  "},
            data={CONF_MAC: " aa:bb:cc:dd:ee:ff ", CONF_NAME: "Fallback Name"},
        )
        coord = SamsungClimateCoordinator(hass, ctrl, entry)  # type: ignore[arg-type]
        assert coord.controller is ctrl
        assert coord.devices == {}
        assert isinstance(coord.debouncer, PropertyDebouncer)
        assert coord.debouncer.coordinator is coord
        assert coord.debouncer.delay == DEFAULT_DEBOUNCE_DELAY
        assert isinstance(coord._global_network_lock, asyncio.Lock)
        assert coord.config_entry is entry
        assert ctrl.token_callbacks == [coord._async_save_new_token]
        assert ctrl.on_push_update_callback == coord.async_handle_push_update
        assert ctrl.on_ssl_config_updated == coord._async_save_ssl_config
        assert ctrl.request_refresh_callback == coord.async_request_refresh
        assert ctrl.on_connection_failed_callback == coord._async_on_connection_failed
        assert ctrl.on_offline_callback == coord._async_handle_persistent_offline
        assert coord.update_interval == timedelta(seconds=DEFAULT_POLL_INTERVAL)
        assert coord.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": "Living Room AC",
            "manufacturer": MANUFACTURER_SAMSUNG,
            "connections": {(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        }
        assert cleanup_calls == 1

        # 2. String enable_polling, clamping & invalid interval fallback, ctrl.poll=False
        coord_min = SamsungClimateCoordinator(
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            _StubEntry(
                options={CONF_ENABLE_POLLING: "True", CONF_POLL_INTERVAL: "5"},
                data={},
            ),  # type: ignore[arg-type]
        )
        assert coord_min.update_interval == timedelta(seconds=MIN_POLL_INTERVAL)

        coord_max = SamsungClimateCoordinator(
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            _StubEntry(
                options={
                    CONF_ENABLE_POLLING: "yes",
                    CONF_POLL_INTERVAL: MAX_POLL_INTERVAL + 100,
                },
                data={},
            ),  # type: ignore[arg-type]
        )
        assert coord_max.update_interval == timedelta(seconds=MAX_POLL_INTERVAL)

        entry_bad_int = _StubEntry(
            options={CONF_ENABLE_POLLING: True, CONF_POLL_INTERVAL: "invalid"},
            data={},
        )
        coord_bad_int = SamsungClimateCoordinator(
            hass,
            ctrl,
            entry_bad_int,  # type: ignore[arg-type]
        )
        assert coord_bad_int.update_interval == timedelta(seconds=DEFAULT_POLL_INTERVAL)

        coord_off = SamsungClimateCoordinator(
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            _StubEntry(
                options={CONF_ENABLE_POLLING: "False", CONF_POLL_INTERVAL: 30},
                data={CONF_ENABLE_POLLING: True},
            ),  # type: ignore[arg-type]
        )
        assert coord_off.update_interval is None

        coord_data_off = SamsungClimateCoordinator(
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            _StubEntry(
                options={},
                data={CONF_ENABLE_POLLING: False, CONF_POLL_INTERVAL: 30},
            ),  # type: ignore[arg-type]
        )
        assert coord_data_off.update_interval is None

        ctrl.poll = False
        coord_no_poll = SamsungClimateCoordinator(
            hass,
            ctrl,
            entry_bad_int,  # type: ignore[arg-type]
        )
        assert coord_no_poll.update_interval is None


def test_05_coordinator_init_device_info() -> None:
    """Verify SamsungClimateCoordinator.__init__ DeviceInfo branches for standalone and sub-devices."""
    hass = _StubHass()
    ctrl = _StubController()
    ctrl.unique_id = "ac_main"
    ctrl.log_prefix = "[ac_main]"
    base_entry = _StubEntry(options={}, data={})

    def _noop_cleanup(_self: Any) -> None:
        return None

    with patch.object(
        SamsungClimateCoordinator,
        "_async_cleanup_auto_healing_issue_if_ignored",
        new=_noop_cleanup,
    ):
        # 1. Whitespace options name falls back to data name
        coord_data_name = SamsungClimateCoordinator(
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            _StubEntry(
                options={CONF_NAME: "   "},
                data={CONF_NAME: "  Data Name AC  "},
            ),  # type: ignore[arg-type]
        )
        assert coord_data_name.device_info["name"] == "Data Name AC"

        # 2. Standalone IntesisBox with empty MAC
        coord_intesis = SamsungClimateCoordinator(
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            _StubEntry(
                options={CONF_NAME: "   "},
                data={CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX, CONF_MAC: "   "},
            ),  # type: ignore[arg-type]
        )
        assert coord_intesis.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": f"{DEFAULT_INTESISBOX_NAME_PREFIX} ac_main",
            "manufacturer": MANUFACTURER_INTESIS,
            "connections": set(),
        }

        # 3. Malformed MAC triggers ValueError fallback
        def _bad_mac(_mac: str) -> str:
            raise ValueError("bad mac")

        with patch(
            "custom_components.climate_ip.coordinator.dr.format_mac",
            new=_bad_mac,
        ):
            coord_bad_mac = SamsungClimateCoordinator(
                hass,  # type: ignore[arg-type]
                ctrl,  # type: ignore[arg-type]
                _StubEntry(options={}, data={CONF_MAC: "bad_mac"}),  # type: ignore[arg-type]
            )
        assert coord_bad_mac.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": f"{DEFAULT_DEVICE_NAME_PREFIX} ac_main",
            "manufacturer": MANUFACTURER_SAMSUNG,
            "connections": set(),
        }

        # 4. Sub-device branches
        coord_sub_parent = SamsungClimateCoordinator(
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            base_entry,  # type: ignore[arg-type]
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
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            base_entry,  # type: ignore[arg-type]
            device_info={CONF_SUBDEVICE_ID: "0", CONF_NAME: "ID 0 (Bedroom)"},
            parent_unique_id=None,
        )
        assert coord_sub_redundant.device_info == {
            "identifiers": {(DOMAIN, "ac_main")},
            "name": "ID 0 (Bedroom)",
            "manufacturer": MANUFACTURER_SAMSUNG,
        }

        coord_sub_unnamed = SamsungClimateCoordinator(
            hass,  # type: ignore[arg-type]
            ctrl,  # type: ignore[arg-type]
            base_entry,  # type: ignore[arg-type]
            device_info={CONF_SUBDEVICE_ID: None, CONF_NAME: "   "},
        )
        assert coord_sub_unnamed.device_info["name"] == DEFAULT_SUBDEVICE_NAME


def test_06_coordinator_callbacks_and_auto_healing_switch() -> None:
    """Verify issue cleanup, token/SSL persistence callbacks, failure callbacks, and RAW switch."""
    hass = _StubHass()
    entry = _StubEntry(
        options={"keep": 1},
        data={
            "host": "192.168.1.10",
            CONF_TOKEN: "tok_1",
            CONF_SSL_CONFIG_KEY: {"c": 1},
        },
        unique_id="u1",
        entry_id="e1",
    )
    stub_ctrl = _StubController()
    coord = _make_bare_coordinator(hass=hass, controller=stub_ctrl, entry=entry)
    stub_debouncer = _StubDebouncer()
    coord.debouncer = stub_debouncer  # type: ignore[assignment]
    update_errors: list[Exception] = []

    def _record_update_error(err: Exception) -> None:
        update_errors.append(err)

    coord.async_set_update_error = _record_update_error  # type: ignore[method-assign]

    # 1. _async_cleanup_auto_healing_issue_if_ignored
    registry = _StubRegistry()
    get_reg_calls: list[Any] = []
    deleted_issues: list[tuple[Any, str, str]] = []

    def _fake_async_get(hass_arg: Any) -> _StubRegistry:
        get_reg_calls.append(hass_arg)
        return registry

    def _fake_delete_issue(hass_arg: Any, domain: str, issue_id: str) -> None:
        deleted_issues.append((hass_arg, domain, issue_id))

    with (
        patch(
            "custom_components.climate_ip.coordinator.ir.async_get",
            new=_fake_async_get,
        ),
        patch(
            "custom_components.climate_ip.coordinator.ir.async_delete_issue",
            new=_fake_delete_issue,
        ),
    ):
        registry.issue = None
        coord._async_cleanup_auto_healing_issue_if_ignored()
        assert get_reg_calls == [hass]
        assert registry.queries == [(DOMAIN, f"{ISSUE_AUTO_HEALING_RAW}_uid_default")]
        assert deleted_issues == []

        registry.issue = _StubIssue(dismissed_version=None)
        coord._async_cleanup_auto_healing_issue_if_ignored()
        assert deleted_issues == []

        registry.issue = _StubIssue(dismissed_version="2026.10.0")
        coord._async_cleanup_auto_healing_issue_if_ignored()
        assert deleted_issues == [
            (hass, DOMAIN, f"{ISSUE_AUTO_HEALING_RAW}_uid_default")
        ]

    # 2. _async_save_new_token (same token vs new token)
    coord._async_save_new_token("tok_1")
    assert hass.config_entries.updates == []

    coord._async_save_new_token("tok_2")
    assert hass.config_entries.updates == [
        (
            entry,
            {
                "host": "192.168.1.10",
                CONF_TOKEN: "tok_2",
                CONF_SSL_CONFIG_KEY: {"c": 1},
            },
            None,
        )
    ]
    hass.config_entries.updates.clear()

    # 3. _async_save_ssl_config (same config vs new config)
    coord._async_save_ssl_config({"c": 1})
    assert hass.config_entries.updates == []

    coord._async_save_ssl_config({"c": 2})
    assert hass.config_entries.updates == [
        (
            entry,
            {
                "host": "192.168.1.10",
                CONF_TOKEN: "tok_1",
                CONF_SSL_CONFIG_KEY: {"c": 2},
            },
            None,
        )
    ]
    hass.config_entries.updates.clear()

    # 4. _async_on_connection_failed & _async_handle_persistent_offline
    coord._async_on_connection_failed()
    assert stub_debouncer.cancel_calls == 1
    assert stub_ctrl.clear_cache_calls == 1
    assert len(update_errors) == 1
    assert isinstance(update_errors[0], UpdateFailed)
    assert str(update_errors[0]) == ERR_PERSISTENT_CONNECTION_FAILURE

    stub_debouncer.cancel_calls = 0
    stub_ctrl.clear_cache_calls = 0
    update_errors.clear()

    coord._async_handle_persistent_offline("ARP lost")
    assert stub_debouncer.cancel_calls == 1
    assert stub_ctrl.clear_cache_calls == 1
    assert len(update_errors) == 1
    assert isinstance(update_errors[0], UpdateFailed)
    assert str(update_errors[0]) == f"{ERR_DEVICE_OFFLINE_PREFIX}: ARP lost"

    # 5. _async_switch_to_raw_engine (with device_info name and fallback to safe_unique_id)
    created_issues: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def _fake_create_issue(*args: Any, **kwargs: Any) -> None:
        created_issues.append((args, kwargs))

    with patch(
        "custom_components.climate_ip.coordinator.ir.async_create_issue",
        new=_fake_create_issue,
    ):
        coord.device_info = {"name": "Kitchen AC"}
        coord._async_switch_to_raw_engine()
        assert hass.config_entries.updates == [
            (entry, None, {"keep": 1, CONF_CONN_METHOD: CONN_METHOD_RAW})
        ]
        assert created_issues == [
            (
                (hass, DOMAIN, f"{ISSUE_AUTO_HEALING_RAW}_uid_default"),
                {
                    "is_fixable": True,
                    "is_persistent": False,
                    "severity": ir.IssueSeverity.WARNING,
                    "translation_key": ISSUE_AUTO_HEALING_RAW,
                    "translation_placeholders": {"device_name": "Kitchen AC"},
                    "data": {"device_name": "Kitchen AC"},
                },
            )
        ]

        created_issues.clear()
        coord.device_info = {}
        coord._async_switch_to_raw_engine()
        assert created_issues == [
            (
                (hass, DOMAIN, f"{ISSUE_AUTO_HEALING_RAW}_uid_default"),
                {
                    "is_fixable": True,
                    "is_persistent": False,
                    "severity": ir.IssueSeverity.WARNING,
                    "translation_key": ISSUE_AUTO_HEALING_RAW,
                    "translation_placeholders": {"device_name": "uid_default"},
                    "data": {"device_name": "uid_default"},
                },
            )
        ]


async def test_07_coordinator_async_update_data() -> None:
    """Verify _async_update_data polling timeout, auto-healing switch, and exception translations."""
    stub_ctrl = _StubController()
    coord = _make_bare_coordinator(controller=stub_ctrl)
    sentinel_state = object()
    stub_ctrl.climate_state = sentinel_state

    # 1. Success path with timeout check
    timeout_stub = _StubTimeout()
    with patch(
        "custom_components.climate_ip.coordinator.asyncio.timeout",
        new=timeout_stub,
    ):
        res = await coord._async_update_data()
        assert res is sentinel_state
        assert timeout_stub.delays == [NETWORK_POLL_TIMEOUT]
        assert stub_ctrl.get_status_calls == 1

    # 2. InvalidHeaderError when not RAW -> triggers _async_switch_to_raw_engine
    coord.config_entry.options = {CONF_CONN_METHOD: "aiohttp"}
    stub_ctrl.get_status_exc = InvalidHeaderError("bad header")
    switch_calls = 0

    def _record_switch() -> None:
        nonlocal switch_calls
        switch_calls += 1

    with patch.object(coord, "_async_switch_to_raw_engine", new=_record_switch):
        with pytest.raises(UpdateFailed, match=ERR_AUTO_HEALING_RAW_IN_PROGRESS):
            await coord._async_update_data()
        assert switch_calls == 1

        # 3. InvalidHeaderError when already RAW -> does NOT switch, raises RAW parsing failure
        coord.config_entry.options = {CONF_CONN_METHOD: CONN_METHOD_RAW}
        with pytest.raises(
            UpdateFailed, match="Data parsing failed on RAW engine: bad header"
        ):
            await coord._async_update_data()
        assert switch_calls == 1

    # 4. ConfigEntryAuthFailed -> clears cache and re-raises
    stub_ctrl.clear_cache_calls = 0
    stub_ctrl.get_status_exc = ConfigEntryAuthFailed("expired")
    with pytest.raises(ConfigEntryAuthFailed, match="expired"):
        await coord._async_update_data()
    assert stub_ctrl.clear_cache_calls == 1

    # 5. AuthError -> clears cache and raises ConfigEntryAuthFailed
    stub_ctrl.clear_cache_calls = 0
    stub_ctrl.get_status_exc = AuthError("401 unauthorized")
    with pytest.raises(
        ConfigEntryAuthFailed, match="Authentication failed: 401 unauthorized"
    ):
        await coord._async_update_data()
    assert stub_ctrl.clear_cache_calls == 1

    # 6. UpdateFailed -> re-raises directly without clearing cache
    stub_ctrl.clear_cache_calls = 0
    stub_ctrl.get_status_exc = UpdateFailed("direct failure")
    with pytest.raises(UpdateFailed, match="direct failure"):
        await coord._async_update_data()
    assert stub_ctrl.clear_cache_calls == 0

    # 7. Network, Data, and Fatal errors
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
        stub_ctrl.clear_cache_calls = 0
        stub_ctrl.get_status_exc = exc
        with pytest.raises(UpdateFailed, match=expected_msg):
            await coord._async_update_data()
        assert stub_ctrl.clear_cache_calls == 1


async def test_08_coordinator_async_handle_push_update() -> None:
    """Verify async_handle_push_update state merging, debounce suppression, flicker guard, and error branches."""
    stub_ctrl = _StubController()
    stub_entry = _StubEntry()
    coord = _make_bare_coordinator(controller=stub_ctrl, entry=stub_entry)
    coord.debouncer = PropertyDebouncer(coord)
    updated_data_calls: list[Any] = []
    update_error_calls: list[Exception] = []

    def _record_updated_data(data: Any) -> None:
        updated_data_calls.append(data)

    def _record_update_error(err: Exception) -> None:
        update_error_calls.append(err)

    coord.async_set_updated_data = _record_updated_data  # type: ignore[method-assign]
    coord.async_set_update_error = _record_update_error  # type: ignore[method-assign]

    # 1. new_data is None -> ignored
    await coord.async_handle_push_update(None)
    assert stub_ctrl.merge_calls == []
    assert updated_data_calls == []

    # 2. Controller rejects merge (False) -> ignored
    stub_ctrl.merge_result = False
    await coord.async_handle_push_update({"junk": 1})
    assert stub_ctrl.merge_calls == [{"junk": 1}]
    assert updated_data_calls == []

    # 3. Merge succeeds, but debouncer is active -> suppressed
    stub_ctrl.merge_result = True
    stub_ctrl.climate_state = "state_active"
    coord.debouncer._pending_payloads["temp"] = (_StubCmd(), (), {}, 0)
    await coord.async_handle_push_update({"power": "on"})
    assert updated_data_calls == []
    coord.debouncer._pending_payloads.clear()

    # 4. Debouncer inactive: identical state when last_update_success is True -> suppressed
    stub_ctrl.climate_state = "state_a"
    coord.data = "state_a"  # type: ignore[assignment]
    coord.last_update_success = True
    await coord.async_handle_push_update({"power": "on"})
    assert updated_data_calls == []

    # 5. Identical state when last_update_success is False -> broadcasts recovery
    coord.last_update_success = False
    await coord.async_handle_push_update({"power": "on"})
    assert updated_data_calls == ["state_a"]
    updated_data_calls.clear()

    # 6. Different state when last_update_success is True -> broadcasts update
    coord.last_update_success = True
    stub_ctrl.climate_state = "state_b"
    await coord.async_handle_push_update({"power": "off"})
    assert updated_data_calls == ["state_b"]

    # 7. CancelledError -> re-raised cleanly
    stub_ctrl.merge_exc = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await coord.async_handle_push_update({"power": "on"})

    # 8. AuthError / ConfigEntryAuthFailed -> clears cache, sets error, starts reauth
    for auth_exc in (AuthError("bad token"), ConfigEntryAuthFailed("expired")):
        stub_ctrl.clear_cache_calls = 0
        update_error_calls.clear()
        stub_entry.reauth_calls.clear()
        stub_ctrl.merge_exc = auth_exc

        await coord.async_handle_push_update({"power": "on"})
        assert stub_ctrl.clear_cache_calls == 1
        assert len(update_error_calls) == 1
        assert isinstance(update_error_calls[0], ConfigEntryAuthFailed)
        assert f"Authentication failed: {auth_exc}" in str(update_error_calls[0])
        assert stub_entry.reauth_calls == [coord.hass]

    # Auth failure when config_entry is None -> does not fail
    coord.config_entry = None  # type: ignore[assignment]
    stub_ctrl.merge_exc = AuthError("no entry")
    await coord.async_handle_push_update({"power": "on"})

    # 9. Generic Exception -> clears cache and sets UpdateFailed
    stub_ctrl.clear_cache_calls = 0
    update_error_calls.clear()
    stub_ctrl.merge_exc = RuntimeError("push boom")
    await coord.async_handle_push_update({"power": "on"})
    assert stub_ctrl.clear_cache_calls == 1
    assert len(update_error_calls) == 1
    assert isinstance(update_error_calls[0], UpdateFailed)
    assert str(update_error_calls[0]) == "Push update failed: push boom"


async def test_09_coordinator_locked_set_property() -> None:
    """Verify _locked_set_property superseding guards, lock spacing sleep, and strict bool check."""
    stub_ctrl = _StubController()
    coord = _make_bare_coordinator(controller=stub_ctrl)
    coord.debouncer = PropertyDebouncer(coord)
    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with patch(
        "custom_components.climate_ip.coordinator.asyncio.sleep",
        new=_fake_sleep,
    ):
        # 1. Superseded by debouncer.has_pending
        coord.debouncer._pending_payloads["temp"] = (_StubCmd(), (), {}, 0)
        assert await coord._locked_set_property("temp", 22.0, "dev_1") is True
        assert stub_ctrl.superseded_calls == []
        assert stub_ctrl.set_prop_calls == []
        assert sleep_calls == []
        coord.debouncer._pending_payloads.clear()

        # 2. Superseded by controller.is_property_superseded
        stub_ctrl.superseded_result = True
        assert await coord._locked_set_property("temp", 22.0, "dev_1") is True
        assert stub_ctrl.superseded_calls == [("temp", 22.0)]
        assert stub_ctrl.set_prop_calls == []
        assert sleep_calls == []

        # 3. Normal execution returning True and False with exact hardware spacing sleep
        stub_ctrl.superseded_result = False
        assert await coord._locked_set_property("temp", 23.0, "dev_1") is True
        assert stub_ctrl.set_prop_calls == [("temp", 23.0, "dev_1")]
        assert sleep_calls == [HARDWARE_BREATHING_ROOM_SEC]

        stub_ctrl.set_prop_calls.clear()
        sleep_calls.clear()
        stub_ctrl.set_prop_result = False
        assert await coord._locked_set_property("fan_mode", "low", None) is False
        assert stub_ctrl.set_prop_calls == [("fan_mode", "low", None)]
        assert sleep_calls == [HARDWARE_BREATHING_ROOM_SEC]

        # 4. Non-bool return raises TypeError
        stub_ctrl.set_prop_result = "invalid_truthy_str"
        with pytest.raises(TypeError, match="expected bool"):
            await coord._locked_set_property("fan_mode", "low")


async def test_10_coordinator_async_set_property_and_failure_rollback() -> None:
    """Verify async_set_property prediction, Enum unwrapping, corrections, and rollback on all failure types."""
    stub_ctrl = _StubController()
    coord = _make_bare_coordinator(controller=stub_ctrl)
    stub_debouncer = _StubDebouncer()
    coord.debouncer = stub_debouncer  # type: ignore[assignment]
    updated_data: list[Any] = []
    refresh_calls = 0

    def _record_updated_data(data: Any) -> None:
        updated_data.append(data)

    async def _record_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    coord.async_set_updated_data = _record_updated_data  # type: ignore[method-assign]
    coord.async_request_refresh = _record_refresh  # type: ignore[method-assign]

    existing_state = object()
    predicted_state = object()
    coord.data = existing_state  # type: ignore[assignment]
    stub_ctrl.climate_state = predicted_state
    stub_ctrl.predict_corrections = {"fan_mode": HVACMode.AUTO, "swing": "on"}

    # 1. Success path with existing self.data, Enum new_value, and Enum/str corrections
    await coord.async_set_property(ATTR_HVAC_MODE, HVACMode.COOL, device_id="sub_1")
    assert stub_ctrl.predict_calls == [(existing_state, ATTR_HVAC_MODE, "cool")]
    assert updated_data == [predicted_state]
    assert stub_debouncer.execute_calls == [
        (
            ATTR_HVAC_MODE,
            coord._locked_set_property,
            (ATTR_HVAC_MODE, "cool", "sub_1"),
            {"val": "cool"},
        ),
        (
            "fan_mode",
            coord._locked_set_property,
            ("fan_mode", "auto", "sub_1"),
            {"val": "auto"},
        ),
        (
            "swing",
            coord._locked_set_property,
            ("swing", "on", "sub_1"),
            {"val": "on"},
        ),
    ]
    assert refresh_calls == 0

    # 2. Fallback to _create_device_state() when self.data is None, and partial False result rollback
    coord.data = None  # type: ignore[assignment]
    stub_ctrl.predict_calls.clear()
    stub_ctrl.predict_corrections = {"fan_mode": "high"}
    stub_debouncer.outcomes = [True, False]

    with pytest.raises(
        HomeAssistantError, match="Failed to set property hvac_mode to dry"
    ):
        await coord.async_set_property(ATTR_HVAC_MODE, "dry")

    assert stub_ctrl.predict_calls == [(predicted_state, ATTR_HVAC_MODE, "dry")]
    assert stub_debouncer.cancel_calls == 1
    assert stub_ctrl.cleared_pending == [[ATTR_HVAC_MODE, "fan_mode"]]
    assert refresh_calls == 1

    # 3. CannotConnect / OSError label and host resolution fallbacks
    stub_ctrl.predict_corrections = {}
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
        stub_ctrl.name = ctrl_name
        stub_ctrl.ip_address = ip_addr
        stub_ctrl.host = host
        stub_debouncer.cancel_calls = 0
        stub_ctrl.cleared_pending.clear()
        refresh_calls = 0
        stub_debouncer.outcomes = [exc]

        with pytest.raises(
            HomeAssistantError,
            match=r"^" + expected_err.replace("(", r"\(").replace(")", r"\)") + r"$",
        ):
            await coord.async_set_property("temp", 21.0)
        assert stub_debouncer.cancel_calls == 1
        assert stub_ctrl.cleared_pending == [["temp"]]
        assert refresh_calls == 1

    # 4. Data errors (ValueError, TypeError, KeyError), CancelledError, and generic Exception
    for data_exc in (ValueError("bad v"), TypeError("bad t"), KeyError("bad k")):
        stub_debouncer.cancel_calls = 0
        stub_ctrl.cleared_pending.clear()
        refresh_calls = 0
        stub_debouncer.outcomes = [data_exc]
        with pytest.raises(
            HomeAssistantError, match=f"Data error setting property temp: {data_exc}"
        ):
            await coord.async_set_property("temp", 21.0)
        assert stub_debouncer.cancel_calls == 1
        assert stub_ctrl.cleared_pending == [["temp"]]
        assert refresh_calls == 1

    stub_debouncer.cancel_calls = 0
    stub_ctrl.cleared_pending.clear()
    refresh_calls = 0
    stub_debouncer.outcomes = [asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        await coord.async_set_property("temp", 21.0)
    assert stub_debouncer.cancel_calls == 1
    assert stub_ctrl.cleared_pending == [["temp"]]
    assert refresh_calls == 1

    stub_debouncer.cancel_calls = 0
    stub_ctrl.cleared_pending.clear()
    refresh_calls = 0
    stub_debouncer.outcomes = [RuntimeError("unexpected")]
    with pytest.raises(
        HomeAssistantError, match="Failed to set property temp: unexpected"
    ):
        await coord.async_set_property("temp", 21.0)
    assert stub_debouncer.cancel_calls == 1
    assert stub_ctrl.cleared_pending == [["temp"]]
    assert refresh_calls == 1


async def test_11_coordinator_properties_and_shutdown() -> None:
    """Verify coordinator identifier/connection properties and async_shutdown error handling."""
    stub_ctrl = _StubController()
    coord = _make_bare_coordinator(controller=stub_ctrl)
    stub_debouncer = _StubDebouncer()
    coord.debouncer = stub_debouncer  # type: ignore[assignment]

    # 1. log_prefix, unique_id, safe_unique_id, auto_healing_issue_id
    stub_ctrl.log_prefix = "[custom_prefix]"
    stub_ctrl.unique_id = "  ctrl.uid 1  "
    assert coord.log_prefix == "[custom_prefix]"
    assert coord.unique_id == "  ctrl.uid 1  "
    assert coord.safe_unique_id == "ctrl_uid_1"
    assert coord.auto_healing_issue_id == f"{ISSUE_AUTO_HEALING_RAW}_ctrl_uid_1"

    for empty_ctrl_uid in (None, "   "):
        stub_ctrl.unique_id = empty_ctrl_uid
        coord.config_entry.unique_id = "  entry.uid 2  "
        assert coord.safe_unique_id == "entry_uid_2"

    for empty_entry_uid in (None, "   "):
        stub_ctrl.unique_id = "   "
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
    super_shutdown_calls = 0

    async def _fake_super_shutdown(_self: Any) -> None:
        nonlocal super_shutdown_calls
        super_shutdown_calls += 1

    with patch.object(
        DataUpdateCoordinator, "async_shutdown", new=_fake_super_shutdown
    ):
        await coord.async_shutdown()
        assert stub_debouncer.cancel_calls == 1
        assert super_shutdown_calls == 1
        assert stub_ctrl.shutdown_calls == 1

        for net_exc in (
            TimeoutError("timeout"),
            CannotConnect("cannot"),
            OSError("os"),
        ):
            stub_ctrl.shutdown_exc = net_exc
            await coord.async_shutdown()

        stub_ctrl.shutdown_exc = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await coord.async_shutdown()

        stub_ctrl.shutdown_exc = RuntimeError("shutdown boom")
        await coord.async_shutdown()
