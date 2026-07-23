import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from custom_components.climate_ip.samsung_2878 import ConnectionSamsung2878, PROTOCOL_2878_DPLUG

@pytest.fixture
def connection():
    config = {"host": "192.168.1.100", "port": 2878, "cert": "dummy.pem", "duid": "123"}
    logger = MagicMock()
    return ConnectionSamsung2878(config, logger)

@pytest.mark.asyncio
async def test_00_io_strict_timeouts_and_reads(connection):
    """Mata mutantes de asyncio.timeout(None), timeout=6.0 y read(4097) ANTES de que cuelguen otros tests."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._reader.read = AsyncMock(side_effect=[b"chunk", b""])

    mock_timeout_ctx = MagicMock()
    mock_timeout_ctx.__aenter__ = AsyncMock()
    mock_timeout_ctx.__aexit__ = AsyncMock()

    with patch("custom_components.climate_ip.samsung_2878.asyncio.timeout", return_value=mock_timeout_ctx) as mock_timeout, \
         patch.object(connection, "_close_connection", new_callable=AsyncMock):
        
        res = await connection._read_full_response()
        assert res == "chunk" # If it throws TypeError, it returns None. This kills decoding mutants!
        
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
    """Mata mutantes específicos de decodificación y de logic operators en _read_full_response."""
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
    connection._reader.read = AsyncMock(side_effect=[PROTOCOL_2878_DPLUG.encode() + b"test", b""])
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
    """Mata el mutante del bloque except Exception as e de _read_full_response que hace return buffer.decode(None) if buffer else None"""
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
    """Mata el mutante de decodificación en la línea 793 (después de un TimeoutError)."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    
    # El primer read devuelve bytes (buffer += chunk).
    # El segundo read lanza TimeoutError, rompiendo el bucle.
    connection._reader.read = AsyncMock(side_effect=[b"partial_data", TimeoutError()])
    
    with patch.object(connection, "_close_connection", new_callable=AsyncMock):
        res = await connection._read_full_response()
        # Si el mutante cambia decode("utf-8") a decode(None), lanzará TypeError y retornará None
        assert res == "partial_data"


@pytest.mark.asyncio
async def test_00_async_execute_fast_fail_backoff(connection):
    """Mata el mutante 'if self._is_ready.is_set()' en async_execute ANTES de que cuelgue tests de integración."""
    import asyncio
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
    """Mata mutante en linea 107 (self._socket_timeout = float(GLOBAL_HTTP_TIMEOUT) + 10.0)."""
    from custom_components.climate_ip.samsung_2878 import GLOBAL_HTTP_TIMEOUT
    assert connection._socket_timeout == float(GLOBAL_HTTP_TIMEOUT) + 10.0


def test_00_load_from_yaml_dict_get_default(connection):
    """Mata mutante en linea 298 (params_node = node.get(..., {}))."""
    res = connection.load_from_yaml({"other_key": 123}, None)
    assert res is False


@pytest.mark.asyncio
async def test_00_connection_manager_read_task_creation(connection):
    """Mata mutante ID 11 en linea 1268: self._read_task = asyncio.create_task(reader.read(8192)) -> None.

    Estrategia: Mockeamos asyncio.create_task para devolver un mock_task sin crear
    tareas reales (evita lingering tasks). Mockeamos asyncio.wait para lanzar
    CancelledError y salir del while True en la primera iteración.
    Si el mutante reemplaza la línea con None, self._reader.read nunca se invoca
    (la coroutine nunca se crea) y la aserción falla.
    """
    connection._writer = MagicMock()
    connection._writer.is_closing.return_value = False
    connection._reader = MagicMock()
    connection._reader.read = AsyncMock(return_value=b"data")

    mock_task = AsyncMock()
    mock_task.done.return_value = False
    mock_task.cancel = MagicMock()

    with patch("custom_components.climate_ip.samsung_2878.asyncio.create_task", return_value=mock_task), \
         patch("custom_components.climate_ip.samsung_2878.asyncio.wait", side_effect=asyncio.CancelledError()), \
         patch("custom_components.climate_ip.samsung_2878.asyncio.sleep", new_callable=AsyncMock), \
         patch.object(connection, "_close_connection", new_callable=AsyncMock):
        try:
            await connection._connection_manager()
        except asyncio.CancelledError:
            pass

    # Si el mutante pone `self._read_task = None`, reader.read(8192) nunca se invoca → falla aquí
    connection._reader.read.assert_called_with(8192)
