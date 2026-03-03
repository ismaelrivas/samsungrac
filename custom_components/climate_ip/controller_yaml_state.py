import aiofiles
import asyncio
import time

from homeassistant.components.climate import ClimateEntityFeature, HVACMode, ATTR_HVAC_MODE
import copy
import re
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.entity_component
from homeassistant.helpers import config_entry_oauth2_flow
import voluptuous as vol
import yaml
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    ATTR_TEMPERATURE,
    CONF_MAC,
    CONF_IP_ADDRESS,
    CONF_TOKEN,
    STATE_ON,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util.dt import now
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from requests.exceptions import RequestException
from homeassistant.helpers.update_coordinator import UpdateFailed

from .connection import CLIMATE_IP_CONNECTIONS
from .controller import ATTR_POWER, ClimateController, register_controller
from .properties import DeviceProperty, create_property, create_status_getter
from .state import ClimateIPDeviceState
from .const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_8888_GROUP,
    DEVICE_TYPE_AIOHTTP_SUPPORTED,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    CONF_CONN_METHOD,
    CONN_METHOD_AIOHTTP,
    CONN_METHOD_REQUESTS,
    CONN_METHOD_RAW,
    DOMAIN,
)
from .exceptions import CannotConnect, AuthError, InvalidHeaderError
from .helpers import stream_wrapper, get_value_by_path, mask_sensitive_data
from .const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONFIG_DEVICE,
    CONFIG_DEVICE_ATTRIBUTES,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_OPERATIONS,
    CONFIG_DEVICE_OPERATION_VALUES,
    CONFIG_DEVICE_SWITCHES,
    CONFIG_DEVICE_SENSORS,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_STATUS,
    CONFIG_DEVICE_CONNECTION_TYPE,
    DEFAULT_CONF_TEMP_UNIT,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
)

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = "yaml"
from .const import MAX_GET_STATUS_RETRIES

# Exception and update coordinator imports for state management.
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

