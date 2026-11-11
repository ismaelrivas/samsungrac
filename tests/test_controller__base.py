# pylint: disable=protected-access,no-member,redefined-outer-name,too-few-public-methods,line-too-long,missing-class-docstring,missing-function-docstring,unused-argument,arguments-differ,import-outside-toplevel,too-many-public-methods,trailing-newlines
"""Tests for the base ClimateController and create_controller factory."""

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.climate_ip.controller import ClimateController, ControllerError


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


class PristineDummyController(DummyController):
    """Pristine dummy controller that executes ABC log_prefix without shadowing."""

    def __init__(self, uid: str | None, name: str | None) -> None:
        super().__init__({}, logging.getLogger("test_pristine"), uid_override=uid)
        self._name = name


async def test_controller_base_init_and_getters() -> None:
    """Test the base state initialization, default callbacks, and common getters."""
    assert issubclass(ControllerError, Exception)
    err = ControllerError("test_error_message")
    assert str(err) == "test_error_message"

    logger = logging.getLogger(__name__)
    controller = DummyController({"test": "config"}, logger)
    assert controller._logger is logger
    assert controller._connection is None
    assert controller.discovered_devices is None
    assert controller._token_refreshed_callback is None
    assert controller.hass is None

    # Callbacks must be initialized to their explicit default handlers, not None
    assert (
        controller.on_ssl_config_updated
        is ClimateController._default_on_ssl_config_updated
    )
    assert (
        controller.on_push_update_callback
        is ClimateController._default_on_push_update_callback
    )
    assert (
        controller.request_refresh_callback
        is ClimateController._default_request_refresh_callback
    )
    assert (
        controller.on_offline_callback is ClimateController._default_on_offline_callback
    )
    assert (
        controller.on_connection_failed_callback
        is ClimateController._default_on_connection_failed_callback
    )

    # Verify invoking default callbacks executes without raising exceptions
    assert controller.on_ssl_config_updated({"ssl": True}) is None
    assert await controller.on_push_update_callback({"data": 1}) is None
    assert await controller.on_push_update_callback(None) is None
    assert await controller.request_refresh_callback() is None
    assert controller.on_offline_callback("device_offline") is None
    assert controller.on_connection_failed_callback() is None

    # Base getters and diagnostic properties
    assert controller.config == {"test": "config"}
    assert controller.connection is None
    controller._connection = "mock_conn"
    assert controller.connection == "mock_conn"
    assert controller.raw_state is None
    assert controller.last_poll_data is None
    assert controller.connection_diagnostics == {}
    assert controller.get_diagnostics() == {}

    # Token property
    assert controller.token is None
    controller._token = "test_token_123"
    assert controller.token == "test_token_123"

    # Host property delegating to ip_address
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
    for invalid_token in ("", "   ", None, 12345, ["token"]):
        with pytest.raises(TypeError, match="new_token must be a non-empty string"):
            controller.on_token_refreshed(invalid_token)  # type: ignore[arg-type]


def test_controller_port_resolution_and_validation() -> None:
    """Test port default fallbacks, explicit ints, string integer parsing, and validation."""
    logger = logging.getLogger(__name__)

    # Default fallback when missing or None
    assert DummyController({}, logger).port == 8888
    assert DummyController({"port": None}, logger).port == 8888

    # Explicit integer port resolution and range boundaries
    for valid_int in (1, 2878, 8888, 65535):
        ctrl = DummyController({"port": valid_int}, logger)
        assert ctrl.port == valid_int
        assert isinstance(ctrl.port, int)

    # Valid string integer coercion and whitespace handling
    for valid_str, expected_int in (
        ("8888", 8888),
        (" 2878 ", 2878),
        ("1", 1),
        ("65535", 65535),
    ):
        ctrl = DummyController({"port": valid_str}, logger)
        assert ctrl.port == expected_int
        assert isinstance(ctrl.port, int)

    # Out-of-range integer values -> ValueError
    for out_int in (-1, 0, 65536, 99999):
        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            _ = DummyController({"port": out_int}, logger).port

    # Invalid non-numeric strings -> ValueError
    for inv_str in ("invalid_port", "", "   ", "88.88", "-1"):
        with pytest.raises(ValueError, match="Invalid port string"):
            _ = DummyController({"port": inv_str}, logger).port

    # Out-of-range string integers -> ValueError
    for out_str in ("0", "65536", "99999"):
        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            _ = DummyController({"port": out_str}, logger).port

    # Unsupported types -> TypeError
    for inv_type in ([], {}, (8888,), 88.88, True, False):
        with pytest.raises(TypeError, match="Unsupported port type"):
            _ = DummyController({"port": inv_type}, logger).port


def test_controller_log_prefix_resolution() -> None:
    """Achieves 100% branch coverage on ClimateController.log_prefix."""
    cases = (
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
        # Truncation boundary checks (clean_mac[-6:] vs entire slice)
        ("12345", None, "[12345]"),
        ("123456", None, "[123456]"),
        ("1234567", None, "[234567]"),
        (None, "DummyName", "[myName]"),
        # UUID boundary conditions (kills 'or' mutant on len == 36 and count("-") == 4)
        ("001122334455_" + "0" * 36, None, f"[334455:{'0' * 36}]"),
        ("001122334455_a-b-c-d-e", None, "[334455:a-b-c-d-e]"),
    )
    for uid, name, expected_prefix in cases:
        controller = PristineDummyController(uid, name)
        assert controller.log_prefix == expected_prefix
