# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ConnectionRequest."""

# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests  # type: ignore[import-untyped]
from homeassistant.const import CONF_TOKEN

from custom_components.climate_ip.connection_request import ConnectionRequest
from custom_components.climate_ip.connection_request_tls_auto import (
    ConnectionRequestTlsAuto,
)
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import AuthError, RetryNextAttempt


@pytest.fixture
def mock_logger():
    """Return a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def connection_config():
    """Return a basic connection config dict."""
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}


@pytest.fixture
def mock_response():
    """Return a mock HTTP response."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"result": "ok"}
    mock.text = '{"result": "ok"}'
    mock.content = b'{"result": "ok"}'
    mock.raise_for_status = MagicMock()
    return mock


def test_initialization(connection_config, mock_logger):
    """Test connection initialization — also asserts the deprecation notice is emitted."""
    with patch("os.path.exists", return_value=True):
        with pytest.warns(DeprecationWarning, match="'request' connection method is deprecated"):
            conn = ConnectionRequest(connection_config, mock_logger)
        assert conn.is_async_native is False
        assert conn.is_push_supported is False
        assert conn._session is not None


def test_execute_success(connection_config, mock_logger, mock_response):
    """Test successful request execution."""
    with patch("os.path.exists", return_value=True):
        # Patch session BEFORE instantiation
        with patch("requests.sessions.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.__enter__.return_value = mock_session
            mock_session.request.return_value = mock_response

            with pytest.warns(DeprecationWarning, match="'request' connection method is deprecated"):
                conn = ConnectionRequest(connection_config, mock_logger)

            mock_template = MagicMock()
            mock_template.render.return_value = '{"method": "GET", "url": "/test"}'

            result = conn.execute(mock_template, None, None)
            assert result == {"result": "ok"}


def test_execute_auth_error(connection_config, mock_logger):
    """Test request execution with authentication error."""
    with patch("os.path.exists", return_value=True):
        # Patch session BEFORE instantiation
        with patch("requests.sessions.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.__enter__.return_value = mock_session

            with pytest.warns(DeprecationWarning, match="'request' connection method is deprecated"):
                conn = ConnectionRequest(connection_config, mock_logger)

            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
                response=mock_response
            )
            mock_session.request.return_value = mock_response

            mock_template = MagicMock()
            mock_template.render.return_value = '{"method": "GET", "url": "/test"}'

            with pytest.raises(AuthError):
                conn.execute(mock_template, None, None)


def test_execute_connection_error(connection_config, mock_logger):
    """Test request execution with connection error."""
    with patch("os.path.exists", return_value=True):
        # Patch session BEFORE instantiation
        with patch("requests.sessions.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.__enter__.return_value = mock_session

            with pytest.warns(DeprecationWarning, match="'request' connection method is deprecated"):
                conn = ConnectionRequest(connection_config, mock_logger)

            mock_session.request.side_effect = requests.exceptions.ConnectionError(
                "Connection failed"
            )

            mock_template = MagicMock()
            mock_template.render.return_value = '{"method": "GET", "url": "/test"}'

            with pytest.raises(RetryNextAttempt):
                conn.execute(mock_template, None, None)


# ====================================================================================
# EMBEDDED COMMAND TESTS (Migrated from test_embedded_command.py)
# ====================================================================================


def _make_request_connection(cls):
    """Create an initialized request-based connection with mocked internals.

    Wraps instantiation in pytest.warns(DeprecationWarning) so that Paranoia
    Mode (-W error::DeprecationWarning) treats the expected deprecation notice
    as a passing assertion rather than a test failure.
    """
    from unittest.mock import MagicMock, patch

    from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN

    from custom_components.climate_ip.const import CONF_CERT

    config = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_CERT: "cert.pem",
        CONF_TOKEN: "mock_token",
    }
    with patch("os.path.exists", return_value=True):
        with pytest.warns(DeprecationWarning):
            conn = cls(config, MagicMock(), MagicMock())
    return conn


@pytest.mark.skip_legacy
@pytest.mark.parametrize(
    "connection_class", [ConnectionRequest, ConnectionRequestTlsAuto]
)
def test_request_embedded_command_is_executed(connection_class):
    """Verifies that request engines execute their embedded commands by delegating."""
    from unittest.mock import MagicMock, patch

    conn = _make_request_connection(connection_class)
    embedded = _make_request_connection(connection_class)

    conn._embedded_command = embedded
    embedded.execute = MagicMock()
    device_state = MagicMock()

    with patch.object(
        conn, "execute_internal", return_value=('{"result": "ok"}', True, 200)
    ):
        conn.execute(
            template=None,
            value='{"modes": ["Cool"]}',
            device_state=device_state,
        )

    # The request engines delegate the exact same arguments down to the embedded command
    embedded.execute.assert_called_once_with(
        None, '{"modes": ["Cool"]}', device_state, None
    )


@pytest.mark.skip_legacy
@pytest.mark.parametrize(
    "connection_class", [ConnectionRequest, ConnectionRequestTlsAuto]
)
def test_request_embedded_command_skipped_when_condition_not_met(connection_class):
    """Verifies that if the main command condition is not met, the embedded command
    IS STILL executed first, but the main command skips its execute_internal.
    """
    from unittest.mock import MagicMock, patch

    from jinja2 import Template

    conn = _make_request_connection(connection_class)
    embedded = _make_request_connection(connection_class)

    conn._embedded_command = embedded
    embedded.execute = MagicMock()

    # Make the MAIN command's condition fail
    conn._condition_template = Template("0")
    device_state = MagicMock()

    with patch.object(
        conn, "execute_internal", return_value=('{"result": "ok"}', True, 200)
    ):
        result = conn.execute(
            template=None,
            value='{"modes": ["Cool"]}',
            device_state=device_state,
        )

    # The embedded command is executed BEFORE the main condition check
    embedded.execute.assert_called_once()
    assert result == {}
