# pylint: disable=import-outside-toplevel,protected-access,too-many-instance-attributes,too-many-public-methods,unused-import,wrong-import-position
"""YAML-based climate device controller for the climate_ip integration."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .connection import ClimateConnection  # Interfaz concreta de conexión

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_TEMP_UNIT,
    DEVICE_TYPE_TO_CONFIG_FILE,
    MAIN_DEVICE_ID,
)
from .controller import ClimateController, register_controller
from .controller_yaml_config import YamlConfigLoader
from .controller_yaml_polling import YamlStatePoller
from .exceptions import CannotConnect
from .properties import DeviceProperty
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = "yaml"


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
        if config is None and config_entry is not None:
            config = {**config_entry.data, **config_entry.options}
            config["entry_id"] = config_entry.entry_id

            base_unique_id = config_entry.unique_id
            if device_id and device_id != MAIN_DEVICE_ID:
                config["unique_id"] = (
                    f"{base_unique_id}_{device_id}"
                    if base_unique_id
                    else f"Unknown_{device_id}"
                )
            else:
                config["unique_id"] = base_unique_id

            if device_id:
                config[CONF_DEVICE_ID] = device_id
            device_type = config.get(CONF_DEVICE_TYPE)
            if device_type:
                config[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)
        elif config is None:
            config = {}

        if logger is None:
            logger = _LOGGER

        super().__init__(config, logger)  # pragma: no mutate
        self._config = dict(config)

        self.hass = hass
        self._session = session

        self._config.pop("hass", None)  # pragma: no mutate
        self._config.pop("session", None)  # pragma: no mutate
        self._config.pop("logger", None)  # pragma: no mutate
        self._yaml = config.get(CONF_CONFIG_FILE)
        self._ip_address = config.get(CONF_IP_ADDRESS) or config.get("host")

        self._device_id = config.get(CONF_DEVICE_ID)
        self._token = config.get(CONF_TOKEN)

        _raw_uid = config.get("unique_id") or config.get(CONF_MAC) or self._ip_address

        if not self._device_id:
            self._device_id = _raw_uid

        self._unique_id = _raw_uid

        # Callbacks tipados con precisión
        self.on_token_refreshed: Callable[[str], None] | None = None
        self.get_current_state_callback: Callable[[], dict[str, Any] | None] | None = None
        self.on_push_update_callback: Callable[[dict[str, Any] | None], None] | None = None
        self.on_ssl_config_updated: Callable[[dict[str, Any]], None] | None = None
        self.request_refresh_callback: Callable[[], None] | None = None
        self.on_connection_failed_callback: Callable[[], None] | None = None
        self.on_offline_callback: Callable[[str], None] | None = None
        self.discovered_devices: list[dict[str, Any]] | None = None
        self._debug = bool(config.get("debug", False))

        self._temperature_unit: str = (
            self._config.get(CONF_TEMP_NATIVE_TARGET)
            or self._config.get(CONF_TEMP_NATIVE_CURRENT)
            or UnitOfTemperature.CELSIUS
        )
        self._attributes: dict[str, Any] = {"controller": self.id}

        self._shared_raw_client = None

        # Caché tipada explícitamente con DeviceProperty en lugar de Any
        self._obj_id_cache: dict[str, DeviceProperty] | None = None

        self.loader = YamlConfigLoader(self)
        self.poller = YamlStatePoller(self)

    @staticmethod
    def match_type(controller_type: str) -> bool:
        """Return True if the given type string matches this controller."""
        return str(controller_type).lower() == CONST_CONTROLLER_TYPE

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
        return self.loader.name

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID of this controller."""
        if self._unique_id and self._device_id and self._device_id != "0":
            if f"_{self._device_id}" not in str(self._unique_id):
                return f"{self._unique_id}_{self._device_id}"
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
        return self._config

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
        if self.connection:
            return self.connection.get_diagnostics().get("is_available", True)
        return True

    @property
    def id(self) -> str | None:
        """Return the unique id of the controller."""
        return self._unique_id

    async def update_state(self) -> bool:
        """Asynchronously update the state of the controller from the device."""
        result = await self.async_update_state()
        return result is not None

    async def initialize(self) -> bool:
        """Perform initial YAML configuration loading and set up the base connection."""
        return await self.loader.async_initialize()

    async def async_set_property(
        self,
        property_name: str,
        new_value: str | int | float | bool,
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
        if op and hasattr(op, "async_set_value"):
            try:
                self.poller.register_pending_update(property_name, new_value)
                _LOGGER.debug(  # pragma: no mutate
                    "%s Registered pending update for '%s': %s",
                    self.log_prefix,
                    property_name,
                    new_value,
                )  # pragma: no mutate
                target_device_id = device_id or self.device_id
                if not target_device_id or target_device_id == MAIN_DEVICE_ID:
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
            except Exception as e:
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

    def get_property(self, property_name: str) -> str | int | float | bool | None:
        """Return the current value of a property by name using safe extraction."""
        obj = self.get_property_object(property_name)
        value = obj.value if obj else self._attributes.get(property_name)

        if value == STATE_UNKNOWN:
            return None
        return value

    @property
    def _objects_by_id(self) -> dict[str, DeviceProperty]:
        """O(1) lazy-loaded cache for property/operation/sensor lookup by internal ID."""
        if self._obj_id_cache is None:
            self._obj_id_cache = {
                getattr(op, "id"): op
                for collection in (
                    self.loader.operations,
                    self.loader.properties,
                    self.loader.sensors,
                )
                for op in collection.values()
                if getattr(op, "id", None) is not None
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
        if mapped_op_id and mapped_op_id != property_name:
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
        if prop and prop.all_values:
            return prop.all_values

        _LOGGER.debug(  # pragma: no mutate
            "%s Cannot get values for '%s': not an operation or missing all_values",
            self.log_prefix,
            property_name,
        )  # pragma: no mutate
        return None

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes dictionary."""
        return self._attributes

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit in use (resolved at construction time)."""
        return self._temperature_unit

    @property
    def service_schema_map(self) -> dict[str, Any] | None:
        """Return the voluptuous service schema map."""
        return self.loader.service_schema_map

    @property
    def operations(self) -> list[str]:
        """Return the list of settable operation names."""
        return self.loader.operations_list

    @property
    def attributes(self) -> list[str]:
        """Return the list of read-only attribute names."""
        return self.loader.properties_list

    @property
    def sensors(self) -> list[DeviceProperty]:
        """Return a list of all defined sensor property objects."""
        return [
            self.loader.sensors[n]
            for n in self.loader.sensors_list
            if n in self.loader.sensors
        ]

    @property
    def last_poll_data(self) -> dict[str, Any] | None:
        """Return the last raw poll response, useful for diagnostics."""
        return self.loader.state_getter.value if self.loader.state_getter else None

    @property
    def connection_diagnostics(self) -> dict[str, Any]:
        """Return connection diagnostic info from the underlying connection."""
        if self.connection:
            return self.connection.get_diagnostics()
        return {}

    @property
    def pure_device_state(self) -> dict[str, Any]:
        """Return the unmutated pure network state of the device."""
        pure = self.poller.pure_network_state
        if pure:
            return pure
        return self.device_state

    @property
    def device_state(self) -> dict[str, Any]:
        """Return the current device state via the poller's public interface."""
        state = self.poller.device_state
        if state:
            return state
        if self.loader.state_getter:
            return self.loader.state_getter.value or {}
        return {}

    @property
    def climate_state(self) -> ClimateIPDeviceState:
        """Return the strictly typed state representation of the device."""
        try:
            raw_hvac = self.get_property(ATTR_HVAC_MODE)
            hvac_mode = (
                HVACMode(str(raw_hvac).lower()) if raw_hvac is not None else None
            )

            raw_target = self.get_property(ATTR_TEMPERATURE)
            target_temp = float(raw_target) if raw_target is not None else None

            raw_current = self.get_property(ATTR_CURRENT_TEMPERATURE)
            current_temp = float(raw_current) if raw_current is not None else None

            raw_fan = self.get_property(ATTR_FAN_MODE)
            fan_mode = str(raw_fan) if raw_fan is not None else None

            raw_swing = self.get_property(ATTR_SWING_MODE)
            swing_mode = str(raw_swing) if raw_swing is not None else None

            raw_preset = self.get_property(ATTR_PRESET_MODE)
            preset_mode = str(raw_preset) if raw_preset is not None else None

            raw_hvac_modes = self.get_property_all_values(ATTR_HVAC_MODE) or []
            hvac_modes_tuple = tuple(
                HVACMode(str(m).lower()) for m in raw_hvac_modes if m is not None
            )

            fan_modes_tuple = tuple(
                str(m) for m in (self.get_property_all_values(ATTR_FAN_MODE) or [])
            )
            swing_modes_tuple = tuple(
                str(m) for m in (self.get_property_all_values(ATTR_SWING_MODE) or [])
            )
            preset_modes_tuple = tuple(
                str(m) for m in (self.get_property_all_values(ATTR_PRESET_MODE) or [])
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
        """Clear cached state in poller to prevent ghosting."""
        if self.poller is not None:
            self.poller.clear_state_cache()

    async def async_merge_device_state(self, new_data: dict[str, Any]) -> bool:
        """Merge incoming push updates or responses into the memory state."""
        return await self.poller.async_merge_device_state(new_data)

    async def async_clear_pending_updates(self, keys: list[str]) -> None:
        """Clear specific pending updates (anti-flicker locks) on failure."""
        self.poller.clear_pending_updates(keys)

    async def async_predict_and_correct_state(
        self, current_hass_state: str | None, property_name: str, new_value: str | int | float | bool
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
    def shared_raw_client(self) -> Any:
        """Return the shared raw socket client."""
        return self._shared_raw_client

    @shared_raw_client.setter
    def shared_raw_client(self, client: Any) -> None:
        """Set the shared raw socket client."""
        self._shared_raw_client = client

    async def async_refresh_from_connection(self) -> None:
        """Refresh the controller's properties from the connection's internal state."""
        pass