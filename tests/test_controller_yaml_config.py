"""Unit tests for Climate IP YAML configuration loader."""

from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import probatio
import pytest

from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    CONFIG_DEVICE,
    CONFIG_DEVICE_ATTRIBUTES,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_TYPE,
    CONFIG_DEVICE_OPERATIONS,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_STATUS,
    CONFIG_DEVICE_SWITCHES,
    CONN_METHOD_AIOHTTP,
    CONN_METHOD_RAW,
    DEFAULT_CONF_TEMP_UNIT,
    DEVICE_TYPE_INTESISBOX,
    DEVICE_TYPE_SAMSUNG_2878,
)
from custom_components.climate_ip.controller_yaml_config import (
    _LOGGER,
    _YAML_FILE_CACHE,
    CONST_CONTROLLER_TYPE,
    YamlConfigLoader,
    clear_yaml_cache,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_NAME, ATTR_TEMPERATURE
from homeassistant.util.yaml import load_yaml


class DummyController:
    """Lightweight controller stub for testing YamlConfigLoader."""

    def __init__(self, **kwargs) -> None:
        """Initialize dummy controller."""
        self.log_prefix = "[Test]"
        self.device_id = "test_dev"
        if not hasattr(type(self), "yaml_file"):
            self.yaml_file = "test.yaml"
        if not hasattr(type(self), "unique_id"):
            self.unique_id = "test_uid"
        if not hasattr(type(self), "config"):
            self.config = {CONF_CONFIG_FILE: "test.yaml"}
        if not hasattr(type(self), "hass"):
            self.hass = None
        for k, v in kwargs.items():
            setattr(self, k, v)


# ====================================================================================
# 1. INITIAL STATE & FRAGMENTED PAYLOADS
# ====================================================================================


@pytest.mark.asyncio
async def test_yaml_config_initial_state_and_fragmented_payloads() -> None:
    """Validate initial state, parsed_yaml_cache property, and fragmented payloads."""
    ctrl = DummyController()
    loader = YamlConfigLoader(ctrl)

    assert loader.name == CONST_CONTROLLER_TYPE
    assert loader.is_fully_initialized is False
    assert loader.parsed_yaml_cache == {}
    assert probatio.Optional(ATTR_ENTITY_ID) in loader.service_schema_map
    assert all(isinstance(k, probatio.Optional) for k in loader.service_schema_map)

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property"
    ) as mock_create:
        # 1. Inject YAML lacking device node entirely
        loader._parsed_yaml_config = {"other_dev": {}}
        loader._parsed_yaml_cache = {}
        await loader.async_finish_initialization()
        mock_create.assert_not_called()

        # 2. Inject YAML with device lacking operations/switches/attributes/sensors
        loader.is_fully_initialized = False
        loader._parsed_yaml_config = {"device": {}}
        loader._parsed_yaml_cache = {}
        await loader.async_finish_initialization()
        mock_create.assert_not_called()

        # 3. Inject YAML with operations and switches
        loader.is_fully_initialized = False
        loader._parsed_yaml_config = {
            "device": {
                "operations": {"op_frag": {"type": "A"}},
                "switches": {"sw_frag": {"type": "B"}},
            }
        }
        loader._parsed_yaml_cache = {}

        def fake_prop(key, node, conn, c, getter):
            p = MagicMock()
            p.id = key
            p.config_validation_type = str
            return p

        mock_create.side_effect = fake_prop
        await loader.async_finish_initialization()
        assert "op_frag" in loader.operations
        assert "sw_frag" in loader.operations
        assert "sw_frag" in loader.operations_list


