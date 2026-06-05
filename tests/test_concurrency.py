# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for per-device command serialization via Connection lock."""

import asyncio
import logging
import time
from typing import Any

import pytest

from custom_components.climate_ip.connection import Connection

_LOGGER = logging.getLogger(__name__)

class MockConnection(Connection):
    # pylint: disable=import-outside-toplevel,abstract-method,arguments-differ
    """Mock connection to test locking."""

    def __init__(self, config: dict[str, Any], logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self.execution_times: list[float] = []
        self.concurrent_violations = 0
        self.is_executing = False
        self.id = "mock_device"

    @property
    def is_push_supported(self) -> bool:
        return False

    async def async_execute(
        self,
        method: str | None = None,
        url: str | None = None,
        data: str | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any
    ) -> tuple[str, dict[str, str]]:
        """Mock execution with simulated delay and concurrency check."""
        async with self._lock:
            # Concurrency check
            if self.is_executing:
                self.concurrent_violations += 1

            self.is_executing = True

            # Record start time
            start = time.perf_counter()
            self.execution_times.append(start)

            # Simulate I/O delay
            await asyncio.sleep(0.1)

            self.is_executing = False
            return "ok", {}

@pytest.mark.asyncio
async def test_lock_serialization():
    """Verify that multiple concurrent async_execute calls are serialized."""
    config = {"ip_address": "127.0.0.1"}
    logger = logging.getLogger("test")
    conn = MockConnection(config, logger)

    # Launch 3 concurrent calls
    start_time = time.perf_counter()
    results = await asyncio.gather(
        conn.async_execute(data="cmd1"),
        conn.async_execute(data="cmd2"),
        conn.async_execute(data="cmd3")
    )
    end_time = time.perf_counter()

    # Total time should be at least 0.3s (3 * 0.1s)
    elapsed = end_time - start_time
    assert elapsed >= 0.3
    assert len(results) == 3
    assert conn.concurrent_violations == 0

    # Check that execution times are separated by at least 0.1s
    times = sorted(conn.execution_times)
    for i in range(1, len(times)):
        assert times[i] - times[i-1] >= 0.1

async def test_lock_with_manual_entry():
    """Verify serialization even when manually using the lock."""
    config = {"ip_address": "127.0.0.1"}
    logger = logging.getLogger("test")
    conn = MockConnection(config, logger)

    async def manual_locked_task():
        async with conn._lock:
            if conn.is_executing:
                conn.concurrent_violations += 1
            conn.is_executing = True
            await asyncio.sleep(0.1)
            conn.is_executing = False
            return "manual_ok"

    # Launch mixed calls
    results = await asyncio.gather(
        conn.async_execute(data="cmd1"),
        manual_locked_task(),
        conn.async_execute(data="cmd2")
    )

    assert len(results) == 3
    assert conn.concurrent_violations == 0
    assert "manual_ok" in results
