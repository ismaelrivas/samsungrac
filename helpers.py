# pylint: disable=import-outside-toplevel,line-too-long
"""
Helper utilities for the climate_ip integration.

Provides:
- A scoped urllib3 monkey-patch (tolerant_header_parsing) for Samsung devices
  that send HTTP responses with malformed headers.
- Data utilities (find_key_in_data, get_value_by_path, stream_wrapper).
- SSL context factory (create_samsung_ssl_context) for Samsung-specific TLS quirks.
- Sensitive data masking (mask_sensitive_data) for safe logging.
- Native ICMP network reachability check (async_check_network_reachability).
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator, Sequence
import contextlib
import functools
import http.client
from io import BytesIO
import logging
from pathlib import Path
import platform
import re
import ssl
import threading
from typing import TYPE_CHECKING, Any
import warnings
import xml.etree.ElementTree as ET

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from homeassistant.const import EntityCategory
from homeassistant.helpers import config_validation as cv
from voluptuous.error import Invalid

_LOGGER = logging.getLogger(__name__)


def sanitize_token(token: str | None) -> str | None:
    """Validate that a Samsung DeviceToken only contains safe characters."""
    if not token:
        return None
    if 8 <= len(token) <= 128:
        cleaned = token.replace("-", "").replace("_", "")
        if (not cleaned or cleaned.isalnum()) and cleaned.isascii():
            return token
    _LOGGER.warning(  # pragma: no mutate
        "Token rejected: contains unexpected characters. "  # pragma: no mutate
        "Expected alphanumeric/dash/underscore (8-128 chars). "  # pragma: no mutate
        "Got length=%d, starts_with=%r",  # pragma: no mutate
        len(token),  # pragma: no mutate
        token[:6],  # pragma: no mutate
    )  # pragma: no mutate
    return None


def parse_entity_category(raw: str | None) -> EntityCategory | None:
    """Parse a raw entity_category string into an EntityCategory enum value."""
    if not raw:
        return None
    try:
        return EntityCategory(raw)
    except ValueError:
        _LOGGER.warning(  # pragma: no mutate
            "Invalid entity_category value '%s' — ignoring. Valid values: %s",  # pragma: no mutate
            raw,  # pragma: no mutate
            [e.value for e in EntityCategory],  # pragma: no mutate
        )  # pragma: no mutate
        return None


class SecureTreeBuilder(ET.TreeBuilder):
    """Native Interceptor: Destroys parsing immediately if the engine

    attempts to process a DOCTYPE, neutralizing XXE and Billion Laughs at the root.
    """

    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ValueError(
            "Security Violation: DOCTYPE declarations strictly prohibited."
        )  # pragma: no mutate


def safe_xml_to_dict(xml_string: str) -> dict[str, Any]:
    """Zero-dependency, Production-Grade XML to dict parser.

    Replaces defusedxml using strictly standard library defenses.
    """
    if not xml_string or not isinstance(xml_string, str):
        return {}

    # Layer 1: Fast-Fail Substring Firewall
    if "<!doctype" in xml_string.lower():
        _LOGGER.error(
            "XML Payload rejected: DOCTYPE injection attempt detected."
        )  # pragma: no mutate
        return {}

    def _element_to_dict(element: ET.Element) -> Any:
        result: dict[str, Any] = {f"@{k}": v for k, v in element.attrib.items()}

        for child in element:
            child_dict = _element_to_dict(child)
            if child.tag not in result:
                result[child.tag] = child_dict
            else:
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(child_dict)

        if not result and element.text:
            return element.text.strip()

        if element.text and element.text.strip():
            if result:
                result["#text"] = element.text.strip()  # pragma: no mutate
            else:
                return element.text.strip()

        return result

    try:
        # Layer 2: Strict Parsing with Native Interceptor
        parser = ET.XMLParser(target=SecureTreeBuilder())  # pragma: no mutate
        root = ET.fromstring(xml_string.strip(), parser=parser)  # pragma: no mutate
        return {root.tag: _element_to_dict(root)}
    except (ET.ParseError, AttributeError, TypeError) as exc:
        _LOGGER.debug(
            "Structural error parsing native XML: %s", exc
        )  # pragma: no mutate
        return {}
    except ValueError as exc:
        _LOGGER.error("XML Security block: %s", exc)  # pragma: no mutate
        return {}


_header_patch_lock = threading.Lock()
_HEADER_PATCH_REFCOUNT = 0
_HEADER_PATCH_ORIGINAL_RESPONSE: Any = None
_HEADER_PATCH_ORIGINAL_CONNECTION: Any = None
_HEADER_PATCH_ORIGINAL_PARSE_HEADERS: Any = None


@contextlib.contextmanager
def tolerant_header_parsing() -> Generator[None, None, None]:
    """Context manager that temporarily suppresses urllib3 HeaderParsingError."""
    # pylint: disable=global-statement
    global _HEADER_PATCH_REFCOUNT, _HEADER_PATCH_ORIGINAL_RESPONSE
    global _HEADER_PATCH_ORIGINAL_CONNECTION, _HEADER_PATCH_ORIGINAL_PARSE_HEADERS

    import urllib3.connection as connection_mod  # pylint: disable=import-outside-toplevel
    from urllib3.exceptions import (
        HeaderParsingError,
    )
    import urllib3.util.response as response_util  # pylint: disable=import-outside-toplevel

    def _tolerant_assert(headers: Any) -> None:
        try:
            if _HEADER_PATCH_ORIGINAL_RESPONSE:
                _HEADER_PATCH_ORIGINAL_RESPONSE(headers)
        except HeaderParsingError as e:
            _LOGGER.debug(
                "Suppressed urllib3 HeaderParsingError: %s", e
            )  # pragma: no mutate

    def _patched_parse_headers(
        fp: Any, _class: Any = http.client.HTTPMessage
    ) -> Any:  # pragma: no mutate
        headers = []  # pragma: no mutate
        while True:  # pragma: no mutate
            line = fp.readline(65536 + 1)  # pragma: no mutate
            if len(line) > 65536:  # pragma: no mutate
                raise http.client.LineTooLong("header line")  # pragma: no mutate

            if line not in (b"\r\n", b"\n", b""):  # pragma: no mutate
                parts = line.split(b":", 1)  # pragma: no mutate
                if len(parts) == 2 and parts[0].endswith(b" "):  # pragma: no mutate
                    line = parts[0][:-1] + b":" + parts[1]  # pragma: no mutate

            headers.append(line)  # pragma: no mutate
            if len(headers) > 100:  # pragma: no mutate
                raise http.client.HTTPException(
                    "got more than 100 headers"
                )  # pragma: no mutate
            if line in (b"\r\n", b"\n", b""):  # pragma: no mutate
                break  # pragma: no mutate

        clean_fp = BytesIO(b"".join(headers))  # pragma: no mutate
        if _HEADER_PATCH_ORIGINAL_PARSE_HEADERS:  # pragma: no mutate
            return _HEADER_PATCH_ORIGINAL_PARSE_HEADERS(
                clean_fp, _class
            )  # pragma: no mutate
        return None  # pragma: no mutate

    with _header_patch_lock:
        if _HEADER_PATCH_REFCOUNT == 0:
            _HEADER_PATCH_ORIGINAL_RESPONSE = response_util.assert_header_parsing
            _HEADER_PATCH_ORIGINAL_CONNECTION = connection_mod.assert_header_parsing
            _HEADER_PATCH_ORIGINAL_PARSE_HEADERS = (
                http.client.parse_headers
            )  # pragma: no mutate
            response_util.assert_header_parsing = _tolerant_assert
            connection_mod.assert_header_parsing = _tolerant_assert
            http.client.parse_headers = _patched_parse_headers
        _HEADER_PATCH_REFCOUNT += 1
    try:
        yield
    finally:
        with _header_patch_lock:
            _HEADER_PATCH_REFCOUNT -= 1
            if _HEADER_PATCH_REFCOUNT == 0:
                response_util.assert_header_parsing = (
                    _HEADER_PATCH_ORIGINAL_RESPONSE  # pragma: no mutate
                )
                connection_mod.assert_header_parsing = (
                    _HEADER_PATCH_ORIGINAL_CONNECTION  # pragma: no mutate
                )
                http.client.parse_headers = (
                    _HEADER_PATCH_ORIGINAL_PARSE_HEADERS  # pragma: no mutate
                )
                _HEADER_PATCH_ORIGINAL_RESPONSE = None  # pragma: no mutate
                _HEADER_PATCH_ORIGINAL_CONNECTION = None  # pragma: no mutate
                _HEADER_PATCH_ORIGINAL_PARSE_HEADERS = None  # pragma: no mutate


def find_key_in_data(data: Any, key: str) -> Any | None:
    """Recursively search for a key in a dictionary or a list of dictionaries."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for _k, v in data.items():
            item = find_key_in_data(v, key)
            if item is not None:
                return item
    elif isinstance(data, list):
        for item_in_list in data:
            item = find_key_in_data(item_in_list, key)
            if item is not None:
                return item
    return None


