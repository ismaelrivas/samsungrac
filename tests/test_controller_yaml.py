# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for YamlController — Phase 2 (executor I/O) and Phase 3 (hass injection) compliance."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import (
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
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
    DOMAIN,
)
from custom_components.climate_ip.controller_yaml import YamlController
from custom_components.climate_ip.controller_yaml_config import _YAML_FILE_CACHE
from custom_components.climate_ip.exceptions import CannotConnect


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
        config={"device_type": "test_device", "ip_address": "127.0.0.1"}, logger=MagicMock()
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
    controller = YamlController(
        yaml_config, mock_logger, hass=mock_hass, session=MagicMock()
    )

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
        controller = YamlController(
            config_input, mock_logger, mock_hass, mock_session
        )

    # 1. Verify delegate injections
    assert controller.hass is mock_hass
    assert controller._session is mock_session
    assert controller._logger is mock_logger

    # 2. Strict IP Address extraction
    assert controller._ip_address == "192.168.1.100"

    # 3. Strict identifier and Token extraction
    assert controller._token == "secret_token"
    assert controller._device_id == "dev_123"
    assert controller._unique_id == "test_mac_uid_dev_123"

    # 4. Callback initialization strictly as callable no-ops
    assert controller.discovered_devices is None
    assert callable(
        controller.on_token_refreshed
    ), "Must implement the no-op from the class"
    assert callable(
        controller.get_current_state_callback
    ), "Must implement the no-op from the class"

    assert callable(
        controller.on_push_update_callback
    ), "Must inherit the no-op from the base class"
    assert callable(
        controller.on_offline_callback
    ), "Must inherit the no-op from the base class"
    assert callable(
        controller.request_refresh_callback
    ), "Must inherit the no-op from the base class"
    assert callable(
        controller.on_ssl_config_updated
    ), "Must inherit the no-op from the base class"
    assert callable(
        controller.on_connection_failed_callback
    ), "Must inherit the no-op from the base class"

    # 5. Debug flag assignment
    assert controller._debug is True, "The mutant altered debug flag extraction"

    # 6. Base attributes dictionary assignment
    assert controller._attributes == {}
    assert controller._shared_raw_client is None

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
    assert (
        controller._device_id == "00:11:22"
    ), "Generic device_id fallback to unique_id failed"
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

    assert (
        controller._device_id == "fallback_mac_only"
    ), "The fallback branch did not assign unique_id to device_id"

    assert controller._debug is False, "The debug fallback is not False"


@pytest.fixture
def mock_yaml_controller():
    """Fixture to provide an initialized YamlController with mocked delegates."""
    mock_logger = logging.getLogger("test_logger")
    config_input = {CONF_CONFIG_FILE: "test.yaml", CONF_MAC: "mac123", "ip_address": "127.0.0.1"}

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
    assert mock_yaml_controller.get_property_all_values("good_op") == ["val1", "val2"]

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
    # Scenario 1: Uninitialized controller -> raises ServiceValidationError
    mock_yaml_controller.loader.is_fully_initialized = False
    with pytest.raises(ServiceValidationError):
        await mock_yaml_controller.async_set_property("prop", "val")
    mock_yaml_controller.loader.is_fully_initialized = True  # Restore state

    # Scenario 2: Property does not exist -> raises ServiceValidationError
    with pytest.raises(ServiceValidationError):
        await mock_yaml_controller.async_set_property("missing_prop", "val")

    # Scenario 3: Network error -> Raises CannotConnect with strict message
    from custom_components.climate_ip.properties import DeviceProperty

    mock_op = AsyncMock()
    mock_op.__class__ = DeviceProperty
    mock_yaml_controller.loader.operations = {"test_prop": mock_op}
    mock_op.async_set_value.side_effect = CannotConnect("Host down")
    with pytest.raises(CannotConnect) as exc_info:
        await mock_yaml_controller.async_set_property("test_prop", "val")
    assert "Host down" in str(exc_info.value)

    # Scenario 4: Network/OS exceptions -> Raises HomeAssistantError
    mock_op.async_set_value.side_effect = TimeoutError("Timeout")
    with pytest.raises(HomeAssistantError):
        await mock_yaml_controller.async_set_property("test_prop", "val")

    # Scenario 5: Programming bugs / ValueErrors -> Raises natively (Fail-Fast)
    mock_op.async_set_value.side_effect = ValueError("Boom")
    with pytest.raises(ValueError):
        await mock_yaml_controller.async_set_property("test_prop", "val")


def test_yaml_controller_setters_strict_assignment(mock_yaml_controller) -> None:
    """Verify property setters assignment."""
    # 1. device_id
    mock_yaml_controller.device_id = "target_dev_id"
    assert mock_yaml_controller._device_id == "target_dev_id"

    # 2. token
    mock_yaml_controller.token = "target_token"
    assert mock_yaml_controller._token == "target_token"


def test_yaml_controller_available_property(mock_yaml_controller) -> None:
    """Kills mutants in available property across all 3 branches."""
    # Scenario 1: connection is None -> Disconnected entity evaluates to False
    mock_yaml_controller.loader.connection = None
    assert mock_yaml_controller.available is False

    # Scenario 2: connection present but returns is_available=False
    conn_mock = MagicMock()
    conn_mock.get_diagnostics.return_value = {"is_available": False}
    mock_yaml_controller.loader.connection = conn_mock
    assert mock_yaml_controller.available is False

    # Scenario 3: connection present but diagnostic dict lacks key (Fail-Fast KeyError)
    conn_mock.get_diagnostics.return_value = {"other_key": "data"}
    with pytest.raises(KeyError):
        _ = mock_yaml_controller.available


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
    assert mock_yaml_controller.id == "uid_999"

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
        config={"device_type": "test_device", "ip_address": "127.0.0.1"}, logger=mock_logger
    )

    # 1. shared_raw_client setter
    controller.shared_raw_client = "mock_client"
    assert controller._shared_raw_client == "mock_client"


    # 3. clear_state_cache
    controller.poller = MagicMock()
    controller.clear_state_cache()
    controller.poller.clear_state_cache.assert_called_once()