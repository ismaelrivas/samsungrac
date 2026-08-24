"""Test Samsung Climate IP repairs flows."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.climate_ip.repairs import async_create_fix_flow


@pytest.mark.asyncio
async def test_async_create_fix_flow_signatures_and_types():
    """Test async_create_fix_flow with various parameter combinations and return types."""
    mock_hass = MagicMock()

    # 1. Default data parameter omitted
    flow_default = await async_create_fix_flow(mock_hass, "issue_default")
    assert flow_default is not None
    assert isinstance(flow_default, ConfirmRepairFlow)
    assert isinstance(flow_default, RepairsFlow)

    # 2. Explicit data=None
    flow_none = await async_create_fix_flow(mock_hass, "issue_none", data=None)
    assert flow_none is not None
    assert isinstance(flow_none, ConfirmRepairFlow)
    assert isinstance(flow_none, RepairsFlow)

    # 3. Explicit dictionary data
    flow_dict = await async_create_fix_flow(
        mock_hass, "issue_custom", data={"key": "val", "count": 42}
    )
    assert flow_dict is not None
    assert isinstance(flow_dict, ConfirmRepairFlow)
    assert isinstance(flow_dict, RepairsFlow)


@pytest.mark.asyncio
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
        assert result_init["description_placeholders"] == {
            "device_name": "Living Room AC"
        }

        # User clicks Submit (Aceptar)
        result_confirm = await flow.async_step_confirm(user_input={})
        assert result_confirm["type"] == FlowResultType.CREATE_ENTRY
        assert result_confirm["data"] == {}


@pytest.mark.asyncio
async def test_repairs_flow_without_placeholders():
    """Test repairs flow lifecycle when issue has no translation placeholders."""
    mock_hass = MagicMock()
    flow = await async_create_fix_flow(mock_hass, "plain_issue")
    flow.hass = mock_hass
    flow.handler = "climate_ip"
    flow.issue_id = "plain_issue"

    mock_issue = MagicMock()
    mock_issue.translation_placeholders = None

    with patch("homeassistant.helpers.issue_registry.async_get") as mock_get_ir:
        mock_ir = MagicMock()
        mock_ir.async_get_issue.return_value = mock_issue
        mock_get_ir.return_value = mock_ir

        result_init = await flow.async_step_init()
        assert result_init["type"] == FlowResultType.FORM
        assert result_init["step_id"] == "confirm"
        assert result_init["description_placeholders"] is None

        result_confirm = await flow.async_step_confirm(user_input={})
        assert result_confirm["type"] == FlowResultType.CREATE_ENTRY
        assert result_confirm["data"] == {}
