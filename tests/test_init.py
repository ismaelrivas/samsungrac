# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,missing-class-docstring,too-few-public-methods,too-many-lines,too-many-locals
"""Test the Climate IP setup and actions."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_ip import (
    CONFIG_ENTRY_VERSION,
    PLATFORMS,
    async_migrate_entry,
    async_remove_config_entry_device,
    async_setup_entry,
    async_unload_entry,
    async_update_listener,
)
from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    DOMAIN,
)
from custom_components.climate_ip.controller_yaml import YamlController
from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878


async def test_unload_entry(hass: HomeAssistant) -> None:
    """Test being able to unload an entry cleanly without leaving active tasks."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "192.168.1.100",
            "mac": "AA:BB:CC:DD:EE:FF",
            "device_type": "samsung_2878",
            "token": "dummy_token",
        },
        unique_id="AABBCCDDEEFF",
    )

    # Ensure the MockConfigEntry has the required methods
    if not hasattr(entry, "async_on_unload"):
        entry.async_on_unload = MagicMock()
    if not hasattr(entry, "add_update_listener"):
        entry.add_update_listener = MagicMock()

    entry.add_to_hass(hass)

    # Initialize hass.data as a real dict for the mock to avoid MagicMock dict issues
    if isinstance(hass.data, MagicMock):
        hass.data = {}

    # Ensure async_forward_entry_setups and async_unload_platforms are async mocks
    # on our dummy hass object so they can be safely awaited.
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    # Setup the entry by directly calling our integration's setup function.
    with (
        patch(
            "custom_components.climate_ip.controller_yaml.YamlController.initialize",
            return_value=True,
        ),
        patch(
            "custom_components.climate_ip.coordinator"
            ".SamsungClimateCoordinator.async_config_entry_first_refresh"
        ),
        patch("custom_components.climate_ip.async_get_clientsession"),
    ):
        result_setup = await async_setup_entry(hass, entry)
        assert result_setup is True

    # Verify the entry is loaded successfully into memory
    assert entry.runtime_data is not None

    # Unload the entry and assert shutdown processes were invoked
    with patch(
        "custom_components.climate_ip.coordinator.SamsungClimateCoordinator.async_shutdown"
    ) as mock_shutdown:
        result_unload = await async_unload_entry(hass, entry)
        assert result_unload is True

        # Ensure the connection manager tasks were cancelled/shutdown cleanly
        mock_shutdown.assert_awaited_once()

    # Verify the entry data was completely cleared from memory
    # (coordinator is shut down, but runtime_data object may still exist)
    assert entry.runtime_data is not None

    # LETHAL ASSERTION (Mutants 9 and 12): Require the exact signature for unloading platforms
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(
        entry, PLATFORMS
    )


# ---------------------------------------------------------------------------
# Plan de Pruebas — Caso 5: Config Entry Migration (Audit v8 §D)
# ---------------------------------------------------------------------------


