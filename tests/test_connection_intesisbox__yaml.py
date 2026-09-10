"""Unit and integration tests for IntesisBox WMP v1.9 support in climate_ip."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from homeassistant.components.climate import HVACMode
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util.yaml import load_yaml
import pytest
from pytest_homeassistant_custom_component.plugins import HASocketBlockedError
import pytest_socket

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.connection_intesisbox import ConnectionIntesisBox
from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_TYPE,
    CONF_TOKEN,
    DEVICE_TYPE_INTESISBOX,
    DEVICE_TYPE_TO_CONFIG_FILE,
)
from custom_components.climate_ip.controller_yaml import YamlController
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.exceptions import CannotConnect
from custom_components.climate_ip.token_acquirer_yaml import GenericYamlTokenAcquirer

_LOGGER = logging.getLogger(__name__)

# Preserve reference to real asyncio.open_connection before test fixtures monkeypatch it
_REAL_OPEN_CONNECTION = asyncio.open_connection


# ---------------------------------------------------------------------------
# 1. YAML Loading & Integrity Tests
# ---------------------------------------------------------------------------
def test_intesisbox_yaml_loading() -> None:
    """Test that intesisbox.yaml is valid YAML and conforms to climate_ip structure."""
    yaml_path = Path(__file__).parents[1] / "intesisbox.yaml"
    assert yaml_path.exists(), "intesisbox.yaml file missing"

    content = load_yaml(str(yaml_path))
    assert isinstance(content, dict)
    assert "device" in content
    dev = content["device"]
    assert dev.get("name") == "intesisbox"
    assert dev.get("poll") is True
    assert dev.get("connection", {}).get("type") == "intesisbox"
    assert dev.get("status", {}).get("connection_template") == "STATUS,1"

    # Verify operations
    ops = dev.get("operations", {})
    assert "hvac" in ops
    assert "temperature" in ops
    assert "fan" in ops
    assert "swing" in ops

    # Verify attributes
    attrs = dev.get("attributes", {})
    assert "current_temperature" in attrs
    assert "min_temp" in attrs
    assert "max_temp" in attrs

    # Verify switches & sensors
    assert "power" in dev.get("switches", {})
    assert "error_status" in dev.get("sensors", {})
    assert "error_code" in dev.get("sensors", {})
    assert "vane_horizontal" in dev.get("sensors", {})


@pytest.mark.asyncio
async def test_intesisbox_controller_climate_state(hass: HomeAssistant) -> None:
    """Test YamlController loading intesisbox.yaml and correctly parsing typed climate_state."""
    hass.data = {}
    hass.config.units.temperature_unit = "°C"
    config = {
        CONF_CONFIG_FILE: "intesisbox.yaml",
        CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX,
        CONF_IP_ADDRESS: "127.0.0.1",
        CONF_PORT: 3310,
        CONF_MAC: "001DC9A2C911",
        CONF_TOKEN: "001DC9A2C911",
    }
    controller = YamlController(config, logger=_LOGGER, hass=hass)
    assert await controller.loader.async_initialize() is True
    await controller.loader.async_finish_initialization()
    assert controller.loader.is_fully_initialized is True

    # Check operations and attributes loaded
    assert "temperature" in controller.loader.operations
    assert "current_temperature" in controller.loader.properties

    # Simulate state update with WMP default state
    wmp_state = {
        "ONOFF": "OFF",
        "MODE": "COOL",
        "SETPTEMP": "220",
        "FANSP": "AUTO",
        "VANEUD": "AUTO",
        "VANELR": "AUTO",
        "AMBTEMP": "230",
        "ERRSTATUS": "OK",
        "ERRCODE": "0",
    }

    # Ingest clean frame into immaculate network state
    controller.poller._pure_network_state = dict(wmp_state)
    st_getter = controller.loader.state_getter
    if st_getter:
        st_getter._value = wmp_state

    await controller.poller.async_update_properties_from_state(
        wmp_state, force_update=True
    )

    # Validate target and current temperatures
    assert controller.get_property("temperature") == 22.0
    assert controller.get_property("current_temperature") == 23.0

    # Validate sensor properties loaded from intesisbox.yaml
    assert len(controller.sensors) == 3
    sensor_ids = [s.id for s in controller.sensors]
    assert "error_status" in sensor_ids
    assert "error_code" in sensor_ids
    assert "vane_horizontal" in sensor_ids
    assert controller.get_property("error_status") == "OK"
    assert controller.get_property("error_code") == "0"
    assert controller.get_property("vane_horizontal") == "AUTO"

    state = controller.climate_state
    assert state.target_temperature == 22.0
    assert state.current_temperature == 23.0
    assert state.hvac_mode == HVACMode.OFF
    assert state.fan_mode == "auto"
    assert state.swing_mode == "off"

    # Test setting operations generates exact WMP SET commands
    with patch.object(
        ConnectionIntesisBox, "async_execute", new_callable=AsyncMock
    ) as mock_exec:
        mock_exec.return_value = ("{}", {})

        # 1. Target Temperature 24.5 °C -> SET,1:SETPTEMP,245
        res = await controller.async_set_property("temperature", 24.5)
        assert res is True
        assert "SET,1:SETPTEMP,245" in mock_exec.call_args[0][2]

        # 2. Fan mode high -> SET,1:FANSP,4
        res = await controller.async_set_property("fan_mode", "high")
        assert res is True
        assert "SET,1:FANSP,4" in mock_exec.call_args[0][2]

        # 3. Swing mode vertical -> SET,1:VANEUD,SWING
        res = await controller.async_set_property("swing_mode", "vertical")
        assert res is True
        assert "SET,1:VANEUD,SWING" in mock_exec.call_args[0][2]


def test_intesisbox_auth_yaml_loading() -> None:
    """Test that auth_flows/intesisbox_auth.yaml is valid."""
    auth_path = Path(__file__).parents[1] / "auth_flows" / "intesisbox_auth.yaml"
    assert auth_path.exists(), "intesisbox_auth.yaml file missing"

    content = load_yaml(str(auth_path))
    assert isinstance(content, dict)
    flow = content.get("auth_flow", {})
    assert flow.get("mode") == "stream"
    assert flow.get("request_pairing", {}).get("port") == 3310
    assert flow.get("request_pairing", {}).get("payload") == "ID\r\n"
    assert "regex" in flow.get("extract_template", {})


def test_device_type_registration() -> None:
    """Verify DEVICE_TYPE_INTESISBOX is registered and points to intesisbox.yaml."""
    assert DEVICE_TYPE_INTESISBOX == "intesisbox"
    assert DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_INTESISBOX] == "intesisbox.yaml"
    assert ConnectionIntesisBox.match_type(DEVICE_TYPE_INTESISBOX) is True
    assert ConnectionIntesisBox.match_type("other_type") is False


# ---------------------------------------------------------------------------
# 2. ConnectionIntesisBox Class Tests
# ---------------------------------------------------------------------------
def test_connection_intesisbox_initialization() -> None:
    """Test ConnectionIntesisBox initialization and properties."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "192.168.1.50", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    assert conn.is_async_native is True
    assert conn.is_push_supported is True
    assert conn.is_available is False
    assert conn.log_prefix == "[IntesisBox 192.168.1.50:3310]"

    # Test load_from_yaml
    assert conn.load_from_yaml(None, None) is False
    assert conn.load_from_yaml(
        {"params": {"host": "192.168.1.55", "port": 3311}, "keep_alive": True},
        None,
    ) is True
    assert conn._host == "192.168.1.55"
    assert conn._port == 3311

    # Test create_updated
    updated = conn.create_updated({"params": {"port": 3312}})
    assert updated._port == 3312
    assert updated._host == "192.168.1.55"

    # Test synchronous execute raises NotImplementedError
    with pytest.raises(NotImplementedError):
        conn.execute("dummy", "val", {})


@pytest.mark.asyncio
async def test_connection_intesisbox_process_lines() -> None:
    """Test parsing incoming protocol lines in ConnectionIntesisBox."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1"},
        logger=_LOGGER,
    )
    mock_cb = AsyncMock()
    conn.set_update_callback(mock_cb)

    # 1. ACK / ERR future handling
    loop = asyncio.get_running_loop()
    conn._pending_ack = loop.create_future()
    conn._process_incoming_line("ACK")
    assert conn._pending_ack.done() and conn._pending_ack.result() is True

    conn._pending_ack = loop.create_future()
    conn._process_incoming_line("ERR")
    assert conn._pending_ack.done() and conn._pending_ack.result() is False

    # 2. ID line
    conn._process_incoming_line("ID:IS-IR-WMP-1,001DC9A2C911,192.168.1.50,1.9,-65")
    assert conn._device_info_raw == "IS-IR-WMP-1,001DC9A2C911,192.168.1.50,1.9,-65"

    # 3. LIMITS line
    conn._process_incoming_line("LIMITS:FANSP,[AUTO,1,2,3,4]")
    assert conn._limits.get("FANSP") == "[AUTO,1,2,3,4]"

    conn._process_incoming_line("LIMITS,1:MODE,[AUTO,HEAT,COOL]")
    assert conn._limits.get("MODE") == "[AUTO,HEAT,COOL]"

    # 4. State updates (STATUS, CHN, and raw <ac>:<uid>,<val>)
    conn._process_incoming_line("STATUS,1:ONOFF,OFF")
    assert conn._device_status.get("ONOFF") == "OFF"

    conn._process_incoming_line("CHN,1:SETPTEMP,220")
    assert conn._device_status.get("SETPTEMP") == "220"

    conn._process_incoming_line("1:AMBTEMP,235")
    assert conn._device_status.get("AMBTEMP") == "235"

    # Yield control so background tasks created for mock_cb run
    await asyncio.sleep(0.01)
    assert mock_cb.await_count >= 3


@pytest.mark.asyncio
async def test_connection_intesisbox_missing_host() -> None:
    """Test that async_connect raises CannotConnect when host is not specified."""
    conn = ConnectionIntesisBox(config={}, logger=_LOGGER)
    with pytest.raises(CannotConnect):
        await conn.async_connect()


@pytest.mark.asyncio
async def test_connection_intesisbox_mocked_execution() -> None:
    """Test command execution using mocked asyncio stream reader/writer."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )

    lines = [
        b"ID:TEST,112233445566,127.0.0.1\r\n",
        b"LIMITS:FANSP,[1,2]\r\n",
        b"STATUS,1:ONOFF,OFF\r\n",
    ]

    async def mock_readline() -> bytes:
        if lines:
            return lines.pop(0)
        # Keep task suspended until cancelled by close()
        await asyncio.sleep(9999)
        return b""

    mock_reader = AsyncMock()
    mock_reader.readline = AsyncMock(side_effect=mock_readline)

    mock_writer = MagicMock()
    mock_writer.is_closing.return_value = False
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        await conn.async_connect()
        assert conn.is_available is True
        assert conn._device_status.get("ONOFF") == "OFF"

        # Test polling
        resp, _ = await conn.async_execute(None, None, None, None, _is_poll=True)
        assert resp is not None
        parsed = json.loads(resp)
        assert parsed.get("ONOFF") == "OFF"

        # Clean shutdown
        await conn.close()
        assert conn.is_available is False


