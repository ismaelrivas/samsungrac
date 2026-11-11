"""Canonical orthogonal tests for climate_ip helpers."""

import asyncio
import http.client
import importlib
import io
import os
from pathlib import Path
import ssl
import sys
import threading
from unittest.mock import AsyncMock, MagicMock, patch

from icmplib import NameLookupError, SocketPermissionError
import pytest
import urllib3.connection as connection_mod
from urllib3.exceptions import HeaderParsingError
import urllib3.util.response as response_util

from custom_components.climate_ip import helpers
from custom_components.climate_ip.const import (
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    PORT_SAMSUNG_2878,
    PORT_SAMSUNG_8888,
)
from custom_components.climate_ip.helpers import (
    ICMPSocketError,
    SecureTreeBuilder,
    _can_use_icmp_privileged,
    async_check_network_reachability,
    async_create_samsung_ssl_context,
    async_force_arp_update,
    async_get_mac_address,
    async_get_network_diagnostics,
    create_samsung_ssl_context,
    find_key_in_data,
    format_placeholders,
    format_poll_interval,
    get_last_network_diagnostic,
    get_tls_version_name,
    get_value_by_path,
    mask_sensitive_data,
    parse_entity_category,
    resolve_cert_path,
    safe_xml_to_dict,
    set_value_by_path,
    stream_wrapper,
    tolerant_header_parsing,
    validate_poll_interval,
)
from homeassistant.const import EntityCategory


def test_sanitize_token() -> None:
    """Validate token sanitization against injection and length bounds."""
    assert helpers.sanitize_token(None) is None
    assert helpers.sanitize_token("") is None
    assert helpers.sanitize_token('my"evil{{token') is None
    assert helpers.sanitize_token("abcd123") is None
    assert helpers.sanitize_token("abcd1234") == "abcd1234"
    assert helpers.sanitize_token("a" * 128) == "a" * 128
    assert helpers.sanitize_token("a" * 129) is None


def test_parse_entity_category() -> None:
    """Validate string conversion to HomeAssistant EntityCategory."""
    assert parse_entity_category("config") == EntityCategory.CONFIG
    assert parse_entity_category("diagnostic") == EntityCategory.DIAGNOSTIC
    assert parse_entity_category(None) is None
    assert parse_entity_category("invalid_category") is None


def test_safe_xml_to_dict_and_secure_builder() -> None:
    """Validate XML parsing, list conversions, mixed text, and DOCTYPE security."""
    builder = SecureTreeBuilder()
    with pytest.raises(ValueError, match="DOCTYPE declarations strictly prohibited"):
        builder.doctype("foo", None, None)

    # Valid Samsung response
    xml = '<Response Type="DeviceState"><Device><Attr id="Wind" value="Auto"/></Device></Response>'
    res = safe_xml_to_dict(xml)
    assert res["Response"]["@Type"] == "DeviceState"
    assert res["Response"]["Device"]["Attr"]["@id"] == "Wind"

    # Sibling list conversion & attributes with text
    xml_list = "<root><item>1</item><item>2</item><val id='5'>hello</val></root>"
    res_list = safe_xml_to_dict(xml_list)
    assert res_list == {
        "root": {"item": ["1", "2"], "val": {"@id": "5", "#text": "hello"}}
    }

    # Mixed content with child elements and text
    xml_mixed = "<parent>leading_text<child>val</child></parent>"
    assert safe_xml_to_dict(xml_mixed) == {
        "parent": {"child": "val", "#text": "leading_text"}
    }

    # Malformed & invalid inputs
    assert safe_xml_to_dict("<bad_xml <missing_close") == {}
    assert safe_xml_to_dict("") == {}
    assert safe_xml_to_dict("   ") == {}
    assert safe_xml_to_dict(["<root></root>"]) == {}
    assert safe_xml_to_dict(12345) == {}

    # Security: Billion laughs and DOCTYPE injection detection
    malicious = '<!DOCTYPE b [ <!ENTITY a "x"> <!ENTITY b "&a;&a;"> ]><S>&b;</S>'
    assert safe_xml_to_dict(malicious) == {}

    with patch("custom_components.climate_ip.helpers._LOGGER.error") as mock_log:
        assert safe_xml_to_dict("<!doctype html><root>bypass</root>") == {}
        mock_log.assert_called_once_with(
            "XML Payload rejected: DOCTYPE injection attempt detected"
        )

    # Layer 2 defense if Layer 1 bypassed
    with patch("custom_components.climate_ip.helpers.re.search", return_value=None):
        assert safe_xml_to_dict("<!DOCTYPE dummy><root>123</root>") == {}

    # ValueError from fromstring handled gracefully
    with patch(
        "xml.etree.ElementTree.fromstring", side_effect=ValueError("Security violation")
    ):
        assert safe_xml_to_dict("<root>test</root>") == {}


