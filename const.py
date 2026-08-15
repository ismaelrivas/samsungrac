"""Constants for the Climate IP integration."""

from __future__ import annotations

from typing import final

from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    UnitOfTemperature,
)

DOMAIN = "climate_ip"
ISSUE_CONNECTION_FAILED = "connection_failed"
ISSUE_AUTO_HEALING_RAW = "auto_healing_raw"
ERR_PROPERTY_SET_FAILED = "property_set_failed"
ERR_CONTROLLER_NOT_INITIALIZED = "controller_not_initialized"
ERR_PROPERTY_NOT_FOUND = "property_not_found"
ERR_INVALID_DEVICE_MODE = "invalid_device_mode"
ERR_MISSING_INIT_CONFIG = "missing_init_config"
ERR_UNREGISTERED_PROPERTY = "unregistered_property"
ERR_CACHE_UNINITIALIZED = "cache_uninitialized"
ERR_INVALID_STATE_TYPE = "invalid_state_type"
ERR_MISSING_IP = "missing_ip"
ERR_MISSING_DIAGNOSTICS = "missing_diagnostics"
ERR_COERCING_STATE = "error_coercing_state"

NON_SERIALIZABLE_KEYS: final = ("hass", "session", "logger")
TRUTHY_STRINGS: final = ("true", "1", "yes", "on")
FALSY_STRINGS: final = ("false", "0", "no", "off")
DEFAULT_CONTROLLER_NAME: final = "Unknown"
DEFAULT_SUBDEVICE_NAME: final = "Unknown Unit"
DEFAULT_DEVICE_NAME_PREFIX: final = "Samsung AC"
PREFIX_SUBDEVICE_ID: final = "ID "
KEY_DUID: final = "duid"
KEY_METHOD: final = "method"
KEY_URL: final = "url"
KEY_HEADERS: final = "headers"
KEY_RAW_PAYLOAD: final = "_raw"
KEY_JSON_PAYLOAD: final = "json"
TMPL_VAR_DEVICE_ID: final = "device_id"
TMPL_VAR_VALUE: final = "value"
TMPL_VAR_DEVICE_STATE: final = "device_state"
ID_DELIMITER: final = "_"



# --- Configurable Options ---
ATTR_IS_AVAILABLE = "is_available"
ATTR_POWER: final = "power"
DEFAULT_DEBOUNCE_DELAY: final = 3.0
CONF_ENTRY_ID = "entry_id"
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 60
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 21600
CONF_ENABLE_POLLING = "enable_polling"
DEFAULT_ENABLE_POLLING = True
CONF_KEEP_ALIVE = "keep_alive"
CONF_INSECURE_SSL = "insecure_ssl"
CONF_USE_HTTP = "use_http"

# --- Configuration Flow and Entry Keys ---
CONFIG_ENTRY_VERSION = 2
MAIN_DEVICE_ID = "main"
WIFI_KIT_MGMT_ID = "0"
EXCLUDED_SUBDEVICE_IDS: final = (MAIN_DEVICE_ID, WIFI_KIT_MGMT_ID)

CONF_DEVICE_TYPE = "device_type"
CONF_CONFIG_FILE = "config_file"
CONF_DISCOVERED_DEVICES = "discovered_devices"
CONF_NAME = "name"
CONF_SELECTED_DEVICES = "selected_devices"
CONF_DEVICES = "devices"
CONF_DEVICE_ID = "device_id"
CONF_SUBDEVICE_ID = "id"

IMMUTABLE_CONFIG_KEYS: final[frozenset[str]] = frozenset({
    CONF_HOST,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    CONF_ENTRY_ID,
    CONF_DEVICE_ID,
    CONF_UNIQUE_ID,
    CONF_DEVICE_TYPE,
})
CONF_TEMP_NATIVE_CURRENT = "temp_native_current"
CONF_TEMP_NATIVE_TARGET = "temp_native_target"
CONF_TARGET_TEMP_STEP = "target_temperature_step"
DEFAULT_TARGET_TEMP_STEP = 1.0

CONF_TOKEN_KEY = "token"
CONF_SSL_CONFIG_KEY = "_ssl_config_2878"
MANUFACTURER_SAMSUNG = "Samsung"
HARDWARE_BREATHING_ROOM_SEC = 1.0

# --- Connection Method Constants (for Dual Engine) ---
CONF_CONN_METHOD = "connection_method"
CONN_METHOD_AIOHTTP = "aiohttp"
CONN_METHOD_REQUESTS = "requests"
CONN_METHOD_RAW = "raw"

# Connection types for config_flow logic
CONN_METHOD_HTTPS_VERIFY = "https_verify"
CONN_METHOD_HTTPS_TLS_AUTO = "tls_auto"

