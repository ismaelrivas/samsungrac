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
    
    mock_coord.get_property = MagicMock(return_value=None)
    
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
    """Aniquila mutantes en __init__ y @property.
    Asegura los valores base correctos, incluyendo identificadores únicos y nombres.
    """
    assert base_sensor_entity._attr_has_entity_name is True
    assert base_sensor_entity._attr_native_value is None
    assert base_sensor_entity._attr_unique_id == "test_mac_123_target_temp"
    assert base_sensor_entity.translation_key == "target_temp"
    assert base_sensor_entity.log_prefix == "[SENSOR_TEST]"
    
    # Aserción de diccionario estricta (no tautológica)
    assert base_sensor_entity.device_info == {"identifiers": {("climate_ip", "test_mac_123")}}


def test_handle_coordinator_update_valid(base_sensor_entity: ClimateIpSensor) -> None:
    """Aniquila mutaciones en _handle_coordinator_update (Rama True)."""
    # Configuramos el estado para que sea válido y devuelva un número
    base_sensor_entity.coordinator.get_property.return_value = "25.5"
    base_sensor_entity._property.is_valid.return_value = True
    
    base_sensor_entity._handle_coordinator_update()
    
    assert base_sensor_entity.native_value == 25.5
    base_sensor_entity.async_write_ha_state.assert_called_once()


def test_handle_coordinator_update_invalid(base_sensor_entity: ClimateIpSensor) -> None:
    """Aniquila mutaciones en _handle_coordinator_update (Rama False).
    Si is_valid es False, debe forzar a None independientemente del valor real.
    """
    # Aunque el coordinador tenga un valor, el sensor es "inválido"
    base_sensor_entity.coordinator.get_property.return_value = "25.5"
    base_sensor_entity._property.is_valid.return_value = False
    
    base_sensor_entity._attr_native_value = 99.0 # Valor previo
    
    base_sensor_entity._handle_coordinator_update()
    
    assert base_sensor_entity.native_value is None
    base_sensor_entity.async_write_ha_state.assert_called_once()


def test_update_state_none_or_unknown(base_sensor_entity: ClimateIpSensor) -> None:
    """Aniquila mutaciones en _update_state (condicional de guardias).
    Prueba explícitamente los límites de None y STATE_UNKNOWN.
    """
    # Frontera 1: None
    base_sensor_entity.coordinator.get_property.return_value = None
    base_sensor_entity._attr_native_value = 10.0
    base_sensor_entity._update_state()
    assert base_sensor_entity._attr_native_value is None
    
    # Frontera 2: STATE_UNKNOWN
    base_sensor_entity.coordinator.get_property.return_value = STATE_UNKNOWN
    base_sensor_entity._attr_native_value = 10.0
    base_sensor_entity._update_state()
    assert base_sensor_entity._attr_native_value is None


def test_update_state_string_property(base_sensor_entity: ClimateIpSensor) -> None:
    """Aniquila mutaciones en getattr(self._property, 'value_is_string')."""
    base_sensor_entity.coordinator.get_property.return_value = "auto_mode"
    base_sensor_entity._property.value_is_string = True
    
    base_sensor_entity._update_state()
    
    # Si mutmut cambia is_str a False, intentará castear "auto_mode" a float, fallará
    # y devolverá None. Esta aserción mata a ese mutante.
    assert base_sensor_entity.native_value == "auto_mode"


def test_update_state_unique_id_property(base_sensor_entity: ClimateIpSensor) -> None:
    """Aniquila mutaciones en isinstance(self._property, UniqueIdProperty)."""
    # Forzamos la clase para que pase el isinstance
    base_sensor_entity._property.__class__ = UniqueIdProperty
    base_sensor_entity._property.value_is_string = False # Forzamos a que dependa del isinstance
    
    base_sensor_entity.coordinator.get_property.return_value = "00:11:22:33:AA:BB"
    
    base_sensor_entity._update_state()
    assert base_sensor_entity.native_value == "00:11:22:33:AA:BB"


