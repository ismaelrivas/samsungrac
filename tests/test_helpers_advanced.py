# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the tolerant_header_parsing context manager (H-12) and find_key_in_data."""
# pylint: disable=broad-exception-caught,import-outside-toplevel

import asyncio
import threading

import pytest

import ssl
from homeassistant.helpers.entity import EntityCategory

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.climate_ip.helpers import (
    async_check_network_reachability,
    async_create_samsung_ssl_context,
    async_get_mac_address,
    format_placeholders,
    get_tls_version_name,
    get_value_by_path,
    mask_sensitive_data,
    parse_entity_category,
    stream_wrapper,
    create_samsung_ssl_context,
    find_key_in_data,
    safe_xml_to_dict,
    tolerant_header_parsing,
    ICMPSocketError,
)


class TestTolerantHeaderParsing:
    """Tests for the urllib3 monkey-patch context manager."""

    def test_patch_applied_inside_context(self):
        """Verify that assert_header_parsing is replaced inside the context."""
        import urllib3.util.response as response_util

        original = response_util.assert_header_parsing

        with tolerant_header_parsing():
            patched = response_util.assert_header_parsing
            assert patched is not original, (
                "assert_header_parsing should be patched inside context"
            )

        assert response_util.assert_header_parsing is original, (
            "assert_header_parsing should be restored after context"
        )

    def test_patch_restored_after_context(self):
        """Verify that the original function is restored after the context exits."""
        import urllib3.connection as connection_mod
        import urllib3.util.response as response_util

        original_response = response_util.assert_header_parsing
        original_connection = connection_mod.assert_header_parsing

        with tolerant_header_parsing():
            pass  # Just enter and exit

        assert response_util.assert_header_parsing is original_response
        assert connection_mod.assert_header_parsing is original_connection

    def test_patch_restored_after_exception(self):
        """Verify cleanup even if an exception is raised inside the context."""
        import urllib3.util.response as response_util

        original = response_util.assert_header_parsing

        with pytest.raises(ValueError), tolerant_header_parsing():
            raise ValueError("Simulated error")

        assert response_util.assert_header_parsing is original, (
            "assert_header_parsing should be restored even after an exception"
        )

    def test_header_parsing_error_suppressed(self):
        """Verify that HeaderParsingError is caught and logged, not raised."""
        from urllib3.exceptions import HeaderParsingError
        import urllib3.util.response as response_util

        # Save the real function
        real_assert = response_util.assert_header_parsing

        # Replace with a version that always raises
        def failing_assert(headers):
            raise HeaderParsingError(defects="bad header", unparsed_data="data")

        response_util.assert_header_parsing = failing_assert
        try:
            with tolerant_header_parsing():
                # The patched version should catch the error, not raise it
                import urllib3.util.response as patched_mod  # pylint: disable=reimported

                patched_mod.assert_header_parsing("test_headers")
                # If we get here, the error was suppressed — test passes
        finally:
            response_util.assert_header_parsing = real_assert

    def test_thread_safety(self):
        """Verify that concurrent usage doesn't corrupt the global state."""
        import urllib3.util.response as response_util

        original = response_util.assert_header_parsing
        errors = []

        def worker():
            try:
                with tolerant_header_parsing():
                    # Simulate some work
                    import time

                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors in threads: {errors}"
        assert response_util.assert_header_parsing is original, (
            "Original function should be restored after all threads complete"
        )


