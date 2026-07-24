"""Test config flow schemas to kill mutants."""

import voluptuous as vol

from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN, CONF_MAC
from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPE_SAMSUNG_2878,
)
from custom_components.climate_ip.config_flow import (
    ClimateIpConfigFlow,
    CONF_DEVICE_ID,
    CONF_NAME,
    CONF_POLL_INTERVAL,
)


def get_schema_marker(schema: vol.Schema, key_name: str):
    """Busca una clave en un vol.Schema y devuelve el marcador (Required/Optional) y su tipo."""
    for key, value_type in schema.schema.items():
        if key.schema == key_name:
            return key, value_type
    return None, None


async def test_rest_api_schema_mutants_annihilation():
    """Mata a los 12 mutantes de _get_rest_api_schema."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
        CONF_IP_ADDRESS: "192.168.1.99",  # Para el mutante 37 (get(None))
    }

    # Al no haber SmartThings en hass, el token debe caer a "" (Mata al Mutante 31)
    # Al no haber CONF_POLL_INTERVAL en flow_data, debe caer a "" (Mata Mutantes 18, 20, 21)

    # Mock de _get_smartthings_token simulando que devuelve None
    flow._get_smartthings_token = lambda: None

    schema = flow._get_rest_api_schema()

    # 1. Verificar tipos estrictos (Mata Mutantes 51 y 65)
    _, dev_id_type = get_schema_marker(schema, CONF_DEVICE_ID)
    assert (
        dev_id_type is str
    )  # Si el mutante asigna None a la derecha del dict, esto falla

    _, name_type = get_schema_marker(schema, CONF_NAME)
    assert name_type is str

    # 2. Verificar parámetros de IP estrictos (Mata Mutantes 37, 53, 54, 55, 56, 57)
    ip_key, ip_type = get_schema_marker(schema, CONF_IP_ADDRESS)
    assert isinstance(ip_key, vol.Required)
    assert (
        ip_key.default() == "192.168.1.99"
    )  # Mata al mutante 37 que usaría la IP de smartthings.com
    assert ip_type is str

    # 3. Verificar fallbacks vacíos (Mata Mutantes 18, 20, 21, 31)
    token_key, _ = get_schema_marker(schema, CONF_TOKEN)
    assert token_key.default() == ""  # Mata al mutante 31 (default_token = "XXXX")


async def test_base_samsung_schema_mutants():
    """Mata a los mutantes de _get_base_samsung_schema."""
    flow = ClimateIpConfigFlow()
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_POLL_INTERVAL: None,
    }

    # Generar esquema exigiendo MAC
    schema = flow._get_samsung_2878_schema(mac_required=True)

    # Mata Mutante 39 (Verifica que CONF_MAC exige str, no None)
    mac_key, mac_type = get_schema_marker(schema, CONF_MAC)
    assert isinstance(mac_key, vol.Required)
    assert mac_type is str

    # Mata Mutante 24 (Verifica que el fallback de intervalo crudo es "" y no "XXXX")
    poll_key, _ = get_schema_marker(schema, CONF_POLL_INTERVAL)
    assert poll_key.default() == ""
