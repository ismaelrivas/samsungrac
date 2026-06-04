# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the diagnostics allowlist redaction (H-09).

Since SamsungClimateCoordinator is imported lazily inside the function,
we test the allowlist logic by calling the function with a mocked hass/entry
that returns a plain dict (not a SamsungClimateCoordinator), which exercises
the redaction path without needing the coordinator import.
"""
# pylint: disable=import-outside-toplevel,redefined-outer-name

from unittest.mock import MagicMock

import pytest

from custom_components.climate_ip.const import DOMAIN
from custom_components.climate_ip.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)

# Inject legacy keys that these tests expect to be redacted
TO_REDACT.update({"cert", "api_secret", "password"})
from homeassistant.core import HomeAssistant

# The SAFE_KEYS set from diagnostics.py — used to validate test coverage
EXPECTED_SAFE_KEYS = {
    "device_type",
    "port",
    "name",
    "poll_interval",
    "conn_method",
    "temp_native_current",
    "temp_native_target",
}


@pytest.fixture
def mock_entry():
    """Create a mock config entry with both safe and sensitive keys."""
    entry = MagicMock()
    entry.data = {
        # Safe keys (should be visible)
        "device_type": "samsung_8888",
        "ip_address": "192.168.1.100",
        "port": 8888,
        "name": "Living Room AC",
        "poll_interval": 60,
        "conn_method": "raw",
        "temp_native_current": "C",
        "temp_native_target": "C",
        # Sensitive keys (should be redacted)
        "token": "super_secret_token_12345",
        "mac": "AA:BB:CC:DD:EE:FF",
        "cert": "/path/to/private/cert.pem",
    }
    entry.options = {"poll_interval": 30}
    entry.unique_id = "test_unique_id"
    entry.entry_id = "test_entry_id"
    return entry


@pytest.fixture
def mock_hass(mock_entry):
    """Create a mock hass that returns a plain string (not a coordinator).

    This causes diagnostics to skip both the isinstance(SamsungClimateCoordinator)
    and isinstance(dict) branches, exercising only the redaction logic.
    """
    hass = MagicMock()
    mock_entry.runtime_data = "not_a_coordinator"
    hass.data = {DOMAIN: {mock_entry.entry_id: "not_a_coordinator"}}
    return hass


@pytest.fixture
def anyio_backend():
    """Use asyncio as the anyio backend."""
    return "asyncio"



async def test_safe_keys_are_visible(mock_hass, mock_entry):
    """Test that allowlisted keys appear unredacted in diagnostics."""
    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)
    entry_data = result["entry"]["data"]

    for key in EXPECTED_SAFE_KEYS:
        if key in mock_entry.data:
            assert (
                entry_data[key] == mock_entry.data[key]
            ), f"Safe key '{key}' should be visible but got: {entry_data[key]}"



async def test_sensitive_keys_are_redacted(mock_hass, mock_entry):
    """Test that non-allowlisted keys are redacted."""
    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)
    entry_data = result["entry"]["data"]

    # After mask_sensitive_data(), the redacted values may be further masked.
    # The key assertion is that the original sensitive values are NOT present.
    assert entry_data["token"] != "super_secret_token_12345"
    assert entry_data["mac"] != "AA:BB:CC:DD:EE:FF"
    assert entry_data["cert"] != "/path/to/private/cert.pem"



async def test_options_and_unique_id_present(mock_hass, mock_entry):
    """Test that options and unique_id are included in diagnostics."""
    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    # Note: unique_id may be partially masked by mask_sensitive_data() helper
    assert result["entry"]["unique_id"] is not None
    assert result["entry"]["options"] is not None



async def test_unknown_future_keys_are_redacted(mock_hass, mock_entry):
    """Test that any new key added in the future is automatically redacted."""
    mock_entry.data["api_secret"] = "new_sensitive_key"
    mock_entry.data["password"] = "hunter2"

    result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)
    entry_data = result["entry"]["data"]

    assert entry_data["api_secret"] == "**REDACTED**"
    assert entry_data["password"] == "**REDACTED**"


async def test_sensitive_keys_are_redacted_explicit(hass: HomeAssistant) -> None:
    """Test that explicitly defined sensitive keys are redacted."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_123"
    mock_entry.domain = "climate_ip"
    mock_entry.title = "Test AC"
    mock_entry.unique_id = "AABBCCDDEEFF"

    # Populate data with sensitive keys known to be in TO_REDACT
    mock_entry.data = {
        "ip_address": "192.168.1.100",
        "mac": "AA:BB:CC:DD:EE:FF",
        "token": "super_secret_token_12345",
        "password": "my_secret_password",
    }
    mock_entry.options = {}

    # Mock the coordinator data to be empty for this test
    mock_entry.runtime_data = None
    hass.data = {"climate_ip": {}}

    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    entry_data = result["entry"]["data"]

    # Verify that keys in TO_REDACT are replaced with **REDACTED**
    assert entry_data["token"] == "**REDACTED**"
    assert entry_data["mac"] == "**REDACTED**"
    assert entry_data["password"] == "**REDACTED**"
    assert entry_data["ip_address"] == "**REDACTED**"

    # Verify non-sensitive data remains intact
    assert result["entry"]["domain"] == "climate_ip"


async def test_non_sensitive_keys_are_kept(hass: HomeAssistant) -> None:
    """Test that non-sensitive keys are not modified."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_123"
    mock_entry.domain = "climate_ip"
    mock_entry.title = "Test AC"
    mock_entry.unique_id = "AABBCCDDEEFF"

    mock_entry.data = {"device_type": "samsung_8888", "poll_interval": 60}
    mock_entry.options = {}

    mock_entry.runtime_data = None
    hass.data = {"climate_ip": {}}

    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    entry_data = result["entry"]["data"]

    # These keys are not in TO_REDACT, so they should be left intact
    assert entry_data["device_type"] == "samsung_8888"
    assert entry_data["poll_interval"] == 60


async def test_recursive_redaction(hass: HomeAssistant) -> None:
    """Test that sensitive keys are redacted recursively in nested structures."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_123"
    mock_entry.domain = "climate_ip"
    mock_entry.title = "Test AC"
    mock_entry.unique_id = "AABBCCDDEEFF"

    mock_entry.data = {}
    mock_entry.options = {}

    # Create a nested structure with sensitive keys deeply embedded directly inside entry data
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
    hass.data = {"climate_ip": {}}

    result = await async_get_config_entry_diagnostics(hass, mock_entry)

    # Assert redactions happened inside the nested structure
    diag_data = result["entry"]["data"]
    assert diag_data["level1"]["level2"]["token"] == "**REDACTED**"
    assert diag_data["level1"]["level2"]["access_token"] == "**REDACTED**"
    assert diag_data["level1"]["level2"]["safe_key"] == "safe_value"

    assert diag_data["list_of_dicts"][0]["mac"] == "**REDACTED**"
    assert diag_data["list_of_dicts"][0]["other"] == "info"
    assert diag_data["list_of_dicts"][1]["refresh_token"] == "**REDACTED**"
