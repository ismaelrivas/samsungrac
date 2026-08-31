# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the diagnostics support in climate_ip."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from homeassistant.const import CONF_MAC
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
    """Create a mock hass instance."""
    hass = MagicMock()
    mock_entry.runtime_data = "not_a_coordinator"
    hass.data = {DOMAIN: {mock_entry.entry_id: "not_a_coordinator"}}
    return hass


async def test_diagnostics_entry_fields(mock_hass, mock_entry):
    """Test entry fields are correctly extracted in diagnostics payload."""
    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "entry" in result
    entry_dict = result["entry"]
    assert entry_dict["domain"] == DOMAIN
    assert entry_dict["title"] == "Test AC"
    assert entry_dict["unique_id"] == "**REDACTED**"
    assert entry_dict["options"] == {"poll_interval": 30}
    assert entry_dict["data"]["device_type"] == "samsung_8888"


async def test_diagnostics_all_sensitive_keys_redacted(mock_hass, mock_entry):
    """Test every sensitive key defined in TO_REDACT is properly redacted."""
    # Populate entry.data with every key from TO_REDACT
    for key in TO_REDACT:
        mock_entry.data[key] = f"sensitive_value_for_{key}"

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)
    entry_data = result["entry"]["data"]

    for key in TO_REDACT:
        assert entry_data[key] == "**REDACTED**", (
            f"Key '{key}' in TO_REDACT was not redacted!"
        )


async def test_diagnostics_single_coordinator(mock_hass, mock_entry):
    """Test single coordinator diagnostics extraction."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.data = DummyCoordinatorData(power="on", target_temperature=24.0)
    mock_coordinator.devices = {}

    mock_controller = MagicMock()
    mock_controller.state_attributes = {"power": "on", "mode": "cool"}
    mock_controller.last_poll_data = {"raw_status": "ok"}
    mock_controller.connection_diagnostics = {"ping_ms": 12}
    mock_coordinator.controller = mock_controller

    mock_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "coordinator_data" in result
    assert result["coordinator_data"] == {"power": "on", "target_temperature": 24.0}
    assert result["controller_state"] == {"power": "on", "mode": "cool"}
    assert result["last_poll_response"] == {"raw_status": "ok"}
    assert result["connection_diagnostics"] == {"ping_ms": 12}


async def test_diagnostics_single_coordinator_no_optional_attrs(mock_hass, mock_entry):
    """Test single coordinator when optional attributes and data are absent."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.data = None
    mock_coordinator.devices = {}
    mock_coordinator.controller = object()  # Bare object without optional attributes

    mock_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "coordinator_data" not in result
    assert "controller_state" not in result
    assert "last_poll_response" not in result
    assert "connection_diagnostics" not in result


async def test_diagnostics_multi_coordinator(mock_hass, mock_entry):
    """Test multi-device dict of coordinators diagnostics extraction."""
    coord1 = MagicMock(spec=SamsungClimateCoordinator)
    coord1.data = DummyCoordinatorData(power="on", target_temperature=21.0)
    coord1.controller = MagicMock()
    coord1.controller.state_attributes = {"device": "ac_1"}
    coord1.controller.last_poll_data = {"status_1": 1}
    coord1.controller.connection_diagnostics = {"latency": 5}

    coord2 = MagicMock(spec=SamsungClimateCoordinator)
    coord2.data = None
    coord2.controller = object()

    mock_entry.runtime_data = {
        "dev_1": coord1,
        "dev_2": coord2,
        "dev_3": "non_coordinator_object",
    }

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "coordinators" in result
    coordinators_dict = result["coordinators"]
    assert "dev_1" in coordinators_dict
    assert "dev_2" in coordinators_dict
    assert "dev_3" not in coordinators_dict

    dev1_diag = coordinators_dict["dev_1"]
    assert dev1_diag["coordinator_data"] == {"power": "on", "target_temperature": 21.0}
    assert dev1_diag["controller_state"] == {"device": "ac_1"}
    assert dev1_diag["last_poll_response"] == {"status_1": 1}
    assert dev1_diag["connection_diagnostics"] == {"latency": 5}

    dev2_diag = coordinators_dict["dev_2"]
    assert "coordinator_data" not in dev2_diag
    assert "controller_state" not in dev2_diag
    assert "last_poll_response" not in dev2_diag
    assert "connection_diagnostics" not in dev2_diag


