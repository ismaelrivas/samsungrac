# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for embedded command execution in ConnectionRaw8888.

Covers the params-fallback fix: embedded commands defined with `_params`
(no `_connection_template`) must be executed, not silently skipped.
"""
# pylint: disable=protected-access,redefined-outer-name,reimported,import-outside-toplevel

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.connection_raw import ConnectionRaw8888
from custom_components.climate_ip.connection_request import ConnectionRequest
from custom_components.climate_ip.connection_request_tls_auto import (
    ConnectionRequestTlsAuto,
)
from custom_components.climate_ip.const import CONF_CERT
from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN
from homeassistant.helpers.json import json_dumps


@pytest.fixture
def connection_config():
    """Return a minimal connection config dict."""
    return {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_CERT: "cert.pem",
        CONF_TOKEN: "mock_token",
    }


@pytest.fixture
def anyio_backend():
    """Use asyncio as the anyio backend."""
    return "asyncio"


def _make_connection(connection_config):
    """Create a ConnectionRaw8888 with mocked filesystem."""
    with patch("os.path.exists", return_value=True):
        return ConnectionRaw8888(connection_config, MagicMock(), MagicMock(), None, None)


def _mock_client():
    """Create a mock Samsung8888Client that returns success."""
    client = AsyncMock()
    client.request.return_value = ('{"result": "ok"}', None)
    client.close = AsyncMock()
    return client



async def test_embedded_command_with_params_is_executed(connection_config):
    """Regression test: embedded commands with _params (no _connection_template)
    must be executed, not skipped with a WARNING.

    This simulates the samsungrac.yaml hvac_mode flow:
      - Main command: PUT /devices/0/mode  {"modes": ["Cool"]}
      - Embedded command: PUT /devices/0   {"Operation": {"power": "On"}}
        Condition: only if device is Off
    """
    conn = _make_connection(connection_config)

    # Create the embedded command (simulating what create_updated does from YAML)
    embedded = _make_connection(connection_config)
    embedded._params = {
        "json": {"Operation": {"power": "On"}},
        "url": "https://192.168.1.100:8888/devices/0",
    }
    embedded._connection_template = None  # This is the key: no template, only params

    # Set up condition_template that evaluates to "1" (condition met = execute)
    from jinja2 import Template

    embedded.condition_template = Template(
        "{% if device_state.Operation.power == 'Off' %}1{% else %}0{% endif %}"
    )

    conn._embedded_command = embedded

    # Mock device_state where power is Off (should trigger embedded command)
    device_state = MagicMock()
    device_state.Operation.power = "Off"

    mock_client = _mock_client()

    with patch(
        "custom_components.climate_ip.connection_raw.Samsung8888Client",
        return_value=mock_client,
    ):
        # Spy on the embedded command's async_execute to verify it was called
        embedded.async_execute = AsyncMock(return_value=('{"result": "ok"}', None))

        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0/mode",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer mock_token"},
            device_state=device_state,
        )

        # THE KEY ASSERTION: embedded command must have been called and awaited
        embedded.async_execute.assert_awaited_once_with(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0",
            data=json_dumps({"Operation": {"power": "On"}}),
            headers={"Authorization": "Bearer mock_token"},
            device_state=device_state,
        )



async def test_embedded_command_skipped_when_condition_not_met(connection_config):
    """Embedded command should NOT be executed when its condition evaluates to 0."""
    conn = _make_connection(connection_config)

    embedded = _make_connection(connection_config)
    embedded._params = {
        "json": {"Operation": {"power": "On"}},
        "url": "https://192.168.1.100:8888/devices/0",
    }
    embedded._connection_template = None

    from jinja2 import Template

    embedded.condition_template = Template(
        "{% if device_state.Operation.power == 'Off' %}1{% else %}0{% endif %}"
    )

    conn._embedded_command = embedded

    # Power is already On → condition evaluates to "0" → skip
    device_state = MagicMock()
    device_state.Operation.power = "On"

    mock_client = _mock_client()

    with patch(
        "custom_components.climate_ip.connection_raw.Samsung8888Client",
        return_value=mock_client,
    ):
        embedded.async_execute = AsyncMock(return_value=('{"result": "ok"}', None))

        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0/mode",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer mock_token"},
            device_state=device_state,
        )

        # Embedded command should NOT have been called
        embedded.async_execute.assert_not_called()



async def test_embedded_command_with_connection_template_still_works(connection_config):
    """Ensure the original code path (with _connection_template) still functions."""
    conn = _make_connection(connection_config)

    embedded = _make_connection(connection_config)
    from jinja2 import Template

    # Template that renders to valid JSON params
    embedded._connection_template = Template(
        '{"method": "PUT", "url": "https://192.168.1.100:8888/devices/0", '
        '"json": {"Operation": {"power": "On"}}}'
    )
    embedded.condition_template = Template("1")  # Always execute

    conn._embedded_command = embedded

    device_state = MagicMock()

    mock_client = _mock_client()

    with patch(
        "custom_components.climate_ip.connection_raw.Samsung8888Client",
        return_value=mock_client,
    ):
        embedded.async_execute = AsyncMock(return_value=('{"result": "ok"}', None))

        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0/mode",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer mock_token"},
            device_state=device_state,
        )

        # Embedded should have been called via the template path and awaited
        embedded.async_execute.assert_awaited_once_with(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0",
            data=json_dumps({"Operation": {"power": "On"}}),
            headers={"Authorization": "Bearer mock_token"},
            device_state=device_state,
        )



async def test_embedded_command_no_params_no_template_logs_warning(connection_config):
    """When embedded command has neither _connection_template nor _params, it should
    log a warning and not crash.
    """
    conn = _make_connection(connection_config)

    embedded = _make_connection(connection_config)
    embedded._connection_template = None
    embedded._params = {}  # Empty params

    from jinja2 import Template

    embedded.condition_template = Template("1")

    conn._embedded_command = embedded

    device_state = MagicMock()
    mock_client = _mock_client()

    with patch(
        "custom_components.climate_ip.connection_raw.Samsung8888Client",
        return_value=mock_client,
    ):
        embedded.async_execute = AsyncMock()

        # Should not crash
        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0/mode",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer mock_token"},
            device_state=device_state,
        )

        # Embedded should NOT have been called (no params to send)
        embedded.async_execute.assert_not_called()


async def test_embedded_command_uses_its_own_headers_and_method(connection_config):
    """Test that embedded commands can override the main command's headers and method."""
    conn = _make_connection(connection_config)
    embedded = _make_connection(connection_config)
    embedded._params = {
        "json": {"Operation": {"power": "On"}},
        "url": "https://192.168.1.100:8888/embedded",
        "method": "POST",
        "headers": {"X-Custom-Auth": "Secret"}
    }
    embedded._connection_template = None
    from jinja2 import Template
    embedded.condition_template = Template("1")
    conn._embedded_command = embedded
    device_state = MagicMock()

    mock_client = _mock_client()
    with patch("custom_components.climate_ip.connection_raw.Samsung8888Client", return_value=mock_client):
        embedded.async_execute = AsyncMock(return_value=('{"result": "ok"}', None))
        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/main",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer mock_token"},
            device_state=device_state,
        )

        embedded.async_execute.assert_awaited_once_with(
            method="POST",
            url="https://192.168.1.100:8888/embedded",
            data=json_dumps({"Operation": {"power": "On"}}),
            headers={"X-Custom-Auth": "Secret"},
            device_state=device_state,
        )


