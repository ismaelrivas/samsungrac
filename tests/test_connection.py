# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,abstract-method,missing-function-docstring,missing-class-docstring,too-few-public-methods,use-implicit-booleaness-not-comparison
"""Tests for base Connection class and registry in connection.py."""

import asyncio
import dataclasses
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from jinja2 import Template
import pytest

from custom_components.climate_ip.connection import (
    _HOST_LOCKS,
    CLIMATE_IP_CONNECTIONS,
    Connection,
    register_connection,
)
from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.connection_intesisbox import ConnectionIntesisBox
from custom_components.climate_ip.connection_raw import ConnectionRaw8888
from custom_components.climate_ip.exceptions import CannotConnect, RetryNextAttempt
from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878

_LOGGER = logging.getLogger("test_connection")

# Precompiled Jinja templates for fast execution during mutation sweeps
_TMPL_ONE = Template("1")
_TMPL_KEY_VAL = Template("{{ 1 if device_state.key == 'val' else 0 }}")
_TMPL_PURE_KEY = Template("{{ 1 if device_state.pure_key == 'active' else 0 }}")
_TMPL_CTRL_STATE_88 = Template(
    "{{ 1 if device_state.ctrl_state_fallback == 88 else 0 }}"
)
_TMPL_EMPTY_DICT = Template("{{ 1 if device_state == {} else 0 }}")
_TMPL_CTRL_STATE_123 = Template("{{ 1 if device_state.ctrl_state == 123 else 0 }}")
_TMPL_STATUS_999 = Template("{{ 1 if device_state.status_from_prop == 999 else 0 }}")
_TMPL_STATUS_RUNNING = Template(
    "{{ 1 if device_state.status_flag == 'running' else 0 }}"
)
_TMPL_ORIGINAL = Template("{{ 1 if device_state.original == 'keep_me' else 0 }}")
_TMPL_TARGET_TEMP_24 = Template("{{ 1 if device_state.target_temp == 24 else 0 }}")
_TMPL_DEVICES_EMPTY = Template(
    "{{ 1 if 'Devices' in device_state and device_state.Devices == [] else 0 }}"
)
_TMPL_DEVICES_NOT_LIST = Template(
    "{{ 1 if device_state.Devices == 'not_a_list' else 0 }}"
)
_TMPL_XXDEVICES = Template(
    "{{ 1 if 'XXDevicesXX' in device_state and device_state.XXDevicesXX == [{'target_temp': 24}] else 0 }}"
)
_TMPL_DATACLASS_DEEP = Template(
    "{{ 1 if device_state.mode == 'cool' and device_state.speed == 3 and device_state.nested is mapping and device_state.nested.val == 42 else 0 }}"
)
_TMPL_OBJECT_STATE = Template("{{ 1 if device_state.mode == 'heat' else 0 }}")
_TMPL_DICT_MODE = Template("{{ 1 if device_state.dict_mode == 'dry' else 0 }}")


class DummyConnection(Connection):
    """Subclass for testing base Connection functionality."""

    @classmethod
    def match_type(cls, conn_type: str) -> bool:
        return conn_type == "dummy"

    @property
    def is_push_supported(self) -> bool:
        return False


def test_register_connection():
    """Test register_connection decorator adds class to CLIMATE_IP_CONNECTIONS."""
    initial_len = len(CLIMATE_IP_CONNECTIONS)

    @register_connection
    class TestConn(Connection):
        @classmethod
        def match_type(cls, conn_type: str) -> bool:
            return conn_type == "test"

        @property
        def is_push_supported(self) -> bool:
            return False

    try:
        assert len(CLIMATE_IP_CONNECTIONS) == initial_len + 1
        assert TestConn in CLIMATE_IP_CONNECTIONS
    finally:
        if TestConn in CLIMATE_IP_CONNECTIONS:
            CLIMATE_IP_CONNECTIONS.remove(TestConn)