async def test_recursive_redaction(mock_hass, mock_entry):
    """Test that sensitive keys are redacted recursively in nested structures."""
    mock_entry.data.update(
        {
            "level1": {
                "level2": {
                    "token": "super_secret_token",
                    "access_token": "oauth_token_123",
                    "safe_key": "safe_value",
                }
            },
            "list_of_dicts": [
                {"mac": "AA:BB:CC", "other": "info"},
                {"refresh_token": "refresh_123"},
            ],
            "a_tuple": ("112233445566", "safe_val", "192.168.1.100"),
        }
    )
    mock_entry.title = "112233445566"
    mock_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    diag_data = result["entry"]["data"]
    assert diag_data["level1"]["level2"]["token"] == "**REDACTED**"
    assert diag_data["level1"]["level2"]["access_token"] == "**REDACTED**"
    assert diag_data["level1"]["level2"]["safe_key"] == "safe_value"
    assert diag_data["list_of_dicts"][0]["mac"] == "**REDACTED**"
    assert diag_data["list_of_dicts"][0]["other"] == "info"
    assert diag_data["list_of_dicts"][1]["refresh_token"] == "**REDACTED**"
    assert diag_data["a_tuple"] == ("**REDACTED**", "safe_val", "192.168.1.100")


async def test_deep_substring_redaction_mac_and_duid(mock_hass, mock_entry):
    """Test that embedded MAC address and DUID substrings are redacted from compound string fields."""
    mock_entry.data.update(
        {
            "device_type": "samsung_8888",
            "mac": "AA:11:22:33:44:55",
            "name": "Samsung AC AA1122334455",
        }
    )
    mock_entry.title = "Samsung AC AA:11:22:33:44:55"
    mock_entry.unique_id = "device_AA1122334455"
    mock_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    entry_dict = result["entry"]
    assert entry_dict["title"] == "Samsung AC **REDACTED**"
    assert entry_dict["unique_id"] == "**REDACTED**"
    assert entry_dict["data"]["name"] == "Samsung AC **REDACTED**"
    assert entry_dict["data"]["mac"] == "**REDACTED**"


async def test_deep_substring_redaction_sort_order(mock_hass, mock_entry):
    """Test that longer threat patterns are redacted before shorter ones."""
    # Add a short pattern and a long pattern where short is a substring of long
    mock_entry.data.update({"mac": "112233"})
    mock_entry.title = "112233445566"
    mock_entry.unique_id = "test_unique"
    mock_entry.options = {"test_string": "Here is my 112233445566 and my 112233"}
    mock_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    # If not sorted by length descending, "SHORT" might be replaced first in "SHORTSHORT",
    # yielding "**REDACTED****REDACTED**" instead of just "**REDACTED**".
    assert (
        result["entry"]["options"]["test_string"]
        == "Here is my **REDACTED** and my **REDACTED**"
    )


async def test_diagnostics_deep_redaction_formats_and_case(mock_hass, mock_entry):
    """Test case-insensitivity, dash format, and DUID redaction."""
    mock_entry.data = {
        CONF_MAC: "aa:bb:cc:dd:ee:ff",
        "custom_info": {
            "colon_upper": "Device is AA:BB:CC:DD:EE:FF",
            "dash_upper": "Dash AA-BB-CC-DD-EE-FF",
            "duid_mixed": "ID is AAbbCCddEEff",
        },
    }
    mock_entry.title = "Test AC"
    mock_entry.unique_id = "test_unique_id"
    mock_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    custom_info = result["entry"]["data"]["custom_info"]
    assert custom_info["colon_upper"] == "Device is **REDACTED**"
    assert custom_info["dash_upper"] == "Dash **REDACTED**"
    assert custom_info["duid_mixed"] == "ID is **REDACTED**"