# ====================================================================================
# 2. EARLY EXITS & FAILURE RETURNS (CRITICAL SOLO KILLER)
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_early_exits_bombardment() -> None:
    """Verify all early failure returns in async_initialize (Critical Solo Killer)."""
    ctrl = DummyController(hass=None)

    # 1. File not specified (None)
    ctrl.yaml_file = None
    loader = YamlConfigLoader(ctrl)
    assert await loader.async_initialize() is False

    mock_conn_class = MagicMock()
    mock_conn_class.__name__ = "MockConnClass"
    mock_conn_class.match_type.return_value = True
    mock_conn_instance = MagicMock()
    mock_conn_instance.load_from_yaml.return_value = False
    mock_conn_class.return_value = mock_conn_instance
    conn_list = [mock_conn_class]

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml"
        ) as mock_load,
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            conn_list,
        ),
    ):
        # 2. Exception while loading YAML
        ctrl.yaml_file = "/test_exploding.yaml"
        clear_yaml_cache()
        loader = YamlConfigLoader(ctrl)
        mock_load.side_effect = RuntimeError("YAML Explosion")
        assert await loader.async_initialize() is False

        # 3. Empty YAML dictionary
        mock_load.side_effect = None
        mock_load.return_value = {}
        ctrl.yaml_file = "/test_empty.yaml"
        clear_yaml_cache()
        loader = YamlConfigLoader(ctrl)
        assert await loader.async_initialize() is False

        # 4. Missing 'device' root key
        mock_load.return_value = {"other_root": {}}
        ctrl.yaml_file = "/test_missing_device.yaml"
        clear_yaml_cache()
        loader = YamlConfigLoader(ctrl)
        assert await loader.async_initialize() is False

        # 5. Missing unique_id
        mock_load.return_value = {"device": {}}
        ctrl.yaml_file = "/test_no_uid.yaml"
        ctrl.unique_id = None
        clear_yaml_cache()
        loader = YamlConfigLoader(ctrl)
        assert await loader.async_initialize() is False
        ctrl.unique_id = "test_uid"

        # 6. Connection load_from_yaml fails and missing status returns False
        mock_load.return_value = {"device": {"connection": {"type": "mock"}}}
        mock_conn_instance.load_from_yaml.return_value = False
        ctrl.yaml_file = "/test_conn_fail.yaml"
        clear_yaml_cache()
        loader = YamlConfigLoader(ctrl)
        assert await loader.async_initialize() is False

        # 7. Status getter creation returns None (status node absent from YAML)
        mock_conn_instance.load_from_yaml.return_value = True
        ctrl.yaml_file = "/test_no_status.yaml"
        clear_yaml_cache()
        loader = YamlConfigLoader(ctrl)
        assert await loader.async_initialize() is False

        # 8. No matching connection class found
        mock_load.return_value = {
            "device": {"connection": {"type": "unsupported_type"}}
        }
        conn_list.clear()
        ctrl.yaml_file = "/test_no_match.yaml"
        clear_yaml_cache()
        loader = YamlConfigLoader(ctrl)
        assert await loader.async_initialize() is False


# ====================================================================================
# 3. YAML CACHING & NON-DICT HANDLING
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_yaml_caching_and_non_dict() -> None:
    """Validate YAML caching behavior, non-dict handling, and clear_yaml_cache."""
    ctrl = DummyController(yaml_file="/test_cache.yaml")
    loader = YamlConfigLoader(ctrl)
    clear_yaml_cache()

    valid_data = {"device": {"connection": {"type": "mock"}, "status": {}}}
    mock_conn = MagicMock()
    mock_conn.__name__ = "MockConn"
    mock_conn.match_type.return_value = True
    mock_conn.return_value.load_from_yaml.return_value = True

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value="not_a_dict",
        ) as mock_load,
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        # 1. Non-dict loaded from YAML -> loader returns False and does not cache
        assert await loader.async_initialize() is False
        assert loader._parsed_yaml_config is None
        assert "/test_cache.yaml" not in _YAML_FILE_CACHE

        # 2. Valid dict cached under resolved file path
        mock_load.return_value = valid_data
        assert await loader.async_initialize() is True
        assert loader.name == CONST_CONTROLLER_TYPE
        assert _YAML_FILE_CACHE.get("/test_cache.yaml") == valid_data

        # 3. Cache hit via resolved path
        loader2 = YamlConfigLoader(ctrl)
        assert await loader2.async_initialize() is True

        # 4. Cache hit via raw_file fallback
        clear_yaml_cache()
        _YAML_FILE_CACHE["raw_relative.yaml"] = valid_data
        ctrl_raw = DummyController(yaml_file="raw_relative.yaml")
        loader3 = YamlConfigLoader(ctrl_raw)
        assert await loader3.async_initialize() is True

    clear_yaml_cache()
    assert len(_YAML_FILE_CACHE) == 0


# ====================================================================================
# 4. DEVICE ID CACHE KEYS
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_device_id_cache_keys() -> None:
    """Verify device_id and fallback empty string cache key handling."""
    ctrl = DummyController(device_id="sniper_target_id", yaml_file="/dev_cache.yaml")
    loader = YamlConfigLoader(ctrl)
    clear_yaml_cache()

    valid_data = {"device": {"connection": {"type": "mock"}, "status": {}}}
    mock_conn = MagicMock()
    mock_conn.__name__ = "MockConn"
    mock_conn.match_type.return_value = True
    mock_conn.return_value.load_from_yaml.return_value = True

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value=valid_data,
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        assert await loader.async_initialize() is True
        assert "sniper_target_id" in loader.parsed_yaml_cache
        assert loader.parsed_yaml_cache["sniper_target_id"] == valid_data

        # Test controller lacking device_id attribute
        del ctrl.device_id
        loader2 = YamlConfigLoader(ctrl)
        assert await loader2.async_initialize() is True
        assert "" in loader2.parsed_yaml_cache