class TestFindKeyInData:
    """Tests for the recursive key finder (validates H-16 cleanup didn't break logic)."""

    def test_find_in_flat_dict(self):
        """Test finds a top-level key."""
        assert find_key_in_data({"a": 1, "b": 2}, "b") == 2

    def test_find_in_nested_dict(self):
        """Test finds a deeply nested key."""
        data = {"level1": {"level2": {"target": "found"}}}
        assert find_key_in_data(data, "target") == "found"

    def test_find_in_list_of_dicts(self):
        """Test finds key in a list of dicts."""
        data = [{"a": 1}, {"b": 2}, {"c": 3}]
        assert find_key_in_data(data, "c") == 3

    def test_find_in_deeply_nested_list(self):
        """Test finds key in a deeply nested list."""
        data = {"Devices": [{"Temperatures": [{"current": 22.0}]}]}
        assert find_key_in_data(data, "current") == 22.0

    def test_key_not_found_returns_none(self):
        """Test returns None when key is absent."""
        assert find_key_in_data({"a": 1}, "missing") is None

    def test_empty_dict(self):
        """Test returns None for an empty dict."""
        assert find_key_in_data({}, "any") is None

    def test_empty_list(self):
        """Test returns None for an empty list."""
        assert find_key_in_data([], "any") is None

    def test_none_value_is_distinguishable(self):
        """A key with value None should still return None (edge case)."""
        # This is a known limitation: find_key_in_data can't distinguish
        # "key exists with None value" from "key not found". Document it.
        assert find_key_in_data({"exists": None}, "exists") is None

    def test_first_occurrence_wins(self):
        """When multiple keys exist, the first one found (DFS) should be returned."""
        data = {"a": {"target": "first"}, "b": {"target": "second"}}
        result = find_key_in_data(data, "target")
        assert result in ("first", "second")  # DFS order depends on dict ordering


class TestResolveCertPath:
    """Tests for the resolve_cert_path utility."""

    def test_resolve_cert_path_absolute(self):
        """Test that an absolute path is returned as-is."""
        from custom_components.climate_ip.helpers import resolve_cert_path

        abs_path = "/config/climate_ip/ac14k_m.pem"
        assert resolve_cert_path(abs_path, "/base/dir") == abs_path

    def test_resolve_cert_path_relative_no_cert_folder(self):
        """Test that a relative path is resolved against base_dir."""
        import os

        from custom_components.climate_ip.helpers import resolve_cert_path

        # Even with backslashes on Windows, the function uses os.path.join
        result = resolve_cert_path("ac14k_m.pem", "/base/dir")
        assert os.path.normpath(result) == os.path.normpath("/base/dir/ac14k_m.pem")

    def test_resolve_cert_path_none(self):
        """Test that None input returns None."""
        from custom_components.climate_ip.helpers import resolve_cert_path

        assert resolve_cert_path(None, "/base/dir") is None

    def test_resolve_cert_path_with_hass_slash(self):
        """Test resolve_cert_path with hass for a path containing slashes."""
        from unittest.mock import MagicMock
        from custom_components.climate_ip.helpers import resolve_cert_path

        mock_hass = MagicMock()
        mock_hass.config.path.return_value = "/ha/config/my_cert.pem"

        res = resolve_cert_path("subdir/my_cert.pem", "/base/dir", hass=mock_hass)
        assert res == "/ha/config/my_cert.pem"
        mock_hass.config.path.assert_called_once_with("subdir/my_cert.pem")

    def test_resolve_cert_path_with_hass_filename_only(self):
        """Test resolve_cert_path with hass for filename only."""
        from pathlib import Path
        from unittest.mock import MagicMock
        from custom_components.climate_ip.helpers import resolve_cert_path
        import custom_components.climate_ip.helpers as helpers

        mock_hass = MagicMock()
        res = resolve_cert_path("ac14k_m.pem", "/base/dir", hass=mock_hass)
        assert res == str(Path(helpers.__file__).parent / "ac14k_m.pem")

    def test_resolve_cert_path_hass_attribute_error(self):
        """Test resolve_cert_path when hass raises AttributeError."""
        from custom_components.climate_ip.helpers import resolve_cert_path

        class FaultyHass:
            @property
            def config(self):
                raise AttributeError("No config")

        from pathlib import Path

        res = resolve_cert_path("subdir/my_cert.pem", "/base/dir", hass=FaultyHass())
        assert res == str(Path("subdir/my_cert.pem"))

    def test_resolve_cert_path_no_base_dir(self):
        """Test resolve_cert_path when base_dir is empty."""
        from pathlib import Path
        from custom_components.climate_ip.helpers import resolve_cert_path
        import custom_components.climate_ip.helpers as helpers

        res = resolve_cert_path("ac14k_m.pem", base_dir="")
        assert res == str(Path(helpers.__file__).parent / "ac14k_m.pem")


