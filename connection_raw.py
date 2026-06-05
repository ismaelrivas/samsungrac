# pylint: disable=import-outside-toplevel,duplicate-code,line-too-long,protected-access,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-nested-blocks,too-many-positional-arguments,too-many-statements,wrong-import-position
"""Raw socket connection engine for Samsung devices on port 8888."""

import asyncio
import copy
import inspect
import logging
import os
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from homeassistant.util.json import json_loads
from homeassistant.helpers.json import json_dumps

from homeassistant.helpers.template import Template

if TYPE_CHECKING:
    from .controller import ClimateController

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN

from .connection import Connection, register_connection
from .const import (
    CONF_CERT,
    CONFIG_DEVICE_CONDITION_TEMPLATE,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
)
from .exceptions import AuthError, CannotConnect
from .helpers import format_placeholders
from .protocol_8888 import Samsung8888Client

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_RAW_8888 = "samsung_8888_raw"


@register_connection
class ConnectionRaw8888(Connection):
    """Wrapper for the robust raw socket API with auto-negotiation."""

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Return True if this connection handles the given type string."""
        return type_str == CONNECTION_TYPE_RAW_8888

    def load_from_yaml(self, node: dict[str, Any] | None, connection_base: Any) -> bool:
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

    def create_updated(self, yaml_node: dict[str, Any] | None) -> "ConnectionRaw8888":
        """Create a new connection instance with updated parameters from YAML.
        Replicates the logic from ConnectionAiohttp8888 to handle
        connection_template and params conversion.
        """
        # pylint: disable=import-outside-toplevel,protected-access
        # Rationale: all accesses are on a shallow copy of self (same class).

        # Shallow copy for value-specific operations
        new_connection = copy.copy(self)
        new_connection._params = self._params.copy()

        if yaml_node and "keep_alive" in yaml_node:
            new_connection._keep_alive = yaml_node["keep_alive"]

        # Compile connection_template if present
        if yaml_node and CONFIG_DEVICE_CONNECTION_TEMPLATE in yaml_node:
            new_connection._connection_template = Template(
                yaml_node[CONFIG_DEVICE_CONNECTION_TEMPLATE], self._hass
            )
        elif yaml_node and CONFIG_DEVICE_CONNECTION_PARAMS in yaml_node:
            params_node = yaml_node[CONFIG_DEVICE_CONNECTION_PARAMS] or {}
            params = {
                **self._params,
                **params_node,
            }
            new_connection._params = params

        # Embedded commands handling
        if yaml_node and CONFIG_DEVICE_CONNECTION in yaml_node:
            new_connection._embedded_command = new_connection.create_updated(
                yaml_node[CONFIG_DEVICE_CONNECTION]
            )
            if CONFIG_DEVICE_CONDITION_TEMPLATE in yaml_node[CONFIG_DEVICE_CONNECTION]:
                condition_str = yaml_node[CONFIG_DEVICE_CONNECTION][
                    CONFIG_DEVICE_CONDITION_TEMPLATE
                ]
                if new_connection._embedded_command:
                    new_connection._embedded_command.condition_template = Template(
                        condition_str, self._hass
                    )
        # pylint: enable=protected-access

        return new_connection

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the raw socket connection."""
        return {
            "is_connected": self._is_connected,
            "reconnect_retries": self._reconnect_retries,
            "engine": "raw_socket",
        }

    # pylint: disable=import-outside-toplevel,too-many-arguments
    def __init__(
        self,
        config: dict[str, Any],
        logger: logging.Logger,
        hass: Any,
        session: Any,
        ip_address: str | None,
    ) -> None:
        """Initialize the connection."""
        super().__init__(config, logger)
        self._hass = hass
        # Marking session as used for Pylint
        _ = session  # pragma: no mutate

        self._host: str | None = ip_address or cast(str | None, config.get(CONF_IP_ADDRESS))  # pragma: no mutate
        cert_file = config.get(CONF_CERT)
        if cert_file and not os.path.dirname(cert_file):
            cert_file = os.path.join(os.path.dirname(__file__), cert_file)
        self._cert = cert_file
        self._controller: "ClimateController | None" = None  # Initialize controller reference
        self._client: Samsung8888Client | None = None
        self._params: dict[str, Any] = {}
        self._connection_template: Template | None = None
        # Public attribute used to store Jinja2 templates for execution conditions.
        # Initialize here so static analyzers and type checkers recognize it.
        self.condition_template: Template | None = None
        self._embedded_command: ConnectionRaw8888 | None = None
        self._keep_alive = config.get("keep_alive", True)
        
        # Estado interno de la conexión nativa
        self._is_connected: bool = False
        self._reconnect_retries: int = 0

    def set_controller_ref(self, controller: "ClimateController") -> None:
        """Allows the property to set a reference to the main controller."""
        self._controller = controller
        # Propagate to embedded command if it exists
        if self._embedded_command:
            self._embedded_command.set_controller_ref(controller)

    async def async_get_client(self) -> Samsung8888Client:
        """Get the raw client, initializing it if necessary (shared or standalone)."""
        # --- Shared Client Logic ---
        if self._controller:
            # pylint: disable=import-outside-toplevel,protected-access
            if self._controller._shared_raw_client is None:  # type: ignore[attr-defined]
                if not self._host:
                    raise CannotConnect("Host/IP address not provided for RAW connection")  # pragma: no mutate

                # --- Dynamic Port Detection ---
                port = 8888  # Default for legacy devices

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

                # fmt: off
                _LOGGER.debug('%s [Shared] Initializing NEW shared client. Controller ID: %s, Port: %s', self.log_prefix, id(self._controller), port)  # pragma: no mutate
                # fmt: on
                self._controller._shared_raw_client = Samsung8888Client(  # type: ignore[attr-defined]
                    self._host, port, self._cert, log_prefix=self.log_prefix
                )
            else:
                # fmt: off
                _LOGGER.debug('%s [Shared] Reusing EXISTING shared client. Controller ID: %s', self.log_prefix, id(self._controller))  # pragma: no mutate
                # fmt: on

            return self._controller._shared_raw_client  # type: ignore[attr-defined]
            # pylint: enable=protected-access

        # Fallback for standalone usage (no controller)
        if self._client is None:
            # fmt: off
            _LOGGER.debug('%s [Standalone] Controller is None! Initializing local client.', self.log_prefix)  # pragma: no mutate
            # fmt: on
            if not self._host:
                raise CannotConnect("Host/IP address not provided for RAW connection")  # pragma: no mutate

            # --- Dynamic Port Detection (Standalone) ---
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
        """Return True if connection is native async."""
        return True

    def execute(
        self,
        template: Template | None,
        value: Any,
        device_state: dict[str, Any],
        device_id: str | None = None,
    ) -> None:
        """Not implemented for async connections."""
        raise NotImplementedError("This connection is async-native. Use async_execute.")  # pragma: no mutate

    async def async_execute(
        self,
        method: str,
        url: str | None,
        data: Any,
        headers: dict[str, str] | None,
        device_state: dict[str, Any] | None = None,
        _is_probe: bool = False,  # pragma: no mutate
        _is_poll: bool = False,  # pragma: no mutate
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Execute a command (including embedded commands) over raw sockets."""
        
        # 1. Erradicación del hasattr defensivo
        host = self._host or self._config.get(CONF_IP_ADDRESS, "")
        mac = self._config.get(CONF_MAC, "")
        dev_id = None
        current_token = self._config.get(CONF_TOKEN)

        if self._controller:
            # Prefer public property if available, closer to the source of truth
            if hasattr(self._controller, "token"):
                current_token = self._controller.token
            else:
                current_token = self._controller._config.get(CONF_TOKEN, current_token)  # type: ignore[attr-defined] # pylint: disable=import-outside-toplevel,protected-access

            if hasattr(self._controller, "device_id"):
                dev_id = self._controller.device_id

        # --- Embedded command handling ---
        if self._embedded_command:
            _LOGGER.debug("%s [async_execute] Found embedded command.", self.log_prefix)  # pragma: no mutate
            try:
                if device_state is not None:
                    if not self._embedded_command.check_execute_condition(device_state):
                        # fmt: off
                        _LOGGER.debug('%s [async_execute] Embedded command condition not met. Skipping execution.', self.log_prefix)  # pragma: no mutate
                        # fmt: on
                    else:
                        # fmt: off
                        _LOGGER.debug('%s [async_execute] Embedded command condition met. Executing it before the main command.', self.log_prefix)  # pragma: no mutate
                        # fmt: on
                        embedded_template = self._embedded_command._connection_template
                        embedded_params = self._embedded_command._params
                        if embedded_template:
                            if hasattr(embedded_template, "async_render"):
                                embedded_params_str = embedded_template.async_render()
                            else:
                                embedded_params_str = embedded_template.render()
                            embedded_params = json_loads(embedded_params_str)
                        elif embedded_params:
                            # Fallback: use _params directly (e.g. YAML-defined params without a Jinja template)
                            # fmt: off
                            _LOGGER.debug('%s [async_execute] Embedded command has no connection_template, using _params directly.', self.log_prefix)  # pragma: no mutate
                            # fmt: on
                        else:
                            # fmt: off
                            _LOGGER.warning('%s [async_execute] Embedded command found but it has no connection_template or params.', self.log_prefix)  # pragma: no mutate
                            # fmt: on
                            embedded_params = None  # pragma: no mutate

                        if embedded_params:
                            # CRITICAL FIX: Replace placeholders in embedded_params early
                            embedded_params = format_placeholders(
                                embedded_params, current_token, host, dev_id, mac
                            )

                            # 2. Erradicación de la doble lectura del diccionario
                            json_payload = embedded_params.get("json")
                            embedded_data = (
                                json_dumps(json_payload)
                                if json_payload is not None
                                else None
                            )
                            
                            # Resolve the URL: prefer the embedded command's own URL, fall back to the main one
                            embedded_url = embedded_params.get("url", url)
                            embedded_method = embedded_params.get("method", method)
                            # fmt: off
                            _LOGGER.debug('%s [async_execute] Executing embedded command with params: %s', self.log_prefix, embedded_params)  # pragma: no mutate
                            # fmt: on
                            res = cast(  # pragma: no mutate
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
                    # fmt: off
                    _LOGGER.warning('%s [async_execute] Embedded command found, but cannot check its condition (device_state missing).', self.log_prefix)  # pragma: no mutate
                    # fmt: on
            except (CannotConnect, AuthError) as e:
                # fmt: off
                _LOGGER.warning('%s [async_execute] Embedded command failed due to connection error: %s', self.log_prefix, e)  # pragma: no mutate
                # fmt: on
                raise  # pragma: no mutate
            except (asyncio.TimeoutError, OSError, ValueError, TypeError) as e:
                _LOGGER.error("%s [async_execute] Embedded command failed: %s", self.log_prefix, e)  # pragma: no mutate
                raise  # pragma: no mutate

        # --- Timing measurement for main request ---
        start_time = time.perf_counter()

        # --- Periodic Connection Reset Logic ---
        # If this is a poll and we are in "Periodic Reset" mode (keep_alive=False in config),
        # we explicitly close the connection before starting the new poll.
        if _is_poll and not self._keep_alive:
            if self._controller:
                client_to_close = self._controller._shared_raw_client  # pylint: disable=protected-access
                self._controller._shared_raw_client = None  # pylint: disable=protected-access
            else:
                client_to_close = self._client
                self._client = None

            if client_to_close:
                # fmt: off
                _LOGGER.debug('%s [Periodic Reset] Closing connection before poll.', self.log_prefix)  # pragma: no mutate
                # fmt: on
                await client_to_close.close()
        # ---------------------------------------

        # fmt: off
        _LOGGER.debug('%s [async_execute] Executing main command with data: %s (is_poll=%s, keep_alive=%s)', self.log_prefix, data, _is_poll, self._keep_alive)  # pragma: no mutate
        # fmt: on

        # CRITICAL FIX: Replace placeholders in URL and Headers
        url = format_placeholders(url, current_token, host, dev_id, mac)
        path = str(urlparse(url).path) if url else ""

        # CRITICAL FIX: Replace placeholders in Data (body)
        data = format_placeholders(data, current_token, host, dev_id, mac)

        # --- Correct Data Type Handling ---
        if isinstance(data, dict):
            body = data
        elif data:
            body = json_loads(data)
        else:
            body = None

        req_headers = headers.copy() if headers else {}
        req_headers = format_placeholders(
            req_headers, current_token, host, dev_id, mac
        )

        if not current_token:
            _LOGGER.error("%s [RAW] No token available! The request will fail.", self.log_prefix)  # pragma: no mutate
            raise AuthError("Token not configured for the raw engine")  # pragma: no mutate

        req_headers.setdefault("Authorization", f"Bearer {current_token}")
        req_headers.setdefault("Content-Type", "application/json")
        # --- END OF FIX ---

        client = await self.async_get_client()
        try:
            async with self.async_lock:
                resp, err = await client.request(method, path, body, req_headers)
            if err:
                # --- Proper Error Handling ---
                _LOGGER.error("%s API Error: %s", self.log_prefix, err)  # pragma: no mutate
                raise CannotConnect(f"API Error: {err}")  # pragma: no mutate
            elapsed = time.perf_counter() - start_time  # pragma: no mutate
            _LOGGER.debug("%s [RAW] Request completed in %.3f seconds", self.log_prefix, elapsed)  # pragma: no mutate
            return resp, None
        except AuthError as exc:
            # pylint: disable=import-outside-toplevel,bad-exception-cause
            raise AuthError("Invalid token") from exc  # pragma: no mutate
        except CannotConnect as e:
            # Classify common, expected connection errors with cleaner messages
            err_str = str(e).lower()
            if "111" in str(e) or "connection refused" in err_str:  # pragma: no mutate
                msg = "Connection refused (device unreachable or offline)"  # pragma: no mutate
            elif "timed out" in err_str or "etimedout" in err_str:  # pragma: no mutate
                msg = "Connection timed out"  # pragma: no mutate
            elif "name or service not known" in err_str or "nodename" in err_str:  # pragma: no mutate
                msg = "Host not found (DNS error)"  # pragma: no mutate
            else:
                msg = f"Connection error: {e}"
            _LOGGER.debug("%s %s", self.log_prefix, msg)  # pragma: no mutate
            await client.close()
            if _is_probe:
                return None, None
            # pylint: disable=import-outside-toplevel,bad-exception-cause
            raise CannotConnect(msg) from e  # pragma: no mutate
        except (asyncio.TimeoutError, OSError, ValueError, TypeError) as e:
            # pylint: disable=import-outside-toplevel,bad-exception-cause
            raise CannotConnect(f"Unexpected error: {e}") from e  # pragma: no mutate

    async def close(self) -> None:
        """
        Close the connection and release resources.
        This is called when the integration is unloaded or the connection method changes.
        """
        _LOGGER.debug("%s [RAW] Closing connection resources...", self.log_prefix)  # pragma: no mutate

        # 1. Close internal embedded command (if any)
        if self._embedded_command:
            try:
                _LOGGER.debug("%s [RAW] Closing embedded command...", self.log_prefix)  # pragma: no mutate
                await self._embedded_command.close()
            except (asyncio.TimeoutError, OSError) as e:
                _LOGGER.warning("%s [RAW] Error closing embedded command: %s", self.log_prefix, e)  # pragma: no mutate

        # 2. Close the local client if it exists
        if self._client:
            _LOGGER.debug("%s [RAW] Closing local client...", self.log_prefix)  # pragma: no mutate
            try:
                # FIX: client.close() is an async routine, it must be awaited!
                # Wait_closed logic is safely handled inside client.close() natively.
                await self._client.close()
            except (asyncio.TimeoutError, OSError) as e:
                _LOGGER.error("%s [RAW] Error closing local client: %s", self.log_prefix, e)  # pragma: no mutate
            finally:
                self._client = None

        # 3. Close the shared client if it exists and we have a controller ref
        if self._controller and self._controller._shared_raw_client:
            shared_client = self._controller._shared_raw_client  # pylint: disable=import-outside-toplevel,protected-access
            if shared_client:
                _LOGGER.debug("%s [RAW] Closing shared client...", self.log_prefix)  # pragma: no mutate
                try:
                    await shared_client.close()
                except (asyncio.TimeoutError, OSError) as e:
                    _LOGGER.error("%s [RAW] Error closing shared client: %s", self.log_prefix, e)  # pragma: no mutate
                finally:
                    self._controller._shared_raw_client = None  # pylint: disable=import-outside-toplevel,protected-access

        _LOGGER.debug("%s [RAW] Connection resources closed.", self.log_prefix)  # pragma: no mutate
