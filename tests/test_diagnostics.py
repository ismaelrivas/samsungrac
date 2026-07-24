# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the diagnostics support in climate_ip."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from custom_components.climate_ip.const import DOMAIN
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant


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
        assert (
            entry_data[key] == "**REDACTED**"
        ), f"Key '{key}' in TO_REDACT was not redacted!"


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
    mock_entry.data = {
        "level1": {
            "level2": {
                "token": "super_secret_token",
                "access_token": "oauth_token_123",
                "safe_key": "safe_value",
            }
        },
        "list_of_dicts": [{"mac": "AA:BB:CC", "other": "info"}, {"refresh_token": "refresh_123"}],
    }
    mock_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    diag_data = result["entry"]["data"]
    assert diag_data["level1"]["level2"]["token"] == "**REDACTED**"
    assert diag_data["level1"]["level2"]["access_token"] == "**REDACTED**"
    assert diag_data["level1"]["level2"]["safe_key"] == "safe_value"
    assert diag_data["list_of_dicts"][0]["mac"] == "**REDACTED**"
    assert diag_data["list_of_dicts"][0]["other"] == "info"
    assert diag_data["list_of_dicts"][1]["refresh_token"] == "**REDACTED**"
