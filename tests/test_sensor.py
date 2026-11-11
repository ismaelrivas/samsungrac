# pylint: disable=protected-access,redefined-outer-name,unused-import,reimported,wrong-import-order,missing-function-docstring
"""Tests for the ClimateIP sensor platform and entity."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.entity import SamsungClimateEntity
from custom_components.climate_ip.properties import UniqueIdProperty
from custom_components.climate_ip.sensor import ClimateIpSensor, async_setup_entry
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import STATE_UNKNOWN


class DummyProperty:
    """Helper property class for deterministic attribute access in unit tests."""

    def __init__(
        self,
        prop_id: str = "target_temp",
        is_valid: bool = True,
        name: str | None = None,
        device_class: str | None = None,
        icon: str | None = None,
        unit: str | None = None,
        state_class: str | None = None,
        category: str | None = None,
        value_is_string: bool = False,
    ) -> None:
        self.id = prop_id
        self._valid = is_valid
        self.name = name
        self.device_class = device_class
        self.icon = icon
        self.unit_of_measurement = unit
        self.state_class = state_class
        self.entity_category = category
        self.value_is_string = value_is_string

    def is_valid(self, _state) -> bool:
        return self._valid


@pytest.fixture
def base_sensor_entity() -> ClimateIpSensor:
    """Fixture providing an isolated ClimateIpSensor instance."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_mac_123"
    mock_coord.log_prefix = "[SENSOR_TEST]"
    mock_coord.device_info = {"identifiers": {("climate_ip", "test_mac_123")}}
    mock_coord.controller = MagicMock()
    mock_coord.controller.device_state = {"temp": 22.5}
    mock_coord.controller.get_property.return_value = 22.5

    prop = DummyProperty(prop_id="target_temp", is_valid=True)

    desc = SensorEntityDescription(
        key="target_temp",
        translation_key="target_temp",
        device_class=None,
        icon="mdi:thermometer",
    )

    with patch.object(ClimateIpSensor, "_sync_data_from_coordinator"):
        sensor = ClimateIpSensor(
            coordinator=mock_coord, description=desc, property_object=prop
        )
    sensor.hass = MagicMock()
    sensor.async_write_ha_state = MagicMock()
    return sensor


# ============================================================
# PHASE 1: Entity Behavior & State Parsing
# ============================================================


def test_sensor_initialization(base_sensor_entity: ClimateIpSensor) -> None:
    """Verify entity initialization attributes and naming flag."""
    assert base_sensor_entity._attr_has_entity_name is True
    assert base_sensor_entity._attr_native_value is None
    assert base_sensor_entity._attr_unique_id == "test_mac_123_target_temp"
    assert base_sensor_entity.device_info == {
        "identifiers": {("climate_ip", "test_mac_123")}
    }
    assert base_sensor_entity.log_prefix == "[SENSOR_TEST]"
    assert base_sensor_entity.entity_description.key == "target_temp"


