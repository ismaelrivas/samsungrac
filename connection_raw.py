# climate_ip/connection_raw.py
import logging
import json
import os
import copy
import time
import inspect
from typing import Any, Dict, Tuple, Optional, cast
from urllib.parse import urlparse
from homeassistant.const import CONF_IP_ADDRESS
from .connection import Connection, register_connection
from .exceptions import CannotConnect, AuthError
from .yaml_const import CONF_CERT
from .protocol_8888 import (
    Samsung8888Client,
    ProtocolError,
    AuthError as LibAuthError,
    ConnectionError as LibConnError,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_RAW_8888 = "samsung_8888_raw"

@register_connection
class ConnectionRaw8888(Connection):
    """Wrapper for the robust raw socket API with auto-negotiation."""

    @staticmethod
    def match_type(type_str):
        return type_str == CONNECTION_TYPE_RAW_8888

    def create_updated(self, yaml_node):
        """Create a new connection instance with updated parameters from YAML.
        Replicates the logic from ConnectionAiohttp8888 to handle
        connection_template and params conversion.
        """
        from .yaml_const import (
            CONFIG_DEVICE_CONNECTION_TEMPLATE,
            CONFIG_DEVICE_CONNECTION_PARAMS,
            CONFIG_DEVICE_CONNECTION,
            CONFIG_DEVICE_CONDITION_TEMPLATE,
        )

        # Shallow copy for value‑specific operations
        new_connection = copy.copy(self)
        new_connection._params = getattr(self, "_params", {}).copy()

        # Compile connection_template if present
        if yaml_node and CONFIG_DEVICE_CONNECTION_TEMPLATE in yaml_node:
            template_str = yaml_node[CONFIG_DEVICE_CONNECTION_TEMPLATE]
            from jinja2 import Template
            new_connection._connection_template = Template(template_str)

        # Convert static params to a template (HACK for legacy configs)
        elif yaml_node and CONFIG_DEVICE_CONNECTION_PARAMS in yaml_node:
            params = {**getattr(self, "_params", {}), **yaml_node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {})}
            new_connection._params = params
            template_dict = {}
            if "json" in params:
                template_dict["json"] = params["json"]
            url_from_params = params.get("url", getattr(self, "_params", {}).get("url"))
            if url_from_params:
                template_dict["url"] = urlparse(url_from_params).path
            template_dict["method"] = params.get("method", getattr(self, "_params", {}).get("method"))
            if not template_dict.get("url"):
                # Use self.log_prefix for consistency, even if it's not fully initialized yet.
                _LOGGER.error(
                    "%s Could not determine 'url' from params during template hack.",
                    self.log_prefix,
                )
            template_str = json.dumps(template_dict)
            from jinja2 import Template
            new_connection._connection_template = Template(template_str)

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

    def __init__(self, config: Dict[str, Any], logger: logging.Logger, hass: Any, session: Any, ip_address: Optional[str]):
        super().__init__(config, logger)
        self._host: Optional[str] = ip_address or cast(Optional[str], config.get(CONF_IP_ADDRESS))
        cert_file = config.get(CONF_CERT)
        if cert_file and not os.path.dirname(cert_file):
            cert_file = os.path.join(os.path.dirname(__file__), cert_file)
        self._cert = cert_file
        self._controller = None # Initialize controller reference
        self._client: Optional[Samsung8888Client] = None
        self._ssl_modes = ["legacy", "modern"]
        self._current_mode_idx = 0
        self._params = {}
        self._connection_template = None
        # Public attribute used to store Jinja2 templates for execution conditions.
        # Initialize here so static analyzers and type checkers recognize it.
        self.condition_template: Optional[Any] = None
        self._embedded_command = None

    def set_controller_ref(self, controller):
        """Allows the property to set a reference to the main controller."""
        self._controller = controller

    async def async_get_client(self) -> Samsung8888Client:
        if self._client is None:
            # Ensure host is present and narrow its type from Optional[str] to str for the client constructor.
            if not self._host:
                raise CannotConnect("Host/IP address not provided for RAW connection")
            mode = self._ssl_modes[self._current_mode_idx]
            _LOGGER.debug("%s Initializing RAW client in mode: %s", self.log_prefix, mode)
            self._client = Samsung8888Client(
                self._host, 8888, self._cert, ssl_mode=mode, log_prefix=self.log_prefix
            )
        return self._client

    def _rotate_mode(self):
        self._current_mode_idx = (self._current_mode_idx + 1) % len(self._ssl_modes)
        _LOGGER.info("%s Rotating SSL to: %s", self.log_prefix, self._ssl_modes[self._current_mode_idx])
        self._client = None

    @property
    def log_prefix(self) -> str:
        """Generate a consistent log prefix."""
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        # Fallback if controller is not set yet
        return f"[{self._host or 'NO_IP'}]"

    @property
    def is_async_native(self) -> bool:
        return True

    async def async_execute(
        self,
        method,
        url,
        data,
        headers,
        device_state=None,
        _is_probe=False,
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
                        if embedded_template:
                            embedded_params_str = embedded_template.render()
                            embedded_params = json.loads(embedded_params_str)
                            embedded_data = json.dumps(embedded_params.get("json")) if "json" in embedded_params else None
                            _LOGGER.debug(
                                "%s [async_execute] Executing embedded command with its own params: %s",
                                self.log_prefix, embedded_params
                            )
                            res = cast(
                                Any,
                                self._embedded_command.async_execute(
                                    method=embedded_params.get("method"),
                                    url=embedded_params.get("url"),
                                    data=embedded_data,
                                    headers=embedded_params.get("headers", headers),
                                    device_state=device_state,
                                ),
                            )
                            # Support both sync and async implementations of embedded command execution.
                            if inspect.isawaitable(res):
                                await res
                        else:
                            _LOGGER.warning("%s [async_execute] Embedded command found but it has no connection_template.", self.log_prefix)
                else:
                    _LOGGER.warning("%s [async_execute] Embedded command found, but cannot check its condition (device_state missing).", self.log_prefix)
            except Exception as e:
                _LOGGER.error(
                    "%s [async_execute] Embedded command failed: %s", self.log_prefix, e
                )
                raise
        # --- Timing measurement for main request ---
        start_time = time.perf_counter()
        _LOGGER.debug("%s [async_execute] Executing main command with data: %s", self.log_prefix, data)
        path = urlparse(url).path
        body = json.loads(data) if data else None
        for i in range(len(self._ssl_modes)):
            client = await self.async_get_client()
            try:
                resp, err = await client.request(method, path, body, headers)
                if err:
                    _LOGGER.warning("%s API Error: %s", self.log_prefix, err)
                    return None, None
                elapsed = time.perf_counter() - start_time
                _LOGGER.info("%s [RAW] Request completed in %.3f seconds", self.log_prefix, elapsed)
                return resp, None
            except LibAuthError:
                raise AuthError("Invalid token")
            except LibConnError as e:
                _LOGGER.warning("%s Connection error (%s)", self.log_prefix, e)
                await client.close()
                if i == len(self._ssl_modes) - 1:
                    if _is_probe:
                        return None, None
                    raise CannotConnect(f"Total connection failure: {e}")
                self._rotate_mode()
            except Exception as e:
                raise CannotConnect(f"Unexpected error: {e}")

        # Fallback return to satisfy type checkers and handle unexpected flows;
        # return a tuple of (resp, error) both set to None to indicate no response.
        return None, None

    def check_execute_condition(self, device_state):
        """Replicates the condition check from connection_request.py for async."""
        do_execute = True
        if hasattr(self, "condition_template") and self.condition_template is not None:
            _LOGGER.debug("%s Evaluating execute condition for a command.", self.log_prefix)
            try:
                rendered_condition = self.condition_template.render(device_state=device_state)
                _LOGGER.debug("%s Execute condition result: %s", self.log_prefix, rendered_condition)
                do_execute = str(rendered_condition).strip() == "1"
            except Exception as e:
                _LOGGER.error(
                    "%s Error evaluating execute condition, executing command anyway. Error: %s",
                    self.log_prefix,
                    e,
                    exc_info=True,
                )
                do_execute = True
        return do_execute