def test_tolerant_header_parsing() -> None:
    """Validate urllib3 header parsing monkey-patch context manager and lifecycle."""
    orig_response = response_util.assert_header_parsing
    orig_conn = connection_mod.assert_header_parsing
    orig_parse = http.client.parse_headers

    # Refcount lifecycle and patching
    assert helpers._HEADER_PATCH_REFCOUNT == 0
    with tolerant_header_parsing():
        assert helpers._HEADER_PATCH_REFCOUNT == 1
        assert response_util.assert_header_parsing is not orig_response
        assert connection_mod.assert_header_parsing is not orig_conn
        assert http.client.parse_headers is not orig_parse

        with tolerant_header_parsing():
            assert helpers._HEADER_PATCH_REFCOUNT == 2
        assert helpers._HEADER_PATCH_REFCOUNT == 1

        # Strict forwarding to original response assert
        mock_orig = MagicMock()
        old_orig = helpers._HEADER_PATCH_ORIGINAL_RESPONSE
        setattr(helpers, "_HEADER_PATCH_ORIGINAL_RESPONSE", mock_orig)
        try:
            test_headers = http.client.HTTPMessage()
            connection_mod.assert_header_parsing(test_headers)
            mock_orig.assert_called_once_with(test_headers)
        finally:
            setattr(helpers, "_HEADER_PATCH_ORIGINAL_RESPONSE", old_orig)

        # Deep execution of _patched_parse_headers
        raw_headers = io.BytesIO(
            b"Content-Type : application/json\r\nHost: example.com\r\n\r\n"
        )
        parsed = http.client.parse_headers(raw_headers)
        assert parsed.get("Content-Type") == "application/json"

        long_line = io.BytesIO(b"A" * 70000 + b"\r\n\r\n")
        with pytest.raises(http.client.LineTooLong):
            http.client.parse_headers(long_line)

        many_headers = io.BytesIO(
            b"".join(f"H{i}: 1\r\n".encode() for i in range(105)) + b"\r\n"
        )
        with pytest.raises(
            http.client.HTTPException, match="got more than 100 headers"
        ):
            http.client.parse_headers(many_headers)

        # Line 192: when _HEADER_PATCH_ORIGINAL_PARSE_HEADERS is None
        old_parse_orig = helpers._HEADER_PATCH_ORIGINAL_PARSE_HEADERS
        setattr(helpers, "_HEADER_PATCH_ORIGINAL_PARSE_HEADERS", None)
        try:
            assert http.client.parse_headers(io.BytesIO(b"Host: test\r\n\r\n")) is None
        finally:
            setattr(helpers, "_HEADER_PATCH_ORIGINAL_PARSE_HEADERS", old_parse_orig)

    # Error suppression
    def failing_assert(headers):
        raise HeaderParsingError(defects="bad header", unparsed_data="data")

    real_assert = response_util.assert_header_parsing
    response_util.assert_header_parsing = failing_assert
    try:
        with tolerant_header_parsing():
            response_util.assert_header_parsing("test_headers")
    finally:
        response_util.assert_header_parsing = real_assert

    assert helpers._HEADER_PATCH_REFCOUNT == 0
    assert response_util.assert_header_parsing is orig_response
    assert connection_mod.assert_header_parsing is orig_conn
    assert http.client.parse_headers is orig_parse

    # Restored after exception
    with pytest.raises(ValueError, match="Simulated error"), tolerant_header_parsing():
        raise ValueError("Simulated error")
    assert response_util.assert_header_parsing is orig_response

    # Thread safety
    def worker():
        with tolerant_header_parsing():
            pass

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert response_util.assert_header_parsing is orig_response


def test_find_key_in_data() -> None:
    """Validate recursive traversal in find_key_in_data across dicts and lists."""
    assert find_key_in_data({"a": 1, "b": 2}, "b") == 2
    assert (
        find_key_in_data({"level1": {"level2": {"target": "found"}}}, "target")
        == "found"
    )
    assert find_key_in_data([{"other": 1}, {"target": 99}], "target") == 99
    assert (
        find_key_in_data(
            {"Devices": [{"Temperatures": [{"current": 22.0}]}]}, "current"
        )
        == 22.0
    )
    assert find_key_in_data({"a": 1}, "missing") is None
    assert find_key_in_data({}, "any") is None
    assert find_key_in_data([], "any") is None
    assert find_key_in_data({"exists": None}, "exists") is None
    assert find_key_in_data(
        {"a": {"target": "first"}, "b": {"target": "second"}}, "target"
    ) in (
        "first",
        "second",
    )


def test_get_value_by_path() -> None:
    """Validate get_value_by_path with list/dot paths and resilient edge handling."""
    data = {"level1": {"level2": {"level3": "target_value"}}}
    assert get_value_by_path(data, ["level1", "level2", "level3"]) == "target_value"
    assert get_value_by_path(data, ["level1", "wrong_level"]) is None
    assert get_value_by_path(data, []) is None
    assert get_value_by_path(None, ["level1"]) is None
    assert get_value_by_path({"level1": "not_a_dict"}, ["level1", "level2"]) is None

    # Dot-separated paths
    dot_data = {"Devices": {"0": {"Temperatures": 23.5}}}
    assert get_value_by_path(dot_data, "Devices.0.Temperatures") == 23.5
    assert get_value_by_path(dot_data, "Devices.0.Humidity") is None

    # List index traversals
    assert get_value_by_path({"items": ["zero", "one", "two"]}, ["items", 1]) == "one"
    assert get_value_by_path([{"id": 42}], [0, "id"]) == 42
    assert get_value_by_path([[0, 1], [2, 3]], [1, 0]) == 2

    # Cross-type and out-of-bound protections
    assert get_value_by_path(["item"], ["item"]) is None
    assert get_value_by_path({0: "val"}, [0]) is None
    assert get_value_by_path({"k": "v"}, [0]) is None
    assert get_value_by_path([1, 2], ["0"]) is None
    assert get_value_by_path([10, 20], [-1]) is None
    assert get_value_by_path([10, 20], [2]) is None
    assert get_value_by_path([10, 20], [100]) is None
    assert get_value_by_path({"a": 1}, ["a", "b"]) is None
    assert get_value_by_path({"a": [10, 20]}, ["a", -1]) is None
    assert get_value_by_path({"a": [10, 20]}, ["a", 2]) is None


