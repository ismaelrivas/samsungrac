# pylint: disable=protected-access, redefined-outer-name
"""Tests for SamsungClimateSwitch entity."""
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import EntityCategory

from custom_components.climate_ip.switch import SamsungClimateSwitch, async_setup_entry
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator
from custom_components.climate_ip.properties import PROPERTY_TYPE_SWITCH


@pytest.fixture
def base_switch_entity() -> SamsungClimateSwitch:
    """Fixture base con coordinador mockeado. Aísla el constructor para pruebas puras."""
    mock_coordinator = MagicMock(spec=SamsungClimateCoordinator)
    mock_coordinator.unique_id = "test_mac_123"
    mock_coordinator.device_info = {"identifiers": {("climate_ip", "test_mac_123")}}
    mock_coordinator.controller = MagicMock()
    mock_coordinator.async_request_refresh = AsyncMock()

    mock_prop = MagicMock()
    mock_prop.id = "test_switch_id"
    mock_prop.value = "unknown"

    description = SwitchEntityDescription(
        key="test_switch_id",
        translation_key="test_switch_id",
        device_class=None,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:toggle-switch",
    )

    # Parcheamos _update_state temporalmente solo durante la instanciación
    # Esto evita que _update_state sobrescriba los valores iniciales de __init__
    with patch.object(SamsungClimateSwitch, "_update_state"):
        switch = SamsungClimateSwitch(
            coordinator=mock_coordinator,
            description=description,
            operation=mock_prop,
        )
    
    mock_platform_data = MagicMock()
    mock_platform_data.platform_name = "climate_ip"
    mock_platform_data.domain = "switch"
    switch.platform_data = mock_platform_data
    
    switch.async_write_ha_state = MagicMock()
    return switch


# ============================================================
# Dummy Classes (stubs for async_setup_entry tests)
# ============================================================


class DummySwitchPropValid:
    """Clase plana para derrotar la creación silenciosa de atributos de MagicMock."""
    id = "good_switch"
    entity_category = "config"
    device_class = "outlet"
    icon = "mdi:power-socket"

    def match_type(self, prop_type):
        return prop_type == PROPERTY_TYPE_SWITCH

    def is_valid(self, state):
        return True


class DummySwitchPropFallback:
    """Clase plana que carece de atributos opcionales para detonar fallbacks."""
    id = "fallback_switch"
    value = "off"

    def match_type(self, prop_type):
        return prop_type == PROPERTY_TYPE_SWITCH

    def is_valid(self, state):
        return True


# ============================================================
# PHASE 1: Constructor & Base Attributes
# ============================================================

def test_switch_initialization(base_switch_entity: SamsungClimateSwitch) -> None:
    """
    Aniquila Mutantes 1, 4, 5, 6, 7 y 8 en __init__.
    Aserta estrictamente las asignaciones estructurales iniciales.
    """
    # Mutante 1: super().__init__(None) -> falla porque coordinator no se asignaría.
    assert base_switch_entity.coordinator is not None
    
    # Mutante 4: self._controller = None
    assert base_switch_entity._controller is base_switch_entity.coordinator.controller
    
    # Mutante 5: self._attr_is_on = ""
    assert base_switch_entity._attr_is_on is None, "Debe ser estrictamente None, no un string vacío."
    
    # Mutantes 6 y 7: self._attr_has_entity_name = None / False
    assert base_switch_entity._attr_has_entity_name is True
    
    # Mutante 8: self._attr_unique_id = None
    assert base_switch_entity._attr_unique_id == "test_mac_123_test_switch_id"

    # Aniquila Mutante 9: self._attr_device_info = None
    assert base_switch_entity._attr_device_info == {"identifiers": {("climate_ip", "test_mac_123")}}, (
        "El device_info no se asignó o fue corrompido con None."
    )


# ============================================================
# PHASE 2: State Parsing (_update_state)
# ============================================================

def test_update_state_value_extraction(base_switch_entity: SamsungClimateSwitch) -> None:
    """
    Aniquila Mutante 1 (value = None en la extracción inicial).
    Si extrae None, ignorará el valor real y el estado terminará en None en lugar de True.
    """
    base_switch_entity._operation.value = "on"
    base_switch_entity._update_state()
    assert base_switch_entity._attr_is_on is True


