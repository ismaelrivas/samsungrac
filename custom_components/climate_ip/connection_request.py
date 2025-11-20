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
from typing import Any, Dict, Optional, Tuple
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN
from requests.adapters import HTTPAdapter

from .connection import Connection, register_connection
from .exceptions import AuthError, CannotConnect, ConnectionRefused
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

    # List of sensitive keys to mask
    SENSITIVE_KEYS = ["token", "DeviceToken", "Authorization", "mac", "unique_id", "uuid", "DUID"]

    # 1. Mask headers
    headers = masked_params.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if key in SENSITIVE_KEYS and isinstance(value, str) and len(value) > 8:
                headers[key] = f"***{value[-6:]}"
            
    # 2. Mask JSON body
    json_payload = masked_params.get("json")
    if isinstance(json_payload, dict):
        for key, value in json_payload.items():
            if key in SENSITIVE_KEYS and isinstance(value, str) and len(value) > 8:
                json_payload[key] = f"***{value[-6:]}"

    # 3. Mask URL
    # This is important for URLs that contain tokens or IDs as part of the path.
    url = masked_params.get("url")
    if isinstance(url, str):
        # Regular expression to find UUIDs or long alphanumeric strings
        # that are likely tokens or IDs.
        url = re.sub(r'([a-fA-F0-9]{8,})', lambda m: f"***{m.group(1)[-6:]}", url)
        masked_params["url"] = url

    return masked_params

