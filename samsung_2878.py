# pylint: disable=broad-exception-caught,duplicate-code,import-outside-toplevel,line-too-long,no-else-return,too-few-public-methods,too-many-arguments,too-many-branches,too-many-instance-attributes,too-many-lines,too-many-locals,too-many-positional-arguments,too-many-statements
"""Support for Samsung AC devices using port 2878."""

import asyncio
import logging
import os
from pathlib import Path
import random
import re
import socket
import ssl
from collections.abc import Callable, Coroutine
from typing import Any

from homeassistant.helpers.json import json_dumps


from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.template import Template

from .connection import Connection, register_connection
from .const import (
    CONF_CERT,
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
    CONFIG_DEVICE_POWER_TEMPLATE,
    DEFAULT_CONF_CERT_FILE,
    GLOBAL_HTTP_TIMEOUT,
    PROTOCOL_2878_ATTR,
    PROTOCOL_2878_ATTR_ID,
    PROTOCOL_2878_ATTR_VALUE,
    PROTOCOL_2878_DEVICE_CONTROL,
    PROTOCOL_2878_DEVICE_STATE,
    PROTOCOL_2878_DPLUG,
    PROTOCOL_2878_DRC,
    PROTOCOL_2878_INVALIDATE,
    PROTOCOL_2878_POWER_ID,
    PROTOCOL_2878_RESPONSE,
    PROTOCOL_2878_STATUS,
    PROTOCOL_2878_STATUS_OK,
    PROTOCOL_2878_UPDATE,
    PROTOCOL_2878_VALUE_ON,
)
from .exceptions import AuthError, CannotConnect
from .helpers import (
    async_check_network_reachability,
    async_create_samsung_ssl_context,
    mask_sensitive_data,
    format_placeholders,
    safe_xml_to_dict,
)

_LOGGER = logging.getLogger(__name__)

# Precompiled regex for parsing XML attributes
ERROR_CODE_RE = re.compile(r'ErrorCode="(\d+)"')

CONNECTION_TYPE_S2878 = "samsung_2878"
CONF_DUID = "duid"

INITIAL_RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 300
RECONNECT_FACTOR = 2
COMMAND_TIMEOUT = 20.0
MAX_RECONNECT_RETRIES = 5


class ConnectionConfig:
    """Configuration data for Samsung 2878 connection."""

    def __init__(
        self,
        host: str | None,
        port: int | None,
        token: str | None,
        cert: str | None,
        duid: str | None,
    ) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.duid = duid
        self.cert = cert


