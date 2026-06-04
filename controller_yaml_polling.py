# pylint: disable=import-outside-toplevel,line-too-long,protected-access,too-many-branches,too-many-instance-attributes,too-many-lines,too-many-locals,too-many-nested-blocks,too-many-statements
"""State management and polling for YAML-configured climate controllers."""

import asyncio
import copy

import logging
import re
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
    CONF_TOKEN,
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

    def __init__(self, controller: Any) -> None:
        """Initialize the poller with a reference to the main controller facade."""
        self.controller = controller

        self._cached_device_state: dict[str, Any] | None = None
        self._last_state_fetch_time: float = 0.0
        self._last_device_state: dict[str, Any] | None = None
        self._consecutive_connection_errors: int = 0
        self._pending_updates: dict[str, tuple[Any, float]] = {}

        self._prop_template_key_cache: dict[str, str | None] = {}
        self._device_state_key_regex = re.compile(
            r"device_state[\[\.](['\"]?)([A-Za-z0-9_]+)\1"
        )
        self._fan_modes_list_changed_pending_flicker: bool = False

    async def _refresh_smartthings_token(self) -> str | None:
        """Attempt to refresh an expired SmartThings token using the official HA integration."""
        try:
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
            masked = f"***{token[-6:]}" if token and len(token) > 6 else "None"
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

    def _try_create_repair_issue(self) -> None:
        """Create a HA repair issue for persistent device offline state."""
        if not getattr(self.controller, "hass", None):
            return
        try:
            async_create_issue(
                self.controller.hass,
                "climate_ip",
                f"connection_failed_{self.controller.ip_address}",
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key="connection_failed",
                translation_placeholders={
                    "host": self.controller.ip_address,
                    "name": getattr(self.controller, "_name", None)
                    or self.controller.ip_address,
                },
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.debug(
                "%s Failed to create repair issue: %s", self.controller.log_prefix, e
            )

    def _update_all_connections_token(self, new_token: str) -> None:
        """Propagate the new token to all active connection engines."""
        _LOGGER.debug(
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
        _LOGGER.debug(
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
                masked["uuid"] = "***" + masked["uuid"][-6:]
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
            _LOGGER.debug(
                "%s [Cache] Returning cached device state (TTL < 2s) to prevent double polling.",
                self.controller.log_prefix,
            )
            return self._cached_device_state.copy()

        _LOGGER.debug(
            "%s Polling device for state. Connection ID: %s",
            self.controller.log_prefix,
            id(self.controller.loader.connection),
        )
        device_state = await self.async_update_state()
        return device_state.copy() if device_state else None

    async def async_update_state(self) -> dict[str, Any] | None:
        """Fetch the actual state from the device over the network."""
        if not self.controller.loader.state_getter:
            raise UpdateFailed("State getter is not initialized, cannot update state.")

        # Pre-check network reachability for non-2878 devices (REST/8888)
        if (
            self.controller.config.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_SAMSUNG_2878
            and self.controller.ip_address
        ):
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
                _LOGGER.debug(
                    "%s Network diagnostic failed: %s",
                    self.controller.log_prefix,
                    diag_err,
                )

        try:
            full_device_state = (
                await self.controller.loader.state_getter.async_update_state(
                    None, self.controller.debug
                )
            )

            if self._consecutive_connection_errors > 0:
                _LOGGER.info(
                    "%s Connection recovered after %d failure(s). Counter reset.",
                    self.controller.log_prefix,
                    self._consecutive_connection_errors,
                )
                self._consecutive_connection_errors = 0
                if getattr(self.controller, "hass", None):
                    try:
                        async_delete_issue(
                            self.controller.hass,
                            "climate_ip",
                            f"connection_failed_{self.controller.ip_address}",
                        )
                        _LOGGER.debug(
                            "%s Successfully resolved/deleted repair issue.",
                            self.controller.log_prefix,
                        )
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        _LOGGER.debug(
                            "%s Failed to delete repair issue: %s",
                            self.controller.log_prefix,
                            e,
                        )

        except AuthError as exc:
            _LOGGER.info(
                "%s [Auth] Authentication failed (401). Refreshing token via OAuth2Session...",
                self.controller.log_prefix,
            )
            new_token = await self._refresh_smartthings_token()

            if new_token and new_token != self.controller.token:
                _LOGGER.info(
                    "%s [Auth] Automatically retrieved new Access Token from SmartThings integration.",
                    self.controller.log_prefix,
                )
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
                except (
                    Exception
                ) as retry_exc:  # pylint: disable=broad-exception-caught,bad-exception-cause
                    raise UpdateFailed(
                        f"Retry after token refresh failed: {retry_exc}"
                    ) from retry_exc
            else:
                _LOGGER.info(
                    "%s [Auth] Token refresh failed. SmartThings integration may not be installed.",
                    self.controller.log_prefix,
                )
                # pylint: disable=import-outside-toplevel,bad-exception-cause
                raise ConfigEntryAuthFailed(
                    "Authentication failed. Please install and configure the "
                    "official SmartThings integration to provide a valid token."
                ) from exc

        except InvalidHeaderError:
            _LOGGER.debug(
                "%s Malformed HTTP header detected, bubbling up to coordinator.",
                self.controller.log_prefix,
            )
            raise

        except (RequestException, CannotConnect) as e:
            if "persistently offline" in str(e):
                self._consecutive_connection_errors = 2
            else:
                self._consecutive_connection_errors += 1

            if self._consecutive_connection_errors <= 2 and self._cached_device_state is not None:
                _LOGGER.debug(
                    "%s Connection failed (%d/3). Using cached state to prevent unavailability. Error: %s",
                    self.controller.log_prefix,
                    self._consecutive_connection_errors,
                    e,
                )
                return self._cached_device_state

            if self._consecutive_connection_errors == 3:
                self._try_create_repair_issue()

            reason = (
                str(e).rsplit(":", maxsplit=1)[-1].strip() if ":" in str(e) else str(e)
            )
            _LOGGER.debug(
                "%s Device unreachable (attempt %d). Marking as unavailable. Reason: %s",
                self.controller.log_prefix,
                self._consecutive_connection_errors,
                reason,
            )
            raise UpdateFailed(f"Device unreachable: {reason}") from e

        if full_device_state is None:
            if self._cached_device_state:
                _LOGGER.debug(
                    "%s Failed to get latest state (API Error), using cached state.",
                    self.controller.log_prefix,
                )
                return self._cached_device_state
            raise UpdateFailed(
                "Failed to get device state: No data received and no cache available"
            )

        self._cached_device_state = full_device_state
        self._last_state_fetch_time = time.time()

        if not self.controller.loader.is_fully_initialized:
            try:
                device_type = self.controller.config.get(CONF_DEVICE_TYPE)
                # pylint: disable=import-outside-toplevel,protected-access
                id_map = (
                    self.controller.loader._parsed_yaml_cache.get(
                        self.controller.device_id, {}
                    )
                    .get(CONFIG_DEVICE, {})
                    .get("identifiers")
                )

                if id_map:
                    _LOGGER.debug(
                        "%s 'identifiers' map found, running discovery",
                        self.controller.log_prefix,
                    )
                    self.controller.discovered_devices = get_value_by_path(
                        full_device_state, id_map.get("path_to_devices", [])
                    )

                    if self.controller.discovered_devices:
                        device_to_discover = None

                        if device_type == DEVICE_TYPE_MIM_H03:
                            # For MIM-H03, we ignore ID 0 (Wifi-kit) and look for devices with 'Mode' (AC units)
                            device_to_discover = next(
                                (
                                    d
                                    for d in self.controller.discovered_devices
                                    if d and d.get("id") != "0" and "Mode" in d
                                ),
                                None,
                            )
                        else:
                            device_to_discover = self.controller.discovered_devices[0]

                        if device_to_discover:
                            discovered_id = get_value_by_path(
                                device_to_discover, id_map.get("id", [])
                            )
                            # Only update if current device_id is missing or "0"
                            if discovered_id is not None and (
                                not self.controller.device_id or self.controller.device_id == "0"
                            ):
                                self.controller.device_id = str(discovered_id)

                            _LOGGER.info(
                                "%s Discovered/Confirmed device with id=%s",
                                self.controller.log_prefix,
                                self.controller.device_id,
                            )

                await self.controller.loader.async_finish_initialization()

            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.error(
                    "%s Error during initial device discovery: %s",
                    self.controller.log_prefix,
                    e,
                    exc_info=True,
                )

        current_state = None
        if hasattr(self.controller, "get_current_state_callback") and self.controller.get_current_state_callback:
            current_state = self.controller.get_current_state_callback()

        await self.async_update_properties_from_state(
            full_device_state,
            current_hass_state=current_state,
        )
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
                _LOGGER.error(
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
            # pylint: disable=import-outside-toplevel,protected-access
            id_map = (
                self.controller.loader._parsed_yaml_cache.get(
                    self.controller.device_id, {}
                )
                .get(CONFIG_DEVICE, {})
                .get("identifiers")
            )

            if id_map:
                devices_list = get_value_by_path(
                    full_device_state, id_map.get("path_to_devices", [])
                )
                if devices_list:
                    # Search for the device that matches our controller's device_id.
                    # We compare as strings to handle numeric IDs safely.
                    found_device = next(
                        (
                            d
                            for d in devices_list
                            if d
                            and str(get_value_by_path(d, id_map.get("id", [])))
                            == str(self.controller.device_id)
                        ),
                        None,
                    )

                    # Fallback to the first device only if no specific ID match was found
                    # to maintain compatibility with legacy single-device configurations.
                    if not found_device and devices_list:
                        found_device = devices_list[0]

                    if found_device:
                        device_to_process = found_device
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s Error during sub-device selection: %s",
                self.controller.log_prefix,
                e,
                exc_info=True,
            )
            device_to_process = full_device_state

        if not is_prediction:
            if (
                not force_update
                and getattr(self, "_last_device_state", None) == device_to_process
                and not self._pending_updates
            ):
                return (
                    {}
                )  # Dirty Check: No changes detected, skip intensive property updates

            self._last_device_state = copy.deepcopy(device_to_process)
        corrections: dict[str, Any] = {}

        all_properties = (
            list(self.controller.loader.operations.values())
            + list(self.controller.loader.properties.values())
            + list(self.controller.loader.sensors.values())
        )

        # Inject pending structural updates into the raw device_to_process so that
        # validation_templates correctly evaluate future configurations during the latency gap.
        for prop in all_properties:
            if prop.id in self._pending_updates:
                pending_val, timestamp = self._pending_updates[prop.id]
                if time.time() - timestamp < 15.0:
                    device_key = self._get_cached_device_key_from_prop(prop)
                    if device_key:
                        device_to_process[device_key] = prop.convert_hass_to_dev(
                            pending_val
                        )

        for prop in all_properties:
            try:
                if prop.id in self._pending_updates:
                    pending_val, timestamp = self._pending_updates[prop.id]
                    if time.time() - timestamp < 15.0:
                        # pylint: disable=import-outside-toplevel,protected-access
                        prop._value = pending_val
                        continue
                    del self._pending_updates[prop.id]

                await prop.async_update_state(device_to_process, self.controller.debug)
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.error(
                    "%s FAILED to update property '%s'. Error: %s",
                    self.controller.log_prefix,
                    prop.name,
                    e,
                )

        for prop in all_properties:
            if hasattr(prop, "set_device_state_for_values"):
                prop.set_device_state_for_values(device_to_process)

        for _, op in list(self.controller.loader.operations.items()):
            if hasattr(op, "is_valid") and not op.is_valid(device_to_process):
                continue
            if (
                hasattr(op, "values")
                and op.value is not None
                and op.value != STATE_UNKNOWN
            ):
                if op.value not in op.values:
                    new_value = op.values[0] if op.values else STATE_UNKNOWN
                    # pylint: disable=import-outside-toplevel,protected-access
                    op._value = new_value
                    corrections[op.id] = new_value
                    # pylint: disable=import-outside-toplevel,protected-access
                    if (
                        hasattr(op, "_feature_flag")
                        and op._feature_flag == ClimateEntityFeature.FAN_MODE
                    ):
                        self._fan_modes_list_changed_pending_flicker = True

        self._rebuild_attributes()
        return corrections

    def _rebuild_attributes(self) -> None:
        """Rebuild the flattened state attributes dictionary."""
        # pylint: disable=import-outside-toplevel,protected-access
        self.controller._attributes = {ATTR_NAME: self.controller.name}
        all_properties = list(self.controller.loader.operations.values()) + list(
            self.controller.loader.properties.values()
        )
        for prop in all_properties:
            self.controller._attributes.update(prop.state_attributes)
        self.controller._attributes["last_sync"] = dt_util.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    def _get_hass_attr_for_op_id(self, op_id: str) -> str:
        """Map YAML operation IDs to ClimateIPDeviceState attributes."""
        # Modes are remapped in properties.py to include '_mode' suffix.
        # We handle both the original YAML key and the remapped ID.
        mapping = {
            "hvac": "hvac_mode",
            "hvac_mode": "hvac_mode",
            "temperature": "target_temperature",
            "target_temperature": "target_temperature",
            "current_temperature": "current_temperature",
            "fan": "fan_mode",
            "fan_mode": "fan_mode",
            "swing": "swing_mode",
            "swing_mode": "swing_mode",
            "preset": "preset_mode",
            "preset_mode": "preset_mode",
            "special": "preset_mode",
        }
        return mapping.get(op_id, op_id)

    async def _build_device_state_from_hass(
        self, hass_state: ClimateIPDeviceState
    ) -> dict[str, Any] | None:
        """Reconstruct the device state payload using cached values and HA entity state."""
        if not self.controller.loader.is_fully_initialized:
            return None
        if not self.controller.loader.state_getter:
            return None

        last_real_state = self.controller.loader.state_getter.value
        if not last_real_state:
            return {}

        reconstructed_state = copy.deepcopy(last_real_state)
        all_props = list(self.controller.loader.operations.values()) + list(
            self.controller.loader.properties.values()
        )

        for op in all_props:
            hass_attr = self._get_hass_attr_for_op_id(op.id)
            hass_value = getattr(hass_state, hass_attr, None)
            if hass_value is not None:
                device_value = op.convert_hass_to_dev(hass_value)
                device_key = self._get_cached_device_key_from_prop(op)
                if device_key and device_key in reconstructed_state:
                    reconstructed_state[device_key] = device_value

        return reconstructed_state

    async def _build_device_state_from_props(self) -> dict[str, Any] | None:
        """Reconstruct the device state using current internal properties."""
        if not self.controller.loader.state_getter:
            return None

        last_real_state = self.controller.loader.state_getter.value
        if not last_real_state:
            return {}

        reconstructed_state = copy.deepcopy(last_real_state)
        all_props = list(self.controller.loader.operations.values()) + list(
            self.controller.loader.properties.values()
        )
        for op in all_props:
            if op.value is None:
                continue

            device_value = op.convert_hass_to_dev(op.value)
            is_2878 = (
                self.controller.config.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_SAMSUNG_2878
            )

            if op.id in ("hvac", "hvac_mode", ATTR_HVAC_MODE):
                # Manual injection for hvac_mode which has complex templates without a single device_key
                if is_2878:
                    reconstructed_state["AC_FUN_OPMODE"] = device_value
                    if device_value != "Off":
                        reconstructed_state["AC_FUN_POWER"] = "On"
                    else:
                        reconstructed_state["AC_FUN_POWER"] = "Off"
                else:
                    # Protocol 8888 uses nested Devices array
                    device_list = reconstructed_state.get("Devices")
                    if isinstance(device_list, list) and len(device_list) > 0:
                        device_obj = device_list[0]
                        if isinstance(device_obj, dict):
                            if "Operation" not in device_obj:
                                device_obj["Operation"] = {}
                            if device_value == "Off":
                                device_obj["Operation"]["power"] = "Off"
                            else:
                                device_obj["Operation"]["power"] = "On"
                                if "Mode" not in device_obj:
                                    device_obj["Mode"] = {}
                                device_obj["Mode"]["modes"] = [device_value]
            elif op.id in ("temperature", ATTR_TEMPERATURE):
                if is_2878:
                    reconstructed_state["AC_FUN_TEMPSET"] = str(device_value)
                else:
                    device_list = reconstructed_state.get("Devices")
                    if isinstance(device_list, list) and len(device_list) > 0:
                        device_obj = device_list[0]
                        if isinstance(device_obj, dict):
                            if "Temperatures" not in device_obj:
                                device_obj["Temperatures"] = [{"desired": device_value}]
                            elif len(device_obj["Temperatures"]) > 0:
                                device_obj["Temperatures"][0]["desired"] = device_value
            elif op.id in (
                "fan",
                "fan_mode",
                "fan_max",
                "swing",
                "swing_mode",
                "good_sleep",
                "preset_mode",
                ATTR_FAN_MODE,
                ATTR_SWING_MODE,
                ATTR_PRESET_MODE,
            ):
                if is_2878:
                    if op.id in ("fan", "fan_mode", ATTR_FAN_MODE):
                        device_key = "AC_FUN_WINDLEVEL"
                    else:
                        device_key = self._get_cached_device_key_from_prop(op)
                    if device_key:
                        reconstructed_state[device_key] = device_value
                else:
                    device_list = reconstructed_state.get("Devices")
                    if isinstance(device_list, list) and len(device_list) > 0:
                        device_obj = device_list[0]
                        if isinstance(device_obj, dict):
                            if op.id in ("fan", "fan_mode", ATTR_FAN_MODE):
                                if "Wind" not in device_obj:
                                    device_obj["Wind"] = {}
                                device_obj["Wind"]["speedLevel"] = (
                                    int(device_value)
                                    if str(device_value).isdigit()
                                    else device_value
                                )
                            elif op.id in ("fan_max",):
                                if "Wind" not in device_obj:
                                    device_obj["Wind"] = {}
                                device_obj["Wind"]["maxSpeedLevel"] = (
                                    int(device_value)
                                    if str(device_value).isdigit()
                                    else device_value
                                )
                            elif op.id in ("swing", "swing_mode", ATTR_SWING_MODE):
                                if "Wind" not in device_obj:
                                    device_obj["Wind"] = {}
                                device_obj["Wind"]["direction"] = device_value
                            elif op.id in ("preset_mode", ATTR_PRESET_MODE):
                                if "Mode" not in device_obj:
                                    device_obj["Mode"] = {}
                                if "options" not in device_obj["Mode"]:
                                    device_obj["Mode"]["options"] = [device_value]
                                elif len(device_obj["Mode"]["options"]) > 0:
                                    device_obj["Mode"]["options"][0] = str(device_value)
                            elif op.id == "good_sleep":
                                if "Mode" not in device_obj:
                                    device_obj["Mode"] = {}
                                if "options" not in device_obj["Mode"]:
                                    device_obj["Mode"]["options"] = [
                                        "Comode_Off",
                                        f"Sleep_{int(float(device_value))}",
                                    ]
                                elif len(device_obj["Mode"]["options"]) > 1:
                                    device_obj["Mode"]["options"][
                                        1
                                    ] = f"Sleep_{int(float(device_value))}"
                                elif len(device_obj["Mode"]["options"]) == 1:
                                    device_obj["Mode"]["options"].append(
                                        f"Sleep_{int(float(device_value))}"
                                    )
            else:
                device_key = self._get_cached_device_key_from_prop(op)
                if device_key:
                    reconstructed_state[device_key] = device_value

        return reconstructed_state

    def _calculate_structured_state(
        self, raw_state: dict[str, Any]
    ) -> ClimateIPDeviceState | None:
        """
        Pure dry-run calculation of the ClimateIPDeviceState from raw data.
        Does NOT mutate properties or internal controller state.
        Returns None if validation fails or a critical exception occurs during parsing.
        """
        if not self.controller.loader.is_fully_initialized:
            return None

        try:
            # Map YAML operation IDs to ClimateIPDeviceState attributes.
            # Using a simplified version of the logic in climate_state property.
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
            prop_values = {
                mapping.get(prop.id, prop.id): prop.calculate_value_from_state(
                    raw_state
                )
                for prop in all_properties
            }

            # Also need to handle available modes lists which are dynamic

            return ClimateIPDeviceState(
                hvac_mode=prop_values.get("hvac_mode"),
                target_temperature=prop_values.get("target_temperature"),
                current_temperature=prop_values.get("current_temperature"),
                fan_mode=prop_values.get("fan_mode"),
                swing_mode=prop_values.get("swing_mode"),
                preset_mode=prop_values.get("preset_mode"),
                # Mode lists are harder to calculate purely without side-effects
                # because they often depend on the controller's current property state.
                # In this atomic update, we prioritize the values.
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s [AtomicMerge] Dry-run calculation failed: %s",
                self.controller.log_prefix,
                e,
            )
            return None

    async def async_merge_device_state(
        self, new_data: dict[str, Any], _is_response: bool, _is_update: bool
    ) -> bool:
        """
        Merge a partial state update (e.g. from a push notification) into the known state.
        Returns True if the update was accepted and committed, False otherwise.
        """
        if not new_data:
            return False

        current_hass_state = None
        if hasattr(self.controller, "get_current_state_callback") and self.controller.get_current_state_callback:
            current_hass_state = self.controller.get_current_state_callback()
        if not current_hass_state:
            if not self.controller.loader.state_getter:
                return False
            base_raw_state = self.controller.loader.state_getter.value
        else:
            base_raw_state = await self._build_device_state_from_hass(
                current_hass_state
            )

        if base_raw_state is None:
            return False

        # 1. Clone & Apply (Candidate State)
        candidate_state = copy.deepcopy(base_raw_state)
        candidate_state.update(new_data)

        # 2. Validate (Dry-Run Calculation)
        structured_candidate = self._calculate_structured_state(candidate_state)

        if structured_candidate is None:
            _LOGGER.warning(
                "%s [AtomicMerge] Push update discarded: dry-run validation failed for payload: %s",
                self.controller.log_prefix,
                new_data,
            )
            return False

        # 3. Commit Phase
        _LOGGER.debug(
            "%s [AtomicMerge] Committing push update to global state.",
            self.controller.log_prefix,
        )

        # Evict pending-update optimism for any property that the push explicitly supersedes.
        # This is critical for sequences like:
        #   user sets fan_only → pending_updates["hvac_mode"] = ('fan_only', t)
        #   remote turns AC off → push {"AC_FUN_POWER": "Off"}
        # Without eviction the pending would override the template and keep showing fan_only.
        self._evict_invalidated_pending_updates(new_data)

        # Update raw cache in state_getter
        if self.controller.loader.state_getter:
            # pylint: disable=import-outside-toplevel,protected-access
            self.controller.loader.state_getter._value = candidate_state

        # Update all property objects (side-effects) — force_update=True bypasses dirty check.
        await self.async_update_properties_from_state(
            candidate_state, force_update=True, current_hass_state=current_hass_state
        )

        return True

    def _evict_invalidated_pending_updates(self, push_data: dict[str, Any]) -> None:
        """Remove pending-update entries whose device-key is now superseded by the push payload.

        Pending updates represent optimistic UI predictions from user commands.  When the
        device sends an explicit push that touches the same raw key (or when AC_FUN_POWER
        turns Off, invalidating any active-mode prediction), we must evict the stale pending
        so the template can render the true device state.
        """
        if not self._pending_updates:
            return

        # Build a reverse map: device_key → prop.id for currently pending props
        pending_ids = list(self._pending_updates.keys())
        invalidated: set[str] = set()

        for prop_id in pending_ids:
            prop = self.controller.loader.operations.get(
                prop_id
            ) or self.controller.loader.properties.get(prop_id)
            if not prop:
                continue

            device_key = self._get_cached_device_key_from_prop(prop)

            # Case 1: the push itself contains the exact device key → push wins
            if device_key and device_key in push_data:
                invalidated.add(prop_id)
                continue

            # Case 2: AC power turned off → any active-mode pending is moot
            if push_data.get("AC_FUN_POWER") == "Off" and prop_id in (
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
            _LOGGER.debug(
                "%s [AtomicMerge] Evicting stale pending update for '%s' (push superseded it).",
                self.controller.log_prefix,
                prop_id,
            )
            self._pending_updates.pop(prop_id, None)

    def _get_cached_device_key_from_prop(self, prop: Any) -> str | None:
        """Extract and cache the raw JSON key mapped to a specific property from its template."""
        prop_id = prop.id
        if prop_id in self._prop_template_key_cache:
            return self._prop_template_key_cache[prop_id]

        key = self._get_device_key_from_template(prop.status_template)
        self._prop_template_key_cache[prop_id] = key
        return key

    def _get_device_key_from_template(self, template_obj: Any) -> str | None:
        """Extract the JSON key from a Jinja template string using regex."""
        if not template_obj:
            return None
        template_string = (
            template_obj.template
            if hasattr(template_obj, "template")
            else str(template_obj)
        )
        if not template_string:
            return None

        match = self._device_state_key_regex.search(template_string)
        if match:
            return match.group(2) or match.group(3)
        return None

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
        # Clear any stale pending update for the property being changed to ensure
        # the prediction uses the new intended value rather than a previous command's ghost.
        if property_name in self._pending_updates:
            del self._pending_updates[property_name]

        for op in list(self.controller.loader.operations.values()):
            hass_attr = self._get_hass_attr_for_op_id(op.id)
            if hasattr(current_hass_state, hass_attr):
                # pylint: disable=import-outside-toplevel,protected-access
                op._value = getattr(current_hass_state, hass_attr)
        for prop in list(self.controller.loader.properties.values()):
            hass_attr = self._get_hass_attr_for_op_id(prop.id)
            if hasattr(current_hass_state, hass_attr):
                # pylint: disable=import-outside-toplevel,protected-access
                prop._value = getattr(current_hass_state, hass_attr)

        prop_to_change = self.controller.loader.operations.get(property_name)
        if not prop_to_change:
            _LOGGER.debug(
                "%s [Predict] prop_to_change for '%s' is None. Returning early.",
                self.controller.log_prefix,
                property_name,
            )
            return ClimateEntityFeature(0), {}

        _LOGGER.debug(
            "%s [Predict] prop_to_change found: %s. Setting its _value to: %s",
            self.controller.log_prefix,
            prop_to_change.id,
            new_value,
        )
        # pylint: disable=import-outside-toplevel,protected-access
        prop_to_change._value = new_value

        future_state = await self._build_device_state_from_props()
        if not future_state:
            _LOGGER.debug(
                "%s [Predict] future_state is empty. Returning early.",
                self.controller.log_prefix,
            )
            return ClimateEntityFeature(0), {}

        _LOGGER.debug(
            "%s [Predict] Initial future_state built from props: %s",
            self.controller.log_prefix,
            future_state,
        )

        # future_state is already populated by _build_device_state_from_props
        # which now iterates through all properties and gracefully handles complex cases
        _LOGGER.debug(
            "%s [Predict] Future_state built and values injected.",
            self.controller.log_prefix,
        )

        update_result = await self.async_update_properties_from_state(
            future_state, is_prediction=True, current_hass_state=current_hass_state
        )
        corrections.update(update_result)

        return ClimateEntityFeature(0), corrections

    async def async_shutdown(self) -> None:
        """Shut down the poller and cleanly close any active connections."""
        conn = self.controller.loader.connection
        if conn:
            _LOGGER.debug("%s Shutting down connection...", self.controller.log_prefix)

            async def _try(coro):  # pylint: disable=invalid-name
                try:
                    await coro
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

            if hasattr(conn, "stop_listening"):
                await _try(conn.stop_listening())

            raw_client = getattr(  # pylint: disable=protected-access
                self.controller, "_shared_raw_client", None
            )
            if raw_client:
                await _try(raw_client.close())
                self.controller._shared_raw_client = (
                    None  # pylint: disable=protected-access
                )

            if hasattr(conn, "close"):
                await _try(conn.close())
            self.controller.loader.connection = None

        await asyncio.sleep(1.0)
