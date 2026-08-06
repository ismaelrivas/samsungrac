"""The Samsung Climate IP integration."""

import logging
from typing import Any

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_MAC, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONFIG_ENTRY_VERSION,
    DEVICE_TYPE_TO_CONFIG_FILE,
    DOMAIN,
    MAIN_DEVICE_ID,
    WIFI_KIT_MGMT_ID,
)
from .controller_yaml import YamlController
from .controller_yaml_config import clear_yaml_cache
from .coordinator import SamsungClimateCoordinator

# Import connection classes to ensure they register themselves via decorators
from .connection_aiohttp import ConnectionAiohttp8888  # noqa: F401
from .connection_raw import ConnectionRaw8888  # noqa: F401
from .connection_request import ConnectionRequest, ConnectionRequestPrint  # noqa: F401
from .connection_request_tls_auto import ConnectionRequestTlsAuto  # noqa: F401
from .samsung_2878 import ConnectionSamsung2878  # noqa: F401

_LOGGER = logging.getLogger(__name__)

type ClimateIPConfigEntry = ConfigEntry[dict[str, SamsungClimateCoordinator]]

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ClimateIPConfigEntry) -> bool:
    """Migrate old config entry to new version."""
    _LOGGER.debug("Migrating climate_ip config entry from version %s to %s", entry.version, CONFIG_ENTRY_VERSION)

    if entry.version == 1:
        # v1 → v2: Validating schema to ensure integrity.
        v2_schema = vol.Schema(
            {
                vol.Required("ip_address"): cv.string,
                vol.Optional("token"): cv.string,
                vol.Optional("mac"): cv.string,
            },
            extra=vol.ALLOW_EXTRA,
        )

        try:
            v2_schema(dict(entry.data))
        except vol.Invalid as err:
            _LOGGER.error("Migration failed: v1 payload structurally invalid - %s", err)
            return False

        _LOGGER.info("Config entry migration v1 → v2 complete (schema validated).")

    if entry.version > CONFIG_ENTRY_VERSION:
        # This should not happen in normal operation, but guard against downgrades.
        _LOGGER.error("Config entry version %s is newer than the integration supports (%s). Please update the integration.", entry.version, CONFIG_ENTRY_VERSION)
        return False

    hass.config_entries.async_update_entry(entry, version=CONFIG_ENTRY_VERSION)
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    # This is called when the user changes options in the UI.
    # Reloading the entry triggers async_unload_entry, which performs the definitive cleanup.
    _LOGGER.debug(
        "Configuration options updated, reloading climate_ip integration for entry %s",
        entry.entry_id,
  )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ClimateIPConfigEntry) -> bool:  # pylint: disable=import-outside-toplevel,too-many-locals,too-many-branches,too-many-statements
    """Set up Samsung Climate IP from a config entry."""

    # Merge options into runtime_config at startup so settings from the OptionsFlow
    # (like conn_method) are available to the controller right from the start.
    runtime_config: dict[str, Any] = {**entry.data, **entry.options}
    runtime_config["unique_id"] = entry.unique_id
    runtime_config["entry_id"] = entry.entry_id

    device_type = runtime_config.get(CONF_DEVICE_TYPE)
    if device_type:
        runtime_config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)

    # Use the official session manager. Network steps controlled by timeouts
    # in the request itself or at the coordinator interval level.
    session = async_get_clientsession(hass)

    _LOGGER.info("Starting setup for device %s at %s (Device Type: %s)", runtime_config.get(CONF_MAC, "Unknown"), runtime_config.get("ip_address", "Unknown"), device_type)

    devices_config = runtime_config.get(CONF_DEVICES)

    # Normalize: If no sub-devices are defined, create a synthetic list for the main unit
    if not devices_config:
        devices_config = [{"id": MAIN_DEVICE_ID, "name": entry.data.get("name", entry.title)}]

    _LOGGER.debug("Climate IP setup. devices_config: %s", devices_config)

    coordinators: dict[str, SamsungClimateCoordinator] = {}

    for device_info in devices_config:
        device_id = device_info.get("id")
        device_name = device_info.get("name")
        device_uuid = device_info.get("uuid")

        if device_id == WIFI_KIT_MGMT_ID:
            _LOGGER.debug("Skipping Wifi-kit management device (ID 0)")
            continue

        device_config_data = runtime_config.copy()

        # Ensure the controller receives its specific UI name
        if device_name:
            device_config_data["name"] = device_name

        # Unique ID generation logic
        if device_id != MAIN_DEVICE_ID:
            device_config_data[CONF_DEVICE_ID] = device_id
            base_unique_id = device_uuid or entry.unique_id
            if base_unique_id and f"_{device_id}" not in str(base_unique_id):
                device_config_data["unique_id"] = f"{base_unique_id}_{device_id}"
            else:
                device_config_data["unique_id"] = base_unique_id
        else:
            device_config_data["unique_id"] = entry.unique_id

        _LOGGER.info("Setting up Samsung unit '%s' (ID %s) with unique_id: %s", device_name, device_id, device_config_data["unique_id"])

        controller = YamlController(
            config=device_config_data, logger=_LOGGER, hass=hass, session=session
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
            raise ConfigEntryNotReady(
                f"Transient network failure initializing device {device_name}: {ex}"
            ) from ex

        if not initialized:
            _LOGGER.debug("%s Failed to initialize controller for %s", controller.log_prefix, device_name, exc_info=True)
            continue

        coordinator = SamsungClimateCoordinator(
            hass,
            controller,
            entry,
            device_info=device_info if device_id != MAIN_DEVICE_ID else None,
            parent_unique_id=entry.unique_id if device_id != MAIN_DEVICE_ID else None,
        )

        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as ex:
            _LOGGER.error("%s Initial connection failed: %s", controller.log_prefix, ex)
            raise ConfigEntryNotReady(f"Device unreachable during startup: {ex}") from ex

        coordinators[device_id] = coordinator

    if not coordinators:
        _LOGGER.error("No coordinators could be set up for entry %s", entry.title)
        raise ConfigEntryNotReady(f"No coordinators could be set up for entry {entry.title}")

    # Contract strictly fulfilled: runtime_data is ALWAYS a dict
    entry.runtime_data = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Add listener for options changes.
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClimateIPConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.entry_id)

    # 1. UNLOAD PLATFORMS FIRST
    # Halt all entity polling and state updates before severing the network connection.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # 2. TERMINATE BACKGROUND TASKS
        # Safely shut down all coordinators and underlying socket/aiohttp connections
        if entry.runtime_data:
            _LOGGER.debug(
                "Terminating active connections and coordinators for entry %s", entry.entry_id
            )
            for device_id, coordinator in entry.runtime_data.items():
                _LOGGER.debug("Executing async_shutdown for device ID: %s", device_id)
                try:
                    await coordinator.async_shutdown()
                except Exception as ex:
                    # Fail-fast: Log the teardown failure but do not halt the unload sequence
                    _LOGGER.error("Failed to cleanly shutdown coordinator for device %s: %s", device_id, ex)

            # 3. PURGE MEMORY FOOTPRINT
            # Explicitly clear the dictionary to drop controller references immediately, 
            # ensuring no dangling pointers prevent garbage collection.
            entry.runtime_data.clear()

        # Clear the YAML cache only if this is the last active config entry for climate_ip
        other_active_entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state == ConfigEntryState.LOADED
        ]
        if not other_active_entries:
            clear_yaml_cache()

        _LOGGER.info("Teardown complete. Config entry %s fully unloaded.", entry.entry_id)
    else:
        _LOGGER.warning("Platform unload failed for entry %s. Aborting teardown to prevent unstable state.", entry.entry_id)

    return unload_ok


async def async_remove_config_entry_device(
    _hass: HomeAssistant, entry: ClimateIPConfigEntry, device_entry: Any
) -> bool:
    """Remove a config entry from a device."""
    _LOGGER.debug(
        "Removing device %s from config entry %s",
        device_entry.id,
        entry.entry_id,
    )
    # If the user removes a device from the integrations page, this allows HA to delete it
    # from the Device Registry if the integration confirms it's okay (returning True).
    # Since we dynamically re-add devices upon startup if they exist, returning True is safe
    # and allows garbage collection of "orphaned" units if a sub-unit is permanently removed.
    return True
