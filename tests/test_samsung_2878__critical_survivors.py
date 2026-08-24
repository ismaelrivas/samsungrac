from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_MAC
import pytest

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


# --- 1. BASE CONFIGURATION TESTS (Kills "None Fallback" mutants in __init__) ---


def test_connection_config_strict_init():
    """Verify mutant kill que reemplazan las asignaciones del constructor por None."""
    cfg = ConnectionConfig(
        host="192.168.1.100",
        port=2878,
        token="test_token",
        cert="test_cert.pem",
        duid="test_duid",
    )

    # We require strict integrity in allocated memory
    assert cfg.host == "192.168.1.100"
    assert cfg.port == 2878
    assert cfg.token == "test_token"
    assert cfg.cert == "test_cert.pem"
    assert cfg.duid == "test_duid"


# --- 2. STRICT I/O TIMEOUT TESTS ---


@pytest.mark.asyncio
async def test_read_full_response_success_and_timeout_args(connection):
    """Kills timeout mutants and gives coverage to successful read using real behavior."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._close_connection = AsyncMock()  # Prevents crash on exception handling

    # 1. Explicit timeout test WITHOUT MOCKing asyncio.timeout
    # If mutated to async with asyncio.timeout(None), this will hang 0.5s instead of failing fast.
    async def slow_read(*args, **kwargs):
        await asyncio.sleep(0.5)
        return b""

    connection._reader.read = AsyncMock(side_effect=slow_read)

    # We use timeout=0.01. Original code will raise TimeoutError internally and return None.
    # If mutated to timeout(None), it will take 0.5s.
    import time

    start = time.time()
    res = await connection._read_full_response(timeout=0.01)
    duration = time.time() - start

    assert res is None
    # If mutated to timeout(None), duration will be ~0.5. If original, ~0.01.
    assert duration < 0.2, "The mutant async with asyncio.timeout(None) survived"

    # 2. Successful read test
    connection._reader.read = AsyncMock(side_effect=[b"<Response>OK</Response>", b""])
    res2 = await connection._read_full_response(timeout=10.0)
    assert res2 == "<Response>OK</Response>"

    # 3. Test to kill 'if not chunk:' -> 'if chunk:'
    # If mutated to 'if chunk:', reading b"<Response>OK</Response>" will enter the if,
    # call _close_connection and return BEFORE adding anything to the buffer.
    connection._reader.read = AsyncMock(side_effect=[b"<Response>OK</Response>", b""])
    connection._close_connection = AsyncMock()
    res3 = await connection._read_full_response(timeout=10.0)
    assert (
        res3 == "<Response>OK</Response>"
    )  # If mutated, this fails because it would return None or empty string


@pytest.mark.asyncio
async def test_read_full_response_timeout_exception(connection):
    """Covers except TimeoutError block in _read_full_response."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._close_connection = AsyncMock()
    # Simulate reading something (buffer) and then raising IncompleteReadError
    connection._reader.read = AsyncMock(
        side_effect=[b"Part1", asyncio.IncompleteReadError(b"Part1", None)]
    )

    res = await connection._read_full_response()
    # Enters except and decodes buffer ("Part1")
    assert res == "Part1"


