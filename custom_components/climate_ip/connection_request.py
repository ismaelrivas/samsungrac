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
import re
import os
import ssl
import time
import traceback
from typing import Any, Dict, Optional

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

_LOGGER: logging.Logger = logging.getLogger(__name__)

CONNECTION_TYPE_REQUEST = "request"
CONNECTION_TYPE_REQUEST_PRINT = "request_print"

REQUEST_MAX_RETRIES = 3
REQUEST_RETRY_DELAY = 1.0  # seconds

class SamsungHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
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
    # Esto es importante para URLs que contienen tokens o IDs como parte de la ruta.
    url = masked_params.get("url")
    if isinstance(url, str):
        # Expresión regular para encontrar UUIDs o cadenas alfanuméricas largas
        # que probablemente sean tokens o IDs.
        url = re.sub(r'([a-fA-F0-9]{8,})', lambda m: f"***{m.group(1)[-6:]}", url)
        masked_params["url"] = url

    return masked_params

class ConnectionRequestBase(Connection):
    def __init__(self, hass_config, _logger):
        super(ConnectionRequestBase, self).__init__(hass_config, _logger)
        self._params = {"timeout": 30}
        self._embedded_command = None # An optional nested command.
        self._controller = None  # Will be set by the property that creates this.
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        self.update_configuration_from_hass(hass_config)
        self._condition_template = None
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

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
    def embedded_command(self):
        return self._embedded_command

    @property
    def condition_template(self):
        return self._condition_template

    def update_configuration_from_hass(self, hass_config):
        if hass_config is not None:
            cert_file = hass_config.get(CONF_CERT, None)
            if cert_file is not None:
                if cert_file.find("\\") == -1 and cert_file.find("/") == -1:
                    cert_file = os.path.join(os.path.dirname(__file__), cert_file)

            self._params[CONF_CERT] = cert_file

    def load_from_yaml(self, node, connection_base):
        from jinja2 import Template

        if connection_base:
            self._params.update(connection_base._params.copy())
            self._condition_template = connection_base._condition_template

        if node:
            self._params.update(node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {}))
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
            _LOGGER.debug("%s Evaluating execute condition", self.log_prefix)
            try:
                rendered_condition = self.condition_template.render(
                    device_state=device_state
                )
                _LOGGER.debug("%s Execute condition result: %s", self.log_prefix, rendered_condition)
                do_execute = rendered_condition == "1"
            except:
                _LOGGER.error(
                    "%s Error evaluating execute condition, executing command anyway", self.log_prefix
                )
                do_execute = True

        return do_execute

    def execute_internal(self, template, value, device_state, device_id=None) -> (json, bool, int):
        """Internal synchronous method to execute the HTTP request with retries."""
        import warnings
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        params = self._params.copy()
        if template is not None:
            try:
                # Pass device_id to the template for use in URLs, etc.
                params.update(json.loads(template.render(value=value, device_id=device_id)))
            except Exception as exc:
                _LOGGER.error("%s Error rendering template or parsing JSON: %s", self.log_prefix, exc)
                raise ValueError(f"Template rendering failed: {exc}") from exc

        with warnings.catch_warnings():
            for attempt in range(REQUEST_MAX_RETRIES):
                try:
                    warnings.filterwarnings("ignore", category=InsecureRequestWarning) # type: ignore
                    with requests.sessions.Session() as session: # type: ignore
                        _LOGGER.debug("%s Request (attempt %s/%s): %s", self.log_prefix, attempt + 1, REQUEST_MAX_RETRIES, _mask_request_params(params, self.log_prefix))
                        
                        session.mount("https://", SamsungHTTPAdapter())

                        resp = session.request(**params)
                        resp.raise_for_status()
                        
                        # Use DEBUG level for successful command execution to avoid log spam.
                        _LOGGER.debug(
                            "%s Command successful with code: %s",
                            self.log_prefix, resp.status_code
                        )
                        
                        if not resp.text or not resp.text.strip():
                            _LOGGER.debug("%s Response was empty, returning empty JSON object.", self.log_prefix)
                            return ({}, True, resp.status_code)

                        try:
                            return (resp.json(), True, resp.status_code)
                        except (requests.exceptions.JSONDecodeError, json.JSONDecodeError):
                            _LOGGER.warning("%s JSON decode failed for response: %s", self.log_prefix, resp.text)
                            return ({}, True, resp.status_code)

                except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
                    _LOGGER.warning("%s Parsing response json failed! Not retrying. Error: %s", self.log_prefix, e)
                    raise ValueError("Failed to parse JSON response") from e

                except requests.exceptions.HTTPError as e:
                    if e.response.status_code in (401, 403):
                        _LOGGER.error("%s Authentication error: %s. Not retrying", self.log_prefix, e)
                        raise AuthError(f"Authentication failed with status {e.response.status_code}") from e
                    elif 500 <= e.response.status_code < 600 and attempt < REQUEST_MAX_RETRIES - 1:
                        _LOGGER.warning("%s Server error (%s). Retrying in %s seconds", self.log_prefix, e.response.status_code, REQUEST_RETRY_DELAY)
                        time.sleep(REQUEST_RETRY_DELAY)
                        continue
                    else:
                        _LOGGER.error("%s HTTP error: %s. Not retrying", self.log_prefix, e)
                        raise CannotConnect(f"HTTP error {e.response.status_code}") from e
                
                except requests.exceptions.Timeout as e:
                    if attempt < REQUEST_MAX_RETRIES - 1:
                        _LOGGER.warning("%s Request timed out. Retrying in %s seconds", self.log_prefix, REQUEST_RETRY_DELAY)
                        time.sleep(REQUEST_RETRY_DELAY)
                        continue
                    else:
                        _LOGGER.error("%s Request timed out after %s attempts: %s", self.log_prefix, REQUEST_MAX_RETRIES, e)
                        raise CannotConnect("Request timed out") from e

                except requests.exceptions.ConnectionError as e:
                    if attempt < REQUEST_MAX_RETRIES - 1:
                        _LOGGER.warning("%s Connection error. Retrying in %s seconds", self.log_prefix, REQUEST_RETRY_DELAY)
                        time.sleep(REQUEST_RETRY_DELAY)
                        continue
                    else:
                        _LOGGER.error("%s Connection error after %s attempts: %s", self.log_prefix, REQUEST_MAX_RETRIES, e, exc_info=True)
                        raise CannotConnect("Failed to establish a connection") from e

                except requests.exceptions.RequestException as e:
                    _LOGGER.error("%s Unhandled request exception: %s. Not retrying", self.log_prefix, e, exc_info=True)
                    raise CannotConnect(f"An unexpected network error occurred: {e}") from e

    async def execute(self, template, value, device_state, device_id=None):
        """Asynchronously executes the command."""
        # Determinar si es una petición de sondeo (sin valor y sin estado) o un comando.
        is_poll_request = template and not value and not device_state
        if is_poll_request:
            _LOGGER.debug("%s Received poll request.", self.log_prefix)
        else:
            _LOGGER.debug("%s Received command request with value: %s", self.log_prefix, value)

        if self.embedded_command:
            _LOGGER.debug("%s Executing embedded command...", self.log_prefix)

            if hasattr(self.embedded_command, 'set_controller_ref'):
                self.embedded_command.set_controller_ref(self._controller)
            # Pass device_id to the nested command.
            await self.embedded_command.execute(template, value, device_state, device_id)

        if not self.check_execute_condition(device_state):
            _LOGGER.debug("%s Execute condition not met, skipping command", self.log_prefix)
            return {}

        _LOGGER.debug("%s Executing command...", self.log_prefix)
        loop = asyncio.get_running_loop()
        
        try:
            # Pass device_id to the internal execution method.
            j, ok, code = await loop.run_in_executor(
                None, self.execute_internal, template, value, device_state, device_id
            )
            # The retry logic for server errors (5xx) is now inside execute_internal
            return j
        except Exception as e:
            raise e


