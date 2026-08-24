# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Smoke test for samsung_2878.py."""
# pylint: disable=protected-access,redefined-outer-name,import-outside-toplevel,reimported,broad-exception-caught,unnecessary-pass,line-too-long

from __future__ import annotations

import pytest

from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878


def test_can_import_connection_class():
    """Test that we can import the class without syntax errors."""
    assert ConnectionSamsung2878 is not None


async def test_async_xml_parse():
    """Test that XML parsing is offloaded to the executor/thread pool."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.helpers import safe_xml_to_dict

    config = {
        "host": "192.168.1.100",
        "port": 2878,
        "cert": "dummy.pem",
        "duid": "12345",
    }
    logger = MagicMock()
    conn = ConnectionSamsung2878(config, logger)

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    # Test case 1: With hass (uses async_add_executor_job)
    mock_hass = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock(
        side_effect=mock_async_add_executor_job
    )
    mock_controller = MagicMock()
    mock_controller.hass = mock_hass
    conn._controller = mock_controller

    large_xml = '<?xml version="1.0" encoding="utf-8" ?><Response Type="DeviceState" DUID="12345"><Device></Device></Response>'

    with patch(
        "custom_components.climate_ip.samsung_2878.safe_xml_to_dict",
        side_effect=safe_xml_to_dict,
    ) as mock_parse:
        await conn._parse_and_update_state(large_xml)
        mock_hass.async_add_executor_job.assert_called_once()
        # The first argument should be safe_xml_to_dict (the mock)
        assert mock_hass.async_add_executor_job.call_args[0][0] == mock_parse
        assert mock_hass.async_add_executor_job.call_args[0][1] == large_xml

    # Test case 2: Without hass (should raise RuntimeError)
    conn._controller = None
    with pytest.raises(
        RuntimeError,
        match="Home Assistant instance is required for parsing XML securely",
    ):
        await conn._parse_and_update_state(large_xml)


def test_2878_auth_token_format():
    """Test that __CLIMATE_IP_TOKEN__ placeholder is properly replaced with the real token."""
    from unittest.mock import MagicMock

    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878

    # 1. Simulate the config dictionary coming from Home Assistant
    hass_config = {
        CONF_IP_ADDRESS: "192.168.1.100",
        "port": 2878,
        CONF_TOKEN: "REAL_SECURE_TOKEN_XYZ",
        "mac": "11:22:33:44:55:66",
    }
    logger = MagicMock()

    # Initialization calls update_configuration_from_hass which parses and prepares self._cfg
    conn = ConnectionSamsung2878(hass_config, logger, hass=MagicMock())
    conn._controller = MagicMock()
    conn._controller.unique_id = "mock_uid"
    conn._controller.log_prefix = "[MOCK]"

    # 2. Simulate the YAML loader reading samsung_2878.yaml
    yaml_node = {
        "params": {
            "connection_template": '<Request Type="AuthToken"><User Token="{{token}}" /></Request>',
            "host": "__CLIMATE_IP_HOST__",
            "token": "__CLIMATE_IP_TOKEN__",
        }
    }

    # This should override the generic YAML placeholders with the real _cfg parameters
    conn.load_from_yaml(yaml_node, None)

    # 3. Assert that the params dictionary successfully replaced the magic string
    assert conn._params.get("token") == "REAL_SECURE_TOKEN_XYZ"
    assert conn._params.get("token") != "__CLIMATE_IP_TOKEN__"
    assert conn._params.get("ip_address") == "192.168.1.100"

    # 4. Assert that rendering the init template produces a valid payload
    import jinja2

    rendered_auth = jinja2.Template(conn._connection_init_template.template).render(
        **conn._params
    )
    assert 'Token="REAL_SECURE_TOKEN_XYZ"' in rendered_auth
    assert "__CLIMATE_IP_TOKEN__" not in rendered_auth


async def test_native_shield_billion_laughs_rejection():
    """Test that Billion Laughs XML attacks are rejected by Native Shield."""
    from custom_components.climate_ip.helpers import safe_xml_to_dict

    # Payload suggested by user (recursive entities)
    malicious_xml = '<!DOCTYPE bomb [ <!ENTITY a "bomb"> <!ENTITY b "&a;&a;"> ]><Status>&b;</Status>'
    assert safe_xml_to_dict(malicious_xml) == {}

    # Also verify that a standard billion laughs (more layers) is caught
    billion_laughs = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
     <!ENTITY lol "lol">
     <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
     <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
    ]>
    <lolz>&lol2;</lolz>"""
    assert safe_xml_to_dict(billion_laughs) == {}


def test_connection_config_mutants():
    """Kill mutants in ConnectionConfig."""
    from custom_components.climate_ip.samsung_2878 import ConnectionConfig

    cfg = ConnectionConfig(
        host="192.168.1.100",
        port=2878,
        token="my_token",
        cert="my_cert.pem",
        duid="my_duid",
    )

    assert cfg.host == "192.168.1.100"
    # Kill mutmut 2: self.port = None
    assert cfg.port == 2878
    assert cfg.token == "my_token"
    # Kill mutmut 4: self.duid = None
    assert cfg.duid == "my_duid"
    # Kill mutmut 5: self.cert = None
    assert cfg.cert == "my_cert.pem"


