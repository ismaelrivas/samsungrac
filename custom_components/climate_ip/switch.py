import logging
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SamsungClimateCoordinator
from .properties import PROPERTY_TYPE_SWITCH

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Samsung Climate IP switches."""
    
    # Coordinator is stored in hass.data[DOMAIN][entry.entry_id]
    # It might be a single coordinator or a dict of coordinators if multiple devices
    coordinator_data = hass.data[DOMAIN][entry.entry_id]
    
    if isinstance(coordinator_data, dict):
        coordinators = list(coordinator_data.values())
    else:
        coordinators = [coordinator_data]

    entities = []
    
    for coordinator in coordinators:
        controller = coordinator.controller
        
        # Iterate over operations to find switches
        # operations is a property returning a list of op objects
        # However, due to some issue, it might return strings (keys). We handle both.
        ops = controller.operations
        if isinstance(ops, dict):
            ops = ops.values()
            
        for op in ops:
            if isinstance(op, str):
                 # Use public accessor instead of private _operations dict
                 prop_obj = controller.get_property_object(op)
                 if prop_obj is not None:
                     op = prop_obj
                 else:
                     _LOGGER.error("Switch setup: Could not find operation object for '%s'", op)
                     continue


            # We skip 'power' because it's the main control for the climate entity
            if not hasattr(op, "id"):
                 _LOGGER.error("Switch setup: op has no id! op=%s", op)
                 continue

            if op.id == "power":
                continue
                
            if op.match_type(PROPERTY_TYPE_SWITCH):
                # Check if the switch is valid for this device (based on capabilities)
                # We use the raw device state from the controller for validation, not the wrapper
                raw_device_state = controller.device_state
                if not op.is_valid(raw_device_state):

                    continue


                entities.append(SamsungClimateSwitch(coordinator, op))

    if entities:
        async_add_entities(entities)


class SamsungClimateSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Samsung Climate IP Switch."""

    def __init__(self, coordinator: SamsungClimateCoordinator, operation):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._operation = operation
        self._controller = coordinator.controller
        
        # Entity Identifiers
        self._attr_has_entity_name = True
        self._attr_name = operation.name
        self._attr_unique_id = f"{coordinator.unique_id}_{operation.id}"
        self._attr_device_info = coordinator.device_info
        
        # Metadata from YAML
        if hasattr(operation, "device_class"):
            self._attr_device_class = operation.device_class
        
        # Determine initial state
        self._update_state()

    @property
    def is_on(self) -> Optional[bool]:
        """Return True if entity is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        _LOGGER.debug("Turning on %s", self.name)
        if await self._controller.async_set_property(self._operation.id, "on"):
            self._is_on = True
            self.async_write_ha_state()
            # Trigger refresh to align state
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        _LOGGER.debug("Turning off %s", self.name)
        if await self._controller.async_set_property(self._operation.id, "off"):
            self._is_on = False
            self.async_write_ha_state()
            # Trigger refresh to align state
            await self.coordinator.async_request_refresh()

    def _update_state(self):
        """Update internal state from operation value."""
        # The operation value comes from the controller/coordinator data
        # 'on' or 'off' (lowercase) or True/False depending on YAML mapping
        # Our yaml mapping usually maps 'on' -> 'Spi_On' etc.
        # But get_property returns the HASS value.
        
        value = self._operation.value
        
        if value in ["on", "On", True]:
            self._is_on = True
        elif value in ["off", "Off", False]:
            self._is_on = False
        else:
             self._is_on = None # Unknown

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._controller.available

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state()
        super()._handle_coordinator_update()