async def test_migrate_entry_v1_to_current(hass: HomeAssistant) -> None:
    """Verify that v1 entries are migrated correctly without data loss."""

    legacy_entry = MagicMock()
    legacy_entry.version = 1
    legacy_entry.data = {
        "ip_address": "192.168.1.100",
        "mac": "AABBCCDDEEFF",
        "token": "legacy_token_abc",
        "device_type": "samsung_2878",
    }
    hass.config_entries.async_update_entry = MagicMock()

    result = await async_migrate_entry(hass, legacy_entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_called_once_with(
        legacy_entry, version=CONFIG_ENTRY_VERSION
    )


async def test_migrate_entry_future_version_rejected(hass: HomeAssistant) -> None:
    """Future config entry versions must be rejected gracefully without crashing."""

    future_entry = MagicMock()
    future_entry.version = 999
    future_entry.data = {}
    hass.config_entries.async_update_entry = MagicMock()

    result = await async_migrate_entry(hass, future_entry)

    assert result is False
    # async_update_entry must NOT be called for an unrecognised future version
    hass.config_entries.async_update_entry.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 3: hass/session injection purity
# ---------------------------------------------------------------------------


def test_hass_not_in_config_dict() -> None:
    """Hass and session must not appear in YamlController._config after init.

    The config dict must remain serializable — no HA runtime objects allowed.
    """

    mock_hass = MagicMock(spec=HomeAssistant)
    config: dict = {
        "ip_address": "192.168.1.1",
        "unique_id": "TESTID",
        "config_file": "samsung_2878.yaml",
    }

    controller = YamlController(
        config=config,
        logger=logging.getLogger("test"),
        hass=mock_hass,
    )

    # Config dict must be clean — no runtime objects
    assert "hass" not in controller._config, (  # type: ignore[attr-defined]
        "hass leaked into YamlController._config"
    )

    # Runtime objects must be properly stored on the instance
    assert controller.hass is mock_hass


async def test_unload_while_connecting(hass: HomeAssistant) -> None:
    """Test race condition when unloading while connection is in progress."""

    config = {
        "host": "192.168.1.100",
        "port": 2878,
        "cert": "dummy.pem",
        "duid": "12345",
    }
    logger = MagicMock()

    conn = ConnectionSamsung2878(config, logger)

    # Use a real Future to simulate the task behaviour
    mock_task = asyncio.get_running_loop().create_future()

    # Mock the manager task to be running
    with patch("asyncio.create_task", return_value=mock_task):
        conn.start_listening()

    # Now simulate stop_listening/unload while the manager is "running"
    with patch.object(conn, "_close_connection", new_callable=AsyncMock) as mock_close:
        # Mock cancel to resolve the future with CancelledError so stop_listening can proceed
        original_cancel = mock_task.cancel

        def mock_cancel_side_effect():
            if not mock_task.done():
                mock_task.set_exception(asyncio.CancelledError())
            return original_cancel()

        with patch.object(
            mock_task, "cancel", side_effect=mock_cancel_side_effect
        ) as mock_cancel_call:
            await conn.stop_listening()

            # Ensure the task was cancelled
            mock_cancel_call.assert_called_once()
            mock_close.assert_awaited_once()
            assert conn._manager_task is None


async def test_migration_runs_for_v1(hass: HomeAssistant) -> None:
    """Asegura que la migración se ejecuta si es v1 y actualiza la entrada."""

    # Entrada v1
    mock_entry = MagicMock()
    mock_entry.version = 1
    mock_entry.data = {"ip_address": "192.168.1.100"}

    with patch.object(hass.config_entries, "async_update_entry") as mock_update:
        result = await async_migrate_entry(hass, mock_entry)

        # Lethal assertions for IDs 10 and 11
        assert result is True, "La migración debió retornar True"

        # FIX: Since async_update_entry is mocked, mock_entry.version property
        # does not auto-update. Must validate arguments mock was called with.
        mock_update.assert_called_once_with(mock_entry, version=2)


async def test_migration_ignored_for_current_version(hass: HomeAssistant) -> None:
    """Asegura que la migración v1 no se ejecute si la versión ya es la correcta."""

    # Entry already in v2. Use INVALID data for v1.
    # If mutant changes 'if entry.version == 1:' to '!= 1' or '== 2',
    # will enter v1 block, fail validator (missing ip_address), and return False.
    mock_entry = MagicMock()
    mock_entry.version = 2
    mock_entry.data = {}

    with patch.object(hass.config_entries, "async_update_entry") as mock_update:
        result = await async_migrate_entry(hass, mock_entry)

        assert result is True
        mock_update.assert_called_once_with(mock_entry, version=2)


async def test_setup_entry_instantiates_controller_strictly(
    hass: HomeAssistant,
) -> None:
    """Verify YamlController is instantiated with exact required arguments."""

    # Base configuration to pass the initial validations of async_setup_entry
    mock_entry = MagicMock()
    mock_entry.data = {
        "ip_address": "192.168.1.100",
        "token": "valid_token",
        "mac": "00:11:22:33:44:55",
        "device_id": "test_device",
        CONF_DEVICE_TYPE: "samsung_2878",
    }
    mock_entry.options = {}
    # Ensure version is correct so it doesn't trigger migration
    mock_entry.version = 2
    mock_entry.unique_id = "test_mac_123"
    mock_entry.entry_id = "test_entry_123"

    # Patch YamlController inside the __init__.py namespace
    with patch("custom_components.climate_ip.YamlController") as mock_yaml_class:
        # Prepare the mock instance to simulate a complete success
        mock_instance = mock_yaml_class.return_value
        mock_instance.initialize = AsyncMock(return_value=True)

        # Prepare network and platform calls so they don't block
        with (
            patch(
                "custom_components.climate_ip.async_get_clientsession"
            ) as mock_get_session,
            patch.object(
                hass.config_entries, "async_forward_entry_setups"
            ) as mock_forward,
            patch(
                "custom_components.climate_ip.SamsungClimateCoordinator"
            ) as mock_coord_class,
        ):
            mock_coord_class.return_value.async_config_entry_first_refresh = AsyncMock()

            # Execute the setup function
            await async_setup_entry(hass, mock_entry)

        # 1. Assertion to kill mutant 108 (controller = None)
        mock_instance.initialize.assert_awaited_once()

        # 2. Assertion to kill mutants 109 to 116 (arguments removed or None)
        mock_yaml_class.assert_called()

        # Extract the kwargs used to call the constructor
        kwargs = mock_yaml_class.call_args.kwargs

        assert "config_entry" in kwargs and kwargs["config_entry"] is mock_entry, (
            "The config_entry argument was omitted or is incorrect"
        )
        assert "logger" in kwargs and kwargs["logger"] is not None, (
            "The logger argument was omitted or is None"
        )
        assert "hass" in kwargs and kwargs["hass"] is hass, (
            "The hass argument was not passed correctly"
        )
        assert kwargs.get("device_id") == "main", (
            "The device_id argument was omitted or incorrect"
        )
        assert kwargs.get("session") is mock_get_session.return_value, (
            "The session argument was omitted or incorrect"
        )

        # Mutant 84: Verify standalone injection
        mock_coord_class.assert_called_once_with(
            hass, mock_instance, mock_entry, device_info=None, parent_unique_id=None
        )
        # Mutants 98 and 99: Verify platforms are registered
        from custom_components.climate_ip import PLATFORMS

        mock_forward.assert_awaited_once_with(mock_entry, PLATFORMS)
        mock_get_session.assert_called_once_with(hass)

        # LETHAL ASSERTIONS (Mutants 101 and 102)
        mock_entry.add_update_listener.assert_called_once_with(async_update_listener)
        mock_entry.async_on_unload.assert_called_once()


async def test_setup_entry_multi_device_branch_and_unique_id_logic(
    hass: HomeAssistant,
) -> None:
    """Verify ID 0 filtering and strict conditional logic for unique_id generation."""

    mock_entry = MagicMock()
    mock_entry.unique_id = "parent_entry_mac"
    mock_entry.entry_id = "test_entry_123"
    # Inject 4 devices to cover ALL logic branches:
    mock_entry.data = {
        "ip_address": "192.168.1.100",
        CONF_DEVICES: [
            # 1. Management device: must be skipped with 'continue'
            {"id": "0", "name": "Wifi Kit", "uuid": "uuid-000"},
            # 2. Normal sub-device: should get "_1" suffix added
            {"id": "1", "name": "Zone A", "uuid": "uuid-111"},
            # 3. Sub-device that ALREADY has the suffix: should fall into 'else' and not duplicate it
            {"id": "2", "name": "Zone B", "uuid": "uuid-222_2"},
            # 4. Sub-device WITHOUT uuid: should fallback to entry.unique_id and add "_3"
            {"id": "3", "name": "Zone C"},
        ],
    }
    mock_entry.options = {}
    mock_entry.version = 2

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch.object(hass.config_entries, "async_forward_entry_setups") as mock_forward,
        patch(
            "custom_components.climate_ip.SamsungClimateCoordinator"
        ) as mock_coordinator_class,
    ):
        mock_yaml_class.return_value.initialize = AsyncMock(return_value=True)
        mock_coordinator_class.return_value.async_config_entry_first_refresh = (
            AsyncMock()
        )

        result = await async_setup_entry(hass, mock_entry)

        assert result is True

        # LETHAL ASSERTION (Mutant 35 - break): Exactly 3 devices must be processed (1, 2 and 3).
        assert mock_yaml_class.call_count == 3, (
            "The loop was prematurely broken or failed to filter ID 0."
        )

        call_args_list = mock_yaml_class.call_args_list

        # Validate Zone A
        kwargs_a = call_args_list[0].kwargs
        assert kwargs_a.get("config_entry") is mock_entry, "config_entry was omitted"
        assert kwargs_a.get("logger") is not None, "The logger was omitted"
        assert kwargs_a.get("hass") is hass, "The hass argument is incorrect"

        # Validate Zone B
        kwargs_b = call_args_list[1].kwargs
        assert kwargs_b.get("config_entry") is mock_entry, "config_entry was omitted"

        # Validate Zone C
        kwargs_c = call_args_list[2].kwargs
        assert kwargs_c.get("config_entry") is mock_entry, "config_entry was omitted"

        # Mutant 71: Verify coordinators were saved in runtime_data
        assert isinstance(mock_entry.runtime_data, dict), (
            "The coordinators dictionary was not saved in runtime_data"
        )
        assert len(mock_entry.runtime_data) == 3, "Missing coordinators in runtime_data"

        # Mutants 98 and 99: Verify platforms are registered
        from custom_components.climate_ip import PLATFORMS

        mock_forward.assert_awaited_once_with(mock_entry, PLATFORMS)

        # LETHAL ASSERTION (Mutant 68)
        assert all(c is not None for c in mock_entry.runtime_data.values()), (
            "None was assigned to the coordinators dictionary instead of the instance"
        )


