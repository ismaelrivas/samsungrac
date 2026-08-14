"""DataUpdateCoordinator for the Samsung Climate integration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_CONN_METHOD,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_SSL_CONFIG_KEY,
    CONF_TOKEN_KEY,
    CONN_METHOD_RAW,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_DEVICE_NAME_PREFIX,
    DEFAULT_SUBDEVICE_NAME,
    DOMAIN,
    HARDWARE_BREATHING_ROOM_SEC,
    MANUFACTURER_SAMSUNG,
    NETWORK_POLL_TIMEOUT,
)
from .controller import ControllerInterface
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)


def _dispatch_to_loop(hass: HomeAssistant, func: Callable[[], None]) -> None:
    """Execute func directly if on main thread or in mock test loop, else delegate via call_soon_threadsafe."""
    try:
        running_loop = asyncio.get_running_loop()
        if hass.loop is running_loop or not isinstance(
            hass.loop, asyncio.AbstractEventLoop
        ):
            func()
            return
    except RuntimeError:
        pass
    hass.loop.call_soon_threadsafe(func)


class PropertyDebouncer:
    """Debounces outgoing commands per property to shield hardware from request flooding."""

    def __init__(
        self, coordinator: "SamsungClimateCoordinator", delay: float = 1.0
    ) -> None:
        """Initialize the property debouncer."""
        self.coordinator = coordinator
        self.delay = delay
        self._timers: dict[str, Callable[[], None]] = {}
        # 🛡️ Updated typing to include the Generation ID (int) at the end of the tuple
        self._pending_payloads: dict[str, tuple[Any, tuple, dict, int]] = {}
        self._last_activities: dict[str, float] = {}
        self._generation: int = 0  # 🛡️ The core of the Anti-Zombie Shield

    @property
    def hass(self) -> HomeAssistant:
        """Return the HomeAssistant instance from the coordinator."""
        return self.coordinator.hass

    @property
    def is_active(self) -> bool:
        """Return True if there are active debouncing timers or pending payloads."""
        return bool(self._timers or self._pending_payloads)

    def has_pending(self, property_name: str) -> bool:
        """Return True if a command for the given property is queued."""
        return property_name in self._pending_payloads

    def cancel_all(self) -> None:
        """Cancel all active timers, clear pending payloads, and poison active zombies."""
        self._generation += 1  # 💥 Global poisoning: any queued task will be invalidated
        
        _LOGGER.debug(
            "[Debouncer] Purge requested. Generation incremented to %s",
            self._generation
        )

        for unsub in self._timers.values():
            if unsub:
                unsub()
        self._timers.clear()
        self._pending_payloads.clear()

    async def async_execute(
        self, property_name: str, coroutine_func: Any, *args: Any, **kwargs: Any
    ) -> bool:
        """Execute a command with trailing debouncing per property."""
        now = time.monotonic()
        last_activity = self._last_activities.get(property_name, 0.0)

        # Immediate execution for turn-off commands (aborts any pending debounced commands across all properties)
        val = (
            kwargs.get("val")
            if "val" in kwargs
            else (args[1] if len(args) > 1 else None)
        )
        val_str = str(val).lower() if val is not None else ""
        is_turn_off = (
            property_name in ("hvac_mode", "power")
            and val_str in ("off", HVACMode.OFF.value)
        )

        if is_turn_off:
            _LOGGER.debug(
                "[Debouncer] Immediate turn-off requested for '%s'. Aborting all pending commands.",
                property_name,
            )
            self.cancel_all()
            self._last_activities[property_name] = now
            return await coroutine_func(*args, **kwargs)

        # Immediate execution if this specific property has not been modified within trailing window
        if now - last_activity >= self.delay:
            if property_name in self._timers:
                unsub = self._timers.pop(property_name)
                if unsub:
                    unsub()
            self._pending_payloads.pop(property_name, None)
            self._last_activities[property_name] = now
            _LOGGER.debug(
                "[Debouncer] Immediate execution for property '%s' with args=%s, kwargs=%s",
                property_name,
                args,
                kwargs,
            )  # pragma: no mutate
            return await coroutine_func(*args, **kwargs)

        # Rapid command for this property within trailing window: update timestamp and reset timer
        self._last_activities[property_name] = now
        if property_name in self._timers:
            unsub = self._timers.pop(property_name)
            if unsub:
                unsub()
            _LOGGER.debug(
                "[Debouncer] Resetting %.1fs countdown timer for property '%s'",
                self.delay,
                property_name,
            )  # pragma: no mutate

        # 🛡️ Package the payload with the CURRENT Generation ID
        self._pending_payloads[property_name] = (coroutine_func, args, kwargs, self._generation)

        def _fire_delayed(prop_or_now: Any = None) -> None:
            prop = prop_or_now if isinstance(prop_or_now, str) else property_name
            self._timers.pop(prop, None)
            payload = self._pending_payloads.pop(prop, None)

            if payload:
                # 🛡️ Unpack the generation ID captured when the task was queued
                func, p_args, p_kwargs, captured_generation = payload
                exec_time = time.monotonic()
                self._last_activities[prop] = exec_time
                _LOGGER.debug(
                    "[Debouncer] Executing delayed queued command for property: '%s'",
                    prop,
                )  # pragma: no mutate

                async def _task_runner() -> None:
                    # 🛡️ THE ANTI-ZOMBIE SHIELD: 
                    # The timer expired, but the background task just entered the Event Loop.
                    # We check if the user smashed another button invoking cancel_all() in the meantime.
                    if self._generation != captured_generation:
                        _LOGGER.debug(
                            "[Debouncer] 🧟 Zombie task intercepted and destroyed for '%s'. Task Gen: %s vs Current Gen: %s",
                            prop,
                            captured_generation,
                            self._generation,
                        )
                        return

                    try:
                        await func(*p_args, **p_kwargs)
                    except (TimeoutError, UpdateFailed, CannotConnect, OSError) as err:
                        _LOGGER.debug(
                            "[Debouncer] Network error executing delayed command for '%s': %s",
                            prop,
                            err,
                            exc_info=True,
                        )  # pragma: no mutate
                        await self.coordinator.async_request_refresh()
                    except Exception as err:  # pylint: disable=broad-exception-caught
                        _LOGGER.error(
                            "[Debouncer] Unexpected error executing delayed command for '%s': %s",
                            prop,
                            err,
                            exc_info=True,
                        )  # pragma: no mutate
                        await self.coordinator.async_request_refresh()

                self.coordinator.config_entry.async_create_background_task(
                    self.hass,
                    _task_runner(),
                    name=f"{DOMAIN}_{self.coordinator.unique_id}_debouncer_{prop}",
                )

        self._timers[property_name] = async_call_later(
            self.hass, self.delay, _fire_delayed
        )
        _LOGGER.debug(
            "[Debouncer] Queued command for property '%s' with %.1fs delay",
            property_name,
            self.delay,
        )  # pragma: no mutate
        return True

class SamsungClimateCoordinator(DataUpdateCoordinator[ClimateIPDeviceState]):
    """Manages data fetching for Samsung Climate devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        controller: ControllerInterface,
        entry: ConfigEntry,
        device_info: dict[str, Any] | None = None,
        parent_unique_id: str | None = None,
    ) -> None:  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        """Initialize the data coordinator."""
        self.controller = controller
        self.config_entry = entry
        self.entry = entry
        self.debouncer = PropertyDebouncer(self, delay=3.0)
        self._global_network_lock = asyncio.Lock()

        # Inject callbacks into the controller to avoid circular dependencies.
        self.controller.register_token_callback(self._async_save_new_token)
        self.controller.on_push_update_callback = (
            self.async_handle_push_update
        )  # pragma: no mutate
        self.controller.on_ssl_config_updated = self._async_save_ssl_config
        self.controller.request_refresh_callback = self.async_request_refresh
        self.controller.on_connection_failed_callback = self._async_on_connection_failed
        self.controller.on_offline_callback = self._async_handle_persistent_offline

        # Determine the update interval from options → data → default.
        enable_polling = entry.options.get(
            CONF_ENABLE_POLLING,
            entry.data.get(CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING),
        )  # pragma: no mutate
        poll_interval_seconds = entry.options.get(
            CONF_POLL_INTERVAL,
            entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )  # pragma: no mutate
        update_interval = (
            timedelta(seconds=poll_interval_seconds)
            if (controller.poll and enable_polling)
            else None
        )  # pragma: no mutate

        _LOGGER.debug(
            "%s Initializing coordinator with update interval: %s",
            self.log_prefix,
            update_interval,
        )  # pragma: no mutate

        super().__init__(
            hass,
            _LOGGER,
            name=f"Samsung Climate {self.log_prefix}",
            update_interval=update_interval,
            config_entry=entry,
        )  # pragma: no mutate

        # Build comprehensive DeviceInfo
        if device_info:
            # Sub-device (e.g., Indoor Unit connected via a MIM-H03)
            name = device_info.get("name") or DEFAULT_SUBDEVICE_NAME
            did = device_info.get("id")

            # Avoid redundant "ID XXX (ID XXX (Name))"
            if did and not name.startswith(f"ID {did}"):
                final_name = f"ID {did} ({name})"
            else:
                final_name = name

            # Parent linkage for hierarchical display in HA UI
            via_device = (
                (DOMAIN, parent_unique_id) if parent_unique_id else None
            )  # pragma: no mutate

            # NOTE: For sub-devices, we DO NOT include 'connections' (MAC) to prevent
            # Home Assistant from merging multiple units behind the same gateway into one.
            self.device_info = DeviceInfo(
                identifiers={(DOMAIN, self.unique_id)},
                name=final_name,
                manufacturer=MANUFACTURER_SAMSUNG,
                via_device=via_device,
            )  # pragma: no mutate
        else:
            # Standalone/Parent device (e.g. the Wifi-kit itself or a single AC)
            mac = self.config_entry.data.get(CONF_MAC)  # pragma: no mutate
            conns = (
                {(dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac))} if mac else set()
            )  # pragma: no mutate

            self.device_info = DeviceInfo(
                identifiers={(DOMAIN, self.unique_id)},
                name=self.config_entry.data.get(
                    CONF_NAME, f"{DEFAULT_DEVICE_NAME_PREFIX} {self.unique_id}"
                ),
                manufacturer=MANUFACTURER_SAMSUNG,
                connections=conns,
            )  # pragma: no mutate

    @callback
    def _async_save_new_token(self, new_token: str) -> None:
        """Callback to save the renewed token from the network layer."""

        def _update_token() -> None:
            new_data = dict(self.config_entry.data)  # pragma: no mutate
            new_data[CONF_TOKEN_KEY] = new_token
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            _LOGGER.info(
                "%s Persisted new network token to Config Entry.", self.log_prefix
            )  # pragma: no mutate

        _dispatch_to_loop(self.hass, _update_token)


    @callback
    def _async_save_ssl_config(self, ssl_config: dict[str, Any]) -> None:
        """Callback to save SSL configuration to the config entry."""

        def _update_ssl() -> None:
            current_data = dict(self.config_entry.data)  # pragma: no mutate
            if current_data.get(CONF_SSL_CONFIG_KEY) != ssl_config:
                current_data[CONF_SSL_CONFIG_KEY] = ssl_config
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=current_data
                )
                _LOGGER.info(
                    "%s Persisted SSL config to ConfigEntry data.", self.log_prefix
                )  # pragma: no mutate

        _dispatch_to_loop(self.hass, _update_ssl)

    @callback
    def _async_on_connection_failed(self) -> None:
        """Callback when connection persistently fails."""
        self.last_update_success = False
        self.async_update_listeners()

    @callback
    def _async_handle_persistent_offline(self, reason: str) -> None:
        """Callback for the network layer to force UI unavailability immediately."""
        _LOGGER.debug(
            "%s Network layer declared device offline. Forcing UpdateFailed.",
            self.log_prefix,
        )  # pragma: no mutate
        if hasattr(self.controller, "clear_state_cache"):  # pragma: no mutate
            self.controller.clear_state_cache()
        self.async_set_update_error(UpdateFailed(f"Device offline: {reason}"))

    async def _async_switch_to_raw_engine(self) -> None:
        """Switch connection method option to RAW permanently and trigger reload."""
        new_options = dict(self.config_entry.options)
        new_options[CONF_CONN_METHOD] = CONN_METHOD_RAW
        self.hass.config_entries.async_update_entry(self.config_entry, options=new_options)

    async def _async_update_data(self) -> ClimateIPDeviceState:
        """Fetch the latest state from the device."""
        try:
            await asyncio.wait_for(
                self.controller.async_get_status(), timeout=NETWORK_POLL_TIMEOUT
            )  # pragma: no mutate
            return self._create_device_state()

        except InvalidHeaderError as err:
            if self.config_entry.options.get(CONF_CONN_METHOD) != CONN_METHOD_RAW:
                _LOGGER.warning(
                    "%s Auto-healing to RAW mode triggered", self.log_prefix
                )  # pragma: no mutate
                self.config_entry.async_create_background_task(
                    self.hass,
                    self._async_switch_to_raw_engine(),
                    name=f"{DOMAIN}_{self.unique_id}_auto_heal_raw",
                )
                raise UpdateFailed(
                    "Auto-healing in progress: Switching to RAW engine"
                ) from err

            _LOGGER.error(
                "%s Invalid header error persists even on the RAW engine. Auto-healing failed: %s",
                self.log_prefix,
                err,
            )  # pragma: no mutate
            raise UpdateFailed(f"Data parsing failed on RAW engine: {err}") from err

        except (AuthError, ConfigEntryAuthFailed) as err:
            if hasattr(self.controller, "clear_state_cache"):  # pragma: no mutate
                self.controller.clear_state_cache()
            raise ConfigEntryAuthFailed(
                f"Authentication failed: {err}"
            ) from err  # pragma: no mutate

        except UpdateFailed:
            raise  # pragma: no mutate

        except (TimeoutError, CannotConnect, ConnectionRefusedError, OSError) as err:
            if hasattr(self.controller, "clear_state_cache"):  # pragma: no mutate
                self.controller.clear_state_cache()

            _LOGGER.debug(
                "%s Network error during state update: %s", self.log_prefix, err
            )  # pragma: no mutate

            raise UpdateFailed(
                f"Network error during update: {err}"
            ) from err  # pragma: no mutate

        except (ValueError, TypeError, KeyError) as err:
            if hasattr(self.controller, "clear_state_cache"):  # pragma: no mutate
                self.controller.clear_state_cache()

            _LOGGER.error(
                "%s Data parsing error during update: %s",
                self.log_prefix,
                err,
                exc_info=True,
            )  # pragma: no mutate

            raise UpdateFailed(
                f"Data parsing error: {err}"
            ) from err  # pragma: no mutate

        except Exception as err:  # pylint: disable=broad-exception-caught
            if hasattr(self.controller, "clear_state_cache"):  # pragma: no mutate
                self.controller.clear_state_cache()

            _LOGGER.critical(
                "%s Fatal unexpected error during update: %s",
                self.log_prefix,
                err,
                exc_info=True,
            )  # pragma: no mutate

            raise UpdateFailed(f"Fatal error: {err}") from err  # pragma: no mutate

    async def async_handle_push_update(
        self, new_data: dict[str, Any] | None = None
    ) -> None:
        """Handle a state update received via push from the connection."""
        try:
            _LOGGER.debug(
                "%s Push update received with data: %s", self.log_prefix, new_data
            )  # pragma: no mutate

            if new_data:
                if await self.controller.async_merge_device_state(new_data):
                    if self.debouncer.is_active:
                        _LOGGER.debug(
                            "%s Push update received during active debouncing; suppressing HA broadcast to protect UI buffer",
                            self.log_prefix,
                        )  # pragma: no mutate
                        return

                    updated_state = self._create_device_state()  # pragma: no mutate
                    if updated_state != self.data:
                        self.async_set_updated_data(updated_state)  # pragma: no mutate
                    else:
                        _LOGGER.debug(
                            "%s Push update yielded identical typed state; suppressing broadcast to prevent UI flicker",
                            self.log_prefix,
                        )  # pragma: no mutate
                else:
                    _LOGGER.debug(
                        "Push update discarded by controller (validation failed or junk data)."
                    )  # pragma: no mutate

            else:
                _LOGGER.debug(
                    "%s Push update did not contain state data, skipping processing",
                    self.log_prefix,
                )  # pragma: no mutate

        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s Unexpected error during push update: %s",
                self.log_prefix,
                err,
                exc_info=True,
            )  # pragma: no mutate

    def _create_device_state(self) -> ClimateIPDeviceState:
        """Fetch the strictly typed state representation directly from the controller."""
        state = self.controller.climate_state
        _LOGGER.debug(
            "%s Fetched typed climate state: %s", self.log_prefix, state
        )  # pragma: no mutate
        return state

    async def _locked_set_property(
        self, prop: str, val: Any, device_id: str | None = None
    ) -> bool:
        """Serialize network commands with a global lock and delay to prevent AC drops."""
        async with self._global_network_lock:
            if self.debouncer.has_pending(prop):
                _LOGGER.debug(
                    "%s [Debouncer] Command for '%s' (val=%s) was superseded while waiting for lock. Dropping stale command.",
                    self.log_prefix,
                    prop,
                    val,
                )
                return True

            if self.controller.is_property_superseded(prop, val):
                _LOGGER.debug(
                    "%s [Debouncer] Command for '%s' (val=%s) was superseded. Dropping stale command.",
                    self.log_prefix,
                    prop,
                    val,
                )
                return True

            res = await self.controller.async_set_property(prop, val, device_id)
            await asyncio.sleep(HARDWARE_BREATHING_ROOM_SEC)
            return bool(res)

    async def async_set_property(
        self,
        property_name: str,
        new_value: Any,
        device_id: str | None = None,
    ) -> None:
        """Set a property on the controller with optimistic prediction and atomic rollback."""
        # 1. Predict (Activates anti-flicker locks in the controller)
        pred_val = new_value.value if isinstance(new_value, HVACMode) else new_value
        _, corrections = await self.controller.async_predict_and_correct_state(
            self.data, property_name, pred_val
        )

        # 2. Push the fast-tracked predicted state through the coordinator
        predicted_state = self._create_device_state()
        self.async_set_updated_data(predicted_state)

        properties_to_set = {property_name: new_value}
        if corrections:
            properties_to_set.update(corrections)

        _LOGGER.debug(
            "%s Dispatching commands to controller: %s",
            self.log_prefix,
            properties_to_set,
        )  # pragma: no mutate

        try:
            results = []
            for prop, val in properties_to_set.items():
                if isinstance(val, HVACMode):
                    val = val.value
                results.append(
                    await self.debouncer.async_execute(
                        prop, self._locked_set_property, prop, val, device_id
                    )
                )

            if not all(results):
                _LOGGER.debug(
                    "%s Not all properties were set successfully. Requesting sync refresh to revert state.",
                    self.log_prefix,
                )  # pragma: no mutate
                await self._async_handle_set_property_failure(properties_to_set)

        except (CannotConnect, OSError) as err:
            await self._async_handle_set_property_failure(properties_to_set)
            _LOGGER.error(
                "%s Network error setting properties: %s",
                self.log_prefix,
                type(err).__name__,
            )  # pragma: no mutate
            raise HomeAssistantError(
                f"Network error setting property {property_name}: {err}"
            ) from err  # pragma: no mutate

        except (ValueError, TypeError, KeyError) as err:
            await self._async_handle_set_property_failure(properties_to_set)
            _LOGGER.error(
                "%s Data error setting properties: %s",
                self.log_prefix,
                err,
                exc_info=True,
            )  # pragma: no mutate
            raise HomeAssistantError(
                f"Data error setting property {property_name}: {err}"
            ) from err  # pragma: no mutate

        except HomeAssistantError:
            await self._async_handle_set_property_failure(properties_to_set)
            raise

        except Exception as err:  # pylint: disable=broad-exception-caught
            await self._async_handle_set_property_failure(properties_to_set)
            _LOGGER.error(
                "%s Error setting properties: %s", self.log_prefix, err, exc_info=True
            )  # pragma: no mutate
            raise HomeAssistantError(
                f"Failed to set property {property_name}: {err}"
            ) from err  # pragma: no mutate

    async def _async_handle_set_property_failure(
        self, properties: dict[str, Any]
    ) -> None:
        """Clear pending updates and request refresh on command failure."""
        await self.controller.async_clear_pending_updates(list(properties.keys()))
        await self.async_request_refresh()

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the controller."""
        return self.controller.log_prefix

    @property
    def unique_id(self) -> str:
        """Return the unique ID from the controller."""
        return self.controller.unique_id

    async def async_shutdown(self) -> None:
        """Shut down the coordinator and its controller.

        Called when the config entry is unloaded.
        """
        _LOGGER.debug(
            "%s Shutting down coordinator", self.log_prefix
        )  # pragma: no mutate

        self.debouncer.cancel_all()
        super().async_shutdown()
        await self.controller.async_shutdown()

        _LOGGER.debug(
            "%s Coordinator shutdown complete", self.log_prefix
        )  # pragma: no mutate
