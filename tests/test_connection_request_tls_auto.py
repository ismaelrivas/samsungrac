# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for ConnectionRequestTlsAuto."""

# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name
import logging
from unittest.mock import ANY, MagicMock, patch

import pytest
from homeassistant.const import CONF_TOKEN

from custom_components.climate_ip.connection_request_tls_auto import (
    ConnectionRequestTlsAuto,
    SamsungHTTPAdapter,
)
from custom_components.climate_ip.const import CONF_CERT


@pytest.fixture
def mock_logger():
    """Create a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def connection_config():
    """Return a minimal connection config dict."""
    return {CONF_TOKEN: "test_token", CONF_CERT: "cert.pem"}


def test_initialization(connection_config, mock_logger):
    """Test connection initialization — also asserts the deprecation notice is emitted."""
    with patch("os.path.exists", return_value=True):
        with pytest.warns(DeprecationWarning, match="'request_tls_auto' connection method is deprecated"):
            conn = ConnectionRequestTlsAuto(connection_config, mock_logger)
        assert conn._params[CONF_CERT].endswith("cert.pem")


def test_samsung_http_adapter_init():
    """Test SamsungHTTPAdapter initialization."""
    adapter = SamsungHTTPAdapter()
    with patch("ssl.create_default_context") as mock_create_context:
        mock_context = MagicMock()
        mock_create_context.return_value = mock_context

        adapter.init_poolmanager(10, 10)

        mock_context.set_ciphers.assert_called_with("ALL:@SECLEVEL=0")
        assert mock_context.check_hostname is False


def test_execute_success(connection_config, mock_logger):
    """Test successful request execution."""
    with patch("os.path.exists", return_value=True):
        with pytest.warns(DeprecationWarning, match="'request_tls_auto' connection method is deprecated"):
            conn = ConnectionRequestTlsAuto(connection_config, mock_logger)

        with patch("requests.sessions.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.__enter__.return_value = mock_session

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "ok"}
            mock_response.content = b'{"result": "ok"}'
            mock_response.raise_for_status = MagicMock()
            mock_session.request.return_value = mock_response

            mock_template = MagicMock()
            mock_template.render.return_value = '{"method": "GET", "url": "/test"}'

            result = conn.execute(mock_template, None, None)

            assert result == {"result": "ok"}
            mock_session.mount.assert_not_called()  # insecure_ssl is False by default


def test_execute_insecure_ssl(connection_config, mock_logger):
    """Test request execution with insecure_ssl=True."""
    with patch("os.path.exists", return_value=True):
        with pytest.warns(DeprecationWarning, match="'request_tls_auto' connection method is deprecated"):
            conn = ConnectionRequestTlsAuto(
                connection_config, mock_logger, insecure_ssl=True
            )

        with patch("requests.sessions.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.__enter__.return_value = mock_session

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "ok"}
            mock_response.content = b'{"result": "ok"}'
            mock_session.request.return_value = mock_response

            mock_template = MagicMock()
            mock_template.render.return_value = '{"method": "GET", "url": "/test"}'

            conn.execute(mock_template, None, None)

            mock_session.mount.assert_called_with("https://", ANY)
