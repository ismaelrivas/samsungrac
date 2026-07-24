import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_MAC
from custom_components.climate_ip.const import CONF_CERT

from custom_components.climate_ip.exceptions import CannotConnect
from custom_components.climate_ip.samsung_2878 import (
    ConnectionConfig,
    ConnectionSamsung2878,
)


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


# --- 1. TESTS PARA LA CONFIGURACIÓN BASE (Kills mutants "None Fallback" en __init__) ---


def test_connection_config_strict_init():
    """Verify mutant kill que reemplazan las asignaciones del constructor por None."""
    cfg = ConnectionConfig(
        host="192.168.1.100",
        port=2878,
        token="test_token",
        cert="test_cert.pem",
        duid="test_duid",
    )

    # Exigimos integridad estricta en la memoria asignada
    assert cfg.host == "192.168.1.100"
    assert cfg.port == 2878
    assert cfg.token == "test_token"
    assert cfg.cert == "test_cert.pem"
    assert cfg.duid == "test_duid"


# --- 2. TESTS DE TIMEOUTS ESTRICTOS EN I/O ---


@pytest.mark.asyncio
async def test_read_full_response_success_and_timeout_args(connection):
    """Kills mutants de timeout y da cobertura a la lectura exitosa usando comportamiento real."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._close_connection = AsyncMock()  # Prevents crash on exception handling

    # 1. Test de timeout explícito SIN MOCK de asyncio.timeout
    # Si muta a async with asyncio.timeout(None), esto se colgará 0.5s en lugar de fallar rápido.
    async def slow_read(*args, **kwargs):
        await asyncio.sleep(0.5)
        return b""

    connection._reader.read = AsyncMock(side_effect=slow_read)

    # Usamos timeout=0.01. El código original lanzará TimeoutError internamente y devolverá None.
    # Si muta a timeout(None), tardará 0.5s.
    import time

    start = time.time()
    res = await connection._read_full_response(timeout=0.01)
    duration = time.time() - start

    assert res is None
    # Si mutó a timeout(None), el duration será ~0.5. Si es original, será ~0.01.
    assert duration < 0.2, "El mutante async with asyncio.timeout(None) sobrevivió"

    # 2. Prueba de lectura exitosa
    connection._reader.read = AsyncMock(side_effect=[b"<Response>OK</Response>", b""])
    res2 = await connection._read_full_response(timeout=10.0)
    assert res2 == "<Response>OK</Response>"

    # 3. Prueba para matar 'if not chunk:' -> 'if chunk:'
    # Si muta a 'if chunk:', al leer b"<Response>OK</Response>" entrará al if,
    # llamará a _close_connection y retornará ANTES de agregar nada al buffer.
    connection._reader.read = AsyncMock(side_effect=[b"<Response>OK</Response>", b""])
    connection._close_connection = AsyncMock()
    res3 = await connection._read_full_response(timeout=10.0)
    assert (
        res3 == "<Response>OK</Response>"
    )  # Si mutó, esto fallará porque devolvería None o string vacío


@pytest.mark.asyncio
async def test_read_full_response_timeout_exception(connection):
    """Cubre el bloque except TimeoutError de _read_full_response."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._close_connection = AsyncMock()
    # Simulamos que leemos algo (buffer) y luego lanzamos IncompleteReadError
    connection._reader.read = AsyncMock(
        side_effect=[b"Part1", asyncio.IncompleteReadError(b"Part1", None)]
    )

    res = await connection._read_full_response()
    # Entra al except y decodifica el buffer ("Part1")
    assert res == "Part1"


@pytest.mark.asyncio
async def test_read_full_response_logic_and_concat(connection):
    """Mata los Logic Condition Flips y mutaciones en buffer.decode / concat."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._close_connection = AsyncMock()

    # Para matar `not in`, necesitamos que el código retorne TEMPRANO si la condición es verdadera,
    # y no lea el siguiente chunk. Si muta a `not in`, leerá el siguiente chunk y fallará la aserción.

    # 1. Test para </Response>
    connection._reader.read = AsyncMock(
        side_effect=[b"Part1</Response>", b"ExtraChunk", b""]
    )
    res = await connection._read_full_response()
    assert res == "Part1</Response>"  # Si lee ExtraChunk, fallará

    # 2. Test para </Update>
    connection._reader.read = AsyncMock(
        side_effect=[b"Part1</Update>", b"ExtraChunk", b""]
    )
    res = await connection._read_full_response()
    assert res == "Part1</Update>"


@pytest.mark.asyncio
async def test_read_full_response_logic_dplug_only(connection):
    """Verify mutant kill: `or PROTOCOL_2878_DPLUG in ... and ...endswith("/>")` y el flip `not in`."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._close_connection = AsyncMock()

    # Proveemos un buffer que SÍ tiene DPLUG pero NO termina en "/>"
    from custom_components.climate_ip.samsung_2878 import PROTOCOL_2878_DPLUG

    dplug_bytes = PROTOCOL_2878_DPLUG.encode("utf-8")

    # Si muta a `not in`, leerá ExtraChunk
    connection._reader.read = AsyncMock(
        side_effect=[dplug_bytes + b" NO_END", b"ExtraChunk", b""]
    )
    res = await connection._read_full_response()

    # El código original usa 'or' y 'in', así que debe retornar temprano sin ExtraChunk
    assert PROTOCOL_2878_DPLUG in res
    assert "ExtraChunk" not in res

    # Mutante: Logic Condition Flips y DPLUG
    # Probamos Update
    connection._reader.read.side_effect = [b"<Update>data</Update>", b""]
    assert await connection._read_full_response() == "<Update>data</Update>"

    # Probamos DPLUG
    from custom_components.climate_ip.samsung_2878 import PROTOCOL_2878_DPLUG

    connection._reader.read.side_effect = [PROTOCOL_2878_DPLUG.encode(), b""]
    assert PROTOCOL_2878_DPLUG in await connection._read_full_response()

    # Probamos endswith("/>")
    connection._reader.read.side_effect = [b"<tag/>", b""]
    assert await connection._read_full_response() == "<tag/>"


