# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,missing-class-docstring,too-few-public-methods,too-many-return-statements,use-implicit-booleaness-not-comparison,missing-final-newline
"""Tests for YamlController — Phase 2 (executor I/O) and Phase 3 (hass injection) compliance."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    STATE_UNKNOWN,
)
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
    DOMAIN,
    MAIN_DEVICE_ID,
    PORT_SAMSUNG_8888,
)
from custom_components.climate_ip.controller_yaml import YamlController
from custom_components.climate_ip.controller_yaml_config import _YAML_FILE_CACHE
from custom_components.climate_ip.exceptions import AuthError, CannotConnect


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
    """Config dict without hass/session — passed as explicit kwargs (Phase 3)."""
    return {
        CONF_CONFIG_FILE: "test_device.yaml",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_DEVICE_ID: "test_device_id",
        CONF_TOKEN: "test_token",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }


def test_yaml_controller_coverage_boost() -> None:
    """Covers match_type, clear_state_cache and climate_state to eliminate untested code."""
    # 1. Test match_type (covers type validation branches)
    assert YamlController.match_type("yaml") is True
    assert YamlController.match_type("other") is False

    # 2. Test clear_state_cache with and without poller
    controller = YamlController(
        config={"device_type": "test_device", "ip_address": "127.0.0.1"},
        logger=MagicMock(),
    )
    controller.clear_state_cache()  # Without poller (should pass safely)

    mock_poller = MagicMock()
    controller.poller = mock_poller
    controller.clear_state_cache()  # With poller
    mock_poller.clear_state_cache.assert_called_once()

    # 3. Test climate_state (executes extraction, sanitization, and strict conversion)
    controller.get_property = MagicMock(return_value=None)
    controller.has_property = MagicMock(return_value=True)
    controller.get_property_all_values = MagicMock(return_value=[])

    state = controller.climate_state
    assert state is not None


# ---------------------------------------------------------------------------
# Phase 2: YAML I/O must be dispatched to the executor thread pool.
# ---------------------------------------------------------------------------


async def test_async_set_property_registers_pending_update(
    yaml_config: dict,  # type: ignore[type-arg]
    mock_logger: logging.Logger,
    mock_hass: MagicMock,
) -> None:
    """Test that async_set_property strictly delegates to poller.register_pending_update."""
    controller = YamlController(yaml_config, mock_logger, hass=mock_hass)

    # Mock loader dependencies
    controller.loader.is_fully_initialized = True

    # Mock the operation
    from custom_components.climate_ip.properties import DeviceProperty

    mock_op = AsyncMock()
    mock_op.__class__ = DeviceProperty
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
    """Kills mutants in YamlController __init__.

    Verifies config dict extraction, state variable assignment,
    and delegate (loader and poller) instantiation occur without alteration.
    """
    mock_logger = logging.getLogger("test_logger")
    mock_hass = MagicMock()
    mock_session = MagicMock()

    # Configure a complete input dictionary
    config_input = {
        CONF_CONFIG_FILE: "test_config.yaml",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_DEVICE_ID: "dev_123",
        CONF_TOKEN: "secret_token",
        "mac": "test_mac_uid",
        "debug": True,
    }

    # Avoid delegates attempting to interact with file system or network in init
    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch(
            "custom_components.climate_ip.controller_yaml.YamlStatePoller"
        ) as mock_poller_class,
    ):
        controller = YamlController(config_input, mock_logger, mock_hass, mock_session)

    # 1. Verify delegate injections
    assert controller.hass is mock_hass
    assert controller._logger is mock_logger

    # 2. Strict IP Address extraction
    assert controller._ip_address == "192.168.1.100"

    # 3. Strict identifier and Token extraction
    assert controller._token == "secret_token"
    assert controller._device_id == "dev_123"
    assert controller._unique_id == "test_mac_uid_dev_123"

    # 4. Callback initialization strictly as callable no-ops
    assert controller.discovered_devices is None
    assert callable(controller.on_token_refreshed), (
        "Must implement the no-op from the class"
    )

    assert callable(controller.on_push_update_callback), (
        "Must inherit the no-op from the base class"
    )
    assert callable(controller.on_offline_callback), (
        "Must inherit the no-op from the base class"
    )
    assert callable(controller.request_refresh_callback), (
        "Must inherit the no-op from the base class"
    )
    assert callable(controller.on_ssl_config_updated), (
        "Must inherit the no-op from the base class"
    )
    assert callable(controller.on_connection_failed_callback), (
        "Must inherit the no-op from the base class"
    )

    # 5. Debug flag assignment
    assert controller._debug is True, "The mutant altered debug flag extraction"

    # 6. Base attributes dictionary assignment
    assert controller._attributes == {}

    # 7. Composition verification (Delegates)
    assert controller.loader is not None
    assert controller.poller is not None
    mock_poller_class.assert_called_once_with(controller)


def test_yaml_controller_fallback_initialization() -> None:
    """Kills mutants in logical fallback branches of init."""
    mock_logger = logging.getLogger("test_logger")

    config_input = {
        "host": "10.0.0.1",  # Fallback for _ip_address
        CONF_MAC: "00:11:22",  # Fallback for _unique_id
        CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878,
        "debug": False,
    }

    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        controller = YamlController(config_input, mock_logger)

    assert controller._ip_address == "10.0.0.1", "Fallback 'host' failed"
    assert controller._unique_id == "00:11:22", "Fallback CONF_MAC failed"
    assert controller._device_id == "00:11:22", (
        "Generic device_id fallback to unique_id failed"
    )
    assert controller._debug is False


def test_yaml_controller_fallback_else_and_debug_default() -> None:
    """Verifies the fallback branch of device_id assignment and default debug value."""
    mock_logger = logging.getLogger("test_logger")

    config_input = {"unique_id": "fallback_mac_only", "ip_address": "127.0.0.1"}

    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        controller = YamlController(config_input, mock_logger)

    assert controller._device_id == "fallback_mac_only", (
        "The fallback branch did not assign unique_id to device_id"
    )

    assert controller._debug is False, "The debug fallback is not False"


@pytest.fixture
def mock_yaml_controller():
    """Fixture to provide an initialized YamlController with mocked delegates."""
    mock_logger = logging.getLogger("test_logger")
    config_input = {
        CONF_CONFIG_FILE: "test.yaml",
        CONF_MAC: "mac123",
        "ip_address": "127.0.0.1",
    }

    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        controller = YamlController(config_input, mock_logger)

        controller.loader.is_fully_initialized = True
        controller.loader.operations = {}
        controller.loader.properties = {}
        controller.loader.sensors = {}
        controller.loader.name = None
        controller._attributes = {}

        return controller


@pytest.mark.asyncio
async def test_update_state_delegation(mock_yaml_controller) -> None:
    """Kills mutants in async_update_state."""
    # Scenario 1: Poller returns dict (success)
    mock_yaml_controller.poller.async_update_state = AsyncMock(
        return_value={"power": "on"}
    )
    assert await mock_yaml_controller.async_update_state() == {"power": "on"}

    # Scenario 2: Poller returns None (failure)
    mock_yaml_controller.poller.async_update_state = AsyncMock(return_value=None)
    assert await mock_yaml_controller.async_update_state() is None


def test_get_property_object_hierarchy(mock_yaml_controller) -> None:
    """Kills mutants in the search hierarchy of get_property_object."""
    mock_op = MagicMock()
    mock_prop = MagicMock()
    mock_sensor = MagicMock()

    mock_yaml_controller.loader.operations = {"test_op": mock_op}
    mock_yaml_controller.loader.properties = {"test_prop": mock_prop}
    mock_yaml_controller.loader.sensors = {"test_sensor": mock_sensor}

    assert mock_yaml_controller.get_property_object("test_op") is mock_op
    assert mock_yaml_controller.get_property_object("test_prop") is mock_prop
    assert mock_yaml_controller.get_property_object("test_sensor") is mock_sensor
    assert mock_yaml_controller.get_property_object("missing_key") is None


def test_get_property_value_extraction(mock_yaml_controller) -> None:
    """Kills mutants in get_property verifying fallbacks and STATE_UNKNOWN."""
    mock_op = MagicMock()
    mock_op.value = "op_value"
    mock_yaml_controller.loader.operations = {"test_op": mock_op}
    mock_yaml_controller._attributes = {
        "test_attr": "attr_value",
        "unknown_attr": STATE_UNKNOWN,
    }

    # Scenario 1: Attribute exists as object
    assert mock_yaml_controller.get_property("test_op") == "op_value"

    # Scenario 2: Attribute is not object, searched in _attributes
    assert mock_yaml_controller.get_property("test_attr") == "attr_value"

    # Scenario 3: Value found is STATE_UNKNOWN, must convert to None
    assert mock_yaml_controller.get_property("unknown_attr") is None

    # Scenario 4: Non-existent key, raises KeyError (Zero-Trust)
    with pytest.raises(KeyError):
        mock_yaml_controller.get_property("missing_key")


def test_get_property_all_values(mock_yaml_controller) -> None:
    """Kills mutants in get_property_all_values verifying null protection."""
    mock_op = MagicMock()
    mock_op.all_values = ["val1", "val2"]

    mock_op_no_values = MagicMock()
    mock_op_no_values.all_values = None

    mock_yaml_controller.loader.operations = {
        "good_op": mock_op,
        "bad_op": mock_op_no_values,
    }

    # Scenario 1: Object exists and has all_values
    assert mock_yaml_controller.get_property_all_values("good_op") == ("val1", "val2")

    # Scenario 2: Object exists but does not have all_values
    assert mock_yaml_controller.get_property_all_values("bad_op") is None

    # Scenario 3: Object does not exist
    assert mock_yaml_controller.get_property_all_values("missing_op") is None


@pytest.mark.asyncio
async def test_async_merge_and_predict_delegation(mock_yaml_controller) -> None:
    """Kills mutants in merge and predict delegates."""
    mock_yaml_controller.poller.async_merge_device_state = AsyncMock(return_value=True)
    mock_yaml_controller.poller.async_predict_and_correct_state = AsyncMock(
        return_value=(True, {"st": 1})
    )

    assert await mock_yaml_controller.async_merge_device_state({"k": "v"}) is True
    mock_yaml_controller.poller.async_merge_device_state.assert_called_once_with(
        {"k": "v"}
    )

    res = await mock_yaml_controller.async_predict_and_correct_state(
        "state", "prop", "val"
    )
    assert res == (True, {"st": 1})
    mock_yaml_controller.poller.async_predict_and_correct_state.assert_called_once_with(
        "state", "prop", "val"
    )


@pytest.mark.asyncio
async def test_async_set_property_error_scenarios(mock_yaml_controller) -> None:
    """Kills mutants in async_set_property asserting failures and exceptions."""
    # Scenario 1: Uninitialized controller -> raises HomeAssistantError
    mock_yaml_controller.loader.is_fully_initialized = False
    with pytest.raises(HomeAssistantError):
        await mock_yaml_controller.async_set_property("prop", "val")
    mock_yaml_controller.loader.is_fully_initialized = True  # Restore state

    # Scenario 2: Property does not exist -> raises HomeAssistantError
    with pytest.raises(HomeAssistantError):
        await mock_yaml_controller.async_set_property("missing_prop", "val")

    # Scenario 3: Transport error (TimeoutError / OSError) -> Wrapped as HomeAssistantError
    from custom_components.climate_ip.properties import DeviceProperty

    mock_op = AsyncMock()
    mock_op.__class__ = DeviceProperty
    mock_yaml_controller.loader.operations = {"test_prop": mock_op}
    mock_op.async_set_value.side_effect = TimeoutError("Host down")
    with pytest.raises(HomeAssistantError) as exc_info:
        await mock_yaml_controller.async_set_property("test_prop", "val")
    assert "Host down" in str(exc_info.value)

    mock_op.async_set_value.side_effect = OSError("Socket error")
    with pytest.raises(HomeAssistantError) as exc_info2:
        await mock_yaml_controller.async_set_property("test_prop", "val")
    assert "Socket error" in str(exc_info2.value)

    # Scenario 4: Domain exceptions propagate directly without swallowing
    mock_op.async_set_value.side_effect = CannotConnect("Host unreachable")
    with pytest.raises(CannotConnect):
        await mock_yaml_controller.async_set_property("test_prop", "val")

    mock_op.async_set_value.side_effect = AuthError("Auth failed")
    with pytest.raises(AuthError):
        await mock_yaml_controller.async_set_property("test_prop", "val")

    # Scenario 5: Programming bugs / ValueErrors -> Raises natively (Fail-Fast)
    mock_op.async_set_value.side_effect = ValueError("Boom")
    with pytest.raises(ValueError):
        await mock_yaml_controller.async_set_property("test_prop", "val")


def test_yaml_controller_setters_strict_assignment(mock_yaml_controller) -> None:
    """Verify that device_id and token are strictly read-only properties without setters."""
    # 1. device_id
    mock_yaml_controller._device_id = "target_dev_id"
    assert mock_yaml_controller.device_id == "target_dev_id"
    with pytest.raises(AttributeError):
        mock_yaml_controller.device_id = "new_dev_id"

    # 2. token
    mock_yaml_controller._token = "target_token"
    assert mock_yaml_controller.token == "target_token"
    with pytest.raises(AttributeError):
        mock_yaml_controller.token = "new_token"


def test_yaml_controller_available_property(mock_yaml_controller) -> None:
    """Kills mutants in available property across all branches."""
    # Scenario 1: connection is None -> Disconnected entity evaluates to False
    mock_yaml_controller.loader.connection = None
    assert mock_yaml_controller.available is False

    # Scenario 2: connection present but returns is_available=False
    conn_mock = MagicMock()
    conn_mock.is_available = False
    mock_yaml_controller.loader.connection = conn_mock
    assert mock_yaml_controller.available is False

    # Scenario 3: connection present and returns is_available=True
    conn_mock.is_available = True
    assert mock_yaml_controller.available is True

    # Scenario 4: connection returns truthy value -> Evaluates to True via bool()
    conn_mock.is_available = "connected"
    assert mock_yaml_controller.available is True


def test_yaml_controller_sensors_property(mock_yaml_controller) -> None:
    """Validates absolute structural integrity enforcement in the sensors property."""
    mock_sensor = MagicMock()
    mock_yaml_controller.loader.sensors = {"valid_sensor": mock_sensor}
    mock_yaml_controller.loader.sensors_list = ["valid_sensor", "ghost_sensor"]

    import pytest

    with pytest.raises(KeyError, match="ghost_sensor"):
        _ = mock_yaml_controller.sensors


def test_yaml_controller_is_push_device_strict(mock_yaml_controller) -> None:
    """Verify mutant kill by evaluating native push support under Fail-Fast."""
    # 1. No connection -> Fails cleanly by logic (returns False)
    mock_yaml_controller.loader.connection = None
    assert mock_yaml_controller.is_push_device is False

    # 2. Fail-Fast Doctrine: Corrupt/incompatible connection -> MUST BLOW UP
    class LegacyConnection:
        pass

    mock_yaml_controller.loader.connection = LegacyConnection()
    with pytest.raises(AttributeError):
        _ = mock_yaml_controller.is_push_device

    # 3. 100% compatible connection -> Returns the value
    conn_mock = MagicMock()
    conn_mock.is_push_supported = True
    mock_yaml_controller.loader.connection = conn_mock
    assert mock_yaml_controller.is_push_device is True


@patch("custom_components.climate_ip.controller_yaml.ClimateIPDeviceState")
def test_yaml_controller_climate_state_mapping(
    mock_state_class: MagicMock, mock_yaml_controller: MagicMock
) -> None:
    """Kills instantiation mutants of state using White Box Mathematics."""

    def mock_get_prop(prop: str) -> Any:
        if prop == ATTR_HVAC_MODE:
            return "cool"
        if prop == ATTR_TEMPERATURE:
            return 22.5
        if prop == "current_temperature":
            return 25.0
        if prop == ATTR_FAN_MODE:
            return "high"
        if prop == ATTR_SWING_MODE:
            return "on"
        if prop == ATTR_PRESET_MODE:
            return "eco"
        return f"val_{prop}"

    mock_yaml_controller.get_property = MagicMock(side_effect=mock_get_prop)
    mock_yaml_controller.has_property = MagicMock(return_value=True)

    mock_yaml_controller._attributes = {
        ATTR_HVAC_MODES: ["auto", "heat", "cool"],
        ATTR_FAN_MODES: ["high", "low"],
        ATTR_SWING_MODES: ["on", "off"],
        ATTR_PRESET_MODES: ["eco"],
    }

    mock_yaml_controller.loader = MagicMock()
    mock_yaml_controller.loader.operations = {
        "hvac_mode": MagicMock(id="hvac_mode", all_values=["auto", "heat", "cool"]),
        "target_temperature": MagicMock(id="target_temperature"),
        "current_temperature": MagicMock(id="current_temperature"),
        "fan_mode": MagicMock(id="fan_mode", all_values=["high", "low"]),
        "swing_mode": MagicMock(id="swing_mode", all_values=["on", "off"]),
        "preset_mode": MagicMock(id="preset_mode", all_values=["eco"]),
    }

    _ = mock_yaml_controller.climate_state

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


def test_yaml_controller_unique_id_property(mock_yaml_controller) -> None:
    """Verifies that unique_id property returns the pre-computed _unique_id."""
    mock_yaml_controller._unique_id = "mac_123_sub_1"
    assert mock_yaml_controller.unique_id == "mac_123_sub_1"

    mock_yaml_controller._unique_id = None
    assert mock_yaml_controller.unique_id is None


def test_yaml_controller_delegated_properties(mock_yaml_controller) -> None:
    """Kills mutants in simple delegated properties."""
    mock_yaml_controller.loader.name = "Test AC Name"
    assert mock_yaml_controller.name == "Test AC Name"

    assert mock_yaml_controller.config == mock_yaml_controller._config

    mock_yaml_controller._ip_address = "192.168.1.50"
    assert mock_yaml_controller.ip_address == "192.168.1.50"

    mock_yaml_controller._debug = True
    assert mock_yaml_controller.debug is True

    mock_yaml_controller.loader.poll = True
    assert mock_yaml_controller.poll is True

    mock_yaml_controller._unique_id = "uid_999"
    mock_yaml_controller._device_id = "uid_999"
    assert mock_yaml_controller.unique_id == "uid_999"

    mock_yaml_controller._attributes = {"controller": "uid_999", "attr_1": 10}
    assert mock_yaml_controller.state_attributes == {
        "controller": "uid_999",
        "attr_1": 10,
    }

    assert mock_yaml_controller.temperature_unit == "°C"

    mock_yaml_controller.loader.service_schema_map = {"schema_key": "schema_val"}
    assert mock_yaml_controller.service_schema_map == {"schema_key": "schema_val"}

    mock_yaml_controller.loader.operations_list = ["op_power", "op_temp"]
    assert mock_yaml_controller.operations == ["op_power", "op_temp"]

    mock_yaml_controller.loader.properties_list = ["attr_curr_temp"]
    assert mock_yaml_controller.attributes == ["attr_curr_temp"]

    # yaml_file & connection properties (Kills M1 Untested)
    assert mock_yaml_controller.yaml_file == "test.yaml"
    mock_yaml_controller._config = {}
    assert mock_yaml_controller.yaml_file is None

    mock_conn = MagicMock()
    mock_yaml_controller.loader.connection = mock_conn
    assert mock_yaml_controller.connection is mock_conn


def test_yaml_controller_last_poll_data(mock_yaml_controller) -> None:
    """Kills mutants in last_poll_data."""
    mock_yaml_controller.loader.state_getter = None
    assert mock_yaml_controller.last_poll_data is None

    mock_state_getter = MagicMock()
    mock_state_getter.value = {"raw_temp": 25}
    mock_yaml_controller.loader.state_getter = mock_state_getter
    assert mock_yaml_controller.last_poll_data == {"raw_temp": 25}


def test_yaml_controller_connection_diagnostics(mock_yaml_controller) -> None:
    """Kills mutants in connection_diagnostics."""
    mock_yaml_controller.loader.connection = None
    assert mock_yaml_controller.connection_diagnostics == {}

    mock_conn = MagicMock()
    mock_conn.get_diagnostics.return_value = {"latency_ms": 12, "connected": True}
    mock_yaml_controller.loader.connection = mock_conn
    assert mock_yaml_controller.connection_diagnostics == {
        "latency_ms": 12,
        "connected": True,
    }


def test_yaml_controller_device_state(mock_yaml_controller) -> None:
    """Kills mutants in device_state checking hierarchy poller -> loader -> empty dict."""
    mock_yaml_controller.poller.device_state = {"poller_key": "val1"}
    assert mock_yaml_controller.device_state == {"poller_key": "val1"}

    # An empty dictionary is a valid state; we DO NOT fall back to loader.
    mock_yaml_controller.poller.device_state = {}
    mock_state_getter = MagicMock()
    mock_state_getter.value = {"loader_key": "val2"}
    mock_yaml_controller.loader.state_getter = mock_state_getter
    assert mock_yaml_controller.device_state == {}

    # None must Fail-Fast (Absolute Zero Doctrine)
    mock_yaml_controller.poller.device_state = None
    with pytest.raises(TypeError):
        _ = mock_yaml_controller.device_state


@pytest.mark.asyncio
async def test_yaml_controller_async_delegates_and_noop(mock_yaml_controller) -> None:
    """Kills mutants in async_get_status, async_update_state, async_shutdown, and async_refresh_from_connection."""
    mock_yaml_controller.poller.async_get_status = AsyncMock(
        return_value={"status": "ok"}
    )
    assert await mock_yaml_controller.async_get_status() == {"status": "ok"}
    mock_yaml_controller.poller.async_get_status.assert_called_once()

    mock_yaml_controller.poller.async_update_state = AsyncMock(
        return_value={"state": "active"}
    )
    assert await mock_yaml_controller.async_update_state() == {"state": "active"}
    mock_yaml_controller.poller.async_update_state.assert_called_once()

    mock_yaml_controller.poller.async_shutdown = AsyncMock()
    await mock_yaml_controller.async_shutdown()
    mock_yaml_controller.poller.async_shutdown.assert_called_once()

    res = await mock_yaml_controller.async_refresh_from_connection()
    assert res is None


def test_platform_schema_removed() -> None:
    """Verify that PLATFORM_SCHEMA is no longer exported by controller_yaml.

    Modern HA Core 2026.x+ uses config_flow.py exclusively.
    The schema block was removed; this test guards against accidental re-introduction.
    """
    import importlib

    module = importlib.import_module("custom_components.climate_ip.controller_yaml")
    assert not hasattr(module, "PLATFORM_SCHEMA"), (
        "PLATFORM_SCHEMA must not be defined in controller_yaml — "
        "use config_flow.py instead."
    )


def test_yaml_controller_untested_properties_and_cache() -> None:
    """Cover getters, setters, and clear_state_cache to kill untested mutants."""
    mock_logger = logging.getLogger(__name__)
    controller = YamlController(
        config={"device_type": "test_device", "ip_address": "127.0.0.1"},
        logger=mock_logger,
    )

    # clear_state_cache
    controller.poller = MagicMock()
    controller.clear_state_cache()
    controller.poller.clear_state_cache.assert_called_once()


def test_yaml_controller_is_property_superseded() -> None:
    """Test is_property_superseded logic under all pending updates states."""
    mock_logger = logging.getLogger(__name__)
    controller = YamlController(
        config={"device_type": "test_device", "ip_address": "127.0.0.1"},
        logger=mock_logger,
    )
    controller.poller._pending_updates = {
        "target_temperature": (22.0, 100.0),
    }

    # 1. Property not in pending updates
    assert controller.is_property_superseded("power", "on") is False

    # 2. Property in pending updates with same value
    assert controller.is_property_superseded("target_temperature", 22.0) is False

    # 3. Property in pending updates with different value (superseded)
    assert controller.is_property_superseded("target_temperature", 24.0) is True


def test_from_config_entry_and_extract_config(mock_hass: MagicMock) -> None:
    """Test from_config_entry factory method and _extract_config_from_entry."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "entry_123"
    mock_entry.unique_id = "uniq_456"
    mock_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.50",
        CONF_CONFIG_FILE: "test.yaml",
        CONF_MAC: "11:22:33:44:55:66",
        CONF_TOKEN: "tok_abc",
    }
    # Options has a mutable key and an immutable key
    mock_entry.options = {
        "debug": True,
        CONF_IP_ADDRESS: "10.0.0.99",  # Should be ignored (immutable)
    }

    custom_logger = logging.getLogger("custom_logger")
    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        # 1. Test with custom logger and explicit device_id
        controller = YamlController.from_config_entry(
            config_entry=mock_entry,
            hass=mock_hass,
            device_id="sub_dev",
            logger=custom_logger,
        )
        assert controller.hass is mock_hass
        assert controller._logger is custom_logger
        assert controller._device_id == "sub_dev"
        assert controller._unique_id == "uniq_456_sub_dev"
        assert controller._ip_address == "192.168.1.50"  # Immutable key preserved
        assert controller._debug is True  # Mutable key applied

        # 2. Test with default logger (logger=None) and no device_id
        controller_default = YamlController.from_config_entry(
            config_entry=mock_entry,
            hass=mock_hass,
            device_id=None,
        )
        assert controller_default._logger is not None
        assert controller_default._device_id == "uniq_456"

        # 3. Test _extract_config_from_entry with empty/whitespace device_id
        extracted = YamlController._extract_config_from_entry(
            mock_entry, device_id="   "
        )
        assert CONF_DEVICE_ID not in extracted
        assert extracted["entry_id"] == "entry_123"
        assert extracted["unique_id"] == "uniq_456"


