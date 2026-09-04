"""Unit tests for Climate IP diagnostic binary_sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
import pytest

from custom_components.climate_ip.binary_sensor import (
    ClimateIPConnectivitySensor,
    async_setup_entry,
)

# --- FIXTURES ---


@pytest.fixture
def mock_hass():
    """Fixture for HomeAssistant instance."""
    return MagicMock()


@pytest.fixture
def mock_async_add_entities():
    """Fixture for the async_add_entities callback."""
    return MagicMock()


@pytest.fixture
def mock_coordinator():
    """Fixture for a standard SamsungClimateCoordinator."""
    coord = MagicMock()
    coord.unique_id = "test_unique_id"
    coord.log_prefix = "[TestPrefix]"
    coord.device_info = {"identifiers": {("climate_ip", "test_unique_id")}}
    return coord


@pytest.fixture
def mock_config_entry(mock_coordinator):
    """Fixture for the ConfigEntry containing the coordinator."""
    entry = MagicMock()
    entry.runtime_data = mock_coordinator
    return entry


@pytest.fixture
def mock_logger():
    """Fixture to patch the module logger."""
    with patch("custom_components.climate_ip.binary_sensor._LOGGER.debug") as mock_log:
        yield mock_log


# --- TESTS ---


@pytest.mark.asyncio
async def test_async_setup_entry_single_coordinator(
    mock_hass, mock_config_entry, mock_async_add_entities, mock_logger
):
    """Test async_setup_entry with a single coordinator instance and strict description assertions."""
    await async_setup_entry(mock_hass, mock_config_entry, mock_async_add_entities)

    mock_async_add_entities.assert_called_once()
    added_entities = mock_async_add_entities.call_args[0][0]

    assert len(added_entities) == 1
    entity = added_entities[0]
    assert isinstance(entity, ClimateIPConnectivitySensor)

    # Target 1: Strict Entity Description & Attribute Assertions
    assert entity.entity_description.key == "connectivity"
    assert entity.entity_description.translation_key == "connectivity"
    assert (
        entity.entity_description.device_class == BinarySensorDeviceClass.CONNECTIVITY
    )
    assert entity.entity_description.entity_category == EntityCategory.DIAGNOSTIC
    assert entity._attr_has_entity_name is True
    assert entity.unique_id == "test_unique_id_connectivity"

    # Target 2: Logger Assertion
    mock_logger.assert_called_once_with(
        "%s Adding diagnostic connectivity binary sensors to Home Assistant.",
        "[TestPrefix]",
    )


@pytest.mark.asyncio
async def test_async_setup_entry_dict_coordinators(
    mock_hass, mock_config_entry, mock_async_add_entities, mock_logger
):
    """Test async_setup_entry with a dict of multi-device coordinators."""
    mock_c1 = MagicMock(unique_id="dev1", log_prefix="[Dev1]")
    mock_c2 = MagicMock(unique_id="dev2", log_prefix="[Dev2]")
    mock_config_entry.runtime_data = {"dev1": mock_c1, "dev2": mock_c2}

    await async_setup_entry(mock_hass, mock_config_entry, mock_async_add_entities)

    added_entities = mock_async_add_entities.call_args[0][0]
    assert len(added_entities) == 2
    assert added_entities[0].unique_id == "dev1_connectivity"
    assert added_entities[1].unique_id == "dev2_connectivity"

    mock_logger.assert_called_once_with(
        "%s Adding diagnostic connectivity binary sensors to Home Assistant.",
        "[Dev1]",
    )


@pytest.mark.asyncio
async def test_async_setup_entry_empty_entities(
    mock_hass, mock_config_entry, mock_async_add_entities, mock_logger
):
    """Test async_setup_entry when no coordinators are provided."""
    mock_config_entry.runtime_data = []

    await async_setup_entry(mock_hass, mock_config_entry, mock_async_add_entities)

    mock_async_add_entities.assert_not_called()
    mock_logger.assert_not_called()


def test_connectivity_sensor_attributes_and_is_on_states(mock_coordinator):
    """Test sensor metadata, availability, and is_on state reflecting coordinator success/failure."""
    mock_description = MagicMock(
        key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    sensor = ClimateIPConnectivitySensor(mock_coordinator, mock_description)

    assert sensor.unique_id == "test_unique_id_connectivity"
    assert sensor.log_prefix == "[TestPrefix]"
    assert sensor.device_info == {"identifiers": {("climate_ip", "test_unique_id")}}

    # In CoordinatorEntity, if coordinator exists, available inherits from last_update_success
    # unless overridden. We assume strict behavior.
    assert getattr(sensor, "available", True) is True

    # State 1: Coordinator last_update_success = True -> is_on = True (Connected)
    mock_coordinator.last_update_success = True
    assert sensor.is_on is True

    # State 2: Coordinator last_update_success = False -> is_on = False (Disconnected)
    mock_coordinator.last_update_success = False
    assert sensor.is_on is False

    # State 3: Coordinator last_update_success = None -> is_on = False
    mock_coordinator.last_update_success = None
    assert sensor.is_on is False
