"""Constants for the Climate IP integration."""

DOMAIN = "climate_ip"

PLATFORMS = ["climate"]

# --- Configurable Options ---
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 60
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 300

# --- Configuration Flow and Entry Keys ---
CONF_DEVICE_TYPE = "device_type"
CONF_CONFIG_FILE = "config_file"
CONF_DISCOVERED_DEVICES = "discovered_devices"
CONF_NAME = "name"
CONF_SELECTED_DEVICES = "selected_devices"
CONF_DEVICES = "devices"
CONF_DEVICE_ID = "device_id"

# --- Connection Method Constants (for Dual Engine) ---
CONF_CONN_METHOD = "connection_method"
CONN_METHOD_AIOHTTP = "aiohttp"
CONN_METHOD_REQUESTS = "requests"

# Connection types for config_flow logic
CONN_METHOD_HTTPS_VERIFY = "https_verify"
CONN_METHOD_HTTPS_TLS_AUTO = "tls_auto"

# --- Device Types ---
DEVICE_TYPE_SAMSUNG_8888 = "samsung_8888"
DEVICE_TYPE_SAMSUNG_2878 = "samsung_2878"
DEVICE_TYPE_MIM_H03 = "mim_h03"
DEVICE_TYPE_SMARTTHINGS_HVAC = "smartthings_hvac"
DEVICE_TYPE_SMARTTHINGS_DHW = "smartthings_dhw"

# Group for modern devices that will get the new engine option
DEVICE_TYPE_8888_GROUP = [DEVICE_TYPE_SAMSUNG_8888, DEVICE_TYPE_MIM_H03]

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
DEFAULT_CONF_TEMP_UNIT = "C"
DEFAULT_CONF_CONTROLLER = "yaml"
DEFAULT_UPDATE_DELAY = 0.5