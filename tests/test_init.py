"""Tests for the Samsung Climate IP integration lifecycle and orchestration."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_ip import (
    CONFIG_ENTRY_VERSION,
    DEFAULT_UNKNOWN,
    PLATFORMS,
    _async_safe_shutdown,
    _async_setup_single_device,
    _build_device_setup_tasks,
    _get_config_value,
    async_migrate_entry,
    async_remove_config_entry_device,
    async_setup,
    async_setup_entry,
    async_unload_entry,
    async_update_listener,
)
from custom_components.climate_ip.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONF_NAME,
    CONF_SUBDEVICE_ID,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
    MAIN_DEVICE_ID,
    WIFI_KIT_MGMT_ID,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import UpdateFailed


async def test_async_setup_and_reload_service() -> None:
    """Test async_setup registers reload service and reloads all domain entries."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.config_entries = MagicMock()
    entry1 = MagicMock(entry_id="climate_ip_1")
    entry2 = MagicMock(entry_id="climate_ip_2")
    hass.config_entries.async_entries = MagicMock(return_value=[entry1, entry2])
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    with patch("custom_components.climate_ip.clear_yaml_cache") as mock_clear:
        result = await async_setup(hass, {})
        assert result is True
        assert type(result) is bool

        hass.services.async_register.assert_called_once()
        reg_args, _ = hass.services.async_register.call_args
        assert len(reg_args) == 3
        assert reg_args[0] == DOMAIN
        assert reg_args[1] == "reload"
        handler = reg_args[2]
        assert callable(handler)

        # Call the reload handler with active entries
        call_obj = MagicMock(spec=ServiceCall)
        await handler(call_obj)

        mock_clear.assert_called_once_with()
        hass.config_entries.async_entries.assert_called_once_with(DOMAIN)
        assert hass.config_entries.async_reload.await_count == 2
        hass.config_entries.async_reload.assert_has_awaits(
            [call("climate_ip_1"), call("climate_ip_2")],
            any_order=True,
        )

        # Call reload handler when no entries exist
        mock_clear.reset_mock()
        hass.config_entries.async_reload.reset_mock()
        hass.config_entries.async_entries.return_value = []
        await handler(call_obj)
        mock_clear.assert_called_once_with()
        hass.config_entries.async_reload.assert_not_awaited()


def test_get_config_value() -> None:
    """Test _get_config_value prioritizes options over data and respects defaults."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"key_shared": "data_val", "key_data_only": "data_only"},
        options={"key_shared": "options_val", "key_opt_only": "opt_only"},
    )
    assert _get_config_value(entry, "key_shared") == "options_val"
    assert _get_config_value(entry, "key_shared", "default") == "options_val"
    assert _get_config_value(entry, "key_data_only") == "data_only"
    assert _get_config_value(entry, "key_opt_only") == "opt_only"
    assert _get_config_value(entry, "nonexistent", "fallback") == "fallback"
    assert _get_config_value(entry, "nonexistent") is None


async def test_async_migrate_entry_success_and_noop() -> None:
    """Verify migration upgrades v1 entries and no-ops when already at current version."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_update_entry = MagicMock()

    # Migrate v1 entry
    entry_v1 = MockConfigEntry(domain=DOMAIN, version=1, data={"host": "1.2.3.4"})
    result_v1 = await async_migrate_entry(hass, entry_v1)
    assert result_v1 is True
    assert type(result_v1) is bool
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry_v1, version=CONFIG_ENTRY_VERSION
    )

    # Migrate current version entry
    hass.config_entries.async_update_entry.reset_mock()
    entry_current = MockConfigEntry(
        domain=DOMAIN, version=CONFIG_ENTRY_VERSION, data={"host": "1.2.3.4"}
    )
    result_current = await async_migrate_entry(hass, entry_current)
    assert result_current is True
    assert type(result_current) is bool
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry_current, version=CONFIG_ENTRY_VERSION
    )