def test_connection_init_properties():
    """Test Connection initialization, properties, templates, controller ref and abstract methods."""
    config = {"host": "192.168.1.10", "port": 8888}
    hass = MagicMock()
    mock_session = MagicMock()

    conn = DummyConnection(
        config, _LOGGER, hass, session=mock_session, ip_address="192.168.1.55"
    )

    assert conn.config == config
    assert conn.logger == _LOGGER
    assert conn._hass == hass
    assert conn._session == mock_session
    assert conn._ip_address == "192.168.1.55"
    assert conn._params == {}
    assert conn.is_async_native is False
    assert conn.is_push_supported is False
    assert conn.log_prefix == ""

    # Templates & controller ref
    mock_tmpl1 = MagicMock()
    mock_tmpl2 = MagicMock()
    conn.condition_template = mock_tmpl1
    assert conn.condition_template is mock_tmpl1
    conn.connection_template = mock_tmpl2
    assert conn.connection_template is mock_tmpl2
    mock_ctrl = MagicMock()
    conn.set_controller_ref(mock_ctrl)
    assert conn._controller is mock_ctrl

    # Base connection abstract methods & properties
    base_conn = Connection(config, _LOGGER)
    assert base_conn.is_available is True
    assert base_conn._ip_address is None
    with pytest.raises(NotImplementedError):
        _ = base_conn.is_push_supported

    with pytest.raises(NotImplementedError):
        base_conn.execute(None, None, None)

    # In base Connection, async_execute raises NotImplementedError
    coro = base_conn.async_execute("GET", "/", None, None)
    with pytest.raises(NotImplementedError):
        coro.send(None)


def test_connection_is_available():
    """Test Connection.is_available property returns True."""
    conn = DummyConnection({}, _LOGGER)
    assert conn.is_available is True
    assert conn.is_available is not False
    base_conn = Connection({}, _LOGGER)
    assert base_conn.is_available is True
    assert base_conn.is_available is not False


def test_load_from_yaml_and_diagnostics():
    """Test base load_from_yaml, get_diagnostics, execute_legacy and create_updated."""
    conn = DummyConnection({"test": "cfg"}, _LOGGER)

    assert conn.load_from_yaml({"key": "val"}, None) is False
    assert conn.execute_legacy(None, None, None) is None
    assert conn.create_updated({"key": "val"}) is conn

    diag = conn.get_diagnostics()
    assert diag == {
        "type": "DummyConnection",
        "status": "not_implemented_in_base_class",
    }


def test_async_lock_resolution():
    """Test async_lock property host/port lock resolution, caching, and fallback."""
    _HOST_LOCKS.clear()

    # 1. No host in params or config -> returns instance fallback lock
    conn_no_host = DummyConnection({"port": 8888}, _LOGGER)
    assert conn_no_host.async_lock is conn_no_host._lock

    # 2. Host in config, port default fallback
    conn_config_host = DummyConnection({"host": "10.0.0.1"}, _LOGGER)
    lock1 = conn_config_host.async_lock
    assert isinstance(lock1, asyncio.Lock)
    assert ("10.0.0.1", "default") in _HOST_LOCKS

    # 3. Host and port in params override config
    conn_params = DummyConnection({"host": "10.0.0.1", "port": 80}, _LOGGER)
    conn_params._params = {"host": "192.168.1.50", "port": 8080}
    lock2 = conn_params.async_lock
    assert ("192.168.1.50", "8080") in _HOST_LOCKS

    # 4. Same host and port returns exact same shared Lock instance
    conn_params2 = DummyConnection({}, _LOGGER)
    conn_params2._params = {"host": "192.168.1.50", "port": 8080}
    assert conn_params2.async_lock is lock2

    # 5. Host in config, port in config (no params) -> resolves config port
    conn_config_port = DummyConnection({"host": "10.0.0.2", "port": 9999}, _LOGGER)
    lock3 = conn_config_port.async_lock
    assert isinstance(lock3, asyncio.Lock)
    assert ("10.0.0.2", "9999") in _HOST_LOCKS