def test_set_value_by_path() -> None:
    """Validate set_value_by_path for dicts, list auto-padding, and boundary protections."""
    # Falsy targets abort
    d_empty = {}
    set_value_by_path(d_empty, ["a"], 1)
    assert d_empty == {}

    l_empty = []
    set_value_by_path(l_empty, [0], 1)
    assert l_empty == []

    # Dict operations
    d = {"base": True}
    set_value_by_path(d, ["a"], 1)
    assert d["a"] == 1
    set_value_by_path(d, ["b", "c"], 2)
    assert d["b"]["c"] == 2
    set_value_by_path(d, ["b", "d"], 3)
    assert d["b"] == {"c": 2, "d": 3}
    d["null_node"] = None
    set_value_by_path(d, ["null_node", "e"], 4)
    assert d["null_node"]["e"] == 4

    # Dot-separated paths
    target_dot = {"Devices": {"0": {"Temperatures": 20.0}}}
    set_value_by_path(target_dot, "Devices.0.Temperatures", 25.0)
    assert target_dot["Devices"]["0"]["Temperatures"] == 25.0

    # List padding & root list
    d_list = {"l": ["first"]}
    set_value_by_path(d_list, ["l", 2], "third")
    assert d_list["l"] == ["first", None, "third"]
    set_value_by_path(d_list, ["l", 1], "second")
    assert d_list["l"] == ["first", "second", "third"]

    root_list = ["init"]
    set_value_by_path(root_list, [2], "b")
    assert root_list == ["init", None, "b"]
    set_value_by_path(root_list, [1, "sub"], "a")
    assert root_list[1] == {"sub": "a"}

    # Intermediate list extensions
    target_inter = {"l": []}
    set_value_by_path(target_inter, ["l", 0, "a"], "val")
    assert target_inter == {"l": [{"a": "val"}]}

    target_inter_root = ["init"]
    set_value_by_path(target_inter_root, [1, 0], "nested_val")
    assert target_inter_root == ["init", ["nested_val"]]

    target_none_elem = [None, "existing"]
    set_value_by_path(target_none_elem, [0, "k"], "v")
    assert target_none_elem == [{"k": "v"}, "existing"]

    target_none_dict = {"node": None}
    set_value_by_path(target_none_dict, ["node", "leaf"], 10)
    assert target_none_dict == {"node": {"leaf": 10}}

    # Alternating keys
    target_alt = {"base": True}
    set_value_by_path(target_alt, ["a", "b", 0, "c"], "val")
    assert target_alt == {"base": True, "a": {"b": [{"c": "val"}]}}

    # Terminal list extensions
    target_term = [10]
    set_value_by_path(target_term, [1], 20)
    assert target_term == [10, 20]

    target_nested_term = {"l": [10]}
    set_value_by_path(target_nested_term, ["l", 1], 20)
    assert target_nested_term == {"l": [10, 20]}

    # Terminal type mismatches & invalid paths
    d_mismatch = {"node": {}}
    set_value_by_path(d_mismatch, ["node", 0], 123)
    assert d_mismatch == {"node": {}}

    l_mismatch = {"node": []}
    set_value_by_path(l_mismatch, ["node", "invalid"], 123)
    assert l_mismatch == {"node": []}

    d_invalid = {"l": []}
    set_value_by_path(d_invalid, ["l", "invalid_key", "x"], 10)
    assert d_invalid["l"] == []


def test_resolve_cert_path() -> None:
    """Validate certificate resolution across relative, absolute, and HA paths."""
    assert resolve_cert_path(None, "/base/dir") is None
    abs_path = "/config/climate_ip/ac14k_m.pem"
    assert resolve_cert_path(abs_path, "/base/dir") == abs_path

    # Relative path without hass
    res_rel = resolve_cert_path("ac14k_m.pem", "/base/dir")
    assert os.path.normpath(res_rel) == os.path.normpath("/base/dir/ac14k_m.pem")

    # Empty base dir resolves to component directory
    res_no_base = resolve_cert_path("ac14k_m.pem", base_dir="")
    assert res_no_base == str(Path(helpers.__file__).parent / "ac14k_m.pem")

    # Windows backslash without hass
    res_win = resolve_cert_path("certs\\ac14k_m.pem", "/base/dir")
    assert res_win == str(Path("certs\\ac14k_m.pem"))

    # With hass
    mock_hass = MagicMock()
    mock_hass.config.path.return_value = "/ha/config/my_cert.pem"

    res_hass_slash = resolve_cert_path(
        "subdir/my_cert.pem", "/base/dir", hass=mock_hass
    )
    assert res_hass_slash == "/ha/config/my_cert.pem"
    mock_hass.config.path.assert_called_with("subdir/my_cert.pem")

    res_hass_win = resolve_cert_path("subdir\\my_cert.pem", "/base/dir", hass=mock_hass)
    assert res_hass_win == "/ha/config/my_cert.pem"
    mock_hass.config.path.assert_called_with("subdir\\my_cert.pem")

    # Filename only with hass points to component directory
    res_hass_fname = resolve_cert_path("ac14k_m.pem", "/base/dir", hass=mock_hass)
    assert res_hass_fname == str(Path(helpers.__file__).parent / "ac14k_m.pem")

    # Broken hass object raises AttributeError
    class FaultyHass:
        @property
        def config(self):
            raise AttributeError("No config")

    with pytest.raises(AttributeError, match="No config"):
        resolve_cert_path("subdir/my_cert.pem", "/base/dir", hass=FaultyHass())


