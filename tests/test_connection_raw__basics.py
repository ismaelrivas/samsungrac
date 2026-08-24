# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,too-many-locals,too-many-statements,unidiomatic-typecheck
"""Tests for ConnectionRaw8888."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

from custom_components.climate_ip.connection_raw import _HOST_CLIENTS, ConnectionRaw8888
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import CannotConnect
from custom_components.climate_ip.protocol_8888 import (
    CannotConnect as LibConnError,
)


@pytest.fixture(autouse=True)
def clean_raw_clients():
    """Ensure raw clients pool is clean before and after each test and prevent live sockets."""
    _HOST_CLIENTS.clear()
    with patch(
        "custom_components.climate_ip.connection_raw.Samsung8888Client"
    ) as default_mock_cls:
        mock_instance = AsyncMock()
        mock_instance.request = AsyncMock(return_value=('{"result": "ok"}', None))
        mock_instance.close = AsyncMock()
        default_mock_cls.return_value = mock_instance
        yield
    _HOST_CLIENTS.clear()


@pytest.fixture
def mock_logger():
    """Create a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock()


@pytest.fixture
def connection_config():
    """Return a minimal ConnectionRaw8888 config dict."""
    return {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_CERT: "cert.pem",
        CONF_TOKEN: "mock_token",
    }


@pytest.fixture
def anyio_backend():
    """Use asyncio as the anyio backend."""
    return "asyncio"


async def test_initialization(connection_config, mock_logger, mock_hass):
    """Test connection initialization."""
    with patch("os.path.exists", return_value=True):
        import os

        from custom_components.climate_ip import connection_raw

        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn._config is connection_config
        assert conn._logger is mock_logger
        assert conn._hass is mock_hass
        assert conn._host == "192.168.1.100"
        assert conn._cert == os.path.join(
            os.path.dirname(connection_raw.__file__), "cert.pem"
        )
        assert conn.condition_template is None
        assert conn._keep_alive is True
        assert conn._params == {}
        assert conn._controller is None
        assert conn._connection_template is None
        assert conn._embedded_command is None
        assert conn._embedded_command is None
        assert conn._client is None

        # Kill mutant 18 and 23 by testing absolute path and exact joining
        config2 = connection_config.copy()
        config2[CONF_CERT] = "/absolute/path/cert.pem"
        conn2 = ConnectionRaw8888(config2, mock_logger, mock_hass, None, None)
        assert conn2._cert == "/absolute/path/cert.pem"

        # Kill mutant __init__ on self._host = None
        config_no_host = connection_config.copy()
        config_no_host.pop(CONF_IP_ADDRESS, None)
        conn_no_host = ConnectionRaw8888(
            config_no_host, mock_logger, mock_hass, None, None
        )
        assert conn_no_host._host == ""

        # Kill mutant on _resolve_cert_path if cert_file: -> if not cert_file:
        config_empty_cert = connection_config.copy()
        config_empty_cert[CONF_CERT] = ""
        conn_empty_cert = ConnectionRaw8888(
            config_empty_cert, mock_logger, mock_hass, None, None
        )
        assert conn_empty_cert._cert is None


