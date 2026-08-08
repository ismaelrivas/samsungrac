"""Dataclass for representing the immutable state of a climate device."""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.components.climate import HVACMode


@dataclass(frozen=True)
class ClimateIPDeviceState:
    """
    Immutable and strictly typed dataclass representing climate device state.
    Enforces Fail-Fast doctrine: invalid types or corrupt contracts raise exceptions immediately.
    """

    # Main state fields (strictly typed, immutable)
    hvac_mode: HVACMode | None = None
    target_temperature: float | None = None
    current_temperature: float | None = None
    fan_mode: str | None = None
    swing_mode: str | None = None
    preset_mode: str | None = None

    # Available mode lists (stored as immutable tuples to prevent shared mutable state)
    hvac_modes: tuple[HVACMode, ...] = field(default_factory=tuple)
    fan_modes: tuple[str, ...] = field(default_factory=tuple)
    swing_modes: tuple[str, ...] = field(default_factory=tuple)
    preset_modes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Enforce strict type contracts and immutability validation."""
        # Validate HVAC Mode type explicitly (Fail-Fast)
        if self.hvac_mode is not None and not isinstance(self.hvac_mode, HVACMode):
            raise TypeError(
                f"Expected HVACMode instance for hvac_mode, got {type(self.hvac_mode)}"
            )  # pragma: no mutate

        # Validate Temperatures explicitly (Reject non-numeric strings or invalid objects)
        if self.target_temperature is not None and not isinstance(
            self.target_temperature, int | float
        ):
            raise TypeError(
                f"Target temperature must be numeric, got {type(self.target_temperature)}"
            )  # pragma: no mutate

        if self.current_temperature is not None and not isinstance(
            self.current_temperature, int | float
        ):
            raise TypeError(
                f"Current temperature must be numeric, got {type(self.current_temperature)}"
            )  # pragma: no mutate

        # Ensure lists/tuples are correctly typed elements
        if any(not isinstance(m, HVACMode) for m in self.hvac_modes):
            raise TypeError(
                "All items in hvac_modes must be valid HVACMode instances."
            )  # pragma: no mutate
