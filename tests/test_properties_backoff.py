# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test exponential backoff and jitter for thundering herd prevention."""
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.climate_ip.samsung_2878 import (
    INITIAL_RECONNECT_DELAY,
    ConnectionSamsung2878,
)


async def test_reconnect_jitter_randomness():
    """Verify that multiple reconnection attempts have different jitter delays."""
    config = {"host": "192.168.1.100", "port": 2878, "cert": "dummy.pem", "duid": "12345"}
    logger = MagicMock()

    conn = ConnectionSamsung2878(config, logger)
    conn._reconnect_delay = INITIAL_RECONNECT_DELAY

    # Mock sleep to capture the actual delay values
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("custom_components.climate_ip.helpers.async_check_network_reachability", return_value=True):

        # Force a port connection failure (handshake False) to trigger jittered sleep
        with patch.object(conn, "_establish_connection_and_handshake", return_value=False):

            delays = []
            for _ in range(5):
                await conn.handle_reconnection()
                # Get the last sleep call delay
                delay_called = mock_sleep.call_args[0][0]
                delays.append(delay_called)

                # Reset delay for next iteration comparison
                conn._reconnect_delay = INITIAL_RECONNECT_DELAY

            # Verify we have different values (randomness)
            # Not strictly guaranteed to be different but very likely with 5 attempts
            assert len(set(delays)) > 1

            # Verify jitter is within range (+/- 20% of INITIAL_RECONNECT_DELAY)
            for d in delays:
                assert d >= INITIAL_RECONNECT_DELAY
                assert d <= INITIAL_RECONNECT_DELAY * 1.25 # allowance for float jitter
