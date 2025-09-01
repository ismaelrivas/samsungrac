"""Diagnostics support for climate_ip."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SamsungClimateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # The data stored could be a single coordinator or a dict of coordinators
    entry_data = hass.data[DOMAIN][entry.entry_id]

    diagnostics_data = {"entry": entry.as_dict()}

    if isinstance(entry_data, SamsungClimateCoordinator):
        # Handle single device entry
        diagnostics_data["coordinator_data"] = entry_data.data
        diagnostics_data["controller_state"] = entry_data.controller.state_attributes
    elif isinstance(entry_data, dict):
        # Handle multi-device entry
        diagnostics_data["coordinators"] = {}
        for device_id, coordinator in entry_data.items():
            if isinstance(coordinator, SamsungClimateCoordinator):
                diagnostics_data["coordinators"][device_id] = {
                    "coordinator_data": coordinator.data,
                    "controller_state": coordinator.controller.state_attributes,
                }

    return diagnostics_data
