# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Unit tests for samsung_2878.py logic."""
# pylint: disable=protected-access,redefined-outer-name,import-outside-toplevel,line-too-long

from unittest.mock import MagicMock, AsyncMock, patch, call, ANY
import pytest

from custom_components.climate_ip.helpers import async_create_samsung_ssl_context
from custom_components.climate_ip.const import PROTOCOL_2878_DPLUG
import os
import ssl
import tempfile
from custom_components.climate_ip.exceptions import AuthError

from custom_components.climate_ip.samsung_2878 import (
    ConnectionSamsung2878,
    INITIAL_RECONNECT_DELAY,
    MAX_RECONNECT_DELAY,
    RECONNECT_FACTOR,
    CONF_PORT,
    CONF_DUID,
)

import socket
import asyncio
from custom_components.climate_ip.exceptions import CannotConnect
from custom_components.climate_ip.const import (
    PROTOCOL_2878_POWER_ID,
    PROTOCOL_2878_VALUE_ON,
)

import inspect
from homeassistant.helpers.issue_registry import IssueSeverity

import custom_components.climate_ip.samsung_2878 as samsung_module


@pytest.fixture
def connection():
    """Fixture to create a ConnectionSamsung2878 instance with mocked dependencies."""
    hass_config = {
        "mac": "AA:BB:CC:DD:EE:FF",
        "ip_address": "192.168.1.100",
        "token": "test_token",
    }
    logger = MagicMock()
    conn = ConnectionSamsung2878(hass_config, logger)
    conn._socket_timeout = 30.0
    return conn


async def test_parse_and_update_state_valid_response(connection):

    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    connection._controller.hass.async_add_executor_job = AsyncMock(
        side_effect=mock_async_add_executor_job
    )
    """Test parsing a valid DeviceState response."""
    xml = """<?xml version="1.0" encoding="utf-8" ?>
    <Response Type="DeviceState" Status="Okay">
        <DeviceState>
            <Device DUID="AABBCCDDEEFF" GroupID="AC" ModelID="AC" >
                <Attr ID="AC_FUN_POWER" Value="On" />
                <Attr ID="AC_FUN_TEMPSET" Value="24" />
            </Device>
        </DeviceState>
    </Response>
    """
    is_response, is_update, data = await connection._parse_and_update_state(xml)

    assert is_response is True
    assert is_update is False
    assert data["AC_FUN_POWER"] == "On"
    assert data["AC_FUN_TEMPSET"] == "24"


async def test_parse_and_update_state_valid_update(connection):
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    connection._controller.hass.async_add_executor_job = AsyncMock(
        side_effect=mock_async_add_executor_job
    )
    """Test parsing a valid Status Update."""
    xml = """<?xml version="1.0" encoding="utf-8" ?>
    <Update Type="Status">
        <Status DUID="AABBCCDDEEFF" GroupID="AC" ModelID="AC" >
            <Attr ID="AC_FUN_POWER" Value="Off" />
        </Status>
    </Update>
    """
    is_response, is_update, data = await connection._parse_and_update_state(xml)

    assert is_response is False
    assert is_update is True
    assert data["AC_FUN_POWER"] == "Off"


async def test_parse_and_update_state_invalid_xml(connection):
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    connection._controller.hass.async_add_executor_job = AsyncMock(
        side_effect=mock_async_add_executor_job
    )
    """Test parsing invalid XML returns False/None."""
    xml = "Not XML"
    is_response, is_update, data = await connection._parse_and_update_state(xml)

    assert is_response is False
    assert is_update is False
    assert data is None


async def test_parse_and_update_state_empty(connection):
    """Test parsing empty string returns False/None."""
    _is_response, _is_update, _data = await connection._parse_and_update_state("")


async def test_async_create_samsung_ssl_context_properties():
    """Test that the SSL context used for 2878 has the correct minimum properties."""

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"dummy cert")
        cert_path = f.name

    try:
        with (
            patch("ssl.SSLContext.load_verify_locations"),
            patch("ssl.SSLContext.load_cert_chain"),
        ):
            context = await async_create_samsung_ssl_context(
                cert_path=cert_path,
                ciphers="HIGH:!DH:!aNULL",
                verify_mode=ssl.CERT_NONE,
            )

            assert context is not None
            assert context.verify_mode == ssl.CERT_NONE
    finally:
        os.unlink(cert_path)


async def test_reconnect_backoff_timing(connection):
    """Test that the backoff timer correctly exponential scales up to 40s (10, 20, 40) using the integration's logic."""

    # 0 failures = INITIAL_RECONNECT_DELAY = 10.0
    assert connection._reconnect_retries == 0
    connection._reconnect_delay = INITIAL_RECONNECT_DELAY
    assert connection._reconnect_delay == 5.0  # INITIAL_RECONNECT_DELAY is 5

    # Simulate first failure calculation inline as in _connection_manager
    connection._reconnect_retries += 1
    connection._reconnect_delay = min(
        connection._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
    )

    # 1 failure
    assert connection._reconnect_retries == 1
    assert connection._reconnect_delay == 10.0

    # Simulate second failure
    connection._reconnect_retries += 1
    connection._reconnect_delay = min(
        connection._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
    )

    # 2 failures
    assert connection._reconnect_retries == 2
    assert connection._reconnect_delay == 20.0

    # Simulate third failure
    connection._reconnect_retries += 1
    connection._reconnect_delay = min(
        connection._reconnect_delay * RECONNECT_FACTOR, MAX_RECONNECT_DELAY
    )

    # 3 failures (not capped yet)
    assert connection._reconnect_retries == 3
    assert connection._reconnect_delay == 40.0


# =====================================================================
# FASE 1: PROPIEDADES, SETTERS, EXCEPCIONES Y DIAGNÓSTICOS (EASY KILL)
# =====================================================================


def test_samsung_2878_properties_and_setters(connection):
    """Mata los mutantes de propiedades básicas y setters."""
    # set_controller_ref y log_prefix
    mock_controller = MagicMock()
    mock_controller.unique_id = "test_id"
    mock_controller.log_prefix = "[test_id]"
    connection.set_controller_ref(mock_controller)
    assert connection._controller == mock_controller
    assert connection.log_prefix == "[test_id]"

    # log_prefix fallback a DUID
    connection._controller = None
    connection._cfg.duid = "112233445566"
    assert connection.log_prefix == "[445566]"

    # log_prefix fallback a [NO_ID]
    connection._cfg.duid = None
    assert connection.log_prefix == "[NO_ID]"

    # is_async_native y is_push_supported
    assert connection.is_async_native is True
    assert connection.is_async_native  # Kill boolean mutants
    assert connection.is_push_supported is True
    assert connection.is_push_supported
    assert connection.match_type("samsung_2878") is True
    assert connection.match_type("otro_tipo") is False

    # set_update_callback
    async def dummy_callback(data):
        pass

    connection.set_update_callback(dummy_callback)
    assert connection._update_callback == dummy_callback


def test_samsung_2878_execute_raises(connection):
    """Mata el mutante de NotImplentedError en execute() síncrono."""
    with pytest.raises(NotImplementedError, match="async-native"):
        connection.execute(None, None, None)


def test_samsung_2878_get_diagnostics(connection):
    """Mata los mutantes del generador de diagnósticos."""
    # Estado inicial / Sin config
    connection._is_ready.clear()
    connection._reconnect_retries = 3
    connection._is_available = False
    connection._last_successful_config = None

    diag1 = connection.get_diagnostics()
    assert diag1["is_connected"] is False
    assert diag1["reconnect_retries"] == 3
    assert diag1["is_available"] is False
    assert diag1["last_successful_config"] is None

    # Estado con config guardada
    connection._is_ready.set()
    connection._last_successful_config = {
        "cert": "/fake/path/cert_file_secret.pem",
        "cipher_name": "AES-256-CBC",
    }
    diag2 = connection.get_diagnostics()
    assert diag2["is_connected"] is True
    assert diag2["last_successful_config"]["cert_filename"] == "cert_file_secret.pem"
    assert diag2["last_successful_config"]["cipher_name"] == "AES-256-CBC"


def test_samsung_2878_update_configuration_from_hass_and_yaml():
    """Mata mutantes de configuración inicial, load_from_yaml y create_updated."""

    # Simular config de Home Assistant
    hass_config = {
        "mac": "AA:BB:CC:DD:EE:FF",
        "ip_address": "192.168.1.100",
        "token": "test_token",
        "cert": "test.pem",
        "port": 2878,
        "preferred_connection": {"cert": "preferred.pem", "cipher_name": "TEST_CIPHER"},
    }

    conn = ConnectionSamsung2878(hass_config, MagicMock(), hass=MagicMock())

    assert conn._cfg.duid == "AABBCCDDEEFF"
    assert "test.pem" in conn._cfg.cert
    assert conn._last_successful_config["cipher_name"] == "TEST_CIPHER"
    assert "preferred.pem" in conn._last_successful_config["cert"]

    # load_from_yaml
    yaml_node = {
        "params": {"connection_template": "template", "power_template": "power"}
    }
    assert conn.load_from_yaml(yaml_node, None) is True
    assert conn._connection_init_template is not None
    assert conn._power_template is not None

    # create_updated
    new_conn = conn.create_updated(yaml_node)
    assert new_conn == conn

    # yaml fail cases
    assert conn.load_from_yaml(None, None) is False

    # Missing required templates when connection_base is None
    bad_yaml_node = {"params": {}}
    assert conn.load_from_yaml(bad_yaml_node, None) is False


# =====================================================================
# FASE 2: ASINCRONÍA BÁSICA, TAREAS Y ESTADOS (MEDIUM KILL)
# =====================================================================


def test_samsung_2878_ensure_callback_linked(connection):
    """Mata los mutantes del enlazado automático del callback."""
    # Simular que el controller tiene el método
    mock_cb = AsyncMock()
    connection._controller = MagicMock()
    connection._controller.on_push_update_callback = mock_cb
    connection._update_callback = None

    connection._ensure_callback_linked()
    assert connection._update_callback == mock_cb


