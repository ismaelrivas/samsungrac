# custom_components/climate_ip/connection_request.py
"""
Synchronous connection engine using the requests library.

TARGET DEVICES:
- Samsung AC (connection type: 'request')
- Samsung AC (connection type: 'request_print')

This engine provides a robust implementation for devices that support
persistent HTTP/1.1 connections with Keep-Alive. It handles automatic
recovery for protocol violations and adaptive timeout management.
"""

import asyncio
import contextlib
import logging
import os
import ssl
import time
import warnings
from collections.abc import Generator
from typing import Any

from homeassistant.util.json import json_loads, JSON_DECODE_EXCEPTIONS
from homeassistant.helpers.json import json_dumps

import requests  # type: ignore[import-untyped]
from jinja2 import Template
from requests.adapters import HTTPAdapter  # type: ignore[import-untyped]
from requests.packages.urllib3.exceptions import (  # type: ignore[import-untyped]  # pylint: disable=import-error
    InsecureRequestWarning,
)

from .connection import Connection, _HOST_LOCKS, register_connection
from .const import (
    CONF_CERT,
    CONFIG_DEVICE_CONDITION_TEMPLATE,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
)
from .exceptions import AuthError, CannotConnect, RetryNextAttempt
from .helpers import (
    create_samsung_ssl_context,
    mask_sensitive_data,
    tolerant_header_parsing,
    format_placeholders,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)

CONNECTION_TYPE_REQUEST = "request"
CONNECTION_TYPE_REQUEST_PRINT = "request_print"

REQUEST_MAX_RETRIES = 3
REQUEST_RETRY_DELAY = 1.0  # seconds


class SamsungHTTPAdapter(HTTPAdapter):
    """Custom HTTP adapter for Samsung devices with specific SSL/TLS requirements."""

    def init_poolmanager(
        self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any
    ) -> Any:
        """Initialize the pool manager with custom SSL context and enforced concurrency."""
        ssl_context = create_samsung_ssl_context(
            ciphers="ALL:@SECLEVEL=0", verify_mode=ssl.CERT_NONE
        )

        pool_kwargs["ssl_context"] = ssl_context
        # Restored default connection pools to prevent I/O bottlenecks.
        # Previously capped at 1, causing slowdowns on slow networks.
        target_connections = max(10, connections)
        target_maxsize = max(10, maxsize)

        # DEBUG: Trace new pool manager creation
        _LOGGER.debug(
            "[SamsungHTTPAdapter] Initializing new PoolManager. "
            "Original: connections=%s, maxsize=%s, block=%s. "
            "Target: connections=%s, maxsize=%s, block=%s",
            connections,
            maxsize,
            block,
            target_connections,
            target_maxsize,
            block,
        )
        return super().init_poolmanager(
            target_connections, target_maxsize, block=block, **pool_kwargs
        )

    def cert_verify(
        self, conn: Any, url: str, verify: bool | str, cert: str | tuple[str, str] | None
    ) -> None:
        """Override default certification verification."""
        # Intentionally empty to bypass default requests verification
        # as it is handled by the custom SSL context in the pool manager.


