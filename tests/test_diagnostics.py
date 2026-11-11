# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the diagnostics support in climate_ip."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.const import DOMAIN
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.diagnostics import (
    TO_REDACT,
    _deep_redact_substrings,
    _extract_controller_diagnostics,
    _extract_raw_device_state,
    _get_mac_threat_patterns,
    async_get_config_entry_diagnostics,
)
from homeassistant.const import CONF_MAC


@dataclass
class DummyCoordinatorData:
    """Dummy dataclass for testing asdict conversion."""

    power: str = "on"
    target_temperature: float = 22.0


@pytest.fixture
def mock_entry():
    """Create a mock config entry with both safe and sensitive keys."""
    entry = MagicMock()
    entry.data = {
        "device_type": "samsung_8888",
        "ip_address": "192.168.1.100",
        "port": 8888,
        "name": "Living Room AC",
        "poll_interval": 60,
        "conn_method": "raw",
        "temp_native_current": "C",
        "temp_native_target": "C",
        "token": "super_secret_token_12345",
        "mac": "AA:BB:CC:DD:EE:FF",
        "cert": "/path/to/private/cert.pem",
    }
    entry.options = {"poll_interval": 30}
    entry.unique_id = "test_unique_id"
    entry.entry_id = "test_entry_id"
    entry.domain = DOMAIN
    entry.title = "Test AC"
    return entry


@pytest.fixture
def mock_hass(mock_entry):
    """Create a pure unit mock hass instance without Core fixture overhead."""
    hass = MagicMock()
    mock_entry.runtime_data = "not_a_coordinator"
    hass.data = {DOMAIN: {mock_entry.entry_id: "not_a_coordinator"}}
    return hass


def test_get_mac_threat_patterns_canonical() -> None:
    """Test standard 12-char hex MAC generates exact canonical variants."""
    entry = MagicMock()
    entry.data = {CONF_MAC: "aa:bb:cc:dd:ee:ff"}
    entry.title = "Device AA1122334455"
    entry.unique_id = "AA:11:22:33:44:55"

    result = _get_mac_threat_patterns(entry)
    expected = {
        "aabbccddeeff",
        "AABBCCDDEEFF",
        "aa:bb:cc:dd:ee:ff",
        "AA:BB:CC:DD:EE:FF",
        "aa-bb-cc-dd-ee-ff",
        "AA-BB-CC-DD-EE-FF",
        "aa1122334455",
        "AA1122334455",
        "aa:11:22:33:44:55",
        "AA:11:22:33:44:55",
        "aa-11-22-33-44-55",
        "AA-11-22-33-44-55",
    }
    assert result == expected


def test_get_mac_threat_patterns_boundaries_and_fallbacks() -> None:
    """Test boundary conditions, whitespace, non-hex candidates, and fallback key."""
    # Fallback to "mac" key when CONF_MAC absent
    entry_mac_key = MagicMock()
    entry_mac_key.data = {"mac": "BB:11:22:33:44:55"}
    entry_mac_key.title = None
    entry_mac_key.unique_id = None
    patterns = _get_mac_threat_patterns(entry_mac_key)
    assert "BB:11:22:33:44:55" in patterns

    # Boundary test: length == 5 is ignored, length > 5 is captured
    entry_boundary = MagicMock()
    entry_boundary.data = {CONF_MAC: "12345"}
    entry_boundary.title = ""
    entry_boundary.unique_id = ""
    assert "12345" not in _get_mac_threat_patterns(entry_boundary)

    entry_boundary.data = {CONF_MAC: "123456"}
    assert "123456" in _get_mac_threat_patterns(entry_boundary)

    # Candidate with len > 5 but clean len != 12 generates upper/lower variants only
    entry_non12 = MagicMock()
    entry_non12.data = {CONF_MAC: "abcdefg"}
    entry_non12.title = ""
    entry_non12.unique_id = ""
    assert _get_mac_threat_patterns(entry_non12) == {"abcdefg", "ABCDEFG"}

    # Pure whitespace candidate
    entry_ws = MagicMock()
    entry_ws.data = {CONF_MAC: "   "}
    entry_ws.title = None
    entry_ws.unique_id = None
    assert _get_mac_threat_patterns(entry_ws) == set()


