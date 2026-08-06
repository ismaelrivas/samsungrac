"""Tests for the ClimateIP sensor entity."""

from unittest.mock import MagicMock, patch
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

    # Prevent que __init__ llame a _sync_data para aislar las pruebas de estado inicial
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
    Verify mutant kill 6 en __init__.
    Al estar parcheado _sync_data_from_coordinator, podemos asertar
    el valor literal exacto asignado en el constructor.
    """
    assert base_sensor_entity._attr_has_entity_name is True
    assert base_sensor_entity._attr_native_value is None, (
        "Mutant 6: _attr_native_value must be exactly None, not ''"
    )
    assert base_sensor_entity._attr_unique_id == "test_mac_123_target_temp"
    assert base_sensor_entity.device_info == {
        "identifiers": {("climate_ip", "test_mac_123")}
    }


def test_update_state_strict_get_property_call(
    base_sensor_entity: ClimateIpSensor,
) -> None:
    """
    Verify mutant kill 2.
    Asegura que get_property reciba exactamente description.key.
    """
    base_sensor_entity._update_state()
    base_sensor_entity.coordinator.controller.get_property.assert_called_once_with("target_temp")


@patch("custom_components.climate_ip.sensor._LOGGER.warning")
def test_update_state_unknown_no_exception_path(
    mock_logger_warning, base_sensor_entity: ClimateIpSensor
) -> None:
    """
    Verify mutant kill 3 (cambio de `or` por `and` en validación de STATE_UNKNOWN).
    If mutant vive, la ejecución pasará a intentar hacer float(STATE_UNKNOWN),
    detonando un ValueError interno y llamando al logger.
    """
    base_sensor_entity.coordinator.controller.get_property.return_value = STATE_UNKNOWN
    base_sensor_entity._update_state()

    assert base_sensor_entity._attr_native_value is None
    # Si el operador lógico fue mutado, la ejecución cae al except y el logger dispara.
    mock_logger_warning.assert_not_called()


def test_update_state_string_property(base_sensor_entity: ClimateIpSensor) -> None:
    """Verifica asignación de cadenas literales sin parseo matemático."""
    base_sensor_entity.coordinator.controller.get_property.return_value = "auto_mode"
    base_sensor_entity._property.value_is_string = True

    base_sensor_entity._update_state()
    assert base_sensor_entity.native_value == "auto_mode"


def test_update_state_unique_id_property(base_sensor_entity: ClimateIpSensor) -> None:
    """Verifica bypass de parseo para propiedades de UniqueId."""
    base_sensor_entity._property.__class__ = UniqueIdProperty
    base_sensor_entity._property.value_is_string = False
    base_sensor_entity.coordinator.controller.get_property.return_value = "00:11:22:33:AA:BB"

    base_sensor_entity._update_state()
    assert base_sensor_entity.native_value == "00:11:22:33:AA:BB"


def test_update_state_valid_float(base_sensor_entity: ClimateIpSensor) -> None:
    """
    Kills mutants 10 y 11.
    Evalúa estrictamente la rama del try donde la conversión a float debe ser exitosa.
    """
    base_sensor_entity.coordinator.controller.get_property.return_value = "23.7"
    base_sensor_entity._property.value_is_string = False
    # No es UniqueIdProperty

    base_sensor_entity._update_state()

    # Lethal assertion: If mutant asigna None o lanza TypeError (float(None)),
    # el valor resultante será None y esta aserción fallará crasamente.
    assert base_sensor_entity._attr_native_value == 23.7, (
        "Falló la conversión matemática a float (Mutante 10/11)."
    )


def test_update_state_float_parsing_failure(
    base_sensor_entity: ClimateIpSensor,
) -> None:
    """Kills mutants en el bloque try/except de float(), incluyendo el Mutante 12."""
    # Al no ser string ni UniqueIdProperty, intentará castear a float
    base_sensor_entity._property.value_is_string = False

    # Inject una cadena corrupta que detonará ValueError
    base_sensor_entity.coordinator.controller.get_property.return_value = "not_a_number"

    # Forzamos un valor previo conocido que NO sea None ni un string vacío
    base_sensor_entity._attr_native_value = 50.0

    base_sensor_entity._update_state()

    # El except debe capturarlo y setear a None explícitamente.
    # El uso de 'is None' asegura que si mutmut lo cambia a '""', el test fallará.
    assert base_sensor_entity._attr_native_value is None, (
        "El fallo de casteo a float debe asignar exactamente None (aniquila Mutante 12)."
    )


# ============================================================
# PHASE 2: Factory / async_setup_entry
# ============================================================


class DummyPropValid:
    """Clase plana pura para derrotar la creación silenciosa de atributos de MagicMock."""

    id = "sensor_valid"
    entity_category = "diagnostic"
    device_class = "temperature"
    icon = "mdi:thermometer"
    unit_of_measurement = "°C"
    state_class = "measurement"

    def is_valid(self, state):
        return True


class DummyPropFallback:
    """Clase plana que carece de atributos opcionales para detonar fallbacks reales."""

    id = "sensor_fallback"

    def is_valid(self, state):
        return True


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
@patch("custom_components.climate_ip.sensor.SensorEntityDescription")
@patch("custom_components.climate_ip.sensor.parse_entity_category")
async def test_async_setup_entry_strict_mapping(
    mock_parse_category, mock_desc_class, mock_sensor_class
) -> None:
    """
    Kills mutants 8-23 y 40-67.
    Asserts the firma exacta de extracción (getattr) e inyección de SensorEntityDescription.
    """
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    target_device_state = {"temp": 22}
    mock_coord.controller.device_state = target_device_state

    # Inyección de la clase plana en lugar de un Mock
    prop_instance = DummyPropValid()
    # Usamos un mock para el método is_valid para asertar que recibe el estado correcto (Mutante 5 y 6)
    prop_instance.is_valid = MagicMock(return_value=True)

    mock_coord.controller.sensors = [prop_instance]
    entry.runtime_data = {"dev_1": mock_coord}

    mock_parse_category.return_value = "parsed_diagnostic"
    mock_desc_class.return_value = "sentinel_desc"
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    # Kills mutants 5 y 6: Asserts the recepción del raw_state exacto
    prop_instance.is_valid.assert_called_once_with(target_device_state)

    # Kills mutants de parse_entity_category (8, 9, 14, 15)
    mock_parse_category.assert_called_once_with("diagnostic")

    # Kills mutants de extracción y asignación de kwargs
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

    # Aniquila Mutante 71: Asserts explícitamente los argumentos posicionales del constructor
    mock_sensor_class.assert_called_once_with(
        mock_coord, mock_desc_class.return_value, prop_instance
    )

    # Aniquila Mutante 68: Asserts the identidad del objeto en la lista, no solo su longitud
    async_add_entities.assert_called_once()
    entities_passed = async_add_entities.call_args[0][0]
    assert entities_passed == [mock_sensor_class.return_value], (
        "El mutante hizo append de None en lugar del sensor instanciado."
    )


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.SensorEntityDescription")
@patch("custom_components.climate_ip.sensor.parse_entity_category")
async def test_async_setup_entry_fallback_and_logic(
    mock_parse_category, mock_desc_class
) -> None:
    """Kills mutants lógicos en las ramas de fallback (ej. mutante 32)."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    mock_coord.controller.sensors = [DummyPropFallback()]
    entry.runtime_data = {"dev_1": mock_coord}

    mock_parse_category.return_value = None
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    # Kills mutants que alteran la condición 'not icon and not device_class'
    # o que corrompen el getattr forzando el default None
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
async def test_async_setup_entry_icon_logical_operator_inverse(
    mock_parse_category, mock_desc_class
) -> None:
    """
    Aniquila Mutante 32 (cambio de 'and' por 'or' en la asignación del icono).
    Evaluamos el caso inverso: No hay icono, pero SÍ hay device_class.
    En el código original ('and'): No se asigna 'mdi:eye' porque hay device_class.
    En el código mutado ('or'): Se asignaría 'mdi:eye' de forma errónea.
    """
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    class DummyPropDeviceClassOnly:
        id = "sensor_dev_class_only"
        device_class = "temperature"
        icon = None  # Crucial: Icon is explicitly None

        def is_valid(self, state):
            return True

    mock_coord.controller.sensors = [DummyPropDeviceClassOnly()]
    entry.runtime_data = {"dev_1": mock_coord}

    mock_parse_category.return_value = None
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    # Extraemos los kwargs con los que se intentó crear el SensorEntityDescription
    mock_desc_class.assert_called_once()
    kwargs = mock_desc_class.call_args.kwargs

    # Lethal assertion: El icono debe seguir siendo None, no "mdi:eye"
    assert kwargs["icon"] is None, (
        "El mutante 'or' reescribió el icono a mdi:eye ignorando el device_class."
    )


