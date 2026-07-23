# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for YamlController — Phase 2 (executor I/O) and Phase 3 (hass injection) compliance."""
# pylint: disable=redefined-outer-name,protected-access

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from homeassistant.helpers.update_coordinator import UpdateFailed
from custom_components.climate_ip.exceptions import CannotConnect

from custom_components.climate_ip.controller_yaml import YamlController
from custom_components.climate_ip.controller_yaml_config import _YAML_FILE_CACHE
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    STATE_UNKNOWN,
)
from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
)

from homeassistant.components.climate import (
    ATTR_HVAC_MODE, ATTR_TEMPERATURE, ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE, ATTR_SWING_MODE, ATTR_PRESET_MODE,
    ATTR_HVAC_MODES, ATTR_FAN_MODES, ATTR_SWING_MODES, ATTR_PRESET_MODES
)

@pytest.fixture
def anyio_backend():
    """Use asyncio as the anyio backend."""
    return "asyncio"


@pytest.fixture
def mock_logger():
    """Return a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture(autouse=True)
def clear_yaml_cache():
    """Clear the YAML file cache before each test."""
    _YAML_FILE_CACHE.clear()



@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance with executor job support."""
    from custom_components.climate_ip.const import (
        DOMAIN,  # pylint: disable=import-outside-toplevel
    )
    hass = MagicMock()
    hass.config.components = set()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    hass.async_add_executor_job = mock_async_add_executor_job

    # Mock hass.data
    hass.data = {DOMAIN: {"connections": {}, "lock": AsyncMock()}}
    return hass


@pytest.fixture
def yaml_config() -> dict:  # type: ignore[type-arg]
    """Config dict without hass/session — they are passed as explicit kwargs (Phase 3)."""
    return {
        CONF_CONFIG_FILE: "test_device.yaml",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_DEVICE_ID: "test_device_id",
        CONF_TOKEN: "test_token",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }



async def test_controller_initialization(
    yaml_config: dict, mock_logger: logging.Logger, mock_hass: MagicMock  # type: ignore[type-arg]
) -> None:
    """Test that YamlController initializes with correct attributes (Phase 3 signature)."""
    controller = YamlController(yaml_config, mock_logger, hass=mock_hass, session=MagicMock())

    assert controller._ip_address == "192.168.1.100"
    assert controller._device_id == "test_device_id"
    assert controller._token == "test_token"
    assert controller._yaml == "test_device.yaml"
    assert controller._unique_id == "AA:BB:CC:DD:EE:FF"
    # Phase 3: hass must not appear in the serializable config dict
    assert "hass" not in controller._config
    assert "session" not in controller._config

    # Hardening against YamlConfigLoader.__init__ dead assignment mutants
    from homeassistant.const import ATTR_ENTITY_ID
    assert controller.loader.connection is None
    assert controller.loader.state_getter is None
    assert controller.loader.name == "yaml"
    assert controller.loader.poll is None
    assert controller.loader.is_fully_initialized is False
    assert controller.loader._parsed_yaml_config is None
    assert controller.loader.properties_list == []
    assert len(controller.loader.service_schema_map) == 1
    key = list(controller.loader.service_schema_map.keys())[0]
    assert key.schema == ATTR_ENTITY_ID



async def test_initialize_loads_yaml(
    yaml_config: dict, mock_logger: logging.Logger, mock_hass: MagicMock  # type: ignore[type-arg]
) -> None:
    """Test that initialize loads YAML configuration."""
    controller = YamlController(yaml_config, mock_logger, hass=mock_hass, session=MagicMock())

    mock_yaml_data = {
        "device": {
            "name": "Test AC",
            "connection": {
                "type": "samsung_2878"
            }
        }
    }

    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml", return_value=mock_yaml_data
    ) as m_load:

        # Mock CLIMATE_IP_CONNECTIONS to return a mock connection class
        with patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS"
        ) as mock_connections:
            mock_conn_class = MagicMock()
            mock_conn_class.match_type.return_value = True
            mock_conn_class.__name__ = "MockConnection"
            mock_conn_instance = MagicMock()
            mock_conn_instance.load_from_yaml.return_value = True
            mock_conn_class.return_value = mock_conn_instance

            mock_connections.__iter__.return_value = [mock_conn_class]

            # Also mock create_status_getter since it's called in initialize
            with patch(
                "custom_components.climate_ip.controller_yaml_config.create_status_getter"
            ) as mock_create_status:
                mock_create_status.return_value = MagicMock()

                result = await controller.initialize()

                assert result is True
                assert controller.loader._parsed_yaml_config == mock_yaml_data
                m_load.assert_called()



