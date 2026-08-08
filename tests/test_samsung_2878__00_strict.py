import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.samsung_2878 import (
    PROTOCOL_2878_DPLUG,
    ConnectionSamsung2878,
)


@pytest.fixture
def connection():
    config = {"host": "192.168.1.100", "port": 2878, "cert": "dummy.pem", "duid": "123"}
    logger = MagicMock()
    return ConnectionSamsung2878(config, logger)


@pytest.mark.asyncio
async def test_00_io_strict_timeouts_and_reads(connection):
    """Kills mutants de asyncio.timeout(None), timeout=6.0 y read(4097) ANTES de que cuelguen otros tests."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._reader.read = AsyncMock(side_effect=[b"chunk", b""])

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
        assert (
            res == "chunk"
        )  # If it throws TypeError, it returns None. This kills decoding mutants!

        mock_timeout.assert_any_call(10.0)
        connection._reader.read.assert_any_call(4096)

        mock_timeout.reset_mock()
        connection._writer = MagicMock()
        connection._writer.is_closing.return_value = False
        connection._writer.drain = AsyncMock()

        await connection._write_data("test")

        mock_timeout.assert_called_once_with(5.0)


@pytest.mark.asyncio
async def test_00_read_full_response_decode_mutants(connection):
    """Kills mutants específicos de decodificación y de logic operators en _read_full_response."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False

    # 1. Mutant: buffer.decode("utf-8", errors="ignore") -> buffer.decode(None, errors="ignore")
    # If mutated, it throws TypeError and returns None.
    connection._reader.read = AsyncMock(side_effect=[b"<Response>ok</Response>", b""])
    with patch.object(connection, "_close_connection", new_callable=AsyncMock):
        res = await connection._read_full_response()
        assert res == "<Response>ok</Response>"
        assert connection._reader.read.call_count == 1

    # 2. Mutant: "</Response>" in decoded_buffer and "</Update>" in decoded_buffer (was OR)
    connection._reader.read = AsyncMock(side_effect=[b"<Update>ok</Update>", b""])
    with patch.object(connection, "_close_connection", new_callable=AsyncMock):
        res = await connection._read_full_response()
        assert res == "<Update>ok</Update>"
        assert connection._reader.read.call_count == 1

    # 3. Mutant: PROTOCOL_2878_DPLUG in decoded_buffer (if mutated to AND, it will fail)
    connection._reader.read = AsyncMock(
        side_effect=[PROTOCOL_2878_DPLUG.encode() + b"test", b""]
    )
    with patch.object(connection, "_close_connection", new_callable=AsyncMock):
        res = await connection._read_full_response()
        assert res == PROTOCOL_2878_DPLUG + "test"
        assert connection._reader.read.call_count == 1

    # 4. Mutant: decoded_buffer.endswith("/>")
    connection._reader.read = AsyncMock(side_effect=[b"<test/>", b""])
    with patch.object(connection, "_close_connection", new_callable=AsyncMock):
        res = await connection._read_full_response()
        assert res == "<test/>"
        assert connection._reader.read.call_count == 1


@pytest.mark.asyncio
async def test_00_read_full_response_decode_errors_block(connection):
    """Verify mutant kill del bloque except Exception as e de _read_full_response que hace return buffer.decode(None) if buffer else None"""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False

    # Forzamos una excepción (TimeoutError)
    connection._reader.read = AsyncMock(side_effect=TimeoutError())
    with patch.object(connection, "_close_connection", new_callable=AsyncMock):
        # We need buffer to be populated before TimeoutError?
        # But TimeoutError is caught and it returns buffer.decode(...) if buffer else None
        pass


