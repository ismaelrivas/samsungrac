"""Tests for the ClimateIP sensor entity."""
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from custom_components.climate_ip.sensor import async_setup_entry, ClimateIpSensor
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.properties import DeviceProperty, UniqueIdProperty


@pytest.fixture
def base_sensor_entity(hass: HomeAssistant) -> ClimateIpSensor:
    """Fixture base con coordinador y propiedad mockeados para aserciones DRY."""
    mock_coord = MagicMock(spec=SamsungClimateCoordinator)
    mock_coord.unique_id = "test_mac_123"
    mock_coord.log_prefix = "[SENSOR_TEST]"
    mock_coord.device_info = {"identifiers": {("climate_ip", "test_mac_123")}}
    mock_coord.controller = MagicMock()
    mock_coord.controller.device_state = {"temp": 22.5}
    
    mock_prop = MagicMock(spec=DeviceProperty)
    mock_prop.id = "target_temp"
    mock_prop.is_valid.return_value = True
    
    desc = SensorEntityDescription(
        key="target_temp",
        translation_key="target_temp",
        device_class=None,
        icon="mdi:thermometer",
    )
    
    # Prevenimos que __init__ llame a _sync_data para aislar las pruebas de estado inicial
    with patch.object(ClimateIpSensor, "_sync_data_from_coordinator"):
        sensor = ClimateIpSensor(
            coordinator=mock_coord, description=desc, property_object=mock_prop
        )
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    return sensor


# ============================================================
# PHASE 1: Entity Behavior & State Parsing
# ============================================================

def test_sensor_initialization(base_sensor_entity: ClimateIpSensor) -> None:
    """
    Aniquila mutante 6 en __init__.
    Al estar parcheado _sync_data_from_coordinator, podemos asertar 
    el valor literal exacto asignado en el constructor.
    """
    assert base_sensor_entity._attr_has_entity_name is True
    assert base_sensor_entity._attr_native_value is None, "Mutant 6: _attr_native_value must be exactly None, not ''"
    assert base_sensor_entity._attr_unique_id == "test_mac_123_target_temp"
    assert base_sensor_entity.device_info == {"identifiers": {("climate_ip", "test_mac_123")}}


def test_update_state_strict_get_property_call(base_sensor_entity: ClimateIpSensor) -> None:
    """
    Aniquila mutante 2.
    Asegura que get_property reciba exactamente description.key.
    """
    base_sensor_entity._update_state()
    base_sensor_entity.coordinator.get_property.assert_called_once_with("target_temp")


@patch("custom_components.climate_ip.sensor._LOGGER.warning")
def test_update_state_unknown_no_exception_path(mock_logger_warning, base_sensor_entity: ClimateIpSensor) -> None:
    """
    Aniquila mutante 3 (cambio de `or` por `and` en validación de STATE_UNKNOWN).
    Si el mutante vive, la ejecución pasará a intentar hacer float(STATE_UNKNOWN),
    detonando un ValueError interno y llamando al logger.
    """
    base_sensor_entity.coordinator.get_property.return_value = STATE_UNKNOWN
    base_sensor_entity._update_state()
    
    assert base_sensor_entity._attr_native_value is None
    # Si el operador lógico fue mutado, la ejecución cae al except y el logger dispara.
    mock_logger_warning.assert_not_called()


def test_update_state_string_property(base_sensor_entity: ClimateIpSensor) -> None:
    """Verifica asignación de cadenas literales sin parseo matemático."""
    base_sensor_entity.coordinator.get_property.return_value = "auto_mode"
    base_sensor_entity._property.value_is_string = True
    
    base_sensor_entity._update_state()
    assert base_sensor_entity.native_value == "auto_mode"


def test_update_state_unique_id_property(base_sensor_entity: ClimateIpSensor) -> None:
    """Verifica bypass de parseo para propiedades de UniqueId."""
    base_sensor_entity._property.__class__ = UniqueIdProperty
    base_sensor_entity._property.value_is_string = False
    base_sensor_entity.coordinator.get_property.return_value = "00:11:22:33:AA:BB"
    
    base_sensor_entity._update_state()
    assert base_sensor_entity.native_value == "00:11:22:33:AA:BB"