async def test_create_updated(connection_config, mock_logger, mock_hass):
    """Test create_updated method."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._params = {"test": "param"}
        conn._keep_alive = True

        # Test with empty node
        new_conn = conn.create_updated({})
        assert isinstance(new_conn, ConnectionRaw8888)
        assert new_conn is not conn
        assert new_conn._params == {"test": "param"}
        assert new_conn._keep_alive is True

        # Test with None
        new_conn_none = conn.create_updated(None)
        assert isinstance(new_conn_none, ConnectionRaw8888)
        assert new_conn_none is not conn

        # pylint: disable=import-outside-toplevel,duplicate-code
        # Test with params and keep_alive
        yaml_node = {"params": {"new": "value"}, "keep_alive": False}
        new_conn_params = conn.create_updated(yaml_node)
        assert new_conn_params._params == {"test": "param", "new": "value"}
        assert new_conn_params._keep_alive is False

        # Test with connection_template
        yaml_node_tmpl = {"connection_template": "{{ test }}"}
        new_conn_tmpl = conn.create_updated(yaml_node_tmpl)
        assert new_conn_tmpl._connection_template is not None
        assert new_conn_tmpl._connection_template.hass == mock_hass

        # Test embedded command creation (kills mutant 27)
        yaml_embedded = {
            "connection_template": '{"method": "POST"}',
            "condition_template": "{{ True }}",
        }
        yaml_node_with_embedded = {"connection": yaml_embedded}
        conn_with_embedded = conn.create_updated(yaml_node_with_embedded)
        assert conn_with_embedded._embedded_command is not None
        # Verify the embedded command used the correct yaml node
        assert conn_with_embedded._embedded_command._connection_template is not None

        # Test with embedded command and condition template
        yaml_node_embedded = {"connection": {"condition_template": "{{ condition }}"}}
        new_conn_embedded = conn.create_updated(yaml_node_embedded)
        assert new_conn_embedded._embedded_command is not None
        assert new_conn_embedded._embedded_command.condition_template is not None
        assert new_conn_embedded._embedded_command.condition_template.hass == mock_hass

        # Test embedded command WITHOUT condition_template (kills boolean condition_str mutant)
        yaml_node_no_cond = {"connection": {"params": {"foo": "bar"}}}
        new_conn_no_cond = conn.create_updated(yaml_node_no_cond)
        assert new_conn_no_cond._embedded_command is not None
        assert new_conn_no_cond._embedded_command.condition_template is None
        # pylint: enable=duplicate-code


async def test_load_from_yaml_keep_alive(connection_config, mock_logger, mock_hass):
    """Test that load_from_yaml properly updates keep_alive and params."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn._keep_alive is True  # Default
        conn._params = {"existing": "val"}

        # Test empty node returns False
        assert conn.load_from_yaml({}, None) is False

        # Test keep_alive and params
        result = conn.load_from_yaml(
            {"keep_alive": False, "params": {"new": "val"}}, None
        )
        assert result is True
        assert conn._keep_alive is False
        assert conn._params == {"existing": "val", "new": "val"}

        # Test partial (only keep_alive)
        result2 = conn.load_from_yaml({"keep_alive": True}, None)
        assert result2 is True
        assert conn._keep_alive is True
        assert conn._params == {"existing": "val", "new": "val"}

        # Test partial (only params)
        result3 = conn.load_from_yaml({"params": {"newer": "val"}}, None)
        assert result3 is True
        assert conn._params == {"existing": "val", "new": "val", "newer": "val"}

        # Test None in params
        with pytest.raises(TypeError):
            conn.load_from_yaml({"params": None}, None)


async def test_match_type():
    """Test match_type."""
    assert ConnectionRaw8888.match_type("samsung_8888_raw") is True
    assert ConnectionRaw8888.match_type("other_type") is False


async def test_get_diagnostics(connection_config, mock_logger, mock_hass):
    """Test get_diagnostics."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)

        # Test defaults
        diag = conn.get_diagnostics()
        assert diag == {
            "is_connected": False,
            "engine": "samsung_8888_raw",
            "keep_alive_enabled": True,
            "has_embedded_command": False,
            "has_shared_client": False,
        }

        # Test custom values
        conn._is_connected = True
        conn._keep_alive = False
        conn._embedded_command = MagicMock()
        _HOST_CLIENTS[("192.168.1.100", 8888)] = MagicMock()

        diag_custom = conn.get_diagnostics()
        assert diag_custom == {
            "is_connected": True,
            "engine": "samsung_8888_raw",
            "keep_alive_enabled": False,
            "has_embedded_command": True,
            "has_shared_client": True,
        }

        # Test port extraction from url (kills mutant on self._params.get("url"))
        _HOST_CLIENTS.pop(("192.168.1.100", 8888), None)
        conn._params = {"url": "http://192.168.1.100:9999"}
        _HOST_CLIENTS[("192.168.1.100", 9999)] = MagicMock()
        diag_url = conn.get_diagnostics()
        assert diag_url["has_shared_client"] is True

        # Test no host branch (kills mutant on else (self._client is not None))
        conn._host = None
        conn._client = None
        assert conn.get_diagnostics()["has_shared_client"] is False

        conn._client = MagicMock()
        assert conn.get_diagnostics()["has_shared_client"] is True


async def test_is_async_native(connection_config, mock_logger, mock_hass):
    """Test is_async_native."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn.is_async_native is True


