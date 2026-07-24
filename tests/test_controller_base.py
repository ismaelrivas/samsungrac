"""Tests for the base ClimateController and create_controller factory."""

import logging
import pytest
from unittest.mock import patch

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
    def name(self) -> str | None:
        return self._name

    @property
    def debug(self) -> bool:
        return False

    async def update_state(self) -> bool:
        return True

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
    assert controller._shared_raw_client is None
    assert controller.discovered_devices is None


def test_register_controller_kills_mutants() -> None:
    """Test register_controller securely without mutating global state permanently."""
    from custom_components.climate_ip.controller import register_controller

    class FakeController(DummyController):
        pass

    # Parcheamos la lista con una nueva lista vacía aislada
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