def test_deep_redact_substrings_sort_and_replacement() -> None:
    """Test length-descending sort order, case insensitivity, empty patterns, and multiple occurrences."""
    # Longer pattern ("AX") must be replaced before shorter ("X")
    assert _deep_redact_substrings("AX", {"X", "AX"}) == "**REDACTED**"
    assert (
        _deep_redact_substrings(
            "Here is 112233445566 and 112233", {"112233", "112233445566"}
        )
        == "Here is **REDACTED** and **REDACTED**"
    )

    # Empty threat pattern skipped safely without infinite loop
    assert (
        _deep_redact_substrings("hello secret world", {"", "secret"})
        == "hello **REDACTED** world"
    )

    # Case insensitivity
    assert (
        _deep_redact_substrings("DEVICE is Aa:Bb:Cc:Dd:Ee:Ff", {"aa:bb:cc:dd:ee:ff"})
        == "DEVICE is **REDACTED**"
    )

    # Multiple occurrences in single string
    assert (
        _deep_redact_substrings("token1 and token1 again", {"token1"})
        == "**REDACTED** and **REDACTED** again"
    )

    # Empty threat_patterns set returns original value immediately
    assert _deep_redact_substrings("unmodified text", set()) == "unmodified text"


def test_deep_redact_substrings_nested_containers() -> None:
    """Test deep redaction recursion across dicts, lists, tuples, and scalar pass-through."""
    payload = {
        "dict_key": {"secret_field": "my_secret_token", "safe_int": 42},
        "list_items": ["item with my_secret_token", 3.14, True, None],
        "tuple_items": ("tuple_secret: my_secret_token", False),
        "scalar_pass": 100,
    }
    threats = {"my_secret_token"}
    redacted = _deep_redact_substrings(payload, threats)

    assert redacted["dict_key"]["secret_field"] == "**REDACTED**"
    assert redacted["dict_key"]["safe_int"] == 42
    assert redacted["list_items"] == ["item with **REDACTED**", 3.14, True, None]
    assert redacted["tuple_items"] == ("tuple_secret: **REDACTED**", False)
    assert redacted["scalar_pass"] == 100


def test_extract_controller_diagnostics_hierarchy() -> None:
    """Test resolution hierarchy in _extract_controller_diagnostics and error guards."""
    # 1. Direct connection_diagnostics property
    ctrl_prop = MagicMock(spec=["connection_diagnostics"])
    ctrl_prop.connection_diagnostics = {"latency_ms": 10}
    assert _extract_controller_diagnostics(ctrl_prop) == {"latency_ms": 10}

    # 2. Controller get_diagnostics() method
    ctrl_method = MagicMock(spec=["get_diagnostics"])
    ctrl_method.get_diagnostics.return_value = {"method_data": "ok"}
    assert _extract_controller_diagnostics(ctrl_method) == {"method_data": "ok"}

    # 3. Connection get_diagnostics() method
    ctrl_conn = MagicMock(spec=["connection"])
    ctrl_conn.connection = MagicMock(spec=["get_diagnostics"])
    ctrl_conn.connection.get_diagnostics.return_value = {"conn_diag": True}
    assert _extract_controller_diagnostics(ctrl_conn) == {"conn_diag": True}

    # 4. Controller with no diagnostics capabilities returns empty dict
    ctrl_empty = MagicMock(spec=[])
    assert _extract_controller_diagnostics(ctrl_empty) == {}

    # 5. Non-callable get_diagnostics raises TypeError (protocol guard)
    ctrl_invalid = MagicMock(spec=["connection"])
    ctrl_invalid.connection = MagicMock(spec=["get_diagnostics"])
    ctrl_invalid.connection.get_diagnostics = "not_callable_string"
    with pytest.raises(TypeError):
        _extract_controller_diagnostics(ctrl_invalid)


