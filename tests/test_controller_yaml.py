# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,missing-class-docstring,too-few-public-methods,too-many-return-statements,use-implicit-booleaness-not-comparison,missing-final-newline
"""Tests for YamlController — Optimized and orthogonal suite."""

import importlib
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_DEBUG,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_CONTROLLER_NAME,
    DEVICE_TYPE_SAMSUNG_2878,
    ERR_CACHE_UNINITIALIZED,
    ERR_INVALID_DEVICE_MODE,
    ERR_MISSING_INIT_CONFIG,
    ERR_MISSING_IP,
    ERR_UNREGISTERED_PROPERTY,
    MAIN_DEVICE_ID,
    PORT_SAMSUNG_8888,
)
from custom_components.climate_ip.controller_yaml import (
    ClimateIPDeviceState,
    YamlController,
)
from custom_components.climate_ip.controller_yaml_config import _YAML_FILE_CACHE
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import AuthError, CannotConnect
from custom_components.climate_ip.properties import DeviceProperty
from homeassistant.components.climate.const import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_HOST,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_NAME,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.exceptions import HomeAssistantError

_REAL_YAML_CONTROLLER_INITIALIZE = YamlController.initialize


@pytest.fixture(autouse=True)
def clear_yaml_cache():
    """Clear the YAML file cache before each test."""
    _YAML_FILE_CACHE.clear()


def _create_mock_controller(
    config: dict[str, Any] | None = None,
    loader_initialized: bool = True,
) -> YamlController:
    """Create a lightweight YamlController instance with mocked loader and poller."""
    mock_logger = logging.getLogger("test_logger")
    cfg = (
        config
        if config is not None
        else {
            CONF_CONFIG_FILE: "test.yaml",
            CONF_MAC: "mac123",
            CONF_IP_ADDRESS: "127.0.0.1",
        }
    )
    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        ctrl = YamlController(cfg, mock_logger)
        ctrl.loader.is_fully_initialized = loader_initialized
        ctrl.loader.operations = {}
        ctrl.loader.properties = {}
        ctrl.loader.sensors = {}
        ctrl.loader.name = None
        ctrl.loader.poll = None
        ctrl.loader.service_schema_map = None
        ctrl.loader.connection = None
        ctrl.poller.last_icmp_diagnostic = None
        ctrl._attributes = {}
        return ctrl


def test_yaml_controller_init_and_config_validation() -> None:
    """Verify standard initialization, fallbacks, subdevice handling, and initial state."""
    mock_logger = logging.getLogger("test_logger")
    mock_hass = MagicMock()
    mock_session = MagicMock()

    # 1. Full standard initialization
    config_full = {
        CONF_CONFIG_FILE: "test_config.yaml",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_DEVICE_ID: "dev_123",
        CONF_TOKEN: "secret_token",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        "debug": True,
        CONF_TEMP_NATIVE_TARGET: "fahrenheit",
    }
    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch(
            "custom_components.climate_ip.controller_yaml.YamlStatePoller"
        ) as mock_poller_cls,
    ):
        ctrl = YamlController(
            config_full,
            mock_logger,
            hass=mock_hass,
            session=mock_session,
        )
        assert ctrl.hass is mock_hass
        assert ctrl._logger is mock_logger
        assert ctrl._session is mock_session
        assert ctrl._ip_address == "192.168.1.100"
        assert ctrl._token == "secret_token"
        assert ctrl._device_id == "dev_123"
        assert ctrl._unique_id == "AA:BB:CC:DD:EE:FF_dev_123"
        assert ctrl._debug is True
        assert ctrl._temperature_unit == UnitOfTemperature.FAHRENHEIT
        assert ctrl._attributes == {}
        assert ctrl.discovered_devices is None
        assert callable(ctrl.on_token_refreshed)
        assert callable(ctrl.on_push_update_callback)
        assert callable(ctrl.on_offline_callback)
        assert callable(ctrl.request_refresh_callback)
        assert callable(ctrl.on_ssl_config_updated)
        assert callable(ctrl.on_connection_failed_callback)
        mock_poller_cls.assert_called_once_with(ctrl)

    # 2. Fallback host -> ip_address, CONF_MAC -> unique_id, DEVICE_TYPE -> CONFIG_FILE
    config_fallbacks = {
        CONF_HOST: "10.0.0.1",
        CONF_MAC: "00:11:22",
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        "debug": False,
    }
    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        ctrl2 = YamlController(config_fallbacks, mock_logger)
        assert ctrl2._ip_address == "10.0.0.1"
        assert ctrl2._unique_id == "00:11:22"
        assert ctrl2._device_id == "00:11:22"
        assert ctrl2._debug is False
        assert ctrl2._config[CONF_CONFIG_FILE] == "samsung_2878.yaml"
        assert ctrl2._temperature_unit == DEFAULT_CONF_TEMP_UNIT

    # 3. Subdevice with base_id already containing suffix vs without suffix
    assert (
        YamlController._resolve_unique_id("base_id_sub1", None, "sub1")
        == "base_id_sub1"
    )
    assert YamlController._resolve_unique_id("base_id", None, "sub1") == "base_id_sub1"
    assert YamlController._resolve_unique_id(None, None, "sub1") == "sub1"

    # 4. Device ID injection when not in config
    cfg_no_dev = {"ip_address": "127.0.0.1"}
    ctrl_sub = YamlController(cfg_no_dev, mock_logger, device_id="sub_device")
    assert ctrl_sub._config[CONF_DEVICE_ID] == "sub_device"

    # 5. Name trimming and empty name pop
    ctrl_name = YamlController(
        {"ip_address": "127.0.0.1", CONF_NAME: "  Living AC  "}, mock_logger
    )
    assert ctrl_name._config[CONF_NAME] == "Living AC"

    ctrl_empty_name = YamlController(
        {"ip_address": "127.0.0.1", CONF_NAME: "   "}, mock_logger
    )
    assert CONF_NAME not in ctrl_empty_name._config

    # 6. Fallback device_id when unique_id is set
    ctrl_fallback_mac = YamlController(
        {"unique_id": "fallback_mac_only", "ip_address": "127.0.0.1"},
        mock_logger,
    )
    assert ctrl_fallback_mac._device_id == "fallback_mac_only"
    assert ctrl_fallback_mac._debug is False