async def test_diagnostics_deep_redaction_lists(mock_hass, mock_entry):
    """Test deep redaction traverses list structures."""
    mock_entry.data = {
        CONF_MAC: "aa:bb:cc:dd:ee:ff",
        "history": ["MAC is aa:bb:cc:dd:ee:ff", "Normal Event"],
    }
    mock_entry.title = "Test AC"
    mock_entry.unique_id = "test_unique_id"
    mock_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    history = result["entry"]["data"]["history"]
    assert history[0] == "MAC is **REDACTED**"
    assert history[1] == "Normal Event"


async def test_diagnostics_mac_fallback_keys(mock_hass, mock_entry):
    """Test fallback to 'mac' key when CONF_MAC is missing and handling of whitespace MAC."""
    # Setup 1: CONF_MAC missing, but "mac" key present
    mock_entry.data = {
        "mac": "11:22:33:44:55:66",
        "info": "Device 11:22:33:44:55:66",
    }
    mock_entry.title = "Test AC"
    mock_entry.unique_id = "test_unique_id"
    mock_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)
    assert result["entry"]["data"]["info"] == "Device **REDACTED**"

    # Setup 2: CONF_MAC is pure whitespace
    mock_entry.data = {
        CONF_MAC: "   ",
        "info": "Some text with spaces",
    }
    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)
    assert result["entry"]["data"]["info"] == "Some text with spaces"


async def test_diagnostics_boundary_length_5(mock_hass):
    """Test 5-character boundary: string of length 5 is NOT redacted when len(candidate) > 5."""
    entry = MagicMock()
    entry.data = {CONF_MAC: "12345"}
    entry.options = {"test_key": "ID is 12345"}
    entry.unique_id = "test_unique_id"
    entry.title = "Test AC"
    entry.domain = DOMAIN
    entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, entry)
    assert result["entry"]["options"]["test_key"] == "ID is 12345"


async def test_diagnostics_strict_dash_format(mock_hass):
    """Test strict dash-formatted MAC redaction."""
    entry = MagicMock()
    entry.data = {CONF_MAC: "AABBCCDDEEFF"}
    entry.options = {"mac_field": "My mac is AA-BB-CC-DD-EE-FF"}
    entry.unique_id = "test_unique_id"
    entry.title = "Test AC"
    entry.domain = DOMAIN
    entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, entry)
    assert result["entry"]["options"]["mac_field"] == "My mac is **REDACTED**"


async def test_diagnostics_isolated_mac_fallback_key(mock_hass):
    """Test isolated fallback to 'mac' key in entry.data when CONF_MAC, title, and unique_id are not set."""
    entry = MagicMock()
    entry.data = {"mac": "11:22:33:44:55:66"}
    entry.options = {"info": "MAC is 11:22:33:44:55:66"}
    entry.unique_id = None
    entry.title = None
    entry.domain = DOMAIN
    entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, entry)
    assert result["entry"]["options"]["info"] == "MAC is **REDACTED**"