async def test_match_type() -> None:
    """Test the match_type static method."""
    assert YamlController.match_type("yaml") is True
    assert YamlController.match_type("YAML") is True
    assert YamlController.match_type("other") is False


# ---------------------------------------------------------------------------
# Phase 2: YAML I/O must be dispatched to the executor thread pool.
# ---------------------------------------------------------------------------



async def test_yaml_file_read_uses_executor(
    yaml_config: dict,  # type: ignore[type-arg]
    mock_logger: logging.Logger,
    mock_hass: MagicMock,
) -> None:
    """YAML file reading must be dispatched via async_add_executor_job.

    Ensures the event loop is never blocked by disk I/O during setup.
    """
    executor_calls: list[str] = []

    async def spy_executor(fn, *args):  # type: ignore[no-untyped-def]
        """Spy on executor dispatches and record the function names."""
        executor_calls.append(getattr(fn, "__name__", repr(fn)))
        return fn(*args)

    mock_hass.async_add_executor_job = spy_executor

    controller = YamlController(yaml_config, mock_logger, hass=mock_hass, session=MagicMock())

    mock_yaml_data = {
        "device": {
            "name": "Test AC",
            "connection": {
                "type": "samsung_2878"
            }
        }
    }
    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml", return_value=mock_yaml_data
    ), patch(
        "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS"
    ) as mock_conns, patch(
        "custom_components.climate_ip.controller_yaml_config.create_status_getter",
        return_value=MagicMock(),
    ):

        mock_conn_class = MagicMock()
        mock_conn_class.match_type.return_value = True
        mock_conn_class.__name__ = "MockConnection"
        mock_conn_instance = MagicMock()
        mock_conn_instance.load_from_yaml.return_value = True
        mock_conn_class.return_value = mock_conn_instance
        mock_conns.__iter__.return_value = [mock_conn_class]

        result = await controller.initialize()

    assert result is True
    # load_yaml must have been dispatched to the executor.
    assert len(executor_calls) >= 1, f"Expected at least 1 executor dispatch, got {executor_calls}"
    assert any(
        "load_yaml" in name for name in executor_calls
    ), f"No load_yaml call found in executor dispatches: {executor_calls}"


async def test_async_set_property_registers_pending_update(
    yaml_config: dict,  # type: ignore[type-arg]
    mock_logger: logging.Logger,
    mock_hass: MagicMock,
) -> None:
    """Test that async_set_property strictly delegates to poller.register_pending_update."""
    controller = YamlController(yaml_config, mock_logger, hass=mock_hass, session=MagicMock())
    
    # Mock loader dependencies
    controller.loader.is_fully_initialized = True
    
    # Mock the operation
    mock_op = AsyncMock()
    mock_op.async_set_value.return_value = True
    controller.loader.operations = {"fan_mode": mock_op}
    
    # Mock the poller
    mock_poller = MagicMock()
    controller.poller = mock_poller
    
    result = await controller.async_set_property("fan_mode", "high")
    
    assert result is True
    # Strict transactional assertion on the delegation contract
    mock_poller.register_pending_update.assert_called_once_with("fan_mode", "high")
    mock_op.async_set_value.assert_called_once_with("high", "test_device_id")


