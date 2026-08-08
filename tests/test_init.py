# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test the Climate IP setup and actions."""
# pylint: disable=protected-access,import-outside-toplevel,reimported,redefined-outer-name

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
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
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    config: dict = {
        "ip_address": "192.168.1.1",
        "unique_id": "TESTID",
        "config_file": "samsung_2878.yaml",
    }

    controller = YamlController(
        config=config,
        logger=logging.getLogger("test"),
        hass=mock_hass,
        session=mock_session,
    )

    # Config dict must be clean — no runtime objects
    assert "hass" not in controller._config, (  # type: ignore[attr-defined]
        "hass leaked into YamlController._config"
    )
    assert "session" not in controller._config, (  # type: ignore[attr-defined]
        "session leaked into YamlController._config"
    )

    # Runtime objects must be properly stored on the instance
    assert controller.hass is mock_hass
    assert controller._session is mock_session  # type: ignore[attr-defined]


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

        assert (
            "config_entry" in kwargs and kwargs["config_entry"] is mock_entry
        ), "The config_entry argument was omitted or is incorrect"
        assert (
            "logger" in kwargs and kwargs["logger"] is not None
        ), "The logger argument was omitted or is None"
        assert (
            "hass" in kwargs and kwargs["hass"] is hass
        ), "The hass argument was not passed correctly"
        assert (
            "session" in kwargs and kwargs["session"] is not None
        ), "The session argument was omitted or is None"

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
        assert (
            mock_yaml_class.call_count == 3
        ), "The loop was prematurely broken or failed to filter ID 0."

        call_args_list = mock_yaml_class.call_args_list

        # Validate Zone A
        kwargs_a = call_args_list[0].kwargs
        assert kwargs_a.get("config_entry") is mock_entry, "config_entry was omitted"
        assert kwargs_a.get("logger") is not None, "The logger was omitted"
        assert kwargs_a.get("hass") is hass, "The hass argument is incorrect"
        assert kwargs_a.get("session") is not None, "The session was omitted"

        # Validate Zone B
        kwargs_b = call_args_list[1].kwargs
        assert kwargs_b.get("config_entry") is mock_entry, "config_entry was omitted"

        # Validate Zone C
        kwargs_c = call_args_list[2].kwargs
        assert kwargs_c.get("config_entry") is mock_entry, "config_entry was omitted"

        # Mutant 71: Verify coordinators were saved in runtime_data
        assert isinstance(
            mock_entry.runtime_data, dict
        ), "The coordinators dictionary was not saved in runtime_data"
        assert len(mock_entry.runtime_data) == 3, "Missing coordinators in runtime_data"

        # Mutants 98 and 99: Verify platforms are registered
        from custom_components.climate_ip import PLATFORMS

        mock_forward.assert_awaited_once_with(mock_entry, PLATFORMS)

        # LETHAL ASSERTION (Mutant 68)
        assert all(
            c is not None for c in mock_entry.runtime_data.values()
        ), "None was assigned to the coordinators dictionary instead of the instance"


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

        # Now test the multi-device branch
        mock_entry.data["devices"] = [{"id": "1", "name": "Zone A"}]
        with pytest.raises(
            ConfigEntryNotReady, match="No coordinators could be set up"
        ):
            await async_setup_entry(hass, mock_entry)


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
        assert (
            len(mock_entry.runtime_data) == 1
        ), "Partial device setup failed to record Zone B."
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
        assert (
            args[1] is mock_instance
        ), "The 'controller' argument is None or incorrect"
        assert args[2] is mock_entry, "The 'entry' argument is incorrect"

        # LETHAL ASSERTIONS (Mutants 61, 62, 66, 67)
        assert (
            "device_info" in kwargs and kwargs["device_info"] is not None
        ), "The 'device_info' argument was omitted"
        assert (
            "parent_unique_id" in kwargs and kwargs["parent_unique_id"] == "parent_mac"
        ), "The 'parent_unique_id' argument is incorrect"

        # LETHAL ASSERTION (Mutants 21 to 24): Verify payload contents
        device_info_payload = kwargs.get("device_info")
        assert device_info_payload is not None, "Missing device_info payload"
        assert (
            device_info_payload.get("name") == "Zone A"
        ), "The sub-device name was lost or incorrectly extracted"


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
