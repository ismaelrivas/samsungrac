# pylint: disable=protected-access,no-member,redefined-outer-name,too-few-public-methods,line-too-long,missing-class-docstring,missing-function-docstring,unused-argument,arguments-differ,import-outside-toplevel,too-many-public-methods,trailing-newlines
"""Tests for the base ClimateController and create_controller factory."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from custom_components.climate_ip.controller import (
    ClimateController,
    create_controller,
)


class DummyController(ClimateController):
    """A dummy controller for testing the base abstract class logic."""

    def __init__(self, config, logger, uid_override=None):
        super().__init__(config, logger)
        self._uid = uid_override
        self._name = "DummyName"
        self.mock_is_push = True
        self._saved_config = config

    @staticmethod
    def match_type(controller_type: str) -> bool:
        return controller_type == "dummy"

    async def initialize(self) -> bool:
        return True

    async def async_get_status(self) -> dict | None:
        return {}

    @property
    def is_push_device(self) -> bool:
        return self.mock_is_push

    @property
    def available(self) -> bool:
        return True

    async def async_predict_and_correct_state(self, *args, **kwargs) -> tuple:
        return None, {}

    async def async_clear_pending_updates(self) -> None:
        pass

    @property
    def poll(self) -> bool | None:
        return False

    @property
    def id(self) -> str | None:
        return self._uid

    @property
    def unique_id(self) -> str | None:
        return self._uid

    @property
    def device_id(self) -> str | None:
        return "device_123"

    @property
    def ip_address(self) -> str | None:
        return getattr(self, "_ip_address", "192.168.1.100")

    @ip_address.setter
    def ip_address(self, value: str | None) -> None:
        self._ip_address = value

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def debug(self) -> bool:
        return False

    async def async_update_state(self) -> dict[str, Any] | None:
        return {}

    async def async_set_property(self, property_name: str, new_value) -> bool:
        return True

    async def async_refresh_from_connection(self) -> None:
        pass

    def get_property(self, property_name: str):
        return None

    @property
    def state_attributes(self) -> dict:
        return {}

    @property
    def temperature_unit(self) -> str:
        from homeassistant.const import UnitOfTemperature

        return UnitOfTemperature.CELSIUS

    @property
    def service_schema_map(self) -> dict | None:
        return None

    @property
    def operations(self) -> list[str]:
        return []

    @property
    def attributes(self) -> list[str]:
        return []

    @property
    def climate_state(self):
        return None

    def is_property_superseded(self, prop: str, val) -> bool:
        return False

    def clear_state_cache(self) -> None:
        pass


@pytest.mark.parametrize(
    "unique_id, expected_prefix",
    [
        (
            "12345",
            "[12345]",
        ),  # <--- CORREGIDO: El slicing devuelve la cadena entera si es corta
        ("123456", "[123456]"),
        ("1234567", "[234567]"),
        (None, "[myName]"),  # <--- CORREGIDO: Actualizado al nombre que realmente corta
    ],
)
def test_controller_log_prefix_truncation(unique_id, expected_prefix) -> None:
    """Test the log_prefix boundary arithmetic for unique_id truncation."""
    logger = logging.getLogger(__name__)
    controller = DummyController({}, logger, uid_override=unique_id)
    assert controller.log_prefix == expected_prefix


@pytest.mark.asyncio
async def test_create_controller_resilience_exceptions(caplog) -> None:
    """Test create_controller gracefully handles KeyError and TimeoutError during initialization."""
    logger = logging.getLogger(__name__)

    # Create mock controller classes that match the requested type but detonate on init
    class KeyErrorController(DummyController):
        @staticmethod
        def match_type(controller_type: str) -> bool:
            return controller_type == "bomb_key"

        def __init__(self, config, logger):
            super().__init__(config, logger)
            raise KeyError("Detonated KeyError")

    class TimeoutErrorController(DummyController):
        @staticmethod
        def match_type(controller_type: str) -> bool:
            return controller_type == "bomb_timeout"

        async def initialize(self) -> bool:
            raise TimeoutError("Detonated TimeoutError")

    # Inject our mock classes into CLIMATE_CONTROLLERS
    with patch(
        "custom_components.climate_ip.controller.CLIMATE_CONTROLLERS",
        [KeyErrorController, TimeoutErrorController],
    ):
        # Test KeyError path
        with caplog.at_level(logging.ERROR):
            controller = await create_controller("bomb_key", {}, logger)
            assert controller is None
            assert (
                "Configuration or data error while creating controller bomb_key"
                in caplog.text
            )
            assert "Detonated KeyError" in caplog.text

        caplog.clear()

        # Test TimeoutError path
        with caplog.at_level(logging.ERROR):
            controller = await create_controller("bomb_timeout", {}, logger)
            assert controller is None
            assert (
                "Network error while initializing controller bomb_timeout"
                in caplog.text
            )
            assert "Detonated TimeoutError" in caplog.text


@pytest.mark.asyncio
async def test_create_controller_initialization_failure(caplog) -> None:
    """Test create_controller gracefully handles when initialize() returns False."""
    logger = logging.getLogger(__name__)

    class InitFailsController(DummyController):
        @staticmethod
        def match_type(controller_type: str) -> bool:
            return controller_type == "fail_init"

        async def initialize(self) -> bool:
            return False

    with patch(
        "custom_components.climate_ip.controller.CLIMATE_CONTROLLERS",
        [InitFailsController],
    ):
        with caplog.at_level(logging.ERROR):
            from custom_components.climate_ip.controller import (
                ControllerInitializationError,
            )

            with pytest.raises(ControllerInitializationError):
                await create_controller("fail_init", {}, logger)
            assert "Failed to initialize controller for type fail_init" in caplog.text


def test_controller_base_init_state() -> None:
    """Test the base state initialization to kill mutmut mutations."""
    logger = logging.getLogger(__name__)
    controller = DummyController({"test": "config"}, logger)
    assert controller._logger is logger
    assert controller._connection is None
    assert controller.discovered_devices is None


def test_register_controller_kills_mutants() -> None:
    """Test register_controller securely without mutating global state permanently."""
    from custom_components.climate_ip.controller import register_controller

    class FakeController(DummyController):
        pass

    # Patch list with isolated new empty list
    with patch(
        "custom_components.climate_ip.controller.CLIMATE_CONTROLLERS", []
    ) as mock_list:
        register_controller(FakeController)

        assert mock_list[-1] is FakeController
        assert len(mock_list) == 1


@pytest.mark.asyncio
async def test_create_controller_success_kills_mutants() -> None:
    """Test successful creation to kill config and logger mutations."""
    logger = logging.getLogger(__name__)
    config = {"unique_test": True}

    class SuccessController(DummyController):
        @staticmethod
        def match_type(controller_type: str) -> bool:
            return controller_type == "success_mutant"

    with patch(
        "custom_components.climate_ip.controller.CLIMATE_CONTROLLERS",
        [SuccessController],
    ):
        controller = await create_controller("success_mutant", config, logger)
        assert controller is not None
        assert controller._saved_config is config  # Kills config=None mutant
        assert controller._logger is logger  # Kills logger=None mutant


def test_controller_host_property() -> None:
    """Cover the host property to kill untested mutants."""
    logger = logging.getLogger(__name__)
    controller = DummyController({}, logger)
    controller.ip_address = "192.168.1.50"
    assert controller.host == "192.168.1.50"

    controller.ip_address = None
    assert controller.host is None


def test_controller_token_callback_lifecycle() -> None:
    """Test register_token_callback and on_token_refreshed parameter validation and invocation."""
    logger = logging.getLogger(__name__)
    controller = DummyController({}, logger)

    # 1. on_token_refreshed without registered callback -> completes cleanly without error
    controller.on_token_refreshed("initial_token")

    # 2. Register callback and invoke -> callback called with exact token
    mock_cb = MagicMock()
    controller.register_token_callback(mock_cb)
    controller.on_token_refreshed("new_auth_token_xyz")
    mock_cb.assert_called_once_with("new_auth_token_xyz")

    # 3. Invalid token inputs -> raise TypeError
    with pytest.raises(TypeError, match="new_token must be a non-empty string"):
        controller.on_token_refreshed("")
    with pytest.raises(TypeError, match="new_token must be a non-empty string"):
        controller.on_token_refreshed("   ")
    with pytest.raises(TypeError, match="new_token must be a non-empty string"):
        controller.on_token_refreshed(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="new_token must be a non-empty string"):
        controller.on_token_refreshed(12345)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="new_token must be a non-empty string"):
        controller.on_token_refreshed(["token"])  # type: ignore[arg-type]


def test_controller_port_explicit_integer() -> None:
    """Test Case 1: Initialize with explicit integer port and verify exact value and type."""
    logger = logging.getLogger(__name__)

    # Standard explicit port
    controller = DummyController({"port": 2878}, logger)
    assert controller.port == 2878
    assert isinstance(controller.port, int)
    assert type(controller.port) is int

    # Boundary valid integer ports: 1 and 65535
    controller_min = DummyController({"port": 1}, logger)
    assert controller_min.port == 1
    assert isinstance(controller_min.port, int)

    controller_max = DummyController({"port": 65535}, logger)
    assert controller_max.port == 65535
    assert isinstance(controller_max.port, int)

    controller_8888 = DummyController({"port": 8888}, logger)
    assert controller_8888.port == 8888
    assert isinstance(controller_8888.port, int)


def test_controller_port_default_fallback() -> None:
    """Test Case 2: Initialize with empty config or None port and verify default fallback."""
    logger = logging.getLogger(__name__)

    # Empty dictionary
    controller_empty = DummyController({}, logger)
    assert controller_empty.port == 8888
    assert isinstance(controller_empty.port, int)
    assert type(controller_empty.port) is int

    # Explicit None port
    controller_none = DummyController({"port": None}, logger)
    assert controller_none.port == 8888
    assert isinstance(controller_none.port, int)
    assert type(controller_none.port) is int


def test_controller_port_string_coercion_and_validation() -> None:
    """Test Case 3: Test valid string integer coercion and invalid string rejection."""
    logger = logging.getLogger(__name__)

    # Valid string port coercion
    controller_str = DummyController({"port": "8888"}, logger)
    assert controller_str.port == 8888
    assert isinstance(controller_str.port, int)
    assert type(controller_str.port) is int

    # Valid string port with whitespace and boundaries
    controller_ws = DummyController({"port": " 2878 "}, logger)
    assert controller_ws.port == 2878

    controller_str_min = DummyController({"port": "1"}, logger)
    assert controller_str_min.port == 1

    controller_str_max = DummyController({"port": "65535"}, logger)
    assert controller_str_max.port == 65535

    # Invalid non-numeric strings raise ValueError
    with pytest.raises(ValueError, match="Invalid port string"):
        _ = DummyController({"port": "invalid_port"}, logger).port

    with pytest.raises(ValueError, match="Invalid port string"):
        _ = DummyController({"port": ""}, logger).port

    with pytest.raises(ValueError, match="Invalid port string"):
        _ = DummyController({"port": "   "}, logger).port

    with pytest.raises(ValueError, match="Invalid port string"):
        _ = DummyController({"port": "88.88"}, logger).port

    with pytest.raises(ValueError, match="Invalid port string"):
        _ = DummyController({"port": "-1"}, logger).port

    # Out-of-range string integers raise ValueError
    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        _ = DummyController({"port": "0"}, logger).port

    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        _ = DummyController({"port": "65536"}, logger).port

    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        _ = DummyController({"port": "99999"}, logger).port


def test_controller_port_invalid_types_and_ranges() -> None:
    """Test Case 4: Pass invalid configurations and assert ValueError or TypeError is raised."""
    logger = logging.getLogger(__name__)

    # Out-of-range integer values -> ValueError
    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        _ = DummyController({"port": -1}, logger).port

    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        _ = DummyController({"port": 0}, logger).port

    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        _ = DummyController({"port": 65536}, logger).port

    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        _ = DummyController({"port": 99999}, logger).port

    # Unsupported types -> TypeError
    with pytest.raises(TypeError, match="Unsupported port type"):
        _ = DummyController({"port": []}, logger).port

    with pytest.raises(TypeError, match="Unsupported port type"):
        _ = DummyController({"port": {}}, logger).port

    with pytest.raises(TypeError, match="Unsupported port type"):
        _ = DummyController({"port": (8888,)}, logger).port

    with pytest.raises(TypeError, match="Unsupported port type"):
        _ = DummyController({"port": 88.88}, logger).port

    with pytest.raises(TypeError, match="Unsupported port type"):
        _ = DummyController({"port": True}, logger).port

    with pytest.raises(TypeError, match="Unsupported port type"):
        _ = DummyController({"port": False}, logger).port


class PristineDummyController(DummyController):
    """Pristine dummy controller that executes ABC log_prefix without shadowing."""

    def __init__(self, uid: str | None, name: str | None) -> None:
        super().__init__({}, logging.getLogger("test_pristine"), uid_override=uid)
        self._name = name


@pytest.mark.parametrize(
    ("uid", "name", "expected_prefix"),
    [
        # Case A: Fallbacks
        (None, None, "[NO:ID]"),
        ("", None, "[NO_ID]"),
        # Case B: Colons stripped
        ("00:11:22:33:44:55", None, "[334455]"),
        # Case C: Hyphens stripped
        ("00-11-22-33-44-55", None, "[334455]"),
        # Case D: Main / 0 sentinels ignored
        ("001122334455_main", None, "[334455]"),
        ("001122334455_0", None, "[334455]"),
        ("001122334455_334455", None, "[334455]"),
        ("001122334455_001122334455", None, "[334455]"),
        ("001122334455_12345678-1234-1234-1234-123456789012", None, "[334455]"),
        # Case E: Sub-device routing captured
        ("001122334455_1", None, "[334455:1]"),
        ("001122334455_zone2", None, "[334455:zone2]"),
        # Fallback to name property when unique_id is None
        (None, "00:11:22:33:44:55", "[334455]"),
        (None, "LivingRoom_AC", "[ngRoom:AC]"),
    ],
)
def test_controller_log_prefix_coverage(
    uid: str | None, name: str | None, expected_prefix: str
) -> None:
    """Achieves 100% branch coverage on ClimateController.log_prefix (kills Mutant 34)."""
    controller = PristineDummyController(uid, name)
    assert controller.log_prefix == expected_prefix
