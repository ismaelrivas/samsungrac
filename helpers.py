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

import asyncio
import contextlib
import functools
import http.client
import logging
from pathlib import Path
import re
import ssl
import threading
from io import BytesIO
from typing import TYPE_CHECKING, Any

import xml.etree.ElementTree as ET_types
import defusedxml.ElementTree as ET

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity import EntityCategory

_LOGGER = logging.getLogger(__name__)

# Precompiled regex for MAC address (e.g., 00:11:22:33:44:55 or 00-11-22-33-44-55)
RE_MAC_ADDRESS = re.compile(r"([0-9a-f]{2}[:-]){5}([0-9a-f]{2})")

# Precompiled regex for a safe Samsung DeviceToken: alphanumeric, dash, underscore (8-128 chars)
_SAFE_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_\-]{8,128}$")


def sanitize_token(token: str | None) -> str | None:
    """Validate that a Samsung DeviceToken only contains safe characters."""
    if not token:
        return None
    if _SAFE_TOKEN_RE.match(token):
        return token
    _LOGGER.warning(  # pragma: no mutate
        "Token rejected: contains unexpected characters. "  # pragma: no mutate
        "Expected alphanumeric/dash/underscore (8-128 chars). "  # pragma: no mutate
        "Got length=%d, starts_with=%r",  # pragma: no mutate
        len(token),  # pragma: no mutate
        token[:6],  # pragma: no mutate
    )  # pragma: no mutate
    return None


def parse_entity_category(raw: str | None) -> "EntityCategory | None":
    """Parse a raw entity_category string into an EntityCategory enum value."""
    from homeassistant.helpers.entity import EntityCategory  # pylint: disable=import-outside-toplevel

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


def safe_xml_to_dict(xml_string: str) -> dict[str, Any]:
    """Parse an XML string into a dictionary using defusedxml for security."""

    def _element_to_dict(element: ET_types.Element) -> Any:
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
        root = ET.fromstring(xml_string.strip())
        return {root.tag: _element_to_dict(root)}
    except (ET_types.ParseError, AttributeError, TypeError) as exc:
        _LOGGER.debug(
            "safe_xml_to_dict: failed to parse XML response: %s", exc
        )  # pragma: no mutate
        return {}
    except ValueError as exc:
        from defusedxml.common import DefusedXmlException  # pylint: disable=import-outside-toplevel

        if isinstance(exc, DefusedXmlException):
            raise  # pragma: no mutate
        _LOGGER.debug(
            "safe_xml_to_dict: failed to parse XML response: %s", exc
        )  # pragma: no mutate
        return {}


_header_patch_lock = threading.Lock()
_HEADER_PATCH_REFCOUNT = 0
_HEADER_PATCH_ORIGINAL_RESPONSE: Any = None
_HEADER_PATCH_ORIGINAL_CONNECTION: Any = None
_HEADER_PATCH_ORIGINAL_PARSE_HEADERS: Any = None


@contextlib.contextmanager
def tolerant_header_parsing():
    """Context manager that temporarily suppresses urllib3 HeaderParsingError."""
    # pylint: disable=global-statement
    global _HEADER_PATCH_REFCOUNT, _HEADER_PATCH_ORIGINAL_RESPONSE
    global _HEADER_PATCH_ORIGINAL_CONNECTION, _HEADER_PATCH_ORIGINAL_PARSE_HEADERS

    import urllib3.connection as connection_mod  # pylint: disable=import-outside-toplevel
    import urllib3.util.response as response_util  # pylint: disable=import-outside-toplevel
    from urllib3.exceptions import HeaderParsingError  # pylint: disable=import-outside-toplevel

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
            _HEADER_PATCH_ORIGINAL_PARSE_HEADERS = http.client.parse_headers
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