def test_format_placeholders() -> None:
    """Validate placeholder replacement in strings, URLs, dicts, and lists."""
    template = "Token:__CLIMATE_IP_TOKEN__, Host:__CLIMATE_IP_HOST__, Mac:__CLIMATE_IP_MAC__, ID:__DEVICE_ID__"
    assert (
        stream_wrapper(
            template, "my_tok", "192.168.1.10", "dev_123", "00:11:22:33:44:55"
        )
        == "Token:my_tok, Host:192.168.1.10, Mac:00:11:22:33:44:55, ID:dev_123"
    )

    url_data = "http://__CLIMATE_IP_HOST__/test?token=__CLIMATE_IP_TOKEN__&mac=__CLIMATE_IP_MAC__&id=__DEVICE_ID__"
    assert (
        stream_wrapper(url_data, "my_tok", "1.1.1.1", "dev123", "AA:BB")
        == "http://1.1.1.1/test?token=my_tok&mac=AA:BB&id=dev123"
    )

    assert (
        stream_wrapper("Token:__CLIMATE_IP_TOKEN__", None, None, None)
        == "Token:__CLIMATE_IP_TOKEN__"
    )

    data = {
        "key1": "Host:__CLIMATE_IP_HOST__",
        "key2": [
            "Token:__CLIMATE_IP_TOKEN__",
            {"nested": "ID:__DEVICE_ID__"},
            "Mac:__CLIMATE_IP_MAC__",
            "Host:__CLIMATE_IP_HOST__",
        ],
        "key3": 42,
        "key4": "Mac:__CLIMATE_IP_MAC__",
    }
    result = format_placeholders(data, "tok", "1.1.1.1", "dev_id", "11:22:33:44:55:66")
    assert result["key1"] == "Host:1.1.1.1"
    assert result["key2"][0] == "Token:tok"
    assert result["key2"][1]["nested"] == "ID:dev_id"
    assert result["key2"][2] == "Mac:11:22:33:44:55:66"
    assert result["key2"][3] == "Host:1.1.1.1"
    assert result["key3"] == 42
    assert result["key4"] == "Mac:11:22:33:44:55:66"


@pytest.mark.asyncio
async def test_tls_version_and_ssl_context() -> None:
    """Validate TLS naming and SSL context configuration."""
    assert get_tls_version_name(0) == "Unknown"
    assert get_tls_version_name(9999) == "9999"
    if hasattr(ssl, "TLSVersion") and hasattr(ssl.TLSVersion, "TLSv1_2"):
        assert (
            get_tls_version_name(ssl.TLSVersion.TLSv1_2) == ssl.TLSVersion.TLSv1_2.name
        )

    # Default SSL Context
    ctx = create_samsung_ssl_context()
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False
    assert ctx.maximum_version == ssl.TLSVersion.TLSv1_2

    # Verify mode branch (covers line 417)
    ctx_req = create_samsung_ssl_context(verify_mode=ssl.CERT_REQUIRED)
    assert ctx_req.verify_mode == ssl.CERT_REQUIRED

    # Bad cert path raises
    with pytest.raises((ssl.SSLError, OSError, FileNotFoundError)):
        create_samsung_ssl_context(cert_path="/nonexistent/cert.pem")

    # Valid cert path loading (covers line 442)
    mock_ctx = MagicMock(spec=ssl.SSLContext)
    with (
        patch("ssl.SSLContext", return_value=mock_ctx),
        patch("os.path.isfile", return_value=True),
    ):
        ctx_loaded = create_samsung_ssl_context(cert_path="/valid/cert.pem")
        assert ctx_loaded is mock_ctx
        mock_ctx.load_verify_locations.assert_called_once_with(cafile="/valid/cert.pem")
        mock_ctx.load_cert_chain.assert_called_once_with("/valid/cert.pem")

    # Version setting exceptions caught gracefully
    mock_ctx_err = MagicMock()
    type(mock_ctx_err).maximum_version = property(
        fget=lambda self: ssl.TLSVersion.TLSv1_2,
        fset=MagicMock(side_effect=AttributeError("Max version unsupported")),
    )
    type(mock_ctx_err).minimum_version = property(
        fget=lambda self: ssl.TLSVersion.TLSv1,
        fset=MagicMock(side_effect=AttributeError("Min version unsupported")),
    )
    with patch("ssl.SSLContext", return_value=mock_ctx_err):
        assert create_samsung_ssl_context() is mock_ctx_err

    # Async factory
    async_ctx = await async_create_samsung_ssl_context(is_server=False)
    assert isinstance(async_ctx, ssl.SSLContext)
    assert async_ctx.check_hostname is False
    assert async_ctx.verify_mode == ssl.CERT_NONE


