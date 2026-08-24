from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.issue_registry import IssueSeverity
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import CannotConnect


# =====================================================================
# UTILITY HELPERS FOR YAML POLLING TESTS
# =====================================================================
class NakedObj:
    """Sterile object without mock overhead to prevent side-effects."""

    def __init__(self, **kwargs):
        self.debug = False
        self.name = "TestName"
        self.ip_address = "1.2.3.4"
        self.available = True
        self.device_id = "XXXX"
        self.hass = __import__("unittest.mock").mock.MagicMock()
        self.__dict__.update(kwargs)


class DummyController(NakedObj):
    """Simulated controller resistant to AttributeErrors."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Prevention of common AttributeErrors in poller
        if not hasattr(self, "config"):
            self.config = {}
        if not hasattr(self, "log_prefix"):
            self.log_prefix = "TEST"
        if not hasattr(self, "ip_address"):
            self.ip_address = "127.0.0.1"
        if not hasattr(self, "loader"):
            self.loader = create_valid_loader()


def create_valid_loader():
    """Crea un loader mínimo para evadir validaciones tempranas."""
    from unittest.mock import MagicMock

    loader = MagicMock()
    loader.is_fully_initialized = True
    loader.operations = {}
    loader.properties = {}
    loader.sensors = {}
    loader.state_getter = NakedObj(value={})
    from unittest.mock import AsyncMock

    loader.state_getter.async_update_state = AsyncMock()
    return loader


# =====================================================================


@patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.info")
@patch("custom_components.climate_ip.controller_yaml_polling.async_create_issue")
def test_try_create_repair_issue_flow(mock_async_create_issue, mock_logger_info):
    """Test control flow and parameters of _try_create_repair_issue."""
    mock_controller = MagicMock()
    mock_controller.hass = MagicMock()
    mock_controller.config = {"name": "Test AC"}
    mock_controller.unique_id = "192.168.1.100"
    mock_controller.ip_address = "192.168.1.100"
    mock_controller.name = "Test AC"

    poller = YamlStatePoller(mock_controller)

    # Call with hass object available
    poller._try_create_repair_issue()
    assert mock_async_create_issue.called
    assert mock_async_create_issue.call_count == 1
    mock_async_create_issue.assert_called_once_with(
        mock_controller.hass,
        "climate_ip",
        "device_offline_192_168_1_100",
        is_fixable=False,
        is_persistent=False,
        severity=IssueSeverity.WARNING,
        translation_key="connection_failed",
        translation_placeholders={
            "device_name": "Test AC",
            "host": "192.168.1.100",
            "ip_address": "192.168.1.100",
        },
    )
    mock_logger_info.assert_called_once_with(
        "%s Created repair issue 'device_offline_%s' for %s (%s)",
        mock_controller.log_prefix,
        "192_168_1_100",
        "Test AC",
        "192.168.1.100",
    )

    # Call without hass object
    mock_async_create_issue.reset_mock()
    mock_logger_info.reset_mock()
    poller.controller = MagicMock()
    poller.controller.hass = None
    poller._try_create_repair_issue()
    assert not mock_async_create_issue.called
    assert not mock_logger_info.called


@pytest.mark.parametrize(
    "unique_id, name, host, ip_address, expected_issue_id, expected_device_name_ph, expected_ip_address_ph",
    [
        (
            None,
            None,
            "192.168.1.10",
            "10.0.0.10",
            "device_offline_192_168_1_10",
            "Samsung AC 192.168.1.10",
            "10.0.0.10",
        ),
        (
            None,
            None,
            None,
            "10.0.0.10",
            "device_offline_10_0_0_10",
            "Samsung AC 10.0.0.10",
            "10.0.0.10",
        ),
        (
            None,
            None,
            None,
            None,
            "device_offline_unknown",
            "Samsung AC unknown",
            "Unknown",
        ),
        (
            "my_device_1",
            "Living Room",
            None,
            "10.0.0.10",
            "device_offline_my_device_1",
            "Living Room",
            "10.0.0.10",
        ),
        (
            None,
            "Bed Room",
            None,
            "10.0.0.10",
            "device_offline_10_0_0_10",
            "Bed Room",
            "10.0.0.10",
        ),
    ],
)
@patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.info")
@patch("custom_components.climate_ip.controller_yaml_polling.async_create_issue")
def test_try_create_repair_issue_fallback_cascade(
    mock_create_issue,
    mock_logger_info,
    unique_id,
    name,
    host,
    ip_address,
    expected_issue_id,
    expected_device_name_ph,
    expected_ip_address_ph,
):
    """Sniper: Test fallback cascade for raw_id, device_name, and ip_address translation placeholders in async_create_issue."""
    mock_controller = MagicMock()
    mock_controller.hass = MagicMock()
    mock_controller.config = {"name": name} if name else {}
    mock_controller.unique_id = unique_id
    mock_controller.name = name
    mock_controller.host = host
    mock_controller.ip_address = ip_address

    poller = YamlStatePoller(mock_controller)
    poller._try_create_repair_issue()

    mock_create_issue.assert_called_once_with(
        mock_controller.hass,
        "climate_ip",
        expected_issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=IssueSeverity.WARNING,
        translation_key="connection_failed",
        translation_placeholders={
            "device_name": expected_device_name_ph,
            "host": expected_ip_address_ph,
            "ip_address": expected_ip_address_ph,
        },
    )
    expected_safe_id = expected_issue_id.replace("device_offline_", "")
    mock_logger_info.assert_called_once_with(
        "%s Created repair issue 'device_offline_%s' for %s (%s)",
        mock_controller.log_prefix,
        expected_safe_id,
        name or "Climate IP",
        expected_ip_address_ph,
    )


@pytest.mark.parametrize(
    "unique_id, host, ip_address, expected_issue_id",
    [
        (None, "192.168.1.10", "10.0.0.10", "device_offline_192_168_1_10"),
        (None, None, "10.0.0.10", "device_offline_10_0_0_10"),
        (None, None, None, "device_offline_unknown"),
        ("my_device_1", None, "10.0.0.10", "device_offline_my_device_1"),
    ],
)
async def test_async_delete_issue_fallback_cascade(
    unique_id, host, ip_address, expected_issue_id
):
    """Sniper: Test fallback cascade for raw_id in async_delete_issue when connection recovers."""
    mock_controller = MagicMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = unique_id
    mock_controller.host = host
    mock_controller.ip_address = ip_address

    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"power": "on"}
    )
    mock_controller.loader.state_getter.value = {"power": "on"}

    poller = YamlStatePoller(mock_controller)
    poller._consecutive_connection_errors = 1
    poller.async_update_properties_from_state = AsyncMock()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
    ) as mock_delete_issue:
        await poller.async_update_state()
        mock_delete_issue.assert_called_once_with(
            mock_controller.hass, "climate_ip", expected_issue_id
        )


async def test_async_update_state_early_exits_and_ping():
    """Asserts that missing getter or ping failure aborts the network request."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # 1. No state_getter (Kills mutants in `if not self.controller.loader.state_getter`)
    poller.controller.loader = MagicMock()
    poller.controller.loader.state_getter = None
    assert await poller.async_update_state() is None

    # 2. Failed ICMP ping for non-2878 devices
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.config.get.return_value = (
        "rest_api"  # Falsa la guardia de DEVICE_TYPE_SAMSUNG_2878
    )
    mock_controller.ip_address = "192.168.1.100"
    poller._consecutive_connection_errors = 2

    # Simulate network unreachable
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        return_value=False,
    ) as mock_ping:
        with pytest.raises(
            UpdateFailed,
            match=r"Device unreachable: Host unreachable \(ICMP ping failed\)",
        ):
            await poller.async_update_state()

        # Assertions strictly on pre-check (Network Front)
        mock_controller.config.get.assert_any_call("device_type")
        mock_ping.assert_called_once_with("192.168.1.100", mock_controller.log_prefix)

        # Kills mutants in counter math (e.g. += 2 instead of += 1)
        assert poller._consecutive_connection_errors == 3

    # 3. Reachability short-circuit due to ip_address = None (Kills mutant and -> or)
    mock_controller.ip_address = None
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        return_value=False,
    ) as mock_ping_none:
        # Simulate state_getter failure to test early return with None
        mock_controller.loader.state_getter.async_update_state.return_value = None
        with pytest.raises(UpdateFailed):
            await poller.async_update_state()
        mock_ping_none.assert_not_called()