@register_connection
class ConnectionSamsung2878(Connection):
    """Connection handler for Samsung devices on port 2878."""

    def __init__(
        self,
        hass_config: dict[str, Any],
        logger: logging.Logger,
        hass: Any | None = None,
    ) -> None:
        super().__init__(hass_config, logger, hass=hass)
        self._params: dict[str, Any] = {}
        self._connection_init_template: Template | None = None
        self._cfg = ConnectionConfig(None, None, None, None, None)
        self._device_status: dict[str, Any] = {}

        # Padding socket timeout as sockets tend to be slower to respond than HTTP.
        self._socket_timeout = float(GLOBAL_HTTP_TIMEOUT) + 10.0
        self._controller: Any = None

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None  # Task for reading from the socket
        self._close_lock = asyncio.Lock()  # To serialize _close_connection calls
        self._cmd_queue: asyncio.Queue = asyncio.Queue()
        self._manager_task: asyncio.Task | None = (
            None  # Main task that manages the persistent connection
        )
        self._update_callback: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None
        ) = None
        self._pending_future: asyncio.Future | None = (
            None  # Future for the command currently being processed
        )

        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._reconnect_retries = 0
        self._is_available = (
            True  # Used for stateful logging to report connection status changes
        )
        self._is_ready = asyncio.Event()  # Event to signal when connection is ready

        self._last_successful_config: dict[str, Any] | None = None
        self._ssl_context_cache: dict[tuple[str | None, str, Any], ssl.SSLContext] = {}
        self._initial_connection_done = False  # To prevent double poll at startup
        self._background_tasks: set[asyncio.Task] = (
            set()
        )  # Track fire-and-forget tasks for clean shutdown
        self._persistent_offline_err_logged = False

        self.update_configuration_from_hass(hass_config)
        self._power_template: Template | None = None

    def set_controller_ref(self, controller: Any) -> None:
        """Set the controller reference."""
        self._controller = controller

    @property
    def log_prefix(self) -> str:
        """Return the logging prefix for this connection."""
        if self._controller and self._controller.unique_id:
            return self._controller.log_prefix
        if self._cfg and self._cfg.duid:
            return f"[{self._cfg.duid[-6:]}]"
        return "[NO_ID]"

    @property
    def is_async_native(self) -> bool:
        """Indicates if the connection is native asynchronous (aiohttp/2878)."""
        return True

    @property
    def is_push_supported(self) -> bool:
        """Return True indicating this connection type supports push updates."""
        return True

    def set_update_callback(
        self, callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """Set the callback for device state updates."""
        self._update_callback = callback

    def _ensure_callback_linked(self) -> None:
        """Link the push update callback via the controller to maintain IoC."""
        if not self._update_callback and self._controller:
            push_callback = getattr(self._controller, "on_push_update_callback", None)
            if push_callback:
                self.set_update_callback(push_callback)
                _LOGGER.debug(
                    "%s Auto-linked push update callback from controller.",
                    self.log_prefix,
                )  # pragma: no mutate

    def start_listening(self) -> None:
        """Start the background connection manager."""
        self._ensure_callback_linked()
        if self._manager_task is None or self._manager_task.done():
            _LOGGER.info("%s Starting connection manager", self.log_prefix)  # pragma: no mutate
            self._reconnect_retries = 0
            self._manager_task = asyncio.create_task(self._connection_manager())

    def _track_task(self, coro: Coroutine) -> asyncio.Task:
        """Create a tracked background task that auto-removes itself on completion."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def stop_listening(self) -> None:
        """Stop the connection manager and close the connection."""
        if self._manager_task:
            _LOGGER.info("%s Stopping connection manager", self.log_prefix)  # pragma: no mutate
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

    def update_configuration_from_hass(
        self, hass_config: dict[str, Any] | None
    ) -> None:
        """Update connection parameters from Home Assistant config."""
        if hass_config is not None:
            # Clear the SSL context cache if configuration changes, as cert path might have changed.
            self._ssl_context_cache.clear()

            duid = re.sub(":", "", mac) if (mac := hass_config.get(CONF_MAC)) else None

            if (cert_file := hass_config.get(CONF_CERT) or "") and not (
                "/" in cert_file or "\\" in cert_file
            ):
                log_prefix = (
                    f"[{duid[-6:]}]"
                    if self.log_prefix == "[NO_ID]" and duid
                    else self.log_prefix
                )
                _LOGGER.debug(
                    "%s Resolving relative certificate path for 2878 connection: %s",
                    log_prefix,
                    cert_file,
                )  # pragma: no mutate
                cert_file = str(Path(__file__).parent / cert_file)

            raw_token, raw_ip, device_id = (
                hass_config.get(CONF_TOKEN),
                hass_config.get(CONF_IP_ADDRESS),
                hass_config.get("device_id"),
            )
            token = format_placeholders(raw_token, raw_token, raw_ip, device_id, mac)

            self._cfg = ConnectionConfig(
                host=raw_ip,
                port=hass_config.get(CONF_PORT, 2878),
                token=token,
                cert=cert_file,
                duid=duid,
            )
            # Ensure DUID and token are available for templates.
            self._params.update(
                {
                    CONF_DUID: self._cfg.duid,
                    CONF_TOKEN: self._cfg.token,
                    CONF_IP_ADDRESS: self._cfg.host,
                }
            )

        # Load the preferred connection settings if they were saved during pairing
        self._last_successful_config = None

        # Restore last successful SSL config from ConfigEntry data across restarts
        stored = self._config.get("_ssl_config_2878")
        if stored:
            self._last_successful_config = stored
            _LOGGER.debug(
                "%s Restored last successful SSL config from ConfigEntry data in init: cert=%s, cipher=%s",
                self.log_prefix,
                stored.get("cert"),
                stored.get("cipher_name"),
            )  # pragma: no mutate

        if not self._last_successful_config and hass_config:
            pref_conn = hass_config.get("preferred_connection")
            if isinstance(pref_conn, dict):
                self._last_successful_config = pref_conn.copy()

        if self._last_successful_config:
            # Resolve relative path in preferred config if needed, to match the runtime behavior
            pref_cert = self._last_successful_config.get("cert")
            if pref_cert and not os.path.dirname(pref_cert):
                self._last_successful_config["cert"] = str(
                    Path(os.path.dirname(__file__)) / pref_cert
                )

    def load_from_yaml(self, node: dict[str, Any] | None, connection_base: Any) -> bool:
        if connection_base:
            self._params.update(
                connection_base._params.copy()  # pylint: disable=protected-access
            )
        if not node:
            return False

        params_node = node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {})
        if CONFIG_DEVICE_CONNECTION_TEMPLATE in params_node:
            self._connection_init_template = Template(
                params_node[CONFIG_DEVICE_CONNECTION_TEMPLATE], self._hass
            )
        elif not connection_base:
            _LOGGER.error(
                "%s Missing 'connection_template' in YAML configuration",
                self.log_prefix,
            )  # pragma: no mutate
            return False

        if CONFIG_DEVICE_POWER_TEMPLATE in params_node:
            self._power_template = Template(
                params_node[CONFIG_DEVICE_POWER_TEMPLATE], self._hass
            )

        if not connection_base:
            # These are critical and should have been provided during setup.
            if not self._cfg.host:
                _LOGGER.error("%s Missing 'host' parameter", self.log_prefix)  # pragma: no mutate
                return False
            if not self._cfg.token:
                _LOGGER.error("%s Missing 'token' parameter", self.log_prefix)  # pragma: no mutate
                return False
            if not self._cfg.duid:
                _LOGGER.error("%s Missing 'mac' parameter", self.log_prefix)  # pragma: no mutate
                return False

        self._params.update(params_node)

        # Runtime config from HA overrides default YAML placeholders
        if hasattr(self, "_cfg") and self._cfg:
            if self._cfg.token:
                self._params[CONF_TOKEN] = self._cfg.token
            if self._cfg.host:
                self._params[CONF_IP_ADDRESS] = self._cfg.host
            if self._cfg.duid:
                self._params[CONF_DUID] = self._cfg.duid

        return True

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Check if this connection type matches the given type string."""
        return type_str == CONNECTION_TYPE_S2878

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the 2878 connection."""
        diag: dict[str, Any] = {
            "is_connected": self._is_ready.is_set(),
            "reconnect_retries": self._reconnect_retries,
            "is_available": self._is_available,
        }

        if self._last_successful_config:
            safe_config = {}
            if (
                "cert" in self._last_successful_config
                and self._last_successful_config["cert"]
            ):
                # Expose only the filename, not the full path, for privacy/security
                safe_config["cert_filename"] = Path(
                    self._last_successful_config["cert"]
                ).name
            if "cipher_name" in self._last_successful_config:
                safe_config["cipher_name"] = self._last_successful_config["cipher_name"]
            diag["last_successful_config"] = safe_config
        else:
            diag["last_successful_config"] = None

        return diag

    def create_updated(
        self, yaml_node: dict[str, Any] | None
    ) -> "ConnectionSamsung2878":
        self.load_from_yaml(yaml_node, self)
        return self

    async def _post_connect_status_request(self) -> None:
        """Queues a request for the full device status after a connection is established."""
        # Give the system a moment to be ready for a new command.
        try:
            await asyncio.sleep(1)

            command = f'<Request Type="{PROTOCOL_2878_DEVICE_STATE}" DUID="{self._cfg.duid}"></Request>\n'
            _LOGGER.debug(
                "%s Queuing post-reconnection status request", self.log_prefix
            )  # pragma: no mutate

            future = asyncio.get_running_loop().create_future()
            await self._cmd_queue.put((command, future))

            # Wait for the command to be processed
            async with asyncio.timeout(COMMAND_TIMEOUT):
                await future

            _LOGGER.debug(
                "%s Post-reconnection status request was processed successfully",
                self.log_prefix,
            )  # pragma: no mutate

        except TimeoutError:
            _LOGGER.warning(
                "%s Post-reconnection status request timed out", self.log_prefix
            )  # pragma: no mutate
            # If the future that timed out is still the pending one, clear it to unblock the manager.
            if self._pending_future and self._pending_future == future:
                self._pending_future = None  # pragma: no mutate
        except Exception as e:
            _LOGGER.error(
                "%s Failed to queue post-reconnection status request: %s",
                self.log_prefix,
                e,
                exc_info=True,
            )  # pragma: no mutate

    async def _close_connection(self) -> None:
        # Use a lock to ensure we don't close the connection multiple times concurrently
        if self._close_lock.locked():
            _LOGGER.debug(
                "%s Connection close already in progress, waiting...", self.log_prefix
            )  # pragma: no mutate

        async with self._close_lock:
            # Check if already closed to avoid redundant work and logs
            if self._writer is None and self._read_task is None:
                return

            self._is_ready.clear()

            # Cancel pending read task to unblock manager
            if self._read_task and not self._read_task.done():
                _LOGGER.debug("%s Cancelling pending read task", self.log_prefix)  # pragma: no mutate
                self._read_task.cancel()
                try:
                    await self._read_task
                except asyncio.CancelledError:
                    pass
            self._read_task = None  # pragma: no mutate

            if self._writer:
                _LOGGER.debug("%s Closing connection", self.log_prefix)  # pragma: no mutate
                try:
                    self._writer.close()
                    try:
                        async with asyncio.timeout(2.0):
                            await self._writer.wait_closed()
                    except TimeoutError:
                        _LOGGER.warning(
                            "%s Timeout waiting for connection close, forcing reset",
                            self.log_prefix,
                        )  # pragma: no mutate
                except (
                    ConnectionResetError,
                    ssl.SSLError,
                    asyncio.CancelledError,
                    OSError,
                ) as e:
                    _LOGGER.debug(
                        "%s Ignoring error during connection close: %s",
                        self.log_prefix,
                        e,
                    )  # pragma: no mutate
            self._writer = self._reader = None

    async def _establish_connection_and_handshake(self) -> bool:
        await self._close_connection()
        cfg = self._cfg
        initial_msg = None  # pragma: no mutate

        # Define the cipher suites.
        # Note: We will reorder these dynamically based on the strategy.
        suite_a = ("HIGH:!DH:!aNULL:@SECLEVEL=0", "Cipher Suite A (High Security No-DH)")  # pragma: no mutate
        suite_b = ("ALL:!DH:!aNULL:@SECLEVEL=0", "Cipher Suite B (Legacy RSA - No DH)")  # pragma: no mutate
        suite_c = ("ALL:!aNULL:@SECLEVEL=0", "Cipher Suite C (Legacy Allow Weak DH)")  # pragma: no mutate
        suite_d = ("ALL:@SECLEVEL=0", "Cipher Suite D (Anonymous / All Supported)")  # pragma: no mutate

        default_ciphers = [suite_a, suite_b, suite_c, suite_d]  # pragma: no mutate
        # For No-Cert strategies, we prioritize Suite D (allows Anonymous) because !aNULL (A/B/C) forces server auth.
        no_cert_ciphers = [suite_d, suite_a, suite_b, suite_c]  # pragma: no mutate

        default_cert_path = str(
            Path(__file__).parent / DEFAULT_CONF_CERT_FILE
        )
        strategies = (
            [
                { "cert": user_cert, "name": "User Cert (Strict Verify)", "verify_mode": ssl.CERT_REQUIRED,},  # pragma: no mutate
                { "cert": user_cert, "name": "User Cert (No Verify)", "verify_mode": ssl.CERT_NONE,},  # pragma: no mutate
                { "cert": None, "name": "No Certificate (Fallback)", "verify_mode": ssl.CERT_NONE,},  # pragma: no mutate
            ]
            if (user_cert := cfg.cert)
            else [
                { "cert": None, "name": "No Certificate (Default)", "verify_mode": ssl.CERT_NONE,},  # pragma: no mutate
                { "cert": default_cert_path, "name": "Default Certificate (Fallback)", "verify_mode": ssl.CERT_NONE,},  # pragma: no mutate
            ]
        )

        all_attempts = [
            {**strategy, "cipher_config": cipher_cfg, "strategy_name": strategy["name"]}
            for strategy in strategies
            for cipher_cfg in (
                no_cert_ciphers if strategy["cert"] is None else default_ciphers
            )
        ]

        if self._last_successful_config:
            pref_cert = self._last_successful_config.get("cert")  # pragma: no mutate
            pref_cipher = self._last_successful_config.get("cipher_name") # pragma: no mutate
            pref_verify = self._last_successful_config.get("verify_mode") # pragma: no mutate

            matching = [
                a
                for a in all_attempts
                if a["cert"] == pref_cert
                and a.get("verify_mode") == pref_verify
                and (not pref_cipher or a["cipher_config"][1] == pref_cipher)
            ]
            if matching:
                all_attempts = matching

        connection_successful = False  # pragma: no mutate
        last_error: Exception | None = None  # pragma: no mutate

        for attempt in all_attempts:
            cert_path = attempt["cert"]
            ciphers, cipher_name = attempt["cipher_config"]
            verify_mode = attempt["verify_mode"]
            strategy_name = attempt["strategy_name"]

            try:
                # --- SSL Context Caching Logic ---
                cache_key = (
                    cert_path,
                    ciphers,
                    verify_mode,
                )  # The key must include all SSL parameters
                ssl_context = self._ssl_context_cache.get(cache_key)

                if not ssl_context:
                    ssl_context = await async_create_samsung_ssl_context(
                        cert_path=cert_path, ciphers=ciphers, verify_mode=verify_mode
                    )
                    self._ssl_context_cache[cache_key] = ssl_context

                # Use raw socket with TCP KEEPALIVE
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setblocking(False)

                # Enable TCP Keep-Alive
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

                # Set Keep-Alive parameters (platforms may vary, these are for Linux/Windows common)
                if hasattr(socket, "TCP_KEEPIDLE"):
                    sock.setsockopt(
                        socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60
                    )  # Send probe after 60s idle
                if hasattr(socket, "TCP_KEEPINTVL"):
                    sock.setsockopt(
                        socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10
                    )  # 10s between probes
                if hasattr(socket, "TCP_KEEPCNT"):
                    sock.setsockopt(
                        socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3
                    )  # 3 failures = dead

                try:
                    async with asyncio.timeout(self._socket_timeout):
                        await asyncio.get_running_loop().sock_connect(
                            sock, (cfg.host, cfg.port)
                        )
                except Exception as connect_exc:
                    sock.close()
                    raise connect_exc

                # Wrap the socket with SSL
                async with asyncio.timeout(self._socket_timeout):
                    self._reader, self._writer = await asyncio.open_connection(
                        sock=sock, ssl=ssl_context, server_hostname=cfg.host
                    )

                # Log connection details on success
                ssl_object = self._writer.get_extra_info("ssl_object")
                if ssl_object:
                    cipher = ssl_object.cipher()
                    negotiated_tls = ssl_object.version() or "Unknown"
                    _LOGGER.info(
                        "%s SSL connection established. Protocol: %s, Cipher: %s, Verify: %s, Negotiated TLS: %s",
                        self.log_prefix,
                        cipher[1],
                        cipher[0],
                        verify_mode,
                        negotiated_tls,
                    )  # pragma: no mutate

                # Memorize the successful configuration for future reconnections
                self._last_successful_config = {
                    "cert": cert_path,
                    "cipher_name": cipher_name,
                    "verify_mode": verify_mode,
                }

                # Persist to ConfigEntry data so it survives HA restarts
                if hasattr(self._controller, "on_ssl_config_updated") and self._controller.on_ssl_config_updated:
                    self._controller.on_ssl_config_updated(self._last_successful_config)

                connection_successful = True
                break  # Exit the loop on successful connection.

            except (ConnectionRefusedError, TimeoutError, OSError, ssl.SSLError) as e:
                # This is an expected failure when the device is offline or the port is wrong.
                last_error = e
                await self._close_connection()
                continue
            except Exception as e:
                _LOGGER.warning(
                    "%s Connection with '%s' / '%s' failed unexpectedly: %s. Trying next.",
                    self.log_prefix,
                    strategy_name,
                    cipher_name,
                    e,
                )  # pragma: no mutate
                last_error = e
                await self._close_connection()
                continue

        if not connection_successful:
            _LOGGER.debug(
                "%s Could not connect to device (likely offline): %s",
                self.log_prefix,
                last_error,
            )  # pragma: no mutate
            return False

        # If we are here, one of the attempts was successful at the socket level
        # Now, proceed with the application-level handshake
        if (
            not initial_msg
        ):  # Read initial message if not already read during plain TCP check
            initial_msg = await self._read_full_response(timeout=self._socket_timeout)  # pragma: no mutate

        if initial_msg:
            # Attempt to parse the initial message to see if it's an update or response
            _, is_update, parsed_data = await self._parse_and_update_state(initial_msg)
            if parsed_data:
                self._device_status.update(parsed_data)
                self._ensure_callback_linked()
                if is_update and self._update_callback:
                    _LOGGER.debug(
                        "%s Initial message was an update, calling update callback",
                        self.log_prefix,
                    )  # pragma: no mutate
                    self._track_task(self._update_callback(parsed_data))

        if not initial_msg or (
            PROTOCOL_2878_DPLUG not in initial_msg
            and PROTOCOL_2878_DRC not in initial_msg
            and PROTOCOL_2878_INVALIDATE not in initial_msg
        ):
            _LOGGER.warning(
                "%s Handshake failed: Did not receive expected initial message (DPLUG-1.6 or DRC-1.00 or InvalidateAccount). Got: %s",
                self.log_prefix,
                initial_msg,
            )  # pragma: no mutate
            raise CannotConnect(
                "Handshake failed: Did not receive expected initial message"
            )

        if not self._connection_init_template:
            _LOGGER.error(
                "%s Handshake failed: Connection initialization template is missing.",
                self.log_prefix,
            )  # pragma: no mutate
            raise CannotConnect(
                "Handshake failed: Connection initialization template is missing."
            )

        try:
            auth_command = (
                self._connection_init_template.async_render(self._params) + "\n"
            )
        except Exception as err:
            _LOGGER.error(
                "%s Error rendering init template: %s",
                self.log_prefix,
                err,
                exc_info=True,
            )  # pragma: no mutate
            raise CannotConnect(f"Template rendering failed: {err}") from err  # pragma: no mutate
        await self._write_data(auth_command)

        auth_response = await self._read_full_response(timeout=self._socket_timeout)
        if not auth_response or PROTOCOL_2878_STATUS_OK not in auth_response:
            # Only process the error response if it's not None
            if auth_response:
                # Handle InvalidateAccount (Session Collision) gracefully
                if PROTOCOL_2878_INVALIDATE in auth_response:
                    _LOGGER.info(
                        "%s Device reported session collision (InvalidateAccount). Waiting for old session to timeout...",
                        self.log_prefix,
                    )  # pragma: no mutate
                    return False  # Trigger retry logic

                if 'ErrorCode="301"' in auth_response:
                    _LOGGER.error(
                        "%s Authentication failed (ErrorCode 301). The device was likely turned off. Please ensure the device is ON before pairing",
                        self.log_prefix,
                    )  # pragma: no mutate
                    raise AuthError(
                        "Authentication failed: Device was turned off (301)"
                    )

                error_code_match = ERROR_CODE_RE.search(auth_response)
                error_code = (
                    error_code_match.group(1) if error_code_match else "Unknown"
                )
                _LOGGER.error(
                    "%s Authentication failed with ErrorCode %s. Got: %s",
                    self.log_prefix,
                    error_code,
                    auth_response,
                )  # pragma: no mutate
                raise AuthError("Authentication failed")
            raise AuthError("Authentication failed: No response from device")

        _LOGGER.info("%s Connection ready", self.log_prefix)  # pragma: no mutate
        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._reconnect_retries = 0
        self._is_ready.set()  # Signal that we are ready for commands
        _LOGGER.debug("%s Connection is ready, _is_ready event set.", self.log_prefix)  # pragma: no mutate

        # Stateful logging: Log when connection is re-established
        if not self._is_available:
            _LOGGER.info("%s Connection re-established", self.log_prefix)  # pragma: no mutate
            self._is_available = True
            self._persistent_offline_err_logged = False
            try:
                # Clear any pending repair issues since the device came back online
                if self._controller and getattr(self._controller, "hass", None):
                    from .const import ISSUE_CONNECTION_FAILED

                    async_delete_issue(
                        self._controller.hass,
                        "climate_ip",
                        f"{ISSUE_CONNECTION_FAILED}_{self._cfg.host}",
                    )
            except Exception as e:
                _LOGGER.debug("%s Could not clear repair issue: %s", self.log_prefix, e)  # pragma: no mutate

        # Request a full status update only on reconnections, not on the very first connection.
        if self._initial_connection_done:
            self._track_task(self._post_connect_status_request())
            # Proactively refresh HA state after reconnection
            if hasattr(self._controller, "request_refresh_callback") and self._controller.request_refresh_callback:
                _LOGGER.info(
                    "%s Requesting immediate coordinator refresh after reconnection.",
                    self.log_prefix,
                )  # pragma: no mutate
                self._track_task(self._controller.request_refresh_callback())

        self._initial_connection_done = True

        return True

    async def _read_full_response(self, timeout: float = 10.0) -> str | None:
        if not self._reader or self._reader.at_eof():
            return None
        try:
            buffer = b""  # pragma: no mutate
            async with asyncio.timeout(timeout):
                while True:
                    chunk = await self._reader.read(4096)
                    if not chunk:
                        await self._close_connection()
                        return (
                            buffer.decode("utf-8", errors="ignore") if buffer else None
                        )

                    buffer += chunk
                    decoded_buffer = buffer.decode("utf-8", errors="ignore").strip()
                    if (
                        "</Response>" in decoded_buffer
                        or "</Update>" in decoded_buffer
                        or PROTOCOL_2878_DPLUG in decoded_buffer
                        or decoded_buffer.endswith("/>")
                    ):
                        return decoded_buffer

        except (TimeoutError, asyncio.IncompleteReadError):
            _LOGGER.debug(
                "%s No full response received in %s seconds",
                self.log_prefix,
                timeout,
                exc_info=True,
            )  # pragma: no mutate
            return buffer.decode("utf-8", errors="ignore") if buffer else None
        except (TimeoutError, OSError) as e:
            _LOGGER.error("%s Error during read: %s", self.log_prefix, e, exc_info=True)  # pragma: no mutate
            await self._close_connection()
            return None

    async def _write_data(self, data_str: str) -> bool:
        if not self._writer or self._writer.is_closing():
            _LOGGER.error("%s Write failed: writer is not available", self.log_prefix)  # pragma: no mutate
            raise CannotConnect("Connection is not available for writing")
        try:
            self._writer.write(data_str.encode("utf-8"))
            async with asyncio.timeout(5.0):
                await self._writer.drain()
            return True
        except (TimeoutError, OSError) as e:
            _LOGGER.error(
                "%s Write failed: %s. Closing connection.", self.log_prefix, e
            )  # pragma: no mutate
            await self._close_connection()
            raise CannotConnect(f"Failed to write to connection: {e}") from e

    async def _parse_and_update_state(
        self, response_xml: str
    ) -> tuple[bool, bool, dict[str, Any] | None]:
        if not response_xml:
            return False, False, None  # pragma: no mutate

        if not (self._controller and self._controller.hass):
            raise RuntimeError(
                "Home Assistant instance is required for parsing XML securely"  # pragma: no mutate
            )  # pragma: no mutate

        is_update = False
        is_response = False
        parsed_data = {}

        # Discard any non-XML prefix like "DPLUG-1.6\n" or "DRC-1.00\n"
        xml_start_index = response_xml.find("<?xml")
        if xml_start_index == -1:
            return False, False, None  # pragma: no mutate

        xml_candidate_content = response_xml[xml_start_index:]

        # Split by '<?xml' to handle multiple XML documents concatenated in the buffer.
        doc_parts = xml_candidate_content.split("<?xml")

        for doc_part in doc_parts:
            if not doc_part.strip():
                continue  # Skip empty parts.

            # Reconstruct the full XML document string.
            # A valid XML fragment after '<?xml' should start with 'version="1.0"' or a root element tag.
            if doc_part.strip().startswith(
                'version="1.0"'
            ) or doc_part.strip().startswith("<"):
                full_doc = "<?xml" + doc_part
            else:
                # This doc_part is not a valid XML fragment (e.g., "DPLUG-1.6" without "version="1.0"")
                # Log it and skip, do not attempt to parse as XML.
                _LOGGER.debug(
                    "%s Skipping non-XML fragment after '<?xml': %s",
                    self.log_prefix,
                    doc_part.strip(),
                )  # pragma: no mutate
                continue
            try:

                # Derivar a Home Assistant executor para no congelar Asyncio (CPU-bound obj)
                data = await self._controller.hass.async_add_executor_job(
                    safe_xml_to_dict, full_doc
                )

                if PROTOCOL_2878_RESPONSE in data:
                    is_response = True
                    device_data = (
                        data[PROTOCOL_2878_RESPONSE]
                        .get(PROTOCOL_2878_DEVICE_STATE, {})
                        .get("Device")
                    )
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
                if (
                    is_update
                    and len(attrs) == 1
                    and attrs[0].get(PROTOCOL_2878_ATTR_ID) == PROTOCOL_2878_POWER_ID
                    and attrs[0].get(PROTOCOL_2878_ATTR_VALUE) == PROTOCOL_2878_VALUE_ON
                ):
                    if (
                        self._device_status.get(PROTOCOL_2878_POWER_ID)
                        == PROTOCOL_2878_VALUE_ON
                    ):
                        _LOGGER.debug(
                            "%s Ignoring redundant 'Power On' push update",
                            self.log_prefix,
                        )  # pragma: no mutate
                        return False, False, None  # pragma: no mutate

                for attr in attrs:
                    if (
                        PROTOCOL_2878_ATTR_ID in attr
                        and PROTOCOL_2878_ATTR_VALUE in attr
                    ):
                        parsed_data[attr[PROTOCOL_2878_ATTR_ID]] = attr[
                            PROTOCOL_2878_ATTR_VALUE
                        ]

            except Exception as e:
                _LOGGER.warning(
                    "%s Error parsing XML part: %s. Document: %s",
                    self.log_prefix,
                    e,
                    full_doc,
                )  # pragma: no mutate
        return is_response, is_update, parsed_data

    async def _process_command_queue(self, queue_task: asyncio.Task) -> None:
        """Process a command from the queue."""
        command, future = queue_task.result()
        self._pending_future = future
        # Store the command string on the future for debugging purposes using setattr.
        setattr(self._pending_future, "_command_debug", command)

        try:
            await self._write_data(command)
            # The future will be resolved when a corresponding response or update is received.
            _LOGGER.debug(
                "%s Command written, now waiting for response to resolve future",
                self.log_prefix,
            )  # pragma: no mutate
        except CannotConnect as e:
            if self._pending_future and not self._pending_future.done():
                self._pending_future.set_exception(e)
            self._pending_future = None  # pragma: no mutate

    async def _process_read_queue(self, buffer: bytes) -> bytes | None:
        """Process data received from the read task."""
        data = None
        is_cancelled = False
        try:
            if self._read_task:
                data = self._read_task.result()
        except asyncio.CancelledError:
            # Task was cancelled (likely by _close_connection), treat as connection closed
            data = None
            is_cancelled = True
        except Exception as e:
            _LOGGER.warning("%s Read task failed: %s", self.log_prefix, e)  # pragma: no mutate
            data = None

        if not data:
            if not is_cancelled:
                _LOGGER.debug("%s Connection closed by device (EOF)", self.log_prefix)  # pragma: no mutate
            else:
                _LOGGER.debug("%s Read task was cancelled", self.log_prefix)  # pragma: no mutate

            await self._close_connection()
            return None

        buffer += data
        # Process buffer to find full XML messages.
        while b"</Response>" in buffer or b"</Update>" in buffer or b"/>" in buffer: # pragma: no mutate
            end_tag = (
                b"</Response>"
                if b"</Response>" in buffer
                else (b"</Update>" if b"</Update>" in buffer else b"/>")
            )
            end_index = buffer.find(end_tag) + len(end_tag)
            message = buffer[:end_index]
            buffer = buffer[end_index:]

            xml_data = message.decode("utf-8", errors="ignore")
            _LOGGER.debug("%s Received message: %s", self.log_prefix, xml_data.strip())  # pragma: no mutate
            is_response, is_update, parsed_data = await self._parse_and_update_state(
                xml_data
            )

            # Update internal state for redundant 'Power On' logic.
            if parsed_data:
                self._device_status.update(parsed_data)

            # --- Command Resolution Logic ---
            # A command is considered complete if we receive:
            # 1. A direct 'DeviceControl Okay' response.
            # 2. Any other response or update that contains actual state data.

            is_control_okay = (
                is_response
                and PROTOCOL_2878_DEVICE_CONTROL in xml_data
                and PROTOCOL_2878_STATUS_OK in xml_data
            )
            is_polling_response = is_response and PROTOCOL_2878_DEVICE_STATE in xml_data

            # Initialize should_resolve to False to prevent UnboundLocalError
            should_resolve = False

            # If a pending command exists, check if this message resolves it.
            if self._pending_future and not self._pending_future.done():
                # If the pending command was a poll, only a DeviceState response can resolve it.
                # If it was a control command, any data update or a specific 'Okay' can resolve it.
                command_debug = getattr(self._pending_future, "_command_debug", "")
                is_poll_command = PROTOCOL_2878_DEVICE_STATE in command_debug

                should_resolve = bool(
                    (is_poll_command and is_polling_response)
                    or (
                        not is_poll_command
                        and (is_control_okay or (is_response and parsed_data))
                    )
                )

            if should_resolve and self._pending_future:
                if is_control_okay:
                    _LOGGER.debug(
                        "%s 'DeviceControl Okay' received, resolving pending command future",
                        self.log_prefix,
                    )  # pragma: no mutate
                else:
                    _LOGGER.debug(
                        "%s Response/Update with data received, resolving pending command future",
                        self.log_prefix,
                    )  # pragma: no mutate
                try:
                    if not self._pending_future.done():
                        self._pending_future.set_result(True)
                    self._pending_future = None  # pragma: no mutate
                except asyncio.InvalidStateError:
                    pass  # Future was already resolved.

            self._ensure_callback_linked()
            if parsed_data and (is_response or is_update) and self._update_callback:
                _LOGGER.debug(
                    "%s Calling update callback with data: %s",
                    self.log_prefix,
                    parsed_data,
                )  # pragma: no mutate
                self._track_task(self._update_callback(parsed_data))
            elif is_control_okay:
                # This is just an acknowledgment. The device will send a separate <Update> push.
                # We don't need to do anything here except acknowledge
                # that the command was successful so the UI doesn't hang. The future is already resolved.
                _LOGGER.debug(
                    "%s 'DeviceControl Okay' ack received. Waiting for subsequent push update.",
                    self.log_prefix,
                )  # pragma: no mutate

        return buffer

    def _check_and_create_repair_issue(self) -> None:
        """Create a repair issue if the device is persistently offline (3 retries)."""
        if (
            self._reconnect_retries == 3
            and self._controller
            and getattr(self._controller, "hass", None)
        ):
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
                        "name": getattr(self._cfg, "name", None) or self._cfg.host,
                    },
                )
            except Exception as e:
                _LOGGER.debug(
                    "%s Failed to create repair issue: %s", self.log_prefix, e
                )  # pragma: no mutate

    def _force_unavailability_if_needed(self, offline_type: str = "Network") -> None:  # pragma: no mutate
        """Force frontend unavailability if retries hit threshold."""
        if self._reconnect_retries == 2:
            if not getattr(self, "_persistent_offline_err_logged", False):
                if not self._initial_connection_done:
                    _LOGGER.debug(
                        "%s AC %s is persistently offline during initial setup.",
                        self.log_prefix,
                        offline_type,
                    )  # pragma: no mutate
                else:
                    _LOGGER.error(
                        "%s AC %s is persistently offline. Forcing frontend unavailability.",
                        self.log_prefix,
                        offline_type,
                    )  # pragma: no mutate
                    # Trigger the panic button callback to notify the coordinator immediately
                    if self._controller and hasattr(self._controller, "on_offline_callback") and self._controller.on_offline_callback:
                        self._controller.on_offline_callback("Host unreachable after multiple retry attempts.")
                self._persistent_offline_err_logged = True
            else:
                _LOGGER.debug(
                    "%s AC %s is persistently offline.", self.log_prefix, offline_type
                )  # pragma: no mutate

            if hasattr(self._controller, "on_connection_failed_callback") and self._controller.on_connection_failed_callback:
                self._controller.on_connection_failed_callback()

    async def handle_reconnection(self) -> bool:
        """Handle the reconnection process."""
        # Stateful logging: Log INFO only when the state changes from available to unavailable.
        if self._is_available:
            _LOGGER.info(
                "%s Connection lost. Attempting to reconnect...", self.log_prefix
            )  # pragma: no mutate
            self._is_available = False
        else:
            _LOGGER.debug(
                "%s Connection is down. Attempting to reconnect...", self.log_prefix
            )  # pragma: no mutate

        # Run network diagnostics on every reconnect attempt to aid troubleshooting.
        # Only attempt to open the TCP port if the ping succeeds to protect fragile ACs.
        network_reachable = True
        try:
            network_reachable = await async_check_network_reachability(
                self._cfg.host or "", self.log_prefix
            )
        except Exception as diag_err:
            _LOGGER.debug("%s Network diagnostic failed: %s", self.log_prefix, diag_err)  # pragma: no mutate

        try:
            # If the network is reachable, attempt handshake. Otherwise, skip to retry to protect device.
            handshake_success = False  # pragma: no mutate
            if network_reachable:
                handshake_success = await self._establish_connection_and_handshake()
            else:
                _LOGGER.debug(
                    "%s Skipping port connection attempt because ICMP ping failed.",
                    self.log_prefix,
                )  # pragma: no mutate

            # --- DUAL-SPEED BACKOFF LOGIC ---
            if not network_reachable:
                # 1. Network is fully down (router off, device unplugged, no wifi)
                # Wait a fixed 10 seconds. Do NOT increment exponential backoff to recover quickly.
                _LOGGER.debug(
                    "%s Host unreachable. Retrying ping in 10 seconds...",
                    self.log_prefix,
                )  # pragma: no mutate
                self._reconnect_retries += 1

                # Create a repair issue if the device is persistently offline
                self._check_and_create_repair_issue()

                # If we've failed 2 times on the ping, force unavailability in HA
                self._force_unavailability_if_needed("Network")  # pragma: no mutate

                self._ssl_context_cache.clear()
                await self._close_connection()

                # Use current exponential backoff but without jitter for network down
                delay_to_use = self._reconnect_delay
                _LOGGER.debug(
                    "%s Host unreachable. Retrying ping in %.1f seconds...",
                    self.log_prefix,
                    delay_to_use,
                )  # pragma: no mutate
                await asyncio.sleep(delay_to_use)

                # Increment exponential backoff delay for the next attempt
                self._reconnect_delay = min(
                    self._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
                )
                return False

            # If the handshake fails with a connection error, it returns False.
            if not handshake_success:
                # 2. Network UP but Port 2878 closed/crashing.
                _LOGGER.debug(
                    "%s Handshake returned False (or skipped). Proceeding to backoff logic.",
                    self.log_prefix,
                )  # pragma: no mutate
                self._reconnect_retries += 1

                # Create a repair issue if the device is persistently offline
                self._check_and_create_repair_issue()

                # If we've failed 2 times on the port, force unavailability in HA
                self._force_unavailability_if_needed("Service")  # pragma: no mutate

                jitter = random.uniform(0, self._reconnect_delay * 0.2)
                delay_with_jitter = self._reconnect_delay + jitter
                _LOGGER.debug(
                    "%s Port connection failed. Backing off for %.1f seconds...",
                    self.log_prefix,
                    delay_with_jitter,
                )  # pragma: no mutate
                self._ssl_context_cache.clear()  # Force fresh SSL context on retry
                await self._close_connection()
                await asyncio.sleep(delay_with_jitter)
                self._reconnect_delay = min(
                    self._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
                )
                return False

        except (CannotConnect, AuthError) as e:
            # 3. Network UP but an exception occurred during connection logic
            self._reconnect_retries += 1

            # Create a repair issue if the device is persistently offline
            self._check_and_create_repair_issue()
            # If reconnection fails, fail any pending command
            if self._pending_future and not self._pending_future.done():
                self._pending_future.set_exception(
                    CannotConnect(f"Connection lost and reconnect failed: {e}")  # pragma: no mutate
                )
                self._pending_future = None  # pragma: no mutate

            jitter = random.uniform(0, self._reconnect_delay * 0.2)
            delay_with_jitter = self._reconnect_delay + jitter
            _LOGGER.debug(
                "%s Port connection error. Backing off for %.1f seconds...",
                self.log_prefix,
                delay_with_jitter,
            )  # pragma: no mutate
            self._ssl_context_cache.clear()  # Force fresh SSL context on retry
            await self._close_connection()
            await asyncio.sleep(delay_with_jitter)
            self._reconnect_delay = min(
                self._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
            )
            return False

        return True

    async def _connection_manager(self) -> None:
        buffer = b""  # pragma: no mutate
        self._read_task = None  # pragma: no mutate
        queue_task = None  # pragma: no mutate

        # Add a small delay at startup to allow the initial poll to establish the first connection
        await asyncio.sleep(2)  # pragma: no mutate

        try:
            while True:
                try:
                    if not self._writer or self._writer.is_closing():
                        if not await self.handle_reconnection():
                            continue

                    if not self._reader:
                        _LOGGER.warning(
                            "%s Reader object is missing, forcing reconnection.",
                            self.log_prefix,
                        )  # pragma: no mutate
                        await self._close_connection()
                        await self.handle_reconnection()
                        continue

                    # Ensure read task is running
                    if not self._read_task or self._read_task.done():
                        self._read_task = asyncio.create_task(self._reader.read(8192))

                    tasks = [self._read_task]

                    # Ensure queue listener is running if we are ready for commands
                    if not queue_task and not self._pending_future:
                        queue_task = asyncio.create_task(self._cmd_queue.get())

                    if queue_task:
                        tasks.append(queue_task)

                    done, pending = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )

                    # --- Process completed tasks ---
                    if queue_task and queue_task in done:
                        await self._process_command_queue(queue_task)
                        queue_task = None  # pragma: no mutate  # Reset to pick up next command

                    if self._read_task in done:
                        read_buffer = await self._process_read_queue(buffer)
                        if read_buffer is None:  # Connection closed
                            buffer = b""  # pragma: no mutate  # Reset buffer to prevent NoneType error on next iteration
                            continue
                        buffer = read_buffer

                    # Cleanup: Only cancel tasks that are NOT persistent
                    # We usually don't have other tasks here, but good practice.
                    # CRITICAL: Do NOT cancel queue_task if it's pending!
                    # for task in pending:
                    #     if task == self._read_task:  # pragma: no mutate
                    #         continue  # pragma: no mutate
                    #     if task == queue_task:  # pragma: no mutate
                    #         continue  # pragma: no mutate
                    #     task.cancel()

                except (TimeoutError, OSError) as e:
                    _LOGGER.error(
                        "%s Unhandled exception in connection manager: %s",
                        self.log_prefix,
                        e,
                        exc_info=True,
                    )  # pragma: no mutate
                    if self._pending_future and not self._pending_future.done():
                        self._pending_future.set_exception(e)
                    self._pending_future = None  # pragma: no mutate
                    buffer = b""  # pragma: no mutate  # CRITICAL: Reset buffer on error to ensure clean state for next iteration
                    await self._close_connection()
                    jitter = random.uniform(0, self._reconnect_delay * 0.2)
                    await asyncio.sleep(self._reconnect_delay + jitter)
        finally:
            _LOGGER.debug("%s Connection manager exiting, cleaning up", self.log_prefix)  # pragma: no mutate
            for task in (self._read_task, queue_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            await self._close_connection()
    def execute(
        self, template: Any, value: Any, device_state: Any, device_id: str | None = None
    ) -> Any:
        """Synchronous execute not supported for async 2878 connection."""
        raise NotImplementedError(
            "ConnectionSamsung2878 is async-native. Use async_execute."
        )  # pragma: no mutate

    async def async_execute(
        self,
        method: str | None,
        url: str | None,
        data: str | None,
        headers: dict[str, str] | None,
        device_state: dict[str, Any] | None = None,
        _is_probe: bool = False,  # pragma: no mutate
        _is_poll: bool = False,  # pragma: no mutate
    ) -> tuple[str | None, dict[str, str] | None]:
        """Executes an asynchronous command (raw XML for 2878)."""
        self._ensure_callback_linked()

        # --- AUTO-START LISTENER IF STOPPED ---
        if self._manager_task is None or self._manager_task.done():
            _LOGGER.debug(
                "%s Connection manager not running during execute. Starting it now.",
                self.log_prefix,
            )  # pragma: no mutate
            self.start_listening()

        # If the connection is not ready and we haven't repeatedly failed, give it some extra margin
        # (especially useful at startup) so the connection_manager completes the SSL handshake before trying to send XML.
        if not self._is_ready.is_set() and self._reconnect_retries == 0:
            _LOGGER.debug(
                "%s Waiting up to %s seconds for background connection handshake...",
                self.log_prefix,
                COMMAND_TIMEOUT,
            )  # pragma: no mutate

        # Fast-fail: If not ready and already failed, fail fast to prevent hanging Home Assistant.
        if not self._is_ready.is_set() and self._reconnect_retries > 0:
             _LOGGER.debug(
                 "%s Connection is in retry backoff. Fast-failing command execution.",
                 self.log_prefix,
             )  # pragma: no mutate
             raise CannotConnect("Client not ready")

        # Wait for the connection to be ready before proceeding.
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                await self._is_ready.wait()
        except TimeoutError as e:
            _LOGGER.warning(
                "%s Timed out waiting for connection to be ready (device is likely offline).",
                self.log_prefix,
            )  # pragma: no mutate
            raise CannotConnect("Timeout waiting for connection") from e

        command = None
        if data:
            command = data.strip() + "\n"
        elif _is_poll:
            command = f'<Request Type="{PROTOCOL_2878_DEVICE_STATE}" DUID="{self._cfg.duid}"></Request>\n'

        if not command:
            return None, None

        async with self._lock:
            _LOGGER.debug(
                "%s Queuing async command: %s",
                self.log_prefix,
                mask_sensitive_data(command.strip().replace("\n", "")),
            )  # pragma: no mutate

            future = asyncio.get_running_loop().create_future()
            await self._cmd_queue.put((command, future))

            try:
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    await future
                _LOGGER.debug("%s Command executed successfully", self.log_prefix)  # pragma: no mutate

            except TimeoutError as e:
                _LOGGER.warning(
                    "%s Command timed out: %s",
                    self.log_prefix,
                    mask_sensitive_data(command.strip().replace("\n", "")),
                )  # pragma: no mutate

                # CRITICAL: If the command times out, we MUST clear the pending_future
                # so the manager can accept new commands and not get stuck.
                if self._pending_future and self._pending_future == future:
                    _LOGGER.debug(
                        "%s Command timed out. Clearing pending future to unblock manager.",
                        self.log_prefix,
                    )  # pragma: no mutate
                    self._pending_future = None  # pragma: no mutate

                # CRITICAL FIX: Always force connection close on timeout.
                # If a command timed out (20s), the connection is effectively dead or hung.
                # We remove the 'is_polling_request' check to ensure we always recover.
                _LOGGER.debug(
                    "%s Command timed out. Forcing connection close to trigger reconnect.",
                    self.log_prefix,
                )  # pragma: no mutate
                asyncio.create_task(self._close_connection())

                raise CannotConnect("Command timed out") from e
            except Exception as e:
                _LOGGER.error(
                    "%s Command failed with exception: %s", self.log_prefix, e
                )  # pragma: no mutate
                raise

        # Synchronously return the JSON state we just received.
        # This allows the Coordinator that invoked this method to get the information
        # instantly, building the entities with fresh data instead of "Unknown".
        return json_dumps(self._device_status), {}