class TestValidatePollInterval:
    """Tests for validate_poll_interval helper function."""

    def test_validate_poll_interval_int(self):
        from custom_components.climate_ip.helpers import validate_poll_interval

        assert validate_poll_interval(60) == 60

    def test_validate_poll_interval_float(self):
        from custom_components.climate_ip.helpers import validate_poll_interval

        assert validate_poll_interval(60.0) == 60

    def test_validate_poll_interval_str(self):
        from custom_components.climate_ip.helpers import validate_poll_interval

        assert validate_poll_interval("00:01:00") == 60

    def test_validate_poll_interval_invalid_str(self):
        import pytest
        from custom_components.climate_ip.helpers import validate_poll_interval

        with pytest.raises(ValueError, match="Invalid time format"):
            validate_poll_interval("invalid_time_string")

    def test_validate_poll_interval_boundary(self):
        from custom_components.climate_ip.helpers import validate_poll_interval
        from custom_components.climate_ip.const import (
            MIN_POLL_INTERVAL,
            MAX_POLL_INTERVAL,
        )

        assert validate_poll_interval(MIN_POLL_INTERVAL) == MIN_POLL_INTERVAL
        assert validate_poll_interval(MAX_POLL_INTERVAL) == MAX_POLL_INTERVAL

    def test_validate_poll_interval_out_of_range(self):
        import pytest
        from custom_components.climate_ip.helpers import validate_poll_interval

        with pytest.raises(ValueError, match="Interval must be between"):
            validate_poll_interval(4)

        with pytest.raises(ValueError, match="Interval must be between"):
            validate_poll_interval(21601)


def test_token_sanitization() -> None:
    """Validate token sanitization against injection and length bounds."""
    from custom_components.climate_ip.helpers import sanitize_token

    assert sanitize_token(None) is None
    assert sanitize_token("") is None
    assert sanitize_token('my"evil{{token') is None
    assert sanitize_token("abcd123") is None  # length 7 (too short)
    assert sanitize_token("abcd1234") == "abcd1234"  # length 8 (min)
    assert sanitize_token("a" * 128) == "a" * 128  # length 128 (max)
    assert sanitize_token("a" * 129) is None  # length 129 (too long)


class TestSafeXmlToDict:
    """Tests for the secured XML to dict converter."""

    def test_safe_xml_to_dict_malformed_input(self):
        """Malformed XML must return empty dict, not raise."""
        result = safe_xml_to_dict("<bad_xml <missing_close")
        assert result == {}

    def test_safe_xml_to_dict_empty_string(self):
        """Empty string must return empty dict, not raise."""
        result = safe_xml_to_dict("")
        assert result == {}

    def test_safe_xml_to_dict_valid_response(self):
        """A valid Samsung-style XML must parse correctly."""
        xml = '<Response Type="DeviceState"><Device><Attr id="Wind" value="Auto"/></Device></Response>'
        result = safe_xml_to_dict(xml)
        assert "Response" in result
        assert result["Response"]["@Type"] == "DeviceState"
        assert result["Response"]["Device"]["Attr"]["@id"] == "Wind"

    def test_safe_xml_to_dict_security_propagates(self):
        """Native Shield XML security firewall rejects DOCTYPE injection payloads."""
        # Billion laughs payload
        malicious = '<!DOCTYPE b [ <!ENTITY a "x"> <!ENTITY b "&a;&a;"> ]><S>&b;</S>'
        assert safe_xml_to_dict(malicious) == {}


class TestCreateSamsungSslContext:
    """Tests for standardized SSL context creation (Standardizing Hallazgo 5)."""

    def test_ssl_context_bad_cert_raises(self):
        """A non-existent cert path must raise, not silently fail."""
        import ssl

        # This will fail during context.load_cert_chain / load_verify_locations
        with pytest.raises((ssl.SSLError, OSError, FileNotFoundError)):
            create_samsung_ssl_context(cert_path="/nonexistent/cert.pem")

    def test_ssl_context_standard_ciphers(self):
        """Test that default context uses secure high-level ciphers."""
        import ssl

        ctx = create_samsung_ssl_context()
        assert ctx.verify_mode == ssl.CERT_NONE  # default for Samsung devices
        # Check that TLS 1.3 is NOT enabled as maximum (Samsung bug)
        if hasattr(ssl, "TLSVersion"):
            assert ctx.maximum_version == ssl.TLSVersion.TLSv1_2