def test_extract_raw_device_state_hierarchy() -> None:
    """Test subdevice raw_state/device_state/AttributeError cascade and controller fallbacks."""
    coordinator = MagicMock()

    # Subdevices: dev1 (raw_state), dev2 (device_state fallback), dev3 (AttributeError on both -> lines 174-175)
    dev1 = MagicMock(spec=["raw_state"])
    dev1.raw_state = {"temp": 20}

    dev2 = MagicMock(spec=["device_state"])
    dev2.device_state = {"temp": 22}

    dev3 = object()  # raises AttributeError on both raw_state and device_state

    coordinator.devices = {"dev_1": dev1, "dev_2": dev2, "dev_3": dev3}
    state = _extract_raw_device_state(coordinator)
    assert state == {"dev_1": {"temp": 20}, "dev_2": {"temp": 22}}

    # Empty devices -> Controller raw_state
    coord_ctrl_raw = MagicMock()
    coord_ctrl_raw.devices = {}
    coord_ctrl_raw.controller = MagicMock(spec=["raw_state"])
    coord_ctrl_raw.controller.raw_state = {"power": "on"}
    assert _extract_raw_device_state(coord_ctrl_raw) == {"main": {"power": "on"}}

    # Controller device_state fallback
    coord_ctrl_dev = MagicMock()
    coord_ctrl_dev.devices = {}
    coord_ctrl_dev.controller = MagicMock(spec=["device_state"])
    coord_ctrl_dev.controller.device_state = {"mode": "heat"}
    assert _extract_raw_device_state(coord_ctrl_dev) == {"main": {"mode": "heat"}}

    # Controller last_poll_data fallback
    coord_ctrl_poll = MagicMock()
    coord_ctrl_poll.devices = {}
    coord_ctrl_poll.controller = MagicMock(spec=["last_poll_data"])
    coord_ctrl_poll.controller.last_poll_data = {"status": "polling"}
    assert _extract_raw_device_state(coord_ctrl_poll) == {"main": {"status": "polling"}}

    # Controller without state attributes returns empty dict
    coord_none = MagicMock()
    coord_none.devices = {}
    coord_none.controller = object()
    assert _extract_raw_device_state(coord_none) == {}


async def test_diagnostics_entry_fields_and_sensitive_redaction(mock_hass, mock_entry):
    """Test top-level dictionary structure and comprehensive redaction of TO_REDACT keys."""
    # Populate mock_entry.data with all sensitive keys in TO_REDACT
    for key in TO_REDACT:
        mock_entry.data[key] = f"secret_value_for_{key}"

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    # Top-level keys verification
    assert "entry" in result
    assert "bootstrapping" in result
    assert "connection_telemetry" in result
    assert "raw_device_state" in result
    assert "network_diagnostics" in result

    # Entry metadata
    entry_dict = result["entry"]
    assert entry_dict["domain"] == DOMAIN
    assert entry_dict["title"] == "Test AC"
    assert entry_dict["options"] == {"poll_interval": 30}
    assert entry_dict["unique_id"] == "**REDACTED**"

    # All keys in TO_REDACT must be redacted
    for key in TO_REDACT:
        assert entry_dict["data"][key] == "**REDACTED**", f"{key} not redacted"


async def test_diagnostics_single_coordinator_full(mock_hass, mock_entry):
    """Test single coordinator diagnostics extraction with full telemetry and bootstrapping."""
    coordinator = MagicMock(spec=SamsungClimateCoordinator)
    coordinator.data = DummyCoordinatorData(power="on", target_temperature=23.5)
    coordinator.discovered_devices_count = 3
    coordinator.skipped_devices_count = 1
    coordinator.entities = ["climate.living_room", "sensor.living_room_temp"]

    device1 = MagicMock()
    device1.raw_state = {"power": "on", "mac": "AA:11:22:33:44:55"}
    coordinator.devices = {"dev1": device1}

    mock_controller = MagicMock()
    mock_controller.state_attributes = {"power": "on", "fan_mode": "auto"}
    mock_controller.last_poll_data = {"raw_voltage": 230}
    mock_controller.connection_diagnostics = {"ping_ms": 15}
    coordinator.controller = mock_controller

    mock_entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert result["coordinator_data"] == {"power": "on", "target_temperature": 23.5}
    assert result["controller_state"] == {"power": "on", "fan_mode": "auto"}
    assert result["last_poll_response"] == {"raw_voltage": 230}
    assert result["connection_diagnostics"] == {"ping_ms": 15}
    assert result["connection_telemetry"] == {"ping_ms": 15}
    assert result["raw_device_state"] == {
        "dev1": {"power": "on", "mac": "**REDACTED**"}
    }
    assert result["bootstrapping"] == {
        "total_devices_discovered": 3,
        "skipped_devices_missing_info": 1,
        "active_entities": 2,
    }


