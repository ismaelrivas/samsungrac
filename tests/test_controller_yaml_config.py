import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import ATTR_ENTITY_ID, ATTR_NAME, ATTR_TEMPERATURE
from homeassistant.util.yaml import load_yaml
from voluptuous import Optional

from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    CONFIG_DEVICE_POLL,
    CONN_METHOD_RAW,
    DEFAULT_CONF_TEMP_UNIT,
    DEVICE_TYPE_AIOHTTP_SUPPORTED,
)
from custom_components.climate_ip.controller_yaml_config import (
    _LOGGER,
    _YAML_FILE_CACHE,
    CONST_CONTROLLER_TYPE,
    YamlConfigLoader,
    clear_yaml_cache,
)
from custom_components.climate_ip.properties import TemperatureOperation


class StrictMock(MagicMock):
    def __getattr__(self, name):
        # We only strictly enforce attributes that the controller uses in getattr() calls
        if name in (
            "_yaml",
            "device_id",
            "_config",
            "config",
            "hass",
            "unique_id",
            "_session",
            "ip_address",
            "id",
            "config_validation_type",
            "device_class",
        ):
            # MagicMock stores mocked children in _mock_children or __dict__ depending on how they are set
            if name not in self.__dict__ and name not in self._mock_children:
                raise AttributeError(f"StrictMock: Attribute '{name}' not set!")
        return super().__getattr__(name)


@pytest.fixture
def mock_controller():
    """Provides a dummy controller to host the YamlConfigLoader."""
    controller = MagicMock()
    controller.config = {CONF_CONFIG_FILE: "test.yaml"}
    controller.log_prefix = "[Test]"
    controller.device_id = "dev_123"
    controller.unique_id = "uid_123"
    controller.hass = MagicMock()
    return controller


# ====================================================================================
# FRENTE A: AUTORIDAD PRIMITIVA (Mata los 8 mutantes de __init__)
# ====================================================================================


def test_yaml_config_initial_state():
    """Valida el estado base estricto y la inmunidad del esquema de validación."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    loader = YamlConfigLoader(mock_controller)

    # Kills mutants 5, 10, 11, 12, 13, 14, 16 (Asignaciones a None, "", etc.)
    assert loader.name == CONST_CONTROLLER_TYPE
    assert loader.state_getter is None
    assert loader.connection is None
    assert loader.poll is None
    assert loader.is_fully_initialized is False
    assert loader._parsed_yaml_config is None
    assert isinstance(loader.properties_list, list)
    assert loader.properties_list == []

    # Kills Mutant 9 (vol.Optional(None) instead of ATTR_ENTITY_ID)
    schema_keys = list(loader.service_schema_map.keys())
    assert len(schema_keys) > 0
    # vol.Optional envuelve el valor en la propiedad .schema
    assert schema_keys[0].schema == ATTR_ENTITY_ID


# ====================================================================================
# FRENTE B: RESILIENCIA A YAML FRAGMENTADO (Kills mutants de fallback en .get)
# ====================================================================================


async def test_yaml_config_fragmented_payloads():
    """Fuerza la evaluación de los diccionarios por defecto .get(..., {})."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "target_dev"
    mock_controller.unique_id = "target_dev"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    # Inject un YAML que carece de switches, sensors, attributes y operations
    loader._parsed_yaml_config = {
        "target_dev": {
            "device": {
                # Solo pasamos la raíz, forzando a que fallen todos los ac.get()
            }
        }
    }

    # Mock create_property to catch any creation attempt
    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property"
    ) as mock_create:
        # If a mutant changes .get(CONFIG_DEVICE_SWITCHES, {}) to None,
        # the for loop op_key in nodes.keys() will explode with AttributeError
        try:
            await loader.async_finish_initialization()
        except AttributeError:
            pytest.fail("Broken fallback: Mutant caused AttributeError in iterator.")

        # We assert that no ghost property was attempted to be created
        mock_create.assert_not_called()


# ====================================================================================
# FRONT C: CACHE INJECTION AND INITIALIZATION PATHS
# ====================================================================================


async def test_yaml_config_cache_hit_and_miss():
    """Ensures that the YAML cache works and is populated correctly."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "test_dev_1"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    fake_yaml_data = {"device": {"id": "test_dev_1"}}
    loader._parsed_yaml_config = fake_yaml_data

    # 1. Run a Cache Miss
    with patch("custom_components.climate_ip.controller_yaml_config.create_property"):
        await loader.async_finish_initialization()

    # We assert it was saved in the cache with the correct key (Kills mutants of self._parsed_yaml_cache[dev_id])
    assert "test_dev_1" in loader._parsed_yaml_cache
    assert loader._parsed_yaml_cache["test_dev_1"] == fake_yaml_data

    # 2. Corrupt the original base YAML but perform a Cache Hit
    loader._parsed_yaml_config = {"device": {"ESTADO_CORRUPTO": True}}

    # Store previous state of operations
    ops_count = len(loader.operations)

    # Re-initialize
    with patch("custom_components.climate_ip.controller_yaml_config.create_property"):
        await loader.async_finish_initialization()

    assert len(loader.operations) == ops_count


# ====================================================================================
# FRONT D: STRICT ASSERTION OF CONNECTION ARGUMENTS
# ====================================================================================


async def test_async_initialize_connection_instantiation_args():
    """Validates that network engines are instantiated with the exact arguments required."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.log_prefix = "[Test]"

    mock_hass = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock()
    mock_controller.hass = mock_hass

    mock_controller._session = "SESSION_INSTANCE"
    mock_controller.ip_address = "192.168.1.100"
    mock_controller._yaml = "/test.yaml"
    # Force the 'else' branch of the connection type (generic/REST)
    mock_controller._config = {"device_type": "UNKNOWN_GENERIC"}

    loader = YamlConfigLoader(mock_controller)
    yaml_data = {"device": {"connection": {"type": "test_conn_type"}}}
    loader._parsed_yaml_config = yaml_data
    _YAML_FILE_CACHE["/test.yaml"] = yaml_data

    # Create a strict interceptor that is not a permissive MagicMock
    class InterceptorConnection:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        @classmethod
        def match_type(cls, conn_type):
            return conn_type == "test_conn_type"

        def load_from_yaml(self, node, state_getter):
            return True

    # Inject our connection class to audit arguments
    with patch(
        "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
        [InterceptorConnection],
    ):
        await loader.async_initialize()

        # Autopsy of the instantiation (Kills mutants that omit hass, config, or change arguments)
        assert loader.connection is not None
        assert loader.connection.args[0] == mock_controller._config
        assert loader.connection.kwargs.get("hass") == mock_hass


