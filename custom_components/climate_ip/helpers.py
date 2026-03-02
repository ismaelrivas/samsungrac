import logging
import copy
import contextlib
import threading
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

# --- H-12: Scoped monkey-patch for urllib3 malformed header tolerance ---
# Some Samsung AC units send HTTP responses with malformed headers that urllib3
# rejects. Instead of globally patching urllib3 (affecting the entire HA process),
# this context manager temporarily overrides the check only during our requests.
_header_patch_lock = threading.Lock()
_header_patch_refcount = 0
_header_patch_original_response = None
_header_patch_original_connection = None
_header_patch_original_parse_headers = None

@contextlib.contextmanager
def tolerant_header_parsing():
    """Context manager that temporarily suppresses urllib3 HeaderParsingError
    and patches http.client.parse_headers to fix spaces before colons.

    Thread-safe via reference counting: the first caller patches, subsequent
    callers just increment the counter. The last caller to exit restores.
    """
    global _header_patch_refcount, _header_patch_original_response
    global _header_patch_original_connection, _header_patch_original_parse_headers

    import urllib3.util.response as response_util
    import urllib3.connection as connection_mod
    from urllib3.exceptions import HeaderParsingError
    import http.client
    from io import BytesIO

    def _tolerant_assert(headers):
        try:
            _header_patch_original_response(headers)
        except HeaderParsingError as e:
            _LOGGER.debug("Suppressed urllib3 HeaderParsingError: %s", e)

    def _patched_parse_headers(fp, _class=http.client.HTTPMessage):
        headers = []
        while True:
            line = fp.readline(http.client._MAXLINE + 1)
            if len(line) > http.client._MAXLINE:
                raise http.client.LineTooLong("header line")
            
            # FIX: Remove space before colon in header names
            # e.g. b'X-API-Version : v1.0.0\\r\\n' -> b'X-API-Version: v1.0.0\\r\\n'
            if line not in (b'\r\n', b'\n', b''):
                parts = line.split(b':', 1)
                if len(parts) == 2 and parts[0].endswith(b' '):
                    line = parts[0][:-1] + b':' + parts[1]
                    
            headers.append(line)
            if len(headers) > http.client._MAXHEADERS:
                raise http.client.HTTPException("got more than %d headers" % http.client._MAXHEADERS)
            if line in (b'\r\n', b'\n', b''):
                break
                
        # Now feed the cleaned headers back to the original parser
        clean_fp = BytesIO(b''.join(headers))
        return _header_patch_original_parse_headers(clean_fp, _class)

    with _header_patch_lock:
        if _header_patch_refcount == 0:
            _header_patch_original_response = response_util.assert_header_parsing
            _header_patch_original_connection = connection_mod.assert_header_parsing
            _header_patch_original_parse_headers = http.client.parse_headers
            response_util.assert_header_parsing = _tolerant_assert
            connection_mod.assert_header_parsing = _tolerant_assert
            http.client.parse_headers = _patched_parse_headers
        _header_patch_refcount += 1
    try:
        yield
    finally:
        with _header_patch_lock:
            _header_patch_refcount -= 1
            if _header_patch_refcount == 0:
                response_util.assert_header_parsing = _header_patch_original_response
                connection_mod.assert_header_parsing = _header_patch_original_connection
                http.client.parse_headers = _header_patch_original_parse_headers
                _header_patch_original_response = None
                _header_patch_original_connection = None
                _header_patch_original_parse_headers = None

def find_key_in_data(data, key):
    """
    Recursively search for a key in a dictionary or a list of dictionaries.
    """
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for k, v in data.items():
            item = find_key_in_data(v, key)
            if item is not None:
                return item
    elif isinstance(data, list):
        for i, item_in_list in enumerate(data):
            item = find_key_in_data(item_in_list, key)
            if item is not None:
                return item
    return None

def get_value_by_path(data: dict, path: list) -> any:
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

def stream_wrapper(data: str, token: str | None, ip_address: str | None, device_id: str | None) -> str:
    """
    Replaces placeholder values in a string.
    """
    if token is not None:
        data = data.replace("__CLIMATE_IP_TOKEN__", token)
    if ip_address is not None:
        data = data.replace("__CLIMATE_IP_HOST__", ip_address)
    if device_id is not None:
        data = data.replace("__DEVICE_ID__", str(device_id))
    return data

def get_tls_version_name(version_code: Any) -> str:
    """Safely convert a TLS version code to its friendly name."""
    import ssl
    if hasattr(ssl, 'TLSVersion'):
        try:
            return ssl.TLSVersion(version_code).name
        except ValueError:
            return str(version_code)
    return str(version_code)