# ====================================================================================
# 5. EXECUTOR DELEGATION
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_executor_job_delegation() -> None:
    """Test executor job delegation when hass is present vs direct load when None."""
    clear_yaml_cache()
    mock_hass = MagicMock()
    yaml_data = {"device": {"status": {}, "connection": {"type": "mock"}}}
    mock_hass.async_add_executor_job = AsyncMock(return_value=yaml_data)

    ctrl = DummyController(hass=mock_hass, yaml_file="executor_test.yaml")
    loader = YamlConfigLoader(ctrl)

    mock_conn = MagicMock()
    mock_conn.__name__ = "MockConn"
    mock_conn.match_type.return_value = True
    mock_conn.return_value.load_from_yaml.return_value = True

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        assert await loader.async_initialize() is True
        expected_path = str(
            Path(
                sys.modules[
                    "custom_components.climate_ip.controller_yaml_config"
                ].__file__
            ).parent
            / "executor_test.yaml"
        )
        mock_hass.async_add_executor_job.assert_called_once_with(
            load_yaml, expected_path
        )


# ====================================================================================
# 6. EXPLICIT YAML NAME & POLL (CRITICAL SOLO KILLER)
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_explicit_yaml_data() -> None:
    """Verify name and poll parsed directly from YAML (Critical Solo Killer)."""
    clear_yaml_cache()
    ctrl = DummyController(yaml_file="/test_explicit.yaml")
    loader = YamlConfigLoader(ctrl)

    yaml_data = {
        "device": {
            "status": {},
            "connection": {"type": "mock"},
            ATTR_NAME: "CustomACName",
            CONFIG_DEVICE_POLL: "false",
        }
    }

    mock_conn = MagicMock()
    mock_conn.__name__ = "MockConn"
    mock_conn.match_type.return_value = True
    mock_conn.return_value.load_from_yaml.return_value = True

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value=yaml_data,
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        assert await loader.async_initialize() is True
        assert loader.name == "CustomACName"
        assert loader.poll is False

        # Also test poll == 'true'
        yaml_data["device"][CONFIG_DEVICE_POLL] = "true"
        clear_yaml_cache()
        loader_true = YamlConfigLoader(ctrl)
        assert await loader_true.async_initialize() is True
        assert loader_true.poll is True


# ====================================================================================
# 7. GENERIC CONNECTION INSTANTIATION
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_connection_instantiation_args() -> None:
    """Validate generic connection instantiation arguments and status getter creation."""
    clear_yaml_cache()
    yaml_data = {
        "device": {
            "connection": {"type": "test_conn_type"},
            "status": {"real_status": 123},
        }
    }
    mock_hass = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock(return_value=yaml_data)

    ctrl = DummyController(
        hass=mock_hass,
        yaml_file="/test_generic_conn.yaml",
        config={"device_type": "generic_type"},
    )
    loader = YamlConfigLoader(ctrl)

    class GenericConnection:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.loaded_node = None
            self.loaded_getter = None

        @classmethod
        def match_type(cls, conn_type):
            return conn_type == "test_conn_type"

        def load_from_yaml(self, node, getter):
            self.loaded_node = node
            self.loaded_getter = getter
            return True

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [GenericConnection],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ) as mock_csg,
    ):
        assert await loader.async_initialize() is True
        assert loader.connection is not None
        assert loader.connection.args[0] == ctrl.config
        assert loader.connection.args[1] == _LOGGER
        assert loader.connection.kwargs.get("hass") == mock_hass
        assert loader.connection.loaded_node == {"type": "test_conn_type"}
        assert loader.connection.loaded_getter is None
        mock_csg.assert_called_once_with(
            "state", {"real_status": 123}, loader.connection, ctrl
        )