async def test_diagnostics_single_coordinator_defaults_and_survivor_kill(
    mock_hass, mock_entry
):
    """Test single coordinator attribute defaults and kill Survivor 1 (line 220)."""
    coordinator = MagicMock(spec=SamsungClimateCoordinator)
    coordinator.data = None
    coordinator.devices = {}
    coordinator.controller = object()  # Bare object without optional attributes
    del coordinator.discovered_devices_count
    del coordinator.skipped_devices_count

    # KILLS SURVIVOR 1: entities is non-None and NOT a list|set|dict (e.g. int 123)
    # Original: (entities is not None and isinstance(entities, list|set|dict)) -> False -> 0
    # Mutant: (entities is not None or isinstance(...)) -> True -> len(123) -> TypeError
    coordinator.entities = 123

    mock_entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "coordinator_data" not in result
    assert "controller_state" not in result
    assert "last_poll_response" not in result
    assert "connection_diagnostics" not in result
    assert result["bootstrapping"]["total_devices_discovered"] == 0
    assert result["bootstrapping"]["skipped_devices_missing_info"] == 0
    assert result["bootstrapping"]["active_entities"] == 0


async def test_diagnostics_multi_coordinator_full(mock_hass, mock_entry):
    """Test multi-coordinator dictionary diagnostics extraction and aggregate bootstrapping math."""
    coord1 = MagicMock(spec=SamsungClimateCoordinator)
    coord1.data = DummyCoordinatorData(power="on", target_temperature=21.0)
    coord1.discovered_devices_count = 3
    coord1.skipped_devices_count = 1
    coord1.entities = ["climate.unit_1", "sensor.unit_1_temp"]
    coord1.controller = MagicMock()
    coord1.controller.state_attributes = {"power": "on"}
    coord1.controller.last_poll_data = {"status": "ok"}
    coord1.controller.connection_diagnostics = {"ping_ms": 8}

    coord2 = MagicMock(spec=SamsungClimateCoordinator)
    coord2.data = None
    coord2.discovered_devices_count = 2
    coord2.skipped_devices_count = 3
    coord2.entities = {"climate.unit_2"}
    coord2.controller = object()

    mock_entry.runtime_data = {
        "unit_1": coord1,
        "unit_2": coord2,
        "ignored_item": "not_a_coordinator",
    }

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "coordinators" in result
    assert "unit_1" in result["coordinators"]
    assert "unit_2" in result["coordinators"]
    assert "ignored_item" not in result["coordinators"]

    u1 = result["coordinators"]["unit_1"]
    assert u1["coordinator_data"] == {"power": "on", "target_temperature": 21.0}
    assert u1["controller_state"] == {"power": "on"}
    assert u1["last_poll_response"] == {"status": "ok"}
    assert u1["connection_diagnostics"] == {"ping_ms": 8}

    u2 = result["coordinators"]["unit_2"]
    assert "coordinator_data" not in u2
    assert "controller_state" not in u2
    assert "last_poll_response" not in u2

    # Verify bootstrapping math summation
    assert result["bootstrapping"] == {
        "total_devices_discovered": 5,  # 3 + 2
        "skipped_devices_missing_info": 4,  # 1 + 3
        "active_entities": 3,  # 2 + 1
    }


async def test_diagnostics_multi_coordinator_defaults_and_survivor_kill(
    mock_hass, mock_entry
):
    """Test multi-coordinator default fallbacks and kill Survivor 2 (line 279)."""
    coord = MagicMock(spec=SamsungClimateCoordinator)
    coord.data = None
    coord.controller = object()
    del coord.discovered_devices_count
    del coord.skipped_devices_count

    # KILLS SURVIVOR 2: entities is non-None and NOT a list|set|dict (e.g. int 456)
    # Original: if entities is not None and isinstance(entities, list|set|dict): -> False -> skipped
    # Mutant: if entities is not None or isinstance(...): -> True -> len(456) -> TypeError
    coord.entities = 456

    mock_entry.runtime_data = {"unit_1": coord}

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert result["bootstrapping"]["total_devices_discovered"] == 1  # default is 1
    assert result["bootstrapping"]["skipped_devices_missing_info"] == 0  # default is 0
    assert result["bootstrapping"]["active_entities"] == 0


