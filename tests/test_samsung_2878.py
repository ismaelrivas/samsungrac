"""Unit tests for Samsung port 2878 connection handler (samsung_2878.py)."""

import asyncio
import contextlib
import inspect
import os
from pathlib import Path
import socket
import ssl
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

import jinja2
import pytest

from custom_components.climate_ip import samsung_2878 as samsung_module
from custom_components.climate_ip.const import (
    CONF_CERT,
    GLOBAL_HTTP_TIMEOUT,
    PROTOCOL_2878_DPLUG,
    PROTOCOL_2878_DRC,
    PROTOCOL_2878_INVALIDATE,
    PROTOCOL_2878_POWER_ID,
    PROTOCOL_2878_VALUE_ON,
)
from custom_components.climate_ip.exceptions import AuthError, CannotConnect
from custom_components.climate_ip.helpers import safe_xml_to_dict
from custom_components.climate_ip.samsung_2878 import (
    CONF_DUID,
    DEFAULT_CERT_PATH,
    DEFAULT_CIPHERS,
    DEFAULT_NETWORK_DIAGNOSTIC,
    INITIAL_RECONNECT_DELAY,
    MAX_RECONNECT_DELAY,
    NO_CERT_CIPHERS,
    OFFLINE_PANIC_MSG,
    SUITE_A,
    SUITE_C,
    SUITE_D,
    ConnectionConfig,
    ConnectionSamsung2878,
    _create_keepalive_socket,
    _resolve_cert_path,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN


def _make_safe_writer() -> MagicMock:
    """Return an AsyncIO StreamWriter mock safe for close/drain/SSL inspection."""
    writer = MagicMock()
    writer.is_closing.return_value = False
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    writer.close = MagicMock()
    ssl_obj = MagicMock()
    ssl_obj.version.return_value = "TLSv1.2"
    ssl_obj.cipher.return_value = ("AES256-SHA", "TLSv1.2", 256)
    writer.get_extra_info.side_effect = lambda key: (
        ssl_obj if key == "ssl_object" else None
    )
    return writer


def _wire_inline_executor(conn: ConnectionSamsung2878) -> MagicMock:
    """Configure controller.hass.async_add_executor_job to run functions inline."""
    mock_hass = MagicMock()
    mock_hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)
    )
    mock_controller = MagicMock(spec=["hass", "unique_id", "log_prefix"])
    mock_controller.hass = mock_hass
    mock_controller.unique_id = "test_uid"
    mock_controller.log_prefix = "[test_uid]"
    conn._controller = mock_controller
    return mock_hass


class _FakeStreamReader:
    """Deterministic StreamReader stub that yields queued chunks or raises."""

    def __init__(self, sequence: list[bytes | Exception], *, eof: bool = False) -> None:
        self.sequence = sequence
        self.index = 0
        self.eof = eof
        self.read_sizes: list[int] = []

    def at_eof(self) -> bool:
        return self.eof

    async def read(self, n: int = -1) -> bytes:
        self.read_sizes.append(n)
        if self.index < len(self.sequence):
            item = self.sequence[self.index]
            self.index += 1
            if isinstance(item, Exception):
                raise item
            return item
        return b""


@pytest.fixture
def connection() -> ConnectionSamsung2878:
    """Create a default ConnectionSamsung2878 instance with mocked logger."""
    hass_config = {
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_TOKEN: "test_token",
    }
    conn = ConnectionSamsung2878(hass_config, MagicMock())
    conn._socket_timeout = 30.0
    return conn


# ============================================================================
# FAST-FAIL GUARDS (executed first to prevent mutant hangs)
# ============================================================================


def test_00a_config_and_helper_primitives() -> None:
    """Verify ConnectionConfig, _resolve_cert_path, and _create_keepalive_socket."""
    empty_cfg = ConnectionConfig()
    assert empty_cfg.host is None
    assert empty_cfg.port is None
    assert empty_cfg.token is None
    assert empty_cfg.cert is None
    assert empty_cfg.duid is None

    cfg = ConnectionConfig(
        host="192.168.1.100",
        port=2878,
        token="my_token",
        cert="my_cert.pem",
        duid="my_duid",
    )
    assert cfg.host == "192.168.1.100"
    assert cfg.port == 2878
    assert cfg.token == "my_token"
    assert cfg.cert == "my_cert.pem"
    assert cfg.duid == "my_duid"

    assert _resolve_cert_path("") == ""
    assert _resolve_cert_path("/abs/path/cert.pem") == "/abs/path/cert.pem"
    expected_rel = str(Path(os.path.dirname(samsung_module.__file__)) / "local.pem")
    assert _resolve_cert_path("local.pem") == expected_rel

    mock_sock = MagicMock()
    with patch("socket.socket", return_value=mock_sock) as mock_sock_cls:
        res_sock = _create_keepalive_socket()
    assert res_sock is mock_sock
    mock_sock_cls.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
    mock_sock.setblocking.assert_called_once_with(False)
    opts = [c.args for c in mock_sock.setsockopt.call_args_list]
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in opts
    if hasattr(socket, "TCP_KEEPIDLE"):
        assert (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60) in opts
    if hasattr(socket, "TCP_KEEPINTVL"):
        assert (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10) in opts
    if hasattr(socket, "TCP_KEEPCNT"):
        assert (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3) in opts


def test_00b_init_properties_and_callbacks() -> None:
    """Verify constructor defaults, properties, controller linking, and sync execute."""
    conn = ConnectionSamsung2878({}, None)
    assert conn._controller is None
    assert conn._hass is None
    assert conn._reader is None
    assert conn._writer is None
    assert conn._read_task is None
    assert conn._manager_task is None
    assert conn._update_callback is None
    assert conn._pending_future is None
    assert conn._last_successful_config is None
    assert conn._last_icmp_diagnostic is None
    assert conn._power_template is None
    assert conn._connection_init_template is None
    assert conn._socket_timeout == float(GLOBAL_HTTP_TIMEOUT) + 10.0
    assert conn._reconnect_delay == INITIAL_RECONNECT_DELAY
    assert conn._reconnect_retries == 0
    assert conn._is_available is True
    assert conn.is_available is True
    assert conn._initial_connection_done is False
    assert conn._persistent_offline_err_logged is False
    assert conn._device_status == {}
    assert isinstance(conn._cmd_queue, asyncio.Queue)
    assert not conn._is_ready.is_set()
    assert conn.is_async_native is True
    assert conn.is_push_supported is True
    assert conn.match_type("samsung_2878") is True
    assert conn.match_type("other") is False

    conn._is_available = False
    assert conn.is_available is False

    # set_controller_ref & log_prefix fallbacks
    mock_ctrl = MagicMock()
    mock_ctrl.unique_id = "uid_1"
    mock_ctrl.log_prefix = "[uid_1]"
    mock_ctrl.hass = MagicMock()
    conn.set_controller_ref(mock_ctrl)
    assert conn._controller is mock_ctrl
    assert conn._hass is mock_ctrl.hass
    assert conn.log_prefix == "[uid_1]"

    mock_ctrl.unique_id = ""
    conn._cfg.duid = "AA112233445566"
    assert conn.log_prefix == "[445566]"
    assert (
        conn._poll_command
        == '<Request Type="DeviceState" DUID="AA112233445566"></Request>\n'
    )

    conn.set_controller_ref(None)
    assert conn._controller is None
    assert conn._hass is mock_ctrl.hass
    conn._cfg.duid = None
    assert conn.log_prefix == "[NO_ID]"
    conn._cfg = None  # type: ignore[assignment]
    assert conn.log_prefix == "[NO_ID]"

    # _ensure_callback_linked edge cases
    conn._cfg = ConnectionConfig()
    conn._update_callback = None
    conn._ensure_callback_linked()  # _controller is None -> no error

    conn._controller = object()
    with pytest.raises(AttributeError):
        conn._ensure_callback_linked()

    no_cb_ctrl = MagicMock()
    no_cb_ctrl.on_push_update_callback = None
    conn._controller = no_cb_ctrl
    conn._ensure_callback_linked()
    assert conn._update_callback is None

    push_cb = AsyncMock()
    no_cb_ctrl.on_push_update_callback = push_cb
    conn._ensure_callback_linked()
    assert conn._update_callback is push_cb

    custom_cb = AsyncMock()
    conn.set_update_callback(custom_cb)
    conn._ensure_callback_linked()
    assert conn._update_callback is custom_cb

    with pytest.raises(
        NotImplementedError,
        match=r"^ConnectionSamsung2878 is async-native\. Use async_execute\.$",
    ):
        conn.execute(None, None, None)