# ============================================================
# PHASE 2: Factory / async_setup_entry
# ============================================================

@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
async def test_async_setup_entry_dict_and_filters(mock_sensor_class) -> None:
    """
    Aniquila mutantes 5 y 6 (aserciones estructurales de is_valid).
    """
    hass = MagicMock()
    entry = MagicMock()
    
    mock_coord = MagicMock()
    # Inyectamos un objeto de estado identificable
    target_device_state = {"power": "on", "temp": 22}
    mock_coord.controller.device_state = target_device_state
    
    prop_valid = MagicMock()
    prop_valid.id = "sensor_1"
    prop_valid.is_valid.return_value = True
    
    mock_coord.controller.sensors = [prop_valid]
    entry.runtime_data = {"dev_1": mock_coord}

    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    # Mutantes 5 y 6 mueren aquí: exigimos que is_valid reciba EXACTAMENTE el raw_device_state
    prop_valid.is_valid.assert_called_once_with(target_device_state)


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
@patch("custom_components.climate_ip.sensor.parse_entity_category")
async def test_async_setup_entry_getattr_fallbacks(mock_parse_category, mock_sensor_class) -> None:
    """
    Aniquila mutantes 7, 8, 9, 13, 14, 15, 21, 29, 44, 52, 58, 65.
    Evalúa matemáticamente que los fallbacks de los atributos opcionales funcionen,
    forzando AttributeError si mutmut elimina el tercer parámetro de getattr.
    """
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()
    
    # Creamos una propiedad "desnuda", sin NINGUNO de los atributos opcionales.
    # Si getattr mutó a no tener valor default, lanzará AttributeError y morirá.
    class BareProperty:
        id = "bare_sensor"
        def is_valid(self, state):
            return True

    prop_bare = BareProperty()
    mock_coord.controller.sensors = [prop_bare]
    entry.runtime_data = {"dev_1": mock_coord}
    async_add_entities = MagicMock()

    mock_parse_category.return_value = None

    await async_setup_entry(hass, entry, async_add_entities)

    # Verificamos que parse_entity_category fue llamado exactamente con None (Mutantes 8, 9, 14, 15)
    mock_parse_category.assert_called_once_with(None)

    # Verificamos que el empaquetado del SensorEntityDescription fue perfecto
    assert mock_sensor_class.call_count == 1
    _, c_desc, _ = mock_sensor_class.call_args.args

    assert c_desc.key == "bare_sensor"
    assert c_desc.device_class is None
    assert c_desc.native_unit_of_measurement is None
    assert c_desc.state_class is None
    assert c_desc.entity_category is None  # Mutantes 44, 52
    assert c_desc.icon == "mdi:eye"  # Fallback final


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
async def test_async_setup_entry_icon_logical_operator(mock_sensor_class) -> None:
    """
    Aniquila mutante 32 (cambio de 'and' por 'or' en la asignación del icono mdi:eye).
    """
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()
    
    # Configuración de asedio: Tiene icono, pero NO tiene device_class.
    prop_test = MagicMock()
    prop_test.id = "sensor_logic"
    prop_test.is_valid.return_value = True
    prop_test.icon = "mdi:thermometer"
    prop_test.device_class = None
    
    mock_coord.controller.sensors = [prop_test]
    entry.runtime_data = {"dev_1": mock_coord}
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    _, c_desc, _ = mock_sensor_class.call_args.args
    
    # Si el mutante `if not icon or not device_class:` sobreviviera, 
    # c_desc.icon habría sido sobrescrito con "mdi:eye".
    assert c_desc.icon == "mdi:thermometer", "Logical operator in icon fallback was mutated."


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
async def test_async_setup_entry_single_coordinator(mock_sensor_class) -> None:
    """Aniquila mutantes en el desempaquetado de coordinador singular."""
    hass = MagicMock()
    entry = MagicMock()
    
    mock_coord = MagicMock()
    mock_coord.controller.sensors = [] 
    
    entry.runtime_data = mock_coord
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)
    
    assert mock_sensor_class.call_count == 0
    async_add_entities.assert_not_called()