async def test_diagnostics_bootstrapping_and_raw_state(mock_hass, mock_entry):
    """Test extraction of bootstrapping metrics, connection telemetry, and raw device state."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.data = DummyCoordinatorData(power="on")
    mock_coordinator.discovered_devices_count = 2
    mock_coordinator.skipped_devices_count = 1
    mock_coordinator.entities = ["climate.ac", "sensor.temp"]

    device1 = MagicMock()
    device1.raw_state = {"power": "on", "mac": "AA:11:22:33:44:55"}
    mock_coordinator.devices = {"dev1": device1}

    mock_controller = MagicMock()
    del mock_controller.connection_diagnostics  # Force cascade to get_diagnostics()
    mock_controller.get_diagnostics.return_value = {
        "is_connected": True,
        "socket_status": "open",
    }
    mock_coordinator.controller = mock_controller

    mock_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert result["bootstrapping"] == {
        "total_devices_discovered": 2,
        "skipped_devices_missing_info": 1,
        "active_entities": 2,
    }
    assert result["connection_telemetry"] == {
        "is_connected": True,
        "socket_status": "open",
    }
    assert result["raw_device_state"] == {
        "dev1": {"power": "on", "mac": "**REDACTED**"}
    }


async def test_diagnostics_controller_missing_methods(mock_hass) -> None:
    """Kill mutants that remove defensive getattr/callable checks in _extract_controller_diagnostics."""
    from custom_components.climate_ip.diagnostics import _extract_controller_diagnostics

    # 1. Controller without 'connection'
    mock_ctrl_no_conn = MagicMock(spec=[])
    assert _extract_controller_diagnostics(mock_ctrl_no_conn) == {}

    # 2. Controller with 'connection' but without 'get_diagnostics'
    # Use spec=[] to prevent auto-creation of connection_diagnostics
    mock_ctrl_no_diag = MagicMock(spec=[])
    mock_ctrl_no_diag.connection = MagicMock(spec=[])
    result_no_diag = _extract_controller_diagnostics(mock_ctrl_no_diag)
    assert result_no_diag == {}

    # 3. get_diagnostics on connection is not callable (e.g., a string)
    # Use spec=[] so connection_diagnostics doesn't auto-exist
    mock_ctrl_not_callable = MagicMock(spec=[])
    mock_ctrl_not_callable.connection = MagicMock(spec=[])
    mock_ctrl_not_callable.connection.get_diagnostics = "not_a_method"
    # Calling a string raises TypeError, not AttributeError — uncaught = crash.
    # But the Protocol cascade hits connection_diagnostics first (AttributeError from spec=[]),
    # then get_diagnostics() on controller (AttributeError from spec=[]),
    # then connection.get_diagnostics() which is a string — TypeError.
    with pytest.raises(TypeError):
        _extract_controller_diagnostics(mock_ctrl_not_callable)

    # 4. get_diagnostics returns a non-dict — Protocol trusts return type, passes through
    mock_ctrl_bad_return = MagicMock(spec=[])
    mock_ctrl_bad_return.connection = MagicMock()
    mock_ctrl_bad_return.connection.get_diagnostics.return_value = ["invalid", "list"]
    result_bad = _extract_controller_diagnostics(mock_ctrl_bad_return)
    assert result_bad == ["invalid", "list"]


async def test_diagnostics_bootstrapping_math_mutants(mock_hass) -> None:
    """Kill mutants altering arithmetic operations (+= to -=) and default values (0 to 1)."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"mac": "aa:bb:cc:dd:ee:ff"}
    entry.options = {}
    entry.unique_id = "test_unique"
    entry.title = "Test AC"
    entry.domain = DOMAIN

    # Create runtime_data with exact metrics
    entry.runtime_data = MagicMock()
    entry.runtime_data.discovered_devices_count = 5
    entry.runtime_data.skipped_devices_count = 2
    entry.runtime_data.entities = ["ent1", "ent2", "ent3"]  # len = 3
    entry.runtime_data.devices = {}  # No devices

    res = await async_get_config_entry_diagnostics(mock_hass, entry)

    boot = res.get("bootstrapping", {})
    assert boot.get("total_devices_discovered") == 5
    assert boot.get("skipped_devices_missing_info") == 2
    assert boot.get("active_entities") == 3


def test_diagnostics_raw_state_fallback():
    """Kill mutants in the elif hasattr(device, 'device_state') branch."""
    from custom_components.climate_ip.diagnostics import _extract_raw_device_state

    coordinator = MagicMock()
    device = MagicMock()
    # Delete raw_state to force the elif branch
    del device.raw_state
    device.device_state = {"temp": 24}

    coordinator.devices = {"dev_1": device}

    res = _extract_raw_device_state(coordinator)
    assert res == {"dev_1": {"temp": 24}}


