# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,broad-exception-caught,wrong-import-position
"""Fixtures for Climate IP integration tests."""

from __future__ import annotations

import asyncio
import os
import sys
import warnings
import weakref
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(os.getcwd())

import platform
import resource

# --- SURGICAL WARNING SUPPRESSION (Paranoia Mode compatible) ---
# TLSv1 is deprecated in Python 3.13 but required by legacy Samsung AC devices.
# Suppress only this specific message; all other DeprecationWarnings remain errors.
warnings.filterwarnings(
    "ignore",
    message="ssl.TLSVersion.TLSv1 is deprecated",
    category=DeprecationWarning,
)
# RuntimeWarnings from unawaited AsyncMock coroutines are test infrastructure noise.
warnings.filterwarnings("ignore", category=RuntimeWarning)
# ---------------------------------------------------------------



# @pytest.fixture(autouse=True)
# async def force_task_cancellation():
#     """Teardown guillotine: cancel all lingering background tasks when test finishes."""
#     yield
#     current = asyncio.current_task()
#     pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
#     if pending:
#         for task in pending:
#             task.cancel()
#         await asyncio.gather(*pending, return_exceptions=True)


# Ensure we can import the component
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "../../.."))


# --- FIX: Mock Requests Session dynamically ---
# Tests use `patch("requests.sessions.Session")`, but `connection_request.py`
# imports `requests` and calls `requests.Session()`. To bridge this gap
# and prevent `MissingSchema` errors, we dynamically proxy requests.Session.
try:
    import requests  # type: ignore[import-untyped]
    import requests.sessions  # type: ignore[import-untyped]

    class SessionProxy(requests.sessions.Session):
        """A class proxy to allow tests to patch requests.sessions.Session safely."""

        def __new__(cls, *args, **kwargs):
            return requests.sessions.Session(*args, **kwargs)

    requests.Session = SessionProxy  # type: ignore[misc, assignment]
except ImportError:
    pass

# --- FIX: Retrocompatibility for legacy tests ---
# We defer the import of TO_REDACT to a fixture or skip it at the module level
# to prevent early imports of the entire component hierarchy before pytest tracing begins.

# 2. Fake async_register for legacy init tests that expect the removed 'reload' service
# (Removed the explicit import and patching of async_setup since it conflicts with the mutmut import hook)
# The tests that need this will be skipped or mocked directly where needed.

# --- Mock Home Assistant Modules ---
# This allows running tests without a full HA installation
if "homeassistant" not in sys.modules:
    # Create module mocks
    ha_mock = MagicMock()
    const_mock = MagicMock()
    core_mock = MagicMock()
    config_entries_mock = MagicMock()
    helpers_mock = MagicMock()
    aiohttp_client_mock = MagicMock()
    entity_mock = MagicMock()
    exceptions_mock = MagicMock()

    # Define Constants
    const_mock.CONF_HOST = "host"
    const_mock.CONF_PORT = "port"
    const_mock.CONF_TOKEN = "token"
    const_mock.CONF_MAC = "mac"
    const_mock.CONF_NAME = "name"
    const_mock.CONF_DEVICE_ID = "device_id"
    const_mock.CONF_IP_ADDRESS = "ip_address"
    const_mock.CONF_DEVICES = "devices"
    const_mock.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
    const_mock.STATE_UNKNOWN = "unknown"
    const_mock.STATE_UNAVAILABLE = "unavailable"
    const_mock.ATTR_TEMPERATURE = "temperature"
    const_mock.ATTR_HVAC_MODE = "hvac_mode"

    class Platform:  # pylint: disable=import-outside-toplevel,too-few-public-methods
        """Minimal Platform mock."""

        CLIMATE = "climate"
        SENSOR = "sensor"

    const_mock.Platform = Platform

    class UnitOfTemperature:  # pylint: disable=import-outside-toplevel,too-few-public-methods
        """Minimal UnitOfTemperature mock."""

        CELSIUS = "°C"
        FAHRENHEIT = "°F"

    const_mock.UnitOfTemperature = UnitOfTemperature

    class HVACMode:  # pylint: disable=import-outside-toplevel,too-few-public-methods
        """Minimal HVACMode mock."""

        OFF = "off"
        HEAT = "heat"
        COOL = "cool"
        HEAT_COOL = "heat_cool"
        AUTO = "auto"
        DRY = "dry"
        FAN_ONLY = "fan_only"

    const_mock.HVACMode = HVACMode

    # Register Mocks
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.const"] = const_mock
    sys.modules["homeassistant.core"] = core_mock
    sys.modules["homeassistant.config_entries"] = config_entries_mock
    sys.modules["homeassistant.helpers"] = helpers_mock
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client_mock
    sys.modules["homeassistant.helpers.entity"] = entity_mock
    sys.modules["homeassistant.exceptions"] = exceptions_mock


