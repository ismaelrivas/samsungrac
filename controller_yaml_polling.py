# pylint: disable=import-outside-toplevel,line-too-long,protected-access,too-many-branches,too-many-instance-attributes,too-many-lines,too-many-locals,too-many-nested-blocks,too-many-statements
"""State management and polling for YAML-configured climate controllers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol, cast, runtime_checkable

from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ClimateEntityFeature,
)
from homeassistant.const import (
    ATTR_NAME,
    ATTR_TEMPERATURE,
    STATE_UNKNOWN,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.json import json_loads

from .const import (
    CONF_DEVICE_TYPE,
    CONFIG_DEVICE,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
)
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .helpers import async_check_network_reachability, get_value_by_path
from .properties import render_template
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class YamlPropertyProtocol(Protocol):
    """Protocol defining the interface for YAML properties and operations."""

    id: str
    value: Any

    def convert_hass_to_dev(self, value: Any) -> Any: ...

    def set_device_state_for_values(self, state: dict[str, Any]) -> None: ...

    def calculate_value_from_state(self, state: dict[str, Any]) -> Any: ...

    def async_update_state(self, state: dict[str, Any], debug: bool) -> Any: ...

    def should_evict_all_locks(
        self, state: dict[str, Any], changed_keys: set[str]
    ) -> bool: ...

    def apply_optimistic_cascades(
        self, state: dict[str, Any], value: Any, dev_val: Any
    ) -> None: ...


class YamlStatePoller:
    """Class responsible for polling the device and managing state."""

    CACHE_FRESHNESS_SEC = 2.0
    LOCK_TTL_SEC = 45.0
    LOCK_SHIELD_SEC = 3.0
    LOCK_PHYSICAL_TIMEOUT_SEC = 15.0
    MAX_LIST_INFLATION_SIZE = 100

    HASS_ATTR_MAP = {
        "hvac": "hvac_mode",
        "hvac_mode": "hvac_mode",
        ATTR_HVAC_MODE: "hvac_mode",
        "temperature": "target_temperature",
        "target_temperature": "target_temperature",
        ATTR_TEMPERATURE: "target_temperature",
        "current_temperature": "current_temperature",
        "fan": "fan_mode",
        "fan_mode": "fan_mode",
        ATTR_FAN_MODE: "fan_mode",
        "swing": "swing_mode",
        "swing_mode": "swing_mode",
        ATTR_SWING_MODE: "swing_mode",
        "preset": "preset_mode",
        "preset_mode": "preset_mode",
        ATTR_PRESET_MODE: "preset_mode",
        "special": "preset_mode",
    }

    @staticmethod
    def _set_prop_value(prop: YamlPropertyProtocol | Any, value: Any) -> None:
        """Safely set a value on a property object regardless of duck-typing interface."""
        if hasattr(prop, "value"):
            prop.value = value
        elif hasattr(prop, "_value"):
            prop._value = value

    @staticmethod
    def _get_prop_value(prop: YamlPropertyProtocol | Any) -> Any:
        """Safely get a value from a property object regardless of duck-typing interface."""
        return getattr(prop, "value", getattr(prop, "_value", None))

    def __init__(self, controller: Any) -> None:
        """Initialize the poller with a reference to the main controller facade."""
        self.controller = controller

        self._cached_device_state: dict[str, Any] | None = None
        self._last_state_fetch_time: float = 0.0
        self._last_device_state: dict[str, Any] | None = None
        self._consecutive_connection_errors: int = 0

        self._pure_network_state: dict[str, Any] | None = None

        # Caches resolved state_nodes for properties
        self._prop_template_key_cache: dict[str, str | None] = {}

        # Shield Engine (Optimistic Locks)
        self._pending_updates: dict[str, tuple[Any, float]] = {}

    def register_pending_update(self, property_id: str, value: Any) -> None:
        """Register a pending update to shield the UI from stale network polling echoes."""
        self._pending_updates[property_id] = (value, time.monotonic())

    def clear_pending_updates(self, keys: list[str]) -> None:
        """Clear specific pending updates (anti-flicker locks) instantly."""
        for key in keys:
            self._pending_updates.pop(key, None)

    def _clear_state_cache(self) -> None:
        """Clear internal state cache buffer to prevent stale data (anti-ghosting)."""
        self._cached_device_state = None
        self._last_device_state = None
        if hasattr(self, "_pure_network_state"):
            self._pure_network_state = None

    def clear_state_cache(self) -> None:
        """Public interface for clearing internal state cache (anti-ghosting).

        Delegates to the internal _clear_state_cache without exposing its
        private naming to callers outside this class.
        """
        self._clear_state_cache()

    async def _refresh_smartthings_token(self) -> str | None:
        """Attempt to refresh an expired SmartThings token using the official HA integration."""
        try:
            if not getattr(self.controller, "hass", None):
                return None

            entries = self.controller.hass.config_entries.async_entries("smartthings")
            if not entries:
                _LOGGER.debug(
                    "%s [Auth] No Official SmartThings config entries found.",
                    self.controller.log_prefix,
                )
                return None

            entry = entries[0]
            implementation = (
                await config_entry_oauth2_flow.async_get_config_entry_implementation(
                    self.controller.hass, entry
                )
            )
            session = config_entry_oauth2_flow.OAuth2Session(
                self.controller.hass, entry, implementation
            )

            await session.async_ensure_token_valid()
            token: str | None = session.token.get("access_token")
            masked = (
                f"***{token[-6:]}" if token and len(token) > 6 else "None"
            )  # pragma: no mutate
            _LOGGER.debug(
                "%s [Auth] OAuth2 session token validated. Token: %s",
                self.controller.log_prefix,
                masked,
            )
            return token
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s [Auth] Error refreshing SmartThings token via OAuth2: %s",
                self.controller.log_prefix,
                e,
            )
            return None

    def _all_props(self) -> list[Any]:
        """Return all loaded properties (state getter + operations + sensors)."""
        loader = self.controller.loader
        return (
            ([loader.state_getter] if loader.state_getter else [])
            + list(loader.operations.values())
            + list(loader.sensors.values())
        )

    @property
    def _device_identifier(self) -> str:
        """Return a reliable identifier for the device (unique_id, host, or ip_address)."""
        return str(
            self.controller.unique_id
            or self.controller.host
            or self.controller.ip_address
            or "unknown"
        )

    def _try_create_repair_issue(self) -> None:
        """Create a HA repair issue for persistent device offline state."""
        if not self.controller.hass:
            return
        try:
            safe_device_id = self._device_identifier.replace(".", "_").replace(" ", "_")
            config_name = self.controller.config.get("name")
            device_name = (
                config_name if config_name else f"Samsung AC {self._device_identifier}"
            )
            async_create_issue(
                self.controller.hass,
                "climate_ip",
                f"device_offline_{safe_device_id}",
                is_fixable=False,
                is_persistent=False,
                severity=IssueSeverity.WARNING,
                translation_key="connection_failed",
                translation_placeholders={
                    "device_name": device_name,
                    "host": self.controller.ip_address
                    or self.controller.host
                    or "Unknown",
                    "ip_address": self.controller.ip_address
                    or self.controller.host
                    or "Unknown",
                },
            )
            _LOGGER.info(
                "%s Created repair issue 'device_offline_%s' for %s (%s)",
                self.controller.log_prefix,
                safe_device_id,
                self.controller.name or "Climate IP",
                self.controller.ip_address or self.controller.host or "Unknown",
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.debug(
                "%s Failed to create repair issue: %s",
                self.controller.log_prefix,
                e,
                exc_info=True,
            )

    def _try_delete_repair_issue(self) -> None:
        """Delete the HA repair issue when the device is back online."""
        if not self.controller.hass:
            return

        try:
            safe_device_id = self._device_identifier.replace(".", "_").replace(" ", "_")
            issue_id = f"device_offline_{safe_device_id}"

            async_delete_issue(
                self.controller.hass,
                "climate_ip",
                issue_id,
            )
            _LOGGER.debug(
                "%s Cleared repair issue '%s' (connection recovered)",
                self.controller.log_prefix,
                issue_id,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.debug(
                "%s Failed to clear repair issue: %s",
                self.controller.log_prefix,
                e,
                exc_info=True,
            )

    def _update_all_connections_token(self, new_token: str) -> None:
        """Propagate the new token to all active connection engines."""
        updated_connections: set[Any] = set()
        for prop in self._all_props():
            if (
                prop
                and (conn := prop.get_connection(None))
                and conn not in updated_connections
            ):
                if hasattr(conn, "update_auth_token"):
                    conn.update_auth_token(new_token)
                    updated_connections.add(conn)

    async def async_get_status(self) -> dict[str, Any] | None:
        """Fetch status prioritizing memory state to shield from polling flicker."""
        now_ts = time.monotonic()
        if self._cached_device_state and (
            now_ts - self._last_state_fetch_time < self.CACHE_FRESHNESS_SEC
        ):
            st_getter = self.controller.loader.state_getter
            if st_getter and st_getter.value:  # pragma: no mutate
                # Return RAM state injected with locks to lock the UI without flickering
                return cast(
                    dict[str, Any] | None,
                    dict(st_getter.value)
                    if isinstance(st_getter.value, dict)
                    else st_getter.value,
                )  # pragma: no mutate
            return self._cached_device_state.copy()

        device_state = await self.async_update_state()
        return (
            dict(device_state) if isinstance(device_state, dict) else device_state
        )  # pragma: no mutate

    def _requires_icmp_ping(self, device_type: str) -> bool:
        """Determine if this device type requires an ICMP ping before polling."""
        return device_type not in (
            DEVICE_TYPE_SAMSUNG_2878,
            DEVICE_TYPE_SMARTTHINGS_HVAC,
            DEVICE_TYPE_SMARTTHINGS_DHW,
        )

    async def _async_perform_icmp_check(self) -> None:
        """Perform ICMP ping connectivity check."""
        device_type = self.controller.config.get(CONF_DEVICE_TYPE)
        if not self._requires_icmp_ping(device_type) or not getattr(
            self.controller, "ip_address", None
        ):
            return

        try:
            network_reachable = await async_check_network_reachability(
                self.controller.ip_address, self.controller.log_prefix
            )
        except Exception as diag_err:
            _LOGGER.debug(
                "%s ICMP check failed: %s", self.controller.log_prefix, diag_err
            )
            return

        if not network_reachable:
            raise CannotConnect("Host unreachable (ICMP ping failed).")

    async def async_update_state(self) -> dict[str, Any] | None:
        """Fetch the actual state from the device over the network."""
        if getattr(self.controller.loader, "state_getter", None) is None:
            return None

        try:
            await self._async_perform_icmp_check()

            full_device_state = (
                await self.controller.loader.state_getter.async_update_state(
                    None, getattr(self.controller, "debug", False)
                )
            )

        except AuthError as exc:
            new_token = await self._refresh_smartthings_token()
            if new_token and new_token != self.controller.token:
                if hasattr(self.controller, "token"):
                    self.controller.token = new_token
                self._update_all_connections_token(new_token)

                if (
                    hasattr(self.controller, "on_token_refreshed")
                    and self.controller.on_token_refreshed
                ):
                    self.controller.on_token_refreshed(new_token)

                try:
                    full_device_state = (
                        await self.controller.loader.state_getter.async_update_state(
                            None, self.controller.debug
                        )
                    )
                except Exception as retry_exc:
                    self._clear_state_cache()
                    raise UpdateFailed(
                        f"Retry after token refresh failed: {retry_exc}"
                    ) from retry_exc
            else:
                self._clear_state_cache()
                raise ConfigEntryAuthFailed(
                    "Authentication failed. Please check tokens."
                ) from exc

        except InvalidHeaderError:
            raise

        except (
            CannotConnect,
            TimeoutError,
            ConnectionRefusedError,
            OSError,
        ) as e:
            if "persistently offline" in str(e):
                self._consecutive_connection_errors = 2
            else:
                self._consecutive_connection_errors += 1

            if (
                getattr(self.controller, "available", True)  # pragma: no mutate
                and self._consecutive_connection_errors <= 2  # pragma: no mutate
                and self._cached_device_state is not None  # pragma: no mutate
            ):
                return self._cached_device_state

            if self._consecutive_connection_errors == 3:
                self._try_create_repair_issue()

            self._clear_state_cache()
            reason = str(e).split(":")[-1].strip()  # pragma: no mutate
            raise UpdateFailed(f"Device unreachable: {reason}") from e

        if full_device_state is None:
            if (
                getattr(self.controller, "available", True)
                and self._cached_device_state
            ):
                return self._cached_device_state
            self._clear_state_cache()
            raise UpdateFailed(
                "Failed to get device state: No data received and no cache available"
            )

        if self._consecutive_connection_errors > 0:
            _LOGGER.info(
                "%s Connection recovered after %d failure(s).",
                self.controller.log_prefix,
                self._consecutive_connection_errors,
            )
            self._try_delete_repair_issue()
            self._consecutive_connection_errors = 0

        self._cached_device_state = full_device_state
        self._last_state_fetch_time = time.monotonic()

        # 💥 NETWORK TRUTH STORAGE: Isolated from UI pollution
        self._pure_network_state = (
            dict(full_device_state)
            if isinstance(full_device_state, dict)
            else full_device_state
        )

        if not self.controller.loader.is_fully_initialized:
            try:
                device_type = self.controller.config.get(CONF_DEVICE_TYPE)
                cache = getattr(self.controller.loader, "_parsed_yaml_cache", {})
                device_id = getattr(self.controller, "device_id", "XXXX")
                device_cache = cache.get(device_id) or {}
                device_config = device_cache.get(CONFIG_DEVICE) or {}
                id_map = device_config.get("identifiers")

                if id_map:
                    self.controller.discovered_devices = get_value_by_path(
                        full_device_state, id_map.get("path_to_devices", [])
                    )

                    if self.controller.discovered_devices:
                        device_to_discover = self._discover_target_node(
                            device_type, self.controller.discovered_devices
                        )

                        if device_to_discover:
                            id_path = id_map.get("id")
                            discovered_id = (
                                get_value_by_path(device_to_discover, id_path)
                                if id_path
                                else None
                            )
                            curr_dev_id = getattr(self.controller, "device_id", "")
                            if discovered_id is not None and (
                                not curr_dev_id or curr_dev_id == "0"
                            ):
                                if hasattr(self.controller, "device_id"):
                                    self.controller.device_id = str(discovered_id)

                await self.controller.loader.async_finish_initialization()

            except Exception:
                _LOGGER.exception(
                    "%s Error during initial device discovery",
                    self.controller.log_prefix,
                )

        await self.async_update_properties_from_state(full_device_state)
        return cast(dict[str, Any] | None, self.controller.loader.state_getter.value)

    def _discover_target_node(
        self, device_type: str, devices_list: list[Any]
    ) -> dict[str, Any] | None:
        """Isolate device-specific discovery logic."""
        if device_type == DEVICE_TYPE_MIM_H03:
            return next(
                (d for d in devices_list if d and d.get("id") != "0" and "Mode" in d),
                None,
            )
        return devices_list[0] if devices_list else None

    @staticmethod
    def _values_match(val1: Any, val2: Any) -> bool:
        """Check if two values match numerically (float cast) or string-wise (case-insensitive)."""
        if val1 is None or val2 is None:  # pragma: no mutate
            return cast(bool, val1 == val2)  # pragma: no mutate
        if hasattr(val1, "value") and not isinstance(val1, dict):
            val1 = val1.value  # pragma: no mutate
        if hasattr(val2, "value") and not isinstance(val2, dict):
            val2 = val2.value  # pragma: no mutate
        try:
            return float(val1) == float(val2)
        except (ValueError, TypeError):
            return str(val1).strip().lower() == str(val2).strip().lower()

    def _get_state_node_from_prop(self, prop: Any) -> str | None:
        """Extract the exact state node key used by this property from the parsed YAML operations."""
        prop_id = getattr(prop, "id", None)  # pragma: no mutate
        if not prop_id:  # pragma: no mutate
            return None

        if prop_id in self._prop_template_key_cache:
            return self._prop_template_key_cache[prop_id]

        state_node = getattr(prop, "state_node", None) or getattr(
            prop, "_state_node", None
        )  # pragma: no mutate
        if state_node and isinstance(state_node, str):  # pragma: no mutate
            self._prop_template_key_cache[prop_id] = state_node
            return state_node

        status_tmpl = getattr(prop, "status_template", None)  # pragma: no mutate
        if not status_tmpl:  # pragma: no mutate
            self._prop_template_key_cache[prop_id] = None
            return None

        template_string = (
            status_tmpl.template
            if hasattr(status_tmpl, "template")
            else str(status_tmpl)
        )  # pragma: no mutate
        if not template_string:  # pragma: no mutate
            self._prop_template_key_cache[prop_id] = None
            return None

        self._prop_template_key_cache[prop_id] = None
        return None

    def _set_dict_value_by_path(
        self, target_dict: dict[str, Any], path_str: str, value: Any
    ) -> None:
        """Inject a value into a nested dict using dot notation path."""
        parts = path_str.split(".")
        current: Any = target_dict
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            next_part = parts[i + 1] if not is_last else None

            if is_last:
                if isinstance(current, dict):
                    current[part] = value
                elif isinstance(current, list) and part.isdigit():  # pragma: no mutate
                    idx = int(part)
                    if idx > self.MAX_LIST_INFLATION_SIZE:
                        raise ValueError(
                            f"Path '{path_str}' attempted to inflate list beyond limit ({idx} > {self.MAX_LIST_INFLATION_SIZE})"  # pragma: no mutate
                        )
                    while len(current) <= idx:
                        current.append(None)

                    current[idx] = value
                return

            if isinstance(current, dict):
                if part not in current or current[part] is None:
                    current[part] = [] if (next_part and next_part.isdigit()) else {}
                current = current[part]
                continue

            if isinstance(current, list) and part.isdigit():  # pragma: no mutate
                idx = int(part)
                if idx > self.MAX_LIST_INFLATION_SIZE:
                    raise ValueError(
                        f"Path '{path_str}' attempted to inflate list beyond limit ({idx} > {self.MAX_LIST_INFLATION_SIZE})"  # pragma: no mutate
                    )
                while len(current) <= idx:
                    current.append({})
                if current[idx] is None:
                    current[idx] = (
                        [] if (next_part and next_part.isdigit()) else {}
                    )  # pragma: no mutate
                current = current[idx]
                continue

            return

    def _inject_value_into_state(
        self, prop: YamlPropertyProtocol | Any, device_state: dict[str, Any], value: Any
    ) -> None:
        """Safely inject an optimistic value into the raw device state using state_node & native converters."""
        if not isinstance(device_state, dict):
            return

        dev_val = value
        if hasattr(prop, "convert_hass_to_dev"):
            try:
                dev_val = prop.convert_hass_to_dev(value)
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.debug(
                    "%s convert_hass_to_dev failed for %s: %s",
                    self.controller.log_prefix,
                    getattr(prop, "id", "unknown"),
                    e,
                    exc_info=True,
                )

        # If property has a connection_template (e.g. good_sleep formatting 'Sleep_{{ value | int }}'),
        # evaluate the template so optimistic predictions mirror the real wire protocol representation.
        conn_tmpl = getattr(prop, "connection_template", None)
        if conn_tmpl is not None:
            try:
                rendered = render_template(
                    conn_tmpl, value=value, device_state=device_state
                )
                parsed = (
                    rendered
                    if isinstance(rendered, dict)
                    else (
                        json_loads(rendered)
                        if rendered and isinstance(rendered, str)
                        else None
                    )
                )
                payload = (
                    parsed.get("json", parsed) if isinstance(parsed, dict) else parsed
                )
                if (
                    isinstance(payload, dict)
                    and "options" in payload
                    and isinstance(payload["options"], list)
                ):
                    if payload["options"] and isinstance(payload["options"][0], str):
                        dev_val = payload["options"][0]
            except (ValueError, TypeError, KeyError):
                pass

        state_node = self._get_state_node_from_prop(prop)
        if state_node and isinstance(state_node, str):
            target_nodes = [device_state]
            if (
                not state_node.startswith("Devices")
                and "Devices" in device_state
                and isinstance(device_state["Devices"], list)
                and len(device_state["Devices"]) > 0
                and isinstance(device_state["Devices"][0], dict)
            ):
                target_nodes.append(device_state["Devices"][0])
            for node in target_nodes:
                self._set_dict_value_by_path(node, state_node, dev_val)

        # Delegate purely to the property object's interface for any cascading relationships defined by YAML metadata
        if hasattr(prop, "apply_optimistic_cascades"):
            try:
                prop.apply_optimistic_cascades(device_state, value, dev_val)
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.debug(
                    "%s [Prop %s] apply_optimistic_cascades failed: %s",
                    self.controller.log_prefix,
                    getattr(prop, "id", "unknown"),
                    e,
                )
        elif hasattr(prop, "set_device_state_for_values"):
            try:
                prop.set_device_state_for_values(device_state)
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.debug(
                    "%s set_device_state_for_values failed for %s: %s",
                    self.controller.log_prefix,
                    getattr(prop, "id", "unknown"),
                    e,
                    exc_info=True,
                )

    def _find_device_node(self, raw_state: dict[str, Any]) -> dict[str, Any] | None:
        """Locate the target device dictionary in the raw network payload."""
        if not isinstance(raw_state, dict):
            return None

        # 1. Retrieve cached YAML structure for this device (fallback to 'XXXX')
        cache = getattr(self.controller.loader, "_parsed_yaml_cache", {})
        if not isinstance(cache, dict):
            return raw_state

        cache_key = getattr(self.controller, "device_id", "XXXX")
        dev_cfg = cache.get(cache_key)
        if not isinstance(dev_cfg, dict):  # pragma: no mutate
            dev_cfg = {}
        device_section = dev_cfg.get(CONFIG_DEVICE)
        if not isinstance(device_section, dict):
            device_section = {}
        identifiers = device_section.get("identifiers")
        if not isinstance(identifiers, dict):
            identifiers = {}

        path_to_devices = (
            identifiers.get("path_to_devices")
            if isinstance(identifiers, dict)
            else None
        )
        id_path = identifiers.get("id") if isinstance(identifiers, dict) else None

        # 2. Extract devices list using get_value_by_path
        devices_list = get_value_by_path(raw_state, path_to_devices)
        if not isinstance(devices_list, list) or len(devices_list) == 0:
            return raw_state

        # 3. Match target device ID (strictly evaluating default fallback to "")
        target_id = str(getattr(self.controller, "device_id", ""))

        matched_device = None
        for dev in devices_list:
            if isinstance(dev, dict):
                curr_id = get_value_by_path(dev, id_path)
                if curr_id is not None and str(curr_id) == target_id:
                    matched_device = dev
                    break

        # Fallback to the matched device, or the first item if no exact match found
        return (
            matched_device
            if matched_device is not None
            else (devices_list[0] if isinstance(devices_list[0], dict) else raw_state)
        )

    def _extract_device_nodes(
        self, full_device_state: dict[str, Any], pure_network_state: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Extract the relevant device nodes based on YAML cache id_map."""
        device_to_process = full_device_state
        pure_device_to_process = pure_network_state
        try:
            found_device = self._find_device_node(full_device_state)
            if isinstance(found_device, dict):
                device_to_process = found_device

            found_pure_device = self._find_device_node(pure_network_state)
            if isinstance(found_pure_device, dict):
                pure_device_to_process = found_pure_device

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.debug(
                "%s [Forensic] Failed to extract device node: %s",
                self.controller.log_prefix,
                e,
            )
            device_to_process = full_device_state
            pure_device_to_process = pure_network_state

        return device_to_process, pure_device_to_process

    def _apply_anti_flicker_locks(
        self,
        all_properties: list[YamlPropertyProtocol | Any],
        device_to_process: dict[str, Any],
        pure_device_to_process: dict[str, Any],
        is_prediction: bool,
        changed_keys: set[str] | None,
    ) -> None:
        """Apply anti-flicker pending updates shielding UI from stale network data."""
        # ------------------- ANTI-FLICKER ENGINE (SHADOW STATE) -------------------
        # MUST RUN FIRST to inject optimistic locks into device_to_process BEFORE parsing properties

        # Check for global evictions driven dynamically by property object metadata
        if changed_keys is not None:
            for op in all_properties:
                if hasattr(op, "should_evict_all_locks"):
                    try:
                        if op.should_evict_all_locks(
                            pure_device_to_process, changed_keys
                        ):
                            self._pending_updates.clear()
                            return
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        _LOGGER.debug(
                            "%s Error evaluating global eviction for %s: %s",
                            self.controller.log_prefix,
                            getattr(op, "id", "unknown"),
                            e,
                            exc_info=True,
                        )

        now = time.monotonic()

        props_by_id = {}
        for op in all_properties:
            op_id = getattr(op, "id", "")
            if op_id:
                props_by_id[op_id] = op
                hass_attr = self._get_hass_attr_for_op_id(op_id)
                if hass_attr != op_id:
                    props_by_id[hass_attr] = op

        for prop_id, (pend_val, ts) in list(self._pending_updates.items()):
            # Extended TTL of 45s to process all AC queues without flickering
            if now - ts > self.LOCK_TTL_SEC:  # pragma: no mutate
                del self._pending_updates[prop_id]
                _LOGGER.debug(
                    "%s [Forensic] Lock expired for %s",
                    self.controller.log_prefix,
                    prop_id,
                )
                continue

            op = props_by_id.get(prop_id)
            if op:
                op_id = getattr(op, "id", "")

                pure_val = None
                if hasattr(op, "calculate_value_from_state") and pure_device_to_process:
                    try:
                        # Evaluate lock AGAINST PURE NETWORK STATE
                        pure_val = op.calculate_value_from_state(pure_device_to_process)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        _LOGGER.debug(
                            "%s calculate_value_from_state failed for %s: %s",
                            self.controller.log_prefix,
                            prop_id,
                            e,
                            exc_info=True,
                        )

                # If REAL physical state matches UI, remove shield
                can_release = True
                state_node = self._get_state_node_from_prop(op)
                device_key = (
                    state_node.split(".")[0] if state_node else None
                )  # pragma: no mutate

                lock_age = now - ts
                if lock_age < self.LOCK_SHIELD_SEC:
                    # Temporal Shield: Prevent immediate premature release on fast echo before physical AC reacts
                    can_release = False
                elif changed_keys is not None and device_key and device_key not in changed_keys:
                    # Push update was for another property (e.g. Wind or Power), NOT for this property!
                    # Keep shield active until THIS property's device_key arrives in push update or poll.
                    can_release = False

                _LOGGER.debug(
                    "%s [Forensic-Verbose] Eval %s: pend_val=%s, pure_val=%s, changed_keys=%s, device_key=%s, can_release=%s",
                    self.controller.log_prefix,
                    prop_id,
                    pend_val,
                    pure_val,
                    changed_keys,
                    device_key,
                    can_release,
                )

                # Race Condition Fix: We DO NOT use hardware_override to blindly drop locks when the device_key arrives.
                # If the user clicks rapidly, the AC will push delayed states from OLD commands.
                # If we blindly drop our NEW prediction just because a push update arrived, the UI will flicker back to the old state.
                # We MUST enforce the lock until the AC pushes a value that MATCHES our prediction, OR 15s expires.

                if (
                    not is_prediction
                    and can_release
                    and pure_val is not None
                    and (
                        self._values_match(pure_val, pend_val)
                        or changed_keys is not None
                        or lock_age
                        > self.LOCK_PHYSICAL_TIMEOUT_SEC  # pragma: no mutate
                    )
                ):
                    _LOGGER.debug(
                        "%s [Forensic] Lock released for %s. Match=%s, Age=%.1f",
                        self.controller.log_prefix,
                        prop_id,
                        self._values_match(pure_val, pend_val),
                        lock_age,
                    )
                    del self._pending_updates[prop_id]
                else:
                    _LOGGER.debug(
                        "%s [Forensic] Lock enforced for %s.",
                        self.controller.log_prefix,
                        prop_id,
                    )
                    # Force UI to stay in expected state and update local variable
                    self._set_prop_value(op, pend_val)

                    self._inject_value_into_state(op, device_to_process, pend_val)

    def _predict_dependency_cascades(
        self, device_to_process: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply cascade logic to correct properties that become invalid (e.g. Fan mode when switching to Dry)."""
        corrections: dict[str, Any] = {}
        for _, op in list(self.controller.loader.operations.items()):
            if hasattr(op, "set_device_state_for_values"):
                op.set_device_state_for_values(device_to_process)

            if hasattr(op, "is_valid") and not op.is_valid(device_to_process):
                continue

            op_value = self._get_prop_value(op)

            op_values = None
            if hasattr(op, "get_valid_values"):
                op_values = op.get_valid_values(device_to_process)
            elif hasattr(op, "values"):
                op_values = (
                    list(op.values.keys()) if isinstance(op.values, dict) else op.values
                )

            if op_values and op_value is not None and op_value != STATE_UNKNOWN:
                if op_value not in op_values:
                    # Injected predictive correction
                    new_value = op_values[0] if op_values else STATE_UNKNOWN
                    _LOGGER.debug(
                        "%s [Forensic] Predictive correction for %s: %s -> %s",
                        self.controller.log_prefix,
                        op.id,
                        op_value,
                        new_value,
                    )
                    self._set_prop_value(op, new_value)
                    corrections[op.id] = new_value
                    self._inject_value_into_state(op, device_to_process, new_value)

        return corrections

    async def async_update_properties_from_state(
        self,
        full_device_state: dict[str, Any] | None = None,
        is_prediction: bool = False,
        force_update: bool = False,
        changed_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """Update individual entity properties shielding from stale polls via pending locks."""
        if not self.controller.loader.is_fully_initialized:
            return {}

        if is_prediction:
            _LOGGER.debug(
                "%s [Forensic] Prediction started. pending_updates=%s",
                self.controller.log_prefix,
                self._pending_updates,
            )

        if full_device_state is None:
            st_getter = self.controller.loader.state_getter
            if st_getter and st_getter.value:
                full_device_state = st_getter.value
            else:
                return {}

        pure_device_to_process = getattr(self, "_pure_network_state", {})
        device_to_process, pure_device_to_process = self._extract_device_nodes(
            full_device_state, pure_device_to_process
        )

        if not is_prediction:
            if (
                not force_update
                and not self._pending_updates
                and getattr(self, "_last_device_state", None) == device_to_process
            ):
                return {}

            self._last_device_state = (
                dict(device_to_process)
                if isinstance(device_to_process, dict)
                else device_to_process
            )

        all_properties = (
            list(self.controller.loader.operations.values())
            + list(self.controller.loader.properties.values())
            + list(self.controller.loader.sensors.values())
        )

        self._apply_anti_flicker_locks(
            all_properties,
            device_to_process,
            pure_device_to_process,
            is_prediction,
            changed_keys,
        )

        for prop in all_properties:
            # 1. Parse from state
            if hasattr(prop, "async_update_state"):
                try:
                    await prop.async_update_state(
                        device_to_process, getattr(self.controller, "debug", False)
                    )
                except Exception as e:
                    _LOGGER.debug(
                        "%s async_update_state on property failed: %s",
                        self.controller.log_prefix,
                        e,
                    )

            # 2. Re-enforce active anti-flicker locks on property values after parsing
            op_id = getattr(prop, "id", "")
            hass_attr = self._get_hass_attr_for_op_id(op_id)

            lock_val = None
            if op_id in self._pending_updates:
                lock_val = self._pending_updates[op_id][0]
            elif hass_attr in self._pending_updates:
                lock_val = self._pending_updates[hass_attr][0]

            if lock_val is not None:
                self._set_prop_value(prop, lock_val)

            # 3. BACKUP NATIVE INJECTION (Ensures memory consistency for HA)
            val = self._get_prop_value(prop)
            if val is not None:
                self._inject_value_into_state(prop, device_to_process, val)

        corrections = self._predict_dependency_cascades(device_to_process)

        self._rebuild_attributes()

        if is_prediction:
            _LOGGER.debug(
                "%s [Forensic] Prediction ended. Corrections=%s",
                self.controller.log_prefix,
                corrections,
            )

        return corrections

    def _rebuild_attributes(self) -> None:
        """Rebuild the flattened state attributes dictionary."""
        new_attrs = {ATTR_NAME: getattr(self.controller, "name", "Unknown")}
        all_properties = list(self.controller.loader.operations.values()) + list(
            self.controller.loader.properties.values()
        )
        for prop in all_properties:
            if hasattr(prop, "state_attributes"):
                new_attrs.update(prop.state_attributes)
        new_attrs["last_sync"] = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")

        self.controller.update_state_attributes(new_attrs)

    def _get_hass_attr_for_op_id(self, op_id: str) -> str:
        """Map YAML operation IDs to HA Attributes for validation mapping."""
        return self.HASS_ATTR_MAP.get(op_id, op_id)

    async def async_merge_device_state(self, new_data: dict[str, Any]) -> bool:
        """Merge a partial state update (e.g. from a push notification) into the known state."""
        if not new_data:
            return False

        st_getter = getattr(self.controller.loader, "state_getter", None)
        if not st_getter:
            return False

        if getattr(self, "_pure_network_state", None) is None:
            self._pure_network_state = {}  # pragma: no mutate

        if not self._pure_network_state:
            if st_getter.value:
                self._pure_network_state = (
                    dict(st_getter.value)
                    if isinstance(st_getter.value, dict)
                    else st_getter.value
                )  # pragma: no mutate
            else:
                return False

        # Ingest clean frame into immaculate network dictionary
        self._pure_network_state.update(new_data)

        # Clone pure network base before Anti-Flicker engine poisons it for UX
        candidate_state = (
            dict(self._pure_network_state)
            if isinstance(self._pure_network_state, dict)
            else self._pure_network_state
        )

        self._set_prop_value(st_getter, candidate_state)

        await self.async_update_properties_from_state(
            candidate_state, force_update=True, changed_keys=set(new_data.keys())
        )

        return True

    async def async_predict_and_correct_state(
        self,
        current_hass_state: ClimateIPDeviceState,
        property_name: str,
        new_value: Any,
    ) -> tuple[ClimateEntityFeature, dict[str, Any]]:
        """Predict the expected state after command natively bypassing abstraction leaks."""
        # 💥 CASCADE SHIELD: Register main command BEFORE predicting!
        _LOGGER.debug(
            "%s [Forensic] async_predict_and_correct_state started for %s=%s",
            self.controller.log_prefix,
            property_name,
            new_value,
        )
        self.register_pending_update(property_name, new_value)

        if (
            not self.controller.loader.state_getter
            or not self.controller.loader.is_fully_initialized
        ):
            return ClimateEntityFeature(0), {}

        st_getter = self.controller.loader.state_getter
        if not st_getter.value or not isinstance(
            st_getter.value, dict
        ):  # pragma: no mutate
            return ClimateEntityFeature(0), {}

        corrections: dict[str, Any] = {}

        prop_to_change = None  # pragma: no mutate
        for op in self.controller.loader.operations.values():
            op_id = getattr(op, "id", "")  # pragma: no mutate
            if (
                op_id == property_name
                or self._get_hass_attr_for_op_id(op_id) == property_name
            ):  # pragma: no mutate
                prop_to_change = op
                break

        if not prop_to_change:
            return ClimateEntityFeature(0), {}

        if (
            new_value is not None
            and hasattr(new_value, "value")
            and not isinstance(new_value, dict)
        ):  # pragma: no mutate
            new_value = new_value.value

        self._set_prop_value(prop_to_change, new_value)

        self._inject_value_into_state(
            prop_to_change, st_getter.value, new_value
        )  # pragma: no mutate

        # Predictive re-evaluation on memory (is_prediction flag prevents early shield removal)
        update_result = await self.async_update_properties_from_state(
            st_getter.value, is_prediction=True
        )

        # 💥 SILENT CASCADES: Lock the predicted UI state, but DO NOT send to the AC
        for k, v in update_result.items():
            if k not in corrections and k != property_name:  # pragma: no mutate
                if k not in self._pending_updates:
                    self.register_pending_update(k, v)

        # 💥 CASCADE SHIELD: Do NOT register predictive corrections as hard locks.
        # This allows dynamic predictions (like fan=auto in Dry mode) to automatically revert
        # to their physical state (fan=medium) if the user swipes quickly to a mode like Cool.
        return ClimateEntityFeature(0), corrections

    async def async_shutdown(self) -> None:
        """Shut down the poller and cleanly close any active connections."""
        conn = self.controller.loader.connection
        if conn:

            async def _try(coro: Any) -> None:  # pylint: disable=invalid-name
                try:
                    await coro
                except Exception as e:  # pylint: disable=broad-exception-caught
                    _LOGGER.debug(
                        "%s Failed cleanup task: %s",
                        self.controller.log_prefix,
                        e,
                        exc_info=True,
                    )

            if hasattr(conn, "stop_listening"):
                await _try(conn.stop_listening())

            if hasattr(conn, "close"):
                await _try(conn.close())

            self.controller.loader.connection = None

        await asyncio.sleep(1.0)

    @property
    def last_device_state(self) -> dict[str, Any] | None:
        """Return the last known parsed device state."""
        return self._last_device_state

    @property
    def device_state(self) -> dict[str, Any]:
        """Return the current device state (public interface over _last_device_state)."""
        return self._last_device_state or {}

    @property
    def pure_network_state(self) -> dict[str, Any]:
        """Return the pure network state, handling vendor-specific payload normalisation.

        The Samsung 'Devices' unwrap is intentionally moved here from the controller
        facade — payload normalisation belongs to the network/poller layer (OCP).
        """
        st: Any = getattr(self, "_pure_network_state", None)
        if not isinstance(st, dict) or not st:
            return {}
        devices = st.get("Devices")
        if (
            isinstance(devices, list)
            and len(devices) > 0
            and isinstance(devices[0], dict)
        ):
            return devices[0]
        return dict(st)

    def get_hass_attr_for_op_id(self, op_id: str) -> str:
        """Public interface: map a YAML operation ID to its HA attribute name."""
        return self._get_hass_attr_for_op_id(op_id)