def test_yaml_controller_init_type_and_value_errors() -> None:
    """Verify TypeError and ValueError validations during YamlController initialization."""
    mock_logger = logging.getLogger("test_logger")

    # Missing config and config_entry
    with pytest.raises(ValueError, match=ERR_MISSING_INIT_CONFIG):
        YamlController(config=None, logger=mock_logger)

    # Invalid config type
    for invalid_cfg in ("string", 123, ["list"]):
        with pytest.raises(TypeError, match="Expected dict for config"):
            YamlController(config=invalid_cfg, logger=mock_logger)  # type: ignore[arg-type]

    # TypeErrors for string parameters
    with pytest.raises(TypeError, match=f"Expected str for {CONF_CONFIG_FILE}"):
        YamlController({"ip_address": "127.0.0.1", CONF_CONFIG_FILE: 123}, mock_logger)

    with pytest.raises(TypeError, match=f"Expected str for {CONF_DEVICE_TYPE}"):
        YamlController({"ip_address": "127.0.0.1", CONF_DEVICE_TYPE: 123}, mock_logger)

    with pytest.raises(TypeError, match=f"Expected str for {CONF_NAME}"):
        YamlController({"ip_address": "127.0.0.1", CONF_NAME: 123}, mock_logger)

    with pytest.raises(TypeError, match=f"Expected str for {CONF_DEVICE_ID}"):
        YamlController({"ip_address": "127.0.0.1", CONF_DEVICE_ID: 123}, mock_logger)

    with pytest.raises(TypeError, match=f"Expected str for {CONF_TOKEN}"):
        YamlController({"ip_address": "127.0.0.1", CONF_TOKEN: 123}, mock_logger)

    with pytest.raises(TypeError, match=f"Expected str for {CONF_UNIQUE_ID}"):
        YamlController._resolve_unique_id(123, None, None)

    with pytest.raises(TypeError, match=f"Expected str for {CONF_MAC}"):
        YamlController._resolve_unique_id(None, 123, None)

    with pytest.raises(TypeError, match=f"{CONF_IP_ADDRESS} must be a string"):
        YamlController({"ip_address": 123}, mock_logger)

    with pytest.raises(TypeError, match=f"{CONF_HOST} must be a string"):
        YamlController({"host": 123}, mock_logger)

    # Missing / empty IP and Host
    with pytest.raises(ValueError, match=ERR_MISSING_IP):
        YamlController({"ip_address": "   ", "host": "   "}, mock_logger)

    with pytest.raises(ValueError, match=ERR_MISSING_IP):
        YamlController({}, mock_logger)

    # Non-bool debug
    with pytest.raises(TypeError, match=f"Expected strict bool for {CONF_DEBUG}"):
        YamlController({"ip_address": "127.0.0.1", "debug": "true"}, mock_logger)

    # Empty whitespace device_id and token fallback to None
    ctrl_ws = YamlController(
        {
            "ip_address": "127.0.0.1",
            CONF_DEVICE_ID: "   ",
            CONF_TOKEN: "   ",
        },
        mock_logger,
    )
    assert ctrl_ws._device_id is None
    assert ctrl_ws._token is None


def test_from_config_entry_and_extract_config() -> None:
    """Test from_config_entry factory method and _extract_config_from_entry."""
    mock_hass = MagicMock()
    mock_entry = MagicMock(spec=ConfigEntry)
    mock_entry.entry_id = "entry_123"
    mock_entry.unique_id = "uniq_456"
    mock_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.50",
        CONF_CONFIG_FILE: "test.yaml",
        CONF_MAC: "11:22:33:44:55:66",
        CONF_TOKEN: "tok_abc",
    }
    mock_entry.options = {
        "debug": True,
        CONF_IP_ADDRESS: "10.0.0.99",
    }

    custom_logger = logging.getLogger("custom_logger")
    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        ctrl = YamlController.from_config_entry(
            config_entry=mock_entry,
            hass=mock_hass,
            device_id="sub_dev",
            logger=custom_logger,
        )
        assert ctrl.hass is mock_hass
        assert ctrl._logger is custom_logger
        assert ctrl._device_id == "sub_dev"
        assert ctrl._unique_id == "uniq_456_sub_dev"
        assert ctrl._ip_address == "192.168.1.50"
        assert ctrl._debug is True

        ctrl_def = YamlController.from_config_entry(
            config_entry=mock_entry,
            hass=mock_hass,
            device_id=None,
        )
        assert ctrl_def._logger is not None
        assert ctrl_def._device_id == "uniq_456"

        extracted = YamlController._extract_config_from_entry(
            mock_entry, device_id="   "
        )
        assert CONF_DEVICE_ID not in extracted
        assert extracted["entry_id"] == "entry_123"
        assert extracted["unique_id"] == "uniq_456"