async def test_async_migrate_entry_future_version_rejected() -> None:
    """Future config entry versions must be rejected gracefully without updating."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_update_entry = MagicMock()

    entry_future = MockConfigEntry(
        domain=DOMAIN, version=CONFIG_ENTRY_VERSION + 1, data={"host": "1.2.3.4"}
    )
    result = await async_migrate_entry(hass, entry_future)
    assert result is False
    assert type(result) is bool
    hass.config_entries.async_update_entry.assert_not_called()


async def test_async_update_listener() -> None:
    """Verify options update triggers async_reload on config entry."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_reload = AsyncMock(return_value=True)
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_reload_123")

    await async_update_listener(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once_with("test_reload_123")


async def test_async_remove_config_entry_device() -> None:
    """Verify removing a child device from a config entry returns True."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MockConfigEntry(domain=DOMAIN, entry_id="entry_456")
    device_entry = MagicMock(spec=DeviceEntry)
    device_entry.id = "dev_789"

    result = await async_remove_config_entry_device(hass, entry, device_entry)
    assert result is True
    assert type(result) is bool


async def test_async_safe_shutdown() -> None:
    """Test _async_safe_shutdown handles coroutines, custom awaitables, sync callables, and errors."""
    # 1. Coroutine return from async_shutdown
    target_coro = MagicMock(async_shutdown=AsyncMock())
    await _async_safe_shutdown(target_coro)
    target_coro.async_shutdown.assert_awaited_once()

    # 2. Custom awaitable object (must be awaited, killing mutant id 2 on line 107)
    awaited = False

    class CustomAwaitable:
        def __await__(self):
            nonlocal awaited
            awaited = True

            async def _dummy():
                return None

            return _dummy().__await__()

    target_custom = MagicMock(async_shutdown=MagicMock(return_value=CustomAwaitable()))
    await _async_safe_shutdown(target_custom)
    target_custom.async_shutdown.assert_called_once()
    assert awaited is True

    # 3. Synchronous non-awaitable return
    target_sync = MagicMock(async_shutdown=MagicMock(return_value=None))
    await _async_safe_shutdown(target_sync)
    target_sync.async_shutdown.assert_called_once()

    # 4. Target without async_shutdown attribute
    target_none = object()
    await _async_safe_shutdown(target_none)

    # 5. Exception during shutdown is caught and logged
    target_err = MagicMock(
        async_shutdown=MagicMock(side_effect=RuntimeError("Shutdown crash"))
    )
    await _async_safe_shutdown(target_err)
    target_err.async_shutdown.assert_called_once()


def test_build_device_setup_tasks_validation_and_filtering() -> None:
    """Test _build_device_setup_tasks validates types and filters out invalid devices."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MockConfigEntry(domain=DOMAIN, data={})

    # Non-list/tuple config returns empty list
    assert _build_device_setup_tasks(hass, entry, None, None) == []
    assert _build_device_setup_tasks(hass, entry, "invalid_str", None) == []
    assert _build_device_setup_tasks(hass, entry, 12345, None) == []

    # Verify each invalid case continues to process subsequent valid items (kills continue->break mutants)
    valid_sub = {CONF_SUBDEVICE_ID: "valid_id", CONF_NAME: "Valid AC"}
    for invalid_case in [
        "not_a_dict",
        {"name": "No SubdeviceId"},
        {CONF_SUBDEVICE_ID: None, "name": "None SubdeviceId"},
        {CONF_SUBDEVICE_ID: "   ", "name": "Whitespace ID"},
        {CONF_SUBDEVICE_ID: WIFI_KIT_MGMT_ID, "name": "Wifi Kit Mgmt"},
        {CONF_SUBDEVICE_ID: " 0 ", "name": "Wifi Kit String Mgmt"},
    ]:
        tasks = _build_device_setup_tasks(hass, entry, [invalid_case, valid_sub], None)
        assert len(tasks) == 1, f"Failed continue check on {invalid_case}"


async def test_build_device_setup_tasks_cardinality_and_payload() -> None:
    """Test _build_device_setup_tasks cardinality, distinct payloads, and fallback names."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICES: [{"id": "1"}]},
        unique_id="PARENT_UID",
    )
    session = "mock_session"

    devices_config = [
        {CONF_SUBDEVICE_ID: " 1 ", CONF_NAME: "Living Room"},
        {CONF_SUBDEVICE_ID: "2", CONF_NAME: ""},
        {CONF_SUBDEVICE_ID: "3"},
    ]

    with patch(
        "custom_components.climate_ip._async_setup_single_device",
        new_callable=AsyncMock,
    ) as mock_single:
        tasks = _build_device_setup_tasks(hass, entry, devices_config, session)
        assert len(tasks) == 3
        results = await asyncio.gather(*tasks)
        assert len(results) == 3

        assert mock_single.await_count == 3
        mock_single.assert_has_awaits(
            [
                call(hass, entry, "1", "Living Room", devices_config[0], session),
                call(hass, entry, "2", DEFAULT_UNKNOWN, devices_config[1], session),
                call(hass, entry, "3", DEFAULT_UNKNOWN, devices_config[2], session),
            ]
        )

    # Verify device_info is None when has_devices_list is False even if device_id != MAIN_DEVICE_ID (kills mutant 44)
    entry_no_devs = MockConfigEntry(domain=DOMAIN, data={})
    devices_sub_only = [{CONF_SUBDEVICE_ID: "sub_no_list", CONF_NAME: "Sub Unit"}]
    with patch(
        "custom_components.climate_ip._async_setup_single_device",
        new_callable=AsyncMock,
    ) as mock_single_sub:
        tasks = _build_device_setup_tasks(
            hass, entry_no_devs, devices_sub_only, session
        )
        assert len(tasks) == 1
        await asyncio.gather(*tasks)
        mock_single_sub.assert_awaited_once_with(
            hass, entry_no_devs, "sub_no_list", "Sub Unit", None, session
        )


async def test_async_setup_single_device_success() -> None:
    """Verify _async_setup_single_device dependency injection, parent_unique_id, and device_info."""
    hass = MagicMock(spec=HomeAssistant)
    integration_logger = logging.getLogger("custom_components.climate_ip")
    session_marker = "session_marker"

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml,
        patch("custom_components.climate_ip.SamsungClimateCoordinator") as mock_coord,
    ):
        ctrl = MagicMock(
            initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
        )
        mock_yaml.return_value = ctrl
        coord = MagicMock(
            async_config_entry_first_refresh=AsyncMock(), async_shutdown=AsyncMock()
        )
        mock_coord.return_value = coord

        # 1. Without CONF_DEVICES: device_info is None, parent_unique_id is None
        entry_single = MockConfigEntry(
            domain=DOMAIN, data={"ip_address": "1.1.1.1"}, unique_id="SINGLE_UID"
        )
        dev_id, res_coord = await _async_setup_single_device(
            hass,
            entry_single,
            MAIN_DEVICE_ID,
            "Living Room",
            {"model": "AC"},
            session_marker,
        )
        assert dev_id == MAIN_DEVICE_ID
        assert res_coord is coord
        mock_yaml.assert_called_once_with(
            config_entry=entry_single,
            device_id=MAIN_DEVICE_ID,
            logger=integration_logger,
            hass=hass,
            session=session_marker,
        )
        mock_coord.assert_called_once_with(
            hass, ctrl, entry_single, device_info=None, parent_unique_id=None
        )
        coord.async_config_entry_first_refresh.assert_awaited_once()

        # 2. With CONF_DEVICES and MAIN_DEVICE_ID: parent_unique_id remains None
        mock_yaml.reset_mock()
        mock_coord.reset_mock()
        entry_multi = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_DEVICES: [{"id": MAIN_DEVICE_ID}]},
            unique_id="MULTI_UID",
        )
        dev_id, res_coord = await _async_setup_single_device(
            hass,
            entry_multi,
            MAIN_DEVICE_ID,
            "Main Unit",
            {"model": "AC_Main"},
            session_marker,
        )
        assert dev_id == MAIN_DEVICE_ID
        mock_coord.assert_called_once_with(
            hass,
            ctrl,
            entry_multi,
            device_info={"model": "AC_Main"},
            parent_unique_id=None,
        )

        # 3. With CONF_DEVICES and sub-device ID: parent_unique_id is entry.unique_id
        mock_coord.reset_mock()
        dev_id, res_coord = await _async_setup_single_device(
            hass,
            entry_multi,
            "sub1",
            "Sub Unit",
            {"model": "AC_Sub"},
            session_marker,
        )
        assert dev_id == "sub1"
        mock_coord.assert_called_once_with(
            hass,
            ctrl,
            entry_multi,
            device_info={"model": "AC_Sub"},
            parent_unique_id="MULTI_UID",
        )


async def test_async_setup_single_device_initialize_failures() -> None:
    """Verify _async_setup_single_device handles initialization returning False or network errors."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MockConfigEntry(domain=DOMAIN, data={})

    with patch("custom_components.climate_ip.YamlController") as mock_yaml:
        # 1. initialize() returns False -> safe shutdown, returns (dev_id, None)
        ctrl_false = MagicMock(
            initialize=AsyncMock(return_value=False), async_shutdown=AsyncMock()
        )
        mock_yaml.return_value = ctrl_false
        dev_id, res = await _async_setup_single_device(
            hass, entry, "dev1", "Room 1", None, None
        )
        assert dev_id == "dev1"
        assert res is None
        ctrl_false.async_shutdown.assert_awaited_once()

        # 2. initialize() raises transient network errors (TimeoutError, ConnectionRefusedError, OSError)
        for err in [
            TimeoutError("Timeout"),
            ConnectionRefusedError("Refused"),
            OSError("Network unreachable"),
        ]:
            ctrl_err = MagicMock(
                initialize=AsyncMock(side_effect=err), async_shutdown=AsyncMock()
            )
            mock_yaml.return_value = ctrl_err
            dev_id, res = await _async_setup_single_device(
                hass, entry, "dev1", "Room 1", None, None
            )
            assert dev_id == "dev1"
            assert res is None
            ctrl_err.async_shutdown.assert_awaited_once()


async def test_async_setup_single_device_first_refresh_failures() -> None:
    """Verify _async_setup_single_device shuts down controller on refresh auth and network errors."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MockConfigEntry(domain=DOMAIN, data={})

    with (
        patch("custom_components.climate_ip.YamlController") as mock_yaml,
        patch("custom_components.climate_ip.SamsungClimateCoordinator") as mock_coord,
    ):
        ctrl = MagicMock(
            initialize=AsyncMock(return_value=True), async_shutdown=AsyncMock()
        )
        mock_yaml.return_value = ctrl

        # 1. ConfigEntryAuthFailed re-raises after controller safe shutdown
        coord_auth = MagicMock(
            async_config_entry_first_refresh=AsyncMock(
                side_effect=ConfigEntryAuthFailed("Auth expired")
            )
        )
        mock_coord.return_value = coord_auth
        with pytest.raises(ConfigEntryAuthFailed):
            await _async_setup_single_device(
                hass, entry, "dev_auth", "Room Auth", None, None
            )
        ctrl.async_shutdown.assert_awaited_once()

        # 2. UpdateFailed, TimeoutError, ConnectionRefusedError, OSError catch and return (dev_id, None)
        for err in [
            UpdateFailed("Update failed"),
            TimeoutError("Timeout"),
            ConnectionRefusedError("Refused"),
            OSError("Socket closed"),
        ]:
            ctrl.async_shutdown.reset_mock()
            coord_err = MagicMock(
                async_config_entry_first_refresh=AsyncMock(side_effect=err)
            )
            mock_coord.return_value = coord_err
            dev_id, res = await _async_setup_single_device(
                hass, entry, "dev_err", "Room Err", None, None
            )
            assert dev_id == "dev_err"
            assert res is None
            ctrl.async_shutdown.assert_awaited_once()


async def test_async_setup_entry_single_device_success() -> None:
    """Test async_setup_entry single-device setup, SmartThings subdevice logic, and platform forwards."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    with (
        patch("custom_components.climate_ip.async_get_clientsession") as mock_session,
        patch("custom_components.climate_ip._build_device_setup_tasks") as mock_tasks,
    ):
        mock_session.return_value = "shared_session"
        coord_mock = MagicMock()
        mock_tasks.return_value = [
            AsyncMock(return_value=(MAIN_DEVICE_ID, coord_mock))()
        ]

        # 1. Regular non-SmartThings device with custom name
        entry_reg = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_DEVICE_TYPE: "samsung_2878",
                CONF_NAME: "Custom AC Name",
            },
            title="Fallback Title",
        )
        entry_reg.async_on_unload = MagicMock()
        entry_reg.add_update_listener = MagicMock(return_value=MagicMock())

        result = await async_setup_entry(hass, entry_reg)
        assert result is True
        assert type(result) is bool
        assert entry_reg.runtime_data == {MAIN_DEVICE_ID: coord_mock}
        hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            entry_reg, PLATFORMS
        )
        entry_reg.add_update_listener.assert_called_once_with(async_update_listener)
        entry_reg.async_on_unload.assert_called_once()

        devices_arg = mock_tasks.call_args[0][2]
        assert devices_arg == [
            {CONF_SUBDEVICE_ID: MAIN_DEVICE_ID, CONF_NAME: "Custom AC Name"}
        ]
        assert len(mock_tasks.call_args[0]) == 4
        assert mock_tasks.call_args[0][3] == "shared_session"

        # 2. SmartThings HVAC with CONF_DEVICE_ID and title fallback
        hass.config_entries.async_forward_entry_setups.reset_mock()
        mock_tasks.reset_mock()
        coord_st = MagicMock()
        mock_tasks.return_value = [AsyncMock(return_value=("st_sub_1", coord_st))()]

        entry_st = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
                CONF_DEVICE_ID: "  st_sub_1  ",
            },
            title="ST Living Room",
        )
        entry_st.async_on_unload = MagicMock()
        entry_st.add_update_listener = MagicMock(return_value=MagicMock())

        result_st = await async_setup_entry(hass, entry_st)
        assert result_st is True
        assert entry_st.runtime_data == {"st_sub_1": coord_st}
        devices_arg_st = mock_tasks.call_args[0][2]
        assert devices_arg_st == [
            {CONF_SUBDEVICE_ID: "st_sub_1", CONF_NAME: "ST Living Room"}
        ]

        # 3. SmartThings DHW with empty CONF_DEVICE_ID falls back to MAIN_DEVICE_ID
        mock_tasks.reset_mock()
        coord_dhw = MagicMock()
        mock_tasks.return_value = [
            AsyncMock(return_value=(MAIN_DEVICE_ID, coord_dhw))()
        ]

        entry_dhw = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_DHW,
                CONF_DEVICE_ID: "   ",
            },
            title="ST Boiler",
        )
        entry_dhw.async_on_unload = MagicMock()
        entry_dhw.add_update_listener = MagicMock(return_value=MagicMock())

        result_dhw = await async_setup_entry(hass, entry_dhw)
        assert result_dhw is True
        devices_arg_dhw = mock_tasks.call_args[0][2]
        assert devices_arg_dhw == [
            {CONF_SUBDEVICE_ID: MAIN_DEVICE_ID, CONF_NAME: "ST Boiler"}
        ]


