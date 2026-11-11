# pylint: disable=protected-access,too-many-locals,line-too-long
"""Tests for OptionsFlowHandler in options_flow.py."""

import datetime
from unittest.mock import MagicMock

import probatio as vol
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from custom_components.climate_ip.options_flow import OptionsFlowHandler
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.selector import SelectSelectorMode, TextSelectorType


def get_schema_marker(schema: vol.Schema, key_name: str):
    """Search for a key in a vol.Schema and return the marker (Required/Optional) and its type."""
    for key, value_type in schema.schema.items():
        if key.schema == key_name:
            return key, value_type
    return None, None


@pytest.mark.asyncio
async def test_options_flow_handler_init():
    """Test OptionsFlowHandler explicit initialization with config_entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DEVICE_TYPE: "some_device"})
    flow = OptionsFlowHandler(entry)

    result = await flow.async_step_init()
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_options_flow_handler_zero_arg():
    """Test OptionsFlowHandler zero-arg initialization and fallback to self.config_entry."""
    flow = OptionsFlowHandler()

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DEVICE_TYPE: "some_device"})
    mock_hass = MagicMock()
    mock_hass.config_entries.async_get_known_entry.return_value = entry
    flow.hass = mock_hass
    flow.handler = entry.entry_id

    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert flow.config_entry == entry


@pytest.mark.asyncio
async def test_options_flow_empty_defaults():
    """Test intrinsic defaults and exact selector configurations when options entry is empty."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )

    flow = OptionsFlowHandler(entry)
    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    schema = result["data_schema"]
    assert isinstance(schema, vol.Schema)

    # 1. Connection method selector
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
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878},
        options={},
    )

    flow = OptionsFlowHandler(entry)
    result = await flow.async_step_init()
    schema = result["data_schema"]

    conn_key, _ = get_schema_marker(schema, CONF_CONN_METHOD)
    assert conn_key is None


@pytest.mark.asyncio
async def test_options_schema_options_precedence_over_data():
    """Test that existing options override data values in schema defaults."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_CONN_METHOD: CONN_METHOD_AIOHTTP,
            CONF_POLL_INTERVAL: 10,
            CONF_TARGET_TEMP_STEP: 1.0,
        },
        options={
            CONF_CONN_METHOD: CONN_METHOD_RAW,
            CONF_POLL_INTERVAL: 20,
            CONF_ENABLE_POLLING: False,
            CONF_TARGET_TEMP_STEP: 0.5,
            CONF_TEMP_NATIVE_CURRENT: UnitOfTemperature.FAHRENHEIT,
            CONF_TEMP_NATIVE_TARGET: UnitOfTemperature.CELSIUS,
        },
    )

    flow = OptionsFlowHandler(entry)
    result = await flow.async_step_init()
    schema = result["data_schema"]

    conn_key, _ = get_schema_marker(schema, CONF_CONN_METHOD)
    assert conn_key.default() == CONN_METHOD_RAW

    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == "0:00:20"

    poll_flag_key, _ = get_schema_marker(schema, CONF_ENABLE_POLLING)
    assert poll_flag_key.default() is False

    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == "0.5"

    curr_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_CURRENT)
    assert curr_key.default() == UnitOfTemperature.FAHRENHEIT

    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == UnitOfTemperature.CELSIUS


@pytest.mark.asyncio
async def test_options_schema_data_fallback_when_options_empty():
    """Test that schema falls back to entry data values when options is empty."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_CONN_METHOD: CONN_METHOD_RAW,
            CONF_TARGET_TEMP_STEP: 1.0,
        },
        options={},
    )

    flow = OptionsFlowHandler(entry)
    result = await flow.async_step_init()
    schema = result["data_schema"]

    conn_key, _ = get_schema_marker(schema, CONF_CONN_METHOD)
    assert conn_key.default() == CONN_METHOD_RAW

    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == "1.0"


@pytest.mark.asyncio
async def test_options_schema_poll_interval_fallback_non_int():
    """Test poll interval formatting fallback when stored option is non-integer string."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={CONF_POLL_INTERVAL: "invalid_time_string"},
    )

    flow = OptionsFlowHandler(entry)
    result = await flow.async_step_init()
    schema = result["data_schema"]

    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == "invalid_time_string"


@pytest.mark.asyncio
async def test_options_schema_target_temp_fallback_empty():
    """Test target temp fallback when options and data are empty."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})

    flow = OptionsFlowHandler(entry)
    result = await flow.async_step_init()
    schema = result["data_schema"]

    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT

    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)