def test_00c_configuration_and_yaml_loading() -> None:
    """Verify update_configuration_from_hass, load_from_yaml, and create_updated."""
    mock_hass = MagicMock()
    hass_config: dict[str, Any] = {
        CONF_MAC: "BC:8C:CD:5B:54:F6",
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_TOKEN: "REAL_SECURE_TOKEN_XYZ",
        CONF_CERT: "test.pem",
        CONF_PORT: 2878,
        "preferred_connection": {
            "cert": "preferred.pem",
            "cipher_name": "TEST_CIPHER",
            "verify_mode": 0,
        },
    }
    conn = ConnectionSamsung2878(hass_config, MagicMock(), hass=mock_hass)
    assert conn._cfg.duid == "BC8CCD5B54F6"
    assert ":" not in conn._cfg.duid
    assert conn._cfg.cert == _resolve_cert_path("test.pem")
    assert conn._last_successful_config is not None
    assert conn._last_successful_config["cipher_name"] == "TEST_CIPHER"
    assert conn._last_successful_config["cert"] == _resolve_cert_path("preferred.pem")

    # Verify stored _ssl_config_2878 takes precedence over preferred_connection
    conn._ssl_context_cache[("a", "b", 0)] = MagicMock()
    conn._config["_ssl_config_2878"] = {
        "cert": "stored.pem",
        "cipher_name": "STORED_CIPHER",
    }
    conn.update_configuration_from_hass({"ip_address": "1.1.1.1"})
    assert conn._ssl_context_cache == {}
    assert conn._cfg.port == 2878
    assert conn._last_successful_config == {
        "cert": _resolve_cert_path("stored.pem"),
        "cipher_name": "STORED_CIPHER",
    }
    conn._config.pop("_ssl_config_2878")

    # Passing None preserves _cfg and _ssl_context_cache while resetting last config
    conn._ssl_context_cache[("keep", "c", 0)] = MagicMock()
    conn.update_configuration_from_hass(None)
    assert len(conn._ssl_context_cache) == 1
    assert conn._last_successful_config is None

    # Exact argument order to format_placeholders and .get() defaults
    mock_dict = MagicMock()
    mock_dict.get.side_effect = lambda k, default=None: (
        default if k in {CONF_PORT, "preferred_connection"} else f"val_{k}"
    )
    with patch(
        "custom_components.climate_ip.samsung_2878.format_placeholders",
        return_value="formatted_tok",
    ) as mock_fmt:
        conn.update_configuration_from_hass(mock_dict)
    mock_dict.get.assert_any_call("device_id")
    mock_dict.get.assert_any_call(CONF_PORT, 2878)
    mock_fmt.assert_called_once_with(
        "val_token", "val_token", "val_ip_address", "val_device_id", "val_mac"
    )

    # Full YAML load & placeholder override
    conn.update_configuration_from_hass(hass_config)
    yaml_node = {
        "params": {
            "connection_template": '<Request Type="AuthToken"><User Token="{{token}}" /></Request>',
            "power_template": "<Power/>",
            "host": "__CLIMATE_IP_HOST__",
            "token": "__CLIMATE_IP_TOKEN__",
        }
    }
    assert conn.load_from_yaml(yaml_node, None) is True
    assert conn._connection_init_template is not None
    assert conn._connection_init_template.hass is mock_hass
    assert conn._power_template is not None
    assert conn._power_template.hass is mock_hass
    assert conn._params[CONF_TOKEN] == "REAL_SECURE_TOKEN_XYZ"
    assert conn._params[CONF_IP_ADDRESS] == "192.168.1.100"
    assert conn._params[CONF_DUID] == "BC8CCD5B54F6"
    rendered = jinja2.Template(conn._connection_init_template.template).render(
        **conn._params
    )
    assert 'Token="REAL_SECURE_TOKEN_XYZ"' in rendered

    # create_updated delegates to load_from_yaml(yaml_node, self)
    with patch.object(conn, "load_from_yaml") as mock_load:
        assert conn.create_updated(yaml_node) is conn
        mock_load.assert_called_once_with(yaml_node, conn)

    # Validation failure cases when connection_base is None
    assert conn.load_from_yaml(None, None) is False
    assert conn.load_from_yaml({}, None) is False
    assert conn.load_from_yaml({"other_key": 1}, None) is False
    assert conn.load_from_yaml({"params": {}}, None) is False

    tpl_only = {"params": {"connection_template": "<Auth/>"}}
    for bad_cfg in (
        {CONF_IP_ADDRESS: None, CONF_TOKEN: "tok", CONF_MAC: "AA:BB:CC:DD:EE:FF"},
        {CONF_IP_ADDRESS: "1.2.3.4", CONF_TOKEN: None, CONF_MAC: "AA:BB:CC:DD:EE:FF"},
        {CONF_IP_ADDRESS: "1.2.3.4", CONF_TOKEN: "tok", CONF_MAC: None},
        {CONF_IP_ADDRESS: "1.2.3.4", CONF_TOKEN: "tok", CONF_MAC: ""},
        {CONF_IP_ADDRESS: "1.2.3.4", CONF_TOKEN: "tok", CONF_MAC: "   "},
    ):
        bad_conn = ConnectionSamsung2878(bad_cfg, MagicMock(), hass=mock_hass)
        assert bad_conn.load_from_yaml(tpl_only, None) is False

    # With connection_base provided: copies base _params and tolerates _cfg=None / missing template
    base_conn = ConnectionSamsung2878(hass_config, MagicMock(), hass=mock_hass)
    base_conn._params["inherited"] = "yes"
    child_conn = ConnectionSamsung2878({}, MagicMock(), hass=mock_hass)
    child_conn._cfg = None  # type: ignore[assignment]
    assert child_conn.load_from_yaml({"params": {"extra": 1}}, base_conn) is True
    assert child_conn._params["inherited"] == "yes"
    assert child_conn._params["extra"] == 1


def test_00d_build_ssl_attempts_ordering(connection: ConnectionSamsung2878) -> None:
    """Verify SSL strategy generation and preferred configuration prioritization."""
    # 1. Default strategies (no user cert)
    connection._cfg.cert = None
    connection._last_successful_config = None
    default_attempts = connection._build_ssl_attempts()
    assert len(default_attempts) == 8
    assert default_attempts[0] == (
        None,
        ssl.CERT_NONE,
        SUITE_D,
        "No Certificate (Default)",
    )
    assert default_attempts[4] == (
        DEFAULT_CERT_PATH,
        ssl.CERT_NONE,
        SUITE_A,
        "Default Certificate (Fallback)",
    )
    assert [a[2] for a in default_attempts[:4]] == list(NO_CERT_CIPHERS)
    assert [a[2] for a in default_attempts[4:]] == list(DEFAULT_CIPHERS)

    # 2. User certificate strategies
    connection._cfg.cert = "/custom/ac.pem"
    user_attempts = connection._build_ssl_attempts()
    assert len(user_attempts) == 12
    assert user_attempts[0] == (
        "/custom/ac.pem",
        ssl.CERT_REQUIRED,
        SUITE_A,
        "User Cert (Strict Verify)",
    )
    assert user_attempts[4] == (
        "/custom/ac.pem",
        ssl.CERT_NONE,
        SUITE_A,
        "User Cert (No Verify)",
    )
    assert user_attempts[8] == (
        None,
        ssl.CERT_NONE,
        SUITE_D,
        "No Certificate (Fallback)",
    )

    # 3. Preferred config with specific cipher moves exact match to index 0 without duplicates
    connection._cfg.cert = None
    connection._last_successful_config = {
        "cert": DEFAULT_CERT_PATH,
        "verify_mode": ssl.CERT_NONE,
        "cipher_name": SUITE_D[1],
    }
    reordered = connection._build_ssl_attempts()
    assert len(reordered) == 8
    assert reordered[0][:3] == (DEFAULT_CERT_PATH, ssl.CERT_NONE, SUITE_D)

    # 4. Preferred config with empty cipher_name matches all ciphers for that cert/verify pair
    connection._last_successful_config = {
        "cert": DEFAULT_CERT_PATH,
        "verify_mode": ssl.CERT_NONE,
        "cipher_name": None,
    }
    reordered_all = connection._build_ssl_attempts()
    assert len(reordered_all) == 8
    assert all(a[0] == DEFAULT_CERT_PATH for a in reordered_all[:4])


