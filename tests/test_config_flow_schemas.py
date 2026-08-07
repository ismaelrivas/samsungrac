"""Test config flow schemas to kill mutants."""

from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
)


def get_schema_marker(schema: vol.Schema, key_name: str):
    """Search for a key in a vol.Schema and return the marker (Required/Optional) and its type."""
    for key, value_type in schema.schema.items():
        if key.schema == key_name:
            return key, value_type
    return None, None


@pytest.mark.asyncio
async def test_rest_api_schema_mutants_annihilation():
    """Kill mutants of _get_rest_api_schema."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []  # Simulate no SmartThings

    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_IP_ADDRESS: "192.168.1.99",
    }

    schema = flow._get_rest_api_schema()

    dev_id_key, dev_id_type = get_schema_marker(schema, CONF_DEVICE_ID)
    assert dev_id_type is str

    _, name_type = get_schema_marker(schema, CONF_NAME)
    assert name_type is str

    ip_key, ip_type = get_schema_marker(schema, CONF_IP_ADDRESS)
    assert isinstance(ip_key, vol.Required)
    assert ip_key.default() == "192.168.1.99"
    assert ip_type is str

    token_key, _ = get_schema_marker(schema, CONF_TOKEN)
    assert token_key.default() == ""


@pytest.mark.asyncio
async def test_base_samsung_schema_mutants():
    """Verify mutant kill of _get_base_samsung_schema."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_POLL_INTERVAL: None,
    }

    schema = flow._get_base_samsung_schema(mac_required=True, is_8888=False)

    mac_key, mac_type = get_schema_marker(schema, CONF_MAC)
    assert isinstance(mac_key, vol.Required)
    assert mac_type is str


@pytest.mark.asyncio
async def test_samsung_2878_and_8888_schemas():
    """Test _get_samsung_2878_schema and _get_samsung_8888_schema methods."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
    }

    schema_2878 = flow._get_samsung_2878_schema(mac_required=True)
    poll_key_2878, _ = get_schema_marker(schema_2878, CONF_ENABLE_POLLING)
    assert poll_key_2878 is not None  # is_8888 is False -> CONF_ENABLE_POLLING present

    schema_8888 = flow._get_samsung_8888_schema(mac_required=False)
    poll_key_8888, _ = get_schema_marker(schema_8888, CONF_ENABLE_POLLING)
    assert poll_key_8888 is None  # is_8888 is True -> CONF_ENABLE_POLLING omitted


@pytest.mark.asyncio
async def test_rest_api_schema_invalid_poll_interval():
    """Test _get_rest_api_schema when CONF_POLL_INTERVAL is invalid string."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_POLL_INTERVAL: "invalid_val",
    }

    schema = flow._get_rest_api_schema()
    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == "invalid_val"