@pytest.mark.asyncio
async def test_read_full_response_logic_and_concat(connection):
    """Kills Logic Condition Flips and mutations in buffer.decode / concat."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._close_connection = AsyncMock()

    # To kill `not in`, we need the code to return EARLY if condition is True,
    # and not read the next chunk. If mutated to `not in`, it will read next chunk and fail assertion.

    # 1. Test for </Response>
    connection._reader.read = AsyncMock(
        side_effect=[b"Part1</Response>", b"ExtraChunk", b""]
    )
    res = await connection._read_full_response()
    assert res == "Part1</Response>"  # If it reads ExtraChunk, it will fail

    # 2. Test for </Update>
    connection._reader.read = AsyncMock(
        side_effect=[b"Part1</Update>", b"ExtraChunk", b""]
    )
    res = await connection._read_full_response()
    assert res == "Part1</Update>"


@pytest.mark.asyncio
async def test_read_full_response_logic_dplug_only(connection):
    """Verify mutant kill: `or PROTOCOL_2878_DPLUG in ... and ...endswith("/>")` and flip `not in`."""
    connection._reader = MagicMock()
    connection._reader.at_eof.return_value = False
    connection._close_connection = AsyncMock()

    # Provide buffer that DOES have DPLUG but DOES NOT end in "/>"
    from custom_components.climate_ip.samsung_2878 import PROTOCOL_2878_DPLUG

    dplug_bytes = PROTOCOL_2878_DPLUG.encode("utf-8")

    # If mutated to `not in`, it will read ExtraChunk
    connection._reader.read = AsyncMock(
        side_effect=[dplug_bytes + b" NO_END", b"ExtraChunk", b""]
    )
    res = await connection._read_full_response()

    # Original code uses 'or' and 'in', so it must return early without ExtraChunk
    assert PROTOCOL_2878_DPLUG in res
    assert "ExtraChunk" not in res

    # Mutant: Logic Condition Flips and DPLUG
    # Test Update
    connection._reader.read.side_effect = [b"<Update>data</Update>", b""]
    assert await connection._read_full_response() == "<Update>data</Update>"

    # Test DPLUG
    from custom_components.climate_ip.samsung_2878 import PROTOCOL_2878_DPLUG

    connection._reader.read.side_effect = [PROTOCOL_2878_DPLUG.encode(), b""]
    assert PROTOCOL_2878_DPLUG in await connection._read_full_response()

    # Test endswith("/>")
    connection._reader.read.side_effect = [b"<tag/>", b""]
    assert await connection._read_full_response() == "<tag/>"


@pytest.mark.asyncio
# --- 3. RECONNECTION LOGIC AND FAST-FAIL TESTS ---


@pytest.mark.asyncio
async def test_async_execute_fast_fail_backoff(connection):
    """Kills Logic Condition Flip: 'if not self._is_ready.is_set()' vs 'if self._is_ready.is_set()'."""
    # Dummy task so async_execute doesn't call start() and leave a lingering task
    connection._manager_task = asyncio.create_task(asyncio.sleep(999))

    # Critical state: not ready and already attempted reconnection (backoff active)
    connection._is_ready = MagicMock()
    connection._is_ready.is_set.return_value = False
    connection._reconnect_retries = 1

    # Make _is_ready.wait() non-blocking if it gets executed.
    # If mutated to 'if self._is_ready.is_set()', condition will be False (since is_set is False)
    # and code will skip fast-fail, attempting await self._is_ready.wait().
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


# --- 4. TESTS FOR _CONNECTION_MANAGER ---


@pytest.mark.asyncio
async def test_connection_manager_critical_survivors(connection):
    """Verify mutant kill in _connection_manager related to read_task and read_buffer."""
    connection._reader = MagicMock()
    connection._reader.read = AsyncMock(return_value=b"<Response>OK</Response>")

    mock_process = AsyncMock(return_value=b"")
    connection._process_read_queue = mock_process

    # Redefine loop to run once and break
    # without raising weird exceptions causing havoc in cleanup
    original_process = connection._process_read_queue

    async def fake_process(*args, **kwargs):
        # On first chunk processed, raise CancelledError to exit infinite loop
        # since _connection_manager runs in a while True normally cancelled by task.
        await original_process(*args, **kwargs)
        raise asyncio.CancelledError()

    connection._process_read_queue = AsyncMock(side_effect=fake_process)

    # For while to run fast without infinite blocking
    with patch("custom_components.climate_ip.samsung_2878.asyncio.sleep", AsyncMock()):
        # Prevent reconnection if writer fails
        with patch.object(
            connection, "handle_reconnection", new_callable=AsyncMock
        ) as mock_recon:

            class KillMutant(BaseException):
                pass

            # If mutant triggers continue branch, calls handle_reconnection again.
            # Raise BaseException to bypass "except Exception:" of manager and fail test.
            mock_recon.side_effect = [
                True,
                KillMutant("The 'continue' mutant has survived!"),
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