async def test_async_update_state_network_failures_and_cache():
    """Valida que un CannotConnect devuelve la caché interna si los reintentos son <= 2."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # Bypass ping to go straight to network
    mock_controller.config.get.return_value = "samsung_2878"
    mock_controller.loader.state_getter = AsyncMock()

    # Mock remaining dependencies to prevent noise
    poller.async_update_properties_from_state = AsyncMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False

    # Simulate valid cache from previous state already present
    poller._cached_device_state = {"power": "on"}
    poller._consecutive_connection_errors = 0

    # Inject a connection exception
    mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect(
        "Timeout HTTP"
    )

    result = await poller.async_update_state()

    # We assert it didn't explode and returned rescued state
    assert result == {"power": "on"}
    # We assert error counter increased in `else` branch
    assert poller._consecutive_connection_errors == 1

    # Inject fatal limit (3 errors)
    poller._consecutive_connection_errors = 2
    poller._try_create_repair_issue = MagicMock()

    with pytest.raises(UpdateFailed, match="Device unreachable: Timeout HTTP"):
        await poller.async_update_state()

    # We assert it attempted to create issue upon reaching 3
    poller._try_create_repair_issue.assert_called_once()

    # Validate Issue resolution (When connection recovers)
    poller._consecutive_connection_errors = 1
    mock_controller.loader.state_getter.async_update_state.side_effect = None
    mock_controller.loader.state_getter.async_update_state.return_value = {
        "power": "on"
    }
    mock_controller.loader.state_getter.value = {"power": "on"}
    mock_controller.ip_address = "192.168.1.100"
    mock_controller.unique_id = "192.168.1.100"

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
    ) as mock_delete_issue:
        await poller.async_update_state()
        # Strict verification that the issue was deleted with correct parameters
        mock_delete_issue.assert_called_once_with(
            mock_controller.hass, "climate_ip", "device_offline_192_168_1_100"
        )


async def test_async_update_state_persistently_offline():
    """Verifica que el error 'persistently offline' asigna exactamente 2 al contador."""
    from unittest.mock import MagicMock

    import pytest
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from custom_components.climate_ip.exceptions import CannotConnect

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.config.get.return_value = "REST_API"

    # 1. "persistently offline" failure (Kills mutants in `if "persistently offline" in str(e)`)
    mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect(
        "Host unreachable (ICMP ping failed). Device is persistently offline."
    )

    with pytest.raises(UpdateFailed):
        await poller.async_update_state()

    assert poller._consecutive_connection_errors == 2

    # 2. Generic network failure (Must add 1, instead of setting to 2)
    poller._consecutive_connection_errors = 0
    mock_controller.loader.state_getter.async_update_state.side_effect = CannotConnect(
        "Timeout"
    )

    with pytest.raises(UpdateFailed):
        await poller.async_update_state()

    assert poller._consecutive_connection_errors == 1


@patch("custom_components.climate_ip.controller_yaml_polling.async_create_issue")
def test_try_create_repair_issue_exception_handling(mock_create_issue):
    """Test that _try_create_repair_issue handles exceptions silently and gracefully."""
    mock_controller = MagicMock()
    mock_controller.hass = MagicMock()

    # 1. Simulate an exception in the core HA component
    mock_create_issue.side_effect = Exception("Simulated Core Drop")

    poller = YamlStatePoller(mock_controller)

    # This should not raise an exception
    poller._try_create_repair_issue()

    # Verify the exception was swallowed and flow continued
    assert mock_create_issue.called


async def test_async_shutdown():
    """Test that shutdown closes connections cleanly."""
    mock_controller = MagicMock()
    mock_connection = AsyncMock()
    mock_controller.loader.connection = mock_connection

    poller = YamlStatePoller(mock_controller)

    await poller.async_shutdown()

    # The connection should have been told to close
    mock_connection.close.assert_called_once()


@patch(
    "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
    new_callable=AsyncMock,
)
async def test_async_update_state_network_failures_thresholds(mock_reachability):
    """Test the thresholds for consecutive network failures."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = "192.168.1.100"
    mock_controller.loader.state_getter.async_update_state = AsyncMock()
    poller = YamlStatePoller(mock_controller)
    poller._try_create_repair_issue = MagicMock()

    mock_reachability.return_value = False

    # 1st failure -> Exception, issue NOT created
    with pytest.raises(UpdateFailed, match="Device unreachable"):
        await poller.async_update_state()
    assert poller._consecutive_connection_errors == 1
    poller._try_create_repair_issue.assert_not_called()

    # 2nd failure -> Exception (persistently offline)
    with pytest.raises(UpdateFailed, match="Device unreachable"):
        await poller.async_update_state()
    assert poller._consecutive_connection_errors == 2
    poller._try_create_repair_issue.assert_not_called()

    # 3rd failure -> Exception (persistently offline) + creates issue
    with pytest.raises(UpdateFailed, match="Device unreachable"):
        await poller.async_update_state()
    assert poller._consecutive_connection_errors == 3
    poller._try_create_repair_issue.assert_called_once()

    # Recovery on 4th call!
    mock_reachability.return_value = True
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"recovered": True}
    )
    poller.controller.loader.state_getter.value = {"recovered": True}

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
    ) as mock_del:
        res = await poller.async_update_state()
        assert res == {"recovered": True}
        assert poller._consecutive_connection_errors == 0
        mock_del.assert_called_once()


