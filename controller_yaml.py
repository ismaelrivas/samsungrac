"""YAML-based climate device controller for the climate_ip integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_HOST,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .connection import ClimateConnection

from .const import (
    ATTR_IS_AVAILABLE,
    CONF_CONFIG_FILE,
    CONF_CONTROLLER,
    CONF_DEBUG,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_ENTRY_ID,
    CONF_NAME,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_CONTROLLER,
    DEFAULT_CONTROLLER_NAME,
    DEVICE_TYPE_TO_CONFIG_FILE,
    MAIN_DEVICE_ID,
    NON_SERIALIZABLE_KEYS,
    TRUTHY_STRINGS,
    WIFI_KIT_MGMT_ID,
)
from .controller import ClimateController, register_controller
from .controller_yaml_config import YamlConfigLoader
from .controller_yaml_polling import YamlStatePoller
from .exceptions import CannotConnect
from .properties import DeviceProperty
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = DEFAULT_CONF_CONTROLLER


@register_controller
class YamlController(ClimateController):
    """YAML-based controller mapped as a clean Facade pattern over composition."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
        hass: HomeAssistant | None = None,
        session: aiohttp.ClientSession | None = None,
        config_entry: ConfigEntry | None = None,
        device_id: str | None = None,
    ) -> None:
        """Initialize the YAML controller from a config dictionary or ConfigEntry."""
        self.loader: Any | None = None
        self.poller: Any | None = None

        if config is None and config_entry is not None:
            config = {**config_entry.data, **config_entry.options, CONF_ENTRY_ID: config_entry.entry_id}

            base_unique_id = config_entry.unique_id
            if device_id is not None and device_id != MAIN_DEVICE_ID:
                config[CONF_UNIQUE_ID] = (
                    f"{base_unique_id}_{device_id}"
                    if base_unique_id is not None
                    else device_id
                )
            else:
                config[CONF_UNIQUE_ID] = base_unique_id

            if device_id is not None:
                config[CONF_DEVICE_ID] = device_id
        elif config is None:
            config = {}
        else:
            config = dict(config)

        # Fallback resolution for CONF_CONFIG_FILE based on CONF_DEVICE_TYPE
        if config.get(CONF_CONFIG_FILE) is None:
            device_type = config.get(CONF_DEVICE_TYPE)
            if device_type is not None and device_type in DEVICE_TYPE_TO_CONFIG_FILE:
                config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE[device_type]

        if logger is None:
            logger = _LOGGER

        super().__init__(config, logger)  # pragma: no mutate
        self._config = config

        self.hass = hass
        self._session = session
        self._shared_raw_client: Any | None = None

        # Purge non-serializable objects from configuration
        for non_serializable in NON_SERIALIZABLE_KEYS:
            self._config.pop(non_serializable, None)  # pragma: no mutate

        self._device_id = config.get(CONF_DEVICE_ID)
        self._token = config.get(CONF_TOKEN)

        base_unique_id = config_entry.unique_id if config_entry else config.get(CONF_UNIQUE_ID)
        if base_unique_id is None:
            base_unique_id = config.get(CONF_MAC)

        # If device_id exists and is a real sub-device (neither "main" nor "0"):
        if self._device_id is not None and self._device_id not in (MAIN_DEVICE_ID, WIFI_KIT_MGMT_ID):
            self._unique_id = f"{base_unique_id}_{self._device_id}" if base_unique_id is not None else self._device_id
        else:
            # Monosplit / Main device: Pure MAC address without suffixes
            self._unique_id = base_unique_id

        if self._device_id is None:
            self._device_id = self._unique_id

        ip_from_config = config.get(CONF_IP_ADDRESS)
        self._ip_address = ip_from_config if ip_from_config is not None else config.get(CONF_HOST)
        if self._ip_address is None:
            _LOGGER.warning(
                "%s Neither %s nor %s present in configuration",
                self.log_prefix,
                CONF_IP_ADDRESS,
                CONF_HOST,
            )

        # Strict Boolean Parsing (Guarded against string casting trap like 'false' -> True)
        raw_debug = config.get(CONF_DEBUG, False)
        if isinstance(raw_debug, str):
            self._debug = raw_debug.lower() in TRUTHY_STRINGS
        else:
            self._debug = bool(raw_debug)

        target_temp_unit = self._config.get(CONF_TEMP_NATIVE_TARGET)
        current_temp_unit = self._config.get(CONF_TEMP_NATIVE_CURRENT)

        if target_temp_unit is not None:
            self._temperature_unit = str(target_temp_unit)
        elif current_temp_unit is not None:
            self._temperature_unit = str(current_temp_unit)
        else:
            self._temperature_unit = UnitOfTemperature.CELSIUS
        self._attributes: dict[str, Any] = {}

        self._obj_id_cache: dict[str, DeviceProperty] | None = None
        self._cached_static_modes: (
            tuple[
                tuple[HVACMode, ...],
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
            ]
            | None
        ) = None

        self.loader = YamlConfigLoader(self)
        self.poller = YamlStatePoller(self)
        self._attributes[CONF_CONTROLLER] = self.id

    @staticmethod
    def match_type(controller_type: str) -> bool:
        """Return True if the given type string matches this controller."""
        return str(controller_type).lower() == CONST_CONTROLLER_TYPE

    @property
    def yaml_file(self) -> str | None:
        """Return the YAML configuration file path from config."""
        return self._config.get(CONF_CONFIG_FILE)

    @property
    def connection(self) -> ClimateConnection | None:
        """Override base connection to point strictly to the loader's active connection."""
        return self.loader.connection

    @property
    def fan_modes_list_changed_pending_flicker(self) -> bool:
        """Expose the flicker flag from the poller delegate."""
        return self.poller.fan_modes_list_changed_pending_flicker

    @fan_modes_list_changed_pending_flicker.setter
    def fan_modes_list_changed_pending_flicker(self, value: bool) -> None:
        """Set the flicker flag on the poller delegate."""
        self.poller.fan_modes_list_changed_pending_flicker = value

    @property
    def name(self) -> str:
        """Return the controller name."""
        if self.loader is not None and self.loader.name:
            return self.loader.name
        return str(self._config.get(CONF_NAME, DEFAULT_CONTROLLER_NAME))

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID of this controller."""
        if (
            self._unique_id is not None
            and self._device_id is not None
            and self._device_id != MAIN_DEVICE_ID
            and self._device_id != self._unique_id
        ):
            suffix = f"_{self._device_id}"
            if not self._unique_id.endswith(suffix):
                return f"{self._unique_id}{suffix}"
        return self._unique_id

    @property
    def device_id(self) -> str | None:
        """Return the device ID of this controller."""
        return self._device_id

    @device_id.setter
    def device_id(self, value: str | None) -> None:
        """Update the device ID and its internal configuration."""
        self._device_id = value
        self._config[CONF_DEVICE_ID] = value

    @property
    def config(self) -> dict[str, Any]:
        """Return the controller configuration dictionary."""
        return dict(self._config)

    @property
    def token(self) -> str | None:
        """Return the authentication token."""
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        """Update the authentication token."""
        self._token = value
        self._config[CONF_TOKEN] = value

    @property
    def ip_address(self) -> str | None:
        """Return the IP address."""
        return self._ip_address

    @property
    def host(self) -> str | None:
        """Return the host or IP address."""
        return self.ip_address

    @property
    def debug(self) -> bool:
        """Return the debug flag."""
        return self._debug

    @property
    def poll(self) -> bool | None:
        """Return the polling state from the YAML configuration."""
        return self.loader.poll

    @property
    def available(self) -> bool:
        """Return True if the controller is connected and available."""
        if self.connection is not None:
            return bool(self.connection.get_diagnostics().get(ATTR_IS_AVAILABLE, True))
        return True

    @property
    def id(self) -> str | None:
        """Return the unique id of the controller."""
        return self.unique_id

    async def initialize(self) -> bool:
        """Perform initial YAML configuration loading and set up the base connection."""
        return await self.loader.async_initialize()

    async def async_set_property(
        self,
        property_name: str,
        new_value: Any,
        device_id: str | None = None,
    ) -> bool:
        """Asynchronously set a property on the device."""
        if not self.loader.is_fully_initialized:
            _LOGGER.error(  # pragma: no mutate
                "%s Cannot set property '%s': controller not fully initialized",
                self.log_prefix,
                property_name,
            )  # pragma: no mutate
            return False

        op = self.get_property_object(property_name)
        if isinstance(op, DeviceProperty):
            try:
                self.poller.register_pending_update(property_name, new_value)
                _LOGGER.debug(  # pragma: no mutate
                    "%s Registered pending update for '%s': %s",
                    self.log_prefix,
                    property_name,
                    new_value,
                )  # pragma: no mutate
                target_device_id = device_id if device_id is not None else self.device_id
                if target_device_id in (None, "", MAIN_DEVICE_ID):
                    target_device_id = self._unique_id

                return await op.async_set_value(new_value, target_device_id)
            except (
                CannotConnect,
                HomeAssistantError,
            ) as e:
                _LOGGER.debug(
                    "%s Setting property '%s' with value '%s' failed: %s",
                    self.log_prefix,
                    property_name,
                    new_value,
                    e,
                )
                raise
            except (TimeoutError, OSError, ValueError) as e:
                _LOGGER.warning(
                    "%s Unexpected error setting property '%s' with value '%s': %s",
                    self.log_prefix,
                    property_name,
                    new_value,
                    e,
                )
                raise HomeAssistantError(
                    f"Failed to set property '{property_name}': {e}"
                ) from e

        _LOGGER.error(  # pragma: no mutate
            "%s Failed to set property '%s': property not found",
            self.log_prefix,
            property_name,
        )  # pragma: no mutate
        return False

    def get_property(self, property_name: str) -> Any:
        """Return the current value of a property by name using safe extraction."""
        obj = self.get_property_object(property_name)
        val = obj.value if obj is not None else self._attributes.get(property_name)
        if val == STATE_UNKNOWN:
            return None
        return val

    @property
    def _objects_by_id(self) -> dict[str, DeviceProperty]:
        """O(1) lazy-loaded cache for property/operation/sensor lookup by internal ID."""
        if self._obj_id_cache is None:
            self._obj_id_cache = {
                op.id: op
                for collection in (
                    self.loader.operations,
                    self.loader.properties,
                    self.loader.sensors,
                )
                for op in collection.values()
                if op.id is not None
            }
        return self._obj_id_cache

    def get_property_object(self, property_name: str) -> DeviceProperty | None:
        """Return the property object by name, internal ID, or mapped HASS attribute."""
        if property_name in self.loader.operations:
            return self.loader.operations[property_name]
        if property_name in self.loader.properties:
            return self.loader.properties[property_name]
        if property_name in self.loader.sensors:
            return self.loader.sensors[property_name]

        obj = self._objects_by_id.get(property_name)
        if obj is not None:
            return obj

        mapped_op_id = self.poller.get_hass_attr_for_op_id(property_name)
        if mapped_op_id is not None and mapped_op_id != property_name:
            obj = self._objects_by_id.get(mapped_op_id)
            if obj is not None:
                return obj

        _LOGGER.warning(
            "%s Property object '%s' not found.",
            self.log_prefix,
            property_name,
        )  # pragma: no mutate
        return None

    def get_property_all_values(self, property_name: str) -> list[str] | None:
        """Return the complete, unfiltered list of values for a property."""
        prop = self.get_property_object(property_name)
        if prop is not None and bool(prop.all_values):
            return list(prop.all_values)

        _LOGGER.debug(  # pragma: no mutate
            "%s Cannot get values for '%s': not an operation or missing all_values",
            self.log_prefix,
            property_name,
        )  # pragma: no mutate
        return None

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return a copy of the state attributes dictionary."""
        return dict(self._attributes)

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit in use (resolved at construction time)."""
        return self._temperature_unit

    @property
    def service_schema_map(self) -> dict[str, Any] | None:
        """Return the voluptuous service schema map."""
        raw = self.loader.service_schema_map
        return dict(raw) if raw is not None else None

    @property
    def operations(self) -> list[str]:
        """Return the list of settable operation names."""
        return list(self.loader.operations_list)

    @property
    def attributes(self) -> list[str]:
        """Return the list of read-only attribute names."""
        return list(self.loader.properties_list)

    @property
    def sensors(self) -> list[DeviceProperty]:
        """Return a list of all defined sensor property objects."""
        sensors_dict = self.loader.sensors
        return [
            sensors_dict[n]
            for n in self.loader.sensors_list
            if n in sensors_dict
        ]

    @property
    def last_poll_data(self) -> dict[str, Any] | None:
        """Return the last raw poll response, useful for diagnostics."""
        if self.loader.state_getter is not None:
            raw = self.loader.state_getter.value
            return dict(raw) if isinstance(raw, dict) else raw
        return None

    @property
    def connection_diagnostics(self) -> dict[str, Any]:
        """Return connection diagnostic info from the underlying connection."""
        if self.connection is not None:
            return dict(self.connection.get_diagnostics())
        return {}

    @property
    def pure_device_state(self) -> dict[str, Any]:
        """Return the unmutated pure network state of the device."""
        pure = self.poller.pure_network_state
        if bool(pure):
            return dict(pure)
        return self.device_state

    @property
    def device_state(self) -> dict[str, Any]:
        """Return the current device state via the poller's public interface."""
        state = self.poller.device_state
        if bool(state):
            return dict(state)
        if self.loader.state_getter is not None:
            getter_value = self.loader.state_getter.value
            return dict(getter_value) if getter_value is not None else {}
        return {}

    def _safe_parse_hvac_mode(self, raw_mode: Any) -> HVACMode | None:
        """Safely parse HVAC mode, returning None on invalid value."""
        if raw_mode is None:
            return None

        try:
            return HVACMode(str(raw_mode).lower())
        except ValueError:
            _LOGGER.warning(
                "%s Invalid HVAC mode string received for cache: %s",
                self.log_prefix,
                raw_mode,
            )
            return None

    def _safe_parse_temperature(self, raw_value: Any, label: str) -> float | None:
        """Safely parse a temperature value, returning None on invalid input."""
        if raw_value is None:
            return None
        try:
            return float(raw_value)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "%s Invalid %s value: %s",
                self.log_prefix,
                label,
                raw_value,
            )
            return None

    @property
    def climate_state(self) -> ClimateIPDeviceState:
        """Return the strictly typed state representation of the device."""
        try:
            raw_hvac = self.get_property(ATTR_HVAC_MODE)
            hvac_mode = self._safe_parse_hvac_mode(raw_hvac)

            target_temp = self._safe_parse_temperature(
                self.get_property(ATTR_TEMPERATURE), "target temperature"
            )

            current_temp = self._safe_parse_temperature(
                self.get_property(ATTR_CURRENT_TEMPERATURE), "current temperature"
            )

            raw_fan = self.get_property(ATTR_FAN_MODE)
            fan_mode = str(raw_fan) if raw_fan is not None else None

            raw_swing = self.get_property(ATTR_SWING_MODE)
            swing_mode = str(raw_swing) if raw_swing is not None else None

            raw_preset = self.get_property(ATTR_PRESET_MODE)
            preset_mode = str(raw_preset) if raw_preset is not None else None

            if self._cached_static_modes is None:
                raw_hvac_modes = self.get_property_all_values(ATTR_HVAC_MODE)
                hvac_modes_list = raw_hvac_modes if raw_hvac_modes is not None else []

                raw_fan_modes = self.get_property_all_values(ATTR_FAN_MODE)
                fan_modes_list = raw_fan_modes if raw_fan_modes is not None else []

                raw_swing_modes = self.get_property_all_values(ATTR_SWING_MODE)
                swing_modes_list = raw_swing_modes if raw_swing_modes is not None else []

                raw_preset_modes = self.get_property_all_values(ATTR_PRESET_MODE)
                preset_modes_list = raw_preset_modes if raw_preset_modes is not None else []

                self._cached_static_modes = (
                    tuple(
                        mode
                        for m in hvac_modes_list
                        if m is not None
                        for mode in [self._safe_parse_hvac_mode(m)]
                        if mode is not None
                    ),
                    tuple(
                        str(m)
                        for m in fan_modes_list
                        if m is not None
                    ),
                    tuple(
                        str(m)
                        for m in swing_modes_list
                        if m is not None
                    ),
                    tuple(
                        str(m)
                        for m in preset_modes_list
                        if m is not None
                    ),
                )

            hvac_modes_tuple, fan_modes_tuple, swing_modes_tuple, preset_modes_tuple = (
                self._cached_static_modes
            )

            return ClimateIPDeviceState(
                hvac_mode=hvac_mode,
                target_temperature=target_temp,
                current_temperature=current_temp,
                fan_mode=fan_mode,
                swing_mode=swing_mode,
                preset_mode=preset_mode,
                hvac_modes=hvac_modes_tuple,
                fan_modes=fan_modes_tuple,
                swing_modes=swing_modes_tuple,
                preset_modes=preset_modes_tuple,
            )
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "%s Error coercing typed ClimateIPDeviceState: %s", self.log_prefix, err
            )  # pragma: no mutate
            raise

    async def async_get_status(self) -> dict[str, Any] | None:
        """Fetch the device status using the poller."""
        return await self.poller.async_get_status()

    async def async_update_state(self) -> dict[str, Any] | None:
        """Update the entity state values."""
        return await self.poller.async_update_state()

    def clear_state_cache(self) -> None:
        """Clear cached state in poller and static mode cache to prevent ghosting."""
        self._cached_static_modes = None
        self._obj_id_cache = None
        if self.poller is not None:
            self.poller.clear_state_cache()

    async def async_merge_device_state(self, new_data: dict[str, Any]) -> bool:
        """Merge incoming push updates or responses into the memory state."""
        return await self.poller.async_merge_device_state(new_data)

    async def async_clear_pending_updates(self, keys: list[str]) -> None:
        """Clear specific pending updates (anti-flicker locks) on failure."""
        self.poller.clear_pending_updates(keys)

    async def async_predict_and_correct_state(
        self, current_hass_state: Any, property_name: str, new_value: Any
    ) -> tuple[ClimateEntityFeature, dict[str, Any]]:
        """Predict expected state changes based on a command."""
        return await self.poller.async_predict_and_correct_state(
            current_hass_state, property_name, new_value
        )

    async def async_shutdown(self) -> None:
        """Shut down the controller and clean up connections."""
        await self.poller.async_shutdown()

    @property
    def is_push_device(self) -> bool:
        """Return True if the device uses push-based updates."""
        if self.connection is None:
            return False

        return self.connection.is_push_supported

    @property
    def shared_raw_client(self) -> Any | None:
        """Return the shared raw socket client."""
        return self._shared_raw_client

    @shared_raw_client.setter
    def shared_raw_client(self, client: Any | None) -> None:
        """Set the shared raw socket client."""
        self._shared_raw_client = client

    async def async_refresh_from_connection(self) -> None:
        """Refresh the controller's properties from the connection's internal state.

        Obligatory implementation to fulfill ClimateController's strict ABC contract.
        Acts as a safe no-op for YAML-based devices.
        """
        pass

    def on_token_refreshed(self, new_token: str) -> None:
        """Callback invoked when the underlying connection refreshes an auth token.

        Acts as a safe no-op. Subclasses or specific connection handlers can
        override or observe this if token persistence is required.
        """
        pass

    def get_current_state_callback(self) -> dict[str, Any] | None:
        """Callback invoked by external pollers to request the raw current state.

        Acts as a safe no-op returning None.
        """
        return None