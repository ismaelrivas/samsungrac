# pylint: disable=import-outside-toplevel,line-too-long,protected-access,too-many-branches,too-many-instance-attributes,too-many-lines,too-many-locals,too-many-nested-blocks,too-many-statements
"""State management and polling for YAML-configured climate controllers."""

import asyncio
import copy
import logging
import time
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_FAN_MODE,
    ATTR_SWING_MODE,
    ATTR_PRESET_MODE,
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
from requests.exceptions import RequestException  # type: ignore[import-untyped]

from .const import (
    CONF_DEVICE_TYPE,
    CONFIG_DEVICE,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
)
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .helpers import async_check_network_reachability, get_value_by_path
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)


class YamlStatePoller:
    """Class responsible for polling the device and managing state."""

    SEMANTIC_DEVICE_KEY_MAP = {
        "hvac": "AC_FUN_OPMODE",
        "hvac_mode": "AC_FUN_OPMODE",
        ATTR_HVAC_MODE: "AC_FUN_OPMODE",
        "temperature": "AC_FUN_TEMPSET",
        "target_temperature": "AC_FUN_TEMPSET",
        ATTR_TEMPERATURE: "AC_FUN_TEMPSET",
        "fan": "AC_FUN_WINDLEVEL",
        "fan_mode": "AC_FUN_WINDLEVEL",
        ATTR_FAN_MODE: "AC_FUN_WINDLEVEL",
        "swing": "AC_FUN_DIRECTION",
        "swing_mode": "AC_FUN_DIRECTION",
        ATTR_SWING_MODE: "AC_FUN_DIRECTION",
        "preset": "AC_FUN_COMODE",
        "preset_mode": "AC_FUN_COMODE",
        ATTR_PRESET_MODE: "AC_FUN_COMODE",
    }

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
    def _set_prop_value(prop: Any, value: Any) -> None:
        """Safely set a value on a property object regardless of duck-typing interface."""
        if hasattr(prop, "value"):
            prop.value = value
        elif hasattr(prop, "_value"):
            prop._value = value

    @staticmethod
    def _get_prop_value(prop: Any) -> Any:
        """Safely get a value from a property object regardless of duck-typing interface."""
        return getattr(prop, "value", getattr(prop, "_value", None))

    def __init__(self, controller: Any) -> None:
        """Initialize the poller with a reference to the main controller facade."""
        self.controller = controller

        self._cached_device_state: dict[str, Any] | None = None
        self._last_state_fetch_time: float = 0.0
        self._last_device_state: dict[str, Any] | None = None
        self._consecutive_connection_errors: int = 0
        
        # 💥 ISOLATED PURE STATE: Stores network truth without UI pollution
        self._pure_network_state: dict[str, Any] = {}
        
        # Shield Engine (Optimistic Locks)
        self._pending_updates: dict[str, tuple[Any, float]] = {}
        self._prop_template_key_cache: dict[str, str | None] = {}

        self.fan_modes_list_changed_pending_flicker: bool = False

    def register_pending_update(self, property_id: str, value: Any) -> None:
        """Register a pending update to shield the UI from stale network polling echoes."""
        self._pending_updates[property_id] = (value, time.time())

    async def _refresh_smartthings_token(self) -> str | None:
        """Attempt to refresh an expired SmartThings token using the official HA integration."""
        try:
            if not getattr(self.controller, "hass", None):
                return None

            entries = self.controller.hass.config_entries.async_entries("smartthings")
            if not entries:
                _LOGGER.debug(  # pragma: no mutate
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
            _LOGGER.debug(  # pragma: no mutate
                "%s [Auth] OAuth2 session token validated. Token: %s",
                self.controller.log_prefix,
                masked,
            )
            return token
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(  # pragma: no mutate
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
            device_name = config_name if config_name else f"Samsung AC {self._device_identifier}"
            async_create_issue(
                self.controller.hass,
                "climate_ip",
                f"device_offline_{safe_device_id}",
                is_fixable=False,
                is_persistent=False,
                severity=IssueSeverity.WARNING,
                translation_key="connection_failed",
                translation_placeholders={
                    "name": "device_name",
                    "device_name": device_name,
                    "host": self.controller.ip_address or self.controller.host or "Unknown",
                    "ip_address": self.controller.ip_address or self.controller.host or "Unknown",
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
            _LOGGER.debug("%s Failed to create repair issue: %s", self.controller.log_prefix, e)

    def _update_all_connections_token(self, new_token: str) -> None:
        """Propagate the new token to all active connection engines."""
        updated_connections: set = set()
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
        now_ts = time.time()
        if self._cached_device_state and (now_ts - self._last_state_fetch_time < 2.0):
            st_getter = self.controller.loader.state_getter
            if st_getter and st_getter.value:
                # Return RAM state injected with locks to lock the UI without flickering
                return copy.deepcopy(st_getter.value)
            return self._cached_device_state.copy()

        device_state = await self.async_update_state()
        return copy.deepcopy(device_state) if device_state else None

    async def async_update_state(self) -> dict[str, Any] | None:
        """Fetch the actual state from the device over the network."""
        if not self.controller.loader.state_getter:
            raise UpdateFailed("State getter is not initialized, cannot update state.")

        if self.controller.config.get(
            CONF_DEVICE_TYPE
        ) != DEVICE_TYPE_SAMSUNG_2878 and getattr(self.controller, "ip_address", None):
            try:
                network_reachable = await async_check_network_reachability(
                    self.controller.ip_address, self.controller.log_prefix
                )
                if not network_reachable:
                    self._consecutive_connection_errors += 1
                    if self._consecutive_connection_errors == 3:
                        self._try_create_repair_issue()
                    if self._consecutive_connection_errors >= 2:
                        raise CannotConnect(
                            "Host unreachable (ICMP ping failed). Device is persistently offline."
                        )
                    raise CannotConnect("Host unreachable (ICMP ping failed).")
            except Exception as diag_err:  # pylint: disable=broad-exception-caught
                if isinstance(diag_err, CannotConnect):
                    raise

        try:
            full_device_state = (
                await self.controller.loader.state_getter.async_update_state(
                    None, getattr(self.controller, "debug", False)
                )
            )

            if self._consecutive_connection_errors > 0:
                self._consecutive_connection_errors = 0
                if getattr(self.controller, "hass", None):
                    try:
                        safe_device_id = self._device_identifier.replace(".", "_").replace(" ", "_")
                        async_delete_issue(
                            self.controller.hass,
                            "climate_ip",
                            f"device_offline_{safe_device_id}",
                        )
                    except Exception as e:
                        _LOGGER.debug("%s Failed to delete repair issue: %s", self.controller.log_prefix, e)

        except AuthError as exc:
            new_token = await self._refresh_smartthings_token()
            if new_token and new_token != self.controller.token:
                if hasattr(self.controller, "token"):
                    self.controller.token = new_token
                self._update_all_connections_token(new_token)

                if hasattr(self.controller, "on_token_refreshed") and self.controller.on_token_refreshed:
                    self.controller.on_token_refreshed(new_token)

                try:
                    full_device_state = (
                        await self.controller.loader.state_getter.async_update_state(
                            None, self.controller.debug
                        )
                    )
                    self._consecutive_connection_errors = 0
                except Exception as retry_exc:
                    raise UpdateFailed(f"Retry after token refresh failed: {retry_exc}") from retry_exc
            else:
                raise ConfigEntryAuthFailed("Authentication failed. Please check tokens.") from exc

        except InvalidHeaderError:
            raise

        except (RequestException, CannotConnect) as e:
            if "persistently offline" in str(e):
                self._consecutive_connection_errors = 2
            else:
                self._consecutive_connection_errors += 1

            if (
                getattr(self.controller, "available", True)
                and self._consecutive_connection_errors <= 2
                and self._cached_device_state is not None
            ):
                return self._cached_device_state

            if self._consecutive_connection_errors == 3:
                self._try_create_repair_issue()

            reason = str(e).split(":")[-1].strip()
            raise UpdateFailed(f"Device unreachable: {reason}") from e

        if full_device_state is None:
            if getattr(self.controller, "available", True) and self._cached_device_state:
                return self._cached_device_state
            raise UpdateFailed("Failed to get device state: No data received and no cache available")

        self._cached_device_state = full_device_state
        self._last_state_fetch_time = time.time()
        
        # 💥 NETWORK TRUTH STORAGE: Isolated from UI pollution
        self._pure_network_state = copy.deepcopy(full_device_state)

        if not self.controller.loader.is_fully_initialized:
            try:
                device_type = self.controller.config.get(CONF_DEVICE_TYPE)
                cache = self.controller.loader._parsed_yaml_cache
                id_map = (
                    cache.get(getattr(self.controller, "device_id", "XXXX"), {})
                    .get(CONFIG_DEVICE, {})
                    .get("identifiers")
                )

                if id_map:
                    self.controller.discovered_devices = get_value_by_path(
                        full_device_state, id_map.get("path_to_devices", [])
                    )

                    if self.controller.discovered_devices:
                        device_to_discover = None

                        if device_type == DEVICE_TYPE_MIM_H03:
                            device_to_discover = next(
                                (d for d in self.controller.discovered_devices if d and d.get("id") != "0" and "Mode" in d),
                                None,
                            )
                        else:
                            device_to_discover = self.controller.discovered_devices[0]

                        if device_to_discover:
                            id_path = id_map.get("id")
                            discovered_id = (
                                get_value_by_path(device_to_discover, id_path) if id_path else None
                            )
                            curr_dev_id = getattr(self.controller, "device_id", "")
                            if discovered_id is not None and (not curr_dev_id or curr_dev_id == "0"):
                                if hasattr(self.controller, "device_id"):
                                    self.controller.device_id = str(discovered_id)

                await self.controller.loader.async_finish_initialization()

            except Exception as e:
                _LOGGER.exception("%s Error during initial device discovery: %s", self.controller.log_prefix, e)

        await self.async_update_properties_from_state(full_device_state)
        return self.controller.loader.state_getter.value

    @staticmethod
    def _values_match(val1: Any, val2: Any) -> bool:
        """Check if two values match numerically (float cast) or string-wise (case-insensitive)."""
        if val1 is None or val2 is None:
            return val1 == val2
        if hasattr(val1, "value") and not isinstance(val1, dict): val1 = val1.value
        if hasattr(val2, "value") and not isinstance(val2, dict): val2 = val2.value
        try:
            return float(val1) == float(val2)
        except (ValueError, TypeError):
            return str(val1).strip().lower() == str(val2).strip().lower()

    def _get_device_key_from_template(self, template_obj: Any) -> str | None:
        """Extract the JSON key from a Jinja template string natively ($O(N)$ string slicing)."""
        if not template_obj:
            return None

        template_string = (
            template_obj.template
            if hasattr(template_obj, "template")
            else str(template_obj)
        )
        if not template_string:
            return None

        def _extract_key(text: str) -> str:
            for i, char in enumerate(text):
                if not (char.isalnum() or char == "_"):
                    return text[:i]
            return text

        if "device_state." in template_string:
            parts = template_string.split("device_state.", 1)[1]
            key = _extract_key(parts)
            return key if key else None

        if "device_state[" in template_string:
            parts = template_string.split("device_state[", 1)[1]
            if parts and parts[0] in ("'", '"'):
                parts = parts[1:]
            key = _extract_key(parts)
            return key if key else None

        return None

    def _get_cached_device_key_from_prop(self, prop: Any) -> str | None:
        """Extract and cache the raw JSON key mapped to a specific property from its template."""
        prop_id = getattr(prop, "id", None)
        if not prop_id:
            return None

        if prop_id in self._prop_template_key_cache:
            return self._prop_template_key_cache[prop_id]

        status_tmpl = getattr(prop, "status_template", None)
        key = self._get_device_key_from_template(status_tmpl)
        self._prop_template_key_cache[prop_id] = key
        return key

    def _inject_8888_api_structures(self, device_state: dict[str, Any], op_id: str, dev_val: Any) -> None:
        """Universal 8888 REST API direct structure injection for core HVAC operations."""
        if not isinstance(device_state, dict):
            return
            
        hass_attr = self._get_hass_attr_for_op_id(op_id)
        if hass_attr in ("hvac_mode", "hvac") and "Mode" in device_state and isinstance(device_state["Mode"], dict):
            modes = device_state["Mode"].get("modes")
            if isinstance(modes, list) and len(modes) > 0:
                modes[0] = str(dev_val)
        elif hass_attr in ("target_temperature", "temperature") and "Temperatures" in device_state and isinstance(device_state["Temperatures"], list):
            if len(device_state["Temperatures"]) > 0 and isinstance(device_state["Temperatures"][0], dict):
                try:
                    device_state["Temperatures"][0]["desired"] = float(dev_val)
                except (ValueError, TypeError):
                    pass
        elif hass_attr in ("fan_mode", "fan") and "Wind" in device_state and isinstance(device_state["Wind"], dict):
            device_state["Wind"]["speedLevel"] = dev_val
        elif hass_attr in ("preset_mode", "preset") and "Mode" in device_state and isinstance(device_state["Mode"], dict):
            options = device_state["Mode"].get("options")
            if isinstance(options, list) and len(options) > 0:
                options[0] = str(dev_val)

    def _inject_value_into_state(self, prop: Any, device_state: dict, value: Any) -> None:
        """Safely inject an optimistic value into the raw device state bypassing stale network data."""
        if not isinstance(device_state, dict):
            return

        if hasattr(prop, "set_device_state_for_values"):
            try:
                # Deep paths for 8888
                prop.set_device_state_for_values(device_state)
            except Exception as e:
                _LOGGER.debug("%s set_device_state_for_values failed: %s", self.controller.log_prefix, e)
                
        op_id = getattr(prop, "id", "")
        
        # SEMANTIC SHIELDING (Memory Corruption Protection for Protocol 2878)
        device_key = None
        if op_id in self.SEMANTIC_DEVICE_KEY_MAP and self.SEMANTIC_DEVICE_KEY_MAP[op_id] in device_state:
            device_key = self.SEMANTIC_DEVICE_KEY_MAP[op_id]
            
        if not device_key:
            device_key = self._get_cached_device_key_from_prop(prop)
            
        if not device_key:
            return
            
        dev_val = value
        if hasattr(prop, "convert_hass_to_dev"):
            try:
                dev_val = prop.convert_hass_to_dev(value)
            except Exception as e:
                _LOGGER.debug("%s convert_hass_to_dev failed: %s", self.controller.log_prefix, e)
            
        if device_key and not isinstance(device_state.get(device_key), (dict, list)):
            device_state[device_key] = dev_val
        else:
            # Fallback for nested structures (e.g. 8888 API) using state_node
            state_node = getattr(prop, "state_node", None)
            if state_node and isinstance(state_node, str):
                parts = state_node.split(".")
                current = device_state
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        if isinstance(current, dict):
                            current[part] = dev_val
                        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                            current[int(part)] = dev_val
                    else:
                        if isinstance(current, dict):
                            current = current.get(part, {})
                        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                            current = current[int(part)]
                        else:
                            break

        # 8888 REST API direct structure injection for core HVAC operations
        self._inject_8888_api_structures(device_state, op_id, dev_val)

        # Universal semantic hardcode for Power
        if op_id in ("hvac", "hvac_mode", ATTR_HVAC_MODE):
            power_op = self.controller.loader.operations.get("power") or self.controller.loader.properties.get("power")
            power_key = None
            if power_op:
                power_key = self._get_cached_device_key_from_prop(power_op)
            if not power_key and "AC_FUN_POWER" in device_state:
                power_key = "AC_FUN_POWER"
                
            if power_key and power_key in device_state:
                is_off = (str(value).lower() == "off" or str(dev_val).lower() == "off")
                if isinstance(device_state[power_key], dict) and "power" in device_state[power_key]:
                    device_state[power_key]["power"] = "Off" if is_off else "On"
                elif not isinstance(device_state[power_key], (dict, list)):
                    device_state[power_key] = "Off" if is_off else "On"

    def _find_device_node(self, state_dict: dict[str, Any], id_map: dict[str, Any]) -> dict[str, Any] | None:
        """Find the matching device node in the state dictionary based on id_map."""
        devices_list = get_value_by_path(state_dict, id_map.get("path_to_devices", []))
        if not devices_list:
            return None
        
        target_id = str(getattr(self.controller, "device_id", ""))
        found = next(
            (
                d
                for d in devices_list
                if d and str(get_value_by_path(d, id_map.get("id", []))) == target_id
            ),
            None,
        )
        return found if found else devices_list[0]

    def _extract_device_nodes(self, full_device_state: dict[str, Any], pure_network_state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Extract the relevant device nodes based on YAML cache id_map."""
        device_to_process = full_device_state
        pure_device_to_process = pure_network_state
        try:
            cache = self.controller.loader._parsed_yaml_cache
            id_map = (
                cache.get(getattr(self.controller, "device_id", "XXXX"), {})
                .get(CONFIG_DEVICE, {})
                .get("identifiers")
            )
            if id_map:
                found_device = self._find_device_node(full_device_state, id_map)
                if found_device:
                    device_to_process = found_device

                found_pure_device = self._find_device_node(pure_network_state, id_map)
                if found_pure_device:
                    pure_device_to_process = found_pure_device

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.debug("%s [Forensic] Failed to extract device node: %s", self.controller.log_prefix, e)
            device_to_process = full_device_state
            pure_device_to_process = pure_network_state
            
        return device_to_process, pure_device_to_process

    def _apply_anti_flicker_locks(
        self,
        all_properties: list[Any],
        device_to_process: dict[str, Any],
        pure_device_to_process: dict[str, Any],
        is_prediction: bool,
        changed_keys: set[str] | None
    ) -> None:
        """Apply anti-flicker pending updates shielding UI from stale network data."""
        # ------------------- ANTI-FLICKER ENGINE (SHADOW STATE) -------------------
        # MUST RUN FIRST to inject optimistic locks into device_to_process BEFORE parsing properties
        now = time.time()
        
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
            if now - ts > 45.0:
                del self._pending_updates[prop_id]
                _LOGGER.debug("%s [Forensic] Lock expired for %s", self.controller.log_prefix, prop_id) # pragma: no mutate
                continue
                
            op = props_by_id.get(prop_id)
            if op:
                op_id = getattr(op, "id", "")
                
                pure_val = None
                if hasattr(op, "calculate_value_from_state") and pure_device_to_process:
                    try:
                        # 💥 THE MAGIC HAPPENS HERE: Evaluate lock AGAINST PURE NETWORK STATE
                        pure_val = op.calculate_value_from_state(pure_device_to_process)
                    except Exception as e:
                        _LOGGER.debug("%s calculate_value_from_state failed: %s", self.controller.log_prefix, e)
                        
                # If REAL physical state matches UI, remove shield
                can_release = True
                device_key = self._get_cached_device_key_from_prop(op)
                if not device_key and op_id in self.SEMANTIC_DEVICE_KEY_MAP:
                    mapped_key = self.SEMANTIC_DEVICE_KEY_MAP[op_id]
                    if pure_device_to_process and mapped_key in pure_device_to_process:
                        device_key = mapped_key
                    elif device_to_process and mapped_key in device_to_process:
                        device_key = mapped_key

                lock_age = now - ts
                if lock_age < 3.0:
                    # Temporal Shield: Prevent immediate premature release on fast echo before physical AC reacts
                    can_release = False
                elif changed_keys is not None:
                    if device_key and device_key not in changed_keys:
                        # Push update was for another property (e.g. Wind or Power), NOT for this property!
                        # Keep shield active until THIS property's device_key arrives in push update or poll.
                        can_release = False
                        
                _LOGGER.debug("%s [Forensic-Verbose] Eval %s: pend_val=%s, pure_val=%s, changed_keys=%s, device_key=%s, can_release=%s", self.controller.log_prefix, prop_id, pend_val, pure_val, changed_keys, device_key, can_release) # pragma: no mutate

                if not is_prediction and can_release and pure_val is not None and self._values_match(pure_val, pend_val):
                    _LOGGER.debug("%s [Forensic] Lock released for %s. Pure matches pend_val: %s", self.controller.log_prefix, prop_id, pend_val) # pragma: no mutate
                    del self._pending_updates[prop_id]
                else:
                    _LOGGER.debug("%s [Forensic] Lock enforced for %s. Injecting %s into state.", self.controller.log_prefix, prop_id, pend_val) # pragma: no mutate
                    # Force UI to stay in expected state and update local variable
                    self._set_prop_value(op, pend_val)
                        
                    self._inject_value_into_state(op, device_to_process, pend_val)

    def _predict_dependency_cascades(self, device_to_process: dict[str, Any]) -> dict[str, Any]:
        """Apply cascade logic to correct properties that become invalid (e.g. Fan mode when switching to Dry)."""
        corrections: dict[str, Any] = {}
        for _, op in list(self.controller.loader.operations.items()):
            if hasattr(op, "is_valid") and not op.is_valid(device_to_process):
                continue

            op_value = self._get_prop_value(op)
            
            op_values = None
            if hasattr(op, "get_valid_values"):
                op_values = op.get_valid_values(device_to_process)
            elif hasattr(op, "values"):
                op_values = list(op.values.keys()) if isinstance(op.values, dict) else op.values

            if op_values and op_value is not None and op_value != STATE_UNKNOWN:
                if op_value not in op_values:
                    # Injected predictive correction
                    new_value = op_values[0] if op_values else STATE_UNKNOWN
                    _LOGGER.debug("%s [Forensic] Predictive correction for %s: %s -> %s", self.controller.log_prefix, op.id, op_value, new_value) # pragma: no mutate
                    self._set_prop_value(op, new_value)
                    corrections[op.id] = new_value
                    self._inject_value_into_state(op, device_to_process, new_value)

                if (
                    getattr(op, "feature_flag", getattr(op, "_feature_flag", None))
                    == ClimateEntityFeature.FAN_MODE
                ):
                    self.fan_modes_list_changed_pending_flicker = True
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
            _LOGGER.debug("%s [Forensic] Prediction started. pending_updates=%s", self.controller.log_prefix, self._pending_updates) # pragma: no mutate

        if full_device_state is None:
            st_getter = self.controller.loader.state_getter
            if st_getter and st_getter.value:
                full_device_state = st_getter.value
            else:
                return {}

        pure_device_to_process = getattr(self, "_pure_network_state", {})
        device_to_process, pure_device_to_process = self._extract_device_nodes(full_device_state, pure_device_to_process)

        if not is_prediction:
            if (
                not force_update
                and not self._pending_updates
                and getattr(self, "_last_device_state", None) == device_to_process
            ):
                return {}

            self._last_device_state = copy.deepcopy(device_to_process)
            
        all_properties = (
            list(self.controller.loader.operations.values())
            + list(self.controller.loader.properties.values())
            + list(self.controller.loader.sensors.values())
        )

        self._apply_anti_flicker_locks(all_properties, device_to_process, pure_device_to_process, is_prediction, changed_keys)

        for prop in all_properties:
            # 1. Parse from state
            if hasattr(prop, "async_update_state"):
                try:
                    await prop.async_update_state(
                        device_to_process, getattr(self.controller, "debug", False)
                    )
                except Exception as e:
                    _LOGGER.debug("%s async_update_state on property failed: %s", self.controller.log_prefix, e)

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
        
        # 💥 ABSOLUTE SHIELD: Poison raw RAM with shielded copy
        st_getter = self.controller.loader.state_getter
        if st_getter and not is_prediction:
            self._set_prop_value(st_getter, device_to_process)

        if is_prediction:
            _LOGGER.debug("%s [Forensic] Prediction ended. Corrections=%s", self.controller.log_prefix, corrections) # pragma: no mutate
            
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

        if hasattr(self.controller, "update_state_attributes"):
            self.controller.update_state_attributes(new_attrs)
        elif hasattr(self.controller, "_attributes"):
            self.controller._attributes = new_attrs

    def _get_hass_attr_for_op_id(self, op_id: str) -> str:
        """Map YAML operation IDs to HA Attributes for validation mapping."""
        return self.HASS_ATTR_MAP.get(op_id, op_id)



    async def async_merge_device_state(
        self, new_data: dict[str, Any]
    ) -> bool:
        """Merge a partial state update (e.g. from a push notification) into the known state."""
        if not new_data:
            return False

        st_getter = self.controller.loader.state_getter
        if not st_getter:
            return False
            
        if getattr(self, "_pure_network_state", None) is None:
            self._pure_network_state = {}
            
        if not self._pure_network_state:
            if st_getter.value:
                self._pure_network_state = copy.deepcopy(st_getter.value)
            else:
                return False

        # Ingest clean frame into immaculate network dictionary
        self._pure_network_state.update(new_data)

        # Clone pure network base before Anti-Flicker engine poisons it for UX
        candidate_state = copy.deepcopy(self._pure_network_state)

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
        _LOGGER.debug("%s [Forensic] async_predict_and_correct_state started for %s=%s", self.controller.log_prefix, property_name, new_value) # pragma: no mutate
        self.register_pending_update(property_name, new_value)

        if (
            not self.controller.loader.state_getter
            or not self.controller.loader.is_fully_initialized
        ):
            return ClimateEntityFeature(0), {}

        st_getter = self.controller.loader.state_getter
        if not st_getter.value or not isinstance(st_getter.value, dict):
            return ClimateEntityFeature(0), {}

        corrections: dict[str, Any] = {}

        prop_to_change = None
        for op in self.controller.loader.operations.values():
            op_id = getattr(op, "id", "")
            if op_id == property_name or self._get_hass_attr_for_op_id(op_id) == property_name:
                prop_to_change = op
                break

        if not prop_to_change:
            return ClimateEntityFeature(0), {}

        if new_value is not None and hasattr(new_value, "value") and not isinstance(new_value, dict):
            new_value = new_value.value

        self._set_prop_value(prop_to_change, new_value)

        self._inject_value_into_state(prop_to_change, st_getter.value, new_value)

        # Predictive re-evaluation on memory (is_prediction flag prevents early shield removal)
        update_result = await self.async_update_properties_from_state(
            st_getter.value, is_prediction=True
        )
        corrections.update(update_result)

        # 💥 CASCADE SHIELD: Do NOT register predictive corrections as hard locks.
        # This allows dynamic predictions (like fan=auto in Dry mode) to automatically revert 
        # to their physical state (fan=medium) if the user swipes quickly to a mode like Cool.
        return ClimateEntityFeature(0), corrections

    async def async_shutdown(self) -> None:
        """Shut down the poller and cleanly close any active connections."""
        conn = self.controller.loader.connection
        if conn:
            async def _try(coro):  # pylint: disable=invalid-name
                try:
                    await coro
                except Exception as e:
                    _LOGGER.debug("%s Failed cleanup task: %s", self.controller.log_prefix, e)

            if hasattr(conn, "stop_listening"):
                await _try(conn.stop_listening())

            if hasattr(self.controller, "close_shared_client"):
                await _try(self.controller.close_shared_client())
            elif hasattr(self.controller, "_shared_raw_client"):
                raw_client = self.controller._shared_raw_client
                if raw_client and hasattr(raw_client, "close"):
                    await _try(raw_client.close())
                self.controller._shared_raw_client = None

            if hasattr(conn, "close"):
                await _try(conn.close())

            self.controller.loader.connection = None

        await asyncio.sleep(1.0)

    @property
    def last_device_state(self) -> dict[str, Any] | None:
        """Return the last known parsed device state."""
        return self._last_device_state