async def test_diagnostics_network_diagnostics_structure_and_reachability(
    mock_hass, mock_entry
):
    """Test network_diagnostics structure, probe support, and connection telemetry check."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.data = None
    mock_coord.devices = {}
    mock_coord.controller = MagicMock()
    mock_coord.controller.connection_diagnostics = {
        "network_reachability": {
            "is_reachable": True,
            "avg_rtt_ms": 2.5,
            "status": "alive",
            "privileged_mode": False,
        }
    }
    mock_entry.runtime_data = mock_coord

    res = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    net_diag = res["network_diagnostics"]
    assert "privileged_probe_support" in net_diag
    assert isinstance(net_diag["privileged_probe_support"], bool)
    assert net_diag["last_runtime_check"] == {
        "is_reachable": True,
        "avg_rtt_ms": 2.5,
        "status": "alive",
        "privileged_mode": False,
    }
    assert net_diag["active_probe"]["is_reachable"] is True
    assert net_diag["active_probe"]["status"] == "alive"


async def test_diagnostics_network_diagnostics_no_host(mock_hass):
    """Test network_diagnostics when no host is configured in data, options, or controller."""
    entry = MagicMock()
    entry.entry_id = "test_no_host"
    entry.data = {}
    entry.options = {}
    entry.title = "No Host AC"
    entry.domain = DOMAIN
    entry.unique_id = "uid_no_host"

    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.data = None
    mock_coord.devices = {}
    mock_coord.controller = MagicMock(spec=[])
    entry.runtime_data = mock_coord

    res = await async_get_config_entry_diagnostics(mock_hass, entry)

    net_diag = res["network_diagnostics"]
    assert net_diag["active_probe"] == {
        "is_reachable": None,
        "status": "no_host_configured",
    }
    assert net_diag["last_runtime_check"] == {
        "is_reachable": None,
        "status": "not_recorded",
    }


async def test_diagnostics_network_diagnostics_multi_coordinator(mock_hass, mock_entry):
    """CRITICAL SOLO KILLER: Test network_diagnostics with multi-coordinator dictionary setup."""
    coord1 = MagicMock(spec=SamsungClimateCoordinator)
    coord1.data = None
    coord1.devices = {}
    coord1.controller = MagicMock()
    coord1.controller.connection_diagnostics = {
        "network_reachability": {
            "is_reachable": False,
            "avg_rtt_ms": None,
            "status": "dead",
        }
    }

    mock_entry.runtime_data = {"sub_unit_1": coord1}

    res = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "network_diagnostics" in res
    net_diag = res["network_diagnostics"]
    assert net_diag["last_runtime_check"] == {
        "is_reachable": False,
        "avg_rtt_ms": None,
        "status": "dead",
    }


async def test_diagnostics_network_diagnostics_fallback_to_global_registry(
    mock_hass, mock_entry
):
    """Test fallback to get_last_network_diagnostic when controller has no network_reachability."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.data = None
    mock_coord.devices = {}
    mock_coord.controller = MagicMock(spec=[])
    mock_entry.runtime_data = mock_coord

    recorded_diag = {
        "is_reachable": True,
        "avg_rtt_ms": 3.1,
        "status": "alive",
        "privileged_mode": False,
    }

    with patch(
        "custom_components.climate_ip.diagnostics.get_last_network_diagnostic",
        return_value=recorded_diag,
    ):
        res = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "network_diagnostics" in res
    assert res["network_diagnostics"]["last_runtime_check"] == recorded_diag


