from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from voluptuous import Optional


from custom_components.climate_ip.controller_yaml_config import (
    YamlConfigLoader,
    clear_yaml_cache,
    CONST_CONTROLLER_TYPE,
    _YAML_FILE_CACHE,
    _LOGGER,
)

from custom_components.climate_ip.properties import TemperatureOperation
from homeassistant.util.yaml import load_yaml

from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_TYPE,
    CONF_CONN_METHOD,
    CONN_METHOD_RAW,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_TEMP_UNIT,
    CONFIG_DEVICE_POLL,
    DEVICE_TYPE_AIOHTTP_SUPPORTED,
)

from homeassistant.const import ATTR_TEMPERATURE, ATTR_ENTITY_ID, ATTR_NAME


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

    # Mata el Mutante 9 (vol.Optional(None) en lugar de ATTR_ENTITY_ID)
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

    # Mock create_property para atrapar cualquier intento de creación
    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property"
    ) as mock_create:
        # Si un mutante cambia .get(CONFIG_DEVICE_SWITCHES, {}) a None,
        # el bucle for op_key in nodes.keys() explotará con AttributeError
        try:
            await loader.async_finish_initialization()
        except AttributeError:
            pytest.fail("Fallback roto: Mutante provocó AttributeError en iterador.")

        # We assert que no se intentó crear ninguna propiedad fantasma
        mock_create.assert_not_called()


# ====================================================================================
# FRENTE C: INYECCIÓN DE LA CACHÉ Y RUTAS DE INICIALIZACIÓN
# ====================================================================================


async def test_yaml_config_cache_hit_and_miss():
    """Garantiza que la caché del YAML funciona y se puebla correctamente."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "test_dev_1"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    fake_yaml_data = {"device": {"id": "test_dev_1"}}
    loader._parsed_yaml_config = fake_yaml_data

    # 1. Ejecutamos un Cache Miss
    with patch("custom_components.climate_ip.controller_yaml_config.create_property"):
        await loader.async_finish_initialization()

    # We assert que se guardó en la caché con la clave correcta (Kills mutants de self._parsed_yaml_cache[dev_id])
    assert "test_dev_1" in loader._parsed_yaml_cache
    assert loader._parsed_yaml_cache["test_dev_1"] == fake_yaml_data

    # 2. Corrompemos el YAML base original pero hacemos un Cache Hit
    loader._parsed_yaml_config = {"device": {"ESTADO_CORRUPTO": True}}

    # Almacenamos el estado previo de las operaciones
    ops_count = len(loader.operations)

    # Volvemos a inicializar
    with patch("custom_components.climate_ip.controller_yaml_config.create_property"):
        await loader.async_finish_initialization()

    assert len(loader.operations) == ops_count


# ====================================================================================
# FRENTE D: ASERCIÓN ESTRICTA DE ARGUMENTOS DE CONEXIÓN
# ====================================================================================


async def test_async_initialize_connection_instantiation_args():
    """Valida que los motores de red se instancien con los argumentos exactos requeridos."""

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
    # Forzamos la rama `else` del tipo de conexión (generic/REST)
    mock_controller._config = {"device_type": "UNKNOWN_GENERIC"}

    loader = YamlConfigLoader(mock_controller)
    yaml_data = {"device": {"connection": {"type": "test_conn_type"}}}
    loader._parsed_yaml_config = yaml_data
    _YAML_FILE_CACHE["/test.yaml"] = yaml_data

    # Create un interceptor estricto que no sea un MagicMock permisivo
    class InterceptorConnection:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        @classmethod
        def match_type(cls, conn_type):
            return conn_type == "test_conn_type"

        def load_from_yaml(self, node, state_getter):
            return True

    # Inject nuestra clase de conexión para auditar los argumentos
    with patch(
        "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
        [InterceptorConnection],
    ):
        await loader.async_initialize()

        # Autopsia de la instanciación (Kills mutants que omiten hass, config, o cambian argumentos)
        assert loader.connection is not None
        assert loader.connection.args[0] == mock_controller._config
        assert loader.connection.kwargs.get("hass") == mock_hass


# ====================================================================================
# FRENTE E: CORTAFUEGOS DE UNIDADES TERMODINÁMICAS (Fallbacks de Temperatura)
# ====================================================================================


async def test_async_finish_initialization_temperature_fallbacks():
    """Fuerza la ausencia de dependencias HASS para asertar el uso de unidades por defecto."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "temp_device_test"
    # 1. Eliminamos el objeto hass por completo
    if hasattr(mock_controller, "hass"):
        delattr(mock_controller, "hass")

    mock_controller._config = {}

    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    # Inject un YAML simulado
    loader._parsed_yaml_config = {
        "device": {"operations": {"target_temp": {"type": "temperature"}}}
    }

    # Create un mock de la propiedad que registre las llamadas de unidades
    mock_prop = StrictMock()
    mock_prop.id = "temperature"
    mock_prop.device_class = "temperature"  # Forzamos el chequeo is_temp

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        return_value=mock_prop,
    ):
        await loader.async_finish_initialization()

        # Al no haber HASS ni config_entries, el código DEBE usar DEFAULT_CONF_TEMP_UNIT
        # Esto destruye a los mutantes que alteran la asignación inicial de `configured_unit`
        # y `native_target_unit`
        mock_prop.set_hass_unit.assert_called_once_with(DEFAULT_CONF_TEMP_UNIT)
        mock_prop.set_device_unit.assert_called_with(DEFAULT_CONF_TEMP_UNIT)


