"""Repairs flows for Samsung Climate IP integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None = None,
) -> RepairsFlow:
    """Create flow using Home Assistant Core's official ConfirmRepairFlow."""
    return ConfirmRepairFlow()