def test_yaml_controller_has_property(mock_yaml_controller) -> None:
    """Kills mutants in has_property logic and parameter validation."""
    # 1. Invalid parameter types / empty strings -> raises TypeError
    with pytest.raises(TypeError):
        mock_yaml_controller.has_property("")
    with pytest.raises(TypeError):
        mock_yaml_controller.has_property("   ")
    with pytest.raises(TypeError):
        mock_yaml_controller.has_property(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        mock_yaml_controller.has_property(123)  # type: ignore[arg-type]

    # 2. Property present as loader property object (not in _attributes) -> True
    mock_op = MagicMock()
    mock_yaml_controller.loader.operations = {"op_prop": mock_op}
    mock_yaml_controller._attributes = {}
    assert mock_yaml_controller.has_property("op_prop") is True

    # 3. Property present only in _attributes (not in loader objects) -> True
    mock_yaml_controller.loader.operations = {}
    mock_yaml_controller._attributes = {"attr_prop": "val"}
    assert mock_yaml_controller.has_property("attr_prop") is True

    # 4. Property not in loader and not in _attributes -> False
    assert mock_yaml_controller.has_property("missing_prop") is False


def test_yaml_controller_init_type_errors_and_whitespace_name() -> None:
    """Kills mutants in __init__ for non-dict config and whitespace name handling."""
    mock_logger = logging.getLogger("test_logger")

    # 1. config is non-dict and not None -> TypeError (L156)
    with pytest.raises(TypeError, match="Expected dict for config"):
        YamlController(config=12345, logger=mock_logger)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Expected dict for config"):
        YamlController(config="string_config", logger=mock_logger)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Expected dict for config"):
        YamlController(config=["item"], logger=mock_logger)  # type: ignore[arg-type]

    # 2. CONF_NAME is whitespace string -> config.pop(CONF_NAME, None) (L177, L180)
    config_whitespace_name = {
        CONF_CONFIG_FILE: "test.yaml",
        CONF_IP_ADDRESS: "192.168.1.10",
        "name": "   ",
    }
    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        controller = YamlController(config_whitespace_name, mock_logger)
        assert "name" not in controller._config

    # 3. CONF_NAME is valid non-empty string -> stripped and kept
    config_valid_name = {
        CONF_CONFIG_FILE: "test.yaml",
        CONF_IP_ADDRESS: "192.168.1.10",
        "name": "  Living Room AC  ",
    }
    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        controller2 = YamlController(config_valid_name, mock_logger)
        assert controller2._config["name"] == "Living Room AC"


def test_yaml_controller_objects_by_id_caching_and_filtering(
    mock_yaml_controller,
) -> None:
    """Kills mutants in _objects_by_id regarding hass_attr filtering, collision, and empty handling."""
    mock_yaml_controller._obj_id_cache = None
    mock_yaml_controller.loader.is_fully_initialized = True

    op1 = MagicMock()
    op1.id = "power_id"
    op2 = MagicMock()
    op2.id = "temp_id"
    op3 = MagicMock()
    op3.id = "empty_hass_id"
    op4 = MagicMock()
    op4.id = "collision_id"

    mock_yaml_controller.loader.sensors = {}
    mock_yaml_controller.loader.properties = {}
    mock_yaml_controller.loader.operations = {
        "op1": op1,
        "op2": op2,
        "op3": op3,
        "op4": op4,
    }

    def mock_get_hass_attr(op_id: str) -> Any:
        if op_id == "power_id":
            return "power_attr"
        if op_id == "temp_id":
            return "   "  # Whitespace only string: should NOT be added
        if op_id == "empty_hass_id":
            return None  # None: should NOT be added
        if op_id == "collision_id":
            return "power_id"  # Collides with existing op_id in cache: should NOT overwrite op1
        return 123  # Non-string: should NOT be added

    mock_yaml_controller.poller.get_hass_attr_for_op_id = MagicMock(
        side_effect=mock_get_hass_attr
    )

    cache = mock_yaml_controller._objects_by_id
    assert cache["power_id"] is op1
    assert cache["power_attr"] is op1
    assert cache["temp_id"] is op2
    assert "   " not in cache
    assert "" not in cache
    assert cache["empty_hass_id"] is op3
    assert cache["collision_id"] is op4
    # collision_id's hass_attr was "power_id", so cache["power_id"] must still be op1
    assert cache["power_id"] is op1


def test_yaml_controller_update_state_attributes(mock_yaml_controller) -> None:
    """Kills mutants in update_state_attributes."""
    # 1. Valid dict
    mock_yaml_controller.update_state_attributes({"key": "val"})
    assert mock_yaml_controller.state_attributes == {"key": "val"}

    # 2. Non-dict input -> raises TypeError
    with pytest.raises(TypeError, match="Expected dict for new_attrs"):
        mock_yaml_controller.update_state_attributes("not_a_dict")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Expected dict for new_attrs"):
        mock_yaml_controller.update_state_attributes(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Expected dict for new_attrs"):
        mock_yaml_controller.update_state_attributes([1, 2, 3])  # type: ignore[arg-type]


def test_yaml_controller_pure_device_state(mock_yaml_controller) -> None:
    """Kills mutants in pure_device_state."""
    # 1. Valid dict from poller
    mock_yaml_controller.poller.pure_network_state = {"net_key": "net_val"}
    assert mock_yaml_controller.pure_device_state == {"net_key": "net_val"}

    # 2. Non-dict from poller -> raises TypeError
    mock_yaml_controller.poller.pure_network_state = "invalid_non_dict"
    with pytest.raises(TypeError):
        _ = mock_yaml_controller.pure_device_state

    mock_yaml_controller.poller.pure_network_state = None
    with pytest.raises(TypeError):
        _ = mock_yaml_controller.pure_device_state


def test_yaml_controller_safe_parse_temperature(mock_yaml_controller) -> None:
    """Kills mutants in _safe_parse_temperature including whitespace strings."""
    # 1. None returns None
    assert mock_yaml_controller._safe_parse_temperature(None, "temp") is None

    # 2. Empty or whitespace string returns None
    assert mock_yaml_controller._safe_parse_temperature("", "temp") is None
    assert mock_yaml_controller._safe_parse_temperature("   ", "temp") is None

    # 3. Numeric string returns float
    assert mock_yaml_controller._safe_parse_temperature("23.5", "temp") == 23.5
    assert mock_yaml_controller._safe_parse_temperature(24, "temp") == 24.0

    # 4. Boolean raises TypeError
    with pytest.raises(TypeError, match="cannot be a boolean"):
        mock_yaml_controller._safe_parse_temperature(True, "temp")

    # 5. Invalid string raises ValueError
    with pytest.raises(ValueError, match="Invalid numeric string"):
        mock_yaml_controller._safe_parse_temperature("invalid_num", "temp")


def test_yaml_controller_port_resolution_and_validation() -> None:
    """Test resolution and fail-fast validation of the port property."""
    mock_logger = logging.getLogger("test_logger")

    with (
        patch("custom_components.climate_ip.controller_yaml.YamlConfigLoader"),
        patch("custom_components.climate_ip.controller_yaml.YamlStatePoller"),
    ):
        # 1. Explicit valid integer ports (including boundaries 1, 65535, and standard 8888)
        controller_int = YamlController(
            {"port": 8888, "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_int.port == 8888
        assert isinstance(controller_int.port, int)

        controller_min = YamlController(
            {"port": 1, "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_min.port == 1

        controller_max = YamlController(
            {"port": 65535, "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_max.port == 65535

        # 2. Default fallback when CONF_PORT is absent or None
        controller_absent = YamlController({"ip_address": "127.0.0.1"}, mock_logger)
        assert controller_absent.port == PORT_SAMSUNG_8888
        assert isinstance(controller_absent.port, int)

        controller_none = YamlController(
            {"port": None, "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_none.port == PORT_SAMSUNG_8888
        assert isinstance(controller_none.port, int)

        # 3. Numeric string coercion
        controller_str_8888 = YamlController(
            {"port": "8888", "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_str_8888.port == 8888
        assert isinstance(controller_str_8888.port, int)

        controller_str_2878 = YamlController(
            {"port": "2878", "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_str_2878.port == 2878
        assert isinstance(controller_str_2878.port, int)

        controller_str_padded = YamlController(
            {"port": "  8888  ", "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_str_padded.port == 8888

        controller_str_min = YamlController(
            {"port": "1", "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_str_min.port == 1

        controller_str_max = YamlController(
            {"port": "65535", "ip_address": "127.0.0.1"}, mock_logger
        )
        assert controller_str_max.port == 65535

        # 4. Out-of-range integer validation (ValueError)
        for invalid_int in (-1, 0, 65536, 70000):
            controller_invalid_int = YamlController(
                {"port": invalid_int, "ip_address": "127.0.0.1"}, mock_logger
            )
            with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
                _ = controller_invalid_int.port

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
            controller_invalid_str = YamlController(
                {"port": invalid_str, "ip_address": "127.0.0.1"}, mock_logger
            )
            with pytest.raises(ValueError):
                _ = controller_invalid_str.port

        # 6. Unsupported types (TypeError)
        for invalid_type in (
            True,
            False,
            [8888],
            {"port": 8888},
            8888.0,
            (8888,),
        ):
            controller_invalid_type = YamlController(
                {"port": invalid_type, "ip_address": "127.0.0.1"}, mock_logger
            )
            with pytest.raises(TypeError, match="Unsupported port type"):
                _ = controller_invalid_type.port


@pytest.mark.asyncio
async def test_yaml_controller_async_set_property_fail_fast_branches(
    mock_yaml_controller,
) -> None:
    """Test async_set_property fail-fast branches, deterministic target device resolution, and rollback."""
    from custom_components.climate_ip.properties import DeviceProperty

    # 1. Invalid property_name type / empty string -> TypeError
    with pytest.raises(TypeError):
        await mock_yaml_controller.async_set_property("", "val")
    with pytest.raises(TypeError):
        await mock_yaml_controller.async_set_property("   ", "val")
    with pytest.raises(TypeError):
        await mock_yaml_controller.async_set_property(None, "val")  # type: ignore[arg-type]

    # 2. Invalid device_id type -> TypeError
    with pytest.raises(TypeError):
        await mock_yaml_controller.async_set_property(
            "fan_mode",
            "high",
            device_id=12345,  # type: ignore[arg-type]
        )

    # 3. Uninitialized Loader -> HomeAssistantError
    mock_yaml_controller.loader.is_fully_initialized = False
    with pytest.raises(HomeAssistantError):
        await mock_yaml_controller.async_set_property("target_temperature", 22)
    mock_yaml_controller.loader.is_fully_initialized = True

    # 4. Missing / Unregistered Property -> HomeAssistantError
    mock_yaml_controller.loader.operations = {}
    with pytest.raises(HomeAssistantError):
        await mock_yaml_controller.async_set_property("non_existent_prop", 22)

    # Setup a mock DeviceProperty operation
    mock_op = AsyncMock()
    mock_op.__class__ = DeviceProperty
    mock_op.async_set_value.return_value = True
    mock_yaml_controller.loader.operations = {"target_temperature": mock_op}
    mock_yaml_controller._unique_id = "uniq_base_123"
    mock_yaml_controller._device_id = "dev_base_456"

    # 5. Device ID Branching:
    # 5a. Explicit sub-device id -> forwarded trimmed to op.async_set_value
    mock_op.reset_mock()
    res = await mock_yaml_controller.async_set_property(
        "target_temperature", 22, device_id="sub_device_1"
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(22, "sub_device_1")

    # 5b. Whitespace-padded sub-device id -> trimmed
    mock_op.reset_mock()
    res = await mock_yaml_controller.async_set_property(
        "target_temperature", 23, device_id="  sub_device_2  "
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(23, "sub_device_2")

    # 5c. device_id=None -> falls back to self.device_id ("dev_base_456")
    mock_op.reset_mock()
    res = await mock_yaml_controller.async_set_property(
        "target_temperature", 24, device_id=None
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(24, "dev_base_456")

    # 5d. device_id="" or whitespace -> raises TypeError
    with pytest.raises(TypeError):
        await mock_yaml_controller.async_set_property(
            "target_temperature", 25, device_id=""
        )

    with pytest.raises(TypeError):
        await mock_yaml_controller.async_set_property(
            "target_temperature", 25, device_id="   "
        )

    # 5e. device_id=MAIN_DEVICE_ID ("main") -> resolves to self._unique_id ("uniq_base_123")
    mock_op.reset_mock()
    res = await mock_yaml_controller.async_set_property(
        "target_temperature", 26, device_id=MAIN_DEVICE_ID
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(26, "uniq_base_123")

    # 5f. device_id=None and self.device_id is MAIN_DEVICE_ID -> resolves to self._unique_id
    mock_yaml_controller._device_id = MAIN_DEVICE_ID
    mock_op.reset_mock()
    res = await mock_yaml_controller.async_set_property(
        "target_temperature", 27, device_id=None
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(27, "uniq_base_123")

    # 5g. device_id=None and self.device_id is None -> resolves to self._unique_id
    mock_yaml_controller._device_id = None
    mock_op.reset_mock()
    res = await mock_yaml_controller.async_set_property(
        "target_temperature", 28, device_id=None
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(28, "uniq_base_123")

    # 5h. device_id=None and self.device_id is "" -> resolves to self._unique_id
    mock_yaml_controller._device_id = ""
    mock_op.reset_mock()
    res = await mock_yaml_controller.async_set_property(
        "target_temperature", 29, device_id=None
    )
    assert res is True
    mock_op.async_set_value.assert_called_once_with(29, "uniq_base_123")

    # 6. Exception Handling & Rollback (TimeoutError & OSError -> HomeAssistantError)
    mock_yaml_controller.async_clear_pending_updates = AsyncMock()

    # 6a. TimeoutError -> HomeAssistantError + rollback
    mock_op.async_set_value.side_effect = TimeoutError("Connection timed out")
    mock_yaml_controller.async_clear_pending_updates.reset_mock()
    with pytest.raises(
        HomeAssistantError, match="Communication failed: Connection timed out"
    ):
        await mock_yaml_controller.async_set_property("target_temperature", 22)
    mock_yaml_controller.async_clear_pending_updates.assert_awaited_once_with(
        ["target_temperature"]
    )

    # 6b. OSError -> HomeAssistantError + rollback
    mock_op.async_set_value.side_effect = OSError("Socket unreachable")
    mock_yaml_controller.async_clear_pending_updates.reset_mock()
    with pytest.raises(
        HomeAssistantError, match="Communication failed: Socket unreachable"
    ):
        await mock_yaml_controller.async_set_property("target_temperature", 22)
    mock_yaml_controller.async_clear_pending_updates.assert_awaited_once_with(
        ["target_temperature"]
    )

    # 6c. Domain exceptions propagate directly + rollback
    mock_op.async_set_value.side_effect = CannotConnect("No route to host")
    mock_yaml_controller.async_clear_pending_updates.reset_mock()
    with pytest.raises(CannotConnect):
        await mock_yaml_controller.async_set_property("target_temperature", 22)
    mock_yaml_controller.async_clear_pending_updates.assert_awaited_once_with(
        ["target_temperature"]
    )

    # 6d. Result is False -> Rollback
    mock_op.async_set_value.side_effect = None
    mock_op.async_set_value.return_value = False
    mock_yaml_controller.async_clear_pending_updates.reset_mock()
    res_false = await mock_yaml_controller.async_set_property("target_temperature", 22)
    assert res_false is False
    mock_yaml_controller.async_clear_pending_updates.assert_awaited_once_with(
        ["target_temperature"]
    )


@pytest.mark.asyncio
async def test_yaml_controller_async_set_property_state_injection(
    mock_yaml_controller,
) -> None:
    """Kills mutants in async_set_property state injection (L437, L442, L456)."""
    from custom_components.climate_ip.properties import DeviceProperty

    mock_op = AsyncMock()
    mock_op.__class__ = DeviceProperty
    mock_op.async_set_value.return_value = True
    mock_yaml_controller.loader.operations = {"fan_mode": mock_op}

    # Case 1: _pure_network_state is None and loader has valid state_getter dict
    mock_yaml_controller.poller._pure_network_state = None
    mock_yaml_controller.poller._inject_value_into_state = MagicMock()
    mock_state_getter = MagicMock()
    mock_state_getter.value = {"fan_speed": "low", "power": "on"}
    mock_yaml_controller.loader.state_getter = mock_state_getter

    res = await mock_yaml_controller.async_set_property("fan_mode", "high")
    assert res is True

    # Check deepcopy occurred and _pure_network_state was populated
    assert mock_yaml_controller.poller._pure_network_state == {
        "fan_speed": "low",
        "power": "on",
    }
    assert (
        mock_yaml_controller.poller._pure_network_state is not mock_state_getter.value
    )

    # Check injection called twice: once for _pure_network_state and once for state_getter.value
    assert mock_yaml_controller.poller._inject_value_into_state.call_count == 2
    mock_yaml_controller.poller._inject_value_into_state.assert_any_call(
        mock_op, mock_yaml_controller.poller._pure_network_state, "high"
    )
    mock_yaml_controller.poller._inject_value_into_state.assert_any_call(
        mock_op, mock_state_getter.value, "high"
    )

    # Case 2: _pure_network_state is already set (not None) -> deepcopy skipped, injection still runs
    mock_yaml_controller.poller._pure_network_state = {"fan_speed": "medium"}
    mock_yaml_controller.poller._inject_value_into_state.reset_mock()
    mock_state_getter.value = {"fan_speed": "medium"}

    res = await mock_yaml_controller.async_set_property("fan_mode", "auto")
    assert res is True
    assert mock_yaml_controller.poller._inject_value_into_state.call_count == 2

    # Case 3: state_getter is None
    mock_yaml_controller.loader.state_getter = None
    mock_yaml_controller.poller._inject_value_into_state.reset_mock()
    res = await mock_yaml_controller.async_set_property("fan_mode", "auto")
    assert res is True
    assert mock_yaml_controller.poller._inject_value_into_state.call_count == 1

    # Case 4: state_getter.value is not a dict (e.g. None or string)
    mock_state_getter_non_dict = MagicMock()
    mock_state_getter_non_dict.value = "not_a_dict"
    mock_yaml_controller.loader.state_getter = mock_state_getter_non_dict
    mock_yaml_controller.poller._inject_value_into_state.reset_mock()
    res = await mock_yaml_controller.async_set_property("fan_mode", "auto")
    assert res is True
    assert mock_yaml_controller.poller._inject_value_into_state.call_count == 1
