with open("custom_components/climate_ip/tests/test_config_flow.py", "a") as f:
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
        assert res["type"] == "progress_done"
        assert res["step_id"] == "handle_error"
        assert flow.flow_data["error_key"] == "cannot_connect"

async def test_initiate_pairing_fallback_error(hass: HomeAssistant) -> None:
    \"\"\"Testea que el fallback de unknown_error funciona si la respuesta no trae motivo.\"\"\"
    from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
    from unittest.mock import patch
    from homeassistant.core import HomeAssistant
    import asyncio
    
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {"device_type": "samsung_8888"}
    
    async def mock_wait():
        return {"ok": False}
        
    with patch.object(flow, "_wait_token_safe", side_effect=mock_wait):
        res1 = await flow.async_step_await_button()
        if res1["type"] == "progress_done":
            assert res1["step_id"] == "handle_error"
        else:
            assert res1["type"] == "progress"
            res2 = await flow.async_step_await_button()
            assert res2["type"] == "progress_done"
            assert res2["step_id"] == "handle_error"
            
        assert flow.flow_data.get("error_key") == "unknown_error"
""")
