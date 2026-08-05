"""Support for Samsung AC devices using climate_ip."""
# pylint: disable=import-outside-toplevel,too-many-instance-attributes,too-many-public-methods
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components import climate as ha_climate
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    PLATFORM_SCHEMA,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
)
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant import const
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.update_coordinator import CoordinatorEntity
if TYPE_CHECKING:
    from . import ClimateIPConfigEntry
from .const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_CONTROLLER,
    CONF_DEVICE_ID,
    CONF_DEVICES,
    CONF_TARGET_TEMP_STEP,
    CONF_TEMP_STEP,
    CONFIG_DEVICE_NAME,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_UPDATE_DELAY,
    DEFAULT_CLIMATE_IP_TEMP_MAX,
    DEFAULT_CLIMATE_IP_TEMP_MIN,
    DEFAULT_CONF_CERT_FILE,
    DEFAULT_CONF_CONFIG_FILE,
    DEFAULT_CONF_CONTROLLER,
    DEFAULT_TARGET_TEMP_STEP,
    DEFAULT_UPDATE_DELAY,
    DOMAIN,
)
from .controller import ATTR_POWER
from .coordinator import SamsungClimateCoordinator
_LOGGER = logging.getLogger(__name__)
SUPPORTED_FEATURES_MAP: Final[dict[str, ClimateEntityFeature]] = {
    const.ATTR_TEMPERATURE: ClimateEntityFeature.TARGET_TEMPERATURE,
    ATTR_FAN_MODE: ClimateEntityFeature.FAN_MODE,
    ATTR_SWING_MODE: ClimateEntityFeature.SWING_MODE,
    ATTR_PRESET_MODE: ClimateEntityFeature.PRESET_MODE,
}

CLIMATE_ENTITY_DESCRIPTION: Final[ClimateEntityDescription] = ClimateEntityDescription(
    key="samsung_ac",
    translation_key="samsung_ac",
)
# Legacy platform schema for YAML import.
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(const.CONF_IP_ADDRESS): cv.string,
        vol.Optional(const.CONF_TOKEN): cv.string,
        vol.Optional(const.CONF_MAC): cv.string,
        vol.Optional(CONFIG_DEVICE_NAME): cv.string,
        vol.Optional(CONF_CERT, default=DEFAULT_CONF_CERT_FILE): cv.string,
        vol.Optional(CONF_CONFIG_FILE, default=DEFAULT_CONF_CONFIG_FILE): cv.string,
        vol.Optional(CONF_CONTROLLER, default=DEFAULT_CONF_CONTROLLER): cv.string,
        vol.Optional(const.CONF_DEBUG, default=False): cv.boolean,
        vol.Optional(CONFIG_DEVICE_POLL, default=""): cv.string,
        vol.Optional(
            CONFIG_DEVICE_UPDATE_DELAY, default=DEFAULT_UPDATE_DELAY
        ): cv.positive_float,
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_TEMP_STEP, default=1.0): vol.Coerce(float),
    }
)
async def async_setup_platform(
    _hass: HomeAssistant,
    config: dict[str, Any],
    _add_entities: AddEntitiesCallback,
    _discovery_info: dict[str, Any] | None = None,
) -> None:
    """Import YAML platform configuration to a Config Flow."""
    async_create_issue(
        _hass,
        DOMAIN,
        "deprecated_yaml",
        breaks_in_ha_version="2026.0.0",
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
    )
    # fmt: off
    _LOGGER.warning("Configuration of 'climate_ip' via YAML is deprecated and will be removed in a future version. Your configuration has been automatically imported into the UI (Config Entries)")  # pragma: no mutate
    # fmt: on
    # Anti-loop guard: skip if this entry was already imported from YAML
    current_entries = _hass.config_entries.async_entries(DOMAIN)
    if any(entry.source == SOURCE_IMPORT for entry in current_entries):
        _LOGGER.debug(
            "YAML setup suppressed: Entry already imported previously."
        )  # pragma: no mutate
        return
    _hass.async_create_task(
        _hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=config
        ),
        name="climate_ip_yaml_import",
    )