@patch(
    "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
    new_callable=AsyncMock,
)
async def test_async_update_state_network_diagnostics_exceptions(mock_reachability):
    """Test when reachability throws non-CannotConnect exceptions."""
    mock_controller = MagicMock()
    mock_controller.config = {"device_type": "some_rest"}
    mock_controller.ip_address = "192.168.1.100"
    poller = YamlStatePoller(mock_controller)

    # Reachability throws a ValueError
    mock_reachability.side_effect = ValueError("Some weird DNS error")

    # The error should be swallowed and we attempt to poll anyway!
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"polled": True}
    )
    poller.controller.loader.state_getter.value = {"polled": True}
    res = await poller.async_update_state()
    assert res == {"polled": True}


async def test_async_shutdown_no_connection():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    mock_controller.loader.connection = None

    # Should not throw, should just sleep and return
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        await poller.async_shutdown()
        mock_sleep.assert_called_once_with(1.0)


async def test_async_shutdown_stop_listening_exception():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    conn = MagicMock()
    conn.stop_listening = AsyncMock(side_effect=ValueError("Boom"))
    mock_controller.loader.connection = conn

    # Bypass the others
    del conn.close

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await poller.async_shutdown()  # Should not raise
    conn.stop_listening.assert_called_once()
    assert mock_controller.loader.connection is None


