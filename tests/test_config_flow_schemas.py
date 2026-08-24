# pylint: disable=protected-access,too-many-locals,line-too-long,too-many-statements,too-many-arguments,redefined-outer-name
"""Tests for ConfigFlowSchemasMixin in config_flow_schemas.py."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    UnitOfTemperature,
)
from homeassistant.helpers.selector import SelectSelectorMode, TextSelectorType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_CERT_FILE,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SMARTTHINGS_HOST,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
)


def get_schema_marker(schema: vol.Schema, key_name: str):
    """Search for a key in a vol.Schema and return the marker (Required/Optional) and its type."""
    for key, value_type in schema.schema.items():
        if key.schema == key_name:
            return key, value_type
    return None, None


# -----------------------------------------------------------------------------
# 1. Tests for _get_base_samsung_schema (Kills Mutants 2-6, 11-15, 17-21, 30-35, 37-40, 51-58, 67, 69, 72, 73)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_samsung_schema_empty_defaults():
    """Test _get_base_samsung_schema defaults when flow_data is completely empty."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {}

    schema = flow._get_base_samsung_schema(mac_required=True, is_8888=False)

    # 1. IP Address
    ip_key, ip_type = get_schema_marker(schema, CONF_IP_ADDRESS)
    assert isinstance(ip_key, vol.Required)
    assert ip_key.default() == ""
    assert ip_type is str

    # 2. MAC (required=True)
    mac_key, mac_type = get_schema_marker(schema, CONF_MAC)
    assert isinstance(mac_key, vol.Required)
    assert mac_key.default() == ""
    assert mac_type is str

    # 3. Name
    name_key, name_type = get_schema_marker(schema, CONF_NAME)
    assert isinstance(name_key, vol.Optional)
    assert name_key.default() == ""
    assert name_type is str

    # 4. Token (Kills M30-M35)
    tok_key, tok_type = get_schema_marker(schema, CONF_TOKEN)
    assert isinstance(tok_key, vol.Optional)
    assert tok_key.default() == ""
    assert tok_type is str

    # 5. Cert (Kills M37-M40)
    cert_key, cert_type = get_schema_marker(schema, CONF_CERT)
    assert isinstance(cert_key, vol.Optional)
    assert cert_key.default() == DEFAULT_CONF_CERT_FILE
    assert cert_type is str

    # 6. Poll interval default
    poll_key, poll_selector = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert isinstance(poll_key, vol.Optional)
    assert poll_key.default() == str(datetime.timedelta(seconds=DEFAULT_POLL_INTERVAL))
    assert poll_selector.config["type"] == TextSelectorType.TEXT

    # 7. Enable Polling (is_8888=False -> Kills M51, M53-M58)
    poll_flag_key, poll_flag_type = get_schema_marker(schema, CONF_ENABLE_POLLING)
    assert isinstance(poll_flag_key, vol.Optional)
    assert poll_flag_key.default() is DEFAULT_ENABLE_POLLING
    assert poll_flag_type is bool

    # 8. Temp Native Current & Target (Kills M67, M69, M72, M73)
    curr_key, curr_selector = get_schema_marker(schema, CONF_TEMP_NATIVE_CURRENT)
    assert isinstance(curr_key, vol.Optional)
    assert curr_key.default() == DEFAULT_CONF_TEMP_UNIT
    assert curr_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert curr_selector.config["options"] == [
        UnitOfTemperature.CELSIUS,
        UnitOfTemperature.FAHRENHEIT,
    ]

    targ_key, targ_selector = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert isinstance(targ_key, vol.Optional)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT
    assert targ_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert targ_selector.config["options"] == [
        UnitOfTemperature.CELSIUS,
        UnitOfTemperature.FAHRENHEIT,
    ]


