"""Diagnostics support for climate_ip."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

def _mask_sensitive_data(data: Any) -> Any:
    """Recursively mask sensitive data in a dictionary or list."""
    if isinstance(data, dict):
        return {
            key: f"***{value[-4:]}" if key in SENSITIVE_KEYS and isinstance(value, str) and len(value) > 4 else _mask_sensitive_data(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_mask_sensitive_data(item) for item in data]
    return data

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # Move imports inside the function to prevent blocking calls during startup.
    from .coordinator import SamsungClimateCoordinator
    from homeassistant.const import CONF_MAC, CONF_TOKEN

    from .const import DOMAIN

    # Define sensitive keys here, now that constants are imported.
    sensitive_keys = [
        CONF_TOKEN,
        CONF_MAC,
        "unique_id",
        "uuid",
        "DeviceToken",
        "Authorization",
        "DUID",
    ]

    # The data stored could be a single coordinator or a dict of coordinators
    entry_data = hass.data[DOMAIN][entry.entry_id]

    # Filter the entry data to only include relevant information for this integration.
    filtered_entry_data = {
        "data": dict(entry.data),
        "options": entry.options,
        "unique_id": entry.unique_id,
    }
    diagnostics_data = {"entry": filtered_entry_data}

    if isinstance(entry_data, SamsungClimateCoordinator):
        # Handle single device entry
        diagnostics_data["coordinator_data"] = asdict(entry_data.data) if entry_data.data else None
        diagnostics_data["controller_state"] = entry_data.controller.state_attributes
        diagnostics_data["last_poll_response"] = entry_data.controller._state_getter.value
    elif isinstance(entry_data, dict):
        # Handle multi-device entry
        diagnostics_data["coordinators"] = {}
        for device_id, coordinator in entry_data.items():
            if isinstance(coordinator, SamsungClimateCoordinator):
                diagnostics_data["coordinators"][device_id] = {
                    "coordinator_data": asdict(coordinator.data) if coordinator.data else None,
                    "controller_state": coordinator.controller.state_attributes,
                    "last_poll_response": coordinator.controller._state_getter.value,
                }

    # Local masking function that uses the locally defined sensitive_keys.
    def _local_mask_data(data: Any) -> Any:
        """Recursively mask sensitive data."""
        if isinstance(data, dict):
            masked_dict = {}
            for key, value in data.items():                
                if key in sensitive_keys and isinstance(value, str) and len(value) > 6:
                    masked_dict[key] = f"***{value[-6:]}"
                elif isinstance(value, Mapping):
                    masked_dict[key] = _local_mask_data(dict(value))
                else:
                    masked_dict[key] = _local_mask_data(value)
            return masked_dict
        if isinstance(data, list):
            return [_local_mask_data(item) for item in data]
        return data

    return _local_mask_data(diagnostics_data)