def test_yaml_controller_strict_initialization() -> None:
    """
    Aniquila los 35 mutantes del __init__ de YamlController.
    Verifica matemáticamente que la extracción del config dict, 
    la asignación de variables de estado y la instanciación 
    de los delegados (loader y poller) ocurren sin alteraciones.
    """
    mock_logger = logging.getLogger("test_logger")
    mock_hass = MagicMock()
    mock_session = MagicMock()

    # Configuramos un diccionario de entrada completo
    config_input = {
        "hass": "should_be_popped",
        "session": "should_be_popped",
        CONF_CONFIG_FILE: "test_config.yaml",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_DEVICE_ID: "dev_123",
        CONF_TOKEN: "secret_token",
        "unique_id": "test_mac_uid",
        "debug": True,
    }

    # Evitamos que los delegados intenten interactuar con el sistema de archivos o red en el init
    with patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"), \
         patch("custom_components.climate_ip.controller_yaml.YamlStatePoller") as mock_poller_class:
        
        controller = YamlController(config_input, mock_logger, mock_hass, mock_session)

    # --- ASERCIONES LETALES ---

    # 1. Mutantes 7-16: Verificar que 'hass' y 'session' fueron extraídos del config.
    assert "hass" not in controller._config, "El mutante evitó hacer pop('hass')"
    assert "session" not in controller._config, "El mutante evitó hacer pop('session')"
    assert controller.hass is mock_hass
    assert controller._session is mock_session
    assert controller._logger is mock_logger

    # 2. Mutantes 23-25: Extracción estricta de IP Address
    assert controller._ip_address == "192.168.1.100"

    # 3. Mutantes 33-35: Extracción estricta de Identificadores y Token
    assert controller._token == "secret_token"
    assert controller._device_id == "dev_123"
    assert controller._unique_id == "test_mac_uid"

    # 4. Mutantes 52-60: Inicialización de Callbacks estrictamente a None
    assert controller.on_token_refreshed is None
    assert controller.get_current_state_callback is None
    assert controller.on_push_update_callback is None
    assert controller.on_ssl_config_updated is None
    assert controller.request_refresh_callback is None
    assert controller.on_connection_failed_callback is None
    assert controller.on_offline_callback is None
    assert controller.discovered_devices is None

    # 5. Mutantes 61-68: Asignación de flag de debug
    assert controller._debug is True, "El mutante alteró la extracción del flag debug"

    # 6. Mutantes 69-72: Asignación del diccionario de atributos base
    # Tiene que contener exactamente la clave 'controller' mapeada al unique_id
    assert controller._attributes == {"controller": "test_mac_uid"}
    assert controller._shared_raw_client is None

    # 7. Mutantes 75-76: Verificación de composición (Delegados)
    assert controller.loader is not None
    assert controller.poller is not None
    # Verificamos que al poller se le pasó el controlador como argumento (self)
    mock_poller_class.assert_called_once_with(controller)


def test_yaml_controller_fallback_initialization() -> None:
    """Aniquila mutantes en las ramas condicionales de fallbacks lógicos del init."""
    mock_logger = logging.getLogger("test_logger")
    
    # Configuramos un config donde faltan claves primarias para forzar los `or` lógicos
    config_input = {
        "host": "10.0.0.1",           # Fallback para _ip_address
        CONF_MAC: "00:11:22",         # Fallback para _unique_id
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878, # Fueraza la rama de fallback de device_id
        "debug": False,               # Debug explícito a False
    }

    with patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"), \
         patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"):
        controller = YamlController(config_input, mock_logger)

    assert controller._ip_address == "10.0.0.1", "Falló el fallback 'host'"
    assert controller._unique_id == "00:11:22", "Falló el fallback CONF_MAC"
    # Como DEVICE_TYPE_SAMSUNG_2878 está presente, device_id debe tomar el valor de unique_id
    assert controller._device_id == "00:11:22", "Falló la asignación Samsung 2878 para device_id"
    assert controller._debug is False