def test_yaml_controller_port_resolution_and_validation() -> None:
    """Test resolution and fail-fast validation of the port property."""
    mock_logger = logging.getLogger("test_logger")

    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        # 1. Valid integers and boundary conditions
        c_int = YamlController({"port": 8888, "ip_address": "127.0.0.1"}, mock_logger)
        assert c_int.port == 8888
        assert isinstance(c_int.port, int)

        c_min = YamlController({"port": 1, "ip_address": "127.0.0.1"}, mock_logger)
        assert c_min.port == 1

        c_max = YamlController({"port": 65535, "ip_address": "127.0.0.1"}, mock_logger)
        assert c_max.port == 65535

        # 2. Default fallback when absent or None
        c_absent = YamlController({"ip_address": "127.0.0.1"}, mock_logger)
        assert c_absent.port == PORT_SAMSUNG_8888

        c_none = YamlController({"port": None, "ip_address": "127.0.0.1"}, mock_logger)
        assert c_none.port == PORT_SAMSUNG_8888

        # 3. Numeric string coercion
        c_str = YamlController({"port": "8888", "ip_address": "127.0.0.1"}, mock_logger)
        assert c_str.port == 8888

        c_str_padded = YamlController(
            {"port": "  8888  ", "ip_address": "127.0.0.1"}, mock_logger
        )
        assert c_str_padded.port == 8888

        c_str_min = YamlController(
            {"port": "1", "ip_address": "127.0.0.1"}, mock_logger
        )
        assert c_str_min.port == 1

        c_str_max = YamlController(
            {"port": "65535", "ip_address": "127.0.0.1"}, mock_logger
        )
        assert c_str_max.port == 65535

        # 4. Out-of-range integer validation (ValueError)
        for invalid_int in (-1, 0, 65536, 70000):
            c_inv_int = YamlController(
                {"port": invalid_int, "ip_address": "127.0.0.1"}, mock_logger
            )
            with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
                _ = c_inv_int.port

        # 5. Malformed string validation (ValueError)
        for invalid_str in (
            "-1",
            "0",
            "65536",
            "70000",
            "invalid",
            "",
            "   ",
            "8888abc",
            "12.34",
        ):
            c_inv_str = YamlController(
                {"port": invalid_str, "ip_address": "127.0.0.1"}, mock_logger
            )
            with pytest.raises(ValueError):
                _ = c_inv_str.port

        # 6. Unsupported types (TypeError)
        for invalid_type in (
            True,
            False,
            [8888],
            {"port": 8888},
            8888.0,
            (8888,),
        ):
            c_inv_type = YamlController(
                {"port": invalid_type, "ip_address": "127.0.0.1"}, mock_logger
            )
            with pytest.raises(TypeError, match="Unsupported port type"):
                _ = c_inv_type.port


@pytest.mark.asyncio
async def test_yaml_controller_delegated_properties_and_attributes() -> None:
    """Verify delegated properties, attributes, schema, sensors, cache clearing, and immutability."""
    ctrl = _create_mock_controller()

    # 1. Name resolution priority: config -> loader -> default
    ctrl._config[CONF_NAME] = "Custom Name"
    assert ctrl.name == "Custom Name"

    del ctrl._config[CONF_NAME]
    ctrl.loader.name = "Loader Name"
    assert ctrl.name == "Loader Name"

    ctrl.loader.name = 123
    with pytest.raises(TypeError, match="Expected str for loader name"):
        _ = ctrl.name

    ctrl.loader.name = "   "
    with pytest.raises(ValueError, match="Loader name cannot be empty"):
        _ = ctrl.name

    ctrl.loader.name = None
    assert ctrl.name == DEFAULT_CONTROLLER_NAME

    # 2. Delegated getters and basic properties
    assert ctrl.config == ctrl._config
    ctrl._ip_address = "192.168.1.50"
    assert ctrl.ip_address == "192.168.1.50"
    ctrl._debug = True
    assert ctrl.debug is True
    ctrl.loader.poll = True
    assert ctrl.poll is True
    ctrl._unique_id = "uid_123"
    assert ctrl.unique_id == "uid_123"
    ctrl._device_id = "dev_123"
    assert ctrl.device_id == "dev_123"
    ctrl._token = "tok_123"
    assert ctrl.token == "tok_123"
    assert ctrl.temperature_unit == DEFAULT_CONF_TEMP_UNIT

    # 3. Read-only property setters raise AttributeError
    with pytest.raises(AttributeError):
        ctrl.device_id = "new_dev"
    with pytest.raises(AttributeError):
        ctrl.token = "new_tok"

    # 4. State attributes and update_state_attributes
    ctrl._attributes = {"k1": "v1"}
    assert ctrl.state_attributes == {"k1": "v1"}
    ctrl.update_state_attributes({"k2": "v2"})
    assert ctrl.state_attributes == {"k2": "v2"}
    for inv_attrs in ("not_dict", None, [1, 2]):
        with pytest.raises(TypeError, match="Expected dict for new_attrs"):
            ctrl.update_state_attributes(inv_attrs)  # type: ignore[arg-type]

    # 5. Service schema map, operations, and attributes
    ctrl.loader.service_schema_map = None
    assert ctrl.service_schema_map is None
    ctrl.loader.service_schema_map = {"schema_k": "schema_v"}
    assert ctrl.service_schema_map == {"schema_k": "schema_v"}

    ctrl.loader.operations_list = ["op1", "op2"]
    assert ctrl.operations == ["op1", "op2"]
    ctrl.loader.properties_list = ["attr1"]
    assert ctrl.attributes == ["attr1"]

    # 6. Sensors property
    s1 = MagicMock(spec=DeviceProperty)
    s2 = MagicMock(spec=DeviceProperty)
    ctrl.loader.sensors = {"s1": s1, "s2": s2}
    ctrl.loader.sensors_list = ["s1", "s2"]
    assert ctrl.sensors == [s1, s2]

    # 7. Yaml file and connection
    assert ctrl.yaml_file == "test.yaml"
    ctrl._config = {}
    assert ctrl.yaml_file is None

    mock_conn = MagicMock()
    ctrl.loader.connection = mock_conn
    assert ctrl.connection is mock_conn

    # 8. match_type, clear_state_cache, async_clear_pending_updates, initialize
    assert YamlController.match_type("yaml") is True
    assert YamlController.match_type("other") is False

    mock_poller = MagicMock()
    ctrl.poller = mock_poller
    ctrl.clear_state_cache()
    mock_poller.clear_state_cache.assert_called_once()

    await ctrl.async_clear_pending_updates(["fan_mode"])
    mock_poller.clear_pending_updates.assert_called_once_with(["fan_mode"])

    ctrl.loader.async_initialize = AsyncMock(return_value=True)
    assert await _REAL_YAML_CONTROLLER_INITIALIZE(ctrl) is True
    ctrl.loader.async_initialize.assert_awaited_once()


