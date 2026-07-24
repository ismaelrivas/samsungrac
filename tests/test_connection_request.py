# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ConnectionRequest."""

# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests  # type: ignore[import-untyped]

from custom_components.climate_ip.connection_request import ConnectionRequest
from custom_components.climate_ip.const import CONF_CERT
from custom_components.climate_ip.exceptions import AuthError, RetryNextAttempt
from homeassistant.const import CONF_TOKEN


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
    """Test connection initialization."""
    with patch("os.path.exists", return_value=True):
        conn = ConnectionRequest(connection_config, mock_logger)
        assert conn._params[CONF_CERT].endswith("cert.pem")


def test_execute_success(connection_config, mock_logger, mock_response):
    """Test successful request execution."""
    with patch("os.path.exists", return_value=True):
        # Patch session BEFORE instantiation because __init__ creates it
        with patch("requests.sessions.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.__enter__.return_value = mock_session
            mock_session.request.return_value = mock_response

            conn = ConnectionRequest(connection_config, mock_logger)

            # Mock template
            mock_template = MagicMock()
            mock_template.render.return_value = '{"method": "GET", "url": "/test"}'

            result = conn.execute(mock_template, None, None)

            assert result == {"result": "ok"}
            mock_session.request.assert_called_once()


def test_execute_auth_error(connection_config, mock_logger):
    """Test request execution with auth error."""
    with patch("os.path.exists", return_value=True):
        # Patch session BEFORE instantiation
        with patch("requests.sessions.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.__enter__.return_value = mock_session

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

            conn = ConnectionRequest(connection_config, mock_logger)

            mock_session.request.side_effect = requests.exceptions.ConnectionError(
                "Connection failed"
            )

            mock_template = MagicMock()
            mock_template.render.return_value = '{"method": "GET", "url": "/test"}'

            with pytest.raises(RetryNextAttempt):
                conn.execute(mock_template, None, None)