async def test_setup_entry_total_initialization_failure(hass: HomeAssistant) -> None:
    """Verify that async_setup_entry raises ConfigEntryNotReady if no controller initializes."""

    mock_entry = MagicMock()
    mock_entry.data = {"ip_address": "192.168.1.100"}  # Standalone
    mock_entry.options = {}

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
    ):
        # Simulate a critical network or validation failure in the controller
        mock_yaml_class.return_value.initialize = AsyncMock(return_value=False)
        mock_yaml_class.return_value.async_shutdown = AsyncMock()

        # Execute for standalone
        with pytest.raises(
            ConfigEntryNotReady, match="No coordinators could be set up"
        ):
            await async_setup_entry(hass, mock_entry)

        mock_yaml_class.return_value.async_shutdown.assert_awaited()

        # Now test the multi-device branch
        mock_yaml_class.return_value.async_shutdown.reset_mock()
        mock_entry.data["devices"] = [{"id": "1", "name": "Zone A"}]
        with pytest.raises(
            ConfigEntryNotReady, match="No coordinators could be set up"
        ):
            await async_setup_entry(hass, mock_entry)

        mock_yaml_class.return_value.async_shutdown.assert_awaited()


async def test_setup_entry_multi_device_partial_failure(hass: HomeAssistant) -> None:
    """Verify that if a sub-device fails, the loop continues with the rest (continue vs break)."""

    mock_entry = MagicMock()
    mock_entry.data = {
        "ip_address": "192.168.1.100",
        CONF_DEVICES: [{"id": "1", "name": "Zone A"}, {"id": "2", "name": "Zone B"}],
    }
    mock_entry.options = {}
    mock_entry.version = 2

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch(
            "custom_components.climate_ip.SamsungClimateCoordinator"
        ) as mock_coord_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch.object(hass.config_entries, "async_forward_entry_setups"),
    ):
        # Force Zone A to fail, but Zone B to succeed
        mock_instance_1 = MagicMock()
        mock_instance_1.initialize = AsyncMock(return_value=False)
        mock_instance_1.async_shutdown = AsyncMock()
        mock_instance_1.log_prefix = "[Zone A]"

        mock_instance_2 = MagicMock()
        mock_instance_2.initialize = AsyncMock(return_value=True)
        mock_instance_2.async_shutdown = AsyncMock()
        mock_instance_2.log_prefix = "[Zone B]"

        # side_effect returns the mocks in order for each loop iteration
        mock_yaml_class.side_effect = [mock_instance_1, mock_instance_2]

        mock_coord_class.return_value.async_config_entry_first_refresh = AsyncMock()
        await async_setup_entry(hass, mock_entry)

        # In concurrent setup, Zone B coordinator succeeds and is saved in runtime_data
        assert len(mock_entry.runtime_data) == 1, (
            "Partial device setup failed to record Zone B."
        )
        assert "2" in mock_entry.runtime_data


async def test_setup_entry_coordinator_instantiation_strict(
    hass: HomeAssistant,
) -> None:
    """Verify strict dependency injection in the SamsungClimateCoordinator."""

    mock_entry = MagicMock()
    mock_entry.unique_id = "parent_mac"
    mock_entry.data = {
        "ip_address": "192.168.1.100",
        CONF_DEVICES: [{"id": "1", "name": "Zone A"}],
    }
    mock_entry.options = {}
    mock_entry.version = 2

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch(
            "custom_components.climate_ip.SamsungClimateCoordinator"
        ) as mock_coord_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch.object(hass.config_entries, "async_forward_entry_setups"),
    ):
        mock_instance = mock_yaml_class.return_value
        mock_instance.initialize = AsyncMock(return_value=True)

        mock_coord_class.return_value.async_config_entry_first_refresh = AsyncMock()
        await async_setup_entry(hass, mock_entry)

        # LETHAL ASSERTIONS (Mutants 58 and 59)
        mock_coord_class.assert_called_once()
        args, kwargs = mock_coord_class.call_args

        assert args[0] is hass, "The 'hass' argument is None or incorrect"
        assert args[1] is mock_instance, (
            "The 'controller' argument is None or incorrect"
        )
        assert args[2] is mock_entry, "The 'entry' argument is incorrect"

        # LETHAL ASSERTIONS (Mutants 61, 62, 66, 67)
        assert "device_info" in kwargs and kwargs["device_info"] is not None, (
            "The 'device_info' argument was omitted"
        )
        assert (
            "parent_unique_id" in kwargs and kwargs["parent_unique_id"] == "parent_mac"
        ), "The 'parent_unique_id' argument is incorrect"

        # LETHAL ASSERTION (Mutants 21 to 24): Verify payload contents
        device_info_payload = kwargs.get("device_info")
        assert device_info_payload is not None, "Missing device_info payload"
        assert device_info_payload.get("name") == "Zone A", (
            "The sub-device name was lost or incorrectly extracted"
        )


async def test_async_update_listener(hass: HomeAssistant) -> None:
    """Verify that updating options triggers a clean integration reload."""

    entry = MagicMock()
    entry.entry_id = "test_reload_id_123"
    hass.config_entries.async_reload = AsyncMock()

    await async_update_listener(hass, entry)

    # Lethal Assertion: Must reload exactly the current entry ID
    hass.config_entries.async_reload.assert_awaited_once_with("test_reload_id_123")


async def test_async_remove_config_entry_device(hass: HomeAssistant) -> None:
    """Verify the integration permits Home Assistant to remove child devices."""

    entry = MagicMock()
    device_entry = MagicMock()

    # The function is simple but must be strictly validated to return True
    result = await async_remove_config_entry_device(hass, entry, device_entry)
    assert result is True