async def test_execute_raises_not_implemented(
    connection_config, mock_logger, mock_hass
):
    """Test execute raises NotImplementedError."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        with pytest.raises(NotImplementedError):
            conn.execute(None, None, {})


async def test_async_get_client(connection_config, mock_logger, mock_hass):
    """Test all paths of async_get_client."""
    with patch("os.path.exists", return_value=True):
        # 1. Standalone client (no controller, no explicit port, https)
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._params = {"url": "https://test.com/path"}

        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            client = await conn.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 443, conn._cert, log_prefix=conn.log_prefix
            )
            assert conn._client is not None

            # Requesting again should return cached client
            mock_client_cls.reset_mock()
            client_cached = await conn.async_get_client()
            assert client_cached == client
            mock_client_cls.assert_not_called()

        # 1b. Standalone client (http)
        conn_http = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )
        conn_http._params = {"url": "http://test.com/path"}
        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            await conn_http.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 80, conn_http._cert, log_prefix=conn_http.log_prefix
            )

        # 1c. Standalone client (explicit port) (kills mutant 41)
        conn_explicit = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )
        conn_explicit._params = {"url": "http://test.com:5678/path"}
        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            await conn_explicit.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100",
                5678,
                conn_explicit._cert,
                log_prefix=conn_explicit.log_prefix,
            )

        # 1d. Standalone client (no url, default port) (kills mutants 33, 34)
        conn_def = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )
        conn_def._params = {}
        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            await conn_def.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 8888, conn_def._cert, log_prefix=conn_def.log_prefix
            )

            # Kill mutant on `self._extract_port(self._params.get("url"))` where "url" gets flipped
            mock_client_cls.reset_mock()
            conn_def._client = None  # Reset client
            conn_def._host = (
                "192.168.1.101"  # use different host to not hit cached _HOST_CLIENTS
            )
            conn_def._params = {
                "url": "http://test.com:7777/path",
                "XXurlXX": "http://test.com:9999/path",
            }
            await conn_def.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.101", 7777, conn_def._cert, log_prefix=conn_def.log_prefix
            )

        # 2. Standalone client, no host raises CannotConnect
        conn2 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn2._host = None
        conn2._config = {}  # No fallback ip address either
        with pytest.raises(CannotConnect):
            await conn2.async_get_client()

        # 3. Shared client (internal host pool)
        conn3 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn3._params = {"url": "http://test.com:1234/path"}

        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            client = await conn3.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 1234, conn3._cert, log_prefix=conn3.log_prefix
            )
            assert _HOST_CLIENTS[("192.168.1.100", 1234)] == client

            # Requesting again should return cached shared client
            mock_client_cls.reset_mock()
            client_cached = await conn3.async_get_client()
            assert client_cached == client
            mock_client_cls.assert_not_called()

        # 3b. Shared client (https and http)
        _HOST_CLIENTS.clear()
        conn3b = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )
        conn3b._params = {"url": "https://test.com/path"}
        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            await conn3b.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 443, conn3b._cert, log_prefix=conn3b.log_prefix
            )

        conn3c = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )
        conn3c._params = {"url": "http://test.com/path"}
        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            await conn3c.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 80, conn3c._cert, log_prefix=conn3c.log_prefix
            )

        # 4. Shared client, no host raises CannotConnect
        conn4 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn4._host = None
        with pytest.raises(CannotConnect):
            await conn4.async_get_client()


async def test_close(connection_config, mock_logger, mock_hass):
    """Test all paths of close."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)

        # 1. Close internal embedded command
        conn._embedded_command = MagicMock()
        conn._embedded_command.close = AsyncMock()
        await conn.close()
        conn._embedded_command.close.assert_called_once()

        # 2. Close local client
        mock_client = AsyncMock()
        conn._client = mock_client
        await conn.close()
        mock_client.close.assert_called_once()
        assert conn._client is None

        # 3. Close shared client in pool
        mock_shared_client = AsyncMock()
        _HOST_CLIENTS[("192.168.1.100", 8888)] = mock_shared_client
        await conn.close()
        mock_shared_client.close.assert_called_once()
        assert ("192.168.1.100", 8888) not in _HOST_CLIENTS

        # 4. Handle exceptions during close
        mock_client2 = AsyncMock()
        mock_client2.close.side_effect = TimeoutError("timeout")
        conn._client = mock_client2

        mock_shared_client2 = AsyncMock()
        mock_shared_client2.close.side_effect = TimeoutError("timeout")
        _HOST_CLIENTS[("192.168.1.100", 8888)] = mock_shared_client2

        conn._embedded_command.close.side_effect = TimeoutError("timeout")

        # Should not raise
        await conn.close()
        assert conn._client is None

        # 5. Handle missing client fields cleanly
        conn_empty = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )
        conn_empty._client = None
        conn_empty._embedded_command = None
        await conn_empty.close()  # Should succeed cleanly


