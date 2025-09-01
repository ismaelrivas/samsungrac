"""DataUpdateCoordinator for the Samsung Climate integration."""
import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.core import callback
from .exceptions import CannotConnect

_LOGGER = logging.getLogger(__name__)

# --- Constants for the exponential backoff retry strategy ---
INITIAL_RETRY_DELAY = timedelta(seconds=10)
MAX_RETRY_DELAY = timedelta(minutes=5)
NORMAL_POLL_INTERVAL = timedelta(seconds=60)
RETRY_FACTOR = 2
MAX_COORDINATOR_RETRIES_BEFORE_RELOAD = 3

class SamsungClimateCoordinator(DataUpdateCoordinator):
    """
    Manages data fetching for Samsung Climate devices.

    Implements an exponential backoff retry strategy to handle
    connection failures robustly.
    """

    def __init__(self, hass, controller, entry: ConfigEntry):
        """Initialize the data coordinator."""
        self.controller = controller
        self.entry = entry
        self._retry_delay = INITIAL_RETRY_DELAY
        self._poll_timer: asyncio.TimerHandle | None = None
        self._coordinator_retries = 0
        
        super().__init__(
            hass,
            _LOGGER,
            name=f"Samsung Climate {self.log_prefix}",
            # Disable automatic polling to manage it manually.
            update_interval=None,
        )

    def _schedule_next_update(self, delay: timedelta) -> None:
        """Cancel any pending poll and schedule the next one."""
        if self._poll_timer:
            self._poll_timer.cancel()

        _LOGGER.debug("%s Scheduling next poll in %s seconds", self.log_prefix, delay.total_seconds())
        self._poll_timer = self.hass.loop.call_later(
            delay.total_seconds(),
            lambda: asyncio.create_task(self.async_request_refresh())
        )

    async def _async_update_data(self):
        """
        Fetch the latest state from the device and manage the retry logic.
        """
        # Clear the current timer as the update is running now.
        if self._poll_timer:
            self._poll_timer.cancel()
            self._poll_timer = None

        try:
            # Add a timeout to the update operation to prevent it from getting stuck.
            status = await asyncio.wait_for(
                self.controller.async_get_status(), timeout=30.0
            )
            
            # If the update succeeds, reset retry counters and schedule the next normal poll.
            if self._retry_delay != INITIAL_RETRY_DELAY or self._coordinator_retries > 0:
                _LOGGER.info("%s Connection to device re-established.", self.log_prefix)
                self._retry_delay = INITIAL_RETRY_DELAY
                self._coordinator_retries = 0
            
            self._schedule_next_update(NORMAL_POLL_INTERVAL)
            return status

        except (CannotConnect, asyncio.TimeoutError) as err:
            self._coordinator_retries += 1
            _LOGGER.error(
                "%s Error communicating with device (attempt %d). Retrying in %s seconds. Error: %s",
                self.log_prefix, self._coordinator_retries, self._retry_delay.total_seconds(), err
            )

            if self._coordinator_retries > MAX_COORDINATOR_RETRIES_BEFORE_RELOAD:
                _LOGGER.error(
                    "%s Maximum coordinator retries reached. Reloading integration to attempt a full recovery.",
                    self.log_prefix
                )
                self.hass.async_create_task(self.hass.config_entries.async_reload(self.entry.entry_id))
                # We still raise to mark unavailable until reload completes
                raise UpdateFailed(f"Failed to fetch device state after multiple retries: {err}") from err

            # If the connection manager has stopped, try restarting it.
            connection = self.controller.connection
            if connection and hasattr(connection, 'start_listening'):
                _LOGGER.info("%s Attempting to restart connection manager.", self.log_prefix)
                connection.start_listening()

            # Schedule the next retry with exponential backoff.
            self._schedule_next_update(self._retry_delay)
            self._retry_delay = min(self._retry_delay * RETRY_FACTOR, MAX_RETRY_DELAY)
            
            # Propagate the exception to mark the entity as unavailable.
            raise UpdateFailed(f"Failed to fetch device state: {err}") from err

        except Exception as err:
            # For any other unexpected error, log the full traceback for easier debugging.
            _LOGGER.exception(
                "%s Unexpected error during update. Retrying in %s seconds.",
                self.log_prefix, self._retry_delay.total_seconds()
            )
            self._schedule_next_update(self._retry_delay)
            self._retry_delay = min(self._retry_delay * RETRY_FACTOR, MAX_RETRY_DELAY)

            # Propagate the exception.
            raise UpdateFailed(f"An unexpected error occurred: {err}") from err

    async def async_handle_push_update(self) -> None:
        """
        Handle a state update received via push from the connection.
        """
        _LOGGER.debug("%s Push update received.", self.log_prefix)
        
        # If a push is received, the connection is alive. Reset retry counters.
        if self._retry_delay != INITIAL_RETRY_DELAY or self._coordinator_retries > 0:
            _LOGGER.info("%s Connection to device re-established (detected by push).", self.log_prefix)
            self._retry_delay = INITIAL_RETRY_DELAY
            self._coordinator_retries = 0
        
        # Reset the normal polling timer, as we just received fresh data.
        self._schedule_next_update(NORMAL_POLL_INTERVAL)
        
        connection = self.controller.connection
        if connection and hasattr(connection, '_device_status'):
            new_status = connection._device_status
            if new_status:
                await self.controller.async_update_properties_from_state(new_status)
                self.async_set_updated_data(new_status.copy())
            else:
                # This can happen if the push is just a keep-alive with no data
                _LOGGER.debug("%s Push update did not contain state data.", self.log_prefix)
        else:
            _LOGGER.warning("%s Could not access device state from connection during push update.", self.log_prefix)

    async def async_set_property(self, property_name: str, new_value: Any, device_id: str = None):
        """Set a property and force a refresh."""
        try:
            await self.controller.async_set_property(property_name, new_value, device_id)
            # After a command, force an immediate refresh to see the result.
            # The _async_update_data method will then reschedule the next poll.
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(
                "%s Error setting property '%s' to '%s'. Error: %s",
                self.log_prefix, property_name, new_value, err
            )
            # Optionally, re-raise as UpdateFailed to notify HA UI
            raise UpdateFailed(f"Failed to set property {property_name}: {err}") from err

    # --- Passthrough Properties and Methods ---
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
