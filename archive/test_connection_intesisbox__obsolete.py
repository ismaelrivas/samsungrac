"""Archived redundant and shadowed tests for ConnectionIntesisBox.

These tests were identified as 100% shadowed in mutmut test usage maps
(test_connection_intesisbox_usage_map.json) with 0 mutant kills and zero unique coverage.
Their behavioral assertions have been consolidated into canonical tests in
tests/test_connection_intesisbox__yaml.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.climate_ip.connection_intesisbox import ConnectionIntesisBox
from custom_components.climate_ip.const import (
    DEVICE_TYPE_INTESISBOX,
    DEVICE_TYPE_TO_CONFIG_FILE,
)
from custom_components.climate_ip.exceptions import CannotConnect
import pytest
from pytest_homeassistant_custom_component.plugins import HASocketBlockedError
import pytest_socket

from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT

_REAL_OPEN_CONNECTION = asyncio.open_connection


def test_device_type_registration() -> None:
    """Verify DEVICE_TYPE_INTESISBOX is registered and points to intesisbox.yaml."""
    assert DEVICE_TYPE_INTESISBOX == "intesisbox"
    assert DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_INTESISBOX] == "intesisbox.yaml"
    assert ConnectionIntesisBox.match_type(DEVICE_TYPE_INTESISBOX) is True
    assert ConnectionIntesisBox.match_type("other_type") is False


@pytest.mark.asyncio
async def test_connection_intesisbox_missing_host() -> None:
    """Test that async_connect raises CannotConnect when host is not specified."""
    conn = ConnectionIntesisBox(config={}, logger=MagicMock())
    with pytest.raises(CannotConnect):
        await conn.async_connect()


@pytest.mark.asyncio
async def test_live_emulator_connection_and_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test ConnectionIntesisBox live against running emulator on 127.0.0.1:3310."""
    pytest_socket.enable_socket()
    HASocketBlockedError.instances.clear()
    monkeypatch.setattr("asyncio.open_connection", _REAL_OPEN_CONNECTION)

    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=MagicMock(),
    )

    try:
        try:
            await conn.async_connect()
        except CannotConnect:
            pytest.skip("Local IntesisBox emulator not reachable on port 3310")

        assert conn.is_available is True
        for _ in range(60):
            if {"ONOFF", "MODE", "SETPTEMP"}.issubset(conn._device_status):
                break
            await asyncio.sleep(0.1)

        assert conn._device_status.get("ONOFF") in ["ON", "OFF"]
        assert "MODE" in conn._device_status

        # Test command execution
        resp, _ = await conn.async_execute(None, None, "SET,1:ONOFF,ON", None)
        assert resp is not None
        assert conn._device_status.get("ONOFF") == "ON"
    finally:
        await conn.close()
        pytest_socket.disable_socket()
        HASocketBlockedError.instances.clear()


@pytest.mark.asyncio
async def test_intesisbox_loop_breaker_window_purging_and_alternation_boundary() -> (
    None
):
    """Shadowed test for loop breaker window purging and alternation boundaries."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=MagicMock(),
    )
    rule = {
        "node": "FANSP",
        "fallback_value": "AUTO",
        "threshold": 4,
        "window_seconds": 2.0,
    }
    conn._loop_breakers = [rule]
    sent_commands: list[str] = []

    async def fake_send(payload: str) -> None:
        sent_commands.append(payload)

    conn._send_raw = fake_send
    import time

    now = time.monotonic()
    conn._node_history["FANSP"] = [(now - 10.0, "OLD_VAL")]
    conn._evaluate_oscillation_rule("FANSP", "VAL1", rule)
    assert len(conn._node_history["FANSP"]) == 1

    conn._node_history.clear()
    sent_commands.clear()
    for v in ["A", "B", "A", "B"]:
        conn._process_incoming_line(f"CHN,1:FANSP,{v}")

    await asyncio.sleep(0)
    assert len(sent_commands) == 0

    conn._process_incoming_line("CHN,1:FANSP,A")
    await asyncio.sleep(0)
    assert conn._device_status["FANSP"] == "AUTO"


@pytest.mark.asyncio
async def test_intesisbox_loop_breaker_else_branch_and_value_selection() -> None:
    """Shadowed test for oscillation between two non-pruned values."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=MagicMock(),
    )
    rule = {
        "node": "FANSP",
        "fallback_value": "AUTO",
        "fallback_command": "SET,1:FANSP,AUTO",
        "prune_values": ["1"],
        "threshold": 3,
        "window_seconds": 5.0,
    }
    conn._loop_breakers = [rule]
    conn._limits["FANSP"] = "[AUTO,1,2,3,4]"
    sent_commands: list[str] = []

    async def fake_send(payload: str) -> None:
        sent_commands.append(payload)

    conn._send_raw = fake_send
    for v in ["2", "3", "2", "3"]:
        conn._process_incoming_line(f"CHN,1:FANSP,{v}")

    await asyncio.sleep(0)
    assert "SET,1:FANSP,AUTO\r\n" in sent_commands
    assert conn._limits["FANSP"] == "[AUTO,1,2,3,4]"
    assert conn._device_status["FANSP"] == "AUTO"


@pytest.mark.asyncio
async def test_intesisbox_async_probe_exceptions() -> None:
    """Shadowed test for async_probe exceptions."""
    with patch("asyncio.open_connection", side_effect=OSError("Network unreachable")):
        with pytest.raises(CannotConnect):
            await ConnectionIntesisBox.async_probe("192.168.1.50")

    mock_reader = AsyncMock()
    mock_reader.read = AsyncMock(side_effect=TimeoutError("Probe read timeout"))
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with pytest.raises(CannotConnect):
            await ConnectionIntesisBox.async_probe("192.168.1.50")