# ====================================================================================
# FRENTE F: ASERCIÓN ESTRICTA DE FACTORÍAS Y DEDUPLICACIÓN
# ====================================================================================


async def test_async_finish_initialization_strict_factory_args():
    """Valida que create_property recibe sus 5 argumentos intactos y aserta listas únicas."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    mock_controller.device_id = "test_dev"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    loader.connection = "STRICT_CONN"
    loader.state_getter = "STRICT_GETTER"

    # YAML malicioso: Pass 'target_op' en operations Y attributes para forzar colisión de IDs
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"target_op": {"type": "A"}},
            "attributes": {"target_op": {"type": "B"}},  # Duplicado intencional
            "sensors": {"target_sensor": {"type": "C"}},
        }
    }

    # Interceptor estricto para simular la creación de la propiedad
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

        # 1. ASERCIÓN RÍGIDA DE ARGUMENTOS (Kills mutants 32 al 118)
        # If mutmut cambia `self.state_getter` a `None` en el código de producción, esto explotará
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

        # 2. ASERCIÓN DE DEDUPLICACIÓN DE LISTAS
        # If mutmut cambia `if op_id not in self.operations_list` por `in`, habrá duplicados o faltarán
        assert loader.operations_list.count("target_op") == 1
        assert "target_sensor" in loader.sensors_list


# ====================================================================================
# FRENTE G: LA CASCADA INFERNAL DE FALLBACKS (.get y getattr)
# ====================================================================================


async def test_async_initialize_fallback_cascades():
    """Fuerza atributos y diccionarios inexistentes para evaluar los fallback a {}."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"

    # Destruimos los atributos de configuración de forma atómica
    if hasattr(mock_controller, "_config"):
        delattr(mock_controller, "_config")
    if hasattr(mock_controller, "config"):
        delattr(mock_controller, "config")

    loader = YamlConfigLoader(mock_controller)

    # YAML vacío en su raíz (Mata mutaciones de `ac = yaml_device.get(CONFIG_DEVICE, {})`)
    loader._parsed_yaml_config = {}

    try:
        # Si un mutante mutó los `{}` por `None`, fallará estrepitosamente aquí
        await loader.async_initialize()
    except AttributeError as e:
        pytest.fail(f"La cascada de fallbacks fue corrompida por un mutante: {e}")


# ====================================================================================
# FRENTE H: DUCK-TYPING VS HERENCIA (El Motor Termodinámico)
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

    # Propiedad 2: Temperatura por Duck-Typing (Verify mutant kill de == "temperature")
    prop_duck = StrictMock()
    prop_duck.device_class = "temperature"
    prop_duck.id = "target_temperature"

    # Propiedad 3: Temperatura por Herencia Estricta (Verify mutant kill de isinstance)
    prop_isinstance = StrictMock(spec=TemperatureOperation)
    prop_isinstance.id = "current_temperature"

    # Inject en el loader saltándonos el parseo YAML
    loader.properties = {"p1": prop_other, "p2": prop_duck, "p3": prop_isinstance}

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property"
    ):  # Silenciamos llamadas externas
        await loader.async_finish_initialization()

    # Aserciones de precisión (El método apply_unit debió haber iterado sobre loader.properties)
    prop_other.set_hass_unit.assert_not_called()
    prop_duck.set_hass_unit.assert_called_once()
    prop_isinstance.set_hass_unit.assert_called_once()