async def test_async_setup_entry_multi_device_success() -> None:
    """Test async_setup_entry with multi-device configuration."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICES: [
                {CONF_SUBDEVICE_ID: "1", CONF_NAME: "Zone 1"},
                {CONF_SUBDEVICE_ID: "2", CONF_NAME: "Zone 2"},
            ]
        },
    )
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock(return_value=MagicMock())

    coord1 = MagicMock()
    coord2 = MagicMock()

    with (
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch(
            "custom_components.climate_ip._build_device_setup_tasks",
            return_value=[
                AsyncMock(return_value=("1", coord1))(),
                AsyncMock(return_value=("2", coord2))(),
            ],
        ),
    ):
        result = await async_setup_entry(hass, entry)
        assert result is True
        assert entry.runtime_data == {"1": coord1, "2": coord2}
        hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            entry, PLATFORMS
        )


async def test_async_setup_entry_options_override() -> None:
    """Test async_setup_entry prioritizes options over entry data for configuration keys."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: "samsung_2878",
            CONF_NAME: "Data Name",
            CONF_DEVICE_ID: "data_dev_id",
            CONF_DEVICES: [{"id": "data_sub"}],
        },
        options={
            CONF_DEVICE_TYPE: DEVICE_TYPE_SMARTTHINGS_HVAC,
            CONF_NAME: "Options Name",
            CONF_DEVICE_ID: "options_dev_id",
            CONF_DEVICES: [{CONF_SUBDEVICE_ID: "opt_sub", CONF_NAME: "Opt Zone"}],
        },
    )
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock(return_value=MagicMock())

    coord = MagicMock()
    with (
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch("custom_components.climate_ip._build_device_setup_tasks") as mock_tasks,
    ):
        mock_tasks.return_value = [AsyncMock(return_value=("opt_sub", coord))()]
        result = await async_setup_entry(hass, entry)
        assert result is True
        assert entry.runtime_data == {"opt_sub": coord}
        devices_arg = mock_tasks.call_args[0][2]
        assert devices_arg == [{CONF_SUBDEVICE_ID: "opt_sub", CONF_NAME: "Opt Zone"}]