@pytest.mark.asyncio
@patch("custom_components.climate_ip.sensor.ClimateIpSensor")
async def test_async_setup_entry_single_coordinator(mock_sensor_class) -> None:
    """Kills mutants en el desempaquetado singular (if isinstance)."""
    hass = MagicMock()
    entry = MagicMock()

    mock_coord = MagicMock()
    mock_coord.controller.sensors = []
    entry.runtime_data = mock_coord
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    assert mock_sensor_class.call_count == 0
    async_add_entities.assert_not_called()


def test_sensor_handle_coordinator_update_invalid_state():
    """Kills untested mutants in _handle_coordinator_update by forcing an invalid state."""
    from custom_components.climate_ip.sensor import ClimateIpSensor

    # Mock coordinator and property
    mock_coordinator = MagicMock()
    mock_coordinator.controller.device_state = {"power": "off"}  # Some state

    mock_prop = MagicMock()
    # Force is_valid to return False
    mock_prop.is_valid.return_value = False

    # Init sensor with a dummy valid value first to ensure it changes
    sensor = ClimateIpSensor(mock_coordinator, MagicMock(), mock_prop)
    sensor._attr_native_value = "previous_valid_value"
    sensor.async_write_ha_state = MagicMock()  # Prevent calling HA Core

    # Execute the update callback
    sensor._handle_coordinator_update()

    # Assertions to kill the mutants
    assert sensor._attr_native_value is None, (
        "Mutant survived! _attr_native_value should be explicitly None when state is invalid."
    )
    # Ensure properties were checked
    mock_prop.is_valid.assert_called_with({"power": "off"})


