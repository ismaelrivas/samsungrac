# climate_ip/connection_raw.py
import logging
import json
import os
import copy
import time
import inspect
from typing import Any, Dict, Tuple, Optional, cast
from urllib.parse import urlparse
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC
from .connection import Connection, register_connection
from .exceptions import CannotConnect, AuthError
from .const import CONF_CERT
from .protocol_8888 import (
    Samsung8888Client,
    ProtocolError,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_RAW_8888 = "samsung_8888_raw"

@register_connection
class ConnectionRaw8888(Connection):
    """Wrapper for the robust raw socket API with auto-negotiation."""

    @staticmethod
    def match_type(type_str):
        return type_str == CONNECTION_TYPE_RAW_8888

    def load_from_yaml(self, node, connection_base):
        """Load configuration from yaml node dictionary.
        This provides the specific configuration (like keep_alive)
        from the 'connection' section of the YAML file.
        """
        if node:
            # Update keep_alive if present in the specific connection YAML
            if "keep_alive" in node:
                self._keep_alive = node["keep_alive"]
                
            # Also load params if present, to be consistent
            if "params" in node:
                self._params.update(node["params"])

            return True
        return False

    def create_updated(self, yaml_node):
        """Create a new connection instance with updated parameters from YAML.
        Replicates the logic from ConnectionAiohttp8888 to handle
        connection_template and params conversion.
        """
        from .const import (
            CONFIG_DEVICE_CONNECTION_TEMPLATE,
            CONFIG_DEVICE_CONNECTION_PARAMS,
            CONFIG_DEVICE_CONNECTION,
            CONFIG_DEVICE_CONDITION_TEMPLATE,
        )

        # Shallow copy for value‑specific operations
        new_connection = copy.copy(self)
        new_connection._params = getattr(self, "_params", {}).copy()
        # Propagate controller reference to the new instance (crucial for shared client logic)
        new_connection._controller = getattr(self, "_controller", None)

        if yaml_node and "keep_alive" in yaml_node:
            new_connection._keep_alive = yaml_node["keep_alive"]

        # Compile connection_template if present
        if yaml_node and CONFIG_DEVICE_CONNECTION_TEMPLATE in yaml_node:
            template_str = yaml_node[CONFIG_DEVICE_CONNECTION_TEMPLATE]
            from jinja2 import Template
            new_connection._connection_template = Template(template_str)

        # If params are defined without an explicit connection_template, store them
        # directly on _params. properties.py's _resolve_async_params will read them.
        elif yaml_node and CONFIG_DEVICE_CONNECTION_PARAMS in yaml_node:
            params = {**getattr(self, "_params", {}), **yaml_node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {})}
            new_connection._params = params


        # Embedded commands handling
        if yaml_node and CONFIG_DEVICE_CONNECTION in yaml_node:
            new_connection._embedded_command = new_connection.create_updated(
                yaml_node[CONFIG_DEVICE_CONNECTION]
            )
            if CONFIG_DEVICE_CONDITION_TEMPLATE in yaml_node[CONFIG_DEVICE_CONNECTION]:
                condition_str = yaml_node[CONFIG_DEVICE_CONNECTION][CONFIG_DEVICE_CONDITION_TEMPLATE]
                from jinja2 import Template
                if new_connection._embedded_command:
                    new_connection._embedded_command.condition_template = Template(condition_str)

        return new_connection

    def get_diagnostics(self) -> dict:
        """Return diagnostic information about the raw socket connection."""
        return {
            "is_connected": getattr(self, "_is_connected", False),
            "reconnect_retries": getattr(self, "_reconnect_retries", 0),
            "engine": "raw_socket"
        }

    # pylint: disable=too-many-arguments
    def __init__(self, config: Dict[str, Any], logger: logging.Logger, hass: Any, session: Any, ip_address: Optional[str]):
        super().__init__(config, logger)
        self._host: Optional[str] = ip_address or cast(Optional[str], config.get(CONF_IP_ADDRESS))
        cert_file = config.get(CONF_CERT)
        if cert_file and not os.path.dirname(cert_file):
            cert_file = os.path.join(os.path.dirname(__file__), cert_file)
        self._cert = cert_file
        self._controller = None # Initialize controller reference
        self._client: Optional[Samsung8888Client] = None
        self._params = {}
        self._connection_template = None
        # Public attribute used to store Jinja2 templates for execution conditions.
        # Initialize here so static analyzers and type checkers recognize it.
        self.condition_template: Optional[Any] = None
        self._embedded_command = None
        self._keep_alive = config.get("keep_alive", True)

    def set_controller_ref(self, controller):
        """Allows the property to set a reference to the main controller."""
        self._controller = controller
        # Propagate to embedded command if it exists
        if self._embedded_command and hasattr(self._embedded_command, "set_controller_ref"):
            self._embedded_command.set_controller_ref(controller)

    async def async_get_client(self) -> Samsung8888Client:
        """Get the raw client, initializing it if necessary (shared or standalone)."""
        # --- Shared Client Logic ---
        # If we have a controller reference, try to use a shared client stored on it.
        # This prevents multiple connections (sockets) for the same device.
        if self._controller:
            if not hasattr(self._controller, "_shared_raw_client"):
                self._controller._shared_raw_client = None
            
            if self._controller._shared_raw_client is None:
                if not self._host:
                    raise CannotConnect("Host/IP address not provided for RAW connection")
                
                # --- START OF FIX: Dynamic Port Detection ---
                port = 8888 # Default for legacy devices
                
                # Try to extract from current params URL (if absolute)
                url = self._params.get("url")
                if url:
                    parsed = urlparse(url)
                    if parsed.port:
                        port = parsed.port
                    elif parsed.scheme == "https":
                        port = 443
                    elif parsed.scheme == "http":
                        port = 80
                
                _LOGGER.debug("%s [Shared] Initializing NEW shared client. Controller ID: %s, Port: %s", self.log_prefix, id(self._controller), port)
                self._controller._shared_raw_client = Samsung8888Client(
                    self._host, port, self._cert, log_prefix=self.log_prefix
                )
            else:
                _LOGGER.debug("%s [Shared] Reusing EXISTING shared client. Controller ID: %s", self.log_prefix, id(self._controller))
            
            return self._controller._shared_raw_client
        
        # Fallback for standalone usage (no controller)
        if self._client is None:
            _LOGGER.debug("%s [Standalone] Controller is None! Initializing local client.", self.log_prefix)
            if not self._host:
                raise CannotConnect("Host/IP address not provided for RAW connection")
            
            # --- START OF FIX: Dynamic Port Detection (Standalone) ---
            port = 8888
            url = self._params.get("url")
            if url:
                parsed = urlparse(url)
                if parsed.port:
                    port = parsed.port
                elif parsed.scheme == "https":
                    port = 443
                elif parsed.scheme == "http":
                    port = 80

            self._client = Samsung8888Client(
                self._host, port, self._cert, log_prefix=self.log_prefix
            )
        return self._client



    @property
    def log_prefix(self) -> str:
        """Generate a consistent log prefix."""
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        mac = self._config.get(CONF_MAC)
        if mac:
            duid = mac.replace(":", "")
            return f"[{duid[-6:]}]"
        # Fallback if controller is not set yet and no MAC available
        return f"[{self._host or 'NO_IP'}]"

    @property
    def is_async_native(self) -> bool:
        return True

    def execute(self, template, value, device_state, device_id=None):
        """Not implemented for async connections."""
        raise NotImplementedError("This connection is async-native. Use async_execute.")

    async def async_execute(
        self,
        method,
        url,
        data,
        headers,
        device_state=None,
        _is_probe=False,
        _is_poll=False,
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Execute a command (including embedded commands) over raw sockets."""
        # --- Embedded command handling ---
        if self._embedded_command:
            _LOGGER.debug("%s [async_execute] Found embedded command.", self.log_prefix)
            try:
                if hasattr(self._embedded_command, "check_execute_condition") and device_state is not None:
                    if not self._embedded_command.check_execute_condition(device_state):
                        _LOGGER.debug(
                            "%s [async_execute] Embedded command condition not met. Skipping execution.",
                            self.log_prefix,
                        )
                    else:
                        _LOGGER.debug("%s [async_execute] Embedded command condition met. Executing it before the main command.", self.log_prefix)
                        embedded_template = getattr(self._embedded_command, "_connection_template", None)
                        embedded_params = getattr(self._embedded_command, "_params", {})
                        if embedded_template:
                            embedded_params_str = embedded_template.render()
                            embedded_params = json.loads(embedded_params_str)
                        elif embedded_params:
                            # Fallback: use _params directly (e.g. YAML-defined params without a Jinja template)
                            _LOGGER.debug(
                                "%s [async_execute] Embedded command has no connection_template, using _params directly.",
                                self.log_prefix,
                            )
                        else:
                            _LOGGER.warning("%s [async_execute] Embedded command found but it has no connection_template or params.", self.log_prefix)
                            embedded_params = None

                        if embedded_params:
                            embedded_data = json.dumps(embedded_params.get("json")) if "json" in embedded_params else None
                            # Resolve the URL: prefer the embedded command's own URL, fall back to the main one
                            embedded_url = embedded_params.get("url", url)
                            embedded_method = embedded_params.get("method", method)
                            _LOGGER.debug(
                                "%s [async_execute] Executing embedded command with params: %s",
                                self.log_prefix, embedded_params
                            )
                            res = cast(
                                Any,
                                self._embedded_command.async_execute(
                                    method=embedded_method,
                                    url=embedded_url,
                                    data=embedded_data,
                                    headers=embedded_params.get("headers", headers),
                                    device_state=device_state,
                                ),
                            )
                            # Support both sync and async implementations of embedded command execution.
                            if inspect.isawaitable(res):
                                await res
                else:
                    _LOGGER.warning("%s [async_execute] Embedded command found, but cannot check its condition (device_state missing).", self.log_prefix)
            except (CannotConnect, AuthError) as e:
                _LOGGER.warning(
                    "%s [async_execute] Embedded command failed due to connection error: %s", self.log_prefix, e
                )
                raise
            except Exception as e:
                _LOGGER.error(
                    "%s [async_execute] Embedded command failed: %s", self.log_prefix, e
                )
                raise
        # --- Timing measurement for main request ---
        start_time = time.perf_counter()

        # --- Periodic Connection Reset Logic ---
        # If this is a poll and we are in "Periodic Reset" mode (keep_alive=False in config),
        # we explicitly close the connection before starting the new poll.
        # If this is a poll and we are in "Periodic Reset" mode (keep_alive=False in config),
        # we explicitly close the connection before starting the new poll.
        if _is_poll and not self._keep_alive:
            client_to_close = None
            if self._controller and hasattr(self._controller, "_shared_raw_client"):
                client_to_close = self._controller._shared_raw_client
                self._controller._shared_raw_client = None # Clear shared ref
            elif self._client:
                client_to_close = self._client
                self._client = None
        
            if client_to_close:
                _LOGGER.debug("%s [Periodic Reset] Closing connection before poll.", self.log_prefix)
                await client_to_close.close()
        # ---------------------------------------

        _LOGGER.debug("%s [async_execute] Executing main command with data: %s (is_poll=%s, keep_alive=%s)", self.log_prefix, data, _is_poll, self._keep_alive)
        path = urlparse(url).path
        
        # --- FIX 2: Correct Data Type Handling ---
        if isinstance(data, dict):
            body = data
        elif data:
            body = json.loads(data)
        else:
            body = None

        # --- FIX 3: Safe Token Access ---
        from homeassistant.const import CONF_TOKEN
        
        req_headers = headers.copy() if headers else {}
        
        # Get token from config or controller (mimics aiohttp logic)
        current_token = self._config.get(CONF_TOKEN)
        if self._controller:
             # Prefer public property if available, closer to the source of truth
            if hasattr(self._controller, "token"):
                current_token = self._controller.token
            else:
                current_token = self._controller._config.get(CONF_TOKEN, current_token)

        if not current_token:
            _LOGGER.error("%s [RAW] No token available! The request will fail.", self.log_prefix)
            raise AuthError("Token not configured for the raw engine")

        req_headers.setdefault("Authorization", f"Bearer {current_token}")
        req_headers.setdefault("Content-Type", "application/json")
        # --- END OF FIX ---

        client = await self.async_get_client()
        try:
            resp, err = await client.request(method, path, body, req_headers)
            if err:
                # --- FIX 1: Proper Error Handling ---
                _LOGGER.error("%s API Error: %s", self.log_prefix, err)
                raise CannotConnect(f"API Error: {err}")
            elapsed = time.perf_counter() - start_time
            _LOGGER.debug("%s [RAW] Request completed in %.3f seconds", self.log_prefix, elapsed)
            return resp, None
        except AuthError:
            raise AuthError("Invalid token")
        except CannotConnect as e:
            # Classify common, expected connection errors with cleaner messages
            err_str = str(e).lower()
            if "111" in str(e) or "connection refused" in err_str:
                msg = "Connection refused (device unreachable or offline)"
            elif "timed out" in err_str or "etimedout" in err_str:
                msg = "Connection timed out"
            elif "name or service not known" in err_str or "nodename" in err_str:
                msg = "Host not found (DNS error)"
            else:
                msg = f"Connection error: {e}"
            _LOGGER.debug("%s %s", self.log_prefix, msg)
            await client.close()
            if _is_probe:
                return None, None
            raise CannotConnect(msg)
        except Exception as e:
            raise CannotConnect(f"Unexpected error: {e}")



    async def close(self):
        """
        Close the connection and release resources.
        This is called when the integration is unloaded or the connection method changes.
        """
        _LOGGER.debug("%s [RAW] Closing connection resources...", self.log_prefix)
        
        # 1. Close internal embedded command (if any)
        if self._embedded_command and hasattr(self._embedded_command, "close"):
            try:
                _LOGGER.debug("%s [RAW] Closing embedded command...", self.log_prefix)
                await self._embedded_command.close()
            except Exception as e:
                _LOGGER.warning("%s [RAW] Error closing embedded command: %s", self.log_prefix, e)

        # 2. Close the local client if it exists
        if self._client:
            _LOGGER.debug("%s [RAW] Closing local client...", self.log_prefix)
            try:
                await self._client.close()
            except Exception as e:
                _LOGGER.error("%s [RAW] Error closing local client: %s", self.log_prefix, e)
            finally:
                self._client = None
             
        # 3. Close the shared client if it exists and we have a controller ref
        if self._controller and hasattr(self._controller, "_shared_raw_client"):
            shared_client = self._controller._shared_raw_client
            if shared_client:
                _LOGGER.debug("%s [RAW] Closing shared client...", self.log_prefix)
                try:
                    await shared_client.close()
                except Exception as e:
                    _LOGGER.error("%s [RAW] Error closing shared client: %s", self.log_prefix, e)
                finally:
                    self._controller._shared_raw_client = None
        
        _LOGGER.debug("%s [RAW] Connection resources closed.", self.log_prefix)
