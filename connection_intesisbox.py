"""Support for IntesisBox AC devices using WMP v1.9 protocol on TCP port 3310."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import logging
import time
from typing import Any

from homeassistant.const import CONF_HOST, CONF_IP_ADDRESS, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_dumps

from .connection import Connection, register_connection
from .const import CONF_KEEP_ALIVE
from .exceptions import CannotConnect

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_INTESISBOX = "intesisbox"
DEFAULT_INTESISBOX_PORT = 3310
COMMAND_TIMEOUT = 5.0
CONNECT_TIMEOUT = 10.0


@register_connection
class ConnectionIntesisBox(Connection):
    """Native asynchronous connection for IntesisBox WMP v1.9 gateways over TCP."""

    def __init__(
        self,
        config: dict[str, Any],
        logger: logging.Logger,
        hass: HomeAssistant | None = None,
        session: Any = None,
        ip_address: str | None = None,
    ) -> None:
        """Initialize the IntesisBox connection."""
        super().__init__(config, logger, hass, session, ip_address)
        self._host: str | None = (
            ip_address or config.get(CONF_IP_ADDRESS) or config.get(CONF_HOST)
        )
        self._port: int = int(config.get(CONF_PORT, DEFAULT_INTESISBOX_PORT))
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._is_connected: bool = False
        self._is_ready: asyncio.Event = asyncio.Event()
        self._device_status: dict[str, Any] = {}
        self._limits: dict[str, Any] = {}
        self._loop_breakers: list[dict[str, Any]] = []
        self._node_history: dict[str, list[tuple[float, str]]] = {}
        self._device_info_raw: str | None = None
        self._update_callback: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None
        ) = None
        self._cmd_lock = asyncio.Lock()
        self._pending_ack: asyncio.Future[bool] | None = None
        self._keep_alive: bool = True
        self._closing: bool = False
        self._ac_num: int = 1
        self._command_timeout: float = COMMAND_TIMEOUT
        self._connect_timeout: float = CONNECT_TIMEOUT
        self._handshake_timeout: float = 3.0
        self._limits_prefix: str = "_LIMITS_"
        self._handshake_commands: list[str] | None = None

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Return True if this connection handles the given type string."""
        return type_str == CONNECTION_TYPE_INTESISBOX

    @property
    def is_async_native(self) -> bool:
        """Indicate that this connection is native asynchronous."""
        return True

    @property
    def is_push_supported(self) -> bool:
        """Return True as IntesisBox emits CHN push updates on state change."""
        return True

    @property
    def is_available(self) -> bool:
        """Return True if currently connected."""
        return self._is_connected and not self._closing

    @property
    def log_prefix(self) -> str:
        """Generate consistent log prefix."""
        return f"[IntesisBox {self._host}:{self._port}]"

    def load_from_yaml(
        self, node: dict[str, Any] | None, connection_base: Any
    ) -> bool:
        """Load configuration from yaml node dictionary."""
        # pylint: disable=unused-argument
        if not node:
            return False

        if CONF_KEEP_ALIVE in node:
            self._keep_alive = bool(node[CONF_KEEP_ALIVE])

        params = node.get("params", {})
        self._params.update(params)

        if "port" in params:
            try:
                self._port = int(params["port"])
            except (ValueError, TypeError):
                pass

        if "host" in params and params["host"] != "__CLIMATE_IP_HOST__":
            self._host = params["host"]

        if "ac_num" in params:
            try:
                self._ac_num = int(params["ac_num"])
            except (ValueError, TypeError):
                pass

        if "command_timeout" in params:
            try:
                self._command_timeout = float(params["command_timeout"])
            except (ValueError, TypeError):
                pass

        if "connect_timeout" in params:
            try:
                self._connect_timeout = float(params["connect_timeout"])
            except (ValueError, TypeError):
                pass

        if "handshake_timeout" in params:
            try:
                self._handshake_timeout = float(params["handshake_timeout"])
            except (ValueError, TypeError):
                pass

        if "limits_prefix" in params:
            self._limits_prefix = str(params["limits_prefix"])

        raw_handshake = node.get("handshake_commands")
        if isinstance(raw_handshake, list):
            self._handshake_commands = [
                str(cmd).replace("{{ac_num}}", str(self._ac_num))
                for cmd in raw_handshake
                if cmd
            ]
        elif isinstance(raw_handshake, str):
            self._handshake_commands = [
                raw_handshake.replace("{{ac_num}}", str(self._ac_num))
            ]

        loop_breakers_cfg = node.get("loop_breakers") or node.get("loop_breaker")
        if isinstance(loop_breakers_cfg, dict):
            self._loop_breakers = [loop_breakers_cfg]
        elif isinstance(loop_breakers_cfg, list):
            self._loop_breakers = [b for b in loop_breakers_cfg if isinstance(b, dict)]
        else:
            self._loop_breakers = []

        return True

    def _get_handshake_commands(self) -> list[str]:
        """Return configured or default handshake commands."""
        if self._handshake_commands is not None:
            return self._handshake_commands
        return ["ID", "LIMITS:*", f"STATUS,{self._ac_num}", f"GET,{self._ac_num}:*"]

    def create_updated(
        self, yaml_node: dict[str, Any] | None
    ) -> ConnectionIntesisBox:
        """Create an updated copy of this connection instance, or return self if unchanged."""
        if not yaml_node:
            return self

        params = yaml_node.get("params")
        if not isinstance(params, dict) or not params:
            return self

        new_host = params.get("host")
        new_port = params.get("port")
        if (new_host and new_host != self._host) or (
            new_port and int(new_port) != self._port
        ):
            new_conn = ConnectionIntesisBox(
                config=self._config,
                logger=self.logger,
                hass=self._hass,
                session=self._session,
                ip_address=new_host or self._host,
            )
            if self._controller:
                new_conn.set_controller_ref(self._controller)
            new_conn._params = self._params.copy()
            new_conn._loop_breakers = list(self._loop_breakers)
            new_conn._ac_num = self._ac_num
            new_conn._command_timeout = self._command_timeout
            new_conn._connect_timeout = self._connect_timeout
            new_conn._handshake_timeout = self._handshake_timeout
            new_conn._limits_prefix = self._limits_prefix
            if self._handshake_commands is not None:
                new_conn._handshake_commands = list(self._handshake_commands)
            new_conn.load_from_yaml(yaml_node, None)
            return new_conn

        return self

    def set_update_callback(
        self, callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """Register the push notification update callback."""
        self._update_callback = callback
        if not self._update_callback and self._controller:
            cb = getattr(self._controller, "on_push_update_callback", None)
            if callable(cb):
                self._update_callback = cb

    def _ensure_callback_linked(self) -> None:
        """Ensure the coordinator push callback is linked."""
        if not self._update_callback and self._controller:
            cb = getattr(self._controller, "on_push_update_callback", None)
            if callable(cb):
                self.set_update_callback(cb)

    async def async_connect(self) -> None:
        """Establish the TCP socket connection to IntesisBox."""
        if self._is_connected and self._writer and not self._writer.is_closing():
            return

        if not self._host:
            raise CannotConnect("Host IP address is not specified.")

        self._closing = False
        self.logger.debug(
            "%s Connecting to TCP socket on port %s...", self.log_prefix, self._port
        )

        try:
            async with asyncio.timeout(self._connect_timeout):
                self._reader, self._writer = await asyncio.open_connection(
                    self._host, self._port
                )
        except Exception as err:
            self._is_connected = False
            self.logger.warning(
                "%s Failed to connect to IntesisBox at %s:%s (device offline or unreachable): %s",
                self.log_prefix,
                self._host,
                self._port,
                err,
            )
            raise CannotConnect(
                f"Failed to connect to IntesisBox at {self._host}:{self._port}: {err}"
            ) from None

        self._is_connected = True
        self._is_ready.clear()
        self._reader_task = asyncio.create_task(self._reader_loop())

        # Perform initial handshake and capability discovery
        try:
            for cmd in self._get_handshake_commands():
                await self._send_raw(f"{cmd}\r\n")
        except Exception as err:
            self.logger.warning(
                "%s Initial handshake send failed: %s", self.log_prefix, err
            )

        # Wait briefly for initial state synchronization
        try:
            async with asyncio.timeout(self._handshake_timeout):
                await self._is_ready.wait()
        except TimeoutError:
            self.logger.debug(
                "%s Handshake wait timed out, continuing with available state",
                self.log_prefix,
            )

    async def _send_raw(self, payload: str) -> None:
        """Send raw ASCII string terminating with CRLF."""
        if not self._writer or self._writer.is_closing():
            raise CannotConnect("IntesisBox socket is not connected.")
        self._writer.write(payload.encode("ascii", errors="ignore"))
        await self._writer.drain()

    async def _reader_loop(self) -> None:
        """Continuously read lines from IntesisBox socket and parse updates."""
        self.logger.debug(
            "%s Started background TCP reader loop", self.log_prefix
        )  # pragma: no mutate
        try:
            while not self._closing and self._reader:
                line_bytes = await self._reader.readline()
                if not line_bytes:
                    # Connection closed by remote
                    self.logger.warning(
                        "%s Remote closed TCP connection (EOF)", self.log_prefix
                    )  # pragma: no mutate
                    break

                raw_line = line_bytes.decode("ascii", errors="ignore").strip()
                if raw_line:
                    self._process_incoming_line(raw_line)

        except asyncio.CancelledError:
            self.logger.debug(
                "%s Reader task cancelled gracefully", self.log_prefix
            )  # pragma: no mutate
        except Exception as err:
            if not self._closing:
                self.logger.error(
                    "%s Unexpected error in reader loop: %s", self.log_prefix, err
                )  # pragma: no mutate
        finally:
            self._is_connected = False
            self.logger.debug(
                "%s Exited background TCP reader loop", self.log_prefix
            )  # pragma: no mutate

    def _process_incoming_line(self, line: str) -> None:
        """Parse an individual protocol line and update state or futures."""
        self.logger.debug("%s RX: '%s'", self.log_prefix, line)

        # 1. Handle command acknowledgements
        if line == "ACK":
            if self._pending_ack and not self._pending_ack.done():
                self._pending_ack.set_result(True)
            return

        if line == "ERR":
            if self._pending_ack and not self._pending_ack.done():
                self._pending_ack.set_result(False)
            return

        # 2. Handle ID response
        if line.startswith("ID:"):
            self._device_info_raw = line[3:]
            return

        # 3. Handle LIMITS response
        if line.startswith("LIMITS"):
            # Syntax: LIMITS:FANSP,[AUTO,1,2,3,4] or LIMITS,1:FANSP,[AUTO,1,2,3,4]
            if ":" in line:
                _, payload = line.split(":", 1)
                if "," in payload:
                    fn, vals = payload.split(",", 1)
                    clean_fn = fn.strip()
                    clean_vals = vals.strip()
                    self._limits[clean_fn] = clean_vals
                    limits_key = f"{self._limits_prefix}{clean_fn}"
                    self._device_status[limits_key] = clean_vals
                    self._ensure_callback_linked()
                    if self._update_callback:
                        coro = self._update_callback({limits_key: clean_vals})
                        if asyncio.iscoroutine(coro) or hasattr(coro, "__await__"):
                            if self._hass:
                                self._hass.async_create_task(coro)
                            else:
                                asyncio.create_task(coro)
            return

        # 4. Handle State / Push updates (STATUS, CHN, or <ac_num>:<uid>,<val>)
        # Examples:
        # STATUS,1:ONOFF,OFF
        # CHN,1:SETPTEMP,225
        # 1:ONOFF,OFF
        work_line = line
        if work_line.startswith("CHN,"):
            work_line = work_line[4:]
        elif work_line.startswith("STATUS,"):
            work_line = work_line[7:]

        if ":" in work_line:
            _, payload = work_line.split(":", 1)
        else:
            payload = work_line

        updated_dict: dict[str, Any] = {}
        for raw_item in payload.split(";"):
            item = raw_item.strip()
            if "," in item:
                uid, val = item.split(",", 1)
                uid = uid.strip()
                val = val.strip()
                self._device_status[uid] = val
                updated_dict[uid] = val
                if self._loop_breakers:
                    self._check_loop_breakers(uid, val)

        if updated_dict:
            self._is_ready.set()

            # Dispatch push update to coordinator
            self._ensure_callback_linked()
            if self._update_callback:
                try:
                    coro = self._update_callback(updated_dict)
                    if asyncio.iscoroutine(coro) or hasattr(coro, "__await__"):
                        if self._hass and hasattr(self._hass, "async_create_task"):
                            self._hass.async_create_task(coro)
                        else:
                            asyncio.create_task(coro)
                except Exception as ex:
                    self.logger.error(
                        "%s Failed dispatching push update: %s",
                        self.log_prefix,
                        ex,
                    )

    def _check_loop_breakers(self, uid: str, val: str) -> None:
        """Check all registered loop breakers for the updated state node."""
        for rule in self._loop_breakers:
            target_node = rule.get("node") or rule.get("state_node")
            if target_node == uid:
                self._evaluate_oscillation_rule(uid, val, rule)

    def _evaluate_oscillation_rule(
        self, uid: str, val: str, rule: dict[str, Any]
    ) -> None:
        """Evaluate oscillation for a specific state node against a YAML rule."""
        fallback_val = str(rule.get("fallback_value", "AUTO"))
        threshold = int(rule.get("threshold", 3))
        window_seconds = float(rule.get("window_seconds", 3.0))
        prune_values = [str(pv) for pv in rule.get("prune_values", [])]

        now = time.monotonic()
        history = self._node_history.setdefault(uid, [])
        history.append((now, val))
        self._node_history[uid] = [
            (t, v) for t, v in history if now - t <= window_seconds
        ]
        active_hist = self._node_history[uid]

        if len(active_hist) >= threshold + 1:  # pragma: no mutate  # Guard: len >= threshold + 1 is required for alternations >= threshold
            distinct_values = set(v for _, v in active_hist)
            if len(distinct_values) == 2:
                bad_val = None
                other_val = None
                prune_matches = [v for v in distinct_values if v in prune_values]
                if prune_matches:
                    bad_val = prune_matches[0]
                    other_val = next(v for v in distinct_values if v != bad_val)
                elif fallback_val in distinct_values:
                    bad_val = next(v for v in distinct_values if v != fallback_val)
                    other_val = fallback_val
                else:
                    bad_val = active_hist[-1][1]
                    other_val = next(v for v in distinct_values if v != bad_val)

                if bad_val and other_val:  # pragma: no mutate  # Equivalent: both values guaranteed non-empty from distinct_values
                    alternations = 0
                    for i in range(1, len(active_hist)):
                        if active_hist[i][1] != active_hist[i - 1][1]:
                            alternations += 1

                    if alternations >= threshold:
                        self.logger.warning(
                            "%s Loop breaker triggered for node '%s': oscillation "
                            "detected between '%s' and '%s'.",
                            self.log_prefix,
                            uid,
                            bad_val,
                            other_val,
                        )
                        self._node_history[uid].clear()
                        if self._hass and hasattr(self._hass, "async_create_task"):
                            self._hass.async_create_task(
                                self._async_execute_loop_break(
                                    uid, bad_val, fallback_val, rule
                                )
                            )
                        else:
                            asyncio.create_task(
                                self._async_execute_loop_break(
                                    uid, bad_val, fallback_val, rule
                                )
                            )

    async def _async_execute_loop_break(
        self, uid: str, bad_val: str, fallback_val: str, rule: dict[str, Any]
    ) -> None:
        """Execute the loop breaker actions defined in the YAML rule."""
        try:
            # 1. Force fallback command (e.g. SET,1:FANSP,AUTO)
            fallback_cmd = rule.get("fallback_command")
            if fallback_cmd:
                await self._send_raw(fallback_cmd + "\r\n")

            # 2. Check if bad_val is eligible for auto-pruning
            prune_values = [str(pv) for pv in rule.get("prune_values", [])]
            prune_template = rule.get("prune_command_template")
            new_limits_str = None

            if bad_val in prune_values and prune_template:
                current_raw = self._limits.get(
                    uid, ""
                )  # pragma: no mutate  # Equivalent: empty string vs None in bool check
                if current_raw:
                    cleaned = current_raw.strip("[]")
                    items = [
                        item.strip() for item in cleaned.split(",") if item.strip()
                    ]
                    new_items = [item for item in items if item != bad_val]
                    new_limits_str = f"[{','.join(new_items)}]"
                    self.logger.info(
                        "%s Pruning bad value '%s' from %s limits: %s -> %s",
                        self.log_prefix,
                        bad_val,
                        uid,
                        current_raw,
                        new_limits_str,
                    )
                    rendered_prune = prune_template.replace(
                        "{{new_limits}}", new_limits_str
                    )
                    await self._send_raw(rendered_prune + "\r\n")
                    self._limits[uid] = new_limits_str
                    self._device_status[f"{self._limits_prefix}{uid}"] = new_limits_str

            # 3. Update device status and notify coordinator
            self._device_status[uid] = fallback_val
            update_payload: dict[str, Any] = {uid: fallback_val}
            if new_limits_str:
                update_payload[f"{self._limits_prefix}{uid}"] = new_limits_str

            self._ensure_callback_linked()
            if self._update_callback:
                coro = self._update_callback(update_payload)
                if asyncio.iscoroutine(coro) or hasattr(coro, "__await__"):
                    if self._hass and hasattr(self._hass, "async_create_task"):
                        self._hass.async_create_task(coro)
                    else:
                        asyncio.create_task(coro)
        except Exception as err:
            self.logger.error("%s Error executing loop breaker: %s", self.log_prefix, err)

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
        """Execute an asynchronous command or query against IntesisBox."""
        # pylint: disable=unused-argument
        self._ensure_callback_linked()
        await self.async_connect()

        if _is_poll:
            # Polling: Request fresh status dump and return current cache
            poll_cmd = (
                data.strip()
                if (data and isinstance(data, str) and data.strip())
                else f"STATUS,{self._ac_num}"
            )
            try:
                await self._send_raw(f"{poll_cmd}\r\n")
            except Exception as err:
                self.logger.debug(
                    "%s Poll status query error: %s", self.log_prefix, err
                )
            return json_dumps(self._device_status), {}

        if not data:
            return json_dumps(self._device_status), {}

        # Execute command(s) with sequential ACK verification
        async with self._cmd_lock:
            lines = [ln.strip() for ln in data.splitlines() if ln.strip()]
            for cmd in lines:
                self._pending_ack = asyncio.get_running_loop().create_future()
                self.logger.debug("%s TX: '%s'", self.log_prefix, cmd)
                await self._send_raw(cmd + "\r\n")

                try:
                    async with asyncio.timeout(self._command_timeout):
                        ack_ok = await self._pending_ack
                    if not ack_ok:
                        raise CannotConnect(
                            f"Command '{cmd}' rejected with ERR by IntesisBox"
                        )
                    # Confirmed setting command: update local status cache immediately
                    # Standard syntax: <ACTION>,<AC>:<UID>,<VAL> (e.g. SET,1:FANSP,AUTO)
                    if ":" in cmd:
                        _, payload = cmd.split(":", 1)
                        if "," in payload:
                            uid, val = payload.split(",", 1)
                            self._device_status[uid.strip()] = val.strip()
                except TimeoutError as err:
                    raise CannotConnect(
                        f"Timed out waiting for ACK from IntesisBox for '{cmd}'"
                    ) from err
                finally:
                    self._pending_ack = None

        return json_dumps(self._device_status), {}

    def execute(
        self,
        template: Any,
        value: Any,
        device_state: Any,
        device_id: str | None = None,
    ) -> Any:
        """Synchronous execute not supported for async-native IntesisBox."""
        raise NotImplementedError(
            "ConnectionIntesisBox is async-native. Use async_execute."
        )

    async def stop_listening(self) -> None:
        """Stop background tasks gracefully."""
        self._closing = True
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None

    async def close(self) -> None:
        """Cleanly terminate TCP connection and clean up resources."""
        await self.stop_listening()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None
        self._is_connected = False
        self._is_ready.clear()
