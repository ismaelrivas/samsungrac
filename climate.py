"""Support for Samsung AC devices using climate_ip."""
# pylint: disable=import-outside-toplevel,too-many-instance-attributes,too-many-public-methods
import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from . import ClimateIPConfigEntry

from .const import (
    CONF_TARGET_TEMP_STEP,
    DEFAULT_CLIMATE_IP_TEMP_MAX,
    DEFAULT_CLIMATE_IP_TEMP_MIN,
    DEFAULT_TARGET_TEMP_STEP,
)
from .controller import ATTR_POWER
from .coordinator import SamsungClimateCoordinator

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES_MAP: Final[dict[str, ClimateEntityFeature]] = {
    ATTR_TEMPERATURE: ClimateEntityFeature.TARGET_TEMPERATURE,
    ATTR_FAN_MODE: ClimateEntityFeature.FAN_MODE,
    ATTR_SWING_MODE: ClimateEntityFeature.SWING_MODE,
    ATTR_PRESET_MODE: ClimateEntityFeature.PRESET_MODE,
}

CLIMATE_ENTITY_DESCRIPTION: Final[ClimateEntityDescription] = ClimateEntityDescription(
    key="samsung_ac",
    translation_key="samsung_ac",
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

class ClimateIP(CoordinatorEntity[SamsungClimateCoordinator], ClimateEntity):
    # pylint: disable=import-outside-toplevel,abstract-method
    """Representation of a climate_ip climate device using a coordinator."""
    entity_description: ClimateEntityDescription
    _attr_has_entity_name = True
    _attr_name = None
    
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
        ops = self.coordinator.controller.operations
        for attr, feature in SUPPORTED_FEATURES_MAP.items():
            if attr in ops:
                features |= feature
        if ATTR_POWER in ops:
            features |= ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        self._attr_supported_features = features

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
                    self.coordinator.log_prefix,
                    configured_step,
                )
                step = float(DEFAULT_TARGET_TEMP_STEP)
        
        self._attr_target_temperature_step = int(step) if step.is_integer() else step
        
        if step < PRECISION_HALVES:
            self._attr_precision = PRECISION_TENTHS
        elif step == PRECISION_HALVES:
            self._attr_precision = PRECISION_HALVES
        else:
            self._attr_precision = PRECISION_WHOLE

        # Cache static hardware temperature boundaries
        self._attr_min_temp = self._extract_float_boundary(
            self.coordinator.controller, ATTR_MIN_TEMP, DEFAULT_CLIMATE_IP_TEMP_MIN
        )
        self._attr_max_temp = self._extract_float_boundary(
            self.coordinator.controller, ATTR_MAX_TEMP, DEFAULT_CLIMATE_IP_TEMP_MAX
        )

    def _extract_float_boundary(self, controller: Any, prop_key: str, default_val: float) -> float:
        """Extract and cast numeric boundaries safely."""
        prop = controller.get_property_object(prop_key)
        if prop and prop.value is not None:
            try:
                return float(prop.value)
            except (ValueError, TypeError):
                pass
        return float(default_val)

    @property
    def hvac_mode(self) -> HVACMode | str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.hvac_mode or HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.current_temperature if self.coordinator.data else None

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.target_temperature if self.coordinator.data else None

    @property
    def fan_mode(self) -> str | None:
        return self.coordinator.data.fan_mode if self.coordinator.data else None

    @property
    def swing_mode(self) -> str | None:
        return self.coordinator.data.swing_mode if self.coordinator.data else None

    @property
    def preset_mode(self) -> str | None:
        return self.coordinator.data.preset_mode if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        core_attrs = {
            ATTR_TEMPERATURE, ATTR_CURRENT_TEMPERATURE,
            ATTR_HVAC_MODE, ATTR_FAN_MODE, ATTR_SWING_MODE, ATTR_PRESET_MODE,
        }
        return {
            k: v for k, v in self.coordinator.controller.state_attributes.items() 
            if k not in core_attrs
        }

    @property
    def hvac_modes(self) -> list[HVACMode] | list[str]:
        if not self.coordinator.data:
            return []
        modes = list(self.coordinator.data.hvac_modes)
        if ClimateEntityFeature.TURN_OFF in self._attr_supported_features and HVACMode.OFF not in modes:
            modes.append(HVACMode.OFF)
        return modes

    @property
    def fan_modes(self) -> list[str]:
        return self.coordinator.data.fan_modes if self.coordinator.data else []

    @property
    def swing_modes(self) -> list[str]:
        return self.coordinator.data.swing_modes if self.coordinator.data else []

    @property
    def preset_modes(self) -> list[str]:
        return self.coordinator.data.preset_modes if self.coordinator.data else []

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit."""
        return self.hass.config.units.temperature_unit
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator and update the entity state."""
        super()._handle_coordinator_update()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature and handle optional hvac_mode."""
        temp: float | None = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode: HVACMode | None = kwargs.get(ATTR_HVAC_MODE)

        _LOGGER.debug(
            "%s [Forensic] async_set_temperature called with temp=%s, hvac_mode=%s, kwargs=%s", 
            self.coordinator.log_prefix, temp, hvac_mode, kwargs
        )  # pragma: no mutate

        if hvac_mode is not None:
            await self.async_set_hvac_mode(hvac_mode)

        if temp is not None:
            await self.coordinator.async_set_property(
                ATTR_TEMPERATURE, temp
            )
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        await self.coordinator.async_set_property(ATTR_HVAC_MODE, hvac_mode)
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        if fan_mode not in self.fan_modes:
            # fmt: off
            _LOGGER.warning("%s Requested fan mode '%s' is not available. Ignoring request.", self.coordinator.log_prefix, fan_mode)  # pragma: no mutate
            # fmt: on
            return
        await self.coordinator.async_set_property(ATTR_FAN_MODE, fan_mode)
    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing operation."""
        await self.coordinator.async_set_property(
            ATTR_SWING_MODE, swing_mode
        )
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        await self.coordinator.async_set_property(
            ATTR_PRESET_MODE, preset_mode
        )
    async def async_turn_on(self) -> None:
        """Turn the climate device on."""
        await self.coordinator.async_set_property(ATTR_POWER, STATE_ON)
    async def async_turn_off(self) -> None:
        """Turn the climate device off."""
        await self.coordinator.async_set_property(ATTR_POWER, STATE_OFF)
    async def async_service_set_property(self, **kwargs: Any) -> None:
        """Set a property on the device via action call."""
        key: str | None = kwargs.get("key")
        value: Any | None = kwargs.get("value")
        if not key:
            _LOGGER.warning(
                "%s set_property action called without a valid key.", self.coordinator.log_prefix
            )  # pragma: no mutate
            return
        _LOGGER.debug(
            "%s Action set_property called: %s = %s", self.coordinator.log_prefix, key, value
        )  # pragma: no mutate
        await self.coordinator.async_set_property(key, value)