def test_yaml_controller_availability_and_push() -> None:
    """Verify available and is_push_device properties across all branches."""
    ctrl = _create_mock_controller()

    # 1. Available: no connection
    ctrl.loader.connection = None
    assert ctrl.available is False

    # 2. Available: connection is_available False vs True vs truthy
    conn_mock = MagicMock()
    conn_mock.is_available = False
    ctrl.loader.connection = conn_mock
    assert ctrl.available is False

    conn_mock.is_available = True
    assert ctrl.available is True

    conn_mock.is_available = "connected"
    assert ctrl.available is True

    # 3. is_push_device: no connection -> False
    ctrl.loader.connection = None
    assert ctrl.is_push_device is False

    # 4. is_push_device: missing is_push_supported -> AttributeError (Fail-Fast)
    class LegacyConnection:
        pass

    ctrl.loader.connection = LegacyConnection()
    with pytest.raises(AttributeError):
        _ = ctrl.is_push_device

    # 5. is_push_device: valid connection -> True
    conn_mock.is_push_supported = True
    ctrl.loader.connection = conn_mock
    assert ctrl.is_push_device is True


def test_yaml_controller_connection_diagnostics() -> None:
    """Verify connection_diagnostics assembly and poller last_icmp_diagnostic contract."""
    ctrl = _create_mock_controller()

    # 1. Both connection and last_icmp_diagnostic are None
    ctrl.loader.connection = None
    ctrl.poller.last_icmp_diagnostic = None
    assert ctrl.connection_diagnostics == {}

    # 2. Connection diagnostics present
    mock_conn = MagicMock()
    mock_conn.get_diagnostics.return_value = {"latency_ms": 12, "connected": True}
    ctrl.loader.connection = mock_conn
    assert ctrl.connection_diagnostics == {
        "latency_ms": 12,
        "connected": True,
    }

    # 3. Merged with network reachability
    ctrl.poller.last_icmp_diagnostic = {
        "is_reachable": True,
        "avg_rtt_ms": 1.5,
        "status": "alive",
    }
    assert ctrl.connection_diagnostics == {
        "latency_ms": 12,
        "connected": True,
        "network_reachability": {
            "is_reachable": True,
            "avg_rtt_ms": 1.5,
            "status": "alive",
        },
    }

    # 4. Contract test for YamlStatePoller.last_icmp_diagnostic
    poller = object.__new__(YamlStatePoller)
    poller._last_icmp_diagnostic = None
    assert poller.last_icmp_diagnostic is None
    diag = {"is_reachable": False, "status": "unreachable_timeout"}
    poller._last_icmp_diagnostic = diag
    assert poller.last_icmp_diagnostic is diag


@pytest.mark.asyncio
async def test_yaml_controller_state_and_polling_delegation() -> None:
    """Verify state getters and delegation to poller methods."""
    ctrl = _create_mock_controller()

    # 1. device_state: returns poller dict
    ctrl.poller.device_state = {"poller_key": "val1"}
    assert ctrl.device_state == {"poller_key": "val1"}

    # 2. device_state: empty dict is valid and does not fall back
    ctrl.poller.device_state = {}
    mock_state_getter = MagicMock()
    mock_state_getter.value = {"loader_key": "val2"}
    ctrl.loader.state_getter = mock_state_getter
    assert ctrl.device_state == {}

    # 3. device_state: None raises TypeError
    ctrl.poller.device_state = None
    with pytest.raises(TypeError):
        _ = ctrl.device_state

    # 4. pure_device_state: valid dict vs invalid
    ctrl.poller.pure_network_state = {"net_key": "net_val"}
    assert ctrl.pure_device_state == {"net_key": "net_val"}

    for inv_state in ("invalid", None):
        ctrl.poller.pure_network_state = inv_state
        with pytest.raises(TypeError):
            _ = ctrl.pure_device_state

    # 5. last_poll_data: None vs dict
    ctrl.loader.state_getter = None
    assert ctrl.last_poll_data is None
    mock_state_getter.value = {"raw_temp": 25}
    ctrl.loader.state_getter = mock_state_getter
    assert ctrl.last_poll_data == {"raw_temp": 25}

    # 6. Poller async delegates
    ctrl.poller.async_get_status = AsyncMock(return_value={"status": "ok"})
    assert await ctrl.async_get_status() == {"status": "ok"}
    ctrl.poller.async_get_status.assert_awaited_once()

    ctrl.poller.async_update_state = AsyncMock(return_value={"state": "active"})
    assert await ctrl.async_update_state() == {"state": "active"}
    ctrl.poller.async_update_state.assert_awaited_once()

    ctrl.poller.async_update_state = AsyncMock(return_value=None)
    assert await ctrl.async_update_state() is None

    ctrl.poller.async_shutdown = AsyncMock()
    await ctrl.async_shutdown()
    ctrl.poller.async_shutdown.assert_awaited_once()

    assert await ctrl.async_refresh_from_connection() is None

    ctrl.poller.async_merge_device_state = AsyncMock(return_value=True)
    assert await ctrl.async_merge_device_state({"k": "v"}) is True
    ctrl.poller.async_merge_device_state.assert_awaited_once_with({"k": "v"})

    ctrl.poller.async_predict_and_correct_state = AsyncMock(
        return_value=(True, {"st": 1})
    )
    assert await ctrl.async_predict_and_correct_state("state", "prop", "val") == (
        True,
        {"st": 1},
    )
    ctrl.poller.async_predict_and_correct_state.assert_awaited_once_with(
        "state", "prop", "val"
    )


