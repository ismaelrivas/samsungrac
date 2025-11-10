"""Constants for the Climate IP integration."""

DOMAIN = "climate_ip"

PLATFORMS = ["climate"]

# --- Configuration Flow and Entry Keys ---
CONF_DEVICE_TYPE = "device_type"
CONF_CONFIG_FILE = "config_file"
CONF_DISCOVERED_DEVICES = "discovered_devices"
CONF_NAME = "name"
CONF_SELECTED_DEVICES = "selected_devices"
CONF_DEVICES = "devices"
CONF_DEVICE_ID = "device_id"

# --- Device Types ---
DEVICE_TYPE_SAMSUNG_8888 = "samsung_8888"
DEVICE_TYPE_SAMSUNG_2878 = "samsung_2878"
DEVICE_TYPE_MIM_H03 = "mim_h03"
DEVICE_TYPE_SMARTTHINGS_HVAC = "smartthings_hvac"
DEVICE_TYPE_SMARTTHINGS_DHW = "smartthings_dhw"

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