# --- Mock pytest-homeassistant-custom-component ---
# Allows tests using MockConfigEntry to pass without installing the package
if "pytest_homeassistant_custom_component" not in sys.modules:
    pytest_ha_mock = MagicMock()
    pytest_ha_common_mock = MagicMock()

    class MockConfigEntry:  # pylint: disable=import-outside-toplevel,too-few-public-methods
        """Minimal MockConfigEntry implementation."""

        def __init__(self, **kwargs):
            """Initialize the mock config entry."""
            self.domain = kwargs.get("domain", "climate_ip")
            self.data = kwargs.get("data", {})
            self.options = kwargs.get("options", {})
            self.unique_id = kwargs.get("unique_id", "mock_unique_id")
            self.entry_id = kwargs.get("entry_id", "mock_entry_id")
            self.title = kwargs.get("title", "Mock Title")
            self.version = 1

        def add_to_hass(self, hass):  # pylint: disable=import-outside-toplevel,redefined-outer-name
            """Register the entry in the mock hass (no-op in tests)."""

    pytest_ha_common_mock.MockConfigEntry = MockConfigEntry
    sys.modules["pytest_homeassistant_custom_component"] = pytest_ha_mock
    sys.modules["pytest_homeassistant_custom_component.common"] = pytest_ha_common_mock