@pytest.mark.asyncio
async def test_base_samsung_schema_populated_values_and_optional_mac():
    """Test _get_base_samsung_schema with populated flow_data and optional mac."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "00:11:22:33:44:55",
        CONF_NAME: "My AC",
        CONF_TOKEN: "secret_tok",
        CONF_CERT: "custom_cert.pem",
        CONF_POLL_INTERVAL: 60,
        CONF_ENABLE_POLLING: False,
        CONF_TEMP_NATIVE_CURRENT: UnitOfTemperature.FAHRENHEIT,
        CONF_TEMP_NATIVE_TARGET: UnitOfTemperature.FAHRENHEIT,
    }

    # mac_required=False, is_8888=False
    schema = flow._get_base_samsung_schema(mac_required=False, is_8888=False)

    ip_key, _ = get_schema_marker(schema, CONF_IP_ADDRESS)
    assert ip_key.default() == "192.168.1.100"

    mac_key, _ = get_schema_marker(schema, CONF_MAC)
    assert isinstance(mac_key, vol.Optional)
    assert mac_key.default() == "00:11:22:33:44:55"

    name_key, _ = get_schema_marker(schema, CONF_NAME)
    assert name_key.default() == "My AC"

    tok_key, _ = get_schema_marker(schema, CONF_TOKEN)
    assert tok_key.default() == "secret_tok"

    cert_key, _ = get_schema_marker(schema, CONF_CERT)
    assert cert_key.default() == "custom_cert.pem"

    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == "0:01:00"

    poll_flag_key, _ = get_schema_marker(schema, CONF_ENABLE_POLLING)
    assert poll_flag_key.default() is False

    curr_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_CURRENT)
    assert curr_key.default() == UnitOfTemperature.FAHRENHEIT

    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == UnitOfTemperature.FAHRENHEIT


@pytest.mark.asyncio
async def test_base_samsung_schema_poll_interval_matrix():
    """Test all poll interval conversion branches in _get_base_samsung_schema (Kills M2-M6, M11-M15)."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    # 1. Non-integer valid string
    flow.flow_data = {CONF_POLL_INTERVAL: "invalid_str"}
    schema1 = flow._get_base_samsung_schema(mac_required=True, is_8888=False)
    poll_key1, _ = get_schema_marker(schema1, CONF_POLL_INTERVAL)
    assert poll_key1.default() == "invalid_str"

    # 2. None value in flow_data
    flow.flow_data = {CONF_POLL_INTERVAL: None}
    schema2 = flow._get_base_samsung_schema(mac_required=True, is_8888=False)
    poll_key2, _ = get_schema_marker(schema2, CONF_POLL_INTERVAL)
    assert poll_key2.default() == ""


@pytest.mark.asyncio
async def test_samsung_2878_and_8888_schema_differences():
    """Test _get_samsung_2878_schema and _get_samsung_8888_schema methods."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    schema_2878 = flow._get_samsung_2878_schema(mac_required=True)
    poll_key_2878, _ = get_schema_marker(schema_2878, CONF_ENABLE_POLLING)
    assert poll_key_2878 is not None

    schema_8888 = flow._get_samsung_8888_schema(mac_required=False)
    poll_key_8888, _ = get_schema_marker(schema_8888, CONF_ENABLE_POLLING)
    assert poll_key_8888 is None


# -----------------------------------------------------------------------------
# 2. Tests for _get_smartthings_token (Kills Mutants 3, 4)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_smartthings_token_discovery_branches():
    """Test _get_smartthings_token when SmartThings entry is present, has access_token, or is missing."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    # 1. Official SmartThings entry exists with valid access_token
    entry_with_tok = MockConfigEntry(
        domain="smartthings", data={"access_token": "st_token_xyz"}
    )
    flow.hass.config_entries.async_entries.return_value = [entry_with_tok]
    assert flow._get_smartthings_token() == "st_token_xyz"

    # 2. SmartThings entry exists but access_token is None / missing
    entry_empty = MockConfigEntry(domain="smartthings", data={})
    flow.hass.config_entries.async_entries.return_value = [entry_empty]
    assert flow._get_smartthings_token() == ""

    # 3. No SmartThings entry at all
    flow.hass.config_entries.async_entries.return_value = []
    assert flow._get_smartthings_token() is None