# ====================================================================================
# 8. CONNECTION AIOHTTP8888 (CRITICAL SOLO KILLER)
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_connection_instantiation_args_frente_d() -> None:
    """Solo killer: verifies ConnectionAiohttp8888 full argument forwarding."""
    clear_yaml_cache()
    mock_hass = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock(
        return_value={"device": {"connection": {"type": "aiohttp"}, "status": {}}}
    )

    ctrl = DummyController(
        hass=mock_hass,
        _session="SESSION_INSTANCE",
        ip_address="192.168.1.100",
        yaml_file="/test_d.yaml",
        unique_id="test_d",
        _config={"device_type": "samsung_8888"},
        config={"device_type": "samsung_8888"},
    )
    loader = YamlConfigLoader(ctrl)

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ) as mock_csg,
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS"
        ) as mock_connections,
    ):
        mock_conn_class = MagicMock()
        mock_conn_class.__name__ = "ConnectionAiohttp8888"
        mock_conn_class.match_type.return_value = True

        mock_conn_instance = MagicMock()
        mock_conn_instance.load_from_yaml.return_value = True
        mock_conn_class.return_value = mock_conn_instance
        mock_connections.__iter__.return_value = [mock_conn_class]

        assert await loader.async_initialize() is True

        merged_config = {
            "device_type": "samsung_8888",
            "type": "samsung_8888_aiohttp",
        }
        mock_conn_class.assert_called_once_with(
            merged_config,
            _LOGGER,
            ctrl.hass,
            ctrl._session,
            ctrl.ip_address,
        )
        mock_conn_instance.load_from_yaml.assert_called_once_with(
            {"type": "samsung_8888_aiohttp"}, None
        )
        mock_csg.assert_called_once_with("state", {}, mock_conn_instance, ctrl)


# ====================================================================================
# 9. CONNECTION RAW8888 (CRITICAL SOLO KILLER)
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_connection_raw8888_args() -> None:
    """Solo killer: audits ConnectionRaw8888 5-positional arguments path."""
    clear_yaml_cache()
    yaml_data = {"device": {"connection": {"type": "samsung_8888_raw"}, "status": {}}}
    mock_hass = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock(return_value=yaml_data)

    config_dict = {
        CONF_DEVICE_TYPE: "samsung_8888",
        CONF_CONN_METHOD: CONN_METHOD_RAW,
    }
    ctrl = DummyController(
        hass=mock_hass,
        _config=config_dict,
        config=config_dict,
        _session="RAW_SESSION_OBJECT",
        ip_address="10.0.0.99",
        yaml_file="/test_raw.yaml",
    )
    loader = YamlConfigLoader(ctrl)

    class ConnectionRaw8888:
        def __init__(self, *args, **kwargs):
            self.args = args

        @classmethod
        def match_type(cls, conn_type):
            return conn_type == "samsung_8888_raw"

        def load_from_yaml(self, node, getter):
            return True

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [ConnectionRaw8888],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        assert await loader.async_initialize() is True
        assert isinstance(loader.connection, ConnectionRaw8888)
        assert loader.connection.args[0] == ctrl.config
        assert loader.connection.args[1] == _LOGGER
        assert loader.connection.args[2] == ctrl.hass
        assert loader.connection.args[3] == "RAW_SESSION_OBJECT"
        assert loader.connection.args[4] == "10.0.0.99"


# ====================================================================================
# 10. DEVICE TYPES & OPTIONS RESOLUTION
# ====================================================================================