@pytest.mark.asyncio
async def test_async_execute_with_retry_success():
    """Test async_execute_with_retry succeeds via hass, controller.hass, and to_thread fallback."""
    # Case 1: Direct self._hass provided
    mock_hass = MagicMock()
    conn_hass = DummyConnection({"host": "127.0.0.1"}, _LOGGER, hass=mock_hass)
    conn_hass.execute = MagicMock(return_value={"status": "ok_hass"})

    async def _mock_add_job(fn, *args):
        return fn(*args)

    mock_hass.async_add_executor_job = AsyncMock(side_effect=_mock_add_job)

    res1 = await conn_hass.async_execute_with_retry(
        "template", "val", {"state": 1}, "dev1"
    )
    assert res1 == {"status": "ok_hass"}
    conn_hass.execute.assert_called_once_with("template", "val", {"state": 1}, "dev1")
    mock_hass.async_add_executor_job.assert_awaited_once_with(
        conn_hass.execute, "template", "val", {"state": 1}, "dev1"
    )

    # Case 2: self._hass is None, fallback to self._controller.hass
    mock_ctrl_hass = MagicMock()
    mock_ctrl_hass.async_add_executor_job = AsyncMock(side_effect=_mock_add_job)
    ctrl = MagicMock(spec=["hass"])
    ctrl.hass = mock_ctrl_hass

    conn_ctrl = DummyConnection({"host": "127.0.0.1"}, _LOGGER, hass=None)
    conn_ctrl.set_controller_ref(ctrl)
    conn_ctrl.execute = MagicMock(return_value="ok_ctrl")

    res2 = await conn_ctrl.async_execute_with_retry("tmpl2", "val2")
    assert res2 == "ok_ctrl"
    conn_ctrl.execute.assert_called_once_with("tmpl2", "val2", None, None)
    mock_ctrl_hass.async_add_executor_job.assert_awaited_once_with(
        conn_ctrl.execute, "tmpl2", "val2", None, None
    )

    # Case 3: Both self._hass and self._controller are None -> falls back to asyncio.to_thread
    conn_thread = DummyConnection({"host": "127.0.0.1"}, _LOGGER, hass=None)
    conn_thread.execute = MagicMock(return_value="ok_thread")

    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = "ok_thread"
        res3 = await conn_thread.async_execute_with_retry("tmpl3", "val3")
        assert res3 == "ok_thread"
        mock_to_thread.assert_awaited_once_with(
            conn_thread.execute, "tmpl3", "val3", None, None
        )


@pytest.mark.asyncio
async def test_async_execute_with_retry_failures_and_backoff():
    """Test retry loop with exponential backoff, exhaustion, and unexpected exception wrapping."""
    conn = DummyConnection({"host": "127.0.0.1"}, _LOGGER, hass=None)

    # Case 1: RetryNextAttempt with eventual success on attempt 3
    attempts = [0]

    def _mock_execute_eventual(*args):
        attempts[0] += 1
        if attempts[0] < 3:
            raise RetryNextAttempt("Temporary socket timeout")
        return "eventual_success"

    conn.execute = _mock_execute_eventual

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await conn.async_execute_with_retry("tmpl", "val")
        assert res == "eventual_success"
        assert attempts[0] == 3
        assert mock_sleep.call_count == 2
        assert [call.args[0] for call in mock_sleep.call_args_list] == [1.0, 2.0]

    # Case 2: RetryNextAttempt exhausting all 5 retries raises CannotConnect
    conn.execute = MagicMock(side_effect=RetryNextAttempt("Persistent timeout"))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(
            CannotConnect,
            match=r"Connection failed after 5 retries: Persistent timeout",
        ):
            await conn.async_execute_with_retry("tmpl", "val")
        assert mock_sleep.call_count == 4
        assert [call.args[0] for call in mock_sleep.call_args_list] == [
            1.0,
            2.0,
            4.0,
            8.0,
        ]

    # Case 3: Unexpected Exception (ValueError) is immediately wrapped in CannotConnect without sleeping
    conn.execute = MagicMock(side_effect=ValueError("Invalid parameter"))
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(
            CannotConnect,
            match=r"Connection failed after 5 retries: Invalid parameter",
        ):
            await conn.async_execute_with_retry("tmpl", "val")
        mock_sleep.assert_not_called()