async def test_01a_io_timeouts_and_write_data(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify strict timeouts, chunk sizes, and _write_data error paths."""
    connection._reader = _FakeStreamReader([b"chunk", b""])
    mock_timeout_ctx = MagicMock()
    mock_timeout_ctx.__aenter__ = AsyncMock()
    mock_timeout_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.timeout",
            return_value=mock_timeout_ctx,
        ) as mock_timeout,
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        res = await connection._read_full_response()
        assert res == "chunk"
        assert connection._reader.read_sizes == [4096, 4096]
        mock_timeout.assert_called_once_with(10.0)

        mock_timeout.reset_mock()
        await connection._read_full_response(timeout_sec=3.5)
        mock_timeout.assert_called_once_with(3.5)

    # _write_data: None writer and closing writer
    connection._writer = None
    with pytest.raises(CannotConnect, match="not available for writing"):
        await connection._write_data("payload")

    closing_writer = _make_safe_writer()
    closing_writer.is_closing.return_value = True
    connection._writer = closing_writer
    with pytest.raises(CannotConnect, match="not available for writing"):
        await connection._write_data("payload")

    # _write_data: happy path
    connection._writer = _make_safe_writer()
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.timeout",
        return_value=mock_timeout_ctx,
    ) as mock_timeout:
        assert await connection._write_data("<Request/>") is True
        connection._writer.write.assert_called_once_with(b"<Request/>")
        connection._writer.drain.assert_awaited_once()
        mock_timeout.assert_called_once_with(5.0)

    # _write_data: OSError / TimeoutError closes connection and raises CannotConnect
    for err in (OSError("Network drop"), TimeoutError("Drain timeout")):
        connection._writer = _make_safe_writer()
        connection._writer.drain.side_effect = err
        with (
            patch(
                "custom_components.climate_ip.samsung_2878.asyncio.timeout",
                return_value=mock_timeout_ctx,
            ),
            pytest.raises(CannotConnect, match="Failed to write to connection"),
        ):
            await connection._write_data("test")
        assert connection._writer is None


async def test_01b_read_full_response_framing_and_errors(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify _read_full_response framing markers, decoding, timeouts, and OSError."""
    connection._close_connection = AsyncMock()

    # None reader vs at_eof reader
    connection._reader = None
    assert await connection._read_full_response() is None

    connection._reader = _FakeStreamReader([b"<Ignored/>"], eof=True)
    assert await connection._read_full_response() is None

    # Empty EOF -> None and closes connection; Partial + EOF -> decoded and closes
    connection._reader = _FakeStreamReader([b""])
    assert await connection._read_full_response(timeout_sec=1.0) is None
    connection._close_connection.assert_awaited_once()

    connection._close_connection.reset_mock()
    connection._reader = _FakeStreamReader([b"A", b"B", b""])
    assert await connection._read_full_response(timeout_sec=1.0) == "AB"
    connection._close_connection.assert_awaited_once()

    # Invalid UTF-8 bytes ignored without crashing
    connection._reader = _FakeStreamReader([b"Valid\xff\xfe", b""])
    res_utf8 = await connection._read_full_response(timeout_sec=1.0)
    assert res_utf8 is not None and "Valid" in res_utf8

    # Immediate return on each end marker (second read would explode if loop continued)
    markers = [
        (f"  {PROTOCOL_2878_DPLUG}\n".encode(), PROTOCOL_2878_DPLUG),
        (b"<Data></Response>\n", "<Data></Response>"),
        (b"<Data></Update>\n", "<Data></Update>"),
        (b"  <SelfClose/>  \n", "<SelfClose/>"),
    ]
    for frame, expected in markers:
        connection._reader = _FakeStreamReader([frame, RuntimeError("Must not read")])
        assert await connection._read_full_response(timeout_sec=1.0) == expected

    # TimeoutError & IncompleteReadError return buffered text (or None when empty)
    connection._reader = _FakeStreamReader([TimeoutError()])
    assert await connection._read_full_response() is None

    connection._reader = _FakeStreamReader([b"partial_data", TimeoutError()])
    assert await connection._read_full_response() == "partial_data"

    connection._reader = _FakeStreamReader(
        [b"part_inc", asyncio.IncompleteReadError(b"part_inc", None)]
    )
    assert await connection._read_full_response() == "part_inc"

    # OSError closes connection and discards partial buffer (returns None)
    connection._close_connection.reset_mock()
    connection._reader = _FakeStreamReader([b"discarded", OSError("reset")])
    assert await connection._read_full_response() is None
    connection._close_connection.assert_awaited_once()


async def test_01c_connection_manager_task_and_queue_guards(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify fast-fail task creation and dispatch in _connection_manager."""
    # 1. Read task creation with 8192 buffer size
    connection._writer = _make_safe_writer()
    connection._reader = MagicMock()
    connection._reader.read = AsyncMock(return_value=b"data")

    mock_task: asyncio.Future[bytes] = asyncio.Future()

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.create_task",
            side_effect=lambda c: (
                c.close() if hasattr(c, "close") else None,
                mock_task,
            )[1],
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.wait",
            side_effect=asyncio.CancelledError(),
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, asyncio.CancelledError()],
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(connection._connection_manager(), timeout=0.05)

    connection._reader.read.assert_called_once_with(8192)
    assert mock_task.cancelled()

    # 2. Queue task creation, queue_task reset (line 1137), and dispatch on FIRST_COMPLETED
    connection._writer = _make_safe_writer()
    connection._reader = MagicMock()
    connection._cmd_queue = asyncio.Queue()
    cmd_future: asyncio.Future[bool] = asyncio.Future()
    await connection._cmd_queue.put(("<TestCmd1/>", cmd_future))
    await connection._cmd_queue.put(("<TestCmd2/>", cmd_future))

    async def _pending_read(_size: int) -> bytes:
        fut: asyncio.Future[bytes] = asyncio.Future()
        return await fut

    connection._reader.read = AsyncMock(side_effect=_pending_read)

    with (
        patch.object(
            connection,
            "_process_command_queue",
            new_callable=AsyncMock,
            side_effect=[None, asyncio.CancelledError()],
        ) as mock_cmd,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, asyncio.CancelledError()],
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(connection._connection_manager(), timeout=0.05)

    assert mock_cmd.await_count == 2
    assert mock_cmd.call_args.args[0] is not None

    # 3. Read completes while queue_task is still pending -> _process_command_queue NOT called
    connection._writer = _make_safe_writer()
    connection._reader = MagicMock()
    connection._pending_future = None
    idle_r_task: asyncio.Future[bytes] = asyncio.Future()
    idle_q_task: asyncio.Future[Any] = asyncio.Future()
    spawned = [idle_r_task, idle_q_task]

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.create_task",
            side_effect=lambda c: (
                c.close() if hasattr(c, "close") else None,
                spawned.pop(0) if spawned else idle_r_task,
            )[1],
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.wait",
            new_callable=AsyncMock,
            return_value=({idle_r_task}, {idle_q_task}),
        ),
        patch.object(
            connection, "_process_command_queue", new_callable=AsyncMock
        ) as mock_cmd_idle,
        patch.object(
            connection,
            "_process_read_queue",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, asyncio.CancelledError()],
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(connection._connection_manager(), timeout=0.05)

    mock_cmd_idle.assert_not_called()
    assert idle_q_task.cancelled()


# ============================================================================
# LIFECYCLE & DIAGNOSTICS
# ============================================================================


async def test_lifecycle_start_stop_and_track_task(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify start_listening, _track_task, stop_listening, and _close_connection."""
    connection._ensure_callback_linked = MagicMock()

    # _track_task registers task and discard callback
    sentinel_coro: Any = MagicMock()
    mock_tracked = MagicMock()
    with patch("asyncio.create_task", return_value=mock_tracked) as mock_create:
        returned = connection._track_task(sentinel_coro)
    assert returned is mock_tracked
    assert mock_tracked in connection._background_tasks
    mock_tracked.add_done_callback.assert_called_once_with(
        connection._background_tasks.discard
    )
    connection._background_tasks.clear()
    mock_create.assert_called_once_with(sentinel_coro)

    # start_listening when already running preserves retries and task
    running_task = MagicMock()
    running_task.done.return_value = False
    connection._manager_task = running_task
    connection._reconnect_retries = 99
    connection.start_listening()
    assert connection._reconnect_retries == 99
    assert connection._manager_task is running_task
    connection._ensure_callback_linked.assert_called_once()

    # start_listening when None or done resets retries and creates manager task
    for initial_state in (None, MagicMock(done=MagicMock(return_value=True))):
        connection._manager_task = initial_state
        connection._reconnect_retries = 42
        with (
            patch("asyncio.create_task", return_value="new_mgr_task") as mock_ct,
            patch.object(
                connection,
                "_connection_manager",
                new=MagicMock(return_value="mgr_coro"),
            ),
        ):
            connection.start_listening()
        assert connection._reconnect_retries == 0
        assert connection._manager_task == "new_mgr_task"
        mock_ct.assert_called_once_with("mgr_coro")

    # stop_listening cancels real sleeping manager task (hits except CancelledError)
    # and cancels only unfinished background tasks
    connection._manager_task = asyncio.create_task(asyncio.sleep(60))
    await asyncio.sleep(0)
    task_done = MagicMock()
    task_done.done.return_value = True
    task_pending = MagicMock()
    task_pending.done.return_value = False
    connection._background_tasks = {task_done, task_pending}

    with patch.object(
        connection, "_close_connection", new_callable=AsyncMock
    ) as mock_close:
        await connection.stop_listening()

    assert connection._manager_task is None
    task_pending.cancel.assert_called_once()
    task_done.cancel.assert_not_called()
    assert len(connection._background_tasks) == 0
    mock_close.assert_awaited_once()


async def test_close_connection_edge_cases(connection: ConnectionSamsung2878) -> None:
    """Verify _close_connection idempotency, read_task cancellation, and writer errors."""
    # 1. Both None -> early return without clearing _is_ready
    connection._is_ready.set()
    connection._writer = None
    connection._read_task = None
    await connection._close_connection()
    assert connection._is_ready.is_set()

    # 2. Only _read_task set (unfinished) -> cancels it and clears _is_ready
    pending_read = asyncio.create_task(asyncio.sleep(60))
    await asyncio.sleep(0)
    connection._read_task = pending_read
    await connection._close_connection()
    assert not connection._is_ready.is_set()
    assert pending_read.cancelled()
    assert connection._read_task is None

    # 3. Already done _read_task is not cancelled again; writer TimeoutError & OSError handled
    done_read = MagicMock()
    done_read.done.return_value = True
    connection._read_task = done_read
    writer = _make_safe_writer()
    writer.wait_closed.side_effect = TimeoutError()
    connection._writer = writer
    connection._reader = MagicMock()
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.timeout",
        wraps=asyncio.timeout,
    ) as mock_close_to:
        await connection._close_connection()
    mock_close_to.assert_called_once_with(2.0)
    done_read.cancel.assert_not_called()
    writer.close.assert_called_once()
    assert connection._writer is None
    assert connection._reader is None

    writer_err = _make_safe_writer()
    writer_err.close.side_effect = ConnectionResetError("reset")
    connection._writer = writer_err
    async with connection._close_lock:
        queued_close = asyncio.create_task(connection._close_connection())
        await asyncio.sleep(0)
    await queued_close
    assert connection._writer is None


def test_get_diagnostics_variants(connection: ConnectionSamsung2878) -> None:
    """Verify diagnostics privacy masking and reachability defaults."""
    connection._is_ready.clear()
    connection._reconnect_retries = 3
    connection._is_available = False
    connection._last_successful_config = None
    connection._last_icmp_diagnostic = None

    diag = connection.get_diagnostics()
    assert diag == {
        "is_connected": False,
        "reconnect_retries": 3,
        "is_available": False,
        "last_successful_config": None,
        "network_reachability": {"is_reachable": None, "status": "not_checked_yet"},
    }
    diag["network_reachability"]["status"] = "mutated"
    assert DEFAULT_NETWORK_DIAGNOSTIC["status"] == "not_checked_yet"

    # Populated SSL config strips directory path; custom ICMP preserved
    connection._is_ready.set()
    connection._last_successful_config = {
        "cert": "/secret/dir/ac_cert.pem",
        "cipher_name": "AES-256-CBC",
    }
    custom_icmp = {"is_reachable": True, "avg_rtt_ms": 1.5, "status": "alive"}
    connection._last_icmp_diagnostic = custom_icmp
    diag2 = connection.get_diagnostics()
    assert diag2["is_connected"] is True
    assert diag2["last_successful_config"] == {
        "cert_filename": "ac_cert.pem",
        "cipher_name": "AES-256-CBC",
    }
    assert diag2["network_reachability"] == custom_icmp

    # Empty cert omits cert_filename
    connection._last_successful_config = {"cert": ""}
    assert connection.get_diagnostics()["last_successful_config"] == {}


# ============================================================================
# XML PARSING & STATE UPDATES
# ============================================================================


async def test_parse_and_update_state_single_and_guards(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify XML guard clauses, executor offloading, and single-Response attribute extraction."""
    # Empty XML returns immediately before touching controller
    assert await connection._parse_and_update_state("") == (False, False, None)

    # Missing controller/hass raises RuntimeError
    connection._controller = None
    with pytest.raises(
        RuntimeError,
        match="Home Assistant instance is required for parsing XML securely",
    ):
        await connection._parse_and_update_state("<?xml version='1.0'?><Response/>")

    mock_hass = _wire_inline_executor(connection)

    # Non-XML text returns (False, False, None)
    assert await connection._parse_and_update_state("DPLUG-1.6\nNo XML") == (
        False,
        False,
        None,
    )

    # Offloads parsing to hass.async_add_executor_job(safe_xml_to_dict, ...)
    single_attr_resp = (
        '<?xml version="1.0" encoding="utf-8" ?>'
        '<Response Type="DeviceState" Status="Okay">'
        '<DeviceState><Device DUID="AABBCCDDEEFF">'
        '<Attr ID="AC_FUN_POWER" Value="On" />'
        "</Device></DeviceState></Response>"
    )
    with patch(
        "custom_components.climate_ip.samsung_2878.safe_xml_to_dict",
        side_effect=safe_xml_to_dict,
    ) as mock_safe_xml:
        is_resp, is_upd, parsed = await connection._parse_and_update_state(
            single_attr_resp
        )
        mock_hass.async_add_executor_job.assert_awaited_once_with(
            mock_safe_xml, single_attr_resp
        )
    assert (is_resp, is_upd, parsed) == (True, False, {"AC_FUN_POWER": "On"})

    # Missing DeviceState, missing Attr, and Attr missing Value or ID (must not log parse warnings)
    with patch.object(samsung_module._LOGGER, "warning") as mock_warn:
        assert await connection._parse_and_update_state(
            '<?xml version="1.0"?><Response Type="Fake"></Response>'
        ) == (True, False, {})
        assert await connection._parse_and_update_state(
            '<?xml version="1.0"?><Response><DeviceState><Device><Dummy>1</Dummy></Device></DeviceState></Response>'
        ) == (True, False, {})
    mock_warn.assert_not_called()

    mixed_attrs = (
        '<?xml version="1.0"?><Response Type="DeviceState" Status="Okay">'
        "<DeviceState><Device>"
        '<Attr ID="MISSING_VAL" />'
        '<Attr Value="MISSING_ID" />'
        '<Attr ID="AC_FUN_POWER" Value="On" />'
        '<Attr ID="AC_FUN_TEMPSET" Value="24" />'
        "</Device></DeviceState></Response>"
    )
    assert await connection._parse_and_update_state(mixed_attrs) == (
        True,
        False,
        {"AC_FUN_POWER": "On", "AC_FUN_TEMPSET": "24"},
    )


async def test_parse_and_update_state_multidoc_and_push_dedup(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify multi-document XML splitting, lone Power-On Update dedup, and parse error recovery."""
    mock_hass = _wire_inline_executor(connection)

    single_attr_resp = (
        '<?xml version="1.0" encoding="utf-8" ?>'
        '<Response Type="DeviceState" Status="Okay">'
        '<DeviceState><Device DUID="AABBCCDDEEFF">'
        '<Attr ID="AC_FUN_POWER" Value="On" />'
        "</Device></DeviceState></Response>"
    )
    status_tpl = (
        '<?xml version="1.0"?><Update Type="Status">'
        '<Status DUID="1"><Attr ID="{}" Value="{}"/></Status></Update>'
    )
    multi_xml = (
        "DPLUG-1.6\n"
        "<?xml bogus_fragment "
        '<?xml version="1.0"?><Fake/>'
        + status_tpl.format("A", "1")
        + '<?xml version="1.0"?><Update Type="Status"></Update>'
        + status_tpl.format("B", "2")
    )
    assert await connection._parse_and_update_state(multi_xml) == (
        False,
        True,
        {"A": "1", "B": "2"},
    )

    # Redundant lone Power On push is ignored ONLY on Update when already On
    connection._device_status[PROTOCOL_2878_POWER_ID] = PROTOCOL_2878_VALUE_ON
    lone_on_update = status_tpl.format(PROTOCOL_2878_POWER_ID, PROTOCOL_2878_VALUE_ON)
    assert await connection._parse_and_update_state(lone_on_update) == (
        False,
        False,
        None,
    )
    # Response with Power On is NOT ignored
    assert await connection._parse_and_update_state(single_attr_resp) == (
        True,
        False,
        {PROTOCOL_2878_POWER_ID: PROTOCOL_2878_VALUE_ON},
    )
    # Multi-attribute Update containing Power On is NOT ignored
    multi_attr_upd = (
        '<?xml version="1.0"?><Update Type="Status"><Status DUID="1">'
        '<Attr ID="AC_FUN_POWER" Value="On" />'
        '<Attr ID="AC_FUN_TEMPSET" Value="24" />'
        "</Status></Update>"
    )
    assert await connection._parse_and_update_state(multi_attr_upd) == (
        False,
        True,
        {"AC_FUN_POWER": "On", "AC_FUN_TEMPSET": "24"},
    )

    # Executor exception on one part logs warning and continues to next document
    mock_hass.async_add_executor_job = AsyncMock(
        side_effect=[
            RuntimeError("parse boom"),
            safe_xml_to_dict(status_tpl.format("C", "3")),
        ]
    )
    assert await connection._parse_and_update_state(
        status_tpl.format("X", "0") + status_tpl.format("C", "3")
    ) == (False, True, {"C": "3"})


# ============================================================================
# SSL HANDSHAKE & AUTHENTICATION
# ============================================================================


async def test_establish_connection_initial_and_ssl_cache(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify initial handshake, SSL config persistence, and reconnection SSL context cache."""
    connection._cfg.host = "10.0.0.1"
    connection._cfg.port = 2878
    connection._cfg.cert = None
    connection._connection_init_template = MagicMock()
    connection._connection_init_template.async_render.return_value = "<Auth/>"
    connection._is_available = False
    connection._persistent_offline_err_logged = True

    mock_ctrl = MagicMock()
    mock_ctrl.hass = MagicMock()
    mock_ctrl.on_ssl_config_updated = MagicMock()
    mock_ctrl.request_refresh_callback = AsyncMock()
    connection._controller = mock_ctrl

    mock_sock = MagicMock()
    mock_writer = _make_safe_writer()

    with (
        patch("socket.socket", return_value=mock_sock) as mock_sock_cls,
        patch("asyncio.get_running_loop") as mock_loop,
        patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(MagicMock(), mock_writer),
        ) as mock_open,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ) as mock_ssl_ctx,
        patch.object(
            connection, "_read_full_response", new_callable=AsyncMock
        ) as mock_read,
        patch.object(connection, "_write_data", new_callable=AsyncMock) as mock_write,
        patch.object(
            connection,
            "_parse_and_update_state",
            new_callable=AsyncMock,
            return_value=(False, False, None),
        ) as mock_parse,
        patch.object(
            connection, "_post_connect_status_request", new_callable=AsyncMock
        ) as mock_post_status,
    ):
        mock_loop.return_value.sock_connect = AsyncMock()
        mock_read.side_effect = ["DPLUG-1.6\n", 'Status="Okay"']

        # 1st connection: initial_connection_done was False -> no post-connect refresh yet
        assert await connection._establish_connection_and_handshake() is True
        assert connection._is_ready.is_set()
        assert connection._is_available is True
        assert connection._persistent_offline_err_logged is False
        assert connection._initial_connection_done is True
        mock_post_status.assert_not_called()
        mock_ctrl.request_refresh_callback.assert_not_called()
        mock_parse.assert_awaited_once_with("DPLUG-1.6\n")
        mock_read.assert_has_calls(
            [
                call(timeout_sec=connection._socket_timeout),
                call(timeout_sec=connection._socket_timeout),
            ]
        )

        mock_sock_cls.assert_called_with(socket.AF_INET, socket.SOCK_STREAM)
        mock_loop.return_value.sock_connect.assert_awaited_once_with(
            mock_sock, ("10.0.0.1", 2878)
        )
        mock_open.assert_awaited_once_with(
            sock=mock_sock,
            ssl=mock_ssl_ctx.return_value,
            server_hostname="10.0.0.1",
        )
        mock_ssl_ctx.assert_awaited_once_with(
            cert_path=None, ciphers=ANY, verify_mode=ssl.CERT_NONE
        )
        mock_write.assert_awaited_once_with("<Auth/>\n")
        mock_writer.get_extra_info.assert_called_with("ssl_object")
        expected_ssl_cfg = {
            "cert": None,
            "cipher_name": SUITE_D[1],
            "verify_mode": ssl.CERT_NONE,
        }
        assert connection._last_successful_config == expected_ssl_cfg
        mock_ctrl.on_ssl_config_updated.assert_called_once_with(expected_ssl_cfg)

        # 2nd connection (reconnection): hits SSL context cache & schedules post-connect refresh
        connection._is_ready.clear()
        mock_read.side_effect = [f"{PROTOCOL_2878_DRC}\n", 'Status="Okay"']
        tracked: list[Any] = []

        def _capture_task(coro: Any) -> MagicMock:
            tracked.append(coro)
            coro.close()
            return MagicMock()

        with patch.object(connection, "_track_task", side_effect=_capture_task):
            assert await connection._establish_connection_and_handshake() is True
        assert mock_ssl_ctx.await_count == 1  # Cached!
        assert len(tracked) == 2

        # Reconnection ready without a controller skips coordinator refresh safely
        tracked.clear()
        connection._controller = None
        with patch.object(connection, "_track_task", side_effect=_capture_task):
            connection._on_connection_ready()
        assert len(tracked) == 1


async def test_establish_connection_socket_and_cipher_fallback(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify raw socket cleanup on sock_connect error, cipher fallback, and initial Update push."""
    connection._cfg.host = "10.0.0.1"
    connection._cfg.port = 2878
    connection._cfg.cert = "/custom/cert.pem"
    connection._connection_init_template = MagicMock()
    connection._connection_init_template.async_render.return_value = "<Auth/>"

    mock_ctrl = MagicMock()
    mock_ctrl.hass = MagicMock()
    mock_ctrl.on_ssl_config_updated = MagicMock()
    mock_ctrl.request_refresh_callback = AsyncMock()
    connection._controller = mock_ctrl

    mock_sock = MagicMock()
    with (
        patch("socket.socket", return_value=mock_sock),
        patch("asyncio.get_running_loop") as mock_loop,
        patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            side_effect=[
                ssl.SSLError("cipher 1 failed"),
                (MagicMock(), _make_safe_writer()),
            ],
        ) as mock_open2,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ) as mock_ssl_ctx2,
        patch.object(
            connection,
            "_read_full_response",
            new_callable=AsyncMock,
            side_effect=["DPLUG-1.6", 'Status="Okay"'],
        ),
        patch.object(connection, "_write_data", new_callable=AsyncMock),
        patch.object(
            connection,
            "_parse_and_update_state",
            new_callable=AsyncMock,
            return_value=(False, True, {"temp": "22"}),
        ),
        patch.object(
            connection, "_track_task", side_effect=lambda c: (c.close(), MagicMock())[1]
        ),
    ):
        mock_loop.return_value.sock_connect = AsyncMock(
            side_effect=[RuntimeError("unexpected socket glitch"), None, None]
        )
        update_cb = AsyncMock()
        connection.set_update_callback(update_cb)
        assert await connection._establish_connection_and_handshake() is True
        mock_sock.close.assert_called_once()
        assert mock_open2.await_count == 2
        mock_ssl_ctx2.assert_any_await(
            cert_path="/custom/cert.pem",
            ciphers=SUITE_A[0],
            verify_mode=ssl.CERT_REQUIRED,
        )
        assert connection._last_successful_config == {
            "cert": "/custom/cert.pem",
            "cipher_name": SUITE_C[1],
            "verify_mode": ssl.CERT_REQUIRED,
        }
        assert connection._device_status["temp"] == "22"
        update_cb.assert_called_once_with({"temp": "22"})


async def test_establish_connection_all_ciphers_refused(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify exhausting all SSL strategies on ConnectionRefusedError returns False."""
    connection._cfg.host = "192.168.1.50"
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()
    connection._controller.on_ssl_config_updated = None

    with (
        patch("socket.socket"),
        patch("asyncio.get_running_loop") as mock_loop,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ),
    ):
        mock_loop.return_value.sock_connect = AsyncMock(
            side_effect=ConnectionRefusedError
        )
        assert await connection._establish_connection_and_handshake() is False


async def test_establish_connection_greeting_template_and_auth_errors(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify greeting, template, session collision, and ErrorCode failure branches."""
    connection._cfg.host = "192.168.1.50"
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()
    connection._controller.on_ssl_config_updated = None

    update_cb = AsyncMock()
    connection.set_update_callback(update_cb)

    with (
        patch("socket.socket"),
        patch("asyncio.get_running_loop") as mock_loop,
        patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(MagicMock(), _make_safe_writer()),
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ),
        patch.object(
            connection, "_read_full_response", new_callable=AsyncMock
        ) as mock_read,
        patch.object(connection, "_write_data", new_callable=AsyncMock),
        patch.object(
            connection,
            "_parse_and_update_state",
            new_callable=AsyncMock,
            return_value=(True, False, {"mode": "cool"}),
        ),
    ):
        mock_loop.return_value.sock_connect = AsyncMock()

        # Initial message that is a Response (not Update) updates status without firing callback
        connection._connection_init_template = MagicMock()
        connection._connection_init_template.async_render.return_value = "<Auth/>"
        mock_read.side_effect = ["DPLUG-1.6", 'Status="Okay"']
        assert await connection._establish_connection_and_handshake() is True
        assert connection._device_status["mode"] == "cool"
        update_cb.assert_not_called()

        # Invalid/missing greeting
        for bad_greeting in (None, "", "GARBAGE-HEADER"):
            mock_read.side_effect = [bad_greeting]
            with pytest.raises(
                CannotConnect, match="Did not receive expected initial message"
            ):
                await connection._establish_connection_and_handshake()

        # Missing template
        connection._connection_init_template = None
        mock_read.side_effect = ["DPLUG-1.6"]
        with pytest.raises(
            CannotConnect, match="Connection initialization template is missing"
        ):
            await connection._establish_connection_and_handshake()

        # Template rendering exception
        broken_tpl = MagicMock()
        broken_tpl.async_render.side_effect = ValueError("bad jinja")
        connection._connection_init_template = broken_tpl
        mock_read.side_effect = ["DPLUG-1.6"]
        with pytest.raises(CannotConnect, match="Template rendering failed"):
            await connection._establish_connection_and_handshake()

        # Restore working template for auth response branches
        ok_tpl = MagicMock()
        ok_tpl.async_render.return_value = "<Auth/>"
        connection._connection_init_template = ok_tpl

        # Empty auth response
        mock_read.side_effect = ["DPLUG-1.6", None]
        with pytest.raises(AuthError, match="No response from device"):
            await connection._establish_connection_and_handshake()

        # Session collision (InvalidateAccount in greeting & auth response) -> returns False
        mock_read.side_effect = [PROTOCOL_2878_INVALIDATE, PROTOCOL_2878_INVALIDATE]
        assert await connection._establish_connection_and_handshake() is False

        # ErrorCode 301
        mock_read.side_effect = ["DPLUG-1.6", 'ErrorCode="301"']
        with pytest.raises(AuthError, match="Device was turned off"):
            await connection._establish_connection_and_handshake()

        # Generic ErrorCode regex extraction vs Unknown fallback
        with patch.object(samsung_module._LOGGER, "error") as mock_log_err:
            mock_read.side_effect = [
                "DPLUG-1.6",
                '<Response Status="Failed" ErrorCode="999" />',
            ]
            with pytest.raises(AuthError, match="^Authentication failed$"):
                await connection._establish_connection_and_handshake()

            mock_read.side_effect = ["DPLUG-1.6", '<Response Status="Failed" />']
            with pytest.raises(AuthError, match="^Authentication failed$"):
                await connection._establish_connection_and_handshake()

        logged_codes = [
            c.args[2]
            for c in mock_log_err.call_args_list
            if "Authentication failed with ErrorCode" in str(c.args[0])
        ]
        assert logged_codes == ["999", "Unknown"]


# ============================================================================
# COMMAND QUEUE, READ STREAM FRAMING & POST-CONNECT REQUEST
# ============================================================================


async def test_process_command_queue_and_post_connect_status(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify _process_command_queue and _post_connect_status_request."""
    # 1. _process_command_queue success and CannotConnect failure
    fut1: asyncio.Future[bool] = asyncio.Future()
    q_task1: asyncio.Future[Any] = asyncio.Future()
    q_task1.set_result(('<Request Type="Test"/>\n', fut1))

    with patch.object(connection, "_write_data", new_callable=AsyncMock) as mock_write:
        await connection._process_command_queue(q_task1)  # type: ignore[arg-type]
        mock_write.assert_awaited_once_with('<Request Type="Test"/>\n')
        assert connection._pending_future is fut1
        assert fut1._command_debug == '<Request Type="Test"/>\n'  # type: ignore[attr-defined]

        mock_write.side_effect = CannotConnect("write err")
        fut2: asyncio.Future[bool] = asyncio.Future()
        q_task2: asyncio.Future[Any] = asyncio.Future()
        q_task2.set_result(('<Request Type="Test2"/>\n', fut2))
        await connection._process_command_queue(q_task2)  # type: ignore[arg-type]
        assert isinstance(fut2.exception(), CannotConnect)
        assert connection._pending_future is None

    # 2. _post_connect_status_request: success, timeout clearing matching future, generic error
    connection._cfg.duid = "TESTDUID"
    resolved_cmds: list[str] = []

    async def _put_resolve(item: tuple[str, asyncio.Future[bool]]) -> None:
        cmd, fut = item
        resolved_cmds.append(cmd)
        fut.set_result(True)

    connection._cmd_queue = MagicMock()
    connection._cmd_queue.put = AsyncMock(side_effect=_put_resolve)
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        await connection._post_connect_status_request()
        mock_sleep.assert_awaited_once_with(1)
    assert resolved_cmds == ['<Request Type="DeviceState" DUID="TESTDUID"></Request>\n']

    async def _put_timeout(item: tuple[str, asyncio.Future[bool]]) -> None:
        _, fut = item
        connection._pending_future = fut
        raise TimeoutError

    connection._cmd_queue.put = AsyncMock(side_effect=_put_timeout)
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await connection._post_connect_status_request()
    assert connection._pending_future is None

    connection._cmd_queue.put = AsyncMock(side_effect=RuntimeError("queue error"))
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await connection._post_connect_status_request()


async def test_process_read_queue_and_handle_message(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify stream framing, EOF/error handling, future resolution, and push callbacks."""
    connection._ensure_callback_linked = MagicMock()

    # 1. EOF, CancelledError, and generic Exception all close connection and return None
    for task_factory in (
        lambda: _completed_future(b""),
        _cancelled_future,
        lambda: _failed_future(RuntimeError("read crash")),
    ):
        connection._read_task = task_factory()
        with patch.object(
            connection, "_close_connection", new_callable=AsyncMock
        ) as mock_close:
            assert await connection._process_read_queue(b"stale") is None
            mock_close.assert_awaited_once()

    # 2. Multi-tag framing (.find vs .rfind) for </Response>, </Update>, and />
    for stream, expected_calls, remainder in (
        (
            b"A</Response>B</Response>C",
            [call("A</Response>"), call("B</Response>")],
            b"C",
        ),
        (b"X</Update>Y</Update>Z", [call("X</Update>"), call("Y</Update>")], b"Z"),
        (b"Data\xff<Fake/>More", [call("Data<Fake/>")], b"More"),
    ):
        connection._read_task = _completed_future(stream)
        with patch.object(
            connection,
            "_parse_and_update_state",
            new_callable=AsyncMock,
            return_value=(False, False, None),
        ) as mock_parse:
            res = await connection._process_read_queue(b"")
        assert res == remainder
        assert mock_parse.call_count == len(expected_calls)
        mock_parse.assert_has_calls(expected_calls)

    # 3. Fragmented buffer assembly + update callback dispatch
    update_cb = AsyncMock()
    connection.set_update_callback(update_cb)
    connection._read_task = _completed_future(b"sponse>")
    with (
        patch.object(
            connection,
            "_parse_and_update_state",
            new_callable=AsyncMock,
            return_value=(True, False, {"power": "on"}),
        ),
        patch.object(
            connection,
            "_track_task",
            side_effect=lambda c: (c.close(), MagicMock())[1],
        ) as mock_track,
    ):
        rem = await connection._process_read_queue(b"<?xml><Response>data</Re")
    assert rem == b""
    assert connection._device_status["power"] == "on"
    mock_track.assert_called_once()
    update_cb.assert_called_once_with({"power": "on"})
    connection.set_update_callback(None)  # type: ignore[arg-type]

    # 4. Pending future resolution: ignores non-matching Update/Fail, resolves on DeviceControl Okay ack
    ctrl_fut: asyncio.Future[bool] = asyncio.Future()
    ctrl_fut._command_debug = '<Request Type="DeviceControl" />'  # type: ignore[attr-defined]
    connection._pending_future = ctrl_fut
    for non_resolving_frame, parse_ret in (
        (b'<Update Type="Status" Status="Okay"></Update>', (False, True, None)),
        (b'<Response Type="AuthToken" Status="Fail"></Response>', (True, False, None)),
    ):
        connection._read_task = _completed_future(non_resolving_frame)
        with patch.object(
            connection,
            "_parse_and_update_state",
            new_callable=AsyncMock,
            return_value=parse_ret,
        ):
            await connection._process_read_queue(b"")
        assert not ctrl_fut.done()

    connection._read_task = _completed_future(
        b'<Response Type="DeviceControl" Status="Okay" />'
    )
    with patch.object(
        connection,
        "_parse_and_update_state",
        new_callable=AsyncMock,
        return_value=(True, False, None),
    ):
        await connection._process_read_queue(b"")
    assert ctrl_fut.result() is True
    assert connection._pending_future is None

    # 5. Poll command ignores DeviceControl ack and resolves ONLY on DeviceState response
    poll_fut: asyncio.Future[bool] = asyncio.Future()
    poll_fut._command_debug = '<Request Type="DeviceState" />'  # type: ignore[attr-defined]
    connection._pending_future = poll_fut
    connection._read_task = _completed_future(
        b'<Response Type="DeviceControl" Status="Okay" />'
    )
    with patch.object(
        connection,
        "_parse_and_update_state",
        new_callable=AsyncMock,
        return_value=(True, False, None),
    ):
        await connection._process_read_queue(b"")
    assert not poll_fut.done()

    connection._read_task = _completed_future(
        b'<Response Type="DeviceState" Status="Okay"></Response>'
    )
    with patch.object(
        connection,
        "_parse_and_update_state",
        new_callable=AsyncMock,
        return_value=(True, False, {"DeviceState": "ok"}),
    ):
        await connection._process_read_queue(b"")
    assert poll_fut.result() is True
    assert connection._pending_future is None

    # 6. Future without _command_debug attribute uses "" fallback cleanly
    bare_fut: asyncio.Future[bool] = asyncio.Future()
    connection._pending_future = bare_fut
    connection._read_task = _completed_future(b'<Response Status="Okay"></Response>')
    with patch.object(
        connection,
        "_parse_and_update_state",
        new_callable=AsyncMock,
        return_value=(True, False, {"temp": "21"}),
    ):
        await connection._process_read_queue(b"")
    assert bare_fut.result() is True


def _completed_future(val: bytes) -> asyncio.Future[bytes]:
    fut: asyncio.Future[bytes] = asyncio.Future()
    fut.set_result(val)
    return fut


def _cancelled_future() -> asyncio.Future[bytes]:
    fut: asyncio.Future[bytes] = asyncio.Future()
    fut.cancel()
    return fut


def _failed_future(err: Exception) -> asyncio.Future[bytes]:
    fut: asyncio.Future[bytes] = asyncio.Future()
    fut.set_exception(err)
    return fut


# ============================================================================
# RECONNECTION, BACKOFF & UNAVAILABILITY
# ============================================================================


def test_force_unavailability_if_needed(connection: ConnectionSamsung2878) -> None:
    """Verify threshold, initial-setup suppression, and controller callback dispatch."""
    sig = inspect.signature(ConnectionSamsung2878._force_unavailability_if_needed)
    assert sig.parameters["offline_type"].default == "Network"

    class _StrictController:
        unique_id = "strict_id"
        log_prefix = "[strict_id]"

        def __init__(self) -> None:
            self.on_offline_callback = MagicMock()
            self.on_connection_failed_callback = MagicMock()

    ctrl = _StrictController()
    connection._controller = ctrl

    # Retries != 2 -> no action
    connection._reconnect_retries = 1
    connection._force_unavailability_if_needed("Network")
    ctrl.on_offline_callback.assert_not_called()
    ctrl.on_connection_failed_callback.assert_not_called()
    assert connection._persistent_offline_err_logged is False

    # Retries == 2 during startup (_initial_connection_done=False) -> suppresses panic callback
    connection._reconnect_retries = 2
    connection._initial_connection_done = False
    connection._force_unavailability_if_needed("Network")
    ctrl.on_offline_callback.assert_not_called()
    ctrl.on_connection_failed_callback.assert_called_once()
    assert connection._persistent_offline_err_logged is True

    # Retries == 2 after connected once -> fires panic callback once, suppresses on repeat
    connection._persistent_offline_err_logged = False
    connection._initial_connection_done = True
    ctrl.on_connection_failed_callback.reset_mock()
    connection._force_unavailability_if_needed("Service")
    ctrl.on_offline_callback.assert_called_once_with(OFFLINE_PANIC_MSG)
    ctrl.on_connection_failed_callback.assert_called_once()
    assert connection._persistent_offline_err_logged is True

    ctrl.on_offline_callback.reset_mock()
    ctrl.on_connection_failed_callback.reset_mock()
    connection._force_unavailability_if_needed("Service")
    ctrl.on_offline_callback.assert_not_called()
    ctrl.on_connection_failed_callback.assert_called_once()

    # Controller missing attributes raises AttributeError (verifies direct attribute access)
    class _EmptyController:
        unique_id = "empty_id"
        log_prefix = "[empty_id]"

    connection._controller = _EmptyController()
    connection._persistent_offline_err_logged = False
    with pytest.raises(AttributeError):
        connection._force_unavailability_if_needed("Service")


async def test_check_reachability_and_backoff_calculations(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify ping diagnostics, jitter vs non-jitter backoff doubling, and MAX_RECONNECT_DELAY cap."""
    connection._cfg.host = "192.168.1.50"
    connection._initial_connection_done = True
    ctrl = MagicMock()
    ctrl.unique_id = "uid_2878"
    ctrl.log_prefix = "[uid_2878]"
    ctrl.on_offline_callback = MagicMock()
    ctrl.on_connection_failed_callback = MagicMock()
    connection._controller = ctrl

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.async_check_network_reachability",
            new_callable=AsyncMock,
        ) as mock_ping,
        patch(
            "custom_components.climate_ip.samsung_2878.get_last_network_diagnostic",
            return_value=None,
        ),
        patch.object(
            connection, "_establish_connection_and_handshake", new_callable=AsyncMock
        ) as mock_handshake,
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep,
    ):
        # 1. Network down (ping=False): exact sleep without jitter, backoff doubles, 2nd triggers offline
        mock_ping.return_value = False
        connection._reconnect_delay = 10.0
        connection._reconnect_retries = 0
        connection._ssl_context_cache[("k", "c", 0)] = MagicMock()

        assert await connection.handle_reconnection() is False
        mock_ping.assert_awaited_once_with("192.168.1.50", "[uid_2878]")
        assert connection._is_available is False
        assert connection._ssl_context_cache == {}
        assert connection._last_icmp_diagnostic == {
            "is_reachable": False,
            "status": "unreachable_timeout",
        }
        mock_sleep.assert_awaited_once_with(10.0)
        assert connection._reconnect_retries == 1
        assert connection._reconnect_delay == 20.0
        ctrl.on_offline_callback.assert_not_called()
        mock_handshake.assert_not_called()

        # Verify empty-string fallback when host is None
        connection._cfg.host = None
        mock_ping.reset_mock()
        assert await connection._check_network_reachability() is False
        mock_ping.assert_awaited_once_with("", "[uid_2878]")
        connection._cfg.host = "192.168.1.50"

        mock_sleep.reset_mock()
        assert await connection.handle_reconnection() is False
        mock_sleep.assert_awaited_once_with(20.0)
        assert connection._reconnect_retries == 2
        assert connection._reconnect_delay == 40.0
        ctrl.on_offline_callback.assert_called_once_with(OFFLINE_PANIC_MSG)

        # 2. Ping True, handshake False -> jitter applied, delay capped at MAX_RECONNECT_DELAY (60)
        mock_sleep.reset_mock()
        mock_ping.return_value = True
        mock_handshake.return_value = False
        with patch(
            "custom_components.climate_ip.samsung_2878.random.uniform",
            return_value=1.5,
        ) as mock_uniform:
            assert await connection.handle_reconnection() is False
            mock_uniform.assert_called_once_with(0, 40.0 * 0.2)
        assert connection._last_icmp_diagnostic == {
            "is_reachable": True,
            "status": "alive",
        }
        mock_sleep.assert_awaited_once_with(41.5)
        assert connection._reconnect_delay == float(MAX_RECONNECT_DELAY)


async def test_handle_reconnection_exceptions_and_delegation(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify ping error fallback, pending-future failure propagation, recovery, and backoff args."""
    connection._cfg.host = "192.168.1.50"
    connection._initial_connection_done = True
    ctrl = MagicMock()
    ctrl.unique_id = "uid_2878"
    ctrl.log_prefix = "[uid_2878]"
    ctrl.on_offline_callback = MagicMock()
    ctrl.on_connection_failed_callback = MagicMock()
    connection._controller = ctrl

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.async_check_network_reachability",
            new_callable=AsyncMock,
        ) as mock_ping,
        patch(
            "custom_components.climate_ip.samsung_2878.get_last_network_diagnostic",
            return_value=None,
        ),
        patch.object(
            connection, "_establish_connection_and_handshake", new_callable=AsyncMock
        ) as mock_handshake,
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep,
    ):
        # 1. Ping raises exception -> defaults to reachable=True; handshake raises CannotConnect -> fails pending future
        mock_ping.side_effect = RuntimeError("icmp error")
        mock_handshake.side_effect = CannotConnect("handshake boom")
        pending_fut: asyncio.Future[bool] = asyncio.Future()
        connection._pending_future = pending_fut

        assert await connection.handle_reconnection() is False
        assert isinstance(pending_fut.exception(), CannotConnect)
        assert connection._pending_future is None
        assert isinstance(mock_sleep.call_args.args[0], float)

        # AuthError when _pending_future is None must not dereference .done()
        mock_handshake.side_effect = AuthError("auth boom")
        assert await connection.handle_reconnection() is False

        # 2. Recovery -> returns True
        mock_ping.side_effect = None
        mock_ping.return_value = True
        mock_handshake.side_effect = None
        mock_handshake.return_value = True
        assert await connection.handle_reconnection() is True

        # 3. Verify exact delegation arguments to _backoff_after_failure
        with patch.object(
            connection,
            "_backoff_after_failure",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_backoff:
            mock_ping.return_value = False
            assert await connection.handle_reconnection() is False
            mock_backoff.assert_awaited_once_with("Network", jitter=False)

            mock_backoff.reset_mock()
            mock_ping.return_value = True
            mock_handshake.return_value = False
            assert await connection.handle_reconnection() is False
            mock_backoff.assert_awaited_once_with("Service")


# ============================================================================
# CONNECTION MANAGER LOOP & ASYNC EXECUTE
# ============================================================================


async def test_connection_manager_loop_branches(
    connection: ConnectionSamsung2878,
) -> None:
    """Verify reconnect continue, missing reader, buffer retention, error recovery, and finally cleanup."""
    # 1. Disconnected writer -> handle_reconnection False continues loop
    connection._writer = None
    with (
        patch.object(
            connection,
            "handle_reconnection",
            new_callable=AsyncMock,
            side_effect=[False, asyncio.CancelledError()],
        ) as mock_reconn,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, asyncio.CancelledError()],
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(connection._connection_manager(), timeout=0.05)
    assert mock_reconn.await_count == 2

    # 2. Writer alive, _reader missing -> closes connection, reconnects, and continues
    connection._writer = _make_safe_writer()
    connection._reader = None
    with (
        patch.object(
            connection,
            "handle_reconnection",
            new_callable=AsyncMock,
            side_effect=[True, asyncio.CancelledError()],
        ) as mock_reconn2,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, asyncio.CancelledError()],
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await asyncio.wait_for(connection._connection_manager(), timeout=0.05)
    assert mock_reconn2.await_count == 2

    # 3. Buffer retention across iterations and reset on disconnect (None)
    connection._writer = _make_safe_writer()
    connection._reader = MagicMock()
    fake_read: asyncio.Future[bytes] = asyncio.Future()
    connection._pending_future = MagicMock()
    connection._pending_future.done.return_value = False

    with (
        patch(
            "asyncio.create_task",
            side_effect=lambda c: (
                c.close() if hasattr(c, "close") else None,
                fake_read,
            )[1],
        ),
        patch(
            "asyncio.wait",
            new_callable=AsyncMock,
            return_value=({fake_read}, set()),
        ) as mock_wait,
        patch.object(
            connection,
            "_process_read_queue",
            new_callable=AsyncMock,
            side_effect=[b"FRAGMENT", None, asyncio.CancelledError()],
        ) as mock_proc_read,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, None, asyncio.CancelledError()],
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(connection._connection_manager(), timeout=0.05)

    assert [c.args[0] for c in mock_proc_read.call_args_list] == [
        b"",
        b"FRAGMENT",
        b"",
    ]
    assert mock_wait.call_args.kwargs.get("return_when") == asyncio.FIRST_COMPLETED

    # 4. OSError & generic Exception recovery + finally cancellation of _read_task and queue_task
    connection._writer = _make_safe_writer()
    connection._reader = MagicMock()
    pending_cmd_fut: asyncio.Future[bool] = asyncio.Future()
    connection._pending_future = None
    fake_r_task: asyncio.Future[bytes] = asyncio.Future()
    fake_q_task: asyncio.Future[Any] = asyncio.Future()

    created = [fake_r_task, fake_q_task, fake_r_task, fake_q_task]

    def _create_side_effect(coro: Any) -> asyncio.Future[Any]:
        if hasattr(coro, "close"):
            coro.close()
        return created.pop(0) if created else fake_r_task

    with (
        patch("asyncio.create_task", side_effect=_create_side_effect),
        patch(
            "asyncio.wait",
            new_callable=AsyncMock,
            return_value=({fake_q_task}, {fake_r_task}),
        ),
        patch.object(
            connection,
            "_process_command_queue",
            new_callable=AsyncMock,
            side_effect=[ValueError("unexpected bug"), OSError("socket crash")],
        ) as mock_proc_cmd,
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, None, asyncio.CancelledError()],
        ),
    ):
        # Set pending_future before OSError iteration via sleep side effect check
        connection._pending_future = None
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(connection._connection_manager(), timeout=0.05)

    mock_proc_cmd.assert_has_awaits([call(fake_q_task), call(fake_q_task)])
    assert fake_r_task.cancelled() is True
    assert fake_q_task.cancelled() is True

    # Verify OSError also fails an active _pending_future and sleeps _reconnect_delay + jitter
    connection._writer = _make_safe_writer()
    connection._reader = MagicMock()
    connection._pending_future = pending_cmd_fut
    connection._reconnect_delay = 10.0
    r_task2: asyncio.Future[bytes] = asyncio.Future()
    with (
        patch(
            "asyncio.create_task",
            side_effect=lambda c: (c.close() if hasattr(c, "close") else None, r_task2)[
                1
            ],
        ),
        patch(
            "asyncio.wait",
            new_callable=AsyncMock,
            side_effect=OSError("wait crash"),
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
        patch(
            "custom_components.climate_ip.samsung_2878.random.uniform",
            return_value=1.5,
        ) as mock_mgr_uniform,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, asyncio.CancelledError()],
        ) as mock_mgr_sleep,
        contextlib.suppress(asyncio.CancelledError),
    ):
        await asyncio.wait_for(connection._connection_manager(), timeout=0.05)
    assert isinstance(pending_cmd_fut.exception(), OSError)
    assert connection._pending_future is None
    mock_mgr_uniform.assert_called_once_with(0, 10.0 * 0.2)
    mock_mgr_sleep.assert_has_awaits([call(2), call(11.5)])


