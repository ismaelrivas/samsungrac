"""Diagnostics support for climate_ip."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any, TYPE_CHECKING

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_MAC
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

# Regex to detect 12-char hex DUID or 17-char colon/dash MAC addresses
RE_MAC_DUID = re.compile(
    r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b|\b[0-9A-Fa-f]{12}\b"
)


def _get_mac_threat_patterns(entry: "ClimateIPConfigEntry") -> set[str]:
    """Extract MAC address and DUID variants to build threat patterns for substring redaction."""
    patterns: set[str] = set()

    # Retrieve explicit MAC configuration values securely
    raw_mac = entry.data.get(CONF_MAC, entry.data.get("mac"))
    candidates: list[str] = []

    if isinstance(raw_mac, str):
        candidates.append(raw_mac)

    # Also inspect title and unique_id for embedded MAC patterns
    for item in (entry.title, entry.unique_id):
        if isinstance(item, str):
            for match in RE_MAC_DUID.findall(item):
                candidates.append(match)

    for candidate in candidates:
        clean = candidate.replace(":", "").replace("-", "").strip()
        if len(clean) == 12:
            patterns.add(clean)
            formatted_colon = ":".join(clean[i : i + 2] for i in range(0, 12, 2))
            formatted_dash = "-".join(
                clean[i : i + 2] for i in range(0, 12, 2)
            )
            patterns.add(formatted_colon)
            patterns.add(formatted_dash)
        elif len(candidate) > 5:
            patterns.add(candidate)

    return {p for p in patterns if p}


def _deep_redact_substrings(val: Any, threat_patterns: set[str]) -> Any:
    """Recursively traverse data structures and redact threat patterns embedded in strings."""
    if not threat_patterns:
        return val

    # Sort patterns by length descending so longer MAC formats are replaced first
    sorted_patterns = sorted(
        threat_patterns, key=len, reverse=True
    )

    if isinstance(val, str):
        result = val
        for pattern in sorted_patterns:
            result = re.sub(
                re.escape(pattern), "**REDACTED**", result, flags=re.IGNORECASE
            )
        return result

    if isinstance(val, dict):
        return {k: _deep_redact_substrings(v, threat_patterns) for k, v in val.items()}

    if isinstance(val, list):
        return [_deep_redact_substrings(v, threat_patterns) for v in val]

    if isinstance(val, tuple):
        return tuple(_deep_redact_substrings(v, threat_patterns) for v in val)

    return val


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: "ClimateIPConfigEntry"
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    # The data stored could be a single coordinator or a dict of coordinators
    entry_data = entry.runtime_data

    # Filter the entry data to only include relevant information for this integration.
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
                if hasattr(coordinator.controller, "connection_diagnostics"):
                    coordinator_diag["connection_diagnostics"] = (
                        coordinator.controller.connection_diagnostics
                    )

                if coordinator.data:
                    coordinator_diag["coordinator_data"] = asdict(coordinator.data)

                diagnostics_data["coordinators"][device_id] = coordinator_diag

    # Apply Home Assistant's native async_redact_data to recursively clean
    # the entire diagnostic tree (including nested YAML dictionaries or raw responses).
    redacted_data = async_redact_data(diagnostics_data, TO_REDACT)

    # Apply deep substring walker to redact embedded MAC / DUID patterns from strings
    threat_patterns = _get_mac_threat_patterns(entry)
    return _deep_redact_substrings(redacted_data, threat_patterns)
