"""Constants for the Climate IP integration."""

# Domain
DOMAIN = "climate_ip"

# Platforms
PLATFORMS = ["climate", "sensor"]

# Configuration keys
CONF_DEVICE_TYPE   = "device_type"
CONF_CONFIG_FILE   = "config_file"
CONF_IP_ADDRESS    = "ip_address"
CONF_MAC_ADDRESS   = "mac_address"
CONF_NAME          = "name"
CONF_TOKEN         = "token"
CONF_CERT          = "cert"
CONF_DEVICE_ID     = "device_id"
CONF_DEVICES       = "devices"
CONF_DISCOVERED_DEVICES = "discovered_devices"
CONF_SELECTED_DEVICES = "selected_devices"

# Device types
DEVICE_TYPE_SAMSUNG_8888 = "samsung_8888"
DEVICE_TYPE_SAMSUNG_2878 = "samsung_2878"
DEVICE_TYPE_MIM_H03      = "mim_h03"
DEVICE_TYPE_SMARTTHINGS_HVAC = "smartthings_hvac"
DEVICE_TYPE_SMARTTHINGS_DHW = "smartthings_dhw"


# Map of Device Types to YAML config file names
DEVICE_TYPE_TO_CONFIG_FILE = {
    DEVICE_TYPE_SAMSUNG_8888:  "samsungrac.yaml",
    DEVICE_TYPE_SAMSUNG_2878:  "samsung_2878.yaml",
    DEVICE_TYPE_MIM_H03:       "mim-h03_heatpump.yaml",
    DEVICE_TYPE_SMARTTHINGS_HVAC: "samsung_smartthings_hvac.yaml",
    DEVICE_TYPE_SMARTTHINGS_DHW: "samsung_smartthings_dhw.yaml",
}

# Reverse map for YAML import
CONFIG_FILE_TO_DEVICE_TYPE = {
    filename: device_type
    for device_type, filename in DEVICE_TYPE_TO_CONFIG_FILE.items()
}