@pytest.mark.asyncio
async def test_samsung_2878_process_command_queue(connection):
    """Mata los mutantes del procesamiento de la cola de comandos sin colgar el event loop."""
    future = asyncio.Future()

    # SIMULACIÓN SEGURA: Usamos un Future ya resuelto en lugar de un Task en vivo
    # Esto evita que mutmut rompa el event loop y cuelgue pytest.
    queue_task = asyncio.Future()
    queue_task.set_result(('<Request Type="Test"></Request>\n', future))

    with patch.object(connection, "_write_data", new_callable=AsyncMock) as mock_write:
        # Caso de éxito
        await connection._process_command_queue(queue_task)
        mock_write.assert_called_once_with('<Request Type="Test"></Request>\n')
        assert connection._pending_future == future
        assert (
            getattr(connection._pending_future, "_command_debug")
            == '<Request Type="Test"></Request>\n'
        )

        # Caso de error (CannotConnect)
        mock_write.reset_mock()
        mock_write.side_effect = CannotConnect("Test Error")

        future2 = asyncio.Future()
        queue_task2 = asyncio.Future()
        queue_task2.set_result(('<Request Type="Test2"></Request>\n', future2))

        await connection._process_command_queue(queue_task2)
        assert future2.exception() is not None
        assert isinstance(future2.exception(), CannotConnect)
        assert connection._pending_future is None


@pytest.mark.asyncio
async def test_samsung_2878_parse_redundant_power_on(connection):
    """Mata el mutante que ignora el update redundante de Power On."""
    # Forzar el estado actual a Encendido
    connection._device_status[PROTOCOL_2878_POWER_ID] = PROTOCOL_2878_VALUE_ON

    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    connection._controller.hass.async_add_executor_job = AsyncMock(
        side_effect=mock_async_add_executor_job
    )

    xml_redundant = f"""<?xml version="1.0" encoding="utf-8" ?>
    <Update Type="Status">
        <Status DUID="AABBCCDDEEFF" GroupID="AC" ModelID="AC" >
            <Attr ID="{PROTOCOL_2878_POWER_ID}" Value="{PROTOCOL_2878_VALUE_ON}" />
        </Status>
    </Update>
    """
    is_resp, is_upd, parsed = await connection._parse_and_update_state(xml_redundant)

    # Debe devolver todo en False/None porque ignoró el mensaje por ser redundante
    assert is_resp is False
    assert is_upd is False
    assert parsed is None


def test_ensure_callback_linked_mutants(connection):
    """Mata los mutantes de la condicional y el getattr sin default."""
    # Mutante 1: 'and' a 'or'. Si es 'or', entrará aquí e intentará hacer getattr sobre None,
    # lanzando AttributeError.
    connection._controller = None
    connection._update_callback = None
    connection._ensure_callback_linked()  # Si sobrevive el mutante 'or', esto explota

    # Mutante 8: Falta de 'None' en el getattr.
    # Le pasamos un objeto genérico que NO tiene 'on_push_update_callback'.
    # Si mutmut quitó el 'None' del getattr, lanzará AttributeError.
    connection._controller = object()
    connection._ensure_callback_linked()


def test_get_diagnostics_empty_cert(connection):
    """Mata el mutante de 'and' a 'or' en la comprobación del certificado."""
    # Le damos un cert vacío. Si mutmut cambia 'and' a 'or', intentará procesarlo y fallará.
    connection._last_successful_config = {"cert": ""}
    diag = connection.get_diagnostics()
    assert "cert_filename" not in diag["last_successful_config"]


def test_track_task_safe(connection):
    """Mata los 4 mutantes de _track_task SIN usar el event loop (Anti-Cuelgues)."""
    with patch("asyncio.create_task") as mock_create:
        mock_task = MagicMock()
        mock_create.return_value = mock_task

        async def dummy():
            pass

        result = connection._track_task(dummy())

        assert result == mock_task
        assert mock_task in connection._background_tasks
        # Comprueba que se añadió el callback para eliminarse del set
        mock_task.add_done_callback.assert_called_once_with(
            connection._background_tasks.discard
        )


# =====================================================================
# FASE 3: NETWORKING ASÍNCRONO, HANDSHAKE Y COLAS (SUPER FIXED)
# =====================================================================


def get_safe_mock_writer():
    """Crea un mock de writer asíncrono a prueba de bombas."""
    writer = MagicMock()
    writer.is_closing.return_value = False
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()  # ¡Este era el culpable de los TypeErrors!
    writer.close = MagicMock()
    writer.get_extra_info.return_value.version.return_value = "TLSv1.2"
    writer.get_extra_info.return_value.cipher.return_value = ("AES", "HIGH")
    return writer


@pytest.mark.asyncio
async def test_write_data_logic(connection):
    """Mata los mutantes de _write_data con Mocks seguros."""
    # 1. Sin writer
    connection._writer = None
    with pytest.raises(CannotConnect):
        await connection._write_data("test")

    # 2. Con writer cerrándose
    connection._writer = get_safe_mock_writer()
    connection._writer.is_closing.return_value = True
    with pytest.raises(CannotConnect):
        await connection._write_data("test")

    # 3. Flujo Feliz
    connection._writer = get_safe_mock_writer()
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.timeout"
    ) as mock_timeout:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock()
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_timeout.return_value = mock_ctx
        result = await connection._write_data("<Request/>")
        assert result is True
        connection._writer.write.assert_called_once_with(b"<Request/>")
        connection._writer.drain.assert_awaited_once()
        mock_timeout.assert_called_once_with(5.0)

    # 4. Fallo de Red (TimeoutError / OSError)
    connection._writer = get_safe_mock_writer()
    connection._writer.drain.side_effect = OSError("Network drop")
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.timeout"
    ) as mock_timeout:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock()
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_timeout.return_value = mock_ctx
        with pytest.raises(CannotConnect):
            await connection._write_data("test2")
        mock_timeout.assert_any_call(5.0)
    assert connection._writer is None


@pytest.mark.asyncio
async def test_close_connection_logic(connection):
    """Mata los mutantes de limpieza en _close_connection."""
    await connection._close_connection()  # Idempotencia

    connection._is_ready.set()
    connection._writer = get_safe_mock_writer()
    connection._reader = MagicMock()

    fake_read_task = asyncio.Future()
    connection._read_task = fake_read_task

    await connection._close_connection()

    assert not connection._is_ready.is_set()
    assert connection._writer is None
    assert connection._reader is None
    assert connection._read_task is None
    assert fake_read_task.cancelled() is True


@pytest.mark.asyncio
async def test_establish_connection_network_refused(connection):
    """Fallo de red puro que itera los ciphers."""
    connection._cfg.host = "192.168.1.50"
    with (
        patch("socket.socket"),
        patch("asyncio.get_running_loop") as mock_loop,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ),
    ):
        mock_loop_inst = MagicMock()
        mock_loop_inst.sock_connect = AsyncMock(side_effect=ConnectionRefusedError)
        mock_loop.return_value = mock_loop_inst

        # Tras fallar todos los ciphers, devuelve False
        assert await connection._establish_connection_and_handshake() is False


@pytest.mark.asyncio
async def test_process_read_queue_fragmented(connection):
    """Fragmentación de buffers y EOF en lectura."""
    connection._ensure_callback_linked = MagicMock()

    # 1. EOF
    connection._read_task = asyncio.Future()
    connection._read_task.set_result(b"")
    with patch.object(
        connection, "_close_connection", new_callable=AsyncMock
    ) as mock_close:
        assert await connection._process_read_queue(b"old") is None
        mock_close.assert_called_once()

    # 2. Fragmentación exitosa con tag completo
    connection._read_task = asyncio.Future()
    connection._read_task.set_result(b"sponse>")
    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = (True, False, {"power": "on"})
        # ¡Corrección aquí! Incluimos 'Response' en el inicio para que el bucle lo intercepte bien al unirse
        result = await connection._process_read_queue(b"<?xml><Response>data</Re")

        mock_parse.assert_called_once()
        assert result == b""
        assert connection._device_status["power"] == "on"


@pytest.mark.asyncio
async def test_process_read_queue_resolves_future(connection):
    """DeviceControl y resolución de Future en lectura."""
    connection._read_task = asyncio.Future()
    connection._read_task.set_result(b'<Response Type="DeviceControl" Status="Okay" />')

    pending_future = asyncio.Future()
    setattr(pending_future, "_command_debug", '<Request Type="DeviceControl" />')
    connection._pending_future = pending_future

    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = (True, False, None)
        await connection._process_read_queue(b"")
        assert pending_future.result() is True
        assert connection._pending_future is None


@pytest.mark.asyncio
async def test_establish_connection_success(connection):
    """Flujo feliz del Handshake asegurando llamadas AsyncMock."""
    connection._cfg.host = "192.168.1.50"
    connection._cfg.port = 2878
    connection._cfg.cert = "fake_cert.pem"
    connection._connection_init_template = MagicMock()
    connection._connection_init_template.async_render.return_value = "<Auth/>"
    connection._is_available = False

    with (
        patch("socket.socket"),
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open_conn,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ),
    ):
        # LA CLAVE: Forzar que sock_connect sea asíncrono
        mock_loop.return_value.sock_connect = AsyncMock()
        mock_writer = get_safe_mock_writer()
        mock_open_conn.return_value = (MagicMock(), mock_writer)

        with (
            patch.object(
                connection, "_read_full_response", new_callable=AsyncMock
            ) as mock_read_resp,
            patch.object(
                connection, "_write_data", new_callable=AsyncMock
            ) as mock_write,
            patch.object(
                connection, "_parse_and_update_state", new_callable=AsyncMock
            ) as mock_parse,
        ):
            mock_read_resp.side_effect = ["DPLUG-1.6\n", 'Status="Okay"']
            mock_parse.return_value = (False, False, None)

            result = await connection._establish_connection_and_handshake()

            assert result is True
            assert connection._is_ready.is_set()
            mock_open_conn.assert_called_once()
            mock_write.assert_called_once_with("<Auth/>\n")


@pytest.mark.asyncio
async def test_establish_connection_auth_failure(connection):
    """Errores de Autenticación 301 e InvalidateAccount."""
    connection._cfg.host = "192.168.1.50"
    connection._connection_init_template = MagicMock()
    connection._connection_init_template.async_render.return_value = "<Auth/>"

    # Inyectamos mocks básicos para el controlador
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    with (
        patch("socket.socket"),
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open_conn,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ),
    ):
        mock_loop.return_value.sock_connect = AsyncMock()
        mock_writer = get_safe_mock_writer()
        mock_open_conn.return_value = (MagicMock(), mock_writer)

        # AÑADIDO: mock_parse para evitar el RuntimeError del XML de Home Assistant
        with (
            patch.object(
                connection, "_read_full_response", new_callable=AsyncMock
            ) as mock_read_resp,
            patch.object(connection, "_write_data", new_callable=AsyncMock),
            patch.object(
                connection, "_parse_and_update_state", new_callable=AsyncMock
            ) as mock_parse,
        ):
            mock_parse.return_value = (False, False, None)

            # CASO 1: InvalidateAccount
            mock_read_resp.side_effect = ["DPLUG-1.6\n", "InvalidateAccount"]
            assert await connection._establish_connection_and_handshake() is False

            # CASO 2: ErrorCode 301

            mock_read_resp.side_effect = ["DPLUG-1.6\n", 'ErrorCode="301"']
            with pytest.raises(AuthError, match="Device was turned off"):
                await connection._establish_connection_and_handshake()