# --- Device Ports ---
PORT_SAMSUNG_2878 = 2878
PORT_SAMSUNG_8888 = 8888

# --- Device Types ---
DEVICE_TYPE_SAMSUNG_8888 = "samsung_8888"
DEVICE_TYPE_SAMSUNG_2878 = "samsung_2878"
DEVICE_TYPE_MIM_H03 = "mim_h03"
DEVICE_TYPE_SMARTTHINGS_HVAC = "smartthings_hvac"
DEVICE_TYPE_SMARTTHINGS_DHW = "smartthings_dhw"

# Group for modern devices that will get the new engine option
DEVICE_TYPE_8888_GROUP = [DEVICE_TYPE_SAMSUNG_8888, DEVICE_TYPE_MIM_H03]

# Group for all devices that support the aiohttp engine (Modern + SmartThings)
DEVICE_TYPE_AIOHTTP_SUPPORTED = DEVICE_TYPE_8888_GROUP + [
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPE_SMARTTHINGS_DHW,
]

# Maps device types to their corresponding YAML configuration files.
DEVICE_TYPE_TO_CONFIG_FILE = {
    DEVICE_TYPE_SAMSUNG_8888: "samsungrac.yaml",
    DEVICE_TYPE_SAMSUNG_2878: "samsung_2878.yaml",
    DEVICE_TYPE_MIM_H03: "mim-h03_heatpump.yaml",
    DEVICE_TYPE_SMARTTHINGS_HVAC: "samsung_smartthings_hvac.yaml",
    DEVICE_TYPE_SMARTTHINGS_DHW: "samsung_smartthings_dhw.yaml",
}

# Reverse map for inferring device type during YAML import.
CONFIG_FILE_TO_DEVICE_TYPE = {
    filename: device_type
    for device_type, filename in DEVICE_TYPE_TO_CONFIG_FILE.items()
}

# --- Legacy Constants for YAML Import ---
CONF_CERT = "cert"
CONF_CONTROLLER = "controller"
CONF_TEMP_STEP = "temp_step"
# This is intentionally different from HA's CONF_NAME to avoid conflicts during import.
CONFIG_DEVICE_NAME = "name"
CONFIG_DEVICE_POLL = "poll"
CONFIG_DEVICE_UPDATE_DELAY = "update_delay"

DEFAULT_CONF_CERT_FILE = "ac14k_m.pem"
DEFAULT_CONF_CONFIG_FILE = "samsungrac.yaml"
DEFAULT_CONF_TEMP_UNIT = UnitOfTemperature.CELSIUS
DEFAULT_CONF_CONTROLLER = "yaml"
DEFAULT_UPDATE_DELAY = 0.5
MAX_GET_STATUS_RETRIES = 4
DEFAULT_SMARTTHINGS_HOST = "api.smartthings.com"

# --- Protocol Constants (Samsung 2878) ---
PROTOCOL_2878_DPLUG = "DPLUG-1.6"
PROTOCOL_2878_DRC = "DRC-1.00"
PROTOCOL_2878_INVALIDATE = "InvalidateAccount"
PROTOCOL_2878_DEVICE_STATE = "DeviceState"
PROTOCOL_2878_DEVICE_CONTROL = "DeviceControl"
PROTOCOL_2878_STATUS_OK = 'Status="Okay"'
PROTOCOL_2878_STATUS = "Status"
PROTOCOL_2878_UPDATE = "Update"
PROTOCOL_2878_RESPONSE = "Response"
PROTOCOL_2878_ATTR = "Attr"
PROTOCOL_2878_ATTR_ID = "@ID"
PROTOCOL_2878_ATTR_VALUE = "@Value"
PROTOCOL_2878_POWER_ID = "AC_FUN_POWER"
PROTOCOL_2878_VALUE_ON = "On"

