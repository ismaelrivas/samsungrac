"""Dataclass for representing the state of a climate device."""

from dataclasses import dataclass, field

from homeassistant.components.climate import HVACMode


@dataclass
class ClimateIPDeviceState:  # pylint: disable=import-outside-toplevel,too-many-instance-attributes
    """
    Dataclass to represent the state of the climate device.
    This provides strong typing for coordinator.data and helps optimize state updates.
    """

    # Main state fields
    hvac_mode: HVACMode | None = None
    target_temperature: float | None = None
    current_temperature: float | None = None
    fan_mode: str | None = None
    swing_mode: str | None = None
    preset_mode: str | None = None

    # Available mode lists (can be dynamic)
    hvac_modes: list[HVACMode] = field(default_factory=list)
    fan_modes: list[str] = field(default_factory=list)
    swing_modes: list[str] = field(default_factory=list)
    preset_modes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Strictly validate and coerce data types to prevent data corruption."""
        # Coerce HVAC Mode
        if self.hvac_mode is not None and not isinstance(self.hvac_mode, HVACMode):
            self.hvac_mode = HVACMode(str(self.hvac_mode).lower())

        # Coerce Temperatures
        if self.target_temperature is not None:
            self.target_temperature = float(self.target_temperature)
        if self.current_temperature is not None:
            self.current_temperature = float(self.current_temperature)

        # Coerce Fan Mode, Swing Mode, Preset Mode to strings
        if self.fan_mode is not None:
            self.fan_mode = str(self.fan_mode)
        if self.swing_mode is not None:
            self.swing_mode = str(self.swing_mode)
        if self.preset_mode is not None:
            self.preset_mode = str(self.preset_mode)

        # Coerce HVAC Modes List
        if self.hvac_modes:
            coerced_hvac_modes = []
            for mode in self.hvac_modes:
                coerced_hvac_modes.append(
                    HVACMode(str(mode).lower())
                    if not isinstance(mode, HVACMode)
                    else mode
                )
            self.hvac_modes = coerced_hvac_modes

        # Ensure string lists
        if self.fan_modes:
            self.fan_modes = [str(x) for x in self.fan_modes]
        if self.swing_modes:
            self.swing_modes = [str(x) for x in self.swing_modes]
        if self.preset_modes:
            self.preset_modes = [str(x) for x in self.preset_modes]