# -----------------------------------------------------------------------------
# 3. Tests for _get_rest_api_schema (Kills Mutants 5, 6, 8, 9, 10, 16-18, 20-23, 36)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rest_api_schema_smartthings_hvac_defaults():
    """Test _get_rest_api_schema for SMARTTHINGS_HVAC with token auto-fill and host default."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    entry_with_tok = MockConfigEntry(
        domain="smartthings", data={"access_token": "auto_st_token"}
    )
    flow.hass.config_entries.async_entries.return_value = [entry_with_tok]

    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        # No IP, no token, no poll interval provided
    }

    schema = flow._get_rest_api_schema()

    # IP Address default is DEFAULT_SMARTTHINGS_HOST
    ip_key, ip_type = get_schema_marker(schema, CONF_IP_ADDRESS)
    assert isinstance(ip_key, vol.Required)
    assert ip_key.default() == DEFAULT_SMARTTHINGS_HOST
    assert ip_type is str

    # Device ID is present
    dev_id_key, dev_id_type = get_schema_marker(schema, CONF_DEVICE_ID)
    assert isinstance(dev_id_key, vol.Optional)
    assert dev_id_type is str

    # Token default is auto-filled from SmartThings
    token_key, token_type = get_schema_marker(schema, CONF_TOKEN)
    assert isinstance(token_key, vol.Required)
    assert token_key.default() == "auto_st_token"
    assert token_type is str

    # Name is present
    _, name_type = get_schema_marker(schema, CONF_NAME)
    assert name_type is str

    # Poll interval default is DEFAULT_POLL_INTERVAL
    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == str(datetime.timedelta(seconds=DEFAULT_POLL_INTERVAL))


@pytest.mark.asyncio
async def test_rest_api_schema_smartthings_dhw_defaults():
    """Test _get_rest_api_schema for SMARTTHINGS_DHW (Kills M5 is_st DHW condition flip)."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []

    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW,
    }

    schema = flow._get_rest_api_schema()

    ip_key, _ = get_schema_marker(schema, CONF_IP_ADDRESS)
    assert ip_key.default() == DEFAULT_SMARTTHINGS_HOST

    dev_id_key, _ = get_schema_marker(schema, CONF_DEVICE_ID)
    assert dev_id_key is not None

    token_key, _ = get_schema_marker(schema, CONF_TOKEN)
    assert token_key.default() == ""


@pytest.mark.asyncio
async def test_rest_api_schema_non_smartthings_device():
    """Test _get_rest_api_schema for non-SmartThings generic REST device."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []

    # 1. Without IP in flow_data -> Required(CONF_IP_ADDRESS) without default
    flow.flow_data = {
        CONF_DEVICE_TYPE: "generic_rest",
    }
    schema1 = flow._get_rest_api_schema()
    ip_key1, _ = get_schema_marker(schema1, CONF_IP_ADDRESS)
    assert isinstance(ip_key1, vol.Required)
    assert ip_key1.default is vol.UNDEFINED or not callable(
        getattr(ip_key1, "default", None)
    )
    dev_id_key1, _ = get_schema_marker(schema1, CONF_DEVICE_ID)
    assert dev_id_key1 is None  # Not present for non-ST

    # 2. With IP in flow_data -> Required(CONF_IP_ADDRESS, default="10.0.0.5")
    flow.flow_data = {
        CONF_DEVICE_TYPE: "generic_rest",
        CONF_IP_ADDRESS: "10.0.0.5",
        CONF_TOKEN: "direct_token",
    }
    schema2 = flow._get_rest_api_schema()
    ip_key2, _ = get_schema_marker(schema2, CONF_IP_ADDRESS)
    assert ip_key2.default() == "10.0.0.5"
    tok_key2, _ = get_schema_marker(schema2, CONF_TOKEN)
    assert tok_key2.default() == "direct_token"


@pytest.mark.asyncio
async def test_rest_api_schema_poll_interval_matrix():
    """Test poll interval conversion branches in _get_rest_api_schema (Kills M6, M8-10, M16-18, M20-21)."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []

    # 1. Custom integer in flow_data
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_POLL_INTERVAL: 120,
    }
    schema1 = flow._get_rest_api_schema()
    poll_key1, _ = get_schema_marker(schema1, CONF_POLL_INTERVAL)
    assert poll_key1.default() == "0:02:00"

    # 2. Invalid string in flow_data
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_POLL_INTERVAL: "not_a_number",
    }
    schema2 = flow._get_rest_api_schema()
    poll_key2, _ = get_schema_marker(schema2, CONF_POLL_INTERVAL)
    assert poll_key2.default() == "not_a_number"

    # 3. None in flow_data
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_POLL_INTERVAL: None,
    }
    schema3 = flow._get_rest_api_schema()
    poll_key3, _ = get_schema_marker(schema3, CONF_POLL_INTERVAL)
    assert poll_key3.default() == ""