def test_sensor_sync_data_on_init() -> None:
    """Verify unpatched initialization synchronizes data from the coordinator."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_mac_123"
    mock_coord.log_prefix = "[SENSOR_TEST]"
    mock_coord.device_info = {"identifiers": {("climate_ip", "test_mac_123")}}
    mock_coord.controller = MagicMock()
    mock_coord.controller.device_state = {}
    mock_coord.controller.get_property.return_value = "21.5"

    prop = DummyProperty(prop_id="temp", is_valid=True)
    desc = SensorEntityDescription(key="temp")

    sensor = ClimateIpSensor(mock_coord, desc, prop)
    assert sensor.native_value == 21.5


def test_update_state_none_value(base_sensor_entity: ClimateIpSensor) -> None:
    """Verify None value resets native value without error."""
    base_sensor_entity.coordinator.controller.get_property.return_value = None
    base_sensor_entity._attr_native_value = 10.0

    base_sensor_entity._update_state()
    assert base_sensor_entity._attr_native_value is None
    base_sensor_entity.coordinator.controller.get_property.assert_called_with(
        "target_temp"
    )


@patch("custom_components.climate_ip.sensor._LOGGER.warning")
def test_update_state_unknown_value(
    mock_logger_warning: MagicMock, base_sensor_entity: ClimateIpSensor
) -> None:
    """Verify STATE_UNKNOWN resets native value and bypasses float conversion."""
    base_sensor_entity.coordinator.controller.get_property.return_value = STATE_UNKNOWN
    base_sensor_entity._attr_native_value = 10.0

    base_sensor_entity._update_state()
    assert base_sensor_entity._attr_native_value is None
    mock_logger_warning.assert_not_called()


def test_update_state_unique_id_property(base_sensor_entity: ClimateIpSensor) -> None:
    """Verify UniqueIdProperty casts raw value to string without float conversion."""
    prop = DummyProperty(prop_id="mac", is_valid=True)
    prop.__class__ = UniqueIdProperty
    base_sensor_entity._property = prop
    base_sensor_entity.coordinator.controller.get_property.return_value = 12345

    base_sensor_entity._update_state()
    assert base_sensor_entity.native_value == "12345"
    assert isinstance(base_sensor_entity.native_value, str)


def test_update_state_string_property(base_sensor_entity: ClimateIpSensor) -> None:
    """Verify value_is_string casts raw value to string without float conversion."""
    base_sensor_entity._property.value_is_string = True
    base_sensor_entity.coordinator.controller.get_property.return_value = "auto_mode"

    base_sensor_entity._update_state()
    assert base_sensor_entity.native_value == "auto_mode"
    assert isinstance(base_sensor_entity.native_value, str)


def test_update_state_valid_float(base_sensor_entity: ClimateIpSensor) -> None:
    """Verify numeric string is parsed as float."""
    base_sensor_entity.coordinator.controller.get_property.return_value = "23.7"
    base_sensor_entity._property.value_is_string = False

    base_sensor_entity._update_state()
    assert base_sensor_entity._attr_native_value == 23.7
    assert isinstance(base_sensor_entity._attr_native_value, float)


@patch("custom_components.climate_ip.sensor._LOGGER.warning")
def test_update_state_float_parsing_failure(
    mock_logger_warning: MagicMock, base_sensor_entity: ClimateIpSensor
) -> None:
    """Verify both ValueError and TypeError in float conversion reset value to None and log warning."""
    base_sensor_entity._property.value_is_string = False

    # Test ValueError
    base_sensor_entity.coordinator.controller.get_property.return_value = "not_a_number"
    base_sensor_entity._attr_native_value = 50.0
    base_sensor_entity._update_state()
    assert base_sensor_entity._attr_native_value is None

    # Test TypeError
    base_sensor_entity.coordinator.controller.get_property.return_value = [
        "invalid_type"
    ]
    base_sensor_entity._attr_native_value = 50.0
    base_sensor_entity._update_state()
    assert base_sensor_entity._attr_native_value is None

    assert mock_logger_warning.call_count == 2


def test_sensor_handle_coordinator_update_valid(
    base_sensor_entity: ClimateIpSensor,
) -> None:
    """Verify valid update triggers _update_state and async_write_ha_state."""
    target_state = {"temp": 25.0}
    base_sensor_entity.coordinator.controller.device_state = target_state
    base_sensor_entity.coordinator.controller.get_property.return_value = "25.0"
    mock_prop = MagicMock(spec=DummyProperty)
    mock_prop.id = "target_temp"
    mock_prop.is_valid.return_value = True
    mock_prop.value_is_string = False
    base_sensor_entity._property = mock_prop

    with patch.object(base_sensor_entity, "async_write_ha_state") as mock_write:
        base_sensor_entity._handle_coordinator_update()
        assert base_sensor_entity.native_value == 25.0
        mock_write.assert_called_once()
        mock_prop.is_valid.assert_called_once_with(target_state)


@patch("custom_components.climate_ip.sensor._LOGGER.debug")
def test_sensor_handle_coordinator_update_invalid(
    mock_logger_debug: MagicMock, base_sensor_entity: ClimateIpSensor
) -> None:
    """Verify invalid state resets native value to None and writes state."""
    base_sensor_entity._property = DummyProperty(prop_id="target_temp", is_valid=False)
    base_sensor_entity._attr_native_value = 25.0

    with patch.object(base_sensor_entity, "async_write_ha_state") as mock_write:
        base_sensor_entity._handle_coordinator_update()
        assert base_sensor_entity._attr_native_value is None
        mock_write.assert_called_once()
        mock_logger_debug.assert_called_once()


# ============================================================
# PHASE 2: Factory / async_setup_entry
# ============================================================


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
@patch("custom_components.climate_ip.sensor.SensorEntityDescription")
@patch("custom_components.climate_ip.sensor.parse_entity_category")
async def test_async_setup_entry_strict_mapping(
    mock_parse_category: MagicMock,
    mock_desc_class: MagicMock,
    mock_sensor_class: MagicMock,
) -> None:
    """Verify mapping of sensor properties into SensorEntityDescription kwargs."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    target_state = {"temp": 22}
    mock_coord.controller.device_state = target_state

    prop = DummyProperty(
        prop_id="sensor_valid",
        is_valid=True,
        category="diagnostic",
        device_class="temperature",
        icon="mdi:thermometer",
        unit="°C",
        state_class="measurement",
    )
    mock_coord.controller.sensors = [prop]
    entry.runtime_data = {"dev_1": mock_coord}

    mock_parse_category.return_value = "parsed_diagnostic"
    mock_desc_class.return_value = "sentinel_desc"
    mock_sensor_class.return_value = "sentinel_sensor"
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    mock_parse_category.assert_called_once_with("diagnostic")
    mock_desc_class.assert_called_once_with(
        key="sensor_valid",
        translation_key="sensor_valid",
        name=None,
        device_class="temperature",
        native_unit_of_measurement="°C",
        state_class="measurement",
        entity_category="parsed_diagnostic",
        icon="mdi:thermometer",
    )
    mock_sensor_class.assert_called_once_with(mock_coord, "sentinel_desc", prop)
    async_add_entities.assert_called_once_with(["sentinel_sensor"])


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.SensorEntityDescription")
@patch("custom_components.climate_ip.sensor.parse_entity_category")
async def test_async_setup_entry_fallback_icon(
    mock_parse_category: MagicMock, mock_desc_class: MagicMock
) -> None:
    """Verify fallback icon 'mdi:eye' when neither icon nor device_class is provided."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    mock_coord.controller.device_state = {}
    mock_coord.controller.sensors = [
        DummyProperty(
            prop_id="sensor_fallback", is_valid=True, icon=None, device_class=None
        )
    ]
    entry.runtime_data = {"dev_1": mock_coord}
    mock_parse_category.return_value = None
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    mock_desc_class.assert_called_once_with(
        key="sensor_fallback",
        translation_key="sensor_fallback",
        name=None,
        device_class=None,
        native_unit_of_measurement=None,
        state_class=None,
        entity_category=None,
        icon="mdi:eye",
    )


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.SensorEntityDescription")
@patch("custom_components.climate_ip.sensor.parse_entity_category")
async def test_async_setup_entry_device_class_no_fallback_icon(
    mock_parse_category: MagicMock, mock_desc_class: MagicMock
) -> None:
    """Verify that having device_class prevents fallback to 'mdi:eye' even if icon is None."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    mock_coord.controller.device_state = {}
    mock_coord.controller.sensors = [
        DummyProperty(
            prop_id="sensor_dc",
            is_valid=True,
            icon=None,
            device_class="temperature",
        )
    ]
    entry.runtime_data = {"dev_1": mock_coord}
    mock_parse_category.return_value = None
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    assert mock_desc_class.call_args.kwargs["icon"] is None


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
async def test_async_setup_entry_single_coordinator(
    mock_sensor_class: MagicMock,
) -> None:
    """Verify single coordinator in runtime_data (non-dict) unpacks and registers correctly."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    prop = DummyProperty(prop_id="temp", is_valid=True)
    mock_coord.controller.device_state = {}
    mock_coord.controller.sensors = [prop]
    entry.runtime_data = mock_coord
    mock_sensor_class.return_value = "sensor_instance"
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    assert mock_sensor_class.call_count == 1
    async_add_entities.assert_called_once_with(["sensor_instance"])


@pytest.mark.asyncio
async def test_async_setup_entry_custom_yaml_name() -> None:
    """Verify YAML custom name is propagated to SensorEntityDescription."""
    entry = MagicMock()
    mock_coord = MagicMock()

    prop = DummyProperty(prop_id="test_sensor", is_valid=True, name="Custom Name")
    mock_coord.controller.device_state = {}
    mock_coord.controller.sensors = [prop]
    mock_coord.unique_id = "test_mac"
    entry.runtime_data = {"test_mac": mock_coord}

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    assert len(added_entities) == 1
    assert added_entities[0].entity_description.name == "Custom Name"


@pytest.mark.asyncio
async def test_async_setup_entry_no_valid_sensors() -> None:
    """Verify async_add_entities is not called when no sensors are valid."""
    entry = MagicMock()
    mock_coord = MagicMock()

    prop = DummyProperty(prop_id="invalid_prop", is_valid=False)
    mock_coord.controller.device_state = {}
    mock_coord.controller.sensors = [prop]
    entry.runtime_data = {"test_mac": mock_coord}

    mock_add_entities = MagicMock()
    await async_setup_entry(MagicMock(), entry, mock_add_entities)

    mock_add_entities.assert_not_called()


def test_samsung_climate_base_entity_properties() -> None:
    """Verify base SamsungClimateEntity attributes delegation."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.log_prefix = "[BASE_TEST]"
    mock_coord.device_info = {"identifiers": {("climate_ip", "123")}}

    base_ent = SamsungClimateEntity(mock_coord)
    assert base_ent.has_entity_name is True
    assert base_ent.log_prefix == "[BASE_TEST]"
    assert base_ent.device_info == {"identifiers": {("climate_ip", "123")}}
