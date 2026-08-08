"""Test config flow schemas to kill mutants."""

from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
)


def get_schema_marker(schema: vol.Schema, key_name: str):
    """Busca una clave en un vol.Schema y devuelve el marcador (Required/Optional) y su tipo."""
    for key, value_type in schema.schema.items():
        if key.schema == key_name:
            return key, value_type
    return None, None


@pytest.mark.asyncio
async def test_rest_api_schema_mutants_annihilation():
    """Mata a los 12 mutantes de _get_rest_api_schema."""
    """Kill the 12 mutants of _get_rest_api_schema."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []  # Simulate no SmartThings

    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_IP_ADDRESS: "192.168.1.99",  # For mutant 37 (get(None))
    }

    # With no SmartThings in hass, token must fall back to "" (Kills Mutant 31)
    # With no CONF_POLL_INTERVAL in flow_data, it must fall back to ""...
    schema = flow._get_rest_api_schema()

    # 1. Verify base parameters (Kills mutants 51, 60)
    dev_id_key, dev_id_type = get_schema_marker(schema, CONF_DEVICE_ID)
    assert dev_id_type is str  # If mutant assigns None to the right of the dict, this fails

    _, name_type = get_schema_marker(schema, CONF_NAME)
    assert name_type is str

    # 2. Verify strict IP parameters (Kills mutants 37, 53, 54, 55, 56, 57)
    ip_key, ip_type = get_schema_marker(schema, CONF_IP_ADDRESS)
    assert isinstance(ip_key, vol.Required)
    assert (
        ip_key.default() == "192.168.1.99"
    )  # Kills mutant 37 that would use smartthings.com IP
    assert ip_type is str

    # 3. Verificar fallbacks vacíos (Kills mutants 18, 20, 21, 31)
    token_key, _ = get_schema_marker(schema, CONF_TOKEN)
    assert token_key.default() == ""  # Kills mutant 31 (default_token = "XXXX")


@pytest.mark.asyncio
async def test_base_samsung_schema_mutants():
    """Verify mutant kill de _get_base_samsung_schema."""
    flow = ClimateIpConfigFlow()
    flow.hass = MagicMock()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_POLL_INTERVAL: None,
    }

    # Generar esquema exigiendo MAC (is_8888=False)
    schema = flow._get_base_samsung_schema(mac_required=True, is_8888=False)

    mac_key, mac_type = get_schema_marker(schema, CONF_MAC)
    assert isinstance(mac_key, vol.Required)
    assert mac_type is str


# ====================================================================================
# OPTIONS FLOW SCHEMAS TESTS - Migrated to kill mutants
# ====================================================================================


@pytest.mark.asyncio
async def test_options_flow_empty_defaults(hass):
    """Prueba que los defaults intrínsecos funcionen si la entrada de opciones está vacía."""
    import datetime

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.climate_ip.config_flow import (
        OptionsFlowHandler,
    )
    from custom_components.climate_ip.const import (
        CONF_CONN_METHOD,
        CONF_TARGET_TEMP_STEP,
        CONF_TEMP_NATIVE_TARGET,
        CONN_METHOD_AIOHTTP,
        DEFAULT_CONF_TEMP_UNIT,
        DEFAULT_POLL_INTERVAL,
        DEFAULT_TARGET_TEMP_STEP,
        DOMAIN,
    )

    # Entrada vacía de opciones y configuración básica
    # WE USE SMARTTHINGS_HVAC because it supports AIOHTTP and exposes CONF_CONN_METHOD in options
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC},
        options={},  # Key to kill mutants
    )
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] == "form", f"Expected form but got: {result}"
    schema = result["data_schema"]

    # Kills mutant 12
    conn_key, _ = get_schema_marker(schema, CONF_CONN_METHOD)
    assert conn_key.default() == CONN_METHOD_AIOHTTP

    # Kills mutant 54
    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == str(datetime.timedelta(seconds=DEFAULT_POLL_INTERVAL))

    # Kills mutants 71, 72
    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT

    # Kills mutants 82, 83
    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)


@pytest.mark.asyncio
async def test_options_schema_target_temp_fallback_empty(hass):
    """Kills mutants 71, 72, 82, 83 mediante el generador interno de esquema."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.climate_ip.config_flow import OptionsFlowHandler
    from custom_components.climate_ip.const import (
        CONF_TARGET_TEMP_STEP,
        CONF_TEMP_NATIVE_TARGET,
        DEFAULT_CONF_TEMP_UNIT,
        DEFAULT_TARGET_TEMP_STEP,
        DOMAIN,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    schema = flow._get_options_schema()

    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT

    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)