# ---------------------------------------------------------------------------
# 3. Live Integration Tests against Local Emulator (Port 3310)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_emulator_connection_and_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test ConnectionIntesisBox live against running emulator on 127.0.0.1:3310."""
    pytest_socket.enable_socket()
    HASocketBlockedError.instances.clear()
    monkeypatch.setattr("asyncio.open_connection", _REAL_OPEN_CONNECTION)

    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )

    try:
        try:
            await conn.async_connect()
        except CannotConnect:
            pytest.skip("Local IntesisBox emulator not reachable on port 3310")

        assert conn.is_available is True
        # Allow brief time for reader task to ingest handshake line burst
        for _ in range(60):
            if {"ONOFF", "MODE", "SETPTEMP"}.issubset(conn._device_status):
                break
            await asyncio.sleep(0.1)

        # Verify initial status populated
        assert "ONOFF" in conn._device_status
        assert "MODE" in conn._device_status
        assert "SETPTEMP" in conn._device_status

        # Execute SET command
        resp, _ = await conn.async_execute(None, None, "SET,1:SETPTEMP,240\r\n", None)
        assert resp is not None
        state = json.loads(resp)
        assert state.get("SETPTEMP") == "240"

        # Execute multi-line command
        resp, _ = await conn.async_execute(
            None, None, "SET,1:ONOFF,ON\nSET,1:MODE,HEAT\r\n", None
        )
        assert resp is not None
        state = json.loads(resp)
        assert state.get("ONOFF") == "ON"
        assert state.get("MODE") == "HEAT"

        await conn.close()
        assert conn.is_available is False
    finally:
        pytest_socket.disable_socket()
        HASocketBlockedError.instances.clear()