def get_value_by_path(data: dict[str, Any], path: list[str]) -> Any | None:
    """Navigate through a nested dictionary using a list of keys."""
    if not data or not path:
        return None
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def resolve_cert_path(
    cert_path: str | None, base_dir: str = "", hass: "HomeAssistant | None" = None
) -> str | None:
    """Safely resolve certificate path using pathlib and Home Assistant dual-resolution rules."""
    if not cert_path:
        return None
    if "/" in cert_path or "\\" in cert_path:
        if hass is not None:
            try:
                return hass.config.path(cert_path)
            except AttributeError:
                pass
        return str(Path(cert_path))

    if hass is not None:
        try:
            _ = hass.config.path  # pragma: no mutate
            return str(Path(__file__).parent / cert_path)
        except AttributeError:
            pass

    return (
        str(Path(base_dir) / cert_path)
        if base_dir
        else str(Path(__file__).parent / cert_path)
    )


def stream_wrapper(
    data: str,
    token: str | None,
    ip_address: str | None,
    device_id: str | None,
    mac: str | None = None,
) -> str:
    """Replaces placeholder values in a string."""
    if token is not None:
        data = data.replace("__CLIMATE_IP_TOKEN__", str(token))
    if ip_address is not None:
        data = data.replace("__CLIMATE_IP_HOST__", str(ip_address))
    if mac is not None:
        data = data.replace("__CLIMATE_IP_MAC__", str(mac))
    if device_id is not None:
        data = data.replace("__DEVICE_ID__", str(device_id))
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
            elif isinstance(value, (dict, list)):
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
    from icmplib import ICMPSocketError
    from icmplib import NameLookupError as IcmpNameLookupError  # pylint: disable=import-outside-toplevel
    from icmplib import async_ping

    _ICMPLIB_AVAILABLE = True
except ImportError:
    _ICMPLIB_AVAILABLE = False
    async_ping = None  # type: ignore[assignment]
    IcmpNameLookupError = None  # type: ignore[assignment, misc]
    ICMPSocketError = None  # type: ignore[assignment, misc]


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
            _LOGGER.debug(  # pragma: no mutate
                "%s Network diagnostic: Host %s responded to UDP ping (RTT: %sms). Network is OK.",  # pragma: no mutate
                log_prefix,  # pragma: no mutate
                host,  # pragma: no mutate
                host_obj.avg_rtt,  # pragma: no mutate
            )  # pragma: no mutate
            return True

        _LOGGER.debug(  # pragma: no mutate
            "%s Network diagnostic: Host %s is NOT reachable (UDP ping failed/timed out). "  # pragma: no mutate
            "Check that the device is powered on and connected to your Wi-Fi.",  # pragma: no mutate
            log_prefix,  # pragma: no mutate
            host,  # pragma: no mutate
        )  # pragma: no mutate
        return False

    except (IcmpNameLookupError, ICMPSocketError) as err:  # type: ignore[misc]
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
    """Get the MAC address for a given IP address using the 'arp' command."""
    import platform

    try:
        if platform.system() == "Windows":  # pragma: no mutate
            cmd = ["arp", "-a", ip_address]
        else:
            cmd = ["arp", "-n", ip_address]

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().lower()

        match = RE_MAC_ADDRESS.search(output)
        if match:
            return match.group(0)

    except FileNotFoundError:
        _LOGGER.debug(
            "ARP command not found. Cannot resolve MAC for %s.", ip_address
        )  # pragma: no mutate
    except (OSError, UnicodeDecodeError, asyncio.TimeoutError) as e:
        _LOGGER.debug(
            "Failed to resolve MAC address for %s via ARP: %s", ip_address, e
        )  # pragma: no mutate

    return None


def validate_poll_interval(val: Any) -> int:
    """Validate and convert poll interval to seconds."""
    from homeassistant.helpers import config_validation as cv
    from voluptuous.error import Invalid
    from .const import MIN_POLL_INTERVAL, MAX_POLL_INTERVAL

    try:
        if isinstance(val, (int, float)):
            seconds = int(val)
        else:
            seconds = int(cv.time_period_str(str(val)).total_seconds())
    except Invalid as e:
        raise ValueError(f"Invalid time format: {e}")

    if seconds < MIN_POLL_INTERVAL or seconds > MAX_POLL_INTERVAL:
        raise ValueError(
            f"Interval must be between {MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL}"
        )
    return seconds
