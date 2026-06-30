import os

test_file = "custom_components/climate_ip/tests/test_config_flow.py"
with open(test_file, "a") as f:
    f.write("""
async def test_connection_fallback_error(hass: HomeAssistant) -> None:
    \"\"\"Testea que el fallback de error funciona si la respuesta no trae motivo.\"\"\"
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from unittest.mock import patch
    
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {"device_type": "samsung_8888", "ip_address": "1.1.1.1", "mac": "aa:bb"}
    
    with patch.object(flow, "_test_connection_safe", return_value={"ok": False}):
        res = await flow.async_step_test_connection()
        assert res["type"] == "form"
        assert res.get("data_schema") is not None
        assert res["errors"]["base"] == "cannot_connect"

async def test_initiate_pairing_fallback_error(hass: HomeAssistant) -> None:
    \"\"\"Testea que el fallback de unknown_error funciona si la respuesta no trae motivo.\"\"\"
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from unittest.mock import patch
    from homeassistant.core import HomeAssistant
    
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {"device_type": "samsung_8888"}
    
    # We mock _wait_token_safe to return {"ok": False} without "error"
    with patch.object(flow, "_wait_token_safe", return_value={"ok": False}):
        # First step creates the task
        res1 = await flow.async_step_await_button()
        assert res1["type"] == "progress"
        
        # Second step awaits the task
        res2 = await flow.async_step_await_button()
        assert res2["type"] == "progress"
        assert res2["step_id"] == "handle_error"
        assert flow.flow_data.get("error_key") == "unknown_error"

""")
print("Tests added.")