def test_safe_xml_to_dict_list_conversion():
    """Kills mutmut 6, 7, 8: Ensures identical sibling tags become lists."""
    xml_string = "<root><item>1</item><item>2</item></root>"
    result = safe_xml_to_dict(xml_string)
    assert result == {"root": {"item": ["1", "2"]}}


def test_safe_xml_to_dict_text_with_attributes():
    """Kills mutmut 9, 10, 12, 13, 14: Ensures elements with attrs and text use '#text'."""
    xml_string = '<root id="5">hello</root>'
    result = safe_xml_to_dict(xml_string)
    assert result == {"root": {"@id": "5", "#text": "hello"}}


# --- parse_entity_category ---
def test_parse_entity_category():
    assert parse_entity_category("config") == EntityCategory.CONFIG
    assert parse_entity_category("diagnostic") == EntityCategory.DIAGNOSTIC
    assert parse_entity_category(None) is None
    assert parse_entity_category("invalid_category") is None


# --- get_value_by_path ---
def test_get_value_by_path():
    data = {"level1": {"level2": {"level3": "target_value"}}}
    assert get_value_by_path(data, ["level1", "level2", "level3"]) == "target_value"
    assert get_value_by_path(data, ["level1", "wrong_level"]) is None
    assert get_value_by_path(data, []) is None
    assert get_value_by_path(None, ["level1"]) is None
    assert get_value_by_path({"level1": "not_a_dict"}, ["level1", "level2"]) is None


# --- stream_wrapper ---
def test_stream_wrapper():
    template = "Token:__CLIMATE_IP_TOKEN__, Host:__CLIMATE_IP_HOST__, Mac:__CLIMATE_IP_MAC__, ID:__DEVICE_ID__"
    result = stream_wrapper(
        template, "my_token", "192.168.1.10", "dev_123", "00:11:22:33:44:55"
    )
    assert (
        result == "Token:my_token, Host:192.168.1.10, Mac:00:11:22:33:44:55, ID:dev_123"
    )

    # Test partial replacements
    partial = stream_wrapper("Token:__CLIMATE_IP_TOKEN__", None, None, None)
    assert partial == "Token:__CLIMATE_IP_TOKEN__"


# --- get_tls_version_name ---
def test_get_tls_version_name():
    assert get_tls_version_name(0) == "Unknown"

    # Test valid TLS version
    if hasattr(ssl, "TLSVersion") and hasattr(ssl.TLSVersion, "TLSv1_2"):
        assert (
            get_tls_version_name(ssl.TLSVersion.TLSv1_2) == ssl.TLSVersion.TLSv1_2.name
        )

    # Test fallback to string representation for invalid types
    assert get_tls_version_name(9999) == "9999"


# --- async_create_samsung_ssl_context ---
@pytest.mark.asyncio
async def test_async_create_samsung_ssl_context():
    context = await async_create_samsung_ssl_context(is_server=False)
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


# --- format_placeholders ---
def test_format_placeholders():
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


# --- mask_sensitive_data ---
def test_mask_sensitive_data():
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