def test_yaml_controller_is_property_superseded() -> None:
    """Test is_property_superseded logic under all pending updates states."""
    ctrl = _create_mock_controller()
    ctrl.poller._pending_updates = {
        "target_temperature": (22.0, 100.0),
    }

    # 1. Property not in pending updates
    assert ctrl.is_property_superseded("power", "on") is False

    # 2. Property in pending updates with same value
    assert ctrl.is_property_superseded("target_temperature", 22.0) is False

    # 3. Property in pending updates with different value (superseded)
    assert ctrl.is_property_superseded("target_temperature", 24.0) is True


def test_yaml_controller_has_property() -> None:
    """Verify has_property argument validation, loader lookup, and attributes fallback."""
    ctrl = _create_mock_controller()

    # 1. Invalid parameter types / empty strings -> TypeError
    for invalid_prop in ("", "   ", None, 123):
        with pytest.raises(TypeError):
            ctrl.has_property(invalid_prop)  # type: ignore[arg-type]

    # 2. Found in loader operations
    mock_op = MagicMock(spec=DeviceProperty)
    ctrl.loader.operations = {"op_prop": mock_op}
    ctrl._attributes = {}
    assert ctrl.has_property("op_prop") is True

    # 3. Found only in _attributes
    ctrl.loader.operations = {}
    ctrl._attributes = {"attr_prop": "val"}
    assert ctrl.has_property("attr_prop") is True

    # 4. Missing from both
    assert ctrl.has_property("missing_prop") is False


def test_yaml_controller_get_property_and_values() -> None:
    """Verify get_property and get_property_all_values extraction and strict validation."""
    ctrl = _create_mock_controller()

    # 1. get_property argument validation
    for invalid_arg in ("", "   ", None, 123):
        with pytest.raises(TypeError):
            ctrl.get_property(invalid_arg)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            ctrl.get_property_all_values(invalid_arg)  # type: ignore[arg-type]

    # 2. get_property extraction hierarchy
    mock_op = MagicMock(spec=DeviceProperty)
    mock_op.value = "op_value"
    ctrl.loader.operations = {"test_op": mock_op}
    ctrl._attributes = {
        "test_attr": "attr_value",
        "unknown_attr": STATE_UNKNOWN,
        "none_attr": None,
    }

    assert ctrl.get_property("test_op") == "op_value"
    assert ctrl.get_property("test_attr") == "attr_value"
    assert ctrl.get_property("unknown_attr") is None
    assert ctrl.get_property("none_attr") is None

    with pytest.raises(KeyError, match=ERR_UNREGISTERED_PROPERTY):
        ctrl.get_property("missing_key")

    # 3. get_property_all_values validation and extraction
    mock_op_vals = MagicMock(spec=DeviceProperty)
    mock_op_vals.all_values = ["val1", "val2"]
    mock_op_no_vals = MagicMock(spec=DeviceProperty)
    mock_op_no_vals.all_values = None
    mock_op_bad_type = MagicMock(spec=DeviceProperty)
    mock_op_bad_type.all_values = 12345
    mock_op_bad_item = MagicMock(spec=DeviceProperty)
    mock_op_bad_item.all_values = ["val1", 99]

    ctrl.loader.operations = {
        "good_op": mock_op_vals,
        "bad_op": mock_op_no_vals,
        "bad_type_op": mock_op_bad_type,
        "bad_item_op": mock_op_bad_item,
    }

    assert ctrl.get_property_all_values("good_op") == ("val1", "val2")
    assert ctrl.get_property_all_values("bad_op") is None
    assert ctrl.get_property_all_values("missing_op") is None

    with pytest.raises(TypeError, match="Expected iterable for bad_type_op all_vals"):
        ctrl.get_property_all_values("bad_type_op")

    with pytest.raises(TypeError, match="Mode value must be a string"):
        ctrl.get_property_all_values("bad_item_op")


def test_yaml_controller_get_property_object_and_caching() -> None:
    """Verify get_property_object search hierarchy, caching, uninitialized guards, and collisions."""
    ctrl = _create_mock_controller()

    # 1. Invalid argument types
    for invalid_arg in ("", "   ", None, 123):
        with pytest.raises(TypeError):
            ctrl.get_property_object(invalid_arg)  # type: ignore[arg-type]

    # 2. Loader not initialized -> get_property_object returns None, _objects_by_id raises
    ctrl.loader.is_fully_initialized = False
    assert ctrl.get_property_object("any_prop") is None
    with pytest.raises(RuntimeError, match=ERR_CACHE_UNINITIALIZED):
        _ = ctrl._objects_by_id
    ctrl.loader.is_fully_initialized = True

    # 3. Hierarchy in loader (operations -> properties -> sensors -> _objects_by_id)
    mock_op = MagicMock(spec=DeviceProperty)
    mock_prop = MagicMock(spec=DeviceProperty)
    mock_sensor = MagicMock(spec=DeviceProperty)

    ctrl.loader.operations = {"test_op": mock_op}
    ctrl.loader.properties = {"test_prop": mock_prop}
    ctrl.loader.sensors = {"test_sensor": mock_sensor}

    assert ctrl.get_property_object("test_op") is mock_op
    assert ctrl.get_property_object("test_prop") is mock_prop
    assert ctrl.get_property_object("test_sensor") is mock_sensor

    # 4. _objects_by_id caching, hass_attr mapping, whitespace/None filtering, and collision guard
    ctrl._obj_id_cache = None
    op1 = MagicMock(spec=DeviceProperty)
    op1.id = "power_id"
    op2 = MagicMock(spec=DeviceProperty)
    op2.id = "temp_id"
    op3 = MagicMock(spec=DeviceProperty)
    op3.id = "empty_hass_id"
    op4 = MagicMock(spec=DeviceProperty)
    op4.id = "collision_id"
    op5 = MagicMock(spec=DeviceProperty)
    op5.id = "other_id"

    ctrl.loader.sensors = {}
    ctrl.loader.properties = {}
    ctrl.loader.operations = {
        "op1": op1,
        "op2": op2,
        "op3": op3,
        "op4": op4,
        "op5": op5,
    }

    def mock_get_hass_attr(op_id: str) -> Any:
        if op_id == "power_id":
            return "power_attr"
        if op_id == "temp_id":
            return "   "
        if op_id == "empty_hass_id":
            return None
        if op_id == "collision_id":
            return "power_id"
        return 123

    ctrl.poller.get_hass_attr_for_op_id = MagicMock(side_effect=mock_get_hass_attr)

    cache = ctrl._objects_by_id
    assert cache["power_id"] is op1
    assert cache["power_attr"] is op1
    assert cache["temp_id"] is op2
    assert "   " not in cache
    assert "" not in cache
    assert cache["empty_hass_id"] is op3
    assert cache["collision_id"] is op4
    assert cache["power_id"] is op1

    # Verify get_property_object finds object through _objects_by_id
    assert ctrl.get_property_object("power_attr") is op1
    assert ctrl.get_property_object("missing_key") is None