def test_mask_sensitive_data() -> None:
    """Validate sensitive payload masking across dicts, lists, regexes, and scalars."""
    raw_data = {
        "Authorization": "Bearer 123",
        "unique_id": "uid_12345",
        "DeviceToken": "dtok_123",
        "DUID": "duid_12",
        "device_id": "12345678",
        "uuid": "1234567",
        "token": "123456",
        "mac": "AABBCCDDEEFF",
        "nested_limits": {
            "mac": "1234567",
            "device_id": "123456",
            "token": "12345",
            "uuid": "1234",
            "DUID": "123",
        },
        "normal_key": "visible",
    }
    masked = mask_sensitive_data(raw_data)
    assert masked["Authorization"] == "***er 123"
    assert masked["unique_id"] == "***_12345"
    assert masked["DeviceToken"] == "***ok_123"
    assert masked["DUID"] == "***uid_12"
    assert masked["device_id"] == "***345678"
    assert masked["uuid"] == "***234567"
    assert masked["token"] == "***3456"
    assert masked["mac"] == "***DDEEFF"
    assert masked["nested_limits"]["mac"] == "***234567"
    assert masked["nested_limits"]["device_id"] == "***3456"
    assert masked["nested_limits"]["token"] == "***2345"
    assert masked["nested_limits"]["uuid"] == "1234"
    assert masked["nested_limits"]["DUID"] == "123"
    assert masked["normal_key"] == "visible"

    # List masking
    assert mask_sensitive_data([{"token": "12345678"}]) == [{"token": "***345678"}]

    # Regex masking on string payloads
    assert mask_sensitive_data('DUID="1234567890"') == 'DUID="***567890"'
    assert mask_sensitive_data('DUID="123456"') == 'DUID="***"'
    assert mask_sensitive_data('DUID="1234567"') == 'DUID="***234567"'
    assert mask_sensitive_data('duid="1234567890"') == 'duid="***567890"'
    assert (
        mask_sensitive_data('Token="12345678-1234-1234-1234-123456789012"')
        == 'Token="***"'
    )
    assert mask_sensitive_data('DeviceToken="secret123"') == 'DeviceToken="***"'

    # Scalar passthrough (covers line 512)
    assert mask_sensitive_data(12345) == 12345
    assert mask_sensitive_data(None) is None


def test_can_use_icmp_privileged() -> None:
    """Validate dynamic ICMP socket privilege check and caching."""
    # Library not available
    with patch.object(helpers, "_ICMPLIB_AVAILABLE", False):
        _can_use_icmp_privileged.cache_clear()
        assert _can_use_icmp_privileged() is False

    # Ping succeeds with privileged=True
    with patch("icmplib.ping", return_value=MagicMock()) as mock_ping_sync:
        _can_use_icmp_privileged.cache_clear()
        assert _can_use_icmp_privileged() is True
        mock_ping_sync.assert_called_once_with(
            "127.0.0.1", count=0, timeout=0, privileged=True
        )

    # Ping raises exception
    with patch("icmplib.ping", side_effect=Exception("Root privileges required")):
        _can_use_icmp_privileged.cache_clear()
        assert _can_use_icmp_privileged() is False

    _can_use_icmp_privileged.cache_clear()
    with patch("icmplib.ping", side_effect=Exception("Root privileges required")):
        _can_use_icmp_privileged()


def test_get_last_network_diagnostic() -> None:
    """Validate get_last_network_diagnostic host cleaning and retrieval."""
    assert get_last_network_diagnostic(None) is None
    assert get_last_network_diagnostic("") is None
    assert get_last_network_diagnostic(12345) is None
    assert get_last_network_diagnostic([1, 2, 3]) is None

    diag = {"is_reachable": True, "status": "alive"}
    last_diags = helpers._LAST_NETWORK_DIAGNOSTICS
    last_diags["192.168.1.50"] = dict(diag)
    last_diags["fe80::1"] = dict(diag)
    last_diags["fe80:1"] = dict(diag)
    last_diags["192.168.1.50]"] = dict(diag)
    last_diags["[192.168.1.50"] = dict(diag)

    assert get_last_network_diagnostic("http://192.168.1.50/api/v1") == diag
    assert get_last_network_diagnostic("http://192.168.1.50/status") == diag
    assert get_last_network_diagnostic("192.168.1.50:2878") == diag
    assert get_last_network_diagnostic("[fe80::1]:8080") == diag
    assert get_last_network_diagnostic("[fe80:1]") == diag
    assert get_last_network_diagnostic("192.168.1.50]") == diag
    assert get_last_network_diagnostic("[192.168.1.50") == diag
    assert get_last_network_diagnostic("fe80::1") == diag


