"""Tests for the base ClimateController and create_controller factory."""

import logging
import pytest
from typing import Any
from unittest.mock import patch

from custom_components.climate_ip.controller import (
    ClimateController,
    create_controller,
)


class DummyController(ClimateController):
    """Concrete dummy implementation of ClimateController for testing."""

    def __init__(self, config, logger, uid_override=None):
        super().__init__(config, logger)
        self._uid = uid_override

    @staticmethod
    def match_type(controller_type: str) -> bool:
        """Match the dummy controller."""
        return controller_type == "dummy"

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID."""
        return self._uid

    @property
    def device_id(self) -> str | None:
        """Return the device ID."""
        return "device_1"

    @property
    def name(self) -> str | None:
        """Return the name."""
        return "DummyName"

    async def initialize(self) -> bool:
        """Initialize."""
        return True

    async def async_get_status(self):
        """Get status."""
        return {}

    @property
    def poll(self):
        """Poll."""
        return False

    async def update_state(self):
        """Update state."""
        return True

    async def async_set_property(self, property_name, new_value):
        """Set property."""
        return True

    def get_property(self, property_name):
        """Get property."""
        return None

    @property
    def available(self) -> bool:
        return True

    @property
    def id(self) -> str | None:
        return "dummy_id"

    @property
    def state_attributes(self) -> dict:
        return {}

    @property
    def climate_state(self) -> Any:
        return None


@pytest.mark.parametrize(
    "unique_id, expected_prefix",
    [
        ("12345", "[DummyName]"),  # 5 chars -> less than 6, falls back to name
        ("123456", "[123456]"),    # 6 chars -> exactly 6, should use the whole string
        ("1234567", "[234567]"),   # 7 chars -> more than 6, should truncate to last 6
        (None, "[DummyName]"),     # None -> falls back to name
    ],
)
def test_controller_log_prefix_truncation(unique_id, expected_prefix):
    """Test the log_prefix boundary arithmetic for unique_id truncation."""
    logger = logging.getLogger(__name__)
    controller = DummyController({}, logger, uid_override=unique_id)
    assert controller.log_prefix == expected_prefix


@pytest.mark.asyncio
async def test_create_controller_resilience_exceptions(caplog):
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
            assert "Configuration or data error while creating controller bomb_key" in caplog.text
            assert "Detonated KeyError" in caplog.text

        caplog.clear()

        # Test TimeoutError path
        with caplog.at_level(logging.ERROR):
            controller = await create_controller("bomb_timeout", {}, logger)
            assert controller is None
            assert "Network error while initializing controller bomb_timeout" in caplog.text
            assert "Detonated TimeoutError" in caplog.text


@pytest.mark.asyncio
async def test_create_controller_initialization_failure(caplog):
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
            controller = await create_controller("fail_init", {}, logger)
            assert controller is None
            assert "Failed to initialize controller for type fail_init" in caplog.text
