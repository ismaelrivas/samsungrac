import re

def main():
    with open("tests/test_config_flow.py", "r") as f:
        content = f.read()

    # Quitar el viejo test que falló si existe
    if "def test_form_schemas_types_and_defaults" in content:
        content = content[:content.find("async def test_form_schemas_types_and_defaults")]

    new_test = """
async def test_form_schemas_types_and_defaults(hass):
    \"\"\"Kill mutants changing types or defaults in reconfigure and rest_api forms.\"\"\"
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from custom_components.climate_ip.const import CONF_DEVICE_TYPE, DEVICE_TYPE_SAMSUNG_2878, DEVICE_TYPE_SMARTTHINGS_HVAC
    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
    from custom_components.climate_ip.const import CONF_CERT
    from unittest.mock import patch

    # 1. Reconfigure form (types and error re-injection)
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {"source": "reconfigure", "entry_id": "test_id"}
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.10",
        CONF_MAC: "AA:BB:CC",
        CONF_TOKEN: "old_token",
        CONF_CERT: ""
    }
    
    with patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._get_reconfigure_entry") as mock_get_entry, \\
         patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id") as mock_resolve:
         
        mock_get_entry.return_value.data = flow.flow_data
        mock_resolve.return_value = "mac_resolve_failed"
        
        # Inject bad MAC
        res_err = await flow.async_step_reconfigure_confirm({
            CONF_IP_ADDRESS: "192.168.1.99",
            CONF_MAC: "BAD_MAC",
            CONF_TOKEN: "new_token",
            CONF_CERT: "cert.pem"
        })
        
        assert res_err["type"] == "form"
        assert res_err["step_id"] == "reconfigure_confirm"
        
        schema = res_err["data_schema"].schema
        
        ip_key = next(k for k in schema.keys() if str(k) == CONF_IP_ADDRESS)
        assert schema[ip_key] is str
        assert ip_key.description["suggested_value"] == "192.168.1.99"
        
        mac_key = next(k for k in schema.keys() if str(k) == CONF_MAC)
        assert schema[mac_key] is str
        assert mac_key.description["suggested_value"] == "BAD_MAC"
        
        token_key = next(k for k in schema.keys() if str(k) == CONF_TOKEN)
        assert schema[token_key] is str
        assert token_key.description["suggested_value"] == "new_token"

    # 2. REST API form (types and error re-injection)
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    flow2.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC
    }
    
    with patch("custom_components.climate_ip.config_flow.async_get_clientsession") as mock_session_func:
        # Cause auth error
        mock_session_func.return_value.get.return_value.__aenter__.return_value.status = 401
        
        res_rest = await flow2.async_step_rest_api({
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_IP_ADDRESS: "api.smartthings.com",
            CONF_TOKEN: "wrong_token"
        })
        
        assert res_rest["type"] == "form"
        assert res_rest["step_id"] == "rest_api"
        
        schema2 = res_rest["data_schema"].schema
        
        ip_key2 = next(k for k in schema2.keys() if str(k) == CONF_IP_ADDRESS)
        assert schema2[ip_key2] is str
        assert getattr(ip_key2, "default", lambda: None)() == "api.smartthings.com"
        
        token_key2 = next(k for k in schema2.keys() if str(k) == CONF_TOKEN)
        assert schema2[token_key2] is str
        assert getattr(token_key2, "default", lambda: None)() == "wrong_token"
"""
    
    content += "\n" + new_test
    with open("tests/test_config_flow.py", "w") as f:
        f.write(content)

if __name__ == "__main__":
    main()