@pytest.mark.asyncio
async def test_options_flow_async_step_init_show_form():
    """Test async_step_init without user_input shows the init form."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )

    flow = OptionsFlowHandler(entry)
    result = await flow.async_step_init(None)

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert isinstance(result["data_schema"], vol.Schema)


@pytest.mark.asyncio
async def test_options_flow_async_step_init_success_valid_input():
    """Test options flow successfully creates entry with valid input and exact types."""
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

    # Also test integer boundaries directly
    res_int = await flow.async_step_init(
        {
            CONF_POLL_INTERVAL: MIN_POLL_INTERVAL,
            CONF_TARGET_TEMP_STEP: 1.0,
        }
    )
    assert res_int["type"] == "create_entry"
    assert res_int["data"][CONF_POLL_INTERVAL] == MIN_POLL_INTERVAL
    assert res_int["data"][CONF_TARGET_TEMP_STEP] == 1.0


@pytest.mark.asyncio
async def test_options_flow_async_step_init_invalid_poll_interval_errors():
    """Test options flow handles invalid poll interval input and returns form with error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    flow = OptionsFlowHandler(entry)

    # 1. Non-numeric / invalid time format
    result = await flow.async_step_init({CONF_POLL_INTERVAL: "invalid_value"})
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert isinstance(result["step_id"], str)
    assert isinstance(result.get("data_schema"), vol.Schema)
    assert result["errors"] == {CONF_POLL_INTERVAL: "invalid_poll_interval"}

    # 2. Below minimum boundary (< MIN_POLL_INTERVAL)
    result_below_min = await flow.async_step_init(
        user_input={CONF_POLL_INTERVAL: MIN_POLL_INTERVAL - 1}
    )
    assert result_below_min["type"] == "form"
    assert result_below_min["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    # 3. Above maximum boundary (> MAX_POLL_INTERVAL)
    result_above_max = await flow.async_step_init(
        user_input={CONF_POLL_INTERVAL: MAX_POLL_INTERVAL + 1}
    )
    assert result_above_max["type"] == "form"
    assert result_above_max["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"


@pytest.mark.asyncio
async def test_options_flow_async_step_init_none_poll_interval():
    """Test options flow when poll interval is explicitly None."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    flow = OptionsFlowHandler(entry)

    result = await flow.async_step_init({CONF_POLL_INTERVAL: None})
    assert result["type"] == "create_entry"
    assert result["title"] == ""
    assert result["data"][CONF_POLL_INTERVAL] is None


@pytest.mark.asyncio
async def test_options_flow_async_step_init_missing_optional_keys():
    """Test options flow when keys are omitted from user_input."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    flow = OptionsFlowHandler(entry)

    # 1. Empty dict
    result_empty = await flow.async_step_init({})
    assert result_empty["type"] == "create_entry"
    assert result_empty["data"] == {}

    # 2. Dict with only enable_polling
    result_polling = await flow.async_step_init({CONF_ENABLE_POLLING: True})
    assert result_polling["type"] == "create_entry"
    assert result_polling["data"] == {CONF_ENABLE_POLLING: True}


@pytest.mark.asyncio
async def test_options_flow_async_step_init_target_temp_step_fallbacks():
    """Test options flow falls back to default when target temp step raises ValueError or TypeError."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    flow = OptionsFlowHandler(entry)

    # 1. ValueError: String that cannot convert to float
    result_val = await flow.async_step_init({CONF_TARGET_TEMP_STEP: "invalid_step"})
    assert result_val["type"] == "create_entry"
    assert result_val["title"] == ""
    assert result_val["data"][CONF_TARGET_TEMP_STEP] == DEFAULT_TARGET_TEMP_STEP
    assert isinstance(result_val["data"][CONF_TARGET_TEMP_STEP], float)

    # 2. TypeError: Incompatible type (dict/list) that triggers TypeError
    result_type = await flow.async_step_init({CONF_TARGET_TEMP_STEP: ["bad_type"]})
    assert result_type["type"] == "create_entry"
    assert result_type["data"][CONF_TARGET_TEMP_STEP] == DEFAULT_TARGET_TEMP_STEP
    assert isinstance(result_type["data"][CONF_TARGET_TEMP_STEP], float)