async def test_async_setup_entry_rollback_on_sibling_failure() -> None:
    """Test rollback tears down booted sibling coordinators when a task raises fatal exception."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MockConfigEntry(domain=DOMAIN, title="Rollback AC", data={})

    coord_ok = MagicMock()

    # 1. ConfigEntryNotReady sibling failure triggers rollback shutdown with warning
    async def shutdown_side_effect(target):
        if target is coord_ok:
            raise RuntimeError("Safe shutdown error")

    with (
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch(
            "custom_components.climate_ip._build_device_setup_tasks",
            return_value=[
                AsyncMock(side_effect=ConfigEntryNotReady("Transient failure"))(),
                AsyncMock(return_value=("dev_ok", coord_ok))(),
                AsyncMock(side_effect=ConfigEntryNotReady("Second failure"))(),
            ],
        ),
        patch(
            "custom_components.climate_ip._async_safe_shutdown",
            side_effect=shutdown_side_effect,
        ) as mock_shutdown,
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)
        mock_shutdown.assert_awaited_once_with(coord_ok)

    # 2. Fatal non-ConfigEntryNotReady exception triggers rollback shutdown with error
    coord_ok2 = MagicMock()
    with (
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch(
            "custom_components.climate_ip._build_device_setup_tasks",
            return_value=[
                AsyncMock(side_effect=ConfigEntryAuthFailed("Fatal auth fail"))(),
                AsyncMock(return_value=("dev_ok2", coord_ok2))(),
            ],
        ),
        patch("custom_components.climate_ip._async_safe_shutdown") as mock_shutdown2,
    ):
        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, entry)
        mock_shutdown2.assert_awaited_once_with(coord_ok2)

    # 3. Single device failure with no coordinators booted raises fatal exception directly
    with (
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch(
            "custom_components.climate_ip._build_device_setup_tasks",
            return_value=[
                AsyncMock(side_effect=ConfigEntryNotReady("Direct failure"))()
            ],
        ),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)


async def test_async_setup_entry_no_coordinators_raises_not_ready() -> None:
    """Verify async_setup_entry raises ConfigEntryNotReady if no coordinators could be set up."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MockConfigEntry(domain=DOMAIN, title="Empty AC", data={})

    with (
        patch("custom_components.climate_ip.async_get_clientsession"),
        patch(
            "custom_components.climate_ip._build_device_setup_tasks",
            return_value=[
                AsyncMock(return_value=("dev1", None))(),
                AsyncMock(return_value=("dev2", None))(),
            ],
        ),
    ):
        with pytest.raises(ConfigEntryNotReady) as exc_info:
            await async_setup_entry(hass, entry)
        assert "No coordinators could be set up for entry Empty AC" in str(
            exc_info.value
        )