async def test_deep_redact_substrings_strict_sort_order(mock_hass):
    """Kill mutants 4 and 7 in _deep_redact_substrings by enforcing length-descending sort order."""
    from custom_components.climate_ip.diagnostics import _deep_redact_substrings

    # "X" (len 1) is lexicographically larger than "AX" (len 2).
    # If sorted(key=len, reverse=True) is mutated to sorted(reverse=True) or key=None,
    # "X" would be sorted before "AX", producing "A**REDACTED**" instead of "**REDACTED**".
    threat_patterns = {"X", "AX"}
    text = "AX"

    redacted = _deep_redact_substrings(text, threat_patterns)
    assert redacted == "**REDACTED**"


async def test_diagnostics_multi_coordinator_bootstrapping_math(mock_hass, mock_entry):
    """Kill mutants in multi-coordinator bootstrapping math operations."""
    coord1 = MagicMock(spec=SamsungClimateCoordinator)
    coord1.data = None
    coord1.controller = object()
    coord1.discovered_devices_count = 3
    coord1.skipped_devices_count = 1
    coord1.entities = ["e1", "e2"]

    coord2 = MagicMock(spec=SamsungClimateCoordinator)
    coord2.data = None
    coord2.controller = object()
    coord2.discovered_devices_count = 2
    coord2.skipped_devices_count = 4
    coord2.entities = ["e3"]

    mock_entry.runtime_data = {
        "dev_1": coord1,
        "dev_2": coord2,
    }

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    boot = result.get("bootstrapping", {})
    assert boot.get("total_devices_discovered") == 5  # 3 + 2
    assert boot.get("skipped_devices_missing_info") == 5  # 1 + 4
    assert boot.get("active_entities") == 3  # 2 + 1


async def test_get_mac_threat_patterns_conf_mac_vs_string(mock_hass):
    """Kill mutants 3, 4, 6, 7 in _get_mac_threat_patterns by isolating CONF_MAC vs 'mac' fallback key."""
    from homeassistant.const import CONF_MAC

    from custom_components.climate_ip.diagnostics import _get_mac_threat_patterns

    # Case 1: CONF_MAC present, "mac" missing
    entry1 = MagicMock()
    entry1.data = {CONF_MAC: "AA:11:22:33:44:55"}
    entry1.title = None
    entry1.unique_id = None
    patterns1 = _get_mac_threat_patterns(entry1)
    assert "AA:11:22:33:44:55" in patterns1

    # Case 2: CONF_MAC missing, "mac" string key present
    entry2 = MagicMock()
    entry2.data = {"mac": "BB:11:22:33:44:55"}
    entry2.title = None
    entry2.unique_id = None
    patterns2 = _get_mac_threat_patterns(entry2)
    assert "BB:11:22:33:44:55" in patterns2


def test_extract_controller_diagnostics_via_connection():
    """Kill mutants in _extract_controller_diagnostics when connection has get_diagnostics."""
    from custom_components.climate_ip.diagnostics import _extract_controller_diagnostics

    controller = MagicMock(spec=["connection"])
    controller.connection = MagicMock()
    controller.connection.get_diagnostics.return_value = {"ping": 5, "connected": True}

    res = _extract_controller_diagnostics(controller)
    assert res == {"ping": 5, "connected": True}