# ====================================================================================
# FRONT E: THERMODYNAMIC UNITS FIREWALL (Temperature Fallbacks)
# ====================================================================================


async def test_async_finish_initialization_temperature_fallbacks():
    """Forces the absence of HASS dependencies to assert the use of default units."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "temp_device_test"
    # 1. Remove the hass object entirely
    if hasattr(mock_controller, "hass"):
        delattr(mock_controller, "hass")

    mock_controller._config = {}

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    # Inject a simulated YAML
    loader._parsed_yaml_config = {
        "device": {"operations": {"target_temp": {"type": "temperature"}}}
    }

    # Create a mock property that logs unit calls
    mock_prop = StrictMock()
    mock_prop.id = "temperature"
    mock_prop.device_class = "temperature"  # Force is_temp check

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        return_value=mock_prop,
    ):
        await loader.async_finish_initialization()

        # Since there is no HASS or config_entries, the code MUST use DEFAULT_CONF_TEMP_UNIT
        # This destroys mutants that alter the initial assignment of `configured_unit`
        # and `native_target_unit`
        mock_prop.set_hass_unit.assert_called_once_with(DEFAULT_CONF_TEMP_UNIT)
        mock_prop.set_device_unit.assert_called_with(DEFAULT_CONF_TEMP_UNIT)


# ====================================================================================
# FRONT F: STRICT FACTORY AND DEDUPLICATION ASSERTION
# ====================================================================================


async def test_async_finish_initialization_strict_factory_args():
    """Validates that create_property receives its 5 arguments intact and asserts unique lists."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "test_dev"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    loader.connection = "STRICT_CONN"
    loader.state_getter = "STRICT_GETTER"

    # Malicious YAML: Pass 'target_op' in operations AND attributes to force ID collision
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"target_op": {"type": "A"}},
            "attributes": {"target_op": {"type": "B"}},  # Intentional duplicate
            "sensors": {"target_sensor": {"type": "C"}},
        }
    }

    # Strict interceptor to simulate property creation
    def fake_create(key, node, conn, ctrl, getter):
        prop = MagicMock()
        prop.id = key
        prop.config_validation_type = str
        return prop

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ) as mock_create:
        await loader.async_finish_initialization()

        # 1. RIGID ARGUMENT ASSERTION (Kills mutants 32 to 118)
        # If mutmut changes `self.state_getter` to `None` in production code, this will explode
        mock_create.assert_any_call(
            "target_op", {"type": "A"}, "STRICT_CONN", mock_controller, "STRICT_GETTER"
        )
        mock_create.assert_any_call(
            "target_sensor",
            {"type": "C"},
            "STRICT_CONN",
            mock_controller,
            "STRICT_GETTER",
        )

        # 2. LIST DEDUPLICATION ASSERTION
        # If mutmut changes `if op_id not in self.operations_list` to `in`, there will be duplicates or missing items
        assert loader.operations_list.count("target_op") == 1
        assert "target_sensor" in loader.sensors_list


# ====================================================================================
# FRONT G: THE INFERNAL CASCADE OF FALLBACKS (.get and getattr)
# ====================================================================================


async def test_async_initialize_fallback_cascades():
    """Forces nonexistent attributes and dictionaries to evaluate {} fallbacks."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"

    # Destroy configuration attributes atomically
    if hasattr(mock_controller, "_config"):
        delattr(mock_controller, "_config")
    if hasattr(mock_controller, "config"):
        delattr(mock_controller, "config")

    loader = YamlConfigLoader(mock_controller)

    # Empty YAML at root (Kills mutations of `ac = yaml_device.get(CONFIG_DEVICE, {})`)
    loader._parsed_yaml_config = {}

    try:
        # If a mutant mutated `{}` to `None`, it will fail catastrophically here
        await loader.async_initialize()
    except AttributeError as e:
        pytest.fail(f"The fallback cascade was corrupted by a mutant: {e}")


# ====================================================================================
# FRONT H: DUCK-TYPING VS INHERITANCE (The Thermodynamic Engine)
# ====================================================================================


async def test_async_finish_initialization_apply_unit_polymorphism():
    """Asserts que apply_unit distingue correctamente mediante isinstance y device_class."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = {"device": {}}

    # Propiedad 1: Basura (No debe recibir unidades)
    prop_other = StrictMock()
    prop_other.device_class = "power"
    prop_other.id = "power_switch"

    # Property 2: Duck-Typing Temperature (Verify mutant kill of == "temperature")
    prop_duck = StrictMock()
    prop_duck.device_class = "temperature"
    prop_duck.id = "target_temperature"

    # Property 3: Strict Inheritance Temperature (Verify mutant kill of isinstance)
    prop_isinstance = StrictMock(spec=TemperatureOperation)
    prop_isinstance.id = "current_temperature"

    # Inject into the loader, skipping YAML parsing
    loader.properties = {"p1": prop_other, "p2": prop_duck, "p3": prop_isinstance}

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property"
    ):  # Silence external calls
        await loader.async_finish_initialization()

    # Precision assertions (apply_unit method should have iterated over loader.properties)
    prop_other.set_hass_unit.assert_not_called()
    prop_duck.set_hass_unit.assert_called_once()
    prop_isinstance.set_hass_unit.assert_called_once()