# --- YAML Configuration Constants (Merged from yaml_const.py) ---
CONFIG_DEVICE = "device"
CONFIG_DEVICE_UNIQUE_ID = "unique_id"
CONFIG_DEVICE_VALIDATE_PROPS = "validate_properties"
CONFIG_DEVICE_CONNECTION = "connection"
CONFIG_DEVICE_CONNECTION_PARAMS = "params"
CONFIG_DEVICE_STATUS = "status"
CONFIG_DEVICE_ATTRIBUTES = "attributes"
CONFIG_DEVICE_OPERATIONS = "operations"
CONFIG_DEVICE_SWITCHES = "switches"
CONFIG_DEVICE_SENSORS = "sensors"
CONFIG_TYPE = "type"
CONFIG_DEVICE_OPERATION_VALUES = "values"
CONFIG_DEVICE_OPERATION_VALUE = "value"
CONFIG_DEVICE_OPERATION_NUMBER_MIN = "min"
CONFIG_DEVICE_OPERATION_NUMBER_MAX = "max"
CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE = "unit_template"
CONFIG_DEVICE_STATUS_TEMPLATE = "status_template"
CONFIG_DEVICE_CONNECTION_TEMPLATE = "connection_template"
CONFIG_DEVICE_VALIDATION_TEMPLATE = "validation_template"
CONFIG_DEVICE_CONDITION_TEMPLATE = "condition_template"
CONFIG_DEVICE_POWER_TEMPLATE = "power_template"
CONFIG_DEVICE_CONNECTION_TYPE = "type"
CONFIG_STATE_NODE = "state_node"
CONFIG_DEVICE_CLASS = "device_class"
CONFIG_UNIT_OF_MEASUREMENT = "unit_of_measurement"
CONFIG_ENTITY_CATEGORY = "entity_category"
CONFIG_STATE_CLASS = "state_class"

CONF_DEBUG = "debug"
ERROR_MESSAGE = "ERROR"

# --- Constants for async I/O sizes and networking ---
BUFFER_CHUNK_SIZE = 8192
ICMP_PING_TIMEOUT_MS = 500
MAX_CONSECUTIVE_CONNECTION_ERRORS = 3

# Global HTTP/Network Setup ---
# Aligns with Home Assistant Core's standard 10-second universal setup timeout.
# Replacing scattered magic numbers (e.g., 5s, 10s, 15s) in connection scripts.
GLOBAL_HTTP_TIMEOUT = 10

# Maximum wait time for device polling over the network.
NETWORK_POLL_TIMEOUT = 30.0

# --- Property Constants ---
PROPERTY_TYPE_MODE = "modes"
PROPERTY_TYPE_SWITCH = "switch"
PROPERTY_TYPE_NUMBER = "number"
PROPERTY_TYPE_TEMP = "temperature"
PROPERTY_TYPE_STRING = "string"
PROPERTY_TYPE_ENUM = "enum"
PROPERTY_TYPE_UNIQUE_ID = "unique_id"
STATUS_GETTER_JSON = "json_status"

TEMP_UNIT_CELSIUS_ALIASES: final = ("C", "CELSIUS")
TEMP_UNIT_FAHRENHEIT_ALIASES: final = ("F", "FAHRENHEIT")
DEGREE_SYMBOL: final = "°"

# --- Default Climate Values ---
DEFAULT_CLIMATE_IP_TEMP_MIN: float = 8.0
DEFAULT_CLIMATE_IP_TEMP_MAX: float = 30.0

# --- YAML Operation Names ---
YAML_HVAC = "hvac"
YAML_FAN = "fan"
YAML_PRESET = "preset"
YAML_SWING = "swing"
YAML_SPECIAL = "special"

# --- Intermediate Constants and Maps ---
DEFAULT_JSON_STATUS_PAYLOAD = '{"method": "GET", "url": "/devices"}'
MODE_PROPERTY_SUFFIX = "_mode"
KEY_HVAC = "hvac"
KEY_STATUS = "status"
VALIDATION_SUCCESS_TOKEN = "valid"
LABEL_TARGET_TEMP: final = "target_temperature"
LABEL_CURRENT_TEMP: final = "current_temperature"
FALLBACK_DEVICE_ID: final = "XXXX"
KEY_DEVICE_CONFIG: final = "device"
KEY_IDENTIFIERS: final = "identifiers"
KEY_PATH_TO_DEVICES: final = "path_to_devices"
KEY_DEVICE_MODE: final = "Mode"
KEY_DEVICE_STATE: final = "device_state"
DEFAULT_CACHE_KEY_ID: final = "none"

# Map YAML operation names to Home Assistant features.
YAML_NAME_TO_HA_FEATURE: dict[str, ClimateEntityFeature] = {
    YAML_FAN: ClimateEntityFeature.FAN_MODE,
    YAML_SWING: ClimateEntityFeature.SWING_MODE,
    YAML_PRESET: ClimateEntityFeature.PRESET_MODE,
    YAML_SPECIAL: ClimateEntityFeature.PRESET_MODE,
    YAML_HVAC: ClimateEntityFeature.TARGET_TEMPERATURE,
}

# Map Legacy YAML operation names to HA attribute names.
LEGACY_YAML_TO_ATTR_MAP: dict[str, str] = {
    YAML_HVAC: ATTR_HVAC_MODE,
    YAML_FAN: ATTR_FAN_MODE,
    YAML_PRESET: ATTR_PRESET_MODE,
    YAML_SWING: ATTR_SWING_MODE,
    YAML_SPECIAL: ATTR_PRESET_MODE,
}