async def test_async_shutdown_conn_close():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    conn = MagicMock()
    del conn.stop_listening
    conn.close = AsyncMock(side_effect=ValueError("Boom"))
    mock_controller.loader.connection = conn

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await poller.async_shutdown()  # Should not raise
    conn.close.assert_called_once()
    assert mock_controller.loader.connection is None


async def test_update_state_repair_issue_delete_exception():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"a": 1}
    )
    mock_controller.loader.state_getter.value = {"a": 1}
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.discovered_devices = [{"id": "dev1"}]

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue",
        side_effect=Exception("Boom"),
    ):
        res = await poller.async_update_state()
    assert res == {"a": 1}


async def test_update_state_invalid_header_error():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    from custom_components.climate_ip.exceptions import InvalidHeaderError

    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=InvalidHeaderError("Bad header")
    )
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.discovered_devices = [{"id": "dev1"}]

    with pytest.raises(InvalidHeaderError):
        await poller.async_update_state()


async def test_update_state_api_error_cached_fallback():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter = AsyncMock()
    from custom_components.climate_ip.exceptions import CannotConnect

    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=CannotConnect("API Failure")
    )
    mock_controller.loader.state_getter.value = {"cached": True}
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.discovered_devices = [{"id": "dev1"}]

    # With cache
    poller._cached_device_state = {"cached": True}
    res = await poller.async_update_state()
    assert res == {"cached": True}

    # Without cache -> raises UpdateFailed
    poller._cached_device_state = None
    from homeassistant.helpers.update_coordinator import UpdateFailed

    with pytest.raises(UpdateFailed):
        await poller.async_update_state()