@pytest.mark.asyncio
async def test_async_check_network_reachability() -> None:
    """Validate async_check_network_reachability states, types, and host cleaning matrix."""
    mock_host = MagicMock()
    mock_host.is_alive = True
    mock_host.avg_rtt = 10

    with (
        patch(
            "custom_components.climate_ip.helpers._can_use_icmp_privileged",
            return_value=False,
        ),
        patch(
            "custom_components.climate_ip.helpers.async_ping", return_value=mock_host
        ) as mock_ping,
    ):
        # Host is alive
        assert await async_check_network_reachability("192.168.1.100") is True
        assert mock_ping.call_args.kwargs == {
            "address": "192.168.1.100",
            "count": 1,
            "timeout": 2.0,
            "interval": 0.2,
            "privileged": False,
        }
        assert isinstance(mock_ping.call_args.kwargs["address"], str)
        assert isinstance(mock_ping.call_args.kwargs["count"], int)
        assert isinstance(mock_ping.call_args.kwargs["timeout"], float)
        assert isinstance(mock_ping.call_args.kwargs["interval"], float)
        assert isinstance(mock_ping.call_args.kwargs["privileged"], bool)

        rec_alive = get_last_network_diagnostic("192.168.1.100")
        assert rec_alive is not None
        assert rec_alive["is_reachable"] is True
        assert rec_alive["status"] == "alive"

        # Host is dead
        mock_host.is_alive = False
        assert await async_check_network_reachability("192.168.1.100") is False

        # Permission bypass (OSError)
        mock_ping.side_effect = OSError("Permission denied")
        assert await async_check_network_reachability("192.168.1.100") is True

        # Permission bypass (SocketPermissionError)
        mock_ping.side_effect = SocketPermissionError(privileged=False)
        assert await async_check_network_reachability("192.168.1.100") is True

        # Socket error fails
        mock_ping.side_effect = ICMPSocketError("Mocked socket error")
        assert await async_check_network_reachability("192.168.1.201") is False
        rec_fail = get_last_network_diagnostic("192.168.1.201")
        assert rec_fail is not None
        assert rec_fail["is_reachable"] is False
        assert rec_fail["status"] == "socket_error"

    # Missing library fallback
    orig_ping = helpers.async_ping
    helpers.async_ping = None
    try:
        assert await async_check_network_reachability("192.168.1.100") is True
    finally:
        helpers.async_ping = orig_ping

    # Privileged flag passed through
    with (
        patch(
            "custom_components.climate_ip.helpers._can_use_icmp_privileged",
            return_value=True,
        ),
        patch("custom_components.climate_ip.helpers.async_ping") as mock_ping_priv,
    ):
        mock_ping_priv.return_value = MagicMock(is_alive=True)
        assert await async_check_network_reachability("192.168.1.100") is True
        assert mock_ping_priv.call_args.kwargs["privileged"] is True

    # Host cleaning matrix executed fast in a single test
    cases = [
        ("192.168.1.100", "192.168.1.100", False),
        ("http://192.168.1.50:8888", "192.168.1.50", False),
        ("http://192.168.1.50:8888/api/status", "192.168.1.50", False),
        ("https://10.0.0.1:443/", "10.0.0.1", False),
        ("192.168.1.200:8888", "192.168.1.200", False),
        ("http://[fe80::1]:8888", "fe80::1", False),
        ("https://[2001:db8::1]:8443/status", "2001:db8::1", False),
        ("[2001:db8::1]", "2001:db8::1", False),
        ("localhost", "localhost", True),
        ("127.0.0.1", "127.0.0.1", True),
        ("::1", "::1", True),
        ("http://fake.schema://192.168.1.55/foo/bar", "192.168.1.55", False),
        ("192.168.1.55/foo/bar", "192.168.1.55", False),
        ("[invalid", "[invalid", False),
        ("invalid]", "invalid]", False),
        ("[fe80::1]:8888]spurious]", "fe80::1", False),
    ]
    with (
        patch(
            "custom_components.climate_ip.helpers._can_use_icmp_privileged",
            return_value=False,
        ),
        patch("custom_components.climate_ip.helpers.async_ping") as mock_ping_matrix,
    ):
        mock_ping_matrix.return_value = MagicMock(is_alive=True)
        for input_host, expected_ip, is_bypass in cases:
            mock_ping_matrix.reset_mock()
            res = await async_check_network_reachability(input_host)
            assert res is True
            if is_bypass:
                mock_ping_matrix.assert_not_called()
            else:
                assert mock_ping_matrix.call_args.kwargs["address"] == expected_ip


