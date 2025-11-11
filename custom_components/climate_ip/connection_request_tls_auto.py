# Monkey-patch urllib3 to be more tolerant of malformed headers from some AC units.
import urllib3.util.response as response_util
from urllib3.exceptions import HeaderParsingError
import urllib3.connection as connection_mod
import logging

_LOGGER_PATCH = logging.getLogger(__package__)

_original_assert = response_util.assert_header_parsing

def _tolerant_assert_header_parsing(headers):
    """A tolerant version of assert_header_parsing that logs instead of raising."""
    try:
        _original_assert(headers)
    except HeaderParsingError as e:
        _LOGGER_PATCH.debug(
            "Ignored HeaderParsingError: %s",
            e
        )

response_util.assert_header_parsing = _tolerant_assert_header_parsing
connection_mod.assert_header_parsing = _tolerant_assert_header_parsing
import asyncio
import copy
import concurrent.futures
import json
import logging
import os
import re
import ssl
import time
import traceback

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN
from requests.adapters import HTTPAdapter

from .connection import Connection, register_connection
from .exceptions import AuthError, CannotConnect
from .yaml_const import (
    CONF_CERT,
    CONFIG_DEVICE_CONDITION_TEMPLATE,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
)

_"""  """LOGGER: logging.Logger = logging.getLogger(__name__)

CONNECTION_TYPE_REQUEST = "request_tls_auto"
CONNECTION_TYPE_REQUEST_PRINT = "request_tls_auto_print"

class SamsungHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.set_ciphers("ALL:@SECLEVEL=0")
        kwargs["ssl_context"] = ssl_context
        return super().init_poolmanager(*args, **kwargs)

def _mask_request_params(params: dict, log_prefix: str) -> dict:
    """Return a copy of request params with sensitive data masked for logging."""
    masked_params = copy.deepcopy(params)
    
    # Lista de claves sensibles a enmascarar
    SENSITIVE_KEYS = ["token", "DeviceToken", "Authorization", "mac", "unique_id", "uuid", "DUID"]

    # 1. Enmascarar cabeceras
    headers = masked_params.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if key in SENSITIVE_KEYS and isinstance(value, str) and len(value) > 8:
                headers[key] = f"***{value[-6:]}"
            
    # 2. Enmascarar cuerpo JSON
    json_payload = masked_params.get("json")
    if isinstance(json_payload, dict):
        for key, value in json_payload.items():
            if key in SENSITIVE_KEYS and isinstance(value, str) and len(value) > 8:
                json_payload[key] = f"***{value[-6:]}"

    # 3. Enmascarar URL
    url = masked_params.get("url")
    if isinstance(url, str):
        # Expresión regular para encontrar UUIDs o cadenas alfanuméricas largas
        url = re.sub(r'([a-fA-F0-9]{8,})', lambda m: f"***{m.group(1)[-6:]}", url)
        masked_params["url"] = url

    return masked_params