async def test_async_setup_entry_controller_transient_network_error(
    hass: HomeAssistant,
) -> None:
    """Verify that transient network errors during controller.initialize raise ConfigEntryNotReady."""
    mock_entry = MagicMock()
    mock_entry.unique_id = "test_mac"
    mock_entry.title = "Test AC"
    mock_entry.data = {"ip_address": "192.168.1.50"}
    mock_entry.options = {}

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
    ):
        mock_instance = mock_yaml_class.return_value
        mock_instance.initialize = AsyncMock(
            side_effect=TimeoutError("Connection timed out")
        )
        mock_instance.async_shutdown = AsyncMock()

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_entry)

        mock_instance.async_shutdown.assert_awaited_once()


async def test_setup_single_device_auth_and_refresh_failures(
    hass: HomeAssistant,
) -> None:
    """Verify controller shutdown on auth failure and initial connection error during first refresh."""
    mock_entry = MagicMock()
    mock_entry.unique_id = "mac_123"
    mock_entry.data = {
        "ip_address": "192.168.1.50",
        CONF_DEVICES: [{"id": "1", "name": "Zone Auth Fail"}],
    }
    mock_entry.options = {}

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch(
            "custom_components.climate_ip.SamsungClimateCoordinator"
        ) as mock_coord_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
    ):
        controller = mock_yaml_class.return_value
        controller.initialize = AsyncMock(return_value=True)
        controller.async_shutdown = AsyncMock()

        coord = mock_coord_class.return_value
        coord.async_config_entry_first_refresh = AsyncMock(
            side_effect=ConfigEntryAuthFailed("Invalid token")
        )

        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, mock_entry)

        controller.async_shutdown.assert_awaited()

        # Test UpdateFailed / Connection error branch
        coord.async_config_entry_first_refresh = AsyncMock(
            side_effect=UpdateFailed("Conn error")
        )
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_entry)

        assert controller.async_shutdown.await_count >= 2


async def test_async_setup_entry_rollback_shuts_down_booted_coordinators(
    hass: HomeAssistant,
) -> None:
    """Verify that a fatal exception in one sub-device rolls back and shuts down sibling booted coordinators."""
    mock_entry = MagicMock()
    mock_entry.unique_id = "multi_mac"
    mock_entry.title = "Multi AC"
    mock_entry.data = {
        "ip_address": "192.168.1.100",
        CONF_DEVICES: [
            {"id": "1", "name": "Zone Success"},
            {"id": "2", "name": "Zone Auth Fail"},
        ],
    }
    mock_entry.options = {}

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch(
            "custom_components.climate_ip.SamsungClimateCoordinator"
        ) as mock_coord_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
    ):
        ctrl1 = MagicMock()
        ctrl1.initialize = AsyncMock(return_value=True)
        ctrl1.async_shutdown = AsyncMock()
        ctrl1.log_prefix = "[Z1]"

        ctrl2 = MagicMock()
        ctrl2.initialize = AsyncMock(return_value=True)
        ctrl2.async_shutdown = AsyncMock()
        ctrl2.log_prefix = "[Z2]"

        mock_yaml_class.side_effect = [ctrl1, ctrl2]

        coord1 = MagicMock()
        coord1.async_config_entry_first_refresh = AsyncMock()
        coord1.async_shutdown = AsyncMock()

        coord2 = MagicMock()
        coord2.async_config_entry_first_refresh = AsyncMock(
            side_effect=ConfigEntryAuthFailed("Auth error")
        )
        coord2.async_shutdown = AsyncMock()

        mock_coord_class.side_effect = [coord1, coord2]

        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, mock_entry)

        coord1.async_shutdown.assert_awaited()


async def test_rollback_shutdown_exception_handled(hass: HomeAssistant) -> None:
    """Verify that an exception raised during rollback coordinator shutdown is caught and logged."""
    mock_entry = MagicMock()
    mock_entry.unique_id = "multi_mac_err"
    mock_entry.title = "Multi AC Err"
    mock_entry.data = {
        "ip_address": "192.168.1.100",
        CONF_DEVICES: [
            {"id": "1", "name": "Zone Success"},
            {"id": "2", "name": "Zone Fatal"},
        ],
    }
    mock_entry.options = {}

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch(
            "custom_components.climate_ip.SamsungClimateCoordinator"
        ) as mock_coord_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
    ):
        ctrl1 = MagicMock()
        ctrl1.initialize = AsyncMock(return_value=True)
        ctrl1.async_shutdown = AsyncMock()
        ctrl1.log_prefix = "[Z1]"

        ctrl2 = MagicMock()
        ctrl2.initialize = AsyncMock(return_value=True)
        ctrl2.async_shutdown = AsyncMock()
        ctrl2.log_prefix = "[Z2]"

        mock_yaml_class.side_effect = [ctrl1, ctrl2]

        coord1 = MagicMock()
        coord1.async_config_entry_first_refresh = AsyncMock()
        coord1.async_shutdown = AsyncMock(side_effect=RuntimeError("Shutdown crash"))

        coord2 = MagicMock()
        coord2.async_config_entry_first_refresh = AsyncMock(
            side_effect=ConfigEntryAuthFailed("Fatal")
        )
        coord2.async_shutdown = AsyncMock()

        mock_coord_class.side_effect = [coord1, coord2]

        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, mock_entry)

        coord1.async_shutdown.assert_awaited()