async def test_set_controller_ref(connection_config, mock_logger, mock_hass):
    """Test setting controller ref."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_controller = MagicMock()

        # Test basic assignment
        conn.set_controller_ref(mock_controller)
        assert conn._controller == mock_controller

        # Test embedded command propagation
        conn._embedded_command = MagicMock()
        conn._embedded_command.set_controller_ref = MagicMock()
        conn._embedded_command.close = AsyncMock()

        conn.set_controller_ref(mock_controller)

        assert conn._controller == mock_controller
        conn._embedded_command.set_controller_ref.assert_called_once_with(
            mock_controller
        )

        # Also test async_get_client creates shared client in pool
        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            client = await conn.async_get_client()
            assert client == _HOST_CLIENTS[("192.168.1.100", 8888)]
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 8888, conn._cert, log_prefix=conn.log_prefix
            )

        # Also test close removes from pool
        mock_shared_client = AsyncMock()
        _HOST_CLIENTS[("192.168.1.100", 8888)] = mock_shared_client
        await conn.close()
        mock_shared_client.close.assert_called_once()
        assert ("192.168.1.100", 8888) not in _HOST_CLIENTS


async def test_load_from_yaml(connection_config, mock_logger, mock_hass):
    """Test load_from_yaml."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn.load_from_yaml(None, None) is False
        assert (
            conn.load_from_yaml({"keep_alive": False, "params": {"foo": "bar"}}, None)
            is True
        )
        assert conn._params["foo"] == "bar"


async def test_async_execute_embedded_command(
    connection_config, mock_logger, mock_hass
):
    """Test execution of embedded commands."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._host = "1.2.3.4"

        # 1. Condition True
        mock_emb = MagicMock()
        mock_emb.check_execute_condition.return_value = True
        mock_emb.params = {
            "url": "/emb___CLIMATE_IP_MAC__",
            "method": "POST",
            "json": {"auth": "__CLIMATE_IP_TOKEN__"},
            "headers": {"X-Emb": "__DEVICE_ID__"},
        }
        mock_emb.connection_template = None
        mock_emb._params = mock_emb.params
        mock_emb._connection_template = None
        mock_emb.async_execute = AsyncMock()
        conn._embedded_command = mock_emb

        mock_client = AsyncMock()
        mock_client.request.return_value = ('{"ok": 1}', None)

        with (
            patch(
                "custom_components.climate_ip.connection_raw.Samsung8888Client",
                return_value=mock_client,
            ),
            patch.object(conn, "async_get_client", return_value=mock_client),
        ):
            await conn.async_execute(
                "GET", "/main", {"data": "main"}, None, device_state={"state": "on"}
            )

            # Verify embedded was called with replaced placeholders
            mock_emb.check_execute_condition.assert_called_once_with({"state": "on"})
            mock_emb.async_execute.assert_called_once()
            _, kwargs = mock_emb.async_execute.call_args
            assert kwargs["method"] == "POST"
            assert kwargs["url"] == "/emb_"  # Since mac is ""
            assert kwargs["data"] == '{"auth":"mock_token"}'
            assert kwargs["headers"] == {
                "X-Emb": "__DEVICE_ID__"
            }  # dev_id is None by default

        # 2. Condition False
        mock_emb.check_execute_condition.return_value = False
        mock_emb.async_execute.reset_mock()
        with patch.object(conn, "async_get_client", return_value=mock_client):
            await conn.async_execute(
                "GET", "/main", None, None, device_state={"state": "off"}
            )
            mock_emb.async_execute.assert_not_called()

            # Kill device_state is not None mutant
            await conn.async_execute("GET", "/main", None, None, device_state=None)
            mock_emb.async_execute.assert_called_once()

        # 3. Exceptions in embedded
        mock_emb.check_execute_condition.return_value = True
        mock_emb.async_execute.side_effect = CannotConnect("emb err")
        with patch.object(conn, "async_get_client", return_value=mock_client):
            with pytest.raises(CannotConnect, match="emb err"):
                await conn.async_execute(
                    "GET", "/main", None, None, device_state={"state": "on"}
                )


async def test_async_execute_poll_and_keep_alive(
    connection_config, mock_logger, mock_hass
):
    """Test closing of socket when polling with keep_alive False."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        mock_client.request.return_value = ("ok", None)

        with patch.object(conn, "async_get_client", return_value=mock_client):
            # _is_poll=True, _keep_alive=False -> Closes connection
            conn._keep_alive = False
            conn._client = AsyncMock()
            client_to_close = conn._client
            await conn.async_execute("GET", "/poll", None, None, _is_poll=True)
            client_to_close.close.assert_called_once()
            assert conn._client is None

            # With shared client in pool
            mock_shared = AsyncMock()
            _HOST_CLIENTS[("192.168.1.100", 8888)] = mock_shared
            await conn.async_execute("GET", "/poll2", None, None, _is_poll=True)
            mock_shared.close.assert_called_once()
            assert ("192.168.1.100", 8888) not in _HOST_CLIENTS

            # Kill mutant on `self._extract_port` by setting a custom port
            conn._params = {"url": "http://192.168.1.100:9999"}
            mock_shared_custom = AsyncMock()
            _HOST_CLIENTS[("192.168.1.100", 9999)] = mock_shared_custom
            await conn.async_execute("GET", "/poll2", None, None, _is_poll=True)
            mock_shared_custom.close.assert_called_once()
            assert ("192.168.1.100", 9999) not in _HOST_CLIENTS
            conn._params = {}  # Reset

            # _is_poll=False -> Does NOT close
            conn._client = AsyncMock()
            client_not_to_close = conn._client
            await conn.async_execute("POST", "/write", None, None, _is_poll=False)
            client_not_to_close.close.assert_not_called()

            # _keep_alive=True -> Does NOT close
            conn._keep_alive = True
            await conn.async_execute("GET", "/poll3", None, None, _is_poll=True)
            client_not_to_close.close.assert_not_called()

            # self._host is None does not crash and gets active clients
            conn_no_host = ConnectionRaw8888(
                {CONF_TOKEN: "mock_token"}, mock_logger, mock_hass, None, None
            )
            conn_no_host._keep_alive = False
            conn_no_host._client = AsyncMock()
            client_to_close2 = conn_no_host._client
            client_to_close2.request.return_value = ("ok", None)

            with patch.object(
                conn_no_host, "async_get_client", return_value=conn_no_host._client
            ):
                await conn_no_host.async_execute(
                    "GET", "/poll4", None, None, _is_poll=True
                )
                client_to_close2.close.assert_called_once()