# ====================================================================================
# FRENTE I: LA TRAMPA DE LA IDENTIDAD ASIMÉTRICA (op_key vs op.id)
# ====================================================================================


async def test_async_finish_initialization_asymmetric_id_fallback():
    """Valida que si op.id existe, NO se use op_key. Kills mutants de getattr('id')."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    loader = YamlConfigLoader(mock_controller)
    loader.is_fully_initialized = False

    # Inject diccionarios con llaves YAML que son DIFERENTES al ID real de la propiedad
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"yaml_op_key": {"type": "A"}},
            "switches": {"yaml_switch_key": {"type": "B"}},
            "attributes": {"yaml_attr_key": {"type": "C"}},
            "sensors": {
                "yaml_sensor_key": {"type": "D"}
            },  # Sensors usa la variable 'name'
        }
    }
    loader._parsed_yaml_cache = {"": loader._parsed_yaml_config}

    def fake_create(key, node, conn, ctrl, getter):
        prop = MagicMock()
        # El ID interno es diferente a la clave del YAML
        prop.id = f"real_id_for_{key}"
        return prop

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ):
        await loader.async_finish_initialization()

        # If mutmut cambia getattr(op, "id", op_key) por getattr(op, "XXidXX", op_key),
        # las listas registrarán "yaml_op_key" en lugar de "real_id_for_yaml_op_key", y el test explotará.
        assert "real_id_for_yaml_op_key" in loader.operations
        assert "yaml_op_key" not in loader.operations

        assert "real_id_for_yaml_switch_key" in loader.operations
        assert "real_id_for_yaml_attr_key" in loader.properties


# ====================================================================================
# FRENTE J: INYECCIÓN PROFUNDA DE CONFIG ENTRIES (Opciones HASS)
# ====================================================================================


async def test_async_finish_initialization_config_entry_options():
    """Fuerza la evaluación de unidades y motores de red mediante entry.options."""

    mock_controller = StrictMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = "test_unique"
    # Inject el entry_id
    mock_controller._config = {
        "entry_id": "test_entry_777",
        "device_type": "samsung_8888",
    }

    # Preparamos el Mock de Home Assistant para devolver un ConfigEntry
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
            },  # Gatilla TemperatureOperation
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

        # 1. Validación de Unidades (Kills mutants de entry.options.get(CONF_TEMP...))
        mock_temp_prop.set_device_unit.assert_called_with("Fahrenheit")

    # Validamos la parte de conexión ejecutando async_initialize
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
        # Debe haber extraído "raw" de las opciones del ConfigEntry y creado la conexión
        assert isinstance(loader.connection, DummySamsungConn)


# ====================================================================================
# FRENTE K: CORTOCIRCUITOS Y EARLY EXITS
# ====================================================================================


@pytest.mark.asyncio
async def test_async_finish_initialization_early_exits(mock_controller) -> None:
    """Aniquila la Familia B (Mutante 1, 6, 12) con una excepción trampa."""
    loader = YamlConfigLoader(mock_controller)

    # Preparamos una trampa: Si la función NO sale prematuramente,
    # intentará leer CONFIG_DEVICE y eventualmente llamar a create_property.
    # Rompemos deliberadamente el estado interno para que cualquier avance reviente violentamente.
    loader._parsed_yaml_config = {"device": {"operations": {"trap": {}}}}

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=RuntimeError("TRAMPA: No debió avanzar"),
    ):
        # 1. Sale temprano si ya está inicializado (PERO hay config válida)
        loader.is_fully_initialized = True
        try:
            await loader.async_finish_initialization()
        except RuntimeError:
            pytest.fail(
                "Mutante 1 sobrevivió: El bloque 'or' se mutó a 'and' y no salió anticipadamente."
            )

        # 2. Sale temprano si NO hay config válida (PERO no está inicializado)
        loader.is_fully_initialized = False
        loader._parsed_yaml_config = None
        try:
            await loader.async_finish_initialization()
        except RuntimeError:
            pytest.fail(
                "Mutante 1 sobrevivió: El bloque 'or' se mutó a 'and' y no salió anticipadamente."
            )

        # 3. Comprueba el uso seguro de getattr en device_id mutado a "XXXX" (Mutantes 6, 12)
        del mock_controller.device_id
        loader._parsed_yaml_config = {"device": {}}
        loader._parsed_yaml_cache = {"": {"device": {"name": "cached_device"}}}
        # Al no tener operaciones, no saltará la trampa, pero comprobaremos que no revienta el AttributeError
        await loader.async_finish_initialization()


@pytest.mark.asyncio
async def test_async_finish_initialization_idempotency(mock_controller) -> None:
    """Aniquila la Familia A (Mutantes 49, 50, 88, 89...) evitando el StopIteration."""
    loader = YamlConfigLoader(mock_controller)

    # Aislamos SOLO el bloque de operaciones para no agotar el side_effect
    loader._parsed_yaml_config = {"device": {"operations": {"op_1": {}, "op_2": {}}}}
    loader._parsed_yaml_cache = {"dev_123": loader._parsed_yaml_config}
    loader.connection = MagicMock()
    loader.state_getter = MagicMock()

    mock_prop_1 = MagicMock()
    mock_prop_1.id = "shared_id"
    mock_prop_2 = MagicMock()
    mock_prop_2.id = "shared_id"

    # Devolvemos los Mocks para 'operations' y luego None para cualquier otra cosa que intente parsear (switches, atributos)
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

        assert loader.operations_list == ["shared_id"], (
            "Falló la protección contra IDs duplicados."
        )
        assert loader.operations["shared_id"] is mock_prop_2


@pytest.mark.asyncio
async def test_apply_temperature_units_master_matrix() -> None:
    """Aniquila a la Familia C y los fallbacks de diccionario (Mutantes 167-253)."""

    # Matriz: (entry_options, entry_data, expected_target, expected_current)
    matrix = [
        # 1. Todo en options (El camino feliz)
        (
            {CONF_TEMP_NATIVE_TARGET: "°K", CONF_TEMP_NATIVE_CURRENT: "°F"},
            {},
            "°K",
            "°F",
        ),
        # 2. Todo en data (El fallback de options a data)
        (
            {},
            {CONF_TEMP_NATIVE_TARGET: "°K", CONF_TEMP_NATIVE_CURRENT: "°F"},
            "°K",
            "°F",
        ),
        # 3. Vacío absoluto (Fallback al display unit por defecto)
        (
            {},
            {},
            "°C",
            "°C",  # °C es nuestro mock para hass.config.units.temperature_unit
        ),
    ]

    for opts, data, exp_target, exp_current in matrix:
        # Aislamiento Total
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

        # Sensor general (No temperatura)
        general_sensor = MagicMock()
        general_sensor.device_class = "humidity"

        # Sensor genérico de temperatura
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

        assert loader.is_fully_initialized is True, (
            "El loader no levantó la bandera de inicialización completa"
        )


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
# FRENTE D: ASERCIÓN ESTRICTA DE ARGUMENTOS DE CONEXIÓN
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

        assert loader.is_fully_initialized is True, (
            "El loader no levantó la bandera de inicialización completa"
        )


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
            assert loader.poll is expected_poll, (
                f"Falló el parsing para '{poll_str}'. Esperado {expected_poll}, Obtuvo {loader.poll}"
            )


@pytest.mark.asyncio
async def test_async_finish_initialization_property_creation(mock_controller) -> None:
    """Kills mutants asertando la firma estricta de create_property y esquemas lógicos."""
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
    # Además, usamos dinámicamente un tipo de dispositivo válido del array de soporte real.
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
    # ASERCIÓN LETAL EN TIEMPO REAL: Solo devuelve True si el mutante NO alteró la cadena "request"
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
        assert result is True, (
            "Falló la inicialización o la clase mock rechazó la cadena mutada"
        )

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
    from custom_components.climate_ip.controller_yaml_config import (
        YamlConfigLoader,
        _LOGGER,
    )
    from unittest.mock import patch, MagicMock
    from custom_components.climate_ip.const import CONF_CONN_METHOD, CONF_DEVICE_TYPE

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
        assert isinstance(loader.connection, MockRawConn), (
            "El motor RAW no fue instanciado"
        )
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
    assert loader.is_fully_initialized is True, (
        "INFRACCIÓN: La bandera de inicialización no fue levantada."
    )