@pytest.mark.asyncio
async def test_async_initialize_options_and_device_types() -> None:
    """Validate device_type routing, entry.options resolution, and fallbacks."""
    clear_yaml_cache()
    mock_conn = MagicMock()
    mock_conn.__name__ = "MockConn"
    mock_conn.match_type.return_value = True
    mock_conn.return_value.load_from_yaml.return_value = True

    yaml_data = {"device": {"connection": {}, "status": {}}}
    dep_yaml = {
        "device": {
            "connection": {CONFIG_DEVICE_CONNECTION_TYPE: "request"},
            "status": {},
        }
    }

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value=yaml_data,
        ) as mock_load,
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
    ):
        # 1. samsung_2878 and intesisbox routing
        for dev_type, expected_conn_type in (
            (DEVICE_TYPE_SAMSUNG_2878, "samsung_2878"),
            (DEVICE_TYPE_INTESISBOX, "intesisbox"),
        ):
            clear_yaml_cache()
            ctrl = DummyController(
                yaml_file="/test_routing.yaml",
                config={CONF_DEVICE_TYPE: dev_type},
            )
            loader = YamlConfigLoader(ctrl)
            assert await loader.async_initialize() is True
            mock_conn.match_type.assert_called_with(expected_conn_type)

        # 2. Options resolution with entry.options override (raw method)
        mock_hass = MagicMock()
        mock_hass.async_add_executor_job = AsyncMock(return_value=yaml_data)
        mock_entry = MagicMock()
        mock_entry.options = {CONF_CONN_METHOD: CONN_METHOD_RAW}
        mock_hass.config_entries.async_get_entry.return_value = mock_entry

        ctrl_opt = DummyController(
            hass=mock_hass,
            yaml_file="/test_opt.yaml",
            config={
                "entry_id": "test_entry_1",
                CONF_DEVICE_TYPE: "samsung_8888",
                CONF_CONN_METHOD: CONN_METHOD_AIOHTTP,
            },
        )
        loader_opt = YamlConfigLoader(ctrl_opt)
        clear_yaml_cache()
        assert await loader_opt.async_initialize() is True
        mock_conn.match_type.assert_called_with("samsung_8888_raw")

        # 3. Options truthy but lacking CONF_CONN_METHOD -> preserves controller config
        mock_entry.options = {"other_key": 123}
        loader_fallback = YamlConfigLoader(ctrl_opt)
        clear_yaml_cache()
        assert await loader_fallback.async_initialize() is True
        mock_conn.match_type.assert_called_with("samsung_8888_aiohttp")

        # 4. Obsolete / unsupported connection method -> fallback to yaml / request
        ctrl_dep = DummyController(
            yaml_file="/test_dep.yaml",
            config={
                CONF_DEVICE_TYPE: "samsung_8888",
                CONF_CONN_METHOD: "invalid_obsolete",
            },
        )
        loader_dep = YamlConfigLoader(ctrl_dep)
        mock_load.return_value = dep_yaml
        clear_yaml_cache()
        assert await loader_dep.async_initialize() is True
        mock_conn.match_type.assert_called_with("request")


# ====================================================================================
# 11. FINISH INITIALIZATION EARLY EXITS
# ====================================================================================


@pytest.mark.asyncio
async def test_async_finish_initialization_early_exits() -> None:
    """Verify idempotency and early returns in async_finish_initialization."""
    ctrl = DummyController()
    loader = YamlConfigLoader(ctrl)

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=RuntimeError("TRAP: create_property should not be called"),
    ):
        # 1. is_fully_initialized is True -> early exit even with truthy _parsed_yaml_config
        loader.is_fully_initialized = True
        loader._parsed_yaml_config = {"device": {"operations": {"trap": {}}}}
        await loader.async_finish_initialization()

        # 2. _parsed_yaml_config is None -> early exit
        loader.is_fully_initialized = False
        loader._parsed_yaml_config = None
        await loader.async_finish_initialization()

        # 3. device key missing from cached yaml -> completes safely without error
        del ctrl.device_id
        loader._parsed_yaml_config = {"other": {}}
        loader._parsed_yaml_cache = {"": {"other": {}}}
        await loader.async_finish_initialization()
        assert loader.is_fully_initialized is True


# ====================================================================================
# 12. PROPERTIES & SENSORS CREATION
# ====================================================================================


@pytest.mark.asyncio
async def test_async_finish_initialization_properties_creation() -> None:
    """Verify property creation across operations, switches, attributes, sensors, and schemas."""
    ctrl = DummyController(device_id="dev_props")
    loader = YamlConfigLoader(ctrl)
    loader.connection = "TEST_CONN"
    loader.state_getter = "TEST_GETTER"

    loader._parsed_yaml_config = {
        "device": {
            "operations": {"op1": {"type": "A"}, "op1_dup": {"type": "A"}},
            "switches": {"sw1": {"type": "B"}},
            "attributes": {"attr1": {"unit_of_measurement": "kWh"}},
            "sensors": {"sen1": {"type": "C"}},
        }
    }
    loader._parsed_yaml_cache = {"dev_props": loader._parsed_yaml_config}

    mock_prop_dup = MagicMock()
    mock_prop_dup.id = "real_op1"
    mock_prop_dup.config_validation_type = "cv_custom"
    mock_prop_dup.device_class = "temperature"

    def fake_create(key, node, conn, c, getter):
        if key == "op1_dup":
            return mock_prop_dup
        prop = MagicMock()
        prop.id = f"real_{key}"
        prop.config_validation_type = "cv_custom"
        if key == "attr1":
            prop.device_class = "power"
        else:
            prop.device_class = "temperature"
        return prop

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ) as mock_create:
        await loader.async_finish_initialization()

        mock_create.assert_any_call(
            "op1", {"type": "A"}, "TEST_CONN", ctrl, "TEST_GETTER"
        )
        mock_create.assert_any_call(
            "sw1", {"type": "B"}, "TEST_CONN", ctrl, "TEST_GETTER"
        )
        mock_create.assert_any_call(
            "attr1", {"unit_of_measurement": "kWh"}, "TEST_CONN", ctrl, "TEST_GETTER"
        )
        mock_create.assert_any_call(
            "sen1", {"type": "C"}, "TEST_CONN", ctrl, "TEST_GETTER"
        )

        assert loader.service_schema_map[probatio.Optional("real_op1")] == "cv_custom"
        assert loader.service_schema_map[probatio.Optional("real_sw1")] == "cv_custom"
        assert all(isinstance(k, probatio.Optional) for k in loader.service_schema_map)
        assert "real_sw1" in loader.operations_list
        assert "real_attr1" in loader.properties_list
        assert "sen1" in loader.sensors_list

        assert loader.operations_list.count("real_op1") == 1
        assert loader.operations["real_op1"] is mock_prop_dup

        loader.properties["real_attr1"].set_unit_of_measurement.assert_called_once_with(
            "kWh"
        )
        assert loader.is_fully_initialized is True