# ====================================================================================
# FRONT I: ASYMMETRIC IDENTITY TRAP (op_key vs op.id)
# ====================================================================================


async def test_async_finish_initialization_asymmetric_id_fallback():
    """Validates that if op.id exists, op_key is NOT used. Kills getattr('id') mutants."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    # Inject dictionaries with YAML keys that are DIFFERENT from the property's real ID
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"yaml_op_key": {"type": "A"}},
            "switches": {"yaml_switch_key": {"type": "B"}},
            "attributes": {"yaml_attr_key": {"type": "C"}},
            "sensors": {
                "yaml_sensor_key": {"type": "D"}
            },  # Sensors uses the 'name' variable
        }
    }
    loader._parsed_yaml_cache = {"": loader._parsed_yaml_config}

    def fake_create(key, node, conn, ctrl, getter):
        prop = MagicMock()
        # Internal ID is different from YAML key
        prop.id = f"real_id_for_{key}"
        return prop

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ):
        await loader.async_finish_initialization()

        # If mutmut changes getattr(op, "id", op_key) to getattr(op, "XXidXX", op_key),
        # the lists will register "yaml_op_key" instead of "real_id_for_yaml_op_key", and the test will explode.
        assert "real_id_for_yaml_op_key" in loader.operations
        assert "yaml_op_key" not in loader.operations

        assert "real_id_for_yaml_switch_key" in loader.operations
        assert "real_id_for_yaml_attr_key" in loader.properties


# ====================================================================================
# FRONT J: DEEP INJECTION OF CONFIG ENTRIES (HASS Options)
# ====================================================================================


async def test_async_finish_initialization_config_entry_options():
    """Forces unit evaluation and network engines through entry.options."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    # Inject entry_id
    mock_controller._config = {
        "entry_id": "test_entry_777",
        "device_type": "samsung_8888",
    }

    # Prepare Home Assistant Mock to return a ConfigEntry
    mock_entry = MagicMock()
    mock_entry.options = {
        CONF_CONN_METHOD: "raw",
        CONF_TEMP_NATIVE_CURRENT: "Kelvin",
        CONF_TEMP_NATIVE_TARGET: "Fahrenheit",
    }
    mock_controller.hass.config_entries.async_get_entry.return_value = mock_entry

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = {
        "device": {
            "operations": {
                "temp_op": {"type": "temperature"}
            },  # Triggers TemperatureOperation
            "connection": {},
        }
    }
    loader._parsed_yaml_cache = {"": loader._parsed_yaml_config}

    mock_temp_prop = StrictMock()
    mock_temp_prop.device_class = "temperature"
    mock_temp_prop.id = "temperature"

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        return_value=mock_temp_prop,
    ):
        await loader.async_finish_initialization()

        # 1. Unit Validation (Kills mutants of entry.options.get(CONF_TEMP...))
        mock_temp_prop.set_device_unit.assert_called_with("Fahrenheit")

    # Validate the connection part by executing async_initialize
    class DummySamsungConn:
        def __init__(self, *args, **kwargs):
            pass

        @classmethod
        def match_type(cls, conn_type):
            return conn_type == "samsung_8888_raw"

        def load_from_yaml(self, node, state_getter):
            return True

    with patch(
        "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
        [DummySamsungConn],
    ):
        # Prevent load_yaml check failing by using absolute path or mocking cache
        mock_controller._yaml = "/test_j.yaml"
        _YAML_FILE_CACHE["/test_j.yaml"] = loader._parsed_yaml_config

        await loader.async_initialize()
        # Must have extracted "raw" from ConfigEntry options and created the connection
        assert isinstance(loader.connection, DummySamsungConn)


# ====================================================================================
# FRONT K: SHORT CIRCUITS AND EARLY EXITS
# ====================================================================================


@pytest.mark.asyncio
async def test_async_finish_initialization_early_exits(mock_controller) -> None:
    """Annihilates Family B (Mutants 1, 6, 12) with a trap exception."""
    loader = YamlConfigLoader(mock_controller)

    # Prepare a trap: If the function does NOT exit early,
    # it will try to read CONFIG_DEVICE and eventually call create_property.
    # We deliberately break internal state so any progress will explode violently.
    loader._parsed_yaml_config = {"device": {"operations": {"trap": {}}}}

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=RuntimeError("TRAP: Should not have advanced"),
    ):
        # 1. Exit early if already initialized (BUT there is valid config)
        loader.is_fully_initialized = True
        try:
            await loader.async_finish_initialization()
        except RuntimeError:
            pytest.fail(
                "Mutant 1 survived: The 'or' block was mutated to 'and' and did not exit early."
            )

        # 2. Exit early if NO valid config (BUT it is not initialized)
        loader.is_fully_initialized = False
        loader._parsed_yaml_config = None
        try:
            await loader.async_finish_initialization()
        except RuntimeError:
            pytest.fail(
                "Mutant 1 survived: The 'or' block was mutated to 'and' and did not exit early."
            )

        # 3. Check safe use of getattr on device_id mutated to "XXXX" (Mutants 6, 12)
        del mock_controller.device_id
        loader._parsed_yaml_config = {"device": {}}
        loader._parsed_yaml_cache = {"": {"device": {"name": "cached_device"}}}
        # Since there are no operations, it won't trigger the trap, but we verify it doesn't cause an AttributeError
        await loader.async_finish_initialization()