def test_update_state_float_parsing_failure(base_sensor_entity: ClimateIpSensor) -> None:
    """Aniquila mutantes en el bloque try/except de float()."""
    # Al no ser string ni UniqueIdProperty, intentará castear a float
    base_sensor_entity._property.value_is_string = False
    
    # Inyectamos una cadena corrupta que detonará ValueError
    base_sensor_entity.coordinator.get_property.return_value = "not_a_number"
    base_sensor_entity._attr_native_value = 50.0
    
    base_sensor_entity._update_state()
    
    # El except debe capturarlo y setear a None
    assert base_sensor_entity.native_value is None


# ============================================================
# PHASE 2: Factory / async_setup_entry
# ============================================================

@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
async def test_async_setup_entry_dict_and_filters(mock_sensor_class) -> None:
    """Aniquila mutantes en la iteración, diccionarios y extracción de atributos (paths Multi-device)."""
    hass = MagicMock()
    entry = MagicMock()
    
    # Simulador de Coordinador
    mock_coord = MagicMock()
    
    # Propiedad 1: Válida, con icono y device_class
    prop_valid = MagicMock()
    prop_valid.id = "sensor_1"
    prop_valid.is_valid.return_value = True
    prop_valid.entity_category = "diagnostic"
    prop_valid.device_class = "temperature"
    prop_valid.icon = "mdi:thermometer"
    prop_valid.unit_of_measurement = "°C"
    prop_valid.state_class = "measurement"

    # Propiedad 2: Inválida (debe ser ignorada por completo)
    prop_invalid = MagicMock()
    prop_invalid.is_valid.return_value = False

    # Propiedad 3: Válida, PERO sin icono ni device class (Dispara fallback 'mdi:eye')
    prop_fallback = MagicMock()
    prop_fallback.id = "sensor_3"
    prop_fallback.is_valid.return_value = True
    prop_fallback.entity_category = None
    prop_fallback.device_class = None
    prop_fallback.icon = None

    mock_coord.controller.sensors = [prop_valid, prop_invalid, prop_fallback]
    entry.runtime_data = {"dev_1": mock_coord} # Diccionario

    async_add_entities = MagicMock()

    # Ejecución
    with patch("custom_components.climate_ip.sensor.parse_entity_category", return_value="diagnostic"):
        await async_setup_entry(hass, entry, async_add_entities)

    # Aserciones Letales: Solo 2 sensores deben haberse instanciado (prop_invalid se ignora)
    assert mock_sensor_class.call_count == 2
    
    # Extracción de llamadas reales a la clase ClimateIpSensor
    call_1_args = mock_sensor_class.call_args_list[0].args
    call_2_args = mock_sensor_class.call_args_list[1].args

    # Validaciones del Sensor 1
    c1_coord, c1_desc, c1_prop = call_1_args
    assert c1_coord == mock_coord
    assert c1_prop == prop_valid
    assert c1_desc.key == "sensor_1"
    assert c1_desc.translation_key == "sensor_1"
    assert c1_desc.device_class == "temperature"
    assert c1_desc.icon == "mdi:thermometer"
    assert c1_desc.native_unit_of_measurement == "°C"
    assert c1_desc.state_class == "measurement"
    assert c1_desc.name is None

    # Validaciones del Sensor 3 (Fallback mutantes: 'if not icon and not device_class')
    _, c2_desc, _ = call_2_args
    assert c2_desc.key == "sensor_3"
    assert c2_desc.icon == "mdi:eye", "El fallback del icono mdi:eye falló o el operador lógico fue mutado"
    assert c2_desc.device_class is None

    # Verificación de inyección
    async_add_entities.assert_called_once()
    assert len(async_add_entities.call_args[0][0]) == 2


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
async def test_async_setup_entry_single_coordinator(mock_sensor_class) -> None:
    """Aniquila mutantes en la estructura `if isinstance(coordinator_data, dict)`."""
    hass = MagicMock()
    entry = MagicMock()
    
    # Inyectamos el objeto directo en lugar de un diccionario
    mock_coord = MagicMock()
    mock_coord.controller.sensors = [] # Lista vacía, no creará entidades
    
    entry.runtime_data = mock_coord
    
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)
    
    # Al pasar una lista vacía de sensores, comprueba la guarda `if entities_to_add:`
    assert mock_sensor_class.call_count == 0
    async_add_entities.assert_not_called()