class ConnectionRequestBase(Connection):
    def __init__(self, hass_config, _logger):
        super(ConnectionRequestBase, self).__init__(hass_config, _logger)
        self._params: Dict[str, Any] = {"timeout": 30}
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

            self._params[CONF_CERT] = cert_file # type: ignore

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
        import urllib3
        from requests.packages.urllib3.exceptions import InsecureRequestWarning
        from typing import Tuple, Any, Optional

        # --- START OF FIX: StreamWrapper logic ---
        # The StreamWrapper logic from controller_yaml.py needs to be applied here
        # to ensure placeholders are replaced just before execution.
        def _stream_wrapper(data: str, token: Optional[str], ip_address: Optional[str], device_id: Optional[str]) -> str:
            """Replaces placeholders in the rendered template string."""
            if token is not None:
                data = data.replace("__CLIMATE_IP_TOKEN__", str(token))
            if ip_address is not None:
                data = data.replace("__CLIMATE_IP_HOST__", str(ip_address))
            if device_id is not None:
                data = data.replace("__DEVICE_ID__", str(device_id))
            return data

        params = self._params.copy()
        if template is not None:
            try:
                # Pass device_id to the template for use in URLs, etc.
                rendered_template = template.render(value=value, device_id=device_id)
                # --- START OF FIX: Add null check for self._controller ---
                token = self._controller.token if self._controller else None
                ip_address = self._controller.ip_address if self._controller else None
                final_template = _stream_wrapper(rendered_template, token, ip_address, device_id)
                # --- END OF FIX ---
                params.update(json.loads(final_template))
            except Exception as exc:
                _LOGGER.error("%s Error rendering template or parsing JSON: %s", self.log_prefix, exc)
                raise ValueError(f"Template rendering failed: {exc}") from exc

        # INCREASE DELAY: Give the device more time to recover between failures (e.g., 5 seconds)
        LOCAL_RETRY_DELAY = 5.0 

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=InsecureRequestWarning) # type: ignore
            
            # CRITICAL FIX: Create the session OUTSIDE the loop to reuse the TCP/SSL connection (Keep-Alive)
            # This prevents saturating the device with new SSL handshakes on every retry.
            with requests.sessions.Session() as session: # type: ignore
                session.mount("https://", SamsungHTTPAdapter())

                for attempt in range(REQUEST_MAX_RETRIES):
                    try:
                        _LOGGER.debug("%s Request (attempt %s/%s): %s", self.log_prefix, attempt + 1, REQUEST_MAX_RETRIES, _mask_request_params(params, self.log_prefix))
                        
                        resp = session.request(**params)
                        
                        # --- DEBUGGING: Log Raw Response on Error ---
                        if resp.status_code >= 400:
                            _LOGGER.debug(
                                "%s [Debug] HTTP %s Response Body: %s", 
                                self.log_prefix, resp.status_code, resp.text
                            )
                        # --------------------------------------------

                        resp.raise_for_status()
                        
                        # Use DEBUG level for successful command execution to avoid log spam.
                        _LOGGER.debug(
                            "%s Command successful with code: %s",
                            self.log_prefix, resp.status_code
                        )
                        
                        if not resp.text or not resp.text.strip():
                            _LOGGER.debug("%s Response was empty, returning None to trigger a poll.", self.log_prefix)
                            return (None, True, resp.status_code)

                        try:
                            return (resp.json(), True, resp.status_code)
                        except (requests.exceptions.JSONDecodeError, json.JSONDecodeError):
                            # --- START OF FIX: Treat non-JSON success response as a trigger to poll ---
                            # If the response is successful (2xx) but not valid JSON (e.g., just "OK"),
                            # it's a successful command acknowledgment. We return None to trigger a refresh.
                            _LOGGER.debug("%s Response was not valid JSON (e.g., 'OK'). Returning None to trigger poll. Response: %s", self.log_prefix, resp.text.strip())
                            return (None, True, resp.status_code)
                            # --- END OF FIX ---

                    except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
                        _LOGGER.warning("%s Parsing response json failed! Not retrying. Error: %s", self.log_prefix, e)
                        raise ValueError("Failed to parse JSON response") from e

                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code in (401, 403):
                            _LOGGER.error("%s Authentication error: %s. Not retrying", self.log_prefix, e)
                            raise AuthError(f"Authentication failed with status {e.response.status_code}") from e
                        # Retrying 500 errors with longer delay
                        elif 500 <= e.response.status_code < 600 and attempt < REQUEST_MAX_RETRIES - 1:
                            _LOGGER.warning("%s Server error (%s). Retrying in %s seconds", self.log_prefix, e.response.status_code, LOCAL_RETRY_DELAY)
                            time.sleep(LOCAL_RETRY_DELAY)
                            continue
                        else:
                            # Enhanced error logging
                            _LOGGER.error("%s HTTP error: %s. Body: %s. Not retrying", self.log_prefix, e, getattr(e.response, 'text', 'No Body'))
                            raise CannotConnect(f"HTTP error {e.response.status_code}") from e
                    
                    except requests.exceptions.Timeout as e:
                        if attempt < REQUEST_MAX_RETRIES - 1:
                            _LOGGER.warning("%s Request timed out. Retrying in %s seconds", self.log_prefix, LOCAL_RETRY_DELAY)
                            time.sleep(LOCAL_RETRY_DELAY)
                            continue
                        else:
                            _LOGGER.error("%s Request timed out after %s attempts: %s", self.log_prefix, REQUEST_MAX_RETRIES, e)
                            raise CannotConnect("Request timed out") from e

                    except requests.exceptions.ConnectionError as e:
                        if attempt < REQUEST_MAX_RETRIES - 1:
                            _LOGGER.warning("%s Connection error. Retrying in %s seconds", self.log_prefix, LOCAL_RETRY_DELAY)
                            time.sleep(LOCAL_RETRY_DELAY)
                            continue
                        else:
                            # Recursively check the exception chain for the root cause.
                            def has_connection_refused(exc):
                                if isinstance(exc, ConnectionRefusedError):
                                    return True
                                if exc.__cause__:
                                    return has_connection_refused(exc.__cause__)
                                if exc.__context__:
                                    return has_connection_refused(exc.__context__)
                                return False

                            if has_connection_refused(e):
                                _LOGGER.debug("%s Connection refused after %s attempts. Device is likely offline or IP is incorrect.", self.log_prefix, REQUEST_MAX_RETRIES)
                                raise ConnectionRefusedError("Connection was refused by the device") from e
                            else:
                                _LOGGER.error("%s Connection error after %s attempts: %s", self.log_prefix, REQUEST_MAX_RETRIES, e, exc_info=True)
                                raise CannotConnect("Failed to establish a connection") from e

                    except requests.exceptions.RequestException as e:
                        _LOGGER.error("%s Unhandled request exception: %s. Not retrying", self.log_prefix, e, exc_info=True)
                        raise CannotConnect(f"An unexpected network error occurred: {e}") from e
        
        # Fallback return to satisfy static analysis
        return (None, False, 0)

    def execute(self, template, value, device_state, device_id=None):
        """Synchronously executes the command. To be run in an executor."""
        # Determine if it's a polling request (no value and no state) or a command.
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
            self.embedded_command.execute(template, value, device_state, device_id)

        if not self.check_execute_condition(device_state):
            _LOGGER.debug("%s Execute condition not met, skipping command", self.log_prefix)
            return {}

        try:
            # Pass device_id to the internal execution method.
            j, ok, code = self.execute_internal(template, value, device_state, device_id)
            # The retry logic for server errors (5xx) is now inside execute_internal

            # --- FIX: PREVENT DOUBLE POLLING ---
            # If the command was successful but returned no data, strictly return empty dict.
            # We DO NOT trigger a refresh here anymore. The Coordinator handles the 
            # post-command refresh logic (Smart Polling or Delay).
            if j is None:
                _LOGGER.debug("%s Command returned no data (or was a simple 'OK'). Returning empty dict.", self.log_prefix)
                return {} 
            # -----------------------------------

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