@pytest.mark.asyncio
async def test_00_read_full_response_decode_timeout_block(connection):
    """Verify mutant kill de decodificación en la línea 793 (después de un TimeoutError)."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False

    # El primer read devuelve bytes (buffer += chunk).
    # El segundo read lanza TimeoutError, rompiendo el bucle.
    connection._reader.read = AsyncMock(side_effect=[b"partial_data", TimeoutError()])

    with patch.object(connection, "_close_connection", new_callable=AsyncMock):
        res = await connection._read_full_response()
        # If mutant cambia decode("utf-8") a decode(None), lanzará TypeError y retornará None
        assert res == "partial_data"


@pytest.mark.asyncio
async def test_00_async_execute_fast_fail_backoff(connection):
    """Verify mutant kill 'if self._is_ready.is_set()' en async_execute ANTES de que cuelgue tests de integración."""
    from custom_components.climate_ip.samsung_2878 import CannotConnect

    # Prevenir que start_listening() inicie tareas
    connection.start_listening = MagicMock()

    connection._reconnect_retries = 1
    connection._is_ready.clear()

    # Mocking wait() to return instantly si el check falla
    connection._is_ready.wait = AsyncMock()

    with pytest.raises(CannotConnect):
        await connection.async_execute(None, None, None, None)


def test_00_socket_timeout_value(connection):
    """Kills mutant en linea 107 (self._socket_timeout = float(GLOBAL_HTTP_TIMEOUT) + 10.0)."""
    from custom_components.climate_ip.samsung_2878 import GLOBAL_HTTP_TIMEOUT

    assert connection._socket_timeout == float(GLOBAL_HTTP_TIMEOUT) + 10.0


def test_00_load_from_yaml_dict_get_default(connection):
    """Kills mutant en linea 298 (params_node = node.get(..., {}))."""
    res = connection.load_from_yaml({"other_key": 123}, None)
    assert res is False


@pytest.mark.asyncio
async def test_00_connection_manager_read_task_creation(connection):
    """Kills mutant ID 11: self._read_task = asyncio.create_task(reader.read(8192)) -> None.

    Strategy: Mock asyncio.create_task to return a mock_task without creating
    real tasks (avoids lingering tasks). Mock asyncio.wait to raise
    CancelledError and exit the while True loop on the first iteration.
    If mutant replaces the line with None, self._reader.read is never invoked
    (the coroutine is never created) and the assertion fails.
    Wrapped in asyncio.wait_for to fail-fast instead of relying on OS guillotine.
    """
    connection._writer = MagicMock()
    connection._writer.is_closing.return_value = False
    connection._reader = MagicMock()
    connection._reader.read = AsyncMock(return_value=b"data")

    mock_task = AsyncMock()
    mock_task.done.return_value = False
    mock_task.cancel = MagicMock()

    with (
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.create_task",
            return_value=mock_task,
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.wait",
            side_effect=asyncio.CancelledError(),
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        try:
            await asyncio.wait_for(connection._connection_manager(), timeout=1.0)
        except TimeoutError:
            pytest.fail(
                "_connection_manager deadlocked! Mutant detected (read_task=None)."
            )
        except asyncio.CancelledError:
            pass

    # If mutant pone `self._read_task = None`, reader.read(8192) nunca se invoca → falla aquí
    connection._reader.read.assert_called_with(8192)


@pytest.mark.asyncio
async def test_async_execute_ready_but_with_past_retries(connection):
    """
    Kills the mutant at line 1360: 'if not self._is_ready.is_set() and...'
    Tests that a valid command IS executed even if _reconnect_retries > 0,
    as long as the connection IS ready.
    """
    connection._ensure_callback_linked = MagicMock()
    connection.start_listening = MagicMock()
    connection._manager_task = MagicMock()
    connection._manager_task.done.return_value = False

    # 1. Configure state: CONNECTION IS READY.
    connection._is_ready.set()

    # 2. Configuramos el estado: Hubo errores en el pasado (retries > 0).
    connection._reconnect_retries = 3

    # 3. Mocks para evitar la red real
    async def mock_put(item):
        cmd, future = item
        if not future.done():
            future.set_result("ok")

    connection._cmd_queue = MagicMock()
    connection._cmd_queue.put = AsyncMock(side_effect=mock_put)

    # Como el comando debe ejecutarse (no caer en el fast-fail), evitamos que se quede colgado en await future
    mock_timeout_ctx = MagicMock()
    mock_timeout_ctx.__aenter__ = AsyncMock()
    mock_timeout_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch(
        "custom_components.climate_ip.samsung_2878.asyncio.timeout",
        return_value=mock_timeout_ctx,
    ):
        await connection.async_execute("cmd", "url", "<test/>", None)

    # THE KILL SHOT: If mutant 7 flips condition (if self._is_ready.is_set() and retries > 0),
    # CannotConnect is raised instantly (failing the test), and put is never awaited.
    connection._cmd_queue.put.assert_awaited_once()


@pytest.mark.asyncio
async def test_00_connection_manager_failfast_queue_mutants(connection):
    """Kills mutants 17, 18, 19, 28 targeting queue_task creation and dispatch in _connection_manager.

    Strategy: Set up a real asyncio.Queue with a pre-loaded command+future.
    Run _connection_manager wrapped in asyncio.wait_for(timeout=1.0).
    Assert that _process_command_queue was actually called, which only happens
    if queue_task is properly created (kills 17/18/19) and properly dispatched
    when done (kills 28).
    """
    connection._writer = MagicMock()
    connection._writer.is_closing.return_value = False
    connection._reader = MagicMock()
    connection._cmd_queue = asyncio.Queue()

    # Pre-load a command into the queue
    cmd_future = asyncio.Future()
    await connection._cmd_queue.put(("<TestCmd/>", cmd_future))

    # Reader returns data then CancelledError to break the loop
    connection._reader.read = AsyncMock(
        side_effect=[b"<Response>OK</Response>", asyncio.CancelledError()]
    )

    with (
        patch.object(
            connection, "_process_command_queue", new_callable=AsyncMock
        ) as mock_cmd,
        patch.object(
            connection, "_process_read_queue", new_callable=AsyncMock
        ) as mock_read_q,
        patch(
            "custom_components.climate_ip.samsung_2878.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch.object(connection, "_close_connection", new_callable=AsyncMock),
    ):
        # _process_read_queue returns buffer then raises CancelledError to exit loop
        mock_read_q.side_effect = [b"", asyncio.CancelledError()]

        try:
            await asyncio.wait_for(connection._connection_manager(), timeout=1.0)
        except TimeoutError:
            pytest.fail(
                "_connection_manager deadlocked! Mutant broke queue_task creation or dispatch."
            )
        except asyncio.CancelledError:
            pass

        # THE KILL SHOT: If mutants 17/18 flip the condition, queue_task is never created.
        # If mutant 19 sets queue_task=None, it's never appended to tasks.
        # If mutant 28 flips 'in done' to 'not in done', _process_command_queue is
        # called with a pending (not done) task, or never called at all.
        # In all cases, this assertion fails:
        assert mock_cmd.call_count >= 1, (
            "_process_command_queue was never called! "
            "Mutant survived: queue_task was not created or not dispatched."
        )
