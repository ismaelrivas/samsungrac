import asyncio
import concurrent.futures
import json
import logging
import os
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

_LOGGER: logging.Logger = logging.getLogger(__package__)

CONNECTION_TYPE_REQUEST = "request_tls_auto"
CONNECTION_TYPE_REQUEST_PRINT = "request_tls_auto_print"

class SamsungHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        _LOGGER.warning("Initializing SamsungHTTPAdapter with insecure SSL/TLS settings. "
                        "This is not recommended and may pose a security risk.")
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.set_ciphers("ALL:@SECLEVEL=0")
        kwargs["ssl_context"] = ssl_context
        return super().init_poolmanager(*args, **kwargs)


class ConnectionRequestBase(Connection):
    def __init__(self, hass_config, logger, insecure_ssl=False, timeout=5, retry_delay=1.0, debug=False):
        super(ConnectionRequestBase, self).__init__(hass_config, logger)
        self._params = {"timeout": timeout}
        self._embedded_command = None
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        self.update_configuration_from_hass(hass_config)
        self._condition_template = None
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._insecure_ssl = insecure_ssl
        self._retry_delay = retry_delay
        self._debug = debug

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
        self.logger.info("Checking execute condition")
        if self.condition_template is not None:
            self.logger.info("Execute condition found, evaluating")
            try:
                rendered_condition = self.condition_template.render(
                    device_state=device_state
                )
                self.logger.info(
                    "Execute condition evaluated: {0}".format(rendered_condition)
                )
                do_execute = rendered_condition == "1"
            except:
                self.logger.error(
                    "Execute condition found, error while evaluating, executing command"
                )
                do_execute = True
        else:
            self.logger.warning("Execute condition not found, executing")

        return do_execute

    def execute_internal(self, template, value, device_state) -> (json, bool, int):
        import warnings
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        params = self._params.copy()
        if template is not None:
            try:
                params.update(json.loads(template.render(value=value)))
            except Exception as e:
                self.logger.error(f"Error rendering template or parsing JSON: {e}")
                raise ValueError(f"Template rendering failed: {e}") from e

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=InsecureRequestWarning)
            with requests.sessions.Session() as session:
                if self._insecure_ssl:
                    self.logger.info("Setting up HTTP Adapter and ssl context")
                    session.mount("https://", SamsungHTTPAdapter())
                
                if self._debug:
                    _LOGGER.debug(f"execute_internal - self: {self} - params: {params} - template: {template} - value: {value} - device_state: {device_state}")

                self.logger.info(params)

                try:
                    resp = session.request(**params)
                    resp.raise_for_status()
                    
                    self.logger.info(
                        "Command executed with code: %s",
                        resp.status_code
                    )
                    
                    return (resp.json(), True, resp.status_code)

                except json.JSONDecodeError as e:
                    self.logger.warning("Parsing response json failed!")
                    raise ValueError("Failed to parse JSON response") from e

                except requests.exceptions.HTTPError as e:
                    if e.response.status_code in (401, 403):
                        self.logger.error("Authentication error: %s", e)
                        raise AuthError(f"Authentication failed with status {e.response.status_code}") from e
                    else:
                        self.logger.error("HTTP error: %s", e)
                        raise CannotConnect(f"HTTP error {e.response.status_code}") from e
                
                except requests.exceptions.Timeout as e:
                    self.logger.error("Request timed out: %s", e)
                    raise CannotConnect("Request timed out") from e

                except requests.exceptions.ConnectionError as e:
                    self.logger.error("Connection error: %s", e)
                    raise CannotConnect("Failed to establish a connection") from e

                except requests.exceptions.RequestException as e:
                    self.logger.error(f"Unhandled request exception: {e}")
                    raise CannotConnect(f"An unexpected network error occurred: {e}") from e

    async def execute(self, template, value, device_state):
        """Asynchronously executes the command."""
        if self.embedded_command:
            self.logger.info("Embedded command found, executing...")
            await self.embedded_command.execute(template, value, device_state)

        if not self.check_execute_condition(device_state):
            self.logger.info("Execute condition not met, skipping command")
            return {}

        self.logger.info("Executing command...")
        loop = asyncio.get_running_loop()

        try:
            # Run the blocking execute_internal method in an executor
            j, ok, code = await loop.run_in_executor(
                None, self.execute_internal, template, value, device_state
            )
            
            if not ok and 500 <= code < 505:
                # server error, try again
                await asyncio.sleep(self._retry_delay)
                j, _, _ = await loop.run_in_executor(
                    None, self.execute_internal, template, value, device_state
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
        c = ConnectionRequestTlsAuto(None, self.logger, self._insecure_ssl, self._params["timeout"], self._retry_delay, self._debug)
        c.load_from_yaml(node, self)
        return c
