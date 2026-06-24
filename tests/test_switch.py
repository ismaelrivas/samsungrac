# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for SamsungClimateSwitch entity."""
# pylint: disable=import-outside-toplevel,redefined-outer-name
from unittest.mock import MagicMock

from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.switch import SamsungClimateSwitch
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import EntityCategory


def test_switch_translation_key_and_entity_category() -> None:
    """Test that Switch objects correctly map translation_key and entity_category."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_unique_id"
    mock_coordinator.device_info = {"identifiers": {("climate_ip", "test_unique_id")}}
    mock_coordinator.controller = MagicMock()

    mock_prop = MagicMock()
    mock_prop.id = "test_switch_id"

    description = SwitchEntityDescription(
        key="test_switch_id",
        translation_key="test_switch_id",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:toggle-switch",
    )

    switch = SamsungClimateSwitch(
        coordinator=mock_coordinator, description=description, operation=mock_prop
    )

    # Test Translation Key
    assert switch.translation_key == "test_switch_id"

    # Test Entity Category
    assert switch.entity_category == EntityCategory.CONFIG

    # Test Device Info matches Coordinator (Parent linkage)
    assert switch.device_info == {"identifiers": {("climate_ip", "test_unique_id")}}
