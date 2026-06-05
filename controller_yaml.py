# pylint: disable=import-outside-toplevel,protected-access,too-many-instance-attributes,too-many-public-methods,unused-import,wrong-import-position
"""YAML-based climate device controller for the climate_ip integration."""

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .state import ClimateIPDeviceState

import logging
import time

import aiohttp
import homeassistant.helpers.config_validation as cv
import requests.exceptions  # type: ignore[import-untyped]
import voluptuous as vol
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    ClimateEntityFeature,
)
from homeassistant.const import (
    ATTR_NAME,
    ATTR_TEMPERATURE,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_TEMP_UNIT,
    DEVICE_TYPE_SAMSUNG_2878,
)
from .controller import ClimateController, register_controller

# pylint: disable=unused-import
from .controller_yaml_config import YamlConfigLoader, clear_yaml_cache
from .controller_yaml_polling import YamlStatePoller
from .exceptions import CannotConnect
from .properties import DeviceProperty

_LOGGER = logging.getLogger(__name__)

CONST_CONTROLLER_TYPE = "yaml"
CONST_MAX_GET_STATUS_RETRIES = 4


@register_controller
class YamlController(ClimateController):
    """YAML-based controller mapped as a clean Facade pattern over composition."""
# pylint: disable=import-outside-toplevel,protected-access,too-many-instance-attributes,too-many-public-methods,unused-import,wrong-import-position

    def __init__(
        self,
        config: dict[str, Any],
        logger: logging.Logger,
        hass: HomeAssistant | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the YAML controller from a config dictionary.

        hass and session are passed explicitly to keep the config dict
        serializable (safe for ConfigEntry storage and diagnostics).
        """
        super().__init__(config, logger)
        # Store HA runtime objects as typed instance attributes.
        self.hass = hass
        self._session = session

        # Remove HA runtime objects from the config dict so it stays serializable.
        config.pop("hass", None)
        config.pop("session", None)

        self._config = config
        self._yaml = config.get(CONF_CONFIG_FILE)
        self._ip_address = config.get(CONF_IP_ADDRESS) or config.get("host")

        self._device_id = config.get(CONF_DEVICE_ID)
        self._token = config.get(CONF_TOKEN)
        self._unique_id = config.get("unique_id") or config.get(CONF_MAC) or self._ip_address

        if not self._device_id:
            if config.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_SAMSUNG_2878:
                self._device_id = self._unique_id
                _LOGGER.info(
                    "%s [Init] device_id was missing, fell back to unique_id: %s",  # pragma: no mutate
                    f"[{self._unique_id[-6:]}]" if self._unique_id else "[Unknown]",
                    self._device_id,
                )
            else:
                self._device_id = self._unique_id

        self.on_token_refreshed: Callable[[str], None] | None = None
        self.get_current_state_callback: Callable[[], Any] | None = None
        self.on_push_update_callback: Callable[[dict[str, Any] | None], Any] | None = None
        self.on_ssl_config_updated: Callable[[dict[str, Any]], None] | None = None
        self.request_refresh_callback: Callable[[], Any] | None = None
        self.on_connection_failed_callback: Callable[[], None] | None = None
        self.on_offline_callback: Callable[[str], None] | None = None
        self.discovered_devices: list[Any] | None = None
        self._debug = config.get("debug", False)
        self._attributes: dict[str, Any] = {"controller": self.id}
        self._shared_raw_client = None

        # Delegate implementations (Composition over Inheritance)
        self.loader = YamlConfigLoader(self)
        self.poller = YamlStatePoller(self)

    @staticmethod
    def match_type(controller_type: str) -> bool:
        """Return True if the given type string matches this controller."""
        return str(controller_type).lower() == CONST_CONTROLLER_TYPE

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
    def log_prefix(self) -> str:
        """Return a short log prefix based on the unique_id."""
        if self._unique_id and len(self._unique_id) >= 6:
            return f"[{self._unique_id[-6:]}]"
        return f"[{self.name or 'NO_ID'}]"

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID of this controller."""
        if self._unique_id and self._device_id and self._device_id != "0":
            # Ensure the device_id is included in the unique_id for sub-devices
            # to avoid collision in the HA device registry.
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
        if self.loader.connection:
            return self.loader.connection.get_diagnostics().get("is_available", True)
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
        new_value: Any,
        _device_id: str | None = None,
    ) -> bool:
        """Asynchronously set a property on the device."""
        if not self.loader.is_fully_initialized:
            _LOGGER.error(
                "%s Cannot set property '%s': controller not fully initialized",  # pragma: no mutate
                self.log_prefix,
                property_name,
            )
            return False

        op = self.loader.operations.get(property_name)
        if op:
            try:
                # Register the pending update in the poller dispatcher
                # pylint: disable=protected-access
                self.poller.register_pending_update(property_name, new_value)
                _LOGGER.debug(
                    "%s Registered pending update for '%s': %s",  # pragma: no mutate
                    self.log_prefix,
                    property_name,
                    new_value,
                )
                return await op.async_set_value(new_value, _device_id or self._device_id)
            except (requests.exceptions.RequestException, CannotConnect) as e:
                raise UpdateFailed(f"Failed to set property '{property_name}': {e}") from e
            except Exception as e:
                _LOGGER.error(
                    "%s Setting property '%s' with value '%s' failed",  # pragma: no mutate
                    self.log_prefix,
                    property_name,
                    new_value,
                    exc_info=True,
                )
                return False

        _LOGGER.error(
            "%s Failed to set property '%s': property not found",
            self.log_prefix,
            property_name,
        )
        return False

    def get_property(self, property_name: str) -> Any:
        """Return the current value of a property by name."""
        value = None
        if property_name in self.loader.operations:
            value = self.loader.operations[property_name].value
        elif property_name in self.loader.properties:
            value = self.loader.properties[property_name].value
        elif property_name in self.loader.sensors:
            value = self.loader.sensors[property_name].value
        else:
            value = self._attributes.get(property_name)

        if value == STATE_UNKNOWN:
            value = None

        return value

    def get_property_object(self, property_name: str) -> Any | None:
        """Return the property object (not just its value) by name."""
        if property_name in self.loader.operations:
            return self.loader.operations[property_name]
        if property_name in self.loader.properties:
            return self.loader.properties[property_name]
        if property_name in self.loader.sensors:
            return self.loader.sensors[property_name]

        _LOGGER.debug("%s Property object '%s' not found", self.log_prefix, property_name)  # pragma: no mutate
        return None

    def get_property_all_values(self, property_name: str) -> list[str] | None:
        """Return the complete, unfiltered list of values for a property."""
        prop = self.get_property_object(property_name)
        if prop and prop.all_values:
            return prop.all_values

        _LOGGER.debug(
            "%s Cannot get values for '%s': not an operation or missing all_values",  # pragma: no mutate
            self.log_prefix,
            property_name,
        )
        return None

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes dictionary."""
        return self._attributes

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit in use."""
        return UnitOfTemperature.CELSIUS

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
        # FIXED C0301: Line split to stay under 100 chars
        return [
            self.loader.sensors[n] for n in self.loader.sensors_list if n in self.loader.sensors
        ]

    @property
    def last_poll_data(self) -> Any:
        """Return the last raw poll response, useful for diagnostics."""
        return self.loader.state_getter.value if self.loader.state_getter else None

    @property
    def connection_diagnostics(self) -> dict[str, Any]:
        """Return connection diagnostic info from the underlying connection."""
        if self.loader.connection:
            return self.loader.connection.get_diagnostics()
        return {}

    @property
    def device_state(self) -> dict[str, Any]:
        """Return the current unwrapped device state."""
        # pylint: disable=protected-access
        if self.poller._last_device_state:
            return self.poller._last_device_state
        if self.loader.state_getter:
            return self.loader.state_getter.value
        return {}

    @property
    def climate_state(self) -> "ClimateIPDeviceState":
        """Return the strictly typed state representation of the device."""
        from .state import ClimateIPDeviceState  # imported here to avoid circular dep

        try:
            return ClimateIPDeviceState(
                hvac_mode=self.get_property(ATTR_HVAC_MODE),
                target_temperature=self.get_property(ATTR_TEMPERATURE),
                current_temperature=self.get_property(ATTR_CURRENT_TEMPERATURE),
                fan_mode=self.get_property(ATTR_FAN_MODE),
                swing_mode=self.get_property(ATTR_SWING_MODE),
                preset_mode=self.get_property(ATTR_PRESET_MODE),
                hvac_modes=self.state_attributes.get(ATTR_HVAC_MODES, []),
                fan_modes=self.state_attributes.get(ATTR_FAN_MODES, []),
                swing_modes=self.state_attributes.get(ATTR_SWING_MODES, []),
                preset_modes=self.state_attributes.get(ATTR_PRESET_MODES, []),
            )
        except (ValueError, TypeError) as err:
            _LOGGER.error("%s Error coercing typed ClimateIPDeviceState: %s", self.log_prefix, err)  # pragma: no mutate
            raise

    async def async_get_status(self) -> dict[str, Any] | None:
        """Fetch the device status using the poller."""
        return await self.poller.async_get_status()

    async def async_update_state(self) -> dict[str, Any] | None:
        """Update the entity state values."""
        return await self.poller.async_update_state()

    async def async_merge_device_state(
        self, new_data: dict[str, Any], is_response: bool, is_update: bool
    ) -> bool:
        """Merge incoming push updates or responses into the memory state.
        Returns True if committed.
        """
        return await self.poller.async_merge_device_state(new_data, is_response, is_update)

    async def async_predict_and_correct_state(
        self, current_hass_state: Any, property_name: str, new_value: Any
    ) -> tuple[ClimateEntityFeature, dict[str, Any]]:
        """Predict expected state changes based on a command."""
        # FIXED C0301: Multi-argument method call split for readability and length
        return await self.poller.async_predict_and_correct_state(
            current_hass_state, property_name, new_value
        )

    async def async_shutdown(self) -> None:
        """Shut down the controller and clean up connections."""
        await self.poller.async_shutdown()


# Extend the core platform schema
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_CONFIG_FILE): cv.string,
        vol.Optional(CONF_IP_ADDRESS): cv.string,
        vol.Optional(CONF_TOKEN): cv.string,
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_TEMP_NATIVE_CURRENT, default=DEFAULT_CONF_TEMP_UNIT): cv.string,
        vol.Optional(CONF_TEMP_NATIVE_TARGET, default=DEFAULT_CONF_TEMP_UNIT): cv.string,
    }
)