async def test_update_state_delete_issue_exception():
    """L260-261: Captura de excepción en async_delete_issue."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.ip_address = "1.2.3.4"
    mock_controller.hass = MagicMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"a": 1}
    )

    poller = YamlStatePoller(mock_controller)
    poller._consecutive_connection_errors = 1
    poller._build_device_state_from_hass = AsyncMock(return_value={"a": 1})
    poller.async_update_properties_from_state = AsyncMock()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue",
        side_effect=Exception("Test Error"),
    ):
        # No debe crashear
        await poller.async_update_state()


async def test_async_update_state_sniper_network_ping():
    """Sniper: Dispositivos REST fallan temprano y generan repair issue en el umbral."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = DummyController(ip_address="192.168.1.100")
    mock_controller.config = {"device_type": "REST"}

    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    poller._consecutive_connection_errors = 2
    poller._cached_device_state = {"a": 1}

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        new_callable=AsyncMock,
    ) as mock_ping:
        mock_ping.return_value = False

        # Wrap the ENTIRE sequence in the repair patch
        with patch.object(poller, "_try_create_repair_issue") as mock_repair:
            # 1. First Ping Failure (Counter goes 2 -> 3)
            with pytest.raises(
                UpdateFailed,
                match=r"Device unreachable: Host unreachable \(ICMP ping failed\)",
            ):
                await poller.async_update_state()

            mock_ping.assert_called_with("192.168.1.100", mock_controller.log_prefix)
            assert poller._consecutive_connection_errors == 3
            mock_repair.assert_called_once()  # Issue generated EXACTLY at 3

            # 2. Second Ping Failure (Counter goes 3 -> 4)
            mock_ping.reset_mock()
            with pytest.raises(
                UpdateFailed,
                match=r"Device unreachable: Host unreachable \(ICMP ping failed\)",
            ):
                await poller.async_update_state()

            assert poller._consecutive_connection_errors == 4
            mock_repair.assert_called_once()  # Remains at 1, no duplicate issues generated

        # 3. Ping raises exception but captured as diagnostic, delegating later to state_getter
        mock_ping.side_effect = Exception("Ping error")
        mock_controller.loader.state_getter.async_update_state.return_value = {
            "state": "ping_failed_but_recovered"
        }
        mock_controller.loader.state_getter.value = {
            "state": "ping_failed_but_recovered"
        }

        res = await poller.async_update_state()
        assert res == {"state": "ping_failed_but_recovered"}


@patch("custom_components.climate_ip.controller_yaml_polling.async_create_issue")
def test_try_create_repair_issue_missing_hass(mock_create_issue):
    """Verify early exit when self.controller.hass is None."""
    mock_controller = MagicMock()
    mock_controller.hass = None
    poller = YamlStatePoller(mock_controller)
    poller._try_create_repair_issue()
    mock_create_issue.assert_not_called()


async def test_async_update_state_force_connection_errors():
    """Kills mutants de rsplit/split y validación de UpdateFailed."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.config = {"device_type": "Other"}

    # Mock getter
    poller.controller.loader.state_getter = AsyncMock()

    # Inject CannotConnect. El poller debe capturarlo y relanzar UpdateFailed
    poller.controller.loader.state_getter.async_update_state.side_effect = (
        CannotConnect("Prefix:TargetReason")
    )
    poller._consecutive_connection_errors = 2
    poller._cached_device_state = None

    with pytest.raises(UpdateFailed) as exc:
        await poller.async_update_state()

    assert str(exc.value) == "Device unreachable: TargetReason"
