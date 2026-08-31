"""Diagnostics support for climate_ip."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import TYPE_CHECKING, Any, Final, Protocol, cast, runtime_checkable

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant

from .coordinator import SamsungClimateCoordinator

if TYPE_CHECKING:
    from . import ClimateIPConfigEntry

KEY_MAIN_DEVICE: Final = "main"
REDACTED_TOKEN: Final = "**REDACTED**"

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


@runtime_checkable
class DiagnosticController(Protocol):
    """Protocol for controllers providing diagnostic data."""

    @property
    def connection_diagnostics(self) -> dict[str, Any]:
        """Return connection telemetry diagnostics."""

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic data."""

    @property
    def connection(self) -> Any:
        """Return the underlying connection."""


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
        stripped = candidate.strip()
        clean = stripped.replace(":", "").replace("-", "")
        if len(clean) == 12:
            patterns.add(clean.lower())
            patterns.add(clean.upper())
            formatted_colon = ":".join(clean[i : i + 2] for i in range(0, 12, 2))
            formatted_dash = "-".join(clean[i : i + 2] for i in range(0, 12, 2))
            patterns.add(formatted_colon.lower())
            patterns.add(formatted_colon.upper())
            patterns.add(formatted_dash.lower())
            patterns.add(formatted_dash.upper())
        elif len(stripped) > 5:
            patterns.add(stripped.lower())
            patterns.add(stripped.upper())

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
            target_len = len(pattern)
            if not target_len:
                continue
            target_lower = pattern.lower()
            res_lower = result.lower()
            start = 0
            chunks: list[str] = []
            while True:
                idx = res_lower.find(target_lower, start)
                if idx == -1:
                    chunks.append(result[start:])
                    break
                chunks.append(result[start:idx])
                chunks.append(REDACTED_TOKEN)
                start = idx + target_len
            result = "".join(chunks)
        return result

    if isinstance(val, dict):
        return {k: _deep_redact_substrings(v, threat_patterns) for k, v in val.items()}

    if isinstance(val, list):
        return [_deep_redact_substrings(v, threat_patterns) for v in val]

    if isinstance(val, tuple):
        return tuple(_deep_redact_substrings(v, threat_patterns) for v in val)

    return val


def _extract_controller_diagnostics(controller: DiagnosticController) -> dict[str, Any]:
    """Safely extract connection telemetry diagnostics strictly enforcing the Protocol."""
    try:
        return controller.connection_diagnostics
    except AttributeError:
        pass

    try:
        return controller.get_diagnostics()
    except AttributeError:
        pass

    try:
        return controller.connection.get_diagnostics()
    except AttributeError:
        return {}


def _extract_raw_device_state(coordinator: SamsungClimateCoordinator) -> dict[str, Any]:
    """Extract raw payload/state representation of the AC unit."""
    devices_state: dict[str, Any] = {}

    for device_id, device in coordinator.devices.items():
        try:
            devices_state[device_id] = device.raw_state
        except AttributeError:
            try:
                devices_state[device_id] = device.device_state
            except AttributeError:
                pass

    if not devices_state:
        ctrl = coordinator.controller
        try:
            devices_state[KEY_MAIN_DEVICE] = ctrl.raw_state
        except AttributeError:
            try:
                devices_state[KEY_MAIN_DEVICE] = ctrl.device_state
            except AttributeError:
                try:
                    devices_state[KEY_MAIN_DEVICE] = ctrl.last_poll_data
                except AttributeError:
                    pass

    return devices_state


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClimateIPConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    # Retrieve coordinator(s) from runtime_data
    entry_data = getattr(entry, "runtime_data", None)  # pragma: no mutate

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
                len(entities)
                if (entities := getattr(entry_data, "entities", None)) is not None
                and isinstance(entities, list | set | dict)
                else 0
            ),
        },
        "connection_telemetry": {},
        "raw_device_state": {},
    }

    if isinstance(entry_data, SamsungClimateCoordinator):
        if entry_data.data:
            diagnostics_data["coordinator_data"] = asdict(entry_data.data)
        state_attrs = getattr(entry_data.controller, "state_attributes", None)
        if state_attrs is not None:
            diagnostics_data["controller_state"] = state_attrs

        last_poll = getattr(entry_data.controller, "last_poll_data", None)
        if last_poll is not None:
            diagnostics_data["last_poll_response"] = last_poll

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

                state_attrs = getattr(coordinator.controller, "state_attributes", None)
                if state_attrs is not None:
                    coordinator_diag["controller_state"] = state_attrs

                last_poll = getattr(coordinator.controller, "last_poll_data", None)
                if last_poll is not None:
                    coordinator_diag["last_poll_response"] = last_poll

                conn_diag = _extract_controller_diagnostics(coordinator.controller)
                if conn_diag:
                    coordinator_diag["connection_diagnostics"] = conn_diag

                if coordinator.data:
                    coordinator_diag["coordinator_data"] = asdict(coordinator.data)

                diagnostics_data["coordinators"][device_id] = coordinator_diag

                total_discovered += getattr(coordinator, "discovered_devices_count", 1)
                total_skipped += getattr(coordinator, "skipped_devices_count", 0)
                entities = getattr(coordinator, "entities", None)
                if entities is not None and isinstance(
                    entities, list | set | dict
                ):
                    total_entities += len(entities)

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
    return cast(dict[str, Any], _deep_redact_substrings(redacted_data, threat_patterns))
