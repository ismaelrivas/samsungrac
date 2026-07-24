"""
Platform that offers support for IP controlled climate device switches.
This file defines the Home Assistant switch entities.
"""

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClimateIPConfigEntry
from .coordinator import SamsungClimateCoordinator
from .helpers import parse_entity_category
from .properties import PROPERTY_TYPE_SWITCH, DeviceProperty

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(  # pylint: disable=import-outside-toplevel,too-many-branches,too-many-locals
    _hass: HomeAssistant,
    entry: ClimateIPConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung Climate IP switches."""

    coordinator_data = entry.runtime_data

    coordinators: list[SamsungClimateCoordinator] = (
        list(coordinator_data.values())
        if isinstance(coordinator_data, dict)
        else [coordinator_data]
    )

    entities: list[SamsungClimateSwitch] = []

    for coordinator in coordinators:
        controller = coordinator.controller
        ops = controller.operations

        if isinstance(ops, dict):
            ops = list(ops.values())

        for op in ops:
            if isinstance(op, str):
                prop_obj = controller.get_property_object(op)
                if prop_obj is not None:
                    op = prop_obj
                else:
                    msg = "Switch setup: Could not find operation object for '%s'"  # pragma: no mutate
                    _LOGGER.error(msg, op)  # pragma: no mutate
                    continue

            # We skip 'power' because it's the main control for the climate entity
            if not hasattr(op, "id"):
                msg = "Switch setup: op has no id! op=%s"  # pragma: no mutate
                _LOGGER.error(msg, op)  # pragma: no mutate
                continue

            if op.id == "power":
                continue

            if op.match_type(PROPERTY_TYPE_SWITCH):
                raw_device_state = controller.device_state
                if not op.is_valid(raw_device_state):
                    continue

                parsed_category = parse_entity_category(
                    getattr(op, "entity_category", None)
                )

                device_class = getattr(op, "device_class", None)
                icon = getattr(op, "icon", None)
                if not icon and not device_class:
                    icon = "mdi:toggle-switch"

                # Build a modern SwitchEntityDescription from the YAML operation.
                description = SwitchEntityDescription(
                    key=op.id,
                    translation_key=op.id,
                    name=None,  # Delegated fully to HA translations
                    device_class=device_class,
                    entity_category=parsed_category,
                    icon=icon,
                )

                entities.append(SamsungClimateSwitch(coordinator, description, op))

    if entities:
        async_add_entities(entities)


class SamsungClimateSwitch(CoordinatorEntity[SamsungClimateCoordinator], SwitchEntity):
    """Representation of a Samsung Climate IP Switch."""

    # pylint: disable=import-outside-toplevel,abstract-method

    _attr_is_on: bool | None

    def __init__(
        self,
        coordinator: SamsungClimateCoordinator,
        description: SwitchEntityDescription,
        operation: DeviceProperty,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        # Inject the standardized description provided by the platform
        self.entity_description = description
        self._operation = operation
        self._controller = coordinator.controller

        # Internal state attribute for HA SwitchEntity
        self._attr_is_on = None

        # Modern Entity Architecture Identifiers
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"
        self._attr_device_info = coordinator.device_info

        # Determine initial state
        self._update_state()

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=import-outside-toplevel,unused-argument
        """Turn the entity on."""
        msg = "Turning on %s"  # pragma: no mutate
        _LOGGER.debug(msg, self.name)  # pragma: no mutate
        if await self._controller.async_set_property(self.entity_description.key, "on"):
            self._attr_is_on = True
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=import-outside-toplevel,unused-argument
        """Turn the entity off."""
        msg = "Turning off %s"  # pragma: no mutate
        _LOGGER.debug(msg, self.name)  # pragma: no mutate
        if await self._controller.async_set_property(
            self.entity_description.key, "off"
        ):
            self._attr_is_on = False
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()

    def _update_state(self) -> None:
        """Update internal state from operation value."""
        value = getattr(self._operation, "value", None)

        if value in ["on", "On", True]:
            self._attr_is_on = True
        elif value in ["off", "Off", False]:
            self._attr_is_on = False
        else:
            self._attr_is_on = None  # Unknown

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Delegates exclusively to the coordinator so that availability is always
        consistent with the rest of the platform.  Direct access to
        ``_controller.available`` is intentionally avoided: it is an internal
        implementation detail that may diverge from the coordinator's view,
        producing a switch that reports ``available=True`` while the coordinator
        is in ``last_update_success=False``.
        """
        return super().available

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state()
        super()._handle_coordinator_update()
