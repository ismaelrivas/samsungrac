# pylint: disable=unused-argument
"""Repairs flows for Samsung Climate IP integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,  # noqa: ARG001
    data: dict[str, Any] | None = None,  # noqa: ARG001
) -> RepairsFlow:
    """Create flow using Home Assistant Core's official ConfirmRepairFlow."""
    return ConfirmRepairFlow()
