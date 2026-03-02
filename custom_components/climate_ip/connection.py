
import asyncio
import logging
from .const import (
    CONFIG_DEVICE_CONNECTION_PARAMS,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
)
from typing import Any, Dict, Optional, Tuple

CLIMATE_IP_CONNECTIONS = []

def register_connection(conn):
    """Decorate a function to register a propery."""
    CLIMATE_IP_CONNECTIONS.append(conn)
    return conn


class Connection:
    def __init__(self, config, logger):
        self._params = {}
        self._logger = logger
        self._config = config

    @property
    def logger(self):
        return self._logger

    @property
    def config(self):
        return self._config

    def load_from_yaml(self, node, connection_base):
        """Load configuration from yaml node dictionary. Use connection base as base but DO NOT modify it.
        Return True if successful False otherwise."""
        return False
        
    def get_diagnostics(self) -> Dict[str, Any]:
        """Return diagnostic information about the connection for troubleshooting.
        Override in subclasses to provide specific connection details."""
        return {}
    
    # --- START OF MODIFICATION (Milestone 0) ---
    
    # Interface for synchronous engines (requests, 2878)
    def execute(self, template, value, device_state, device_id=None) -> Any:
        """Executes a synchronous command."""
        raise NotImplementedError
    
    # Interface for asynchronous engines (aiohttp, raw)
    async def async_execute(self, method, url, data, headers, device_state=None, _is_probe=False, _is_poll=False) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
        """Executes an asynchronous command."""
        raise NotImplementedError
    
    # Helper property for Milestone 1
    @property
    def is_async_native(self) -> bool:
        """Indicates if the connection is native asynchronous (aiohttp)."""
        # Subclasses can override this if 'async_execute' is just a wrapper.
        return False
    
    # --- END OF MODIFICATION (Milestone 0) ---
    
    def check_execute_condition(self, device_state) -> bool:
        """Return True if the command should be executed for the given device state.

        Evaluates the optional Jinja2 ``condition_template`` attribute.  The
        template must render to the string ``"1"`` for the command to run.
        Any other rendered value means skip; a missing template means always run.

        This single shared implementation replaces 4 previously duplicated copies
        in connection_request, connection_request_tls_auto, connection_aiohttp and
        connection_raw.
        """
        _log = self._logger or logging.getLogger(__name__)
        condition = getattr(self, "condition_template", None)
        if condition is None:
            return True
        try:
            rendered = condition.render(device_state=device_state)
            _log.debug(
                "%s Execute condition result: %s",
                getattr(self, "log_prefix", ""),
                rendered,
            )
            return str(rendered).strip() == "1"
        except Exception as e:  # pylint: disable=broad-except
            _log.error(
                "%s Error evaluating execute condition, executing command anyway. Error: %s",
                getattr(self, "log_prefix", ""),
                e,
                exc_info=True,
            )
            return True

    def execute_legacy(self, template, value, device_state, device_id):
        """execute connection and return JSON object as result or None if unsuccesful."""
        return None

    def create_updated(self, yaml_node):
        """Create a copy of connection object and update this object from YAML configuration node"""
        return None