@pytest.mark.asyncio
async def test_live_emulator_token_acquirer_plain_tcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test GenericYamlTokenAcquirer against live emulator using intesisbox_auth.yaml."""
    pytest_socket.enable_socket()
    HASocketBlockedError.instances.clear()
    monkeypatch.setattr("asyncio.open_connection", _REAL_OPEN_CONNECTION)

    auth_path = Path(__file__).parents[1] / "auth_flows" / "intesisbox_auth.yaml"
    auth_cfg = load_yaml(str(auth_path))

    acquirer = GenericYamlTokenAcquirer(
        hass=MagicMock(),
        ip_address="127.0.0.1",
        auth_config=auth_cfg["auth_flow"],
    )

    try:
        try:
            init_res = await acquirer.async_initiate_pairing()
        except CannotConnect:
            pytest.skip("Local IntesisBox emulator not reachable on port 3310")

        assert init_res.get("plain_tcp") is True

        # Phase 2 extracts MAC address immediately from handshake response
        token = await acquirer.async_wait_for_token()
        assert token.upper() == "001DC9A2C911"
        await acquirer.async_close()
    finally:
        pytest_socket.disable_socket()
        HASocketBlockedError.instances.clear()


# ---------------------------------------------------------------------------
# 4. Config Flow Step Integration Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_config_flow_intesisbox_step(hass: HomeAssistant) -> None:
    """Test full configuration flow for IntesisBox."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}

    # 1. Step user: select intesisbox
    result = await flow.async_step_user({CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "intesisbox"

    # 2. Step intesisbox: submit IP address
    # Mock open_connection to simulate device answering ID query
    mock_reader = AsyncMock()
    mock_reader.read.return_value = (
        b"ID:IS-IR-WMP-1,001DC9A2C911,192.168.1.100,1.9,-44\r\n"
    )
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        create_result = await flow.async_step_intesisbox(
            {CONF_IP_ADDRESS: "192.168.1.100"}
        )

    assert create_result["type"] == FlowResultType.CREATE_ENTRY
    assert create_result["title"] == "IntesisBox (192.168.1.100)"
    data = create_result["data"]
    assert data[CONF_DEVICE_TYPE] == DEVICE_TYPE_INTESISBOX
    assert data[CONF_CONFIG_FILE] == "intesisbox.yaml"
    assert data[CONF_MAC] == "001DC9A2C911"
    assert data[CONF_TOKEN] == "001DC9A2C911"


# ---------------------------------------------------------------------------
# 5. Offline Error Handling & Repair Issue Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_intesisbox_offline_error_and_repair_lifecycle(hass: HomeAssistant) -> None:
    """Test clean HomeAssistantError on command failure and poller repair issue lifecycle."""
    hass.data = {}
    hass.config.units.temperature_unit = "°C"
    config = {
        CONF_CONFIG_FILE: "intesisbox.yaml",
        CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX,
        CONF_NAME: "IntesisBox (192.168.1.195)",
        CONF_IP_ADDRESS: "192.168.1.195",
        CONF_PORT: 3310,
        CONF_MAC: "001DC9A2C911",
        CONF_TOKEN: "001DC9A2C911",
    }
    controller = YamlController(config, logger=_LOGGER, hass=hass)
    await controller.loader.async_initialize()
    await controller.loader.async_finish_initialization()

    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = config
    mock_entry.unique_id = "001DC9A2C911"
    mock_entry.entry_id = "entry_123"

    coordinator = SamsungClimateCoordinator(hass, controller, mock_entry)
    coordinator.async_request_refresh = AsyncMock()

    # 1. Verify clean, elegant error handling on service call without raw tracebacks
    with patch.object(
        controller.connection, "async_execute", side_effect=CannotConnect("Connect call failed")
    ):
        with pytest.raises(HomeAssistantError) as exc_info:
            await coordinator.async_set_property("hvac_mode", HVACMode.COOL)

        assert "Connection error: could not set value for" in str(exc_info.value)

    # 2. Verify poller repair issue lifecycle (as defined in controller_yaml_polling.py)
    poller = controller.poller
    poller._cached_device_state = {"ONOFF": "ON"}
    poller._consecutive_connection_errors = 0

    with patch.object(
        YamlController, "available", new_callable=PropertyMock, return_value=True
    ), patch(
        "custom_components.climate_ip.controller_yaml_polling.async_create_issue"
    ) as mock_create_issue:
        # Simulate connection errors during polling
        with patch.object(
            ConnectionIntesisBox, "async_execute", side_effect=CannotConnect("Offline")
        ):
            # 1st failure: cache/grace
            state1 = await poller.async_get_status()
            assert state1 == {"ONOFF": "ON"}
            assert not mock_create_issue.called
            assert poller._consecutive_connection_errors == 1

            # 2nd failure: cache/grace
            state2 = await poller.async_get_status()
            assert state2 == {"ONOFF": "ON"}
            assert not mock_create_issue.called
            assert poller._consecutive_connection_errors == 2

            # 3rd failure: threshold reached -> triggers repair issue
            with pytest.raises(UpdateFailed):
                await poller.async_get_status()

            assert mock_create_issue.called
            assert mock_create_issue.call_args[0][2] == "device_offline_001DC9A2C911"
            assert mock_create_issue.call_args[1]["translation_key"] == "connection_failed"
            assert (
                mock_create_issue.call_args[1]["translation_placeholders"]["device_name"]
                == "IntesisBox (192.168.1.195)"
            )

    # 3. Verify clearing of repair issue on connection recovery
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
    ) as mock_delete_issue:
        mock_data = {"ONOFF": "ON", "MODE": "COOL", "SETPTEMP": 220, "AMBTEMP": 240}
        with patch.object(
            ConnectionIntesisBox, "async_execute", return_value=(json.dumps(mock_data), {})
        ):
            state = await poller.async_get_status()
            assert state is not None
            assert poller._consecutive_connection_errors == 0
            assert mock_delete_issue.called
            assert mock_delete_issue.call_args[0][2] == "device_offline_001DC9A2C911"


@pytest.mark.asyncio
async def test_intesisbox_sensor_platform_setup(hass: HomeAssistant) -> None:
    """Test that sensor platform creates entities for IntesisBox sensors."""
    from custom_components.climate_ip.sensor import async_setup_entry

    hass.data = {}
    hass.config.units.temperature_unit = "°C"
    config = {
        CONF_CONFIG_FILE: "intesisbox.yaml",
        CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX,
        CONF_IP_ADDRESS: "127.0.0.1",
        CONF_PORT: 3310,
        CONF_TOKEN: "001DC9A2C911",
        CONF_MAC: "001DC9A2C911",
    }
    controller = YamlController(config, logger=_LOGGER, hass=hass)
    await controller.loader.async_initialize()
    await controller.loader.async_finish_initialization()

    mock_entry = MagicMock()
    mock_entry.data = config
    mock_entry.unique_id = "001DC9A2C911"
    coordinator = SamsungClimateCoordinator(hass, controller, mock_entry)
    mock_entry.runtime_data = coordinator

    added_entities: list[Any] = []
    await async_setup_entry(hass, mock_entry, added_entities.extend)

    assert len(added_entities) == 3
    keys = [e.entity_description.key for e in added_entities]
    assert "error_status" in keys
    assert "error_code" in keys
    assert "vane_horizontal" in keys

    # Push a state update
    wmp_state = {
        "ONOFF": "ON",
        "ERRSTATUS": "ERR",
        "ERRCODE": "12",
        "VANELR": "SWING",
    }
    await controller.poller.async_update_properties_from_state(wmp_state, force_update=True)

    for entity in added_entities:
        entity._update_state()
        if entity.entity_description.key == "error_status":
            assert entity.native_value == "ERR"
        elif entity.entity_description.key == "error_code":
            assert entity.native_value == "12"
        elif entity.entity_description.key == "vane_horizontal":
            assert entity.native_value == "SWING"


def test_connection_intesisbox_create_updated_reuses_instance() -> None:
    """Test that ConnectionIntesisBox reuses the instance when parameters are unchanged."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1"},
        logger=_LOGGER,
    )
    # Empty, None, or unrelated nodes should return the exact same instance
    assert conn.create_updated(None) is conn
    assert conn.create_updated({}) is conn
    assert conn.create_updated({"value": "DRY"}) is conn
    assert conn.create_updated({"params": {}}) is conn
    assert conn.create_updated({"params": {"host": "127.0.0.1", "port": 3310}}) is conn

    # Different port/host should return a new instance
    new_conn = conn.create_updated({"params": {"port": 3312}})
    assert new_conn is not conn
    assert new_conn._port == 3312


@pytest.mark.asyncio
async def test_emulator_shared_state_and_broadcasting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that Emulator maintains shared state across multiple clients and broadcasts updates."""
    from custom_components.climate_ip_tools.emulator_intesisbox import Emulator

    pytest_socket.enable_socket()
    HASocketBlockedError.instances.clear()
    monkeypatch.setattr("asyncio.open_connection", _REAL_OPEN_CONNECTION)

    loop = asyncio.get_running_loop()
    Emulator.reset()
    server = await loop.create_server(Emulator, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    r1, w1 = await _REAL_OPEN_CONNECTION("127.0.0.1", port)
    r2, w2 = await _REAL_OPEN_CONNECTION("127.0.0.1", port)

    try:
        # Client 1 sets mode to FAN and turns on
        w1.write(b"SET,1:ONOFF,ON\r\n")
        await w1.drain()
        ack1 = await r1.readline()
        assert b"ACK" in ack1
        chn1 = await r1.readline()
        assert b"CHN,1:ONOFF,ON" in chn1

        # Client 2 should also have received the broadcast CHN notification
        chn2 = await r2.readline()
        assert b"CHN,1:ONOFF,ON" in chn2

        # Client 1 changes mode to FAN
        w1.write(b"SET,1:MODE,FAN\r\n")
        await w1.drain()
        ack2 = await r1.readline()
        assert b"ACK" in ack2
        chn3 = await r1.readline()
        assert b"CHN,1:MODE,FAN" in chn3
        chn3_temp = await r1.readline()
        assert b"CHN,1:SETPTEMP,32768" in chn3_temp
        chn4 = await r2.readline()
        assert b"CHN,1:MODE,FAN" in chn4
        chn4_temp = await r2.readline()
        assert b"CHN,1:SETPTEMP,32768" in chn4_temp

        # Client 2 now queries STATUS,1; it must see ONOFF,ON, MODE,FAN, and SETPTEMP,32768 in semicolon format
        w2.write(b"STATUS,1\r\n")
        await w2.drain()
        status_line = (await r2.readline()).decode().strip()
        assert status_line.startswith("STATUS,1:")
        assert "ONOFF,ON" in status_line
        assert "MODE,FAN" in status_line
        assert "SETPTEMP,32768" in status_line

        # Now client 1 switches from FAN to DRY
        w1.write(b"SET,1:MODE,DRY\r\n")
        await w1.drain()
        ack3 = await r1.readline()
        assert b"ACK" in ack3
        chn5 = await r1.readline()
        assert b"CHN,1:MODE,DRY" in chn5
        chn5_temp = await r1.readline()
        assert b"CHN,1:SETPTEMP,220" in chn5_temp
        chn6 = await r2.readline()
        assert b"CHN,1:MODE,DRY" in chn6
        chn6_temp = await r2.readline()
        assert b"CHN,1:SETPTEMP,220" in chn6_temp

        # Check state: ONOFF remains ON, MODE is DRY
        assert Emulator.shared_state["ONOFF"] == "ON"
        assert Emulator.shared_state["MODE"] == "DRY"

    finally:
        w1.close()
        w2.close()
        await w1.wait_closed()
        await w2.wait_closed()
        server.close()
        await server.wait_closed()
        pytest_socket.disable_socket()


@pytest.mark.asyncio
async def test_emulator_delayed_response_and_queued_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that Emulator delays responses and processes burst commands sequentially from queue."""
    from custom_components.climate_ip_tools.emulator_intesisbox import Emulator

    pytest_socket.enable_socket()
    HASocketBlockedError.instances.clear()
    monkeypatch.setattr("asyncio.open_connection", _REAL_OPEN_CONNECTION)

    loop = asyncio.get_running_loop()
    Emulator.reset()
    # Configure 0.15s delay per command
    server = await loop.create_server(Emulator, "127.0.0.1", 0)
    Emulator.delay = 0.15
    port = server.sockets[0].getsockname()[1]

    reader, writer = await _REAL_OPEN_CONNECTION("127.0.0.1", port)

    try:
        t0 = time.perf_counter()
        # Send two commands immediately in a single write without waiting
        writer.write(b"SET,1:ONOFF,ON\r\nSET,1:SETPTEMP,240\r\n")
        await writer.drain()

        # Read first response (ACK + CHN for ONOFF)
        ack1 = await reader.readline()
        t1 = time.perf_counter()
        assert b"ACK" in ack1
        assert (t1 - t0) >= 0.12, f"First command responded too fast: {t1 - t0:.3f}s"

        chn1 = await reader.readline()
        assert b"CHN,1:ONOFF,ON" in chn1

        # Read second response (ACK + CHN for SETPTEMP)
        ack2 = await reader.readline()
        t2 = time.perf_counter()
        assert b"ACK" in ack2
        assert (t2 - t0) >= 0.25, f"Second command responded too fast: {t2 - t0:.3f}s"

        chn2 = await reader.readline()
        assert b"CHN,1:SETPTEMP,240" in chn2

        # Verify state updated sequentially
        assert Emulator.shared_state["ONOFF"] == "ON"
        assert Emulator.shared_state["SETPTEMP"] == "240"

    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()
        pytest_socket.disable_socket()


@pytest.mark.asyncio
async def test_emulator_start_helper_with_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test start() helper with delay parameter and clean task teardown on disconnect."""
    from custom_components.climate_ip_tools.emulator_intesisbox import Emulator, start

    pytest_socket.enable_socket()
    HASocketBlockedError.instances.clear()
    monkeypatch.setattr("asyncio.open_connection", _REAL_OPEN_CONNECTION)

    server = await start(host="127.0.0.1", port=0, delay=0.2)
    port = server.sockets[0].getsockname()[1]
    assert Emulator.delay == 0.2

    _reader, writer = await _REAL_OPEN_CONNECTION("127.0.0.1", port)
    try:
        # Send command and close connection before delay expires
        writer.write(b"SET,1:MODE,COOL\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        # Allow event loop to process connection_lost and processor cancellation
        await asyncio.sleep(0.05)
    finally:
        server.close()
        await server.wait_closed()
        pytest_socket.disable_socket()


@pytest.mark.asyncio
async def test_connection_semicolon_status_parsing():
    """Verify ConnectionIntesisBox correctly parses real hardware semicolon-delimited STATUS,1 lines."""
    from custom_components.climate_ip.connection_intesisbox import ConnectionIntesisBox

    conn = ConnectionIntesisBox(
        config={"ip_address": "127.0.0.1"},
        logger=logging.getLogger("test"),
        ip_address="127.0.0.1",
    )
    push_updates = []
    async def _on_push(data):
        push_updates.append(data)
    conn.set_update_callback(_on_push)

    raw_status = (
        "STATUS,1:ONOFF,ON;MODE,DRY;FANSP,AUTO;VANEUD,AUTO;VANELR,AUTO;"
        "SETPTEMP,260;AMBTEMP,280;ERRSTATUS,OK;ERRCODE,0"
    )
    conn._process_incoming_line(raw_status)
    await asyncio.sleep(0)

    assert conn._device_status["ONOFF"] == "ON"
    assert conn._device_status["MODE"] == "DRY"
    assert conn._device_status["FANSP"] == "AUTO"
    assert conn._device_status["VANEUD"] == "AUTO"
    assert conn._device_status["VANELR"] == "AUTO"
    assert conn._device_status["SETPTEMP"] == "260"
    assert conn._device_status["AMBTEMP"] == "280"
    assert conn._device_status["ERRSTATUS"] == "OK"
    assert conn._device_status["ERRCODE"] == "0"

    assert len(push_updates) == 1
    assert push_updates[0]["ONOFF"] == "ON"
    assert push_updates[0]["MODE"] == "DRY"
    assert push_updates[0]["SETPTEMP"] == "260"
    assert push_updates[0]["AMBTEMP"] == "280"


@pytest.mark.asyncio
async def test_intesisbox_yaml_temperature_sentinel_and_idempotence(
    hass: HomeAssistant,
) -> None:
    """Verify intesisbox.yaml handles 32768 sentinel (None) and is idempotent against double division."""
    from custom_components.climate_ip.controller_yaml import YamlController

    hass.data = {}
    hass.config.units.temperature_unit = "°C"
    config = {
        CONF_CONFIG_FILE: "intesisbox.yaml",
        CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX,
        CONF_IP_ADDRESS: "127.0.0.1",
        CONF_PORT: 3310,
        CONF_MAC: "001DC9A2C911",
        CONF_TOKEN: "001DC9A2C911",
    }
    controller = YamlController(config, logger=_LOGGER, hass=hass)
    assert await controller.loader.async_initialize() is True
    await controller.loader.async_finish_initialization()
    assert controller.loader.is_fully_initialized is True

    # 1. FAN mode: SETPTEMP=32768 sentinel should evaluate to None
    fan_state = {
        "ONOFF": "ON",
        "MODE": "FAN",
        "SETPTEMP": "32768",
        "AMBTEMP": "280",
    }
    controller.poller._pure_network_state = dict(fan_state)
    if controller.loader.state_getter:
        controller.loader.state_getter._value = fan_state
    await controller.poller.async_update_properties_from_state(fan_state, force_update=True)

    assert controller.get_property("temperature") is None
    assert controller.get_property("current_temperature") == 28.0

    # 2. DRY mode: SETPTEMP=260 should evaluate to 26.0
    dry_state = {
        "ONOFF": "ON",
        "MODE": "DRY",
        "SETPTEMP": "260",
        "AMBTEMP": "280",
    }
    controller.poller._pure_network_state = dict(dry_state)
    if controller.loader.state_getter:
        controller.loader.state_getter._value = dry_state
    await controller.poller.async_update_properties_from_state(dry_state, force_update=True)

    assert controller.get_property("temperature") == 26.0
    assert controller.get_property("current_temperature") == 28.0

    # 3. Idempotence test: If state in memory is already converted (26.0 and 28.0), NO double division!
    already_converted_state = {
        "ONOFF": "ON",
        "MODE": "DRY",
        "SETPTEMP": 26.0,
        "AMBTEMP": 28.0,
    }
    controller.poller._pure_network_state = dict(already_converted_state)
    if controller.loader.state_getter:
        controller.loader.state_getter._value = already_converted_state
    await controller.poller.async_update_properties_from_state(already_converted_state, force_update=True)

    assert controller.get_property("temperature") == 26.0
    assert controller.get_property("current_temperature") == 28.0


@pytest.mark.asyncio
async def test_intesisbox_dry_mode_fan_coercion_and_validation(hass: HomeAssistant) -> None:
    """Test that switching to DRY mode forces FANSP AUTO and restricts fan modes to auto."""
    hass.data = {}
    hass.config.units.temperature_unit = "°C"
    config = {
        CONF_CONFIG_FILE: "intesisbox.yaml",
        CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX,
        CONF_IP_ADDRESS: "127.0.0.1",
        CONF_PORT: 3310,
        CONF_MAC: "001DC9A2C911",
        CONF_TOKEN: "001DC9A2C911",
    }
    controller = YamlController(config, logger=_LOGGER, hass=hass)
    assert await controller.loader.async_initialize() is True
    await controller.loader.async_finish_initialization()

    # 1. COOL mode with fan_mode=low (FANSP=2) and _LIMITS_FANSP="[AUTO,2,3,4]"
    cool_state = {
        "ONOFF": "ON",
        "MODE": "COOL",
        "SETPTEMP": "240",
        "FANSP": "2",
        "AMBTEMP": "260",
        "_LIMITS_FANSP": "[AUTO,2,3,4]",
    }
    controller.poller._pure_network_state = dict(cool_state)
    if controller.loader.state_getter:
        controller.loader.state_getter._value = cool_state
    await controller.poller.async_update_properties_from_state(cool_state, force_update=True)

    # In COOL mode with [AUTO,2,3,4], quiet (1) is excluded
    fan_op = controller.loader.operations["fan_mode"]
    valid_fan_modes = fan_op.values
    assert "auto" in valid_fan_modes
    assert "low" in valid_fan_modes
    assert "medium" in valid_fan_modes
    assert "high" in valid_fan_modes
    assert "quiet" not in valid_fan_modes
    assert controller.get_property("fan_mode") == "low"

    # If _LIMITS_FANSP contains "1" (e.g. [AUTO,1,2,3,4]), quiet is included
    cool_state_with_quiet = dict(cool_state)
    cool_state_with_quiet["_LIMITS_FANSP"] = "[AUTO,1,2,3,4]"
    controller.poller._pure_network_state = dict(cool_state_with_quiet)
    if controller.loader.state_getter:
        controller.loader.state_getter._value = cool_state_with_quiet
    await controller.poller.async_update_properties_from_state(cool_state_with_quiet, force_update=True)
    valid_with_quiet = fan_op.values
    assert "quiet" in valid_with_quiet
    assert "low" in valid_with_quiet
    assert "medium" in valid_with_quiet
    assert "high" in valid_with_quiet

    # 2. When switching to DRY mode, verify command template emits SET,1:FANSP,AUTO then SET,1:MODE,DRY
    with patch.object(ConnectionIntesisBox, "async_execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = ("{}", {})
        res = await controller.async_set_property("hvac_mode", "dry")
        assert res is True
        sent_data = mock_exec.call_args[0][2]
        assert "SET,1:FANSP,AUTO" in sent_data
        assert "SET,1:MODE,DRY" in sent_data
        # Ensure FANSP,AUTO precedes MODE,DRY
        assert sent_data.index("SET,1:FANSP,AUTO") < sent_data.index("SET,1:MODE,DRY")

    # 3. DRY mode: only 'auto' is valid in fan_modes
    dry_state = {
        "ONOFF": "ON",
        "MODE": "DRY",
        "SETPTEMP": "240",
        "FANSP": "AUTO",
        "AMBTEMP": "260",
        "_LIMITS_FANSP": "[AUTO,2,3,4]",
    }
    controller.poller._pure_network_state = dict(dry_state)
    if controller.loader.state_getter:
        controller.loader.state_getter._value = dry_state
    await controller.poller.async_update_properties_from_state(dry_state, force_update=True)

    dry_fan_modes = fan_op.values
    assert dry_fan_modes == ["auto"]
    assert controller.get_property("fan_mode") == "auto"

    # 4. Even if device_state had FANSP='2' in DRY mode, status_template forces 'auto'
    inconsistent_dry_state = {
        "ONOFF": "ON",
        "MODE": "DRY",
        "SETPTEMP": "240",
        "FANSP": "2",
        "AMBTEMP": "260",
    }
    controller.poller._pure_network_state = dict(inconsistent_dry_state)
    if controller.loader.state_getter:
        controller.loader.state_getter._value = inconsistent_dry_state
    await controller.poller.async_update_properties_from_state(inconsistent_dry_state, force_update=True)
    assert controller.get_property("fan_mode") == "auto"

    # 5. Setting fan_mode to low while in DRY mode produces empty command (no-op)
    with patch.object(ConnectionIntesisBox, "async_execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = ("{}", {})
        await controller.async_set_property("fan_mode", "low")
        if mock_exec.called:
            sent = mock_exec.call_args[0][2]
            assert "SET,1:FANSP,2" not in sent

    # 6. Optimistic cascade check: when switching to dry, FANSP cascades to AUTO
    state_for_cascade = {"ONOFF": "ON", "MODE": "COOL", "FANSP": "2"}
    hvac_op = controller.loader.operations["hvac_mode"]
    hvac_op.apply_optimistic_cascades(state_for_cascade, "dry")
    assert state_for_cascade["FANSP"] == "AUTO"


@pytest.mark.asyncio
async def test_intesisbox_loop_breaker_auto_pruning(hass: HomeAssistant) -> None:
    """Test that rapid fan speed oscillation triggers emergency brake, and only prunes values defined in YAML."""
    config = {
        CONF_IP_ADDRESS: "127.0.0.1",
        CONF_PORT: 3310,
    }
    hass.async_create_task.side_effect = asyncio.create_task
    conn = ConnectionIntesisBox(config, _LOGGER, hass=hass)
    conn.load_from_yaml(
        {
            "loop_breakers": [
                {
                    "node": "FANSP",
                    "fallback_value": "AUTO",
                    "fallback_command": "SET,1:FANSP,AUTO",
                    "prune_values": ["1"],
                    "prune_command_template": "LIMITS:FANSP,{{new_limits}}",
                    "threshold": 3,
                    "window_seconds": 3.0,
                }
            ]
        },
        None,
    )
    conn._limits["FANSP"] = "[AUTO,1,2,3,4]"

    # Mock _send_raw to capture emergency commands
    sent_commands: list[str] = []

    async def fake_send_raw(payload: str) -> None:
        sent_commands.append(payload)

    conn._send_raw = fake_send_raw

    # Case A: Oscillation with '1' (quiet) -> in prune_values -> brake + prune
    conn._process_incoming_line("CHN,1:FANSP,1")
    conn._process_incoming_line("CHN,1:FANSP,AUTO")
    conn._process_incoming_line("CHN,1:FANSP,1")
    conn._process_incoming_line("CHN,1:FANSP,AUTO")

    await asyncio.sleep(0.05)

    assert "SET,1:FANSP,AUTO\r\n" in sent_commands
    assert "LIMITS:FANSP,[AUTO,2,3,4]\r\n" in sent_commands
    assert conn._limits["FANSP"] == "[AUTO,2,3,4]"
    assert conn._device_status["_LIMITS_FANSP"] == "[AUTO,2,3,4]"

    # Case B: Oscillation with '2' (low) -> NOT in prune_values -> brake only, NO pruning
    sent_commands.clear()
    conn._process_incoming_line("CHN,1:FANSP,2")
    conn._process_incoming_line("CHN,1:FANSP,AUTO")
    conn._process_incoming_line("CHN,1:FANSP,2")
    conn._process_incoming_line("CHN,1:FANSP,AUTO")

    await asyncio.sleep(0.05)

    assert "SET,1:FANSP,AUTO\r\n" in sent_commands
    # Must NOT prune 2
    assert not any("LIMITS" in cmd for cmd in sent_commands)
    assert conn._limits["FANSP"] == "[AUTO,2,3,4]"

    # Case C: Oscillation between '1' and '4' (real AC bounce against HIGH) -> in prune_values -> brake + prune
    conn._limits["FANSP"] = "[AUTO,1,2,3,4]"
    conn._device_status["_LIMITS_FANSP"] = "[AUTO,1,2,3,4]"
    sent_commands.clear()
    conn._process_incoming_line("CHN,1:FANSP,4")
    conn._process_incoming_line("CHN,1:FANSP,1")
    conn._process_incoming_line("CHN,1:FANSP,4")
    conn._process_incoming_line("CHN,1:FANSP,1")

    await asyncio.sleep(0.05)

    assert "SET,1:FANSP,AUTO\r\n" in sent_commands
    assert "LIMITS:FANSP,[AUTO,2,3,4]\r\n" in sent_commands
    assert conn._limits["FANSP"] == "[AUTO,2,3,4]"


@pytest.mark.asyncio
async def test_emulator_ducted_ac_oscillation_and_loop_breaker(
    monkeypatch: pytest.MonkeyPatch, hass: HomeAssistant
) -> None:
    """Test ducted AC simulation on emulator: speed 1 triggers oscillation loop until loop breaker restores AUTO."""
    from custom_components.climate_ip_tools.emulator_intesisbox import (
        LIMITS,
        Emulator,
        start,
    )

    pytest_socket.enable_socket()
    HASocketBlockedError.instances.clear()
    monkeypatch.setattr("asyncio.open_connection", _REAL_OPEN_CONNECTION)

    # 1. Start emulator in ducted AC mode
    server = await start(host="127.0.0.1", port=0, duct_ac=True)
    port = server.sockets[0].getsockname()[1]
    assert Emulator.duct_ac is True
    assert LIMITS["FANSP"] == "[AUTO,1,2,3,4]"

    # 2. Connect client ConnectionIntesisBox with loop breakers configured
    hass.async_create_task.side_effect = asyncio.create_task
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: port},
        logger=_LOGGER,
        hass=hass,
    )
    conn.load_from_yaml(
        {
            "loop_breakers": [
                {
                    "node": "FANSP",
                    "fallback_value": "AUTO",
                    "fallback_command": "SET,1:FANSP,AUTO",
                    "prune_values": ["1"],
                    "prune_command_template": "LIMITS:FANSP,{{new_limits}}",
                    "threshold": 3,
                    "window_seconds": 3.0,
                }
            ]
        },
        None,
    )

    try:
        await conn.async_connect()
        assert conn._is_connected is True
        assert conn._limits.get("FANSP") == "[AUTO,1,2,3,4]"

        # 3. Request speed 1 (quiet) against ducted AC
        await conn._send_raw("SET,1:FANSP,1\r\n")

        # 4. Wait for the oscillation loop to run and loop breaker to trigger
        # Oscillation takes: 0.25s (AUTO) + 0.25s (1) + 0.25s (AUTO) = ~0.75s to reach 3 alternations
        # Loop breaker sends SET,1:FANSP,AUTO and LIMITS:FANSP,[AUTO,2,3,4]
        for _ in range(30):
            await asyncio.sleep(0.1)
            if (
                Emulator._oscillation_task is None
                and conn._limits.get("FANSP") == "[AUTO,2,3,4]"
            ):
                break

        # 5. Verify emulator oscillation stopped, speed is AUTO, and limits were pruned
        assert Emulator._oscillation_task is None
        assert Emulator.shared_state.get("FANSP") == "AUTO"
        assert conn._device_status.get("FANSP") == "AUTO"
        assert conn._limits.get("FANSP") == "[AUTO,2,3,4]"
        assert LIMITS["FANSP"] == "[AUTO,2,3,4]"

    finally:
        await conn.close()
        server.close()
        await server.wait_closed()
        Emulator.reset()
        pytest_socket.disable_socket()


@pytest.mark.asyncio
async def test_emulator_ducted_ac_direct_socket_loop_and_exit_on_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that ducted AC emulator oscillates until an explicit AUTO command is sent."""
    from custom_components.climate_ip_tools.emulator_intesisbox import (
        Emulator,
        start,
    )

    pytest_socket.enable_socket()
    HASocketBlockedError.instances.clear()
    monkeypatch.setattr("asyncio.open_connection", _REAL_OPEN_CONNECTION)

    server = await start(host="127.0.0.1", port=0, duct_ac=True)
    port = server.sockets[0].getsockname()[1]

    reader, writer = await _REAL_OPEN_CONNECTION("127.0.0.1", port)

    try:
        # Request speed 1
        writer.write(b"SET,1:FANSP,1\r\n")
        await writer.drain()

        # Read ACK and immediate CHN,1:FANSP,1
        ack = await reader.readline()
        assert b"ACK" in ack
        chn1 = await reader.readline()
        assert b"CHN,1:FANSP,1" in chn1
        assert Emulator._oscillation_task is not None

        # Receive bus rejection oscillation (AUTO followed by 1)
        chn_auto = await reader.readline()
        assert b"CHN,1:FANSP,AUTO" in chn_auto
        chn_1_again = await reader.readline()
        assert b"CHN,1:FANSP,1" in chn_1_again

        # Loop continues while task is active
        assert not Emulator._oscillation_task.done()

        # Sending a non-AUTO speed does NOT break the loop
        writer.write(b"SET,1:FANSP,2\r\n")
        await writer.drain()
        ack2 = await reader.readline()
        assert b"ACK" in ack2
        chn2 = await reader.readline()
        assert b"CHN,1:FANSP,2" in chn2
        assert Emulator._oscillation_task is not None
        assert not Emulator._oscillation_task.done()

        # Sending SET,1:FANSP,AUTO immediately terminates the oscillation loop
        writer.write(b"SET,1:FANSP,AUTO\r\n")
        await writer.drain()
        ack_auto = await reader.readline()
        assert b"ACK" in ack_auto
        chn_final = await reader.readline()
        assert b"CHN,1:FANSP,AUTO" in chn_final

        # Allow task cancellation to settle
        await asyncio.sleep(0.05)
        assert Emulator._oscillation_task is None
        assert Emulator.shared_state["FANSP"] == "AUTO"

    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()
        Emulator.reset()
        pytest_socket.disable_socket()


@pytest.mark.asyncio
async def test_intesisbox_yaml_parameterized_configuration(hass: HomeAssistant) -> None:
    """Test that all hardcoded values (ac_num, timeouts, handshake commands, limits_prefix) are configurable via YAML."""
    config = {
        CONF_IP_ADDRESS: "127.0.0.1",
        CONF_PORT: 3310,
    }
    conn = ConnectionIntesisBox(config, _LOGGER, hass=hass)

    # 1. Verify defaults
    assert conn._ac_num == 1
    assert conn._command_timeout == 5.0
    assert conn._connect_timeout == 10.0
    assert conn._handshake_timeout == 3.0
    assert conn._limits_prefix == "_LIMITS_"
    assert conn._get_handshake_commands() == ["ID", "LIMITS:*", "STATUS,1", "GET,1:*"]

    # 2. Load custom configuration from YAML
    yaml_node = {
        "params": {
            "ac_num": 2,
            "command_timeout": 2.5,
            "connect_timeout": 4.0,
            "handshake_timeout": 1.5,
            "limits_prefix": "_CUSTOM_LIMITS_",
        },
        "handshake_commands": [
            "ID",
            "LIMITS:*",
            "STATUS,{{ac_num}}",
            "CUSTOM,{{ac_num}}",
        ],
    }
    conn.load_from_yaml(yaml_node, None)

    assert conn._ac_num == 2
    assert conn._command_timeout == 2.5
    assert conn._connect_timeout == 4.0
    assert conn._handshake_timeout == 1.5
    assert conn._limits_prefix == "_CUSTOM_LIMITS_"
    assert conn._get_handshake_commands() == [
        "ID",
        "LIMITS:*",
        "STATUS,2",
        "CUSTOM,2",
    ]

    # 3. Test propagation in create_updated
    updated_conn = conn.create_updated(
        {
            "params": {
                "host": "192.168.1.150",
                "port": 3311,
            }
        }
    )
    assert updated_conn._host == "192.168.1.150"
    assert updated_conn._port == 3311
    assert updated_conn._ac_num == 2
    assert updated_conn._command_timeout == 2.5
    assert updated_conn._connect_timeout == 4.0
    assert updated_conn._handshake_timeout == 1.5
    assert updated_conn._limits_prefix == "_CUSTOM_LIMITS_"
    assert updated_conn._get_handshake_commands() == [
        "ID",
        "LIMITS:*",
        "STATUS,2",
        "CUSTOM,2",
    ]

    # 4. Test limits parsing using custom limits_prefix
    conn._process_incoming_line("LIMITS:FANSP,[AUTO,1,2,3,4]")
    assert conn._device_status["_CUSTOM_LIMITS_FANSP"] == "[AUTO,1,2,3,4]"

    # 5. Test polling command uses data from status.connection_template
    sent_cmds: list[str] = []

    async def fake_send_raw(payload: str) -> None:
        sent_cmds.append(payload)

    conn._send_raw = fake_send_raw
    conn._is_connected = True
    conn._writer = MagicMock()
    conn._writer.is_closing.return_value = False

    # Poll with explicit data from YAML template
    await conn.async_execute(None, None, data="STATUS,2", headers=None, _is_poll=True)
    assert sent_cmds[-1] == "STATUS,2\r\n"

    # Poll without data defaults to f"STATUS,{self._ac_num}"
    await conn.async_execute(None, None, data=None, headers=None, _is_poll=True)
    assert sent_cmds[-1] == "STATUS,2\r\n"


@pytest.mark.asyncio
async def test_intesisbox_swing_mode_dynamic_limits(hass: HomeAssistant) -> None:
    """Test that swing_mode dynamically adapts to VANEUD and VANELR limits (Option A)."""
    hass.data = {}
    hass.config.units.temperature_unit = "°C"
    config = {
        CONF_CONFIG_FILE: "intesisbox.yaml",
        CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX,
        CONF_IP_ADDRESS: "192.168.1.101",
        CONF_PORT: 3310,
        CONF_MAC: "001DC982C938",
        CONF_TOKEN: "001DC982C938",
    }
    controller = YamlController(config, logger=_LOGGER, hass=hass)
    assert await controller.loader.async_initialize() is True
    await controller.loader.async_finish_initialization()

    # Scenario 1: Real AC with [AUTO,SWING,PULSE] on both VANEUD and VANELR
    state_real_ac = {
        "ONOFF": "ON",
        "MODE": "COOL",
        "SETPTEMP": "240",
        "FANSP": "AUTO",
        "VANEUD": "AUTO",
        "VANELR": "AUTO",
        "AMBTEMP": "260",
        "_LIMITS_VANEUD": "[AUTO,SWING,PULSE]",
        "_LIMITS_VANELR": "[AUTO,SWING,PULSE]",
    }
    controller.poller._pure_network_state = dict(state_real_ac)
    await controller.poller.async_update_properties_from_state(
        state_real_ac, force_update=True
    )

    climate_state = controller.climate_state
    # swing_modes must include off, vertical, horizontal, both, pulse, and EXCLUDE 1..5
    assert set(climate_state.swing_modes) == {"off", "vertical", "horizontal", "both", "pulse"}
    assert "1" not in climate_state.swing_modes
    assert "2" not in climate_state.swing_modes
    assert climate_state.swing_mode == "off"

    # Test status_template parsing of swing states
    state_real_ac["VANEUD"] = "SWING"
    state_real_ac["VANELR"] = "SWING"
    await controller.poller.async_update_properties_from_state(
        state_real_ac, force_update=True
    )
    assert controller.climate_state.swing_mode == "both"

    state_real_ac["VANEUD"] = "AUTO"
    state_real_ac["VANELR"] = "SWING"
    await controller.poller.async_update_properties_from_state(
        state_real_ac, force_update=True
    )
    assert controller.climate_state.swing_mode == "horizontal"

    state_real_ac["VANEUD"] = "PULSE"
    state_real_ac["VANELR"] = "AUTO"
    await controller.poller.async_update_properties_from_state(
        state_real_ac, force_update=True
    )
    assert controller.climate_state.swing_mode == "pulse"

    # Test command generation for Option A
    with patch.object(
        ConnectionIntesisBox, "async_execute", new_callable=AsyncMock
    ) as mock_exec:
        mock_exec.return_value = ("{}", {})

        # Vertical swing
        await controller.async_set_property("swing_mode", "vertical")
        sent = mock_exec.call_args[0][2]
        assert "SET,1:VANEUD,SWING" in sent

        # Both swing
        await controller.async_set_property("swing_mode", "both")
        sent = mock_exec.call_args[0][2]
        assert "SET,1:VANEUD,SWING" in sent
        assert "SET,1:VANELR,SWING" in sent

        # Horizontal swing
        await controller.async_set_property("swing_mode", "horizontal")
        sent = mock_exec.call_args[0][2]
        assert "SET,1:VANELR,SWING" in sent

        # Pulse mode
        await controller.async_set_property("swing_mode", "pulse")
        sent = mock_exec.call_args[0][2]
        assert "SET,1:VANEUD,PULSE" in sent

    # Scenario 2: Standard unit with fixed positions and no horizontal vane
    controller.poller._pending_updates.clear()
    state_positions_ac = {
        "ONOFF": "ON",
        "MODE": "COOL",
        "SETPTEMP": "240",
        "FANSP": "AUTO",
        "VANEUD": "1",
        "AMBTEMP": "260",
        "_LIMITS_VANEUD": "[AUTO,1,2,3,4,5,SWING]",
        "_LIMITS_VANELR": "",
    }
    controller.poller._pure_network_state = dict(state_positions_ac)
    await controller.poller.async_update_properties_from_state(
        state_positions_ac, force_update=True
    )

    climate_state2 = controller.climate_state
    assert set(climate_state2.swing_modes) == {"off", "vertical", "1", "2", "3", "4", "5"}
    assert "horizontal" not in climate_state2.swing_modes
    assert "both" not in climate_state2.swing_modes
    assert "pulse" not in climate_state2.swing_modes
    assert climate_state2.swing_mode == "1"


# ---------------------------------------------------------------------------
# 11. Targeted Mutant Killing & Comprehensive Coverage Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_intesisbox_set_update_callback_controller_fallback_and_linking() -> None:
    """Kill L216-217 mutants in set_update_callback.

    Test callback fallback to controller.on_push_update_callback when None is passed,
    and ensure explicit callback is preserved and not overwritten.
    """
    conn = ConnectionIntesisBox(config={CONF_IP_ADDRESS: "127.0.0.1"}, logger=_LOGGER)

    # 1. Controller has callable on_push_update_callback
    mock_controller = MagicMock()
    controller_cb = AsyncMock()
    mock_controller.on_push_update_callback = controller_cb
    conn.set_controller_ref(mock_controller)

    # Pass None: must link controller callback
    conn.set_update_callback(None)
    assert conn._update_callback == controller_cb

    # 2. Pass explicit user callback: must NOT overwrite with controller callback
    user_cb = AsyncMock()
    conn.set_update_callback(user_cb)
    assert conn._update_callback == user_cb

    # 3. Controller has non-callable on_push_update_callback: must stay None
    mock_controller2 = MagicMock()
    mock_controller2.on_push_update_callback = "not_a_callable"
    conn2 = ConnectionIntesisBox(config={CONF_IP_ADDRESS: "127.0.0.1"}, logger=_LOGGER)
    conn2.set_controller_ref(mock_controller2)
    conn2.set_update_callback(None)
    assert conn2._update_callback is None


def test_intesisbox_load_from_yaml_handshake_single_string() -> None:
    """Kill L153 untested mutants in load_from_yaml.

    Test when handshake_commands is configured as a single string instead of a list.
    """
    conn = ConnectionIntesisBox(config={CONF_IP_ADDRESS: "127.0.0.1"}, logger=_LOGGER)
    success = conn.load_from_yaml(
        {"handshake_commands": "STATUS,{{ac_num}}"},
        None,
    )
    assert success is True
    assert conn._handshake_commands == [f"STATUS,{conn._ac_num}"]


@pytest.mark.asyncio
async def test_intesisbox_process_line_ack_err_without_pending_ack() -> None:
    """Kill L325 and L330 mutants in _process_incoming_line.

    When _pending_ack is None, receiving ACK or ERR must safely return without
    AttributeError (mutant mutates 'and not' to 'or not' which calls None.done()).
    """
    conn = ConnectionIntesisBox(config={CONF_IP_ADDRESS: "127.0.0.1"}, logger=_LOGGER)
    conn._pending_ack = None

    # Should not raise AttributeError: 'NoneType' object has no attribute 'done'
    conn._process_incoming_line("ACK")
    conn._process_incoming_line("ERR")
    assert conn._pending_ack is None


@pytest.mark.asyncio
async def test_intesisbox_process_line_splits_with_multiple_colons_and_commas(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill L321, L343, L373, and L381 mutants in _process_incoming_line.

    Test that protocol splitting uses maxsplit=1:
    - L321: verify RX logger format contains 'RX:'
    - L343: LIMITS with extra colon in payload does not fail unpacking
    - L373: STATUS / CHN with extra colon does not fail unpacking
    - L381: UID,val item with extra comma does not fail unpacking
    """
    conn = ConnectionIntesisBox(config={CONF_IP_ADDRESS: "127.0.0.1"}, logger=_LOGGER)

    with caplog.at_level(logging.DEBUG):
        # L321: test logger RX formatting
        conn._process_incoming_line("ACK")
        assert "RX: 'ACK'" in caplog.text

    # L343: LIMITS with extra colon in payload: "LIMITS:FANSP,[AUTO,1:2,3]"
    conn._process_incoming_line("LIMITS:FANSP,[AUTO,1:2,3]")
    assert conn._limits.get("FANSP") == "[AUTO,1:2,3]"
    assert conn._device_status.get("_LIMITS_FANSP") == "[AUTO,1:2,3]"

    # L373: STATUS line with extra colon: "STATUS,1:EXTRA:COLON,VAL"
    conn._process_incoming_line("STATUS,1:EXTRA:COLON,VAL")
    assert conn._device_status.get("EXTRA:COLON") == "VAL"

    # L381: Item with extra comma in value: "1:DATA,VAL1,VAL2"
    conn._process_incoming_line("1:DATA,VAL1,VAL2")
    assert conn._device_status.get("DATA") == "VAL1,VAL2"


@pytest.mark.asyncio
async def test_intesisbox_process_line_awaitable_object_and_hass_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill L354, L397, L398, and L403 mutants in _process_incoming_line.

    - L354 & L397: Non-coroutine awaitables (custom __await__) must be scheduled
      via hass.async_create_task (mutant changes 'or hasattr(__await__)' to 'and hasattr(__await__)').
    - L398: If self._hass is not None but lacks async_create_task, fall back to asyncio.create_task.
    - L403: Callback raising exception is caught and logged as error.
    """
    class CustomAwaitable:
        def __await__(self):
            async def _dummy():
                return None
            return _dummy().__await__()

    conn = ConnectionIntesisBox(config={CONF_IP_ADDRESS: "127.0.0.1"}, logger=_LOGGER)
    mock_hass = MagicMock()
    conn._hass = mock_hass

    # 1. Test L397 with custom awaitable in state update
    custom_state_awaitable = CustomAwaitable()
    conn.set_update_callback(lambda data: custom_state_awaitable)
    conn._process_incoming_line("1:ONOFF,ON")
    mock_hass.async_create_task.assert_called_with(custom_state_awaitable)

    # 2. Test L354 with custom awaitable in LIMITS update
    custom_limits_awaitable = CustomAwaitable()
    conn.set_update_callback(lambda data: custom_limits_awaitable)
    conn._process_incoming_line("LIMITS:MODE,[AUTO,COOL]")
    mock_hass.async_create_task.assert_called_with(custom_limits_awaitable)

    # 3. Test L398: hass object without async_create_task falls back to asyncio.create_task
    coro_executed = False

    async def real_coro():
        nonlocal coro_executed
        coro_executed = True

    conn._hass = object()  # Truthy, but lacks async_create_task
    conn.set_update_callback(lambda data: real_coro())
    conn._process_incoming_line("1:ONOFF,ON")
    await asyncio.sleep(0.02)
    assert coro_executed is True

    # 4. Test L403: Callback raising exception
    def broken_callback(data):
        raise RuntimeError("Callback explosion")

    conn.set_update_callback(broken_callback)
    with caplog.at_level(logging.ERROR):
        conn._process_incoming_line("1:ONOFF,OFF")
        assert "Failed dispatching push update" in caplog.text


@pytest.mark.asyncio
async def test_intesisbox_loop_breaker_state_node_and_custom_rule_attributes(
    hass: HomeAssistant,
) -> None:
    """Kill L412, L420, L421, L422, and L423 mutants in loop breaker evaluation.

    - L412: rule using 'state_node' instead of 'node'.
    - L420: custom non-default fallback_value ("CUSTOM_STOP").
    - L421: custom non-default threshold (2 instead of default 3).
    - L422: custom non-default window_seconds (1.5 instead of default 3.0).
    - L423: custom non-default prune_values (["CUSTOM_PRUNE"]).
    """
    hass.async_create_task.side_effect = asyncio.create_task
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
        hass=hass,
    )
    conn.load_from_yaml(
        {
            "loop_breakers": [
                {
                    "state_node": "FANSP",  # Tests L412
                    "fallback_value": "CUSTOM_STOP",  # Tests L420
                    "fallback_command": "SET,1:FANSP,CUSTOM_STOP",
                    "threshold": 2,  # Tests L421 (triggers on 2 alternations / 3 values)
                    "window_seconds": 1.5,  # Tests L422
                    "prune_values": ["CUSTOM_PRUNE"],  # Tests L423
                    "prune_command_template": "LIMITS:FANSP,{{new_limits}}",
                }
            ]
        },
        None,
    )
    conn._limits["FANSP"] = "[CUSTOM_STOP,CUSTOM_PRUNE,OTHER]"

    sent_commands: list[str] = []

    async def fake_send_raw(payload: str) -> None:
        sent_commands.append(payload)

    conn._send_raw = fake_send_raw

    # Send 3 alternating values: CUSTOM_PRUNE -> CUSTOM_STOP -> CUSTOM_PRUNE (2 alternations)
    conn._process_incoming_line("CHN,1:FANSP,CUSTOM_PRUNE")
    conn._process_incoming_line("CHN,1:FANSP,CUSTOM_STOP")
    conn._process_incoming_line("CHN,1:FANSP,CUSTOM_PRUNE")

    await asyncio.sleep(0.05)

    assert "SET,1:FANSP,CUSTOM_STOP\r\n" in sent_commands
    assert "LIMITS:FANSP,[CUSTOM_STOP,OTHER]\r\n" in sent_commands
    assert conn._limits["FANSP"] == "[CUSTOM_STOP,OTHER]"
    assert conn._device_status["FANSP"] == "CUSTOM_STOP"


@pytest.mark.asyncio
async def test_intesisbox_loop_breaker_window_purging_and_alternation_boundary() -> None:
    """Kill L429, L433, and L451 mutants in _evaluate_oscillation_rule.

    - L429: Expired history entries outside window_seconds must be pruned.
    - L433: len(active_hist) >= threshold + 1 boundary.
    - L451: Alternations loop starts at index 1 (mutant range(len(...)) falsely compares index 0 to -1).
    """
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    rule = {
        "node": "FANSP",
        "fallback_value": "AUTO",
        "threshold": 4,  # Requires 4 alternations (at least 5 values)
        "window_seconds": 2.0,
    }
    conn._loop_breakers = [rule]

    sent_commands: list[str] = []

    async def fake_send(payload: str) -> None:
        sent_commands.append(payload)

    conn._send_raw = fake_send

    # 1. L429: History window purging test
    now = time.monotonic()
    # Inject old entry 10 seconds ago
    conn._node_history["FANSP"] = [(now - 10.0, "OLD_VAL")]
    conn._evaluate_oscillation_rule("FANSP", "VAL1", rule)
    # The old entry must be purged, leaving only VAL1
    assert len(conn._node_history["FANSP"]) == 1
    assert conn._node_history["FANSP"][0][1] == "VAL1"

    # 2. L433 & L451: Test 4 alternating values ["A", "B", "A", "B"] with threshold=4
    # Real alternations: A->B (1), B->A (2), A->B (3) = 3 alternations.
    # Mutant range(len(...)) at i=0 compares active_hist[0] ("A") with active_hist[-1] ("B"),
    # falsely adding a 4th alternation and triggering prematurely!
    conn._node_history.clear()
    sent_commands.clear()

    conn._process_incoming_line("CHN,1:FANSP,A")
    conn._process_incoming_line("CHN,1:FANSP,B")
    conn._process_incoming_line("CHN,1:FANSP,A")
    conn._process_incoming_line("CHN,1:FANSP,B")

    await asyncio.sleep(0.02)
    # Must NOT have triggered because 3 alternations < threshold (4)
    assert len(sent_commands) == 0

    # 3. Add 5th alternating value "A" -> 4 alternations reached, triggers!
    conn._process_incoming_line("CHN,1:FANSP,A")
    await asyncio.sleep(0.02)
    assert conn._device_status["FANSP"] == "AUTO"


@pytest.mark.asyncio
async def test_intesisbox_loop_breaker_else_branch_and_value_selection() -> None:
    """Kill L438, L441, L442, L443, L446-447, and L449 mutants.

    Test oscillation between two values where NEITHER is in prune_values
    and NEITHER is fallback_value. This executes the L446-447 else branch.
    """
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    rule = {
        "node": "FANSP",
        "fallback_value": "AUTO",
        "fallback_command": "SET,1:FANSP,AUTO",
        "prune_values": ["1"],  # '2' and '3' are not in prune_values
        "threshold": 3,
        "window_seconds": 5.0,
    }
    conn._loop_breakers = [rule]
    conn._limits["FANSP"] = "[AUTO,1,2,3,4]"

    sent_commands: list[str] = []

    async def fake_send(payload: str) -> None:
        sent_commands.append(payload)

    conn._send_raw = fake_send

    # Alternate between '2' and '3' (neither is '1', neither is 'AUTO')
    conn._process_incoming_line("CHN,1:FANSP,2")
    conn._process_incoming_line("CHN,1:FANSP,3")
    conn._process_incoming_line("CHN,1:FANSP,2")
    conn._process_incoming_line("CHN,1:FANSP,3")

    await asyncio.sleep(0.05)

    # Fallback command sent, but neither 2 nor 3 is pruned
    assert "SET,1:FANSP,AUTO\r\n" in sent_commands
    assert conn._limits["FANSP"] == "[AUTO,1,2,3,4]"
    assert conn._device_status["FANSP"] == "AUTO"


@pytest.mark.asyncio
async def test_intesisbox_loop_breaker_without_hass_and_callback_and_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill L465, L472-473, L526, L527, and L532 mutants in loop breaker execution.

    - L465 & L472-473: Connection with hass=None creates asyncio.create_task.
    - L526 & L527: Update callback receives payload during loop break.
    - L532: Error in _send_raw during loop break is logged.
    """
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
        hass=None,  # hass=None forces L472-473 branch
    )
    callback_received: list[dict[str, Any]] = []

    async def mock_cb(payload: dict[str, Any]) -> None:
        callback_received.append(payload)

    conn.set_update_callback(mock_cb)

    # 1. Normal execution with callback
    rule = {
        "node": "FANSP",
        "fallback_value": "AUTO",
        "fallback_command": "SET,1:FANSP,AUTO",
        "threshold": 2,
        "window_seconds": 3.0,
    }
    conn._loop_breakers = [rule]
    sent_commands: list[str] = []

    async def fake_send(payload: str) -> None:
        sent_commands.append(payload)

    conn._send_raw = fake_send

    conn._process_incoming_line("CHN,1:FANSP,1")
    conn._process_incoming_line("CHN,1:FANSP,AUTO")
    conn._process_incoming_line("CHN,1:FANSP,1")

    await asyncio.sleep(0.05)

    assert "SET,1:FANSP,AUTO\r\n" in sent_commands
    assert len(callback_received) >= 1
    assert callback_received[-1].get("FANSP") == "AUTO"

    # 2. Test L532: Exception in _send_raw during loop break
    async def broken_send(payload: str) -> None:
        raise OSError("Socket write failure")

    conn._send_raw = broken_send
    with caplog.at_level(logging.ERROR):
        await conn._async_execute_loop_break("FANSP", "1", "AUTO", rule)
        assert "Error executing loop breaker" in caplog.text


@pytest.mark.asyncio
async def test_intesisbox_async_connect_handshake_failure_and_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill L268 and L277 mutants in async_connect.

    - L268: Initial handshake send exception is caught and logged as warning.
    - L277: Handshake wait timeout is caught cleanly without error.
    """
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    conn._connect_timeout = 1.0
    conn._handshake_timeout = 0.01

    mock_reader = AsyncMock()
    mock_reader.readline = AsyncMock(return_value=b"")
    mock_writer = MagicMock()
    mock_writer.is_closing.return_value = False
    mock_writer.drain = AsyncMock()
    mock_writer.write = MagicMock()

    # 1. Test L268: handshake command send fails
    async def broken_send(payload: str) -> None:
        raise OSError("Handshake network error")

    conn._send_raw = broken_send

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with caplog.at_level(logging.WARNING):
            await conn.async_connect()
            assert "Initial handshake send failed" in caplog.text

    await conn.close()

    # 2. Test L277: Handshake wait timeout logs debug message
    conn2 = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    conn2._connect_timeout = 1.0
    conn2._handshake_timeout = 0.01

    mock_reader2 = AsyncMock()
    # Keep readline waiting
    async def hanging_read() -> bytes:
        await asyncio.sleep(999)
        return b""
    mock_reader2.readline = AsyncMock(side_effect=hanging_read)

    with patch("asyncio.open_connection", return_value=(mock_reader2, mock_writer)):
        with caplog.at_level(logging.DEBUG):
            await conn2.async_connect()
            assert "Handshake wait timed out" in caplog.text

    await conn2.close()


@pytest.mark.asyncio
async def test_intesisbox_reader_loop_eof_and_unexpected_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill L297, L311, and L312 mutants in _reader_loop.

    - L297: Remote closes TCP connection (EOF readline returns b"") -> warning logged, loop breaks.
    - L311-312: Unexpected exception in reader loop while not closing -> error logged.
    """
    # 1. Test L297: EOF handling
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    mock_reader = AsyncMock()
    mock_reader.readline.return_value = b""  # EOF
    conn._reader = mock_reader
    conn._is_connected = True

    with caplog.at_level(logging.WARNING):
        await conn._reader_loop()
        assert "Remote closed TCP connection (EOF)" in caplog.text
        assert conn._is_connected is False

    # 2. Test L311-312: Unexpected exception in reader loop
    conn2 = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    mock_reader2 = AsyncMock()
    mock_reader2.readline.side_effect = ConnectionResetError("Connection lost abruptly")
    conn2._reader = mock_reader2
    conn2._closing = False
    conn2._is_connected = True

    with caplog.at_level(logging.ERROR):
        await conn2._reader_loop()
        assert "Unexpected error in reader loop" in caplog.text
        assert conn2._is_connected is False


@pytest.mark.asyncio
async def test_intesisbox_async_execute_all_branches() -> None:
    """Kill L559, L564, L569, L572-573, L577-578, L584-587, and L589-592 in async_execute.

    - L559: _is_poll=True with error in _send_raw.
    - L564: data=None or data="" returns current status cache.
    - L569: multi-line data with empty lines.
    - L577-578: IntesisBox returns ERR rejection -> raises CannotConnect.
    - L584-587: Command success updates local status cache with split parts.
    - L589-592: Command timeout waiting for ACK -> raises CannotConnect.
    """
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    conn._is_connected = True
    conn._writer = MagicMock()
    conn._writer.is_closing.return_value = False
    conn._command_timeout = 0.05

    sent_cmds: list[str] = []

    # 1. Test L564: data=None and empty data
    conn._device_status = {"ONOFF": "ON"}
    resp1, _ = await conn.async_execute(None, None, data=None, headers=None)
    assert json.loads(resp1).get("ONOFF") == "ON"

    resp2, _ = await conn.async_execute(None, None, data="", headers=None)
    assert json.loads(resp2).get("ONOFF") == "ON"

    # 2. Test L559: Polling with error in _send_raw
    async def failing_send(payload: str) -> None:
        raise OSError("Poll send failed")

    conn._send_raw = failing_send
    resp_poll, _ = await conn.async_execute(None, None, data=None, headers=None, _is_poll=True)
    assert json.loads(resp_poll).get("ONOFF") == "ON"

    # 3. Test L569, L572-573, L584-587: Sequential execution with ACK & cache update
    async def ack_send(payload: str) -> None:
        sent_cmds.append(payload)
        # Simulate background ACK response from reader loop
        if conn._pending_ack and not conn._pending_ack.done():
            conn._pending_ack.set_result(True)

    conn._send_raw = ack_send
    # Multi-line with blank lines (tests L569 stripping)
    cmd_data = "\n\nSET,1:FANSP,AUTO\nSET,1:MODE,COOL\n\n"
    resp_ack, _ = await conn.async_execute(None, None, data=cmd_data, headers=None)
    assert "SET,1:FANSP,AUTO\r\n" in sent_cmds
    assert "SET,1:MODE,COOL\r\n" in sent_cmds
    status = json.loads(resp_ack)
    assert status.get("FANSP") == "AUTO"
    assert status.get("MODE") == "COOL"

    # 4. Test L577-578: Command rejected with ERR
    async def err_send(payload: str) -> None:
        if conn._pending_ack and not conn._pending_ack.done():
            conn._pending_ack.set_result(False)

    conn._send_raw = err_send
    with pytest.raises(CannotConnect, match="rejected with ERR"):
        await conn.async_execute(None, None, data="SET,1:SETPTEMP,999", headers=None)

    # 5. Test L589-592: Command timeout waiting for ACK
    async def hanging_cmd(payload: str) -> None:
        pass  # Never set _pending_ack

    conn._send_raw = hanging_cmd
    with pytest.raises(CannotConnect, match="Timed out waiting for ACK"):
        await conn.async_execute(None, None, data="SET,1:SETPTEMP,220", headers=None)


@pytest.mark.asyncio
async def test_intesisbox_async_execute_loop_break_direct() -> None:
    """Kill L489-513 and L526-527 mutants in _async_execute_loop_break directly.

    Tests exact limits string formatting, template substitution, bracket stripping,
    dictionary updates, and awaitable callback scheduling.
    """
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    sent_cmds: list[str] = []

    async def fake_send(payload: str) -> None:
        sent_cmds.append(payload)

    conn._send_raw = fake_send

    rule = {
        "fallback_command": "SET,1:FANSP,AUTO",
        "prune_values": ["1"],
        "prune_command_template": "LIMITS:FANSP,{{new_limits}}",
    }
    conn._limits["FANSP"] = "[AUTO,1,2,3,4]"
    conn._device_status["_LIMITS_FANSP"] = "[AUTO,1,2,3,4]"

    # Test callback with non-coroutine awaitable (kills L526-527)
    class CustomAwaitable:
        def __init__(self) -> None:
            self.done = False

        def __await__(self):
            self.done = True
            async def _d():
                return None
            return _d().__await__()

    custom_cb = CustomAwaitable()
    mock_hass = MagicMock()
    conn._hass = mock_hass
    conn.set_update_callback(lambda d: custom_cb)

    # 1. Execute loop break with eligible pruning
    await conn._async_execute_loop_break("FANSP", "1", "AUTO", rule)

    # Assert exact command format (kills L490, L510, L513)
    assert sent_cmds == [
        "SET,1:FANSP,AUTO\r\n",
        "LIMITS:FANSP,[AUTO,2,3,4]\r\n",
    ]
    # Assert exact limits string (kills L494, L497, L498, L500)
    assert conn._limits["FANSP"] == "[AUTO,2,3,4]"
    assert conn._device_status["_LIMITS_FANSP"] == "[AUTO,2,3,4]"
    assert conn._device_status["FANSP"] == "AUTO"

    # Assert callback scheduled via mock_hass (kills L526-527)
    mock_hass.async_create_task.assert_called_with(custom_cb)

    # 2. Bad val not in prune_values -> no pruning commands sent
    sent_cmds.clear()
    await conn._async_execute_loop_break("FANSP", "2", "AUTO", rule)
    assert sent_cmds == ["SET,1:FANSP,AUTO\r\n"]

    # 3. No prune_command_template -> no pruning commands sent
    sent_cmds.clear()
    rule_no_template = {"fallback_command": "SET,1:FANSP,AUTO", "prune_values": ["1"]}
    await conn._async_execute_loop_break("FANSP", "1", "AUTO", rule_no_template)
    assert sent_cmds == ["SET,1:FANSP,AUTO\r\n"]

    # 4. Empty limits cache -> no pruning commands sent
    sent_cmds.clear()
    conn._limits["FANSP"] = ""
    await conn._async_execute_loop_break("FANSP", "1", "AUTO", rule)
    assert sent_cmds == ["SET,1:FANSP,AUTO\r\n"]


@pytest.mark.asyncio
async def test_intesisbox_evaluate_oscillation_rule_logging_and_boundaries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill L420-423, L429, L433, L438, L441-443, L446-447, L449, and L451 mutants.

    Verifies exact warning log output with distinct values, threshold boundary,
    and history window inclusion.
    """
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    sent_cmds: list[str] = []

    async def fake_send(payload: str) -> None:
        sent_cmds.append(payload)

    conn._send_raw = fake_send

    rule = {
        "node": "FANSP",
        "fallback_value": "AUTO",
        "fallback_command": "SET,1:FANSP,AUTO",
        "prune_values": ["1"],
        "threshold": 3,
        "window_seconds": 3.0,
    }
    conn._loop_breakers = [rule]
    conn._limits["FANSP"] = "[AUTO,1,2,3,4]"

    # 1. Boundary: exactly threshold (3) updates must NOT trigger loop breaker (kills L433)
    conn._process_incoming_line("CHN,1:FANSP,1")
    conn._process_incoming_line("CHN,1:FANSP,AUTO")
    conn._process_incoming_line("CHN,1:FANSP,1")
    await asyncio.sleep(0.01)
    assert len(sent_cmds) == 0

    # 2. 4th update (threshold + 1) triggers with prune match
    with caplog.at_level(logging.WARNING):
        conn._process_incoming_line("CHN,1:FANSP,AUTO")
        await asyncio.sleep(0.02)
        assert len(sent_cmds) > 0
        # Kills L441 (other_val == bad_val), L442, L443: must say between '1' and 'AUTO'
        assert "oscillation detected between '1' and 'AUTO'" in caplog.text

    # 3. Else branch: neither in prune_values, neither is fallback (kills L446, L447, L449)
    sent_cmds.clear()
    caplog.clear()
    conn._node_history.clear()
    conn._process_incoming_line("CHN,1:FANSP,2")
    conn._process_incoming_line("CHN,1:FANSP,3")
    conn._process_incoming_line("CHN,1:FANSP,2")
    with caplog.at_level(logging.WARNING):
        conn._process_incoming_line("CHN,1:FANSP,3")
        await asyncio.sleep(0.02)
        assert len(sent_cmds) > 0
        # In else branch, bad_val is last item ('3') and other_val is '2'
        assert "oscillation detected between '3' and '2'" in caplog.text

    # 4. History window exact boundary (kills L429 <= vs <)
    with patch("time.monotonic", return_value=100.0):
        # Entry exactly at window_seconds boundary: now - t == 3.0 (100.0 - 97.0 == 3.0)
        conn._node_history["FANSP"] = [(97.0, "BOUNDARY_VAL")]
        conn._evaluate_oscillation_rule("FANSP", "NEW_VAL", rule)
        # With <= window_seconds (3.0 <= 3.0), BOUNDARY_VAL is kept (2 items); with < it is discarded
        assert any(v == "BOUNDARY_VAL" for _, v in conn._node_history["FANSP"])


@pytest.mark.asyncio
async def test_intesisbox_reader_loop_closing_and_ascii_decode() -> None:
    """Kill L293 (while not self._closing or self._reader) and L302 (ascii decode) mutants."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    # 1. Test immediate exit when _closing=True (kills L293 'while not self._closing or self._reader')
    conn._closing = True
    mock_reader = AsyncMock()
    conn._reader = mock_reader
    await conn._reader_loop()
    mock_reader.readline.assert_not_called()

    # 2. Test ASCII decoding with errors='ignore' vs UTF-8 (kills L302 decode default mutant)
    conn._closing = False
    mock_reader = AsyncMock()
    # \xc3\x84 is invalid ASCII (ignored to "") but valid UTF-8 ("Ä")
    mock_reader.readline = AsyncMock(
        side_effect=[b"CHN,1:FANSP,\xc3\x84VALID\r\n", b""]
    )
    conn._reader = mock_reader

    processed: list[str] = []
    conn._process_incoming_line = MagicMock(side_effect=processed.append)

    await conn._reader_loop()
    assert processed == ["CHN,1:FANSP,VALID"]


@pytest.mark.asyncio
async def test_intesisbox_evaluate_oscillation_rule_precision_spying() -> None:
    """Kill L420-423 defaults, L438, L443, L446, L451, and L465 in _evaluate_oscillation_rule."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    spy_loop_break = AsyncMock()
    conn._async_execute_loop_break = spy_loop_break

    # 1. Rule without fallback_value (defaults to "AUTO", kills L420)
    rule_no_fb = {"threshold": 3, "window_seconds": 3.0, "prune_values": []}
    for val in ["MANUAL", "AUTO", "MANUAL", "AUTO"]:
        conn._evaluate_oscillation_rule("FANSP", val, rule_no_fb)
    spy_loop_break.assert_called_with("FANSP", "MANUAL", "AUTO", rule_no_fb)

    # 2. Rule without threshold (defaults to 3, kills L421)
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_no_th = {"fallback_value": "AUTO", "window_seconds": 3.0, "prune_values": []}
    for val in ["1", "2", "1"]:
        conn._evaluate_oscillation_rule("FANSP", val, rule_no_th)
    assert not spy_loop_break.called
    conn._evaluate_oscillation_rule("FANSP", "2", rule_no_th)
    assert spy_loop_break.called

    # 3. Rule without prune_values and without window_seconds (kills defaults)
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_minimal = {"fallback_value": "AUTO", "threshold": 3}
    for val in ["1", "2", "1", "2"]:
        conn._evaluate_oscillation_rule("FANSP", val, rule_minimal)
    assert spy_loop_break.called

    # Rule with non-default window_seconds (kills L426 rule.get mutants [22, 26, 27, 28])
    # Case A: window_seconds=2.0 with span 2.4s (10.0 -> 12.4).
    # Original: span 2.4s > 2.0s -> first item purged, 3 items < 4 -> does NOT trigger.
    # Mutants (using default 3.0s): span 2.4s <= 3.0s -> 4 items preserved -> TRIGGERS (fails assertion).
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_win_2 = {
        "fallback_value": "AUTO",
        "threshold": 3,
        "window_seconds": 2.0,
        "prune_values": [],
    }
    with patch("time.monotonic", side_effect=[10.0, 10.8, 11.6, 12.4]):
        for val in ["1", "2", "1", "2"]:
            conn._evaluate_oscillation_rule("FANSP", val, rule_win_2)
    assert not spy_loop_break.called

    # Case B: window_seconds=4.0 with span 3.5s (10.0 -> 13.5).
    # Original: span 3.5s <= 4.0s -> 4 items preserved -> TRIGGERS.
    # Mutants (using default 3.0s): span 3.5s > 3.0s -> first item purged, 3 items < 4 -> does NOT trigger (fails assertion).
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_win_4 = {
        "fallback_value": "AUTO",
        "threshold": 3,
        "window_seconds": 4.0,
        "prune_values": [],
    }
    with patch("time.monotonic", side_effect=[10.0, 10.9, 11.8, 13.5]):
        for val in ["1", "2", "1", "2"]:
            conn._evaluate_oscillation_rule("FANSP", val, rule_win_4)
    assert spy_loop_break.called

    # Case C: Rule WITHOUT window_seconds key, testing exact default 3.0s boundary (kills L426 Mutant 28: default 3.0 -> 4.0).
    # Updates span 3.5s (10.0 -> 13.5).
    # Original (default 3.0s): span 3.5s > 3.0s -> first item purged, 3 items < 4 -> does NOT trigger.
    # Mutant 28 (default 4.0s): span 3.5s <= 4.0s -> all 4 items preserved -> TRIGGERS (fails assertion).
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_default_win = {"fallback_value": "AUTO", "threshold": 3, "prune_values": []}
    with patch("time.monotonic", side_effect=[10.0, 10.9, 11.8, 13.5]):
        for val in ["1", "2", "1", "2"]:
            conn._evaluate_oscillation_rule("FANSP", val, rule_default_win)
    assert not spy_loop_break.called

    # 4. Prune values matching (kills L423 list comp, L427 PRUNE_VALUES case, and L442 prune_matches = None)
    # Uses fallback_value="AUTO" which is NOT one of the oscillating values ("PRUNE_ME", "OTHER_VAL").
    # Ending on "OTHER_VAL":
    # - Original: detects prune_matches=["PRUNE_ME"], bad_val="PRUNE_ME", fallback="AUTO".
    # - Mutant 36 (PRUNE_VALUES): prune_values is empty, fallback not in values, falls to else -> bad_val="OTHER_VAL".
    # - Mutant 50 (prune_matches=None): falls to else -> bad_val="OTHER_VAL".
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_prune = {
        "fallback_value": "AUTO",
        "threshold": 3,
        "window_seconds": 3.0,
        "prune_values": ["PRUNE_ME"],
    }
    for val in ["PRUNE_ME", "OTHER_VAL", "PRUNE_ME", "OTHER_VAL"]:
        conn._evaluate_oscillation_rule("FANSP", val, rule_prune)
    spy_loop_break.assert_called_with("FANSP", "PRUNE_ME", "AUTO", rule_prune)

    # 5. Fallback matching bad_val selection (kills L443 if v != fallback_val mutant '==')
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_fb = {
        "fallback_value": "FB_VAL",
        "threshold": 3,
        "window_seconds": 3.0,
        "prune_values": [],
    }
    for val in ["FB_VAL", "BAD_VAL", "FB_VAL", "BAD_VAL"]:
        conn._evaluate_oscillation_rule("FANSP", val, rule_fb)
    spy_loop_break.assert_called_with("FANSP", "BAD_VAL", "FB_VAL", rule_fb)

    # 6. Else branch: bad_val = active_hist[-1][1] vs [+1] (kills L446)
    # With threshold=4 and 5 updates: ["A", "B", "A", "B", "A"]:
    # Update 4 ("B") has 3 alternations (<4, does not trigger).
    # Update 5 ("A") has 4 alternations (>=4, triggers).
    # active_hist[-1] is "A", while mutant active_hist[+1] is "B".
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_else = {
        "fallback_value": "NEITHER",
        "threshold": 4,
        "window_seconds": 3.0,
        "prune_values": [],
    }
    for val in ["A", "B", "A", "B", "A"]:
        conn._evaluate_oscillation_rule("FANSP", val, rule_else)
    spy_loop_break.assert_called_with("FANSP", "A", "NEITHER", rule_else)

    # 7. Alternations range boundary (kills L451 range(1, len) vs range(len))
    # 4 updates with threshold=4 has 3 alternations. range(len) wraps around and counts 4
    spy_loop_break.reset_mock()
    conn._node_history.clear()
    rule_range = {
        "fallback_value": "NEITHER",
        "threshold": 4,
        "window_seconds": 3.0,
        "prune_values": [],
    }
    for val in ["A", "B", "A", "B"]:
        conn._evaluate_oscillation_rule("FANSP", val, rule_range)
    assert not spy_loop_break.called


@pytest.mark.asyncio
async def test_intesisbox_loop_breaker_hass_attribute_fallback() -> None:
    """Kill L465 and L527 (if self._hass and hasattr(...) mutants) when hass lacks async_create_task."""
    conn = ConnectionIntesisBox(
        config={CONF_IP_ADDRESS: "127.0.0.1", CONF_PORT: 3310},
        logger=_LOGGER,
    )
    # Set _hass to a non-None object that does NOT have async_create_task
    # Mutants mutating 'and' to 'or' will try to access self._hass.async_create_task and fail
    conn._hass = object()

    rule = {
        "node": "FANSP",
        "fallback_value": "AUTO",
        "fallback_command": "SET,1:FANSP,AUTO",
        "prune_values": [],
        "threshold": 3,
        "window_seconds": 3.0,
    }
    conn._send_raw = AsyncMock()

    # 1. Test _evaluate_oscillation_rule with non-HA hass (kills L465)
    with patch("asyncio.create_task") as mock_task:
        for val in ["MANUAL", "AUTO", "MANUAL", "AUTO"]:
            conn._evaluate_oscillation_rule("FANSP", val, rule)
        mock_task.assert_called_once()

    # 2. Test _async_execute_loop_break with non-HA hass and coroutine callback (kills L527)
    async def async_cb(payload: dict[str, Any]) -> None:
        pass

    conn._update_callback = async_cb

    with patch("asyncio.create_task") as mock_task:
        await conn._async_execute_loop_break("FANSP", "MANUAL", "AUTO", rule)
        mock_task.assert_called_once()













