"""Tests to achieve 100% test coverage on config_flow.py for Bronze IQS."""

import asyncio
from unittest.mock import MagicMock, patch

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.config_flow_helpers import _AUTH_FLOW_CACHE
from custom_components.climate_ip.exceptions import (
    AuthError,
    CannotConnect,
    TokenAcquisitionError,
)
import pytest

from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow


async def test_load_auth_flow_config_errors(hass: HomeAssistant) -> None:
    """Test error handling in _load_auth_flow_config."""
    _AUTH_FLOW_CACHE.clear()
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    # 1. Unmapped device type
    with pytest.raises(ValueError, match="No configuration file mapping"):
        await flow._load_auth_flow_config("unknown_device_type")

    # 2. Main YAML is not a dict
    with patch(
        "custom_components.climate_ip.config_flow_helpers.load_yaml",
        return_value="not_dict",
    ), pytest.raises(ValueError, match="Invalid YAML configuration loaded from"):
        await flow._load_auth_flow_config("samsung_2878")

    # 3. Auth YAML is not a dict
    def fake_load_yaml(path: str):
        if "auth" in str(path):
            return "not_dict"
        return {"device": {"auth_flow_file": "fake_auth.yaml"}}

    with patch(
        "custom_components.climate_ip.config_flow_helpers.load_yaml",
        side_effect=fake_load_yaml,
    ), pytest.raises(ValueError, match="Invalid YAML configuration loaded from"):
        await flow._load_auth_flow_config("samsung_2878")


async def test_cancelled_tasks_in_steps(hass: HomeAssistant) -> None:
    """Test CancelledError propagation across background task steps."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.acquirer = MagicMock()

    loop = asyncio.get_running_loop()

    # 1. async_step_initiate_pairing
    task1 = loop.create_future()
    task1.cancel()
    flow.task = task1
    with pytest.raises(asyncio.CancelledError):
        await flow.async_step_initiate_pairing()

    # 2. async_step_await_button
    task2 = loop.create_future()
    task2.cancel()
    flow.task = task2
    with pytest.raises(asyncio.CancelledError):
        await flow.async_step_await_button()

    # 3. async_step_test_connection
    task3 = loop.create_future()
    task3.cancel()
    flow.task = task3
    with pytest.raises(asyncio.CancelledError):
        await flow.async_step_test_connection()


async def test_map_exception_to_error_all_branches(hass: HomeAssistant) -> None:
    """Exercise _map_exception_to_error across all match branches."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.flow_data = {CONF_IP_ADDRESS: "192.168.1.100"}

    # 1. AbortFlow
    with pytest.raises(AbortFlow):
        flow._map_exception_to_error(
            AbortFlow("already_configured"), phase="initiate_pairing"
        )

    # 2. CannotConnect
    res_conn = flow._map_exception_to_error(
        CannotConnect("conn_err"), phase="initiate_pairing"
    )
    assert res_conn == {
        "ok": False,
        "error": "pairing_connection_failed",
        "error_details": "conn_err",
    }

    # 3. TimeoutError
    res_timeout = flow._map_exception_to_error(
        TimeoutError("timed_out"), phase="initiate_pairing"
    )
    assert res_timeout == {
        "ok": False,
        "error": "timeout_connect",
        "error_details": "timed_out",
    }

    # 4. AuthError with phase="test_connection"
    res_auth_test = flow._map_exception_to_error(
        AuthError("bad_tok"), phase="test_connection"
    )
    assert res_auth_test == {
        "ok": False,
        "error": "invalid_auth",
        "error_details": "bad_tok",
    }

    # 5. AuthError with phase="initiate_pairing"
    res_auth_init = flow._map_exception_to_error(
        AuthError("bad_init"), phase="initiate_pairing"
    )
    assert res_auth_init == {
        "ok": False,
        "error": "pairing_connection_failed",
        "error_details": "bad_init",
    }

    # 6. TokenAcquisitionError with phase="wait_token"
    res_tok_wait = flow._map_exception_to_error(
        TokenAcquisitionError("no_tok"), phase="wait_token"
    )
    assert res_tok_wait == {"ok": False, "error": "token_acquisition_failed"}

    # 7. Default catch-all (RuntimeError) for initiate_pairing and test_connection
    res_unknown = flow._map_exception_to_error(
        RuntimeError("boom"), phase="initiate_pairing"
    )
    assert res_unknown == {"ok": False, "error": "unknown_error"}

    res_cannot_conn = flow._map_exception_to_error(
        RuntimeError("boom"), phase="test_connection"
    )
    assert res_cannot_conn == {"ok": False, "error": "cannot_connect"}


async def test_consume_completed_task_variations(hass: HomeAssistant) -> None:
    """Test _consume_completed_task handles success, failure, and cancellation."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    loop = asyncio.get_running_loop()

    # 1. Successful task
    task_ok = loop.create_future()
    task_ok.set_result({"ok": True, "token": "abc"})
    flow.task = task_ok
    result_ok = flow._consume_completed_task()
    assert result_ok == {"ok": True, "token": "abc"}
    assert flow.task is None

    # 2. Task raising generic Exception
    task_err = loop.create_future()
    task_err.set_exception(RuntimeError("Task failed"))
    flow.task = task_err
    result_err = flow._consume_completed_task()
    assert result_err == {"ok": False, "error": "unknown_error"}
    assert flow.task is None

    # 3. Task raising CancelledError
    task_cancel = loop.create_future()
    task_cancel.cancel()
    flow.task = task_cancel
    with pytest.raises(asyncio.CancelledError):
        flow._consume_completed_task()