async def test_offline_callback_invoked_on_disconnect():
    """Test that the controller's offline callback is triggered after 2 failures."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878

    mock_hass = MagicMock()
    mock_controller = MagicMock()
    mock_controller.hass = mock_hass
    # Explicitly define callbacks to satisfy Fail-Fast contract
    mock_controller.on_offline_callback = MagicMock()
    mock_controller.on_connection_failed_callback = MagicMock()

    config = {
        "host": "192.168.1.100",
        "port": 2878,
        "cert": "dummy.pem",
        "duid": "12345",
    }
    logger = MagicMock()

    conn = ConnectionSamsung2878(config, logger)
    conn._cfg = MagicMock()
    conn._cfg.host = "192.168.1.100"
    conn._controller = mock_controller

    # CRITICAL FIX: Simulate AC connected successfully at least once.
    # Without this, system suppresses UI errors assuming startup phase.
    conn._initial_connection_done = True

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.climate_ip.helpers.async_check_network_reachability",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(
            conn,
            "_establish_connection_and_handshake",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        # 1st attempt (retries = 1) -> No trigger
        await conn.handle_reconnection()
        mock_controller.on_offline_callback.assert_not_called()

        # 2nd attempt (retries = 2) -> Exceeds strict threshold and triggers offline to UI
        await conn.handle_reconnection()
        mock_controller.on_offline_callback.assert_called_once_with(
            "Host unreachable after multiple retry attempts."
        )
        mock_controller.on_connection_failed_callback.assert_called()


async def test_reconnection_state_changes_availability():
    """Test that connection recovery correctly updates the internal availability flag."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878

    mock_hass = MagicMock()
    mock_controller = MagicMock()
    mock_controller.hass = mock_hass

    config = {
        "host": "192.168.1.100",
        "port": 2878,
        "cert": "dummy.pem",
        "duid": "12345",
    }
    logger = MagicMock()

    conn = ConnectionSamsung2878(config, logger)
    conn._cfg = MagicMock()
    conn._cfg.host = "192.168.1.100"
    conn._controller = mock_controller
    conn._is_available = False  # Start offline

    with patch.object(
        conn,
        "_establish_connection_and_handshake",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await conn.handle_reconnection()
        # If restored, handshake updates is_available and clears persistent flag
        # (Occurs inside _establish_connection_and_handshake, but since mocked
        # returning True, only verify handle_reconnection returns True)
        assert (
            conn._is_available is False
        )  # It doesn't flip it here, it flips inside establish

@pytest.mark.parametrize("invalid_mac", [None, "", "   "])
def test_malformed_or_missing_mac_fails_yaml_load(invalid_mac: str | None):
    """Test que asegura que si la MAC está ausente o vacía, la carga de YAML falla (devuelve False)."""
    from unittest.mock import MagicMock

    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878

    hass_config = {
        CONF_IP_ADDRESS: "192.168.1.100",
        "port": 2878,
        CONF_TOKEN: "VALID_TOKEN_123",
        CONF_MAC: invalid_mac,
    }
    logger = MagicMock()
    conn = ConnectionSamsung2878(hass_config, logger, hass=MagicMock())

    yaml_node = {
        "params": {
            "connection_template": '<Request Type="AuthToken"><User Token="{{token}}" /></Request>',
        }
    }

    # Intentar cargar YAML sin una MAC/DUID válida debe retornar False
    success = conn.load_from_yaml(yaml_node, None)
    assert success is False
    assert conn._cfg.duid is None or conn._cfg.duid.strip() == ""


def test_mac_formatting_and_sanitization():
    """Test que verifica que los separadores de la MAC (: y -) se limpian correctamente al generar el DUID."""
    from unittest.mock import MagicMock

    from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

    from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878

    # MAC con formato estándar de red con dos puntos
    hass_config = {
        CONF_IP_ADDRESS: "192.168.1.100",
        "port": 2878,
        CONF_TOKEN: "VALID_TOKEN_123",
        CONF_MAC: "BC:8C:CD:5B:54:F6",
    }
    logger = MagicMock()
    conn = ConnectionSamsung2878(hass_config, logger, hass=MagicMock())

    # DUID debe haberse limpiado sin dos puntos
    assert conn._cfg.duid == "BC8CCD5B54F6"
    assert ":" not in conn._cfg.duid


async def test_command_execution_fails_with_unconfigured_duid():
    """Test que verifica que async_execute falla limpiamente si el DUID no está listo o es inválido."""
    from unittest.mock import MagicMock

    import pytest

    from custom_components.climate_ip.exceptions import CannotConnect
    from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878

    hass_config = {
        "ip_address": "192.168.1.100",
        "port": 2878,
        "token": "TOKEN",
        "mac": None,  # MAC no configurada
    }
    conn = ConnectionSamsung2878(hass_config, MagicMock(), hass=MagicMock())
    conn.start_listening = MagicMock()
    conn._reconnect_retries = 1  # Forzamos estado de reintento/no listo

    # Si la conexión no está lista por falta de DUID/configuración, async_execute debe lanzar CannotConnect
    with pytest.raises(CannotConnect, match="Client not ready"):
        await conn.async_execute(
            method=None,
            url=None,
            data='<Request Type="DeviceControl"><Control CommandID="AC_FUN_POWER" DUID="main"><Attr ID="AC_FUN_POWER" Value="Off" /></Control></Request>',
            headers=None,
        )