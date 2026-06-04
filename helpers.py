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
import os
import re
import ssl
import threading
from io import BytesIO
from typing import Any

import xml.etree.ElementTree as ET_types

import defusedxml.ElementTree as ET

_LOGGER = logging.getLogger(__name__)

# Precompiled regex for MAC address (e.g., 00:11:22:33:44:55 or 00-11-22-33-44-55)
RE_MAC_ADDRESS = re.compile(r"([0-9a-f]{2}[:-]){5}([0-9a-f]{2})")

# Precompiled regex for a safe Samsung DeviceToken: alphanumeric, dash, underscore (8-128 chars)
_SAFE_TOKEN_RE = re.compile(r'^[a-zA-Z0-9_\-]{8,128}$')


def sanitize_token(token: str | None) -> str | None:
    """Validate that a Samsung DeviceToken only contains safe characters.

    Accepts alphanumeric characters, dashes, and underscores (8-128 chars).
    Rejects tokens containing Jinja2 delimiters, control characters, or
    injection sequences that could be evaluated by the template engine.

    Returns the token unchanged if valid, or None if suspicious.
    """
    if not token:
        return None
    if _SAFE_TOKEN_RE.match(token):
        return token
    _LOGGER.warning(
        "Token rejected: contains unexpected characters. "
        "Expected alphanumeric/dash/underscore (8-128 chars). "
        "Got length=%d, starts_with=%r",
        len(token),
        token[:6],
    )
    return None


def parse_entity_category(raw: str | None) -> "EntityCategory | None":
    """Parse a raw entity_category string into an EntityCategory enum value.

    Returns None and logs a warning if the value is unrecognised.
    Extracted from sensor.py / switch.py to comply with the DRY principle (Issue #10).
    """
    from homeassistant.helpers.entity import EntityCategory  # pylint: disable=import-outside-toplevel

    if not raw:
        return None
    try:
        return EntityCategory(raw)
    except ValueError:
        _LOGGER.warning(
            "Invalid entity_category value '%s' — ignoring. "
            "Valid values: %s",
            raw,
            [e.value for e in EntityCategory],
        )
        return None




def safe_xml_to_dict(xml_string: str) -> dict[str, Any]:
    """
    Parse an XML string into a dictionary using defusedxml for security.
    Implements a structure similar to xmltodict (attributes prefixed with '@').
    Returns an empty dict on parse or structural errors.
    """

    def _element_to_dict(element: ET_types.Element) -> Any:
        # Extract attributes with '@' prefix
        result: dict[str, Any] = {f"@{k}": v for k, v in element.attrib.items()}

        # Process children
        for child in element:
            child_dict = _element_to_dict(child)
            if child.tag not in result:
                result[child.tag] = child_dict
            else:
                # If tag already exists, convert to list
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(child_dict)

        # If it has text and no children/attributes, return the text
        if not result and element.text:
            return element.text.strip()

        # If it has text AND (children or attributes), add it as '#text'
        if element.text and element.text.strip():
            # xmltodict only adds #text if there are other things
            if result:
                result["#text"] = element.text.strip()
            else:
                return element.text.strip()

        return result

    try:
        # Strip the XML string to avoid leading whitespace issues with ET.fromstring
        root = ET.fromstring(xml_string.strip())
        return {root.tag: _element_to_dict(root)}
    except (ET_types.ParseError, AttributeError, TypeError) as exc:
        # Legitimate parse/structural errors — return empty dict and log at DEBUG.
        _LOGGER.debug("safe_xml_to_dict: failed to parse XML response: %s", exc)
        return {}
    except ValueError as exc:
        # ValueError covers structural issues, BUT defusedxml security exceptions
        # (EntitiesForbidden, DTDForbidden, etc.) are subclasses of ValueError.
        # Those MUST propagate — they indicate deliberate attacks.
        # pylint: disable=import-outside-toplevel
        from defusedxml.common import DefusedXmlException
        if isinstance(exc, DefusedXmlException):
            raise
        _LOGGER.debug("safe_xml_to_dict: failed to parse XML response: %s", exc)
        return {}