def test_yaml_controller_fallback_else_and_debug_default() -> None:
    """
    Aniquila los últimos 4 mutantes (52, 63, 65, 68).
    Verifica la rama 'else' de la asignación de device_id 
    y el valor por defecto puro de 'debug' cuando no se proporciona en config.
    """
    mock_logger = logging.getLogger("test_logger")
    
    # 1. NO proveemos 'debug' en absoluto para forzar el fallback de config.get("debug", False)
    # 2. NO proveemos DEVICE_TYPE_SAMSUNG_2878 para forzar la rama `else` del fallback de device_id
    # 3. Proveemos solo unique_id, sin device_id.
    config_input = {
        "unique_id": "fallback_mac_only"
    }

    with patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"), \
         patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"):
        controller = YamlController(config_input, mock_logger)

    # Aniquila Mutante 52: La rama 'else' debe haber asignado unique_id a _device_id
    assert controller._device_id == "fallback_mac_only", "La rama else no asignó el unique_id al device_id"
    
    # Aniquila Mutantes 63, 65, 68: El valor de _debug debe ser estrictamente False (por default)
    assert controller._debug is False, "El fallback de debug fue mutado y no es False"

@pytest.fixture
def mock_yaml_controller():
    """Fixture to provide an initialized YamlController with mocked delegates."""
    mock_logger = logging.getLogger("test_logger")
    config_input = {CONF_CONFIG_FILE: "test.yaml", CONF_MAC: "mac123"}
    
    with patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"), \
         patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"):
        controller = YamlController(config_input, mock_logger)
        
        # Setup specific mock properties for testing
        controller.loader.operations = {}
        controller.loader.properties = {}
        controller.loader.sensors = {}
        controller._attributes = {}
        
        return controller

@pytest.mark.asyncio
async def test_update_state_delegation(mock_yaml_controller) -> None:
    """Aniquila mutantes en update_state (evalúa retorno booleano)."""
    # Escenario 1: Poller devuelve un dict (éxito) -> update_state debe devolver True
    mock_yaml_controller.poller.async_update_state = AsyncMock(return_value={"power": "on"})
    assert await mock_yaml_controller.update_state() is True

    # Escenario 2: Poller devuelve None (fallo) -> update_state debe devolver False
    mock_yaml_controller.poller.async_update_state = AsyncMock(return_value=None)
    assert await mock_yaml_controller.update_state() is False


def test_get_property_object_hierarchy(mock_yaml_controller) -> None:
    """Aniquila mutantes en la jerarquía de búsqueda de get_property_object."""
    mock_op = MagicMock()
    mock_prop = MagicMock()
    mock_sensor = MagicMock()
    
    mock_yaml_controller.loader.operations = {"test_op": mock_op}
    mock_yaml_controller.loader.properties = {"test_prop": mock_prop}
    mock_yaml_controller.loader.sensors = {"test_sensor": mock_sensor}

    # Búsqueda en orden: operations -> properties -> sensors -> None
    assert mock_yaml_controller.get_property_object("test_op") is mock_op
    assert mock_yaml_controller.get_property_object("test_prop") is mock_prop
    assert mock_yaml_controller.get_property_object("test_sensor") is mock_sensor
    assert mock_yaml_controller.get_property_object("missing_key") is None


def test_get_property_value_extraction(mock_yaml_controller) -> None:
    """Aniquila mutantes en get_property comprobando fallbacks y STATE_UNKNOWN."""

    mock_op = MagicMock()
    mock_op.value = "op_value"
    mock_yaml_controller.loader.operations = {"test_op": mock_op}
    mock_yaml_controller._attributes = {"test_attr": "attr_value", "unknown_attr": STATE_UNKNOWN}

    # Escenario 1: Atributo existe como objeto
    assert mock_yaml_controller.get_property("test_op") == "op_value"
    
    # Escenario 2: Atributo no es objeto, se busca en _attributes
    assert mock_yaml_controller.get_property("test_attr") == "attr_value"
    
    # Escenario 3: Valor encontrado es STATE_UNKNOWN, debe convertirse a None
    assert mock_yaml_controller.get_property("unknown_attr") is None
    
    # Escenario 4: Clave inexistente, devuelve None
    assert mock_yaml_controller.get_property("missing_key") is None


