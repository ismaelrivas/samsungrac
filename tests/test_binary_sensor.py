"""Unit tests for Climate IP diagnostic binary_sensor platform."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.climate_ip.binary_sensor import (
    ClimateIPConnectivitySensor,
    async_setup_entry,
)
from custom_components.climate_ip.const import DOMAIN
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory


def _create_mock_coordinator(
    unique_id: str | None = "test_unique_id",
    log_prefix: str = "[TestPrefix]",
    last_update_success: bool | None = True,
) -> MagicMock:
    """Create a mock SamsungClimateCoordinator instance."""
    coord = MagicMock()
    coord.unique_id = unique_id
    coord.log_prefix = log_prefix
    coord.device_info = (
        {"identifiers": {("climate_ip", unique_id)}} if unique_id else None
    )
    coord.last_update_success = last_update_success
    return coord


@pytest.mark.asyncio
async def test_async_setup_entry():
    """Test async_setup_entry with single coordinator, coordinator dict, and empty coordinators."""
    mock_hass = MagicMock()

    # Case 1: Single coordinator
    coord = _create_mock_coordinator()
    entry_single = MagicMock()
    entry_single.runtime_data = coord
    mock_add_entities = MagicMock()

    with patch(
        "custom_components.climate_ip.binary_sensor._LOGGER.debug"
    ) as mock_debug:
        await async_setup_entry(mock_hass, entry_single, mock_add_entities)
        mock_debug.assert_called_once_with(
            "%s Adding diagnostic connectivity binary sensors to Home Assistant",
            "[TestPrefix]",
        )

    mock_add_entities.assert_called_once()
    added_entities = mock_add_entities.call_args[0][0]
    assert len(added_entities) == 1
    entity = added_entities[0]
    assert isinstance(entity, ClimateIPConnectivitySensor)
    assert entity.entity_description.key == "connectivity"
    assert entity.entity_description.translation_key == "connectivity"
    assert (
        entity.entity_description.device_class == BinarySensorDeviceClass.CONNECTIVITY
    )
    assert entity.entity_description.entity_category == EntityCategory.DIAGNOSTIC
    assert entity.has_entity_name is True
    assert entity.unique_id == "test_unique_id_connectivity"

    # Case 2: Multi-device dictionary of coordinators
    c1 = _create_mock_coordinator(unique_id="dev1", log_prefix="[Dev1]")
    c2 = _create_mock_coordinator(unique_id="dev2", log_prefix="[Dev2]")
    entry_dict = MagicMock()
    entry_dict.runtime_data = {"dev1": c1, "dev2": c2}
    mock_add_entities_dict = MagicMock()

    with patch(
        "custom_components.climate_ip.binary_sensor._LOGGER.debug"
    ) as mock_debug_dict:
        await async_setup_entry(mock_hass, entry_dict, mock_add_entities_dict)
        mock_debug_dict.assert_called_once_with(
            "%s Adding diagnostic connectivity binary sensors to Home Assistant",
            "[Dev1]",
        )

    mock_add_entities_dict.assert_called_once()
    added_dict_entities = mock_add_entities_dict.call_args[0][0]
    assert len(added_dict_entities) == 2
    assert added_dict_entities[0].unique_id == "dev1_connectivity"
    assert added_dict_entities[1].unique_id == "dev2_connectivity"

    # Case 3: Empty coordinator list
    entry_empty = MagicMock()
    entry_empty.runtime_data = []
    mock_add_entities_empty = MagicMock()

    with patch(
        "custom_components.climate_ip.binary_sensor._LOGGER.debug"
    ) as mock_debug_empty:
        await async_setup_entry(mock_hass, entry_empty, mock_add_entities_empty)
        mock_debug_empty.assert_not_called()

    mock_add_entities_empty.assert_not_called()


def test_connectivity_sensor_attributes_and_is_on_states():
    """Test sensor metadata, availability, fallback unique ID, and is_on states."""
    coord = _create_mock_coordinator(
        unique_id="test_unique_id",
        log_prefix="[TestPrefix]",
        last_update_success=True,
    )
    desc = MagicMock(
        key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    sensor = ClimateIPConnectivitySensor(coord, desc)

    assert sensor.unique_id == "test_unique_id_connectivity"
    assert sensor.log_prefix == "[TestPrefix]"
    assert sensor.device_info == {"identifiers": {("climate_ip", "test_unique_id")}}
    assert sensor.available is True

    # State 1: last_update_success = True -> is_on = True
    assert sensor.is_on is True

    # State 2: last_update_success = False -> is_on = False
    coord.last_update_success = False
    assert sensor.is_on is False

    # State 3: last_update_success = None -> is_on = False
    coord.last_update_success = None
    assert sensor.is_on is False

    # Edge Case: Coordinator without unique_id falls back to DOMAIN
    coord_fallback = _create_mock_coordinator(unique_id=None)
    sensor_fallback = ClimateIPConnectivitySensor(coord_fallback, desc)
    assert sensor_fallback.unique_id == f"{DOMAIN}_connectivity"