@patch("custom_components.climate_ip.controller_yaml.ClimateIPDeviceState")
def test_yaml_controller_climate_state_mapping(
    mock_state_class: MagicMock,
) -> None:
    """Verify climate_state strictly maps all attributes, temperatures, and modes."""
    ctrl = _create_mock_controller()

    def mock_get_prop(prop: str) -> Any:
        if prop == ATTR_HVAC_MODE:
            return "cool"
        if prop == ATTR_TEMPERATURE:
            return 22.5
        if prop == ATTR_CURRENT_TEMPERATURE:
            return 25.0
        if prop == ATTR_FAN_MODE:
            return "high"
        if prop == ATTR_SWING_MODE:
            return "on"
        if prop == ATTR_PRESET_MODE:
            return "eco"
        return f"val_{prop}"

    ctrl.get_property = MagicMock(side_effect=mock_get_prop)
    ctrl.has_property = MagicMock(return_value=True)

    ctrl.loader.operations = {
        "hvac_mode": MagicMock(
            spec=DeviceProperty, all_values=["auto", "heat", "cool"]
        ),
        "target_temperature": MagicMock(spec=DeviceProperty),
        "current_temperature": MagicMock(spec=DeviceProperty),
        "fan_mode": MagicMock(spec=DeviceProperty, all_values=["high", "low"]),
        "swing_mode": MagicMock(spec=DeviceProperty, all_values=["on", "off"]),
        "preset_mode": MagicMock(spec=DeviceProperty, all_values=["eco"]),
    }

    _ = ctrl.climate_state
    assert ctrl.get_property("other_prop") == "val_other_prop"

    mock_state_class.assert_called_once_with(
        hvac_mode=HVACMode.COOL,
        target_temperature=22.5,
        current_temperature=25.0,
        fan_mode="high",
        swing_mode="on",
        preset_mode="eco",
        hvac_modes=(HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL),
        fan_modes=("high", "low"),
        swing_modes=("on", "off"),
        preset_modes=("eco",),
    )


def test_yaml_controller_climate_state_edge_cases() -> None:
    """Verify climate_state under uninitialized loader, dynamic modes, KeyError, and invalid modes."""
    ctrl = _create_mock_controller()

    # 1. Loader uninitialized -> returns empty ClimateIPDeviceState
    ctrl.loader.is_fully_initialized = False
    assert ctrl.climate_state == ClimateIPDeviceState()
    ctrl.loader.is_fully_initialized = True

    # 2. Dynamic modes overriding static fallback
    prop_fan = MagicMock(spec=DeviceProperty)
    prop_fan.values = ["turbo", "quiet"]
    prop_fan.all_values = ["low", "high"]

    prop_swing = MagicMock(spec=DeviceProperty)
    prop_swing.values = ["auto", "fixed"]
    prop_swing.all_values = ["on", "off"]

    ctrl.loader.operations = {
        ATTR_HVAC_MODE: MagicMock(
            spec=DeviceProperty, all_values=["cool", "heat", "off"]
        ),
        ATTR_FAN_MODE: prop_fan,
        ATTR_SWING_MODE: prop_swing,
    }

    # 3. KeyError in _get_val caught cleanly and returns None
    ctrl.get_property = MagicMock(side_effect=KeyError("Unregistered"))
    state = ctrl.climate_state
    assert state.fan_modes == ("turbo", "quiet")
    assert state.swing_modes == ("auto", "fixed")
    assert state.hvac_mode is None

    # 4. HVACMode.OFF when not in hvac_modes does not raise
    ctrl._cached_static_modes = None
    ctrl.loader.operations[ATTR_HVAC_MODE].all_values = ["cool", "heat"]
    ctrl.get_property = MagicMock(
        side_effect=lambda p: "off" if p == ATTR_HVAC_MODE else None
    )
    state_off = ctrl.climate_state
    assert state_off.hvac_mode == HVACMode.OFF

    # 5. Invalid HVAC mode raises ValueError
    ctrl._cached_static_modes = None
    ctrl.get_property = MagicMock(
        side_effect=lambda p: "dry" if p == ATTR_HVAC_MODE else None
    )
    with pytest.raises(ValueError, match=ERR_INVALID_DEVICE_MODE):
        _ = ctrl.climate_state


