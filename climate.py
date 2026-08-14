"""Support for Samsung AC devices using climate_ip."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
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

_CORE_ATTRIBUTES: Final[set[str]] = {
    ATTR_TEMPERATURE,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_MODE,
    ATTR_FAN_MODE,
    ATTR_SWING_MODE,
    ATTR_PRESET_MODE,
}


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ClimateIPConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate entity from a config entry."""
    entities = [
        ClimateIP(coordinator, CLIMATE_ENTITY_DESCRIPTION)
        for coordinator in entry.runtime_data.values()
    ]
    if not entities:
        _LOGGER.error(
            "No valid entities could be initialized from the provided coordinators."
        )
        return
    async_add_entities(entities)


class ClimateIP(CoordinatorEntity[SamsungClimateCoordinator], ClimateEntity):
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

        entry = getattr(self.coordinator, "entry", None) or getattr(self.coordinator, "config_entry", None)
        options_dict = entry.options if entry is not None else {}
        data_dict = entry.data if entry is not None else {}
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
            ATTR_MIN_TEMP, DEFAULT_CLIMATE_IP_TEMP_MIN
        )
        self._attr_max_temp = self._extract_float_boundary(
            ATTR_MAX_TEMP, DEFAULT_CLIMATE_IP_TEMP_MAX
        )

    def _extract_float_boundary(self, prop_key: str, default_val: float) -> float:
        """Extract and cast numeric boundaries safely."""
        prop = self.coordinator.controller.get_property_object(prop_key)
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
    def hvac_action(self) -> HVACAction | str | None:
        """Return the current running hvac operation if supported."""
        if not self.coordinator.data or self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        mode = self.hvac_mode
        if mode == HVACMode.DRY:
            return HVACAction.DRYING
        if mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN

        current = self.current_temperature
        target = self.target_temperature

        if mode == HVACMode.COOL:
            return (
                HVACAction.COOLING
                if current is None or target is None or current > (target - 0.5)
                else HVACAction.IDLE
            )

        if mode == HVACMode.HEAT:
            return (
                HVACAction.HEATING
                if current is None or target is None or current < (target + 0.5)
                else HVACAction.IDLE
            )

        if (
            mode in (HVACMode.AUTO, HVACMode.HEAT_COOL)
            and current is not None
            and target is not None
        ):
            if current < (target - 0.5):
                return HVACAction.HEATING
            if current > (target + 0.5):
                return HVACAction.COOLING

        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        return (
            self.coordinator.data.current_temperature if self.coordinator.data else None
        )

    @property
    def target_temperature(self) -> float | None:
        return (
            self.coordinator.data.target_temperature if self.coordinator.data else None
        )

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
        return {
            k: v
            for k, v in self.coordinator.controller.state_attributes.items()
            if k not in _CORE_ATTRIBUTES
        }

    @property
    def hvac_modes(self) -> list[HVACMode] | list[str]:
        if not self.coordinator.data:
            return []
        modes = list(self.coordinator.data.hvac_modes)
        if (
            ClimateEntityFeature.TURN_OFF in self._attr_supported_features
            and HVACMode.OFF not in modes
        ):
            modes.append(HVACMode.OFF)
        return modes

    @property
    def fan_modes(self) -> list[str]:
        return list(self.coordinator.data.fan_modes) if self.coordinator.data else []

    @property
    def swing_modes(self) -> list[str]:
        return list(self.coordinator.data.swing_modes) if self.coordinator.data else []

    @property
    def preset_modes(self) -> list[str]:
        return list(self.coordinator.data.preset_modes) if self.coordinator.data else []

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit used for display."""
        return self.hass.config.units.temperature_unit

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature and/or hvac mode."""
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        if hvac_mode is not None:
            await self.async_set_hvac_mode(hvac_mode)

        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            await self.coordinator.async_set_property(ATTR_TEMPERATURE, temperature)
        elif hvac_mode is None:
            # Only raise an error if BOTH parameters are missing
            raise ServiceValidationError(
                f"[{self.coordinator.log_prefix}] No temperature or HVAC mode provided in set_temperature action."
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode not in self.hvac_modes:
            raise ServiceValidationError(
                f"[{self.coordinator.log_prefix}] Requested HVAC mode '{hvac_mode}' is not available."
            )
        await self.coordinator.async_set_property(ATTR_HVAC_MODE, hvac_mode)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        if fan_mode not in self.fan_modes:
            raise ServiceValidationError(
                f"[{self.coordinator.log_prefix}] Requested fan mode '{fan_mode}' is not available."
            )
        await self.coordinator.async_set_property(ATTR_FAN_MODE, fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing operation."""
        if swing_mode not in self.swing_modes:
            raise ServiceValidationError(
                f"[{self.coordinator.log_prefix}] Requested swing mode '{swing_mode}' is not available."
            )
        await self.coordinator.async_set_property(ATTR_SWING_MODE, swing_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        if preset_mode not in self.preset_modes:
            raise ServiceValidationError(
                f"[{self.coordinator.log_prefix}] Requested preset mode '{preset_mode}' is not available."
            )
        await self.coordinator.async_set_property(ATTR_PRESET_MODE, preset_mode)

    async def async_turn_on(self) -> None:
        """Turn the climate device on."""
        await self.coordinator.async_set_property(ATTR_POWER, STATE_ON)

    async def async_turn_off(self) -> None:
        """Turn the climate device off."""
        await self.coordinator.async_set_property(ATTR_POWER, STATE_OFF)

    async def async_service_set_property(self, key: str, value: Any) -> None:
        """Set a property on the device via action call with strict validation."""
        if key not in self.coordinator.controller.operations:
            raise ServiceValidationError(
                f"Action set_property failed: '{key}' is not a valid operation for this device."
            )

        if not isinstance(value, str | int | float | bool):
            raise ServiceValidationError(
                f"Action set_property failed: Invalid value type '{type(value).__name__}' for key '{key}'."
            )

        _LOGGER.debug(
            "%s Action set_property called: %s = %s",
            self.coordinator.log_prefix,
            key,
            value,
        )
        await self.coordinator.async_set_property(key, value)