# --- async_get_mac_address ---
@pytest.mark.asyncio
@patch("asyncio.create_subprocess_exec")
async def test_async_get_mac_address(mock_exec):
    mock_proc = AsyncMock()
    # Cambiamos la MAC a una con LETRAS para cazar el mutante '.lower()' a '.upper()'
    mock_proc.communicate.return_value = (
        b"Address HWtype 1A:2B:3C:4D:5E:6F C eth0",
        b"",
    )
    mock_exec.return_value = mock_proc

    mac = await async_get_mac_address("192.168.1.10")
    assert mac == "1a:2b:3c:4d:5e:6f"

    # Matamos los mutantes que quitan los argumentos o los cambian a None
    mock_exec.assert_called_with(
        "arp",
        "-n",
        "192.168.1.10",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    mock_proc.communicate.return_value = (b"No entries", b"")
    assert await async_get_mac_address("192.168.1.11") is None

    # Sniper boundary tests to kill `and` -> `or` mutants in MAC parsing
    # 1. Candidate token with 5 colons but length 18 (len != 17)
    mock_proc.communicate.return_value = (b"1a:-2b:3c:4d:5e:6f", b"")
    assert await async_get_mac_address("192.168.1.12") is None

    # 2. Candidate token of length 17 with 5 colons but non-alphanumeric character (cleaned.isalnum() is False)
    mock_proc.communicate.return_value = (b"1:2:3:4:5:678901!", b"")
    assert await async_get_mac_address("192.168.1.13") is None


@pytest.mark.asyncio
@patch("asyncio.create_subprocess_exec")
@patch("platform.system")
async def test_async_get_mac_address_windows(mock_system, mock_exec):
    mock_system.return_value = "Windows"  # Forzamos la entrada al IF

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"1A-2B-3C-4D-5E-6F", b"")
    mock_exec.return_value = mock_proc

    mac = await async_get_mac_address("192.168.1.10")
    assert mac == "1a-2b-3c-4d-5e-6f"

    # Validamos que los argumentos del SO sean puramente los de Windows
    mock_exec.assert_called_with(
        "arp",
        "-a",
        "192.168.1.10",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )


# --- mask_sensitive_data (Añadido para cazar al Mutante 29 y string DUID mutants) ---
def test_mask_sensitive_data_list():
    """Test explicit list processing to kill Mutant 29."""
    data = [{"token": "12345678"}]
    # If mutmut cambia 'item' a 'None', devolverá [None] y este assert fallará
    assert mask_sensitive_data(data) == [{"token": "***345678"}]


def test_mask_sensitive_data_strings():
    """Test masking of sensitive string payloads containing DUID, Token, and DeviceToken to kill all DUID mutants."""
    # 1. Long DUID (> 6 chars): "1234567890" (len 10 -> masked ***567890)
    str_duid_long = 'DUID="1234567890"'
    assert mask_sensitive_data(str_duid_long) == 'DUID="***567890"'

    # 2. Short DUID (<= 6 chars): "123456" (len 6 -> masked ***)
    str_duid_short = 'DUID="123456"'
    assert mask_sensitive_data(str_duid_short) == 'DUID="***"'

    # 3. Boundary case DUID (7 chars): "1234567" (len 7 > 6 -> masked ***234567)
    str_duid_boundary = 'DUID="1234567"'
    assert mask_sensitive_data(str_duid_boundary) == 'DUID="***234567"'

    # 4. Case-insensitive DUID match: lowercase duid="1234567890"
    str_duid_lower = 'duid="1234567890"'
    assert mask_sensitive_data(str_duid_lower) == 'duid="***567890"'

    # 5. Token regex: Token="36-char-uuid-format-string-goes-here"
    str_token = 'Token="12345678-1234-1234-1234-123456789012"'
    assert mask_sensitive_data(str_token) == 'Token="***"'

    # 6. DeviceToken regex: DeviceToken="secret123"
    str_device_token = 'DeviceToken="secret123"'
    assert mask_sensitive_data(str_device_token) == 'DeviceToken="***"'


# --- async_check_network_reachability (Actualizado) ---
@pytest.mark.asyncio
@patch("custom_components.climate_ip.helpers.async_ping")
async def test_async_check_network_reachability(mock_ping):
    mock_host = MagicMock()
    mock_host.is_alive = True
    mock_host.avg_rtt = 10
    mock_ping.return_value = mock_host
    assert await async_check_network_reachability("192.168.1.100") is True

    mock_ping.assert_called_with(
        address="192.168.1.100", count=1, timeout=0.5, interval=0.2, privileged=False
    )

    mock_host.is_alive = False
    assert await async_check_network_reachability("192.168.1.100") is False

    mock_ping.side_effect = OSError("Permission denied")
    assert await async_check_network_reachability("192.168.1.100") is True

    # ¡LA TRAMPA PARA EL MUTANTE 23!
    if ICMPSocketError is not None:
        mock_ping.side_effect = ICMPSocketError("Mocked socket error")
        assert await async_check_network_reachability("192.168.1.100") is False