def test_check_execute_condition():
    """Test check_execute_condition template rendering, return evaluation, and error handling."""
    mock_logger = MagicMock()
    conn = DummyConnection({}, mock_logger)

    # 1. No condition_template -> returns True
    assert conn.check_execute_condition({"state": "on"}) is True

    # 2. Async render template returning "1" -> True (Kills M57, M58, M59, M44, M61)
    mock_async_tmpl = MagicMock(spec=["async_render"])
    mock_async_tmpl.async_render.return_value = "1"
    conn.condition_template = mock_async_tmpl
    assert conn.check_execute_condition({"state": "on"}) is True
    mock_async_tmpl.async_render.assert_called_once_with(
        {"device_state": {"state": "on"}}
    )
    mock_logger.debug.assert_called_with(
        "%s Execute condition result: %s",
        conn.log_prefix,
        "1",
    )

    # 3. Async render template returning "0" -> False
    mock_async_tmpl.async_render.return_value = "0"
    assert conn.check_execute_condition({"state": "off"}) is False

    # 4. Async render raises Exception -> logs error with exc_info=True and returns False (Kills M68, M70, M71, M72)
    mock_err_tmpl = MagicMock(spec=["async_render"])
    err = RuntimeError("Template syntax error")
    mock_err_tmpl.async_render.side_effect = err
    conn.condition_template = mock_err_tmpl
    assert conn.check_execute_condition({"state": "on"}) is False
    mock_logger.error.assert_called_once_with(
        "%s Error evaluating execute condition, skipping command. Error: %s",
        conn.log_prefix,
        err,
        exc_info=True,
    )

    # 5. Sync render fallback with whitespace stripping
    mock_sync_tmpl = MagicMock(spec=["render"])
    mock_sync_tmpl.render.return_value = "  1  \n"
    conn.condition_template = mock_sync_tmpl
    assert conn.check_execute_condition({"test": "ok"}) is True
    mock_sync_tmpl.render.assert_called_once_with({"device_state": {"test": "ok"}})

    # 6. Sync render result not "1"
    mock_sync_tmpl.render.return_value = "0"
    assert conn.check_execute_condition({"test": "ok"}) is False
    mock_sync_tmpl.render.return_value = "true"
    assert conn.check_execute_condition({"test": "ok"}) is False

    # 7. Sync render error fallback exception logging
    sync_err = ValueError("Sync render error")
    mock_sync_tmpl.render.side_effect = sync_err
    mock_logger.error.reset_mock()
    assert conn.check_execute_condition({"state": "on"}) is False
    mock_logger.error.assert_called_once_with(
        "%s Error evaluating execute condition, skipping command. Error: %s",
        conn.log_prefix,
        sync_err,
        exc_info=True,
    )


def test_check_execute_condition_default_logger():
    """Test logger fallback in check_execute_condition when conn.logger is None."""
    conn = DummyConnection({}, logger=None)
    # 1. No template returns True
    assert conn.check_execute_condition(None) is True

    # 2. Precompiled template returns True and exercises _log.debug fallback without AttributeError
    conn.condition_template = _TMPL_ONE
    assert conn.check_execute_condition({"state": "on"}) is True

    # 3. Exception in template exercises _log.error fallback without AttributeError
    mock_err = MagicMock(spec=["async_render"])
    mock_err.async_render.side_effect = RuntimeError("fallback error")
    conn.condition_template = mock_err
    assert conn.check_execute_condition({"state": "on"}) is False


@pytest.mark.parametrize(
    "conn_cls",
    [
        Connection,
        ConnectionSamsung2878,
    ],
)
def test_connection_async_execute_signature_defaults(conn_cls):
    """Sniper test: kills boolean flip mutants on async_execute default arguments via inspection."""
    sig = inspect.signature(conn_cls.async_execute)
    assert sig.parameters["_is_probe"].default is False
    assert sig.parameters["_is_poll"].default is False