@pytest.mark.asyncio
# --- 3. TESTS DE LÓGICA DE RECONEXIÓN Y FAST-FAIL ---

@pytest.mark.asyncio
async def test_async_execute_fast_fail_backoff(connection):
    """Mata el Logic Condition Flip: 'if not self._is_ready.is_set()' vs 'if self._is_ready.is_set()'."""
    # Dummy task so async_execute doesn't call start() and leave a lingering task
    connection._manager_task = asyncio.create_task(asyncio.sleep(999))

    # Estado crítico: no estamos listos y ya hemos intentado reconectar (backoff activo)
    connection._is_ready = MagicMock()
    connection._is_ready.is_set.return_value = False
    connection._reconnect_retries = 1

    # Hacemos que _is_ready.wait() no bloquee si llega a ejecutarse.
    # Si muta a 'if self._is_ready.is_set()', la condición será falsa (porque is_set es False)
    # y el código saltará el fast-fail, intentando hacer await self._is_ready.wait().
    connection._is_ready.wait = AsyncMock()
    connection._cmd_queue = MagicMock()
    connection._cmd_queue.put = AsyncMock()

    try:
        with patch("custom_components.climate_ip.samsung_2878.COMMAND_TIMEOUT", 0.01):
            with pytest.raises(CannotConnect, match="Client not ready"):
                await connection.async_execute(
                    method="GET", url="test_url", data="<data>", headers={}
                )
    finally:
        connection._manager_task.cancel()


# --- 4. TESTS PARA _CONNECTION_MANAGER ---


@pytest.mark.asyncio
async def test_connection_manager_critical_survivors(connection):
    """Verify mutant kill en _connection_manager relacionados con read_task y read_buffer."""
    connection._reader = MagicMock()
    connection._reader.read = AsyncMock(return_value=b"<Response>OK</Response>")

    mock_process = AsyncMock(return_value=b"")
    connection._process_read_queue = mock_process

    # Redefinimos el loop para que corra 1 sola vez y luego rompa
    # sin necesidad de lanzar excepciones raras que causan estragos en el cleanup
    original_process = connection._process_read_queue

    async def fake_process(*args, **kwargs):
        # A la primera que procese un chunk, lanzamos CancelledError para salir del loop infinito
        # ya que _connection_manager corre en un while True que normalmente se cancela por tarea.
        await original_process(*args, **kwargs)
        raise asyncio.CancelledError()

    connection._process_read_queue = AsyncMock(side_effect=fake_process)

    # Para que el while corra rápido y sin bloqueos infinitos
    with patch("custom_components.climate_ip.samsung_2878.asyncio.sleep", AsyncMock()):
        # Prevent reconnection si falla el writer
        with patch.object(
            connection, "handle_reconnection", new_callable=AsyncMock
        ) as mock_recon:

            class KillMutant(BaseException):
                pass

            # If mutant triggers continue branch, volverá a llamar a handle_reconnection.
            # Raise BaseException para saltarnos el "except Exception:" del manager y fallar el test.
            mock_recon.side_effect = [
                True,
                KillMutant("El mutante 'continue' ha sobrevivido!"),
            ]
            try:
                await asyncio.wait_for(connection._connection_manager(), timeout=1.0)
            except TimeoutError:
                pytest.fail(
                    "_connection_manager deadlocked! Mutant broke read/queue task lifecycle."
                )
            except asyncio.CancelledError:
                pass  # The manager cancelled itself as expected

    assert connection._process_read_queue.call_count >= 1


# --- 4. TESTS DE MANEJO DE RUTAS ABSOLUTAS ---


def test_update_configuration_cert_file_strict_path(connection):
    """Kills mutants de rutas nulas (None Fallback) en la carga del certificado."""
    hass_config = {CONF_MAC: "00:11:22:33:44:55", CONF_CERT: "local_cert.pem"}

    connection.update_configuration_from_hass(hass_config)

    import custom_components.climate_ip.samsung_2878 as s2878

    expected_cert_path = os.path.join(os.path.dirname(s2878.__file__), "local_cert.pem")
    assert connection._cfg.cert == expected_cert_path


@pytest.mark.asyncio
async def test_read_full_response_reader_none(connection):
    """Verify mutant kill `if not self._reader and self._reader.at_eof():`"""
    connection._reader = None
    res = await connection._read_full_response()
    assert res is None
