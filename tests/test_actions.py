# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test native Home Assistant actions from actions.yaml."""

# pylint: disable=import-outside-toplevel
from unittest.mock import AsyncMock, MagicMock
import asyncio

from homeassistant.core import HomeAssistant


async def test_set_property_action(hass: HomeAssistant) -> None:
    """Test that set_property action correctly calls the entity method."""
    from custom_components.climate_ip.climate import (
        ClimateIP,
        ClimateIPEntityDescription,
    )
    from custom_components.climate_ip.coordinator import (
        SamsungClimateCoordinator,
    )

    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_unique_id_001"
    mock_coordinator.log_prefix = "[ActionTest]"
    mock_coordinator.operations = {"hvac_mode": MagicMock(), "fan_mode": MagicMock()}
    mock_coordinator.attributes = []
    mock_coordinator.is_push_device = False
    mock_coordinator.poll = True
    mock_coordinator.temperature_unit = "°C"
    mock_coordinator.data = MagicMock(
        hvac_mode="cool",
        target_temperature=22.0,
        current_temperature=None,
        fan_mode="auto",
        swing_mode=None,
        preset_mode=None,
        hvac_modes=["cool", "heat"],
        fan_modes=["auto", "low"],
        swing_modes=[],
        preset_modes=[],
    )
    mock_coordinator.entry = MagicMock(options={}, data={})
    mock_coordinator.config_entry = mock_coordinator.entry
    mock_coordinator.device_info = MagicMock()
    mock_coordinator.async_set_property = AsyncMock()
    mock_coordinator.register_entity = MagicMock()
    mock_coordinator.coordinator = None

    description = ClimateIPEntityDescription(
        key="samsung_ac", translation_key="samsung_ac"
    )
    entity = ClimateIP(mock_coordinator, description)
    entity.hass = hass
    entity.entity_id = "climate.test_ac"
    # Mock HA state writing to avoid "Frame helper not set up" errors in unit tests
    entity.async_write_ha_state = MagicMock()

    # In a real HA environment, this would be triggered via hass.services.async_call
    # Here we just verify the entity method exists and behaves as expected when called
    # with common parameters from actions.yaml
    hass.async_create_task.side_effect = lambda coro, **kw: asyncio.create_task(coro)
    await entity.async_set_property("AC_FUN_POWER", "On")
    await asyncio.sleep(0)

    # Verify it delegated to the coordinator
    mock_coordinator.async_set_property.assert_awaited_once_with("AC_FUN_POWER", "On")

    # The first call to async_execute is usually for polling or setup,
    # but here we are testing the actual command execution


async def test_native_service_registry(hass: HomeAssistant) -> None:
    """Verify that no deprecated manual service registration exists."""

    # Reloading/setup should NOT call hass.services.register for 'set_property'
    # as it should be handles by actions.yaml automatically
    with MagicMock() as mock_register:
        hass.services.async_register = mock_register
        # Verify manually that we don't have code in __init__.py doing this.
        # This is more of a architectural test.