def test_extract_raw_device_state_controller_fallbacks():
    """Kill mutants in _extract_raw_device_state main controller fallbacks."""
    from custom_components.climate_ip.diagnostics import _extract_raw_device_state

    # 1. Main controller raw_state
    coord1 = MagicMock(spec=["controller"])
    coord1.devices = {}
    coord1.controller = MagicMock(spec=["raw_state"])
    coord1.controller.raw_state = {"temp": 21}
    assert _extract_raw_device_state(coord1) == {"main": {"temp": 21}}

    # 2. Main controller device_state
    coord2 = MagicMock(spec=["controller"])
    coord2.devices = {}
    coord2.controller = MagicMock(spec=["device_state"])
    coord2.controller.device_state = {"mode": "cool"}
    assert _extract_raw_device_state(coord2) == {"main": {"mode": "cool"}}

    # 3. Main controller last_poll_data
    coord3 = MagicMock(spec=["controller"])
    coord3.devices = {}
    coord3.controller = MagicMock(spec=["last_poll_data"])
    coord3.controller.last_poll_data = {"status": "ok"}
    assert _extract_raw_device_state(coord3) == {"main": {"status": "ok"}}


async def test_diagnostics_top_level_keys(mock_hass):
    """Kill mutants altering top-level dictionary keys in async_get_config_entry_diagnostics."""
    from custom_components.climate_ip.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = MagicMock()
    entry.entry_id = "entry_123"
    entry.data = {}
    entry.options = {}
    entry.title = "AC"
    entry.domain = DOMAIN
    entry.unique_id = "uid"

    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.data = None
    mock_coord.devices = {}
    mock_coord.controller = MagicMock(spec=[])
    mock_coord.discovered_devices_count = 0
    mock_coord.skipped_devices_count = 0
    mock_coord.entities = []

    entry.runtime_data = mock_coord

    res = await async_get_config_entry_diagnostics(mock_hass, entry)

    # Strictly assert top-level dictionary key names
    assert "connection_telemetry" in res
    assert "raw_device_state" in res
    assert "bootstrapping" in res
    assert "entry" in res
    assert res["bootstrapping"]["total_devices_discovered"] == 0
    assert res["bootstrapping"]["skipped_devices_missing_info"] == 0


async def test_diagnostics_single_coordinator_default_fallback_metrics(mock_hass):
    """Kill mutants 22, 26, 31, 35 in single coordinator getattr default fallback values."""
    from custom_components.climate_ip.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = MagicMock()
    entry.entry_id = "test_single_fallback"
    entry.data = {}
    entry.options = {}
    entry.title = "Test AC"
    entry.domain = DOMAIN
    entry.unique_id = "uid"

    # Coordinator without discovered_devices_count or skipped_devices_count attributes
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.data = None
    mock_coord.devices = {}
    mock_coord.controller = object()
    del mock_coord.discovered_devices_count
    del mock_coord.skipped_devices_count
    mock_coord.entities = []

    entry.runtime_data = mock_coord

    res = await async_get_config_entry_diagnostics(mock_hass, entry)
    boot = res.get("bootstrapping", {})

    assert boot.get("total_devices_discovered") == 0
    assert boot.get("skipped_devices_missing_info") == 0


async def test_diagnostics_multi_coordinator_default_fallback_metrics(
    mock_hass, mock_entry
):
    """Kill mutants 95 and 104 in multi-coordinator getattr default fallback values."""
    from custom_components.climate_ip.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    coord1 = MagicMock(spec=SamsungClimateCoordinator)
    coord1.data = None
    coord1.controller = object()
    del coord1.discovered_devices_count
    del coord1.skipped_devices_count
    coord1.entities = []

    mock_entry.runtime_data = {"dev_1": coord1}

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    boot = result.get("bootstrapping", {})
    assert boot.get("total_devices_discovered") == 1
    assert boot.get("skipped_devices_missing_info") == 0


# ---------------------------------------------------------
# ESCUADRÓN FRANCOTIRADOR: EJECUCIÓN DIRECTA (0.001s Kill)
# ---------------------------------------------------------


def test_sniper_deep_redact_substrings():
    """Mata mutantes de recursión y ordenación al instante."""
    patterns = {"AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff"}

    payload = {
        "mac_1": "AABBCCDDEEFF",
        "nested_list": ["My MAC is aa:bb:cc:dd:ee:ff"],
        "nested_tuple": ("AABBCCDDEEFF",),
        "normal_string": "Hello World",
    }

    # If a mutant breaks recursion, this raises instantaneous TypeError
    res = _deep_redact_substrings(payload, patterns)

    assert res["mac_1"] == "**REDACTED**"
    assert res["nested_list"][0] == "My MAC is **REDACTED**"
    assert res["nested_tuple"][0] == "**REDACTED**"
    assert res["normal_string"] == "Hello World"