# --- Scoped monkey-patch for urllib3 malformed header tolerance ---
# Some Samsung AC units send HTTP responses with malformed headers (e.g. spaces before colons)
# that urllib3 rejects. Instead of globally patching urllib3 (affecting the entire HA process),
# this context manager temporarily overrides the check only during our legacy requests.
#
# DEPRECATION NOTE: This entire workaround will be removed in a future release
# when the legacy `requests` platform is fully dropped in favor of `connection_raw.py`
# (which natively handles malformed buffers without monkey-patching standard libraries).
_header_patch_lock = threading.Lock()
_HEADER_PATCH_REFCOUNT = 0
_HEADER_PATCH_ORIGINAL_RESPONSE: Any = None
_HEADER_PATCH_ORIGINAL_CONNECTION: Any = None
_HEADER_PATCH_ORIGINAL_PARSE_HEADERS: Any = None


@contextlib.contextmanager
def tolerant_header_parsing():
    """Context manager that temporarily suppresses urllib3 HeaderParsingError
    and patches http.client.parse_headers to fix spaces before colons.

    Thread-safe via reference counting: the first caller patches, subsequent
    callers just increment the counter. The last caller to exit restores.
    """
    # pylint: disable=global-statement
    global _HEADER_PATCH_REFCOUNT, _HEADER_PATCH_ORIGINAL_RESPONSE
    global _HEADER_PATCH_ORIGINAL_CONNECTION, _HEADER_PATCH_ORIGINAL_PARSE_HEADERS

    import urllib3.connection as connection_mod  # pylint: disable=import-outside-toplevel
    import urllib3.util.response as response_util  # pylint: disable=import-outside-toplevel
    from urllib3.exceptions import (
        HeaderParsingError,  # pylint: disable=import-outside-toplevel
    )

    def _tolerant_assert(headers: Any) -> None:
        try:
            if _HEADER_PATCH_ORIGINAL_RESPONSE:
                _HEADER_PATCH_ORIGINAL_RESPONSE(headers)
        except HeaderParsingError as e:
            _LOGGER.debug("Suppressed urllib3 HeaderParsingError: %s", e)

    def _patched_parse_headers(fp: Any, _class: Any = http.client.HTTPMessage) -> Any:
        headers = []
        while True:
            line = fp.readline(65536 + 1)
            if len(line) > 65536:
                raise http.client.LineTooLong("header line")

            # FIX: Remove space before colon in header names
            # e.g. b'X-API-Version : v1.0.0\\r\\n' -> b'X-API-Version: v1.0.0\\r\\n'
            if line not in (b"\r\n", b"\n", b""):
                parts = line.split(b":", 1)
                if len(parts) == 2 and parts[0].endswith(b" "):
                    line = parts[0][:-1] + b":" + parts[1]

            headers.append(line)
            if len(headers) > 100:
                raise http.client.HTTPException("got more than 100 headers")
            if line in (b"\r\n", b"\n", b""):
                break

        # Now feed the cleaned headers back to the original parser
        clean_fp = BytesIO(b"".join(headers))
        if _HEADER_PATCH_ORIGINAL_PARSE_HEADERS:
            return _HEADER_PATCH_ORIGINAL_PARSE_HEADERS(clean_fp, _class)
        return None

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
                response_util.assert_header_parsing = _HEADER_PATCH_ORIGINAL_RESPONSE
                connection_mod.assert_header_parsing = _HEADER_PATCH_ORIGINAL_CONNECTION
                http.client.parse_headers = _HEADER_PATCH_ORIGINAL_PARSE_HEADERS
                _HEADER_PATCH_ORIGINAL_RESPONSE = None
                _HEADER_PATCH_ORIGINAL_CONNECTION = None
                _HEADER_PATCH_ORIGINAL_PARSE_HEADERS = None


def find_key_in_data(data: Any, key: str) -> Any | None:
    """
    Recursively search for a key in a dictionary or a list of dictionaries.
    """
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
    """
    Navigate through a nested dictionary using a list of keys.
    Returns the found value or None if the path does not exist.
    """
    if not data or not path:
        return None
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def resolve_cert_path(cert_path: str | None, base_dir: str, hass: Any | None = None) -> str | None:
    """Safely resolve certificate path.

    If hass is provided, resolves relative paths using hass.config.path.
    Otherwise, resolves relative to base_dir.
    """
    if not cert_path:
        return None
    if os.path.isabs(cert_path) or os.path.dirname(cert_path):
        return cert_path

    if hass and hasattr(hass, "config") and hasattr(hass.config, "path"):
        return os.path.join(os.path.dirname(__file__), cert_path)

    return os.path.join(base_dir, cert_path)


