"""Tests for base Connection class and registry in connection.py."""

from __future__ import annotations

import asyncio
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    logger = logging.getLogger("test")
    conn = DummyConnection({}, logger)

    # 1. No condition_template -> returns True
    assert conn.check_execute_condition({"state": "on"}) is True

    # 2. Async render template returning "1" -> True
    mock_async_tmpl = MagicMock()
    mock_async_tmpl.async_render.return_value = "1"
    conn.condition_template = mock_async_tmpl
    assert conn.check_execute_condition({"state": "on"}) is True
    mock_async_tmpl.async_render.assert_called_once_with(
        {"device_state": {"state": "on"}}
    )

    # 3. Async render template returning "0" -> False
    mock_async_tmpl.async_render.return_value = "0"
    assert conn.check_execute_condition({"state": "off"}) is False

    # 4. Render raises Exception -> logs error and returns False
    mock_err_tmpl = MagicMock()
    mock_err_tmpl.async_render.side_effect = RuntimeError("Template syntax error")
    conn.condition_template = mock_err_tmpl
    assert conn.check_execute_condition({"state": "on"}) is False


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
    from jinja2 import Template

    conn = DummyConnection({}, logger=None)
    conn.condition_template = Template("1")
    # Since logger=None, _log will use logging.getLogger(__name__) and reach .debug() without blowing up.
    # If mutmut changes 'or' to 'and', _log will be None and raise AttributeError on attempting .debug()
    assert conn.check_execute_condition({"state": "on"}) is True