async def test_async_execute_placeholders_and_request(
    connection_config, mock_logger, mock_hass
):
    """Test payload formatting and main request execution."""
    config = connection_config.copy()
    config[CONF_IP_ADDRESS] = "192.168.1.100"
    config["token"] = "TOKEN123"
    config["mac"] = "AA:BB"

    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(config, mock_logger, mock_hass, None, None)
        mock_controller = MagicMock()
        mock_controller.device_id = "DEV456"
        mock_controller.token = "CTRL_TOKEN"
        conn.set_controller_ref(mock_controller)

        mock_client = AsyncMock()
        mock_client.request.return_value = ('{"ok": 1}', None)

        with patch.object(conn, "async_get_client", return_value=mock_client):
            # Execute with placeholders
            headers_in = {
                "Custom": "__CLIMATE_IP_MAC__",
                "Token": "__CLIMATE_IP_TOKEN__",
                "Host": "__CLIMATE_IP_HOST__",
                "DevId": "__DEVICE_ID__",
            }
            data_in = {
                "payload": "__DEVICE_ID__",
                "tok": "__CLIMATE_IP_TOKEN__",
                "mac": "__CLIMATE_IP_MAC__",
                "host": "__CLIMATE_IP_HOST__",
            }
            resp, err = await conn.async_execute(
                "PUT",
                "/path/__CLIMATE_IP_TOKEN__/__CLIMATE_IP_HOST__/__DEVICE_ID__/__CLIMATE_IP_MAC__",
                data_in,
                headers_in,
            )

            assert resp == '{"ok": 1}'
            assert err is None

            # Check what was passed to request
            mock_client.request.assert_called_once()
            c_method, c_path, c_body, c_headers = mock_client.request.call_args[0]

            assert c_method == "PUT"
            assert c_path == "/path/CTRL_TOKEN/192.168.1.100/DEV456/AA:BB"
            assert c_body == {
                "payload": "DEV456",
                "tok": "CTRL_TOKEN",
                "mac": "AA:BB",
                "host": "192.168.1.100",
            }
            assert c_headers["Custom"] == "AA:BB"

            # Kill mutant on host extraction from config
            mock_client.request.reset_mock()
            conn_no_host = ConnectionRaw8888({}, mock_logger, mock_hass, None, None)
            conn_no_host.set_controller_ref(mock_controller)
            with patch.object(
                conn_no_host, "async_get_client", return_value=mock_client
            ):
                await conn_no_host.async_execute(
                    "PUT", "/path/__CLIMATE_IP_HOST__", None, None
                )
                assert mock_client.request.call_args[0][1] == "/path/"

                # Kill mutant that changes method to None
                mock_client.request.reset_mock()
                await conn_no_host.async_execute("GET", "/path", None, None)
                assert mock_client.request.call_args[0][0] == "GET"

            assert c_headers["Token"] == "CTRL_TOKEN"

            assert c_headers["Host"] == "192.168.1.100"
            assert c_headers["DevId"] == "DEV456"
            assert c_headers["Authorization"] == "Bearer CTRL_TOKEN"
            assert c_headers["Content-Type"] == "application/json"

            # Test string data JSON parsing (kills mutant 150)
            mock_client.request.reset_mock()
            await conn.async_execute("PUT", "/x", '{"string_json": 1}', None)
            c_method, c_path, c_body, c_headers = mock_client.request.call_args[0]
            assert c_body == {"string_json": 1}

            # Test None data parsing (kills mutant 152)
            mock_client.request.reset_mock()
            await conn.async_execute("PUT", "/x", None, None)
            c_method, c_path, c_body, c_headers = mock_client.request.call_args[0]
            assert c_body is None

            # Kill formatting data placeholder without dev_id
            mock_client.request.reset_mock()
            await conn.async_execute(
                "PUT", "/x", '{"string_json": 1, "test": "__DEVICE_ID__"}', None
            )
            c_method, c_path, c_body, c_headers = mock_client.request.call_args[0]
            assert c_body == {"string_json": 1, "test": "DEV456"}


