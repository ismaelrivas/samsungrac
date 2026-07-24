# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the diagnostics support in climate_ip."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from homeassistant.const import CONF_MAC

from custom_components.climate_ip.const import DOMAIN
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.diagnostics import (
    TO_REDACT,
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