@pytest.mark.asyncio
async def test_async_get_network_diagnostics() -> None:
    """Validate async_get_network_diagnostics status reporting and cleaning."""
    mock_host_obj = MagicMock()
    mock_host_obj.is_alive = True
    mock_host_obj.avg_rtt = 2.45

    with (
        patch(
            "custom_components.climate_ip.helpers._can_use_icmp_privileged",
            return_value=True,
        ),
        patch(
            "custom_components.climate_ip.helpers.async_ping",
            return_value=mock_host_obj,
        ) as mock_ping,
    ):
        # Success alive
        diag = await async_get_network_diagnostics("192.168.1.100", ping_timeout=2.5)
        mock_ping.assert_called_with(
            address="192.168.1.100",
            count=1,
            timeout=2.5,
            interval=0.2,
            privileged=True,
        )
        assert diag["is_reachable"] is True
        assert diag["avg_rtt_ms"] == 2.45
        assert diag["status"] == "alive"
        assert diag["privileged_mode"] is True

        # Unreachable timeout
        mock_host_obj.is_alive = False
        diag_unreach = await async_get_network_diagnostics("192.168.1.101")
        assert diag_unreach["is_reachable"] is False
        assert diag_unreach["status"] == "unreachable_timeout"

        # Permission bypass
        mock_ping.side_effect = SocketPermissionError(privileged=False)
        diag_perm = await async_get_network_diagnostics("192.168.1.102")
        assert diag_perm["is_reachable"] is True
        assert diag_perm["status"] == "permission_bypassed"

        mock_ping.side_effect = OSError("Permission denied")
        diag_os = await async_get_network_diagnostics("192.168.1.102")
        assert diag_os["is_reachable"] is True
        assert diag_os["status"] == "permission_bypassed"

        # Errors: DNS, socket, general
        mock_ping.side_effect = NameLookupError("Unknown host")
        diag_dns = await async_get_network_diagnostics("unknown.device.lan")
        assert diag_dns["is_reachable"] is False
        assert diag_dns["status"] == "dns_error"

        mock_ping.side_effect = ICMPSocketError("Socket closed")
        diag_sock = await async_get_network_diagnostics("192.168.1.103")
        assert diag_sock["is_reachable"] is False
        assert diag_sock["status"] == "socket_error"

        mock_ping.side_effect = RuntimeError("Unexpected")
        diag_err = await async_get_network_diagnostics("192.168.1.104")
        assert diag_err["is_reachable"] is False
        assert diag_err["status"] == "error_RuntimeError"

        # Host cleaning checks
        mock_ping.side_effect = None
        mock_host_obj.is_alive = True
        await async_get_network_diagnostics(
            "http://192.168.1.101:8080/status", ping_timeout=1.0
        )
        assert mock_ping.call_args.kwargs["address"] == "192.168.1.101"

        await async_get_network_diagnostics(
            "http://192.168.1.101/status", ping_timeout=1.0
        )
        assert mock_ping.call_args.kwargs["address"] == "192.168.1.101"

        await async_get_network_diagnostics("[fe80::2]:8888", ping_timeout=1.0)
        assert mock_ping.call_args.kwargs["address"] == "fe80::2"

        await async_get_network_diagnostics("[fe80:1]", ping_timeout=1.0)
        assert mock_ping.call_args.kwargs["address"] == "fe80:1"

        await async_get_network_diagnostics("192.168.1.50]", ping_timeout=1.0)
        assert mock_ping.call_args.kwargs["address"] == "192.168.1.50]"

        await async_get_network_diagnostics("[192.168.1.50", ping_timeout=1.0)
        assert mock_ping.call_args.kwargs["address"] == "[192.168.1.50"

    # Missing host bypasses
    diag_none = await async_get_network_diagnostics("")
    assert diag_none["is_reachable"] is False
    assert diag_none["status"] == "missing_host"
    assert diag_none["privileged_mode"] is False

    diag_invalid = await async_get_network_diagnostics(12345)
    assert diag_invalid["is_reachable"] is False
    assert diag_invalid["status"] == "missing_host"
    assert diag_invalid["privileged_mode"] is False

    # Loopback bypass
    diag_loop = await async_get_network_diagnostics("http://127.0.0.1:8888")
    assert diag_loop["is_reachable"] is True
    assert diag_loop["status"] == "loopback_bypass"
    assert diag_loop["privileged_mode"] is False

    # Library missing bypass
    orig_ping = helpers.async_ping
    helpers.async_ping = None
    try:
        diag_no_lib = await async_get_network_diagnostics("192.168.1.105")
        assert diag_no_lib["is_reachable"] is True
        assert diag_no_lib["status"] == "library_missing"
        assert diag_no_lib["privileged_mode"] is False
    finally:
        helpers.async_ping = orig_ping


