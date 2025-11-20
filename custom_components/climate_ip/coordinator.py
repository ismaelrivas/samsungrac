"""DataUpdateCoordinator for the Samsung Climate integration."""
import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, Platform
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.components.climate import ClimateEntityFeature
from .exceptions import CannotConnect, AuthError, InvalidHeaderError, ConnectionRefused
from .state import ClimateIPDeviceState, HVACMode

from .const import DOMAIN, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, CONF_NAME, CONF_CONN_METHOD, CONN_METHOD_REQUESTS

_LOGGER = logging.getLogger(__name__)

class SamsungClimateCoordinator(DataUpdateCoordinator):
    """Manages data fetching for Samsung Climate devices."""

    def __init__(self, hass, controller, entry: ConfigEntry):
        """Initialize the data coordinator."""
        self.controller = controller
        self.entry = entry
        self._entity = None  # Reference to the ClimateIP entity

        # Give the controller a reference back to this coordinator.
        self.controller.coordinator = self

        # Determine the update interval from the config entry's options,
        # falling back to the entry's data, and finally to the default.
        poll_interval_seconds = entry.options.get(
            CONF_POLL_INTERVAL, entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )
        update_interval = timedelta(seconds=poll_interval_seconds) if controller.poll else None

        _LOGGER.debug("%s Initializing coordinator with update interval: %s", self.log_prefix, update_interval)

        super().__init__(
            hass,
            _LOGGER,
            name=f"Samsung Climate {self.log_prefix}",
            update_interval=update_interval,
            always_update=True,
        )

        # --- START OF FIX ---
        # Centralize DeviceInfo creation in the coordinator.
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=self.entry.data.get(CONF_NAME, f"Samsung AC {self.unique_id}"),
            manufacturer="Samsung",
        )
        # --- END OF FIX ---

        # Start the connection listener if it's a push-based device
        if self.is_push_device:
            _LOGGER.debug("%s Device is push-based, starting connection listener.", self.log_prefix)
            self.controller.connection.start_listening()

    def register_entity(self, entity):
        """Register the climate entity instance."""
        self._entity = entity

    def unregister_entity(self, entity):
        """Unregister the climate entity instance."""
        self._entity = None

    async def _async_update_data(self) -> ClimateIPDeviceState:
        """Fetch the latest state from the device."""
        try:
            # The controller gets and processes the device state.
            await asyncio.wait_for(
                self.controller.async_get_status(), timeout=30.0
            )
            return self._create_device_state()
        
        except InvalidHeaderError as err:
            # --- START OF SOLUTION: Automatically switch to the 'requests' engine ---
            _LOGGER.warning(
                "%s Malformed header error detected! Automatically switching to the 'Legacy (requests)' connection engine.",
                self.log_prefix
            )
            # Get the current options and create a mutable copy.
            new_options = dict(self.entry.options) 
            # Switch to the 'requests' engine.
            new_options[CONF_CONN_METHOD] = CONN_METHOD_REQUESTS
            
            # Update the config entry with the new options.
            # This will trigger the 'update_listener', which will reload the integration.
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            
            # Raise UpdateFailed to cleanly stop the current poll, allowing the integration reload
            # to take over without logging a setup error.
            raise UpdateFailed("Switching to 'Legacy' connection engine due to non-standard HTTP headers. Reload is in progress.")

        except (AuthError, ConfigEntryAuthFailed) as err:
            # This will stop further polling and prompt for re-authentication.
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err

        except (CannotConnect, ConnectionRefusedError, asyncio.TimeoutError) as err:
            # The coordinator will log this and schedule a retry.
            raise UpdateFailed(f"Failed to fetch device state: {err}") from err

        except Exception as err:
            _LOGGER.error("%s Unexpected error during update", self.log_prefix, exc_info=True)
            raise UpdateFailed(f"An unexpected error occurred: {err}") from err

    async def async_handle_push_update(self, new_data: Optional[Dict[str, Any]] = None) -> None:
        """Handle a state update received via push from the connection."""
        try:
            _LOGGER.debug("%s Push update received with data: %s", self.log_prefix, new_data)

            if new_data:
                # Use the merge logic in the controller.
                await self.controller.async_merge_device_state(new_data, is_response=False, is_update=True)

                # Check if the fan mode list changed during the state update.
                if self.controller._fan_modes_list_changed_pending_flicker:
                    _LOGGER.debug("%s Fan modes list changed. Triggering UI flicker", self.log_prefix)
                    if self._entity:
                        # Flicker OFF
                        await self._entity.async_flicker_feature(ClimateEntityFeature.FAN_MODE, False)
                        await asyncio.sleep(0.1)  # Short delay for UI to process the change.
                        # Flicker ON
                        await self._entity.async_flicker_feature(ClimateEntityFeature.FAN_MODE, True)
                    # Reset the flag after handling it.
                    self.controller._fan_modes_list_changed_pending_flicker = False

                # Create the new state object and notify listeners.
                updated_state = self._create_device_state()
                self.async_set_updated_data(updated_state)
            else:
                _LOGGER.debug("%s Push update did not contain state data, skipping processing", self.log_prefix)

        except Exception as err:
            _LOGGER.error("%s Unexpected error during push update: %s", self.log_prefix, err, exc_info=True)

    def _create_device_state(self) -> ClimateIPDeviceState:
        """Create a ClimateIPDeviceState object from the controller's current properties."""
        hvac_val = self.controller.get_property(ATTR_HVAC_MODE)
        try:
            hvac_enum = HVACMode(hvac_val) if hvac_val else None
        except ValueError:
            _LOGGER.warning("%s Invalid HVAC value '%s' received from controller. Treating as None", self.log_prefix, hvac_val)
            hvac_enum = None

        # Ensure the list of HVAC modes consists of enums, not strings.
        hvac_modes_str = self.controller.state_attributes.get(ATTR_HVAC_MODES, [])
        hvac_modes_enum = []
        for mode_str in hvac_modes_str:
            try:
                hvac_modes_enum.append(HVACMode(mode_str))
            except ValueError:
                _LOGGER.warning("%s Invalid HVAC mode '%s' found in available modes list. Skipping", self.log_prefix, mode_str)

        a = ClimateIPDeviceState(
            hvac_mode=hvac_enum,
            target_temperature=self.controller.get_property(ATTR_TEMPERATURE),
            current_temperature=self.controller.get_property(ATTR_CURRENT_TEMPERATURE),
            fan_mode=self.controller.get_property(ATTR_FAN_MODE),
            swing_mode=self.controller.get_property(ATTR_SWING_MODE),
            preset_mode=self.controller.get_property(ATTR_PRESET_MODE),
            hvac_modes=hvac_modes_enum,
            fan_modes=self.controller.state_attributes.get(ATTR_FAN_MODES, []),
            swing_modes=self.controller.state_attributes.get(ATTR_SWING_MODES, []),
            preset_modes=self.controller.state_attributes.get(ATTR_PRESET_MODES, []),
        )

        _LOGGER.debug("%s Created device state: %s", self.log_prefix, a)
        return a

    async def async_set_property(self, property_name: str, new_value: Any, corrections: Optional[Dict[str, Any]] = None, device_id: Optional[str] = None):
        """Set a property and force a refresh."""
        try:
            # Combine the main command with any corrections.
            properties_to_set = {property_name: new_value}
            if corrections:
                properties_to_set.update(corrections)

            _LOGGER.debug("%s Setting properties: %s", self.log_prefix, properties_to_set)

            # Send commands sequentially to maintain order.
            success = True
            for prop, val in properties_to_set.items():
                # If this property was part of the corrections dictionary,
                # it's assumed that the main property's command already handled it.
                # We skip sending a separate command for it to avoid duplication.
                if corrections and prop in corrections and prop != property_name:
                    _LOGGER.debug("%s Skipping redundant command for corrected property '%s'", self.log_prefix, prop)
                    continue

                # Ensure HVACMode enums are converted to string values for the command.
                if isinstance(val, HVACMode):
                    val = val.value

                if not await self.controller.async_set_property(prop, val, device_id):
                    success = False

            if success:
                if not self.is_push_device:
                    _LOGGER.debug("%s Command successful, waiting 2.5s for device to update before refreshing state", self.log_prefix)
                    await asyncio.sleep(2.5)
                    await self.async_refresh()
            else:
                _LOGGER.debug("%s Not all properties were set successfully", self.log_prefix)
        except Exception as err:
            _LOGGER.error(
                "%s Error setting properties: %s", self.log_prefix, err, exc_info=True
            )
            raise UpdateFailed(f"Failed to set property {property_name}: {err}") from err

    async def async_predict_and_correct(self, current_state: ClimateIPDeviceState, property_name: str, new_value: Any) -> Tuple[ClimateEntityFeature, Dict[str, Any]]:
        """Passthrough for the controller's prediction method."""
        if hasattr(self.controller, 'async_predict_and_correct_state'):
            # Ensure HVACMode enums are converted to string values.
            if isinstance(new_value, HVACMode):
                new_value = new_value.value

            changed_flags, corrections = await self.controller.async_predict_and_correct_state(current_state, property_name, new_value)
            return changed_flags, corrections
        else:
            _LOGGER.debug("%s Controller does not support state prediction", self.log_prefix)
            return ClimateEntityFeature(0), {}

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the controller."""
        return self.controller.log_prefix

    @property
    def unique_id(self) -> str:
        return self.controller.unique_id

    @property
    def operations(self) -> list:
        return self.controller.operations

    @property
    def attributes(self) -> list:
        return self.controller.attributes

    @property
    def is_push_device(self) -> bool:
        return self.controller.is_push_device

    @property
    def state_attributes(self) -> Dict[str, Any]:
        return self.controller.state_attributes

    @property
    def poll(self) -> bool:
        return self.controller.poll

    @property
    def temperature_unit(self) -> str:
        return self.controller.temperature_unit

    def get_property(self, property_name: str) -> Any:
        return self.controller.get_property(property_name)

    def get_property_object(self, property_name: str) -> Optional[Any]:
        """Passthrough to get the actual property object from the controller."""
        return self.controller.get_property_object(property_name)