async def test_async_unload_entry_success() -> None:
    """Test successful unload shuts down coordinators, clears runtime_data, and clears cache."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    entry = MockConfigEntry(domain=DOMAIN, entry_id="entry_unload_1")
    coord1 = MagicMock()
    coord2 = MagicMock()
    entry.runtime_data = {"1": coord1, "2": coord2}

    # Only this entry exists -> YAML cache must be cleared
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    with (
        patch("custom_components.climate_ip._async_safe_shutdown") as mock_shutdown,
        patch("custom_components.climate_ip.clear_yaml_cache") as mock_clear,
    ):
        result = await async_unload_entry(hass, entry)
        assert result is True
        assert type(result) is bool
        hass.config_entries.async_unload_platforms.assert_awaited_once_with(
            entry, PLATFORMS
        )
        assert mock_shutdown.await_count == 2
        mock_shutdown.assert_has_awaits([call(coord1), call(coord2)], any_order=True)
        assert len(entry.runtime_data) == 0
        hass.config_entries.async_entries.assert_called_once_with(DOMAIN)
        mock_clear.assert_called_once_with()


async def test_async_unload_entry_other_active_entries_prevents_cache_clear() -> None:
    """Verify clear_yaml_cache is NOT called if other entries are loaded or in setup retry."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    entry = MockConfigEntry(domain=DOMAIN, entry_id="unloading_entry")
    entry.runtime_data = {}

    for active_state in [
        ConfigEntryState.LOADED,
        ConfigEntryState.SETUP_IN_PROGRESS,
        ConfigEntryState.SETUP_RETRY,
    ]:
        other_entry = MagicMock(
            entry_id=f"other_{active_state.name}",
            state=active_state,
        )

        def mock_entries(domain=None, _entry=entry, _other=other_entry):
            if domain == DOMAIN:
                return [_entry, _other]
            return []

        assert mock_entries("OTHER_DOMAIN") == []

        hass.config_entries.async_entries = MagicMock(side_effect=mock_entries)

        with (
            patch("custom_components.climate_ip._async_safe_shutdown"),
            patch("custom_components.climate_ip.clear_yaml_cache") as mock_clear,
        ):
            result = await async_unload_entry(hass, entry)
            assert result is True
            hass.config_entries.async_entries.assert_called_with(DOMAIN)
            mock_clear.assert_not_called()

    # Inactive state (e.g. NOT_LOADED) allows cache clear
    inactive_entry = MagicMock(
        entry_id="other_not_loaded",
        state=ConfigEntryState.NOT_LOADED,
    )

    def mock_inactive_entries(domain=None, _entry=entry, _inact=inactive_entry):
        if domain == DOMAIN:
            return [_entry, _inact]
        return []

    assert mock_inactive_entries("OTHER_DOMAIN") == []

    hass.config_entries.async_entries = MagicMock(side_effect=mock_inactive_entries)
    with (
        patch("custom_components.climate_ip._async_safe_shutdown"),
        patch("custom_components.climate_ip.clear_yaml_cache") as mock_clear,
    ):
        result = await async_unload_entry(hass, entry)
        assert result is True
        hass.config_entries.async_entries.assert_called_with(DOMAIN)
        mock_clear.assert_called_once_with()


