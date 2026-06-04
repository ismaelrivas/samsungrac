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
from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN


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
    return {CONF_IP_ADDRESS: "192.168.1.100", CONF_CERT: "cert.pem", CONF_TOKEN: "mock_token"}


@pytest.fixture
def anyio_backend():
    """Use asyncio as the anyio backend."""
    return "asyncio"



async def test_initialization(connection_config, mock_logger, mock_hass):
    """Test connection initialization."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn._host == "192.168.1.100"
        assert conn._cert.endswith("cert.pem")



async def test_create_updated(connection_config, mock_logger, mock_hass):
    """Test create_updated method."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn._params = {"test": "param"}

        # Test with empty node
        new_conn = conn.create_updated({})
        assert isinstance(new_conn, ConnectionRaw8888)
        assert new_conn is not conn
        assert new_conn._params == {"test": "param"}

        # pylint: disable=import-outside-toplevel,duplicate-code
        # Test with params
        yaml_node = {"params": {"new": "value"}}
        new_conn_params = conn.create_updated(yaml_node)
        assert new_conn_params._params == {"test": "param", "new": "value"}

        # Test with connection_template
        yaml_node_tmpl = {"connection_template": "{{ test }}"}
        new_conn_tmpl = conn.create_updated(yaml_node_tmpl)
        assert new_conn_tmpl._connection_template is not None
        assert new_conn_tmpl._connection_template.hass == mock_hass
        # pylint: enable=duplicate-code



async def test_async_execute_success(connection_config, mock_logger, mock_hass):
    """Test successful request execution."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)

        # Mock Samsung8888Client
        mock_client = AsyncMock()
        mock_client.request.return_value = ('{"result": "ok"}', None)
        mock_client.close = AsyncMock()

        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client",
            return_value=mock_client,
        ):
            response, error = await conn.async_execute("GET", "/test", None, None)

            assert response == '{"result": "ok"}'
            assert error is None
            mock_client.request.assert_called_once()



async def test_async_execute_connection_error(connection_config, mock_logger, mock_hass):
    """Test request execution with connection error."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)

        # Mock Samsung8888Client to raise ConnectionError
        mock_client = AsyncMock()
        mock_client.request.side_effect = LibConnError("Connection failed")
        mock_client.close = AsyncMock()

        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client",
            return_value=mock_client,
        ):
            # It should rotate modes and eventually fail
            with pytest.raises(CannotConnect):
                await conn.async_execute("GET", "/test", None, None)


async def test_async_execute_cannot_connect_classification(connection_config, mock_logger, mock_hass):
    """Test that connection error messages are correctly classified."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)

        mock_client = AsyncMock()
        mock_client.close = AsyncMock()

        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client",
            return_value=mock_client,
        ):
            # Test 111 / connection refused
            mock_client.request.side_effect = CannotConnect("Error 111")
            with pytest.raises(CannotConnect) as exc:
                await conn.async_execute("GET", "/test", None, None)
            assert "Connection refused (device unreachable or offline)" in str(exc.value)

            mock_client.request.side_effect = CannotConnect("Connection refused by peer")
            with pytest.raises(CannotConnect) as exc:
                await conn.async_execute("GET", "/test", None, None)
            assert "Connection refused (device unreachable or offline)" in str(exc.value)

            # Test timed out
            mock_client.request.side_effect = CannotConnect("timed out")
            with pytest.raises(CannotConnect) as exc:
                await conn.async_execute("GET", "/test", None, None)
            assert "Connection timed out" in str(exc.value)
            
            mock_client.request.side_effect = CannotConnect("etimedout")
            with pytest.raises(CannotConnect) as exc:
                await conn.async_execute("GET", "/test", None, None)
            assert "Connection timed out" in str(exc.value)

            # Test DNS error
            mock_client.request.side_effect = CannotConnect("name or service not known")
            with pytest.raises(CannotConnect) as exc:
                await conn.async_execute("GET", "/test", None, None)
            assert "Host not found (DNS error)" in str(exc.value)
            
            mock_client.request.side_effect = CannotConnect("nodename")
            with pytest.raises(CannotConnect) as exc:
                await conn.async_execute("GET", "/test", None, None)
            assert "Host not found (DNS error)" in str(exc.value)


async def test_load_from_yaml_keep_alive(connection_config, mock_logger, mock_hass):
    """Test that load_from_yaml properly updates keep_alive."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn._keep_alive is True # Default
        
        conn.load_from_yaml({"keep_alive": False}, None)
        assert conn._keep_alive is False