def stream_wrapper(
    data: str,
    token: str | None,
    ip_address: str | None,
    device_id: str | None,
    mac: str | None = None,
) -> str:
    """
    Replaces placeholder values in a string.
    """
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
    """
    Recursively replaces placeholder values in a dictionary or list.
    """
    if isinstance(data, dict):
        return {
            key: format_placeholders(value, token, ip_address, device_id, mac)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [
            format_placeholders(item, token, ip_address, device_id, mac) for item in data
        ]
    if isinstance(data, str):
        return stream_wrapper(data, token, ip_address, device_id, mac)
    return data


def get_tls_version_name(version_code: int | ssl.TLSVersion) -> str:
    """Safely convert a TLS version code to its friendly name."""
    if version_code == 0:
        return "Unknown"
    if hasattr(ssl, "TLSVersion"):
        try:
            tls_ver = ssl.TLSVersion(version_code)
            return tls_ver.name if hasattr(tls_ver, "name") else str(version_code)
        except ValueError:
            return str(version_code)
    return str(version_code)


def create_samsung_ssl_context(
    cert_path: str | None = None,
    ciphers: str = "HIGH:!aNULL:!MD5:@SECLEVEL=0",
    verify_mode: int | None = None,
    is_server: bool = False,
) -> ssl.SSLContext:
    """
    Creates the standardized SSL context for Samsung devices.
    Enforces PROTOCOL_TLS_CLIENT (or PROTOCOL_TLS_SERVER), sets verify mode, loads ciphers,
    and caps the maximum TLS version to TLSv1_2 to prevent the AC handshake bug.

    Default cipher suite is ``HIGH:!aNULL:!MD5:@SECLEVEL=0`` (secure-by-default).
    Callers that must support legacy Samsung hardware (RSA-only, no DH) should pass
    ``ciphers="ALL:@SECLEVEL=0"`` explicitly.
    """
    if is_server:
        protocol = getattr(
            ssl, "PROTOCOL_TLS_SERVER", getattr(ssl, "PROTOCOL_TLS", ssl.PROTOCOL_TLSv1)
        )
    else:
        protocol = getattr(
            ssl, "PROTOCOL_TLS_CLIENT", getattr(ssl, "PROTOCOL_TLS", ssl.PROTOCOL_TLSv1)
        )

    context = ssl.SSLContext(protocol)
    context.set_ciphers(ciphers)

    if not is_server:
        context.check_hostname = False

    if verify_mode is not None:
        context.verify_mode = ssl.VerifyMode(verify_mode)
    else:
        context.verify_mode = ssl.CERT_NONE

    if hasattr(ssl, "TLSVersion"):
        if hasattr(ssl.TLSVersion, "TLSv1_2"):
            try:
                context.maximum_version = ssl.TLSVersion.TLSv1_2
            except (AttributeError, TypeError, ssl.SSLError) as e:
                _LOGGER.debug("Could not set TLS max version: %s", e)
        if hasattr(ssl.TLSVersion, "TLSv1"):
            try:
                context.minimum_version = ssl.TLSVersion.TLSv1
            except (AttributeError, TypeError, ssl.SSLError):
                pass

    if cert_path:
        try:
            context.load_verify_locations(cafile=cert_path)
            context.load_cert_chain(cert_path)
        except (ssl.SSLError, OSError, FileNotFoundError) as e:
            _LOGGER.warning("Could not load Samsung certificate from '%s': %s", cert_path, e)
            raise

    # Versions are queried but only used for potential logging; assign to _ to silence warnings.
    _ = get_tls_version_name(getattr(context, "minimum_version", 0))
    _ = get_tls_version_name(getattr(context, "maximum_version", 0))

    return context


async def async_create_samsung_ssl_context(
    cert_path: str | None = None,
    ciphers: str = "HIGH:!aNULL:!MD5:@SECLEVEL=0",
    verify_mode: int | None = None,
    is_server: bool = False,
) -> ssl.SSLContext:
    """
    Async wrapper for create_samsung_ssl_context.
    Executes the blocking disk I/O parts of the SSL context creation
    in the default executor to avoid blocking the Home Assistant event loop.

    Default cipher suite is ``HIGH:!aNULL:!MD5:@SECLEVEL=0`` (secure-by-default).
    """
    loop = asyncio.get_running_loop()
    func = functools.partial(
        create_samsung_ssl_context,
        cert_path=cert_path,
        ciphers=ciphers,
        verify_mode=verify_mode,
        is_server=is_server,
    )
    return await loop.run_in_executor(None, func)


def mask_sensitive_data(data: Any) -> Any:
    """
    Recursively mask sensitive data in a dictionary or list.
    Handles: uuid, Authorization, token, mac, device_id, unique_id, DeviceToken, DUID.
    """
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
            if key in sensitive_keys and isinstance(value, str) and len(value) > 6:
                masked[key] = "***" + value[-6:]
            elif key in sensitive_keys and isinstance(value, str) and len(value) > 4:
                masked[key] = "***" + value[-4:]
            elif isinstance(value, (dict, list)):
                masked[key] = mask_sensitive_data(value)
        return masked
    if isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    if isinstance(data, str):
        # Mask Token="..." pattern
        data = re.sub(r'(Token=")([a-fA-F0-9-]{36})(")', r"\1***\3", data)
        # Mask DeviceToken="..." or DeviceToken : "..." pattern securely without matching random text
        data = re.sub(r'(DeviceToken["\'\s]*[:=]+["\'\s]*)([^"\'\s}]+)', r"\1***", data)
        # Mask DUID="..." pattern
        data = re.sub(r'(DUID=")([^"]+)(")', r"\1***\3", data)
        return data
    return data


# --- Native ICMP Ping via icmplib ---
try:
    from icmplib import (
        ICMPSocketError,
    )
    from icmplib import (
        NameLookupError as IcmpNameLookupError,  # pylint: disable=import-outside-toplevel
    )
    from icmplib import (
        async_ping,
    )

    _ICMPLIB_AVAILABLE = True
except ImportError:
    _ICMPLIB_AVAILABLE = False
    async_ping = None  # type: ignore[assignment]
    IcmpNameLookupError = None  # type: ignore[assignment, misc]
    ICMPSocketError = None  # type: ignore[assignment, misc]


async def async_check_network_reachability(host: str, log_prefix: str = "") -> bool:
    """Check if the device is reachable on the network using native icmplib.
    Uses non-privileged (UDP) ping to avoid root permission requirements in Docker/HAOS.
    Results are logged at DEBUG level to help diagnose disconnections.
    """
    if not _ICMPLIB_AVAILABLE or async_ping is None:
        _LOGGER.debug("%s icmplib not available, skipping ICMP reachability check.", log_prefix)
        return True

    try:
        # async_ping is non-blocking and handles socket pooling.
        # We FORCE privileged=False to use Datagram (UDP) sockets.
        # This prevents kernel permission errors in Docker/Home Assistant OS.
        host_obj = await async_ping(
            address=host, count=1, timeout=0.5, interval=0.2, privileged=False
        )

        if host_obj.is_alive:
            _LOGGER.debug(
                "%s Network diagnostic: Host %s responded to UDP ping (RTT: %sms). "
                "Network is OK.",
                log_prefix,
                host,
                host_obj.avg_rtt,
            )
            return True

        _LOGGER.debug(
            "%s Network diagnostic: Host %s is NOT reachable (UDP ping failed/timed out). "
            "Check that the device is powered on and connected to your Wi-Fi.",
            log_prefix,
            host,
        )
        return False

    except (IcmpNameLookupError, ICMPSocketError) as err:  # type: ignore[misc]
        _LOGGER.debug("%s Network diagnostic error for %s: %s", log_prefix, host, err)
        return False
    except OSError as e:
        # Fallback si el Kernel de HAOS bloquea incluso los sockets UDP (ping_group_range)
        _LOGGER.debug(
            "%s Network diagnostic OS error (likely ping_group_range restriction): %s. "
            "Bypassing ping check to protect AC firmware.",
            log_prefix,
            e,
        )
        # We return True to let the upper layers attempt the TCP connection as a last resort
        return True


async def async_get_mac_address(ip_address: str) -> str | None:
    """
    Get the MAC address for a given IP address using the 'arp' command.
    Avoids external library dependencies like 'getmac'.
    """
    import platform

    try:
        # Determine the correct command and arguments based on the OS
        if platform.system() == "Windows":
            cmd = ["arp", "-a", ip_address]
        else:
            # Linux/Unix-like systems
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
        # 'arp' command not available on this system (e.g. minimal container)
        _LOGGER.debug("ARP command not found. Cannot resolve MAC for %s.", ip_address)
    except (OSError, UnicodeDecodeError, asyncio.TimeoutError) as e:
        _LOGGER.debug("Failed to resolve MAC address for %s via ARP: %s", ip_address, e)

    return None
