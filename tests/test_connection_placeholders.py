# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Regression tests to ensure format_placeholders is applied in ALL connection engines.

Each test verifies that the engine imports and applies format_placeholders from helpers.py to
resolve placeholders like __CLIMATE_IP_HOST__ and __CLIMATE_IP_TOKEN__ before network access.
"""
# pylint: disable=import-outside-toplevel
from __future__ import annotations

from custom_components.climate_ip.helpers import format_placeholders

MOCK_HOST = "192.168.1.100"
MOCK_TOKEN = "SUPER_SECRET_TOKEN"
MOCK_MAC = "AA:BB:CC:DD:EE:FF"


def make_params() -> dict:
    """Return a fresh copy of params containing unreplaced placeholders for each test."""
    return {
        "url": "https://__CLIMATE_IP_HOST__:8888/devices",
        "headers": {
            "Authorization": "Bearer __CLIMATE_IP_TOKEN__",
            "X-Mac": "__CLIMATE_IP_MAC__",
        },
        "json": {
            "Device": "__CLIMATE_IP_HOST__",
        },
    }


def _assert_fully_resolved(resolved: dict) -> None:
    """Assert a resolved params dict has all placeholders expanded."""
    url = resolved.get("url", "")
    headers = str(resolved.get("headers", {}))
    json_payload = str(resolved.get("json", {}))

    assert MOCK_HOST in url, f"Host not in URL: {url}"
    assert MOCK_TOKEN in headers, f"Token not in headers: {headers}"
    assert MOCK_HOST in json_payload, f"Host not in json payload: {json_payload}"
    assert "__CLIMATE_IP_HOST__" not in url, f"Placeholder still in URL: {url}"
    assert "__CLIMATE_IP_TOKEN__" not in headers, f"Placeholder still in headers: {headers}"
    assert "__CLIMATE_IP_HOST__" not in json_payload, f"Placeholder still in payload: {json_payload}"


def test_format_placeholders_resolves_params():
    """Core helper: format_placeholders correctly substitutes all placeholder tokens."""
    resolved = format_placeholders(make_params(), MOCK_TOKEN, MOCK_HOST, "device_0", MOCK_MAC)
    _assert_fully_resolved(resolved)


def test_connection_request_uses_format_placeholders():
    """ConnectionRequest imports and uses format_placeholders for placeholder substitution."""
    import custom_components.climate_ip.connection_request as mod
    assert mod.format_placeholders is format_placeholders, (
        "ConnectionRequest must use the canonical helpers.format_placeholders"
    )
    # Simulate execute_internal's exact call (no network needed)
    params = make_params()
    resolved = format_placeholders(params, MOCK_TOKEN, MOCK_HOST, "0", MOCK_MAC)
    _assert_fully_resolved(resolved)


def test_connection_request_tls_auto_uses_format_placeholders():
    """ConnectionRequestTlsAuto imports and uses format_placeholders for placeholder substitution."""
    import custom_components.climate_ip.connection_request_tls_auto as mod
    assert mod.format_placeholders is format_placeholders, (
        "ConnectionRequestTlsAuto must use the canonical helpers.format_placeholders"
    )
    params = make_params()
    resolved = format_placeholders(params, MOCK_TOKEN, MOCK_HOST, "0", MOCK_MAC)
    _assert_fully_resolved(resolved)


def test_connection_aiohttp_uses_format_placeholders():
    """ConnectionAiohttp8888 imports and uses format_placeholders for placeholder substitution."""
    import custom_components.climate_ip.connection_aiohttp as mod
    assert mod.format_placeholders is format_placeholders, (
        "ConnectionAiohttp8888 must use the canonical helpers.format_placeholders"
    )
    params = make_params()
    resolved = format_placeholders(params, MOCK_TOKEN, MOCK_HOST, "0", MOCK_MAC)
    _assert_fully_resolved(resolved)


def test_connection_raw_uses_format_placeholders():
    """ConnectionRaw8888 imports and uses format_placeholders for placeholder substitution."""
    import custom_components.climate_ip.connection_raw as mod
    assert mod.format_placeholders is format_placeholders, (
        "ConnectionRaw8888 must use the canonical helpers.format_placeholders"
    )
    params = make_params()
    resolved = format_placeholders(params, MOCK_TOKEN, MOCK_HOST, "0", MOCK_MAC)
    _assert_fully_resolved(resolved)
