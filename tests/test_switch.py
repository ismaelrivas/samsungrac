# pylint: disable=protected-access, redefined-outer-name
"""Tests for SamsungClimateSwitch entity."""
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import EntityCategory

from custom_components.climate_ip.switch import SamsungClimateSwitch
from custom_components.climate_ip.coordinator import SamsungClimateCoordinator


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