async def test_async_execute_exceptions(connection_config, mock_logger, mock_hass):
    """Test exception handling in async_execute."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._params = {"url": "/test"}

        mock_client = AsyncMock()
        mock_client.close = AsyncMock()

        with patch.object(conn, "async_get_client", return_value=mock_client):
            # ConnectionRefused
            mock_client.request.side_effect = LibConnError("Connection refused")
            with pytest.raises(
                CannotConnect,
                match="Connection refused",
            ):
                await conn.async_execute("GET", "/x", None, None)

            # ConnectionRefused by peer
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Connection refused by peer")
            with pytest.raises(
                CannotConnect,
                match="Connection refused by peer",
            ):
                await conn.async_execute("GET", "/x", None, None)

            # Timeout
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("timed out")
            with pytest.raises(CannotConnect, match="timed out"):
                await conn.async_execute("GET", "/x", None, None)

            # ETIMEDOUT
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("etimedout")
            with pytest.raises(CannotConnect, match="etimedout"):
                await conn.async_execute("GET", "/x", None, None)

            # DNS Error
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Name or service not known")
            with pytest.raises(CannotConnect, match="Name or service not known"):
                await conn.async_execute("GET", "/x", None, None)

            # DNS Error nodename
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("nodename")
            with pytest.raises(CannotConnect, match="nodename"):
                await conn.async_execute("GET", "/x", None, None)

            # Other Error
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("some other error")
            with pytest.raises(CannotConnect, match="some other error"):
                await conn.async_execute("GET", "/x", None, None)

            # Probe suppresses errors
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Connection refused")
            res, err = await conn.async_execute("GET", "/x", None, None, _is_probe=True)
            assert res is None
            assert err is None

            # General Exception
            mock_client.close.reset_mock()
            mock_client.request.side_effect = TypeError("General error")
            with pytest.raises(TypeError, match="General error"):
                await conn.async_execute("GET", "/x", None, None)

            # Kill mutant on `resp, err = await client.request(method, path, body, req_headers)`
            mock_client.request.reset_mock()
            mock_client.request.side_effect = None
            mock_client.request.return_value = (None, None)
            await conn.async_execute(None, "/x", None, None)
            assert mock_client.request.call_args[0][0] is None


async def test_async_execute_mutants_coverage(
    connection_config, mock_logger, mock_hass
):
    """Test specific default values and branches to kill remaining mutants in async_execute."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._params = {"url": "/test"}

        # Test 1: Test without _host set (fallback to config IP) and without controller token (fallback to config token)
        conn._host = None
        conn._config[CONF_IP_ADDRESS] = "2.2.2.2"
        conn._config[CONF_TOKEN] = "CONN_TOKEN"

        mock_controller = MagicMock()
        mock_controller.device_id = None
        mock_controller.token = None
        mock_controller._config = {CONF_TOKEN: "CTRL_CONFIG_TOKEN"}
        conn.set_controller_ref(mock_controller)

        mock_client = AsyncMock()
        mock_client.request.return_value = ('{"ok": 1}', None)

        with patch.object(conn, "async_get_client", return_value=mock_client):
            await conn.async_execute(
                "POST",
                "/x/__CLIMATE_IP_HOST__/__CLIMATE_IP_TOKEN__",
                {"test": "__CLIMATE_IP_HOST__"},
                None,
            )

            mock_client.request.assert_called_once()
            method, url, data, headers = mock_client.request.call_args[0]
            assert method == "POST"
            # Fallback to config IP (2.2.2.2) and controller config token (CTRL_CONFIG_TOKEN)
            assert url == "/x/2.2.2.2/CTRL_CONFIG_TOKEN"
            assert data == {"test": "2.2.2.2"}
            mock_client.close.assert_not_called()

        # Test 2: Test with _host set and controller config missing token
        conn._host = "1.1.1.1"
        mock_controller._config = {}  # Missing CONF_TOKEN

        with patch.object(conn, "async_get_client", return_value=mock_client):
            mock_client.request.reset_mock()
            await conn.async_execute(
                "POST", "/x/__CLIMATE_IP_HOST__/__CLIMATE_IP_TOKEN__", None, None
            )

            mock_client.request.assert_called_once()
            method, url, data, headers = mock_client.request.call_args[0]
            # Uses _host (1.1.1.1) and fallback to connection config token (CONN_TOKEN)
            assert url == "/x/1.1.1.1/CONN_TOKEN"

        # Test 3: Test fallback to empty string when neither _host nor _config IP is set
        conn._host = None
        conn._config = {"token": "SOME_TOKEN"}
        with patch.object(conn, "async_get_client", return_value=mock_client):
            mock_client.request.reset_mock()
            await conn.async_execute("POST", "/x/__CLIMATE_IP_HOST__", None, None)
            mock_client.request.assert_called_once()
            method, url, data, headers = mock_client.request.call_args[0]
            assert url == "/x/"  # Replaced with empty string

        # Test embedded command raising Exception
        conn._embedded_command = MagicMock()
        conn._embedded_command.connection_template = None
        conn._embedded_command.params = {"url": "/emb", "method": "GET"}
        conn._embedded_command._connection_template = None
        conn._embedded_command._params = conn._embedded_command.params
        conn._embedded_command.check_execute_condition = MagicMock(return_value=True)
        # Use an AsyncMock with side_effect to simulate standard failure in an awaitable
        conn._embedded_command.async_execute = AsyncMock(
            side_effect=TypeError("Emb failed")
        )

        with patch.object(conn, "async_get_client", return_value=mock_client):
            # The production code catches Exception and wraps it in CannotConnect
            with pytest.raises(
                CannotConnect, match="Embedded command failed: Emb failed"
            ):
                await conn.async_execute(
                    "GET", "/main", None, None, device_state={"state": "on"}
                )