class ConnectionRequestBase(Connection):
    def __init__(self, hass_config, _logger, insecure_ssl=False, timeout=30, retry_delay=1.0, debug=False):
        super(ConnectionRequestBase, self).__init__(hass_config, _logger)
        self._params = {"timeout": timeout}
        self._max_retries = 3
        self._embedded_command = None
        self._controller = None # Will be set by the property that creates this.
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        self.update_configuration_from_hass(hass_config)
        self._condition_template = None
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._insecure_ssl = insecure_ssl
        self._retry_delay = retry_delay
        self._debug = debug

    def set_controller_ref(self, controller):
        """Allows the property to set a reference to the main controller."""
        self._controller = controller

    @property
    def log_prefix(self) -> str:
        """Get the log prefix from the controller for consistent logging."""
        if self._controller:
            return self._controller.log_prefix
        return "[NO_ID]"

    def __del__(self):
        self._thread_pool.shutdown(wait=False)

    @property
    def embedded_command:
        return self._embedded_command

    @property
    def condition_template:
        return self._condition_template

    def update_configuration_from_hass(self, hass_config):
        if hass_config is not None:
            cert_file = hass_config.get(CONF_CERT, None)
            if cert_file is not None:
                if cert_file.find("\") == -1 and cert_file.find("/") == -1:
                    cert_file = os.path.join(os.path.dirname(__file__), cert_file)

            self._params[CONF_CERT] = cert_file

    def load_from_yaml(self, node, connection_base):
        from jinja2 import Template

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
                self._embedded_command = self.create_updated(
                    node[CONFIG_DEVICE_CONNECTION]
                )
            if CONFIG_DEVICE_CONDITION_TEMPLATE in node:
                self._condition_template = Template(
                    node[CONFIG_DEVICE_CONDITION_TEMPLATE]
                )

        return True

    def check_execute_condition(self, device_state):
        do_execute = True
        if self.condition_template is not None:
            _LOGGER.debug("Evaluating execute condition")
            try:
                rendered_condition = self.condition_template.render(
                    device_state=device_state
                )
                _LOGGER.debug("Execute condition result: %s", rendered_condition)
                do_execute = rendered_condition == "1"
            except:
                _LOGGER.error(
                    "Error evaluating execute condition, executing command anyway"
                )
                do_execute = True

        return do_execute

    def execute_internal(self, template, value, device_state, device_id=None) -> (json, bool, int):
        import warnings
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        params = self._params.copy()
        if template is not None:
            try:
                params.update(json.loads(template.render(value=value, device_id=device_id)))
            except Exception as exc:
                _LOGGER.error("%s Error rendering template or parsing JSON: %s", self.log_prefix, exc)
                raise ValueError(f"Template rendering failed: {exc}") from exc

        with warnings.catch_warnings():
            for attempt in range(self._max_retries):
                try:
                    warnings.filterwarnings("ignore", category=InsecureRequestWarning)
                    with requests.sessions.Session() as session:
                        if self._insecure_ssl:
                            session.mount("https://", SamsungHTTPAdapter())
                        
                        if self._debug:
                            _LOGGER.debug("%s Executing request (attempt %d/%d) with params: %s", self.log_prefix, attempt + 1, self._max_retries, _mask_request_params(params, self.log_prefix))

                        resp = session.request(**params)
                        resp.raise_for_status()
                        
                        _LOGGER.debug(
                            "Command successful with code: %s",
                            resp.status_code
                        )
                        
                        return (resp.json(), True, resp.status_code)

                except json.JSONDecodeError as e:
                    _LOGGER.warning("%s Failed to parse JSON response. Response text: %s", self.log_prefix, resp.text, exc_info=True)
                    raise ValueError("Failed to parse JSON response") from e

                except requests.exceptions.HTTPError as e:
                    if e.response.status_code in (401, 403):
                        _LOGGER.error("%s Authentication error: %s", self.log_prefix, e, exc_info=True)
                        raise AuthError(f"Authentication failed with status {e.response.status_code}") from e
                    else:
                        _LOGGER.error("%s HTTP error: %s", self.log_prefix, e, exc_info=True)
                        raise CannotConnect(f"HTTP error {e.response.status_code}") from e
                
                except requests.exceptions.Timeout as e:
                    if attempt < self._max_retries - 1:
                        _LOGGER.warning("%s Request timed out. Retrying in %s seconds...", self.log_prefix, self._retry_delay)
                        time.sleep(self._retry_delay)
                        continue
                    else:
                        _LOGGER.error("%s Request timed out after %d attempts: %s", self.log_prefix, self._max_retries, e, exc_info=True)
                        raise CannotConnect("Request timed out") from e

                except requests.exceptions.ConnectionError as e:
                    _LOGGER.error("%s Connection error: %s", self.log_prefix, e, exc_info=True)
                    raise CannotConnect("Failed to establish a connection") from e

                except requests.exceptions.RequestException as e:
                    _LOGGER.error("%s Unhandled request exception: %s", self.log_prefix, e, exc_info=True)
                    raise CannotConnect(f"An unexpected network error occurred: {e}") from e

    async def execute(self, template, value, device_state, device_id=None):
        """Asynchronously executes the command."""
        is_poll_request = template and not value and not device_state
        if is_poll_request:
            _LOGGER.debug("%s Received poll request.", self.log_prefix)
        else:
            _LOGGER.debug("%s Received command request with value: %s", self.log_prefix, value)

        if self.embedded_command:
            _LOGGER.debug("%s Executing embedded command...", self.log_prefix)
            if hasattr(self.embedded_command, 'set_controller_ref'):
                self.embedded_command.set_controller_ref(self._controller)
            await self.embedded_command.execute(template, value, device_state, device_id)

        if not self.check_execute_condition(device_state):
            _LOGGER.debug("%s Execute condition not met, skipping command", self.log_prefix)
            return {}

        loop = asyncio.get_running_loop()

        _LOGGER.debug("%s Executing command...", self.log_prefix)
        try:
            # Run the blocking execute_internal method in an executor
            j, ok, code = await loop.run_in_executor(
                None, self.execute_internal, template, value, device_state, device_id
            )
            return j
        except Exception as e:
            raise e


@register_connection
class ConnectionRequestTlsAuto(ConnectionRequestBase):
    def __init__(self, hass_config, logger, insecure_ssl=False, timeout=30, retry_delay=1.0, debug=False):
        super(ConnectionRequestTlsAuto, self).__init__(hass_config, logger, insecure_ssl, timeout, retry_delay, debug)

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_REQUEST

    def create_updated(self, node):
        c = ConnectionRequestTlsAuto(None, _LOGGER, self._insecure_ssl, self._params["timeout"], self._retry_delay, self._debug)
        c.load_from_yaml(node, self)
        return c
                    
                    _LOGGER.debug(
                        "Command successful with code: %s",
                        resp.status_code
                    )
                    
                    return (resp.json(), True, resp.status_code)

                except json.JSONDecodeError as e:
                    _LOGGER.warning("%s Failed to parse JSON response. Response text: %s", self.log_prefix, resp.text, exc_info=True)
                    raise ValueError("Failed to parse JSON response") from e

                except requests.exceptions.HTTPError as e:
                    if e.response.status_code in (401, 403):
                        _LOGGER.error("%s Authentication error: %s", self.log_prefix, e, exc_info=True)
                        raise AuthError(f"Authentication failed with status {e.response.status_code}") from e
                    else:
                        _LOGGER.error("%s HTTP error: %s", self.log_prefix, e, exc_info=True)
                        raise CannotConnect(f"HTTP error {e.response.status_code}") from e
                
                except requests.exceptions.Timeout as e:
                    _LOGGER.error("%s Request timed out: %s", self.log_prefix, e, exc_info=True)
                    raise CannotConnect("Request timed out") from e

                except requests.exceptions.ConnectionError as e:
                    _LOGGER.error("%s Connection error: %s", self.log_prefix, e, exc_info=True)
                    raise CannotConnect("Failed to establish a connection") from e

                except requests.exceptions.RequestException as e:
                    _LOGGER.error("%s Unhandled request exception: %s", self.log_prefix, e, exc_info=True)
                    raise CannotConnect(f"An unexpected network error occurred: {e}") from e

    async def execute(self, template, value, device_state, device_id=None):
        """Asynchronously executes the command."""
        is_poll_request = template and not value and not device_state
        if is_poll_request:
            _LOGGER.debug("%s Received poll request.", self.log_prefix)
        else:
            _LOGGER.debug("%s Received command request with value: %s", self.log_prefix, value)

        if self.embedded_command:
            _LOGGER.debug("%s Executing embedded command...", self.log_prefix)
            if hasattr(self.embedded_command, 'set_controller_ref'):
                self.embedded_command.set_controller_ref(self._controller)
            await self.embedded_command.execute(template, value, device_state, device_id)

        if not self.check_execute_condition(device_state):
            _LOGGER.debug("%s Execute condition not met, skipping command", self.log_prefix)
            return {}

        loop = asyncio.get_running_loop()

        _LOGGER.debug("%s Executing command...", self.log_prefix)
        try:
            # Run the blocking execute_internal method in an executor
            j, ok, code = await loop.run_in_executor(
                None, self.execute_internal, template, value, device_state, device_id
            )
            
            if not ok and 500 <= code < 505:
                # server error, try again
                await asyncio.sleep(self._retry_delay)
                j, _, _ = await loop.run_in_executor(
                    None, self.execute_internal, template, value, device_state, device_id
                )

            return j
        except Exception as e:
            raise e


@register_connection
class ConnectionRequestTlsAuto(ConnectionRequestBase):
    def __init__(self, hass_config, logger, insecure_ssl=False, timeout=5, retry_delay=1.0, debug=False):
        super(ConnectionRequestTlsAuto, self).__init__(hass_config, logger, insecure_ssl, timeout, retry_delay, debug)

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_REQUEST

    def create_updated(self, node):
        c = ConnectionRequestTlsAuto(None, _LOGGER, self._insecure_ssl, self._params["timeout"], self._retry_delay, self._debug)
        c.load_from_yaml(node, self)
        return c