def create_samsung_ssl_context(
    cert_path: str | None = None,
    ciphers: str = "ALL:@SECLEVEL=0",
    verify_mode: Any = None,
    is_server: bool = False,
) -> Any:
    """
    Creates the standardized SSL context for Samsung devices.
    Enforces PROTOCOL_TLS_CLIENT (or PROTOCOL_TLS_SERVER), sets verify mode, loads ciphers,
    and caps the maximum TLS version to TLSv1_2 to prevent the AC handshake bug.
    """
    import ssl
    import asyncio
    
    if is_server:
        protocol = getattr(ssl, 'PROTOCOL_TLS_SERVER', getattr(ssl, 'PROTOCOL_TLS', ssl.PROTOCOL_TLSv1))
    else:
        protocol = getattr(ssl, 'PROTOCOL_TLS_CLIENT', getattr(ssl, 'PROTOCOL_TLS', ssl.PROTOCOL_TLSv1))
        
    context = ssl.SSLContext(protocol)
    
    context.set_ciphers(ciphers)
    
    if not is_server:
        context.check_hostname = False
        
    if verify_mode is not None:
        context.verify_mode = verify_mode
    else:
        context.verify_mode = ssl.CERT_NONE
        
    if hasattr(ssl, 'TLSVersion'):
        if hasattr(ssl.TLSVersion, 'TLSv1_2'):
            try:
                context.maximum_version = ssl.TLSVersion.TLSv1_2
            except Exception as e:
                _LOGGER.debug("Could not set TLS max version: %s", e)
        if hasattr(ssl.TLSVersion, 'TLSv1'):
            try:
                context.minimum_version = ssl.TLSVersion.TLSv1
            except Exception:
                pass

    if cert_path:
        context.load_verify_locations(cafile=cert_path)
        context.load_cert_chain(cert_path)

    min_ver = get_tls_version_name(getattr(context, 'minimum_version', 'Unknown'))
    max_ver = get_tls_version_name(getattr(context, 'maximum_version', 'Unknown'))
    # _LOGGER.debug("Shared SSLContext configured. Min: %s, Max: %s, Cert: %s", min_ver, max_ver, bool(cert_path))

    return context

async def async_create_samsung_ssl_context(
    cert_path: str | None = None,
    ciphers: str = "ALL:@SECLEVEL=0",
    verify_mode: Any = None,
    is_server: bool = False,
) -> Any:
    """
    Async wrapper for create_samsung_ssl_context.
    Executes the blocking disk I/O parts of the SSL context creation
    in the default executor to avoid blocking the Home Assistant event loop.
    """
    import asyncio
    import functools
    loop = asyncio.get_running_loop()
    func = functools.partial(
        create_samsung_ssl_context,
        cert_path=cert_path,
        ciphers=ciphers,
        verify_mode=verify_mode,
        is_server=is_server
    )
    return await loop.run_in_executor(None, func)

def mask_sensitive_data(data: Any) -> Any:
    """
    Recursively mask sensitive data in a dictionary or list.
    Handles: uuid, Authorization, token, mac, device_id, unique_id, DeviceToken, DUID.
    """
    SENSITIVE_KEYS = ["uuid", "Authorization", "token", "mac", "device_id", "unique_id", "DeviceToken", "DUID"]
    
    if isinstance(data, dict):
        masked = data.copy()
        for key, value in masked.items():
            if key in SENSITIVE_KEYS and isinstance(value, str) and len(value) > 6:
                masked[key] = "***" + value[-6:]
            elif key in SENSITIVE_KEYS and isinstance(value, str) and len(value) > 4:
                masked[key] = "***" + value[-4:]
            elif isinstance(value, (dict, list)):
                masked[key] = mask_sensitive_data(value)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        # Mask Token="..." pattern
        data = re.sub(r'(Token=")([a-fA-F0-9-]{36})(")', r'\1***\3', data)
        # Mask DeviceToken="..." or DeviceToken : "..." pattern
        data = re.sub(r'(DeviceToken["\s:]+)([^"\s}]+)', r'\1***', data)
        # Mask DUID="..." pattern
        data = re.sub(r'(DUID=")([^"]+)(")', r'\1***\3', data)
        return data
    return data

# --- H-??/Phase 6: Native ICMP Ping via icmplib ---
from icmplib import SocketPermissionError, ping as icmp_ping_sync
import functools

@functools.lru_cache(maxsize=None)
def _can_use_icmp_lib_with_privilege() -> bool:
    """Verifica si el kernel actual admite la creación de sockets ICMP crudos."""
    try:
        # Lanzamos un ping síncrono nulo a localhost estrictamente
        # para probar la infraestructura de permisos del SO.
        icmp_ping_sync("127.0.0.1", count=0, timeout=0, privileged=True)
        return True
    except SocketPermissionError:
        # Bloqueado (Docker sin root, Virtualenv, Podman) -> Fallback a datagramas
        return False
    except Exception as e:
        _LOGGER.debug("Error unexpected during privilege check: %s", e)
        return False


async def async_check_network_reachability(host: str, log_prefix: str = "") -> bool:
    """Check if the device is reachable on the network using native icmplib.
    Results are logged at DEBUG level to help diagnose disconnections.
    """
    from icmplib import async_ping, NameLookupError, ICMPSocketError
    import asyncio

    is_privileged = _can_use_icmp_lib_with_privilege()

    try:
        # async_ping is non-blocking and handles ICMP socket pooling.
        # We use a 2-second timeout and 1 packet as we only care if it's alive.
        host_obj = await async_ping(
            address=host,
            count=1,
            timeout=2.0,
            interval=0.2,
            privileged=is_privileged
        )
        
        if host_obj.is_alive:
            _LOGGER.debug(
                "%s Network diagnostic: Host %s responded to ICMP ping (RTT: %sms). "
                "Network is OK.",
                log_prefix, host, host_obj.avg_rtt
            )
            return True
        else:
            _LOGGER.debug(
                "%s Network diagnostic: Host %s is NOT reachable (ICMP ping failed/timed out). "
                "Check that the device is powered on and connected to your Wi-Fi.",
                log_prefix, host
            )
            return False

    except NameLookupError as err:
        _LOGGER.debug("%s Network diagnostic: DNS Resolution failed for %s: %s", log_prefix, host, err)
        return False
    except ICMPSocketError as err:
        _LOGGER.warning("%s Network diagnostic: Socket error (Errno 24?) for %s: %s", log_prefix, host, err)
        return False
    except Exception as e:
        _LOGGER.warning("%s Network diagnostic (ping) error: %s", log_prefix, e)
        return False