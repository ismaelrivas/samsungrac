"""Diagnostics support for climate_ip."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, TYPE_CHECKING

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import ClimateIPConfigEntry
from .coordinator import SamsungClimateCoordinator

# Keys containing sensitive data that must be redacted from diagnostic payloads.
# Kept in sync with helpers.mask_sensitive_data — any new sensitive field should
# be added to BOTH lists.
TO_REDACT: set[str] = {
    "token",
    "mac",
    "ip_address",
    "host",
    "unique_id",
    "password",
    "uuid",
    "duid",
    "DUID",  # Samsung uses uppercase in some protocol responses
    "Authorization",
    "DeviceToken",
    "access_token",
    "refresh_token",
    "serial_number",  # Future-proofing: Samsung REST API may expose this
    "serialNumber",  # Samsung camelCase variant
}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: "ClimateIPConfigEntry"
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    # The data stored could be a single coordinator or a dict of coordinators
    entry_data = entry.runtime_data

    # Filter the entry data to only include relevant information for this integration.
    # We don't pre-filter entry.data with a hardcoded allowlist anymore;
    # instead, we rely on async_redact_data to deep-clean the entire dictionary,
    # ensuring no unexpected PII leaks if new fields are added in the future.
    filtered_entry_data: dict[str, Any] = {
        "data": dict(entry.data),
        "options": dict(entry.options),
        "unique_id": entry.unique_id,
        "domain": entry.domain,
        "title": entry.title,
    }
    diagnostics_data: dict[str, Any] = {"entry": filtered_entry_data}

    if isinstance(entry_data, SamsungClimateCoordinator):
        # Handle single device entry
        if entry_data.data:
            diagnostics_data["coordinator_data"] = asdict(entry_data.data)
        if hasattr(entry_data.controller, "state_attributes"):
            diagnostics_data["controller_state"] = (
                entry_data.controller.state_attributes
            )
        if hasattr(entry_data.controller, "last_poll_data"):
            diagnostics_data["last_poll_response"] = (
                entry_data.controller.last_poll_data
            )
        # FIXED C0301: Line split to stay under 100 chars
        if hasattr(entry_data.controller, "connection_diagnostics"):
            diagnostics_data["connection_diagnostics"] = (
                entry_data.controller.connection_diagnostics
            )

    elif isinstance(entry_data, dict):
        # Handle multi-device entry
        diagnostics_data["coordinators"] = {}
        for device_id, coordinator in entry_data.items():
            if isinstance(coordinator, SamsungClimateCoordinator):
                coordinator_diag: dict[str, Any] = {}

                if hasattr(coordinator.controller, "state_attributes"):
                    coordinator_diag["controller_state"] = (
                        coordinator.controller.state_attributes
                    )
                if hasattr(coordinator.controller, "last_poll_data"):
                    coordinator_diag["last_poll_response"] = (
                        coordinator.controller.last_poll_data
                    )
                # FIXED C0301: Line split to stay under 100 chars
                if hasattr(coordinator.controller, "connection_diagnostics"):
                    coordinator_diag["connection_diagnostics"] = (
                        coordinator.controller.connection_diagnostics
                    )

                if coordinator.data:
                    coordinator_diag["coordinator_data"] = asdict(coordinator.data)

                diagnostics_data["coordinators"][device_id] = coordinator_diag

    # Apply Home Assistant's native async_redact_data to recursively clean
    # the entire diagnostic tree (including nested YAML dictionaries or raw responses).
    return async_redact_data(diagnostics_data, TO_REDACT)