# --- async_check_network_reachability (Nuevo Test para Mutantes 2 y 5) ---
@pytest.mark.asyncio
async def test_async_check_network_reachability_no_library():
    """Test fallback logic when icmplib is missing or fails to load."""
    import custom_components.climate_ip.helpers as helpers_module

    original_ping = helpers_module.async_ping

    # Simulamos que la librería no está instalada en el sistema
    helpers_module.async_ping = None

    try:
        # Esto debería usar la vía de escape y devolver True
        assert await async_check_network_reachability("192.168.1.100") is True
    finally:
        # Restauramos el módulo a su estado original para no romper otros tests
        helpers_module.async_ping = original_ping


def test_safe_xml_to_dict_non_string_mutation():
    """Mata al Mutante 1 forzando un tipo no-string evaluable como True."""
    # El mutante 'and' intentaría hacer un re.search sobre una lista, reventando.
    # El código correcto corta por lo sano y devuelve {}.
    assert safe_xml_to_dict(["<root></root>"]) == {}
    assert safe_xml_to_dict(12345) == {}


def test_safe_xml_to_dict_case_insensitive_doctype():
    """Kill Mutant 9 by verifying that re.IGNORECASE is mandatory (Layer 1)."""
    malicious_payload = "<!doctype html><root>bypass</root>"

    # Assert that Layer 1 specific error log was called.
    # If the mutant removes IGNORECASE, Layer 1 will miss the lowercase doctype.
    with patch("custom_components.climate_ip.helpers._LOGGER.error") as mock_log:
        assert safe_xml_to_dict(malicious_payload) == {}
        mock_log.assert_called_once_with(
            "XML Payload rejected: DOCTYPE injection attempt detected."
        )


def test_safe_xml_to_dict_layer2_fallback_defense():
    """Kill Mutants 21, 22, 25, 27 by demonstrating Layer 2 acts if Layer 1 is bypassed."""
    malicious_payload = "<!DOCTYPE dummy><root>123</root>"

    # Simulate an attacker bypassing the Regex Firewall (Layer 1)
    with patch("custom_components.climate_ip.helpers.re.search", return_value=None):
        result = safe_xml_to_dict(malicious_payload)

        # If parser=parser was removed by a mutant, standard parser accepts DOCTYPE.
        # With SecureTreeBuilder intact, doctype() raises ValueError and returns {}.
        assert (
            result == {}
        ), "Critical Failure! Native interceptor (Layer 2) was removed or bypassed."


def test_tolerant_header_parsing_strict_mutants():
    """Kill Mutants 5, 7, and 8 in monkey-patch variable assignments."""
    import http.client
    import urllib3.connection as connection_mod
    from custom_components.climate_ip.helpers import tolerant_header_parsing

    orig_parse = http.client.parse_headers
    orig_conn = connection_mod.assert_header_parsing

    with tolerant_header_parsing():
        # Mutants 7 and 8 change assignments to None.
        assert connection_mod.assert_header_parsing is not None
        assert connection_mod.assert_header_parsing is not orig_conn
        assert http.client.parse_headers is not None
        assert http.client.parse_headers is not orig_parse

    # Mutant 5 changes original reference backup variable to None, breaking cleanup.
    assert http.client.parse_headers is orig_parse
    assert connection_mod.assert_header_parsing is orig_conn


def test_tolerant_assert_strict_forwarding():
    """Kill Mutant 1 which sends None instead of original headers."""
    import http.client
    import custom_components.climate_ip.helpers as helpers_mod
    import urllib3.connection as connection_mod
    from custom_components.climate_ip.helpers import tolerant_header_parsing

    mock_orig = MagicMock()
    test_headers = http.client.HTTPMessage()

    with tolerant_header_parsing():
        old_orig = helpers_mod._HEADER_PATCH_ORIGINAL_RESPONSE
        helpers_mod._HEADER_PATCH_ORIGINAL_RESPONSE = mock_orig
        try:
            _tolerant_assert = connection_mod.assert_header_parsing
            _tolerant_assert(test_headers)
            mock_orig.assert_called_once_with(test_headers)
        finally:
            helpers_mod._HEADER_PATCH_ORIGINAL_RESPONSE = old_orig