async def test_embedded_command_skipped_when_device_state_missing(connection_config, caplog):
    """Test warning is logged when device_state is missing."""
    conn = _make_connection(connection_config)
    embedded = _make_connection(connection_config)
    embedded._connection_template = None
    conn._embedded_command = embedded

    # Mock client to prevent real execution if it bypasses condition
    mock_client = _mock_client()
    with patch("custom_components.climate_ip.connection_raw.Samsung8888Client", return_value=mock_client):
        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/main",
            data='{}',
            headers={},
            device_state=None, # Missing device state
        )
    
    assert "cannot check its condition" in caplog.text
    assert any(record.levelname == "WARNING" for record in caplog.records)


# ─────────────────────────────────────────────────────────────────────────────
# ConnectionAiohttp8888 tests
# ─────────────────────────────────────────────────────────────────────────────

AIOHTTP_CONFIG = {
    CONF_TOKEN: "test_token",
    CONF_CERT: "cert.pem",
}


def _make_aiohttp_connection():
    """Create an initialized ConnectionAiohttp8888 with mocked internals."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            AIOHTTP_CONFIG,
            MagicMock(),
            MagicMock(),
            MagicMock(spec=aiohttp.ClientSession),
            "192.168.1.100",
        )
    # Pre-initialize to skip the probe
    conn._shared_state.initialized = True
    conn._shared_state.ssl_context = MagicMock()
    return conn


def _mock_aiohttp_response():
    """Create a mock aiohttp response context manager."""
    # pylint: disable=duplicate-code
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text.return_value = '{"result": "ok"}'
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.raise_for_status = MagicMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_response
    # pylint: enable=duplicate-code
    return mock_ctx



async def test_aiohttp_embedded_command_with_params_is_executed():
    """Regression test for aiohttp: embedded commands with _params (no template)
    must be executed, not skipped.
    """
    conn = _make_aiohttp_connection()

    embedded = _make_aiohttp_connection()
    embedded._params = {
        "json": {"Operation": {"power": "On"}},
        "url": "https://192.168.1.100:8888/devices/0",
    }
    embedded._connection_template = None

    from jinja2 import Template

    embedded.condition_template = Template(
        "{% if device_state.Operation.power == 'Off' %}1{% else %}0{% endif %}"
    )

    conn._embedded_command = embedded

    device_state = MagicMock()
    device_state.Operation.power = "Off"

    conn._session.request.return_value = _mock_aiohttp_response()
    embedded.async_execute = AsyncMock(return_value=('{"result": "ok"}', None))

    # Mock _try_connection to skip the probe
    with patch.object(conn, "_try_connection", new_callable=AsyncMock, return_value=None):
        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0/mode",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer test_token"},
            device_state=device_state,
        )

    embedded.async_execute.assert_awaited_once_with(
        method="PUT",
        url="https://192.168.1.100:8888/devices/0",
        data=json_dumps({"Operation": {"power": "On"}}),
        headers={"Authorization": "Bearer test_token"},
        device_state=device_state,
    )



async def test_aiohttp_embedded_command_skipped_when_condition_not_met():
    """Aiohttp: embedded command not executed when condition evaluates to 0."""
    conn = _make_aiohttp_connection()

    embedded = _make_aiohttp_connection()
    embedded._params = {
        "json": {"Operation": {"power": "On"}},
        "url": "https://192.168.1.100:8888/devices/0",
    }
    embedded._connection_template = None

    from jinja2 import Template

    embedded.condition_template = Template(
        "{% if device_state.Operation.power == 'Off' %}1{% else %}0{% endif %}"
    )

    conn._embedded_command = embedded

    device_state = MagicMock()
    device_state.Operation.power = "On"  # Already on → skip

    conn._session.request.return_value = _mock_aiohttp_response()
    embedded.async_execute = AsyncMock()

    with patch.object(conn, "_try_connection", new_callable=AsyncMock, return_value=None):
        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0/mode",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer test_token"},
            device_state=device_state,
        )

    embedded.async_execute.assert_not_called()



async def test_aiohttp_embedded_command_with_template_still_works():
    """Aiohttp: the original template-based path still functions correctly."""
    conn = _make_aiohttp_connection()

    embedded = _make_aiohttp_connection()
    from jinja2 import Template

    embedded._connection_template = Template(
        '{"method": "PUT", "url": "https://192.168.1.100:8888/devices/0", '
        '"json": {"Operation": {"power": "On"}}}'
    )
    embedded.condition_template = Template("1")

    conn._embedded_command = embedded

    device_state = MagicMock()

    conn._session.request.return_value = _mock_aiohttp_response()
    embedded.async_execute = AsyncMock(return_value=('{"result": "ok"}', None))

    with patch.object(conn, "_try_connection", new_callable=AsyncMock, return_value=None):
        await conn.async_execute(
            method="PUT",
            url="https://192.168.1.100:8888/devices/0/mode",
            data='{"modes": ["Cool"]}',
            headers={"Authorization": "Bearer test_token"},
            device_state=device_state,
        )

    embedded.async_execute.assert_awaited_once_with(
        method="PUT",
        url="https://192.168.1.100:8888/devices/0",
        data=json_dumps({"Operation": {"power": "On"}}),
        headers={"Authorization": "Bearer test_token"},
        device_state=device_state,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ConnectionRequest8888 & ConnectionRequestTlsAuto8888 tests
# ─────────────────────────────────────────────────────────────────────────────


def _make_request_connection(cls):
    """Create an initialized request-based connection with mocked internals."""
    config = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_CERT: "cert.pem",
        CONF_TOKEN: "mock_token",
    }
    with patch("os.path.exists", return_value=True):
        conn = cls(config, MagicMock(), MagicMock())
    return conn


@pytest.mark.skip_legacy
@pytest.mark.parametrize("connection_class", [ConnectionRequest, ConnectionRequestTlsAuto])
def test_request_embedded_command_is_executed(connection_class):
    """Verifies that request engines execute their embedded commands by delegating
    the execute() call down to the child.
    """
    conn = _make_request_connection(connection_class)
    embedded = _make_request_connection(connection_class)

    conn._embedded_command = embedded

    # For request engines, the condition is evaluated on the MAIN command's execution
    # but the embedded check is internal to execute_internal, OR we just trust
    # that `execute` is called on the child.
    embedded.execute = MagicMock()

    device_state = MagicMock()

    with patch.object(conn, "execute_internal", return_value=('{"result": "ok"}', True, 200)):
        conn.execute(
            template=None,
            value='{"modes": ["Cool"]}',
            device_state=device_state,
        )

    # The request engines delegate the exact same arguments down to the embedded command
    embedded.execute.assert_called_once_with(None, '{"modes": ["Cool"]}', device_state, None)


@pytest.mark.skip_legacy
@pytest.mark.parametrize("connection_class", [ConnectionRequest, ConnectionRequestTlsAuto])
def test_request_embedded_command_skipped_when_condition_not_met(connection_class):
    """Verifies that if the main command condition is not met, the embedded command
    IS STILL executed first (as per current code logic in line 550 of connection_request),
    but the main command skips its execute_internal.
    """
    conn = _make_request_connection(connection_class)
    embedded = _make_request_connection(connection_class)

    conn._embedded_command = embedded
    embedded.execute = MagicMock()

    # Make the MAIN command's condition fail
    from jinja2 import Template

    conn._condition_template = Template("0")

    device_state = MagicMock()

    with patch.object(conn, "execute_internal", return_value=('{"result": "ok"}', True, 200)):
        result = conn.execute(
            template=None,
            value='{"modes": ["Cool"]}',
            device_state=device_state,
        )

    # In the request engines, the embedded command is executed BEFORE the main
    # command's condition check. So it SHOULD be called.
    embedded.execute.assert_called_once()
    # But the main command returns empty dict (skips execute_internal)
    assert result == {}
