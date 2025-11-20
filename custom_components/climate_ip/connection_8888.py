# custom_components/climate_ip/connection_8888.py
"""
Asynchronous connection engine for modern Samsung devices (port 8888) using aiohttp.
This engine implements HTTP Keep-Alive for low latency and correct mTLS.
"""
import asyncio
import copy
import json
import ssl
from urllib.parse import urlparse
import logging
import os
from jinja2 import Template
from typing import Any, Dict, Optional, Tuple
from functools import partial

import aiohttp
from homeassistant.const import CONF_TOKEN

from .connection import Connection, register_connection
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .yaml_const import CONF_CERT

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_AIOHTTP_8888 = "samsung_8888_aiohttp"

@register_connection
class ConnectionAiohttp8888(Connection):
    """
    An asynchronous connection handler for Samsung devices on port 8888.
    It uses aiohttp's ClientSession for persistent connections (Keep-Alive)
    and implements the correct mTLS (mutual-TLS) authentication.
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger, hass: Any, session: aiohttp.ClientSession, ip_address: str):
        logger.debug("[aiohttp_init] Initializing ConnectionAiohttp8888. IP: %s", ip_address)
        super().__init__(config, logger)
        self._hass = hass
        self._controller = None # Initialize controller reference
        self._session = session
        self._ip_address = ip_address
        self._token = config.get(CONF_TOKEN)
        self._cert_path = self._resolve_cert_path(config.get(CONF_CERT))

        # --- START OF FIX: Reintroduce shared state with a Lock ---
        # Object to share initialization state across all copies.
        # The Lock prevents race conditions during the first initialization.
        self._shared_state = {"initialized": False, "lock": asyncio.Lock(), "ssl_context": None}
        # --- END OF FIX ---
        # --- Simplified Connection Logic ---
        # This will hold the Jinja2 template for this specific connection instance.
        self._connection_template: Optional[Template] = None

        self.condition_template: Optional[Template] = None
        self._embedded_command: Optional[ConnectionAiohttp8888] = None
        self._ssl_context: Optional[ssl.SSLContext] = None

        if not self._token:
             _LOGGER.error("[aiohttp_init] aiohttp engine started without a token. This will fail.")
        if not self._cert_path or not os.path.exists(self._cert_path):
            _LOGGER.error(f"[aiohttp_init] Certificate file not found at {self._cert_path}")

    @property
    def log_prefix(self) -> str:
        """Generate a consistent log prefix."""
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        return f"[{self._ip_address or 'NO_IP'}]"

    def set_controller_ref(self, controller):
        """Allows the property to set a reference to the main controller."""
        _LOGGER.debug("%s [set_controller_ref] Setting controller reference for connection object.", self.log_prefix)
        self._controller = controller

    def _resolve_cert_path(self, cert_file: Optional[str]) -> Optional[str]:
        """Resolve the full path to the certificate file."""
        if not cert_file:
            return None
        if not os.path.dirname(cert_file):
            return os.path.join(os.path.dirname(__file__), cert_file)
        return cert_file

    async def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """
        Creates the correct SSL context for mTLS (Mutual TLS Authentication).
        This replicates the logic of 'requests' (cert=... and verify=...).
        """
        if not self._cert_path or not os.path.exists(self._cert_path):
            _LOGGER.error("%s [aiohttp] Cannot create SSL context: certificate path is invalid: %s", self.log_prefix, self._cert_path)
            return None
            
        try:
            _LOGGER.debug("%s [aiohttp] Creating SSL context for mTLS (does not verify server, presents client cert)", self.log_prefix)
            
            # --- SSL FIX ---
            # Use PROTOCOL_TLSv1 for maximum compatibility (as in requests)
            context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
            
            # 1. We DO NOT verify the server's certificate (it's self-signed)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            # 2. Fix [SSL: UNSUPPORTED_PROTOCOL] and [SSL: CA_MD_TOO_WEAK]
            # We replicate the 'requests' logic to allow ALL ciphers
            context.set_ciphers("ALL:@SECLEVEL=0")
            
            # 3. BUT we DO load our client certificate to present ourselves
            # --- START OF FIX: Use the _cert_path of the current object ---
            # Do not use self._cert_path directly in the partial function
            _LOGGER.debug("%s [aiohttp] ...loading 'load_cert_chain' with: %s", self.log_prefix, self._cert_path)
            # --- END OF FIX ---
            loop = asyncio.get_running_loop()
            
            load_chain_func = partial(context.load_cert_chain, self._cert_path)
            await loop.run_in_executor(None, load_chain_func)
            
            return context
        except Exception as e:
            _LOGGER.error("%s [aiohttp] Failed to load 'load_cert_chain': %s. The .pem file may be invalid or corrupt.", self.log_prefix, e)
            return None

    @staticmethod
    def match_type(type_str: str) -> bool:
        return type_str == CONNECTION_TYPE_AIOHTTP_8888

    def load_from_yaml(self, node, connection_base) -> bool:
        return True

    def create_updated(self, yaml_node):
        """
        Creates a new connection instance with updated parameters from YAML.
        This is crucial for async operations where each 'value' can have its own
        connection_template OR static params.
        
        HACK: This also converts static 'params' blocks into a
        'connection_template' because the async_set_value in properties.py
        fails to check _params.
        """
        from .yaml_const import (
            CONFIG_DEVICE_CONNECTION_TEMPLATE,
            CONFIG_DEVICE_CONNECTION_PARAMS,
            CONFIG_DEVICE_CONNECTION,
            CONFIG_DEVICE_CONDITION_TEMPLATE,
        )

        # Create a shallow copy. This is important so that each value-specific
        # operation gets its own connection object with its own template.
        new_connection = copy.copy(self)

        # A shallow copy makes new_connection._params point to the *same*
        # dictionary as self._params. We need to break that link.
        new_connection._params = {} # Create a new, empty dict for this instance.

        # --- START OF FIX: Ensure controller reference is inherited ---
        # The controller reference is set on the base connection object.
        # When we create a copy for a specific value, it must inherit this reference.
        new_connection._controller = self._controller
        # --- END OF FIX ---
        # --- START OF FIX: Revert to a single shared state ---
        # All copies must point to the SAME shared state object
        # so that the connection initialization only happens once.
        new_connection._shared_state = self._shared_state
        # --- END OF FIX ---

        # --- START OF FIX: Move import to the top of the function ---
        from jinja2 import Template
        # --- END OF FIX ---

        # If a connection_template is defined in the value-specific node,
        # compile it and store it in the new connection object.
        if yaml_node and CONFIG_DEVICE_CONNECTION_TEMPLATE in yaml_node:
            template_str = yaml_node[CONFIG_DEVICE_CONNECTION_TEMPLATE]
            #_LOGGER.debug("%s [create_updated] Found and creating value-specific template: %s", self.log_prefix, template_str)
            new_connection._connection_template = Template(template_str)
        
        # HACK: Convert static params to a connection_template string.
        elif yaml_node and CONFIG_DEVICE_CONNECTION_PARAMS in yaml_node:
            # This is a static command (like setting a mode)
            params = {**self._params, **yaml_node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {})} # Inherit from parent
            new_connection._params.update(params) # Store params for good practice
            
            # --- START OF FIX (v2) ---
            # The template must contain all necessary keys. If a key (like 'url')
            # is missing in the value-specific params, fall back to the base connection's params.
            template_dict = {}
            if 'json' in params:
                template_dict['json'] = params['json']
            
            # Use the value-specific method/url if present, otherwise use the base one.
            # --- START OF FIX ---
            # Ensure the URL is just the path, not the full URL, to prevent duplication.
            url_from_params = params.get('url', self._params.get('url'))
            if url_from_params:
                # Use urlparse for robust path extraction.
                template_dict['url'] = urlparse(url_from_params).path
            
            # --- START OF FIX ---
            # If the method is not in the current params (common for embedded commands),
            # explicitly fall back to the base connection's params (`self._params`).
            template_dict['method'] = params.get('method', self._params.get('method'))
            # --- END OF FIX ---

            if not template_dict.get('url'):
                _LOGGER.error("%s [create_updated] HACK FAILED: Could not determine 'url' from value-specific or base params.", self.log_prefix)
            
            template_str = json.dumps(template_dict)
            #_LOGGER.debug("%s [create_updated] HACK: Converting static params to template: %s", self.log_prefix, template_str)
            new_connection._connection_template = Template(template_str)
            # --- END OF FIX (v2) ---
        #else:
        #    _LOGGER.debug("%s [create_updated] No 'connection_template' or 'params' found in this YAML node.", self.log_prefix)

        # --- START: Replicate embedded command logic from connection_request.py ---
        # This MUST run AFTER the parent's params have been processed.
        if yaml_node and CONFIG_DEVICE_CONNECTION in yaml_node:
            #_LOGGER.debug("%s [create_updated] Found an embedded command. Creating it from parent with params: %s", self.log_prefix, new_connection._params)
            # The 'new_connection' object is now the fully configured parent.
            new_connection._embedded_command = new_connection.create_updated(yaml_node[CONFIG_DEVICE_CONNECTION])

            if CONFIG_DEVICE_CONDITION_TEMPLATE in yaml_node[CONFIG_DEVICE_CONNECTION]:
                condition_str = yaml_node[CONFIG_DEVICE_CONNECTION][CONFIG_DEVICE_CONDITION_TEMPLATE]
                #_LOGGER.debug("%s [create_updated] Found condition_template for embedded command: %s", self.log_prefix, condition_str)
                if new_connection._embedded_command:
                    new_connection._embedded_command.condition_template = Template(condition_str)
        # --- END: Replicate embedded command logic ---

        return new_connection

    @property
    def is_async_native(self) -> bool:
        return True
    
    async def _try_connection(self) -> None:
        """
        Probes the connection (HTTPS mTLS ONLY)
        and memorizes it for future use.
        """
        # --- START OF FIX: Use Lock for safe, one-time initialization ---
        if self._shared_state["initialized"]:
            return None

        async with self._shared_state["lock"]:
            # Double-check in case another task initialized it while we were waiting for the lock.
            if self._shared_state["initialized"]:
                return None

            current_token = self._token
            if self._controller:
                current_token = self._controller._config.get(CONF_TOKEN, self._token)
            probe_headers = {"Authorization": f"Bearer {current_token}"}

            # --- START OF FIX: Use the shared state's SSL context ---
            if not self._shared_state["ssl_context"]:
                self._shared_state["ssl_context"] = await self._create_ssl_context()

            if self._shared_state["ssl_context"]:
            # --- END OF FIX ---
                try:
                    _LOGGER.debug("%s [aiohttp_probe] Probing HTTPS (mTLS) connection for the first time...", self.log_prefix)
                    async with self._session.request("GET", f"https://{self._ip_address}:8888/devices", headers=probe_headers, ssl=self._shared_state["ssl_context"], timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status in (200, 401, 403):
                            _LOGGER.info("%s [aiohttp] HTTPS (mTLS) connection successful and memorized.", self.log_prefix)
                            self._shared_state["initialized"] = True
                            return None
                        else:
                            raise Exception(f"Unexpected HTTPS probe response: {response.status}")
                
                # --- START OF FIX: Handle offline device gracefully ---
                except aiohttp.ClientConnectorError as e:
                    # Log as warning (not error) because it's expected when AC is offline.
                    _LOGGER.warning("%s [aiohttp_probe] Device is unreachable (offline). Connection refused: %s", self.log_prefix, e)
                    self._shared_state["ssl_context"] = None # Reset to try again later
                    # Raise CannotConnect to let the coordinator know and retry later, but prevent the noisy traceback below.
                    raise CannotConnect(f"Device unreachable: {e}") from e
                # --- END OF FIX ---

                except Exception as e:
                    # --- START OF FIX: Detect malformed header error ---
                    if "Invalid header token" in str(e):
                        _LOGGER.error(
                            "%s [aiohttp_probe] Malformed header error detected! "
                            "The device does not comply with the HTTP standard. "
                            "Please switch to the 'Legacy (requests)' connection engine in the integration options.",
                            self.log_prefix
                        )
                        raise InvalidHeaderError("Malformed HTTP headers from device") from None
                    # --- END OF FIX ---
                    _LOGGER.warning("%s [aiohttp_probe] Initial probe with HTTPS (mTLS) failed: %s.", self.log_prefix, e, exc_info=True)
                    self._shared_state["ssl_context"] = None # Clear on failure to allow retries

            _LOGGER.error("%s [aiohttp_probe] HTTPS (mTLS) connection probe failed. The device is unreachable or the certificate/token is incorrect.", self.log_prefix)
            raise CannotConnect("Connection initialization failed (HTTPS)")
        # --- END OF FIX ---

    async def _async_execute_request(
        self,
        method: str,
        url_path: Optional[str],
        data: Optional[str],
        headers: Optional[Dict[str, str]],
        _is_probe: bool = False # Flag interno (ignorado en esta versión, pero mantenido por si acaso)
    ) -> Tuple[str, Optional[Dict[str, str]]]:
        """
        Executes a command asynchronously using aiohttp.
        It uses the "memorized" connection logic (HTTPS only).
        """
        req_headers = headers.copy() if headers else {}
        
        current_token = self._token
        if self._controller:
            current_token = self._controller._config.get(CONF_TOKEN, self._token)

        if not current_token:
            _LOGGER.error("%s [aiohttp] No token available! The request will fail.", self.log_prefix)
            raise AuthError("Token not configured for the aiohttp engine")

        req_headers.setdefault("Authorization", f'Bearer {current_token}')
        req_headers.setdefault("Content-Type", "application/json")

        # --- FIX: REMOVE FALLBACK LOGIC ---
        # We only use HTTPS (mTLS)
        # --- START OF FIX: Always use the shared SSL context ---
        ssl_context = self._shared_state.get("ssl_context")
        base_url = f"https://{self._ip_address}:8888"
        # --- END OF FIX ---

        if not ssl_context:
             # Attempt to initialize if context is missing (e.g., after a failed probe retry)
             try:
                 await self._try_connection()
                 ssl_context = self._shared_state.get("ssl_context")
             except CannotConnect:
                 # _try_connection already logged the warning/error
                 pass

             if not ssl_context:
                 _LOGGER.warning("%s [aiohttp] SSL context unavailable. Request aborted.", self.log_prefix)
                 raise CannotConnect("SSL context not available")

        full_url = f"{base_url}{url_path}"

        try:
            # --- START: Add log for sent command ---
            _LOGGER.debug(
                "%s [aiohttp] Sending request -> Method: %s, URL: %s, Payload: %s",
                self.log_prefix, method, full_url, data
            )
            # --- END: Add log for sent command ---
            async with self._session.request(
                method,
                url=full_url,
                headers=req_headers,
                data=data,
                ssl=ssl_context,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:

                response_text = await response.text()

                if _is_probe and response.status in (401, 403):
                     _LOGGER.debug("%s [aiohttp] Probe connected but got 401/403 (expected if token is bad, but connection is OK)", self.log_prefix)
                     return response_text, dict(response.headers)

                if response.status in (401, 403):
                    _LOGGER.error("%s [aiohttp] Authentication error (status %d). Token: %s...%s", self.log_prefix, response.status, current_token[:4], current_token[-4:])
                    raise AuthError(f"Authentication failed with status {response.status}. Check your token.")

                # If header parsing fails, aiohttp raises an exception here
                response.raise_for_status()

                _LOGGER.debug("%s [aiohttp] Request to %s successful. Status: %d", self.log_prefix, full_url, response.status)

                return response_text, dict(response.headers)

        except aiohttp.client_exceptions.ClientResponseError as e:
            if e.status == 400 and "Invalid header token" in str(e.message):
                _LOGGER.error("%s [aiohttp] Header parsing error detected! (BadHttpMessage)", self.log_prefix)
                _LOGGER.error("%s [aiohttp] This indicates the server responds with malformed headers even with mTLS.", self.log_prefix)

            _LOGGER.warning("%s [aiohttp] Client response error: %s", self.log_prefix, e)
            raise CannotConnect(f"Client response error: {e}") from e

        except (aiohttp.ClientSSLError, aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
            _LOGGER.warning("%s [aiohttp] Connection or timeout error: %s", self.log_prefix, e)
            raise CannotConnect(f"Connection error: {e}") from e
        except Exception as e:
            _LOGGER.error("%s [aiohttp] Unexpected error in async_execute: %s", self.log_prefix, e, exc_info=True)
            raise CannotConnect(f"Unexpected error: {e}") from e

    async def async_execute(
        self,
        method: str,
        url_path: Optional[str],
        data: Optional[str],
        headers: Optional[Dict[str, str]], # Main command's headers
        device_state: Optional[Dict[str, Any]] = None, # Pass device state for conditions
        _is_probe: bool = False
    ) -> Tuple[str, Optional[Dict[str, str]]]:
        """
        Orchestrates the execution of commands, including embedded ones.
        """
        # --- START: Replicate and FIX embedded command logic ---
        # --- START OF FIX: Ensure initialization before any execution ---
        await self._try_connection()
        # --- END OF FIX ---
        if self._embedded_command:
            _LOGGER.debug("%s [async_execute] Found embedded command.", self.log_prefix)
            try:
                # Check the condition before executing the embedded command
                if hasattr(self._embedded_command, 'check_execute_condition') and device_state:
                    if not self._embedded_command.check_execute_condition(device_state):
                        _LOGGER.debug("%s [async_execute] Embedded command condition not met. Skipping execution.", self.log_prefix)
                    else:
                        _LOGGER.debug("%s [async_execute] Embedded command condition met. Executing it before the main command.", self.log_prefix)
                        # The embedded command has its own template and params. We must render them.
                        embedded_template = getattr(self._embedded_command, '_connection_template', None)
                        if embedded_template:
                            # The embedded command might not need a 'value'
                            embedded_params_str = embedded_template.render()
                            embedded_params = json.loads(embedded_params_str)
                            embedded_data = json.dumps(embedded_params.get('json')) if 'json' in embedded_params else None

                            _LOGGER.debug("%s [async_execute] Executing embedded command with its own params: %s", self.log_prefix, embedded_params)
                            # Execute the embedded command by calling its own async_execute method.
                            # This ensures it is fully initialized and uses its own specific parameters.
                            await self._embedded_command.async_execute(
                                method=embedded_params.get('method'), url_path=embedded_params.get('url'),
                                data=embedded_data, headers=embedded_params.get('headers', headers),
                                device_state=device_state)
                            # --- END OF FIX ---
                        else:
                            _LOGGER.warning("%s [async_execute] Embedded command found but it has no connection_template.", self.log_prefix)
                else:
                    _LOGGER.warning("%s [async_execute] Embedded command found, but cannot check its condition (device_state is missing). Skipping.", self.log_prefix)

            except Exception as e:
                _LOGGER.error("%s [async_execute] Embedded command failed: %s", self.log_prefix, e, exc_info=True)
                # Re-raise the exception to prevent the main command from executing, as the failure is critical.
                raise
        # --- END: Replicate and FIX embedded command logic ---

        # Now, execute the main command.
        _LOGGER.debug("%s [async_execute] Executing main command with data: %s", self.log_prefix, data)
        return await self._async_execute_request(method, url_path, data, headers, _is_probe=_is_probe)

    def check_execute_condition(self, device_state):
        """Replicates the condition check from connection_request.py for async."""
        do_execute = True
        if hasattr(self, 'condition_template') and self.condition_template is not None:
            _LOGGER.debug("%s Evaluating execute condition for a command.", self.log_prefix)
            try:
                # The template expects '1' for true.
                rendered_condition = self.condition_template.render(device_state=device_state)
                _LOGGER.debug("%s Execute condition result: %s", self.log_prefix, rendered_condition)
                do_execute = str(rendered_condition).strip() == "1"
            except Exception as e:
                _LOGGER.error("%s Error evaluating execute condition, executing command anyway. Error: %s", self.log_prefix, e, exc_info=True)
                do_execute = True
        return do_execute