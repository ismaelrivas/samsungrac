import os

SOURCE_FILE = r'h:\custom_components\climate_ip\controller_yaml.py'
DIR_PATH = os.path.dirname(SOURCE_FILE)

with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 0-indexed line numbers from the exact outline + buffer lines
# Imports and head: 0 to 78
header_lines = lines[0:79]

# YAML Cache: 79 to 87
cache_lines = lines[79:88]

# YamlController declaration: 88 to 93
class_decl_lines = lines[88:94]
class_decl_lines[-1] = "class YamlController(ClimateController, YamlControllerInitMixin, YamlControllerStateMixin):\n"

# 1. Init Mixin Methods
init_ranges = [
    (241, 245), # is_fully_initialized (wait, outline says 242-245. Line 241 is @property)
    (246, 249), # log_prefix
    (250, 253), # unique_id
    (254, 257), # device_id
    (258, 262), # token
    (263, 267), # ip_address
    (268, 400), # _finish_initialization
    (402, 544), # initialize
]

# 2. State Mixin Methods
state_ranges = [
    (167, 204), # _refresh_smartthings_token
    (205, 224), # _update_all_connections_token
    (225, 240), # _mask_sensitive_data
    (545, 566), # async_get_status
    (567, 777), # async_update_state
    (796, 919), # async_update_properties_from_state
    (920, 926), # _rebuild_attributes
    (927, 977), # _build_device_state_from_hass
    (978, 1008),# _build_device_state_from_props
    (1009, 1050),# async_merge_device_state
    (1051, 1064),# _get_cached_device_key_from_prop
    (1065, 1090),# _get_device_key_from_template
    (1091, 1204),# async_predict_and_correct_state
    (1307, 1346),# async_shutdown
]

# 3. Main Class Methods (Stay in controller_yaml.py)
main_ranges = [
    (94, 166),  # __init__
    (778, 781), # match_type
    (782, 785), # name
    (786, 789), # debug
    (790, 795), # poll
    (1205, 1228),# async_set_property
    (1229, 1244),# get_property
    (1245, 1255),# get_property_object
    (1256, 1263),# get_property_all_values
    (1264, 1267),# state_attributes
    (1268, 1271),# temperature_unit
    (1272, 1275),# service_schema_map
    (1276, 1279),# operations
    (1280, 1283),# attributes
    (1284, 1289),# sensors
    (1290, 1306),# device_state
]

# Footer
footer_lines = lines[1347:]

def extract_lines(ranges_list):
    extracted = []
    for start, end in ranges_list:
        extracted.extend(lines[start:end])
        extracted.append("\n") # Blank line between methods
    return extracted

# Write controller_yaml_init.py
with open(os.path.join(DIR_PATH, 'controller_yaml_init.py'), 'w', encoding='utf-8') as f:
    f.writelines(header_lines)
    f.writelines(cache_lines)
    f.write("\nclass YamlControllerInitMixin:\n")
    f.write("    \"\"\"Mixin for initialization and YAML loading logic.\"\"\"\n\n")
    f.writelines(extract_lines(init_ranges))

# Write controller_yaml_state.py
with open(os.path.join(DIR_PATH, 'controller_yaml_state.py'), 'w', encoding='utf-8') as f:
    f.writelines(header_lines)
    f.write("from .exceptions import CannotConnect, AuthError, InvalidHeaderError\n")
    f.write("from homeassistant.exceptions import ConfigEntryAuthFailed\n")
    f.write("from homeassistant.helpers.update_coordinator import UpdateFailed\n")
    f.write("\nclass YamlControllerStateMixin:\n")
    f.write("    \"\"\"Mixin for state management and polling.\"\"\"\n\n")
    f.writelines(extract_lines(state_ranges))

# Write modified controller_yaml.py
with open(os.path.join(DIR_PATH, 'controller_yaml.py'), 'w', encoding='utf-8') as f:
    f.writelines(header_lines)
    f.write("from .controller_yaml_init import YamlControllerInitMixin, clear_yaml_cache\n")
    f.write("from .controller_yaml_state import YamlControllerStateMixin\n\n")
    f.writelines(class_decl_lines)
    f.writelines(extract_lines(main_ranges))
    f.writelines(footer_lines)

print("Split completed successfully!")