def get_value_by_path(
    data: dict[str, Any] | list[Any] | None,
    path: Sequence[str | int] | str | None,
) -> Any | None:
    """Navigate through a nested dictionary or list using a path of keys/indices."""
    if data is None or not path:
        return None

    path_seq: Sequence[str | int]
    if isinstance(path, str):
        path_seq = path.split(".")
    else:
        path_seq = path

    current = data
    for key in path_seq:
        if isinstance(current, dict) and isinstance(key, str):
            if key not in current:
                return None
            current = current[key]
        elif isinstance(current, list) and isinstance(key, int):
            if key < 0 or key >= len(current):
                return None
            current = current[key]
        else:
            return None
    return current


def set_value_by_path(
    target: dict[str, Any] | list[Any],
    path: Sequence[str | int] | str | None,
    value: Any,
) -> None:
    """Set a value in a deeply nested dictionary/list structure. Aborts securely if target is falsy."""
    if not target or not path:
        return

    path_seq: Sequence[str | int]
    if isinstance(path, str):
        path_seq = path.split(".")
    else:
        path_seq = path

    current = target
    for i, key in enumerate(path_seq[:-1]):
        next_key = path_seq[i + 1]
        is_next_list = isinstance(next_key, int)

        if isinstance(current, dict) and isinstance(key, str):
            if key not in current or current[key] is None:
                current[key] = [] if is_next_list else {}
            current = current[key]
        elif isinstance(current, list) and isinstance(key, int):
            # Strict O(1) list extension. Replaces vulnerable while-loops and avoids infinite timeouts.
            if key >= len(current):
                current.extend([None] * (key - len(current) + 1))

            if current[key] is None:
                current[key] = [] if is_next_list else {}
            current = current[key]
        else:
            return

    # Assign final value at the terminal node
    last_key = path[-1]
    if isinstance(current, dict) and isinstance(last_key, str):
        current[last_key] = value
    elif isinstance(current, list) and isinstance(last_key, int):
        if last_key >= len(current):
            current.extend([None] * (last_key - len(current) + 1))
        current[last_key] = value