@pytest.mark.asyncio
async def test_async_finish_initialization_idempotency(mock_controller) -> None:
    """Annihilates Family A (Mutants 49, 50, 88, 89...) preventing StopIteration."""
    loader = YamlConfigLoader(mock_controller)

    # Isolate ONLY the operations block so we don't exhaust side_effect
    loader._parsed_yaml_config = {"device": {"operations": {"op_1": {}, "op_2": {}}}}
    loader._parsed_yaml_cache = {"dev_123": loader._parsed_yaml_config}
    loader.connection = MagicMock()
    loader.state_getter = MagicMock()

    mock_prop_1 = MagicMock()
    mock_prop_1.id = "shared_id"
    mock_prop_2 = MagicMock()
    mock_prop_2.id = "shared_id"

    # Return Mocks for 'operations' and then None for anything else trying to parse (switches, attributes)
    def create_property_mock(*args, **kwargs):
        if args[0] == "op_1":
            return mock_prop_1
        if args[0] == "op_2":
            return mock_prop_2
        return None

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=create_property_mock,
    ):
        await loader.async_finish_initialization()

        assert loader.operations_list == [
            "shared_id"
        ], "Protection against duplicate IDs failed."
        assert loader.operations["shared_id"] is mock_prop_2


@pytest.mark.asyncio
async def test_apply_temperature_units_master_matrix() -> None:
    """Annihilates Family C and dictionary fallbacks (Mutants 167-253)."""

    # Matrix: (entry_options, entry_data, expected_target, expected_current)
    matrix = [
        # 1. Everything in options (The happy path)
        (
            {CONF_TEMP_NATIVE_TARGET: "°K", CONF_TEMP_NATIVE_CURRENT: "°F"},
            {},
            "°K",
            "°F",
        ),
        # 2. Everything in data (Fallback of options to data)
        (
            {},
            {CONF_TEMP_NATIVE_TARGET: "°K", CONF_TEMP_NATIVE_CURRENT: "°F"},
            "°K",
            "°F",
        ),
        # 3. Absolute empty (Fallback to default display unit)
        (
            {},
            {},
            "°C",
            "°C",  # °C is our mock for hass.config.units.temperature_unit
        ),
    ]

    for opts, data, exp_target, exp_current in matrix:
        # Total isolation
        mock_controller = MagicMock()
        mock_controller.config = {"entry_id": "123"}
        mock_controller.log_prefix = "[Test]"
        mock_controller._yaml = "test.yaml"
        mock_controller.hass = MagicMock()
        mock_controller.hass.config.units.temperature_unit = "°C"

        mock_entry = MagicMock()
        mock_entry.options = opts
        mock_entry.data = data
        mock_controller.hass.config_entries.async_get_entry.return_value = mock_entry

        loader = YamlConfigLoader(mock_controller)
        loader._parsed_yaml_config = {"device": {}}
        loader._parsed_yaml_cache = {"dev_123": loader._parsed_yaml_config}

        # General sensor (Not temperature)
        general_sensor = MagicMock()
        general_sensor.device_class = "humidity"

        # Generic temperature sensor
        current_temp = MagicMock()
        current_temp.device_class = "temperature"
        current_temp.id = "current_temperature"

        # Operación específica de target
        target_temp = MagicMock()
        target_temp.device_class = "temperature"
        target_temp.id = ATTR_TEMPERATURE

        loader.sensors = {"humidity_sensor": general_sensor}
        loader.operations = {
            ATTR_TEMPERATURE: target_temp,
            "current_temperature": current_temp,
        }

        await loader.async_finish_initialization()

        # Aserciones Letales
        general_sensor.set_unit_of_measurement.assert_not_called()

        target_temp.set_hass_unit.assert_called_once_with("°C")
        target_temp.set_device_unit.assert_called_once_with(exp_target)

        current_temp.set_hass_unit.assert_called_once_with("°C")
        current_temp.set_device_unit.assert_called_once_with(exp_current)


@pytest.mark.asyncio
async def test_apply_temperature_units_no_hass() -> None:
    """Kills mutants que dependen de hasattr(self.controller, 'hass')."""
    # Escenario donde hass NO existe
    mock_controller = MagicMock()
    mock_controller.config = {}
    mock_controller.log_prefix = "[Test]"
    mock_controller.hass = None

    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_config = {"device": {}}
    loader._parsed_yaml_cache = {"dev_123": loader._parsed_yaml_config}

    target_temp = MagicMock()
    target_temp.device_class = "temperature"
    target_temp.id = ATTR_TEMPERATURE
    loader.operations = {ATTR_TEMPERATURE: target_temp}

    await loader.async_finish_initialization()

    # Sin HASS, debe caer al DEFAULT_CONF_TEMP_UNIT global (que importamos como DEFAULT_CONF_TEMP_UNIT)
    target_temp.set_hass_unit.assert_called_once_with(DEFAULT_CONF_TEMP_UNIT)
    target_temp.set_device_unit.assert_called_once_with(DEFAULT_CONF_TEMP_UNIT)


# ====================================================================================
# FRENTE L: LA PURGA DE LAS 4 DIMENSIONES (Operations, Switches, Attributes, Sensors)
# ====================================================================================


async def test_async_finish_initialization_all_loops_exhaustive():
    """Fuerza la asimetría de IDs y el parseo en las 4 listas del loader para matar bucles espejo."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "test_dev_loops"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    # Inject datos en TODAS las categorías simultáneamente
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"yaml_op": {"type": "A"}},
            "switches": {"yaml_sw": {"type": "B"}},
            "attributes": {"yaml_attr": {"type": "C"}},
            "sensors": {"yaml_sen": {"type": "D"}},
        }
    }
    loader._parsed_yaml_cache = {}

    # Generador asimétrico de propiedades
    def fake_create(key, node, conn, ctrl, getter):
        prop = MagicMock()
        prop.id = f"real_{key}"  # Asimetría para matar getattr(..., "id", key)
        prop.config_validation_type = str
        return prop

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ):
        await loader.async_finish_initialization()

        # Aserciones implacables de mapeo y deduplicación (Kills mutants 42-135)
        assert "real_yaml_op" in loader.operations
        assert "real_yaml_sw" in loader.operations
        assert "real_yaml_attr" in loader.properties
        assert "yaml_sen" in loader.sensors

        # Validamos que las listas de deduplicación se llenaron (Mata "if op_id not in...")
        assert "real_yaml_sw" in loader.operations_list
        assert "real_yaml_attr" in loader.properties_list
        assert "yaml_sen" in loader.sensors_list

        assert (
            loader.is_fully_initialized is True
        ), "El loader no levantó la bandera de inicialización completa"


# ====================================================================================
# FRENTE M: LA CASCADA DE CONFIGURACIÓN PRIVADA/PÚBLICA (_config vs config)
# ====================================================================================


async def test_async_initialize_config_fallback_cascade():
    """Fuerza la ejecución del getattr anidado eliminando _config y usando config."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    # 1. Destruimos el atributo privado para obligar a usar el público
    if hasattr(mock_controller, "_config"):
        delattr(mock_controller, "_config")

    # 2. Asignamos el atributo público
    mock_controller.config = {CONF_DEVICE_TYPE: "samsung_2878"}

    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_config = {"device": {}}

    mock_controller._yaml = "/test_m.yaml"
    _YAML_FILE_CACHE["/test_m.yaml"] = loader._parsed_yaml_config

    await loader.async_initialize()

    # If mutmut alteró getattr(..., "config", {}), el device_type será None
    # y no entrará en la rama de samsung_2878, por lo que connection_node fallará.
    assert type(loader.connection).__name__ == "ConnectionSamsung2878"