# ====================================================================================
# 13. TEMPERATURE UNITS & SURVIVOR KILLER (MUTANT ID 64)
# ====================================================================================


@pytest.mark.asyncio
async def test_async_finish_initialization_temperature_units_and_survivor_sniper() -> (
    None
):
    """Validate temperature units and kill mutant on line 481 (if hass_ref and entry_id:)."""
    # 1. SNIPER CASE A: hass_ref is present, but entry_id is absent.
    # Under mutant 'if hass_ref or entry_id:', async_get_entry(None) is called.
    mock_hass_no_entry = MagicMock()
    mock_hass_no_entry.config.units.temperature_unit = "Celsius"
    ctrl_no_entry = DummyController(hass=mock_hass_no_entry, config={})
    loader_no_entry = YamlConfigLoader(ctrl_no_entry)
    loader_no_entry._parsed_yaml_config = {"device": {}}
    loader_no_entry._parsed_yaml_cache = {
        "test_dev": loader_no_entry._parsed_yaml_config
    }

    await loader_no_entry.async_finish_initialization()
    mock_hass_no_entry.config_entries.async_get_entry.assert_not_called()

    # 2. SNIPER CASE B: hass_ref is None, but entry_id is present.
    # Under mutant 'if hass_ref or entry_id:', raises AttributeError on None.config_entries.
    ctrl_no_hass = DummyController(hass=None, config={"entry_id": "orphan_id"})
    loader_no_hass = YamlConfigLoader(ctrl_no_hass)
    loader_no_hass._parsed_yaml_config = {"device": {}}
    loader_no_hass._parsed_yaml_cache = {"test_dev": loader_no_hass._parsed_yaml_config}

    await loader_no_hass.async_finish_initialization()
    assert loader_no_hass.is_fully_initialized is True

    # 3. BOTH present: entry options configure native current and target units
    mock_hass = MagicMock()
    mock_hass.config.units.temperature_unit = "Celsius"
    mock_entry = MagicMock()
    mock_entry.options = {
        CONF_TEMP_NATIVE_CURRENT: "Kelvin",
        CONF_TEMP_NATIVE_TARGET: "Fahrenheit",
    }
    mock_hass.config_entries.async_get_entry.return_value = mock_entry

    ctrl = DummyController(hass=mock_hass, config={"entry_id": "valid_entry_id"})
    loader = YamlConfigLoader(ctrl)
    loader._parsed_yaml_config = {
        "device": {"operations": {"target_temp": {}, "current_temp": {}}}
    }
    loader._parsed_yaml_cache = {"test_dev": loader._parsed_yaml_config}

    target_prop = MagicMock()
    target_prop.id = ATTR_TEMPERATURE
    target_prop.device_class = "temperature"

    current_prop = MagicMock()
    current_prop.id = "current_temperature"
    current_prop.device_class = "temperature"

    def fake_create(key, *args):
        return target_prop if key == "target_temp" else current_prop

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ):
        await loader.async_finish_initialization()
        mock_hass.config_entries.async_get_entry.assert_called_once_with(
            "valid_entry_id"
        )

        target_prop.set_hass_unit.assert_called_with("Celsius")
        target_prop.set_device_unit.assert_called_with("Fahrenheit")
        current_prop.set_hass_unit.assert_called_with("Celsius")
        current_prop.set_device_unit.assert_called_with("Kelvin")


# ====================================================================================
# 14. EDGE BRANCHES & 100% STATEMENT COVERAGE
# ====================================================================================


