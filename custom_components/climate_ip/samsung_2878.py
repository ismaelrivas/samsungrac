import asyncio
import logging
import os
import random
import re
import ssl
from typing import Callable, Dict, Any, Optional, Set, Tuple, Coroutine

import xmltodict
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN

from .connection import Connection, register_connection
from .exceptions import AuthError, CannotConnect
from .properties import DeviceProperty, register_status_getter
from homeassistant.helpers.issue_registry import async_create_issue, async_delete_issue, IssueSeverity
from .const import (
    CONF_CERT,
    CONFIG_DEVICE_POWER_TEMPLATE,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
)
from .helpers import mask_sensitive_data, async_check_network_reachability
from .const import (
    DOMAIN,
    DEFAULT_CONF_CERT_FILE,
    PROTOCOL_2878_DPLUG,
    PROTOCOL_2878_DRC,
    PROTOCOL_2878_INVALIDATE,
    PROTOCOL_2878_DEVICE_STATE,
    PROTOCOL_2878_DEVICE_CONTROL,
    PROTOCOL_2878_STATUS_OK,
    PROTOCOL_2878_STATUS,
    PROTOCOL_2878_UPDATE,
    PROTOCOL_2878_RESPONSE,
    PROTOCOL_2878_ATTR,
    PROTOCOL_2878_ATTR_ID,
    PROTOCOL_2878_ATTR_VALUE,
    PROTOCOL_2878_POWER_ID,
    PROTOCOL_2878_VALUE_ON,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_S2878 = "samsung_2878"
CONF_DUID = "duid"

INITIAL_RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 300
RECONNECT_FACTOR = 2
COMMAND_TIMEOUT = 20.0
MAX_RECONNECT_RETRIES = 5

class connection_config:
    def __init__(self, host, port, token, cert, duid):
        self.host = host
        self.port = port
        self.token = token
        self.duid = duid
        self.cert = cert

@register_connection
class ConnectionSamsung2878(Connection):
    def __init__(self, hass_config, logger):
        super(ConnectionSamsung2878, self).__init__(hass_config, logger)
        self._params = {}
        self._connection_init_template = None
        self._cfg = connection_config(None, None, None, None, None)
        self._device_status = {}
        self._socket_timeout = 30.0
        self._controller = None

        self._reader = None
        self._writer = None
        self._read_task: Optional[asyncio.Task] = None # Task for reading from the socket
        self._lock = asyncio.Lock()  # To serialize execute() calls
        self._close_lock = asyncio.Lock() # To serialize _close_connection calls
        self._cmd_queue = asyncio.Queue()
        self._manager_task: Optional[asyncio.Task] = None # The main task that manages the persistent connection.
        self._update_callback: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None
        self._pending_future: Optional[asyncio.Future] = None # The future for the command currently being processed.
        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._reconnect_retries = 0
        self._is_available = True # Used for stateful logging to report connection status changes.
        self._is_ready = asyncio.Event()  # Event to signal when connection is ready
        self._last_successful_config: Optional[Dict[str, Any]] = None
        self._ssl_context_cache: Dict[Tuple[Optional[str], str, int], ssl.SSLContext] = {}
        self._initial_connection_done = False # To prevent double poll at startup
        self._background_tasks: Set[asyncio.Task] = set()  # Track fire-and-forget tasks for clean shutdown
        
        self.update_configuration_from_hass(hass_config)
        self._power_template = None

    def set_controller_ref(self, controller):
        self._controller = controller

    @property
    def log_prefix(self) -> str:
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        if self._cfg and self._cfg.duid:
            return f"[{self._cfg.duid[-6:]}]"
        return "[NO_ID]"

    @property
    def is_async_native(self) -> bool:
        """Indicates if the connection is native asynchronous (aiohttp/2878)."""
        return True

    def set_update_callback(self, callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        self._update_callback = callback

    def start_listening(self) -> None:
        if self._manager_task is None or self._manager_task.done():
            _LOGGER.info("%s Starting connection manager", self.log_prefix)
            self._reconnect_retries = 0
            self._manager_task = asyncio.create_task(self._connection_manager())

    def _track_task(self, coro) -> asyncio.Task:
        """Create a tracked background task that auto-removes itself on completion."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def stop_listening(self) -> None:
        if self._manager_task:
            _LOGGER.info("%s Stopping connection manager", self.log_prefix)
            self._manager_task.cancel()
            try:
                await self._manager_task
            except asyncio.CancelledError:
                pass
            self._manager_task = None
        # Cancel all tracked background tasks
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        self._background_tasks.clear()
        await self._close_connection()

    def update_configuration_from_hass(self, hass_config):
        if hass_config is not None:
            # Clear the SSL context cache if configuration changes, as cert path might have changed.
            self._ssl_context_cache.clear()

            duid = None
            mac = hass_config.get(CONF_MAC)
            if mac:
                duid = re.sub(":", "", mac)

            cert_file = hass_config.get(CONF_CERT) or ""
            # If the certificate path does not contain a directory, assume it's in the integration's folder.
            # This makes it robust to HA installation changes.
            if cert_file and not os.path.dirname(cert_file):
                log_prefix = self.log_prefix
                if log_prefix == "[NO_ID]" and duid:
                    log_prefix = f"[{duid[-6:]}]"
                _LOGGER.debug("%s Resolving relative certificate path for 2878 connection: %s", log_prefix, cert_file)
                cert_file = os.path.join(os.path.dirname(__file__), cert_file)

            self._cfg = connection_config(
                host=hass_config.get(CONF_IP_ADDRESS),
                port=hass_config.get(CONF_PORT, 2878),
                token=hass_config.get(CONF_TOKEN),
                cert=cert_file,
                duid=duid,
            )
            # Ensure DUID and token are available for templates.
            self._params.update({
                CONF_DUID: self._cfg.duid,
                CONF_TOKEN: self._cfg.token,
                CONF_IP_ADDRESS: self._cfg.host,
            })
            
            # Load the preferred connection settings if they were saved during pairing
        self._last_successful_config = None
        
        # --- 2.1b: Restore last successful SSL config from ConfigEntry data across restarts ---
        # The configuration entry merges its 'data' into self._config at initialization.
        stored = self._config.get('_ssl_config_2878')
        if stored:
            self._last_successful_config = stored
            _LOGGER.debug(
                "%s Restored last successful SSL config from ConfigEntry data in init: cert=%s, cipher=%s",
                self.log_prefix, stored.get('cert'), stored.get('cipher_name')
            )
        # -----------------------------------------------------------------------

        if not self._last_successful_config and hass_config.get("preferred_connection"):
            self._last_successful_config = hass_config.get("preferred_connection").copy()
            # Resolve relative path in preferred config if needed, to match the runtime behavior
            pref_cert = self._last_successful_config.get('cert')
            if pref_cert and not os.path.dirname(pref_cert):
                self._last_successful_config['cert'] = os.path.join(os.path.dirname(__file__), pref_cert)


    def load_from_yaml(self, node, connection_base):
        from jinja2 import Template
        if connection_base:
            self._params.update(connection_base._params.copy())
        if not node:
            return False
        
        params_node = node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {})
        if CONFIG_DEVICE_CONNECTION_TEMPLATE in params_node:
            self._connection_init_template = Template(params_node[CONFIG_DEVICE_CONNECTION_TEMPLATE])
        elif not connection_base:
            _LOGGER.error("%s Missing 'connection_template' in YAML configuration", self.log_prefix)
            return False

        if CONFIG_DEVICE_POWER_TEMPLATE in params_node:
            self._power_template = Template(params_node[CONFIG_DEVICE_POWER_TEMPLATE])

        if not connection_base:
            # These are critical and should have been provided during setup.
            if not self._cfg.host: _LOGGER.error("%s Missing 'host' parameter", self.log_prefix); return False
            if not self._cfg.token: _LOGGER.error("%s Missing 'token' parameter", self.log_prefix); return False
            if not self._cfg.duid: _LOGGER.error("%s Missing 'mac' parameter", self.log_prefix); return False

        self._params.update(params_node)
        return True

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_S2878

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return diagnostic information about the 2878 connection."""
        diag = {
            "is_connected": self._is_ready.is_set(),
            "reconnect_retries": self._reconnect_retries,
            "is_available": self._is_available,
        }

        if self._last_successful_config:
            safe_config = {}
            if "cert" in self._last_successful_config and self._last_successful_config["cert"]:
                # Expose only the filename, not the full path, for privacy/security
                safe_config["cert_filename"] = os.path.basename(self._last_successful_config["cert"])
            if "cipher_name" in self._last_successful_config:
                safe_config["cipher_name"] = self._last_successful_config["cipher_name"]
            diag["last_successful_config"] = safe_config
        else:
            diag["last_successful_config"] = None

        return diag

    def create_updated(self, node):
        self.load_from_yaml(node, self)
        return self

    async def _post_connect_status_request(self):
        """Queues a request for the full device status after a connection is established."""
        # Give the system a moment to be ready for a new command.
        try:
            await asyncio.sleep(1)
            
            command = f'<Request Type="{PROTOCOL_2878_DEVICE_STATE}" DUID="{self._cfg.duid}"></Request>\n'
            _LOGGER.debug("%s Queuing post-reconnection status request", self.log_prefix)
            
            future = asyncio.get_event_loop().create_future()
            await self._cmd_queue.put((command, future))
            
            # Wait for the command to be processed
            await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT) # This raises TimeoutError if it takes too long
            _LOGGER.debug("%s Post-reconnection status request was processed successfully", self.log_prefix)
 
        except asyncio.TimeoutError:
            _LOGGER.warning("%s Post-reconnection status request timed out", self.log_prefix)
            # If the future that timed out is still the pending one, clear it to unblock the manager.
            if self._pending_future and self._pending_future == future:
                self._pending_future = None
        except Exception as e:
            _LOGGER.error("%s Failed to queue post-reconnection status request: %s", self.log_prefix, e, exc_info=True)

    async def _close_connection(self):
        # Use a lock to ensure we don't close the connection multiple times concurrently
        if self._close_lock.locked():
            _LOGGER.debug("%s Connection close already in progress, waiting...", self.log_prefix)

        async with self._close_lock:
            # Check if already closed to avoid redundant work and logs
            if self._writer is None and self._read_task is None:

                return

            self._is_ready.clear()
            
            # --- START OF FIX: Cancel pending read task to unblock manager ---
            if self._read_task and not self._read_task.done():
                _LOGGER.debug("%s Cancelling pending read task", self.log_prefix)
                self._read_task.cancel()
                try:
                    await self._read_task
                except asyncio.CancelledError:
                    pass
            self._read_task = None
            # --- END OF FIX ---

            if self._writer:
                _LOGGER.debug("%s Closing connection", self.log_prefix)
                try:
                    self._writer.close()
                    # --- START OF FIX: Add timeout to wait_closed ---
                    try:
                        await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
                    except asyncio.TimeoutError:
                        _LOGGER.warning("%s Timeout waiting for connection close, forcing reset", self.log_prefix)
                    # --- END OF FIX ---
                except (ConnectionResetError, ssl.SSLError, asyncio.CancelledError, OSError) as e:
                    _LOGGER.debug("%s Ignoring error during connection close: %s", self.log_prefix, e)
            self._writer = self._reader = None

    async def _establish_connection_and_handshake(self):
        await self._close_connection()
        cfg = self._cfg
        initial_msg = None

        # Define the cipher suites.
        # Note: We will reorder these dynamically based on the strategy.
        suite_A = ("HIGH:!DH:!aNULL:@SECLEVEL=0", "Cipher Suite A (High Security No-DH)")
        suite_B = ("ALL:!DH:!aNULL:@SECLEVEL=0", "Cipher Suite B (Legacy RSA - No DH)")
        suite_C = ("ALL:!aNULL:@SECLEVEL=0", "Cipher Suite C (Legacy Allow Weak DH)")
        suite_D = ("ALL:@SECLEVEL=0", "Cipher Suite D (Anonymous / All Supported)")
        
        default_ciphers = [suite_A, suite_B, suite_C, suite_D]
        # For No-Cert strategies, we prioritize Suite D (allows Anonymous) because !aNULL (A/B/C) forces server auth.
        no_cert_ciphers = [suite_D, suite_A, suite_B, suite_C]

        # Define connection strategies based on user input.
        user_cert = cfg.cert
        default_cert_path = os.path.join(os.path.dirname(__file__), DEFAULT_CONF_CERT_FILE)
        
        strategies = []
        if user_cert:
            # If a user certificate is provided, try strict verification first, then no verification.
            strategies.append({'cert': user_cert, 'name': 'User Cert (Strict Verify)', 'verify_mode': ssl.CERT_REQUIRED})
            strategies.append({'cert': user_cert, 'name': 'User Cert (No Verify)', 'verify_mode': ssl.CERT_NONE})
            # As a fallback, try with no certificate at all.
            strategies.append({'cert': None, 'name': 'No Certificate (Fallback)'})
        else:
            # If no user certificate, the only possible verification mode is CERT_NONE.
            strategies.append({'cert': None, 'name': 'No Certificate (Default)'})
            # As a fallback, try with the integration's default certificate.
            strategies.append({'cert': default_cert_path, 'name': 'Default Certificate (Fallback)'})

        # Build a list of all possible connection attempts.
        all_attempts = [] # List of connection attempts
        for strategy in strategies:
            # Determine which cipher list to use
            if strategy['cert'] is None:
                ciphers_to_try = no_cert_ciphers
            else:
                ciphers_to_try = default_ciphers

            for cipher_config in ciphers_to_try:
                all_attempts.append({
                    'cert': strategy['cert'],
                    # Default to CERT_NONE if verify_mode is not specified.
                    'verify_mode': strategy.get('verify_mode', ssl.CERT_NONE),
                    'cipher_config': cipher_config,
                    'strategy_name': strategy['name']
                })

        # If we have a last known good configuration, prioritize it
        if self._last_successful_config:

            
            preferred_cert = self._last_successful_config.get('cert')
            preferred_cipher = self._last_successful_config.get('cipher_name')
            preferred_verify = self._last_successful_config.get('verify_mode')

            # Find all attempts that match the criteria
            matching_attempts = []
            other_attempts = []

            for attempt in all_attempts:
                cert_match = attempt['cert'] == preferred_cert
                verify_match = attempt['verify_mode'] == preferred_verify
                
                # If cipher name is saved, we require it to match.
                # If it's NOT saved (legacy config), we ignore it and match only on cert/verify.
                cipher_match = True
                if preferred_cipher:
                    cipher_match = attempt['cipher_config'][1] == preferred_cipher
                
                if cert_match and verify_match and cipher_match:
                    matching_attempts.append(attempt)
                else:
                    other_attempts.append(attempt)
            
            # Reconstruct the list with matching attempts first
            if matching_attempts:

                all_attempts = matching_attempts
                # We discard 'other_attempts' to avoid trying invalid configs (like No Cert)

        connection_successful = False
        last_error = None
        logged_ssl_config = False

        for attempt in all_attempts:
            cert_path = attempt['cert']
            ciphers, cipher_name = attempt['cipher_config']
            verify_mode = attempt['verify_mode']
            strategy_name = attempt['strategy_name']

            try:

                
                # --- SSL Context Caching Logic ---
                cache_key = (cert_path, ciphers, verify_mode) # The key must include all SSL parameters
                ssl_context = self._ssl_context_cache.get(cache_key)

                if not ssl_context:
                    from .helpers import async_create_samsung_ssl_context
                    ssl_context = await async_create_samsung_ssl_context(
                        cert_path=cert_path, 
                        ciphers=ciphers, 
                        verify_mode=verify_mode
                    )

                    self._ssl_context_cache[cache_key] = ssl_context

                # --- START OF FIX: Use raw socket with TCP KEEPALIVE ---
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setblocking(False)
                
                # Enable TCP Keep-Alive
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                
                # Set Keep-Alive parameters (platforms may vary, these are for Linux/Windows common)
                if hasattr(socket, 'TCP_KEEPIDLE'):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60) # Send probe after 60s idle
                if hasattr(socket, 'TCP_KEEPINTVL'):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10) # 10s between probes
                if hasattr(socket, 'TCP_KEEPCNT'):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3) # 3 failures = dead
                
                # Check for Windows specific constant (SIO_KEEPALIVE_VALS) if needed, 
                # but standard setsockopt often works or is sufficient.
                
                try:
                    await asyncio.wait_for(
                        asyncio.get_running_loop().sock_connect(sock, (cfg.host, cfg.port)), 
                        timeout=self._socket_timeout
                    )
                except Exception as connect_exc:
                    sock.close()
                    raise connect_exc

                # Wrap the socket with SSL
                conn_future = asyncio.open_connection(sock=sock, ssl=ssl_context, server_hostname=cfg.host)
                self._reader, self._writer = await asyncio.wait_for(conn_future, timeout=self._socket_timeout)
                # --- END OF FIX ---

                # Log connection details on success
                ssl_object = self._writer.get_extra_info('ssl_object')
                if ssl_object:
                    cipher = ssl_object.cipher()
                    negotiated_tls = ssl_object.version() or "Unknown"
                    _LOGGER.info(
                        "%s SSL connection established. Protocol: %s, Cipher: %s, Verify: %s, Negotiated TLS: %s",
                        self.log_prefix, cipher[1], cipher[0], verify_mode, negotiated_tls
                    )

                # Memorize the successful configuration for future reconnections
                self._last_successful_config = {'cert': cert_path, 'cipher_name': cipher_name, 'verify_mode': verify_mode}
                
                # --- 2.1b: Persist to ConfigEntry data so it survives HA restarts ---
                if hasattr(self._controller, 'coordinator') and self._controller.coordinator:
                    entry = getattr(self._controller.coordinator, 'entry', None)
                    hass = getattr(self._controller, 'hass', None)
                    if entry and hass:
                        current_data = dict(entry.data)
                        if current_data.get('_ssl_config_2878') != self._last_successful_config:
                            current_data['_ssl_config_2878'] = self._last_successful_config
                            hass.config_entries.async_update_entry(entry, data=current_data)
                            _LOGGER.debug("%s Persisted SSL config to ConfigEntry data", self.log_prefix)
                # -------------------------------------------------------------------
                # ------------------------------------------------------------
                connection_successful = True
                break  # Exit the loop on successful connection.

            except (ConnectionRefusedError, asyncio.TimeoutError, OSError, ssl.SSLError) as e:
                # This is an expected failure when the device is offline or the port is wrong.
                # Log at debug level to avoid spamming logs when the device is intentionally off.

                last_error = e
                await self._close_connection()
                continue
            except Exception as e:
                _LOGGER.warning("%s Connection with '%s' / '%s' failed unexpectedly: %s. Trying next.", self.log_prefix, strategy_name, cipher_name, e)
                last_error = e
                await self._close_connection()
                continue

        if not connection_successful:
            _LOGGER.debug("%s Could not connect to device (likely offline): %s", self.log_prefix, last_error)
            return False
        
        # If we are here, one of the attempts was successful at the socket level
        # Now, proceed with the application-level handshake
        if not initial_msg: # Read initial message if not already read during plain TCP check
            initial_msg = await self._read_full_response(timeout=self._socket_timeout)

        if initial_msg:
            # Attempt to parse the initial message to see if it's an update or response
            is_response, is_update, parsed_data = self._parse_and_update_state(initial_msg)
            if parsed_data:
                self._device_status.update(parsed_data)
                if is_update and self._update_callback:
                    _LOGGER.debug("%s Initial message was an update, calling update callback", self.log_prefix)
                    self._track_task(self._update_callback(parsed_data))

        if not initial_msg or (PROTOCOL_2878_DPLUG not in initial_msg and PROTOCOL_2878_DRC not in initial_msg and PROTOCOL_2878_INVALIDATE not in initial_msg):
            _LOGGER.warning("%s Handshake failed: Did not receive expected initial message (DPLUG-1.6 or DRC-1.00 or InvalidateAccount). Got: %s", self.log_prefix, initial_msg)
            raise CannotConnect("Handshake failed: Did not receive expected initial message")
        
        if not self._connection_init_template:
            _LOGGER.error("%s Handshake failed: Connection initialization template is missing.", self.log_prefix)
            raise CannotConnect("Handshake failed: Connection initialization template is missing.")

        auth_command = self._connection_init_template.render(**self._params) + "\n"
        await self._write_data(auth_command)

        auth_response = await self._read_full_response(timeout=self._socket_timeout)
        if not auth_response or PROTOCOL_2878_STATUS_OK not in auth_response:
            # Only process the error response if it's not None
            if auth_response:
                # Handle InvalidateAccount (Session Collision) gracefully
                if PROTOCOL_2878_INVALIDATE in auth_response:
                    _LOGGER.info("%s Device reported session collision (InvalidateAccount). Waiting for old session to timeout...", self.log_prefix)
                    return False # Trigger retry logic

                if 'ErrorCode="301"' in auth_response:
                    _LOGGER.error("%s Authentication failed (ErrorCode 301). The device was likely turned off. Please ensure the device is ON before pairing", self.log_prefix)
                    raise AuthError("Authentication failed: Device was turned off (301)")
                
                error_code_match = re.search(r'ErrorCode="(\d+)"', auth_response)
                error_code = error_code_match.group(1) if error_code_match else "Unknown"
                _LOGGER.error("%s Authentication failed with ErrorCode %s. Got: %s", self.log_prefix, error_code, auth_response)
                raise AuthError("Authentication failed")
            raise AuthError("Authentication failed: No response from device")

        _LOGGER.info("%s Connection ready", self.log_prefix)
        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._reconnect_retries = 0
        self._is_ready.set()  # Signal that we are ready for commands
        _LOGGER.debug("%s Connection is ready, _is_ready event set.", self.log_prefix)
        
        # Stateful logging: Log when connection is re-established
        if not self._is_available:
            _LOGGER.info("%s Connection re-established", self.log_prefix)
            self._is_available = True
            try:
                # Clear any pending repair issues since the device came back online
                if self._controller and getattr(self._controller, 'hass', None):
                    async_delete_issue(
                        self._controller.hass,
                        "climate_ip",
                        f"connection_failed_{self._cfg.host}"
                    )
            except Exception as e:
                _LOGGER.debug("%s Could not clear repair issue: %s", self.log_prefix, e)

        # Request a full status update only on reconnections, not on the very first connection.
        if self._initial_connection_done:
            self._track_task(self._post_connect_status_request())
            # --- START OF FIX: Proactively refresh HA state after reconnection ---
            if self._controller and hasattr(self._controller, 'coordinator'):
                _LOGGER.info("%s Requesting immediate coordinator refresh after reconnection.", self.log_prefix)
                self._track_task(self._controller.coordinator.async_request_refresh())
            # --- END OF FIX ---
        
        self._initial_connection_done = True
        
        return True

    async def _read_full_response(self, timeout=10.0) -> Optional[str]:
        if not self._reader or self._reader.at_eof():
            return None
        try:
            buffer = b""
            end_time = asyncio.get_event_loop().time() + timeout
            while True:
                remaining_time = end_time - asyncio.get_event_loop().time()
                if remaining_time <= 0:
                    raise asyncio.TimeoutError

                chunk = await asyncio.wait_for(self._reader.read(4096), timeout=remaining_time)
                if not chunk: 
                    await self._close_connection()
                    return buffer.decode("utf-8", errors='ignore') if buffer else None

                buffer += chunk
                decoded_buffer = buffer.decode("utf-8", errors='ignore').strip()
                if "</Response>" in decoded_buffer or "</Update>" in decoded_buffer or PROTOCOL_2878_DPLUG in decoded_buffer or decoded_buffer.endswith("/>"):
                    return decoded_buffer

        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            _LOGGER.debug("%s No full response received in %s seconds", self.log_prefix, timeout, exc_info=True)
            return buffer.decode("utf-8", errors='ignore') if buffer else None
        except Exception as e:
            _LOGGER.error("%s Error during read: %s", self.log_prefix, e, exc_info=True)
            await self._close_connection()
            return None

    async def _write_data(self, data_str: str):
        if not self._writer or self._writer.is_closing():
            _LOGGER.error("%s Write failed: writer is not available", self.log_prefix)
            raise CannotConnect("Connection is not available for writing")
        try:
            self._writer.write(data_str.encode("utf-8"))
            await asyncio.wait_for(self._writer.drain(), timeout=5.0)
            return True
        except (asyncio.TimeoutError, OSError) as e:
            _LOGGER.error("%s Write failed: %s. Closing connection.", self.log_prefix, e)
            await self._close_connection()
            raise CannotConnect(f"Failed to write to connection: {e}") from e

    def _parse_and_update_state(self, response_xml: str) -> Tuple[bool, bool, Optional[Dict[str, Any]]]:
        if not response_xml:
            return False, False, None
        
        is_update = False
        is_response = False
        parsed_data = {}
        
        # Discard any non-XML prefix like "DPLUG-1.6\n" or "DRC-1.00\n"
        xml_start_index = response_xml.find("<?xml")
        if xml_start_index == -1:
            return False, False, None

        xml_candidate_content = response_xml[xml_start_index:]

        # Split by '<?xml' to handle multiple XML documents concatenated in the buffer.
        doc_parts = xml_candidate_content.split('<?xml')

        for doc_part in doc_parts:
            if not doc_part.strip():
                continue # Skip empty parts.

            # Reconstruct the full XML document string.
            # A valid XML fragment after '<?xml' should start with 'version="1.0"' or a root element tag.
            if doc_part.strip().startswith('version="1.0"') or doc_part.strip().startswith('<'):
                full_doc = '<?xml' + doc_part
            else:
                # This doc_part is not a valid XML fragment (e.g., "DPLUG-1.6" without "version="1.0"")
                # Log it and skip, do not attempt to parse as XML.
                _LOGGER.debug("%s Skipping non-XML fragment after '<?xml': %s", self.log_prefix, doc_part.strip())
                continue
            try:
                data = xmltodict.parse(full_doc)

                if PROTOCOL_2878_RESPONSE in data:
                    is_response = True
                    device_data = data[PROTOCOL_2878_RESPONSE].get(PROTOCOL_2878_DEVICE_STATE, {}).get('Device')
                elif PROTOCOL_2878_UPDATE in data:
                    is_update = True
                    device_data = data[PROTOCOL_2878_UPDATE].get(PROTOCOL_2878_STATUS)
                else:
                    continue

                if not device_data:
                    continue
                attrs = device_data.get(PROTOCOL_2878_ATTR, [])
                if not isinstance(attrs, list):
                    attrs = [attrs]
                
                # Ignore redundant 'Power On' push updates if the device was already known to be on.
                # This reduces unnecessary state updates in Home Assistant.
                if is_update and len(attrs) == 1 and attrs[0].get(PROTOCOL_2878_ATTR_ID) == PROTOCOL_2878_POWER_ID and attrs[0].get(PROTOCOL_2878_ATTR_VALUE) == PROTOCOL_2878_VALUE_ON:
                    if self._device_status.get(PROTOCOL_2878_POWER_ID) == PROTOCOL_2878_VALUE_ON:
                        _LOGGER.debug("%s Ignoring redundant 'Power On' push update", self.log_prefix)
                        return False, False, None

                for attr in attrs:
                    if PROTOCOL_2878_ATTR_ID in attr and PROTOCOL_2878_ATTR_VALUE in attr:
                        parsed_data[attr[PROTOCOL_2878_ATTR_ID]] = attr[PROTOCOL_2878_ATTR_VALUE]

            except Exception as e:
                _LOGGER.warning("%s Error parsing XML part: %s. Document: %s", self.log_prefix, e, full_doc)
        return is_response, is_update, parsed_data

    async def _process_command_queue(self, queue_task: asyncio.Task) -> None:
        """Process a command from the queue."""
        command, future = queue_task.result()
        self._pending_future = future
        # Store the command string on the future for debugging purposes using setattr.
        setattr(self._pending_future, '_command_debug', command)

        try:
            await self._write_data(command)
            # The future will be resolved when a corresponding response or update is received.
            _LOGGER.debug("%s Command written, now waiting for response to resolve future", self.log_prefix)
        except CannotConnect as e:
            if self._pending_future and not self._pending_future.done():
                self._pending_future.set_exception(e)
            self._pending_future = None

    async def _process_read_queue(self, buffer: bytes, done: set[asyncio.Task]) -> Optional[bytes]:
        """Process data received from the read task."""
        data = None
        is_cancelled = False
        try:
            data = self._read_task.result()
        except asyncio.CancelledError:
            # Task was cancelled (likely by _close_connection), treat as connection closed
            data = None
            is_cancelled = True
        except Exception as e:
            _LOGGER.warning("%s Read task failed: %s", self.log_prefix, e)
            data = None
             
        if not data: 
            if not is_cancelled:
                _LOGGER.debug("%s Connection closed by device (EOF)", self.log_prefix)
            else:
                _LOGGER.debug("%s Read task was cancelled", self.log_prefix)
                
            await self._close_connection()
            return None
        
        buffer += data
        # Process buffer to find full XML messages.
        while b"</Response>" in buffer or b"</Update>" in buffer or b"/>" in buffer:
            end_tag = b"</Response>" if b"</Response>" in buffer else (b"</Update>" if b"</Update>" in buffer else b"/>")
            end_index = buffer.find(end_tag) + len(end_tag)
            message = buffer[:end_index]
            buffer = buffer[end_index:]
            
            xml_data = message.decode("utf-8", errors='ignore')
            _LOGGER.debug("%s Received message: %s", self.log_prefix, xml_data.strip())
            is_response, is_update, parsed_data = self._parse_and_update_state(xml_data)

            # Update internal state for redundant 'Power On' logic.
            if parsed_data:
                self._device_status.update(parsed_data)
            
            # --- Command Resolution Logic ---
            # A command is considered complete if we receive:
            # 1. A direct 'DeviceControl Okay' response.
            # 2. Any other response or update that contains actual state data.

            is_control_okay = is_response and not parsed_data and PROTOCOL_2878_DEVICE_CONTROL in xml_data and PROTOCOL_2878_STATUS_OK in xml_data
            is_polling_response = is_response and PROTOCOL_2878_DEVICE_STATE in xml_data

            # Initialize should_resolve to False to prevent UnboundLocalError
            should_resolve = False

            # If a pending command exists, check if this message resolves it.
            if self._pending_future and not self._pending_future.done():
                # If the pending command was a poll, only a DeviceState response can resolve it.
                # If it was a control command, any data update or a specific 'Okay' can resolve it.
                command_debug = getattr(self._pending_future, '_command_debug', '')
                is_poll_command = PROTOCOL_2878_DEVICE_STATE in command_debug
                
                should_resolve = (is_poll_command and is_polling_response) or \
                                 (not is_poll_command and (is_control_okay or parsed_data))

            if should_resolve and self._pending_future:
                if is_control_okay:
                    _LOGGER.debug("%s 'DeviceControl Okay' received, resolving pending command future", self.log_prefix)
                else:
                    _LOGGER.debug("%s Response/Update with data received, resolving pending command future", self.log_prefix)
                try:
                    if not self._pending_future.done():
                        self._pending_future.set_result(True)
                    self._pending_future = None
                except asyncio.InvalidStateError:
                    pass  # Future was already resolved.
            if parsed_data and (is_response or is_update) and self._update_callback:
                _LOGGER.debug("%s Calling update callback with data: %s", self.log_prefix, parsed_data)
                self._track_task(self._update_callback(parsed_data))
            elif is_control_okay:
                # This is just an acknowledgment. The device will send a separate <Update> push.
                # We don't need to do anything here except acknowledge
                # that the command was successful so the UI doesn't hang. The future is already resolved.
                _LOGGER.debug("%s 'DeviceControl Okay' ack received. Waiting for subsequent push update.", self.log_prefix)
        
        return buffer




    async def handle_reconnection(self) -> bool:
        """Handle the reconnection process."""
        # Stateful logging: Log INFO only when the state changes from available to unavailable.
        if self._is_available:
            _LOGGER.info("%s Connection lost. Attempting to reconnect...", self.log_prefix)
            self._is_available = False
        else:
            _LOGGER.debug("%s Connection is down. Attempting to reconnect...", self.log_prefix)

        # Run network diagnostics on every reconnect attempt to aid troubleshooting.
        # Only attempt to open the TCP port if the ping succeeds to protect fragile ACs.
        network_reachable = True
        try:
            network_reachable = await async_check_network_reachability(self._cfg.host, self.log_prefix)
        except Exception as diag_err:
            _LOGGER.debug("%s Network diagnostic failed: %s", self.log_prefix, diag_err)

        try:
            # If the network is reachable, attempt handshake. Otherwise, skip to retry to protect device.
            handshake_success = False
            if network_reachable:
                handshake_success = await self._establish_connection_and_handshake()
            else:
                _LOGGER.debug("%s Skipping port connection attempt because ICMP ping failed.", self.log_prefix)

            # --- DUAL-SPEED BACKOFF LOGIC ---
            if not network_reachable:
                # 1. Network is fully down (router off, device unplugged, no wifi)
                # Wait a fixed 10 seconds. Do NOT increment exponential backoff to recover quickly.
                _LOGGER.debug("%s Host unreachable. Retrying ping in 10 seconds...", self.log_prefix)
                self._reconnect_retries += 1
                
                # Create a repair issue if the device is persistently offline
                if self._reconnect_retries == 3 and self._controller and getattr(self._controller, 'hass', None):
                    try:
                        async_create_issue(
                            self._controller.hass,
                            "climate_ip",
                            f"connection_failed_{self._cfg.host}",
                            is_fixable=False,
                            severity=IssueSeverity.WARNING,
                            translation_key="connection_failed",
                            translation_placeholders={
                                "host": self._cfg.host,
                                "name": getattr(self._cfg, 'name', None) or self._cfg.host
                            }
                        )
                    except Exception as e:
                        _LOGGER.debug("%s Failed to create repair issue: %s", self.log_prefix, e)

                # If we've failed 2 times on the ping, force unavailability in HA
                if self._reconnect_retries == 2:
                    _LOGGER.error("%s AC Network is persistently offline. Forcing frontend unavailability.", self.log_prefix)
                    if self._controller and getattr(self._controller, 'coordinator', None):
                        self._controller.coordinator.last_update_success = False
                        self._controller.coordinator.async_update_listeners()

                self._ssl_context_cache.clear()
                await self._close_connection()
                
                # Use current exponential backoff but without jitter for network down
                delay_to_use = self._reconnect_delay
                _LOGGER.debug("%s Host unreachable. Retrying ping in %.1f seconds...", self.log_prefix, delay_to_use)
                await asyncio.sleep(delay_to_use)
                
                # Increment exponential backoff delay for the next attempt
                self._reconnect_delay = min(self._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY)
                return False

            # If the handshake fails with a connection error, it returns False.
            if not handshake_success:
                # 2. Network UP but Port 2878 closed/crashing.
                _LOGGER.debug("%s Handshake returned False (or skipped). Proceeding to backoff logic.", self.log_prefix)
                self._reconnect_retries += 1
                
                # Create a repair issue if the device is persistently offline
                if self._reconnect_retries == 3 and self._controller and getattr(self._controller, 'hass', None):
                    try:
                        async_create_issue(
                            self._controller.hass,
                            "climate_ip",
                            f"connection_failed_{self._cfg.host}",
                            is_fixable=False,
                            severity=IssueSeverity.WARNING,
                            translation_key="connection_failed",
                            translation_placeholders={
                                "host": self._cfg.host,
                                "name": getattr(self._cfg, 'name', None) or self._cfg.host
                            }
                        )
                    except Exception as e:
                        _LOGGER.debug("%s Failed to create repair issue: %s", self.log_prefix, e)

                # If we've failed 2 times on the port, force unavailability in HA
                if self._reconnect_retries == 2:
                    _LOGGER.error("%s AC Service is persistently offline. Forcing frontend unavailability.", self.log_prefix)
                    if self._controller and getattr(self._controller, 'coordinator', None):
                        self._controller.coordinator.last_update_success = False
                        self._controller.coordinator.async_update_listeners()

                jitter = random.uniform(0, self._reconnect_delay * 0.2)
                delay_with_jitter = self._reconnect_delay + jitter
                _LOGGER.warning("%s Port connection failed. Backing off for %.1f seconds (jitter: %.1f)...", self.log_prefix, delay_with_jitter, jitter)
                self._ssl_context_cache.clear() # Force fresh SSL context on retry
                await self._close_connection()
                await asyncio.sleep(delay_with_jitter)
                self._reconnect_delay = min(self._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY)
                return False
                
        except (CannotConnect, AuthError) as e:
            # 3. Network UP but an exception occurred during connection logic
            self._reconnect_retries += 1

            # Create a repair issue if the device is persistently offline
            if self._reconnect_retries == 3 and self._controller and getattr(self._controller, 'hass', None):
                try:
                    async_create_issue(
                        self._controller.hass,
                        "climate_ip",
                        f"connection_failed_{self._cfg.host}",
                        is_fixable=False,
                        severity=IssueSeverity.WARNING,
                        translation_key="connection_failed",
                        translation_placeholders={
                            "host": self._cfg.host,
                            "name": getattr(self._cfg, 'name', None) or self._cfg.host
                        }
                    )
                except Exception as ex:
                    _LOGGER.debug("%s Failed to create repair issue: %s", self.log_prefix, ex)

            # If reconnection fails, fail any pending command
            if self._pending_future and not self._pending_future.done():
                self._pending_future.set_exception(CannotConnect(f"Connection lost and reconnect failed: {e}"))
                self._pending_future = None
                
            jitter = random.uniform(0, self._reconnect_delay * 0.2)
            delay_with_jitter = self._reconnect_delay + jitter
            _LOGGER.warning("%s Port connection error. Backing off for %.1f seconds (jitter: %.1f)...", self.log_prefix, delay_with_jitter, jitter)
            self._ssl_context_cache.clear() # Force fresh SSL context on retry
            await self._close_connection()
            await asyncio.sleep(delay_with_jitter)
            self._reconnect_delay = min(self._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY)
            return False
        
        return True

    async def _connection_manager(self):
        buffer = b""
        self._read_task = None
        queue_task = None

        # Add a small delay at startup to allow the initial poll to establish the first connection
        await asyncio.sleep(2)

        try:
            while True:
                try:
                    if not self._writer or self._writer.is_closing():
                        if not await self.handle_reconnection():
                            continue

                    if not self._reader:
                        _LOGGER.warning("%s Reader object is missing, forcing reconnection.", self.log_prefix)
                        await self._close_connection()
                        await self.handle_reconnection()
                    else: # Ensure read task is running
                        if not self._read_task or self._read_task.done():
                            self._read_task = asyncio.create_task(self._reader.read(8192))
                        
                        tasks = [self._read_task]

                    # Ensure queue listener is running if we are ready for commands
                    if not queue_task and not self._pending_future:
                        queue_task = asyncio.create_task(self._cmd_queue.get())
                    
                    if queue_task:
                        tasks.append(queue_task)
                    
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                    # --- Process completed tasks ---
                    if queue_task and queue_task in done:
                        await self._process_command_queue(queue_task)
                        queue_task = None # Reset to pick up next command

                    if self._read_task in done:
                        buffer = await self._process_read_queue(buffer, done)
                        if buffer is None: # Connection closed
                            buffer = b"" # Reset buffer to prevent NoneType error on next iteration
                            continue
                    
                    # Cleanup: Only cancel tasks that are NOT persistent
                    # We usually don't have other tasks here, but good practice.
                    # CRITICAL: Do NOT cancel queue_task if it's pending!
                    for task in pending:
                        if task == self._read_task: continue
                        if task == queue_task: continue
                        task.cancel()

                except Exception as e:
                    _LOGGER.error("%s Unhandled exception in connection manager: %s", self.log_prefix, e, exc_info=True)
                    if self._pending_future and not self._pending_future.done():
                        self._pending_future.set_exception(e)
                    self._pending_future = None
                    buffer = b"" # CRITICAL: Reset buffer on error to ensure clean state for next iteration
                    await self._close_connection()
                    await asyncio.sleep(self._reconnect_delay)
        finally:
            _LOGGER.debug("%s Connection manager exiting, cleaning up", self.log_prefix)
            if self._read_task and not self._read_task.done():
                self._read_task.cancel()
            if queue_task and not queue_task.done():
                queue_task.cancel()
            await self._close_connection()

    async def async_execute(self, method, url, data, headers, device_state=None, _is_probe=False, _is_poll=False) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
        """Executes an asynchronous command (raw XML for 2878)."""
        # Fast-fail if the connection is known to be offline and in retry backoff.
        if not self._is_ready.is_set() and self._reconnect_retries > 0:
            _LOGGER.debug("%s Connection is in retry backoff. Fast-failing command execution.", self.log_prefix)
            if self._reconnect_retries >= 2:
                raise CannotConnect("Connection is persistently offline")
            else:
                raise CannotConnect("Connection is temporarily offline")

        # Wait for the connection to be ready before proceeding.
        try:
            await asyncio.wait_for(self._is_ready.wait(), timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError as e:
            _LOGGER.warning("%s Timed out waiting for connection to be ready (device is likely offline).", self.log_prefix)
            raise CannotConnect("Connection not ready") from e

        command = None
        if data:
            command = data.strip() + "\n"
        elif _is_poll:
            command = f'<Request Type="{PROTOCOL_2878_DEVICE_STATE}" DUID="{self._cfg.duid}"></Request>\n'
        
        if not command:
             return None, None

        async with self._lock:
            _LOGGER.debug("%s Queuing async command: %s", self.log_prefix, mask_sensitive_data(command.strip().replace('\n', '')))
            future = asyncio.get_event_loop().create_future()
            await self._cmd_queue.put((command, future))

            try:
                await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
                _LOGGER.debug("%s Async command executed successfully", self.log_prefix)
                # The result set on the future is True (boolean).
                # We need to return the response body if available.
                # However, 2878 protocol is push-based. The response comes via _process_read_queue.
                # The future simply indicates "command processed/resolved".
                # But async_execute contract expects (response_body, headers).
                # For 2878, we don't really have a direct "response body" associated with the command future 
                # other than what was updated in state.
                # Properties.py expects JSON response body for GetJsonStatus.
                # If we return None, Properties.py might be unhappy if it expects state.
                # But we updated self._device_status!
                # Maybe we should return the current device state as JSON/XML?
                # Connection.async_execute docstring says: "return JSON object as result or None".
                # Actually returns Tuple[Optional[str], Optional[Dict[str, str]]].
                
                # If it was a poll (GetJsonStatus), we should return the full device state.
                import json
                return json.dumps(self._device_status), {}
            except asyncio.TimeoutError as e:
                _LOGGER.warning("%s Async command timed out", self.log_prefix)
                if self._pending_future and self._pending_future == future:
                    self._pending_future = None
                
                _LOGGER.debug("%s Command timed out. Forcing connection close to trigger reconnect.", self.log_prefix)
                asyncio.create_task(self._close_connection())
                raise CannotConnect("Command timed out") from e
            except Exception as e:
                _LOGGER.error("%s Error executing async command: %s", self.log_prefix, e)
                raise e

    def execute(self, template: Any, value: Any, device_state: Dict[str, Any], device_id: Optional[str] = None) -> Dict[str, Any]:
        """Synchronous wrapper to execute a command. To be called from an executor."""
        if not self._controller or not hasattr(self._controller, 'hass') or not self._controller.hass:
            _LOGGER.error("%s Cannot execute command synchronously: controller or HASS instance is not available.", self.log_prefix)
            raise RuntimeError("Controller or HASS instance not available for thread-safe execution.")
        
        # PREVENT DEADLOCK: Check if we are running in the event loop
        try:
            running_loop = asyncio.get_running_loop()
            if running_loop == self._controller.hass.loop:
                _LOGGER.error("%s BLOCKING CALL DETECTED: execute() called from the event loop! This will deadlock.", self.log_prefix)
                raise RuntimeError("Cannot call synchronous execute() from the event loop. Use await async_execute() instead.")
        except RuntimeError:
            pass # No running loop, safe to proceed

        return asyncio.run_coroutine_threadsafe(
            self._async_execute_internal(template, value, device_state, device_id),
            self._controller.hass.loop
        ).result()

    async def _async_execute_internal(self, template: Any, value: Any, device_state: Dict[str, Any], device_id: Optional[str] = None) -> Dict[str, Any]:
        """The actual async implementation of the execute logic."""
        # Wait for the connection to be ready before proceeding.
        try:
            await asyncio.wait_for(self._is_ready.wait(), timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError as e:
            _LOGGER.warning("%s Timed out waiting for connection to be ready (device is likely offline).", self.log_prefix)
            raise CannotConnect("Connection not ready") from e

        async with self._lock:
            is_polling_request = (not template) and (not value) and (not device_state)
            # Use the provided device_id if available, otherwise fall back to the main DUID
            duid_to_use = device_id or self._cfg.duid

            if is_polling_request:
                command = f'<Request Type="{PROTOCOL_2878_DEVICE_STATE}" DUID="{duid_to_use}"></Request>\n'
            else:
                params = self._params.copy()
                params.update({"value": value, "device_state": device_state, "duid": duid_to_use})
                command = template.render(**params).strip() + "\n"

            _LOGGER.debug("%s Queuing command: %s", self.log_prefix, mask_sensitive_data(command.strip().replace('\n', '')))
            future = asyncio.get_event_loop().create_future()
            await self._cmd_queue.put((command, future))

            try:
                await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
                _LOGGER.debug("%s Command executed successfully", self.log_prefix)
            except asyncio.TimeoutError as e:
                _LOGGER.warning("%s Command timed out: %s", self.log_prefix, mask_sensitive_data(command.strip().replace('\n', '')))
                
                # CRITICAL: If the command times out, we MUST clear the pending_future
                # so the manager can accept new commands and not get stuck.
                if self._pending_future and self._pending_future == future:
                    _LOGGER.debug("%s Command timed out. Clearing pending future to unblock manager.", self.log_prefix)
                    self._pending_future = None

                # CRITICAL FIX: Always force connection close on timeout.
                # If a command timed out (20s), the connection is effectively dead or hung.
                # We remove the 'is_polling_request' check to ensure we always recover.
                _LOGGER.debug("%s Command timed out. Forcing connection close to trigger reconnect.", self.log_prefix)
                asyncio.create_task(self._close_connection())
                
                raise CannotConnect("Command timed out") from e
            except Exception as e:
                _LOGGER.error("%s Command failed with exception: %s", self.log_prefix, e)
                raise

        return self._device_status