def test_get_property_all_values(mock_yaml_controller) -> None:
    """Aniquila mutantes en get_property_all_values evaluando protección contra nulos."""
    mock_op = MagicMock()
    mock_op.all_values = ["val1", "val2"]
    
    mock_op_no_values = MagicMock()
    mock_op_no_values.all_values = None

    mock_yaml_controller.loader.operations = {
        "good_op": mock_op, 
        "bad_op": mock_op_no_values
    }

    # Escenario 1: El objeto existe y tiene all_values
    assert mock_yaml_controller.get_property_all_values("good_op") == ["val1", "val2"]
    
    # Escenario 2: El objeto existe pero no tiene all_values
    assert mock_yaml_controller.get_property_all_values("bad_op") is None
    
    # Escenario 3: El objeto ni siquiera existe
    assert mock_yaml_controller.get_property_all_values("missing_op") is None


@pytest.mark.asyncio
async def test_async_merge_and_predict_delegation(mock_yaml_controller) -> None:
    """Aniquila mutantes en los delegados de merge y predict."""
    mock_yaml_controller.poller.async_merge_device_state = AsyncMock(return_value=True)
    mock_yaml_controller.poller.async_predict_and_correct_state = AsyncMock(return_value=(True, {"st": 1}))

    # Test merge
    assert await mock_yaml_controller.async_merge_device_state({"k": "v"}, True, False) is True
    mock_yaml_controller.poller.async_merge_device_state.assert_called_once_with({"k": "v"}, True, False)

    # Test predict
    res = await mock_yaml_controller.async_predict_and_correct_state("state", "prop", "val")
    assert res == (True, {"st": 1})
    mock_yaml_controller.poller.async_predict_and_correct_state.assert_called_once_with("state", "prop", "val")

@pytest.mark.asyncio
async def test_async_set_property_error_scenarios(mock_yaml_controller) -> None:
    """Aniquila mutantes 2, 14, 15, 16 en async_set_property asertando fallos y excepciones."""
    # Escenario 1 (Mutante 2): Controlador no inicializado -> devuelve False
    mock_yaml_controller.loader.is_fully_initialized = False
    assert await mock_yaml_controller.async_set_property("prop", "val") is False
    mock_yaml_controller.loader.is_fully_initialized = True  # Restaurar estado

    # Escenario 2 (Mutante 16): Propiedad no existe -> devuelve False
    assert await mock_yaml_controller.async_set_property("missing_prop", "val") is False

    # Preparamos una operación simulada para los siguientes escenarios
    mock_op = AsyncMock()
    mock_yaml_controller.loader.operations = {"test_prop": mock_op}

    # Escenario 3 (Mutante 14): Error de red -> Lanza UpdateFailed con mensaje estricto
    mock_op.async_set_value.side_effect = CannotConnect("Host down")
    with pytest.raises(UpdateFailed) as exc_info:
        await mock_yaml_controller.async_set_property("test_prop", "val")
    # Asertamos la concatenación estricta de la cadena de error
    assert "Failed to set property 'test_prop': Host down" in str(exc_info.value)

    # Escenario 4 (Mutante 15): Exception genérica -> captura silenciosa y devuelve False
    mock_op.async_set_value.side_effect = ValueError("Boom")
    assert await mock_yaml_controller.async_set_property("test_prop", "val") is False