def test_check_execute_condition_pure_device_state_and_controller():
    """Test check_execute_condition controller.pure_device_state resolution and guards."""
    conn = DummyConnection({}, _LOGGER)

    # Case 1: Controller without pure_device_state does not crash with AttributeError
    conn._controller = object()
    conn.condition_template = _TMPL_KEY_VAL
    assert conn.check_execute_condition({"key": "val"}) is True

    # Case 2: Controller with valid pure_device_state dictionary overrides raw device_state
    mock_ctrl = MagicMock()
    mock_ctrl.pure_device_state = {"pure_key": "active"}
    conn._controller = mock_ctrl
    conn.condition_template = _TMPL_PURE_KEY
    assert conn.check_execute_condition({"pure_key": "ignored"}) is True

    # Case 3: Controller pure_device_state is empty dict / invalid non-dict -> falls back to controller.device_state
    mock_ctrl.pure_device_state = {}
    mock_ctrl.device_state = {"ctrl_state_fallback": 88}
    conn.condition_template = _TMPL_CTRL_STATE_88
    assert conn.check_execute_condition(None) is True

    mock_ctrl.pure_device_state = "invalid_string"
    assert conn.check_execute_condition(None) is True

    # Case 4: Controller pure_device_state is truthy non-dict without controller.device_state (Kills M11)
    mock_ctrl2 = MagicMock(spec=["pure_device_state"])
    mock_ctrl2.pure_device_state = "invalid_truthy"
    conn._controller = mock_ctrl2
    conn.condition_template = _TMPL_KEY_VAL
    assert conn.check_execute_condition({"key": "val"}) is True


def test_check_execute_condition_controller_device_state_fallback():
    """Test check_execute_condition controller.device_state fallback and guards."""
    conn = DummyConnection({}, _LOGGER)

    # Case 1: Non-dict device_state (None) and controller without device_state
    conn._controller = object()
    conn.condition_template = _TMPL_EMPTY_DICT
    assert conn.check_execute_condition(None) is True

    # Case 2: Non-dict device_state with controller.device_state dict
    mock_ctrl = MagicMock(spec=["device_state", "get_property"])
    mock_ctrl.device_state = {"ctrl_state": 123}
    conn._controller = mock_ctrl
    conn.condition_template = _TMPL_CTRL_STATE_123
    assert conn.check_execute_condition(None) is True

    # Case 3: controller.device_state is empty dict -> falls through to status_prop (Kills M20)
    mock_ctrl.device_state = {}
    status_prop = MagicMock()
    status_prop.value = {"status_from_prop": 999}
    mock_ctrl.get_property.return_value = status_prop
    conn.condition_template = _TMPL_STATUS_999
    assert conn.check_execute_condition(None) is True

    # Case 4: controller.device_state is invalid non-dict -> falls through to status_prop
    mock_ctrl.device_state = "invalid_non_dict"
    assert conn.check_execute_condition(None) is True


def test_check_execute_condition_controller_get_property_status():
    """Test check_execute_condition controller.get_property('status') fallback."""
    conn = DummyConnection({}, _LOGGER)

    # Case 1: Controller without get_property method
    conn._controller = object()
    conn.condition_template = _TMPL_EMPTY_DICT
    assert conn.check_execute_condition(None) is True

    # Case 2: Controller with get_property returning None (Kills M27)
    mock_ctrl = MagicMock(spec=["get_property"])
    mock_ctrl.get_property.return_value = None
    conn._controller = mock_ctrl
    conn.condition_template = _TMPL_EMPTY_DICT
    assert conn.check_execute_condition(None) is True

    # Case 3: Controller with get_property returning object whose value is None
    status_prop = MagicMock()
    status_prop.value = None
    mock_ctrl.get_property.return_value = status_prop
    conn.condition_template = _TMPL_EMPTY_DICT
    assert conn.check_execute_condition(None) is True

    # Case 4: Controller with get_property returning object whose value is non-dict string
    status_prop.value = "not_a_dict_string"
    assert conn.check_execute_condition(None) is True

    # Case 5: Controller with get_property returning dict value
    status_prop.value = {"status_flag": "running"}
    conn.condition_template = _TMPL_STATUS_RUNNING
    assert conn.check_execute_condition(None) is True

    # Case 6: When raw_state is already a valid dict, get_property is NOT called (kills slow-killed mutant 17 & 19)
    mock_ctrl.get_property.reset_mock()
    status_prop.value = {"overwritten": True}
    conn.condition_template = _TMPL_ORIGINAL
    assert conn.check_execute_condition({"original": "keep_me"}) is True
    mock_ctrl.get_property.assert_not_called()


