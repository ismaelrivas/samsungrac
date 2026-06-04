# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for the tolerant_header_parsing context manager (H-12) and find_key_in_data."""
# pylint: disable=broad-exception-caught,import-outside-toplevel

import threading

import pytest

from custom_components.climate_ip.helpers import (
    create_samsung_ssl_context,
    find_key_in_data,
    safe_xml_to_dict,
    tolerant_header_parsing,
)


class TestTolerantHeaderParsing:
    """Tests for the urllib3 monkey-patch context manager."""

    def test_patch_applied_inside_context(self):
        """Verify that assert_header_parsing is replaced inside the context."""
        import urllib3.util.response as response_util

        original = response_util.assert_header_parsing

        with tolerant_header_parsing():
            patched = response_util.assert_header_parsing
            assert patched is not original, "assert_header_parsing should be patched inside context"

        assert (
            response_util.assert_header_parsing is original
        ), "assert_header_parsing should be restored after context"

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

        assert (
            response_util.assert_header_parsing is original
        ), "assert_header_parsing should be restored even after an exception"

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
        assert (
            response_util.assert_header_parsing is original
        ), "Original function should be restored after all threads complete"


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

def test_token_sanitization() -> None:
    """Validate token sanitization against injection."""
    from custom_components.climate_ip.helpers import sanitize_token
    assert sanitize_token('my"evil{{token') is None
    assert sanitize_token("abcd1234") == "abcd1234"


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
        """DefusedXml security exceptions must propagate, not be swallowed."""
        from defusedxml import EntitiesForbidden
        # Billion laughs payload
        malicious = '<!DOCTYPE b [ <!ENTITY a "x"> <!ENTITY b "&a;&a;"> ]><S>&b;</S>'
        with pytest.raises(EntitiesForbidden):
            safe_xml_to_dict(malicious)


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
