from __future__ import annotations

import aiohttp
import logging
import math
import types
from typing import TYPE_CHECKING, Any, Callable, Coroutine

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
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .connection import Connection

from .const import (
    DOMAIN,
    ERR_CONTROLLER_NOT_INITIALIZED,
    ERR_PROPERTY_NOT_FOUND,
    ERR_PROPERTY_SET_FAILED,
    ERR_INVALID_DEVICE_MODE,
    ERR_MISSING_INIT_CONFIG,
    ERR_UNREGISTERED_PROPERTY,
    ERR_CACHE_UNINITIALIZED,
    ERR_INVALID_STATE_TYPE,
    ERR_MISSING_IP,
    ERR_MISSING_DIAGNOSTICS,
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
)
from .controller import ClimateController, register_controller
from .controller_yaml_config import YamlConfigLoader
from .controller_yaml_polling import YamlStatePoller
from .properties import DeviceProperty, _parse_temperature_unit
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)


@register_controller
class YamlController(ClimateController):
    """YAML-based controller mapped as a clean Facade pattern over composition."""

    @classmethod
    def _extract_config_from_entry(
        cls, config_entry: ConfigEntry[Any], device_id: str | None
    ) -> dict[str, Any]:
        """Extract config enforcing flow segregation and immutable hardware credentials."""
        base_unique_id: str | None = config_entry.unique_id
        resolved_unique_id: str | None = (
            f"{base_unique_id}{ID_DELIMITER}{device_id}"
            if (base_unique_id is not None and device_id is not None and cls._is_subdevice(device_id))
            else base_unique_id
        )

        # Base immutable data from entry creation selectively merged with runtime options
        extracted: dict[str, Any] = dict(config_entry.data)
        for key, value in config_entry.options.items():
            if key not in (
                CONF_HOST,
                CONF_IP_ADDRESS,
                CONF_MAC,
                CONF_TOKEN,
                CONF_ENTRY_ID,
                CONF_DEVICE_ID,
                CONF_UNIQUE_ID,
                CONF_DEVICE_TYPE,
            ):
                extracted[key] = value

        extracted[CONF_ENTRY_ID] = config_entry.entry_id
        extracted[CONF_UNIQUE_ID] = resolved_unique_id
        if device_id is not None:
            extracted[CONF_DEVICE_ID] = device_id

        return extracted

    @classmethod
    def from_config_entry(
        cls,
        config_entry: ConfigEntry[Any],
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
        config_entry: ConfigEntry[Any] | None = None,
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
            raise ValueError(ERR_MISSING_INIT_CONFIG)

        # Fallback resolution for CONF_CONFIG_FILE based on CONF_DEVICE_TYPE
        if config.get(CONF_CONFIG_FILE) is None:
            device_type = config.get(CONF_DEVICE_TYPE)
            if device_type is not None:
                if not isinstance(device_type, str):
                    raise TypeError(f"Expected str for {CONF_DEVICE_TYPE}, got {type(device_type).__name__}")
                if device_type in DEVICE_TYPE_TO_CONFIG_FILE:
                    config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE[device_type]

        logger = logger if logger is not None else _LOGGER
        super().__init__(config, logger)

        self._config = types.MappingProxyType(dict(config))

        self.hass = hass
        self._session = session

        raw_device_id = config.get(CONF_DEVICE_ID)
        if raw_device_id is not None:
            if not isinstance(raw_device_id, str):
                raise TypeError(f"Expected str for {CONF_DEVICE_ID}, got {type(raw_device_id).__name__}")
            if len(raw_device_id.strip()) == 0:
                raise ValueError(f"{CONF_DEVICE_ID} cannot be empty")
            self._device_id: str | None = raw_device_id.strip()
        else:
            self._device_id = None

        raw_token = config.get(CONF_TOKEN)
        if raw_token is not None:
            if not isinstance(raw_token, str):
                raise TypeError(f"Expected str for {CONF_TOKEN}, got {type(raw_token).__name__}")
            if len(raw_token.strip()) == 0:
                raise ValueError(f"{CONF_TOKEN} cannot be empty")
            self._token: str | None = raw_token.strip()
        else:
            self._token = None

        raw_unique_id = config.get(CONF_UNIQUE_ID)
        if raw_unique_id is not None:
            if not isinstance(raw_unique_id, str):
                raise TypeError(f"Expected str for {CONF_UNIQUE_ID}, got {type(raw_unique_id).__name__}")
            self._unique_id: str | None = raw_unique_id.strip() if len(raw_unique_id.strip()) > 0 else None
        else:
            self._unique_id = None

        if self._unique_id is None:
            raw_mac = config.get(CONF_MAC)
            if raw_mac is not None:
                if not isinstance(raw_mac, str):
                    raise TypeError(f"Expected str for {CONF_MAC}, got {type(raw_mac).__name__}")
                base_unique_id: str | None = raw_mac.strip() if len(raw_mac.strip()) > 0 else None
            else:
                base_unique_id = None

            if self._is_subdevice(self._device_id):
                self._unique_id = (
                    f"{base_unique_id}{ID_DELIMITER}{self._device_id}"
                    if base_unique_id is not None
                    else self._device_id
                )
            else:
                self._unique_id = base_unique_id

        if self._device_id is None:
            self._device_id = self._unique_id

        raw_ip = config.get(CONF_IP_ADDRESS)
        raw_host = config.get(CONF_HOST)
        
        if raw_ip is not None and not isinstance(raw_ip, str):
            raise TypeError(f"{CONF_IP_ADDRESS} must be a string")
        if raw_host is not None and not isinstance(raw_host, str):
            raise TypeError(f"{CONF_HOST} must be a string")
            
        resolved_ip = (
            raw_ip
            if (raw_ip is not None and len(raw_ip.strip()) > 0)
            else raw_host
        )
        if resolved_ip is None or len(resolved_ip.strip()) == 0:
            raise ValueError(ERR_MISSING_IP)
        self._ip_address = resolved_ip.strip()

        # Strict Boolean Parsing (Guarded against string casting trap like 'false' -> True)
        raw_debug = config[CONF_DEBUG] if CONF_DEBUG in config else False
        if not isinstance(raw_debug, bool):
            raise TypeError(f"Expected strict bool for {CONF_DEBUG}, got {type(raw_debug).__name__}")
        self._debug = raw_debug

        target_temp_unit = self._config.get(CONF_TEMP_NATIVE_TARGET)
        current_temp_unit = self._config.get(CONF_TEMP_NATIVE_CURRENT)

        raw_unit = target_temp_unit if target_temp_unit is not None else current_temp_unit
        if raw_unit is not None:
            self._temperature_unit = _parse_temperature_unit(raw_unit)
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

    @staticmethod
    def match_type(controller_type: str) -> bool:
        """Return True if the given type string matches this controller."""
        if not isinstance(controller_type, str):
            raise TypeError(f"Expected str for controller_type, got {type(controller_type).__name__}")
        return controller_type.lower() == DEFAULT_CONF_CONTROLLER

    @property
    def yaml_file(self) -> str | None:
        """Return the YAML configuration file path from config."""
        val = self._config.get(CONF_CONFIG_FILE)
        if val is not None and not isinstance(val, str):
            raise TypeError(f"Expected str for {CONF_CONFIG_FILE}, got {type(val).__name__}")
        return val

    @property
    def connection(self) -> Connection | None:
        """Override base connection to point strictly to the loader's active connection."""
        return self.loader.connection


    @property
    def name(self) -> str:
        """Return the controller name prioritizing user configuration over YAML loader default."""
        config_name = self._config.get(CONF_NAME)
        if config_name is not None:
            if not isinstance(config_name, str):
                raise TypeError(f"Expected str for {CONF_NAME}, got {type(config_name).__name__}")
            if len(config_name.strip()) == 0:
                raise ValueError(f"{CONF_NAME} cannot be empty")
            return config_name

        loader_name = self.loader.name
        if loader_name is not None:
            if not isinstance(loader_name, str):
                raise TypeError("Loader name must be a string")
            if len(loader_name.strip()) == 0:
                raise ValueError("Loader name cannot be empty")
            return loader_name

        return DEFAULT_CONTROLLER_NAME

    @staticmethod
    def _is_subdevice(device_id: Any) -> bool:
        """Return True if device_id represents a sub-device."""
        if device_id is None:
            return False
        if not isinstance(device_id, str):
            raise TypeError(f"Expected str for device_id, got {type(device_id).__name__}")
        if len(device_id.strip()) == 0:
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
        if value is not None:
            if not isinstance(value, str):
                raise TypeError(f"Expected str for device_id, got {type(value).__name__}")
            if len(value.strip()) == 0:
                raise ValueError("device_id cannot be empty")
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
        if value is not None:
            if not isinstance(value, str):
                raise TypeError(f"Expected str for token, got {type(value).__name__}")
            if len(value.strip()) == 0:
                raise ValueError("token cannot be empty")
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
            raise KeyError(ERR_MISSING_DIAGNOSTICS)
            
        is_avail = diag[ATTR_IS_AVAILABLE]
        if not isinstance(is_avail, bool):
            raise TypeError(f"Expected bool for {ATTR_IS_AVAILABLE}, got {type(is_avail).__name__}")
        return is_avail

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
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(f"Expected non-empty str for property_name, got {property_name!r}")

        if not self.loader.is_fully_initialized:
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
                if device_id is not None and not isinstance(device_id, str):
                    raise TypeError(f"device_id must be a string, got {type(device_id).__name__}")
                
                target_device_id = (
                    device_id
                    if (device_id is not None and len(device_id.strip()) > 0)
                    else self.device_id
                )
                if target_device_id is None or not self._is_subdevice(target_device_id):
                    target_device_id = self._unique_id

                return await op.async_set_value(new_value, target_device_id)
            except HomeAssistantError:
                self.poller.clear_pending_updates([property_name])
                raise
            except (TimeoutError, OSError, aiohttp.ClientError) as e:
                self.poller.clear_pending_updates([property_name])
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key=ERR_PROPERTY_SET_FAILED,
                    translation_placeholders={"property": property_name, "error": str(e)}
                ) from e

        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=ERR_PROPERTY_NOT_FOUND,
            translation_placeholders={"property": property_name}
        )

    def has_property(self, property_name: str) -> bool:
        """Return True if the property is structurally mapped."""
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(f"Expected non-empty str for property_name, got {property_name!r}")
        return self.get_property_object(property_name) is not None or property_name in self._attributes

    def get_property(self, property_name: str) -> Any:
        """Return the current value of a property by name using safe extraction."""
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(f"Expected non-empty str for property_name, got {property_name!r}")
        obj = self.get_property_object(property_name)
        if obj is not None:
            val = obj.value
        elif property_name in self._attributes:
            val = self._attributes[property_name]
        else:
            raise KeyError(f"{ERR_UNREGISTERED_PROPERTY} [{property_name}]")
        if val is None or val == STATE_UNKNOWN:
            return None
        return val

    @property
    def _objects_by_id(self) -> dict[str, DeviceProperty]:
        """O(1) cached lookup dictionary for properties, operations, and sensors."""
        if not self.loader.is_fully_initialized:
            raise RuntimeError(ERR_CACHE_UNINITIALIZED)

        if self._obj_id_cache is None:
            cache: dict[str, DeviceProperty] = {}
            for collection in (
                self.loader.sensors,
                self.loader.properties,
                self.loader.operations,
            ):
                for op in collection.values():
                    if op.id is not None:
                        cache[op.id] = op
            self._obj_id_cache = cache
        return self._obj_id_cache

    def get_property_object(self, property_name: str) -> DeviceProperty | None:
        """Return the property object by name, internal ID, or mapped HASS attribute."""
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(f"Expected non-empty str for property_name, got {property_name!r}")

        if not self.loader.is_fully_initialized:
            return None

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
            return self._objects_by_id.get(mapped_op_id)

        return None

    def get_property_all_values(self, property_name: str) -> list[str] | None:
        """Return the complete, unfiltered list of values for a property."""
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(f"Expected non-empty str for property_name, got {property_name!r}")
        prop = self.get_property_object(property_name)
        if prop is not None:
            all_vals = prop.all_values
            if all_vals is not None:
                if not isinstance(all_vals, (list, tuple, set)):
                    raise TypeError(f"Expected iterable for {property_name} all_vals, got {type(all_vals).__name__}")
                res = []
                for v in all_vals:
                    if not isinstance(v, str):
                        raise TypeError(f"Mode value must be a string, got {type(v).__name__}: {v}")
                    res.append(v)
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
    def temperature_unit(self) -> UnitOfTemperature:
        """Return the temperature unit in use (resolved at construction time)."""
        if not isinstance(self._temperature_unit, UnitOfTemperature):
            raise TypeError(f"Invalid temperature unit instance: {type(self._temperature_unit).__name__}")
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
            raise TypeError(f"{ERR_INVALID_STATE_TYPE}: pure_network_state got {type(pure).__name__}")
        return dict(pure)

    @property
    def device_state(self) -> dict[str, Any]:
        """Return the current device state via the poller's public interface."""
        state = self.poller.device_state
        if not isinstance(state, dict):
            raise TypeError(f"{ERR_INVALID_STATE_TYPE}: device_state got {type(state).__name__}")
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
        if not isinstance(raw_value, (int, float, str)):
            raise TypeError(f"Expected numeric or string for {label}, got {type(raw_value).__name__}")
        try:
            val = float(raw_value)
        except ValueError as err:
            raise ValueError(f"Invalid numeric string for {label}: '{raw_value}'") from err

        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Non-finite temperature value detected for {label}: {val}")
        return val

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
        hvac_modes_tuple = tuple(hvac_raw) if hvac_raw is not None else ()
        
        fan_raw = self.get_property_all_values(ATTR_FAN_MODE)
        fan_modes_tuple = tuple(fan_raw) if fan_raw is not None else ()
        
        swing_raw = self.get_property_all_values(ATTR_SWING_MODE)
        swing_modes_tuple = tuple(swing_raw) if swing_raw is not None else ()
        
        preset_raw = self.get_property_all_values(ATTR_PRESET_MODE)
        preset_modes_tuple = tuple(preset_raw) if preset_raw is not None else ()
        
        parsed_hvac_modes = tuple(
            mode
            for m in hvac_modes_tuple
            if (mode := self._safe_parse_hvac_mode(m)) is not None
        )
        
        return (
            parsed_hvac_modes,
            fan_modes_tuple,
            swing_modes_tuple,
            preset_modes_tuple,
        )

    @property
    def climate_state(self) -> ClimateIPDeviceState:
        """Return the strictly typed state representation of the device."""
        if self._cached_static_modes is None:
            self._cached_static_modes = self._build_static_modes_cache()

        hvac_modes_tuple, fan_modes_tuple, swing_modes_tuple, preset_modes_tuple = (
            self._cached_static_modes
        )

        def _get_val(prop_name: str) -> Any:
            try:
                return self.get_property(prop_name)
            except KeyError:
                return None

        raw_hvac = _get_val(ATTR_HVAC_MODE)
        hvac_mode = self._safe_parse_hvac_mode(raw_hvac)
        if hvac_mode is not None and hvac_mode not in hvac_modes_tuple:
            raise ValueError(f"{ERR_INVALID_DEVICE_MODE} [{ATTR_HVAC_MODE}]: {hvac_mode}")

        raw_target_temp = _get_val(ATTR_TEMPERATURE)
        target_temp = self._safe_parse_temperature(raw_target_temp, LABEL_TARGET_TEMP)

        raw_current_temp = _get_val(ATTR_CURRENT_TEMPERATURE)
        current_temp = self._safe_parse_temperature(raw_current_temp, LABEL_CURRENT_TEMP)

        raw_fan = _get_val(ATTR_FAN_MODE)
        fan_mode = None
        if raw_fan is not None:
            if not isinstance(raw_fan, str):
                raise TypeError(f"Fan mode must be a string, got {type(raw_fan).__name__}")
            if raw_fan not in fan_modes_tuple:
                raise ValueError(f"{ERR_INVALID_DEVICE_MODE} [{ATTR_FAN_MODE}]: {raw_fan}")
            fan_mode = raw_fan

        raw_swing = _get_val(ATTR_SWING_MODE)
        swing_mode = None
        if raw_swing is not None:
            if not isinstance(raw_swing, str):
                raise TypeError(f"Swing mode must be a string, got {type(raw_swing).__name__}")
            if raw_swing not in swing_modes_tuple:
                raise ValueError(f"{ERR_INVALID_DEVICE_MODE} [{ATTR_SWING_MODE}]: {raw_swing}")
            swing_mode = raw_swing

        raw_preset = _get_val(ATTR_PRESET_MODE)
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
        self, current_hass_state: ClimateIPDeviceState, property_name: str, new_value: Any
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
        
        is_push = self.connection.is_push_supported
        if not isinstance(is_push, bool):
            raise TypeError(f"Expected bool for is_push_supported, got {type(is_push).__name__}")
        return is_push

    async def async_refresh_from_connection(self) -> None:
        """Refresh the controller's properties from the connection's internal state.

        Obligatory implementation to fulfill ClimateController's strict ABC contract.
        Acts as a safe no-op for YAML-based devices.
        """
        _LOGGER.debug("%s Refresh from connection requested (no-op)", self.log_prefix)

    def register_token_callback(
        self,
        callback: (
            Callable[[str], Coroutine[Any, Any, None]] | Callable[[str], None] | None
        ),
    ) -> None:
        """Register an explicit token refreshed callback."""
        self._token_refreshed_callback = callback

    def on_token_refreshed(self, new_token: str) -> None:
        """Invoke the registered token refreshed callback if present."""
        if not isinstance(new_token, str) or len(new_token.strip()) == 0:
            raise TypeError("new_token must be a non-empty string")
        if self._token_refreshed_callback is not None:
            self._token_refreshed_callback(new_token)
        else:
            _LOGGER.debug("%s Token refreshed callback received (no handler registered)", self.log_prefix)