def test_yaml_controller_safe_parsers_and_mode_validator() -> None:
    """Verify _safe_parse_hvac_mode, _safe_parse_temperature, and _validate_mode_value."""
    ctrl = _create_mock_controller()

    # 1. _safe_parse_hvac_mode
    assert ctrl._safe_parse_hvac_mode(None) is None
    assert ctrl._safe_parse_hvac_mode(HVACMode.COOL) == HVACMode.COOL
    assert ctrl._safe_parse_hvac_mode("cool") == HVACMode.COOL
    assert ctrl._safe_parse_hvac_mode("  HEAT  ") == HVACMode.HEAT
    assert ctrl._safe_parse_hvac_mode("") is None
    assert ctrl._safe_parse_hvac_mode("   ") is None
    with pytest.raises(TypeError, match="HVAC mode must be a string or HVACMode"):
        ctrl._safe_parse_hvac_mode(123)
    with pytest.raises(ValueError):
        ctrl._safe_parse_hvac_mode("invalid_mode")

    # 2. _safe_parse_temperature
    assert ctrl._safe_parse_temperature(None, "temp") is None
    assert ctrl._safe_parse_temperature("", "temp") is None
    assert ctrl._safe_parse_temperature("   ", "temp") is None
    assert ctrl._safe_parse_temperature("23.5", "temp") == 23.5
    assert ctrl._safe_parse_temperature("  24  ", "temp") == 24.0
    assert ctrl._safe_parse_temperature(24, "temp") == 24.0
    assert ctrl._safe_parse_temperature(24.5, "temp") == 24.5

    with pytest.raises(TypeError, match="cannot be a boolean"):
        ctrl._safe_parse_temperature(True, "temp")
    with pytest.raises(TypeError, match="cannot be a boolean"):
        ctrl._safe_parse_temperature(False, "temp")
    with pytest.raises(TypeError, match="Expected numeric or string for temp"):
        ctrl._safe_parse_temperature(object(), "temp")
    with pytest.raises(ValueError, match="Invalid numeric string for temp"):
        ctrl._safe_parse_temperature("invalid_num", "temp")
    with pytest.raises(ValueError, match="Non-finite temperature value"):
        ctrl._safe_parse_temperature(float("nan"), "temp")
    with pytest.raises(ValueError, match="Non-finite temperature value"):
        ctrl._safe_parse_temperature(float("inf"), "temp")

    # 3. _validate_mode_value
    assert ctrl._validate_mode_value(None, ("cool", "heat"), "fan_mode") is None
    assert ctrl._validate_mode_value("", ("cool", "heat"), "fan_mode") is None
    assert ctrl._validate_mode_value("   ", ("cool", "heat"), "fan_mode") is None
    assert ctrl._validate_mode_value("cool", ("cool", "heat"), "fan_mode") == "cool"
    assert ctrl._validate_mode_value("  heat  ", ("cool", "heat"), "fan_mode") == "heat"
    with pytest.raises(TypeError, match="fan_mode must be a string"):
        ctrl._validate_mode_value(123, ("cool", "heat"), "fan_mode")
    with pytest.raises(ValueError, match=ERR_INVALID_DEVICE_MODE):
        ctrl._validate_mode_value("dry", ("cool", "heat"), "fan_mode")


