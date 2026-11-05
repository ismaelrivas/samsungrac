# pylint: disable=protected-access,too-many-locals,line-too-long,too-many-statements,too-many-arguments,redefined-outer-name
"""Tests for ConfigFlowSchemasMixin in config_flow_schemas.py."""

import datetime
from unittest.mock import MagicMock

import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.config_flow_schemas import ConfigFlowSchemasMixin
from custom_components.climate_ip.const import (
    CONF_CERT,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_SELECTED_DEVICES,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_CERT_FILE,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SMARTTHINGS_HOST,
    DEVICE_TYPE_INTESISBOX,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPES,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN, UnitOfTemperature
from homeassistant.helpers.selector import SelectSelectorMode, TextSelectorType


def get_schema_marker(schema: probatio.Schema, key_name: str):
    """Search for a key in a probatio.Schema and return the marker (Required/Optional) and its type."""
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
    assert isinstance(ip_key, probatio.Required)
    assert ip_key.default() == ""
    assert ip_type is str

    # 2. MAC (required=True)
    mac_key, mac_type = get_schema_marker(schema, CONF_MAC)
    assert isinstance(mac_key, probatio.Required)
    assert mac_key.default() == ""
    assert mac_type is str

    # 3. Name
    name_key, name_type = get_schema_marker(schema, CONF_NAME)
    assert isinstance(name_key, probatio.Optional)
    assert name_key.default() == ""
    assert name_type is str

    # 4. Token (Kills M30-M35)
    tok_key, tok_type = get_schema_marker(schema, CONF_TOKEN)
    assert isinstance(tok_key, probatio.Optional)
    assert tok_key.default() == ""
    assert tok_type is str

    # 5. Cert (Kills M37-M40)
    cert_key, cert_type = get_schema_marker(schema, CONF_CERT)
    assert isinstance(cert_key, probatio.Optional)
    assert cert_key.default() == DEFAULT_CONF_CERT_FILE
    assert cert_type is str

    # 6. Poll interval default
    poll_key, poll_selector = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert isinstance(poll_key, probatio.Optional)
    assert poll_key.default() == str(datetime.timedelta(seconds=DEFAULT_POLL_INTERVAL))
    assert poll_selector.config["type"] == TextSelectorType.TEXT

    # 7. Enable Polling (is_8888=False -> Kills M51, M53-M58)
    poll_flag_key, poll_flag_type = get_schema_marker(schema, CONF_ENABLE_POLLING)
    assert isinstance(poll_flag_key, probatio.Optional)
    assert poll_flag_key.default() is DEFAULT_ENABLE_POLLING
    assert poll_flag_type is bool

    # 8. Temp Native Current & Target (Kills M67, M69, M72, M73)
    curr_key, curr_selector = get_schema_marker(schema, CONF_TEMP_NATIVE_CURRENT)
    assert isinstance(curr_key, probatio.Optional)
    assert curr_key.default() == DEFAULT_CONF_TEMP_UNIT
    assert curr_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert curr_selector.config["options"] == [
        UnitOfTemperature.CELSIUS,
        UnitOfTemperature.FAHRENHEIT,
    ]

    targ_key, targ_selector = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert isinstance(targ_key, probatio.Optional)
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
    assert isinstance(mac_key, probatio.Optional)
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
    assert isinstance(ip_key, probatio.Required)
    assert ip_key.default() == DEFAULT_SMARTTHINGS_HOST
    assert ip_type is str

    # Device ID is present
    dev_id_key, dev_id_type = get_schema_marker(schema, CONF_DEVICE_ID)
    assert isinstance(dev_id_key, probatio.Optional)
    assert dev_id_type is str

    # Token default is auto-filled from SmartThings
    token_key, token_type = get_schema_marker(schema, CONF_TOKEN)
    assert isinstance(token_key, probatio.Required)
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
    assert isinstance(ip_key1, probatio.Required)
    assert ip_key1.default is probatio.UNDEFINED or not callable(
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


# -----------------------------------------------------------------------------
# 4. Tests for Newly Centralized Schemas & Dynamic Schema Factory (Phase 3)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_schema():
    """Test _get_user_schema renders initial device selection schema with dropdown mode."""
    flow = ClimateIpConfigFlow()
    schema = flow._get_user_schema()

    key, selector = get_schema_marker(schema, CONF_DEVICE_TYPE)
    assert isinstance(key, probatio.Required)
    assert selector.config["options"] == DEVICE_TYPES
    assert selector.config["translation_key"] == CONF_DEVICE_TYPE
    assert selector.config["mode"] == SelectSelectorMode.DROPDOWN


@pytest.mark.asyncio
async def test_get_intesisbox_schema_defaults_and_user_input():
    """Test _get_intesisbox_schema defaults and user_input population."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}

    # 1. Defaults with empty flow_data
    schema_empty = flow._get_intesisbox_schema()
    ip_key, ip_type = get_schema_marker(schema_empty, CONF_IP_ADDRESS)
    assert isinstance(ip_key, probatio.Required)
    assert ip_key.default() == ""
    assert ip_type is str

    mac_key, mac_type = get_schema_marker(schema_empty, CONF_MAC)
    assert isinstance(mac_key, probatio.Optional)
    assert mac_key.description == {"suggested_value": ""}
    assert mac_type is str

    poll_key, poll_type = get_schema_marker(schema_empty, CONF_POLL_INTERVAL)
    assert isinstance(poll_key, probatio.Optional)
    assert poll_key.default() == 60
    assert poll_type is int

    # 2. Populated via flow_data
    flow.flow_data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }
    schema_flow = flow._get_intesisbox_schema()
    ip_key2, _ = get_schema_marker(schema_flow, CONF_IP_ADDRESS)
    assert ip_key2.default() == "192.168.1.100"
    mac_key2, _ = get_schema_marker(schema_flow, CONF_MAC)
    assert mac_key2.description == {"suggested_value": "AA:BB:CC:DD:EE:FF"}

    # 3. Populated via _last_user_input
    flow.flow_data = {}
    flow._last_user_input = {
        CONF_IP_ADDRESS: "192.168.1.200",
        CONF_MAC: "11:22:33:44:55:66",
    }
    schema_input = flow._get_intesisbox_schema()
    ip_key3, _ = get_schema_marker(schema_input, CONF_IP_ADDRESS)
    assert ip_key3.default() == "192.168.1.200"
    mac_key3, _ = get_schema_marker(schema_input, CONF_MAC)
    assert mac_key3.description == {"suggested_value": "11:22:33:44:55:66"}


@pytest.mark.asyncio
async def test_get_reconfigure_schema():
    """Test _get_reconfigure_schema without and with suggested values."""
    flow = ClimateIpConfigFlow()

    # 1. suggested_values is None
    schema_none = flow._get_reconfigure_schema(suggested_values=None)
    ip_key, ip_type = get_schema_marker(schema_none, CONF_IP_ADDRESS)
    assert isinstance(ip_key, probatio.Required)
    assert ip_type is str

    mac_key, mac_type = get_schema_marker(schema_none, CONF_MAC)
    assert isinstance(mac_key, probatio.Optional)
    assert mac_type is str

    tok_key, tok_type = get_schema_marker(schema_none, CONF_TOKEN)
    assert isinstance(tok_key, probatio.Optional)
    assert tok_type is str

    cert_key, cert_type = get_schema_marker(schema_none, CONF_CERT)
    assert isinstance(cert_key, probatio.Optional)
    assert cert_type is str

    # 2. suggested_values provided with ClimateIpConfigFlow (inherits add_suggested_values_to_schema)
    suggested = {
        CONF_IP_ADDRESS: "192.168.1.55",
        CONF_MAC: "123456789ABC",
        CONF_TOKEN: "reconfig_token",
        CONF_CERT: "custom_cert.pem",
    }
    schema_suggested = flow._get_reconfigure_schema(suggested_values=suggested)
    ip_s, _ = get_schema_marker(schema_suggested, CONF_IP_ADDRESS)
    assert ip_s.description == {"suggested_value": "192.168.1.55"}

    # 3. DummyFlow standalone without add_suggested_values_to_schema
    class StandaloneFlow(ConfigFlowSchemasMixin):
        flow_data = {}
        hass = None

    standalone = StandaloneFlow()
    schema_fallback = standalone._get_reconfigure_schema(suggested_values=suggested)
    assert schema_fallback is not None

    # 4. DummyFlow with custom add_suggested_values_to_schema lambda
    called = []
    standalone.add_suggested_values_to_schema = lambda s, v: called.append((s, v)) or s
    schema_dummy = standalone._get_reconfigure_schema(suggested_values=suggested)
    assert schema_dummy is not None
    assert len(called) == 1
    assert called[0][1] == suggested


@pytest.mark.asyncio
async def test_get_select_devices_schema():
    """Test _get_select_devices_schema across all default-key resolution strategies."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {}
    device_options = {"id1": "Device 1", "id2": "Device 2"}

    # 1. Default fallback to device_options keys
    schema1 = flow._get_select_devices_schema(device_options)
    key1, _ = get_schema_marker(schema1, CONF_SELECTED_DEVICES)
    assert isinstance(key1, probatio.Required)
    assert key1.default() == ["id1", "id2"]

    # 2. Explicit default_keys passed
    schema2 = flow._get_select_devices_schema(device_options, default_keys=["id2"])
    key2, _ = get_schema_marker(schema2, CONF_SELECTED_DEVICES)
    assert key2.default() == ["id2"]

    # 3. default_keys resolved from _last_user_input
    flow._last_user_input = {CONF_SELECTED_DEVICES: ["id1"]}
    schema3 = flow._get_select_devices_schema(device_options)
    key3, _ = get_schema_marker(schema3, CONF_SELECTED_DEVICES)
    assert key3.default() == ["id1"]

    # 4. default_keys resolved from _discovered_devices dict
    del flow._last_user_input
    flow._discovered_devices = {"devA": {}, "devB": {}}
    schema4 = flow._get_select_devices_schema(device_options)
    key4, _ = get_schema_marker(schema4, CONF_SELECTED_DEVICES)
    assert key4.default() == ["devA", "devB"]


@pytest.mark.asyncio
async def test_build_device_config_schema_factory():
    """Test build_device_config_schema factory across all device families and contexts."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []
    flow.flow_data = {}

    # 1. is_reconfigure=True
    reconfig_schema = flow.build_device_config_schema(
        is_reconfigure=True, suggested_values={CONF_IP_ADDRESS: "1.2.3.4"}
    )
    assert get_schema_marker(reconfig_schema, CONF_CERT)[0] is not None

    # 2. DEVICE_TYPE_SAMSUNG_2878
    s2878_schema = flow.build_device_config_schema(
        DEVICE_TYPE_SAMSUNG_2878, mac_required=True
    )
    poll_flag_key, _ = get_schema_marker(s2878_schema, CONF_ENABLE_POLLING)
    assert poll_flag_key is not None
    mac_key, _ = get_schema_marker(s2878_schema, CONF_MAC)
    assert isinstance(mac_key, probatio.Required)

    # 3. DEVICE_TYPE_SAMSUNG_8888 (in DEVICE_TYPE_8888_GROUP)
    s8888_schema = flow.build_device_config_schema(
        DEVICE_TYPE_SAMSUNG_8888, mac_required=False
    )
    poll_flag_8888, _ = get_schema_marker(s8888_schema, CONF_ENABLE_POLLING)
    assert poll_flag_8888 is None
    mac_key_8888, _ = get_schema_marker(s8888_schema, CONF_MAC)
    assert isinstance(mac_key_8888, probatio.Optional)

    # 4. DEVICE_TYPE_MIM_H03 (also in DEVICE_TYPE_8888_GROUP)
    mim_schema = flow.build_device_config_schema(DEVICE_TYPE_MIM_H03)
    poll_flag_mim, _ = get_schema_marker(mim_schema, CONF_ENABLE_POLLING)
    assert poll_flag_mim is None

    # 5. DEVICE_TYPE_INTESISBOX
    intesis_schema = flow.build_device_config_schema(DEVICE_TYPE_INTESISBOX)
    poll_key_intesis, _ = get_schema_marker(intesis_schema, CONF_POLL_INTERVAL)
    assert poll_key_intesis.default() == 60

    # 6. DEVICE_TYPE_SMARTTHINGS_HVAC (REST API)
    st_schema = flow.build_device_config_schema(DEVICE_TYPE_SMARTTHINGS_HVAC)
    dev_id_key, _ = get_schema_marker(st_schema, CONF_DEVICE_ID)
    assert dev_id_key is not None

    # 7. Fallback to self.flow_data[CONF_DEVICE_TYPE]
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    flow_schema = flow.build_device_config_schema()
    poll_flag_flow, _ = get_schema_marker(flow_schema, CONF_ENABLE_POLLING)
    assert poll_flag_flow is not None

    # 8. Fallback to self._device_type
    flow.flow_data = {}
    flow._device_type = DEVICE_TYPE_INTESISBOX
    attr_schema = flow.build_device_config_schema()
    poll_key_attr, _ = get_schema_marker(attr_schema, CONF_POLL_INTERVAL)
    assert poll_key_attr.default() == 60


def test_format_poll_interval_helper() -> None:
    """Test format_poll_interval for int, numeric str, fallback str, and fallback defaults."""
    from custom_components.climate_ip.helpers import format_poll_interval

    # 1. Integer seconds
    assert format_poll_interval(60) == "0:01:00"
    assert format_poll_interval(120) == "0:02:00"
    assert format_poll_interval(0) == "0:00:00"

    # 2. Numeric string
    assert format_poll_interval("60") == "0:01:00"
    assert format_poll_interval("120") == "0:02:00"

    # 3. "0:01:30" string fallback
    assert format_poll_interval("0:01:30") == "0:01:30"
    assert format_poll_interval("invalid_str") == "invalid_str"

    # 4. Non-numeric non-string fallback to default_seconds
    assert format_poll_interval(None, default_seconds=45) == "0:00:45"
    assert format_poll_interval(object(), default_seconds=30) == "0:00:30"
    assert format_poll_interval([], default_seconds=60) == "0:01:00"
    assert format_poll_interval(None) == "0:01:00"


def test_schema_default_poll_interval_custom_seconds():
    """Test format_poll_interval uses _default_poll_interval_seconds() in base samsung and rest api schemas."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC}
    flow._default_poll_interval_seconds = lambda: 120

    # 1. Base Samsung Schema
    schema_samsung = flow._get_base_samsung_schema(False, False)
    poll_key_samsung, _ = get_schema_marker(schema_samsung, CONF_POLL_INTERVAL)
    assert poll_key_samsung is not None
    assert poll_key_samsung.default() == "0:02:00"

    # 2. REST API Schema
    schema_rest = flow._get_rest_api_schema()
    poll_key_rest, _ = get_schema_marker(schema_rest, CONF_POLL_INTERVAL)
    assert poll_key_rest is not None
    assert poll_key_rest.default() == "0:02:00"


def test_schema_mac_required_defaults_to_false():
    """Test that mac_required defaults to False in samsung 2878, samsung 8888, and build_device_config_schema."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {}

    # 1. _get_samsung_2878_schema without mac_required
    schema_2878 = flow._get_samsung_2878_schema()
    mac_key_2878, _ = get_schema_marker(schema_2878, CONF_MAC)
    assert isinstance(mac_key_2878, probatio.Optional)
    assert not isinstance(mac_key_2878, probatio.Required)

    # 2. _get_samsung_8888_schema without mac_required
    schema_8888 = flow._get_samsung_8888_schema()
    mac_key_8888, _ = get_schema_marker(schema_8888, CONF_MAC)
    assert isinstance(mac_key_8888, probatio.Optional)
    assert not isinstance(mac_key_8888, probatio.Required)

    # 3. build_device_config_schema(DEVICE_TYPE_SAMSUNG_2878) without mac_required
    schema_build_2878 = flow.build_device_config_schema(DEVICE_TYPE_SAMSUNG_2878)
    mac_key_b2878, _ = get_schema_marker(schema_build_2878, CONF_MAC)
    assert isinstance(mac_key_b2878, probatio.Optional)
    assert not isinstance(mac_key_b2878, probatio.Required)

    # 4. build_device_config_schema(DEVICE_TYPE_SAMSUNG_8888) without mac_required
    schema_build_8888 = flow.build_device_config_schema(DEVICE_TYPE_SAMSUNG_8888)
    mac_key_b8888, _ = get_schema_marker(schema_build_8888, CONF_MAC)
    assert isinstance(mac_key_b8888, probatio.Optional)
    assert not isinstance(mac_key_b8888, probatio.Required)


def test_build_device_config_schema_does_not_overwrite_existing_device_type():
    """Test that build_device_config_schema does not overwrite existing CONF_DEVICE_TYPE in flow_data."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW}

    flow.build_device_config_schema(DEVICE_TYPE_SMARTTHINGS_HVAC)
    assert flow.flow_data[CONF_DEVICE_TYPE] == DEVICE_TYPE_SMARTTHINGS_DHW


def test_async_show_reconfigure_form_calls_async_show_form():
    """Test _async_show_reconfigure_form delegates to async_show_form with correct arguments."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888}
    flow.async_show_form = MagicMock(
        return_value={"type": "form", "step_id": "reconfigure_confirm"}
    )

    errors = {"base": "cannot_connect"}
    suggested = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_TOKEN: "tok123",
        CONF_CERT: "cert.pem",
    }

    # 1. description_placeholders is None -> defaults to {}
    res1 = flow._async_show_reconfigure_form(errors, suggested)
    assert res1 == {"type": "form", "step_id": "reconfigure_confirm"}
    flow.async_show_form.assert_called_once()
    kwargs1 = flow.async_show_form.call_args.kwargs
    assert kwargs1["step_id"] == "reconfigure_confirm"
    assert kwargs1["errors"] == errors
    assert kwargs1["description_placeholders"] == {}
    assert isinstance(kwargs1["data_schema"], probatio.Schema)

    expected_schema = flow._get_reconfigure_schema(suggested)
    assert list(kwargs1["data_schema"].schema.keys()) == list(
        expected_schema.schema.keys()
    )
    ip_key, _ = get_schema_marker(kwargs1["data_schema"], CONF_IP_ADDRESS)
    assert ip_key.description == {"suggested_value": "192.168.1.100"}

    # 2. description_placeholders provided
    flow.async_show_form.reset_mock()
    placeholders = {"device_name": "Living Room AC"}
    res2 = flow._async_show_reconfigure_form(
        errors, suggested, description_placeholders=placeholders
    )
    assert res2 == {"type": "form", "step_id": "reconfigure_confirm"}
    flow.async_show_form.assert_called_once()
    kwargs2 = flow.async_show_form.call_args.kwargs
    assert kwargs2["step_id"] == "reconfigure_confirm"
    assert kwargs2["errors"] == errors
    assert kwargs2["description_placeholders"] == placeholders


def test_current_reconfigure_suggested_branches():
    """Test _current_reconfigure_suggested with populated, empty, and None flow_data."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    # 1. Populated flow_data with lowercase unformatted MAC
    flow.flow_data = {
        CONF_IP_ADDRESS: "192.168.1.50",
        CONF_MAC: "aa-bb-cc-dd-ee-ff",
        CONF_TOKEN: "secret_123",
        CONF_CERT: "/path/cert.pem",
    }
    sug_pop = flow._current_reconfigure_suggested()
    assert sug_pop == {
        CONF_IP_ADDRESS: "192.168.1.50",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_TOKEN: "secret_123",
        CONF_CERT: "/path/cert.pem",
    }

    # 2. Empty flow_data returning "" for all 4 keys
    flow.flow_data = {}
    sug_empty = flow._current_reconfigure_suggested()
    assert sug_empty == {
        CONF_IP_ADDRESS: "",
        CONF_MAC: "",
        CONF_TOKEN: "",
        CONF_CERT: "",
    }

    # 3. None values in flow_data returning "" for all 4 keys
    flow.flow_data = {
        CONF_IP_ADDRESS: None,
        CONF_MAC: None,
        CONF_TOKEN: None,
        CONF_CERT: None,
    }
    sug_none = flow._current_reconfigure_suggested()
    assert sug_none == {
        CONF_IP_ADDRESS: "",
        CONF_MAC: "",
        CONF_TOKEN: "",
        CONF_CERT: "",
    }


def test_get_initial_reconfigure_suggested_cert_logic():
    """Test _get_initial_reconfigure_suggested cert whitespace stripping and device type defaults."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()

    # 1. Whitespace stripped when CONF_CERT has whitespace
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_CERT: "   /path/custom.pem   ",
    }
    sug1 = flow._get_initial_reconfigure_suggested()
    assert sug1[CONF_CERT] == "/path/custom.pem"

    # 2. CONF_CERT empty/whitespace and DEVICE_TYPE_SAMSUNG_8888 -> DEFAULT_CONF_CERT_FILE
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888,
        CONF_CERT: "    ",
    }
    sug2 = flow._get_initial_reconfigure_suggested()
    assert sug2[CONF_CERT] == DEFAULT_CONF_CERT_FILE

    # 3. CONF_CERT empty and DEVICE_TYPE_MIM_H03 -> DEFAULT_CONF_CERT_FILE
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03,
        CONF_CERT: "",
    }
    sug3 = flow._get_initial_reconfigure_suggested()
    assert sug3[CONF_CERT] == DEFAULT_CONF_CERT_FILE

    # 4. CONF_CERT missing and DEVICE_TYPE_SAMSUNG_2878 -> DEFAULT_CONF_CERT_FILE
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
    }
    sug4 = flow._get_initial_reconfigure_suggested()
    assert sug4[CONF_CERT] == DEFAULT_CONF_CERT_FILE

    # 5. CONF_CERT empty and DEVICE_TYPE_SMARTTHINGS_HVAC -> ""
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_CERT: "",
    }
    sug5 = flow._get_initial_reconfigure_suggested()
    assert sug5[CONF_CERT] == ""

    # 6. CONF_CERT missing and DEVICE_TYPE_INTESISBOX -> ""
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX,
    }
    sug6 = flow._get_initial_reconfigure_suggested()
    assert sug6[CONF_CERT] == ""

    # 7. CONF_CERT missing and None device type -> ""
    flow.flow_data = {}
    sug7 = flow._get_initial_reconfigure_suggested()
    assert sug7[CONF_CERT] == ""