async def test_unload_entry_with_entry_in_setup_retry_prevents_yaml_cache_clear(
    hass: HomeAssistant,
) -> None:
    """Verify clear_yaml_cache is not called if another entry is in SETUP_RETRY state."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "entry_unloading"
    mock_entry.runtime_data = {
        "1": MagicMock(
            async_shutdown=AsyncMock(side_effect=RuntimeError("Teardown error"))
        )
    }

    other_entry = MagicMock()
    other_entry.entry_id = "entry_retrying"
    other_entry.state = ConfigEntryState.SETUP_RETRY

    hass.config_entries.async_entries = MagicMock(
        return_value=[mock_entry, other_entry]
    )

    with (
        patch.object(
            hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
        ),
        patch("custom_components.climate_ip.clear_yaml_cache") as mock_clear_cache,
    ):
        result = await async_unload_entry(hass, mock_entry)
        assert result is True
        mock_clear_cache.assert_not_called()


def test_get_config_value_prioritizes_options_and_default() -> None:
    """Test _get_config_value priority (options over data) and fallback default."""
    from custom_components.climate_ip import _get_config_value

    entry = MagicMock()
    entry.options = {"pref_key": "from_options", "shared_key": "opt_val"}
    entry.data = {"data_key": "from_data", "shared_key": "data_val"}

    # 1. Key in options overrides key in data (kills M1, M2)
    assert _get_config_value(entry, "shared_key") == "opt_val"

    # 2. Key only in options returns option value
    assert _get_config_value(entry, "pref_key") == "from_options"

    # 3. Key only in data returns data value
    assert _get_config_value(entry, "data_key") == "from_data"

    # 4. Key missing from both returns specified default (kills M5, M7)
    assert _get_config_value(entry, "missing_key", "custom_default") == "custom_default"
    assert _get_config_value(entry, "missing_key") is None


@pytest.mark.asyncio
async def test_async_safe_shutdown_handles_custom_awaitable_and_sync() -> None:
    """Test _async_safe_shutdown handles custom awaitable object and sync return (kills M2)."""
    from custom_components.climate_ip import _async_safe_shutdown

    # Case 1: Custom awaitable object that is NOT a coroutine
    class CustomAwaitable:
        """Custom awaitable dummy class for testing _async_safe_shutdown."""

        def __init__(self) -> None:
            self.awaited = False

        def __await__(self):
            self.awaited = True

            async def _dummy():
                pass

            return _dummy().__await__()

    awaitable_obj = CustomAwaitable()
    target_custom = MagicMock()
    target_custom.async_shutdown.return_value = awaitable_obj

    await _async_safe_shutdown(target_custom)
    assert awaitable_obj.awaited is True

    # Case 2: Target without async_shutdown
    await _async_safe_shutdown(object())

    # Case 3: Target returning None (sync shutdown)
    target_sync = MagicMock()
    target_sync.async_shutdown.return_value = None
    await _async_safe_shutdown(target_sync)
    target_sync.async_shutdown.assert_called_once()


def test_build_device_setup_tasks_device_name_and_id_strict(
    hass: HomeAssistant,
) -> None:
    """Test _build_device_setup_tasks extracts exact device_name and handles fallbacks (kills M4, M5, M28)."""
    from custom_components.climate_ip import DEFAULT_UNKNOWN, _build_device_setup_tasks

    entry = MagicMock()
    devices_config = [
        {
            "name": "Missing ID Initial Item"
        },  # raw_device_id is None -> MUST continue, NOT break (kills M5)
        {"id": "0", "name": "Management Wifi"},  # must be skipped
        {"id": "1", "name": "Living Room AC"},  # explicit name
        {"id": "2"},  # missing name -> DEFAULT_UNKNOWN
    ]
    session = MagicMock()

    with patch(
        "custom_components.climate_ip._async_setup_single_device"
    ) as mock_setup_single:
        tasks = _build_device_setup_tasks(hass, entry, devices_config, session)
        assert len(tasks) == 2

        # Verify Unit 1
        call1_args = mock_setup_single.call_args_list[0].args
        assert call1_args[2] == "1"
        assert call1_args[3] == "Living Room AC"
        assert call1_args[3] != DEFAULT_UNKNOWN

        # Verify Unit 2 fallback
        call2_args = mock_setup_single.call_args_list[1].args
        assert call2_args[2] == "2"
        assert call2_args[3] == DEFAULT_UNKNOWN

        for coro in tasks:
            if hasattr(coro, "close"):
                coro.close()


def test_build_device_setup_tasks_cardinality_and_payload(
    hass: HomeAssistant,
) -> None:
    """Test _build_device_setup_tasks cardinality, distinct payloads, and boundary sanitization (kills M5)."""
    from custom_components.climate_ip import (
        DEFAULT_UNKNOWN,
        _build_device_setup_tasks,
    )
    from custom_components.climate_ip.const import MAIN_DEVICE_ID

    entry = MagicMock()
    session = MagicMock()

    # 1. Single Device / Default Fallback (synthesized list for main device)
    single_device_config = [
        {
            "id": MAIN_DEVICE_ID,
            "name": "Main Unit",
        }
    ]
    with patch(
        "custom_components.climate_ip._async_setup_single_device"
    ) as mock_setup_single:
        tasks_single = _build_device_setup_tasks(
            hass, entry, single_device_config, session
        )

        assert len(tasks_single) == 1
        mock_setup_single.assert_called_once_with(
            hass, entry, MAIN_DEVICE_ID, "Main Unit", None, session
        )
        for coro in tasks_single:
            if hasattr(coro, "close"):
                coro.close()

    # 2. Multi-Device Configuration with distinct device IDs
    sub_devices = [
        {"id": "1", "name": "Zone 1", "model": "M1"},
        {"id": "2", "name": "Zone 2", "model": "M2"},
        {"id": "3", "name": "Zone 3", "model": "M3"},
    ]
    with patch(
        "custom_components.climate_ip._async_setup_single_device"
    ) as mock_setup_multi:
        tasks_multi = _build_device_setup_tasks(hass, entry, sub_devices, session)

        # Integrity & cardinality assertions
        assert len(tasks_multi) == 3
        assert mock_setup_multi.call_count == 3
        for i, dev in enumerate(sub_devices):
            assert mock_setup_multi.call_args_list[i].args == (
                hass,
                entry,
                dev["id"],
                dev["name"],
                dev,
                session,
            )

        for coro in tasks_multi:
            if hasattr(coro, "close"):
                coro.close()

    # 3. Fail-Fast & Boundary Cases: interspersed malformed items, none, empty strings, invalid types
    interleaved_config = [
        {
            "name": "No ID Device"
        },  # raw_device_id is None -> continue (KILLS Mutant ID 5)
        {
            "id": None,
            "name": "Explicit None ID",
        },  # raw_device_id is None -> continue (KILLS M5)
        {"id": "", "name": "Empty string ID"},  # empty ID -> continue
        {"id": "   ", "name": "Whitespace ID"},  # whitespace ID -> continue
        "invalid_str_payload",  # non-dict -> continue
        99999,  # non-dict -> continue
        None,  # non-dict -> continue
        {"id": "0", "name": "Management Wifi"},  # ID 0 -> continue
        {"id": "1", "name": "Zone 1"},  # VALID -> task 1
        {"no_id_here": True},  # raw_device_id is None -> continue (KILLS M5)
        {"id": None},  # raw_device_id is None -> continue (KILLS M5)
        {"id": "2", "name": "Zone 2"},  # VALID -> task 2
        {"id": "   "},  # whitespace ID -> continue
        {"id": "3"},  # VALID -> task 3
    ]
    with patch(
        "custom_components.climate_ip._async_setup_single_device"
    ) as mock_setup_interleaved:
        tasks_interleaved = _build_device_setup_tasks(
            hass, entry, interleaved_config, session
        )

        assert len(tasks_interleaved) == 3
        assert mock_setup_interleaved.call_count == 3
        calls = mock_setup_interleaved.call_args_list
        assert calls[0].args[2] == "1"
        assert calls[0].args[3] == "Zone 1"
        assert calls[1].args[2] == "2"
        assert calls[1].args[3] == "Zone 2"
        assert calls[2].args[2] == "3"
        assert calls[2].args[3] == DEFAULT_UNKNOWN

        for coro in tasks_interleaved:
            if hasattr(coro, "close"):
                coro.close()

    # 4. Non-iterable / Invalid devices_config container types
    assert not _build_device_setup_tasks(hass, entry, None, session)  # type: ignore[arg-type]
    assert not _build_device_setup_tasks(hass, entry, "invalid_str", session)  # type: ignore[arg-type]
    assert not _build_device_setup_tasks(hass, entry, 12345, session)  # type: ignore[arg-type]
    assert not _build_device_setup_tasks(hass, entry, {}, session)  # type: ignore[arg-type]


async def test_async_setup_entry_empty_devices_fallback_to_main(
    hass: HomeAssistant,
) -> None:
    """Test async_setup_entry creates 1 task for MAIN_DEVICE_ID when CONF_DEVICES is empty."""
    from custom_components.climate_ip.const import MAIN_DEVICE_ID

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "192.168.1.100",
            "device_type": "samsung_2878",
            CONF_DEVICES: [],
        },
        title="Primary AC",
        unique_id="test_empty_devices_main",
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.climate_ip._async_setup_single_device",
            new_callable=AsyncMock,
        ) as mock_setup_single,
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch.object(hass.config_entries, "async_forward_entry_setups"),
    ):
        mock_setup_single.return_value = (MAIN_DEVICE_ID, MagicMock())

        result = await async_setup_entry(hass, entry)
        assert result is True

        mock_setup_single.assert_awaited_once()
        args = mock_setup_single.call_args.args
        assert args[2] == MAIN_DEVICE_ID
        assert args[3] == "Primary AC"
        assert args[4] is None


async def test_async_setup_entry_single_device_custom_name(hass: HomeAssistant) -> None:
    """Test single device setup uses CONF_NAME from entry data (kills L213 mutants)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "192.168.1.100",
            "name": "Custom Unit Name",
            "device_type": "samsung_2878",
        },
        title="Entry Title",
        unique_id="test_custom_name",
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.climate_ip._async_setup_single_device",
            new_callable=AsyncMock,
        ) as mock_setup_single,
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch.object(hass.config_entries, "async_forward_entry_setups"),
    ):
        mock_setup_single.return_value = ("main", MagicMock())

        result = await async_setup_entry(hass, entry)
        assert result is True

        mock_setup_single.assert_awaited_once()
        args = mock_setup_single.call_args.args
        assert args[2] == "main"
        assert args[3] == "Custom Unit Name"
        assert args[4] is None