@pytest.mark.parametrize("input_value", ["on", "On", True])
def test_update_state_on_matrix(base_switch_entity: SamsungClimateSwitch, input_value) -> None:
    """
    Aniquila Mutantes 2 al 10.
    Garantiza que cualquier alteración en la lista ["on", "On", True],
    su operador 'in', o la asignación final 'self._attr_is_on = True' falle matemáticamente.
    """
    base_switch_entity._operation.value = input_value
    base_switch_entity._update_state()
    assert base_switch_entity._attr_is_on is True, f"Falló la asignación a True para la entrada '{input_value}'"


@pytest.mark.parametrize("input_value", ["off", "Off", False])
def test_update_state_off_matrix(base_switch_entity: SamsungClimateSwitch, input_value) -> None:
    """
    Aniquila Mutantes 11 al 19.
    Garantiza que cualquier alteración en la lista ["off", "Off", False],
    su operador lógico, o la asignación final 'self._attr_is_on = False' falle.
    """
    base_switch_entity._operation.value = input_value
    base_switch_entity._update_state()
    assert base_switch_entity._attr_is_on is False, f"Falló la asignación a False para la entrada '{input_value}'"


def test_update_state_unknown_fallback(base_switch_entity: SamsungClimateSwitch) -> None:
    """
    Aniquila Mutante 20.
    Garantiza que la rama 'else' asigne estrictamente None, y no un string vacío u otro valor.
    """
    base_switch_entity._operation.value = "garbage_unrecognized_data"
    base_switch_entity._update_state()
    assert base_switch_entity._attr_is_on is None, "El fallback de estado desconocido debe ser None."

def test_update_state_missing_value_attribute(base_switch_entity: SamsungClimateSwitch) -> None:
    """Eliminate Mutant 6 for fallback when 'value' attribute is missing."""
    # Delete the 'value' attribute
    del base_switch_entity._operation.value
    base_switch_entity._update_state()
    assert base_switch_entity._attr_is_on is None



# ============================================================
# PHASE 3: Network Operations
# ============================================================

@pytest.mark.asyncio
async def test_async_turn_on(base_switch_entity: SamsungClimateSwitch) -> None:
    """Valida la delegación asíncrona de encendido."""
    base_switch_entity._controller.async_set_property = AsyncMock(return_value=True)
    
    await base_switch_entity.async_turn_on()
    
    base_switch_entity._controller.async_set_property.assert_awaited_once_with("test_switch_id", "on")
    assert base_switch_entity._attr_is_on is True
    base_switch_entity.async_write_ha_state.assert_called_once()
    base_switch_entity.coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_turn_off(base_switch_entity: SamsungClimateSwitch) -> None:
    """Valida la delegación asíncrona de apagado."""
    base_switch_entity._controller.async_set_property = AsyncMock(return_value=True)
    
    await base_switch_entity.async_turn_off()
    
    base_switch_entity._controller.async_set_property.assert_awaited_once_with("test_switch_id", "off")
    assert base_switch_entity._attr_is_on is False
    base_switch_entity.async_write_ha_state.assert_called_once()
    base_switch_entity.coordinator.async_request_refresh.assert_awaited_once()

# ============================================================
# PHASE 4: Factory / async_setup_entry
# ============================================================