@pytest.mark.asyncio
async def test_establish_connection_ssl_cache_and_ciphers(connection):
    """Caché de contexto SSL y KeepAlive TCP."""
    connection._cfg.host = "192.168.1.50"
    connection._cfg.cert = "fake_cert.pem"
    connection._connection_init_template = MagicMock()
    connection._connection_init_template.async_render.return_value = "<Auth/>"

    with (
        patch("socket.socket") as mock_socket,
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open_conn,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ) as mock_ssl_ctx,
    ):
        mock_loop.return_value.sock_connect = AsyncMock()
        mock_writer = get_safe_mock_writer()
        mock_open_conn.return_value = (MagicMock(), mock_writer)
        mock_ssl_ctx.return_value = MagicMock()

        # ¡AQUÍ ESTÁ LA MAGIA! Añadimos _post_connect_status_request al bloque de patches
        with (
            patch.object(
                connection, "_read_full_response", new_callable=AsyncMock
            ) as mock_read,
            patch.object(connection, "_write_data", new_callable=AsyncMock),
            patch.object(
                connection, "_parse_and_update_state", new_callable=AsyncMock
            ) as mock_parse,
            patch.object(
                connection, "_post_connect_status_request", new_callable=AsyncMock
            ),
        ):
            mock_read.side_effect = ["DPLUG-1.6\n", 'Status="Okay"']
            mock_parse.return_value = (False, False, None)

            # 1. Primera pasada
            assert await connection._establish_connection_and_handshake() is True
            assert mock_ssl_ctx.call_count == 1

            mock_sock_inst = mock_socket.return_value
            mock_sock_inst.setsockopt.assert_any_call(
                socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1
            )

            # 2. Segunda pasada: Debe usar la caché
            connection._is_ready.clear()
            mock_read.side_effect = ["DPLUG-1.6\n", 'Status="Okay"']
            assert await connection._establish_connection_and_handshake() is True
            assert mock_ssl_ctx.call_count == 1


# =====================================================================
# FASE FINAL: ASYNC EXECUTE, RECONNECT LOOP Y CONNECTION MANAGER
# =====================================================================


@pytest.mark.asyncio
async def test_async_execute_timeout_and_success(connection):
    """Mata mutantes de async_execute (Timeout, Success, Is_Poll)."""
    connection._ensure_callback_linked = MagicMock()
    connection.start_listening = MagicMock()

    # Simular que el manager ya está corriendo
    connection._manager_task = MagicMock()
    connection._manager_task.done.return_value = False

    # 1. Fallo rápido si no está listo y ya hubo reintentos
    connection._is_ready.clear()
    connection._reconnect_retries = 1
    with patch("custom_components.climate_ip.samsung_2878.COMMAND_TIMEOUT", 0.01):
        with pytest.raises(CannotConnect, match="Client not ready"):
            await connection.async_execute(None, None, "<Test/>", None)

    # 2. Timeout esperando a que esté listo (Dispara la excepción)
    connection._reconnect_retries = 0
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.timeout",
        side_effect=TimeoutError,
    ):
        with pytest.raises(CannotConnect, match="Timeout waiting for connection"):
            await connection.async_execute(None, None, "<Test/>", None)

    # 3. Éxito: Encolado de comando correcto
    connection._is_ready.set()

    # Simulamos que al meter el comando en la cola, otro proceso resuelve el future instantáneamente
    async def mock_queue_put(item):
        cmd, future = item
        future.set_result(True)

    connection._cmd_queue = MagicMock()
    connection._cmd_queue.put = AsyncMock(side_effect=mock_queue_put)

    # Ejecutamos comando normal
    json_state, _ = await connection.async_execute(None, None, "<MyData>", None)
    assert json_state == "{}"  # device_status vacio por defecto
    connection._cmd_queue.put.assert_called_once()
    assert "<MyData>\n" in connection._cmd_queue.put.call_args[0][0][0]

    # Ejecutamos modo poll
    connection._cmd_queue.put.reset_mock()
    connection._cfg.duid = "TESTDUID"
    await connection.async_execute(None, None, None, None, _is_poll=True)
    assert 'Type="DeviceState"' in connection._cmd_queue.put.call_args[0][0][0]


