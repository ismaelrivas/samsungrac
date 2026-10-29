"""Tests to achieve 100% test coverage on config_flow.py for Bronze IQS."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow


async def test_load_auth_flow_config_errors(hass: HomeAssistant) -> None:
    """Test error handling in _load_auth_flow_config."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass

    # 1. Unmapped device type
    with pytest.raises(ValueError, match="No configuration file mapping"):
        await flow._load_auth_flow_config("unknown_device_type")

    # 2. Main YAML is not a dict
    with patch(
        "custom_components.climate_ip.config_flow.load_yaml", return_value="not_dict"
    ):
        with pytest.raises(ValueError, match="Invalid YAML configuration loaded from"):
            await flow._load_auth_flow_config("samsung_2878")

    # 3. Auth YAML is not a dict
    def fake_load_yaml(path: str):
        if "auth" in str(path):
            return "not_dict"
        return {"device": {"auth_flow_file": "fake_auth.yaml"}}

    with patch(
        "custom_components.climate_ip.config_flow.load_yaml", side_effect=fake_load_yaml
    ):
        with pytest.raises(ValueError, match="Invalid YAML configuration loaded from"):
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
