# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ConnectionRaw8888."""

# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.connection_raw import ConnectionRaw8888
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import CannotConnect
from custom_components.climate_ip.protocol_8888 import (
    CannotConnect as LibConnError,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN


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
        assert conn._client is None

        # Kill mutant 18 and 23 by testing absolute path and exact joining
        config2 = connection_config.copy()
        config2[CONF_CERT] = "/absolute/path/cert.pem"
        conn2 = ConnectionRaw8888(config2, mock_logger, mock_hass, None, None)
        assert conn2._cert == "/absolute/path/cert.pem"


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
            "reconnect_retries": 0,
            "engine": "raw_socket",
        }

        # Test custom values
        conn._is_connected = True
        conn._reconnect_retries = 5
        diag_custom = conn.get_diagnostics()
        assert diag_custom == {
            "is_connected": True,
            "reconnect_retries": 5,
            "engine": "raw_socket",
        }


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

        # 2. Standalone client, no host raises CannotConnect
        conn2 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn2._host = None
        conn2._config = {}  # No fallback ip address either
        with pytest.raises(CannotConnect):
            await conn2.async_get_client()

        # 3. Shared client (with controller)
        conn3 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn3._params = {"url": "http://test.com:1234/path"}
        mock_controller = MagicMock()
        mock_controller._shared_raw_client = None  # Ensure it does not exist
        conn3.set_controller_ref(mock_controller)

        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            client = await conn3.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 1234, conn3._cert, log_prefix=conn3.log_prefix
            )
            assert mock_controller._shared_raw_client == client

            # Requesting again should return cached shared client
            mock_client_cls.reset_mock()
            client_cached = await conn3.async_get_client()
            assert client_cached == client
            mock_client_cls.assert_not_called()

        # 3b. Shared client (https and http)
        conn3b = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )
        conn3b._params = {"url": "https://test.com/path"}
        mock_controller_b = MagicMock()
        mock_controller_b._shared_raw_client = None
        conn3b.set_controller_ref(mock_controller_b)
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
        mock_controller_c = MagicMock()
        mock_controller_c._shared_raw_client = None
        conn3c.set_controller_ref(mock_controller_c)
        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            await conn3c.async_get_client()
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 80, conn3c._cert, log_prefix=conn3c.log_prefix
            )

        # 4. Shared client, no host raises CannotConnect
        conn4 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_controller2 = MagicMock()
        mock_controller2._shared_raw_client = None
        conn4.set_controller_ref(mock_controller2)
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

        # 3. Close shared client
        mock_controller = MagicMock()
        mock_shared_client = AsyncMock()
        mock_controller._shared_raw_client = mock_shared_client
        conn.set_controller_ref(mock_controller)
        await conn.close()
        mock_shared_client.close.assert_called_once()
        assert mock_controller._shared_raw_client is None

        # 4. Handle exceptions during close
        mock_client2 = AsyncMock()
        mock_client2.close.side_effect = TimeoutError("timeout")
        conn._client = mock_client2

        mock_shared_client2 = AsyncMock()
        mock_shared_client2.close.side_effect = TimeoutError("timeout")
        mock_controller._shared_raw_client = mock_shared_client2

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
        conn_empty._controller = MagicMock()
        conn_empty._controller._shared_raw_client = None
        await conn_empty.close()  # Should succeed cleanly
        assert mock_controller._shared_raw_client is None