@pytest.mark.asyncio
async def test_handle_reconnection_backoff(connection):
    """Mata mutantes del backoff exponencial y limpieza de repair issues."""
    connection._cfg.host = "192.168.1.50"

    # CRÍTICO: Parchear en el namespace de samsung_2878, no en helpers
    with (
        patch(
            "custom_components.climate_ip.samsung_2878.async_check_network_reachability",
            new_callable=AsyncMock,
        ) as mock_ping,
        patch.object(
            connection, "_establish_connection_and_handshake", new_callable=AsyncMock
        ) as mock_handshake,
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        # Escenario 1: Ping falla (Network down)
        mock_ping.return_value = False
        connection._reconnect_delay = 5
        connection._reconnect_retries = 0

        assert await connection.handle_reconnection() is False
        assert connection._reconnect_retries == 1
        assert connection._reconnect_delay == 10  # 5 * factor 2
        mock_handshake.assert_not_called()

        # Escenario 2: Ping bien, pero Handshake falla (Port down)
        mock_ping.return_value = True
        mock_handshake.return_value = False

        assert await connection.handle_reconnection() is False
        assert connection._reconnect_retries == 2
        assert connection._reconnect_delay == 20  # 10 * factor 2
        mock_handshake.assert_called_once()

        # Escenario 3: Ping bien, handshake levanta Exception
        mock_handshake.reset_mock()
        mock_handshake.side_effect = CannotConnect("Test Error")
        # Simular que hay un future pendiente que debe fallar
        fake_future = asyncio.Future()
        connection._pending_future = fake_future

        assert await connection.handle_reconnection() is False
        assert connection._reconnect_retries == 3
        assert connection._reconnect_delay == 40
        assert fake_future.exception() is not None
        assert connection._pending_future is None


@pytest.mark.asyncio
async def test_connection_manager_loop_logic(connection):
    """Mata mutantes de las condiciones y limpiezas del loop del connection_manager sin colgarse."""

    with (
        patch.object(
            connection, "handle_reconnection", new_callable=AsyncMock
        ) as mock_reconn,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        connection._writer = None

        # LA BALA DE PLATA: Lanzamos CancelledError.
        # Como no hereda de Exception sino de BaseException, se salta el 'except Exception'
        # y destruye el 'while True' de forma fulminante.
        mock_reconn.side_effect = asyncio.CancelledError()

        fake_read_task = asyncio.Future()
        connection._read_task = fake_read_task

        await connection.stop_listening()

        with patch.object(
            connection, "_close_connection", new_callable=AsyncMock
        ) as mock_close:
            # Esperamos que la cancelación suba hacia arriba
            with pytest.raises(asyncio.CancelledError):
                await connection._connection_manager()

            # Verificamos que el bloque finally sí se ejecutó antes de morir
            assert fake_read_task.cancelled() is True
            mock_close.assert_called()


@pytest.mark.asyncio
async def test_async_execute_future_timeout(connection):
    """Mata los mutantes de limpieza de Future cuando un comando individual da timeout."""
    connection._ensure_callback_linked = MagicMock()
    connection._is_ready.set()
    connection._manager_task = MagicMock()
    connection._manager_task.done.return_value = False

    connection._cmd_queue = MagicMock()

    async def mock_queue_put(item):
        cmd, future = item
        # Guardamos la referencia como haría el manager
        connection._pending_future = future

        # EL TRUCO MAGISTRAL: Inyectamos el TimeoutError directamente en el Future.
        # Cuando el código haga 'await future', explotará instantáneamente
        # simulando un timeout real sin tener que esperar ni parchear context managers.
        future.set_exception(TimeoutError("Fake Timeout"))

    connection._cmd_queue.put = AsyncMock(side_effect=mock_queue_put)

    with patch.object(
        connection, "_close_connection", new_callable=AsyncMock
    ) as mock_close:
        with pytest.raises(CannotConnect, match="Command timed out"):
            await connection.async_execute(None, None, "<Test/>", None)

        # Validaciones de que la limpieza se ha hecho correctamente
        assert connection._pending_future is None
        mock_close.assert_called_once()


# =====================================================================
# FASE 4 (GOLPE FINAL): COBERTURA TOTAL Y BUCLES INTERNOS
# =====================================================================


@pytest.mark.asyncio
async def test_samsung_2878_start_stop_listening_strict(connection):
    """Mata mutantes de start/stop y chequeos de tareas."""
    connection._ensure_callback_linked = MagicMock()

    # 1. start_listening cuando task ya está corriendo (no debe sobreescribir)
    connection._manager_task = MagicMock()
    connection._manager_task.done.return_value = False
    connection._reconnect_retries = 99

    connection.start_listening()
    # Si mutmut cambia 'or' a 'and', sobreescribirá y retries bajará a 0
    assert connection._reconnect_retries == 99

    # 2. stop_listening asegura que la tarea se borra a None estricto
    mock_task = asyncio.Future()
    mock_task.cancel = MagicMock()
    mock_task.set_result(None)
    connection._manager_task = mock_task

    await connection.stop_listening()
    assert connection._manager_task is None  # Mata el mutante self._manager_task = ""


def test_load_from_yaml_missing_params():
    """Mata el mutante que devuelve True cuando falta el DUID."""

    conn = ConnectionSamsung2878(
        {"host": "192.168.1.10"}, MagicMock(), hass=MagicMock()
    )
    # Falla porque le falta el DUID/mac
    assert conn.load_from_yaml({"params": {}}, None) is False


@pytest.mark.asyncio
async def test_post_connect_status_request_strict(connection):
    """Mata mutantes de _post_connect_status_request (Timeouts y puts)."""
    connection._cfg.duid = "12345"
    connection._cmd_queue = MagicMock()

    # Éxito
    async def mock_put_success(item):
        cmd, fut = item
        assert "DeviceState" in cmd
        assert "12345" in cmd
        fut.set_result(True)

    connection._cmd_queue.put = AsyncMock(side_effect=mock_put_success)
    await connection._post_connect_status_request()

    # Timeout
    asyncio.Future()

    async def mock_put_timeout(item):
        cmd, fut = item
        connection._pending_future = fut
        raise TimeoutError()  # Simulamos que el async with timeout corta la espera

    connection._cmd_queue.put = AsyncMock(side_effect=mock_put_timeout)
    await connection._post_connect_status_request()
    # Debe haber limpiado el future
    assert connection._pending_future is None


@pytest.mark.asyncio
async def test_parse_state_multiple_docs(connection):
    """Mata el mutante de 'break' vs 'continue' al parsear basura antes del XML real."""
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    async def mock_add_exec(func, *args, **kwargs):
        return func(*args, **kwargs)

    connection._controller.hass.async_add_executor_job = AsyncMock(
        side_effect=mock_add_exec
    )

    # Dos bloques XML juntos. El primero es inútil, el segundo es un Update válido
    # Si hay un 'break', se saltará el segundo. Si hay 'continue', lo procesará.
    xml = '<?xml version="1.0"?><Fake/><?xml version="1.0"?><Update Type="Status"><Status DUID="1"><Attr ID="AC_FUN_POWER" Value="Off"/></Status></Update>'
    is_res, is_upd, parsed = await connection._parse_and_update_state(xml)

    assert is_upd is True
    assert parsed["AC_FUN_POWER"] == "Off"


@pytest.mark.asyncio
async def test_process_read_queue_cancelled(connection):
    """Mata los mutantes de variables None y CancelledError en lectura."""
    connection._read_task = asyncio.Future()
    connection._read_task.cancel()  # Lanza CancelledError al hacer .result()

    with patch.object(
        connection, "_close_connection", new_callable=AsyncMock
    ) as mock_close:
        res = await connection._process_read_queue(b"buffer")
        assert res is None  # Mata data = ""
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_establish_connection_cipher_iteration_and_issue_clear(connection):
    """Mata mutantes de iteración de ciphers (break vs continue) y async_delete_issue."""
    connection._cfg.host = "1.2.3.4"
    connection._connection_init_template = MagicMock()
    connection._is_available = False  # Fuerza que elimine el repair issue al reconectar

    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    with (
        patch("socket.socket"),
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open_conn,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.async_delete_issue"
        ) as mock_delete,
    ):
        mock_loop.return_value.sock_connect = AsyncMock()

        # EL TRUCO: Fallamos la primera conexión SSL, acertamos la segunda
        # Si mutmut puso un 'break', devolverá False en vez de intentar la segunda.
        mock_open_conn.side_effect = [
            ssl.SSLError("Cipher 1 fallback"),
            (MagicMock(), get_safe_mock_writer()),
        ]

        with (
            patch.object(
                connection, "_read_full_response", new_callable=AsyncMock
            ) as mock_read,
            patch.object(connection, "_write_data", new_callable=AsyncMock),
            patch.object(
                connection, "_parse_and_update_state", new_callable=AsyncMock
            ) as mock_parse,
        ):
            mock_read.side_effect = ["DPLUG-1.6\n", 'Status="Okay"']
            mock_parse.return_value = (False, False, None)

            res = await connection._establish_connection_and_handshake()

            assert res is True
            assert mock_open_conn.call_count == 2

            # Verificamos que al tener éxito, borró el issue pasándole HASS explícitamente
            mock_delete.assert_called_once_with(
                connection._controller.hass, "climate_ip", "connection_failed_1.2.3.4"
            )


@pytest.mark.asyncio
async def test_connection_manager_full_coverage(connection):
    """Mata los 52 mutantes del Connection Manager iterando el bucle completo de forma natural."""
    connection._writer = get_safe_mock_writer()
    connection._reader = MagicMock()
    connection._cmd_queue = asyncio.Queue()

    # Preparamos un comando para que queue_task termine en el primer ciclo
    await connection._cmd_queue.put(("<Cmd1/>", asyncio.Future()))

    # Controlamos las iteraciones del _read_task:
    # 1. Devuelve b"" (EOF) -> fuerza continue y limpieza
    # 2. Lanza CancelledError -> Rompe el loop de nuestro manager
    read_returns = [b"", asyncio.CancelledError()]

    async def mock_read(size):
        res = read_returns.pop(0)
        if isinstance(res, Exception):
            raise res
        return res

    connection._reader.read = AsyncMock(side_effect=mock_read)

    with (
        patch.object(
            connection, "_process_command_queue", new_callable=AsyncMock
        ) as mock_cmd,
        patch.object(
            connection, "_process_read_queue", new_callable=AsyncMock
        ) as mock_read_q,
    ):
        # Cuando procese EOF, _process_read_queue devuelve None, que limpia buffer y hace continue
        # En el segundo ciclo salta la CancelledError, matando el bucle infinito.
        mock_read_q.side_effect = [None, asyncio.CancelledError()]

        with pytest.raises(asyncio.CancelledError):
            await connection._connection_manager()

        # Si llegó aquí sin colgarse, el loop procesó la cola correctamente y manejó el CancelledError
        assert mock_cmd.call_count == 1
        assert mock_read_q.call_count == 2


@pytest.mark.asyncio
async def test_async_execute_defaults(connection):
    """Mata los mutantes de parámetros booleanos por defecto (_is_probe, _is_poll)."""
    connection._ensure_callback_linked = MagicMock()
    connection.start_listening = MagicMock()
    connection._is_ready.set()
    connection._reconnect_retries = 0
    connection._manager_task = MagicMock()
    connection._manager_task.done.return_value = False

    # Si ejecutamos con (None, None, None, None), _is_poll es False por defecto
    # por lo que command quedará en None y devolverá (None, None) al instante.
    res1, res2 = await connection.async_execute(None, None, None, None)
    assert res1 is None
    assert res2 is None


@pytest.mark.asyncio
async def test_handle_reconnection_success_path(connection):
    """Mata el mutante de 'return False' al final de handle_reconnection."""
    with (
        patch(
            "custom_components.climate_ip.samsung_2878.async_check_network_reachability",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(
            connection,
            "_establish_connection_and_handshake",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        res = await connection.handle_reconnection()
        assert res is True  # Si mutmut pone return False aquí, el test explota


# =====================================================================
# FASE 5 (MISIL FINAL): LIMPIEZAS EXTREMAS, FIRMAS Y EXCEPTIONS RARAS
# =====================================================================


def test_async_execute_signature(connection):
    """Mata mutantes que alteran los defaults booleanos de async_execute usando introspección."""
    sig = inspect.signature(connection.async_execute)
    assert sig.parameters["_is_probe"].default is False
    assert sig.parameters["_is_poll"].default is False


@pytest.mark.asyncio
async def test_establish_connection_callbacks_and_generic_catch(connection):
    """Mata mutantes de callbacks y del bloque 'except Exception' al iterar ciphers."""
    connection._cfg.host = "1.1.1.1"
    connection._connection_init_template = MagicMock()
    connection._is_available = False
    connection._initial_connection_done = True

    mock_update_cb = AsyncMock()
    connection.set_update_callback(mock_update_cb)
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()
    connection._controller.request_refresh_callback = AsyncMock()

    with (
        patch("socket.socket"),
        patch("asyncio.get_running_loop") as mock_loop,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ),
    ):
        mock_loop.return_value.sock_connect = AsyncMock(
            side_effect=[RuntimeError("Weird network issue"), None]
        )

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = (MagicMock(), get_safe_mock_writer())

            # ¡AQUÍ ESTÁ EL ANTÍDOTO! Añadimos el patch para _post_connect_status_request
            with (
                patch.object(
                    connection, "_read_full_response", new_callable=AsyncMock
                ) as mock_read,
                patch.object(connection, "_write_data", new_callable=AsyncMock),
                patch.object(
                    connection, "_parse_and_update_state", new_callable=AsyncMock
                ) as mock_parse,
                patch.object(
                    connection, "_post_connect_status_request", new_callable=AsyncMock
                ),
            ):
                mock_read.side_effect = ["DPLUG-1.6", 'Status="Okay"']
                mock_parse.return_value = (False, True, {"fake": "state"})

                # Ejecutamos. Si el mutante cambió 'continue' a 'break' en el catch genérico, devolvería False
                assert await connection._establish_connection_and_handshake() is True

                # Validamos que se llamaron a los callbacks
                mock_update_cb.assert_called_once_with({"fake": "state"})
                connection._controller.request_refresh_callback.assert_called_once()


def test_load_from_yaml_missing_mac(connection):
    """Mata el mutante que altera el retorno cuando falta el DUID/MAC."""
    connection._cfg.duid = None  # Forzamos que falte el MAC
    # Parcheamos 'Template' para que no explote el Frame Helper de HA
    with patch("custom_components.climate_ip.samsung_2878.Template"):
        # Si mutmut cambió 'return False' por 'return True', esto fallará
        assert (
            connection.load_from_yaml({"params": {"connection_template": "a"}}, None)
            is False
        )


@pytest.mark.asyncio
async def test_establish_connection_deep_mutants(connection):
    """Mata mutantes en las entrañas de _establish_connection_and_handshake."""
    connection._cfg.host = "1.1.1.1"
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    with (
        patch("socket.socket"),
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ),
    ):
        mock_loop.return_value.sock_connect = AsyncMock()
        mock_open.return_value = (MagicMock(), get_safe_mock_writer())

        # AÑADIDO: mock_parse para sortear la seguridad XML de Home Assistant
        with (
            patch.object(
                connection, "_read_full_response", new_callable=AsyncMock
            ) as mock_read,
            patch.object(connection, "_write_data", new_callable=AsyncMock),
            patch.object(
                connection, "_parse_and_update_state", new_callable=AsyncMock
            ) as mock_parse,
        ):
            mock_parse.return_value = (False, False, None)

            # CASO 1: Mensaje inicial basura
            mock_read.return_value = "GARBAGE-HEADER"
            with pytest.raises(
                CannotConnect, match="Did not receive expected initial message"
            ):
                await connection._establish_connection_and_handshake()

            # CASO 2: Plantilla vacía
            connection._connection_init_template = None
            mock_read.return_value = "DPLUG-1.6"
            with pytest.raises(
                CannotConnect, match="Connection initialization template is missing"
            ):
                await connection._establish_connection_and_handshake()

            # CASO 3: Auth fallido sin código 301 ni Invalidate
            connection._connection_init_template = MagicMock()
            mock_read.side_effect = ["DPLUG-1.6", '<Response Status="Failed" />']

            with pytest.raises(
                AuthError,
                match="Authentication failed: No response|Authentication failed",
            ):
                await connection._establish_connection_and_handshake()

            # CASO 4: Auth fallido con ErrorCode genérico (regex fallback)
            mock_read.side_effect = [
                "DPLUG-1.6",
                '<Response Status="Failed" ErrorCode="999" />',
            ]
            with pytest.raises(AuthError, match="Authentication failed"):
                await connection._establish_connection_and_handshake()


@pytest.mark.asyncio
async def test_connection_manager_queues_and_cleanup(connection):
    """Mata los mutantes del bloque finally y gestión de colas dentro del while True."""
    connection._writer = get_safe_mock_writer()
    connection._reader = MagicMock()
    connection._cmd_queue = asyncio.Queue()

    # Usamos MagicMock en vez de Future para asegurar el chequeo de cancel()

    # irp
    # fake_read_task = MagicMock()
    # fake_read_task.done.return_value = False
    # fake_queue_task = MagicMock()
    # fake_queue_task.done.return_value = False
    fake_read_task = asyncio.Future()
    fake_queue_task = asyncio.Future()

    async def mock_wait(tasks, **kwargs):
        return ({fake_queue_task}, {fake_read_task})

    with (
        patch("asyncio.wait", side_effect=mock_wait),
        patch.object(
            connection, "_process_command_queue", new_callable=AsyncMock
        ) as mock_cmd,
    ):
        # Al procesar el comando forzamos un OSError para romper el loop
        mock_cmd.side_effect = OSError("Crash to finally")

        call_count = 0

        def mock_create_task(coro):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                connection._read_task = fake_read_task
                return fake_read_task
            return fake_queue_task

        with (
            patch("asyncio.create_task", side_effect=mock_create_task),
            patch.object(connection, "_close_connection", new_callable=AsyncMock),
        ):
            # EL ARREGLO FINAL: Dejamos pasar el primer sleep(2) de arranque,
            # y reventamos el segundo sleep (el de recuperación tras el error)
            with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):
                with pytest.raises(asyncio.CancelledError):
                    await connection._connection_manager()

            # MATA MUTANTES DEL FINALLY: Valida que task.cancel() se llamó en ambas tareas
            # irp
            # fake_read_task.cancel.assert_called_once()
            # fake_queue_task.cancel.assert_called_once()
            assert fake_read_task.cancelled() is True, (
                "El mutante sobrevivió: _read_task no fue cancelada en el finally"
            )
            assert fake_queue_task.cancelled() is True, (
                "El mutante sobrevivió: queue_task no fue cancelada en el finally"
            )


class MutantTimeoutError(Exception):
    pass


def alarm_handler(signum, frame):
    raise MutantTimeoutError("Infinite loop detected and destroyed!")


@pytest.mark.asyncio
async def test_process_read_queue_exception(connection):
    """Mata mutantes de 'is_cancelled' dentro del catch genérico de lectura."""
    future = asyncio.Future()
    future.set_exception(RuntimeError("Random crash"))
    connection._read_task = future

    with patch.object(
        connection, "_close_connection", new_callable=AsyncMock
    ) as mock_close:
        res = await connection._process_read_queue(b"")
        assert res is None
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_connection_manager_reconnect_continue(connection):
    """Mata el mutante que cambia 'continue' por 'break' al fallar la reconexión."""
    connection._writer = None
    connection._read_task = None

    with (
        patch.object(
            connection, "handle_reconnection", new_callable=AsyncMock
        ) as mock_reconn,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        # Hacemos que handle_reconnection falle la primera vez (devuelve False -> entra al continue),
        # y lance CancelledError la segunda vez para romper el while de forma controlada.
        mock_reconn.side_effect = [False, asyncio.CancelledError()]

        with patch.object(connection, "_close_connection", new_callable=AsyncMock):
            with pytest.raises(asyncio.CancelledError):
                await connection._connection_manager()

        # Si el mutante cambió 'continue' por 'break', el loop se habría roto tras el primer False
        # y mock_reconn solo tendría 1 llamada. Al asertar 2, matamos al mutante.
        assert mock_reconn.call_count == 2


@pytest.mark.asyncio
async def test_connection_manager_reconnect_continue_strict(connection):
    """Mata el mutante que cambia 'continue' por 'break' al fallar la reconexión (Línea 1283)."""
    connection._writer = None

    with (
        patch.object(
            connection, "handle_reconnection", new_callable=AsyncMock
        ) as mock_reconn,
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        # EL TRUCO: El primero devuelve False (falla red) -> activa el 'continue'
        # El segundo lanza CancelledError -> rompe el loop 'while True' de forma controlada
        mock_reconn.side_effect = [False, asyncio.CancelledError()]

        with pytest.raises(asyncio.CancelledError):
            await connection._connection_manager()

        # Si mutmut cambió 'continue' por 'break', el código habría salido del bucle
        # en el primer intento y call_count sería 1. Al exigir 2, el mutante muere.
        assert mock_reconn.call_count == 2


def test_start_listening_strict_assignments(connection):
    """Mata los mutantes de asignación a None en start_listening (Líneas 188 y 189)."""
    connection._ensure_callback_linked = MagicMock()
    # Limpiamos la variable para que el código no se salte el bloque IF
    connection._manager_task = None
    connection._reconnect_retries = 99

    with (
        patch("asyncio.create_task") as mock_create,
        patch.object(connection, "_connection_manager"),
    ):
        mock_create.return_value = "fake_task"

        connection.start_listening()

        # Si mutmut cambió el 0 por None, esto falla
        assert connection._reconnect_retries == 0
        # Si mutmut eliminó el create_task, esto falla
        assert connection._manager_task == "fake_task"
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_connection_manager_missing_reader_continue_strict(connection):
    """Mata al ÚLTIMO mutante: cambia 'continue' por 'break' cuando se pierde el _reader."""

    # 1. Estado inicial: Forzamos que el _writer esté vivo, pero el _reader esté caído
    # Esto evade el primer IF y nos hace caer directamente en la trampa del segundo IF
    connection._writer = get_safe_mock_writer()
    connection._reader = None

    with (
        patch.object(
            connection, "handle_reconnection", new_callable=AsyncMock
        ) as mock_reconn,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        # LA TRAMPA:
        # 1ª iteración: Devuelve True -> Debe golpear el 'continue'.
        # 2ª iteración: Lanza CancelledError -> Destruye el bucle para poder asertar.
        mock_reconn.side_effect = [True, asyncio.CancelledError()]

        # IMPORTANTE: NO mockeamos _close_connection.
        # Dejamos que el código real mate al _writer poniéndolo a None.
        # Así, en la 2ª iteración obligada por el 'continue', entrará por el primer IF y lanzará el error.
        with pytest.raises(asyncio.CancelledError):
            await connection._connection_manager()

        # Si el mutante cambió 'continue' por 'break', la función habría terminado limpiamente en la 1ª iteración.
        # Al exigir que se haya llamado 2 veces (es decir, que haya dado la 2ª vuelta), aniquilamos al mutante.
        assert mock_reconn.call_count == 2


##STRUCTURAL###########


# =====================================================================
# FASE 6 (MUTMUT OLD): ESTRUCTURA, DICCIONARIOS Y VALORES POR DEFECTO
# =====================================================================


def test_create_updated_strict(connection):
    """Mata el mutante que altera los argumentos de create_updated y load_from_yaml."""
    with patch.object(connection, "load_from_yaml") as mock_load:
        fake_node = {"test": 1}
        res = connection.create_updated(fake_node)

        assert res is connection
        # Aseguramos que se pasa fake_node y self, no None
        mock_load.assert_called_once_with(fake_node, connection)


@patch("custom_components.climate_ip.samsung_2878.async_create_issue")
def test_check_and_create_repair_issue_strict(mock_issue, connection):
    """Mata los mutantes kwargs estrictos de la API de HASS."""

    connection._reconnect_retries = 3
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()
    connection._cfg.host = "1.2.3.4"
    connection._cfg.name = "MyAC"

    connection._check_and_create_repair_issue()

    mock_issue.assert_called_once()
    args, kwargs = mock_issue.call_args

    # Validaciones anti-mutmut ultra estrictas
    assert args[0] is connection._controller.hass
    assert args[1] == "climate_ip"
    assert args[2] == "connection_failed_1.2.3.4"
    assert kwargs["is_fixable"] is False
    assert kwargs["severity"] == IssueSeverity.WARNING
    assert kwargs["translation_key"] == "connection_failed"
    assert kwargs["translation_placeholders"]["host"] == "1.2.3.4"
    assert kwargs["translation_placeholders"]["name"] == "MyAC"


def test_update_configuration_from_hass_strict(connection):
    """Mata los mutantes de claves de diccionarios, get() fallbacks y resoluciones de path."""
    # 1. Fallback exacto de puerto (mata hass_config.get(CONF_PORT, 2879))
    connection.update_configuration_from_hass({"ip_address": "1.1.1.1"})
    assert connection._cfg.port == 2878

    # 2. Claves de last_successful_config y paths inyectados desde HA config

    hass_config = {
        "ip_address": "1.1.1.1",
        "preferred_connection": {
            "cert": "fake.pem",
            "cipher_name": "AES",
            "verify_mode": 0,
        },
    }
    connection.update_configuration_from_hass(hass_config)

    # Verificamos que resolvió la ruta del cert haciéndola absoluta (contiene separadores)
    cert_path = connection._last_successful_config["cert"]
    assert "fake.pem" in cert_path
    assert "/" in cert_path or "\\" in cert_path
    assert connection._last_successful_config["cipher_name"] == "AES"


@pytest.mark.asyncio
async def test_process_read_queue_end_tags(connection):
    """Mata mutantes de tags ternarios (/>, </Update>, </Response>)."""
    # Para que entre al while, read_task debe devolver ALGO (data no puede ser vacía)
    mock_task = asyncio.Future()
    mock_task.set_result(b"More")
    connection._read_task = mock_task

    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = (False, False, None)

        # Le pasamos el inicio del mensaje, se concatena con "More"
        res = await connection._process_read_queue(b"Data<Fake/>")

        # El buffer final debe ser "More" tras extraer "Data<Fake/>"
        assert res == b"More"
        mock_parse.assert_called_once_with("Data<Fake/>")


def test_init_strict_defaults():
    """Mata los mutantes del constructor (__init__) y sus tipos."""

    # Creamos un objeto limpio con un diccionario vacío y un MagicMock
    conn = ConnectionSamsung2878({}, MagicMock())

    # Valores exactos usando la misma referencia de variable que el módulo
    assert conn._socket_timeout == float(samsung_module.GLOBAL_HTTP_TIMEOUT) + 10.0
    assert conn._is_available is True
    assert conn._initial_connection_done is False
    assert isinstance(conn._cmd_queue, asyncio.Queue)
    assert conn._reconnect_retries == 0
    assert conn._pending_future is None


def test_execute_sync_not_implemented(connection):
    """Mata los mutantes de strings y NotImplementedError en execute()."""
    # La firma espera de 4 a 5 argumentos (incluyendo self). Le pasamos 3 Nones para cumplir.
    with pytest.raises(
        NotImplementedError,
        match="^ConnectionSamsung2878 is async-native\\. Use async_execute\\.$",
    ):
        connection.execute(None, None, None)


# def test_force_unavailability_if_needed_strict():
#     """Mata mutantes de strings y hasattr en la indisponibilidad usando Análisis Estático."""
#     import inspect
#     from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878

#     # 1. Mata los mutantes del valor por defecto ("Network" -> "network", "NETWORK", "XXNetworkXX")
#     # Inspeccionamos la firma de la función sin ejecutarla
#     sig = inspect.signature(ConnectionSamsung2878._force_unavailability_if_needed)
#     assert sig.parameters['offline_type'].default == "Network"

#     # 2. Mata los mutantes lógicos y de strings dentro del bloque IF
#     # Obtenemos el código fuente de la función tal cual está en memoria
#     source = inspect.getsource(ConnectionSamsung2878._force_unavailability_if_needed)

#     # Si Mutmut cambia 'and' por 'or', o cambia el string "on_offline_callback", esto fallará matemáticamente
#     assert 'and hasattr(self._controller, "on_offline_callback")' in source
#     assert 'and self._controller.on_offline_callback:' in source

# def test_samsung_2878_force_unavailability(connection):
#     """Mata los mutantes de _force_unavailability_if_needed."""
#     mock_controller = MagicMock()
#     connection._controller = mock_controller

#     # Caso 1: retries != 2 (No hace nada)
#     connection._reconnect_retries = 1
#     connection._force_unavailability_if_needed("Network")
#     mock_controller.on_offline_callback.assert_not_called()
#     mock_controller.on_connection_failed_callback.assert_not_called() # <-- CORRECCIÓN: No se llama si retries != 2
#     assert connection._persistent_offline_err_logged is False

#     # Caso 2: retries == 2, initial_connection_done = True
#     mock_controller.reset_mock()
#     connection._reconnect_retries = 2
#     connection._initial_connection_done = True
#     connection._force_unavailability_if_needed("Service")

#     mock_controller.on_offline_callback.assert_called_once_with("Host unreachable after multiple retry attempts.")
#     mock_controller.on_connection_failed_callback.assert_called_once()
#     assert connection._persistent_offline_err_logged is True

#     # Caso 3: Ya está logeado (evita spam de offline, pero sí notifica connection_failed)
#     mock_controller.reset_mock()
#     connection._reconnect_retries = 2
#     connection._force_unavailability_if_needed("Service")

#     # Al estar a True, no debe volver a llamar a on_offline_callback
#     mock_controller.on_offline_callback.assert_not_called()
#     # Pero sí debe llamar a on_connection_failed_callback porque está fuera de la validación del booleano
#     mock_controller.on_connection_failed_callback.assert_called_once()


def test_samsung_2878_force_unavailability(connection):
    """Mata los mutantes de _force_unavailability_if_needed usando una clase estricta."""

    # CLASE ESTRICTA: Mata mutantes que alteran las strings de los callbacks
    class StrictMockController:
        def __init__(self):
            # Atributos de identidad para que self.log_prefix no crashee
            self.unique_id = "strict_id"
            self.log_prefix = "[strict_id]"

            # Callbacks a validar
            self.on_offline_callback = MagicMock()
            self.on_connection_failed_callback = MagicMock()

        def reset_mock(self):
            self.on_offline_callback.reset_mock()
            self.on_connection_failed_callback.reset_mock()

    mock_controller = StrictMockController()
    connection._controller = mock_controller

    # Caso 1: retries != 2 (No hace nada)
    connection._reconnect_retries = 1
    connection._force_unavailability_if_needed("Network")
    mock_controller.on_offline_callback.assert_not_called()
    mock_controller.on_connection_failed_callback.assert_not_called()
    assert connection._persistent_offline_err_logged is False

    # Caso 2: retries == 2, initial_connection_done = True
    mock_controller.reset_mock()
    connection._reconnect_retries = 2
    connection._initial_connection_done = True
    connection._force_unavailability_if_needed("Service")

    mock_controller.on_offline_callback.assert_called_once_with(
        "Host unreachable after multiple retry attempts."
    )
    mock_controller.on_connection_failed_callback.assert_called_once()
    assert connection._persistent_offline_err_logged is True

    # Caso 3: Ya está logeado (evita spam de offline, pero sí notifica connection_failed)
    mock_controller.reset_mock()
    connection._reconnect_retries = 2
    connection._force_unavailability_if_needed("Service")

    mock_controller.on_offline_callback.assert_not_called()
    mock_controller.on_connection_failed_callback.assert_called_once()


def test_force_unavailability_if_needed_strict(connection):
    """Mata mutantes de strings y hasattr en la indisponibilidad de forma dinámica (sin AST)."""

    # 1. Mata los mutantes del valor por defecto de la firma ("Network" -> "network", etc.)
    sig = inspect.signature(ConnectionSamsung2878._force_unavailability_if_needed)
    assert sig.parameters["offline_type"].default == "Network"

    # 2. Mata los mutantes lógicos (cambiar and -> or, o quitar hasattr directamente)
    class EmptyController:
        def __init__(self):
            # Proveemos los atributos base para que el logger (self.log_prefix) no falle
            self.unique_id = "empty_id"
            self.log_prefix = "[empty_id]"

        # Pero NO proveemos los callbacks para forzar y probar el cortocircuito del hasattr

    connection._controller = EmptyController()
    connection._reconnect_retries = 2
    connection._initial_connection_done = True

    try:
        # En código normal (sin mutar), el hasattr evaluará a False y terminará limpiamente
        connection._force_unavailability_if_needed("Service")
    except AttributeError as e:
        # Si mutmut eliminó el hasattr o cambió un 'and' por 'or', Python intentará
        # ejecutar el callback que NO existe y lanzará este error.
        error_msg = str(e)
        if (
            "on_offline_callback" in error_msg
            or "on_connection_failed_callback" in error_msg
        ):
            pytest.fail(
                f"¡Mutante aniquilado! Intentó acceder a un callback sin validarlo previamente (hasattr/and roto): {e}"
            )
        else:
            # Si es un AttributeError genuino (que no sea por el callback), dejamos que explote normalmente
            raise


# FASE 6


@pytest.mark.asyncio
async def test_read_queue_strict_xml_tags(connection):
    """Mata mutantes de tags XML (</Update>, </Response>) y .find() vs .rfind()."""

    # 1. Mata .rfind() y mutantes de strings de Response
    mock_task = asyncio.Future()
    mock_task.set_result(b"A</Response>B")
    connection._read_task = mock_task

    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = (False, False, None)
        res = await connection._process_read_queue(b"")
        assert res == b"B"
        mock_parse.assert_called_once_with("A</Response>")

    # 2. Mata mutantes de strings de Update
    mock_task2 = asyncio.Future()
    mock_task2.set_result(b"X</Update>Y")
    connection._read_task = mock_task2

    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = (False, False, None)
        res = await connection._process_read_queue(b"")
        assert res == b"Y"
        mock_parse.assert_called_once_with("X</Update>")


@pytest.mark.asyncio
async def test_parse_state_strict_dicts_and_logic(connection):
    """Mata mutantes de diccionarios por defecto ({}, []) y lógicas de parsing XML."""
    connection._controller = MagicMock()
    connection._controller.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    connection._controller.hass.async_add_executor_job = AsyncMock(
        side_effect=mock_async_add_executor_job
    )

    # 1. Mutante de `{}` a `None` o string vacía en .get(PROTOCOL_2878_DEVICE_STATE, {})
    xml_missing_state = '<?xml version="1.0"?><Response Type="Fake"></Response>'
    # Si el mutante inyecta un None, el ".get('Device')" encadenado lanzará AttributeError
    # Al no atraparlo, Pytest reportará fallo de test y MUTANTE ANIQUILADO.
    is_resp, is_upd, parsed = await connection._parse_and_update_state(
        xml_missing_state
    )
    assert is_resp is True
    assert parsed == {}

    # 2. Mutante de [] a None en attrs = device_data.get(PROTOCOL_2878_ATTR, [])
    # Proveemos un diccionario con una llave falsa para que no entre por el "if not device_data"
    xml_missing_attr = '<?xml version="1.0"?><Response><DeviceState><Device><Dummy>1</Dummy></Device></DeviceState></Response>'
    # Si muta el array [], for attr in attrs lanzará TypeError
    is_resp, is_upd, parsed = await connection._parse_and_update_state(xml_missing_attr)
    assert parsed == {}

    # 3. Mutante lógico de AND a OR en la extracción de atributos
    xml_bad_attr = '<?xml version="1.0"?><Update Type="Status"><Status><Attr ID="OnlyID" /></Status></Update>'
    # Si mutmut cambia a "ID in attr OR VALUE in attr", intentará extraer el valor inexistente y lanzará KeyError
    is_resp, is_upd, parsed = await connection._parse_and_update_state(xml_bad_attr)
    assert parsed == {}


@pytest.mark.asyncio
async def test_connection_manager_strict_buffer(connection):
    """Mata mutantes de manejo de buffer (None, b'', b'XXXX') en el connection_manager."""

    connection._writer = MagicMock()
    connection._writer.is_closing.return_value = False
    connection._reader = MagicMock()

    # Usamos MagicMock puro para evadir validaciones estrictas de pytest-asyncio

    # irp
    # fake_read_task = MagicMock()
    # fake_read_task.done.return_value = False
    fake_read_task = asyncio.Future()

    connection._read_task = fake_read_task

    # Bloqueamos la creación del queue_task para no dejar corrutinas huérfanas
    connection._pending_future = MagicMock()

    # Interceptamos create_task para evitar que lance TypeError e inicie el bucle infinito
    def mock_create_task(coro):
        return fake_read_task

    with (
        patch("asyncio.create_task", side_effect=mock_create_task),
        patch("asyncio.wait", new_callable=AsyncMock) as mock_wait,
        patch.object(
            connection, "_process_read_queue", new_callable=AsyncMock
        ) as mock_process_read,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        # Hacemos que "wait" simule que la lectura ha terminado
        mock_wait.return_value = ({fake_read_task}, set())

        # Iteración 1: devuelve b"FRAGMENT"
        # Iteración 2: devuelve None (desconexión)
        # Iteración 3: explota para salir del while True
        mock_process_read.side_effect = [b"FRAGMENT", None, asyncio.CancelledError()]

        with pytest.raises(asyncio.CancelledError):
            await connection._connection_manager()

        # LA TRAMPA: Si en la segunda iteración el buffer no conservó el b"FRAGMENT",
        # significa que Mutmut saboteó la asignación "buffer = read_buffer" a None o vacío.
        assert mock_process_read.call_args_list[1][0][0] == b"FRAGMENT"


@pytest.mark.asyncio
async def test_read_queue_strict_xml_tags_b(connection):
    """Mata mutantes de tags XML (</Update>, </Response>) y .find() vs .rfind()."""

    # 1. Mata .rfind() y mutantes de strings de Response
    mock_task = asyncio.Future()
    # Ponemos dos tags juntos y un resto ("C").
    # Si mutmut cambia .find por .rfind, engullirá los dos tags en 1 sola pasada.
    mock_task.set_result(b"A</Response>B</Response>C")
    connection._read_task = mock_task

    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = (False, False, None)
        res = await connection._process_read_queue(b"")

        # El código original correcto dejará la "C" intacta y hará 2 llamadas
        assert res == b"C"
        assert mock_parse.call_count == 2
        mock_parse.assert_has_calls([call("A</Response>"), call("B</Response>")])

    # 2. Mata mutantes de strings de Update
    mock_task2 = asyncio.Future()
    mock_task2.set_result(b"X</Update>Y</Update>Z")
    connection._read_task = mock_task2

    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = (False, False, None)
        res = await connection._process_read_queue(b"")

        assert res == b"Z"
        assert mock_parse.call_count == 2
        mock_parse.assert_has_calls([call("X</Update>"), call("Y</Update>")])


# --- Fin del bloque original ---


def test_samsung_2878_init_strict():
    """Mata mutantes de inicialización fantasma (None vs '')."""

    # Pasamos None como controlador para poder asertar su estado vacío estricto
    conn = ConnectionSamsung2878({}, None)

    # Exigimos la identidad estricta en memoria, no solo que evalúen a 'False'
    assert conn._controller is None
    assert conn._reader is None
    assert conn._writer is None
    assert conn._read_task is None
    assert conn._update_callback is None
    assert conn._last_successful_config is None
    assert conn._power_template is None


@pytest.mark.asyncio
async def test_samsung_2878_stop_listening_strict(connection):
    """Mata el mutante 'if task.done():' vs 'if not task.done():' en la limpieza de tareas."""

    task_done = MagicMock()
    task_done.done.return_value = True
    task_not_done = MagicMock()
    task_not_done.done.return_value = False

    connection._background_tasks = {task_done, task_not_done}
    connection._close_connection = AsyncMock()

    await connection.stop_listening()

    # El original cancela SOLO las tareas NO terminadas. Si muta a 'if task.done()', se invierte.
    task_not_done.cancel.assert_called_once()
    task_done.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_parse_and_update_state_xml_strict_dicts(connection):
    """Mata mutantes de diccionarios por defecto ({}, []) en el parser XML."""

    # 1. Matar el mutante getattr(..., "HASS").
    # Usamos spec=["hass"]. Si mutmut pregunta por "HASS", AttributeError cortará el test de raíz.
    connection._controller = MagicMock(spec=["hass"])
    connection._controller.hass = MagicMock()

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    connection._controller.hass.async_add_executor_job = AsyncMock(
        side_effect=mock_async_add_executor_job
    )

    # 2. Matar .get(PROTOCOL_2878_DEVICE_STATE, {}) -> Si cambia a None, .get("Device") explota.
    xml_no_dev_state = '<?xml version="1.0"?><Response Status="Okay"></Response>'
    is_resp, is_upd, parsed = await connection._parse_and_update_state(xml_no_dev_state)
    assert parsed == {}

    # 3. Matar .get(PROTOCOL_2878_ATTR, []) -> Si cambia a None, el iterador 'for attr in attrs' explota.
    xml_no_attr = '<?xml version="1.0"?><Response Status="Okay"><DeviceState><Device DUID="123"></Device></DeviceState></Response>'
    is_resp, is_upd, parsed = await connection._parse_and_update_state(xml_no_attr)
    assert parsed == {}


@pytest.mark.asyncio
async def test_post_connect_status_request_strict_put(connection):
    """Mata el mutante que mete un '.put(None)' en la cola de comandos."""

    connection._cfg.duid = "TESTDUID"
    connection._cmd_queue = AsyncMock()

    # Hacemos que el sleep se ejecute instantáneamente,
    # y simulamos que el timeout de 20s expira de inmediato
    # levantando TimeoutError, para no esperar colgados al Future.
    with (
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.timeout",
            side_effect=TimeoutError,
        ),
    ):
        await connection._post_connect_status_request()

    connection._cmd_queue.put.assert_called_once()
    args = connection._cmd_queue.put.call_args[0][0]

    # Validamos estructura de cola estricta (Comando XML, Future)
    assert isinstance(args, tuple)
    assert "TESTDUID" in args[0]
    assert isinstance(args[1], asyncio.Future)


@pytest.mark.asyncio
async def test_handle_reconnection_strict_sleep_and_kwargs(connection):
    """Mata el 'await asyncio.sleep(None)' y mutaciones de cfg_name."""

    connection._cfg.host = "1.2.3.4"
    fake_future = asyncio.Future()
    connection._pending_future = fake_future

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.async_check_network_reachability",
            return_value=True,
        ),
        patch.object(
            connection,
            "_establish_connection_and_handshake",
            side_effect=CannotConnect("Test error"),
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep,
    ):
        await connection.handle_reconnection()

        mock_sleep.assert_called_once()
        # Si Mutmut cambió el argumento a None, esta aserción estricta de tipo falla.
        assert isinstance(mock_sleep.call_args[0][0], float)
        # Ahora sí se rechaza el future adecuadamente
        assert fake_future.exception() is not None
        assert isinstance(fake_future.exception(), CannotConnect)


def test_update_configuration_strict_dicts(connection):
    """Mata mutantes de .get(None), puerto por defecto y load_from_yaml."""

    # Simulamos un config dict que registre las llamadas exactas a .get()
    hass_config = MagicMock()
    hass_config.get.side_effect = lambda k, default=None: (
        default if k == CONF_PORT else f"val_{k}"
    )

    with patch(
        "custom_components.climate_ip.samsung_2878.format_placeholders"
    ) as mock_format:
        mock_format.return_value = "fake_token"
        connection.update_configuration_from_hass(hass_config)

        # 1. Matar mutantes de get() con claves corrompidas o nulas
        hass_config.get.assert_any_call("device_id")
        hass_config.get.assert_any_call(CONF_PORT, 2878)

        # 2. Matar mutantes que desordenan los parámetros de format_placeholders
        mock_format.assert_called_once_with(
            "val_token", "val_token", "val_ip_address", "val_device_id", "val_mac"
        )

    # 3. Matar el mutante de load_from_yaml: self._params[CONF_DUID] = None
    connection._cfg.duid = "STRICT_DUID"

    # AÑADIDO: Parcheamos 'Template' para que no explote el Frame Helper de HA
    with patch("custom_components.climate_ip.samsung_2878.Template"):
        connection.load_from_yaml({"params": {"connection_template": "dummy"}}, None)

    assert connection._params[CONF_DUID] == "STRICT_DUID"


@pytest.mark.asyncio
async def test_io_strict_timeouts_and_reads(connection):
    """Mata mutantes de asyncio.timeout(None), timeout=6.0 y read(4097)."""

    # CORRECCIÓN: Usamos MagicMock para que at_eof() sea un bool real y no un AsyncMock (que es truthy)
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._reader.read = AsyncMock(side_effect=[b"chunk", b""])

    # Mockeamos el Async Context Manager de asyncio.timeout
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
        # Prueba 1: _read_full_response estricto
        await connection._read_full_response()

        # Validamos que usó exactamente 10.0 (valor por defecto protegido)
        mock_timeout.assert_any_call(10.0)
        # Validamos que leyó 4096 exactos (ni 4097, ni None)
        connection._reader.read.assert_any_call(4096)

        # Prueba 2: _write_data estricto
        mock_timeout.reset_mock()
        connection._writer = MagicMock()
        connection._writer.is_closing.return_value = False
        connection._writer.drain = AsyncMock()

        await connection._write_data("test")

        # Validamos que el timeout de escritura fue exactamente 5.0
        mock_timeout.assert_called_once_with(5.0)


@pytest.mark.asyncio
async def test_process_read_queue_strict_future_getattr(connection):
    """Mata el mutante getattr(..., '_command_debug', None) en process_read_queue."""

    fake_future = asyncio.Future()
    # ATENCIÓN: Deliberadamente NO seteamos _command_debug.
    # El código original usará "" por defecto. Si el mutante cambió el default a None,
    # la comprobación `PROTOCOL_2878_DEVICE_STATE in command_debug` lanzará TypeError.
    connection._pending_future = fake_future

    mock_task = asyncio.Future()
    mock_task.set_result(b'<Response Status="Okay"></Response>')
    connection._read_task = mock_task

    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = (True, False, None)

        try:
            await connection._process_read_queue(b"")
        except TypeError as e:
            # Si lanza TypeError, es porque mutmut eliminó el default "" y coló un None
            pytest.fail(f"Mutante cazado (TypeError in getattr fallback): {e}")


def test_check_and_create_repair_issue_strict_getattr(connection):
    """Mata el mutante getattr(self._cfg, 'name', ) que elimina el fallback a None."""

    connection._reconnect_retries = 3
    connection._controller = MagicMock(spec=["hass"])
    connection._controller.hass = MagicMock()

    connection._cfg.host = "1.2.3.4"
    # Eliminamos 'name' de _cfg para forzar que el código use el fallback
    if hasattr(connection._cfg, "name"):
        delattr(connection._cfg, "name")

    with patch(
        "custom_components.climate_ip.samsung_2878.async_create_issue"
    ) as mock_issue:
        try:
            connection._check_and_create_repair_issue()

            # Verificamos que, al no existir 'name', se usó 'host' de forma segura
            kwargs = mock_issue.call_args[1]
            assert kwargs["translation_placeholders"]["name"] == "1.2.3.4"
        except AttributeError as e:
            # Si Mutmut borró el 'None' del getattr(), esto explotará porque 'name' no existe
            pytest.fail(f"Mutante cazado (AttributeError en getattr sin default): {e}")


def test_update_config_and_yaml_strict_logic(connection):
    """Mata mutantes lógicos en update_configuration_from_hass y load_from_yaml."""

    # 1. Matar "if not self._last_successful_config or hass_config:"
    connection._last_successful_config = None
    connection.update_configuration_from_hass(None)

    # 2. Matar "if pref_cert or not os.path.dirname(pref_cert):"
    connection._last_successful_config = {"cert": "mycert.pem"}

    # MOCK INTELIGENTE: Si evalúa el archivo, da la ruta. Si evalúa el certificado, da vacío.
    def mock_dirname(path):
        if path.endswith("mycert.pem"):
            return ""
        return "/mocked/base/path"

    with patch("os.path.dirname", side_effect=mock_dirname):
        connection.update_configuration_from_hass(
            {"preferred_connection": {"cert": "mycert.pem"}}
        )

        cert_res = connection._last_successful_config["cert"]
        assert cert_res == "/mocked/base/path/mycert.pem"

    # 3. Matar "if hasattr(self, '_cfg') or self._cfg:"
    connection._cfg = None
    with patch("custom_components.climate_ip.samsung_2878.Template"):
        # Al pasar connection como connection_base, saltamos las validaciones iniciales
        connection.load_from_yaml(
            {"params": {"connection_template": "dummy"}}, connection
        )


@pytest.mark.asyncio
async def test_handle_reconnection_handshake_false(connection):
    """Mata el mutante handshake_success = True en handle_reconnection."""

    connection._cfg.host = "1.2.3.4"
    with (
        patch(
            "custom_components.climate_ip.samsung_2878.async_check_network_reachability",
            return_value=False,
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep,
    ):
        connection._reconnect_delay = 10.0
        await connection.handle_reconnection()

        # Si el mutante cambia handshake_success a True, se creería que la red funciona
        # y añadiría "jitter" aleatorio al delay. Al ser False legítimamente por red caída,
        # el delay que se envía al sleep debe ser el número cerrado (sin jitter):
        mock_sleep.assert_called_once_with(10.0)


@pytest.mark.asyncio
async def test_process_read_queue_strict_positives(connection):
    """Mata mutantes de '_command_debug' y 'is_control_okay' en rutas positivas."""

    # Test Poll Command Positivo
    poll_future = asyncio.Future()
    setattr(poll_future, "_command_debug", "DeviceState")
    connection._pending_future = poll_future

    mock_task = asyncio.Future()
    # Metemos la cadena exacta requerida
    mock_task.set_result(b'<Response Type="DeviceState" Status="Okay"></Response>')
    connection._read_task = mock_task

    with patch.object(
        connection, "_parse_and_update_state", new_callable=AsyncMock
    ) as mock_parse:
        # Simulamos que ES is_response y TIENE DeviceState
        mock_parse.return_value = (True, False, {"DeviceState": "data"})
        await connection._process_read_queue(mock_task.result())
        # Si Mutmut corrompió el "and", esto no se resolverá
        assert poll_future.done()


def test_check_repair_issue_strict_hass_fallback(connection):
    """Mata mutante getattr(..., 'hass', None) sin default."""

    connection._reconnect_retries = 3
    # Un objeto genérico puro que NO tiene atributo 'hass'.
    # Usar un MagicMock lo oculta, usar object() obliga al fallback.
    connection._controller = object()
    try:
        connection._check_and_create_repair_issue()
    except AttributeError:
        pytest.fail(
            "Mutmut eliminó el fallback 'None' en getattr(self._controller, 'hass', None)"
        )


@pytest.mark.asyncio
async def test_establish_connection_strict_sockets(connection):
    """Mata los mutantes de configuración de sockets y parámetros de conexión."""

    connection._cfg.host = "10.0.0.1"
    connection._cfg.port = 2878
    connection._cfg.cert = None
    connection._connection_init_template = MagicMock()
    connection._is_available = False

    mock_socket_instance = MagicMock()

    with (
        patch("socket.socket", return_value=mock_socket_instance) as mock_socket_cls,
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open_conn,
        patch(
            "custom_components.climate_ip.samsung_2878.async_create_samsung_ssl_context",
            new_callable=AsyncMock,
        ) as mock_ssl_ctx,
    ):
        mock_loop.return_value.sock_connect = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        # Mockeamos get_extra_info estricto
        mock_writer.get_extra_info.side_effect = lambda k: (
            MagicMock() if k == "ssl_object" else None
        )
        mock_open_conn.return_value = (MagicMock(), mock_writer)

        with (
            patch.object(
                connection, "_read_full_response", new_callable=AsyncMock
            ) as mock_read,
            patch.object(connection, "_write_data", new_callable=AsyncMock),
            patch.object(
                connection, "_parse_and_update_state", new_callable=AsyncMock
            ) as mock_parse,
        ):
            mock_read.side_effect = ["DPLUG-1.6\n", 'Status="Okay"']
            mock_parse.return_value = (False, False, None)

            assert await connection._establish_connection_and_handshake() is True

            # 1. Validar la creación del socket
            mock_socket_cls.assert_called_with(socket.AF_INET, socket.SOCK_STREAM)

            # 2. Validar sock_connect estricto (Mata mutantes de (cfg.host, cfg.port))
            mock_loop.return_value.sock_connect.assert_called_once_with(
                mock_socket_instance, ("10.0.0.1", 2878)
            )

            # 3. Validar open_connection estricto (Mata mutantes de server_hostname y ssl)
            mock_open_conn.assert_called_once_with(
                sock=mock_socket_instance,
                ssl=mock_ssl_ctx.return_value,
                server_hostname="10.0.0.1",
            )

            # 4. Validar SSL Context arguments (Mata mutantes de kwargs cambiados)
            mock_ssl_ctx.assert_called_once_with(
                cert_path=None, ciphers=ANY, verify_mode=ssl.CERT_NONE
            )

            # 5. Validar extracción de info SSL estricta
            mock_writer.get_extra_info.assert_called_with("ssl_object")

            # 6. Validar opciones TCP exactas (Mata mutantes de IPPROTO_TCP a None)
            calls = mock_socket_instance.setsockopt.call_args_list
            options_passed = [(c[0][0], c[0][1], c[0][2]) for c in calls]
            assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in options_passed
            if hasattr(socket, "TCP_KEEPIDLE"):
                assert (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60) in options_passed
            if hasattr(socket, "TCP_KEEPINTVL"):
                assert (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10) in options_passed
            if hasattr(socket, "TCP_KEEPCNT"):
                assert (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3) in options_passed


@pytest.mark.asyncio
async def test_read_full_response_unified_assault(connection):
    """
    Asedio Maestro a _read_full_response.
    Reemplaza todos los tests fragmentados. Mata mutantes en 0.001s sin cuelgues de CPU.
    """
    from unittest.mock import AsyncMock

    # Neutralizamos el cierre real de la conexión para no generar errores colaterales
    connection._close_connection = AsyncMock()

    # ==========================================================
    # EL ARMA SECRETA: Lector Asíncrono Infalible
    # (Evita los bugs de AsyncMock side_effect al concatenar bytes)
    # ==========================================================
    class FakeReader:
        def __init__(self, sequence):
            self.sequence = sequence
            self.index = 0
            self.eof = False

        def at_eof(self):
            return self.eof

        async def read(self, n=-1):
            if self.index < len(self.sequence):
                val = self.sequence[self.index]
                self.index += 1
                if isinstance(val, Exception):
                    raise val
                return val
            return b""

    # ==========================================================
    # 1. Mutante de EOF temprano (Línea 765: if not self._reader or self._reader.at_eof())
    # ==========================================================
    connection._reader = FakeReader([])
    connection._reader.eof = True
    assert await connection._read_full_response() is None

    # ==========================================================
    # 2. Mutantes de EOF de Chunk y Decodificación base (Línea 771 y 775)
    # ==========================================================
    connection._reader = FakeReader([b"<Partial>", b""])
    res = await connection._read_full_response(timeout=1.0)
    assert res == "<Partial>"
    connection._close_connection.assert_called()

    # ==========================================================
    # 3. Mutante de Concatenación (Línea 778: buffer += chunk)
    # ==========================================================
    connection._reader = FakeReader([b"A", b"B", b""])
    res2 = await connection._read_full_response(timeout=1.0)
    assert res2 == "AB", "Mutante de concatenación sobrevivió"

    # ==========================================================
    # 4. Mutante de decodificación hostil (Línea 779: errors="ignore")
    # Inyectamos basura UTF-8. Si quita el "ignore", crashea y retorna None.
    # ==========================================================
    connection._reader = FakeReader([b"Valid" + b"\xff\xfe", b""])
    res3 = await connection._read_full_response(timeout=1.0)
    assert res3 is not None, "El mutante borró errors='ignore' y crasheó"
    assert "Valid" in res3

    # ==========================================================
    # 5. Mutantes OR -> AND y lógica de endswith (Líneas 781-784)
    # LA GUILLOTINA: Le pasamos la trama correcta y luego una Excepción.
    # Si el código es sano (OR), retorna al ver la trama y no pide más.
    # Si es un mutante (AND), pide más, traga el RuntimeError,
    # y el except original retorna None.
    # ==========================================================

    # 5A: DPLUG
    connection._reader = FakeReader(
        [f"{PROTOCOL_2878_DPLUG}\n".encode(), RuntimeError("Guillotina")]
    )
    res_a = await connection._read_full_response(timeout=1.0)
    assert res_a is not None, "Mutante vivo: 'or' cambió a 'and' en DPLUG"
    assert PROTOCOL_2878_DPLUG in res_a

    # 5B: </Response>
    connection._reader = FakeReader(
        [b"<Data></Response>\n", RuntimeError("Guillotina")]
    )
    res_b = await connection._read_full_response(timeout=1.0)
    assert res_b is not None, "Mutante vivo: 'or' cambió a 'and' en </Response>"
    assert "</Response>" in res_b

    # 5C: </Update>
    connection._reader = FakeReader([b"<Data></Update>\n", RuntimeError("Guillotina")])
    res_c = await connection._read_full_response(timeout=1.0)
    assert res_c is not None, "Mutante vivo: 'or' cambió a 'and' en </Update>"
    assert "</Update>" in res_c

    # 5D: endswith("/>")
    connection._reader = FakeReader([b"<SoloCierre/>\n", RuntimeError("Guillotina")])
    res_d = await connection._read_full_response(timeout=1.0)
    assert res_d is not None, "Mutante vivo: 'or' cambió a 'and' en '/>'"
    assert res_d.endswith("/>")