def test_yaml_controller_setters_strict_assignment(mock_yaml_controller) -> None:
    """Aniquila los mutantes de asignación en los setters (5 mutantes)."""
    # 1. device_id
    mock_yaml_controller.device_id = "target_dev_id"
    assert mock_yaml_controller._device_id == "target_dev_id"
    assert mock_yaml_controller._config[CONF_DEVICE_ID] == "target_dev_id"

    # 2. token
    mock_yaml_controller.token = "target_token"
    assert mock_yaml_controller._token == "target_token"
    assert mock_yaml_controller._config[CONF_TOKEN] == "target_token"

    # 3. fan_modes_list_changed_pending_flicker (delegación estricta)
    mock_yaml_controller.fan_modes_list_changed_pending_flicker = True
    assert mock_yaml_controller.poller.fan_modes_list_changed_pending_flicker is True
    mock_yaml_controller.fan_modes_list_changed_pending_flicker = False
    assert mock_yaml_controller.poller.fan_modes_list_changed_pending_flicker is False


def test_yaml_controller_available_property(mock_yaml_controller) -> None:
    """Aniquila los 8 mutantes de la propiedad available verificando las 3 ramas."""
    # Escenario 1: connection es None -> Fallback a True
    mock_yaml_controller.loader.connection = None
    assert mock_yaml_controller.available is True

    # Escenario 2: connection presente pero devuelve is_available=False
    conn_mock = MagicMock()
    conn_mock.get_diagnostics.return_value = {"is_available": False}
    mock_yaml_controller.loader.connection = conn_mock
    assert mock_yaml_controller.available is False

    # Escenario 3: connection presente pero su diagnostic dict no tiene la llave (Fallback True)
    conn_mock.get_diagnostics.return_value = {"other_key": "data"}
    assert mock_yaml_controller.available is True


def test_yaml_controller_sensors_property(mock_yaml_controller) -> None:
    """Aniquila el mutante de la comprensión de listas en la propiedad sensors."""
    mock_sensor = MagicMock()
    # Inyectamos 1 sensor válido y definimos en la lista 1 válido y 1 "fantasma"
    mock_yaml_controller.loader.sensors = {"valid_sensor": mock_sensor}
    mock_yaml_controller.loader.sensors_list = ["valid_sensor", "ghost_sensor"]

    # Si mutmut cambia 'in' por 'not in', la lista resultante estará vacía o romperá
    res = mock_yaml_controller.sensors
    assert len(res) == 1, "El filtrado de sensors incluyó elementos inválidos o mutó la lista"
    assert res[0] is mock_sensor


def test_yaml_controller_is_push_device_strict(mock_yaml_controller) -> None:
    """Aniquila los mutantes lógicos evaluando el soporte nativo de push bajo Fail-Fast."""
    import pytest
    
    # 1. Sin conexión -> Falla limpiamente por lógica (retorna False)
    mock_yaml_controller.loader.connection = None
    assert mock_yaml_controller.is_push_device is False

    # 2. Doctrina Fail-Fast: Conexión corrupta/incompatible -> DEBE ESTALLAR
    class LegacyConnection:
        pass
    mock_yaml_controller.loader.connection = LegacyConnection()
    with pytest.raises(AttributeError):
        _ = mock_yaml_controller.is_push_device

    # 3. Conexión 100% compatible -> Retorna el valor
    conn_mock = MagicMock()
    conn_mock.is_push_supported = True
    mock_yaml_controller.loader.connection = conn_mock
    assert mock_yaml_controller.is_push_device is True

@patch("custom_components.climate_ip.state.ClimateIPDeviceState")
def test_yaml_controller_climate_state_mapping(mock_state_class, mock_yaml_controller) -> None:
    """Aniquila a los 42 mutantes de la instanciación de estado mediante Caja Blanca Matemática."""
    
    # 1. Secuestramos get_property para devolver un string matemático exacto basado en el argumento
    mock_yaml_controller.get_property = MagicMock(side_effect=lambda prop: f"val_{prop}")
    
    # 2. Secuestramos las listas de atributos
    mock_yaml_controller._attributes = {
        ATTR_HVAC_MODES: ["auto", "heat"],
        ATTR_FAN_MODES: ["high", "low"],
        ATTR_SWING_MODES: ["on", "off"],
        ATTR_PRESET_MODES: ["eco"]
    }

    # 3. Ejecución
    _ = mock_yaml_controller.climate_state

    # 4. Aserción Letal: Cualquier mutante que inserte un 'None' o rompa la delegación morirá aquí.
    mock_state_class.assert_called_once_with(
        hvac_mode=f"val_{ATTR_HVAC_MODE}",
        target_temperature=f"val_{ATTR_TEMPERATURE}",
        current_temperature=f"val_{ATTR_CURRENT_TEMPERATURE}",
        fan_mode=f"val_{ATTR_FAN_MODE}",
        swing_mode=f"val_{ATTR_SWING_MODE}",
        preset_mode=f"val_{ATTR_PRESET_MODE}",
        hvac_modes=["auto", "heat"],
        fan_modes=["high", "low"],
        swing_modes=["on", "off"],
        preset_modes=["eco"],
    )