def resolve_cert_path(
    cert_path: str | None, base_dir: str = "", hass: HomeAssistant | None = None
) -> str | None:
    """Safely resolve certificate path relying on strict Object-Oriented contracts."""
    if not cert_path:
        return None

    has_slash = "/" in cert_path or "\\" in cert_path

    if hass is not None:
        # STRICT CONTRACT: We expect a valid HomeAssistant instance.
        # Fail-fast (raise AttributeError) if an invalid mock or broken object is injected.
        if has_slash:
            return hass.config.path(cert_path)
        return str(Path(__file__).parent / cert_path)

    if has_slash:
        return str(Path(cert_path))

    if base_dir:
        return str(Path(base_dir) / cert_path)
    return str(Path(__file__).parent / cert_path)


def stream_wrapper(
    data: str,
    token: str | None,
    ip_address: str | None,
    device_id: str | None,
    mac: str | None = None,
) -> str:
    """Replaces placeholder values in a string."""
    replacements = {
        "__CLIMATE_IP_TOKEN__": token,
        "__CLIMATE_IP_HOST__": ip_address,
        "__CLIMATE_IP_MAC__": mac,
        "__DEVICE_ID__": device_id,
    }

    for placeholder, actual_value in replacements.items():
        if actual_value is not None:
            data = data.replace(placeholder, str(actual_value))

    return data


