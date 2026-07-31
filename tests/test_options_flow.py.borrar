"""Test options flow to kill mutants."""

import pytest
import voluptuous as vol
import datetime

from custom_components.climate_ip.const import (
    DOMAIN,
    CONF_CONN_METHOD,
    CONN_METHOD_AIOHTTP,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_CONF_TEMP_UNIT,
    CONF_TARGET_TEMP_STEP,
    DEFAULT_TARGET_TEMP_STEP,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_8888,
    CONF_TEMP_NATIVE_TARGET,
)
from custom_components.climate_ip.config_flow import CONF_POLL_INTERVAL


def get_schema_marker(schema: vol.Schema, key_name: str):
    """Busca una clave en un vol.Schema y devuelve el marcador (Required/Optional) y su tipo."""
    for key, value_type in schema.schema.items():
        if key.schema == key_name:
            return key, value_type
    return None, None


async def test_options_flow_empty_defaults(hass):
    """Prueba que los defaults intrínsecos funcionen si la entrada está vacía."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    # Entrada vacía de opciones y configuración básica
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_8888},
        options={},  # Clave para matar a los mutantes
    )
    entry.add_to_hass(hass)

    from custom_components.climate_ip.config_flow import OptionsFlowHandler

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
    """Kills mutants 71, 72, 82, 83."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.climate_ip.config_flow import OptionsFlowHandler

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    flow = OptionsFlowHandler(entry)
    flow.hass = hass
    schema = flow._get_options_schema()

    targ_key, _ = get_schema_marker(schema, CONF_TEMP_NATIVE_TARGET)
    assert targ_key.default() == DEFAULT_CONF_TEMP_UNIT

    step_key, _ = get_schema_marker(schema, CONF_TARGET_TEMP_STEP)
    assert step_key.default() == str(DEFAULT_TARGET_TEMP_STEP)