def test_yaml_controller_unique_id_property(mock_yaml_controller) -> None:
    """Aniquila mutantes en la propiedad unique_id probando todas las combinaciones."""
    # 1. Sub-dispositivo con unique_id simple -> Sufijo _device_id
    mock_yaml_controller._unique_id = "mac_123"
    mock_yaml_controller._device_id = "sub_1"
    assert mock_yaml_controller.unique_id == "mac_123_sub_1"

    # 2. Sub-dispositivo que ya incluye _device_id en unique_id -> No duplica
    mock_yaml_controller._unique_id = "mac_123_sub_1"
    mock_yaml_controller._device_id = "sub_1"
    assert mock_yaml_controller.unique_id == "mac_123_sub_1"

    # 3. Dispositivo principal con device_id "0" -> Mantiene unique_id original
    mock_yaml_controller._unique_id = "mac_123"
    mock_yaml_controller._device_id = "0"
    assert mock_yaml_controller.unique_id == "mac_123"

    # 4. device_id es None -> Devuelve unique_id
    mock_yaml_controller._unique_id = "mac_123"
    mock_yaml_controller._device_id = None
    assert mock_yaml_controller.unique_id == "mac_123"

    # 5. unique_id es None -> Devuelve None
    mock_yaml_controller._unique_id = None
    mock_yaml_controller._device_id = "sub_1"
    assert mock_yaml_controller.unique_id is None


def test_yaml_controller_delegated_properties(mock_yaml_controller) -> None:
    """Aniquila mutantes en las propiedades delegadas simples."""
    # name
    mock_yaml_controller.loader.name = "Test AC Name"
    assert mock_yaml_controller.name == "Test AC Name"

    # config
    assert mock_yaml_controller.config is mock_yaml_controller._config

    # ip_address
    mock_yaml_controller._ip_address = "192.168.1.50"
    assert mock_yaml_controller.ip_address == "192.168.1.50"

    # debug
    mock_yaml_controller._debug = True
    assert mock_yaml_controller.debug is True

    # poll
    mock_yaml_controller.loader.poll = True
    assert mock_yaml_controller.poll is True

    # id
    mock_yaml_controller._unique_id = "uid_999"
    assert mock_yaml_controller.id == "uid_999"

    # state_attributes
    mock_yaml_controller._attributes = {"controller": "uid_999", "attr_1": 10}
    assert mock_yaml_controller.state_attributes == {"controller": "uid_999", "attr_1": 10}

    # temperature_unit
    assert mock_yaml_controller.temperature_unit == "°C"

    # service_schema_map
    mock_yaml_controller.loader.service_schema_map = {"schema_key": "schema_val"}
    assert mock_yaml_controller.service_schema_map == {"schema_key": "schema_val"}

    # operations
    mock_yaml_controller.loader.operations_list = ["op_power", "op_temp"]
    assert mock_yaml_controller.operations == ["op_power", "op_temp"]

    # attributes
    mock_yaml_controller.loader.properties_list = ["attr_curr_temp"]
    assert mock_yaml_controller.attributes == ["attr_curr_temp"]


