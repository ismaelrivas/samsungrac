from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.climate_ip.controller_yaml_config import (
    YamlConfigLoader,
    clear_yaml_cache,
)


class NakedObj:
    """Objeto estrictamente vacío para aniquilar duck-typing (hasattr/getattr)."""

    pass


@pytest.fixture
def mock_controller_errors():
    ctrl = MagicMock()
    ctrl.log_prefix = "[Test]"
    ctrl.device_id = "dev_error"
    ctrl.unique_id = "uid_error"
    ctrl.hass = None
    ctrl.yaml_file = "/test.yaml"
    return ctrl


@pytest.mark.asyncio
async def test_async_initialize_early_exits_bombardment(mock_controller_errors):
    """Kills the Untested mutants by forcing all legitimate return False paths."""

    # 1. Failure: File not specified (None) (Targets 28, 29)
    mock_controller_errors.yaml_file = None
    loader = YamlConfigLoader(mock_controller_errors)
    assert await loader.async_initialize() is False

    # 2. Failure: Exception while reading YAML
    mock_controller_errors.yaml_file = "/test_exploding.yaml"
    clear_yaml_cache()
    loader = YamlConfigLoader(mock_controller_errors)
    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml",
        side_effect=Exception("YAML Explosion"),
    ):
        assert await loader.async_initialize() is False

    # 3. Failure: Empty YAML (Targets 65, 66)
    mock_controller_errors.yaml_file = "/test_empty.yaml"
    clear_yaml_cache()
    loader = YamlConfigLoader(mock_controller_errors)
    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml", return_value={}
    ):
        assert await loader.async_initialize() is False

    # 4. Failure: Missing 'device' node (Targets 76, 77)
    mock_controller_errors.yaml_file = "/test_missing_device.yaml"
    clear_yaml_cache()
    loader = YamlConfigLoader(mock_controller_errors)
    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml",
        return_value={"wrong_node": {}},
    ):
        assert await loader.async_initialize() is False

    # 5. Failure: Without unique_id (Targets 138, 139)
    mock_controller_errors.yaml_file = "/test_no_uid.yaml"
    mock_controller_errors.unique_id = None
    clear_yaml_cache()
    loader = YamlConfigLoader(mock_controller_errors)
    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml",
        return_value={"device": {}},
    ):
        assert await loader.async_initialize() is False
    mock_controller_errors.unique_id = "uid_error"  # Restore

    # 6. Failure: Connection creation fails (ConnectionMatch fails or load_from_yaml returns False)
    mock_conn_class = MagicMock()
    mock_conn_class.__name__ = "MockConnClass"
    mock_conn_class.match_type.return_value = True  # Type matches...
    mock_conn_instance = MagicMock()
    mock_conn_instance.load_from_yaml.return_value = False  # ...but rejects loading
    mock_conn_class.return_value = mock_conn_instance

    mock_controller_errors.yaml_file = "/test_conn_fail.yaml"
    clear_yaml_cache()
    loader = YamlConfigLoader(mock_controller_errors)
    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml",
        return_value={"device": {"connection": {"type": "mock"}}},
    ):
        with patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn_class],
        ):
            assert await loader.async_initialize() is False

    # 7. Failure: Missing 'status' node in YAML (create_status_getter returns None)
    mock_conn_instance.load_from_yaml.return_value = True  # Connection now passes
    mock_controller_errors.yaml_file = "/test_no_status.yaml"
    clear_yaml_cache()
    loader = YamlConfigLoader(mock_controller_errors)
    with patch(
        "custom_components.climate_ip.controller_yaml_config.load_yaml",
        return_value={"device": {"connection": {"type": "mock"}}},
    ):
        with patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [mock_conn_class],
        ):
            with patch(
                "custom_components.climate_ip.controller_yaml_config.create_status_getter",
                return_value=None,
            ):
                assert await loader.async_initialize() is False

    # 8. Failure: No matching connection class found (Targets 208, 209)
    mock_controller_errors.yaml_file = "/test_no_match.yaml"
    clear_yaml_cache()
    loader = YamlConfigLoader(mock_controller_errors)
    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value={"device": {"connection": {"type": "unsupported_type"}}},
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS",
            [],
        ),
    ):
        assert await loader.async_initialize() is False


@pytest.mark.asyncio
async def test_async_finish_initialization_duck_typing_snipers(mock_controller_errors):
    """Kills mutants 42, 98, 111 by isolating hasattr and getattr with NakedObjs."""
    loader = YamlConfigLoader(mock_controller_errors)
    loader.is_fully_initialized = False

    # Prepare a valid YAML so the loop runs
    loader._parsed_yaml_config = {
        "device": {
            "operations": {"op_key_fallback": {}},
            "attributes": {"attr_duck": {}},
        }
    }
    loader._parsed_yaml_cache = {"dev_error": loader._parsed_yaml_config}

    # 1. KILL TARGET 42: Object without "id" attribute to force fallback to "op_key_fallback"
    naked_op = NakedObj()
    naked_op.config_validation_type = str

    # 2. KILL TARGET 98: Asymmetric TemperatureOperation (has one method instead of two)
    naked_attr = NakedObj()
    naked_attr.id = "attr_duck"
    naked_attr.device_class = "temperature"
    naked_attr.set_hass_unit = MagicMock()
    # INTENTIONALLY NO set_device_unit.
    # If mutmut changes 'and' to 'or', it will enter the block and raise AttributeError.

    def fake_create(key, node, conn, ctrl, getter):
        if key == "op_key_fallback":
            return naked_op
        if key == "attr_duck":
            return naked_attr
        return None

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        side_effect=fake_create,
    ):
        try:
            await loader.async_finish_initialization()
        except AttributeError as e:
            pytest.fail(
                f"Mutant alive: Attempted to use a method not validated by hasattr/getattr insecurely: {e}"
            )

        # Lethal assertion for Target 42:
        # Since naked_op did not have "id", it MUST have used "op_key_fallback"
        assert "op_key_fallback" in loader.operations

        # Lethal assertion for Target 98:
        # Lacking 'set_device_unit', the 'and' evaluated False, and it MUST NOT have executed 'set_hass_unit'
        naked_attr.set_hass_unit.assert_not_called()