@pytest.mark.asyncio
@patch("custom_components.climate_ip.switch.SamsungClimateSwitch")
@patch("custom_components.climate_ip.switch.SwitchEntityDescription")
@patch("custom_components.climate_ip.switch.parse_entity_category")
async def test_async_setup_entry_strict_mapping(
    mock_parse_category, mock_desc_class, mock_switch_class
) -> None:
    """Aniquila mutantes en la iteración, filtros y mapeo de atributos completos."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()
    
    target_device_state = {"power": "on"}
    mock_coord.controller.device_state = target_device_state
    
    prop_instance = DummySwitchPropValid()
    prop_instance.match_type = MagicMock(return_value=True)
    prop_instance.is_valid = MagicMock(return_value=True)
    
    mock_coord.controller.operations = [prop_instance]
    entry.runtime_data = {"dev_1": mock_coord}

    mock_parse_category.return_value = "parsed_config"
    mock_desc_class.return_value = "sentinel_desc"
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    # Validaciones estrictas de firma
    prop_instance.match_type.assert_called_once_with(PROPERTY_TYPE_SWITCH)
    prop_instance.is_valid.assert_called_once_with(target_device_state)
    mock_parse_category.assert_called_once_with("config")

    mock_desc_class.assert_called_once_with(
        key="good_switch",
        translation_key="good_switch",
        name=None,
        device_class="outlet",
        entity_category="parsed_config",
        icon="mdi:power-socket",
    )

    mock_switch_class.assert_called_once_with(
        mock_coord, mock_desc_class.return_value, prop_instance
    )

    async_add_entities.assert_called_once()
    assert async_add_entities.call_args[0][0] == [mock_switch_class.return_value]


@pytest.mark.asyncio
@patch("custom_components.climate_ip.switch.SwitchEntityDescription")
@patch("custom_components.climate_ip.switch.parse_entity_category")
async def test_async_setup_entry_fallbacks(mock_parse_category, mock_desc_class) -> None:
    """Aniquila mutantes en los operadores lógicos del fallback de iconos."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()
    
    mock_coord.controller.operations = [DummySwitchPropFallback()]
    entry.runtime_data = {"dev_1": mock_coord}

    mock_parse_category.return_value = None
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    # Si falta el device_class y el icon, debe inyectar el toggle-switch por defecto
    mock_desc_class.assert_called_once_with(
        key="fallback_switch",
        translation_key="fallback_switch",
        name=None,
        device_class=None,
        entity_category=None,
        icon="mdi:toggle-switch",
    )



@pytest.mark.asyncio
@patch("custom_components.climate_ip.switch.SamsungClimateSwitch")
async def test_async_setup_entry_single_coordinator_and_dict_ops(mock_switch_class) -> None:
    """Aniquila mutantes en las ramas de manejo de diccionarios para coordinadores y operaciones."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()
    
    # Suministramos operaciones como Diccionario en lugar de lista
    mock_coord.controller.operations = {"key_ignorado": DummySwitchPropFallback()}
    
    # Suministramos coordinator_data directamente, no como diccionario
    entry.runtime_data = mock_coord
    
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    assert mock_switch_class.call_count == 1
    async_add_entities.assert_called_once()


@pytest.mark.asyncio
@patch("custom_components.climate_ip.switch.SamsungClimateSwitch")
async def test_async_setup_entry_get_property_object_failure(mock_switch_class) -> None:
    """Eliminate mutants 9, 10, 11 by strict execution tracing of string operations."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    # Creamos un objeto válido para que actúe como "testigo" de que el bucle avanzó
    # Si mutmut cambia la validación de string a None o invierte el 'if', este objeto
    # o no será llamado, o será procesado erróneamente.
    valid_op_after_string = DummySwitchPropValid()
    valid_op_after_string.match_type = MagicMock(return_value=True)
    valid_op_after_string.is_valid = MagicMock(return_value=True)

    mock_coord.controller.operations = ["string_op", valid_op_after_string]
    mock_coord.controller.get_property_object.return_value = None
    entry.runtime_data = {"dev_1": mock_coord}

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)

    # Mutante 10: Asegura que get_property_object recibe exactamente "string_op"
    mock_coord.controller.get_property_object.assert_called_once_with("string_op")

    # Mutantes 9 y 11: Si la evaluación del objeto string falla correctamente (prop_obj is None),
    # el bucle debe hacer 'continue' y procesar 'valid_op_after_string'.
    # Si mutmut invierte la lógica ('if prop_obj is None: op = prop_obj'), la iteración explotará
    # o se detendrá. Por tanto, exigimos que la clase se instancie EXACTAMENTE 1 vez.
    assert mock_switch_class.call_count == 1, (
        "El bucle no manejó el string_op correctamente o abortó la iteración."
    )
    async_add_entities.assert_called_once()