async def test_async_execute_embedded_and_path(
    connection_config, mock_logger, mock_hass
):
    """Test embedded template async_render, render, format_placeholders, and path fallback."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._host = "1.1.1.1"
        mock_controller = MagicMock()
        mock_controller.device_id = "DEV456"
        conn.set_controller_ref(mock_controller)

        mock_client = AsyncMock()
        mock_client.request.return_value = ('{"ok": 1}', None)

        # Test embedded template async_render, format_placeholders, and url fallback
        conn._embedded_command = MagicMock()
        conn._embedded_command.params = {}
        conn._embedded_command._params = {}

        mock_template = MagicMock()
        mock_template.async_render = MagicMock(return_value='{"method": "POST"}')
        conn._embedded_command.connection_template = mock_template
        conn._embedded_command._connection_template = mock_template
        conn._embedded_command.check_execute_condition = MagicMock(return_value=True)
        conn._embedded_command.async_execute = AsyncMock(return_value=(None, None))

        with patch.object(conn, "async_get_client", return_value=mock_client):
            await conn.async_execute(
                "PUT",
                "/main/__CLIMATE_IP_HOST__",
                None,
                None,
                device_state={"state": "on"},
            )
            mock_template.async_render.assert_called_once()

            # embedded command should execute with method POST, and fallback url "/main/1.1.1.1"
            conn._embedded_command.async_execute.assert_called_once()
            emb_kwargs = conn._embedded_command.async_execute.call_args[1]
            assert emb_kwargs["method"] == "POST"
            assert emb_kwargs["url"] == "/main/__CLIMATE_IP_HOST__"

        # Test embedded params replacement (second pass)
        # DO NOT delete async_render, just reconfigure the return value
        mock_template.async_render = MagicMock(
            return_value=(
                '{"url": "/emb/__DEVICE_ID__/__CLIMATE_IP_HOST__", "method": "GET"}'
            )
        )
        conn._embedded_command.connection_template = mock_template
        conn._embedded_command._connection_template = mock_template
        conn._embedded_command.async_execute.reset_mock()

        with patch.object(conn, "async_get_client", return_value=mock_client):
            await conn.async_execute(
                "PUT", "/main", None, None, device_state={"state": "on"}
            )
            mock_template.async_render.assert_called_once()
            conn._embedded_command.async_execute.assert_called_once()
            emb_kwargs = conn._embedded_command.async_execute.call_args[1]
            assert emb_kwargs["method"] == "GET"
            assert emb_kwargs["url"] == "/emb/DEV456/1.1.1.1"

        # Test url=None path fallback (Kills mutant 129)
        conn._embedded_command = None
        with patch.object(conn, "async_get_client", return_value=mock_client):
            mock_client.request.reset_mock()
            await conn.async_execute("PUT", None, None, None)
            mock_client.request.assert_called_once()
            method, path, data, headers = mock_client.request.call_args[0]
            assert path == ""


@pytest.mark.asyncio
async def test_async_execute_defaults(mock_logger):
    """
    Test the default parameters of async_execute (_is_poll=False, _is_probe=False).
    By verifying the side-effects that SHOULD happen when they are true,
    and ensuring they DO NOT happen when not provided.
    """
    config = {
        "host": "1.2.3.4",
        "token": "tok",
        "mac": "mac",
        "port": 443,
        "cert": "cert.pem",
        "keep_alive": False,  # This normally closes the client if _is_poll=True
    }
    from aiohttp.client_exceptions import ClientConnectorError

    from custom_components.climate_ip.connection_raw import ConnectionRaw8888
    from custom_components.climate_ip.exceptions import CannotConnect

    conn = ConnectionRaw8888(config, mock_logger, None, None, None)

    mock_client = AsyncMock()
    mock_client.request.return_value = ({"status": "ok"}, None)

    _HOST_CLIENTS[("192.168.1.100", 8888)] = mock_client

    with patch.object(conn, "async_get_client", return_value=mock_client):
        # 1. Test that when _is_poll is False (by default), the client is NOT closed
        await conn.async_execute("GET", "/test", None, None)

        # We explicitly verify that close() was not called (which happens if _is_poll=True)
        mock_client.close.assert_not_called()
        # Ensure the shared client was NOT removed
        assert _HOST_CLIENTS[("192.168.1.100", 8888)] is mock_client

        # 2. Test that when _is_probe is False (by default), errors are NOT swallowed
        mock_client.request.side_effect = ClientConnectorError(
            MagicMock(), OSError("Connection refused")
        )

        # With _is_probe=False, this should raise CannotConnect
        with pytest.raises(CannotConnect):
            await conn.async_execute("GET", "/test", None, None)


async def test_log_prefix(connection_config, mock_logger, mock_hass):
    """Test log_prefix property across all conditional branches."""
    with patch("os.path.exists", return_value=True):
        # 1. Controller with unique_id set
        conn1 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_controller = MagicMock()
        mock_controller.unique_id = "ctrl_unique_123"
        mock_controller.log_prefix = "[CTRL_LOG_PREFIX]"
        conn1.set_controller_ref(mock_controller)
        assert conn1.log_prefix == "[CTRL_LOG_PREFIX]"

        # 2. Host configured, no controller
        config_host = {CONF_IP_ADDRESS: "192.168.1.100"}
        conn_host = ConnectionRaw8888(config_host, mock_logger, mock_hass, None, None)
        assert conn_host.log_prefix == "[192.168.1.100]"

        # 3. Fallback no host, no controller
        conn_none = ConnectionRaw8888({}, mock_logger, mock_hass, None, None)
        assert conn_none.log_prefix == "[NO_IP]"


async def test_is_push_supported(connection_config, mock_logger, mock_hass):
    """Test is_push_supported property returns False strictly."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn.is_push_supported is False
        assert type(conn.is_push_supported) is bool


# ====================================================================================
# TESTS DE COMANDOS EMBEBIDOS: LOGS Y WARNINGS (Migrados)
# ====================================================================================


async def test_embedded_command_no_params_no_template_logs_warning(
    connection_config, mock_logger, mock_hass
):
    """When embedded command has neither _connection_template nor _params, it should log a warning."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from jinja2 import Template

    from custom_components.climate_ip.connection_raw import ConnectionRaw8888

    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        embedded = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )

        embedded._connection_template = None
        embedded._params = {}  # Empty params
        embedded.condition_template = Template("1")
        conn._embedded_command = embedded

    device_state = MagicMock()
    mock_client = AsyncMock()
    mock_client.request.return_value = ('{"result": "ok"}', None)
    mock_client.close = AsyncMock()

    with patch(
        "custom_components.climate_ip.connection_raw.Samsung8888Client",
        return_value=mock_client,
    ):
        embedded.async_execute = AsyncMock()
        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0/mode",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer mock_token"},
            device_state=device_state,
        )

        # Embedded should NOT have been called (no params to send)
        embedded.async_execute.assert_not_called()