class ConnectionRequestBase(Connection): # pylint: disable=import-outside-toplevel,too-many-instance-attributes
    """Base class for connection engines using the requests library."""

    def __init__(
        self,
        hass_config: dict[str, Any] | None,
        _logger: logging.Logger,
        hass: Any | None = None,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(hass_config or {}, _logger, hass=hass)
        self._hass = hass
        self._params: dict[str, Any] = {"timeout": 30}
        self._max_retries = 3
        self._embedded_command: "ConnectionRequestBase | None" = None  # An optional nested command.
        self._controller: Any = None  # Will be set by the property that creates this.
        self._parent: "ConnectionRequestBase | None" = (
            None  # Reference to parent connection for upward propagation
        )
        logging.getLogger("urllib3.connectionpool").setLevel(logging.DEBUG)
        self.update_configuration_from_hass(hass_config)
        self._condition_template: Template | None = None
        self._is_closing = False

        # Initialize a persistent session to support Keep-Alive.
        if session:
            self._session = session
        else:
            self._session = requests.Session()
            self._session.verify = False
            self._session.mount("https://", SamsungHTTPAdapter())

        # Read keep_alive setting
        self._keep_alive = hass_config.get("keep_alive", True) if hass_config else True

        # Registry for child connections (embedded commands) to propagate session updates
        self._children: list["ConnectionRequestBase"] = []
        self._force_close_connection = False
        self._keep_alive_broken = False

        warnings.warn(
            "The 'request' connection method is deprecated and "
            "will be removed in a future release. Please switch the "
            f"connection method for {self.log_prefix} to Modern "
            "(aiohttp) or Robust (raw socket).",
            DeprecationWarning,
        )

    def set_controller_ref(self, controller: Any) -> None:
        """Allows the property to set a reference to the main controller."""
        self._controller = controller

    @property
    def is_async_native(self) -> bool:
        """Indicates if the connection is native asynchronous."""
        return False

    @property
    def is_push_supported(self) -> bool:
        """Return True indicating this connection type supports push updates."""
        return False

    @property
    def async_lock(self) -> asyncio.Lock:
        """Return the shared per-host asyncio.Lock.

        For request engines the host lives in the controller, not in _params,
        so we override the base-class property to source it from there.
        """
        ip: str | None = None
        port: str | int = "default"

        if self._controller:
            ip = getattr(self._controller, "ip_address", None)
            port = getattr(self._controller, "port", port)
        elif self._parent:
            # Child connections (embedded commands) delegate to their parent.
            return self._parent.async_lock  # type: ignore[return-value]

        if not ip:
            return self._lock  # Fallback: per-instance lock

        key = (str(ip), str(port))
        if key not in _HOST_LOCKS:
            _HOST_LOCKS[key] = asyncio.Lock()
        return _HOST_LOCKS[key]

    # pylint: disable=import-outside-toplevel,too-many-arguments,too-many-positional-arguments
    async def async_execute(
        self,
        method: str | None,
        url: str | None,
        data: str | None,
        headers: dict[str, str] | None,
        device_state: dict[str, Any] | None = None,
        _is_probe: bool = False,
        _is_poll: bool = False,
    ) -> tuple[str | None, dict[str, str] | None]:
        """Async execution is not supported by this engine."""
        raise NotImplementedError("This connection engine is synchronous only.")

    async def async_execute_legacy(
        self,
        template: Any,
        value: Any,
        device_state: dict[str, Any] | None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        """Async wrapper for the synchronous execute() method.

        Acquires the shared per-host lock BEFORE dispatching to the thread
        pool, so that at most one request at a time is sent to the same
        physical device, regardless of how many entity instances share the IP.
        """
        async with self.async_lock:
            return await asyncio.to_thread(self.execute, template, value, device_state, device_id)


    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the requests connection."""
        # Assuming _insecure_ssl and _socket_timeout are attributes that would be set
        # or derived from the session/adapter configuration.
        insecure_ssl = not self._session.verify if hasattr(self._session, "verify") else True
        socket_timeout = self._params.get("timeout", None)
        force_close = getattr(self, "_force_close_connection", False)

        return {
            "engine": "requests_sync",
            "insecure_ssl": insecure_ssl,
            "timeout": socket_timeout,
            "keep_alive_fallback_active": force_close,
        }

    @property
    def log_prefix(self) -> str:
        """Get the log prefix from the controller for consistent logging."""
        if self._controller:
            return self._controller.log_prefix

        if getattr(self, "_parent", None):
            return getattr(self._parent, "log_prefix", "[NO_ID]")

        fallback_id = None
        if hasattr(self, "config") and isinstance(self.config, dict):
            fallback_id = (
                self.config.get("mac") or self.config.get("unique_id") or self.config.get("name")
            )

        if fallback_id:
            return f"[{fallback_id[-6:] if len(fallback_id) >= 6 else fallback_id}]"

        return "[NO_ID]"

    def _update_session(self, session: requests.Session) -> None:
        """Updates the session and propagates it to all children."""
        self._session = session
        _LOGGER.debug(
            "%s [Session Propagation] Updated session to ID: %s", self.log_prefix, id(session)
        )

        # Propagate to children
        for child in self._children:
            child._update_session(session)  # pylint: disable=import-outside-toplevel,protected-access

    def _update_session_from_reset(self, session: requests.Session) -> None:
        """Entry point for updates triggered by internal reset."""
        if self._parent:
            _LOGGER.debug(
                "%s [Session Propagation] Delegating session update to parent.", self.log_prefix
            )
            self._parent._update_session(session)  # pylint: disable=import-outside-toplevel,protected-access
        else:
            self._update_session(session)

    async def close(self) -> None:
        """Async wrapper for closing the connection resources."""
        _LOGGER.debug(
            "%s [ConnectionRequest] Closing connection resources (Async)...", self.log_prefix
        )
        # Modern Python 3.9+ syntax for offloading sync blocking tasks
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        """Explicitly close the session (Synchronous)."""
        self._is_closing = True
        # Only the root connection (no parent) should close the shared session and emit logs.
        if not getattr(self, "_parent", None):
            _LOGGER.debug("%s [ConnectionRequest] _close_sync: Cleanup started.", self.log_prefix)
            if hasattr(self, "_session") and self._session:
                try:
                    self._session.close()
                    _LOGGER.debug("%s [ConnectionRequest] Session closed.", self.log_prefix)
                except Exception as e:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                    _LOGGER.debug(
                        "%s [ConnectionRequest] Error closing session: %s", self.log_prefix, e
                    )

    @contextlib.contextmanager
    def _borrow_session(self) -> Generator[requests.Session, None, None]:
        """Yields the persistent session without closing it on exit."""
        _LOGGER.debug("%s [Debug] Borrowing session ID: %s", self.log_prefix, id(self._session))
        if self._session and self._session.adapters:
            adapter = self._session.get_adapter("https://")
            if hasattr(adapter, "poolmanager"):
                _LOGGER.debug(
                    "%s [Debug] PoolManager ID: %s", self.log_prefix, id(adapter.poolmanager)
                )

        yield self._session

    @property
    def embedded_command(self) -> "ConnectionRequestBase | None":
        """Return the optional nested command."""
        return self._embedded_command

    @property
    def condition_template(self) -> Template | None:
        """Return the condition template for execution."""
        return self._condition_template

    def update_configuration_from_hass(self, hass_config: dict[str, Any] | None) -> None:
        """Update connection parameters from Home Assistant configuration."""
        if hass_config is not None:
            cert_file = hass_config.get(CONF_CERT, None)
            if cert_file is not None:
                if cert_file.find("\\") == -1 and cert_file.find("/") == -1:
                    cert_file = os.path.join(os.path.dirname(__file__), cert_file)

            self._params[CONF_CERT] = cert_file

    def load_from_yaml(self, node: dict[str, Any] | None, connection_base: Any) -> bool:
        # pylint: disable=import-outside-toplevel,protected-access
        if connection_base:
            self._params.update(connection_base._params.copy())
            self._condition_template = connection_base._condition_template
            self._keep_alive = getattr(connection_base, "_keep_alive", True)
            self._parent = connection_base

        if node:
            self._params.update(node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {}))
            if "keep_alive" in node:
                self._keep_alive = node["keep_alive"]
            if CONFIG_DEVICE_CONNECTION in node:
                # pylint: disable=import-outside-toplevel,assignment-from-none
                self._embedded_command = self.create_updated(  # type: ignore[assignment]
                    node[CONFIG_DEVICE_CONNECTION]
                )
                if self._embedded_command:
                    self._children.append(self._embedded_command)
                    _LOGGER.debug(
                        "%s [Session Propagation] Registered child connection.", self.log_prefix
                    )
            if CONFIG_DEVICE_CONDITION_TEMPLATE in node:
                self._condition_template = Template(node[CONFIG_DEVICE_CONDITION_TEMPLATE])

        return True

    def _has_connection_refused(self, exc: Exception) -> bool:
        """Recursively check the exception chain for the root cause."""
        if isinstance(exc, ConnectionRefusedError):
            return True
        if exc.__cause__:
            return self._has_connection_refused(exc.__cause__)  # type: ignore[arg-type]
        if exc.__context__:
            return self._has_connection_refused(exc.__context__)  # type: ignore[arg-type]
        return False

    # pylint: disable=import-outside-toplevel,too-many-locals,too-many-branches,too-many-statements
    def execute_internal(
        self,
        template: Template | None,
        value: Any,
        _device_state: dict[str, Any] | None,
        device_id: str | None = None,
    ) -> tuple[Any, bool, int]:
        """Internal synchronous method to execute the HTTP request with retries."""

        token = self._controller.token if self._controller else None
        ip_address = self._controller.ip_address if self._controller else None
        mac = getattr(self._controller, "config", {}).get("mac") if self._controller else None

        params = self._params.copy()
        if template is not None:
            try:
                rendered_template = template.render(value=value, device_id=device_id)
                params.update(json_loads(rendered_template))
            except Exception as exc:
                _LOGGER.error(
                    "%s Error rendering template or parsing JSON: %s", self.log_prefix, exc
                )
                raise ValueError(f"Template rendering failed: {exc}") from exc

        # CRITICAL FIX: Replace placeholders in URLs and headers consistently
        params = format_placeholders(params, token, ip_address, device_id, mac)

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=InsecureRequestWarning)  # type: ignore

            # CRITICAL FIX: Use the persistent session (Keep-Alive)
            # We use a helper context manager to yield the session without closing it,
            # preserving the indentation of the block below.
            with self._borrow_session() as session:
                # The session is already holding the adapter and pool.
                # We do NOT remount it here to safe-guard connection reuse.

                for attempt in range(REQUEST_MAX_RETRIES):
                    if self._is_closing:
                        _LOGGER.debug(
                            "%s [ConnectionRequest] Connection is closing, aborting request.",
                            self.log_prefix,
                        )
                        raise ConnectionError("Connection is closing")
                    try:
                        _LOGGER.debug(
                            "%s Request (attempt %s/%s): %s",
                            self.log_prefix,
                            attempt + 1,
                            REQUEST_MAX_RETRIES,
                            mask_sensitive_data(params),
                        )

                        # --- ADAPTIVE KEEP-ALIVE LOGIC ---
                        # If we previously detected stability issues (timeouts likely due
                        # to missing Content-Length), we strictly force 'Connection: close'.
                        # pivot: Use a fresh copy of headers to avoid mutating self._params
                        # via shallow reference.
                        if getattr(self, "_force_close_connection", False):
                            # Ensure we don't fail if headers key is missing or None
                            if "headers" not in params or params["headers"] is None:
                                params["headers"] = {}
                            else:
                                # Shallow copy the headers dict to detach from self._params
                                params["headers"] = params["headers"].copy()

                            params["headers"]["Connection"] = "close"

                        # --- OPTIMIZATION: Fast Fail on First Attempt ---
                        # If we are seemingly in "stable" mode (keep-alive) but the device
                        # hangs (no Content-Length), the default timeout (e.g. 30s) will
                        # cause the Coordinator to mark us 'unavailable' BEFORE we have a
                        # chance to retry with Connection: close.
                        # So, for the FIRST attempt only, if we are not forcing close,
                        # cap the timeout to 10s.
                        request_params = (
                            params.copy()
                        )  # This is now safe as we handled headers above

                        # Rely on the Adapter's SSLContext. Passing verify=False
                        # explicitely might cause requests/urllib3 to bypass the pool
                        # or recreate the connection.
                        if "verify" in request_params:
                            del request_params["verify"]

                        current_timeout = request_params.get("timeout", 30)
                        if attempt == 0 and not getattr(self, "_force_close_connection", False):
                            if isinstance(current_timeout, (int, float)) and current_timeout > 12:
                                _LOGGER.debug(
                                    "%s [Optimization] Capping timeout to 10s for first "
                                    "attempt to allow retry within window.",
                                    self.log_prefix,
                                )
                                request_params["timeout"] = 10.0

                        resp = session.request(**request_params)

                        # Attempt to log the negotiated TLS version
                        try:
                            # Access the underlying urllib3 connection's socket
                            raw_conn = getattr(resp.raw, "_connection", None)
                            sock = getattr(raw_conn, "sock", None) if raw_conn else None
                            negotiated_tls = (
                                sock.version() if sock and hasattr(sock, "version") else "Unknown"
                            )
                            _LOGGER.debug(
                                "%s [ConnectionRequest] Request successful. Negotiated TLS: %s",
                                self.log_prefix,
                                negotiated_tls,
                            )
                        except Exception:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                            pass

                        # --- HTTP Version Detection ---
                        # Dynamically adjust Keep-Alive support based on server response.
                        # resp.raw.version is an integer: 10 (HTTP/1.0) or 11 (HTTP/1.1)
                        if getattr(resp.raw, "version", 0) == 11:
                            # Only re-enable Keep-Alive if it wasn't permanently disabled
                            # due to a protocol violation (like missing Content-Length).
                            if not getattr(self, "_keep_alive_broken", False):
                                _LOGGER.debug(
                                    "%s [Optimization] Server speaks HTTP/1.1. "
                                    "Re-enabling Keep-Alive.",
                                    self.log_prefix,
                                )
                                self._force_close_connection = False
                        elif getattr(resp.raw, "version", 0) == 10:
                            if not getattr(self, "_force_close_connection", False):
                                _LOGGER.debug(
                                    "%s [Compatibility] Server speaks HTTP/1.0. "
                                    "Enforcing 'Connection: close'.",
                                    self.log_prefix,
                                )
                            self._force_close_connection = True

                        # --- DEBUGGING: Log Raw Response on Error ---
                        if resp.status_code >= 400:
                            # Try to mask JSON response if possible
                            try:
                                json_body = json_loads(resp.content)
                                log_body = json_dumps(mask_sensitive_data(json_body))
                            except Exception:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                                log_body = resp.text

                            _LOGGER.debug(
                                "%s [Debug] HTTP %s Response Body: %s",
                                self.log_prefix,
                                resp.status_code,
                                log_body,
                            )
                        # --------------------------------------------

                        resp.raise_for_status()

                        # Use DEBUG level for successful command execution to avoid log spam.
                        _LOGGER.debug(
                            "%s Command successful with code: %s", self.log_prefix, resp.status_code
                        )
                        if not resp.text or not resp.text.strip():
                            _LOGGER.debug(
                                "%s Response was empty, returning None to trigger a poll.",
                                self.log_prefix,
                            )
                            return (None, True, resp.status_code)

                        try:
                            json_data = json_loads(resp.content)

                            # --- Proactive Content-Length Validation ---
                            # If the server speaks HTTP/1.1 (Keep-Alive by default) but fails
                            # to provide a Content-Length or chunked encoding, 'requests' will
                            # hang reading the socket until a timeout.
                            # The 'requests' library automatically consumes the body when
                            # calling .json() or .text, but if we got here, we want to
                            # proactively flag this broken server for future requests so
                            # we don't hang for 10 seconds again.
                            if (
                                not resp.headers.get("Content-Length")
                                and not resp.headers.get("Transfer-Encoding") == "chunked"
                            ):
                                if not getattr(self, "_force_close_connection", False):
                                    _LOGGER.warning(
                                        "%s [Protocol Violation] Server returned JSON but "
                                        "omitted 'Content-Length' header. "
                                        "This causes socket hangs on Keep-Alive. "
                                        "Forcing 'Connection: close' for all future requests.",
                                        self.log_prefix,
                                    )
                                    self._force_close_connection = True
                                    self._keep_alive_broken = True

                            return (json_data, True, resp.status_code)
                        except (requests.exceptions.JSONDecodeError, *JSON_DECODE_EXCEPTIONS):
                            # Treat non-JSON success response as a trigger to poll
                            # If the response is successful (2xx) but not valid JSON
                            # (e.g., just "OK"), it's a successful command acknowledgment.
                            # We return None to trigger a refresh.
                            _LOGGER.debug(
                                "%s Response was not valid JSON (e.g., 'OK'). "
                                "Returning None to trigger poll. Response: %s",
                                self.log_prefix,
                                resp.text.strip(),
                            )
                            return (None, True, resp.status_code)

                    except (*JSON_DECODE_EXCEPTIONS, requests.exceptions.JSONDecodeError) as e:
                        _LOGGER.warning(
                            "%s Parsing response json failed! Not retrying. Error: %s",
                            self.log_prefix,
                            e,
                        )
                        raise ValueError("Failed to parse JSON response") from e

                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code in (401, 403):
                            _LOGGER.error(
                                "%s Authentication error: %s. Not retrying", self.log_prefix, e
                            )
                            raise AuthError(
                                f"Authentication failed with status {e.response.status_code}"
                            ) from e
                        if (
                            500 <= e.response.status_code < 600
                            and attempt < REQUEST_MAX_RETRIES - 1
                        ):
                            if self._is_closing:
                                raise ConnectionError("Connection is closing") from e
                            _LOGGER.debug(
                                "%s Server error (%s). Delegating retry to async loop.",
                                self.log_prefix,
                                e.response.status_code,
                            )
                            raise RetryNextAttempt(f"Server error {e.response.status_code}") from e

                        # Enhanced error logging
                        _LOGGER.error(
                            "%s HTTP error: %s. Body: %s. Not retrying",
                            self.log_prefix,
                            e,
                            getattr(e.response, "text", "No Body"),
                        )
                        raise CannotConnect(f"HTTP error {e.response.status_code}") from e

                    except requests.exceptions.ReadTimeout as e:
                        # --- ADAPTIVE RECOVERY ---
                        if not getattr(self, "_force_close_connection", False):
                            _LOGGER.warning(
                                "%s [Legacy] ReadTimeout detected (%s). "
                                "The device likely violates HTTP protocol "
                                "(missing Content-Length). "
                                "Switching to 'Connection: close' mode for future attempts.",
                                self.log_prefix,
                                str(e),
                            )
                            self._force_close_connection = True
                            self._keep_alive_broken = True
                            # Continue to next attempt, which will now use Connection: close
                            if attempt < REQUEST_MAX_RETRIES - 1:
                                continue

                        # If we were already in force close mode OR ran out of retries
                        if attempt < REQUEST_MAX_RETRIES - 1:
                            if self._is_closing:
                                raise ConnectionError("Connection is closing") from e
                            _LOGGER.debug(
                                "%s ReadTimeout error. Delegating retry to async loop.",
                                self.log_prefix,
                            )
                            raise RetryNextAttempt("ReadTimeout error") from e

                        _LOGGER.warning(
                            "%s Request timed out (ReadTimeout) after %s attempts.",
                            self.log_prefix,
                            REQUEST_MAX_RETRIES,
                        )
                        raise CannotConnect("Request timed out (ReadTimeout)") from e

                    except requests.exceptions.Timeout as e:
                        if attempt < REQUEST_MAX_RETRIES - 1:
                            if self._is_closing:
                                raise ConnectionError("Connection is closing") from e
                            _LOGGER.debug(
                                "%s Request timed out. Delegating retry to async loop.",
                                self.log_prefix,
                            )
                            raise RetryNextAttempt("Timeout error") from e

                        _LOGGER.warning(
                            "%s Request timed out after %s attempts.",
                            self.log_prefix,
                            REQUEST_MAX_RETRIES,
                        )
                        raise CannotConnect("Request timed out") from e

                    except requests.exceptions.ConnectionError as e:
                        # --- ADAPTIVE RECOVERY for Connection Errors (e.g. RemoteDisconnected) ---
                        if not getattr(self, "_force_close_connection", False):
                            _LOGGER.debug(
                                "%s [Legacy] ConnectionError detected (%s). "
                                "Switching to 'Connection: close' mode for future attempts.",
                                self.log_prefix,
                                str(e),
                            )
                            self._force_close_connection = True
                            if attempt < REQUEST_MAX_RETRIES - 1:
                                # Retry immediately without sleep by yielding execution back
                                raise RetryNextAttempt(
                                    "ConnectionError logic switched to close mode"
                                ) from e

                        if attempt < REQUEST_MAX_RETRIES - 1:
                            if self._is_closing:
                                raise ConnectionError("Connection is closing") from e
                            _LOGGER.debug(
                                "%s Connection error. Delegating retry to async loop.",
                                self.log_prefix,
                            )
                            raise RetryNextAttempt("Connection error") from e

                        if self._has_connection_refused(e):
                            _LOGGER.debug(
                                "%s Connection refused after %s attempts. "
                                "Device is likely offline or IP is incorrect.",
                                self.log_prefix,
                                REQUEST_MAX_RETRIES,
                            )
                            raise CannotConnect(
                                "Connection refused (device unreachable or offline)"
                            ) from e

                        _LOGGER.warning(
                            "%s Connection error after %s attempts: %s",
                            self.log_prefix,
                            REQUEST_MAX_RETRIES,
                            e,
                        )
                        raise CannotConnect("Failed to establish a connection") from e

                    except requests.exceptions.RequestException as e:
                        _LOGGER.error(
                            "%s Unhandled request exception: %s. Not retrying",
                            self.log_prefix,
                            e,
                            exc_info=True,
                        )
                        raise CannotConnect(f"An unexpected network error occurred: {e}") from e

        # Fallback return to satisfy static analysis
        return (None, False, 0)

    def execute(
        self,
        template: Template | None,
        value: Any,
        device_state: dict[str, Any] | None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        """Synchronously executes the command. To be run in an executor."""
        if self.embedded_command:
            # If we have an embedded command, this acts as a command wrapper, not a simple poll.
            pass

        # Determine if it's a polling request (no value).
        # Device state might be present during updates, so we don't check for it being None.
        # Template might also be None if using defaults, so we rely primarily on value being None.
        is_poll_request = value is None

        if is_poll_request:
            _LOGGER.debug("%s Received poll request.", self.log_prefix)
        else:
            _LOGGER.debug("%s Received command request with value: %s", self.log_prefix, value)

        # Periodic Reset Logic (Legacy)
        if is_poll_request and not self._keep_alive:
            _LOGGER.debug(
                "%s [Legacy|Periodic Reset] Closing persistent session before poll.",
                self.log_prefix,
            )
            self._close_sync()

            # Delegate the small delay for TCP cleanup to the executor or skip it
            # if we are doing a clean reconnection logic, it's safer to just reopen.
            # Using a very small sleep here is generally bad practice in the executor,
            # but since it's a legacy engine and we need the socket to close, we keep
            # it minimal or remove it. Let's remove it and let the OS handle it.

            # Re-create the session
            new_session = requests.Session()
            new_session.verify = False
            new_session.mount("https://", SamsungHTTPAdapter())

            # Reset adaptive flags to give connection reuse a chance in the new cycle
            self._force_close_connection = False

            # Propagate the new session to self and children (delegating to parent if exists)
            self._update_session_from_reset(new_session)

            _LOGGER.debug("%s [Legacy|Periodic Reset] New session created.", self.log_prefix)

        if self.embedded_command:
            _LOGGER.debug("%s Executing embedded command...", self.log_prefix)

            if hasattr(self.embedded_command, "set_controller_ref"):
                self.embedded_command.set_controller_ref(self._controller)
            # Pass device_id to the nested command.
            self.embedded_command.execute(template, value, device_state, device_id)

        if not self.check_execute_condition(device_state):
            _LOGGER.debug("%s Execute condition not met, skipping command", self.log_prefix)
            return {}

        # Timing measurement for sync execute
        start_time = time.perf_counter()

        # Pass device_id to the internal execution method.
        with tolerant_header_parsing():
            j, _, code = self.execute_internal(template, value, device_state, device_id)

        elapsed = time.perf_counter() - start_time
        _LOGGER.info(
            "%s [REQUESTS] Execute completed in %.3f seconds (status code %s)",
            self.log_prefix,
            elapsed,
            code,
        )
        # The retry logic for server errors (5xx) is now inside execute_internal

        # PREVENT DOUBLE POLLING
        # If the command was successful but returned no data, strictly return empty dict.
        # We DO NOT trigger a refresh here anymore. The Coordinator handles the
        # post-command refresh logic (Smart Polling or Delay).
        if j is None:
            _LOGGER.debug(
                "%s Command returned no data (or was a simple 'OK'). Returning empty dict.",
                self.log_prefix,
            )
            return {}

        return j


@register_connection
class ConnectionRequest(ConnectionRequestBase):  # pylint: disable=import-outside-toplevel,abstract-method
    """Standard connection engine using requests with persistent session support."""

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Return True if this connection type matches 'request'."""
        return type_str == CONNECTION_TYPE_REQUEST

    def create_updated(self, yaml_node: dict[str, Any] | None) -> "ConnectionRequest":
        c = ConnectionRequest(None, _LOGGER, session=self._session)
        c.load_from_yaml(yaml_node, self)

        # Register this new instance as a child so it receives session updates
        self._children.append(c)

        return c


# Dry-run fixture: sample device response used only by ConnectionRequestPrint.execute()
# for offline testing without a real device. Not used in production connections.
test_json: dict[str, Any] = {
    "Devices": [
        {
            "Alarms": [
                {
                    "alarmType": "Device",
                    "code": "FilterAlarm",
                    "id": "0",
                    "triggeredTime": "2019-02-25T08:46:01",
                }
            ],
            "ConfigurationLink": {"href": "/devices/0/configuration"},
            "Diagnosis": {"diagnosisStart": "Ready"},
            "EnergyConsumption": {"saveLocation": "/files/usage.db"},
            "InformationLink": {"href": "/devices/0/information"},
            "Mode": {
                "modes": ["Auto"],
                "options": [
                    "Comode_Off",
                    "Sleep_0",
                    "Autoclean_Off",
                    "Spi_Off",
                    "FilterCleanAlarm_0",
                    "OutdoorTemp_63",
                    "CoolCapa_35",
                    "WarmCapa_40",
                    "UsagesDB_254",
                    "FilterTime_10000",
                    "OptionCode_54458",
                    "UpdateAllow_0",
                    "FilterAlarmTime_500",
                    "Function_15",
                    "Volume_100",
                ],
                "supportedModes": ["Cool", "Dry", "Wind", "Auto"],
            },
            "Operation": {"power": "Off"},
            "Temperatures": [
                {
                    "current": 22.0,
                    "desired": 25.0,
                    "id": "0",
                    "maximum": 30,
                    "minimum": 16,
                    "unit": "Celsius",
                }
            ],
            "Wind": {"direction": "Fix", "maxSpeedLevel": 4, "speedLevel": 0},
            "connected": True,
            "description": "TP6X_RAC_16K",
            "id": "0",
            "name": "RAC",
            "resources": [
                "Alarms",
                "Configuration",
                "Diagnosis",
                "EnergyConsumption",
                "Information",
                "Mode",
                "Operation",
                "Temperatures",
                "Wind",
            ],
            "type": "Air_Conditioner",
            "uuid": "00000000-0000-0000-0000-000000000000",
        }
    ]
}


@register_connection
class ConnectionRequestPrint(ConnectionRequestBase):  # pylint: disable=import-outside-toplevel,abstract-method
    """Dry-run connection engine that prints request details and returns mock data."""

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Return True if this connection type matches 'request_print'."""
        return type_str == CONNECTION_TYPE_REQUEST_PRINT

    def create_updated(self, yaml_node: dict[str, Any] | None) -> "ConnectionRequestPrint":
        c = ConnectionRequestPrint(None, _LOGGER, session=self._session)
        c.load_from_yaml(yaml_node, self)
        return c

    def execute(
        self,
        template: Template | None,
        value: Any,
        device_state: dict[str, Any] | None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        _LOGGER.debug(
            "%s ConnectionRequestPrint (dry-run), execute with params: %s, device_id: %s",
            self.log_prefix,
            self._params,
            device_id,
        )
        return test_json
