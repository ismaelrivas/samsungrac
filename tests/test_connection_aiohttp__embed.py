# pylint: disable=protected-access,redefined-outer-name,duplicate-code,import-outside-toplevel,missing-docstring,line-too-long
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_TOKEN

from custom_components.climate_ip.connection_aiohttp import ConnectionAiohttp8888
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import CannotConnect


@pytest.fixture
def connection_config():
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}


@pytest.fixture
def mock_logger():
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


@pytest.fixture
def mock_session():
    import aiohttp

    return MagicMock(spec=aiohttp.ClientSession)


async def test_async_execute_with_embedded_command_condition_met(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        # Mock main command execution
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.version = MagicMock(major=1, minor=1)

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        # Setup embedded command
        embedded_mock = AsyncMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=True)
        embedded_mock.params = {"url": "/embedded", "method": "GET"}
        embedded_mock.connection_template = None
        embedded_mock.async_execute = AsyncMock()

        conn._embedded_command = embedded_mock

        await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        embedded_mock.async_execute.assert_called_once()


async def test_async_execute_with_embedded_command_condition_not_met(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.version = MagicMock(major=1, minor=1)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        embedded_mock = AsyncMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=False)
        embedded_mock.params = {}
        embedded_mock.connection_template = None
        conn._embedded_command = embedded_mock

        await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        embedded_mock.async_execute.assert_not_called()


async def test_async_execute_with_embedded_command_no_condition(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.version = MagicMock(major=1, minor=1)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        embedded_mock = MagicMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=True)
        embedded_mock.params = {"url": "/embedded"}
        embedded_mock.connection_template = None
        embedded_mock.async_execute = AsyncMock()
        conn._embedded_command = embedded_mock

        await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        embedded_mock.async_execute.assert_called_once()


async def test_async_execute_main_condition_not_met(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        conn.check_execute_condition = MagicMock(return_value=False)

        res_text, headers = await conn.async_execute(
            "GET", "/main", data=None, headers={}, device_state={"some": "state"}
        )

        assert res_text == "{}"
        assert headers == {}


async def test_async_execute_embedded_command_strict(
    connection_config, mock_logger, mock_hass, mock_session
):
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        # Main mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"result": "ok"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.version = MagicMock(major=1, minor=1)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        # Create embedded command
        embed_conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        embed_conn._params = {
            "method": "POST",
            "url": "/embedded_endpoint",
            "json": {"action": "test"},
        }
        embed_conn.async_execute = AsyncMock(
            return_value=('{"result": "embedded"}', {})
        )
        embed_conn.check_execute_condition = MagicMock(return_value=True)

        # Attach embedded command with a condition that always evaluates to True
        conn._embedded_command = embed_conn
        embed_conn.condition_template = MagicMock()
        embed_conn.condition_template.async_render = AsyncMock(return_value="True")

        await conn.async_execute("GET", "/main", None, {}, device_state={})

        # Verify embedded async_execute was called with ITS exact parameters
        embed_conn.async_execute.assert_called_once_with(
            method="POST",
            url="/embedded_endpoint",
            data='{"action":"test"}',
            headers={},
            device_state={},
        )


async def test_execute_embedded_command_connection_error_logs_warning_and_raises(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Kill mutant at L881 (warn_msg = None on embedded command CannotConnect/AuthError)."""
    with (
        patch("os.path.exists", return_value=True),
        patch("custom_components.climate_ip.connection_aiohttp._LOGGER") as mock_module_logger,
    ):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        embedded_mock = MagicMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=True)
        embedded_mock.params = {"url": "/embedded"}
        embedded_mock.connection_template = None
        error = CannotConnect("API Failure")
        embedded_mock.async_execute = AsyncMock(side_effect=error)
        conn._embedded_command = embedded_mock

        with pytest.raises(CannotConnect):
            await conn.async_execute(
                "GET", "/main", data=None, headers={}, device_state={"some": "state"}
            )

        mock_module_logger.warning.assert_called_with(
            "%s [async_execute] Embedded command failed due to connection error: %s",
            conn.log_prefix,
            error,
        )


def test_set_controller_ref_propagates_to_embedded(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test set_controller_ref sets controller on self and embedded command."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        embedded_mock = MagicMock()
        conn._embedded_command = embedded_mock

        mock_controller = MagicMock()
        mock_controller.unique_id = "test_ac"
        mock_controller.log_prefix = "[test_ac]"

        conn.set_controller_ref(mock_controller)

        assert conn._controller is mock_controller
        embedded_mock.set_controller_ref.assert_called_once_with(mock_controller)


async def test_execute_embedded_command_device_state_none(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test embedded command is skipped when device_state is None."""
    with (
        patch("os.path.exists", return_value=True),
        patch("custom_components.climate_ip.connection_aiohttp._LOGGER") as mock_module_logger,
    ):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        embedded_mock = MagicMock()
        embedded_mock.async_execute = AsyncMock()
        conn._embedded_command = embedded_mock

        mock_response = AsyncMock(status=200, headers={"Content-Type": "application/json"})
        mock_response.text.return_value = "{}"
        mock_response.version = MagicMock(major=1, minor=1)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_session.request.return_value = mock_context

        await conn.async_execute("GET", "/main", data=None, headers={}, device_state=None)

        embedded_mock.async_execute.assert_not_called()
        mock_module_logger.warning.assert_called_with(
            "%s [async_execute] Embedded command found, but cannot check its condition (device_state is missing). Skipping.",
            conn.log_prefix,
        )


async def test_execute_embedded_command_network_error(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test aiohttp.ClientError in embedded command raises CannotConnect."""
    import aiohttp

    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        embedded_mock = MagicMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=True)
        embedded_mock.params = {"url": "/embedded"}
        embedded_mock.connection_template = None
        embedded_mock.async_execute = AsyncMock(side_effect=aiohttp.ClientError("Socket dropped"))
        conn._embedded_command = embedded_mock

        with pytest.raises(CannotConnect) as exc_info:
            await conn.async_execute(
                "GET", "/main", data=None, headers={}, device_state={"some": "state"}
            )
        assert "Embedded command network error" in str(exc_info.value)


async def test_execute_embedded_command_parsing_error(
    connection_config, mock_logger, mock_hass, mock_session
):
    """Test ValueError during embedded template parsing raises CannotConnect."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionAiohttp8888(
            connection_config, mock_logger, mock_hass, mock_session, "192.168.1.100"
        )
        conn._shared_state.initialized = True
        conn._try_connection = AsyncMock()

        embedded_mock = MagicMock()
        embedded_mock.check_execute_condition = MagicMock(return_value=True)
        embedded_mock.params = {}
        mock_tmpl = MagicMock()
        mock_tmpl.async_render.return_value = "invalid json {["
        embedded_mock.connection_template = mock_tmpl
        conn._embedded_command = embedded_mock

        with pytest.raises(CannotConnect) as exc_info:
            await conn.async_execute(
                "GET", "/main", data=None, headers={}, device_state={"some": "state"}
            )
        assert "Embedded command parsing error" in str(exc_info.value)