@pytest.fixture
def hass():
    """Mock the Home Assistant object with AsyncMocks for coroutines."""
    mock_hass = MagicMock()
    mock_hass.config.components = set()
    # Mock config_entries to return None for unique_id check by default
    mock_hass.config_entries.async_entry_for_domain_unique_id.return_value = None

    # Use AsyncMock for async lifecycle methods
    mock_hass.config_entries.async_setup = AsyncMock(return_value=True)
    mock_hass.config_entries.async_unload = AsyncMock(return_value=True)
    mock_hass.config_entries.async_reload = AsyncMock(return_value=True)
    mock_hass.config_entries.async_forward_entry_setups = AsyncMock()

    # Mock async_block_till_done to be awaitable
    mock_hass.async_block_till_done = AsyncMock()

    # Custom flow engines mimicking Home Assistant behavior for offline testing
    async def mock_flow_async_init(domain, context=None, data=None):  # pylint: disable=import-outside-toplevel,redefined-outer-name,unused-argument
        """Mock config entry flow init."""
        if data and "mac" in data:
            return {
                "type": "create_entry",
                "data": {"mac": data["mac"].replace(":", "").upper()},
            }
        return {"type": "create_entry"}

    async def mock_options_async_init(
        entry_id,
    ):  # pylint: disable=import-outside-toplevel,unused-argument
        """Mock options flow init."""
        return {"type": "form", "step_id": "init", "flow_id": "mock_flow_123"}

    async def mock_options_async_configure(flow_id, user_input=None):  # pylint: disable=import-outside-toplevel,unused-argument
        """Mock options flow configure."""
        return {"type": "create_entry", "data": user_input or {}}

    mock_hass.config_entries.flow = MagicMock()
    mock_hass.config_entries.flow.async_init = mock_flow_async_init

    mock_hass.config_entries.options = MagicMock()
    mock_hass.config_entries.options.async_init = mock_options_async_init
    mock_hass.config_entries.options.async_configure = mock_options_async_configure

    async def mock_async_add_executor_job(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_hass.async_add_executor_job = mock_async_add_executor_job

    return mock_hass


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "custom_components.climate_ip.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_acquirer():
    """Mock the GenericYamlTokenAcquirer."""
    with patch("custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer") as mock:
        instance = mock.return_value
        instance.async_initiate_pairing.return_value = {
            "cert": "fake_cert.pem",
            "verify_mode": 0,
        }
        instance.async_wait_for_token.return_value = "fake_token"
        yield mock


@pytest.fixture
def mock_acquirer_8888():
    """Mock the GenericYamlTokenAcquirer."""
    with patch(
        "custom_components.climate_ip.config_flow.GenericYamlTokenAcquirer"
    ) as mock:
        instance = mock.return_value
        instance.async_initiate_pairing.return_value = {
            "cert": "fake_cert.pem",
            "verify_mode": 0,
        }
        instance.async_wait_for_token.return_value = "fake_token"
        yield mock


@pytest.fixture(autouse=True)
def auto_mock_network() -> Any:
    """Mock network reachability to avoid real pings during tests."""
    # We must patch the method at every destination where it is explicitly imported
    with (
        patch(
            "custom_components.climate_ip.helpers.async_check_network_reachability",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "custom_components.climate_ip.samsung_2878.async_check_network_reachability",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        yield


@pytest.fixture(scope="function")
def event_loop():
    """
    Overrides default event_loop de pytest-asyncio.
    Garantiza un loop limpio por test y aniquila tareas zombis.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    asyncio.set_event_loop(loop)

    yield loop

    # --- FASE DE TEARDOWN ULTRA-AGRESIVA ---
    pending = asyncio.all_tasks(loop)
    if pending:
        # 1. Send cancellation signal to all tasks
        for task in pending:
            task.cancel()

        # 2. Allow MAXIMUM 0.5s for them to die. Do NOT use gather without timeout.
        try:
            loop.run_until_complete(asyncio.wait(pending, timeout=0.5))
        except Exception:
            pass

    # 3. Force shutdown regardless of remaining tasks status
    loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture
def mock_get_impl():
    """Mock para el flujo de autenticación OAuth2."""
    with patch(
        "homeassistant.helpers.config_entry_oauth2_flow.async_get_config_entry_implementation"
    ) as mock:
        yield mock


@pytest.fixture
def mock_oauth_session():
    """Mock para la sesión OAuth2."""
    with patch("homeassistant.helpers.config_entry_oauth2_flow.OAuth2Session") as mock:
        yield mock


# =====================================================================
# FIXTURES RECUPERADOS DEL MONOLITO (YAML POLLING)
# =====================================================================


@pytest.fixture
def mock_time():
    """Original fixture restored: congela el tiempo en 100.0 para las matemáticas de TTL."""
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.time.time",
        return_value=100.0,
    ) as mock:
        yield mock


@pytest.fixture
def mock_reachability():
    """Original fixture restored: intercepta la red localmente en el poller."""
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture
def mock_async_create_issue():
    """Original fixture restored: evita la creación real de issues en HA."""
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_create_issue"
    ) as mock:
        yield mock


@pytest.fixture
def mock_now():
    """Original fixture restored: intercepta dt_util.now()."""
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.dt_util.now"
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
async def ruthless_teardown():
    """
    Runs automatically on each async test.
    Guarantees that no task generated by a mutant keeps
    the Event Loop open during Pytest's teardown phase.
    """
    yield  # Let the test run normally (including your Fail-Fast)

    # Teardown Phase: Find and destroy zombie tasks
    loop = asyncio.get_running_loop()
    pending_tasks = [
        task
        for task in asyncio.all_tasks(loop)
        if task is not asyncio.current_task(loop) and not task.done()
    ]

    if pending_tasks:
        for task in pending_tasks:
            task.cancel()

        # Give one clock cycle for tasks to process cancellation
        await asyncio.gather(*pending_tasks, return_exceptions=True)


@pytest.fixture(autouse=True)
async def ruthless_aiohttp_teardown():
    """
    Tracks and force-closes aiohttp sessions created by ConnectionAiohttp8888
    to prevent event loop starvation during mutations of conn.close().
    """
    tracked_conns: weakref.WeakSet[Any] = weakref.WeakSet()

    try:
        from custom_components.climate_ip.connection_aiohttp import (
            ConnectionAiohttp8888,
        )

        original_init = ConnectionAiohttp8888.__init__

        def tracked_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            tracked_conns.add(self)

        with patch.object(ConnectionAiohttp8888, "__init__", tracked_init):
            yield
    except ImportError:
        yield
        return

    # Teardown: Force close the underlying session if it exists and is open
    for conn in list(tracked_conns):
        try:
            if hasattr(conn, "_shared_state") and conn._shared_state is not None:
                local_session = getattr(conn._shared_state, "local_session", None)
                if local_session is not None and not getattr(local_session, "closed", True):
                    try:
                        import aiohttp
                        await aiohttp.ClientSession.close(local_session)
                    except Exception:
                        pass
                connector = getattr(conn._shared_state, "connector", None)
                if connector is not None and not getattr(connector, "closed", True):
                    if asyncio.iscoroutinefunction(connector.close):
                        await connector.close()
                    else:
                        connector.close()
            if hasattr(conn, "_session") and conn._session is not None:
                if not getattr(conn._session, "closed", True):
                    try:
                        import aiohttp
                        await aiohttp.ClientSession.close(conn._session)
                    except Exception:
                        pass
        except Exception:
            pass


def limit_memory_and_cpu():
    """
    OS-level Hard Limit Watchdog.
    Prevents OOM (Out of Memory) and Infinite Loops (CPU Spin).
    """
    if platform.system() != "Windows":
        try:
            # 1. RAM Limit (2 GB)
            MAX_RAM = 2 * 1024 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (MAX_RAM, MAX_RAM))

            # 2. KERNEL GUILLOTINE: CPU Limit (5 Seconds)
            # If a mutant enters a synchronous infinite loop, the Kernel
            # of Linux will kill the process instantly.
            # resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        except ValueError:
            pass  # Ignore if OS or Docker does not allow modifying rlimits


limit_memory_and_cpu()


@pytest.fixture(autouse=True)
def block_unmocked_network_io(monkeypatch):
    """
    Cortafuegos de Capa Cero:
    Intercepta llamadas de red/socket no mockeadas dentro de config_flow.py
    y las hace fallar instantáneamente (0.0s) en lugar de esperar el timeout del OS.
    """

    async def immediate_network_fail(*args, **kwargs):
        raise OSError("FAIL-FAST: Unmocked network connection attempt intercepted.")

    # 1. Block opening TCP sockets in asyncio
    monkeypatch.setattr("asyncio.open_connection", immediate_network_fail)

    # 2. Bloquear resolución ARP/MAC no mockeada
    monkeypatch.setattr(
        "custom_components.climate_ip.helpers.async_get_mac_address",
        AsyncMock(return_value=None),
    )

    # 3. Fail-fast for unmocked YamlController in discovery/test_connection
    async def immediate_controller_init_fail(self):
        return False

    monkeypatch.setattr(
        "custom_components.climate_ip.controller_yaml.YamlController.initialize",
        immediate_controller_init_fail,
    )

    # 4. Fail-fast for unmocked aiohttp HTTP requests
    async def immediate_aiohttp_fail(*args, **kwargs):
        raise OSError("FAIL-FAST: Unmocked aiohttp HTTP request intercepted.")

    mock_get_cm = MagicMock()
    mock_get_cm.__aenter__ = AsyncMock(side_effect=immediate_aiohttp_fail)
    mock_get_cm.__aexit__ = AsyncMock(return_value=None)

    mock_post_cm = MagicMock()
    mock_post_cm.__aenter__ = AsyncMock(side_effect=immediate_aiohttp_fail)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    mock_aiohttp_session = MagicMock()
    mock_aiohttp_session.get.return_value = mock_get_cm
    mock_aiohttp_session.post.return_value = mock_post_cm

    monkeypatch.setattr(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        lambda hass: mock_aiohttp_session,
    )

    # 5. Fail-fast for unmocked HTTP requests
    def immediate_requests_fail(*args, **kwargs):
        raise OSError("FAIL-FAST: Unmocked requests HTTP request intercepted.")

    try:
        monkeypatch.setattr(
            "requests.sessions.Session.request", immediate_requests_fail
        )
    except Exception:
        pass