async def test_8888_raw_all_placeholders_replaced(connection_config, mock_logger, mock_hass):
    """Test that all placeholders are properly replaced in URL, body, and headers."""
    # Build HA Config
    config = connection_config.copy()
    config[CONF_IP_ADDRESS] = "192.168.1.100"
    config["token"] = "REAL_SECURE_TOKEN_8888"
    config["mac"] = "AA:BB:CC:DD:EE:FF"

    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(config, mock_logger, mock_hass, None, None)
        
        mock_controller = MagicMock()
        mock_controller.device_id = "DEV123"
        mock_controller.token = "REAL_SECURE_TOKEN_8888"
        mock_controller._shared_raw_client = None
        conn._controller = mock_controller

        mock_client = AsyncMock()
        mock_client.request.return_value = ('{"result": "ok"}', None)
        mock_client.close = AsyncMock()

        with patch(
            "custom_components.climate_ip.connection_raw.Samsung8888Client",
            return_value=mock_client,
        ):
            url_with_placeholder = "https://__CLIMATE_IP_HOST__:8888/devices/__DEVICE_ID__"
            payload_with_placeholder = {"token": "__CLIMATE_IP_TOKEN__", "mac": "__CLIMATE_IP_MAC__"}
            headers_with_placeholder = {
                "X-Mac": "__CLIMATE_IP_MAC__", 
                "X-Dev": "__DEVICE_ID__", 
                "X-Host": "__CLIMATE_IP_HOST__",
                "X-Token": "__CLIMATE_IP_TOKEN__"
            }

            response, error = await conn.async_execute("POST", url_with_placeholder, payload_with_placeholder, headers_with_placeholder)

            assert response == '{"result": "ok"}'

            expected_headers = {
                "X-Mac": "AA:BB:CC:DD:EE:FF",
                "X-Dev": "DEV123",
                "X-Host": "192.168.1.100",
                "X-Token": "REAL_SECURE_TOKEN_8888",
                "Authorization": "Bearer REAL_SECURE_TOKEN_8888",
                "Content-Type": "application/json"
            }
            
            expected_body = {
                "token": "REAL_SECURE_TOKEN_8888",
                "mac": "AA:BB:CC:DD:EE:FF"
            }

            mock_client.request.assert_called_once_with(
                "POST",
                "/devices/DEV123",
                expected_body,
                expected_headers
            )


async def test_match_type():
    """Test match_type."""
    assert ConnectionRaw8888.match_type("samsung_8888_raw") is True
    assert ConnectionRaw8888.match_type("other_type") is False


async def test_get_diagnostics(connection_config, mock_logger, mock_hass):
    """Test get_diagnostics."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        diag = conn.get_diagnostics()
        assert diag["engine"] == "raw_socket"
        assert "is_connected" in diag


async def test_is_async_native(connection_config, mock_logger, mock_hass):
    """Test is_async_native."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        assert conn.is_async_native is True


async def test_execute_raises_not_implemented(connection_config, mock_logger, mock_hass):
    """Test execute raises NotImplementedError."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        with pytest.raises(NotImplementedError):
            conn.execute(None, None, {})


async def test_close_standalone(connection_config, mock_logger, mock_hass):
    """Test close method for standalone connection."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        conn._client = mock_client
        await conn.close()
        mock_client.close.assert_called_once()
        assert conn._client is None


