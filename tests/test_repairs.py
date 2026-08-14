"""Test Samsung Climate IP repairs flows."""

from unittest.mock import MagicMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.climate_ip.repairs import async_create_fix_flow


async def test_auto_healing_repairs_flow_lifecycle():
    """Test auto-healing repairs flow lifecycle from initial form to confirmed dismissal."""
    mock_hass = MagicMock()
    flow = await async_create_fix_flow(
        mock_hass,
        "auto_healing_raw_test_device",
        data={"device_name": "Living Room AC"},
    )
    flow.hass = mock_hass
    flow.handler = "climate_ip"
    flow.issue_id = "auto_healing_raw_test_device"

    mock_issue = MagicMock()
    mock_issue.translation_placeholders = {"device_name": "Living Room AC"}

    with patch("homeassistant.helpers.issue_registry.async_get") as mock_get_ir:
        mock_ir = MagicMock()
        mock_ir.async_get_issue.return_value = mock_issue
        mock_get_ir.return_value = mock_ir

        # Initial step redirects to confirm form with schema
        result_init = await flow.async_step_init()
        assert result_init["type"] == FlowResultType.FORM
        assert result_init["step_id"] == "confirm"
        assert result_init["description_placeholders"] == {"device_name": "Living Room AC"}

        # User clicks Submit (Aceptar)
        result_confirm = await flow.async_step_confirm(user_input={})
        assert result_confirm["type"] == FlowResultType.CREATE_ENTRY
        assert result_confirm["data"] == {}
