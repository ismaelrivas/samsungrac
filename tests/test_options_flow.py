# pylint: disable=protected-access,too-many-locals,line-too-long
"""Tests for OptionsFlowHandler in options_flow.py."""

import datetime

import probatio as vol
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.selector import SelectSelectorMode, TextSelectorType


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
async def test_options_flow_invalid_poll_interval(hass):
    """Test options flow handles invalid poll interval input and returns correct form schema."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},
    )
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    flow.DEBUG_ME = True

    # 1. Non-numeric / invalid time format
    result = await flow.async_step_init({CONF_POLL_INTERVAL: "invalid_value"})
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert isinstance(result["step_id"], str)
    assert isinstance(result.get("data_schema"), vol.Schema)
    assert result["errors"] == {CONF_POLL_INTERVAL: "invalid_poll_interval"}
    assert result["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    # 2. Below minimum boundary (< 10)
    result_below_min = await flow.async_step_init(
        user_input={CONF_POLL_INTERVAL: "1"}  # invalid, min is 10
    )
    assert result_below_min["type"] == "form"
    assert result_below_min["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    # 3. Empty user_input creates entry with defaults
    result_empty = await flow.async_step_init({})
    assert result_empty["type"] == "create_entry"


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


@pytest.mark.asyncio
async def test_options_flow_validation_and_submission(hass):
    """Kill mutants in OptionsFlowHandler validation boundaries."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DEVICE_TYPE: "some_legacy_device"}
    )
    entry.add_to_hass(hass)
    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    flow.DEBUG_ME = True

    # Kill mutmut testing boundaries (< vs <=) (Kills mutants 8, 9, 11, 12, 14, 15, 17, 18)
    res_min = await flow.async_step_init({CONF_POLL_INTERVAL: MIN_POLL_INTERVAL - 1})
    assert res_min["type"] == "form"
    assert res_min["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    res_max = await flow.async_step_init({CONF_POLL_INTERVAL: MAX_POLL_INTERVAL + 1})
    assert res_max["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    res_min_exact = await flow.async_step_init(
        {CONF_POLL_INTERVAL: MIN_POLL_INTERVAL, CONF_TARGET_TEMP_STEP: "0.5"}
    )
    assert res_min_exact["type"] == "create_entry"
    assert res_min_exact["data"][CONF_POLL_INTERVAL] == MIN_POLL_INTERVAL

    res_max_exact = await flow.async_step_init(
        {CONF_POLL_INTERVAL: MAX_POLL_INTERVAL, CONF_TARGET_TEMP_STEP: "0.5"}
    )
    assert res_max_exact["type"] == "create_entry"
    assert res_max_exact["data"][CONF_POLL_INTERVAL] == MAX_POLL_INTERVAL

    # Kill mutmut ValueError/TypeError branches and time_period_str mutations (Kills mutants 6, 7)
    res_err = await flow.async_step_init({CONF_POLL_INTERVAL: "invalid_time_string"})
    assert res_err["errors"][CONF_POLL_INTERVAL] == "invalid_poll_interval"

    res_str_valid = await flow.async_step_init(
        {CONF_POLL_INTERVAL: "00:05:00", CONF_TARGET_TEMP_STEP: "0.5"}
    )
    assert res_str_valid["type"] == "create_entry"
    assert res_str_valid["data"][CONF_POLL_INTERVAL] == 300

    # Kill mutmut testing correct type casting
    res_success = await flow.async_step_init(
        {
            CONF_POLL_INTERVAL: 120,
            CONF_TARGET_TEMP_STEP: "0.5",  # Passed as string from UI UI
        }
    )
    assert res_success["type"] == "create_entry"
    assert res_success["data"][CONF_POLL_INTERVAL] == 120
    assert (
        res_success["data"][CONF_TARGET_TEMP_STEP] == 0.5
    )  # Assert strict float conversion

    # Kill target_temp_step TypeError fallback
    res_fallback = await flow.async_step_init(
        {CONF_POLL_INTERVAL: 120, CONF_TARGET_TEMP_STEP: "invalid_float"}
    )
    assert res_fallback["data"][CONF_TARGET_TEMP_STEP] == DEFAULT_TARGET_TEMP_STEP


@pytest.mark.asyncio
async def test_options_flow_schema_and_defaults(hass):
    """Kill mutants in OptionsFlowHandler._get_options_schema and init."""
    # Test 1: Supported device (8888) with existing options to verify PRECEDENCE
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_POLL_INTERVAL: 10,  # Options should override data
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
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    flow.DEBUG_ME = True

    result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"

    # Kill mutants changing default fetches (options preferred over data)
    schema = result["data_schema"]
    evaluated = schema({})
    assert evaluated[CONF_CONN_METHOD] == CONN_METHOD_RAW
    assert evaluated[CONF_POLL_INTERVAL] == "0:00:20"
    assert evaluated[CONF_ENABLE_POLLING] is False
    assert evaluated[CONF_TARGET_TEMP_STEP] == "0.5"
    assert evaluated[CONF_TEMP_NATIVE_CURRENT] == UnitOfTemperature.FAHRENHEIT
    assert evaluated[CONF_TEMP_NATIVE_TARGET] == UnitOfTemperature.CELSIUS

    # Kill mutmut_21, 22: Assert selector properties for CONN_METHOD
    conn_method_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_CONN_METHOD
    )
    conn_selector = schema.schema[conn_method_key]
    assert conn_selector.config["translation_key"] == "connection_method"
    assert conn_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    conn_options = conn_selector.config["options"]
    assert {"value": CONN_METHOD_AIOHTTP, "label": "Modern (aiohttp)"} in conn_options
    assert {"value": "requests", "label": "Legacy (Obsolete)"} in conn_options
    assert {"value": CONN_METHOD_RAW, "label": "Robust (raw socket)"} in conn_options

    temp_step_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_TARGET_TEMP_STEP
    )
    temp_step_options = schema.schema[temp_step_key].config["options"]
    assert {"value": "0.1", "label": "0.1°"} in temp_step_options
    assert {"value": "0.5", "label": "0.5°"} in temp_step_options
    assert {"value": "1.0", "label": "1.0°"} in temp_step_options

    native_current_key = next(
        k
        for k in schema.schema
        if getattr(k, "schema", None) == CONF_TEMP_NATIVE_CURRENT
    )
    native_current_options = schema.schema[native_current_key].config["options"]
    assert UnitOfTemperature.CELSIUS in native_current_options
    assert UnitOfTemperature.FAHRENHEIT in native_current_options

    poll_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    poll_selector = schema.schema[poll_key]
    assert poll_selector.config["type"] == TextSelectorType.TEXT

    # Test 1.5: Missing options/data and invalid poll interval string (Kills mutants 7, 10, 24, 27, 32)
    entry_empty = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
            CONF_CONN_METHOD: CONN_METHOD_RAW,
            CONF_POLL_INTERVAL: "invalid",
        },
        options={},
    )
    entry_empty.add_to_hass(hass)
    flow_empty = OptionsFlowHandler(entry_empty)
    flow_empty.hass = hass
    result_empty = await flow_empty.async_step_init()
    schema_empty = result_empty["data_schema"]
    evaluated_empty = schema_empty({})
    # Kill 7, 10: CONN_METHOD_RAW is in data
    assert evaluated_empty[CONF_CONN_METHOD] == CONN_METHOD_RAW
    # Kill 24, 27, 32, 33: Invalid poll interval falls into except TypeError/ValueError and returns raw str
    assert evaluated_empty[CONF_POLL_INTERVAL] == "invalid"

    # Kill 45, 49, 54, 69: Assert defaults when completely missing from options and data
    assert evaluated_empty[CONF_TEMP_NATIVE_TARGET] == DEFAULT_CONF_TEMP_UNIT
    assert evaluated_empty[CONF_ENABLE_POLLING] == DEFAULT_ENABLE_POLLING
    assert evaluated_empty[CONF_TARGET_TEMP_STEP] == str(DEFAULT_TARGET_TEMP_STEP)

    # Kill mutmut_39, 79: Assert exact selector config properties for temp native and step
    temp_curr_key = next(
        k
        for k in schema_empty.schema
        if getattr(k, "schema", None) == CONF_TEMP_NATIVE_CURRENT
    )
    temp_selector = schema_empty.schema[temp_curr_key]
    assert temp_selector.config["mode"] == SelectSelectorMode.DROPDOWN

    step_key = next(
        k
        for k in schema_empty.schema
        if getattr(k, "schema", None) == CONF_TARGET_TEMP_STEP
    )
    step_selector = schema_empty.schema[step_key]
    assert step_selector.config["mode"] == SelectSelectorMode.DROPDOWN

    # Test 2: Legacy unsupported device (AIOHTTP selector MUST NOT APPEAR)
    entry_legacy = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878
        },  # 2878 is definitely not in DEVICE_TYPE_AIOHTTP_SUPPORTED
    )
    entry_legacy.add_to_hass(hass)
    flow_legacy = OptionsFlowHandler(entry_legacy)
    flow_legacy.hass = hass

    result_legacy = await flow_legacy.async_step_init()
    schema_legacy = result_legacy["data_schema"]
    evaluated_legacy = schema_legacy({})
    assert CONF_CONN_METHOD not in evaluated_legacy


@pytest.mark.asyncio
async def test_options_flow_empty_title_and_fallback(hass):
    """Kill mutants setting title to None or testing empty target temps."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DEVICE_TYPE: "some_device"})
    entry.add_to_hass(hass)
    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    flow.DEBUG_ME = True

    res = await flow.async_step_init({CONF_POLL_INTERVAL: 120})
    # Categorically ensure generated title is an empty string
    assert res["title"] == ""


@pytest.mark.asyncio
async def test_options_flow_handler_zero_arg(hass):
    """Test OptionsFlowHandler zero-arg initialization and fallback to self.config_entry."""
    flow = OptionsFlowHandler()
    assert flow._config_entry is None

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DEVICE_TYPE: "some_device"})
    hass.config_entries.async_get_known_entry.return_value = entry
    flow.hass = hass
    flow.handler = entry.entry_id

    assert flow._entry == entry
