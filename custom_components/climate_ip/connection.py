import asyncio
import logging
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT
from .yaml_const import CONFIG_DEVICE_CONNECTION_PARAMS, CONFIG_TYPE

_LOGGER = logging.getLogger(__name__)

CLIMATE_IP_CONNECTIONS = []
_CONNECTIONS_STORE = {}
_CONNECTIONS_LOCK = asyncio.Lock()

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

    def execute(self, template, value, device_state, device_id):
        """execute connection and return JSON object as result or None if unsuccesful."""
        return None

    def create_updated(self, yaml_node):
        """Create a copy of connection object and update this object from YAML configuration node"""
        return None


async def create_connection(node, config, logger):
    # Use the unique_id from the config entry as the singleton key
    key = config.get("unique_id")
    if not key:
        logger.error("Cannot create a unique connection without a unique_id in the config.")
        return None

    async with _CONNECTIONS_LOCK:
        if key in _CONNECTIONS_STORE:
            logger.debug(f"Returning existing connection object for {key}")
            return _CONNECTIONS_STORE[key]

        logger.debug(f"Creating new connection object for {key}")
        for conn_class in CLIMATE_IP_CONNECTIONS:
            if CONFIG_TYPE in node:
                if conn_class.match_type(node[CONFIG_TYPE]):
                    c = conn_class(config, logger)
                    if c.load_from_yaml(node, None):
                        _CONNECTIONS_STORE[key] = c
                        return c
    return None

async def remove_connection(config):
    """Remove a connection object from the store."""
    key = config.get("unique_id")
    if not key:
        _LOGGER.warning("Cannot remove a connection without a unique_id in the config.")
        return

    async with _CONNECTIONS_LOCK:
        if key in _CONNECTIONS_STORE:
            _LOGGER.debug(f"Removing connection object for {key}")
            connection = _CONNECTIONS_STORE.pop(key)
            if hasattr(connection, 'stop_listening'):
                await connection.stop_listening()