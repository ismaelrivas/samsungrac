import asyncio
import concurrent.futures
import json
import logging
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

_LOGGER: logging.Logger = logging.getLogger(__package__)

CONNECTION_TYPE_REQUEST = "request"
CONNECTION_TYPE_REQUEST_PRINT = "request_print"

class SamsungHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
        ssl_context.check_hostname = False
        ssl_context.set_ciphers("ALL:@SECLEVEL=0")
        kwargs["ssl_context"] = ssl_context
        return super().init_poolmanager(*args, **kwargs)


class ConnectionRequestBase(Connection):
    def __init__(self, hass_config, logger):
        super(ConnectionRequestBase, self).__init__(hass_config, logger)
        self._params = {"timeout": 5}
        self._embedded_command = None
        self._controller = None # Will be set by the property that creates this
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        self.update_configuration_from_hass(hass_config)
        self._condition_template = None
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def set_controller_ref(self, controller):
        """Allows the property to set a reference to the main controller."""
        self._controller = controller

    @property
    def log_prefix(self) -> str:
        """Dynamically gets the log prefix from the controller."""
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
        self.logger.info("%s Checking execute condition", self.log_prefix)
        if self.condition_template is not None:
            self.logger.info("%s Execute condition found, evaluating", self.log_prefix)
            try:
                rendered_condition = self.condition_template.render(
                    device_state=device_state
                )
                self.logger.info(
                    "%s Execute condition evaluated: %s", self.log_prefix, rendered_condition
                )
                do_execute = rendered_condition == "1"
            except:
                self.logger.error(
                    "%s Execute condition found, error while evaluating, executing command", self.log_prefix
                )
                do_execute = True
        else:
            self.logger.info("%s Execute condition not found, executing", self.log_prefix)

        return do_execute

    # --- MODIFICACIÓN: Se hace device_id opcional ---
    def execute_internal(self, template, value, device_state, device_id=None) -> (json, bool, int):
        import warnings
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        params = self._params.copy()
        if template is not None:
            try:
                # Pasamos device_id al template para que pueda ser usado si es necesario
                params.update(json.loads(template.render(value=value, device_id=device_id)))
            except Exception as e:
                self.logger.error(f"{self.log_prefix} Error rendering template or parsing JSON: {e}")
                raise ValueError(f"Template rendering failed: {e}") from e

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=InsecureRequestWarning)
            with requests.sessions.Session() as session:
                self.logger.info("%s Setting up HTTP Adapter and ssl context", self.log_prefix)
                
                _LOGGER.debug(f"{self.log_prefix} execute_internal - params: {params} - template: {template} - value: {value} - device_state: {device_state} - device_id: {device_id}")
                
                session.mount("https://", SamsungHTTPAdapter())
                self.logger.info("%s %s", self.log_prefix, params)

                try:
                    resp = session.request(**params)
                    resp.raise_for_status()
                    
                    self.logger.info(
                        "%s Command executed with code: %s",
                        self.log_prefix, resp.status_code
                    )
                    
                    return (resp.json(), True, resp.status_code)

                except json.JSONDecodeError as e:
                    self.logger.warning("%s Parsing response json failed!", self.log_prefix)
                    raise ValueError("Failed to parse JSON response") from e

                except requests.exceptions.HTTPError as e:
                    if e.response.status_code in (401, 403):
                        self.logger.error("%s Authentication error: %s", self.log_prefix, e)
                        raise AuthError(f"Authentication failed with status {e.response.status_code}") from e
                    else:
                        self.logger.error("%s HTTP error: %s", self.log_prefix, e)
                        raise CannotConnect(f"HTTP error {e.response.status_code}") from e
                
                except requests.exceptions.Timeout as e:
                    self.logger.error("%s Request timed out: %s", self.log_prefix, e)
                    raise CannotConnect("Request timed out") from e

                except requests.exceptions.ConnectionError as e:
                    self.logger.error("%s Connection error: %s", self.log_prefix, e)
                    raise CannotConnect("Failed to establish a connection") from e

                except requests.exceptions.RequestException as e:
                    self.logger.error(f"{self.log_prefix} Unhandled request exception: {e}")
                    raise CannotConnect(f"An unexpected network error occurred: {e}") from e

    # --- MODIFICACIÓN: Se hace device_id opcional ---
    async def execute(self, template, value, device_state, device_id=None):
        """Asynchronously executes the command."""
        if self.embedded_command:
            self.logger.info("%s Embedded command found, executing...", self.log_prefix)
            # Pasamos device_id al comando anidado
            await self.embedded_command.execute(template, value, device_state, device_id)

        if not self.check_execute_condition(device_state):
            self.logger.info("%s Execute condition not met, skipping command", self.log_prefix)
            return {}

        self.logger.info("%s Executing command...", self.log_prefix)
        loop = asyncio.get_running_loop()
        
        try:
            # Pasamos device_id a execute_internal
            j, ok, code = await loop.run_in_executor(
                None, self.execute_internal, template, value, device_state, device_id
            )
            
            if not ok and 500 <= code < 505:
                await asyncio.sleep(1.0)
                # Pasamos device_id a execute_internal en el reintento
                j, _, _ = await loop.run_in_executor(
                    None, self.execute_internal, template, value, device_state, device_id
                )

            return j
        except Exception as e:
            raise e


@register_connection
class ConnectionRequest(ConnectionRequestBase):
    def __init__(self, hass_config, logger):
        super(ConnectionRequest, self).__init__(hass_config, logger)

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_REQUEST

    def create_updated(self, node):
        c = ConnectionRequest(None, self.logger)
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
    def __init__(self, hass_config, logger):
        super(ConnectionRequestPrint, self).__init__(hass_config, logger)

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_REQUEST_PRINT

    def create_updated(self, node):
        c = ConnectionRequestPrint(None, self.logger)
        c.load_from_yaml(node, self)
        return c

    # --- MODIFICACIÓN: Se añade device_id opcional para mantener la consistencia ---
    async def execute(self, template, value, device_state, device_id=None):
        self.logger.info(
            "%s ConnectionRequestPrint, execute with params: %s, device_id: %s", self.log_prefix, self._params, device_id
        )
        return test_json
