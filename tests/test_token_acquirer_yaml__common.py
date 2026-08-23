# pylint: disable=protected-access,redefined-outer-name,unused-argument,not-context-manager,invalid-name,line-too-long
"""Common initialization and shared fixtures for GenericYamlTokenAcquirer."""

import ssl
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.climate_ip.token_acquirer_yaml import GenericYamlTokenAcquirer


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.api.local_ip = "192.168.1.100"
    hass.config.path.side_effect = lambda *args: "/".join(args)
    return hass


@pytest.fixture
def stream_config():
    """Mock config for stream mode (2878)."""
    return {
        "mode": "stream",
        "buffer_size": 4096,
        "reconnect_delay": 0.01,
        "tls_config": {
            "strategies": [
                {"cert": "__user_cert__", "verify_mode": "CERT_REQUIRED"},
                {"cert": "__default_cert__", "verify_mode": "CERT_NONE"},
            ],
            "ciphers": ["HIGH:!DH:!aNULL:@SECLEVEL=0"],
            "default_cert": "ac14k_m.pem",
        },
        "request_pairing": {
            "port": 2878,
            "payload": '<Request Type="GetToken" />\r\n',
            "success_template": {
                "match": 'Status="Ready"',
                "fallback_match": 'InvalidateAccount="true"',
            },
        },
        "wait_token": {"timeout_seconds": 45},
        "error_template": {"match": 'ErrorCode="301"'},
        "extract_template": {"regex": r'Token="(.*?)"'},
    }


@pytest.fixture
def listener_config():
    """Mock config for listener mode (8888)."""
    return {
        "mode": "listener",
        "buffer_size": 4096,
        "listener": {
            "port": 8889,
            "timeout_seconds": 60,
            "success_response": "HTTP/1.1 200 OK\r\n\r\n",
            "error_response": "HTTP/1.1 400 Bad Request\r\n\r\n",
        },
        "tls_config": {
            "ciphers": ["HIGH:!aNULL:!MD5:@SECLEVEL=0"],
            "default_cert": "ac14k_m.pem",
        },
        "request_pairing": {
            "port": 8888,
            "path": "/devicetoken/request",
            "headers": {"Content-Type": "application/json"},
            "payload": '{"DeviceToken":"xxxxxxxxxxx"}',
        },
        "extract_template": {"regex": r'DeviceToken[\s"\':]*([a-zA-Z0-9_\-]+)'},
    }


def test_initialization(mock_hass, stream_config):
    """Test that the acquirer initializes state variables correctly."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    assert acq.hass is mock_hass
    assert acq.ip_address == "192.168.1.100"
    assert acq.auth_config == stream_config
    assert acq.user_cert_path is None

    # Verify initial listener state
    assert not acq._token_received_event.is_set()
    assert acq._received_token is None
    assert acq._server is None

    # Verify initial stream state
    assert acq._reader is None
    assert acq._writer is None


def test_resolve_cert_path(mock_hass, stream_config):
    """Test the certificate path resolution logic."""
    # User cert path (Sentinel)
    acq1 = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path="/my/user/cert.pem"
    )
    assert acq1._resolve_cert_path("__user_cert__") == "/my/user/cert.pem"

    # Default cert path (Sentinel)
    acq2 = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    res = acq2._resolve_cert_path("__default_cert__")
    assert "ac14k_m.pem" in res
    assert "/" in res  # Should be joined with __file__

    # Absolute path directly
    assert acq2._resolve_cert_path("/absolute/path.pem") == "/absolute/path.pem"

    # Windows absolute path
    assert acq2._resolve_cert_path("C:\\windows\\path.pem") == "C:\\windows\\path.pem"

    # Relative path directly
    res_rel = acq2._resolve_cert_path("certs/relative.pem")
    assert "certs/relative.pem" in res_rel
    assert "/" in res_rel


async def test_async_close(mock_hass, stream_config):
    """Test closing active server and calling close on None."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )

    # Closing when server/writer are None (no-op)
    await acq.async_close()
    assert acq._server is None
    assert acq._writer is None

    # Closing with active server and writer
    mock_server = AsyncMock()
    mock_writer = AsyncMock()
    acq._server = mock_server
    acq._writer = mock_writer

    await acq.async_close()
    
    mock_server.close.assert_called_once()
    mock_server.wait_closed.assert_called_once()
    mock_writer.close.assert_called_once()
    mock_writer.wait_closed.assert_called_once()
    
    assert acq._server is None
    assert acq._writer is None


async def test_close_swallows_errors(mock_hass, stream_config):
    """Test that async_close handles connection reset errors cleanly."""
    acq = GenericYamlTokenAcquirer(
        mock_hass, "192.168.1.100", stream_config, cert_path=None
    )
    mock_writer = AsyncMock()
    mock_writer.wait_closed = AsyncMock(side_effect=ConnectionResetError())
    acq._writer = mock_writer

    mock_server = AsyncMock()
    mock_server.wait_closed = AsyncMock(side_effect=RuntimeError())
    acq._server = mock_server

    # Should not raise
    await acq.async_close()
    assert acq._server is None
    assert acq._writer is None