def test_sniper_get_mac_threat_patterns():
    """Mata mutantes aritméticos de formateo (los [i : i - 2])."""

    class MockEntry:
        data = {"mac": "AABBCCDDEEFF"}
        options = {}
        title = "Test AC Unit"
        unique_id = "AABBCCDDEEFF"

    # If a mutant changes string partition, it will fail here
    patterns = _get_mac_threat_patterns(MockEntry())

    assert "AABBCCDDEEFF" in patterns
    assert "AA:BB:CC:DD:EE:FF" in patterns
    assert "AA-BB-CC-DD-EE-FF" in patterns


def test_sniper_extract_controller_diagnostics():
    """Mata mutantes booleanos en la extracción del controlador."""

    class FakeController:
        connection_diagnostics = {"ping": 10}

    res = _extract_controller_diagnostics(FakeController())
    assert res == {"ping": 10}


def test_sniper_extract_raw_device_state():
    """Mata mutantes de bucles en la extracción de estado de dispositivos."""

    class FakeDevice:
        raw_state = {"temp": 22}

    class FakeCoordinator:
        devices = {"device_1": FakeDevice()}

    res = _extract_raw_device_state(FakeCoordinator())
    assert "device_1" in res
    assert res["device_1"]["temp"] == 22


def test_sniper_deep_redact_internals():
    """Mata timeouts en la lógica de ordenación, ignorecase y listas/tuplas."""
    from custom_components.climate_ip.diagnostics import _deep_redact_substrings

    # Mutantes 7, 9, 10: reverse=True y key=len (el más largo primero)
    assert _deep_redact_substrings("xabcdy", {"ab", "abcd"}) == "x**REDACTED**y"

    # Mutant 20: re.IGNORECASE
    assert _deep_redact_substrings("MAC_ADDRESS", {"mac_address"}) == "**REDACTED**"

    # Mutant 12: result = None (breaks base substitution)
    assert _deep_redact_substrings("test", {"no_match"}) == "test"

    # Mutants 28, 29, 34: Mutated lists and tuples (removing 'v')
    assert _deep_redact_substrings(["secret"], {"secret"}) == ["**REDACTED**"]
    assert _deep_redact_substrings(("secret",), {"secret"}) == ("**REDACTED**",)


def test_sniper_mac_boundary():
    """Kills mutant M47 (>= 5 instead of > 5)."""
    from custom_components.climate_ip.diagnostics import _get_mac_threat_patterns

    class MockEntry:
        data = {"mac": "12345"}  # Exactamente 5 caracteres
        title = ""
        unique_id = ""
        options = {}

    assert "12345" not in _get_mac_threat_patterns(MockEntry())

    class MockEntry6:
        data = {"mac": "123456"}  # Más de 5 caracteres
        title = ""
        unique_id = ""
        options = {}

    assert "123456" in _get_mac_threat_patterns(MockEntry6())


def test_sniper_extractors_typeerrors():
    """Mata mutantes estructurales de hasattr (ej. hasattr('raw_state'))."""
    from custom_components.climate_ip.diagnostics import (
        _extract_controller_diagnostics,
        _extract_raw_device_state,
    )

    class MockEmpty:
        pass

    class MockCoordinator:
        controller = MockEmpty()
        devices = {}

    # If a mutant changes hasattr(ctrl, "raw_state") to hasattr("raw_state"),
    # Python will raise TypeError immediately, killing mutant without using syrupy.
    assert _extract_controller_diagnostics(MockEmpty()) == {}
    assert _extract_raw_device_state(MockCoordinator()) == {}
