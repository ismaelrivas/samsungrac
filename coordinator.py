# pylint: disable=line-too-long,too-many-statements,too-many-locals,try-except-raise,trailing-whitespace
"""DataUpdateCoordinator for the Samsung Climate integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import timedelta
from enum import Enum
import logging
from typing import Any, Final

from homeassistant.components.climate.const import ATTR_HVAC_MODE, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
    async_get as async_get_issue_registry,
)
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    ATTR_POWER,
    CONF_CONN_METHOD,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_SSL_CONFIG_KEY,
    CONF_SUBDEVICE_ID,
    CONN_METHOD_RAW,
    DEFAULT_DEBOUNCE_DELAY,
    DEFAULT_DEVICE_NAME_PREFIX,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SUBDEVICE_NAME,
    DOMAIN,
    ERR_AUTO_HEALING_RAW_IN_PROGRESS,
    ERR_DEVICE_OFFLINE_PREFIX,
    ERR_PERSISTENT_CONNECTION_FAILURE,
    FALSY_STRINGS,
    HARDWARE_BREATHING_ROOM_SEC,
    ISSUE_AUTO_HEALING_RAW,
    MANUFACTURER_SAMSUNG,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    NETWORK_POLL_TIMEOUT,
    PREFIX_SUBDEVICE_ID,
    TRUTHY_STRINGS,
)
from .controller import ControllerInterface
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_QUEUED: Final = True


class PropertyDebouncer:
    """Debounces outgoing commands per property to shield hardware from request flooding."""

    def __init__(
        self,
        coordinator: SamsungClimateCoordinator,
        delay: float = DEFAULT_DEBOUNCE_DELAY,
    ) -> None:
        """Initialize the property debouncer."""
        self.coordinator = coordinator
        self.delay = delay
        self._timers: dict[str, Callable[[], None]] = {}
        # 🛡️ Updated typing to include the Generation ID (int) at the end of the tuple
        self._pending_payloads: dict[
            str,
            tuple[
                Callable[..., Coroutine[Any, Any, bool]],
                tuple[Any, ...],
                dict[str, Any],
                int,
            ],
        ] = {}
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

    def _cancel_timer(self, property_name: str) -> None:
        """Cancel and remove an active timer for a property if present."""
        unsub = self._timers.pop(property_name, None)
        if unsub is not None:
            unsub()

    def cancel_all(self) -> None:
        """Cancel all active timers, clear pending payloads, and poison active zombies."""
        self._generation += (
            1  # 💥 Global poisoning: any queued task will be invalidated
        )

        _LOGGER.debug(
            "[Debouncer] Purge requested. Generation incremented to %s",
            self._generation,
        )

        for unsub in self._timers.values():
            unsub()
        self._timers.clear()
        self._pending_payloads.clear()
        self._last_activities.clear()

    async def _async_handle_delayed_failure(self, prop: str) -> None:
        """Clear pending controller prediction and request coordinator refresh on failure."""
        await self.coordinator.controller.async_clear_pending_updates([prop])
        await self.coordinator.async_request_refresh()

    async def async_execute(
        self,
        property_name: str,
        coroutine_func: Callable[..., Coroutine[Any, Any, bool]],
        *args: Any,
        val: Any = None,
        **kwargs: Any,
    ) -> bool:
        """Execute a command with trailing debouncing per property."""
        now = self.hass.loop.time()
        last_activity = self._last_activities.get(property_name, 0.0)

        # Immediate execution for turn-off commands (aborts any pending debounced commands across all properties)
        if val is None:
            raise ValueError(
                "async_execute requires an explicit 'val' keyword argument."
            )
        effective_val = val
        is_turn_off = (
            property_name == ATTR_HVAC_MODE
            and effective_val in (HVACMode.OFF, HVACMode.OFF.value)
        ) or (
            property_name == ATTR_POWER
            and (
                effective_val is False
                or (
                    isinstance(effective_val, str)
                    and effective_val.lower() in FALSY_STRINGS
                )
                or effective_val == 0
            )
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
        if property_name not in self._last_activities or (
            now - last_activity >= self.delay
        ):
            self._cancel_timer(property_name)
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
        self._cancel_timer(property_name)
        _LOGGER.debug(
            "[Debouncer] Resetting %.1fs countdown timer for property '%s'",
            self.delay,
            property_name,
        )  # pragma: no mutate

        # 🛡️ Package the payload with the CURRENT Generation ID
        self._pending_payloads[property_name] = (
            coroutine_func,
            args,
            kwargs,
            self._generation,
        )

        @callback
        def _fire_delayed(_now: Any = None) -> None:
            prop = property_name
            self._timers.pop(prop, None)
            payload = self._pending_payloads.pop(prop, None)

            if payload is not None:
                # 🛡️ Unpack the generation ID captured when the task was queued
                func, p_args, p_kwargs, captured_generation = payload
                exec_time = self.hass.loop.time()
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
                        success = await func(*p_args, **p_kwargs)
                        if not success:
                            _LOGGER.warning(
                                "[Debouncer] Delayed command for '%s' returned failure. Reverting optimistic state.",
                                prop,
                            )
                            await self._async_handle_delayed_failure(prop)
                    except (TimeoutError, UpdateFailed, CannotConnect, OSError) as err:
                        _LOGGER.debug(
                            "[Debouncer] Network error executing delayed command for '%s': %s",
                            prop,
                            err,
                            exc_info=True,
                        )  # pragma: no mutate
                        await self._async_handle_delayed_failure(prop)
                    except Exception as err:  # pylint: disable=broad-exception-caught
                        _LOGGER.error(
                            "[Debouncer] Unexpected error executing delayed command for '%s': %s",
                            prop,
                            err,
                            exc_info=True,
                        )  # pragma: no mutate
                        await self._async_handle_delayed_failure(prop)

                task_coro = _task_runner()
                safe_uid = self.coordinator.safe_unique_id
                task_name = f"{DOMAIN}_{safe_uid}_debouncer_{prop}"
                if self.coordinator.config_entry is not None:
                    self.coordinator.config_entry.async_create_background_task(
                        self.hass,
                        task_coro,
                        name=task_name,
                    )
                else:
                    task_coro.close()
                    _LOGGER.error(
                        "[Debouncer] config_entry is None during delayed execution for '%s'. Aborting task.",
                        prop,
                    )

        self._timers[property_name] = async_call_later(
            self.hass, self.delay, _fire_delayed
        )
        _LOGGER.debug(
            "[Debouncer] Queued command for property '%s' with %.1fs delay",
            property_name,
            self.delay,
        )  # pragma: no mutate
        return DEBOUNCE_QUEUED


class SamsungClimateCoordinator(DataUpdateCoordinator[ClimateIPDeviceState]):
    """Manages data fetching for Samsung Climate devices."""

    config_entry: ConfigEntry

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
        self.debouncer = PropertyDebouncer(self, delay=DEFAULT_DEBOUNCE_DELAY)
        self._global_network_lock = asyncio.Lock()
        self.config_entry = entry

        # Inject callbacks into the controller to avoid circular dependencies.
        self.controller.register_token_callback(self._async_save_new_token)
        self.controller.on_push_update_callback = (
            self.async_handle_push_update
        )  # pragma: no mutate
        self.controller.on_ssl_config_updated = self._async_save_ssl_config
        self.controller.request_refresh_callback = self.async_request_refresh
        self.controller.on_connection_failed_callback = self._async_on_connection_failed
        self.controller.on_offline_callback = self._async_handle_persistent_offline

        # Determine the update interval
        raw_polling = entry.options.get(
            CONF_ENABLE_POLLING,
            entry.data.get(CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING),
        )
        enable_polling = (
            raw_polling
            if isinstance(raw_polling, bool)
            else str(raw_polling).lower() in TRUTHY_STRINGS
        )
        raw_interval = entry.options.get(
            CONF_POLL_INTERVAL,
            entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )  # pragma: no mutate
        try:
            poll_interval_seconds = min(
                max(int(raw_interval), MIN_POLL_INTERVAL), MAX_POLL_INTERVAL
            )
        except (ValueError, TypeError):
            poll_interval_seconds = DEFAULT_POLL_INTERVAL
        update_interval = (
            timedelta(seconds=poll_interval_seconds)
            if (controller.poll is True and enable_polling)
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
        safe_uid = self.safe_unique_id
        if device_info is not None:
            # Sub-device (e.g., Indoor Unit connected via a MIM-H03)
            raw_name = device_info.get(CONF_NAME)
            name_str = raw_name.strip() if isinstance(raw_name, str) else ""
            name = name_str or DEFAULT_SUBDEVICE_NAME
            did = device_info.get(CONF_SUBDEVICE_ID)

            # Avoid redundant "ID XXX (ID XXX (Name))"
            if did is not None and not name.startswith(f"{PREFIX_SUBDEVICE_ID}{did}"):
                final_name = f"{PREFIX_SUBDEVICE_ID}{did} ({name})"
            else:
                final_name = name

            # NOTE: For sub-devices, we DO NOT include 'connections' (MAC) to prevent
            # Home Assistant from merging multiple units behind the same gateway into one.
            if parent_unique_id:
                self.device_info = DeviceInfo(
                    identifiers={(DOMAIN, safe_uid)},
                    name=final_name,
                    manufacturer=MANUFACTURER_SAMSUNG,
                    via_device=(DOMAIN, parent_unique_id),
                )  # pragma: no mutate
            else:
                self.device_info = DeviceInfo(
                    identifiers={(DOMAIN, safe_uid)},
                    name=final_name,
                    manufacturer=MANUFACTURER_SAMSUNG,
                )  # pragma: no mutate
        else:
            mac = self.config_entry.data.get(CONF_MAC)  # pragma: no mutate
            conns: set[tuple[str, str]] = set()
            if mac is not None:
                mac_str = mac.strip()
                if mac_str != "":
                    try:
                        conns.add((dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac_str)))
                    except (ValueError, TypeError):
                        _LOGGER.debug(
                            "%s Malformed MAC address '%s' discarded from DeviceInfo connections",
                            self.log_prefix,
                            mac,
                        )
                else:
                    _LOGGER.debug(
                        "%s Empty MAC address string in config entry, skipping",
                        self.log_prefix,
                    )  # pragma: no mutate

            opt_name = self.config_entry.options.get(CONF_NAME)
            data_name = self.config_entry.data.get(CONF_NAME)
            name_candidate = (
                opt_name
                if isinstance(opt_name, str) and opt_name.strip() != ""
                else data_name
            )
            name_str = name_candidate.strip() if isinstance(name_candidate, str) else ""
            device_name = name_str or f"{DEFAULT_DEVICE_NAME_PREFIX} {safe_uid}"
            self.device_info = DeviceInfo(
                identifiers={(DOMAIN, safe_uid)},
                name=device_name,
                manufacturer=MANUFACTURER_SAMSUNG,
                connections=conns,
            )  # pragma: no mutate

        # Clean up auto-healing repair issue on restart if previously dismissed/ignored
        self._async_cleanup_auto_healing_issue_if_ignored()

    @callback
    def _async_cleanup_auto_healing_issue_if_ignored(self) -> None:
        """Delete auto-healing issue from registry if it was ignored/dismissed by the user."""
        issue_id = self.auto_healing_issue_id
        registry = async_get_issue_registry(self.hass)
        issue = registry.async_get_issue(DOMAIN, issue_id)
        if issue is not None and issue.dismissed_version is not None:
            async_delete_issue(self.hass, DOMAIN, issue_id)
            _LOGGER.debug(
                "%s Cleaned up ignored auto-healing repair issue '%s'",
                self.log_prefix,
                issue_id,
            )

    @callback
    def _async_save_new_token(self, new_token: str) -> None:
        """Callback to save the renewed token from the network layer."""
        if self.config_entry.data.get(CONF_TOKEN) == new_token:
            return
        new_data = dict(self.config_entry.data)  # pragma: no mutate
        new_data[CONF_TOKEN] = new_token
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        _LOGGER.info(
            "%s Persisted new network token to Config Entry.", self.log_prefix
        )  # pragma: no mutate

    @callback
    def _async_save_ssl_config(self, ssl_config: dict[str, Any]) -> None:
        """Callback to save SSL configuration to the config entry."""
        if self.config_entry.data.get(CONF_SSL_CONFIG_KEY) == ssl_config:
            return
        new_data = dict(self.config_entry.data)  # pragma: no mutate
        new_data[CONF_SSL_CONFIG_KEY] = ssl_config
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        _LOGGER.info(
            "%s Persisted SSL config to ConfigEntry data.", self.log_prefix
        )  # pragma: no mutate

    @callback
    def _async_on_connection_failed(self) -> None:
        """Callback when connection persistently fails."""
        self.debouncer.cancel_all()
        self.controller.clear_state_cache()
        self.async_set_update_error(UpdateFailed(ERR_PERSISTENT_CONNECTION_FAILURE))

    @callback
    def _async_handle_persistent_offline(self, reason: str) -> None:
        """Callback for the network layer to force UI unavailability immediately."""
        _LOGGER.debug(
            "%s Network layer declared device offline. Forcing UpdateFailed.",
            self.log_prefix,
        )  # pragma: no mutate
        self.debouncer.cancel_all()
        self.controller.clear_state_cache()
        self.async_set_update_error(
            UpdateFailed(f"{ERR_DEVICE_OFFLINE_PREFIX}: {reason}")
        )

    @callback
    def _async_switch_to_raw_engine(self) -> None:
        """Switch connection method option to RAW permanently and notify the user."""
        new_options = {**self.config_entry.options, CONF_CONN_METHOD: CONN_METHOD_RAW}
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=new_options
        )

        device_name = self.device_info.get("name") or self.safe_unique_id

        _LOGGER.warning(
            "%s Auto-healing to RAW mode activated: The device sent non-standard HTTP responses "
            "(RFC 7230 violation). The connection engine has been automatically and permanently "
            "migrated to 'Robust (raw socket)' to preserve full AC control without disconnections.",
            self.log_prefix,
        )
        async_create_issue(
            self.hass,
            DOMAIN,
            self.auto_healing_issue_id,
            is_fixable=True,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key=ISSUE_AUTO_HEALING_RAW,
            translation_placeholders={
                "device_name": device_name,
            },
            data={
                "device_name": device_name,
            },
        )

    async def _async_update_data(self) -> ClimateIPDeviceState:
        """Fetch the latest state from the device."""
        try:
            async with self._global_network_lock:
                async with asyncio.timeout(NETWORK_POLL_TIMEOUT):
                    await self.controller.async_get_status()  # pragma: no mutate
            return self._create_device_state()
        except InvalidHeaderError as err:
            if self.connection_method != CONN_METHOD_RAW:
                _LOGGER.warning(
                    "%s Auto-healing to RAW mode triggered", self.log_prefix
                )  # pragma: no mutate
                self._async_switch_to_raw_engine()
                raise UpdateFailed(ERR_AUTO_HEALING_RAW_IN_PROGRESS) from err

            _LOGGER.error(
                "%s Invalid header error persists even on the RAW engine. Auto-healing failed: %s",
                self.log_prefix,
                err,
            )  # pragma: no mutate
            raise UpdateFailed(f"Data parsing failed on RAW engine: {err}") from err

        except ConfigEntryAuthFailed:
            self.controller.clear_state_cache()
            raise
        except AuthError as err:
            self.controller.clear_state_cache()
            raise ConfigEntryAuthFailed(
                f"Authentication failed: {err}"
            ) from err  # pragma: no mutate

        except UpdateFailed:
            raise  # pragma: no mutate

        except (TimeoutError, CannotConnect, OSError) as err:
            self.controller.clear_state_cache()

            _LOGGER.debug(
                "%s Network error during state update: %s", self.log_prefix, err
            )  # pragma: no mutate

            raise UpdateFailed(
                f"Network error during update: {err}"
            ) from err  # pragma: no mutate

        except (ValueError, TypeError, KeyError) as err:
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

            if new_data is not None:
                if await self.controller.async_merge_device_state(new_data):
                    if self.debouncer.is_active:
                        _LOGGER.debug(
                            "%s Push update received during active debouncing; suppressing HA broadcast to protect UI buffer",
                            self.log_prefix,
                        )  # pragma: no mutate
                        return

                    updated_state = self._create_device_state()  # pragma: no mutate
                    if not self.last_update_success or updated_state != self.data:
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

        except asyncio.CancelledError:
            raise
        except (AuthError, ConfigEntryAuthFailed) as err:
            self.controller.clear_state_cache()
            _LOGGER.error(
                "%s Authentication failed during push update: %s",
                self.log_prefix,
                err,
            )
            self.async_set_update_error(
                ConfigEntryAuthFailed(f"Authentication failed: {err}")
            )
            if self.config_entry is not None:
                self.config_entry.async_start_reauth(self.hass)

        except Exception as err:  # pylint: disable=broad-exception-caught
            self.controller.clear_state_cache()
            _LOGGER.error(
                "%s Unexpected error during push update: %s",
                self.log_prefix,
                err,
                exc_info=True,
            )  # pragma: no mutate
            self.async_set_update_error(UpdateFailed(f"Push update failed: {err}"))

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
            # Hardware spacing: MUST remain inside lock.
            await asyncio.sleep(HARDWARE_BREATHING_ROOM_SEC)
        if not isinstance(res, bool):
            raise TypeError(
                f"Controller.async_set_property returned {type(res)}, expected bool"
            )
        return res

    async def async_set_property(
        self,
        property_name: str,
        new_value: Any,
        device_id: str | None = None,
    ) -> None:
        """Set a property on the controller with optimistic prediction and atomic rollback."""
        # 1. Predict (Activates anti-flicker locks in the controller)
        current_state = (
            self.data if self.data is not None else self._create_device_state()
        )
        pred_val = new_value.value if isinstance(new_value, Enum) else new_value
        _, corrections = await self.controller.async_predict_and_correct_state(
            current_state, property_name, pred_val
        )

        # 2. Push the fast-tracked predicted state through the coordinator
        predicted_state = self._create_device_state()
        self.async_set_updated_data(predicted_state)

        properties_to_set: dict[str, Any] = {property_name: pred_val}
        if corrections:
            for k, v in corrections.items():
                properties_to_set[k] = v.value if isinstance(v, Enum) else v

        _LOGGER.debug(
            "%s Dispatching commands to controller: %s",
            self.log_prefix,
            properties_to_set,
        )  # pragma: no mutate

        try:
            results = []
            for prop, val in properties_to_set.items():
                results.append(
                    await self.debouncer.async_execute(
                        prop,
                        self._locked_set_property,
                        prop,
                        val,
                        device_id,
                        val=val,
                    )
                )

            if not all(results):
                _LOGGER.debug(
                    "%s Not all properties were set successfully. Requesting sync refresh to revert state.",
                    self.log_prefix,
                )  # pragma: no mutate
                raise HomeAssistantError(
                    f"Failed to set property {property_name} to {new_value}"
                )

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

        except asyncio.CancelledError:
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
        """Clear pending updates and cancel pending debounces on command failure."""
        self.debouncer.cancel_all()
        await self.controller.async_clear_pending_updates(list(properties.keys()))
        await self.async_request_refresh()

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the controller."""
        return self.controller.log_prefix

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID from the controller."""
        return self.controller.unique_id

    @property
    def safe_unique_id(self) -> str:
        """Return a sanitized unique ID safe for issue registry and task names."""
        raw_uid = self.unique_id
        if raw_uid is None or str(raw_uid).strip() == "":
            raw_uid = self.config_entry.unique_id
        if raw_uid is None or str(raw_uid).strip() == "":
            raw_uid = self.config_entry.entry_id
        return str(raw_uid).strip().replace(".", "_").replace(" ", "_")

    @property
    def auto_healing_issue_id(self) -> str:
        """Return the standardized issue ID for auto-healing to RAW mode."""
        return f"{ISSUE_AUTO_HEALING_RAW}_{self.safe_unique_id}"

    @property
    def connection_method(self) -> str | None:
        """Return the configured connection method (options taking precedence over data)."""
        res = self.config_entry.options.get(
            CONF_CONN_METHOD, self.config_entry.data.get(CONF_CONN_METHOD)
        )
        return str(res) if res is not None else None

    async def async_shutdown(self) -> None:
        """Shut down the coordinator and its controller.

        Called when the config entry is unloaded.
        """
        _LOGGER.debug(
            "%s Shutting down coordinator", self.log_prefix
        )  # pragma: no mutate

        self.debouncer.cancel_all()
        await super().async_shutdown()

        try:
            await self.controller.async_shutdown()
        except (TimeoutError, CannotConnect, OSError) as err:
            _LOGGER.debug(
                "%s Tolerated network exception during controller shutdown: %s",
                self.log_prefix,
                err,
            )
        except asyncio.CancelledError:
            _LOGGER.debug("%s Shutdown cancelled", self.log_prefix)
            raise
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOGGER.warning(
                "%s Unexpected error during controller shutdown: %s",
                self.log_prefix,
                err,
                exc_info=True,
            )

        _LOGGER.debug(
            "%s Coordinator shutdown complete", self.log_prefix
        )  # pragma: no mutate