@pytest.mark.asyncio
async def test_sensor_setup_entry_name_mapping(hass):
    """Kills mutants modifying the 'name' kwarg in SensorEntityDescription."""
    from custom_components.climate_ip.sensor import async_setup_entry

    # Mock ConfigEntry
    mock_entry = MagicMock()

    # Create a mock property that explicitly HAS a name
    mock_prop = MagicMock()
    mock_prop.id = "test_sensor_id"
    mock_prop.name = "My Custom Sensor Name"  # <--- Crucial for mutant kill
    mock_prop.icon = "mdi:thermometer"
    mock_prop.unit_of_measurement = "°C"

    # Mock Coordinator
    mock_coordinator = MagicMock()
    mock_coordinator.controller.properties = {"test_sensor_id": mock_prop}
    mock_coordinator.controller.sensors = [mock_prop]
    mock_coordinator.controller.device_state = {}

    # Runtime data setup
    mock_entry.runtime_data = {"test_mac": mock_coordinator}

    # Capture added entities
    added_entities = []

    def mock_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, mock_entry, mock_add_entities)

    assert len(added_entities) == 1
    sensor = added_entities[0]

    # Assert the description name explicitly matches the YAML property name.
    # If mutmut changes it to None or removes the getattr fallback, this fails.
    assert sensor.entity_description.name == "My Custom Sensor Name", (
        "Mutant survived! The sensor name did not match the YAML property name."
    )

