# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,abstract-method,missing-function-docstring,missing-class-docstring,too-few-public-methods,use-implicit-booleaness-not-comparison
"""Tests for base Connection class and registry in connection.py."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jinja2 import Template

from custom_components.climate_ip.connection import (
    _HOST_LOCKS,
    CLIMATE_IP_CONNECTIONS,
    Connection,
    register_connection,
)
from custom_components.climate_ip.exceptions import CannotConnect


# Define a mock exception directly for tests to match the one imported dynamically
class RetryNextAttempt(Exception):
    """Mock exception to simulate RetryNextAttempt."""

    pass


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
    """Test Connection initialization and basic properties."""
    logger = logging.getLogger("test_logger")
    config = {"host": "192.168.1.10", "port": 8888}
    hass = MagicMock()

    conn = DummyConnection(config, logger, hass)

    assert conn.config == config
    assert conn.logger == logger
    assert conn._hass == hass
    assert conn._params == {}
    assert conn.is_async_native is False
    assert conn.is_push_supported is False
    assert conn.log_prefix == ""

    base_conn = Connection(config, logger)
    with pytest.raises(NotImplementedError):
        _ = base_conn.is_push_supported


def test_async_lock_resolution():
    """Test async_lock property host/port lock resolution and registry caching."""
    logger = logging.getLogger("test")

    # 1. No host in params or config -> returns instance fallback lock
    conn_no_host = DummyConnection({"port": 8888}, logger)
    assert conn_no_host.async_lock is conn_no_host._lock

    # 2. Host in config, port default fallback
    conn_config_host = DummyConnection({"host": "10.0.0.1"}, logger)
    lock1 = conn_config_host.async_lock
    assert isinstance(lock1, asyncio.Lock)
    assert ("10.0.0.1", "default") in _HOST_LOCKS

    # 3. Host and port in params override config
    conn_params = DummyConnection({"host": "10.0.0.1", "port": 80}, logger)
    conn_params._params = {"host": "192.168.1.50", "port": 8080}
    lock2 = conn_params.async_lock
    assert ("192.168.1.50", "8080") in _HOST_LOCKS

    # 4. Same host and port returns exact same shared Lock instance
    conn_params2 = DummyConnection({}, logger)
    conn_params2._params = {"host": "192.168.1.50", "port": 8080}
    assert conn_params2.async_lock is lock2


def test_load_from_yaml_and_diagnostics():
    """Test base load_from_yaml, get_diagnostics, execute_legacy and create_updated."""
    logger = logging.getLogger("test")
    conn = DummyConnection({"test": "cfg"}, logger)

    assert conn.load_from_yaml({"key": "val"}, None) is False
    assert conn.execute_legacy(None, None, None) is None
    assert conn.create_updated({"key": "val"}) is conn

    diag = conn.get_diagnostics()
    assert diag == {
        "type": "DummyConnection",
        "status": "not_implemented_in_base_class",
    }


def test_execute_and_async_execute_raise_not_implemented():
    """Test execute and async_execute raise NotImplementedError in base class."""
    logger = logging.getLogger("test")
    conn = DummyConnection({}, logger)

    with pytest.raises(NotImplementedError):
        conn.execute(None, None, None)

    with pytest.raises(NotImplementedError):
        asyncio.run(conn.async_execute("GET", "/", None, None))


@pytest.mark.asyncio
async def test_async_execute_with_retry_success_hass_add_job():
    """Test async_execute_with_retry succeeds via hass.async_add_executor_job."""
    logger = logging.getLogger("test")
    hass = MagicMock()
    conn = DummyConnection({"host": "127.0.0.1"}, logger, hass=hass)
    conn.execute = MagicMock(return_value={"status": "ok"})

    async def _mock_add_job(fn, *args):
        return fn(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=_mock_add_job)

    result = await conn.async_execute_with_retry(
        "template", "val", {"state": 1}, "dev1"
    )
    assert result == {"status": "ok"}
    conn.execute.assert_called_once_with("template", "val", {"state": 1}, "dev1")


@pytest.mark.asyncio
async def test_async_execute_with_retry_success_controller_hass():
    """Test async_execute_with_retry fallback to self._controller.hass."""
    logger = logging.getLogger("test")
    conn = DummyConnection({"host": "127.0.0.1"}, logger, hass=None)
    mock_controller = MagicMock()
    mock_hass = MagicMock()
    mock_controller.hass = mock_hass

    # FAIL FAST ASSIGNMENT (Validating initialized property)
    conn._controller = mock_controller
    conn.execute = MagicMock(return_value="success")

    async def _mock_add_job(fn, *args):
        return fn(*args)

    mock_hass.async_add_executor_job = AsyncMock(side_effect=_mock_add_job)

    result = await conn.async_execute_with_retry("tmpl", "val")
    assert result == "success"
    conn.execute.assert_called_once_with("tmpl", "val", None, None)


@pytest.mark.asyncio
async def test_async_execute_with_retry_to_thread_fallback():
    """Test async_execute_with_retry fallback to asyncio.to_thread when hass is None."""
    logger = logging.getLogger("test")
    conn = DummyConnection({"host": "127.0.0.1"}, logger, hass=None)
    conn.execute = MagicMock(return_value="thread_ok")

    result = await conn.async_execute_with_retry("tmpl", "val")
    assert result == "thread_ok"
    conn.execute.assert_called_once_with("tmpl", "val", None, None)


@pytest.mark.asyncio
@patch("custom_components.climate_ip.exceptions.RetryNextAttempt", RetryNextAttempt)
async def test_async_execute_with_retry_retry_loop_and_eventual_success():
    """Test async_execute_with_retry retries on RetryNextAttempt exception."""
    logger = logging.getLogger("test")
    conn = DummyConnection({"host": "127.0.0.1"}, logger, hass=None)

    attempts = [0]

    def _mock_execute(*args):
        attempts[0] += 1
        if attempts[0] < 3:
            raise RetryNextAttempt("Temporary socket timeout")
        return "eventual_success"

    conn.execute = _mock_execute

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await conn.async_execute_with_retry("tmpl", "val")
        assert result == "eventual_success"
        assert attempts[0] == 3
        assert mock_sleep.call_count == 2


@pytest.mark.asyncio
@patch("custom_components.climate_ip.exceptions.RetryNextAttempt", RetryNextAttempt)
async def test_async_execute_with_retry_max_retries_exhausted():
    """Test async_execute_with_retry raises CannotConnect after 5 retries."""
    logger = logging.getLogger("test")
    conn = DummyConnection({"host": "127.0.0.1"}, logger, hass=None)

    conn.execute = MagicMock(side_effect=RetryNextAttempt("Persistent timeout"))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(CannotConnect, match="Connection failed after 5 retries"):
            await conn.async_execute_with_retry("tmpl", "val")
        assert mock_sleep.call_count == 4


@pytest.mark.asyncio
async def test_async_execute_with_retry_other_exception_wrapped():
    """Test non-RetryNextAttempt exception is wrapped in CannotConnect."""
    logger = logging.getLogger("test")
    conn = DummyConnection({"host": "127.0.0.1"}, logger, hass=None)
    conn.execute = MagicMock(side_effect=ValueError("Invalid parameter"))

    with pytest.raises(
        CannotConnect, match="Connection failed after 5 retries: Invalid parameter"
    ):
        await conn.async_execute_with_retry("tmpl", "val")


def test_check_execute_condition():
    """Test check_execute_condition logic for templates, rendering, and exception handling."""
    mock_logger = MagicMock()
    conn = DummyConnection({}, mock_logger)

    # 1. No condition_template -> returns True
    assert conn.check_execute_condition({"state": "on"}) is True

    # 2. Async render template returning "1" -> True (Kills M57, M58, M59)
    mock_async_tmpl = MagicMock()
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

    # 4. Render raises Exception -> logs error with exc_info=True and returns False (Kills M68, M70, M71, M72)
    mock_err_tmpl = MagicMock()
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


def test_check_execute_condition_default_logger():
    """Kills logger fallback / logical mutation mutants in check_execute_condition when logger is None."""
    conn = DummyConnection({}, logger=None)
    assert conn.check_execute_condition(None) is True


def test_connection_async_execute_signature_defaults():
    """Sniper test: kills boolean flip mutants on async_execute default arguments via inspection."""
    sig = inspect.signature(Connection.async_execute)
    assert sig.parameters["_is_probe"].default is False
    assert sig.parameters["_is_poll"].default is False


def test_check_execute_condition_with_default_logger_and_template():
    """Sniper test: kills logical/structural mutants on _log fallback when logger is None and template exists."""
    conn = DummyConnection({}, logger=None)
    conn.condition_template = Template("1")
    # Since logger=None, _log will use logging.getLogger(__name__) and reach .debug() without blowing up.
    # If mutmut changes 'or' to 'and', _log will be None and raise AttributeError on attempting .debug()
    assert conn.check_execute_condition({"state": "on"}) is True


def test_connection_is_available():
    """Test Connection.is_available property returns True."""
    conn = DummyConnection({}, logging.getLogger("test"))
    assert conn.is_available is True
    assert conn.is_available is not False


def test_check_execute_condition_pure_device_state_and_controller():
    """Test check_execute_condition controller.pure_device_state resolution and guards."""
    conn = DummyConnection({}, logging.getLogger("test"))

    # Case 1: Controller without pure_device_state does not crash with AttributeError
    conn._controller = object()
    conn.condition_template = Template("{{ 1 if device_state.key == 'val' else 0 }}")
    assert conn.check_execute_condition({"key": "val"}) is True

    # Case 2: Controller with valid pure_device_state dictionary overrides raw device_state
    mock_ctrl = MagicMock()
    mock_ctrl.pure_device_state = {"pure_key": "active"}
    conn._controller = mock_ctrl
    conn.condition_template = Template(
        "{{ 1 if device_state.pure_key == 'active' else 0 }}"
    )
    assert conn.check_execute_condition({"pure_key": "ignored"}) is True

    # Case 3: Controller pure_device_state is non-dict or empty dict -> does not override and falls back to controller.device_state
    mock_ctrl.pure_device_state = {}
    mock_ctrl.device_state = {"ctrl_state_fallback": 88}
    conn.condition_template = Template(
        "{{ 1 if device_state.ctrl_state_fallback == 88 else 0 }}"
    )
    assert conn.check_execute_condition(None) is True

    mock_ctrl.pure_device_state = "invalid_string"
    assert conn.check_execute_condition(None) is True


def test_check_execute_condition_controller_device_state_fallback():
    """Test check_execute_condition controller.device_state fallback and guards."""
    conn = DummyConnection({}, logging.getLogger("test"))

    # Case 1: Non-dict device_state (None) and controller without device_state
    conn._controller = object()
    conn.condition_template = Template("{{ 1 if device_state == {} else 0 }}")
    assert conn.check_execute_condition(None) is True

    # Case 2: Non-dict device_state with controller.device_state dict
    mock_ctrl = MagicMock()
    del mock_ctrl.pure_device_state
    mock_ctrl.device_state = {"ctrl_state": 123}
    conn._controller = mock_ctrl
    conn.condition_template = Template(
        "{{ 1 if device_state.ctrl_state == 123 else 0 }}"
    )
    assert conn.check_execute_condition(None) is True

    # Case 3: controller.device_state is empty dict or non-dict -> falls through to status_prop
    mock_ctrl.device_state = {}
    status_prop = MagicMock()
    status_prop.value = {"status_from_prop": 999}
    mock_ctrl.get_property.return_value = status_prop
    conn.condition_template = Template(
        "{{ 1 if device_state.status_from_prop == 999 else 0 }}"
    )
    assert conn.check_execute_condition(None) is True

    mock_ctrl.device_state = "invalid_non_dict"
    assert conn.check_execute_condition(None) is True


def test_check_execute_condition_controller_get_property_status():
    """Test check_execute_condition controller.get_property('status') fallback."""
    conn = DummyConnection({}, logging.getLogger("test"))

    # Case 1: Controller without get_property method
    conn._controller = object()
    conn.condition_template = Template("{{ 1 if device_state == {} else 0 }}")
    assert conn.check_execute_condition(None) is True

    # Case 2: Controller with get_property returning None
    mock_ctrl = MagicMock()
    del mock_ctrl.pure_device_state
    del mock_ctrl.device_state
    mock_ctrl.get_property.return_value = None
    conn._controller = mock_ctrl
    assert conn.check_execute_condition(None) is True

    # Case 3: Controller with get_property returning object whose value is None
    status_prop = MagicMock()
    status_prop.value = None
    mock_ctrl.get_property.return_value = status_prop
    assert conn.check_execute_condition(None) is True

    # Case 4: Controller with get_property returning dict value
    status_prop.value = {"status_flag": "running"}
    conn.condition_template = Template(
        "{{ 1 if device_state.status_flag == 'running' else 0 }}"
    )
    assert conn.check_execute_condition(None) is True

    # Case 5: When raw_state is already a valid dict, get_property is NOT called (kills slow-killed mutant 17 & 19)
    mock_ctrl.get_property.reset_mock()
    status_prop.value = {"overwritten": True}
    conn.condition_template = Template(
        "{{ 1 if device_state.original == 'keep_me' else 0 }}"
    )
    assert conn.check_execute_condition({"original": "keep_me"}) is True
    mock_ctrl.get_property.assert_not_called()


def test_check_execute_condition_dataclass_and_object_conversion():
    """Test check_execute_condition fallback to dataclass and object __dict__."""

    @dataclasses.dataclass
    class StateData:
        mode: str = "cool"
        speed: int = 3

    class CustomObjectState:
        def __init__(self) -> None:
            self.mode = "heat"

    mock_logger = MagicMock()
    conn = DummyConnection({}, mock_logger)

    # Case 1: Dataclass instance (Kills M16, M17)
    conn.condition_template = Template(
        "{{ 1 if device_state.mode == 'cool' and device_state.speed == 3 else 0 }}"
    )
    assert conn.check_execute_condition(StateData()) is True
    mock_logger.debug.assert_any_call(
        "%s Translating mapped Dataclass to RAW API dictionary for Jinja evaluation.",
        conn.log_prefix,
    )

    # Case 2: Generic object with __dict__
    conn.condition_template = Template("{{ 1 if device_state.mode == 'heat' else 0 }}")
    assert conn.check_execute_condition(CustomObjectState()) is True

    # Case 3: Primitive / Non-dataclass / Non-object -> falls back to {}
    conn.condition_template = Template("{{ 1 if device_state == {} else 0 }}")
    assert conn.check_execute_condition("primitive_string") is True

    # Case 4: Dict state is preserved and not overwritten
    conn.condition_template = Template(
        "{{ 1 if device_state.dict_mode == 'dry' else 0 }}"
    )
    assert conn.check_execute_condition({"dict_mode": "dry"}) is True


def test_check_execute_condition_devices_list_unwrapping():
    """Test check_execute_condition Samsung/REST Devices array unwrapping and safety."""
    conn = DummyConnection({}, logging.getLogger("test"))

    # Case 1: Valid Devices list with dict
    conn.condition_template = Template(
        "{{ 1 if device_state.target_temp == 24 else 0 }}"
    )
    assert conn.check_execute_condition({"Devices": [{"target_temp": 24}]}) is True

    # Case 2: Empty Devices list does not throw IndexError (kills slow-killed mutant 36, 38)
    conn.condition_template = Template(
        "{{ 1 if 'Devices' in device_state and device_state.Devices == [] else 0 }}"
    )
    assert conn.check_execute_condition({"Devices": []}) is True

    # Case 3: Devices is not a list (e.g. string or None) does not throw exception
    conn.condition_template = Template(
        "{{ 1 if device_state.Devices == 'not_a_list' else 0 }}"
    )
    assert conn.check_execute_condition({"Devices": "not_a_list"}) is True


def test_check_execute_condition_sync_render_and_whitespace():
    """Test check_execute_condition sync render fallback and whitespace handling."""
    conn = DummyConnection({}, logging.getLogger("test"))

    # Case 1: Sync render fallback when callable(async_render) is False
    mock_sync_tmpl = MagicMock(spec=["render"])
    mock_sync_tmpl.render.return_value = "  1  \n"
    conn.condition_template = mock_sync_tmpl
    assert conn.check_execute_condition({"test": "ok"}) is True
    mock_sync_tmpl.render.assert_called_once_with({"device_state": {"test": "ok"}})

    # Case 2: Rendered result is not '1'
    mock_sync_tmpl.render.return_value = "0"
    assert conn.check_execute_condition({"test": "ok"}) is False

    mock_sync_tmpl.render.return_value = "true"
    assert conn.check_execute_condition({"test": "ok"}) is False