async def test_set_controller_ref(connection_config, mock_logger, mock_hass):
    """Test setting controller ref and shared client."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_controller = MagicMock()
        mock_controller._shared_raw_client = None

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

        # Also test async_get_client creates shared client
        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client"
        ) as mock_client_cls:
            client = await conn.async_get_client()
            assert client == mock_controller._shared_raw_client
            mock_client_cls.assert_called_once_with(
                "192.168.1.100", 8888, conn._cert, log_prefix=conn.log_prefix
            )

        # Also test close with controller
        mock_shared_client = AsyncMock()
        mock_controller._shared_raw_client = mock_shared_client
        await conn.close()
        mock_shared_client.close.assert_called_once()
        assert mock_controller._shared_raw_client is None


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
        mock_emb._params = {
            "url": "/emb___CLIMATE_IP_MAC__",
            "method": "POST",
            "json": {"auth": "__CLIMATE_IP_TOKEN__"},
            "headers": {"X-Emb": "__DEVICE_ID__"},
        }
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

            # With shared client
            mock_controller = MagicMock()
            mock_controller._shared_raw_client = AsyncMock()
            shared_to_close = mock_controller._shared_raw_client
            conn.set_controller_ref(mock_controller)
            await conn.async_execute("GET", "/poll2", None, None, _is_poll=True)
            shared_to_close.close.assert_called_once()
            assert mock_controller._shared_raw_client is None

            # _is_poll=False -> Does NOT close
            conn._client = AsyncMock()
            client_not_to_close = conn._client
            await conn.async_execute("POST", "/write", None, None, _is_poll=False)
            client_not_to_close.close.assert_not_called()

            # _keep_alive=True -> Does NOT close
            conn._keep_alive = True
            await conn.async_execute("GET", "/poll3", None, None, _is_poll=True)
            client_not_to_close.close.assert_not_called()


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
                match=r"Connection refused \(device unreachable or offline\)",
            ):
                await conn.async_execute("GET", "/x", None, None)
            mock_client.close.assert_called_once()

            # ConnectionRefused by peer
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Connection refused by peer")
            with pytest.raises(
                CannotConnect,
                match=r"Connection refused \(device unreachable or offline\)",
            ):
                await conn.async_execute("GET", "/x", None, None)

            # Timeout
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("timed out")
            with pytest.raises(CannotConnect, match="Connection timed out"):
                await conn.async_execute("GET", "/x", None, None)

            # ETIMEDOUT
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("etimedout")
            with pytest.raises(CannotConnect, match="Connection timed out"):
                await conn.async_execute("GET", "/x", None, None)

            # DNS Error
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("Name or service not known")
            with pytest.raises(CannotConnect, match=r"Host not found \(DNS error\)"):
                await conn.async_execute("GET", "/x", None, None)

            # DNS Error nodename
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("nodename")
            with pytest.raises(CannotConnect, match=r"Host not found \(DNS error\)"):
                await conn.async_execute("GET", "/x", None, None)

            # Other Error
            mock_client.close.reset_mock()
            mock_client.request.side_effect = LibConnError("some other error")
            with pytest.raises(
                CannotConnect, match="Connection error: some other error"
            ):
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
            with pytest.raises(CannotConnect, match="Unexpected error"):
                await conn.async_execute("GET", "/x", None, None)


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
        del mock_controller.device_id
        del mock_controller.token
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
        conn._embedded_command._connection_template = None
        conn._embedded_command._params = {"url": "/emb", "method": "GET"}
        conn._embedded_command.check_execute_condition = MagicMock(return_value=True)
        conn._embedded_command.async_execute.side_effect = TypeError("Emb failed")
        with patch.object(conn, "async_get_client", return_value=mock_client):
            # It logs the error and raises it
            with pytest.raises(TypeError):
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
        conn._embedded_command._params = {}

        mock_template = MagicMock()
        mock_template.async_render = AsyncMock(return_value='{"method": "POST"}')
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

        # Test render, embedded params replacement
        del mock_template.async_render
        mock_template.render.return_value = (
            '{"url": "/emb/__DEVICE_ID__/__CLIMATE_IP_HOST__", "method": "GET"}'
        )
        conn._embedded_command._connection_template = mock_template
        conn._embedded_command.async_execute.reset_mock()

        with patch.object(conn, "async_get_client", return_value=mock_client):
            await conn.async_execute(
                "PUT", "/main", None, None, device_state={"state": "on"}
            )
            mock_template.render.assert_called_once()
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
    from custom_components.climate_ip.connection_raw import ConnectionRaw8888
    from custom_components.climate_ip.exceptions import CannotConnect
    from aiohttp.client_exceptions import ClientConnectorError

    conn = ConnectionRaw8888(config, mock_logger, None, None, None)

    mock_client = AsyncMock()
    mock_client.request.return_value = ({"status": "ok"}, None)

    mock_controller = MagicMock()
    mock_controller._shared_raw_client = mock_client
    conn._controller = mock_controller

    with patch.object(conn, "async_get_client", return_value=mock_client):
        # 1. Test that when _is_poll is False (by default), the client is NOT closed
        await conn.async_execute("GET", "/test", None, None)

        # We explicitly verify that close() was not called (which happens if _is_poll=True)
        mock_client.close.assert_not_called()
        # Ensure the shared client was NOT removed
        assert mock_controller._shared_raw_client is mock_client

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

        # 2. MAC configured with 16-character DUID string (8 octets: 11:22:33:44:55:66:77:88)
        # duid becomes "1122334455667788" (16 chars), duid[-6:] yields "667788" while duid[+6:] yields "334455667788"
        config_mac = {CONF_MAC: "11:22:33:44:55:66:77:88"}
        conn_mac = ConnectionRaw8888(config_mac, mock_logger, mock_hass, None, None)
        assert conn_mac.log_prefix == "[667788]"

        # 3. Host configured, no MAC, no controller
        config_host = {CONF_IP_ADDRESS: "192.168.1.100"}
        conn_host = ConnectionRaw8888(config_host, mock_logger, mock_hass, None, None)
        assert conn_host.log_prefix == "[192.168.1.100]"

        # 4. Fallback no MAC, no host, no controller
        conn_none = ConnectionRaw8888({}, mock_logger, mock_hass, None, None)
        assert conn_none.log_prefix == "[NO_IP]"


async def test_is_push_supported(connection_config, mock_logger, mock_hass):
    """Test is_push_supported property returns False strictly."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn.is_push_supported is False
        assert type(conn.is_push_supported) is bool
