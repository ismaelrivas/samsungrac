# pylint: disable=broad-exception-caught,duplicate-code,import-outside-toplevel,line-too-long,no-else-return,too-few-public-methods,too-many-arguments,too-many-branches,too-many-instance-attributes,too-many-lines,too-many-locals,too-many-positional-arguments,too-many-statements,hass-logger-period
# ruff: noqa: D102, D107, SLF001, SIM105, G201, TRY300, BLE001
"""Support for Samsung AC devices using port 2878."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import random
import re
import socket
import ssl
from typing import Any

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_dumps
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
    format_placeholders,
    get_last_network_diagnostic,
    mask_sensitive_data,
    safe_xml_to_dict,
)

_LOGGER = logging.getLogger(__name__)

# Precompiled regex for parsing XML attributes
ERROR_CODE_RE = re.compile(r'ErrorCode="(\d+)"')

CONNECTION_TYPE_S2878 = "samsung_2878"
CONF_DUID = "duid"

INITIAL_RECONNECT_DELAY = 3
MAX_RECONNECT_DELAY = 60
RECONNECT_FACTOR = 2
COMMAND_TIMEOUT = 20.0
WRITE_TIMEOUT = 5.0  # pragma: no mutate
MAX_RECONNECT_RETRIES = 5

# --- Wire protocol framing ---
TAG_XML_DECL = "<?xml"
TAG_DEVICE = "Device"
TAG_SELF_CLOSE = "/>"
ERROR_CODE_301 = 'ErrorCode="301"'
# Text markers that terminate a handshake/auth reply read by _read_full_response.
RESPONSE_END_MARKERS = ("</Response>", "</Update>", PROTOCOL_2878_DPLUG)
# Byte end tags used to frame the push stream, in priority order.
STREAM_END_TAGS = (b"</Response>", b"</Update>", b"/>")
# Valid starts of an XML fragment after splitting on '<?xml'.
XML_FRAGMENT_STARTS = ('version="1.0"', "<")
# Any of these in the greeting means the device accepted the TLS session.
HANDSHAKE_MARKERS = (PROTOCOL_2878_DPLUG, PROTOCOL_2878_DRC, PROTOCOL_2878_INVALIDATE)
ATTR_COMMAND_DEBUG = "_command_debug"
OFFLINE_PANIC_MSG = "Host unreachable after multiple retry attempts."

# --- Configuration / diagnostics keys ---
KEY_DEVICE_ID = "device_id"
KEY_SSL_CONFIG = "_ssl_config_2878"
KEY_PREFERRED_CONNECTION = "preferred_connection"
KEY_CERT = "cert"
KEY_CERT_FILENAME = "cert_filename"
KEY_CIPHER_NAME = "cipher_name"
KEY_VERIFY_MODE = "verify_mode"
KEY_IS_REACHABLE = "is_reachable"
KEY_STATUS = "status"
KEY_IS_CONNECTED = "is_connected"
KEY_RECONNECT_RETRIES = "reconnect_retries"
KEY_IS_AVAILABLE = "is_available"
KEY_LAST_SUCCESSFUL_CONFIG = "last_successful_config"
KEY_NETWORK_REACHABILITY = "network_reachability"
STATUS_ALIVE = "alive"
STATUS_UNREACHABLE = "unreachable_timeout"
DEFAULT_NETWORK_DIAGNOSTIC = {KEY_IS_REACHABLE: None, KEY_STATUS: "not_checked_yet"}
JITTER_RATIO = 0.2

# --- SSL negotiation strategies ---
SUITE_A = ("HIGH:!DH:!aNULL:@SECLEVEL=0", "Cipher Suite A (High Security No-DH)")
SUITE_B = ("ALL:!DH:!aNULL:@SECLEVEL=0", "Cipher Suite B (Legacy RSA - No DH)")
SUITE_C = ("ALL:!aNULL:@SECLEVEL=0", "Cipher Suite C (Legacy Allow Weak DH)")
SUITE_D = ("ALL:@SECLEVEL=0", "Cipher Suite D (Anonymous / All Supported)")
DEFAULT_CIPHERS = (SUITE_A, SUITE_B, SUITE_C, SUITE_D)
# For No-Cert strategies, prioritize Suite D (allows Anonymous) because !aNULL (A/B/C) forces server auth.
NO_CERT_CIPHERS = (SUITE_D, SUITE_A, SUITE_B, SUITE_C)
DEFAULT_CERT_PATH = str(Path(__file__).parent / DEFAULT_CONF_CERT_FILE)
USER_CERT = "<user_cert>"  # Placeholder replaced by the configured certificate.
type SSLStrategy = tuple[str | None, ssl.VerifyMode, str]  # (cert, verify, name)
type SSLAttempt = tuple[str | None, ssl.VerifyMode, tuple[str, str], str]
USER_CERT_STRATEGIES: tuple[SSLStrategy, ...] = (
    (USER_CERT, ssl.CERT_REQUIRED, "User Cert (Strict Verify)"),
    (USER_CERT, ssl.CERT_NONE, "User Cert (No Verify)"),
    (None, ssl.CERT_NONE, "No Certificate (Fallback)"),
)
DEFAULT_STRATEGIES: tuple[SSLStrategy, ...] = (
    (None, ssl.CERT_NONE, "No Certificate (Default)"),
    (DEFAULT_CERT_PATH, ssl.CERT_NONE, "Default Certificate (Fallback)"),
)
# TCP keep-alive: probe after 60s idle, 10s between probes, 3 failures = dead.
TCP_KEEPALIVE_OPTS = (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3))


@dataclass
class ConnectionConfig:
    """Configuration data for Samsung 2878 connection."""

    host: str | None = None
    port: int | None = None
    token: str | None = None
    cert: str | None = None
    duid: str | None = None


def _resolve_cert_path(cert: str) -> str:
    """Resolve a bare certificate filename relative to this integration folder."""
    if cert and not os.path.dirname(cert):
        _LOGGER.debug(
            "Resolving relative certificate path for 2878 connection: %s", cert
        )  # pragma: no mutate
        return str(Path(os.path.dirname(__file__)) / cert)
    return cert


def _create_keepalive_socket() -> socket.socket:
    """Create a non-blocking TCP socket with keep-alive probes enabled."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for option, value in TCP_KEEPALIVE_OPTS:
        if hasattr(socket, option):  # Platforms may vary
            sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, option), value)
    return sock


