"""Tests for OptionsFlowHandler in options_flow.py."""

import datetime

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_ip.config_flow import OptionsFlowHandler
from custom_components.climate_ip.const import (
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONF_POLL_INTERVAL,
    CONF_TARGET_TEMP_STEP,
    CONF_TEMP_NATIVE_TARGET,
    CONN_METHOD_AIOHTTP,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TARGET_TEMP_STEP,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
)


def get_schema_marker(schema: vol.Schema, key_name: str):
    """Search for a key in a vol.Schema and return the marker (Required/Optional) and its type."""
    for key, value_type in schema.schema.items():
        if key.schema == key_name:
            return key, value_type
    return None, None


@pytest.mark.asyncio
async def test_options_flow_empty_defaults(hass):
    """Test intrinsic defaults when options entry is empty."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] == "form", f"Expected form but got: {result}"
    assert result["step_id"] == "init"
    schema = result["data_schema"]

    conn_key, _ = get_schema_marker(schema, CONF_CONN_METHOD)
    assert conn_key.default() == CONN_METHOD_AIOHTTP

    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == str(datetime.timedelta(seconds=DEFAULT_POLL_INTERVAL))

    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT

    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)


@pytest.mark.asyncio
async def test_options_schema_target_temp_fallback_empty(hass):
    """Kill mutants in target temp fallback empty options."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    schema = flow._get_options_schema()

    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT

    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)


@pytest.mark.asyncio
async def test_options_flow_invalid_poll_interval(hass):
    """Test options flow handles invalid poll interval input."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init({CONF_POLL_INTERVAL: "invalid"})
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert result.get("data_schema") is not None
    assert result["errors"] == {CONF_POLL_INTERVAL: "invalid_poll_interval"}


@pytest.mark.asyncio
async def test_options_flow_success_valid_input(hass):
    """Test options flow successfully creates entry with valid input."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init(
        {
            CONF_POLL_INTERVAL: "00:02:00",
            CONF_TARGET_TEMP_STEP: "0.5",
        }
    )
    assert result["type"] == "create_entry"
    assert result["title"] == ""
    assert result["data"][CONF_POLL_INTERVAL] == 120
    assert result["data"][CONF_TARGET_TEMP_STEP] == 0.5


@pytest.mark.asyncio
async def test_options_flow_invalid_target_temp_step_fallback(hass):
    """Test options flow falls back to default when target temp step is invalid."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init(
        {
            CONF_TARGET_TEMP_STEP: "invalid_step",
        }
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_TARGET_TEMP_STEP] == DEFAULT_TARGET_TEMP_STEP