@pytest.mark.asyncio
async def test_controller_yaml_config_edge_branches() -> None:
    """Cover remaining corner branches for 100% statement coverage."""

    # 1. AttributeError on unique_id in async_initialize
    class NoUidController(DummyController):
        @property
        def unique_id(self):
            raise AttributeError("no unique_id")

    clear_yaml_cache()
    _YAML_FILE_CACHE["/no_uid.yaml"] = {"device": {"status": {}, "connection": {}}}
    loader_no_uid = YamlConfigLoader(NoUidController(yaml_file="/no_uid.yaml"))
    assert await loader_no_uid.async_initialize() is False

    # 2. AttributeError on controller.hass during aiohttp check, set_controller_ref, and init fallbacks
    class ExplodingHassController(DummyController):
        yaml_file = "/fake.yaml"

        @property
        def config(self):
            return {CONF_DEVICE_TYPE: "samsung_8888", "entry_id": "test_e"}

        @property
        def hass(self):
            raise AttributeError("hass exploded")

    class FallbackInitController(DummyController):
        yaml_file = "/fake.yaml"
        _config = {CONF_DEVICE_TYPE: "samsung_2878"}

        @property
        def config(self):
            raise AttributeError("no config")

    class EmptyInitController(DummyController):
        yaml_file = "/fake.yaml"

        @property
        def config(self):
            raise AttributeError("no config")

        @property
        def _config(self):
            raise AttributeError("no _config")

    class ExplodingHassYamlLoad(DummyController):
        yaml_file = "/fake_load.yaml"

        @property
        def hass(self):
            raise AttributeError("boom")

    conn_cls = MagicMock()
    conn_cls.__name__ = "MockConn"
    conn_cls.match_type.return_value = True
    conn_instance = MagicMock()
    conn_instance.load_from_yaml.return_value = True
    conn_cls.return_value = conn_instance

    _YAML_FILE_CACHE["/fake.yaml"] = {
        CONFIG_DEVICE: {
            CONFIG_DEVICE_STATUS: {},
            CONFIG_DEVICE_CONNECTION: {},
        }
    }

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [conn_cls],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value={"device": {"connection": {}, "status": {}}},
        ),
    ):
        # 2. AttributeError on controller.hass
        loader_expl = YamlConfigLoader(ExplodingHassController(yaml_file="/fake.yaml"))
        assert await loader_expl.async_initialize() is True

        # 3. Connection set_controller_ref called if present
        conn_instance.set_controller_ref.reset_mock()
        loader_ref = YamlConfigLoader(DummyController(yaml_file="/fake.yaml"))
        assert await loader_ref.async_initialize() is True
        conn_instance.set_controller_ref.assert_called_once()

        # 5. Fallback in async_initialize when controller.config raises AttributeError
        loader_init_fb = YamlConfigLoader(
            FallbackInitController(yaml_file="/fake.yaml")
        )
        assert await loader_init_fb.async_initialize() is True

        # 6. Fallback in async_initialize when both config and _config raise AttributeError
        loader_init_empty = YamlConfigLoader(
            EmptyInitController(yaml_file="/fake.yaml")
        )
        assert await loader_init_empty.async_initialize() is True

        # 7. Loading YAML with controller.hass raising AttributeError
        clear_yaml_cache()
        loader_yaml_expl = YamlConfigLoader(
            ExplodingHassYamlLoad(yaml_file="/fake_load.yaml")
        )
        assert await loader_yaml_expl.async_initialize() is True

    # 4. Property edge cases in async_finish_initialization:
    # - Property with no id attribute
    # - Property with no config_validation_type (falls back to cv.string)
    # - Temperature property with no set_hass_unit (falls back to set_unit_of_measurement)
    # - Temperature property with neither unit setter
    # - None in operations / properties / sensors
    class PropNoIdFallback:
        device_class = "temperature"

        def __init__(self):
            self.unit = None

        def set_unit_of_measurement(self, unit):
            self.unit = unit

    class PropNoSetters:
        device_class = "temperature"

    class SwitchNoSchema:
        pass

    class AttrNoUnitSetter:
        pass

    ctrl_finish = DummyController(device_id="dev_edge_finish")
    loader_finish = YamlConfigLoader(ctrl_finish)
    loader_finish._parsed_yaml_config = {
        CONFIG_DEVICE: {
            CONFIG_DEVICE_OPERATIONS: {"op_no_id": {}},
            CONFIG_DEVICE_SWITCHES: {"sw_no_schema": {}},
            CONFIG_DEVICE_ATTRIBUTES: {
                "attr_no_setter": {"unit_of_measurement": "kWh"}
            },
        }
    }
    loader_finish._parsed_yaml_cache["dev_edge_finish"] = (
        loader_finish._parsed_yaml_config
    )

    def edge_prop_creator(key, *args):
        if key == "sw_no_schema":
            return SwitchNoSchema()
        if key == "op_no_id":
            return SwitchNoSchema()  # lacks id and config_validation_type
        return AttrNoUnitSetter()

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=edge_prop_creator,
    ):
        loader_finish.operations["none_op"] = None
        loader_finish.operations["temp_fallback"] = PropNoIdFallback()
        loader_finish.sensors["no_setter"] = PropNoSetters()
        loader_finish.sensors["none_sensor"] = None
        await loader_finish.async_finish_initialization()

    assert loader_finish.is_fully_initialized is True
    assert (
        loader_finish.service_schema_map[probatio.Optional("sw_no_schema")] is not None
    )
    assert loader_finish.operations["temp_fallback"].unit == DEFAULT_CONF_TEMP_UNIT

    # 8. async_finish_initialization when controller.hass raises AttributeError
    class ExplodingHassFinish(DummyController):
        @property
        def hass(self):
            raise AttributeError("boom")

    loader_finish_expl = YamlConfigLoader(ExplodingHassFinish())
    loader_finish_expl._parsed_yaml_config = {"device": {}}
    loader_finish_expl._parsed_yaml_cache["test_dev"] = (
        loader_finish_expl._parsed_yaml_config
    )
    await loader_finish_expl.async_finish_initialization()
    assert loader_finish_expl.is_fully_initialized is True

    # 9. Property with device_class raising AttributeError in apply_unit
    class ExplodingDeviceClassProp:
        @property
        def device_class(self):
            raise AttributeError("boom")

    loader_prop_expl = YamlConfigLoader(DummyController())
    loader_prop_expl._parsed_yaml_config = {"device": {}}
    loader_prop_expl._parsed_yaml_cache["test_dev"] = (
        loader_prop_expl._parsed_yaml_config
    )
    loader_prop_expl.operations["expl_prop"] = ExplodingDeviceClassProp()
    await loader_prop_expl.async_finish_initialization()
    assert loader_prop_expl.is_fully_initialized is True

    # 10. Temperature property with id raising AttributeError in dual units
    class DualUnitsNoIdProp:
        device_class = "temperature"

        @property
        def id(self):
            raise AttributeError("no id")

        def set_hass_unit(self, u):
            pass

        def set_device_unit(self, u):
            pass

    loader_dual_noid = YamlConfigLoader(DummyController())
    loader_dual_noid._parsed_yaml_config = {"device": {}}
    loader_dual_noid._parsed_yaml_cache["test_dev"] = (
        loader_dual_noid._parsed_yaml_config
    )
    loader_dual_noid.operations["dual_noid"] = DualUnitsNoIdProp()
    await loader_dual_noid.async_finish_initialization()
    assert loader_dual_noid.is_fully_initialized is True

    # 11. Fallback in async_finish_initialization when controller.config raises AttributeError
    class FallbackFinishController(DummyController):
        _config = {"entry_id": "fb_entry"}
        hass = MagicMock()

        @property
        def config(self):
            raise AttributeError("no config")

    ctrl_fb = FallbackFinishController()
    ctrl_fb.hass.config_entries.async_get_entry = MagicMock(return_value=None)
    loader_fb = YamlConfigLoader(ctrl_fb)
    loader_fb._parsed_yaml_config = {"device": {}}
    loader_fb._parsed_yaml_cache["test_dev"] = loader_fb._parsed_yaml_config
    await loader_fb.async_finish_initialization()
    ctrl_fb.hass.config_entries.async_get_entry.assert_called_once_with("fb_entry")

    # 12. Fallback in async_finish_initialization when both config and _config raise AttributeError
    class EmptyFinishController(DummyController):
        hass = None

        @property
        def config(self):
            raise AttributeError("no config")

        @property
        def _config(self):
            raise AttributeError("no _config")

    ctrl_empty = EmptyFinishController()
    loader_empty = YamlConfigLoader(ctrl_empty)
    loader_empty._parsed_yaml_config = {"device": {}}
    loader_empty._parsed_yaml_cache["test_dev"] = loader_empty._parsed_yaml_config
    await loader_empty.async_finish_initialization()
    assert loader_empty.is_fully_initialized is True