@pytest.mark.asyncio
async def test_diagnostics_target_host_resolution_hierarchy(mock_hass, mock_entry):
    """CRITICAL SOLO KILLER: Kill L291, L293, L296-297, L301-311, and L331-332 mutants in diagnostics.py.

    Tests target_host resolution across all possible config, option, coordinator, and
    multi-coordinator sources, ensuring exact ping_timeout=1.0 forwarding.
    """
    mock_probe = AsyncMock(return_value={"is_reachable": True, "status": "alive"})

    with patch(
        "custom_components.climate_ip.diagnostics.async_get_network_diagnostics",
        mock_probe,
    ):
        # 1. Host in entry.data['host']
        mock_entry.data = {"host": "10.0.0.1"}
        mock_entry.options = {}
        mock_entry.runtime_data = None
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.1", ping_timeout=1.0)

        # 2. Host in entry.data['ip_address'] (no 'host')
        mock_entry.data = {"ip_address": "10.0.0.2"}
        mock_entry.options = {}
        mock_entry.runtime_data = None
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.2", ping_timeout=1.0)

        # 3. Host in entry.options['host']
        mock_entry.data = {}
        mock_entry.options = {"host": "10.0.0.3"}
        mock_entry.runtime_data = None
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.3", ping_timeout=1.0)

        # 4. Host in entry.options['ip_address']
        mock_entry.data = {}
        mock_entry.options = {"ip_address": "10.0.0.4"}
        mock_entry.runtime_data = None
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.4", ping_timeout=1.0)

        # 5. Host in single coordinator controller.ip_address
        mock_entry.data = {}
        mock_entry.options = {}
        single_coord = MagicMock(spec=SamsungClimateCoordinator)
        single_coord.data = None
        single_coord.devices = {}
        single_coord.controller = MagicMock()
        single_coord.controller.ip_address = "10.0.0.5"
        single_coord.controller.host = None
        setattr(single_coord.controller, "_cfg", None)
        single_coord.controller.connection_diagnostics = {}
        mock_entry.runtime_data = single_coord
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.5", ping_timeout=1.0)

        # 6. Host in single coordinator controller.host
        single_coord.controller.ip_address = None
        single_coord.controller.host = "10.0.0.6"
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.6", ping_timeout=1.0)

        # 7. Host in single coordinator controller._cfg.host
        single_coord.controller.ip_address = None
        single_coord.controller.host = None
        cfg_mock = MagicMock()
        cfg_mock.host = "10.0.0.7"
        setattr(single_coord.controller, "_cfg", cfg_mock)
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.7", ping_timeout=1.0)

        # 8. Host in multi-coordinator dictionary (MIM-H03 indoor units) -> kills L301-311
        multi_coord = MagicMock(spec=SamsungClimateCoordinator)
        multi_coord.data = None
        multi_coord.devices = {}
        multi_coord.controller = MagicMock()
        multi_coord.controller.ip_address = "10.0.0.8"
        multi_coord.controller.connection_diagnostics = {}
        mock_entry.runtime_data = {"indoor_1": multi_coord}
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.8", ping_timeout=1.0)

        # Multi-coordinator with controller.host
        multi_coord.controller.ip_address = None
        multi_coord.controller.host = "10.0.0.9"
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.9", ping_timeout=1.0)

        # Multi-coordinator with controller._cfg.host
        multi_coord.controller.ip_address = None
        multi_coord.controller.host = None
        multi_cfg = MagicMock()
        multi_cfg.host = "10.0.0.10"
        setattr(multi_coord.controller, "_cfg", multi_cfg)
        await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        mock_probe.assert_called_with("10.0.0.10", ping_timeout=1.0)

        # 9. No host configured at all
        mock_entry.data = {}
        mock_entry.options = {}
        mock_entry.runtime_data = None
        res_no_host = await async_get_config_entry_diagnostics(mock_hass, mock_entry)
        assert res_no_host["network_diagnostics"]["active_probe"] == {
            "is_reachable": None,
            "status": "no_host_configured",
        }


async def test_diagnostics_deep_redaction_complex_compound(mock_hass, mock_entry):
    """Test deep redaction across compound strings, formats, case variations, and collections."""
    mock_entry.data = {
        CONF_MAC: "aa:bb:cc:dd:ee:ff",
        "custom_info": {
            "colon_upper": "Device is AA:BB:CC:DD:EE:FF",
            "dash_upper": "Dash AA-BB-CC-DD-EE-FF",
            "duid_mixed": "ID is AAbbCCddEEff",
        },
        "history_list": ["MAC is aa:bb:cc:dd:ee:ff", "Normal Event"],
        "nested_tuple": ("aa:bb:cc:dd:ee:ff", "safe_val"),
    }
    mock_entry.title = "Device AA:BB:CC:DD:EE:FF"
    mock_entry.unique_id = "uid_AA-BB-CC-DD-EE-FF"
    mock_entry.options = {"note": "Contact aa:bb:cc:dd:ee:ff for help"}
    mock_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    entry_data = result["entry"]["data"]
    assert entry_data["custom_info"]["colon_upper"] == "Device is **REDACTED**"
    assert entry_data["custom_info"]["dash_upper"] == "Dash **REDACTED**"
    assert entry_data["custom_info"]["duid_mixed"] == "ID is **REDACTED**"
    assert entry_data["history_list"] == ["MAC is **REDACTED**", "Normal Event"]
    assert entry_data["nested_tuple"] == ("**REDACTED**", "safe_val")
    assert result["entry"]["title"] == "Device **REDACTED**"
    assert result["entry"]["unique_id"] == "**REDACTED**"
    assert result["entry"]["options"]["note"] == "Contact **REDACTED** for help"