async def test_set_controller_ref(connection_config, mock_logger, mock_hass):
    """Test setting controller ref and shared client."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_controller = MagicMock()
        mock_controller._shared_raw_client = None
        conn.set_controller_ref(mock_controller)
        assert conn._controller == mock_controller
        
        # Also test async_get_client creates shared client
        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client") as mock_client_cls:
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
        assert conn.load_from_yaml({"keep_alive": False, "params": {"foo": "bar"}}, None) is True
        assert conn._keep_alive is False
        assert conn._params["foo"] == "bar"


async def test_async_get_client_port_parsing(connection_config, mock_logger, mock_hass):
    """Test dynamic port parsing in async_get_client."""
    with patch("os.path.exists", return_value=True):
        # Default port 8888
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        client1 = await conn.async_get_client()
        assert client1.port == 8888

        # Port from URL
        conn2 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn2._params["url"] = "http://192.168.1.100:1234/test"
        client2 = await conn2.async_get_client()
        assert client2.port == 1234

        # HTTPS fallback
        conn3 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn3._params["url"] = "https://192.168.1.100/test"
        client3 = await conn3.async_get_client()
        assert client3.port == 443

        # HTTP fallback
        conn4 = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        conn4._params["url"] = "http://192.168.1.100/test"
        client4 = await conn4.async_get_client()
        assert client4.port == 80


async def test_async_execute_connection_refused(connection_config, mock_logger, mock_hass):
    """Test handling of ConnectionRefused error in async_execute."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        mock_client.request.side_effect = LibConnError("Errno 111 Connection refused")
        mock_client.close = AsyncMock()

        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client", return_value=mock_client):
            with pytest.raises(CannotConnect) as exc_info:
                await conn.async_execute("GET", "/test", None, None)
            assert "Connection refused (device unreachable or offline)" in str(exc_info.value)
            mock_client.close.assert_called_once()


async def test_async_execute_timeout(connection_config, mock_logger, mock_hass):
    """Test handling of Timeout error in async_execute."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        mock_client.request.side_effect = LibConnError("Operation timed out")
        mock_client.close = AsyncMock()

        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client", return_value=mock_client):
            with pytest.raises(CannotConnect) as exc_info:
                await conn.async_execute("GET", "/test", None, None)
            assert "Connection timed out" in str(exc_info.value)


async def test_async_execute_dns_error(connection_config, mock_logger, mock_hass):
    """Test handling of DNS error in async_execute."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        mock_client.request.side_effect = LibConnError("Name or service not known")
        mock_client.close = AsyncMock()

        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client", return_value=mock_client):
            with pytest.raises(CannotConnect) as exc_info:
                await conn.async_execute("GET", "/test", None, None)
            assert "Host not found (DNS error)" in str(exc_info.value)


async def test_async_execute_is_probe(connection_config, mock_logger, mock_hass):
    """Test that _is_probe suppresses CannotConnect exception."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        mock_client.request.side_effect = LibConnError("Connection failed")
        mock_client.close = AsyncMock()

        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client", return_value=mock_client):
            resp, err = await conn.async_execute("GET", "/test", None, None, _is_probe=True)
            assert resp is None
            assert err is None


async def test_async_execute_unexpected_errors(connection_config, mock_logger, mock_hass):
    """Test handling of unexpected errors like asyncio.TimeoutError and ValueError."""
    import asyncio
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRaw8888(connection_config, mock_logger, mock_hass, None, None)
        mock_client = AsyncMock()
        mock_client.request.side_effect = asyncio.TimeoutError("Network Timeout")

        with patch("custom_components.climate_ip.connection_raw.Samsung8888Client", return_value=mock_client):
            with pytest.raises(CannotConnect) as exc_info:
                await conn.async_execute("GET", "/test", None, None)
            assert "Unexpected error" in str(exc_info.value)

