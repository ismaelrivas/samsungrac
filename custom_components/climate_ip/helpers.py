import logging
import copy
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

def find_key_in_data(data, key):
    """
    Recursively search for a key in a dictionary or a list of dictionaries.
    """
    _LOGGER.debug(f"find_key_in_data: Searching for '{key}' in data type: {type(data)}")

    if isinstance(data, dict):
        _LOGGER.debug(f"find_key_in_data: Current dict keys: {data.keys()}")
        if key in data:
            _LOGGER.debug(f"find_key_in_data: Found '{key}' in current dict: {data[key]}")
            return data[key]
        for k, v in data.items():
            _LOGGER.debug(f"find_key_in_data: Recursing into dict item '{k}'")
            item = find_key_in_data(v, key)
            if item is not None:
                return item
    elif isinstance(data, list):
        _LOGGER.debug(f"find_key_in_data: Recursing into list with {len(data)} items.")
        for i, item_in_list in enumerate(data):
            _LOGGER.debug(f"find_key_in_data: Recursing into list item {i}")
            item = find_key_in_data(item_in_list, key)
            if item is not None:
                return item
    _LOGGER.debug(f"find_key_in_data: '{key}' not found in current data structure.")
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
) -> Any:
    """
    Creates the standardized SSL context for Samsung devices.
    Enforces PROTOCOL_TLS_CLIENT, sets verify mode, loads ciphers,
    and caps the maximum TLS version to TLSv1_2 to prevent the AC handshake bug.
    """
    import ssl
    import asyncio
    
    protocol = getattr(ssl, 'PROTOCOL_TLS_CLIENT', getattr(ssl, 'PROTOCOL_TLS', ssl.PROTOCOL_TLSv1))
    context = ssl.SSLContext(protocol)
    
    context.set_ciphers(ciphers)
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
        verify_mode=verify_mode
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

async def async_check_network_reachability(host: str, log_prefix: str = "") -> bool:
    """Check if the device is reachable on the network.
    Uses system ping to verify if the host is alive.
    Results are logged at DEBUG level to help diagnose disconnections.
    """
    import asyncio
    import os

    process = None
    try:
        # -c 1 = 1 packet, -W 2 = 2 seconds timeout
        # Use 'ping' for Linux/macOS and fallback behavior for Windows if needed
        ping_cmd = ["ping", "-c", "1", "-W", "2", host]
        
        # Windows ping commands are slightly different: -n 1 for count, -w 2000 for timeout
        if os.name == 'nt':
            ping_cmd = ["ping", "-n", "1", "-w", "2000", host]

        process = await asyncio.create_subprocess_exec(
            *ping_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        
        # Wait for ping to finish with a safety timeout
        await asyncio.wait_for(process.wait(), timeout=3.0)
        
        if process.returncode == 0:
            _LOGGER.debug(
                "%s Network diagnostic: Host %s responded to ICMP ping. "
                "Network is OK.",
                log_prefix, host
            )
            return True
        else:
            _LOGGER.debug(
                "%s Network diagnostic: Host %s is NOT reachable (ICMP ping failed). "
                "Check that the device is powered on and connected to your Wi-Fi.",
                log_prefix, host
            )
            return False
    except asyncio.TimeoutError:
        if process:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        _LOGGER.debug(
            "%s Network diagnostic: Host %s is NOT reachable (Ping timed out). "
            "Check that the device is powered on and connected to your Wi-Fi.",
            log_prefix, host
        )
        return False
    except Exception as e:
        _LOGGER.debug("%s Network diagnostic (ping) error: %s", log_prefix, e)
        return True # Fallback to trying connection if ping fails for unknown reasons