async def test_async_unload_entry_platform_unload_failure_and_shutdown_exception() -> (
    None
):
    """Test platform unload failure aborts teardown, and coordinator shutdown error is caught."""
    hass = MagicMock(spec=HomeAssistant)

    # 1. Platform unload fails -> teardown aborted
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    entry_fail = MockConfigEntry(domain=DOMAIN, entry_id="fail_entry")
    coord_fail = MagicMock()
    entry_fail.runtime_data = {"dev1": coord_fail}

    with (
        patch("custom_components.climate_ip._async_safe_shutdown") as mock_shutdown,
        patch("custom_components.climate_ip.clear_yaml_cache") as mock_clear,
    ):
        result = await async_unload_entry(hass, entry_fail)
        assert result is False
        assert type(result) is bool
        mock_shutdown.assert_not_awaited()
        assert "dev1" in entry_fail.runtime_data
        mock_clear.assert_not_called()

    # 2. Shutdown exception is caught and logged, teardown completes
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    entry_err = MockConfigEntry(domain=DOMAIN, entry_id="err_entry")
    coord_err = MagicMock()
    entry_err.runtime_data = {"dev1": coord_err}
    hass.config_entries.async_entries = MagicMock(return_value=[entry_err])

    with (
        patch(
            "custom_components.climate_ip._async_safe_shutdown",
            side_effect=RuntimeError("Shutdown failure"),
        ),
        patch("custom_components.climate_ip.clear_yaml_cache") as mock_clear,
    ):
        result_err = await async_unload_entry(hass, entry_err)
        assert result_err is True
        assert len(entry_err.runtime_data) == 0
        mock_clear.assert_called_once_with()