def test_check_execute_condition_dataclass_and_object_conversion():
    """Test check_execute_condition fallback to dataclass and object __dict__."""

    @dataclasses.dataclass
    class InnerData:
        val: int = 42

    @dataclasses.dataclass
    class StateData:
        mode: str = "cool"
        speed: int = 3
        nested: InnerData = dataclasses.field(default_factory=InnerData)

    class CustomObjectState:
        def __init__(self) -> None:
            self.mode = "heat"

    mock_logger = MagicMock()
    conn = DummyConnection({}, mock_logger)

    # Case 1: Dataclass instance with nested dataclass to enforce asdict() deep mapping conversion
    conn.condition_template = _TMPL_DATACLASS_DEEP
    assert conn.check_execute_condition(StateData()) is True
    mock_logger.debug.assert_any_call(
        "%s Translating mapped Dataclass to RAW API dictionary for Jinja evaluation.",
        conn.log_prefix,
    )

    # Case 1b: Dataclass type (class, not instance) must NOT invoke asdict() which would raise TypeError
    conn.condition_template = _TMPL_ONE
    assert conn.check_execute_condition(StateData) is True

    # Case 2: Generic object with __dict__
    conn.condition_template = _TMPL_OBJECT_STATE
    assert conn.check_execute_condition(CustomObjectState()) is True

    # Case 3: Primitive / Non-dataclass / Non-object -> falls back to {}
    conn.condition_template = _TMPL_EMPTY_DICT
    assert conn.check_execute_condition("primitive_string") is True

    # Case 4: Dict state is preserved and not overwritten
    conn.condition_template = _TMPL_DICT_MODE
    assert conn.check_execute_condition({"dict_mode": "dry"}) is True


def test_check_execute_condition_devices_list_unwrapping():
    """Test check_execute_condition Samsung/REST Devices array unwrapping and safety."""
    conn = DummyConnection({}, _LOGGER)

    # Case 1: Valid Devices list with dict
    conn.condition_template = _TMPL_TARGET_TEMP_24
    assert conn.check_execute_condition({"Devices": [{"target_temp": 24}]}) is True

    # Case 2: Empty Devices list does not throw IndexError (kills slow-killed mutant 36, 38)
    conn.condition_template = _TMPL_DEVICES_EMPTY
    assert conn.check_execute_condition({"Devices": []}) is True

    # Case 3: Devices is not a list (e.g. string or None) does not throw exception
    conn.condition_template = _TMPL_DEVICES_NOT_LIST
    assert conn.check_execute_condition({"Devices": "not_a_list"}) is True

    # Case 4: Key other than Devices is not unwrapped (Kills M39, M40, M41, M42)
    conn.condition_template = _TMPL_XXDEVICES
    assert conn.check_execute_condition({"XXDevicesXX": [{"target_temp": 24}]}) is True


@pytest.mark.parametrize(
    ("conn_cls", "matching_type", "unmatched_type"),
    [
        (ConnectionAiohttp8888, "samsung_8888_aiohttp", "samsung_8888_raw"),
        (ConnectionRaw8888, "samsung_8888_raw", "samsung_8888_aiohttp"),
        (ConnectionSamsung2878, "samsung_2878", "samsung_8888_aiohttp"),
        (ConnectionIntesisBox, "intesisbox", "samsung_8888_aiohttp"),
    ],
)
def test_all_registered_connections_match_type(conn_cls, matching_type, unmatched_type):
    """Test match_type contract across registered connection classes."""
    assert conn_cls.match_type(matching_type) is True
    assert conn_cls.match_type(unmatched_type) is False
    assert conn_cls.match_type("unknown_nonexistent_type") is False