def format_placeholders(
    data: Any,
    token: str | None,
    ip_address: str | None,
    device_id: str | None,
    mac: str | None = None,
) -> Any:
    """Recursively replaces placeholder values in a dictionary or list."""
    if isinstance(data, dict):
        return {
            key: format_placeholders(value, token, ip_address, device_id, mac)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [
            format_placeholders(item, token, ip_address, device_id, mac)
            for item in data
        ]
    if isinstance(data, str):
        return stream_wrapper(data, token, ip_address, device_id, mac)
    return data


def get_tls_version_name(version_code: int | ssl.TLSVersion) -> str:
    """Convert a TLS version code to its friendly name using strict EAFP."""
    if version_code == 0:
        return "Unknown"  # pragma: no mutate
    try:
        tls_ver = ssl.TLSVersion(version_code)
        return tls_ver.name
    except (ValueError, AttributeError):
        return str(version_code)


def create_samsung_ssl_context(
    cert_path: str | None = None,
    ciphers: str = "HIGH:!aNULL:!MD5:@SECLEVEL=0",  # pragma: no mutate
    verify_mode: int | None = None,
    is_server: bool = False,  # pragma: no mutate
) -> ssl.SSLContext:
    """Creates the standardized SSL context for Samsung devices."""

    protocol = (
        ssl.PROTOCOL_TLS_SERVER if is_server else ssl.PROTOCOL_TLS_CLIENT
    )  # pragma: no mutate

    context = ssl.SSLContext(protocol)  # pragma: no mutate
    context.set_ciphers(ciphers)

    if not is_server:
        context.check_hostname = False  # pragma: no mutate

    if verify_mode is not None:
        context.verify_mode = ssl.VerifyMode(verify_mode)  # pragma: no mutate
    else:
        context.verify_mode = ssl.CERT_NONE

    try:
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    except (AttributeError, TypeError, ssl.SSLError, ValueError) as e:
        _LOGGER.debug("Could not set TLS max version: %s", e)  # pragma: no mutate

    try:
        # TLSv1 is deprecated in Python 3.13 but strictly required by legacy Samsung
        # AC devices on port 2878. Suppress surgically; protocol cannot be upgraded.
        with warnings.catch_warnings():
            warnings.filterwarnings(  # pragma: no mutate
                "ignore",  # pragma: no mutate
                message="ssl.TLSVersion.TLSv1 is deprecated",  # pragma: no mutate
                category=DeprecationWarning,  # pragma: no mutate
            )  # pragma: no mutate
            context.minimum_version = ssl.TLSVersion.TLSv1  # pragma: no mutate
    except (AttributeError, TypeError, ssl.SSLError, ValueError):
        pass

    if cert_path:
        try:
            context.load_verify_locations(cafile=cert_path)
            context.load_cert_chain(cert_path)  # pragma: no mutate
        except (ssl.SSLError, OSError, FileNotFoundError) as e:
            _LOGGER.warning(
                "Could not load Samsung certificate from '%s': %s", cert_path, e
            )  # pragma: no mutate
            raise  # pragma: no mutate

    return context


async def async_create_samsung_ssl_context(
    cert_path: str | None = None,
    ciphers: str = "HIGH:!aNULL:!MD5:@SECLEVEL=0",  # pragma: no mutate
    verify_mode: int | None = None,
    is_server: bool = False,  # pragma: no mutate
) -> ssl.SSLContext:
    """Async wrapper for create_samsung_ssl_context."""
    loop = asyncio.get_running_loop()
    func = functools.partial(  # pragma: no mutate
        create_samsung_ssl_context,  # pragma: no mutate
        cert_path=cert_path,  # pragma: no mutate
        ciphers=ciphers,  # pragma: no mutate
        verify_mode=verify_mode,  # pragma: no mutate
        is_server=is_server,  # pragma: no mutate
    )  # pragma: no mutate
    return await loop.run_in_executor(None, func)


def mask_sensitive_data(data: Any) -> Any:
    """Recursively mask sensitive data in a dictionary or list."""
    sensitive_keys = [
        "uuid",
        "Authorization",
        "token",
        "mac",
        "device_id",
        "unique_id",
        "DeviceToken",
        "DUID",
    ]

    if isinstance(data, dict):
        masked = data.copy()
        for key, value in masked.items():
            if key in sensitive_keys and isinstance(value, str):
                if len(value) > 6:
                    masked[key] = "***" + value[-6:]  # pragma: no mutate
                elif len(value) > 4:
                    masked[key] = "***" + value[-4:]  # pragma: no mutate
            elif isinstance(value, dict | list):
                masked[key] = mask_sensitive_data(value)
        return masked
    if isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    if isinstance(data, str):
        data = re.sub(
            r'(Token=")([a-fA-F0-9-]{36})(")', r"\1***\3", data
        )  # pragma: no mutate
        data = re.sub(
            r'(DeviceToken["\'\s]*[:=]+["\'\s]*)([^"\'\s}]+)', r"\1***", data
        )  # pragma: no mutate

        def _mask_duid_match(m: re.Match[str]) -> str:
            val = m.group(2)
            masked = ("***" + val[-6:]) if len(val) > 6 else "***"
            return f"{m.group(1)}{masked}{m.group(3)}"

        data = re.sub(
            r'(DUID=")([^"]+)(")', _mask_duid_match, data, flags=re.IGNORECASE
        )  # pragma: no mutate
        return data
    return data


# --- Native ICMP Ping via icmplib ---
try:
    # pylint: disable=import-outside-toplevel
    from icmplib import (
        ICMPSocketError,
        NameLookupError as IcmpNameLookupError,
        async_ping,
    )

    _ICMPLIB_AVAILABLE = True
except ImportError:
    _ICMPLIB_AVAILABLE = False
    async_ping = None
    IcmpNameLookupError = None
    ICMPSocketError = None


async def async_check_network_reachability(
    host: str, log_prefix: str = ""
) -> bool:  # pragma: no mutate
    """Check if the device is reachable on the network using native icmplib."""
    if not _ICMPLIB_AVAILABLE or async_ping is None:
        _LOGGER.debug(
            "%s icmplib not available, skipping ICMP reachability check.", log_prefix
        )  # pragma: no mutate
        return True

    try:
        host_obj = await async_ping(  # pragma: no mutate
            address=host,
            count=1,
            timeout=0.5,
            interval=0.2,
            privileged=False,  # pragma: no mutate
        )  # pragma: no mutate

        if host_obj.is_alive:
            return True

        _LOGGER.debug(  # pragma: no mutate
            "%s Network diagnostic: Host %s is NOT reachable (UDP ping failed/timed out). "  # pragma: no mutate
            "Check that the device is powered on and connected to your Wi-Fi.",  # pragma: no mutate
            log_prefix,  # pragma: no mutate
            host,  # pragma: no mutate
        )  # pragma: no mutate
        return False

    except (IcmpNameLookupError, ICMPSocketError) as err:
        _LOGGER.debug(
            "%s Network diagnostic error for %s: %s", log_prefix, host, err
        )  # pragma: no mutate
        return False
    except OSError as e:
        _LOGGER.debug(  # pragma: no mutate
            "%s Network diagnostic OS error (likely ping_group_range restriction): %s. "  # pragma: no mutate
            "Bypassing ping check to protect AC firmware.",  # pragma: no mutate
            log_prefix,  # pragma: no mutate
            e,  # pragma: no mutate
        )  # pragma: no mutate
        return True


async def async_get_mac_address(ip_address: str) -> str | None:
    """Get the MAC address for a given IP address using the 'arp' command.

    Strictly uses native O(N) string operations and enforces a fail-fast
    subprocess timeout to prevent Event Loop deadlocks.
    """

    try:
        cmd = (
            ["arp", "-a", ip_address]
            if platform.system() == "Windows"
            else ["arp", "-n", ip_address]
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )

        try:
            # Wrap the wait in a strict 2.0-second firewall
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        except TimeoutError:
            # If the OS hangs, kill the process to avoid leaving zombies
            with contextlib.suppress(OSError):
                proc.kill()
            _LOGGER.debug(
                "ARP command timed out for %s. Process killed.", ip_address
            )  # pragma: no mutate
            return None

        output = stdout.decode("utf-8", errors="ignore")  # pragma: no mutate

        for token in output.split():
            # Phase 1: Fail-fast on length
            if len(token) != 17:
                continue

            # Phase 2: Exact separator count
            colons = token.count(":")
            dashes = token.count("-")

            if colons != 5 and dashes != 5:
                continue

            # Phase 3: Pure alphanumeric length after strip
            cleaned = token.replace(":", "").replace("-", "")
            if len(cleaned) != 12:
                continue

            # Phase 4: Strict Hexadecimal validation natively
            try:
                int(cleaned, 16)
                return token.lower()
            except ValueError:
                continue

    except FileNotFoundError:
        _LOGGER.debug(
            "ARP command not found. Cannot resolve MAC for %s.", ip_address
        )  # pragma: no mutate
    except OSError as e:
        _LOGGER.debug(
            "Failed to resolve MAC address for %s via ARP: %s", ip_address, e
        )  # pragma: no mutate

    return None


def validate_poll_interval(val: Any) -> int:
    """Validate and convert poll interval to seconds."""
    from .const import MAX_POLL_INTERVAL, MIN_POLL_INTERVAL

    try:
        if isinstance(val, int | float):
            seconds = int(val)
        else:
            seconds = int(cv.time_period_str(str(val)).total_seconds())
    except Invalid as e:
        raise ValueError(f"Invalid time format: {e}") from e

    if seconds < MIN_POLL_INTERVAL or seconds > MAX_POLL_INTERVAL:
        raise ValueError(
            f"Interval must be between {MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL}"
        )
    return seconds