@pytest.mark.asyncio
async def test_async_get_mac_address() -> None:
    """Validate async_get_mac_address parsing, OS flags, timeouts, and token loop resilience."""
    mock_proc = AsyncMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        # Invalid lengths, characters, separators
        mock_proc.communicate.return_value = (b"12:34:56:78:90:xx:yy", b"")
        assert await async_get_mac_address("1.1.1.1") is None

        mock_proc.communicate.return_value = (b"12:34:56:78:90:XX", b"")
        assert await async_get_mac_address("1.1.1.1") is None

        mock_proc.communicate.return_value = (b"12_34_56_78_90_ab", b"")
        assert await async_get_mac_address("1.1.1.1") is None

        # Valid Linux and Windows formats
        mock_proc.communicate.return_value = (b"12:34:56:78:90:ab", b"")
        assert await async_get_mac_address("1.1.1.1") == "12:34:56:78:90:ab"

        mock_proc.communicate.return_value = (b"12-34-56-78-90-CD", b"")
        assert await async_get_mac_address("1.1.1.1") == "12-34-56-78-90-cd"

        # OS routing on Windows and Linux
        with patch("platform.system", return_value="Windows"):
            mock_proc.communicate.return_value = (b"1A-2B-3C-4D-5E-6F", b"")
            await async_get_mac_address("192.168.1.10")
            assert "-a" in mock_exec.call_args.args
            assert mock_exec.call_args.kwargs["stdout"] == asyncio.subprocess.PIPE
            assert mock_exec.call_args.kwargs["stderr"] == asyncio.subprocess.DEVNULL

        with patch("platform.system", return_value="Linux"):
            mock_proc.communicate.return_value = (b"1A:2B:3C:4D:5E:6F", b"")
            await async_get_mac_address("192.168.1.10")
            assert "-n" in mock_exec.call_args.args
            assert mock_exec.call_args.kwargs["stdout"] == asyncio.subprocess.PIPE
            assert mock_exec.call_args.kwargs["stderr"] == asyncio.subprocess.DEVNULL

        # Timeout kills zombie process
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            assert await async_get_mac_address("192.168.1.10") is None
            mock_proc.kill.assert_called_once()

        # Strict 2.0s timeout argument
        mock_proc.communicate.return_value = (b"00:11:22:33:44:55", b"")
        with patch("asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait:
            assert await async_get_mac_address("1.1.1.1") == "00:11:22:33:44:55"
            assert mock_wait.call_args.kwargs["timeout"] == 2.0

        # Token filtering and loop resilience
        mock_proc.communicate.return_value = (
            b"? (192.168.1.50) at 00:11:22:33:44:55 [ether] on eth0",
            b"",
        )
        assert await async_get_mac_address("192.168.1.50") == "00:11:22:33:44:55"

        mock_proc.communicate.return_value = (
            b"12345678901234567 00:11:22:33:44:55",
            b"",
        )
        assert await async_get_mac_address("192.168.1.50") == "00:11:22:33:44:55"

        mock_proc.communicate.return_value = (
            b"00:11:22:33:44:-5 00:11:22:33:44:55",
            b"",
        )
        assert await async_get_mac_address("192.168.1.50") == "00:11:22:33:44:55"

        mock_proc.communicate.return_value = (b"00:11:22:33:44:gg", b"")
        assert await async_get_mac_address("192.168.1.50") is None

        mock_proc.communicate.return_value = (
            b"00:11:22:33:44:gg 00:11:22:33:44:55",
            b"",
        )
        assert await async_get_mac_address("192.168.1.50") == "00:11:22:33:44:55"

        mock_proc.communicate.return_value = (
            b"00:11:22:33:44:zz 00:11:22:33:44:55",
            b"",
        )
        assert await async_get_mac_address("192.168.1.50") == "00:11:22:33:44:55"

        mock_proc.communicate.return_value = (b"AA:BB:CC:DD:EE:FF", b"")
        assert await async_get_mac_address("192.168.1.50") == "aa:bb:cc:dd:ee:ff"

    # Errors in command execution
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        assert await async_get_mac_address("192.168.1.99") is None

    with patch("asyncio.create_subprocess_exec", side_effect=OSError("arp failed")):
        assert await async_get_mac_address("192.168.1.99") is None


@pytest.mark.asyncio
async def test_async_force_arp_update() -> None:
    """Validate async_force_arp_update concurrent port probing and clean socket closing."""
    mock_writer_2878 = MagicMock()
    mock_writer_2878.close = MagicMock()
    mock_writer_2878.wait_closed = AsyncMock()

    mock_writer_8888 = MagicMock()
    mock_writer_8888.close = MagicMock()
    mock_writer_8888.wait_closed = AsyncMock()

    async def mock_open_conn(ip, port):
        if port == PORT_SAMSUNG_2878:
            return MagicMock(), mock_writer_2878
        return MagicMock(), mock_writer_8888

    with patch("asyncio.open_connection", side_effect=mock_open_conn) as mock_conn:
        await async_force_arp_update("192.168.1.50")
        assert mock_conn.call_count == 2
        mock_conn.assert_any_call("192.168.1.50", PORT_SAMSUNG_2878)
        mock_conn.assert_any_call("192.168.1.50", PORT_SAMSUNG_8888)
        mock_writer_2878.close.assert_called_once()
        mock_writer_2878.wait_closed.assert_awaited_once()
        mock_writer_8888.close.assert_called_once()
        mock_writer_8888.wait_closed.assert_awaited_once()

    # Exception suppression
    async def mock_open_conn_err(ip, port):
        if port == PORT_SAMSUNG_2878:
            raise TimeoutError("Simulated connection timeout")
        raise OSError("Host unreachable")

    with patch("asyncio.open_connection", side_effect=mock_open_conn_err):
        await async_force_arp_update("10.0.0.99")

    # Mixed one ok, one error
    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    async def mock_mixed(ip, port):
        if port == PORT_SAMSUNG_2878:
            return MagicMock(), mock_writer
        raise OSError("Port 8888 failed")

    with patch("asyncio.open_connection", side_effect=mock_mixed):
        await async_force_arp_update("10.0.0.99")
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()


def test_validate_and_format_poll_interval() -> None:
    """Validate validate_poll_interval bounds and format_poll_interval conversions."""
    assert validate_poll_interval(60) == 60
    assert validate_poll_interval(120) == 120
    assert validate_poll_interval(60.0) == 60
    assert validate_poll_interval("00:01:00") == 60
    assert validate_poll_interval(MIN_POLL_INTERVAL) == MIN_POLL_INTERVAL
    assert validate_poll_interval(MAX_POLL_INTERVAL) == MAX_POLL_INTERVAL

    with pytest.raises(ValueError, match="Invalid time format"):
        validate_poll_interval("invalid_time_string")

    for bad in (1, 4, MIN_POLL_INTERVAL - 1, MAX_POLL_INTERVAL + 1, 21601):
        with pytest.raises(ValueError, match="Interval must be between"):
            validate_poll_interval(bad)

    # format_poll_interval
    assert format_poll_interval(90) == "0:01:30"
    assert format_poll_interval("120") == "0:02:00"
    assert format_poll_interval(0) == "0:00:00"
    assert format_poll_interval(3600) == "1:00:00"
    assert format_poll_interval("0:05:00") == "0:05:00"
    assert format_poll_interval("custom_str") == "custom_str"
    assert format_poll_interval(None, 300) == "0:05:00"
    assert format_poll_interval(None) == "0:01:00"
    assert format_poll_interval(None, default_seconds=60) == "0:01:00"
    assert format_poll_interval(object(), 45) == "0:00:45"
    assert format_poll_interval([], 120) == "0:02:00"
    assert format_poll_interval(None, "not_an_int") == ""
    assert format_poll_interval(object(), "invalid") == ""
    assert format_poll_interval(object(), None) == ""


def test_icmplib_import_error_fallback() -> None:
    """Validate dummy error fallback and behavior when icmplib cannot be imported."""
    dummy_err = helpers._DummyIcmpError("Test dummy exception")
    assert isinstance(dummy_err, Exception)

    # Reload helpers with icmplib blocked to cover lines 530-535
    with patch.dict(sys.modules, {"icmplib": None}):
        importlib.reload(helpers)
        assert helpers._ICMPLIB_AVAILABLE is False
        assert helpers.async_ping is None
        assert helpers.ICMPSocketError is helpers._DummyIcmpError

    # Restore module cleanly
    importlib.reload(helpers)
    assert helpers._ICMPLIB_AVAILABLE is True
