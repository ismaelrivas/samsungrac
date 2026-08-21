"""Tests designed to kill mutmut Ultra survivors in config_flow.py."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_DEVICE_ID, CONF_IP_ADDRESS, CONF_MAC

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
)


async def test_kill_auth_file_not_found(hass):
    """Kill ValueError(None) and get("device", None) mutants."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    
    # 1. Test missing "auth_flow_file" key in "device"
    with patch("custom_components.climate_ip.config_flow.load_yaml", return_value={"device": {}}):
        with pytest.raises(ValueError, match="No 'auth_flow_file' found in"):
            await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)
            
    # 2. Test missing "device" key entirely
    with patch("custom_components.climate_ip.config_flow.load_yaml", return_value={}):
        with pytest.raises(ValueError, match="No 'auth_flow_file' found in"):
            await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)

async def test_kill_create_entry_device_id(hass):
    """Kill if dev_id in ("0", ...) mutant."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.async_create_entry = MagicMock(side_effect=lambda title, data: {"data": data})
    flow.async_abort = MagicMock(return_value={"aborted": True})
    
    # Passing a valid device_id should NOT be deleted
    flow.flow_data = {CONF_DEVICE_ID: "valid_id", "other": "data", CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878, CONF_MAC: "AA:BB:CC:DD:EE:FF"}
    entry = await flow._create_entry()
    assert entry["data"].get(CONF_DEVICE_ID) == "valid_id"
    
    # Passing an invalid device_id should be deleted
    flow.flow_data = {CONF_DEVICE_ID: "0", "other": "data", CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878, CONF_MAC: "AA:BB:CC:DD:EE:FF"}
    entry2 = await flow._create_entry()
    assert CONF_DEVICE_ID not in entry2["data"]

async def test_kill_acquirer_auth_flow_dict_process_samsung(hass):
    """Kill auth_flow_dict = None mutant in _async_process_samsung_device_step."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF"
    }
    
    auth_dict = {"mock_auth": "yes"}
    with patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._load_auth_flow_config", return_value=auth_dict), \
         patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id", return_value=None), \
         patch("custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer") as mock_acquirer:
         
         await flow._async_process_samsung_device_step("samsung_2878", is_8888=False, user_input={"dummy": "input"})
         
         # Verify 3rd argument is exactly auth_dict
         mock_acquirer.assert_called_with(hass, ip_address="192.168.1.100", auth_config=auth_dict, cert_path=None)

async def test_kill_acquirer_auth_flow_dict_initiate_pairing(hass):
    """Kill auth_flow_dict = None mutant in async_step_initiate_pairing."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF"
    }
    
    auth_dict = {"mock_auth": "yes"}
    with patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._load_auth_flow_config", return_value=auth_dict), \
         patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id", return_value=None), \
         patch("custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer") as mock_acquirer:
         
         fut = asyncio.Future()
         fut.set_result({"ok": False, "error": "test"})
         flow.task = fut
         
         await flow.async_step_initiate_pairing()
         mock_acquirer.assert_called_with(hass, "192.168.1.100", auth_dict, None)

async def test_kill_acquirer_auth_flow_dict_reconfigure_confirm(hass):
    """Kill auth_flow_dict = None mutant in async_step_reconfigure_confirm."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    
    mock_entry = MagicMock()
    mock_entry.data = {
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC: "AA:BB:CC:DD:EE:FF"
    }
    
    flow.reauth_entry = mock_entry
    flow.flow_data = mock_entry.data.copy()
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)
    
    auth_dict = {"mock_auth": "yes"}
    with patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._load_auth_flow_config", return_value=auth_dict), \
         patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_resolve_mac_and_set_unique_id", return_value=None), \
         patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow._async_validate_cert_path", return_value=True), \
         patch("custom_components.climate_ip.config_flow.ClimateIpConfigFlow.async_step_initiate_pairing", return_value={}), \
         patch("custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer") as mock_acquirer:
         
         try:
             await flow.async_step_reconfigure_confirm({CONF_IP_ADDRESS: "192.168.1.100"})
         except Exception:
             pass
         
         mock_acquirer.assert_called_with(hass, "192.168.1.100", auth_dict, None)


async def test_kill_auth_flow_dict_extraction(hass):
    """Kill get('auth_flow', {}) mutants in _load_auth_flow_config."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    # 1. Validar que extrae la sección 'auth_flow' correctamente
    mock_yaml_main = {"device": {"auth_flow_file": "auth.yaml"}}
    mock_yaml_auth = {"auth_flow": {"expected_key": "expected_val"}, "other": "ignored"}

    with patch("custom_components.climate_ip.config_flow.load_yaml", side_effect=[mock_yaml_main, mock_yaml_auth]):
        res = await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)
        assert res == {"expected_key": "expected_val"}
        assert res.get("expected_key") == "expected_val"

    # 2. Validar que el fallback {} actúa si 'auth_flow' no existe
    mock_yaml_no_auth = {"other_section": 123}
    with patch("custom_components.climate_ip.config_flow.load_yaml", side_effect=[mock_yaml_main, mock_yaml_no_auth]):
        res_empty = await flow._load_auth_flow_config(DEVICE_TYPE_SAMSUNG_2878)
        assert res_empty == {}
        assert isinstance(res_empty, dict)