async def async_setup_entry(
    _hass: HomeAssistant,
    entry: "ClimateIPConfigEntry",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate entity from a config entry."""
    # coordinators is now guaranteed by contract to be a dictionary
    coordinators = entry.runtime_data
    entities: list[ClimateIP] = []
   
    for device_id, coordinator in coordinators.items():
        entities.append(
            ClimateIP(
                coordinator,
                CLIMATE_ENTITY_DESCRIPTION,
            )
        )
    if not entities:
        _LOGGER.error(
            "No valid entities could be initialized from the provided coordinators."
        )
        return
    async_add_entities(entities, update_before_add=True)

# Alias for backwards compatibility with entity description typing
ClimateIPEntityDescription = ClimateEntityDescription

class ClimateIP(CoordinatorEntity[SamsungClimateCoordinator], ClimateEntity):
    # pylint: disable=import-outside-toplevel,abstract-method
    """Representation of a climate_ip climate device using a coordinator."""
    entity_description: ClimateEntityDescription
    _attr_has_entity_name = True
    _attr_name = None
    _attr_hvac_mode: HVACMode | None
    _attr_target_temperature: float | None
    _attr_current_temperature: float | None
    _attr_fan_mode: str | None
    _attr_swing_mode: str | None
    _attr_preset_mode: str | None
    _attr_hvac_modes: list[HVACMode]
    _attr_fan_modes: list[str]
    _attr_swing_modes: list[str]
    _attr_preset_modes: list[str]
    
    def __init__(
        self,
        coordinator: SamsungClimateCoordinator,
        description: ClimateEntityDescription,
    ) -> None:
        """Initialize the climate device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = str(self.coordinator.unique_id)
        self._attr_device_info = self.coordinator.device_info
        
        # Feature Flag Resolution (Static Run-Once)
        features = ClimateEntityFeature(0)
        ops = self.coordinator.operations
        for attr, feature in SUPPORTED_FEATURES_MAP.items():
            if attr in ops:
                features |= feature
        if ATTR_POWER in ops:
            features |= ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        self._attr_supported_features = features

        # Pre-calculated State Attributes ($O(1)$ enforce)
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_min_temp: float = DEFAULT_CLIMATE_IP_TEMP_MIN
        self._attr_max_temp: float = DEFAULT_CLIMATE_IP_TEMP_MAX

        options_dict = self.coordinator.entry.options
        data_dict = self.coordinator.entry.data
        configured_step = options_dict.get(
            CONF_TARGET_TEMP_STEP, data_dict.get(CONF_TARGET_TEMP_STEP)
        )

        # Defensive parsing of temperature step
        if configured_step is None:
            step: float = float(DEFAULT_TARGET_TEMP_STEP)
        else:
            try:
                step = float(configured_step)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "%s Invalid temp step configured (%s). Falling back to default.",
                    self.log_prefix,
                    configured_step,
                )
                step = float(DEFAULT_TARGET_TEMP_STEP)
        
        self._attr_target_temperature_step = int(step) if step.is_integer() else step
        
        if step < const.PRECISION_HALVES:
            self._attr_precision = const.PRECISION_TENTHS
        elif step == const.PRECISION_HALVES:
            self._attr_precision = const.PRECISION_HALVES
        else:
            self._attr_precision = const.PRECISION_WHOLE

        # Strict Instance Initialization (Eradicating OOP Distrust)
        self._attr_hvac_mode = None
        self._attr_target_temperature = None
        self._attr_current_temperature = None
        self._attr_fan_mode = None
        self._attr_swing_mode = None
        self._attr_preset_mode = None
        self._attr_hvac_modes = []
        self._attr_fan_modes = []
        self._attr_swing_modes = []
        self._attr_preset_modes = []

        self._sync_data_from_coordinator()

    def _sync_data_from_coordinator(self) -> None:
        """Pre-calculate and synchronize all entity states to guarantee $O(1)$ getters."""
        state = self.coordinator.data
        
        # 1. PRE-CALCULATE BOUNDARIES & EXTENDED ATTRIBUTES
        self._attr_min_temp = self._resolve_numeric_boundary(ATTR_MIN_TEMP, DEFAULT_CLIMATE_IP_TEMP_MIN)
        self._attr_max_temp = self._resolve_numeric_boundary(ATTR_MAX_TEMP, DEFAULT_CLIMATE_IP_TEMP_MAX)

        core_attrs = {
            const.ATTR_TEMPERATURE, ATTR_CURRENT_TEMPERATURE,
            ATTR_HVAC_MODE, ATTR_FAN_MODE, ATTR_SWING_MODE, ATTR_PRESET_MODE,
        }
        self._attr_extra_state_attributes = {
            k: v for k, v in self.coordinator.state_attributes.items() if k not in core_attrs
        }

        if state:
            prev_target = self._attr_target_temperature
            self._attr_hvac_mode = state.hvac_mode or HVACMode.OFF
            self._attr_target_temperature = state.target_temperature
            self._attr_current_temperature = state.current_temperature
            self._attr_fan_mode = state.fan_mode
            self._attr_swing_mode = state.swing_mode
            self._attr_preset_mode = state.preset_mode
            self._attr_fan_modes = state.fan_modes
            self._attr_swing_modes = state.swing_modes
            self._attr_preset_modes = state.preset_modes

            # Pre-calculate HVAC modes array (including OFF logic)
            modes = list(state.hvac_modes)
            if ClimateEntityFeature.TURN_OFF in self._attr_supported_features and HVACMode.OFF not in modes:
                modes.append(HVACMode.OFF)
            self._attr_hvac_modes = modes

            if prev_target != state.target_temperature:
                _LOGGER.debug("%s [Forensic-Climate] Target temperature updated: %s -> %s (hvac_mode=%s)", 
                              self.log_prefix, prev_target, state.target_temperature, self._attr_hvac_mode)
        else:
            self._attr_hvac_mode = None
            self._attr_target_temperature = None
            self._attr_current_temperature = None
            self._attr_fan_mode = None
            self._attr_swing_mode = None
            self._attr_preset_mode = None
            # Leave modes intact on brief drops to prevent UI flicker

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the coordinator for consistency."""
        return self.coordinator.log_prefix
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator and update the entity state."""
        self._sync_data_from_coordinator()
        super()._handle_coordinator_update()
    @property
    def available(self) -> bool:
        """Return True if entity is available based on coordinator truth."""
        if not self.coordinator:
            return False
        return self.coordinator.last_update_success and (
            self.coordinator.data is not None
        )
    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return self._attr_device_info

    async def _async_set_climate_mode(
        self, attr_name: str, mode_value: Any
    ) -> None:
        """Helper to unify the logic for setting hvac, fan, swing, and preset modes."""
        await self.coordinator.async_set_property(attr_name, mode_value)
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature and handle optional hvac_mode."""
        temp: float | None = kwargs.get(const.ATTR_TEMPERATURE)
        hvac_mode: HVACMode | None = kwargs.get(ATTR_HVAC_MODE)

        _LOGGER.debug(
            "%s [Forensic] async_set_temperature called with temp=%s, hvac_mode=%s, kwargs=%s", 
            self.log_prefix, temp, hvac_mode, kwargs
        )  # pragma: no mutate

        if hvac_mode is not None:
            await self.async_set_hvac_mode(hvac_mode)

        if temp is not None:
            await self._async_set_climate_mode(
                const.ATTR_TEMPERATURE, temp
            )
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        await self._async_set_climate_mode(ATTR_HVAC_MODE, hvac_mode)
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        if fan_mode not in self.fan_modes:
            # fmt: off
            _LOGGER.warning("%s Requested fan mode '%s' is not available. Ignoring request.", self.log_prefix, fan_mode)  # pragma: no mutate
            # fmt: on
            return
        await self._async_set_climate_mode(ATTR_FAN_MODE, fan_mode)
    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing operation."""
        await self._async_set_climate_mode(
            ATTR_SWING_MODE, swing_mode
        )
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        await self._async_set_climate_mode(
            ATTR_PRESET_MODE, preset_mode
        )
    async def async_set_property(self, key: str, value: Any) -> None:
        """Set a custom property on the device."""
        _LOGGER.debug(
            "%s Setting property %s to %s", self.log_prefix, key, value
        )  # pragma: no mutate
        await self.coordinator.async_set_property(key, value)
    async def async_turn_on(self) -> None:
        """Turn the climate device on."""
        await self._async_set_climate_mode(ATTR_POWER, const.STATE_ON)
    async def async_turn_off(self) -> None:
        """Turn the climate device off."""
        await self._async_set_climate_mode(ATTR_POWER, const.STATE_OFF)
    async def async_service_set_property(self, **kwargs: Any) -> None:
        """Set a property on the device via action call."""
        key: str | None = kwargs.get("key")
        value: Any | None = kwargs.get("value")
        if not key:
            _LOGGER.warning(
                "%s set_property action called without a valid key.", self.log_prefix
            )  # pragma: no mutate
            return
        _LOGGER.debug(
            "%s Action set_property called: %s = %s", self.log_prefix, key, value
        )  # pragma: no mutate
        await self.coordinator.async_set_property(key, value)
        await self.coordinator.async_request_refresh()
    
    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit."""
        return self.hass.config.units.temperature_unit

    def _resolve_numeric_boundary(self, prop_key: str, default_val: float) -> float:
        """Safely resolve numeric boundaries avoiding hot-path overhead."""
        prop_obj = self.coordinator.get_property_object(prop_key)
        if not prop_obj or prop_obj.value is None:
            return float(default_val)
        try:
            return float(prop_obj.value)
        except (ValueError, TypeError):
            return float(default_val)