async def test_async_execute_complete(
    connection: ConnectionSamsung2878, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify async_execute auto-start, backoff fast-fail, poll/data execution, and errors."""
    assert samsung_module.COMMAND_TIMEOUT == 20.0
    connection._ensure_callback_linked = MagicMock()
    connection.start_listening = MagicMock()

    # 1. Auto-starts listener when _manager_task is None, then fast-fails in retry backoff
    connection._manager_task = None
    connection._is_ready.clear()
    connection._reconnect_retries = 1
    with (
        patch.object(samsung_module._LOGGER, "debug") as mock_dbg,
        pytest.raises(CannotConnect, match="Client not ready"),
    ):
        await asyncio.wait_for(
            connection.async_execute(None, None, "<Cmd/>", None), timeout=0.05
        )
    connection.start_listening.assert_called_once()
    assert not any("Waiting up to" in str(c.args[0]) for c in mock_dbg.call_args_list)

    # Keep manager marked alive for subsequent checks
    connection._manager_task = MagicMock()
    connection._manager_task.done.return_value = False

    # 2. Timeout waiting for connection ready when retries == 0 (verifies COMMAND_TIMEOUT=20.0)
    connection._reconnect_retries = 0
    with (
        patch.object(samsung_module._LOGGER, "debug") as mock_dbg2,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.timeout",
            side_effect=TimeoutError,
        ) as mock_exec_to,
        pytest.raises(CannotConnect, match="Timeout waiting for connection"),
    ):
        await connection.async_execute(None, None, "<Cmd/>", None)
    mock_exec_to.assert_called_once_with(20.0)
    assert any(
        "Waiting up to" in str(c.args[0]) and c.args[2] == 20.0
        for c in mock_dbg2.call_args_list
    )

    # Shrink COMMAND_TIMEOUT for remaining in-memory tests so hang mutants fail in 10ms
    monkeypatch.setattr(samsung_module, "COMMAND_TIMEOUT", 0.01)

    # 3. Ready connection does NOT log handshake wait (even if retries == 0 or > 0); empty returns (None, None)
    connection._is_ready.set()
    connection._reconnect_retries = 0
    with patch.object(samsung_module._LOGGER, "debug") as mock_dbg3:
        assert await asyncio.wait_for(
            connection.async_execute(None, None, None, None), timeout=0.05
        ) == (None, None)
    assert not any("Waiting up to" in str(c.args[0]) for c in mock_dbg3.call_args_list)

    connection._reconnect_retries = 3
    assert await asyncio.wait_for(
        connection.async_execute(None, None, None, None), timeout=0.05
    ) == (None, None)

    # 4. Command execution & poll execution return JSON state
    async def _resolve_put(item: tuple[str, asyncio.Future[bool]]) -> None:
        _, fut = item
        fut.set_result(True)

    connection._cmd_queue = MagicMock()
    connection._cmd_queue.put = AsyncMock(side_effect=_resolve_put)
    connection._device_status = {"AC_FUN_POWER": "On"}

    state_json, headers = await asyncio.wait_for(
        connection.async_execute(None, None, "  <Control/>  ", None), timeout=0.05
    )
    assert state_json == '{"AC_FUN_POWER":"On"}'
    assert headers == {}
    assert connection._cmd_queue.put.call_args.args[0][0] == "<Control/>\n"

    connection._cmd_queue.put.reset_mock()
    connection._cfg.duid = "MYDUID"
    await asyncio.wait_for(
        connection.async_execute(None, None, None, None, _is_poll=True), timeout=0.05
    )
    assert (
        connection._cmd_queue.put.call_args.args[0][0]
        == '<Request Type="DeviceState" DUID="MYDUID"></Request>\n'
    )

    # 5. Command future TimeoutError clears matching _pending_future, preserves non-matching, and closes connection
    async def _timeout_put(item: tuple[str, asyncio.Future[bool]]) -> None:
        _, fut = item
        connection._pending_future = fut
        fut.set_exception(TimeoutError("cmd timeout"))

    connection._cmd_queue.put = AsyncMock(side_effect=_timeout_put)
    with (
        patch.object(
            connection, "_close_connection", new_callable=AsyncMock
        ) as mock_close,
        pytest.raises(CannotConnect, match="Command timed out"),
    ):
        await asyncio.wait_for(
            connection.async_execute(None, None, "<Test/>", None), timeout=0.05
        )
    await asyncio.sleep(0)
    assert connection._pending_future is None
    mock_close.assert_awaited_once()

    other_fut: asyncio.Future[bool] = asyncio.Future()

    async def _timeout_other_pending(item: tuple[str, asyncio.Future[bool]]) -> None:
        _, fut = item
        connection._pending_future = other_fut
        fut.set_exception(TimeoutError("cmd timeout"))

    connection._cmd_queue.put = AsyncMock(side_effect=_timeout_other_pending)
    with (
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
        pytest.raises(CannotConnect, match="Command timed out"),
    ):
        await asyncio.wait_for(
            connection.async_execute(None, None, "<Test/>", None), timeout=0.05
        )
    await asyncio.sleep(0)
    assert connection._pending_future is other_fut
    connection._pending_future = None

    # 6. Non-timeout exception on future propagates cleanly
    async def _error_put(item: tuple[str, asyncio.Future[bool]]) -> None:
        _, fut = item
        fut.set_exception(CannotConnect("disconnected mid-command"))

    connection._cmd_queue.put = AsyncMock(side_effect=_error_put)
    with pytest.raises(CannotConnect, match="disconnected mid-command"):
        await asyncio.wait_for(
            connection.async_execute(None, None, "<Test/>", None), timeout=0.05
        )