@pytest.mark.asyncio
async def test_yaml_controller_async_set_property_fail_fast_branches() -> None:
    """Test async_set_property argument validation, device resolution, and rollback."""
    ctrl = _create_mock_controller()

    # 1. Invalid property_name type / empty string -> TypeError
    for inv_prop in ("", "   ", None):
        with pytest.raises(TypeError):
            await ctrl.async_set_property(inv_prop, "val")  # type: ignore[arg-type]

    # 2. Invalid device_id type -> TypeError
    for inv_dev in (12345, "", "   "):
        with pytest.raises(TypeError):
            await ctrl.async_set_property("fan_mode", "high", device_id=inv_dev)  # type: ignore[arg-type]

    # 3. Uninitialized loader -> HomeAssistantError
    ctrl.loader.is_fully_initialized = False
    with pytest.raises(HomeAssistantError):
        await ctrl.async_set_property("target_temperature", 22)
    ctrl.loader.is_fully_initialized = True

    # 4. Missing property -> HomeAssistantError
    ctrl.loader.operations = {}
    with pytest.raises(HomeAssistantError):
        await ctrl.async_set_property("missing_prop", 22)

    # Setup mock operation
    mock_op = AsyncMock(spec=DeviceProperty)
    mock_op.async_set_value.return_value = True
    ctrl.loader.operations = {"target_temperature": mock_op}
    ctrl._unique_id = "uniq_base_123"
    ctrl._device_id = "dev_base_456"

    # 5. Device ID resolution branching
    # 5a. Explicit sub-device
    res = await ctrl.async_set_property(
        "target_temperature", 22, device_id="sub_device_1"
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(22, "sub_device_1")

    # 5b. Whitespace-padded sub-device
    mock_op.reset_mock()
    res = await ctrl.async_set_property(
        "target_temperature", 23, device_id="  sub_device_2  "
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(23, "sub_device_2")

    # 5c. device_id=None -> falls back to self.device_id
    mock_op.reset_mock()
    res = await ctrl.async_set_property("target_temperature", 24, device_id=None)
    assert res is True
    mock_op.async_set_value.assert_called_once_with(24, "dev_base_456")

    # 5d. device_id=MAIN_DEVICE_ID -> resolves to self._unique_id
    mock_op.reset_mock()
    res = await ctrl.async_set_property(
        "target_temperature", 26, device_id=MAIN_DEVICE_ID
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(26, "uniq_base_123")

    # 5e. device_id=None and self.device_id is MAIN_DEVICE_ID -> resolves to self._unique_id
    ctrl._device_id = MAIN_DEVICE_ID
    mock_op.reset_mock()
    res = await ctrl.async_set_property("target_temperature", 27, device_id=None)
    assert res is True
    mock_op.async_set_value.assert_called_once_with(27, "uniq_base_123")

    # 5f. device_id=None and self.device_id is None -> resolves to self._unique_id
    ctrl._device_id = None
    mock_op.reset_mock()
    res = await ctrl.async_set_property("target_temperature", 28, device_id=None)
    assert res is True
    mock_op.async_set_value.assert_called_once_with(28, "uniq_base_123")

    # 5g. device_id=None and self.device_id is "" -> resolves to self._unique_id
    ctrl._device_id = ""
    mock_op.reset_mock()
    res = await ctrl.async_set_property("target_temperature", 29, device_id=None)
    assert res is True
    mock_op.async_set_value.assert_called_once_with(29, "uniq_base_123")

    # 6. Exception handling and rollback via poller.clear_pending_updates
    ctrl.poller.clear_pending_updates = MagicMock()

    # 6a. TimeoutError -> HomeAssistantError + rollback
    mock_op.async_set_value.side_effect = TimeoutError("Connection timed out")
    ctrl.poller.clear_pending_updates.reset_mock()
    with pytest.raises(
        HomeAssistantError, match="Communication failed: Connection timed out"
    ):
        await ctrl.async_set_property("target_temperature", 22)
    ctrl.poller.clear_pending_updates.assert_called_once_with(["target_temperature"])

    # 6b. OSError -> HomeAssistantError + rollback
    mock_op.async_set_value.side_effect = OSError("Socket unreachable")
    ctrl.poller.clear_pending_updates.reset_mock()
    with pytest.raises(
        HomeAssistantError, match="Communication failed: Socket unreachable"
    ):
        await ctrl.async_set_property("target_temperature", 22)
    ctrl.poller.clear_pending_updates.assert_called_once_with(["target_temperature"])

    # 6c. Domain exceptions propagate directly + rollback
    mock_op.async_set_value.side_effect = CannotConnect("No route to host")
    ctrl.poller.clear_pending_updates.reset_mock()
    with pytest.raises(CannotConnect):
        await ctrl.async_set_property("target_temperature", 22)
    ctrl.poller.clear_pending_updates.assert_called_once_with(["target_temperature"])

    mock_op.async_set_value.side_effect = AuthError("Auth failure")
    ctrl.poller.clear_pending_updates.reset_mock()
    with pytest.raises(AuthError):
        await ctrl.async_set_property("target_temperature", 22)
    ctrl.poller.clear_pending_updates.assert_called_once_with(["target_temperature"])

    # 6d. Result is False -> Rollback
    mock_op.async_set_value.side_effect = None
    mock_op.async_set_value.return_value = False
    ctrl.poller.clear_pending_updates.reset_mock()
    res_false = await ctrl.async_set_property("target_temperature", 22)
    assert res_false is False
    ctrl.poller.clear_pending_updates.assert_called_once_with(["target_temperature"])


@pytest.mark.asyncio
async def test_yaml_controller_async_set_property_state_injection_and_pending_update() -> (
    None
):
    """Verify state injection branches and pending update registration in async_set_property."""
    ctrl = _create_mock_controller()

    mock_op = AsyncMock(spec=DeviceProperty)
    mock_op.async_set_value.return_value = True
    ctrl.loader.operations = {"fan_mode": mock_op}

    mock_state_getter = MagicMock()
    mock_state_getter.value = {"fan_speed": "low", "power": "on"}
    ctrl.loader.state_getter = mock_state_getter

    res = await ctrl.async_set_property("fan_mode", "high")
    assert res is True
    ctrl.poller.inject_optimistic_state.assert_called_once_with(
        mock_op, "high", mock_state_getter.value
    )
    ctrl.poller.register_pending_update.assert_called_once_with("fan_mode", "high")


def test_yaml_state_poller_inject_optimistic_state() -> None:
    """Verify YamlStatePoller.inject_optimistic_state branches and state injection."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_ctrl = MagicMock()
    poller = YamlStatePoller(mock_ctrl)
    poller._inject_value_into_state = MagicMock()

    mock_op = MagicMock()

    # Case 1: _pure_network_state is None and state_getter_val is dict
    sg_val = {"fan_speed": "low", "power": "on"}
    poller.inject_optimistic_state(mock_op, "high", sg_val)
    assert poller._pure_network_state == {"fan_speed": "low", "power": "on"}
    assert poller._pure_network_state is not sg_val
    assert poller._inject_value_into_state.call_count == 2
    poller._inject_value_into_state.assert_any_call(
        mock_op, poller._pure_network_state, "high"
    )
    poller._inject_value_into_state.assert_any_call(mock_op, sg_val, "high")

    # Case 2: _pure_network_state already set -> deepcopy skipped
    poller._inject_value_into_state.reset_mock()
    poller.inject_optimistic_state(mock_op, "auto", {"fan_speed": "medium"})
    assert poller._inject_value_into_state.call_count == 2

    # Case 3: state_getter_val is None
    poller._inject_value_into_state.reset_mock()
    poller.inject_optimistic_state(mock_op, "auto", None)
    assert poller._inject_value_into_state.call_count == 1

    # Case 4: state_getter_val is not dict
    poller._inject_value_into_state.reset_mock()
    poller.inject_optimistic_state(mock_op, "auto", "not_a_dict")  # type: ignore[arg-type]
    assert poller._inject_value_into_state.call_count == 1


def test_platform_schema_removed() -> None:
    """Verify that PLATFORM_SCHEMA is not exported by controller_yaml."""
    module = importlib.import_module("custom_components.climate_ip.controller_yaml")
    assert not hasattr(module, "PLATFORM_SCHEMA")