@pytest.mark.asyncio
async def test_async_finish_initialization_default_schema(mock_controller_errors):
    """Annihilates the default cv.string mutant (Target 39)."""
    from unittest.mock import patch

    import homeassistant.helpers.config_validation as cv
    import voluptuous as vol

    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader

    loader = YamlConfigLoader(mock_controller_errors)
    loader._parsed_yaml_config = {"device": {"operations": {"test_op": {}}}}
    # KEY: We use 'dev_error' which is the device_id defined in the mock_controller_errors fixture
    loader._parsed_yaml_cache = {"dev_error": loader._parsed_yaml_config}

    class NakedProp:
        id = "test_op"
        # INTENTIONALLY WITHOUT config_validation_type

    with patch(
        "custom_components.climate_ip.controller_yaml_config.create_property",
        return_value=NakedProp(),
    ):
        await loader.async_finish_initialization()

    # Lethal assertion: It must have used the default cv.string
    assert loader.service_schema_map[vol.Optional("test_op")] == cv.string


@pytest.mark.asyncio
async def test_async_finish_initialization_config_fallback(mock_controller_errors):
    """Annihilates the getattr(None, 'config') forcing the absence of _config (Target 64)."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader

    # Destroy the private attribute
    if hasattr(mock_controller_errors, "_config"):
        delattr(mock_controller_errors, "_config")

    # Leave only the public one
    mock_controller_errors.config = {"entry_id": "fallback_entry_id"}
    mock_controller_errors.hass = MagicMock()
    mock_controller_errors.hass.config_entries.async_get_entry = MagicMock()

    loader = YamlConfigLoader(mock_controller_errors)
    loader._parsed_yaml_config = {"device": {}}
    loader._parsed_yaml_cache = {"dev_error": loader._parsed_yaml_config}

    await loader.async_finish_initialization()

    # Lethal assertion: If fallback failed, async_get_entry will not be called with this ID
    mock_controller_errors.hass.config_entries.async_get_entry.assert_called_once_with(
        "fallback_entry_id"
    )


@pytest.mark.asyncio
async def test_async_initialize_config_entry_fetch(mock_controller_errors):
    """Verify mutant kill for mutation async_get_entry(None) auditing the parameter (Target 70)."""
    from unittest.mock import MagicMock, patch

    from custom_components.climate_ip.const import CONF_DEVICE_TYPE
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader

    # Tactical injection with constants
    mock_controller_errors._config = {
        "entry_id": "TARGET_ENTRY_ID",
        CONF_DEVICE_TYPE: "samsung_8888",
    }
    mock_controller_errors.config = (
        mock_controller_errors._config
    )  # Synchronize fallbacks
    mock_controller_errors.yaml_file = "/test.yaml"
    mock_controller_errors.hass = MagicMock()
    mock_controller_errors.hass.config_entries.async_get_entry = MagicMock()

    # [!] FIX: Inject a real coroutine to simulate Home Assistant's executor and avoid crash
    async def mock_async_add_executor_job(*args, **kwargs):
        return args[0](*args[1:], **kwargs)

    mock_controller_errors.hass.async_add_executor_job = mock_async_add_executor_job

    loader = YamlConfigLoader(mock_controller_errors)
    loader._parsed_yaml_cache = {}

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_config.load_yaml",
            return_value={"device": {"connection": {"type": "mock"}, "status": {}}},
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.CLIMATE_IP_CONNECTIONS"
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_config.create_status_getter"
        ),
    ):
        await loader.async_initialize()

    # Lethal assertion: The framework must have been queried with the exact ID, not None
    mock_controller_errors.hass.config_entries.async_get_entry.assert_called_once_with(
        "TARGET_ENTRY_ID"
    )


@pytest.mark.asyncio
async def test_apply_temperature_units_simple_sensor_fallback(mock_controller_errors):
    """Annihilates the final mutant (Target 83) by forcing the temperature 'elif' branch."""
    from custom_components.climate_ip.controller_yaml_config import YamlConfigLoader

    loader = YamlConfigLoader(mock_controller_errors)
    loader.is_fully_initialized = False

    class SimpleTempSensor:
        def __init__(self):
            self.id = "simple_temp_sensor"
            self.device_class = "temperature"
            self.unit_applied = None

        # [!] INTENTIONALLY OMIT set_hass_unit and set_device_unit
        # Forces production code to fail first 'if' and drop to 'elif'

        def set_unit_of_measurement(self, unit):
            self.unit_applied = unit

    # Inject raw object (NOT MagicMock)
    strict_sensor = SimpleTempSensor()
    loader.sensors = {"simple_temp": strict_sensor}

    loader._parsed_yaml_config = {"device": {}}
    loader._parsed_yaml_cache = {
        mock_controller_errors.device_id: loader._parsed_yaml_config
    }

    # Configure expected unit (fallback)
    mock_controller_errors.hass = MagicMock()
    mock_controller_errors.hass.config.units.temperature_unit = "°F"

    await loader.async_finish_initialization()

    # Lethal assertion: Engine MUST have dropped to 'elif' and applied unit
    assert strict_sensor.unit_applied == "°F", (
        "The temperature fallback 'elif hasattr' block did not execute."
    )
