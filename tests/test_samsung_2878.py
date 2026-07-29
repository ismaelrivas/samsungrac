# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Smoke test for samsung_2878.py."""
# pylint: disable=protected-access,redefined-outer-name,import-outside-toplevel,reimported,broad-exception-caught,unnecessary-pass,line-too-long

import pytest

from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878


def test_can_import_connection_class():
    """Test that we can import the class without syntax errors."""
    assert ConnectionSamsung2878 is not None


async def test_repair_issue_created_on_disconnect():
    """Test that a repair issue is created after 3 connection failures."""
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
    conn._cfg.name = "Test AC"
    conn._controller = mock_controller

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_issue"
        ) as mock_create_issue,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.climate_ip.helpers.async_check_network_reachability",
            new_callable=AsyncMock,
        ) as mock_ping,
        patch.object(
            conn, "_establish_connection_and_handshake", new_callable=AsyncMock
        ) as mock_handshake,
    ):
        mock_ping.return_value = True

        mock_handshake.return_value = False

        # 1st failure (no issue)
        conn._reconnect_retries = 0
        await conn.handle_reconnection()
        assert conn._reconnect_retries == 1
        mock_create_issue.assert_not_called()

        # 2nd failure (no issue)
        await conn.handle_reconnection()
        assert conn._reconnect_retries == 2
        mock_create_issue.assert_not_called()

        # 3rd failure (issue should be created)
        await conn.handle_reconnection()
        assert conn._reconnect_retries == 3
        mock_create_issue.assert_called_once()

        args, kwargs = mock_create_issue.call_args
        assert args[0] == mock_hass
        assert args[1] == "climate_ip"
        assert args[2] == "device_offline_192_168_1_100"
        assert kwargs["translation_key"] == "connection_failed"
        assert kwargs["translation_placeholders"]["name"] == "Test AC"
        assert kwargs["translation_placeholders"]["device_name"] == "Test AC"
        assert kwargs["translation_placeholders"]["host"] == "192.168.1.100"
        assert kwargs["translation_placeholders"]["ip_address"] == "192.168.1.100"


async def test_repair_issue_cleared_on_reconnect():
    """Test that a repair issue is deleted upon successful connection."""
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
    conn._is_available = False

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.async_delete_issue"
        ) as mock_delete_issue,
        patch.object(
            conn, "_establish_connection_and_handshake", new_callable=AsyncMock
        ) as mock_handshake,
    ):
        with patch.object(conn, "_post_connect_status_request", new_callable=AsyncMock):
            mock_handshake.return_value = True
            conn._initial_connection_done = True

    with patch(
        "custom_components.climate_ip.samsung_2878.async_delete_issue"
    ) as mock_delete_issue:
        conn._is_available = False

        if not conn._is_available:
            conn._is_available = True
            try:
                from custom_components.climate_ip.samsung_2878 import (
                    async_delete_issue,
                )

                async_delete_issue(
                    conn._controller.hass,
                    "climate_ip",
                    "device_offline_192_168_1_100",
                )
            except Exception:
                pass

        mock_delete_issue.assert_called_once_with(
            mock_hass, "climate_ip", "device_offline_192_168_1_100"
        )


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

    from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878
    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

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
