# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ClimateIpSensor entity."""
# pylint: disable=import-outside-toplevel,redefined-outer-name
from unittest.mock import MagicMock

from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.sensor import ClimateIpSensor
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import EntityCategory


def test_sensor_translation_key_and_entity_category() -> None:
    """Test that Sensor objects correctly map translation_key and entity_category."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_unique_id"
    mock_coordinator.device_info = {"identifiers": {("climate_ip", "test_unique_id")}}

    mock_prop = MagicMock()
    mock_prop.id = "test_sensor_id"
    mock_prop.value = "20"

    description = SensorEntityDescription(
        key="test_sensor_id",
        translation_key="test_sensor_id",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:eye",
    )

    sensor = ClimateIpSensor(
        coordinator=mock_coordinator, description=description, property_object=mock_prop
    )

    # Test Translation Key
    assert sensor.translation_key == "test_sensor_id"

    # Test Entity Category
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC

    # Test Device Info matches Coordinator (Parent linkage)
    assert sensor.device_info == {"identifiers": {("climate_ip", "test_unique_id")}}