@register_connection
class ConnectionRequest(ConnectionRequestBase):
    def __init__(self, hass_config, _logger):
        super(ConnectionRequest, self).__init__(hass_config, _logger)

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_REQUEST

    def create_updated(self, node):
        c = ConnectionRequest(None, _LOGGER)
        c.load_from_yaml(node, self)
        return c


test_json = {
    "Devices": [
        {
            "Alarms": [
                {
                    "alarmType": "Device",
                    "code": "FilterAlarm",
                    "id": "0",
                    "triggeredTime": "2019-02-25T08:46:01",
                }
            ],
            "ConfigurationLink": {"href": "/devices/0/configuration"},
            "Diagnosis": {"diagnosisStart": "Ready"},
            "EnergyConsumption": {"saveLocation": "/files/usage.db"},
            "InformationLink": {"href": "/devices/0/information"},
            "Mode": {
                "modes": ["Auto"],
                "options": [
                    "Comode_Off",
                    "Sleep_0",
                    "Autoclean_Off",
                    "Spi_Off",
                    "FilterCleanAlarm_0",
                    "OutdoorTemp_63",
                    "CoolCapa_35",
                    "WarmCapa_40",
                    "UsagesDB_254",
                    "FilterTime_10000",
                    "OptionCode_54458",
                    "UpdateAllow_0",
                    "FilterAlarmTime_500",
                    "Function_15",
                    "Volume_100",
                ],
                "supportedModes": ["Cool", "Dry", "Wind", "Auto"],
            },
            "Operation": {"power": "Off"},
            "Temperatures": [
                {
                    "current": 22.0,
                    "desired": 25.0,
                    "id": "0",
                    "maximum": 30,
                    "minimum": 16,
                    "unit": "Celsius",
                }
            ],
            "Wind": {"direction": "Fix", "maxSpeedLevel": 4, "speedLevel": 0},
            "connected": True,
            "description": "TP6X_RAC_16K",
            "id": "0",
            "name": "RAC",
            "resources": [
                "Alarms",
                "Configuration",
                "Diagnosis",
                "EnergyConsumption",
                "Information",
                "Mode",
                "Operation",
                "Temperatures",
                "Wind",
            ],
            "type": "Air_Conditioner",
            "uuid": "00000000-0000-0000-0000-000000000000",
        }
    ]
}


@register_connection
class ConnectionRequestPrint(ConnectionRequestBase):
    def __init__(self, hass_config, _logger):
        super(ConnectionRequestPrint, self).__init__(hass_config, _logger)

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_REQUEST_PRINT

    def create_updated(self, node):
        c = ConnectionRequestPrint(None, _LOGGER)
        c.load_from_yaml(node, self)
        return c

    async def execute(self, template, value, device_state, device_id=None):
        _LOGGER.debug(
            "%s ConnectionRequestPrint (dry-run), execute with params: %s, device_id: %s",
            self.log_prefix, self._params, device_id
        )
        return test_json
