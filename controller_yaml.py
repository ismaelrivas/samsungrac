from __future__ import annotations

import logging
import types
from typing import TYPE_CHECKING, Any

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

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
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.core import HomeAssistant
    from .connection import ClimateConnection

from .const import (
    DOMAIN,
    ERR_CONTROLLER_NOT_INITIALIZED,
    ERR_PROPERTY_NOT_FOUND,
    ERR_PROPERTY_SET_FAILED,
    ERR_INVALID_DEVICE_MODE,
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
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_CONTROLLER_NAME,
    DEVICE_TYPE_TO_CONFIG_FILE,
    EXCLUDED_SUBDEVICE_IDS,
    ID_DELIMITER,
    LABEL_CURRENT_TEMP,
    LABEL_TARGET_TEMP,
    MAIN_DEVICE_ID,
)
from .controller import ClimateController, register_controller
from .controller_yaml_config import YamlConfigLoader
from .controller_yaml_polling import YamlStatePoller
from .exceptions import CannotConnect
from .properties import DeviceProperty, _parse_temperature_unit
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)


@register_controller
class YamlController(ClimateController):
    """YAML-based controller mapped as a clean Facade pattern over composition."""

    @classmethod
    def _extract_config_from_entry(
        cls, config_entry: ConfigEntry, device_id: str | None
    ) -> dict[str, Any]:
        """Extract static config strictly, merging data and options for modern HA compatibility."""
        entry_data = {**config_entry.data, **config_entry.options}
        entry_data[CONF_ENTRY_ID] = config_entry.entry_id
        
        base_unique_id = config_entry.unique_id
        entry_data[CONF_UNIQUE_ID] = (
            f"{base_unique_id}{ID_DELIMITER}{device_id}" 
            if base_unique_id is not None and device_id is not None and cls._is_subdevice(device_id) 
            else base_unique_id
        )

        if device_id is not None:
            entry_data[CONF_DEVICE_ID] = device_id
            
        return entry_data

    @classmethod
    def from_config_entry(
        cls,
        config_entry: ConfigEntry,
        hass: HomeAssistant | None = None,
        session: aiohttp.ClientSession | None = None,
        device_id: str | None = None,
        logger: logging.Logger | None = None,
    ) -> YamlController:
        """Create a YamlController instance directly from a ConfigEntry."""
        logger = logger if logger is not None else _LOGGER
        return cls(logger=logger, hass=hass, session=session, config_entry=config_entry, device_id=device_id)

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
        self.loader: YamlConfigLoader = YamlConfigLoader(self)
        self.poller: YamlStatePoller = YamlStatePoller(self)

        if config is None and config_entry is not None:
            config = self._extract_config_from_entry(config_entry, device_id)
        elif config is not None:
            config = dict(config)
        else:
            raise ValueError("Neither config dict nor ConfigEntry was provided to YamlController")

        # Fallback resolution for CONF_CONFIG_FILE based on CONF_DEVICE_TYPE
        if config.get(CONF_CONFIG_FILE) is None:
            device_type = config.get(CONF_DEVICE_TYPE)
            if device_type is not None and device_type in DEVICE_TYPE_TO_CONFIG_FILE:
                config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE[device_type]

        logger = logger if logger is not None else _LOGGER
        super().__init__(config, logger)

        self._config = types.MappingProxyType(dict(config))

        self.hass = hass
        self._session = session
        self._shared_raw_client: Any | None = None

        self._device_id = config.get(CONF_DEVICE_ID)
        self._token = config.get(CONF_TOKEN)

        self._unique_id = config.get(CONF_UNIQUE_ID)
        if self._unique_id is None:
            base_unique_id = config.get(CONF_MAC)
            if self._is_subdevice(self._device_id):
                self._unique_id = f"{base_unique_id}{ID_DELIMITER}{self._device_id}" if base_unique_id is not None else self._device_id
            else:
                self._unique_id = base_unique_id

        if self._device_id is None:
            self._device_id = self._unique_id

        raw_ip = config.get(CONF_IP_ADDRESS)
        raw_host = config.get(CONF_HOST)
        
        resolved_ip = raw_ip if isinstance(raw_ip, str) and raw_ip.strip() != "" else raw_host
        self._ip_address = resolved_ip.strip() if isinstance(resolved_ip, str) and resolved_ip.strip() != "" else None

        if self._ip_address is None:
            raise ValueError(f"Integration requires {CONF_IP_ADDRESS} or {CONF_HOST} to be explicitly set")

        # Strict Boolean Parsing (Guarded against string casting trap like 'false' -> True)
        raw_debug = config.get(CONF_DEBUG, False)
        if not isinstance(raw_debug, bool):
            raise TypeError(f"Expected strict bool for {CONF_DEBUG}, got {type(raw_debug).__name__}")
        self._debug = raw_debug

        target_temp_unit = self._config.get(CONF_TEMP_NATIVE_TARGET)
        current_temp_unit = self._config.get(CONF_TEMP_NATIVE_CURRENT)

        raw_unit = target_temp_unit if target_temp_unit is not None else current_temp_unit
        if raw_unit is not None:
            self._temperature_unit = _parse_temperature_unit(raw_unit, strict=True)
        else:
            self._temperature_unit = DEFAULT_CONF_TEMP_UNIT
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

        self._attributes[CONF_CONTROLLER] = self.id

    @staticmethod
    def match_type(controller_type: str) -> bool:
        """Return True if the given type string matches this controller."""
        if not isinstance(controller_type, str):
            raise TypeError(f"Expected str for controller_type, got {type(controller_type).__name__}")
        return controller_type.lower() == DEFAULT_CONF_CONTROLLER

    @property
    def yaml_file(self) -> str | None:
        """Return the YAML configuration file path from config."""
        return self._config.get(CONF_CONFIG_FILE)

    @property
    def connection(self) -> ClimateConnection | None:
        """Override base connection to point strictly to the loader's active connection."""
        return self.loader.connection


    @property
    def name(self) -> str:
        """Return the controller name."""
        if self.loader.name is not None:
            return self.loader.name
        raw_name = self._config.get(CONF_NAME)
        if isinstance(raw_name, str) and raw_name.strip() != "":
            return raw_name
        return DEFAULT_CONTROLLER_NAME

    @staticmethod
    def _is_subdevice(device_id: Any) -> bool:
        """Return True if device_id represents a sub-device."""
        if device_id is None:
            return False
        if not isinstance(device_id, str):
            raise TypeError(f"Expected str for device_id, got {type(device_id).__name__}")
        if device_id.strip() == "":
            return False
        return device_id not in EXCLUDED_SUBDEVICE_IDS

    @property
    def unique_id(self) -> str | None:
        """Return the pre-computed unique ID of this controller."""
        return self._unique_id

    @property
    def device_id(self) -> str | None:
        """Return the device ID of this controller."""
        return self._device_id

    @device_id.setter
    def device_id(self, value: str | None) -> None:
        """Strictly update instance state. Do NOT rebuild immutable config."""
        self._device_id = value

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
        """Strictly update instance state. Do NOT rebuild immutable config."""
        self._token = value

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
        if self.connection is None:
            return False
        diag = self.connection.get_diagnostics()
        if ATTR_IS_AVAILABLE not in diag:
            raise KeyError(f"Diagnostics missing strict {ATTR_IS_AVAILABLE} key")
            
        is_avail = diag[ATTR_IS_AVAILABLE]
        if not isinstance(is_avail, bool):
            raise TypeError(f"Expected bool for {ATTR_IS_AVAILABLE}, got {type(is_avail).__name__}")
        return is_avail

    @property
    def id(self) -> str | None:
        """Return the unique id of the controller."""
        return self._unique_id

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
        if self.loader.is_fully_initialized is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERR_CONTROLLER_NOT_INITIALIZED,
                translation_placeholders={"property": property_name}
            )

        op = self.get_property_object(property_name)
        if isinstance(op, DeviceProperty):
            try:
                self.poller.register_pending_update(property_name, new_value)
                _LOGGER.debug(
                    "%s Registered pending update for '%s': %s",
                    self.log_prefix,
                    property_name,
                    new_value,
                )
                target_device_id = device_id if (device_id is not None and isinstance(device_id, str) and device_id.strip() != "") else self.device_id
                if target_device_id is None or target_device_id == MAIN_DEVICE_ID:
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
            except (TimeoutError, OSError) as e:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key=ERR_PROPERTY_SET_FAILED,
                    translation_placeholders={"property": property_name, "error": str(e)}
                ) from e

        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=ERR_PROPERTY_NOT_FOUND,
            translation_placeholders={"property": property_name}
        )

    def get_property(self, property_name: str) -> Any:
        """Return the current value of a property by name using safe extraction."""
        obj = self.get_property_object(property_name)
        if obj is not None:
            val = obj.value
        elif property_name in self._attributes:
            val = self._attributes[property_name]
        else:
            raise KeyError(f"Property '{property_name}' is not registered in object or attributes.")
        if val is None or val == STATE_UNKNOWN:
            return None
        return val

    @property
    def _objects_by_id(self) -> dict[str, DeviceProperty]:
        """O(1) lazy-loaded cache for property/operation/sensor lookup by internal ID."""
        if self.loader.is_fully_initialized is not True:
            raise RuntimeError("Cannot build _objects_by_id cache before loader is fully initialized.")

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
        )
        return None

    def get_property_all_values(self, property_name: str) -> list[str] | None:
        """Return the complete, unfiltered list of values for a property."""
        prop = self.get_property_object(property_name)
        if prop is not None:
            all_vals = prop.all_values
            if all_vals is not None:
                if not isinstance(all_vals, (list, tuple, set)):
                    raise TypeError(f"Expected iterable for {property_name} all_vals, got {type(all_vals).__name__}")
                res = []
                for v in all_vals:
                    if v is None or isinstance(v, bool):
                        raise TypeError(f"Invalid mode value configured: {v}")
                    res.append(str(v))
                return res

        _LOGGER.debug(
            "%s Cannot get values for '%s': not an operation or missing all_values",
            self.log_prefix,
            property_name,
        )
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
        if self.loader.service_schema_map is None:
            return None
        return dict(self.loader.service_schema_map)

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
        return [sensors_dict[n] for n in self.loader.sensors_list]

    @property
    def last_poll_data(self) -> dict[str, Any] | None:
        """Return the last raw poll response, useful for diagnostics."""
        if self.loader.state_getter is not None:
            raw = self.loader.state_getter.value
            return dict(raw) if isinstance(raw, dict) else None
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
        if not isinstance(pure, dict):
            raise TypeError(f"pure_network_state must be a dict, got {type(pure).__name__}")
        return dict(pure)

    @property
    def device_state(self) -> dict[str, Any]:
        """Return the current device state via the poller's public interface."""
        state = self.poller.device_state
        if not isinstance(state, dict):
            raise TypeError(f"device_state must be a dict, got {type(state).__name__}")
        return dict(state)

    def _safe_parse_hvac_mode(self, raw_mode: Any) -> HVACMode | None:
        """Parse HVAC mode strictly. Raises ValueError/TypeError on invalid input."""
        if raw_mode is None:
            return None
        if isinstance(raw_mode, HVACMode):
            return raw_mode
        if not isinstance(raw_mode, str):
            raise TypeError(f"HVAC mode must be a string or HVACMode, got {type(raw_mode).__name__}")
        return HVACMode(raw_mode.lower())

    def _safe_parse_temperature(self, raw_value: Any, label: str) -> float | None:
        """Parse temperature strictly. Raises ValueError/TypeError on invalid input."""
        if raw_value is None:
            return None
        if isinstance(raw_value, bool):
            raise TypeError(f"Temperature for {label} cannot be a boolean, got {raw_value}")
        return float(raw_value)

    def _build_static_modes_cache(
        self,
    ) -> tuple[
        tuple[HVACMode, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        """Build and cache the static modes supported by the device."""
        hvac_raw = self.get_property_all_values(ATTR_HVAC_MODE)
        hvac_modes_list = [] if hvac_raw is None else hvac_raw
        fan_raw = self.get_property_all_values(ATTR_FAN_MODE)
        fan_modes_list = [] if fan_raw is None else fan_raw
        swing_raw = self.get_property_all_values(ATTR_SWING_MODE)
        swing_modes_list = [] if swing_raw is None else swing_raw
        preset_raw = self.get_property_all_values(ATTR_PRESET_MODE)
        preset_modes_list = [] if preset_raw is None else preset_raw
        parsed_hvac_modes = [
            mode
            for m in hvac_modes_list
            if (mode := self._safe_parse_hvac_mode(m)) is not None
        ]
        def _filter_str_modes(modes: list[Any]) -> tuple[str, ...]:
            for m in modes:
                if not isinstance(m, str):
                    raise TypeError(f"Mode must be a string, got {type(m).__name__}: {m}")
            return tuple(modes)
        return (
            tuple(parsed_hvac_modes),
            _filter_str_modes(fan_modes_list),
            _filter_str_modes(swing_modes_list),
            _filter_str_modes(preset_modes_list),
        )

    @property
    def climate_state(self) -> ClimateIPDeviceState:
        """Return the strictly typed state representation of the device."""
        try:
            if self._cached_static_modes is None:
                self._cached_static_modes = self._build_static_modes_cache()

            hvac_modes_tuple, fan_modes_tuple, swing_modes_tuple, preset_modes_tuple = (
                self._cached_static_modes
            )

            raw_hvac = self.get_property(ATTR_HVAC_MODE)
            hvac_mode = self._safe_parse_hvac_mode(raw_hvac)

            target_temp = self._safe_parse_temperature(
                self.get_property(ATTR_TEMPERATURE), LABEL_TARGET_TEMP
            )

            current_temp = self._safe_parse_temperature(
                self.get_property(ATTR_CURRENT_TEMPERATURE), LABEL_CURRENT_TEMP
            )

            raw_fan = self.get_property(ATTR_FAN_MODE)
            fan_mode = None
            if raw_fan is not None:
                if not isinstance(raw_fan, str):
                    raise TypeError(f"Fan mode must be a string, got {type(raw_fan).__name__}")
                if raw_fan not in fan_modes_tuple:
                    raise ValueError(f"{ERR_INVALID_DEVICE_MODE} [{ATTR_FAN_MODE}]: {raw_fan}")
                fan_mode = raw_fan

            raw_swing = self.get_property(ATTR_SWING_MODE)
            swing_mode = None
            if raw_swing is not None:
                if not isinstance(raw_swing, str):
                    raise TypeError(f"Swing mode must be a string, got {type(raw_swing).__name__}")
                if raw_swing not in swing_modes_tuple:
                    raise ValueError(f"{ERR_INVALID_DEVICE_MODE} [{ATTR_SWING_MODE}]: {raw_swing}")
                swing_mode = raw_swing

            raw_preset = self.get_property(ATTR_PRESET_MODE)
            preset_mode = None
            if raw_preset is not None:
                if not isinstance(raw_preset, str):
                    raise TypeError(f"Preset mode must be a string, got {type(raw_preset).__name__}")
                if raw_preset not in preset_modes_tuple:
                    raise ValueError(f"{ERR_INVALID_DEVICE_MODE} [{ATTR_PRESET_MODE}]: {raw_preset}")
                preset_mode = raw_preset

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
            )
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
        _LOGGER.debug("%s Refresh from connection requested (no-op)", self.log_prefix)

    def on_token_refreshed(self, new_token: str) -> None:
        """Callback invoked when the underlying connection refreshes an auth token.

        Acts as a safe no-op. Subclasses or specific connection handlers can
        override or observe this if token persistence is required.
        """
        _LOGGER.debug("%s Token refreshed callback received", self.log_prefix)

    def get_current_state_callback(self) -> dict[str, Any] | None:
        """Callback invoked by external pollers to request the raw current state.

        Acts as a safe no-op returning None.
        """
        return None