@pytest.mark.asyncio
@patch("custom_components.climate_ip.switch.SwitchEntityDescription")
@patch("custom_components.climate_ip.switch.parse_entity_category")
@patch("custom_components.climate_ip.switch.SamsungClimateSwitch")
async def test_async_setup_entry_continue_vs_break(
    mock_switch_class, mock_parse_category, mock_desc_class
) -> None:
    """Elimina los mutantes 13, 21, 25 y 30 garantizando el uso de continue en lugar de break."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    # Mutante 21: Objeto sin atributo 'id'
    class NoIdProp:
        pass

    # Mutante 25: ID es "power"
    class PowerProp:
        id = "power"

    # Mutante 30: No válido para el estado del dispositivo
    class InvalidProp:
        id = "invalid_switch"
        def match_type(self, t): return True
        def is_valid(self, s): return False

    valid_prop = DummySwitchPropValid()
    valid_prop.match_type = MagicMock(return_value=True)
    valid_prop.is_valid = MagicMock(return_value=True)

    # ORDEN CRÍTICO: Los elementos que deben saltarse van PRIMERO.
    # Si cualquiera de ellos muta de 'continue' a 'break', la iteración aborta
    # antes de procesar el 'valid_prop' final, dejando el call_count en 0.
    mock_coord.controller.operations = [
        NoIdProp(),
        PowerProp(),
        InvalidProp(),
        valid_prop
    ]

    entry.runtime_data = {"dev_1": mock_coord}
    mock_parse_category.return_value = "parsed_config"
    mock_desc_class.return_value = "sentinel_desc"
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    # Aserción Letal
    assert mock_switch_class.call_count == 1, (
        "La iteración se detuvo prematuramente. Un filtro usó 'break' en lugar de 'continue'."
    )
    async_add_entities.assert_called_once()

@pytest.mark.asyncio
@patch("custom_components.climate_ip.switch.SwitchEntityDescription")
@patch("custom_components.climate_ip.switch.parse_entity_category")
async def test_async_setup_entry_icon_logical_operator_inverse(mock_parse_category, mock_desc_class) -> None:
    """Eliminate mutant 56 that inverts logical operator for icon fallback."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()
    class IconOnlyProp:
        id = "icon_only"
        device_class = None
        icon = "mdi:lightbulb"
        def match_type(self, t):
            return True
        def is_valid(self, s):
            return True
    mock_coord.controller.operations = [IconOnlyProp()]
    entry.runtime_data = {"dev_1": mock_coord}
    mock_parse_category.return_value = None
    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    mock_desc_class.assert_called_once_with(
        key="icon_only",
        translation_key="icon_only",
        name=None,
        device_class=None,
        entity_category=None,
        icon="mdi:lightbulb",
    )
    async_add_entities.assert_called_once()


@pytest.mark.asyncio
@patch("custom_components.climate_ip.switch.SamsungClimateSwitch")
@patch("custom_components.climate_ip.switch.SwitchEntityDescription")
@patch("custom_components.climate_ip.switch.parse_entity_category")
async def test_async_setup_entry_get_property_object_success(
    mock_parse_category, mock_desc_class, mock_switch_class
) -> None:
    """Elimina al Mutante 11 asertando el Happy Path de la resolución de strings."""
    hass = MagicMock()
    entry = MagicMock()
    mock_coord = MagicMock()

    # Operación string que SÍ se resuelve a un objeto válido
    mock_coord.controller.operations = ["string_op_valid"]

    valid_prop = DummySwitchPropValid()
    valid_prop.match_type = MagicMock(return_value=True)
    valid_prop.is_valid = MagicMock(return_value=True)

    # Configuramos el factory para devolver el objeto válido
    mock_coord.controller.get_property_object.return_value = valid_prop
    entry.runtime_data = {"dev_1": mock_coord}

    mock_parse_category.return_value = "parsed_config"
    mock_desc_class.return_value = "sentinel_desc"
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    # Aserción Letal:
    # Si mutmut cambia `if prop_obj is not None` por `if prop_obj is None`,
    # el objeto válido caerá en la rama 'else', se ejecutará 'continue',
    # y el contador de llamadas será 0.
    assert mock_switch_class.call_count == 1, (
        "El string operation válido no instanció la entidad. "
        "El mutante 11 invirtió el chequeo de 'is not None'."
    )
