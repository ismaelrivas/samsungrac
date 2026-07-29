"""Support for Samsung AC devices using climate_ip."""
# pylint: disable=import-outside-toplevel,too-many-instance-attributes,too-many-public-methods

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
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
from homeassistant.exceptions import ConfigEntryNotReady
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
    CONF_TEMP_STEP,
    CONFIG_DEVICE_NAME,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_UPDATE_DELAY,
    DEFAULT_CLIMATE_IP_TEMP_MAX,
    DEFAULT_CLIMATE_IP_TEMP_MIN,
    DEFAULT_CONF_CERT_FILE,
    DEFAULT_CONF_CONFIG_FILE,
    DEFAULT_CONF_CONTROLLER,
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

# Strict map for optimistic predictions (removes dynamic hasattr attack vector)
ALLOWED_OPTIMISTIC_CORRECTIONS: Final[dict[str, str]] = {
    const.ATTR_TEMPERATURE: "_attr_target_temperature",
    ATTR_HVAC_MODE: "_attr_hvac_mode",
    ATTR_FAN_MODE: "_attr_fan_mode",
    ATTR_SWING_MODE: "_attr_swing_mode",
    ATTR_PRESET_MODE: "_attr_preset_mode",
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
    from homeassistant.helpers.issue_registry import async_create_issue, IssueSeverity

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
    # coordinators ahora está garantizado por contrato que es un diccionario
    coordinators = entry.runtime_data

    entities: list[ClimateIP] = []
    
    for device_id, coordinator in coordinators.items():
        entities.append(
            ClimateIP(
                coordinator,
                CLIMATE_ENTITY_DESCRIPTION,
                dict(entry.data),
                entry.unique_id,
            )
        )

    if not entities:
        _LOGGER.error(
            "No valid entities could be initialized from the provided coordinators."
        )
        return

    async_add_entities(entities, update_before_add=True)


@dataclass(frozen=True, kw_only=True)
class ClimateIPEntityDescription(ClimateEntityDescription):
    """Class describing ClimateIP entities."""

    key: str
    translation_key: str | None = None


class ClimateIP(CoordinatorEntity[SamsungClimateCoordinator], ClimateEntity):
    # pylint: disable=import-outside-toplevel,abstract-method
    """Representation of a climate_ip climate device using a coordinator."""

    entity_description: ClimateIPEntityDescription

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

    _config: dict[str, Any]
    _main_unique_id: str

    def __init__(
        self,
        coordinator: SamsungClimateCoordinator,
        description: ClimateIPEntityDescription,
        config: dict[str, Any],
        main_unique_id: str | None = None,
    ) -> None:
        """Initialize the climate device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._config = config
        self._main_unique_id = main_unique_id or str(coordinator.unique_id)

        self._attr_unique_id = str(self.coordinator.unique_id)
        self._attr_device_info = self.coordinator.device_info

        from .const import CONF_TARGET_TEMP_STEP, DEFAULT_TARGET_TEMP_STEP

        # entry = getattr(self.coordinator, "entry", None)
        # options_dict = entry.options if entry else {}
        options_dict = self.coordinator.entry.options

        configured_step = options_dict.get(
            CONF_TARGET_TEMP_STEP,
            self._config.get(CONF_TARGET_TEMP_STEP, self._config.get(CONF_TEMP_STEP)),
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
                )  # pragma: no mutate
                step = float(DEFAULT_TARGET_TEMP_STEP)

        # self._attr_target_temperature_step = int(step) if step == int(step) else step
        self._attr_target_temperature_step = int(step) if step.is_integer() else step

        if step < 0.5:
            self._attr_precision = const.PRECISION_TENTHS
        elif step == 0.5:
            self._attr_precision = const.PRECISION_HALVES
        else:
            self._attr_precision = const.PRECISION_WHOLE

        self._sync_data_from_coordinator()

    @property
    def log_prefix(self) -> str:
        """Return the log prefix from the coordinator for consistency."""
        return self.coordinator.log_prefix

    def _sync_data_from_coordinator(self) -> None:
        """Synchronize the entity's state with the latest data from the coordinator."""
        state = self.coordinator.data
        if state:
            self._attr_hvac_mode = state.hvac_mode or HVACMode.OFF
            self._attr_target_temperature = state.target_temperature
            self._attr_current_temperature = state.current_temperature
            self._attr_fan_mode = state.fan_mode
            self._attr_swing_mode = state.swing_mode
            self._attr_preset_mode = state.preset_mode
            self._attr_hvac_modes = state.hvac_modes
            self._attr_fan_modes = state.fan_modes
            self._attr_swing_modes = state.swing_modes
            self._attr_preset_modes = state.preset_modes
        else:
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

        # Cache temperature boundaries to prevent dynamic parsing on UI render
        min_t_prop = self.coordinator.get_property_object(ATTR_MIN_TEMP)
        try:
            self._attr_min_temp = float(min_t_prop.value) if min_t_prop and min_t_prop.value is not None else float(DEFAULT_CLIMATE_IP_TEMP_MIN)
        except (ValueError, TypeError):
            self._attr_min_temp = float(DEFAULT_CLIMATE_IP_TEMP_MIN)

        max_t_prop = self.coordinator.get_property_object(ATTR_MAX_TEMP)
        try:
            self._attr_max_temp = float(max_t_prop.value) if max_t_prop and max_t_prop.value is not None else float(DEFAULT_CLIMATE_IP_TEMP_MAX)
        except (ValueError, TypeError):
            self._attr_max_temp = float(DEFAULT_CLIMATE_IP_TEMP_MAX)

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

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the supported features, computed from the controller's operations."""
        features = ClimateEntityFeature(0)
        ops = self.coordinator.operations

        for attr, feature in SUPPORTED_FEATURES_MAP.items():
            if attr in ops:
                if attr == ATTR_SWING_MODE and not self.swing_modes:
                    continue
                features |= feature

        if ATTR_POWER in ops:
            features |= ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF

        return features

    def _apply_optimistic_corrections(self, corrections: dict[str, Any] | None) -> None:
        """Apply predicted corrections strictly using ALLOWED_OPTIMISTIC_CORRECTIONS map."""
        if not corrections:
            return

        _LOGGER.debug(
            "%s Applying optimistic corrections: %s", self.log_prefix, corrections
        )  # pragma: no mutate

        for prop, value in corrections.items():
            if target_attr := ALLOWED_OPTIMISTIC_CORRECTIONS.get(prop):
                setattr(self, target_attr, value)
            else:
                _LOGGER.debug(
                    "%s Ignoring unmapped optimistic correction for property: %s",
                    self.log_prefix,
                    prop,
                )  # pragma: no mutate

    async def _async_set_climate_mode(
        self, attr_name: str, mode_value: Any, local_attr: str | None
    ) -> None:
        """Helper to unify the logic for setting hvac, fan, swing, and preset modes."""
        _, corrections = await self.coordinator.async_predict_and_correct(
            self.coordinator.data, attr_name, mode_value
        )
        if local_attr and hasattr(self, local_attr):
            setattr(self, local_attr, mode_value)

        self._apply_optimistic_corrections(corrections)
        self.async_write_ha_state()
        self.hass.async_create_task(
            self.coordinator.async_set_property(attr_name, mode_value, corrections)
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp: float | None = kwargs.get(const.ATTR_TEMPERATURE)
        if temp is not None:
            await self._async_set_climate_mode(
                const.ATTR_TEMPERATURE, temp, "_attr_target_temperature"
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        await self._async_set_climate_mode(ATTR_HVAC_MODE, hvac_mode, "_attr_hvac_mode")

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        if fan_mode not in self.fan_modes:
            # fmt: off
            _LOGGER.warning("%s Requested fan mode '%s' is not available. Ignoring request.", self.log_prefix, fan_mode)  # pragma: no mutate
            # fmt: on
            return
        await self._async_set_climate_mode(ATTR_FAN_MODE, fan_mode, "_attr_fan_mode")

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing operation."""
        await self._async_set_climate_mode(
            ATTR_SWING_MODE, swing_mode, "_attr_swing_mode"
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        await self._async_set_climate_mode(
            ATTR_PRESET_MODE, preset_mode, "_attr_preset_mode"
        )

    async def async_set_property(self, key: str, value: Any) -> None:
        """Set a custom property on the device."""
        _LOGGER.debug(
            "%s Setting property %s to %s", self.log_prefix, key, value
        )  # pragma: no mutate
        self.hass.async_create_task(self.coordinator.async_set_property(key, value))
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn the climate device on."""
        await self._async_set_climate_mode(ATTR_POWER, const.STATE_ON, None)

    async def async_turn_off(self) -> None:
        """Turn the climate device off."""
        self._attr_hvac_mode = HVACMode.OFF
        await self._async_set_climate_mode(ATTR_POWER, const.STATE_OFF, None)

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
        await self.coordinator.async_set_property(key, value, {})
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        core_attrs = {
            const.ATTR_TEMPERATURE,
            ATTR_CURRENT_TEMPERATURE,
            ATTR_HVAC_MODE,
            ATTR_FAN_MODE,
            ATTR_SWING_MODE,
            ATTR_PRESET_MODE,
        }
        return {
            k: v
            for k, v in self.coordinator.state_attributes.items()
            if k not in core_attrs
        }

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit."""
        return self.hass.config.units.temperature_unit

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes."""
        modes: list[HVACMode] = self._attr_hvac_modes
        if (
            ClimateEntityFeature.TURN_OFF in self.supported_features
            and HVACMode.OFF not in modes
        ):
            return modes + [HVACMode.OFF]
        return modes

    @property
    def fan_modes(self) -> list[str]:
        """Return the list of available fan modes."""
        return self._attr_fan_modes

    @property
    def swing_modes(self) -> list[str]:
        """Return the list of available swing modes."""
        return self._attr_swing_modes

    @property
    def preset_modes(self) -> list[str]:
        """Return the list of available preset modes."""
        return self._attr_preset_modes

    # @property
    # def min_temp(self) -> float:
    #     """Return the minimum temperature strictly."""
    #     min_t_prop = self.coordinator.get_property_object(ATTR_MIN_TEMP)
    #     if min_t_prop and min_t_prop.value is not None:
    #         try:
    #             return float(min_t_prop.value)
    #         except (ValueError, TypeError):
    #             pass
    #     return float(DEFAULT_CLIMATE_IP_TEMP_MIN)

    # @property
    # def max_temp(self) -> float:
    #     """Return the maximum temperature strictly."""
    #     max_t_prop = self.coordinator.get_property_object(ATTR_MAX_TEMP)
    #     if max_t_prop and max_t_prop.value is not None:
    #         try:
    #             return float(max_t_prop.value)
    #         except (ValueError, TypeError):
    #             pass
    #     return float(DEFAULT_CLIMATE_IP_TEMP_MAX)