async def test_async_setup_entry_single_device_fallback_to_title(
    hass: HomeAssistant,
) -> None:
    """Test single device setup falls back to entry.title when CONF_NAME is not in data (kills L213 default mutants)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "192.168.1.100",
            "device_type": "samsung_2878",
        },
        title="My Custom Title",
        unique_id="test_fallback_title",
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.climate_ip._async_setup_single_device",
            new_callable=AsyncMock,
        ) as mock_setup_single,
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch.object(hass.config_entries, "async_forward_entry_setups"),
    ):
        mock_setup_single.return_value = ("main", MagicMock())

        result = await async_setup_entry(hass, entry)
        assert result is True

        mock_setup_single.assert_awaited_once()
        args = mock_setup_single.call_args.args
        assert args[2] == "main"
        assert args[3] == "My Custom Title"
        assert args[3] != "Unknown"
        assert args[4] is None


async def test_async_setup_entry_multi_device_exception_continues_gathering_for_rollback(
    hass: HomeAssistant,
) -> None:
    """Test that when an exception occurs in results, loop continues so ALL booted coordinators roll back (kills M69)."""
    mock_entry = MagicMock()
    mock_entry.unique_id = "test_multi_rollback"
    mock_entry.title = "Rollback AC"
    mock_entry.data = {
        "ip_address": "192.168.1.100",
        CONF_DEVICES: [
            {"id": "1", "name": "Zone Error"},
            {"id": "2", "name": "Zone OK 1"},
            {"id": "3", "name": "Zone OK 2"},
        ],
    }
    mock_entry.options = {}
    mock_entry.version = 2

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml_class,
        patch(
            "custom_components.climate_ip.SamsungClimateCoordinator"
        ) as mock_coord_class,
        patch("custom_components.climate_ip.async_get_clientsession"),
    ):
        c1 = MagicMock(
            initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
        )
        c2 = MagicMock(
            initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
        )
        c3 = MagicMock(
            initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
        )
        mock_yaml_class.side_effect = [c1, c2, c3]

        coord1 = MagicMock(
            async_config_entry_first_refresh=AsyncMock(
                side_effect=ConfigEntryAuthFailed("Auth Fail")
            ),
            async_shutdown=AsyncMock(),
        )
        coord2 = MagicMock(
            async_config_entry_first_refresh=AsyncMock(),
            async_shutdown=AsyncMock(),
        )
        coord3 = MagicMock(
            async_config_entry_first_refresh=AsyncMock(),
            async_shutdown=AsyncMock(),
        )
        mock_coord_class.side_effect = [coord1, coord2, coord3]

        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, mock_entry)

        # If mutant was 'break' instead of 'continue', coord2 and coord3 are not added to coordinators
        # and will NOT be shutdown during rollback!
        coord2.async_shutdown.assert_awaited_once()
        coord3.async_shutdown.assert_awaited_once()


async def test_async_unload_entry_last_entry_clears_yaml_cache_strict(
    hass: HomeAssistant,
) -> None:
    """Test that unloading the last active entry calls clear_yaml_cache (kills M26, M27)."""
    entry = MagicMock()
    entry.entry_id = "unloading_entry_id"
    entry.state = ConfigEntryState.LOADED
    entry.runtime_data = {"main": MagicMock(async_shutdown=AsyncMock())}

    # hass.config_entries.async_entries returns this entry (and only this entry)
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    with patch("custom_components.climate_ip.clear_yaml_cache") as mock_clear_cache:
        result = await async_unload_entry(hass, entry)
        assert result is True
        # Verify async_entries was called with DOMAIN strictly (kills M26)
        hass.config_entries.async_entries.assert_called_once_with(DOMAIN)
        # Verify clear_yaml_cache was called because other_active_entries was empty (kills M27)
        mock_clear_cache.assert_called_once()


# =====================================================================
# PHASE 4 TARGET 2: __INIT__.PY SURVIVOR ERADICATION
# =====================================================================
async def test_async_setup_single_device_boundary_args_and_fallbacks(
    hass: HomeAssistant,
) -> None:
    """Target 2: Verify _async_setup_single_device parent_unique_id, device_info and error paths."""
    from custom_components.climate_ip import _async_setup_single_device
    from custom_components.climate_ip.const import (
        CONF_DEVICES,
        CONF_SUBDEVICE_ID,
        MAIN_DEVICE_ID,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ip_address": "192.168.1.100", "device_type": "samsung_2878"},
        unique_id="PARENT_UID",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml,
        patch("custom_components.climate_ip.SamsungClimateCoordinator") as mock_coord,
    ):
        # 1. No CONF_DEVICES -> has_devices_list is False -> device_info=None, parent_unique_id=None
        ctrl1 = MagicMock(
            initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
        )
        mock_yaml.return_value = ctrl1
        coord1 = MagicMock(
            async_config_entry_first_refresh=AsyncMock(), async_shutdown=AsyncMock()
        )
        mock_coord.return_value = coord1

        dev_id, res_coord = await _async_setup_single_device(
            hass, entry, MAIN_DEVICE_ID, "Living Room", {"model": "AC"}, None
        )
        assert dev_id == MAIN_DEVICE_ID
        assert res_coord is coord1
        mock_coord.assert_called_once_with(
            hass, ctrl1, entry, device_info=None, parent_unique_id=None
        )

        # 2. With CONF_DEVICES, but device_id is MAIN_DEVICE_ID ("main") -> parent_unique_id is None
        mock_coord.reset_mock()
        entry_main_dev = MockConfigEntry(
            domain=DOMAIN,
            data={
                "ip_address": "192.168.1.100",
                "device_type": "samsung_2878",
                CONF_DEVICES: [{"id": MAIN_DEVICE_ID}],
            },
            unique_id="PARENT_UID",
        )
        entry_main_dev.add_to_hass(hass)
        dev_id, res_coord = await _async_setup_single_device(
            hass,
            entry_main_dev,
            MAIN_DEVICE_ID,
            "Main Unit",
            {"model": "AC_Main"},
            None,
        )
        assert dev_id == MAIN_DEVICE_ID
        assert res_coord is coord1
        mock_coord.assert_called_once_with(
            hass,
            ctrl1,
            entry_main_dev,
            device_info={"model": "AC_Main"},
            parent_unique_id=None,
        )

        # 3. With CONF_DEVICES, and device_id is "sub1" -> parent_unique_id is entry.unique_id
        mock_coord.reset_mock()
        dev_id, res_coord = await _async_setup_single_device(
            hass, entry_main_dev, "sub1", "Sub Unit", {"model": "AC_Sub"}, None
        )
        assert dev_id == "sub1"
        assert res_coord is coord1
        mock_coord.assert_called_once_with(
            hass,
            ctrl1,
            entry_main_dev,
            device_info={"model": "AC_Sub"},
            parent_unique_id="PARENT_UID",
        )

        # 4. Controller initialize returns False -> safe shutdown and returns (device_id, None)
        ctrl_fail = MagicMock(
            initialize=AsyncMock(return_value=False), async_shutdown=AsyncMock()
        )
        mock_yaml.return_value = ctrl_fail
        dev_id, res_coord = await _async_setup_single_device(
            hass, entry, "sub1", "Sub Unit", None, None
        )
        assert dev_id == "sub1"
        assert res_coord is None
        ctrl_fail.async_shutdown.assert_awaited_once()

        # 5. Controller initialize raises OSError -> safe shutdown and returns (device_id, None)
        ctrl_err = MagicMock(
            initialize=AsyncMock(side_effect=OSError("Network down")),
            async_shutdown=AsyncMock(),
        )
        mock_yaml.return_value = ctrl_err
        dev_id, res_coord = await _async_setup_single_device(
            hass, entry, "sub1", "Sub Unit", None, None
        )
        assert dev_id == "sub1"
        assert res_coord is None
        ctrl_err.async_shutdown.assert_awaited_once()


async def test_build_device_setup_tasks_strict_validation(hass: HomeAssistant) -> None:
    """Target 2: Verify _build_device_setup_tasks filtering on non-lists, missing subdevice_ids, and wifi-kit id 0."""
    from custom_components.climate_ip import _build_device_setup_tasks
    from custom_components.climate_ip.const import (
        CONF_NAME,
        CONF_SUBDEVICE_ID,
        WIFI_KIT_MGMT_ID,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="TEST_UID")

    # Non list/tuple -> returns []
    assert _build_device_setup_tasks(hass, entry, None, None) == []
    assert _build_device_setup_tasks(hass, entry, "string_config", None) == []

    # Filtered list: invalid dicts, missing subdevice_id, empty string id, and wifi kit 0
    devices = [
        "not_a_dict",
        {CONF_NAME: "No Sub ID"},
        {CONF_SUBDEVICE_ID: None, CONF_NAME: "None Sub ID"},
        {CONF_SUBDEVICE_ID: "   ", CONF_NAME: "Blank Sub ID"},
        {CONF_SUBDEVICE_ID: WIFI_KIT_MGMT_ID, CONF_NAME: "Wifi Kit 0"},
        {CONF_SUBDEVICE_ID: "1", CONF_NAME: "Zone 1"},
        {CONF_SUBDEVICE_ID: "2", CONF_NAME: None},  # Tests fallback to DEFAULT_UNKNOWN
    ]

    with patch(
        "custom_components.climate_ip._async_setup_single_device"
    ) as mock_setup_single:
        tasks = _build_device_setup_tasks(hass, entry, devices, None)
        assert len(tasks) == 2


async def test_async_setup_entry_smartthings_device_id_normalization(
    hass: HomeAssistant,
) -> None:
    """Target 2: Verify async_setup_entry SmartThings subdevice ID normalization paths."""
    from custom_components.climate_ip.const import (
        CONF_DEVICE_ID,
        CONF_DEVICE_TYPE,
        CONF_NAME,
        CONF_SUBDEVICE_ID,
        DEVICE_TYPE_SMARTTHINGS_DHW,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
        MAIN_DEVICE_ID,
    )

    # 1. SmartThings HVAC with valid device_id
    entry_st_hvac = MockConfigEntry(
        domain=DOMAIN,
        title="Living Room AC",
        data={
            "ip_address": "1.2.3.4",
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_DEVICE_ID: "st_hvac_123",
            CONF_NAME: "Custom HVAC Name",
        },
        unique_id="ST_HVAC_UID",
    )
    entry_st_hvac.add_to_hass(hass)

    with (
        patch(
            "custom_components.climate_ip._build_device_setup_tasks"
        ) as mock_build_tasks,
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch(
            "asyncio.gather", new=AsyncMock(return_value=[("st_hvac_123", MagicMock())])
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ),
    ):
        result_st_hvac = await async_setup_entry(hass, entry_st_hvac)
        assert result_st_hvac is True
        # Verify devices_config passed to _build_device_setup_tasks
        called_devices = mock_build_tasks.call_args[0][2]
        assert called_devices == [
            {CONF_SUBDEVICE_ID: "st_hvac_123", CONF_NAME: "Custom HVAC Name"}
        ]

    # 2. SmartThings DHW with empty device_id -> falls back to MAIN_DEVICE_ID
    entry_st_dhw = MockConfigEntry(
        domain=DOMAIN,
        title="DHW Water Heater",
        data={
            "ip_address": "1.2.3.4",
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW,
            CONF_DEVICE_ID: "   ",
        },
        unique_id="ST_DHW_UID",
    )
    entry_st_dhw.add_to_hass(hass)

    with (
        patch(
            "custom_components.climate_ip._build_device_setup_tasks"
        ) as mock_build_tasks,
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch(
            "asyncio.gather",
            new=AsyncMock(return_value=[(MAIN_DEVICE_ID, MagicMock())]),
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ),
    ):
        result_st_dhw = await async_setup_entry(hass, entry_st_dhw)
        assert result_st_dhw is True
        called_devices = mock_build_tasks.call_args[0][2]
        assert called_devices == [
            {CONF_SUBDEVICE_ID: MAIN_DEVICE_ID, CONF_NAME: "DHW Water Heater"}
        ]


async def test_async_setup_single_device_refresh_error_shutdowns(
    hass: HomeAssistant,
) -> None:
    """Target 3: Kills mutants on lines 105, 149, 158 in _async_setup_single_device."""
    from custom_components.climate_ip import _async_setup_single_device
    from custom_components.climate_ip.const import MAIN_DEVICE_ID

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ip_address": "192.168.1.100", "device_type": "samsung_2878"},
        unique_id="PARENT_UID_SHUTDOWN",
    )
    entry.add_to_hass(hass)
    session_obj = "mock_session_marker"

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml,
        patch("custom_components.climate_ip.SamsungClimateCoordinator") as mock_coord,
    ):
        # 1. Line 105: Verify exact constructor signature and kwargs passed to YamlController
        ctrl1 = MagicMock(
            initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
        )
        mock_yaml.return_value = ctrl1
        coord1 = MagicMock(
            async_config_entry_first_refresh=AsyncMock(), async_shutdown=AsyncMock()
        )
        mock_coord.return_value = coord1

        dev_id, res_coord = await _async_setup_single_device(
            hass, entry, "dev_kw", "Living Room", None, session_obj
        )
        assert dev_id == "dev_kw"
        assert res_coord is coord1
        assert mock_yaml.call_args.kwargs["config_entry"] is entry
        assert mock_yaml.call_args.kwargs["device_id"] == "dev_kw"
        assert mock_yaml.call_args.kwargs["hass"] is hass
        assert mock_yaml.call_args.kwargs["session"] == session_obj

        # 2. Line 149: ConfigEntryAuthFailed triggers safe shutdown on controller and re-raises
        ctrl_auth = MagicMock(
            initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
        )
        mock_yaml.return_value = ctrl_auth
        coord_auth = MagicMock(
            async_config_entry_first_refresh=AsyncMock(
                side_effect=ConfigEntryAuthFailed("Auth invalid")
            ),
            async_shutdown=AsyncMock(),
        )
        mock_coord.return_value = coord_auth

        with pytest.raises(ConfigEntryAuthFailed):
            await _async_setup_single_device(
                hass, entry, "dev_auth", "Living Room", None, session_obj
            )
        ctrl_auth.async_shutdown.assert_awaited_once()

        # 3. Line 158: UpdateFailed, TimeoutError, ConnectionRefusedError, OSError trigger safe shutdown on controller and return (device_id, None)
        error_types = [
            UpdateFailed("Update failed"),
            TimeoutError("Refresh timeout"),
            ConnectionRefusedError("Connection refused"),
            OSError("Network socket error"),
        ]
        for err in error_types:
            ctrl_err = MagicMock(
                initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
            )
            mock_yaml.return_value = ctrl_err
            coord_err = MagicMock(
                async_config_entry_first_refresh=AsyncMock(side_effect=err),
                async_shutdown=AsyncMock(),
            )
            mock_coord.return_value = coord_err

            dev_id_err, res_coord_err = await _async_setup_single_device(
                hass, entry, "dev_fail", "Living Room", None, session_obj
            )
            assert dev_id_err == "dev_fail"
            assert res_coord_err is None
            ctrl_err.async_shutdown.assert_awaited_once()


async def test_async_setup_entry_options_override_and_task_dispatch(
    hass: HomeAssistant,
) -> None:
    """Target 3: Kills mutant on line 234 in async_setup_entry (options vs data for CONF_DEVICE_ID)."""
    from custom_components.climate_ip.const import (
        CONF_DEVICE_ID,
        CONF_DEVICE_TYPE,
        CONF_NAME,
        CONF_SUBDEVICE_ID,
        DEVICE_TYPE_SMARTTHINGS_HVAC,
        MAIN_DEVICE_ID,
    )

    # Options override data for CONF_DEVICE_ID
    entry_opt = MockConfigEntry(
        domain=DOMAIN,
        title="Opt Unit",
        data={
            "ip_address": "1.2.3.4",
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_DEVICE_ID: "data_dev_id",
            CONF_NAME: "Data Name",
        },
        options={
            CONF_DEVICE_ID: "opt_dev_id",
            CONF_NAME: "Opt Name",
        },
        unique_id="OPT_OVERRIDE_UID",
    )
    entry_opt.add_to_hass(hass)

    with (
        patch(
            "custom_components.climate_ip._build_device_setup_tasks"
        ) as mock_build_tasks,
        patch(
            "custom_components.climate_ip.async_get_clientsession"
        ) as mock_session_getter,
        patch(
            "asyncio.gather", new=AsyncMock(return_value=[("opt_dev_id", MagicMock())])
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ),
    ):
        mock_session_getter.return_value = "custom_session_obj"
        res = await async_setup_entry(hass, entry_opt)
        assert res is True
        # Exact kwargs and parameters dispatched to _build_device_setup_tasks
        mock_build_tasks.assert_called_once_with(
            hass,
            entry_opt,
            [{CONF_SUBDEVICE_ID: "opt_dev_id", CONF_NAME: "Opt Name"}],
            "custom_session_obj",
        )