class YamlControllerStateMixin:
    """Mixin for state management and polling."""

    async def _refresh_smartthings_token(self) -> Optional[str]:
        """
        Refreshes the SmartThings access token using the official integration's
        OAuth2 session helper. This handles expiration checks, clock skew (20s),
        and token refreshing automatically.
        """
        try:
            # 1. Find the SmartThings config entry
            entries = self.hass.config_entries.async_entries("smartthings")
            if not entries:
                _LOGGER.debug("%s [Auth] No Official SmartThings config entries found.", self.log_prefix)
                return None
            
            # Use the first entry found
            entry = entries[0]
            
            # 2. Get the OAuth2 implementation and create a session
            implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
                self.hass, entry
            )
            session = config_entry_oauth2_flow.OAuth2Session(self.hass, entry, implementation)

            # 3. Force validation (refresh if needed)
            # async_ensure_token_valid() checks expiration + clock skew
            await session.async_ensure_token_valid()
            
            # 4. Return the (potentially new) access token
            token = session.token.get("access_token")
            # Log masked token for debugging
            masked = f"***{token[-6:]}" if token and len(token) > 6 else "None"
            _LOGGER.debug("%s [Auth] OAuth2 session token validated. Token: %s", self.log_prefix, masked)
            
            return token

        except Exception as e:
            _LOGGER.error("%s [Auth] Error refreshing SmartThings token via OAuth2: %s", self.log_prefix, e)
            return None

    def _update_all_connections_token(self, new_token: str):
        """Iterates through all properties and updates their connection token."""
        _LOGGER.debug("%s [Auth] Propagating new token to all connections.", self.log_prefix)
        # Collect all properties
        all_props = [self._state_getter] if self._state_getter else []
        all_props.extend(self._operations.values())
        all_props.extend(self._sensors.values())

        # Use a set to update unique connection objects (avoid duplicate updates)
        updated_connections = set()

        for prop in all_props:
            if prop:
                conn = prop.get_connection(None)
                if conn and conn not in updated_connections:
                    if hasattr(conn, "update_auth_token"):
                        conn.update_auth_token(new_token)
                        updated_connections.add(conn)
        _LOGGER.debug("%s [Auth] Updated token for %d unique connection objects.", self.log_prefix, len(updated_connections))

    def _mask_sensitive_data(self, data: Any) -> Any:
        """Mask sensitive data in the device state for logging."""
        if isinstance(data, dict):
            masked = data.copy()
            if "uuid" in masked and isinstance(masked["uuid"], str) and len(masked["uuid"]) > 6:
                masked["uuid"] = "***" + masked["uuid"][-6:]
            
            # Recursively mask children
            for key, value in masked.items():
                if isinstance(value, (dict, list)):
                    masked[key] = self._mask_sensitive_data(value)
            return masked
        elif isinstance(data, list):
            return [self._mask_sensitive_data(item) for item in data]
        return data

    async def async_get_status(self) -> Optional[Dict[str, Any]]:
        """
        Fetches the device state. Uses a Short-Term Cache (TTL 2s) to avoid
        double polling when the Coordinator requests a refresh immediately after
        a Smart Poll update.
        """
        # --- SHORT-TERM CACHE LOGIC ---
        now_ts = time.time()
        if self._cached_device_state and (now_ts - self._last_state_fetch_time < 2.0):
             _LOGGER.debug(
                 "%s [Cache] Returning cached device state (TTL < 2s) to prevent double polling.", 
                 self.log_prefix
             )
             return self._cached_device_state.copy()
        # ------------------------------

        _LOGGER.debug("%s Polling device for state. Connection ID: %s, Prefix: %s", self.log_prefix, id(self._connection), self._connection.log_prefix)

        # Directly call async_update_state to ensure the most recent state is always fetched when requested.
        device_state = await self.async_update_state()
        return device_state.copy() if device_state else None

    async def async_update_state(self) -> Optional[Dict[str, Any]]: # This is the main polling function
        """
        Fetches the full device state from the physical device using the state_getter.
        This method also handles the one-time discovery of sub-devices.
        """
        # --- START OF FIX: Add null check for self._state_getter ---
        if not self._state_getter:
            raise UpdateFailed("State getter is not initialized, cannot update state.")
        # --- END OF FIX ---

        # --- DUAL-SPEED BACKOFF: PING GATE ---
        # Exclude port 2878 devices since they manage their own ping gate in `samsung_2878.py`
        if self._config.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_SAMSUNG_2878 and getattr(self, "_ip_address", None):
            try:
                from .helpers import async_check_network_reachability
                network_reachable = await async_check_network_reachability(self._ip_address, self.log_prefix)
                if not network_reachable:
                    # Increment failure counter explicitly for ping failures
                    self._consecutive_connection_errors += 1
                    
                    # Create a repair issue if the device is persistently offline (3 ping failures)
                    if self._consecutive_connection_errors == 3 and getattr(self, 'hass', None):
                        try:
                            from homeassistant.helpers.issue_registry import async_create_issue, IssueSeverity
                            async_create_issue(
                                self.hass,
                                "climate_ip",
                                f"connection_failed_{self._ip_address}",
                                is_fixable=False,
                                severity=IssueSeverity.WARNING,
                                translation_key="connection_failed",
                                translation_placeholders={
                                    "host": self._ip_address,
                                    "name": getattr(self, '_name', None) or self._ip_address
                                }
                            )
                        except Exception as e:
                            _LOGGER.debug("%s Failed to create repair issue on ping timeout: %s", self.log_prefix, e)

                    if self._consecutive_connection_errors >= 2:
                        raise CannotConnect("Host unreachable (ICMP ping failed). Device is persistently offline.")
                    else:
                        raise CannotConnect("Host unreachable (ICMP ping failed).")
            except Exception as diag_err:
                # If ping check throws some internal exception, don't fail the execution, let it try the socket
                if isinstance(diag_err, CannotConnect):
                    raise # Bubble up our intentionally raised exception
                _LOGGER.debug("%s Network diagnostic failed: %s", self.log_prefix, diag_err)
        # -------------------------------------

        try:
            full_device_state = await self._state_getter.async_update_state(None, self._debug)
            
            # --- CONNECTION ERROR COUNTER RESET ---
            if self._consecutive_connection_errors > 0:
                _LOGGER.info(
                    "%s Connection recovered after %d failure(s). Counter reset.", 
                    self.log_prefix, 
                    self._consecutive_connection_errors
                )
                self._consecutive_connection_errors = 0
                
                # --- START OF MODIFICATION: Resolve Repair Issue ---
                if getattr(self, 'hass', None):
                    try:
                        from homeassistant.helpers.issue_registry import async_delete_issue
                        async_delete_issue(
                            self.hass,
                            "climate_ip",
                            f"connection_failed_{self._ip_address}"
                        )
                        _LOGGER.debug("%s Successfully resolved/deleted repair issue on reconnection.", self.log_prefix)
                    except Exception as e:
                        _LOGGER.debug("%s Failed to delete repair issue: %s", self.log_prefix, e)
                # --- END OF MODIFICATION ---
            # --------------------------------------

        except AuthError:
            _LOGGER.info("%s [Auth] Authentication failed (401). Refreshing token via OAuth2Session...", self.log_prefix)
            new_token = await self._refresh_smartthings_token()
            
            if new_token and new_token != self._token:
                _LOGGER.info("%s [Auth] Automatically retrieved new Access Token from SmartThings integration.", self.log_prefix)
                self._token = new_token
                self._update_all_connections_token(new_token)
                
                # --- START OF MODIFICATION: Persist token to Config Entry ---
                if self.coordinator and self.coordinator.entry:
                    entry = self.coordinator.entry
                    # Update config entry data with new token
                    new_data = dict(entry.data)
                    new_data[CONF_TOKEN] = new_token
                    self.hass.config_entries.async_update_entry(entry, data=new_data)
                    _LOGGER.info("%s [Auth] Persisted new SmartThings token to Config Entry.", self.log_prefix)
                # --- END OF MODIFICATION ---

                # Retry the update with the new token
                try:
                    full_device_state = await self._state_getter.async_update_state(None, self._debug)
                    # Reset counter on successful retry
                    self._consecutive_connection_errors = 0
                except Exception as retry_exc:
                    raise UpdateFailed(f"Retry after token refresh failed: {retry_exc}") from retry_exc
            else:
                _LOGGER.info("%s [Auth] Token refresh failed. SmartThings integration may not be installed or configured.", self.log_prefix)
                # Raise ConfigEntryAuthFailed to trigger the Reconfiguration flow in Home Assistant
                raise ConfigEntryAuthFailed(
                    "Authentication failed. Please install and configure the official SmartThings integration to provide a valid token."
                )

        # --- EXPLICIT BUBBLE-UP FOR FALLBACK LOGIC ---
        except InvalidHeaderError:
             # This specific error (protocol violation) must bubble up to the coordinator
             # so it can trigger the auto-switch fallback to RAW engine.
             # We do NOT want it caught by the generic 'CannotConnect' handler below.
             raise
        # ---------------------------------------------

        except (RequestException, CannotConnect) as e:
            # --- TRANSIENT ERROR SUPPRESSION ---
            if "persistently offline" in str(e):
                self._consecutive_connection_errors = 2 # Force failure bypasses cache
            else:
                self._consecutive_connection_errors += 1
            
            if self._consecutive_connection_errors < 2 and self._cached_device_state:
                _LOGGER.debug(
                    "%s Connection failed (%d/2). Using cached state to prevent unavailability. Error: %s", 
                    self.log_prefix, 
                    self._consecutive_connection_errors,
                    e
                )
                return self._cached_device_state
            
            # Create a repair issue if the device is persistently offline (3 failures on the socket)
            if self._consecutive_connection_errors == 3 and getattr(self, 'hass', None):
                try:
                    from homeassistant.helpers.issue_registry import async_create_issue, IssueSeverity
                    async_create_issue(
                        self.hass,
                        "climate_ip",
                        f"connection_failed_{self._ip_address}",
                        is_fixable=False,
                        severity=IssueSeverity.WARNING,
                        translation_key="connection_failed",
                        translation_placeholders={
                            "host": self._ip_address,
                            "name": getattr(self, '_name', None) or self._ip_address
                        }
                    )
                except Exception as issue_e:
                    _LOGGER.debug("%s Failed to create repair issue on socket timeout: %s", self.log_prefix, issue_e)
            
            # If we reached here, it's either the 2nd failure OR we have no cache.
            # We raise the exception to mark the entity as unavailable.
            # Use a compact, user-friendly message — the HA coordinator will log it as ERROR.
            reason = str(e).split(":")[-1].strip() if ":" in str(e) else str(e)
            _LOGGER.warning(
                "%s Device unreachable (attempt %d). Marking as unavailable. Reason: %s",
                self.log_prefix, self._consecutive_connection_errors, reason
            )
            raise UpdateFailed(f"Device unreachable: {reason}") from e
            # -----------------------------------

        if full_device_state is None:
            if self._cached_device_state:
                 _LOGGER.debug("%s Failed to get latest state (API Error), using cached state to prevent unavailability.", self.log_prefix)
                 return self._cached_device_state
            
            raise UpdateFailed("Failed to get device state: No data received and no cache available")
        
        # --- CACHE UPDATE ---
        # We successfully fetched data, so we update the cache and timestamp here.
        # This allows async_get_status to utilize this data if called immediately after.
        self._cached_device_state = full_device_state
        self._last_state_fetch_time = time.time()
        # --------------------

        # --- One-time device discovery and initialization logic ---
        if not self._is_fully_initialized:
            try:
                device_type = self._config.get(CONF_DEVICE_TYPE)
                # Use the cached YAML for the current context (device_id is likely None here)
                id_map = self._parsed_yaml_cache.get(self._device_id, {}).get(CONFIG_DEVICE, {}).get("identifiers")
                
                if id_map:
                    _LOGGER.debug("%s 'identifiers' map found, running discovery", self.log_prefix)
                    self.discovered_devices = get_value_by_path(full_device_state, id_map.get("path_to_devices", []))
                    
                    if self.discovered_devices:
                        device_to_discover = None
                        
                        if device_type == DEVICE_TYPE_MIM_H03: # Special logic for MIM-H03
                            # For MIM-H03, find the coordinator unit (the one without a "Mode")
                            device_to_discover = next((d for d in self.discovered_devices if d and "Mode" not in d), None)
                            if not device_to_discover and self.discovered_devices:
                                # Fallback for older configs or different structures
                                device_to_discover = self.discovered_devices[0]
                        else: # Default for SAMSUNG_8888 and others
                            device_to_discover = self.discovered_devices[0] if self.discovered_devices else None
                        
                        if device_to_discover:
                            discovered_id = get_value_by_path(device_to_discover, id_map.get("id", []))
                            if discovered_id is not None:
                                self._device_id = str(discovered_id)
                            _LOGGER.info("%s Discovered device with id=%s", self.log_prefix, self._device_id)

                # Now that _device_id is potentially assigned, finish initialization
                await self._finish_initialization()

            except Exception as e:
                _LOGGER.error("%s Error during initial device discovery: %s", self.log_prefix, e, exc_info=True)
                # Do not return here, allow property update to proceed with what we have

        await self.async_update_properties_from_state(full_device_state)
        return self._state_getter.value

    async def async_update_properties_from_state(self, full_device_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Updates all properties from a given device state dictionary.
        If no state is provided, it reconstructs it from the current Home Assistant state.
        """
        if not self._is_fully_initialized:
            return {}

        # Check if coordinator exists before accessing its data.
        current_hass_state = self.coordinator.data if self.coordinator else None
        if not current_hass_state:
            _LOGGER.debug("%s Coordinator data is not available (normal during setup or first poll)", self.log_prefix)

        if full_device_state is None:
            _LOGGER.debug("%s [UpdateProps] No state provided, rebuilding from HASS for merge", self.log_prefix)
            if not current_hass_state:
                _LOGGER.error("%s [UpdateProps] Cannot rebuild state from HASS: coordinator data is null. Aborting update", self.log_prefix)
                return {} # ABORT
            full_device_state = await self._build_device_state_from_hass(current_hass_state)
        else:
            _LOGGER.debug("%s [UpdateProps] Using provided state (poll/prediction)", self.log_prefix)
        
        if full_device_state is None:
            _LOGGER.error("%s [UpdateProps] full_device_state is None, cannot update properties. Aborting", self.log_prefix)
            return {}

        device_to_process = full_device_state
        
        # --- START: Sub-device selection logic ---
        try:
            # Use the cached YAML for the current context
            id_map = self._parsed_yaml_cache.get(self._device_id, {}).get(CONFIG_DEVICE, {}).get("identifiers")
            
            if id_map:
                _LOGGER.debug("%s 'identifiers' map found. Searching in path: %s", self.log_prefix, id_map.get("path_to_devices", []))
                devices_list = get_value_by_path(full_device_state, id_map.get("path_to_devices", []))
                
                if devices_list:
                    _LOGGER.debug("%s Found %d devices in state. Selecting correct one.", self.log_prefix, len(devices_list))
                    
                    # Simplified logic: Take the first valid device
                    found_device = devices_list[0] if devices_list[0] else None
                    # Future improvement: select the device based on self._device_id
                    if found_device:
                        _LOGGER.debug("%s Success. 'device_to_process' is now the sub-device", self.log_prefix)
                        device_to_process = found_device
                    else:
                        _LOGGER.warning("%s 'devices_list' exists but the first element is empty or null", self.log_prefix)
                else:
                    _LOGGER.warning("%s 'identifiers' exists but the path '%s' did not return a list", self.log_prefix, id_map.get("path_to_devices", []))
            else:
                _LOGGER.debug("%s No 'identifiers' map. Using full state (normal for 2878)", self.log_prefix)

        except Exception as e:
            _LOGGER.error("%s Error during sub-device selection: %s. Using full state.", self.log_prefix, e, exc_info=True)
            device_to_process = full_device_state
        # --- END: Sub-device selection logic ---

        # --- START OF FIX: Store unwrapped state ---
        self._last_device_state = device_to_process
        # --- END OF FIX ---

        corrections = {}
        all_properties = list(self._operations.values()) + list(self._properties.values()) + list(self._sensors.values())
        _LOGGER.debug("%s Updating %d properties using device_state: %s", self.log_prefix, len(all_properties), str(mask_sensitive_data(device_to_process)))
        
        for prop in all_properties:
            try:
                # --- START OF FIX: Pending Updates Logic ---
                # Check if we have a pending optimistic update for this property.
                # If so, and it's recent (< 5 seconds), we skip the update from the (potentially stale) device state
                # and enforce the optimistic value. This prevents the "revert" effect in the UI.
                if prop.id in self._pending_updates:
                    pending_val, timestamp = self._pending_updates[prop.id]
                    if time.time() - timestamp < 5.0:
                        _LOGGER.debug(
                            "%s [UpdateProps] Skipping update for '%s' due to pending optimistic value: %s", 
                            self.log_prefix, prop.name, pending_val
                        )
                        # We must convert the pending value (which might be a float) to the internal format if needed,
                        # but usually op._value stores the HA representation.
                        # However, pending_val comes from async_set_property -> new_value.
                        # If new_value is what we sent, it should be compatible with op._value.
                        prop._value = pending_val 
                        continue
                    else:
                        # Expired, remove it
                        del self._pending_updates[prop.id]
                # --- END OF FIX ---

                await prop.async_update_state(device_to_process, self._debug)
            except Exception as e:
                _LOGGER.error("%s FAILED to update property '%s'. Error: %s", self.log_prefix, prop.name, e, exc_info=True)
        
        for prop in all_properties:
            if hasattr(prop, 'set_device_state_for_values'):
                prop.set_device_state_for_values(device_to_process)

        _LOGGER.debug("%s Checking for post-update state inconsistencies", self.log_prefix)
        for op_name, op in self._operations.items():
            # Skip auto-correction for properties that are not supported by the device
            if hasattr(op, 'is_valid') and not op.is_valid(device_to_process):
                continue
                
            if hasattr(op, 'values') and op.value is not None and op.value != STATE_UNKNOWN:
                if op.value not in op.values:
                    new_value = op.values[0] if op.values else STATE_UNKNOWN
                    _LOGGER.debug(
                        "%s State auto-correction for '%s'. Value '%s' is no longer valid in %s. Setting to '%s'.",
                        self.log_prefix, op.name, op.value, op.values, new_value,
                    )
                    op._value = new_value
                    corrections[op.id] = new_value

                    # If this auto-correction is for a property with a feature flag (like fan_mode),
                    # ensure the pending flicker flag is set so the coordinator can handle it on the next update.
                    if hasattr(op, '_feature_flag') and op._feature_flag == ClimateEntityFeature.FAN_MODE:
                        self._fan_modes_list_changed_pending_flicker = True

        self._rebuild_attributes()
        return corrections

    def _rebuild_attributes(self) -> None:
        """Rebuilds the _attributes dictionary from all properties."""
        self._attributes = {ATTR_NAME: self.name}
        all_properties = list(self._operations.values()) + list(self._properties.values())
        for prop in all_properties:
            self._attributes.update(prop.state_attributes)
        self._attributes["last_sync"] = now().strftime("%Y-%m-%d %H:%M:%S")

    async def _build_device_state_from_hass(self, hass_state: ClimateIPDeviceState) -> Optional[Dict[str, Any]]:
        """
        Converts a Home Assistant state object (ClimateIPDeviceState) back into a
        raw device state dictionary, similar to what self._state_getter.value would contain.
        This is essentially the inverse of async_update_properties_from_state.

        *** This function reads from the provided hass_state. ***
        """
        if not self._is_fully_initialized:
            _LOGGER.warning("%s Cannot convert HASS state to device state: controller not fully initialized", self.log_prefix)
            return None

        # --- START OF FIX: Add null check for self._state_getter ---
        if not self._state_getter:
            _LOGGER.warning("%s [HASS->DEV] Cannot build device state: state_getter is not initialized.", self.log_prefix)
            return None
        last_real_state = self._state_getter.value
        # --- END OF FIX ---
        if not last_real_state:
            _LOGGER.warning("%s [HASS->DEV] No previous real device state available to use as a template", self.log_prefix)
            return {}

        import json
        reconstructed_state = json.loads(json.dumps(last_real_state))

        all_props = list(self._operations.values()) + list(self._properties.values())

        for op in all_props:
            hass_value = getattr(hass_state, op.id, None)
        
            if hass_value is not None:                
                # This conversion is what matters for building the device state
                device_value = op.convert_hass_to_dev(hass_value)
                # Optimization: Use cached device key from template.
                device_key = self._get_cached_device_key_from_prop(op) # Get the key like 'AC_FUN_OPMODE'
                # --- START OF FIX: Ensure key exists before writing ---
                # Check if the key exists in the reconstructed state dictionary.
                if device_key and device_key in reconstructed_state:
                    reconstructed_state[device_key] = device_value
                # --- END OF FIX ---
                
        return reconstructed_state

    async def _build_device_state_from_props(self) -> Optional[Dict[str, Any]]: # Used for prediction
        """
        Builds a raw device state dictionary (template) using the current
        *internal* values of the properties (operations + attributes).
        This is the core of the optimistic update prediction.
        """
        # --- START OF FIX: Final robust state reconstruction ---
        # --- START OF FIX: Add null check for self._state_getter ---
        if not self._state_getter:
            _LOGGER.warning("%s [PROP->DEV] Cannot build device state: state_getter is not initialized.", self.log_prefix)
            return None
        last_real_state = self._state_getter.value
        # --- END OF FIX ---
        if not last_real_state:
            _LOGGER.warning("%s [PROP->DEV] No previous real device state available to use as a template", self.log_prefix)
            return {}

        import json
        reconstructed_state = json.loads(json.dumps(last_real_state))
        _LOGGER.debug("%s [PROP->DEV] Building future state from template: %s", self.log_prefix, str(reconstructed_state)[:200] + "...")

        # Now, iterate through all properties and inject their *current* internal values
        # into the reconstructed state. This ensures the new value (e.g., new temperature)
        # is present for the next step of the prediction.
        all_props = list(self._operations.values()) + list(self._properties.values())
        for op in all_props:
            device_key = self._get_cached_device_key_from_prop(op)
            if device_key and device_key in reconstructed_state and op.value is not None:
                reconstructed_state[device_key] = op.convert_hass_to_dev(op.value)

        return reconstructed_state

    async def async_merge_device_state(self, new_data: Dict[str, Any], is_response: bool, is_update: bool):
        """
        Combines a partial state update (from a push or a response) with the current state,
        rebuilding the full state from Home Assistant to ensure consistency.
        """
        if not new_data:
            _LOGGER.debug("%s async_merge_device_state called with no new data", self.log_prefix)
            return

        _LOGGER.debug("%s Merging partial state update (from push/response): %s", self.log_prefix, new_data)

        # --- START OF FIX: Add null check for self.coordinator ---
        current_hass_state = self.coordinator.data if self.coordinator else None
        # --- END OF FIX ---
        if not current_hass_state:
            _LOGGER.warning("%s Cannot merge state, coordinator data is not available", self.log_prefix)
            # --- START OF FIX: Add null check for self._state_getter ---
            if not self._state_getter:
                _LOGGER.error("%s Cannot get a base state for merging: state_getter is not initialized.", self.log_prefix)
                return
            base_state = self._state_getter.value  # Fallback to last known state
            # --- END OF FIX ---
        else:
            base_state = await self._build_device_state_from_hass(current_hass_state)
            _LOGGER.debug("%s Base state reconstructed from HASS: %s", self.log_prefix, base_state)     

        if base_state is None:
            _LOGGER.error("%s Could not get a base state for merging. Aborting.", self.log_prefix)
            return

        base_state.update(new_data) # Overwrite base state with new data
        _LOGGER.debug("%s Resulting merged state: %s", self.log_prefix, base_state)
        
        # --- START OF FIX: Add null check for self._state_getter ---
        if self._state_getter:
            self._state_getter._value = base_state
        else:
            _LOGGER.error("%s Cannot store merged state: state_getter is not initialized.", self.log_prefix)
            return
        # --- END OF FIX ---
        await self.async_update_properties_from_state(base_state)

    def _get_cached_device_key_from_prop(self, prop: Any) -> Optional[str]:
        """
        Gets the device state key from a property's template, using a cache
        to avoid repeated regex searches on the same template string.
        """
        prop_id = prop.id
        if prop_id in self._prop_template_key_cache:
            return self._prop_template_key_cache[prop_id]

        # Key not in cache, so we calculate and store it.
        key = self._get_device_key_from_template(prop.status_template)
        self._prop_template_key_cache[prop_id] = key
        return key

    def _get_device_key_from_template(self, template_obj: Any) -> Optional[str]:
        """
        Extracts the *primary* device state key (e.g., 'AC_FUN_OPMODE') 
        from a Home Assistant Template object.
        """
        if not template_obj:
            return None
        
        # Use .template attribute which holds the raw string.
        if hasattr(template_obj, 'template'):
            template_string = template_obj.template
        else:
            # Fallback for non-template objects, though less common.
            template_string = str(template_obj) 

        if not template_string:
            return None

        match = self._device_state_key_regex.search(template_string)
        if match:
            return match.group(2)
        
        # If no match, it's likely a complex template. This is not an error,
        # so we log at debug level instead of warning to keep logs clean.
        return None

    async def async_predict_and_correct_state(self, current_hass_state: ClimateIPDeviceState, property_name: str, new_value: Any) -> Tuple[ClimateEntityFeature, Dict[str, Any]]:
        """
        Predicts the device state after a change, performs corrections,
        and triggers feature flags if necessary.
        It now uses the current state from Home Assistant (via the coordinator) as the baseline.
        """
        _LOGGER.debug("%s [Predict] Starting prediction based on coordinator state: %s", self.log_prefix, str(current_hass_state))
        # --- START OF FIX: Add null check for self._state_getter ---
        if not self._state_getter:
            _LOGGER.warning("%s [Predict] Cannot predict state: state_getter is not initialized.", self.log_prefix)
            return ClimateEntityFeature(0), {}
        last_real_state = self._state_getter.value
        # --- END OF FIX ---

        if not self._is_fully_initialized:
            _LOGGER.info("%s [Predict] Cannot predict state: controller not fully initialized", self.log_prefix)
            return ClimateEntityFeature(0), {}
            
        if not last_real_state:
            _LOGGER.info("%s [Predict] Cannot predict state: last real state is unavailable", self.log_prefix)
            return ClimateEntityFeature(0), {}
        
        corrections = {}

        _LOGGER.debug("%s [Predict] Simulating state change: %s -> %s", self.log_prefix, property_name, new_value)

        
        original_values = {
            op_name: (op.value.value if isinstance(op.value, HVACMode) else op.value)
            for op_name, op in self._operations.items()
        }

        _LOGGER.debug("%s [Predict] Syncing internal properties to current HASS state before prediction", self.log_prefix)
        for op in self._operations.values():
            if hasattr(current_hass_state, op.id):
                op._value = getattr(current_hass_state, op.id)
        for prop in self._properties.values():
            if hasattr(current_hass_state, prop.id):
                prop._value = getattr(current_hass_state, prop.id)


        prop_to_change = self._operations.get(property_name)
        if not prop_to_change:
            _LOGGER.warning("%s [Predict] Property '%s' not found for prediction", self.log_prefix, property_name)
            return ClimateEntityFeature(0), {}
        
        # --- START OF LOGGING ---
        _LOGGER.debug("%s [Predict] New value for '%s' is %s (type: %s)", self.log_prefix, property_name, new_value, type(new_value).__name__)
        # --- END OF LOGGING ---
        
        prop_to_change._value = new_value
        _LOGGER.debug("%s [Predict] Applied change to internal property '%s'", self.log_prefix, property_name)

        future_state = await self._build_device_state_from_props()
        if not future_state:
            _LOGGER.error("%s [Predict] Failed to reconstruct future state from internal properties", self.log_prefix)
            return ClimateEntityFeature(0), {}

        try:
            device_value = prop_to_change.convert_hass_to_dev(new_value)
            
            # Optimization: Use cached device key from template
            device_key = self._get_cached_device_key_from_prop(prop_to_change)
            
            if device_key:
                if device_key in future_state:
                    _LOGGER.debug("%s [Predict] Auto-injecting '%s' into key '%s' (from cached template key)", self.log_prefix, device_value, device_key)
                    future_state[device_key] = device_value
                else:
                    _LOGGER.warning("%s [Predict] Auto-key '%s' found for '%s', but key not in state. Falling back to manual logic.", self.log_prefix, device_key, property_name)
                    device_key = None # Invalidate key to trigger manual logic
            else:
                _LOGGER.debug("%s [Predict] Auto-key failed for '%s' (template complex?). Using manual logic", self.log_prefix, property_name)

            if device_key is None:
                if property_name == ATTR_TEMPERATURE:
                    _LOGGER.debug("%s [Predict] Manual-injecting temperature: %s", self.log_prefix, new_value)
                    device_list = future_state.get('Devices')
                    if isinstance(device_list, list) and len(device_list) > 0:
                        device_obj = device_list[0]
                        if isinstance(device_obj, dict) and 'Temperatures' in device_obj:
                            device_obj['Temperatures'][0]['desired'] = new_value
                        else:
                            _LOGGER.warning("%s [Predict] 'Temperatures' key missing inside 'Devices' list.", self.log_prefix)
                    elif 'AC_FUN_TEMPSET' in future_state:
                        _LOGGER.debug("%s [Predict] Manual-injecting for 2878-style device into AC_FUN_TEMPSET", self.log_prefix)
                        future_state['AC_FUN_TEMPSET'] = str(new_value)
                    else:
                        _LOGGER.warning("%s [Predict] Manual prediction failed. Neither 'Devices' nor 'AC_FUN_TEMPSET' found.", self.log_prefix)

                elif property_name == ATTR_HVAC_MODE:
                    if 'AC_FUN_OPMODE' in future_state:
                        _LOGGER.debug("%s [Predict] Manual-injecting hvac_mode: %s into AC_FUN_OPMODE", self.log_prefix, device_value)
                        future_state['AC_FUN_OPMODE'] = device_value
                    else:
                        _LOGGER.debug("%s [Predict] Manual hvac_mode prediction failed, 'AC_FUN_OPMODE' key missing", self.log_prefix)

                else:
                    _LOGGER.debug("%s [Predict] Auto-key failed and no manual logic exists for '%s'. Prediction may be inaccurate", self.log_prefix, property_name)
        
        except Exception as e:
            _LOGGER.error("%s [Predict] Error while writing prediction: %s", self.log_prefix, e)

        _LOGGER.debug("%s [Predict] Updating properties with simulated future state: %s", self.log_prefix, str(future_state)[:200] + "...")
        corrections.update(await self.async_update_properties_from_state(future_state))
        
        return ClimateEntityFeature(0), corrections

    async def async_shutdown(self):
        """
        Shutdown the controller and its underlying connection.
        This is called when the coordination/integration is being unloaded.
        """
        if self._connection:
            _LOGGER.debug("%s Shutting down controller and connection...", self.log_prefix)
            
            # Stop listening if applicable (for 2878/socket connections)
            if hasattr(self._connection, "stop_listening"):
                try:
                    await self._connection.stop_listening()
                except Exception as e:
                     _LOGGER.warning("%s Error stopping listener during shutdown: %s", self.log_prefix, e)

            # FORCE CLOSE SHARED CLIENT (if exists) before connection wrapper
            if hasattr(self, "_shared_raw_client") and self._shared_raw_client:
                _LOGGER.debug("%s [SHUTDOWN] Force closing shared raw client...", self.log_prefix)
                try:
                    await self._shared_raw_client.close()
                except Exception as e:
                    _LOGGER.error("%s [SHUTDOWN] Error closing shared raw client: %s", self.log_prefix, e)
                finally:
                    self._shared_raw_client = None

            # Close the connection
            if hasattr(self._connection, "close"):
                try:
                    await self._connection.close()
                except Exception as e:
                    _LOGGER.error("%s Error closing connection during shutdown: %s", self.log_prefix, e)
            
            self._connection = None
        
        # Add a short delay to allow the network stack to fully release the socket/port
        # before a potential immediate reload tries to bind/connect again.
        await asyncio.sleep(1.0)
        
        _LOGGER.debug("%s Controller shutdown complete.", self.log_prefix)