# ====================================================================================
# FRENTE N: EL RESCATE DE ENTRY.DATA (Unidades Térmicas)
# ====================================================================================


async def test_async_finish_initialization_entry_data_fallback():
    """Evalúa la extracción de unidades cuando options está vacío pero data existe."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller._config = {"entry_id": "test_entry"}

    # Opciones vacías, Data lleno (Kills mutants 200-208)
    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {
        CONF_TEMP_NATIVE_CURRENT: "Kelvin",
        CONF_TEMP_NATIVE_TARGET: "Rankine",
    }
    mock_controller.hass.config_entries.async_get_entry.return_value = mock_entry

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False
    loader._parsed_yaml_config = {
        "device": {"operations": {"t": {"type": "temperature"}}}
    }
    loader._parsed_yaml_cache = {"": loader._parsed_yaml_config}

    mock_prop = StrictMock()
    mock_prop.device_class = "temperature"
    mock_prop.id = ATTR_TEMPERATURE

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        return_value=mock_prop,
    ):
        await loader.async_finish_initialization()

        # Debe haber extraído los valores del diccionario .data porque .options estaba vacío
        # If mutmut cambia .data.get(..., def) a None, esta aserción explotará
        mock_prop.set_device_unit.assert_any_call("Rankine")


# ====================================================================================


# ====================================================================================
# FRENTE O: LA PARADOJA DE LA CACHÉ FANTASMA
# ====================================================================================
async def test_async_initialize_frente_o():
    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller._yaml = "/test_o.yaml"
    mock_controller.device_id = "target_dev"
    mock_controller.unique_id = "target_dev"
    mock_controller.hass = MagicMock()

    async def mock_async_add_executor_job(*args, **kwargs):
        return args[0](*args[1:], **kwargs)

    mock_controller.hass.async_add_executor_job = mock_async_add_executor_job

    _YAML_FILE_CACHE["/test_o.yaml"] = {
        "device": {"connection": {"type": "request"}, "token": "test"}
    }
    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_config = None

    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml",
        return_value={"device": {"dummy": "data"}},
    ):
        with patch(
            "custom_components.climate_ip.connection_request.ConnectionRequest.load_from_yaml",
            return_value=True,
        ):
            with patch(
                "custom_components.climate_ip.controller_yaml_config.create_status_getter",
                return_value=MagicMock(),
            ):
                await loader.async_initialize()
                assert loader.connection is not None


# ====================================================================================
# FRONT D: STRICT ASSERTION OF CONNECTION ARGUMENTS
# ====================================================================================
async def test_async_initialize_connection_instantiation_args_frente_d():
    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.hass = MagicMock()
    mock_controller._session = "SESSION_INSTANCE"
    mock_controller.ip_address = "192.168.1.100"
    mock_controller._yaml = "/test_d.yaml"
    mock_controller.unique_id = "test_d"
    mock_controller._config = {"device_type": "samsung_8888"}

    async def mock_async_add_executor_job(*args, **kwargs):
        return args[0](*args[1:], **kwargs)

    mock_controller.hass.async_add_executor_job = mock_async_add_executor_job

    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_cache = {}

    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml",
        return_value={"device": {"connection": {"type": "aiohttp"}}},
    ):
        with patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ):
            with patch(
                "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS"
            ) as mock_connections:
                mock_conn_class = MagicMock()
                mock_conn_class.__name__ = "ConnectionAiohttp8888"
                mock_conn_class.match_type.return_value = True

                # Mock the instance returned by the class
                mock_conn_instance = MagicMock()
                mock_conn_instance.load_from_yaml.return_value = True
                mock_conn_class.return_value = mock_conn_instance

                mock_connections.__iter__.return_value = [mock_conn_class]

                await loader.async_initialize()

                # In config_aiohttp, the signature is (merged_config, logger, hass, session, ip)
                merged_config = {
                    "device_type": "samsung_8888",
                    "type": "samsung_8888_aiohttp",
                }
                mock_conn_class.assert_called_once_with(
                    merged_config,
                    _LOGGER,
                    mock_controller.hass,
                    mock_controller._session,
                    mock_controller.ip_address,
                )


# ====================================================================================
# FRENTE P: VALIDACIÓN CV.STRING Y CASCADAS SECUNDARIAS
# ====================================================================================
async def test_async_finish_initialization_frente_p():
    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.hass = MagicMock()
    mock_controller.device_id = "dev_p"

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    # Proveemos operaciones, switches, atributos y sensors para que se aserten todos los bucles
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"op1": {}},
            "switches": {"sw1": {}},
            "attributes": {"attr1": {"unit_of_measurement": "custom_unit"}},
            "sensors": {"sen1": {}},
        }
    }
    loader._parsed_yaml_cache = {}

    def fake_create(key, node, conn, ctrl, getter):
        prop = StrictMock()
        # Claves distintas para deduplicar
        prop.id = f"real_{key}"
        prop.config_validation_type = "cv_boolean"

        # Soportamos el getattr de device_class
        if key == "attr1":
            prop.device_class = "sensor"  # ¡EVITA que entre al if is_temp!
        else:
            prop.device_class = "temperature"

        if key == "attr1":
            prop.set_unit_of_measurement = MagicMock()

        # Soportamos la asignación de unidades
        prop.set_hass_unit = MagicMock()
        prop.set_device_unit = MagicMock()
        return prop

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ):
        await loader.async_finish_initialization()

        # 1. We assert cv_boolean (mata mutantes 59-60, 97-99)
        # Las claves en service_schema_map son Optional("real_op1"), etc.
        assert loader.service_schema_map[Optional("real_op1")] == "cv_boolean"
        assert loader.service_schema_map[Optional("real_sw1")] == "cv_boolean"

        # 2. We assert unit_of_measurement method (mata 132-135)
        attr1_mock = loader.properties["real_attr1"]
        attr1_mock.set_unit_of_measurement.assert_called_once_with("custom_unit")

        # 3. We assert asimetría en operaciones (mata 49-53, 87-94)
        assert "real_sw1" in loader.operations_list
        assert "real_attr1" in loader.properties_list
        assert "sen1" in loader.sensors_list

        assert (
            loader.is_fully_initialized is True
        ), "El loader no levantó la bandera de inicialización completa"


# ====================================================================================
# FRENTE R: CASCADAS DE CONFIGURATION HASS UNITS Y ENTRY.OPTIONS
# ====================================================================================
async def test_async_finish_initialization_frente_r():
    mock_controller = StrictMock()
    mock_controller.log_prefix = "[Test]"
    mock_controller.device_id = "dev_r"
    mock_controller._config = {"entry_id": "test_entry"}

    mock_hass = MagicMock()
    # Para configured_unit = self.controller.hass.config.units.temperature_unit
    mock_hass.config.units.temperature_unit = "Fahrenheit"
    mock_controller.hass = mock_hass

    # Mock entry para que devuelva algo distinto en options vs data
    mock_entry = MagicMock()
    mock_entry.options = {
        CONF_TEMP_NATIVE_CURRENT: "OptionsCurrent",
        CONF_TEMP_NATIVE_TARGET: "OptionsTarget",
    }
    mock_hass.config_entries.async_get_entry.return_value = mock_entry

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    loader._parsed_yaml_config = {"device": {"operations": {"temp_op": {}}}}
    loader._parsed_yaml_cache = {}

    def fake_create(key, node, conn, ctrl, getter):
        prop = StrictMock()
        prop.id = "real_temp_op"
        prop.device_class = "temperature"
        prop.config_validation_type = "cv_string"
        prop.set_hass_unit = MagicMock()
        prop.set_device_unit = MagicMock()
        return prop

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ):
        await loader.async_finish_initialization()

        mock_op = loader.operations["real_temp_op"]
        # We assert units_temperature_unit
        mock_op.set_hass_unit.assert_called_once_with("Fahrenheit")
        # We assert options de native target
        mock_op.set_device_unit.assert_called_once_with("OptionsCurrent")


@pytest.mark.asyncio
async def test_async_initialize_sync_fallback(mock_controller) -> None:
    """Kills mutants 34-46 comprobando el fallback a load_yaml síncrono si hass es None."""
    mock_controller.hass = None  # Forzamos la rama síncrona
    mock_controller._yaml = (
        "test.yaml"  # El código lee directamente getattr(controller, "_yaml")
    )

    loader = YamlConfigLoader(mock_controller)

    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml"
    ) as mock_load:
        # YAML must contain CONFIG_DEVICE (device) y CONFIG_DEVICE_STATUS (status) to avoid early exit
        mock_load.return_value = {
            "device": {"connection": {"type": "test"}, "status": {}}
        }

        # Mock create_status_getter para no depender de la clase base real
        with patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ):
            await loader.async_initialize()

            expected_path = str(
                Path(
                    sys.modules[
                        "custom_components.climate_ip.controller_yaml_config"
                    ].__file__
                ).parent
                / "test.yaml"
            )
            mock_load.assert_called_once_with(expected_path)


@pytest.mark.asyncio
async def test_async_initialize_poll_parsing() -> None:
    """Kills mutants 270-294 bombardeando el parser de CONFIG_DEVICE_POLL con aislamiento total."""

    test_cases = [
        ("true", True),
        ("True", True),
        ("false", False),
        ("False", False),
        ("auto", None),
        (None, None),
        ("", None),
    ]

    for poll_str, expected_poll in test_cases:
        # Aislamiento Total Nivel 0: Purgar el caché del módulo
        clear_yaml_cache()

        # Aislamiento Total Nivel 1: Nuevo Controlador Mock
        mock_controller = MagicMock()
        mock_controller.config = {CONF_CONFIG_FILE: "test.yaml"}
        mock_controller.log_prefix = "[Test]"
        mock_controller.device_id = "dev_123"
        mock_controller.unique_id = "uid_123"
        mock_controller._yaml = "test.yaml"
        mock_controller.hass = None

        # Aislamiento Total Nivel 2: Nuevo Loader
        loader = YamlConfigLoader(mock_controller)
        loader.poll = None  # Forzamos reinicio explícito por si acaso

        yaml_data = {"device": {"connection": {"type": "test_type"}, "status": {}}}
        if poll_str is not None:
            yaml_data["device"][CONFIG_DEVICE_POLL] = poll_str

        mock_conn_class = MagicMock()
        mock_conn_class.match_type.return_value = True
        mock_conn_class.__name__ = "MockConnection"

        mock_conn_instance = MagicMock()
        mock_conn_instance.load_from_yaml.return_value = True
        # EVITAMOS que el mock tenga un atributo 'poll' que pueda interferir mágicamente
        del mock_conn_instance.poll
        mock_conn_class.return_value = mock_conn_instance

        with (
            patch(
                "custom_components.climate_ip.controller_yaml_config.load_yaml",
                return_value=yaml_data,
            ),
            patch(
                "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
                [mock_conn_class],
            ),
            patch(
                "custom_components.climate_ip.controller_yaml_config.create_status_getter",
                return_value=MagicMock(),
            ),
        ):
            result = await loader.async_initialize()

            assert result is True, f"Abortado prematuramente para {poll_str}"
            assert (
                loader.poll is expected_poll
            ), f"Falló el parsing para '{poll_str}'. Esperado {expected_poll}, Obtuvo {loader.poll}"


@pytest.mark.asyncio
async def test_async_finish_initialization_property_creation(mock_controller) -> None:
    """Kills mutants by asserting strict create_property signature and logical schemas."""
    loader = YamlConfigLoader(mock_controller)

    loader._parsed_yaml_config = {
        "device": {
            "attributes": {  # Usamos atributos porque ese bloque ejecuta el set_unit_of_measurement
                "test_attr": {"unit_of_measurement": "C"}
            }
        }
    }
    loader._parsed_yaml_cache = {"dev_123": loader._parsed_yaml_config}
    loader.connection = MagicMock()
    loader.state_getter = MagicMock()

    # MOCK MAGICO AVANZADO PARA PASAR hasattr()
    class MockProp:
        def __init__(self):
            self.set_unit_of_measurement = MagicMock()

        @property
        def id(self):
            raise AttributeError("Forzar getattr")

        @property
        def config_validation_type(self):
            raise AttributeError("Forzar getattr")

    mock_prop = MockProp()

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        return_value=mock_prop,
    ) as mock_create:
        await loader.async_finish_initialization()

        mock_create.assert_any_call(
            "test_attr",
            {"unit_of_measurement": "C"},
            loader.connection,
            loader.controller,
            loader.state_getter,
        )

        assert "test_attr" in loader.properties
        mock_prop.set_unit_of_measurement.assert_called_once_with("C")


@pytest.mark.asyncio
async def test_apply_temperature_units_logic(mock_controller) -> None:
    """Kills mutants 167-266 forzando la lógica diferencial de ATTR_TEMPERATURE vs Otros."""
    loader = YamlConfigLoader(mock_controller)

    # Configuramos el ConfigEntry mockeado para tener options puras
    mock_entry = MagicMock()
    mock_entry.options = {CONF_TEMP_NATIVE_CURRENT: "°F", CONF_TEMP_NATIVE_TARGET: "°K"}
    mock_controller.config = {"entry_id": "123"}
    mock_controller.hass.config_entries.async_get_entry.return_value = mock_entry
    mock_controller.hass.config.units.temperature_unit = "°C"

    # 1. Sensor Genérico (Debe recibir native_current_unit)
    generic_temp = MagicMock()
    generic_temp.device_class = "temperature"
    generic_temp.id = "room_temp"

    # 2. Operación ATTR_TEMPERATURE (Debe recibir native_target_unit)
    target_temp = MagicMock()
    target_temp.device_class = "temperature"
    target_temp.id = ATTR_TEMPERATURE

    loader.sensors = {"room_temp": generic_temp}
    loader.operations = {ATTR_TEMPERATURE: target_temp}

    loader._parsed_yaml_config = {
        "device": {}
    }  # Para permitir que async_finish ejecute
    await loader.async_finish_initialization()

    # Aserciones Letales:
    generic_temp.set_hass_unit.assert_called_once_with("°C")
    generic_temp.set_device_unit.assert_called_once_with("°F")  # Current

    target_temp.set_hass_unit.assert_called_once_with("°C")
    target_temp.set_device_unit.assert_called_once_with("°K")  # Target


@pytest.mark.asyncio
async def test_async_initialize_yaml_deep_fallbacks(mock_controller) -> None:
    """Kills mutants comprobando las extracciones profundas y defaults reales."""

    # ¡PURGA DEL CACHÉ OBLIGATORIA!
    clear_yaml_cache()

    loader = YamlConfigLoader(mock_controller)
    mock_controller._yaml = "test.yaml"
    mock_controller.hass = None

    # EL TRAMPÓN DE MAGICMOCK: _config se auto-crea como Mock. Hay que sobreescribirlo explícitamente.
    # In addition, dynamically use a valid device type from the real support array.
    test_config = {
        CONF_DEVICE_TYPE: list(DEVICE_TYPE_AIOHTTP_SUPPORTED)[0],
        CONF_CONN_METHOD: "metodo_invalido_para_forzar_else",
    }
    mock_controller._config = test_config  # Mata al MagicMock residual
    mock_controller.config = test_config

    # Inject YAML incompleto PERO CON STATUS para que no aborte en la línea 265
    yaml_data = {
        "device": {
            "status": {}  # Obligatorio para llegar al parsing del nombre y polling
        }
    }

    mock_conn_class = MagicMock()
    # REAL-TIME LETHAL ASSERTION: Only returns True if mutant DID NOT alter string "request"
    mock_conn_class.match_type.side_effect = lambda x: x == "request"
    mock_conn_class.__name__ = "ConnectionUnknown"

    mock_conn_instance = MagicMock()
    mock_conn_instance.load_from_yaml.return_value = True
    mock_conn_class.return_value = mock_conn_instance

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value=yaml_data,
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn_class],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        result = await loader.async_initialize()

        # Lethal assertion: El proceso debe completarse con éxito
        assert (
            result is True
        ), "Falló la inicialización o la clase mock rechazó la cadena mutada"

        # Lethal assertion: El nombre debe ser el default 'yaml' (CONST_CONTROLLER_TYPE)
        assert loader.name == "yaml"


@pytest.mark.asyncio
async def test_async_initialize_explicit_yaml_data(mock_controller) -> None:
    """Kills mutants 260-271 forzando la lectura explícita de nombre y poll del YAML."""

    clear_yaml_cache()
    loader = YamlConfigLoader(mock_controller)
    mock_controller._yaml = "test.yaml"
    mock_controller.hass = None

    # Configuramos un controlador limpio
    mock_controller._config = {
        CONF_DEVICE_TYPE: list(DEVICE_TYPE_AIOHTTP_SUPPORTED)[0],
        CONF_CONN_METHOD: "metodo_invalido_para_forzar_else",
    }
    mock_controller.config = mock_controller._config

    # ESTE ES EL YAML LETAL: Tiene nombre customizado y poll_config
    yaml_data = {
        "device": {
            "status": {},
            ATTR_NAME: "CustomACName",
            "poll": "false",  # Debe forzar loader.poll = False
        }
    }

    mock_conn_class = MagicMock()
    mock_conn_class.match_type.return_value = True
    mock_conn_class.__name__ = "ConnectionUnknown"

    mock_conn_instance = MagicMock()
    mock_conn_instance.load_from_yaml.return_value = True
    mock_conn_class.return_value = mock_conn_instance

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value=yaml_data,
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn_class],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        result = await loader.async_initialize()

        assert result is True
        # If mutant cambia self.name = None o self.name = ac.get(ATTR_NAME, ), esta aserción reventará
        assert loader.name == "CustomACName"
        # If mutant muta poll_config o lo pone en upper(), esta aserción reventará
        assert loader.poll is False


@pytest.mark.asyncio
async def test_async_initialize_executor_job(mock_controller) -> None:
    """Kills mutants 36, 38 probando la delegación al executor."""

    clear_yaml_cache()

    loader = YamlConfigLoader(mock_controller)
    mock_controller._yaml = "test.yaml"

    # Create un mock para el hass que registre las llamadas al executor
    mock_controller.hass = AsyncMock()
    mock_controller.hass.async_add_executor_job.return_value = {
        "device": {"status": {}, "connection": {"type": "test_executor"}}
    }

    mock_conn_class = MagicMock()
    mock_conn_class.match_type.return_value = True
    mock_conn_class.__name__ = "MockConnection"
    mock_conn_instance = MagicMock()
    mock_conn_class.return_value = mock_conn_instance

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn_class],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        # Disable el parcheo de load_yaml para que intente pasar la función real al executor
        await loader.async_initialize()

        # Lethal assertion: Executor was invoked with exact function and path
        expected_path = str(
            Path(
                sys.modules[
                    "custom_components.climate_ip.controller_yaml_config"
                ].__file__
            ).parent
            / "test.yaml"
        )
        mock_controller.hass.async_add_executor_job.assert_called_once_with(
            load_yaml, expected_path
        )


@pytest.mark.asyncio
async def test_async_initialize_connection_raw8888_args(mock_controller) -> None:
    """Kills mutants 113-127 (Untested) forzando y auditando la ruta ConnectionRaw8888."""
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.const import CONF_CONN_METHOD, CONF_DEVICE_TYPE
    from custom_components.climate_ip.controller_yaml_config import (
        _LOGGER,
        YamlConfigLoader,
    )

    # Inyección táctica de dependencias para RAW (usando constantes estrictas)
    mock_controller._config = {
        CONF_DEVICE_TYPE: "samsung_8888",
        CONF_CONN_METHOD: CONN_METHOD_RAW,
    }
    mock_controller.config = (
        mock_controller._config
    )  # Sincronizamos para el getattr anidado
    mock_controller._session = "RAW_SESSION_OBJECT"
    mock_controller.ip_address = "10.0.0.99"
    mock_controller._yaml = "test_raw.yaml"

    # Inject una corrutina real para simular el executor de Home Assistant
    async def mock_async_add_executor_job(*args, **kwargs):
        return args[0](*args[1:], **kwargs)

    mock_controller.hass.async_add_executor_job = mock_async_add_executor_job

    loader = YamlConfigLoader(mock_controller)
    loader._parsed_yaml_cache = {}

    yaml_data = {"device": {"connection": {"type": "samsung_8888_raw"}, "status": {}}}

    class MockRawConn:
        def __init__(self, *args, **kwargs):
            self.args = args  # Capturamos los argumentos del constructor

        @classmethod
        def match_type(cls, conn_type):
            return conn_type == "samsung_8888_raw"

        def load_from_yaml(self, node, getter):
            return True

    # Suplantamos el nombre de la clase para engañar al if conn_class.__name__ == "ConnectionRaw8888"
    MockRawConn.__name__ = "ConnectionRaw8888"

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value=yaml_data,
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [MockRawConn],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        await loader.async_initialize()

        # Aserciones Letales de la firma del constructor
        assert isinstance(
            loader.connection, MockRawConn
        ), "El motor RAW no fue instanciado"
        # Firma esperada: (controller_config, _LOGGER, hass, _session, ip_address)
        assert loader.connection.args[0] == mock_controller._config
        assert loader.connection.args[1] == _LOGGER
        assert loader.connection.args[2] == mock_controller.hass
        assert loader.connection.args[3] == "RAW_SESSION_OBJECT"
        assert loader.connection.args[4] == "10.0.0.99"


@pytest.mark.asyncio
async def test_async_finish_initialization_state_flag(mock_controller) -> None:
    """Kills mutants 119-120 asertando la bandera is_fully_initialized estrictamente."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False  # Partimos de estado base

    # Proveemos lo mínimo viable para que atraviese el método sin early exits
    loader._parsed_yaml_config = {"device": {}}
    loader._parsed_yaml_cache = {mock_controller.device_id: loader._parsed_yaml_config}

    await loader.async_finish_initialization()

    # Lethal assertion: If mutmut cambia = True por = False en la línea 417, esto detonará.
    assert (
        loader.is_fully_initialized is True
    ), "INFRACCIÓN: La bandera de inicialización no fue levantada."
