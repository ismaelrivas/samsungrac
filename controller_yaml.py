from __future__ import annotations

import asyncio
import logging
import math
import types
from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
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
    CONF_CONFIG_FILE,
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
    DOMAIN,
    ERR_CACHE_UNINITIALIZED,
    ERR_CONTROLLER_NOT_INITIALIZED,
    ERR_INVALID_DEVICE_MODE,
    ERR_INVALID_STATE_TYPE,
    ERR_MISSING_INIT_CONFIG,
    ERR_MISSING_IP,
    ERR_PROPERTY_NOT_FOUND,
    ERR_UNREGISTERED_PROPERTY,
    EXCLUDED_SUBDEVICE_IDS,
    ID_DELIMITER,
    IMMUTABLE_CONFIG_KEYS,
    LABEL_CURRENT_TEMP,
    LABEL_TARGET_TEMP,
)
from .controller import ClimateController, register_controller
from .controller_yaml_config import YamlConfigLoader
from .controller_yaml_polling import YamlStatePoller
from .exceptions import AuthError, CannotConnect
from .properties import DeviceProperty, parse_temperature_unit
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)


@register_controller
class YamlController(ClimateController):
    """YAML-based controller mapped as a clean Facade pattern over composition."""

    @classmethod
    def _resolve_unique_id(
        cls,
        raw_unique_id: Any,
        raw_mac: Any,
        device_id: str | None,
    ) -> str | None:
        """Resolve canonical unique ID incorporating sub-device segmentation."""
        base_id: str | None = None
        if raw_unique_id is not None:
            if not isinstance(raw_unique_id, str):
                raise TypeError(
                    f"Expected str for {CONF_UNIQUE_ID}, got {type(raw_unique_id).__name__}"
                )
            base_id = raw_unique_id.strip() if len(raw_unique_id.strip()) > 0 else None

        if base_id is None and raw_mac is not None:
            if not isinstance(raw_mac, str):
                raise TypeError(
                    f"Expected str for {CONF_MAC}, got {type(raw_mac).__name__}"
                )
            base_id = raw_mac.strip() if len(raw_mac.strip()) > 0 else None

        if device_id is not None and cls._is_subdevice(device_id):
            sub_id = device_id.strip()
            if base_id is not None:
                if not base_id.endswith(f"{ID_DELIMITER}{sub_id}"):
                    return f"{base_id}{ID_DELIMITER}{sub_id}"
                return base_id
            return sub_id

        return base_id

    @classmethod
    def _extract_config_from_entry(
        cls, config_entry: ConfigEntry[Any], device_id: str | None
    ) -> dict[str, Any]:
        """Extract config enforcing flow segregation and immutable hardware credentials."""
        resolved_unique_id = cls._resolve_unique_id(
            config_entry.unique_id, config_entry.data.get(CONF_MAC), device_id
        )

        # Base immutable data from entry creation selectively merged with runtime options
        extracted: dict[str, Any] = dict(config_entry.data)
        for key, value in config_entry.options.items():
            if key not in IMMUTABLE_CONFIG_KEYS:
                extracted[key] = value

        extracted[CONF_ENTRY_ID] = config_entry.entry_id
        extracted[CONF_UNIQUE_ID] = resolved_unique_id
        if isinstance(device_id, str) and len(device_id.strip()) > 0:
            extracted[CONF_DEVICE_ID] = device_id.strip()

        return extracted

    @classmethod
    def from_config_entry(
        cls,
        config_entry: ConfigEntry[Any],
        hass: HomeAssistant | None = None,
        device_id: str | None = None,
        logger: logging.Logger | None = None,
    ) -> YamlController:
        """Create a YamlController instance directly from a ConfigEntry."""
        logger = logger if logger is not None else _LOGGER
        return cls(
            logger=logger, hass=hass, config_entry=config_entry, device_id=device_id
        )

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
        hass: HomeAssistant | None = None,
        config_entry: ConfigEntry[Any] | None = None,
        device_id: str | None = None,
        session: Any | None = None,
        **kwargs: Any,
    ) -> None:
        if config is None and config_entry is not None:
            config = self._extract_config_from_entry(config_entry, device_id)
        elif isinstance(config, (dict, types.MappingProxyType)):
            config = dict(config)
            if device_id is not None and CONF_DEVICE_ID not in config:
                config[CONF_DEVICE_ID] = (
                    device_id.strip() if isinstance(device_id, str) else device_id
                )
        elif config is not None:
            raise TypeError(f"Expected dict for config, got {type(config).__name__}")
        else:
            raise ValueError(ERR_MISSING_INIT_CONFIG)

        # Fallback resolution for CONF_CONFIG_FILE based on CONF_DEVICE_TYPE
        raw_config_file = config.get(CONF_CONFIG_FILE)
        if raw_config_file is not None and not isinstance(raw_config_file, str):
            raise TypeError(
                f"Expected str for {CONF_CONFIG_FILE}, got {type(raw_config_file).__name__}"
            )
        if raw_config_file is None or len(raw_config_file.strip()) == 0:
            device_type = config.get(CONF_DEVICE_TYPE)
            if device_type is not None:
                if not isinstance(device_type, str):
                    raise TypeError(
                        f"Expected str for {CONF_DEVICE_TYPE}, got {type(device_type).__name__}"
                    )
                if device_type in DEVICE_TYPE_TO_CONFIG_FILE:
                    config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE[device_type]

        raw_name = config.get(CONF_NAME)
        if raw_name is not None:
            if not isinstance(raw_name, str):
                raise TypeError(
                    f"Expected str for {CONF_NAME}, got {type(raw_name).__name__}"
                )
            if len(raw_name.strip()) > 0:
                config[CONF_NAME] = raw_name.strip()
            else:
                config.pop(CONF_NAME, None)

        logger = logger if logger is not None else _LOGGER
        super().__init__(config, logger)

        self.hass = hass
        self._session = session
        self.loader: YamlConfigLoader = YamlConfigLoader(self)
        self.poller: YamlStatePoller = YamlStatePoller(self)

        self._device_id: str | None = None
        self._token: str | None = None

        raw_device_id = config.get(CONF_DEVICE_ID)
        if raw_device_id is not None:
            if not isinstance(raw_device_id, str):
                raise TypeError(
                    f"Expected str for {CONF_DEVICE_ID}, got {type(raw_device_id).__name__}"
                )
            if len(raw_device_id.strip()) > 0:
                self._device_id = raw_device_id.strip()
            else:
                self._device_id = None
        else:
            self._device_id = None

        raw_token = config.get(CONF_TOKEN)
        if raw_token is not None:
            if not isinstance(raw_token, str):
                raise TypeError(
                    f"Expected str for {CONF_TOKEN}, got {type(raw_token).__name__}"
                )
            if len(raw_token.strip()) > 0:
                self._token = raw_token.strip()
            else:
                self._token = None
        else:
            self._token = None

        self._unique_id = self._resolve_unique_id(
            config.get(CONF_UNIQUE_ID), config.get(CONF_MAC), self._device_id
        )

        if self._device_id is None:
            self._device_id = self._unique_id

        raw_ip = config.get(CONF_IP_ADDRESS)
        raw_host = config.get(CONF_HOST)

        if raw_ip is not None and not isinstance(raw_ip, str):
            raise TypeError(f"{CONF_IP_ADDRESS} must be a string")
        if raw_host is not None and not isinstance(raw_host, str):
            raise TypeError(f"{CONF_HOST} must be a string")

        resolved_ip = (
            raw_ip if (raw_ip is not None and len(raw_ip.strip()) > 0) else raw_host
        )
        if resolved_ip is None or len(resolved_ip.strip()) == 0:
            raise ValueError(ERR_MISSING_IP)
        self._ip_address = resolved_ip.strip()

        # Strict Boolean Parsing (Guarded against string casting trap like 'false' -> True)
        raw_debug = config.get(CONF_DEBUG, False)
        if not isinstance(raw_debug, bool):
            raise TypeError(
                f"Expected strict bool for {CONF_DEBUG}, got {type(raw_debug).__name__}"
            )
        self._debug = raw_debug

        target_temp_unit = config.get(CONF_TEMP_NATIVE_TARGET)
        current_temp_unit = config.get(CONF_TEMP_NATIVE_CURRENT)

        raw_unit = (
            target_temp_unit if target_temp_unit is not None else current_temp_unit
        )
        if raw_unit is not None:
            self._temperature_unit = parse_temperature_unit(raw_unit)
        else:
            self._temperature_unit = DEFAULT_CONF_TEMP_UNIT
        self._attributes: dict[str, Any] = {}
        self._config = types.MappingProxyType(config)

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
        return controller_type.strip().lower() == DEFAULT_CONF_CONTROLLER

    @property
    def yaml_file(self) -> str | None:
        """Return the YAML configuration file path from config."""
        return self._config.get(CONF_CONFIG_FILE)

    @property
    def connection(self) -> Connection | None:
        """Override base connection to point strictly to the loader's active connection."""
        return self.loader.connection

    @property
    def port(self) -> int | str | None:
        """Return the port of the controller if configured."""
        if hasattr(self, "_config") and self._config is not None:
            return self._config.get("port")
        return None

    @property
    def name(self) -> str:
        """Return the controller name prioritizing user configuration over YAML loader default."""
        config_name = self._config.get(CONF_NAME)
        if config_name is not None:
            return config_name

        loader_name = self.loader.name
        if loader_name is not None:
            if not isinstance(loader_name, str):
                raise TypeError(
                    f"Expected str for loader name, got {type(loader_name).__name__}"
                )
            if len(loader_name.strip()) == 0:
                raise ValueError("Loader name cannot be empty")
            return loader_name

        return DEFAULT_CONTROLLER_NAME

    @staticmethod
    def _is_subdevice(device_id: str | None) -> bool:
        """Return True if device_id represents a sub-device."""
        if not isinstance(device_id, str) or len(device_id.strip()) == 0:
            return False
        return device_id.strip() not in EXCLUDED_SUBDEVICE_IDS

    @property
    def unique_id(self) -> str | None:
        """Return the pre-computed unique ID of this controller."""
        return self._unique_id

    @property
    def device_id(self) -> str | None:
        """Return the device ID of this controller."""
        return self._device_id

    @property
    def config(self) -> dict[str, Any]:
        """Return the controller configuration dictionary."""
        return dict(self._config)

    @property
    def token(self) -> str | None:
        """Return the authentication token."""
        return self._token

    @property
    def ip_address(self) -> str | None:
        """Return the IP address."""
        return self._ip_address

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
        return bool(self.connection.is_available)

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
            raise TypeError(
                f"Expected non-empty str for property_name, got {property_name!r}"
            )

        if not self.loader.is_fully_initialized:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=ERR_CONTROLLER_NOT_INITIALIZED,
                translation_placeholders={"property": property_name},
            )

        op = self.get_property_object(property_name)
        if not isinstance(op, DeviceProperty):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERR_PROPERTY_NOT_FOUND,
                translation_placeholders={"property": property_name},
            )

        if device_id is not None and not isinstance(device_id, str):
            raise TypeError(
                f"device_id must be a string, got {type(device_id).__name__}"
            )

        target_device_id = (
            device_id
            if (device_id is not None and len(device_id.strip()) > 0)
            else self.device_id
        )
        if target_device_id is None or not self._is_subdevice(target_device_id):
            target_device_id = self._unique_id

        self.poller.register_pending_update(property_name, new_value)
        _LOGGER.debug(
            "%s Registered pending update for '%s': %s",
            self.log_prefix,
            property_name,
            new_value,
        )

        success = False
        try:
            result = await op.async_set_value(new_value, target_device_id)
            success = bool(result)
            if success and hasattr(self, "poller") and self.poller is not None:
                if (
                    getattr(self.poller, "_pure_network_state", None) is None
                    and hasattr(self.loader, "state_getter")
                    and self.loader.state_getter is not None
                    and isinstance(self.loader.state_getter.value, dict)
                ):
                    import copy

                    self.poller._pure_network_state = copy.deepcopy(
                        self.loader.state_getter.value
                    )
                if (
                    getattr(self.poller, "_pure_network_state", None) is not None
                    and isinstance(self.poller._pure_network_state, dict)
                ):
                    self.poller._inject_value_into_state(
                        op, self.poller._pure_network_state, new_value
                    )
                if (
                    hasattr(self.loader, "state_getter")
                    and self.loader.state_getter is not None
                    and isinstance(self.loader.state_getter.value, dict)
                ):
                    self.poller._inject_value_into_state(
                        op, self.loader.state_getter.value, new_value
                    )
            return result
        except asyncio.CancelledError:
            await self.async_clear_pending_updates([property_name])
            raise
        except (CannotConnect, AuthError) as err:
            await self.async_clear_pending_updates([property_name])
            raise HomeAssistantError(f"Communication failed: {err}") from err
        except HomeAssistantError:
            await self.async_clear_pending_updates([property_name])
            raise
        finally:
            if not success:
                await self.async_clear_pending_updates([property_name])

    def has_property(self, property_name: str) -> bool:
        """Return True if the property is structurally mapped."""
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(
                f"Expected non-empty str for property_name, got {property_name!r}"
            )
        return (
            self.get_property_object(property_name) is not None
            or property_name in self._attributes
        )

    def get_property(self, property_name: str) -> Any:
        """Return the current value of a property by name using safe extraction."""
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(
                f"Expected non-empty str for property_name, got {property_name!r}"
            )
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
                    op_id = getattr(op, "id", None)
                    if isinstance(op_id, str) and len(op_id.strip()) > 0:
                        cache[op_id] = op
                        hass_attr = self.poller.get_hass_attr_for_op_id(op_id)
                        if (
                            isinstance(hass_attr, str)
                            and len(hass_attr.strip()) > 0
                            and hass_attr not in cache
                        ):
                            cache[hass_attr] = op
            self._obj_id_cache = cache
        return self._obj_id_cache

    def get_property_object(self, property_name: str) -> DeviceProperty | None:
        """Return the property object by name, internal ID, or mapped HASS attribute."""
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(
                f"Expected non-empty str for property_name, got {property_name!r}"
            )

        if not self.loader.is_fully_initialized:
            return None

        if property_name in self.loader.operations:
            return self.loader.operations[property_name]
        if property_name in self.loader.properties:
            return self.loader.properties[property_name]
        if property_name in self.loader.sensors:
            return self.loader.sensors[property_name]

        return self._objects_by_id.get(property_name)

    def get_property_all_values(self, property_name: str) -> tuple[str, ...] | None:
        """Return the complete, unfiltered tuple of values for a property."""
        if not isinstance(property_name, str) or len(property_name.strip()) == 0:
            raise TypeError(
                f"Expected non-empty str for property_name, got {property_name!r}"
            )
        prop = self.get_property_object(property_name)
        if prop is not None:
            all_vals = prop.all_values
            if all_vals is not None:
                if not isinstance(all_vals, (list, tuple, set)):
                    raise TypeError(
                        f"Expected iterable for {property_name} all_vals, got {type(all_vals).__name__}"
                    )
                for v in all_vals:
                    if not isinstance(v, str):
                        raise TypeError(
                            f"Mode value must be a string, got {type(v).__name__}: {v}"
                        )
                return tuple(all_vals)

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

    def update_state_attributes(self, new_attrs: dict[str, Any]) -> None:
        """Update the internal state attributes dictionary."""
        if not isinstance(new_attrs, dict):
            raise TypeError(
                f"Expected dict for new_attrs, got {type(new_attrs).__name__}"
            )
        self._attributes = dict(new_attrs)

    @property
    def temperature_unit(self) -> UnitOfTemperature:
        """Return the temperature unit in use (resolved at construction time)."""
        return self._temperature_unit

    @property
    def service_schema_map(self) -> dict[Any, Any] | None:
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
        """Return standardized connection diagnostic dictionary from the underlying connection."""
        if self.connection is not None and hasattr(self.connection, "get_diagnostics"):
            diag = self.connection.get_diagnostics()
            if isinstance(diag, dict):
                return dict(diag)
        return {}

    @property
    def pure_device_state(self) -> dict[str, Any]:
        """Return the unmutated pure network state of the device."""
        pure = self.poller.pure_network_state
        if not isinstance(pure, dict):
            raise TypeError(
                f"{ERR_INVALID_STATE_TYPE}: pure_network_state got {type(pure).__name__}"
            )
        return dict(pure)

    @property
    def device_state(self) -> dict[str, Any]:
        """Return the current device state via the poller's public interface."""
        state = self.poller.device_state
        if not isinstance(state, dict):
            raise TypeError(
                f"{ERR_INVALID_STATE_TYPE}: device_state got {type(state).__name__}"
            )
        return dict(state)

    def _safe_parse_hvac_mode(self, raw_mode: Any) -> HVACMode | None:
        """Parse HVAC mode strictly. Raises ValueError/TypeError on invalid input."""
        if raw_mode is None:
            return None
        if isinstance(raw_mode, HVACMode):
            return raw_mode
        if not isinstance(raw_mode, str):
            raise TypeError(
                f"HVAC mode must be a string or HVACMode, got {type(raw_mode).__name__}"
            )
        trimmed = raw_mode.strip()
        if len(trimmed) == 0:
            return None
        return HVACMode(trimmed.lower())

    def _safe_parse_temperature(self, raw_value: Any, label: str) -> float | None:
        """Parse temperature strictly. Raises ValueError/TypeError on invalid input."""
        if raw_value is None:
            return None
        if isinstance(raw_value, bool):
            raise TypeError(
                f"Temperature for {label} cannot be a boolean, got {raw_value}"
            )
        if not isinstance(raw_value, (int, float, str)):
            raise TypeError(
                f"Expected numeric or string for {label}, got {type(raw_value).__name__}"
            )
        if isinstance(raw_value, str):
            trimmed = raw_value.strip()
            if len(trimmed) == 0:
                return None
            raw_value = trimmed
        try:
            val = float(raw_value)
        except ValueError as err:
            raise ValueError(
                f"Invalid numeric string for {label}: '{raw_value}'"
            ) from err

        if math.isnan(val) or math.isinf(val):
            raise ValueError(
                f"Non-finite temperature value detected for {label}: {val}"
            )
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
        hvac_modes_tuple = hvac_raw if hvac_raw is not None else ()

        fan_raw = self.get_property_all_values(ATTR_FAN_MODE)
        fan_modes_tuple = fan_raw if fan_raw is not None else ()

        swing_raw = self.get_property_all_values(ATTR_SWING_MODE)
        swing_modes_tuple = swing_raw if swing_raw is not None else ()

        preset_raw = self.get_property_all_values(ATTR_PRESET_MODE)
        preset_modes_tuple = preset_raw if preset_raw is not None else ()

        parsed_hvac_modes = tuple(
            dict.fromkeys(
                mode
                for m in hvac_modes_tuple
                if (mode := self._safe_parse_hvac_mode(m)) is not None
            )
        )

        return (
            parsed_hvac_modes,
            fan_modes_tuple,
            swing_modes_tuple,
            preset_modes_tuple,
        )

    def _validate_mode_value(
        self, raw_val: Any, allowed_tuple: tuple[str, ...], attr_name: str
    ) -> str | None:
        """Validate string mode against allowed tuple strictly."""
        if raw_val is None:
            return None
        if not isinstance(raw_val, str):
            raise TypeError(
                f"{attr_name} must be a string, got {type(raw_val).__name__}"
            )
        trimmed = raw_val.strip()
        if len(trimmed) == 0:
            return None
        if len(allowed_tuple) > 0 and trimmed not in allowed_tuple:
            raise ValueError(f"{ERR_INVALID_DEVICE_MODE} [{attr_name}]: {trimmed}")
        return trimmed

    @property
    def climate_state(self) -> ClimateIPDeviceState:
        """Return the strictly typed state representation of the device."""
        if self._cached_static_modes is None:
            if not self.loader.is_fully_initialized:
                return ClimateIPDeviceState()
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

        # Unrolled strict boolean evaluation (mutmut resistant)
        if (
            hvac_mode is not None
            and hvac_mode != HVACMode.OFF
            and len(hvac_modes_tuple) > 0
        ):
            if hvac_mode not in hvac_modes_tuple:
                raise ValueError(
                    f"{ERR_INVALID_DEVICE_MODE} [{ATTR_HVAC_MODE}]: {hvac_mode}"
                )

        target_temp = self._safe_parse_temperature(
            _get_val(ATTR_TEMPERATURE), LABEL_TARGET_TEMP
        )
        current_temp = self._safe_parse_temperature(
            _get_val(ATTR_CURRENT_TEMPERATURE), LABEL_CURRENT_TEMP
        )
        fan_mode = self._validate_mode_value(
            _get_val(ATTR_FAN_MODE), fan_modes_tuple, ATTR_FAN_MODE
        )
        swing_mode = self._validate_mode_value(
            _get_val(ATTR_SWING_MODE), swing_modes_tuple, ATTR_SWING_MODE
        )
        preset_mode = self._validate_mode_value(
            _get_val(ATTR_PRESET_MODE), preset_modes_tuple, ATTR_PRESET_MODE
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

    async def async_get_status(self) -> dict[str, Any] | None:
        """Fetch the device status using the poller."""
        return await self.poller.async_get_status()

    async def async_update_state(self) -> dict[str, Any] | None:
        """Update the entity state values."""
        return await self.poller.async_update_state()

    def is_property_superseded(self, prop: str, val: Any) -> bool:
        """Return True if an outgoing command has been superseded by a newer target.

        Direct poller access — no getattr/hasattr. Fulfills ClimateController ABC contract.
        """
        pending = self.poller._pending_updates
        if prop in pending:
            current_target = pending[prop][0]
            if current_target != val:
                return True
        return False

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
        self,
        current_hass_state: ClimateIPDeviceState,
        property_name: str,
        new_value: Any,
    ) -> tuple[Any, dict[str, Any]]:
        """Predict expected state changes based on a command."""
        return await self.poller.async_predict_and_correct_state(
            current_hass_state, property_name, new_value
        )

    async def async_shutdown(self) -> None:
        """Shut down the controller and clean up connections and memory caches."""
        self.clear_state_cache()
        await self.poller.async_shutdown()

    @property
    def is_push_device(self) -> bool:
        """Return True if the device uses push-based updates."""
        if self.connection is None:
            return False
        return bool(self.connection.is_push_supported)

    async def async_refresh_from_connection(self) -> None:
        """Refresh the controller's properties from the connection's internal state.

        Obligatory implementation to fulfill ClimateController's strict ABC contract.
        Acts as a safe no-op for YAML-based devices.
        """
        _LOGGER.debug("%s Refresh from connection requested (no-op)", self.log_prefix)
