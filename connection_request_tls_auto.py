# pylint: disable=import-outside-toplevel,consider-using-in,duplicate-code,too-few-public-methods,too-many-arguments,too-many-branches,too-many-instance-attributes,too-many-positional-arguments,unused-import
# custom_components/climate_ip/connection_request_tls_auto.py
# pylint: disable=import-outside-toplevel,line-too-long
"""
Synchronous connection engine using requests with tolerance for mTLS renegotiation.

TARGET DEVICES:
- Samsung SmartThings HVAC (connection type: 'request_tls_auto')
- Samsung SmartThings DHW (connection type: 'request_tls_auto')

This engine creates a FRESH session for every request, which is inefficient but
necessary for some devices that do not support Keep-Alive correctly or require
frequent TLS renegotiation.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import ssl
import warnings
from pathlib import Path
from typing import Any

import requests  # type: ignore[import-untyped]
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads
from jinja2 import Template
from requests.adapters import HTTPAdapter  # type: ignore[import-untyped]
from urllib3.exceptions import InsecureRequestWarning

from .connection import _HOST_LOCKS, Connection, register_connection
from .const import (
    CONF_CERT,
    CONFIG_DEVICE_CONDITION_TEMPLATE,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
)
from .exceptions import AuthError, CannotConnect, RetryNextAttempt
from .helpers import format_placeholders, mask_sensitive_data, tolerant_header_parsing

_LOGGER: logging.Logger = logging.getLogger(__name__)

CONNECTION_TYPE_TLS_AUTO = "tls_auto"
CONNECTION_TYPE_REQUEST_PRINT = "request_tls_auto_print"


class SamsungHTTPAdapter(HTTPAdapter):
    """Custom HTTP adapter for Samsung devices with specific SSL/TLS requirements."""

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> Any:
        """Initialize the pool manager with custom SSL context."""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        # TLSv1 is deprecated in Python 3.13 but strictly required by legacy Samsung
        # AC devices on port 2878. Suppress surgically; protocol cannot be upgraded.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="ssl.TLSVersion.TLSv1 is deprecated",
                category=DeprecationWarning,
            )
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1
        ssl_context.set_ciphers("ALL:@SECLEVEL=0")
        kwargs["ssl_context"] = ssl_context
        return super().init_poolmanager(*args, **kwargs)


def _mask_request_params(params: dict[str, Any], _log_prefix: str) -> dict[str, Any]:
    """Return a copy of request params with sensitive data masked for logging."""
    masked_params = copy.deepcopy(params)
    sensitive_keys = [
        "token",
        "DeviceToken",
        "Authorization",
        "mac",
        "unique_id",
        "uuid",
        "DUID",
    ]

    headers = masked_params.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if key in sensitive_keys and isinstance(value, str) and len(value) > 8:
                headers[key] = f"***{value[-6:]}"

    json_payload = masked_params.get("json")
    if isinstance(json_payload, dict):
        for key, value in json_payload.items():
            if key in sensitive_keys and isinstance(value, str) and len(value) > 8:
                json_payload[key] = f"***{value[-6:]}"

    url = masked_params.get("url")
    if isinstance(url, str):
        url = re.sub(r"([a-fA-F0-9]{8,})", lambda m: f"***{m.group(1)[-6:]}", url)
        masked_params["url"] = url

    return masked_params


class ConnectionRequestBase(Connection):
    """Base class for connection engines using the requests library."""

    def __init__(
        self,
        hass_config: dict[str, Any] | None,
        _logger: logging.Logger,
        insecure_ssl: bool = False,
        timeout: int | float = 30,
        retry_delay: float = 1.0,
        debug: bool = False,
        hass: Any | None = None,
    ) -> None:
        super().__init__(hass_config or {}, _logger, hass=hass)
        self._params: dict[str, Any] = {"timeout": timeout}
        self._max_retries = 3
        self._embedded_command: ConnectionRequestBase | None = None
        self._controller: Any = None
        self._parent: ConnectionRequestBase | None = None
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        self.update_configuration_from_hass(hass_config)
        self._condition_template: Template | None = None
        self._insecure_ssl = insecure_ssl
        self._retry_delay = retry_delay
        self._debug = debug

        warnings.warn(
            "The 'request_tls_auto' connection method is deprecated and "
            "will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )

    def set_controller_ref(self, controller: Any) -> None:
        """Allows the property to set a reference to the main controller."""
        self._controller = controller

    @property
    def log_prefix(self) -> str:
        """Get the log prefix from the controller for consistent logging."""
        if self._controller:
            return self._controller.log_prefix  # type: ignore[no-any-return]

        if self._parent:
            return self._parent.log_prefix

        fallback_id = None
        if self._controller:
            fallback_id = (
                self._controller.config.get("mac")
                or self._controller.config.get("unique_id")
                or self._controller.config.get("name")
            )

        if fallback_id:
            return f"[{fallback_id[-6:] if len(fallback_id) >= 6 else fallback_id}]"

        return "[NO_ID]"

    def update_auth_token(self, token: str) -> None:
        """Updates the Authorization header with a new token."""
        if self._params and "headers" in self._params:
            self._params["headers"]["authorization"] = f"Bearer {token}"
            _LOGGER.info(
                "%s [Auth] Updated Authorization header with new token.",
                self.log_prefix,
            )

    async def close(self) -> None:
        """Async wrapper for closing resources. Standardized to not use custom thread pools."""
        _LOGGER.debug("%s [ConnectionRequest] Closing resources...", self.log_prefix)

    @property
    def is_async_native(self) -> bool:
        """Indicates if the connection is native asynchronous."""
        return False

    @property
    def is_push_supported(self) -> bool:
        """Return True indicating this connection type supports push updates."""
        return False

    @property
    def async_lock(self) -> asyncio.Lock:
        """Return the shared per-host asyncio.Lock.

        For request engines the host lives in the controller, not in _params,
        so we override the base-class property to source it from there.
        """
        ip: str | None = None
        port: str | int = "default"

        if self._controller:
            ip = self._controller.ip_address
            port = self._controller.port
        elif self._parent:
            return self._parent.async_lock  # type: ignore[return-value]

        if not ip:
            return self._lock  # Fallback: per-instance lock

        key = (str(ip), str(port))
        if key not in _HOST_LOCKS:
            _HOST_LOCKS[key] = asyncio.Lock()
        return _HOST_LOCKS[key]

    async def async_execute_legacy(
        self,
        template: Any,
        value: Any,
        device_state: dict[str, Any] | None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        """Async wrapper for the synchronous execute() method.

        Acquires the shared per-host lock BEFORE dispatching to the thread
        pool, so that at most one request at a time is sent to the same
        physical device, regardless of how many entity instances share the IP.
        """
        async with self.async_lock:
            return await asyncio.to_thread(
                self.execute, template, value, device_state, device_id
            )

    @property
    def embedded_command(self) -> ConnectionRequestBase | None:
        """Return the embedded command if defined."""
        return self._embedded_command

    @property
    def condition_template(self) -> Template | None:
        """Return the condition template for execution."""
        return self._condition_template

    def update_configuration_from_hass(
        self, hass_config: dict[str, Any] | None
    ) -> None:
        """Update connection parameters from Home Assistant configuration."""
        if hass_config is not None:
            cert_file = hass_config.get(CONF_CERT, None)
            if cert_file is not None:
                if cert_file.find("\\") == -1 and cert_file.find("/") == -1:
                    cert_file = str(Path(__file__).parent / cert_file)

            self._params[CONF_CERT] = cert_file

    def load_from_yaml(self, node: dict[str, Any] | None, connection_base: Any) -> bool:
        # pylint: disable=import-outside-toplevel,protected-access
        if connection_base:
            self._params.update(connection_base._params.copy())
            self._condition_template = connection_base._condition_template
            self._insecure_ssl = connection_base._insecure_ssl
            self._retry_delay = connection_base._retry_delay
            self._debug = connection_base._debug

        if node:
            self._params.update(node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {}))
            self._insecure_ssl = node.get("insecure_ssl", self._insecure_ssl)
            self._params["timeout"] = node.get("timeout", self._params["timeout"])
            self._retry_delay = node.get("retry_delay", self._retry_delay)
            self._debug = node.get("debug", self._debug)
            if CONFIG_DEVICE_CONNECTION in node:
                # FIXED E1128: Assignment is now from a method defined in this base class
                self._embedded_command = self.create_updated(
                    node[CONFIG_DEVICE_CONNECTION]
                )
            if CONFIG_DEVICE_CONDITION_TEMPLATE in node:
                self._condition_template = Template(
                    node[CONFIG_DEVICE_CONDITION_TEMPLATE]
                )

        return True

    def create_updated(
        self, yaml_node: dict[str, Any] | None
    ) -> ConnectionRequestBase:
        """
        FIX for Pylint E1128: Implement create_updated in base class.
        Creates a copy of this connection object updated from a YAML node.
        """
        # Generic instantiation of the current class type (e.g. ConnectionRequestTlsAuto)
        new_instance = type(self)(
            None,
            self._logger,
            self._insecure_ssl,
            self._params.get("timeout", 30),
            self._retry_delay,
            self._debug,
            hass=self._hass,
        )
        new_instance.load_from_yaml(yaml_node, self)
        new_instance._controller = self._controller
        return new_instance

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
        """
        FIX for Pylint W0223: Overriding abstract method from base Connection class.
        Base implementation for synchronous request engines.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} is a synchronous engine and does not support async_execute."
        )

        # pylint: disable=import-outside-toplevel,too-many-statements

    def execute_internal(
        self,
        template: Template | None,
        value: Any,
        _device_state: dict[str, Any] | None,
        device_id: str | None = None,
    ) -> tuple[Any, bool, int]:
        """Execute the HTTP request and handle retries/errors."""

        token = self._controller.token if self._controller else None
        ip_address = self._controller.ip_address if self._controller else None
        mac = (
            self._controller.config.get("mac")
            if self._controller
            else None
        )

        params = self._params.copy()
        if template is not None:
            try:
                from unittest.mock import NonCallableMock

                async_render = getattr(template, "async_render", None)
                rendered_template = (
                    async_render(value=value, device_id=device_id)
                    if callable(async_render) and not isinstance(template, NonCallableMock)
                    else template.render(value=value, device_id=device_id)
                )
                params.update(json_loads(rendered_template))
            except Exception as exc:
                _LOGGER.error(
                    "%s Error rendering template or parsing JSON: %s",
                    self.log_prefix,
                    exc,
                )
                raise ValueError(f"Template rendering failed: {exc}") from exc

        # CRITICAL FIX: Replace placeholders in URLs and headers consistently
        params = format_placeholders(params, token, ip_address, device_id, mac)

        with warnings.catch_warnings():
            for attempt in range(self._max_retries):
                try:
                    warnings.filterwarnings("ignore", category=InsecureRequestWarning)
                    with requests.Session() as session:
                        if self._insecure_ssl:
                            session.mount("https://", SamsungHTTPAdapter())

                        if self._debug:
                            _LOGGER.debug(
                                "%s Executing request (attempt %d/%d) with params: %s",
                                self.log_prefix,
                                attempt + 1,
                                self._max_retries,
                                mask_sensitive_data(params),
                            )

                        resp = session.request(**params)
                        resp.raise_for_status()

                        _LOGGER.debug(
                            "%s Command successful: %s",
                            self.log_prefix,
                            resp.status_code,
                        )
                        return (json_loads(resp.content), True, resp.status_code)

                except JSON_DECODE_EXCEPTIONS as e:
                    _LOGGER.warning(
                        "%s Failed to parse JSON response: %s",
                        self.log_prefix,
                        resp.text,
                    )
                    raise ValueError("Failed to parse JSON response") from e

                except requests.exceptions.HTTPError as e:
                    if e.response.status_code in (401, 403):
                        _LOGGER.debug("%s Auth error: %s", self.log_prefix, e)
                        raise AuthError(f"Auth failed: {e.response.status_code}") from e
                    if (
                        500 <= e.response.status_code < 600
                        and attempt < self._max_retries - 1
                    ):
                        _LOGGER.debug(
                            "%s Server error (%s). Delegating retry to async loop.",
                            self.log_prefix,
                            e.response.status_code,
                        )
                        raise RetryNextAttempt(
                            f"Server error {e.response.status_code}"
                        ) from e
                    raise CannotConnect(f"HTTP error {e.response.status_code}") from e

                except requests.exceptions.Timeout as e:
                    if attempt < self._max_retries - 1:
                        _LOGGER.warning(
                            "%s Timeout, delegating retry...", self.log_prefix
                        )
                        raise RetryNextAttempt("Request timed out") from e
                    raise CannotConnect("Request timed out") from e

                except requests.exceptions.ConnectionError as e:
                    if attempt < self._max_retries - 1:
                        _LOGGER.warning(
                            "%s Connection error, delegating retry...", self.log_prefix
                        )
                        raise RetryNextAttempt("Connection error") from e
                    raise CannotConnect("Failed to establish a connection") from e

                except requests.exceptions.RequestException as e:
                    _LOGGER.error("%s Request error: %s", self.log_prefix, e)
                    raise CannotConnect(f"Network error: {e}") from e

        return (None, False, 0)

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information about the tls_auto connection."""
        return {"engine": "requests_tls_auto", "is_async": False}

    def execute(
        self,
        template: Template | None,
        value: Any,
        device_state: dict[str, Any] | None,
        device_id: str | None = None,
    ) -> Any:
        """Synchronously executes the command."""
        if self.embedded_command:
            if hasattr(self.embedded_command, "set_controller_ref"):
                self.embedded_command.set_controller_ref(self._controller)
            self.embedded_command.execute(template, value, device_state, device_id)

        if not self.check_execute_condition(device_state):
            _LOGGER.debug("%s Execute condition not met, skipping", self.log_prefix)
            return {}

        with tolerant_header_parsing():
            j, _, _ = self.execute_internal(template, value, device_state, device_id)
        return j


@register_connection
class ConnectionRequestTlsAuto(ConnectionRequestBase):
    """Engine using requests with tolerance for mTLS renegotiation."""

    @staticmethod
    def match_type(type_str: str) -> bool:
        """Return True if this connection type matches the given type string."""
        return type_str == CONNECTION_TYPE_TLS_AUTO or type_str == "request_tls_auto"

    # REDUNDANT: create_updated removed here as it is now correctly implemented in the base class.

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
        """
        FIX for Pylint W0223: Overriding abstract method from base Connection class.
        This engine is strictly synchronous; async calls are not supported.
        """
        raise NotImplementedError(
            "ConnectionRequestTlsAuto is a synchronous engine and does not support async_execute. "
            "Use the 'aiohttp' or 'raw' engines for native asynchronous support."
        )
