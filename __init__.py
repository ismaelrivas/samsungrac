"""The Samsung Climate IP integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONF_SUBDEVICE_ID,
    CONFIG_ENTRY_VERSION,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
    MAIN_DEVICE_ID,
    WIFI_KIT_MGMT_ID,
)
from .controller_yaml import YamlController
from .controller_yaml_config import clear_yaml_cache
from .coordinator import SamsungClimateCoordinator

_LOGGER = logging.getLogger(__name__)

DEFAULT_UNKNOWN = "Unknown"

type ClimateIPConfigEntry = ConfigEntry[dict[str, SamsungClimateCoordinator]]

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
]


def _get_config_value(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Extract configuration value prioritizing options over entry data."""
    val = entry.options.get(key)
    if val is not None:
        return val
    return entry.data.get(key, default)


async def async_migrate_entry(hass: HomeAssistant, entry: ClimateIPConfigEntry) -> bool:
    """Migrate old config entry to new version."""
    _LOGGER.debug(
        "Migrating climate_ip config entry from version %s to %s",
        entry.version,
        CONFIG_ENTRY_VERSION,
    )

    if entry.version > CONFIG_ENTRY_VERSION:
        # Guard against downgrades.
        _LOGGER.error(
            "Config entry version %s is newer than integration supports (%s). Update integration.",
            entry.version,
            CONFIG_ENTRY_VERSION,
        )
        return False

    hass.config_entries.async_update_entry(entry, version=CONFIG_ENTRY_VERSION)
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug(
        "Configuration options updated, reloading climate_ip integration for entry %s",
        entry.entry_id,
    )
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_safe_shutdown(target: Any) -> None:
    """Safely shut down a controller or coordinator if async_shutdown exists and is awaitable."""
    if hasattr(target, "async_shutdown"):
        try:
            res = target.async_shutdown()
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                await res
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _LOGGER.warning("Error during safe shutdown of %s: %s", target, ex)