@register_connection
class ConnectionSamsung2878(Connection):
    """Connection handler for Samsung devices on port 2878."""

    # Per-instance state defaults (rebound on the instance when they change).
    _connection_init_template: Template | None = None
    _power_template: Template | None = None
    _reader: asyncio.StreamReader | None = None
    _writer: asyncio.StreamWriter | None = None
    _read_task: asyncio.Task[bytes] | None = None
    _manager_task: asyncio.Task[None] | None = None  # Manages the persistent link
    _update_callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = (
        None
    )
    _pending_future: asyncio.Future[bool] | None = None  # Command being processed
    _reconnect_delay: float = INITIAL_RECONNECT_DELAY
    _reconnect_retries = 0
    _is_available = True  # Used for stateful logging of connection status changes
    _initial_connection_done = False  # To prevent double poll at startup
    _persistent_offline_err_logged = False
    _last_successful_config: dict[str, Any] | None = None
    _last_icmp_diagnostic: dict[str, Any] | None = None

    def __init__(
        self,
        hass_config: dict[str, Any],
        logger: logging.Logger,
        hass: HomeAssistant | None = None,
    ) -> None:
        super().__init__(hass_config, logger, hass=hass)
        self._cfg = ConnectionConfig()
        self._device_status: dict[str, Any] = {}
        # Padding socket timeout as sockets tend to be slower to respond than HTTP.
        self._socket_timeout = float(GLOBAL_HTTP_TIMEOUT) + 10.0
        self._close_lock = asyncio.Lock()  # To serialize _close_connection calls
        self._cmd_queue: asyncio.Queue[tuple[str, asyncio.Future[bool]]] = (
            asyncio.Queue()
        )
        self._is_ready = asyncio.Event()  # Event to signal when connection is ready
        self._ssl_context_cache: dict[tuple[str | None, str, Any], ssl.SSLContext] = {}
        # Track fire-and-forget tasks for clean shutdown
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self.update_configuration_from_hass(hass_config)

    def set_controller_ref(self, controller: Any) -> None:
        """Set the controller reference."""
        self._controller = controller
        if controller:
            self._hass = controller.hass

    @property
    def log_prefix(self) -> str:
        """Return the logging prefix for this connection."""
        if self._controller and self._controller.unique_id:
            prefix: str = self._controller.log_prefix
            return prefix
        if self._cfg and self._cfg.duid:
            return f"[{self._cfg.duid[-6:]}]"
        return "[NO_ID]"

    @property
    def is_async_native(self) -> bool:
        """Indicates if the connection is native asynchronous (aiohttp/2878)."""
        return True

    @property
    def is_available(self) -> bool:
        """Return True indicating if this connection is currently connected and available."""
        return self._is_available

    @property
    def is_push_supported(self) -> bool:
        """Return True indicating this connection type supports push updates."""
        return True

    @property
    def _poll_command(self) -> str:
        """Return the full device status request."""
        return f'<Request Type="{PROTOCOL_2878_DEVICE_STATE}" DUID="{self._cfg.duid}"></Request>\n'

    def set_update_callback(
        self, callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """Set the callback for device state updates."""
        self._update_callback = callback

    def _ensure_callback_linked(self) -> None:
        """Link the push update callback via the controller to maintain IoC."""
        if not self._update_callback and self._controller:
            if self._controller.on_push_update_callback:
                self.set_update_callback(self._controller.on_push_update_callback)
                _LOGGER.debug(
                    "%s Auto-linked push update callback from controller.",
                    self.log_prefix,
                )  # pragma: no mutate

    def start_listening(self) -> None:
        """Start the background connection manager."""
        self._ensure_callback_linked()
        if self._manager_task is None or self._manager_task.done():
            _LOGGER.debug(
                "%s Starting connection manager", self.log_prefix
            )  # pragma: no mutate
            self._reconnect_retries = 0
            self._manager_task = asyncio.create_task(self._connection_manager())

    def _track_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Create a tracked background task that auto-removes itself on completion."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def stop_listening(self) -> None:
        """Stop the connection manager and close the connection."""
        if self._manager_task:
            _LOGGER.info(
                "%s Stopping connection manager", self.log_prefix
            )  # pragma: no mutate
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
            mac = hass_config.get(CONF_MAC)
            raw_token = hass_config.get(CONF_TOKEN)
            raw_ip = hass_config.get(CONF_IP_ADDRESS)
            self._cfg = ConnectionConfig(
                host=raw_ip,
                port=hass_config.get(CONF_PORT, 2878),
                token=format_placeholders(
                    raw_token, raw_token, raw_ip, hass_config.get(KEY_DEVICE_ID), mac
                ),
                cert=_resolve_cert_path(hass_config.get(CONF_CERT) or ""),
                duid=mac.replace(":", "") if mac else None,
            )
            # Ensure DUID and token are available for templates.
            self._params.update(
                {
                    CONF_DUID: self._cfg.duid,
                    CONF_TOKEN: self._cfg.token,
                    CONF_IP_ADDRESS: self._cfg.host,
                }
            )

        self._last_successful_config = None
        self._last_icmp_diagnostic = None
        # Restore the last successful SSL config from ConfigEntry data across
        # restarts, else the preferred connection saved during pairing.
        if stored := self._config.get(KEY_SSL_CONFIG):
            self._last_successful_config = stored
            _LOGGER.debug(
                "%s Restored last successful SSL config from ConfigEntry data in init: cert=%s, cipher=%s",
                self.log_prefix,
                stored.get(KEY_CERT),
                stored.get(KEY_CIPHER_NAME),
            )  # pragma: no mutate
        elif hass_config and isinstance(
            pref_conn := hass_config.get(KEY_PREFERRED_CONNECTION), dict
        ):
            self._last_successful_config = pref_conn.copy()

        # Resolve a relative path in the preferred config to match runtime behavior.
        if self._last_successful_config and (
            pref_cert := self._last_successful_config.get(KEY_CERT)
        ):
            self._last_successful_config[KEY_CERT] = _resolve_cert_path(pref_cert)

    def load_from_yaml(self, node: dict[str, Any] | None, connection_base: Any) -> bool:
        if connection_base:
            self._params.update(
                connection_base._params.copy()  # pylint: disable=protected-access
            )
        if not node:
            return False

        params_node = node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {})
        hass: Any = self._hass
        if CONFIG_DEVICE_CONNECTION_TEMPLATE in params_node:
            self._connection_init_template = Template(
                params_node[CONFIG_DEVICE_CONNECTION_TEMPLATE],
                hass,
            )
        elif not connection_base:
            _LOGGER.error(
                "%s Missing 'connection_template' in YAML configuration",
                self.log_prefix,
            )  # pragma: no mutate
            return False

        if CONFIG_DEVICE_POWER_TEMPLATE in params_node:
            self._power_template = Template(
                params_node[CONFIG_DEVICE_POWER_TEMPLATE],
                hass,
            )

        if not connection_base:
            # These are critical and should have been provided during setup.
            if not self._cfg.host:
                _LOGGER.error(
                    "%s Missing 'host' parameter", self.log_prefix
                )  # pragma: no mutate
                return False
            if not self._cfg.token:
                _LOGGER.error(
                    "%s Missing 'token' parameter", self.log_prefix
                )  # pragma: no mutate
                return False
            if not self._cfg.duid or not self._cfg.duid.strip():
                _LOGGER.error(
                    "%s Missing 'mac' parameter", self.log_prefix
                )  # pragma: no mutate
                return False

        self._params.update(params_node)

        # Runtime config from HA overrides default YAML placeholders
        if self._cfg:
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
        safe_config: dict[str, Any] | None = None
        if last_config := self._last_successful_config:
            safe_config = {}
            if last_config.get(KEY_CERT):
                # Expose only the filename, not the full path, for privacy/security
                safe_config[KEY_CERT_FILENAME] = Path(last_config[KEY_CERT]).name
            if KEY_CIPHER_NAME in last_config:
                safe_config[KEY_CIPHER_NAME] = last_config[KEY_CIPHER_NAME]

        return {
            KEY_IS_CONNECTED: self._is_ready.is_set(),
            KEY_RECONNECT_RETRIES: self._reconnect_retries,
            KEY_IS_AVAILABLE: self._is_available,
            KEY_LAST_SUCCESSFUL_CONFIG: safe_config,
            KEY_NETWORK_REACHABILITY: self._last_icmp_diagnostic
            or dict(DEFAULT_NETWORK_DIAGNOSTIC),
        }

    def create_updated(self, yaml_node: dict[str, Any] | None) -> ConnectionSamsung2878:
        self.load_from_yaml(yaml_node, self)
        return self

    async def _post_connect_status_request(self) -> None:
        """Queues a request for the full device status after a connection is established."""
        # Give the system a moment to be ready for a new command.
        try:
            await asyncio.sleep(1)
            _LOGGER.debug(
                "%s Queuing post-reconnection status request", self.log_prefix
            )  # pragma: no mutate

            future = asyncio.get_running_loop().create_future()
            await self._cmd_queue.put((self._poll_command, future))

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
                _LOGGER.debug(
                    "%s Cancelling pending read task", self.log_prefix
                )  # pragma: no mutate
                self._read_task.cancel()
                try:
                    await self._read_task
                except asyncio.CancelledError:
                    pass
            self._read_task = None  # pragma: no mutate

            if self._writer:
                _LOGGER.debug(
                    "%s Closing connection", self.log_prefix
                )  # pragma: no mutate
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
        """Open the TLS link, validate the greeting and authenticate."""
        await self._close_connection()
        if not await self._connect_ssl():
            return False
        initial_msg = await self._read_full_response(
            timeout_sec=self._socket_timeout
        )  # pragma: no mutate
        await self._process_initial_message(initial_msg)
        if not await self._authenticate():
            return False  # Session collision: trigger retry logic
        self._on_connection_ready()
        return True

    def _build_ssl_attempts(self) -> list[SSLAttempt]:
        """Return every strategy/cipher combination, last successful one first."""
        user_cert = self._cfg.cert
        attempts: list[SSLAttempt] = [
            (user_cert if cert == USER_CERT else cert, verify_mode, cipher_cfg, name)
            for cert, verify_mode, name in (
                USER_CERT_STRATEGIES if user_cert else DEFAULT_STRATEGIES
            )
            for cipher_cfg in (NO_CERT_CIPHERS if cert is None else DEFAULT_CIPHERS)
        ]
        if pref := self._last_successful_config:
            pref_cipher = pref.get(KEY_CIPHER_NAME)
            matching = [
                a
                for a in attempts
                if a[0] == pref.get(KEY_CERT)
                and a[1] == pref.get(KEY_VERIFY_MODE)
                and (not pref_cipher or a[2][1] == pref_cipher)
            ]
            attempts = matching + [a for a in attempts if a not in matching]
        return attempts

    async def _connect_ssl(self) -> bool:
        """Try each SSL attempt until one connects at the socket level."""
        last_error: Exception | None = None  # pragma: no mutate
        for (
            cert_path,
            verify_mode,
            cipher_cfg,
            strategy_name,
        ) in self._build_ssl_attempts():
            try:
                await self._open_ssl_connection(cert_path, verify_mode, cipher_cfg)
                return True
            except (ConnectionRefusedError, TimeoutError, OSError, ssl.SSLError) as e:
                # Expected when the device is offline or the port is wrong.
                last_error = e  # pragma: no mutate
            except Exception as e:
                _LOGGER.warning(
                    "%s Connection with '%s' / '%s' failed unexpectedly: %s. Trying next.",
                    self.log_prefix,
                    strategy_name,
                    cipher_cfg[1],
                    e,
                )  # pragma: no mutate
                last_error = e  # pragma: no mutate
            await self._close_connection()

        _LOGGER.debug(
            "%s Could not connect to device (likely offline): %s",
            self.log_prefix,
            last_error,
        )  # pragma: no mutate
        return False

    async def _open_ssl_connection(
        self,
        cert_path: str | None,
        verify_mode: ssl.VerifyMode,
        cipher_cfg: tuple[str, str],
    ) -> None:
        """Open one TLS connection and memorize its configuration on success."""
        ciphers, cipher_name = cipher_cfg
        cache_key = (cert_path, ciphers, verify_mode)  # All SSL parameters
        if not (ssl_context := self._ssl_context_cache.get(cache_key)):
            ssl_context = await async_create_samsung_ssl_context(
                cert_path=cert_path, ciphers=ciphers, verify_mode=verify_mode
            )
            self._ssl_context_cache[cache_key] = ssl_context

        sock = _create_keepalive_socket()
        try:
            async with asyncio.timeout(self._socket_timeout):
                await asyncio.get_running_loop().sock_connect(
                    sock, (self._cfg.host, self._cfg.port)
                )
        except Exception:
            sock.close()
            raise

        async with asyncio.timeout(self._socket_timeout):
            self._reader, self._writer = await asyncio.open_connection(
                sock=sock, ssl=ssl_context, server_hostname=self._cfg.host
            )

        if ssl_object := self._writer.get_extra_info("ssl_object"):
            _LOGGER.debug(
                "%s SSL connection established. Cipher: %s, Verify: %s, Negotiated TLS: %s",
                self.log_prefix,
                ssl_object.cipher(),
                verify_mode,
                ssl_object.version(),
            )  # pragma: no mutate

        # Memorize the successful configuration for future reconnections
        self._last_successful_config = {
            KEY_CERT: cert_path,
            KEY_CIPHER_NAME: cipher_name,
            KEY_VERIFY_MODE: verify_mode,
        }
        # Persist to ConfigEntry data so it survives HA restarts
        if self._controller and self._controller.on_ssl_config_updated:
            self._controller.on_ssl_config_updated(self._last_successful_config)

    async def _process_initial_message(self, initial_msg: str | None) -> None:
        """Apply state carried by the greeting and validate the handshake marker."""
        if initial_msg:
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

        if not initial_msg or not any(m in initial_msg for m in HANDSHAKE_MARKERS):
            _LOGGER.warning(
                "%s Handshake failed: Did not receive expected initial message (DPLUG-1.6 or DRC-1.00 or InvalidateAccount). Got: %s",
                self.log_prefix,
                initial_msg,
            )  # pragma: no mutate
            raise CannotConnect(
                "Handshake failed: Did not receive expected initial message"
            )

    async def _authenticate(self) -> bool:
        """Send the auth command; return False on a session collision."""
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
            raise CannotConnect(
                f"Template rendering failed: {err}"
            ) from err  # pragma: no mutate
        await self._write_data(auth_command)

        auth_response = await self._read_full_response(timeout_sec=self._socket_timeout)
        if not auth_response:
            raise AuthError("Authentication failed: No response from device")
        if PROTOCOL_2878_STATUS_OK in auth_response:
            return True
        # Handle InvalidateAccount (Session Collision) gracefully
        if PROTOCOL_2878_INVALIDATE in auth_response:
            _LOGGER.info(
                "%s Device reported session collision (InvalidateAccount). Waiting for old session to timeout...",
                self.log_prefix,
            )  # pragma: no mutate
            return False
        if ERROR_CODE_301 in auth_response:
            _LOGGER.error(
                "%s Authentication failed (ErrorCode 301). The device was likely turned off. Please ensure the device is ON before pairing",
                self.log_prefix,
            )  # pragma: no mutate
            raise AuthError("Authentication failed: Device was turned off (301)")
        _LOGGER.error(
            "%s Authentication failed with ErrorCode %s. Got: %s",
            self.log_prefix,
            m.group(1) if (m := ERROR_CODE_RE.search(auth_response)) else "Unknown",
            auth_response,
        )  # pragma: no mutate
        raise AuthError("Authentication failed")

    def _on_connection_ready(self) -> None:
        """Reset backoff state and schedule post-reconnection refreshes."""
        _LOGGER.info("%s Connection ready", self.log_prefix)  # pragma: no mutate
        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._reconnect_retries = 0
        self._is_ready.set()  # Signal that we are ready for commands

        # Stateful logging: Log when connection is re-established
        if not self._is_available:
            _LOGGER.debug(
                "%s Connection re-established", self.log_prefix
            )  # pragma: no mutate
            self._is_available = True
            self._persistent_offline_err_logged = False

        # Request a full status update only on reconnections, not on the very first connection.
        if self._initial_connection_done:
            self._track_task(self._post_connect_status_request())
            # Proactively refresh HA state after reconnection
            if self._controller and self._controller.request_refresh_callback:
                _LOGGER.debug(
                    "%s Requesting immediate coordinator refresh after reconnection.",
                    self.log_prefix,
                )  # pragma: no mutate
                self._track_task(self._controller.request_refresh_callback())

        self._initial_connection_done = True

    async def _read_full_response(self, timeout_sec: float = 10.0) -> str | None:
        if not self._reader or self._reader.at_eof():
            return None
        buffer = b""  # pragma: no mutate
        try:
            async with asyncio.timeout(timeout_sec):
                while True:
                    chunk = await self._reader.read(4096)
                    if not chunk:
                        await self._close_connection()
                        break
                    buffer += chunk
                    decoded = buffer.decode(errors="ignore").strip()
                    if decoded.endswith(TAG_SELF_CLOSE) or any(
                        marker in decoded for marker in RESPONSE_END_MARKERS
                    ):
                        return decoded
        except TimeoutError, asyncio.IncompleteReadError:
            _LOGGER.debug(
                "%s No full response received in %s seconds",
                self.log_prefix,
                timeout_sec,
                exc_info=True,
            )  # pragma: no mutate
        except OSError as e:
            _LOGGER.error(
                "%s Error during read: %s", self.log_prefix, e, exc_info=True
            )  # pragma: no mutate
            await self._close_connection()
            return None
        return buffer.decode(errors="ignore") if buffer else None

    async def _write_data(self, data_str: str) -> bool:
        if not self._writer or self._writer.is_closing():
            _LOGGER.error(
                "%s Write failed: writer is not available", self.log_prefix
            )  # pragma: no mutate
            raise CannotConnect("Connection is not available for writing")
        try:
            self._writer.write(data_str.encode("utf-8"))
            async with asyncio.timeout(WRITE_TIMEOUT):
                await self._writer.drain()
            return True
        except (TimeoutError, OSError) as e:
            _LOGGER.error(
                "%s Write failed: %s. Closing connection.", self.log_prefix, e
            )  # pragma: no mutate
            await self._close_connection()
            raise CannotConnect(f"Failed to write to connection: {e}") from e

    def _is_redundant_power_on(self, attrs: list[dict[str, Any]]) -> bool:
        """Return True for a lone 'Power On' push while the device is known to be on."""
        return (
            len(attrs) == 1
            and attrs[0].get(PROTOCOL_2878_ATTR_ID) == PROTOCOL_2878_POWER_ID
            and attrs[0].get(PROTOCOL_2878_ATTR_VALUE) == PROTOCOL_2878_VALUE_ON
            and self._device_status.get(PROTOCOL_2878_POWER_ID)
            == PROTOCOL_2878_VALUE_ON
        )

    async def _parse_and_update_state(
        self, response_xml: str
    ) -> tuple[bool, bool, dict[str, Any] | None]:
        if not response_xml:
            return False, False, None  # pragma: no mutate

        if not (self._controller and self._controller.hass):
            raise RuntimeError(
                "Home Assistant instance is required for parsing XML securely"  # pragma: no mutate
            )  # pragma: no mutate

        # Discard any non-XML prefix like "DPLUG-1.6\n" or "DRC-1.00\n"
        xml_start_index = response_xml.find(TAG_XML_DECL)
        if xml_start_index == -1:
            return False, False, None  # pragma: no mutate

        is_update = False
        is_response = False
        parsed_data: dict[str, Any] = {}
        # Split on '<?xml' to handle multiple XML documents concatenated in the buffer.
        for doc_part in response_xml[xml_start_index:].split(TAG_XML_DECL):
            if not (fragment := doc_part.strip()):
                continue
            if not fragment.startswith(XML_FRAGMENT_STARTS):
                _LOGGER.debug(
                    "%s Skipping non-XML fragment after '<?xml': %s",
                    self.log_prefix,
                    fragment,
                )  # pragma: no mutate
                continue
            full_doc = TAG_XML_DECL + doc_part
            try:
                # Parse in the HA executor thread to prevent blocking the event loop
                data = await self._controller.hass.async_add_executor_job(
                    safe_xml_to_dict, full_doc
                )
                if PROTOCOL_2878_RESPONSE in data:
                    is_response = True
                    device_data = (
                        data[PROTOCOL_2878_RESPONSE]
                        .get(PROTOCOL_2878_DEVICE_STATE, {})
                        .get(TAG_DEVICE)
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

                if is_update and self._is_redundant_power_on(attrs):
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

    async def _process_command_queue(self, queue_task: asyncio.Task[Any]) -> None:
        """Process a command from the queue."""
        command, future = queue_task.result()
        self._pending_future = future
        # Store the command string on the future for debugging purposes.
        setattr(self._pending_future, ATTR_COMMAND_DEBUG, command)

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
        try:
            if self._read_task:
                data = self._read_task.result()
        except asyncio.CancelledError:
            # Task was cancelled (likely by _close_connection), treat as connection closed
            pass
        except Exception as e:
            _LOGGER.warning(
                "%s Read task failed: %s", self.log_prefix, e
            )  # pragma: no mutate

        if not data:
            _LOGGER.debug(
                "%s Connection closed by device (EOF) or read task cancelled",
                self.log_prefix,
            )  # pragma: no mutate
            await self._close_connection()
            return None

        buffer += data
        # Process buffer to find full XML messages.
        while any(tag in buffer for tag in STREAM_END_TAGS):  # pragma: no mutate
            end_tag = next(tag for tag in STREAM_END_TAGS if tag in buffer)
            end_index = buffer.find(end_tag) + len(end_tag)
            message = buffer[:end_index]
            buffer = buffer[end_index:]
            await self._handle_message(message.decode(errors="ignore"))
        return buffer

    async def _handle_message(self, xml_data: str) -> None:
        """Parse one framed message, resolve the pending command and push updates."""
        _LOGGER.debug(
            "%s Received message: %s",
            self.log_prefix,
            mask_sensitive_data(xml_data.strip()),
        )  # pragma: no mutate
        is_response, is_update, parsed_data = await self._parse_and_update_state(
            xml_data
        )
        # Update internal state for redundant 'Power On' logic.
        if parsed_data:
            self._device_status.update(parsed_data)

        # A command completes on a 'DeviceControl Okay' response or on any other
        # response carrying state data; a poll only completes on a DeviceState response.
        is_control_okay = (
            is_response
            and PROTOCOL_2878_DEVICE_CONTROL in xml_data
            and PROTOCOL_2878_STATUS_OK in xml_data
        )
        if self._pending_future and not self._pending_future.done():
            command_debug = getattr(self._pending_future, ATTR_COMMAND_DEBUG, "")
            if (
                is_response and PROTOCOL_2878_DEVICE_STATE in xml_data
                if PROTOCOL_2878_DEVICE_STATE in command_debug
                else is_control_okay or (is_response and parsed_data)
            ):
                _LOGGER.debug(
                    "%s Response received (control okay: %s), resolving pending command future",
                    self.log_prefix,
                    is_control_okay,
                )  # pragma: no mutate
                self._pending_future.set_result(True)
                self._pending_future = None  # pragma: no mutate

        self._ensure_callback_linked()
        if parsed_data and (is_response or is_update) and self._update_callback:
            _LOGGER.debug(
                "%s Calling update callback with data: %s",
                self.log_prefix,
                parsed_data,
            )  # pragma: no mutate
            self._track_task(self._update_callback(parsed_data))
        elif is_control_okay:
            # Just an acknowledgment: the device sends a separate <Update> push.
            _LOGGER.debug(
                "%s 'DeviceControl Okay' ack received. Waiting for subsequent push update.",
                self.log_prefix,
            )  # pragma: no mutate

    def _force_unavailability_if_needed(
        self, offline_type: str = "Network"
    ) -> None:  # pragma: no mutate
        """Force frontend unavailability if retries hit threshold."""
        if self._reconnect_retries == 2:
            if not self._persistent_offline_err_logged:
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
                    if self._controller and self._controller.on_offline_callback:
                        self._controller.on_offline_callback(OFFLINE_PANIC_MSG)
                self._persistent_offline_err_logged = True
            else:
                _LOGGER.debug(
                    "%s AC %s is persistently offline.", self.log_prefix, offline_type
                )  # pragma: no mutate

            if self._controller and self._controller.on_connection_failed_callback:
                self._controller.on_connection_failed_callback()

    async def _check_network_reachability(self) -> bool:
        """Ping the host and store the ICMP diagnostic to aid troubleshooting."""
        network_reachable = True
        try:
            network_reachable = await async_check_network_reachability(
                self._cfg.host or "", self.log_prefix
            )
            self._last_icmp_diagnostic = get_last_network_diagnostic(
                self._cfg.host
            ) or {
                KEY_IS_REACHABLE: network_reachable,
                KEY_STATUS: STATUS_ALIVE if network_reachable else STATUS_UNREACHABLE,
            }
        except Exception as diag_err:
            _LOGGER.debug(
                "%s Network diagnostic failed: %s", self.log_prefix, diag_err
            )  # pragma: no mutate
        return network_reachable

    async def _backoff_after_failure(
        self, offline_type: str | None = None, jitter: bool = True
    ) -> bool:
        """Count a failed attempt and sleep with exponential backoff."""
        self._reconnect_retries += 1
        if offline_type:
            # After 2 consecutive failures, force unavailability in HA
            self._force_unavailability_if_needed(offline_type)
        delay = self._reconnect_delay
        if jitter:
            delay += random.uniform(0, self._reconnect_delay * JITTER_RATIO)
        _LOGGER.debug(
            "%s Reconnect failed (%s). Backing off for %.1f seconds...",
            self.log_prefix,
            offline_type or "Error",
            delay,
        )  # pragma: no mutate
        self._ssl_context_cache.clear()  # Force fresh SSL context on retry
        await self._close_connection()
        await asyncio.sleep(delay)
        self._reconnect_delay = min(
            self._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
        )
        return False

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

        # Only attempt to open the TCP port if the ping succeeds to protect fragile ACs.
        try:
            if not await self._check_network_reachability():
                # Network fully down: retry without jitter to recover quickly.
                return await self._backoff_after_failure("Network", jitter=False)
            if not await self._establish_connection_and_handshake():
                # Network UP but Port 2878 closed/crashing.
                return await self._backoff_after_failure("Service")
        except (CannotConnect, AuthError) as e:
            # Network UP but an exception occurred: fail any pending command.
            if self._pending_future and not self._pending_future.done():
                self._pending_future.set_exception(
                    CannotConnect(
                        f"Connection lost and reconnect failed: {e}"
                    )  # pragma: no mutate
                )
                self._pending_future = None  # pragma: no mutate
            return await self._backoff_after_failure()
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

                    tasks: list[asyncio.Task[Any]] = [self._read_task]

                    # Ensure queue listener is running if we are ready for commands
                    if not queue_task and not self._pending_future:
                        queue_task = asyncio.create_task(self._cmd_queue.get())

                    if queue_task:
                        tasks.append(queue_task)

                    done, _ = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )

                    if queue_task and queue_task in done:
                        await self._process_command_queue(queue_task)
                        queue_task = None  # pragma: no mutate

                    if self._read_task in done:
                        read_buffer = await self._process_read_queue(buffer)
                        if read_buffer is None:  # Connection closed
                            buffer = b""  # pragma: no mutate
                            # Yield to event loop to prevent starvation on rapid reconnect cycles
                            await asyncio.sleep(0.05)
                            continue
                        buffer = read_buffer

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
                    buffer = b""  # pragma: no mutate  # CRITICAL: clean state for next iteration
                    await self._close_connection()
                    jitter = random.uniform(0, self._reconnect_delay * JITTER_RATIO)
                    await asyncio.sleep(self._reconnect_delay + jitter)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    _LOGGER.error(
                        "%s Unexpected exception in connection manager: %s",
                        self.log_prefix,
                        e,
                        exc_info=True,
                    )  # pragma: no mutate
                    # Yield to event loop to prevent starvation on unexpected errors
                    await asyncio.sleep(0.05)
        finally:
            _LOGGER.debug(
                "%s Connection manager exiting, cleaning up", self.log_prefix
            )  # pragma: no mutate
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
            command = self._poll_command

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
                _LOGGER.debug(
                    "%s Command executed successfully", self.log_prefix
                )  # pragma: no mutate

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
                _LOGGER.debug(
                    "%s Command timed out. Forcing connection close to trigger reconnect.",
                    self.log_prefix,
                )  # pragma: no mutate
                self._track_task(self._close_connection())

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
