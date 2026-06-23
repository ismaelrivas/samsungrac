# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for YamlController — Phase 2 (executor I/O) and Phase 3 (hass injection) compliance."""
# pylint: disable=redefined-outer-name,protected-access

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.const import CONF_CONFIG_FILE
from custom_components.climate_ip.controller_yaml import YamlController
from custom_components.climate_ip.controller_yaml_config import _YAML_FILE_CACHE
from homeassistant.const import CONF_DEVICE_ID, CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN


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
    from custom_components.climate_ip.const import (
        DOMAIN,  # pylint: disable=import-outside-toplevel
    )
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
    """Config dict without hass/session — they are passed as explicit kwargs (Phase 3)."""
    return {
        CONF_CONFIG_FILE: "test_device.yaml",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_DEVICE_ID: "test_device_id",
        CONF_TOKEN: "test_token",
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
    }



async def test_controller_initialization(
    yaml_config: dict, mock_logger: logging.Logger, mock_hass: MagicMock  # type: ignore[type-arg]
) -> None:
    """Test that YamlController initializes with correct attributes (Phase 3 signature)."""
    controller = YamlController(yaml_config, mock_logger, hass=mock_hass, session=MagicMock())

    assert controller._ip_address == "192.168.1.100"
    assert controller._device_id == "test_device_id"
    assert controller._token == "test_token"
    assert controller._yaml == "test_device.yaml"
    assert controller._unique_id == "AA:BB:CC:DD:EE:FF"
    # Phase 3: hass must not appear in the serializable config dict
    assert "hass" not in controller._config
    assert "session" not in controller._config

    # Hardening against YamlConfigLoader.__init__ dead assignment mutants
    from homeassistant.const import ATTR_ENTITY_ID
    assert controller.loader.connection is None
    assert controller.loader.state_getter is None
    assert controller.loader.name == "yaml"
    assert controller.loader.poll is None
    assert controller.loader.is_fully_initialized is False
    assert controller.loader._parsed_yaml_config is None
    assert controller.loader.properties_list == []
    assert len(controller.loader.service_schema_map) == 1
    key = list(controller.loader.service_schema_map.keys())[0]
    assert key.schema == ATTR_ENTITY_ID



async def test_initialize_loads_yaml(
    yaml_config: dict, mock_logger: logging.Logger, mock_hass: MagicMock  # type: ignore[type-arg]
) -> None:
    """Test that initialize loads YAML configuration."""
    controller = YamlController(yaml_config, mock_logger, hass=mock_hass, session=MagicMock())

    mock_yaml_data = {
        "device": {
            "name": "Test AC",
            "connection": {
                "type": "samsung_2878"
            }
        }
    }

    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml", return_value=mock_yaml_data
    ) as m_load:

        # Mock CLIMATE_IP_CONNECTIONS to return a mock connection class
        with patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS"
        ) as mock_connections:
            mock_conn_class = MagicMock()
            mock_conn_class.match_type.return_value = True
            mock_conn_class.__name__ = "MockConnection"
            mock_conn_instance = MagicMock()
            mock_conn_instance.load_from_yaml.return_value = True
            mock_conn_class.return_value = mock_conn_instance

            mock_connections.__iter__.return_value = [mock_conn_class]

            # Also mock create_status_getter since it's called in initialize
            with patch(
                "custom_components.climate_ip.controller_yaml_config.create_status_getter"
            ) as mock_create_status:
                mock_create_status.return_value = MagicMock()

                result = await controller.initialize()

                assert result is True
                assert controller.loader._parsed_yaml_config == mock_yaml_data
                m_load.assert_called()



async def test_match_type() -> None:
    """Test the match_type static method."""
    assert YamlController.match_type("yaml") is True
    assert YamlController.match_type("YAML") is True
    assert YamlController.match_type("other") is False


# ---------------------------------------------------------------------------
# Phase 2: YAML I/O must be dispatched to the executor thread pool.
# ---------------------------------------------------------------------------



async def test_yaml_file_read_uses_executor(
    yaml_config: dict,  # type: ignore[type-arg]
    mock_logger: logging.Logger,
    mock_hass: MagicMock,
) -> None:
    """YAML file reading must be dispatched via async_add_executor_job.

    Ensures the event loop is never blocked by disk I/O during setup.
    """
    executor_calls: list[str] = []

    async def spy_executor(fn, *args):  # type: ignore[no-untyped-def]
        """Spy on executor dispatches and record the function names."""
        executor_calls.append(getattr(fn, "__name__", repr(fn)))
        return fn(*args)

    mock_hass.async_add_executor_job = spy_executor

    controller = YamlController(yaml_config, mock_logger, hass=mock_hass, session=MagicMock())

    mock_yaml_data = {
        "device": {
            "name": "Test AC",
            "connection": {
                "type": "samsung_2878"
            }
        }
    }
    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml", return_value=mock_yaml_data
    ), patch(
        "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS"
    ) as mock_conns, patch(
        "custom_components.climate_ip.controller_yaml_config.create_status_getter",
        return_value=MagicMock(),
    ):

        mock_conn_class = MagicMock()
        mock_conn_class.match_type.return_value = True
        mock_conn_class.__name__ = "MockConnection"
        mock_conn_instance = MagicMock()
        mock_conn_instance.load_from_yaml.return_value = True
        mock_conn_class.return_value = mock_conn_instance
        mock_conns.__iter__.return_value = [mock_conn_class]

        result = await controller.initialize()

    assert result is True
    # load_yaml must have been dispatched to the executor.
    assert len(executor_calls) >= 1, f"Expected at least 1 executor dispatch, got {executor_calls}"
    assert any(
        "load_yaml" in name for name in executor_calls
    ), f"No load_yaml call found in executor dispatches: {executor_calls}"


async def test_async_set_property_registers_pending_update(
    yaml_config: dict,  # type: ignore[type-arg]
    mock_logger: logging.Logger,
    mock_hass: MagicMock,
) -> None:
    """Test that async_set_property strictly delegates to poller.register_pending_update."""
    controller = YamlController(yaml_config, mock_logger, hass=mock_hass, session=MagicMock())
    
    # Mock loader dependencies
    controller.loader.is_fully_initialized = True
    
    # Mock the operation
    mock_op = AsyncMock()
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
