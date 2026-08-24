"""Diagnostics support for climate_ip."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import ClimateIPConfigEntry
from .const import DOMAIN
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
    "cert",
}

# Regex to detect 12-char hex DUID or 17-char colon/dash MAC addresses
RE_MAC_DUID = re.compile(
    r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b|\b[0-9A-Fa-f]{12}\b"
)


def _get_mac_threat_patterns(entry: ClimateIPConfigEntry) -> set[str]:
    """Extract MAC address and DUID variants to build threat patterns for substring redaction."""
    patterns: set[str] = set()

    # Retrieve explicit MAC configuration values securely
    raw_mac = entry.data.get(CONF_MAC)
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
            formatted_dash = "-".join(clean[i : i + 2] for i in range(0, 12, 2))
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
    sorted_patterns = sorted(threat_patterns, key=len, reverse=True)

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


def _extract_controller_diagnostics(controller: Any) -> dict[str, Any]:
    """Safely extract connection telemetry diagnostics from controller or connection."""
    if hasattr(controller, "connection_diagnostics") and isinstance(
        getattr(controller, "connection_diagnostics", None), dict
    ):
        return controller.connection_diagnostics

    if hasattr(controller, "get_diagnostics"):
        get_diag = controller.get_diagnostics
        if callable(get_diag):
            res = get_diag()
            if isinstance(res, dict):
                return res

    if hasattr(controller, "connection"):
        conn = controller.connection
        if hasattr(conn, "get_diagnostics"):
            get_diag = conn.get_diagnostics
            if callable(get_diag):
                res = get_diag()
                if isinstance(res, dict):
                    return res

    return {}


def _extract_raw_device_state(coordinator: Any) -> dict[str, Any]:
    """Extract raw payload/state representation of the AC unit."""
    devices_state: dict[str, Any] = {}

    if hasattr(coordinator, "devices") and isinstance(coordinator.devices, dict):
        for device_id, device in coordinator.devices.items():
            if hasattr(device, "raw_state"):
                devices_state[device_id] = device.raw_state
            elif hasattr(device, "device_state"):
                devices_state[device_id] = device.device_state

    if not devices_state and hasattr(coordinator, "controller"):
        ctrl = coordinator.controller
        if hasattr(ctrl, "raw_state"):
            devices_state["main"] = ctrl.raw_state
        elif hasattr(ctrl, "device_state"):
            devices_state["main"] = ctrl.device_state
        elif hasattr(ctrl, "last_poll_data"):
            devices_state["main"] = ctrl.last_poll_data

    return devices_state


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClimateIPConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    # Retrieve coordinator(s) from runtime_data or hass.data
    entry_data = getattr(entry, "runtime_data", None)  # pragma: no mutate
    if entry_data is None and hass and DOMAIN in hass.data:  # pragma: no mutate
        entry_data = hass.data[DOMAIN].get(entry.entry_id)  # pragma: no mutate

    filtered_entry_data: dict[str, Any] = {
        "title": entry.title,
        "domain": entry.domain,
        "unique_id": entry.unique_id,
        "data": dict(entry.data),
        "options": dict(entry.options),
    }

    diagnostics_data: dict[str, Any] = {
        "entry": filtered_entry_data,
        "bootstrapping": {
            "total_devices_discovered": getattr(
                entry_data, "discovered_devices_count", 0
            ),
            "skipped_devices_missing_info": getattr(
                entry_data, "skipped_devices_count", 0
            ),
            "active_entities": (
                len(entry_data.entities)
                if entry_data is not None
                and hasattr(entry_data, "entities")
                and isinstance(entry_data.entities, list | set | dict)
                else 0
            ),
        },
        "connection_telemetry": {},
        "raw_device_state": {},
    }

    if isinstance(entry_data, SamsungClimateCoordinator):
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

        conn_diag = _extract_controller_diagnostics(entry_data.controller)
        if conn_diag:
            diagnostics_data["connection_diagnostics"] = conn_diag
            diagnostics_data["connection_telemetry"] = conn_diag

        raw_state = _extract_raw_device_state(entry_data)
        if raw_state:
            diagnostics_data["raw_device_state"] = raw_state

    elif isinstance(entry_data, dict):
        diagnostics_data["coordinators"] = {}
        total_discovered = 0
        total_skipped = 0
        total_entities = 0

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

                conn_diag = _extract_controller_diagnostics(coordinator.controller)
                if conn_diag:
                    coordinator_diag["connection_diagnostics"] = conn_diag

                if coordinator.data:
                    coordinator_diag["coordinator_data"] = asdict(coordinator.data)

                diagnostics_data["coordinators"][device_id] = coordinator_diag

                total_discovered += getattr(coordinator, "discovered_devices_count", 1)
                total_skipped += getattr(coordinator, "skipped_devices_count", 0)
                if hasattr(coordinator, "entities") and isinstance(
                    coordinator.entities, list | set | dict
                ):
                    total_entities += len(coordinator.entities)

        diagnostics_data["bootstrapping"]["total_devices_discovered"] = total_discovered
        diagnostics_data["bootstrapping"]["skipped_devices_missing_info"] = (
            total_skipped
        )
        diagnostics_data["bootstrapping"]["active_entities"] = total_entities

    # Apply Home Assistant's native async_redact_data to recursively clean
    # the entire diagnostic tree (including nested YAML dictionaries or raw responses).
    redacted_data = async_redact_data(diagnostics_data, TO_REDACT)

    # Apply deep substring walker to redact embedded MAC / DUID patterns from strings
    threat_patterns = _get_mac_threat_patterns(entry)
    return _deep_redact_substrings(redacted_data, threat_patterns)