async def _async_setup_single_device(
    hass: HomeAssistant,
    entry: ClimateIPConfigEntry,
    device_id: str,
    device_name: str,
    device_info: dict[str, Any] | None,
    session: Any,
) -> tuple[str, SamsungClimateCoordinator | None]:
    """Initialize a single device controller and coordinator concurrently with resource safety."""
    controller = YamlController(
        config_entry=entry,
        device_id=device_id,
        logger=_LOGGER,
        hass=hass,
        session=session,
    )

    try:
        initialized = await controller.initialize()
    except (TimeoutError, ConnectionRefusedError, OSError) as ex:
        _LOGGER.warning(
            "%s Transient network error during controller initialization for %s: %s",
            controller.log_prefix,
            device_name,
            ex,
        )
        await _async_safe_shutdown(controller)
        return device_id, None

    if not initialized:
        _LOGGER.debug(
            "%s Failed to initialize controller for %s",
            controller.log_prefix,
            device_name,
            exc_info=True,
        )
        await _async_safe_shutdown(controller)
        return device_id, None

    has_devices_list = bool(_get_config_value(entry, CONF_DEVICES))
    coordinator = SamsungClimateCoordinator(
        hass,
        controller,
        entry,
        device_info=device_info if has_devices_list else None,
        parent_unique_id=entry.unique_id
        if (has_devices_list and device_id != MAIN_DEVICE_ID)
        else None,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        await _async_safe_shutdown(controller)
        raise
    except (TimeoutError, ConnectionRefusedError, OSError, UpdateFailed) as ex:
        _LOGGER.error(
            "%s Initial connection failed for %s: %s",
            controller.log_prefix,
            device_name,
            ex,
        )
        await _async_safe_shutdown(controller)
        return device_id, None

    return device_id, coordinator


def _build_device_setup_tasks(
    hass: HomeAssistant,
    entry: ClimateIPConfigEntry,
    devices_config: list[dict[str, Any]],
    session: Any,
) -> list[Any]:
    """Build list of concurrent setup tasks for sub-devices."""
    if not isinstance(devices_config, (list, tuple)):
        return []

    has_devices_list = bool(_get_config_value(entry, CONF_DEVICES))
    setup_tasks = []
    for device_info in devices_config:
        if not isinstance(device_info, dict):
            continue

        raw_device_id = device_info.get(CONF_SUBDEVICE_ID)
        if raw_device_id is None:
            continue

        device_id = str(raw_device_id).strip()
        if not device_id:
            continue

        device_name = device_info.get(CONF_NAME)

        if device_id == WIFI_KIT_MGMT_ID:
            _LOGGER.debug("Skipping Wifi-kit management device (ID 0)")
            continue

        _LOGGER.info("Setting up Samsung unit '%s' (ID %s)", device_name, device_id)

        setup_tasks.append(
            _async_setup_single_device(
                hass,
                entry,
                device_id,
                device_name or DEFAULT_UNKNOWN,
                device_info
                if (has_devices_list and device_id != MAIN_DEVICE_ID)
                else None,
                session,
            )
        )
    return setup_tasks


async def async_setup_entry(hass: HomeAssistant, entry: ClimateIPConfigEntry) -> bool:
    """Set up Samsung Climate IP from a config entry."""

    device_type = _get_config_value(entry, CONF_DEVICE_TYPE)  # pragma: no mutate
    mac = _get_config_value(entry, CONF_MAC, None)  # pragma: no mutate
    ip_address = _get_config_value(
        entry, CONF_IP_ADDRESS, DEFAULT_UNKNOWN
    )  # pragma: no mutate

    # Use the official session manager.
    session = async_get_clientsession(hass)

    _LOGGER.info(
        "Starting setup for device %s at %s (Device Type: %s)",
        mac,
        ip_address,
        device_type,
    )

    devices_config = _get_config_value(entry, CONF_DEVICES)

    # Normalize: If no sub-devices are defined, create a synthetic list for the main unit
    if not devices_config:
        st_dev_id = _get_config_value(entry, CONF_DEVICE_ID)
        is_st = device_type in (
            DEVICE_TYPE_SMARTTHINGS_HVAC,
            DEVICE_TYPE_SMARTTHINGS_DHW,
        )
        subdev_id = (
            str(st_dev_id).strip()
            if (is_st and st_dev_id and str(st_dev_id).strip())
            else MAIN_DEVICE_ID
        )
        devices_config = [
            {
                CONF_SUBDEVICE_ID: subdev_id,
                CONF_NAME: _get_config_value(entry, CONF_NAME, entry.title),
            }
        ]

    _LOGGER.debug("Climate IP setup. devices_config: %s", devices_config)

    # Pass 1: Instantiate controllers and coordinators
    setup_tasks = _build_device_setup_tasks(hass, entry, devices_config, session)

    # Pass 2: Concurrent bootstrapping using asyncio.gather
    results = await asyncio.gather(*setup_tasks, return_exceptions=True)

    coordinators: dict[str, SamsungClimateCoordinator] = {}
    fatal_exception: Exception | None = None

    for result in results:
        if isinstance(result, Exception):
            if not fatal_exception:
                fatal_exception = result
            _LOGGER.error("Device setup task raised fatal exception: %s", result)
            continue

        if isinstance(result, tuple):
            dev_id, coord = result
            if coord is not None:
                coordinators[dev_id] = coord

    # 4. ROLLBACK CHECK: Tear down successfully booted orphans if a sibling failed fatally
    if fatal_exception is not None:
        if coordinators:
            _LOGGER.error(
                "Rolling back %d booted coordinators due to sibling fatal exception: %s",
                len(coordinators),
                fatal_exception,
            )
            for dev_id, coord in coordinators.items():
                try:
                    await _async_safe_shutdown(coord)
                except Exception as ex:
                    _LOGGER.error(
                        "Failed clean shutdown for device %s during rollback: %s",
                        dev_id,
                        ex,
                    )
        raise fatal_exception

    # 5. EMPTY CHECK
    if not coordinators:
        _LOGGER.error("No coordinators could be set up for entry %s", entry.title)
        raise ConfigEntryNotReady(
            f"No coordinators could be set up for entry {entry.title}"
        )

    # 6. SUCCESS: Contract strictly fulfilled: runtime_data is ALWAYS a dict
    entry.runtime_data = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Add listener for options changes.
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClimateIPConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.entry_id)

    # 1. UNLOAD PLATFORMS FIRST
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # 2. TERMINATE BACKGROUND TASKS
        if entry.runtime_data:
            _LOGGER.debug(
                "Terminating active connections and coordinators for entry %s",
                entry.entry_id,
            )
            for device_id, coordinator in entry.runtime_data.items():
                _LOGGER.debug("Executing async_shutdown for device ID: %s", device_id)
                try:
                    await _async_safe_shutdown(coordinator)
                except Exception as ex:
                    _LOGGER.error(
                        "Failed to cleanly shutdown coordinator for device %s: %s",
                        device_id,
                        ex,
                    )

            # 3. PURGE MEMORY FOOTPRINT
            entry.runtime_data.clear()

        # Clear the YAML cache only if this is the last active config entry for climate_ip
        other_active_entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
            and e.state
            in (
                ConfigEntryState.LOADED,
                ConfigEntryState.SETUP_IN_PROGRESS,
                ConfigEntryState.SETUP_RETRY,
            )
        ]
        if not other_active_entries:
            clear_yaml_cache()

        _LOGGER.info(
            "Teardown complete. Config entry %s fully unloaded.", entry.entry_id
        )
    else:
        _LOGGER.warning(
            "Platform unload failed for entry %s. Aborting teardown to prevent unstable state.",
            entry.entry_id,
        )

    return unload_ok


async def async_remove_config_entry_device(
    _hass: HomeAssistant, entry: ClimateIPConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    _LOGGER.debug(
        "Removing device %s from config entry %s",
        device_entry.id,
        entry.entry_id,
    )
    return True
