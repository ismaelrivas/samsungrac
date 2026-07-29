# pylint: disable=import-outside-toplevel,line-too-long,protected-access,too-many-branches,too-many-instance-attributes,too-many-lines,too-many-locals,too-many-nested-blocks,too-many-statements
"""State management and polling for YAML-configured climate controllers."""

import asyncio
import copy
import re

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
from .helpers import async_check_network_reachability, get_value_by_path, set_value_by_path
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)


class YamlStatePoller:
    """Class responsible for polling the device and managing state."""

    def __init__(self, controller: Any) -> None:
        """Initialize the poller with a reference to the main controller facade."""
        self.controller = controller

        self._cached_device_state: dict[str, Any] | None = None
        self._last_state_fetch_time: float = 0.0
        self._last_device_state: dict[str, Any] | None = None
        self._consecutive_connection_errors: int = 0
        self._pending_updates: dict[str, tuple[Any, float]] = {}

        self._prop_template_key_cache: dict[str, str | None] = {}
        self.fan_modes_list_changed_pending_flicker: bool = False

    def register_pending_update(self, property_id: str, value: Any) -> None:
        """Register a pending update for a property to override the fetched state temporarily."""
        self._pending_updates[property_id] = (value, time.time())

    async def _refresh_smartthings_token(self) -> str | None:
        """Attempt to refresh an expired SmartThings token using the official HA integration."""
        try:
            # Home Assistant dependency check
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

    def _try_create_repair_issue(self) -> None:
        """Create a HA repair issue for persistent device offline state."""
        if not self.controller.hass:
            return
        try:
            raw_id = (
                self.controller.unique_id
                or self.controller.host
                or self.controller.ip_address
                or "unknown"
            )
            safe_device_id = str(raw_id).replace(".", "_").replace(" ", "_")

            config_name = self.controller.config.get("name")

            hardware_id = (
                self.controller.unique_id
                or self.controller.host
                or self.controller.ip_address
                or "Unknown"
            )

            # 3. Final UX String
            device_name = config_name if config_name else f"Samsung AC {hardware_id}"
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
            _LOGGER.debug(  # pragma: no mutate
                "%s Failed to create repair issue: %s", self.controller.log_prefix, e
            )

    def _update_all_connections_token(self, new_token: str) -> None:
        """Propagate the new token to all active connection engines."""
        _LOGGER.debug(  # pragma: no mutate
            "%s [Auth] Propagating new token to all connections.",
            self.controller.log_prefix,
        )
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
        _LOGGER.debug(  # pragma: no mutate
            "%s [Auth] Updated token for %d unique connection objects.",
            self.controller.log_prefix,
            len(updated_connections),
        )

    def _mask_sensitive_data(self, data: Any) -> Any:
        """Recursively mask sensitive identifiers from data payloads."""
        if isinstance(data, dict):
            masked = data.copy()
            if (
                "uuid" in masked
                and isinstance(masked["uuid"], str)
                and len(masked["uuid"]) > 6
            ):
                masked["uuid"] = "***" + masked["uuid"][-6:]  # pragma: no mutate
            for key, value in masked.items():
                if isinstance(value, (dict, list)):
                    masked[key] = self._mask_sensitive_data(value)
            return masked
        if isinstance(data, list):
            return [self._mask_sensitive_data(item) for item in data]
        return data

    async def async_get_status(self) -> dict[str, Any] | None:
        """Fetch status using a short cache to prevent double-polling storms."""
        now_ts = time.time()
        if self._cached_device_state and (now_ts - self._last_state_fetch_time < 2.0):
            _LOGGER.debug(  # pragma: no mutate
                "%s [Cache] Returning cached device state (TTL < 2s) to prevent double polling.",
                self.controller.log_prefix,
            )
            return self._cached_device_state.copy()

        _LOGGER.debug(  # pragma: no mutate
            "%s Polling device for state. Connection ID: %s",
            self.controller.log_prefix,
            id(self.controller.loader.connection),
        )
        device_state = await self.async_update_state()
        return device_state.copy() if device_state else None

    async def async_update_state(self) -> dict[str, Any] | None:
        """Fetch the actual state from the device over the network."""
        if not self.controller.loader.state_getter:
            raise UpdateFailed(
                "State getter is not initialized, cannot update state."
            )  # pragma: no mutate

        # Pre-check network reachability for non-2878 devices (REST/8888)
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
                            "Host unreachable (ICMP ping failed). Device is persistently offline."  # pragma: no mutate
                        )
                    raise CannotConnect(
                        "Host unreachable (ICMP ping failed)."
                    )  # pragma: no mutate
            except Exception as diag_err:  # pylint: disable=broad-exception-caught
                if isinstance(diag_err, CannotConnect):
                    raise
                _LOGGER.debug(  # pragma: no mutate
                    "%s Network diagnostic failed: %s",
                    self.controller.log_prefix,
                    diag_err,
                )

        try:
            full_device_state = (
                await self.controller.loader.state_getter.async_update_state(
                    None, getattr(self.controller, "debug", False)
                )
            )

            if self._consecutive_connection_errors > 0:
                _LOGGER.info(  # pragma: no mutate
                    "%s Connection recovered after %d failure(s). Counter reset.",
                    self.controller.log_prefix,
                    self._consecutive_connection_errors,
                )
                self._consecutive_connection_errors = 0
                if getattr(self.controller, "hass", None):
                    try:
                        raw_id = (
                            self.controller.unique_id
                            or self.controller.host
                            or self.controller.ip_address
                            or "unknown"
                        )
                        safe_device_id = str(raw_id).replace(".", "_").replace(" ", "_")
                        async_delete_issue(
                            self.controller.hass,
                            "climate_ip",
                            f"device_offline_{safe_device_id}",
                        )
                        _LOGGER.info(
                            "%s Cleared repair issue 'device_offline_%s'",
                            self.controller.log_prefix,
                            safe_device_id,
                        )
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        _LOGGER.debug(  # pragma: no mutate
                            "%s Failed to delete repair issue: %s",
                            self.controller.log_prefix,
                            e,
                        )

        except AuthError as exc:
            _LOGGER.info(  # pragma: no mutate
                "%s [Auth] Authentication failed (401). Refreshing token via OAuth2Session...",
                self.controller.log_prefix,
            )
            new_token = await self._refresh_smartthings_token()
            if new_token and new_token != self.controller.token:
                _LOGGER.info(  # pragma: no mutate
                    "%s [Auth] Automatically retrieved new Access Token from SmartThings integration.",
                    self.controller.log_prefix,
                )
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
                    self._consecutive_connection_errors = 0
                except Exception as retry_exc:  # pylint: disable=broad-exception-caught,bad-exception-cause
                    raise UpdateFailed(
                        f"Retry after token refresh failed: {retry_exc}"  # pragma: no mutate
                    ) from retry_exc
            else:
                _LOGGER.info(  # pragma: no mutate
                    "%s [Auth] Token refresh failed. SmartThings integration may not be installed.",
                    self.controller.log_prefix,
                )
                # pylint: disable=import-outside-toplevel,bad-exception-cause
                raise ConfigEntryAuthFailed(
                    "Authentication failed. Please install and configure the "  # pragma: no mutate
                    "official SmartThings integration to provide a valid token."  # pragma: no mutate
                ) from exc

        except InvalidHeaderError:
            _LOGGER.debug(  # pragma: no mutate
                "%s Malformed HTTP header detected, bubbling up to coordinator.",
                self.controller.log_prefix,
            )
            raise

        except (RequestException, CannotConnect) as e:
            if "persistently offline" in str(e):
                self._consecutive_connection_errors = 2
            else:
                self._consecutive_connection_errors += 1

            if (
                getattr(self.controller, "available", True)  # pragma: no mutate
                and self._consecutive_connection_errors <= 2  # pragma: no mutate
                and self._cached_device_state is not None
            ):  # pragma: no mutate
                _LOGGER.debug(
                    "%s Connection failed (%d/3). Using cached state to prevent unavailability. Error: %s",
                    self.controller.log_prefix,
                    self._consecutive_connection_errors,
                    e,
                )  # pragma: no mutate
                return self._cached_device_state

            if self._consecutive_connection_errors == 3:
                self._try_create_repair_issue()

            reason = str(e).split(":")[-1].strip()  # pragma: no mutate

            _LOGGER.debug(  # pragma: no mutate
                "%s Device unreachable (attempt %d). Marking as unavailable. Reason: %s",
                self.controller.log_prefix,
                self._consecutive_connection_errors,
                reason,
            )
            raise UpdateFailed(
                f"Device unreachable: {reason}"
            ) from e  # pragma: no mutate

        if full_device_state is None:
            if getattr(self.controller, "available", True) and self._cached_device_state:  # pragma: no mutate
                _LOGGER.debug(  # pragma: no mutate
                    "%s Failed to get latest state (API Error), using cached state.",
                    self.controller.log_prefix,
                )
                return self._cached_device_state
            raise UpdateFailed(
                "Failed to get device state: No data received and no cache available"  # pragma: no mutate
            )

        self._cached_device_state = full_device_state
        self._last_state_fetch_time = time.time()

        if not self.controller.loader.is_fully_initialized:
            try:
                device_type = self.controller.config.get(CONF_DEVICE_TYPE)

                # Safe access to loader's internal cache
                cache = self.controller.loader._parsed_yaml_cache
                id_map = (
                    cache.get(getattr(self.controller, "device_id", "XXXX"), {})
                    .get(CONFIG_DEVICE, {})
                    .get("identifiers")
                )

                if id_map:
                    _LOGGER.debug(  # pragma: no mutate
                        "%s 'identifiers' map found, running discovery",
                        self.controller.log_prefix,
                    )
                    self.controller.discovered_devices = get_value_by_path(
                        full_device_state, id_map.get("path_to_devices", [])
                    )

                    if self.controller.discovered_devices:
                        device_to_discover = None  # pragma: no mutate

                        if device_type == DEVICE_TYPE_MIM_H03:
                            device_to_discover = next(
                                (
                                    d
                                    for d in self.controller.discovered_devices
                                    if d and d.get("id") != "0" and "Mode" in d
                                ),
                                None,  # pragma: no mutate
                            )
                        else:
                            device_to_discover = self.controller.discovered_devices[0]

                        if device_to_discover:
                            id_path = id_map.get("id")
                            discovered_id = (
                                get_value_by_path(device_to_discover, id_path)
                                if id_path
                                else None
                            )

                            # discovered_id = device_to_discover.get("id", None)
                            # Only update if current device_id is missing or "0"

                            curr_dev_id = getattr(
                                self.controller, "device_id", ""
                            )  # pragma: no mutate
                            if discovered_id is not None and (
                                not curr_dev_id or curr_dev_id == "0"
                            ):
                                if hasattr(
                                    self.controller, "device_id"
                                ):  # pragma: no mutate
                                    self.controller.device_id = str(discovered_id)

                            _LOGGER.info(  # pragma: no mutate
                                "%s Discovered/Confirmed device with id=%s",
                                self.controller.log_prefix,
                                getattr(
                                    self.controller, "device_id", "unknown"
                                ),  # pragma: no mutate
                            )

                await self.controller.loader.async_finish_initialization()

            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.exception(  # pragma: no mutate
                    "%s Error during initial device discovery: %s",
                    self.controller.log_prefix,
                    e,
                )

        current_state = None
        if (
            hasattr(self.controller, "get_current_state_callback")
            and self.controller.get_current_state_callback
        ):
            current_state = self.controller.get_current_state_callback()

        await self.async_update_properties_from_state(
            full_device_state,
            current_hass_state=current_state,
        )
        # Safe access to state_getter .value
        return self.controller.loader.state_getter.value

    async def async_update_properties_from_state(
        self,
        full_device_state: dict[str, Any] | None = None,
        is_prediction: bool = False,
        force_update: bool = False,
        current_hass_state: Any | None = None,
    ) -> dict[str, Any]:
        """Update individual entity properties from the parsed network state."""
        if not self.controller.loader.is_fully_initialized:
            return {}

        if full_device_state is None:
            if not current_hass_state:
                _LOGGER.error(  # pragma: no mutate
                    "%s [UpdateProps] Cannot rebuild state from HASS: coordinator data is null.",
                    self.controller.log_prefix,
                )
                return {}
            full_device_state = await self._build_device_state_from_hass(
                current_hass_state
            )

        if full_device_state is None:
            return {}

        device_to_process = full_device_state

        try:
            cache = self.controller.loader._parsed_yaml_cache
            id_map = (
                cache.get(getattr(self.controller, "device_id", "XXXX"), {})
                .get(CONFIG_DEVICE, {})
                .get("identifiers")
            )
            if id_map:
                devices_list = get_value_by_path(
                    full_device_state, id_map.get("path_to_devices", [])
                )
                if devices_list:
                    found_device = next(
                        (
                            d
                            for d in devices_list
                            if d
                            and str(get_value_by_path(d, id_map.get("id", [])))
                            == str(getattr(self.controller, "device_id", ""))
                        ),
                        None,
                    )
                    if not found_device and devices_list:
                        found_device = devices_list[0]

                    if found_device:
                        device_to_process = found_device
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.exception(  # pragma: no mutate
                "%s Error during sub-device selection: %s",
                self.controller.log_prefix,
                e,
            )
            device_to_process = full_device_state

        if not is_prediction:
            if (
                not force_update
                and getattr(self, "_last_device_state", None) == device_to_process
                and not self._pending_updates
            ):
                return {}  # Dirty Check: No changes detected

            self._last_device_state = copy.deepcopy(device_to_process)
        corrections: dict[str, Any] = {}

        all_properties = (
            list(self.controller.loader.operations.values())
            + list(self.controller.loader.properties.values())
            + list(self.controller.loader.sensors.values())
        )

        now = time.time()
        PENDING_TTL = 15.0

        # PASS 1: Evaluate TTL and patch the raw device dictionary optimally
        for prop in all_properties:
            prop_id = getattr(prop, "id", None)
            if not prop_id or prop_id not in self._pending_updates:
                continue

            pending_val, timestamp = self._pending_updates[prop_id]

            # Expire stale pending updates
            if now - timestamp >= PENDING_TTL:
                del self._pending_updates[prop_id]
                continue

            # Update the underlying raw dictionary so dependencies evaluate correctly
            device_key = self._get_cached_device_key_from_prop(prop)
            if device_key and hasattr(prop, "convert_hass_to_dev"):
                device_to_process[device_key] = prop.convert_hass_to_dev(pending_val)

        # PASS 2: Sync UI properties with the crucial optimistic bypass
        for prop in all_properties:
            prop_id = getattr(prop, "id", None)

            try:
                # If the property is under an active optimistic lock, inject value and SKIP network sync
                if prop_id and prop_id in self._pending_updates:
                    pending_val, _ = self._pending_updates[prop_id]
                    if hasattr(prop, "value"):
                        prop.value = pending_val
                    elif hasattr(prop, "_value"):
                        prop._value = pending_val
                    continue  # CRITICAL: Do not overwrite optimistic value with stale network data

                # Normal sync for unlocked properties
                if hasattr(prop, "async_update_state"):
                    # Polling logic requires synchronous execution if it's a normal method, 
                    # but async if explicitly defined. We await it since it's defined as async.
                    await prop.async_update_state(device_to_process, getattr(self.controller, "debug", False))

            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.error(  # pragma: no mutate
                    "%s FAILED to update property '%s'. Error: %s",
                    self.controller.log_prefix,
                    getattr(prop, "name", "unknown"),
                    e,
                )
        # PASS 3: Propagate state flags and enforce hardware limits
        for prop in all_properties:
            if hasattr(prop, "set_device_state_for_values"):
                prop.set_device_state_for_values(device_to_process)

        for _, op in list(self.controller.loader.operations.items()):
            if hasattr(op, "is_valid") and not op.is_valid(device_to_process):
                continue

            op_value = getattr(op, "value", getattr(op, "_value", None))
            op_values = getattr(op, "values", None)

            if op_values and op_value is not None and op_value != STATE_UNKNOWN:
                if op_value not in op_values:
                    new_value = op_values[0] if op_values else STATE_UNKNOWN
                    if hasattr(op, "value"):
                        op.value = new_value
                    elif hasattr(op, "_value"):
                        op._value = new_value
                    corrections[op.id] = new_value

                if getattr(op, "feature_flag", getattr(op, "_feature_flag", None)) == ClimateEntityFeature.FAN_MODE:
                    self.fan_modes_list_changed_pending_flicker = True

        self._rebuild_attributes()
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

        # Respectful setter
        if hasattr(self.controller, "update_state_attributes"):
            self.controller.update_state_attributes(new_attrs)
        elif hasattr(self.controller, "_attributes"):
            self.controller._attributes = new_attrs

    def _get_hass_attr_for_op_id(self, op_id: str) -> str:
        """Map YAML operation IDs to ClimateIPDeviceState attributes."""
        mapping = {
            "hvac": "hvac_mode",  # pragma: no mutate
            "hvac_mode": "hvac_mode",  # pragma: no mutate
            "temperature": "target_temperature",  # pragma: no mutate
            "target_temperature": "target_temperature",  # pragma: no mutate
            "current_temperature": "current_temperature",  # pragma: no mutate
            "fan": "fan_mode",  # pragma: no mutate
            "fan_mode": "fan_mode",  # pragma: no mutate
            "swing": "swing_mode",  # pragma: no mutate
            "swing_mode": "swing_mode",  # pragma: no mutate
            "preset": "preset_mode",  # pragma: no mutate
            "preset_mode": "preset_mode",  # pragma: no mutate
            "special": "preset_mode",  # pragma: no mutate
        }
        return mapping.get(op_id, op_id)

    async def _build_device_state_from_hass(
        self, hass_state: ClimateIPDeviceState
    ) -> dict[str, Any] | None:
        """Reconstruct the device state payload using cached values and HA entity state."""
        if not self.controller.loader.is_fully_initialized:
            return None
        st_getter = self.controller.loader.state_getter
        if not st_getter:
            return None

        last_real_state = st_getter.value

        if not last_real_state:
            return {}

        reconstructed_state = copy.deepcopy(last_real_state)
        all_props = list(self.controller.loader.operations.values()) + list(
            self.controller.loader.properties.values()
        )

        for op in all_props:
            op_id = getattr(op, "id", None)
            if not op_id:
                continue

            hass_attr = self._get_hass_attr_for_op_id(op_id)
            hass_value = getattr(hass_state, hass_attr, None)
            if hass_value is not None and hasattr(op, "convert_hass_to_dev"):
                device_value = op.convert_hass_to_dev(hass_value)
                device_key = self._get_cached_device_key_from_prop(op)
                if device_key and device_key in reconstructed_state:
                    reconstructed_state[device_key] = device_value

        return reconstructed_state

    # async def _build_device_state_from_props(self) -> dict[str, Any] | None:
    #     """Reconstruct the device state using current internal properties."""
    #     st_getter = self.controller.loader.state_getter
    #     if not st_getter:
    #         return None

    #     last_real_state = st_getter.value

    #     if last_real_state is None:
    #         return {}

    #     reconstructed_state = copy.deepcopy(last_real_state)
    #     all_props = list(self.controller.loader.operations.values()) + list(
    #         self.controller.loader.properties.values()
    #     )
    #     for op in all_props:
    #         op_value = getattr(op, "value", getattr(op, "_value", None))
    #         if op_value is None:
    #             continue

    #         device_value = op_value
    #         if hasattr(op, "convert_hass_to_dev"):  # pragma: no mutate
    #             device_value = op.convert_hass_to_dev(op_value)  # pragma: no mutate

    #         is_2878 = (
    #             self.controller.config.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_SAMSUNG_2878
    #         )
    #         op_id = op.id

    #         if op_id in ("hvac", "hvac_mode", ATTR_HVAC_MODE):
    #             if is_2878:
    #                 device_key = self._get_cached_device_key_from_prop(op)
    #                 if device_key:
    #                     reconstructed_state[device_key] = device_value
    #                 power_op = self.controller.loader.operations.get(
    #                     "power"
    #                 ) or self.controller.loader.properties.get("power")
    #                 if power_op:
    #                     power_key = self._get_cached_device_key_from_prop(power_op)
    #                     if power_key:
    #                         reconstructed_state[power_key] = (
    #                             "Off" if device_value == "Off" else "On"
    #                         )
    #             else:
    #                 device_list = reconstructed_state.get("Devices")
    #                 if isinstance(device_list, list) and device_list:
    #                     device_obj = device_list[0]
    #                     if isinstance(device_obj, dict):
    #                         if "Operation" not in device_obj:
    #                             device_obj["Operation"] = {}
    #                         if device_value == "Off":
    #                             device_obj["Operation"]["power"] = "Off"
    #                         else:
    #                             device_obj["Operation"]["power"] = "On"
    #                             device_obj.setdefault("Mode", {})["modes"] = [
    #                                 device_value
    #                             ]
    #         elif op_id in ("temperature", ATTR_TEMPERATURE):
    #             if is_2878:
    #                 device_key = self._get_cached_device_key_from_prop(op)
    #                 if device_key:
    #                     reconstructed_state[device_key] = str(device_value)
    #             else:
    #                 device_list = reconstructed_state.get("Devices")
    #                 if isinstance(device_list, list) and device_list:
    #                     device_obj = device_list[0]
    #                     if isinstance(device_obj, dict):
    #                         if "Temperatures" not in device_obj:
    #                             device_obj["Temperatures"] = [{"desired": device_value}]
    #                         elif device_obj["Temperatures"]:
    #                             device_obj["Temperatures"][0]["desired"] = device_value
    #         elif op_id in (
    #             "fan",
    #             "fan_mode",
    #             "fan_max",
    #             "swing",
    #             "swing_mode",
    #             "good_sleep",
    #             "preset_mode",
    #             ATTR_FAN_MODE,
    #             ATTR_SWING_MODE,
    #             ATTR_PRESET_MODE,
    #         ):
    #             if is_2878:
    #                 device_key = self._get_cached_device_key_from_prop(
    #                     op
    #                 )  # pragma: no mutate
    #                 if device_key:
    #                     reconstructed_state[device_key] = device_value
    #             else:
    #                 device_list = reconstructed_state.get("Devices")
    #                 if isinstance(device_list, list) and device_list:
    #                     device_obj = device_list[0]
    #                     if isinstance(device_obj, dict):
    #                         if op_id in ("fan", "fan_mode", ATTR_FAN_MODE):
    #                             device_obj.setdefault("Wind", {})["speedLevel"] = (
    #                                 int(device_value)
    #                                 if str(device_value).isdigit()
    #                                 else device_value
    #                             )
    #                         elif op_id in ("fan_max",):
    #                             device_obj.setdefault("Wind", {})["maxSpeedLevel"] = (
    #                                 int(device_value)
    #                                 if str(device_value).isdigit()
    #                                 else device_value
    #                             )
    #                         elif op_id in ("swing", "swing_mode", ATTR_SWING_MODE):
    #                             device_obj.setdefault("Wind", {})["direction"] = (
    #                                 device_value
    #                             )
    #                         elif op_id in ("preset_mode", ATTR_PRESET_MODE):
    #                             options = device_obj.setdefault("Mode", {}).setdefault(
    #                                 "options", []
    #                             )
    #                             val_str = str(device_value)
    #                             if not options:
    #                                 options.append(val_str)
    #                             else:
    #                                 options[0] = val_str
    #                         elif op_id == "good_sleep":
    #                             options = device_obj.setdefault("Mode", {}).setdefault(
    #                                 "options", []
    #                             )
    #                             sleep_val = f"Sleep_{int(float(device_value))}"

    #                             if not options:
    #                                 options.extend(["Comode_Off", sleep_val])
    #                             elif len(options) == 1:
    #                                 options.append(sleep_val)
    #                             else:
    #                                 options[1] = sleep_val
    #         else:
    #             device_key = self._get_cached_device_key_from_prop(op)
    #             if device_key:
    #                 reconstructed_state[device_key] = device_value

    #     return reconstructed_state


    async def _build_device_state_from_props(self) -> dict[str, Any] | None:
        """Reconstruct the device state by delegating to protocol-specific mutators."""
        st_getter = self.controller.loader.state_getter
        if not st_getter:
            return None

        last_real_state = st_getter.value
        if last_real_state is None:
            return {}

        reconstructed_state = copy.deepcopy(last_real_state)
        all_props = list(self.controller.loader.operations.values()) + list(
            self.controller.loader.properties.values()
        )

        is_2878 = self.controller.config.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_SAMSUNG_2878

        for op in all_props:
            op_value = getattr(op, "value", getattr(op, "_value", None))
            if op_value is None:
                continue

            device_value = op_value
            if hasattr(op, "convert_hass_to_dev"):
                device_value = op.convert_hass_to_dev(op_value)

            op_id = getattr(op, "id", "")

            # Delegate to protocol-specific mutations
            if is_2878:
                self._apply_2878_state_mutation(reconstructed_state, op, op_id, device_value)
            else:
                self._apply_8888_state_mutation(reconstructed_state, op, op_id, device_value)

        return reconstructed_state

    def _apply_2878_state_mutation(self, state: dict[str, Any], op: Any, op_id: str, device_value: Any) -> None:
        """Apply a property mutation specific to the Samsung 2878 socket protocol, with robust fallbacks."""
        device_key = self._get_cached_device_key_from_prop(op)

        if op_id in ("hvac", "hvac_mode", ATTR_HVAC_MODE):
            # Fallback to the rigid Samsung XML attribute if template parsing yields None
            state[device_key or "AC_FUN_OPMODE"] = device_value

            power_op = self.controller.loader.operations.get("power") or self.controller.loader.properties.get("power")
            power_key = "AC_FUN_POWER"
            if power_op:
                power_key = self._get_cached_device_key_from_prop(power_op) or "AC_FUN_POWER"

            state[power_key] = "Off" if device_value == "Off" else "On"

        elif op_id in ("temperature", ATTR_TEMPERATURE):
            state[device_key or "AC_FUN_TEMPSET"] = str(device_value)

        elif op_id in ("fan", "fan_mode", ATTR_FAN_MODE):
            state[device_key or "AC_FUN_WINDLEVEL"] = device_value

        elif op_id in ("swing", "swing_mode", ATTR_SWING_MODE):
            state[device_key or "AC_FUN_DIRECTION"] = device_value

        elif op_id in ("preset_mode", ATTR_PRESET_MODE, "good_sleep"):
            state[device_key or "AC_FUN_COMODE"] = device_value

        else:
            # Fallback for generic switches/sensors
            if device_key:
                state[device_key] = device_value

    def _apply_8888_state_mutation(self, state: dict[str, Any], op: Any, op_id: str, device_value: Any) -> None:
        """Apply a property mutation specific to the Samsung 8888 REST protocol."""

        # Keys that require deep injection into the Devices array
        if op_id in (
            "hvac", "hvac_mode", ATTR_HVAC_MODE, 
            "temperature", ATTR_TEMPERATURE, 
            "fan", "fan_mode", ATTR_FAN_MODE, "fan_max", 
            "swing", "swing_mode", ATTR_SWING_MODE, 
            "preset_mode", ATTR_PRESET_MODE, "good_sleep"
        ):
            device_list = state.get("Devices")
            if not isinstance(device_list, list) or not device_list:
                return
            device_obj = device_list[0]
            if not isinstance(device_obj, dict):
                return

            if op_id in ("hvac", "hvac_mode", ATTR_HVAC_MODE):
                device_obj.setdefault("Operation", {})["power"] = "Off" if device_value == "Off" else "On"
                device_obj.setdefault("Mode", {})["modes"] = [device_value]
            elif op_id in ("temperature", ATTR_TEMPERATURE):
                temps = device_obj.setdefault("Temperatures", [{"desired": device_value}])
                if temps:
                    temps[0]["desired"] = device_value
            elif op_id in ("fan", "fan_mode", ATTR_FAN_MODE):
                device_obj.setdefault("Wind", {})["speedLevel"] = int(device_value) if str(device_value).isdigit() else device_value
            elif op_id == "fan_max":
                device_obj.setdefault("Wind", {})["maxSpeedLevel"] = int(device_value) if str(device_value).isdigit() else device_value
            elif op_id in ("swing", "swing_mode", ATTR_SWING_MODE):
                device_obj.setdefault("Wind", {})["direction"] = device_value
            elif op_id in ("preset_mode", ATTR_PRESET_MODE):
                options = device_obj.setdefault("Mode", {}).setdefault("options", [])
                val_str = str(device_value)
                if not options:
                    options.append(val_str)
                else:
                    options[0] = val_str
            elif op_id == "good_sleep":
                options = device_obj.setdefault("Mode", {}).setdefault("options", [])
                sleep_val = f"Sleep_{int(float(device_value))}"
                if not options:
                    options.extend(["Comode_Off", sleep_val])
                elif len(options) == 1:
                    options.append(sleep_val)
                else:
                    options[1] = sleep_val
        else:
            # Fallback generic key mapping at the ROOT level
            device_key = self._get_cached_device_key_from_prop(op)
            if device_key:
                state[device_key] = device_value

    def _calculate_structured_state(
        self, raw_state: dict[str, Any]
    ) -> ClimateIPDeviceState | None:
        """Pure dry-run calculation of the ClimateIPDeviceState from raw data, respecting optimistic locks."""
        if not self.controller.loader.is_fully_initialized:
            return None

        try:
            mapping = {
                ATTR_HVAC_MODE: "hvac_mode",
                ATTR_TEMPERATURE: "target_temperature",
                "current_temperature": "current_temperature",
                ATTR_FAN_MODE: "fan_mode",
                ATTR_SWING_MODE: "swing_mode",
                ATTR_PRESET_MODE: "preset_mode",
            }

            all_properties = (
                list(self.controller.loader.operations.values())
                + list(self.controller.loader.properties.values())
                + list(self.controller.loader.sensors.values())
            )

            prop_values = {}
            for prop in all_properties:
                prop_id = getattr(prop, "id", None)
                if not prop_id:
                    continue

                mapped_key = mapping.get(prop_id)
                if not mapped_key:
                    continue

                # OPTIMISTIC INTERCEPTION: If locked, bypass the stale raw payload entirely
                if prop_id in self._pending_updates:
                    pending_val, _ = self._pending_updates[prop_id]
                    prop_values[mapped_key] = pending_val
                    continue

                # Normal evaluation from the network payload
                if hasattr(prop, "calculate_value_from_state"):
                    prop_values[mapped_key] = prop.calculate_value_from_state(
                        raw_state
                    )

            return ClimateIPDeviceState(
                hvac_mode=prop_values.get("hvac_mode"),
                target_temperature=prop_values.get("target_temperature"),
                current_temperature=prop_values.get("current_temperature"),
                fan_mode=prop_values.get("fan_mode"),
                swing_mode=prop_values.get("swing_mode"),
                preset_mode=prop_values.get("preset_mode"),
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(  # pragma: no mutate
                "%s [AtomicMerge] Dry-run calculation failed: %s",
                self.controller.log_prefix,
                e,
            )
            return None

    async def async_merge_device_state(
        self, new_data: dict[str, Any], _is_response: bool, _is_update: bool
    ) -> bool:
        """Merge a partial state update (e.g. from a push notification) into the known state."""
        if not new_data:
            return False

        current_hass_state = None  # pragma: no mutate
        if (
            hasattr(self.controller, "get_current_state_callback")
            and self.controller.get_current_state_callback
        ):
            current_hass_state = self.controller.get_current_state_callback()

        if not current_hass_state:
            st_getter = self.controller.loader.state_getter
            if not st_getter:
                return False
            base_raw_state = st_getter.value
        else:
            base_raw_state = await self._build_device_state_from_hass(
                current_hass_state
            )

        if base_raw_state is None:
            return False

        candidate_state = copy.deepcopy(base_raw_state)
        candidate_state.update(new_data)

        structured_candidate = self._calculate_structured_state(candidate_state)

        if structured_candidate is None:
            _LOGGER.warning(  # pragma: no mutate
                "%s [AtomicMerge] Push update discarded: dry-run validation failed for payload: %s",
                self.controller.log_prefix,
                new_data,
            )
            return False

        _LOGGER.debug(  # pragma: no mutate
            "%s [AtomicMerge] Committing push update to global state.",
            self.controller.log_prefix,
        )

        self._evict_invalidated_pending_updates(new_data)

        st_getter = self.controller.loader.state_getter
        if st_getter:
            if hasattr(st_getter, "value"):
                st_getter.value = candidate_state
            elif hasattr(st_getter, "_value"):
                st_getter._value = candidate_state

        await self.async_update_properties_from_state(
            candidate_state, force_update=True, current_hass_state=current_hass_state
        )

        return True

    @staticmethod
    def _values_match(val1: Any, val2: Any) -> bool:
        """Check if two values match numerically (float cast) or string-wise (case-insensitive)."""
        try:
            return float(val1) == float(val2)
        except (ValueError, TypeError):
            return str(val1).strip().lower() == str(val2).strip().lower()

    def _evict_invalidated_pending_updates(self, push_data: dict[str, Any]) -> None:
        """Remove pending-update entries whose device-key is superseded by matching push payload or expired."""
        if not self._pending_updates:
            return

        now = time.time()
        ttl_threshold = 15.0
        pending_ids = list(self._pending_updates.keys())
        invalidated: set[str] = set()

        for prop_id in pending_ids:
            entry = self._pending_updates.get(prop_id)
            if not entry:
                continue

            if isinstance(entry, tuple) and len(entry) == 2:
                pending_val, timestamp = entry
            else:
                pending_val, timestamp = entry, now

            if now - timestamp > ttl_threshold:
                invalidated.add(prop_id)
                continue

            prop = self.controller.loader.operations.get(
                prop_id
            ) or self.controller.loader.properties.get(prop_id)
            if not prop:
                continue

            device_key = self._get_cached_device_key_from_prop(prop)

            if device_key and device_key in push_data:
                push_val = push_data[device_key]
                expected_dev_val = (
                    prop.convert_hass_to_dev(pending_val)
                    if hasattr(prop, "convert_hass_to_dev")
                    else pending_val
                )
                if self._values_match(push_val, expected_dev_val):
                    invalidated.add(prop_id)
                continue

            power_op = self.controller.loader.operations.get(
                "power"
            ) or self.controller.loader.properties.get("power")
            power_key = (
                self._get_cached_device_key_from_prop(power_op)
                if power_op
                else None
            )
            if power_key and push_data.get(power_key) == "Off" and prop_id in (
                "hvac_mode",
                "hvac",
                "fan_mode",
                "fan",
                "preset_mode",
                "preset",
                "swing_mode",
                "swing",
            ):
                invalidated.add(prop_id)

        for prop_id in invalidated:
            _LOGGER.debug(  # pragma: no mutate
                "%s [AtomicMerge] Evicting stale pending update for '%s' (push superseded it or TTL expired).",
                self.controller.log_prefix,
                prop_id,
            )
            if prop_id in self._pending_updates:
                del self._pending_updates[prop_id]

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

        # Helper to extract the alphanumeric + underscore key bounds
        def _extract_key(text: str) -> str:
            for i, char in enumerate(text):
                if not (char.isalnum() or char == "_"):
                    return text[:i]
            return text

        # Match: device_state.KeyName
        if "device_state." in template_string:
            parts = template_string.split("device_state.", 1)[1]
            key = _extract_key(parts)
            return key if key else None

        # Match: device_state['KeyName'] or device_state["KeyName"]
        if "device_state[" in template_string:
            parts = template_string.split("device_state[", 1)[1]
            if parts and parts[0] in ("'", '"'):
                parts = parts[1:]
            key = _extract_key(parts)
            return key if key else None

        return None


    def _get_cached_device_path_from_prop(self, prop: Any) -> list[str | int] | None:
        """Extract and cache the deep JSON path mapped to a specific property from its template."""
        prop_id = getattr(prop, "id", None)
        if not prop_id:
            return None

        if not hasattr(self, "_prop_template_path_cache"):
            self._prop_template_path_cache: dict[str, list[str | int] | None] = {}

        if prop_id in self._prop_template_path_cache:
            return self._prop_template_path_cache[prop_id]

        status_tmpl = getattr(prop, "status_template", None)
        path = self._get_device_path_from_template(status_tmpl)
        self._prop_template_path_cache[prop_id] = path
        return path

    def _get_device_path_from_template(self, template_obj: Any) -> list[str | int] | None:
        """Robustly tokenize a Jinja template string to extract a deep JSON path.
        Returns paths like: ["Devices", 0, "Wind", "speedLevel"] or ["AC_FUN_OPMODE"]
        """
        if not template_obj:
            return None

        template_string = (
            template_obj.template
            if hasattr(template_obj, "template")
            else str(template_obj)
        )

        if not template_string or "device_state" not in template_string:
            return None

        chain = template_string.split("device_state", 1)[1]
        path: list[str | int] = []

        pattern = re.compile(
            r"^(?:"
            r"\.get\(\s*['\"]([^'\"]+)['\"]"
            r"|\.([a-zA-Z_]\w*)"
            r"|\[['\"]([^'\"]+)['\"]\]"
            r"|\[(\d+)\]"
            r")"
        )

        while chain:
            match = pattern.match(chain)
            if not match:
                break

            get_key, dot_key, bracket_str, bracket_int = match.groups()

            if get_key:
                path.append(get_key)
            elif dot_key:
                path.append(dot_key)
            elif bracket_str:
                path.append(bracket_str)
            elif bracket_int:
                path.append(int(bracket_int))

            chain = chain[match.end():]

        return path if path else None

    async def async_predict_and_correct_state(
        self,
        current_hass_state: ClimateIPDeviceState,
        property_name: str,
        new_value: Any,
    ) -> tuple[ClimateEntityFeature, dict[str, Any]]:
        """Predict the expected state after command to improve UI responsiveness."""
        if (
            not self.controller.loader.state_getter
            or not self.controller.loader.is_fully_initialized
        ):
            return ClimateEntityFeature(0), {}

        last_real_state = self.controller.loader.state_getter.value
        if not last_real_state:
            return ClimateEntityFeature(0), {}

        corrections: dict[str, Any] = {}
        if property_name in self._pending_updates:
            del self._pending_updates[property_name]

        # 1. Sync properties with current HA state (unwrap Enums safely)
        all_props = list(self.controller.loader.operations.values()) + list(self.controller.loader.properties.values())
        for op in all_props:
            op_id = getattr(op, "id", None)
            if op_id:
                hass_attr = self._get_hass_attr_for_op_id(op_id)
                if hasattr(current_hass_state, hass_attr):
                    val = getattr(current_hass_state, hass_attr)
                    # Extract string value if it's an Enum (e.g., HVACMode.DRY -> "dry")
                    if val is not None and hasattr(val, "value") and not isinstance(val, dict):
                        val = val.value

                    if hasattr(op, "value"):
                        op.value = val
                    elif hasattr(op, "_value"):
                        op._value = val

        # 2. Find the property being changed using robust alias mapping
        prop_to_change = None
        for op in self.controller.loader.operations.values():
            op_id = getattr(op, "id", "")
            if op_id == property_name or self._get_hass_attr_for_op_id(op_id) == property_name:
                prop_to_change = op
                break

        if not prop_to_change:
            _LOGGER.debug(
                "%s [Predict] prop_to_change for '%s' is None. Returning early.",
                self.controller.log_prefix,
                property_name,
            )
            return ClimateEntityFeature(0), {}

        # Unwrap the new value if it's an enum
        if new_value is not None and hasattr(new_value, "value") and not isinstance(new_value, dict):
            new_value = new_value.value

        # FORCED INJECTION: Directly mutate the operation's value so future_state picks it up
        if hasattr(prop_to_change, "value"):
            prop_to_change.value = new_value
        elif hasattr(prop_to_change, "_value"):
            prop_to_change._value = new_value

        # 3. Build futuristic payload using the highly-specific legacy builder
        future_state = await self._build_device_state_from_props()
        if not future_state:
            return ClimateEntityFeature(0), {}

        # --- OPTIMISTIC RAW STATE INJECTION ---
        if isinstance(self.controller.loader.state_getter.value, dict):
            self.controller.loader.state_getter.value.update(future_state)
        # --------------------------------------

        # 4. Process rules and fetch restricted lists
        update_result = await self.async_update_properties_from_state(
            future_state, is_prediction=True, current_hass_state=current_hass_state
        )
        corrections.update(update_result)

        return ClimateEntityFeature(0), corrections    

    async def async_shutdown(self) -> None:
        """Shut down the poller and cleanly close any active connections."""
        conn = self.controller.loader.connection
        if conn:
            _LOGGER.debug(
                "%s Shutting down connection...", self.controller.log_prefix
            )  # pragma: no mutate

            async def _try(coro):  # pylint: disable=invalid-name
                try:
                    await coro
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

            if hasattr(conn, "stop_listening"):
                await _try(conn.stop_listening())

            # Delegated shutdown to facade to avoid accessing protected variables
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