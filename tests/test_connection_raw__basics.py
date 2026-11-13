# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,too-many-locals,too-many-statements,unidiomatic-typecheck
"""Tests for ConnectionRaw8888."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.connection_raw import (
    _HOST_CLIENTS,
    ConnectionRaw8888,
    clear_raw_clients_pool,
)
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import AuthError, CannotConnect
from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN


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


def test_raw_initialization(connection_config, mock_logger, mock_hass):
    """Test connection initialization."""
    from pathlib import Path

    from custom_components.climate_ip import connection_raw

    conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
    assert conn._config is connection_config
    assert conn._logger is mock_logger
    assert conn._hass is mock_hass
    assert conn._host == "192.168.1.100"
    assert ConnectionRaw8888.match_type("samsung_8888_raw") is True
    assert ConnectionRaw8888.match_type("invalid_type") is False
    assert conn._cert == str(Path(connection_raw.__file__).parent / "cert.pem")
    assert conn.condition_template is None
    assert conn._keep_alive is True
    assert conn._params == {}
    assert conn.params == {}
    assert conn._controller is None
    assert conn._connection_template is None
    assert conn._embedded_command is None
    assert conn._client is None
    assert conn.is_available is False
    conn._is_connected = True
    assert conn.is_available is True

    tmpl = MagicMock()
    conn.connection_template = tmpl
    assert conn.connection_template is tmpl

    with pytest.raises(NotImplementedError):
        conn.execute(None, None, {})

    # Kill mutant 18 and 23 by testing absolute path and exact joining
    config2 = connection_config.copy()
    config2[CONF_CERT] = "/absolute/path/cert.pem"
    conn2 = ConnectionRaw8888(config2, mock_logger, mock_hass, None, None)
    assert conn2._cert == "/absolute/path/cert.pem"

    # Kill mutant __init__ on self._host = None
    config_no_host = connection_config.copy()
    config_no_host.pop(CONF_IP_ADDRESS, None)
    conn_no_host = ConnectionRaw8888(config_no_host, mock_logger, mock_hass, None, None)
    assert conn_no_host._host == ""

    # Kill mutant on _resolve_cert_path if cert_file: -> if not cert_file:
    config_empty_cert = connection_config.copy()
    config_empty_cert[CONF_CERT] = ""
    conn_empty_cert = ConnectionRaw8888(
        config_empty_cert, mock_logger, mock_hass, None, None
    )
    assert conn_empty_cert._cert is None

    # Kill mutant on _resolve_cert_path: and -> or with relative path containing directories
    config_sub_cert = connection_config.copy()
    config_sub_cert[CONF_CERT] = "subfolder/cert.pem"
    conn_sub_cert = ConnectionRaw8888(
        config_sub_cert, mock_logger, mock_hass, None, None
    )
    assert conn_sub_cert._cert == "subfolder/cert.pem"

    # Kill mutant 24 on self._keep_alive = config.get(CONF_KEEP_ALIVE, True)
    config_ka_false = connection_config.copy()
    config_ka_false["keep_alive"] = False
    conn_ka_false = ConnectionRaw8888(
        config_ka_false, mock_logger, mock_hass, None, None
    )
    assert conn_ka_false._keep_alive is False

    # Test clear_raw_clients_pool flushes client cache
    _HOST_CLIENTS[("1.1.1.1", 8888)] = MagicMock()
    assert len(_HOST_CLIENTS) > 0
    clear_raw_clients_pool()
    assert len(_HOST_CLIENTS) == 0


def test_raw_create_updated(connection_config, mock_logger, mock_hass):
    """Test create_updated method."""
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

    # Test preserving controller reference and embedded propagation
    mock_controller = MagicMock()
    conn.set_controller_ref(mock_controller)
    assert conn._controller == mock_controller
    updated_ctrl = conn.create_updated({})
    assert updated_ctrl._controller is mock_controller

    conn._embedded_command = MagicMock()
    conn._embedded_command.set_controller_ref = MagicMock()
    conn.set_controller_ref(mock_controller)
    assert conn._controller == mock_controller
    conn._embedded_command.set_controller_ref.assert_called_once_with(mock_controller)
    conn._embedded_command = None

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


def test_load_from_yaml_keep_alive(connection_config, mock_logger, mock_hass):
    """Test that load_from_yaml properly updates keep_alive and params."""
    conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
    assert conn._keep_alive is True  # Default
    conn._params = {"existing": "val"}

    # Test empty and None node returns False
    assert conn.load_from_yaml(None, None) is False
    assert conn.load_from_yaml({}, None) is False

    # Test keep_alive and params
    result = conn.load_from_yaml({"keep_alive": False, "params": {"new": "val"}}, None)
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


def test_raw_get_diagnostics(connection_config, mock_logger, mock_hass):
    """Test get_diagnostics."""
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


def test_is_async_native(connection_config, mock_logger, mock_hass):
    """Test is_async_native."""
    conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
    assert conn.is_async_native is True


async def test_async_get_client(connection_config, mock_logger, mock_hass):
    """Test all paths of async_get_client."""
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
    conn_http = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
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
    conn_def = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
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

        # Kill mutant on `if key not in _HOST_CLIENTS or _HOST_CLIENTS[key] is None:`
        # when _HOST_CLIENTS[key] is not None -> a second connection instance with same host/port
        # (conn3_new._client is None) should reuse _HOST_CLIENTS[key] without calling Samsung8888Client
        conn3_new = ConnectionRaw8888(
            connection_config, mock_logger, mock_hass, None, None
        )
        conn3_new._params = {"url": "http://test.com:1234/path"}
        mock_client_cls.reset_mock()
        client_reused = await conn3_new.async_get_client()
        assert client_reused is client
        mock_client_cls.assert_not_called()

        # Also test when _HOST_CLIENTS[key] is explicitly None
        _HOST_CLIENTS[("192.168.1.100", 1234)] = None
        conn3_new._client = None
        mock_client_cls.reset_mock()
        await conn3_new.async_get_client()
        mock_client_cls.assert_called_once_with(
            "192.168.1.100", 1234, conn3_new._cert, log_prefix=conn3_new.log_prefix
        )

    # 3b. Shared client (https and http)
    _HOST_CLIENTS.clear()
    conn3b = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
    conn3b._params = {"url": "https://test.com/path"}
    with patch(
        "custom_components.climate_ip.connection_raw.Samsung8888Client"
    ) as mock_client_cls:
        await conn3b.async_get_client()
        mock_client_cls.assert_called_once_with(
            "192.168.1.100", 443, conn3b._cert, log_prefix=conn3b.log_prefix
        )

    conn3c = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
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

    # 3b. Close shared client in pool with explicit custom port in url
    # Kills mutants on port = self._extract_port(self._params.get("url"))
    conn._params = {"url": "https://192.168.1.100:9999"}
    mock_custom_port_client = AsyncMock()
    mock_default_port_client = AsyncMock()
    _HOST_CLIENTS[("192.168.1.100", 9999)] = mock_custom_port_client
    _HOST_CLIENTS[("192.168.1.100", 8888)] = mock_default_port_client
    await conn.close()
    mock_custom_port_client.close.assert_called_once()
    assert ("192.168.1.100", 9999) not in _HOST_CLIENTS
    assert ("192.168.1.100", 8888) in _HOST_CLIENTS
    _HOST_CLIENTS.clear()
    conn._params = {}

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


async def test_async_execute_embedded_command(
    connection_config, mock_logger, mock_hass
):
    """Test execution of embedded commands."""
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
            await conn_no_host.async_execute("GET", "/poll4", None, None, _is_poll=True)
            client_to_close2.close.assert_called_once()


async def test_is_available_follows_successful_requests(
    connection_config, mock_logger, mock_hass
):
    """Test is_available turns True after a successful request and False on close.

    The poller only serves the cached state on transient errors while the base
    connection reports itself as available, but requests run on the copies
    made by create_updated, so the state must be shared with them.
    """
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        op_conn = conn.create_updated({})
        mock_client = AsyncMock()
        device_error = "HTTP 500: InvokeGetDeviceListFunc fail"

        with patch.object(op_conn, "async_get_client", return_value=mock_client):
            assert conn.is_available is False

            # A failed request before any success keeps it unavailable
            mock_client.request.return_value = (None, device_error)
            with pytest.raises(CannotConnect):
                await op_conn.async_execute("GET", "/devices", None, None)
            assert conn.is_available is False

            mock_client.request.return_value = ('{"Devices": []}', None)
            await op_conn.async_execute("GET", "/devices", None, None)
            assert conn.is_available is True
            assert op_conn.is_available is True

            # A transient error afterwards does not flip it back
            mock_client.request.return_value = (None, device_error)
            with pytest.raises(CannotConnect):
                await op_conn.async_execute("GET", "/devices", None, None)
            assert conn.is_available is True

        await conn.close()
        assert conn.is_available is False
        assert op_conn.is_available is False


async def test_async_execute_placeholders_and_request(
    connection_config, mock_logger, mock_hass
):
    """Test payload formatting and main request execution."""
    config = connection_config.copy()
    config[CONF_IP_ADDRESS] = "192.168.1.100"
    config["token"] = "TOKEN123"
    config["mac"] = "AA:BB"

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
        with patch.object(conn_no_host, "async_get_client", return_value=mock_client):
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

        # Verify debug logging enabled execution path
        with patch(
            "custom_components.climate_ip.connection_raw._LOGGER.isEnabledFor",
            return_value=True,
        ):
            resp_dbg, err_dbg = await conn.async_execute(
                "GET", "/debug_path", None, None
            )
            assert resp_dbg == '{"ok": 1}'
            assert err_dbg is None


async def test_async_execute_mutants_coverage(
    connection_config, mock_logger, mock_hass
):
    """Test specific default values and branches to kill remaining mutants in async_execute."""
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
        method, url, data, _headers = mock_client.request.call_args[0]
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
        _method, url, _data, _headers = mock_client.request.call_args[0]
        # Uses _host (1.1.1.1) and fallback to connection config token (CONN_TOKEN)
        assert url == "/x/1.1.1.1/CONN_TOKEN"

    # Test 2b: Public controller.config dict takes priority when token is None and _config is empty (kills L250 mutant 26)
    mock_controller.config = {CONF_TOKEN: "PUBLIC_CTRL_CFG_TOKEN"}
    mock_controller._config = {}
    with patch.object(conn, "async_get_client", return_value=mock_client):
        mock_client.request.reset_mock()
        await conn.async_execute(
            "POST", "/x/__CLIMATE_IP_HOST__/__CLIMATE_IP_TOKEN__", None, None
        )
        mock_client.request.assert_called_once()
        _, url_pub, _, _ = mock_client.request.call_args[0]
        assert url_pub == "/x/1.1.1.1/PUBLIC_CTRL_CFG_TOKEN"
    del mock_controller.config

    # Test 3: Test fallback to empty string when neither _host nor _config IP is set
    conn._host = None
    conn._config = {"token": "SOME_TOKEN"}
    with patch.object(conn, "async_get_client", return_value=mock_client):
        mock_client.request.reset_mock()
        await conn.async_execute("POST", "/x/__CLIMATE_IP_HOST__", None, None)
        mock_client.request.assert_called_once()
        _method, url, _data, _headers = mock_client.request.call_args[0]
        assert url == "/x/"  # Replaced with empty string

    # Test embedded command raising Exception
    conn._embedded_command = MagicMock()
    conn._embedded_command.connection_template = None
    conn._embedded_command.params = {"url": "/emb", "method": "GET"}
    conn._embedded_command._connection_template = None
    conn._embedded_command._params = conn._embedded_command.params
    conn._embedded_command.check_execute_condition = MagicMock(return_value=True)
    conn._embedded_command.async_execute = AsyncMock(
        side_effect=TypeError("Emb failed")
    )

    with patch.object(conn, "async_get_client", return_value=mock_client):
        # The production code catches Exception and wraps it in CannotConnect
        with pytest.raises(CannotConnect, match="Embedded command failed: Emb failed"):
            await conn.async_execute(
                "GET", "/main", None, None, device_state={"state": "on"}
            )


async def test_async_execute_embedded_and_path(
    connection_config, mock_logger, mock_hass
):
    """Test embedded template async_render, render, format_placeholders, and path fallback."""
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
            {"X-Parent": "1"},
            device_state={"state": "on"},
        )
        mock_template.async_render.assert_called_once_with(parse_result=False)

        # embedded command should execute with method POST, and fallback url "/main/1.1.1.1"
        conn._embedded_command.async_execute.assert_called_once()
        emb_kwargs = conn._embedded_command.async_execute.call_args[1]
        assert emb_kwargs["method"] == "POST"
        assert emb_kwargs["url"] == "/main/__CLIMATE_IP_HOST__"
        assert emb_kwargs["headers"] == {"X-Parent": "1"}
        assert emb_kwargs["device_state"] == {"state": "on"}

    # Test embedded params replacement and method/headers fallback when omitted in template
    mock_template.async_render = MagicMock(
        return_value='{"url": "/emb/__DEVICE_ID__/__CLIMATE_IP_HOST__"}'
    )
    conn._embedded_command.connection_template = mock_template
    conn._embedded_command._connection_template = mock_template
    conn._embedded_command.async_execute.reset_mock()

    with patch.object(conn, "async_get_client", return_value=mock_client):
        await conn.async_execute(
            "PUT",
            "/main",
            None,
            {"X-Parent": "2"},
            device_state={"state": "on"},
        )
        mock_template.async_render.assert_called_once_with(parse_result=False)
        conn._embedded_command.async_execute.assert_called_once()
        emb_kwargs = conn._embedded_command.async_execute.call_args[1]
        assert emb_kwargs["method"] == "PUT"
        assert emb_kwargs["url"] == "/emb/DEV456/1.1.1.1"
        assert emb_kwargs["headers"] == {"X-Parent": "2"}
        assert emb_kwargs["device_state"] == {"state": "on"}

    # Test url=None path fallback (Kills mutant 129)
    conn._embedded_command = None
    with patch.object(conn, "async_get_client", return_value=mock_client):
        mock_client.request.reset_mock()
        await conn.async_execute("PUT", None, None, None)
        mock_client.request.assert_called_once()
        _method, path, _data, _headers = mock_client.request.call_args[0]
        assert path == ""

    # Test embedded command without params and without template logs warning and returns
    conn._embedded_command = MagicMock()
    conn._embedded_command.params = {}
    conn._embedded_command._params = {}
    conn._embedded_command.connection_template = None
    conn._embedded_command._connection_template = None
    conn._embedded_command.check_execute_condition = MagicMock(return_value=True)
    conn._embedded_command.async_execute = AsyncMock()
    with patch.object(conn, "async_get_client", return_value=mock_client):
        await conn.async_execute(
            "PUT", "/main", None, None, device_state={"state": "on"}
        )
        conn._embedded_command.async_execute.assert_not_called()


def test_log_prefix(connection_config, mock_logger, mock_hass):
    """Test log_prefix property across all conditional branches."""
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


def test_is_push_supported(connection_config, mock_logger, mock_hass):
    """Test is_push_supported property returns False strictly."""
    conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
    assert conn.is_push_supported is False
    assert type(conn.is_push_supported) is bool


@pytest.mark.asyncio
async def test_async_execute_api_error_and_auth_error(
    connection_config, mock_logger, mock_hass
):
    """Test async_execute exception handling, API error, probe suppression, and auth errors."""
    conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
    mock_client = AsyncMock()
    mock_client.request.return_value = (None, "Bad Gateway")

    with patch.object(conn, "async_get_client", return_value=mock_client):
        # 1. API Error string from client
        with pytest.raises(CannotConnect, match="API Error: Bad Gateway"):
            await conn.async_execute("GET", "/test", None, None)

        # Probe suppresses API error
        resp, err = await conn.async_execute("GET", "/test", None, None, _is_probe=True)
        assert resp is None
        assert err is None

        # 2. CannotConnect raised during request
        mock_client.request.side_effect = CannotConnect("Connection refused")
        with pytest.raises(CannotConnect, match="Connection refused"):
            await conn.async_execute("GET", "/test", None, None)

        # Probe suppresses CannotConnect
        resp, err = await conn.async_execute("GET", "/test", None, None, _is_probe=True)
        assert resp is None
        assert err is None

        # 3. AuthError wrapped as Invalid token
        mock_client.request.side_effect = AuthError("Socket auth failure")
        with pytest.raises(AuthError, match="Invalid token"):
            await conn.async_execute("GET", "/test", None, None)

        # 4. Socket OSError wrapped in CannotConnect
        mock_client.request.side_effect = OSError("Socket write failure")
        with pytest.raises(CannotConnect, match="Socket error: Socket write failure"):
            await conn.async_execute("GET", "/test", None, None)

        # 5. Unexpected Exception re-raised
        mock_client.request.side_effect = TypeError("Unexpected payload type")
        with pytest.raises(TypeError, match="Unexpected payload type"):
            await conn.async_execute("GET", "/test", None, None)

    # 6. Missing token in config raises AuthError
    conn._config = {}
    with pytest.raises(AuthError, match="Token not configured for the raw engine"):
        await conn.async_execute("GET", "/test", None, None)


@pytest.mark.asyncio
async def test_async_reset_client_close_error(
    connection_config, mock_logger, mock_hass
):
    """Test _handle_periodic_reset ignores OSError during client close."""
    conn = ConnectionRaw8888(
        connection_config, mock_logger, mock_hass, None, "192.168.1.100"
    )
    conn._keep_alive = False
    mock_client = AsyncMock()
    mock_client.close.side_effect = OSError("Socket close error")
    conn._client = mock_client
    await conn._handle_periodic_reset(is_poll=True)
    assert conn._client is None