def test_yaml_controller_last_poll_data(mock_yaml_controller) -> None:
    """Aniquila mutantes en last_poll_data."""
    # Sin state_getter -> None
    mock_yaml_controller.loader.state_getter = None
    assert mock_yaml_controller.last_poll_data is None

    # Con state_getter -> Devuelve value
    mock_state_getter = MagicMock()
    mock_state_getter.value = {"raw_temp": 25}
    mock_yaml_controller.loader.state_getter = mock_state_getter
    assert mock_yaml_controller.last_poll_data == {"raw_temp": 25}


def test_yaml_controller_connection_diagnostics(mock_yaml_controller) -> None:
    """Aniquila mutantes en connection_diagnostics."""
    # Sin conexión -> Dict vacío
    mock_yaml_controller.loader.connection = None
    assert mock_yaml_controller.connection_diagnostics == {}

    # Con conexión -> Devuelve diagnostics
    mock_conn = MagicMock()
    mock_conn.get_diagnostics.return_value = {"latency_ms": 12, "connected": True}
    mock_yaml_controller.loader.connection = mock_conn
    assert mock_yaml_controller.connection_diagnostics == {"latency_ms": 12, "connected": True}


def test_yaml_controller_device_state(mock_yaml_controller) -> None:
    """Aniquila mutantes en device_state comprobando la jerarquía poller -> loader -> dict vacío."""
    # 1. Poller tiene _last_device_state -> Devuelve estado de poller
    mock_yaml_controller.poller._last_device_state = {"poller_key": "val1"}
    assert mock_yaml_controller.device_state == {"poller_key": "val1"}

    # 2. Poller _last_device_state es None, loader tiene state_getter -> Devuelve loader value
    mock_yaml_controller.poller._last_device_state = None
    mock_state_getter = MagicMock()
    mock_state_getter.value = {"loader_key": "val2"}
    mock_yaml_controller.loader.state_getter = mock_state_getter
    assert mock_yaml_controller.device_state == {"loader_key": "val2"}

    # 3. Ninguno tiene datos -> Devuelve dict vacío
    mock_yaml_controller.loader.state_getter = None
    assert mock_yaml_controller.device_state == {}


@pytest.mark.asyncio
async def test_yaml_controller_async_delegates_and_noop(mock_yaml_controller) -> None:
    """Aniquila mutantes en async_get_status, async_update_state, async_shutdown, y async_refresh_from_connection."""
    # async_get_status
    mock_yaml_controller.poller.async_get_status = AsyncMock(return_value={"status": "ok"})
    assert await mock_yaml_controller.async_get_status() == {"status": "ok"}
    mock_yaml_controller.poller.async_get_status.assert_called_once()

    # async_update_state
    mock_yaml_controller.poller.async_update_state = AsyncMock(return_value={"state": "active"})
    assert await mock_yaml_controller.async_update_state() == {"state": "active"}
    mock_yaml_controller.poller.async_update_state.assert_called_once()

    # async_shutdown
    mock_yaml_controller.poller.async_shutdown = AsyncMock()
    await mock_yaml_controller.async_shutdown()
    mock_yaml_controller.poller.async_shutdown.assert_called_once()

    # async_refresh_from_connection (no-op)
    res = await mock_yaml_controller.async_refresh_from_connection()
    assert res is None


def test_platform_schema_validation() -> None:
    """Aniquila mutantes en la definición de PLATFORM_SCHEMA."""
    from homeassistant.const import CONF_PLATFORM
    from custom_components.climate_ip.controller_yaml import PLATFORM_SCHEMA

    valid_config = {
        CONF_PLATFORM: "climate_ip",
        CONF_CONFIG_FILE: "device.yaml",
        CONF_IP_ADDRESS: "192.168.1.10",
        CONF_TOKEN: "abc",
        CONF_DEVICE_ID: "dev1",
    }
    validated = PLATFORM_SCHEMA(valid_config)
    assert validated[CONF_CONFIG_FILE] == "device.yaml"
    assert validated[CONF_IP_ADDRESS] == "192.168.1.10"
    assert validated[CONF_TOKEN] == "abc"
    assert validated[CONF_DEVICE_ID] == "dev1"