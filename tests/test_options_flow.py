# pylint: disable=protected-access,too-many-locals,line-too-long
"""Tests for OptionsFlowHandler in options_flow.py."""

from __future__ import annotations

import datetime

from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.selector import SelectSelectorMode, TextSelectorType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.climate_ip.config_flow import OptionsFlowHandler
from custom_components.climate_ip.const import (
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_POLLING,
    CONF_POLL_INTERVAL,
    CONF_TARGET_TEMP_STEP,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    CONN_METHOD_AIOHTTP,
    CONN_METHOD_RAW,
    CONN_METHOD_REQUESTS,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_ENABLE_POLLING,
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
async def test_options_flow_empty_defaults():
    """Test intrinsic defaults and exact selector configurations when options entry is empty."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )

    flow = OptionsFlowHandler(entry)
    assert flow._config_entry is entry

    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    schema = result["data_schema"]
    assert isinstance(schema, vol.Schema)

    # 1. Connection method selector (Kills Mutant 12 translation_key & selectors)
    conn_key, conn_selector = get_schema_marker(schema, CONF_CONN_METHOD)
    assert isinstance(conn_key, vol.Required)
    assert conn_key.default() == CONN_METHOD_AIOHTTP
    assert conn_selector.config["translation_key"] == "connection_method"
    assert conn_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert conn_selector.config["options"] == [
        {"value": CONN_METHOD_REQUESTS, "label": "Legacy (Obsolete)"},
        {"value": CONN_METHOD_AIOHTTP, "label": "Modern (aiohttp)"},
        {"value": CONN_METHOD_RAW, "label": "Robust (raw socket)"},
    ]

    # 2. Poll interval
    poll_key, poll_selector = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert isinstance(poll_key, vol.Required)
    assert poll_key.default() == str(datetime.timedelta(seconds=DEFAULT_POLL_INTERVAL))
    assert poll_selector.config["type"] == TextSelectorType.TEXT

    # 3. Temp native current
    curr_key, curr_selector = get_schema_marker(schema, CONF_TEMP_NATIVE_CURRENT)
    assert isinstance(curr_key, vol.Required)
    assert curr_key.default() == DEFAULT_CONF_TEMP_UNIT
    assert curr_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert curr_selector.config["options"] == [
        UnitOfTemperature.CELSIUS,
        UnitOfTemperature.FAHRENHEIT,
    ]

    # 4. Temp native target
    targ_key, targ_selector = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert isinstance(targ_key, vol.Required)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT
    assert targ_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert targ_selector.config["options"] == [
        UnitOfTemperature.CELSIUS,
        UnitOfTemperature.FAHRENHEIT,
    ]

    # 5. Enable polling
    poll_flag_key, poll_flag_type = get_schema_marker(schema, CONF_ENABLE_POLLING)
    assert isinstance(poll_flag_key, vol.Optional)
    assert poll_flag_key.default() == DEFAULT_ENABLE_POLLING
    assert poll_flag_type is bool

    # 6. Target temp step
    step_key, step_selector = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert isinstance(step_key, vol.Optional)
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)
    assert step_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert step_selector.config["options"] == [
        {"value": "0.1", "label": "0.1°"},
        {"value": "0.5", "label": "0.5°"},
        {"value": "1.0", "label": "1.0°"},
    ]


@pytest.mark.asyncio
async def test_options_schema_unsupported_device_type():
    """Test schema when device type does not support AIOHTTP selector."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: "generic_unsupported"},
        options={},
    )

    flow = OptionsFlowHandler(entry)
    schema = flow._get_options_schema()

    conn_key, _ = get_schema_marker(schema, CONF_CONN_METHOD)
    assert conn_key is None


@pytest.mark.asyncio
async def test_options_schema_poll_interval_fallback_non_int():
    """Test poll interval formatting fallback when stored option is non-integer string."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={CONF_POLL_INTERVAL: "invalid_time_string"},
    )

    flow = OptionsFlowHandler(entry)
    schema = flow._get_options_schema()

    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == "invalid_time_string"


@pytest.mark.asyncio
async def test_options_schema_target_temp_fallback_empty():
    """Test target temp fallback when options and data are empty."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})

    flow = OptionsFlowHandler(entry)
    schema = flow._get_options_schema()

    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT

    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)


@pytest.mark.asyncio
async def test_options_flow_invalid_poll_interval():
    """Test options flow handles invalid poll interval input and returns correct form schema."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )

    flow = OptionsFlowHandler(entry)

    result = await flow.async_step_init({CONF_POLL_INTERVAL: "invalid_value"})
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert isinstance(result["step_id"], str)
    assert isinstance(result.get("data_schema"), vol.Schema)
    assert result["errors"] == {CONF_POLL_INTERVAL: "invalid_poll_interval"}
    assert result["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"


@pytest.mark.asyncio
async def test_options_flow_success_valid_input():
    """Test options flow successfully creates entry with valid input."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )

    flow = OptionsFlowHandler(entry)

    result = await flow.async_step_init(
        {
            CONF_POLL_INTERVAL: "00:02:00",
            CONF_TARGET_TEMP_STEP: "0.5",
        }
    )
    assert result["type"] == "create_entry"
    assert result["title"] == ""
    assert isinstance(result["title"], str)
    assert result["data"][CONF_POLL_INTERVAL] == 120
    assert isinstance(result["data"][CONF_POLL_INTERVAL], int)
    assert result["data"][CONF_TARGET_TEMP_STEP] == 0.5
    assert isinstance(result["data"][CONF_TARGET_TEMP_STEP], float)


@pytest.mark.asyncio
async def test_options_flow_none_poll_interval_and_missing_keys():
    """Test options flow when poll interval is None or keys are omitted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )

    flow = OptionsFlowHandler(entry)

    # 1. user_input with CONF_POLL_INTERVAL as None
    result = await flow.async_step_init({CONF_POLL_INTERVAL: None})
    assert result["type"] == "create_entry"
    assert result["title"] == ""
    assert result["data"][CONF_POLL_INTERVAL] is None

    # 2. user_input without CONF_POLL_INTERVAL and without CONF_TARGET_TEMP_STEP
    result2 = await flow.async_step_init({CONF_ENABLE_POLLING: True})
    assert result2["type"] == "create_entry"
    assert result2["title"] == ""
    assert result2["data"] == {CONF_ENABLE_POLLING: True}


@pytest.mark.asyncio
async def test_options_flow_invalid_target_temp_step_fallback():
    """Test options flow falls back to default when target temp step is invalid or non-numeric."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )

    flow = OptionsFlowHandler(entry)

    # String that cannot convert to float
    result = await flow.async_step_init(
        {
            CONF_TARGET_TEMP_STEP: "invalid_step",
        }
    )
    assert result["type"] == "create_entry"
    assert result["title"] == ""
    assert result["data"][CONF_TARGET_TEMP_STEP] == DEFAULT_TARGET_TEMP_STEP
    assert isinstance(result["data"][CONF_TARGET_TEMP_STEP], float)

    # Incompatible type (dict/list) that triggers TypeError
    result_type_error = await flow.async_step_init(
        {
            CONF_TARGET_TEMP_STEP: ["bad_type"],
        }
    )
    assert result_type_error["type"] == "create_entry"
    assert result_type_error["data"][CONF_TARGET_TEMP_STEP] == DEFAULT_TARGET_TEMP_STEP
