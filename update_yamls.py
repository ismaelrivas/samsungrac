import yaml
from collections import OrderedDict
import ruamel.yaml

def add_state_node(filepath, mapping):
    yaml = ruamel.yaml.YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    
    with open(filepath, 'r') as f:
        data = yaml.load(f)
        
    for category in ['switches', 'operations']:
        if category in data:
            for prop_id, prop_data in data[category].items():
                if prop_id in mapping:
                    # Insert state_node
                    prop_data['state_node'] = mapping[prop_id]
                    
    with open(filepath, 'w') as f:
        yaml.dump(data, f)

map_2878 = {
    'purify': 'AC_ADD_SPI',
    'beep': 'AC_ADD_BEEP',
    'auto_clean': 'AC_ADD_AUTOCLEAN',
    'hvac': 'AC_FUN_OPMODE',
    'preset': 'AC_FUN_COMODE',
    'power': 'AC_FUN_POWER',
    'special': 'AC_FUN_COMODE',
    'fan': 'AC_FUN_WINDLEVEL',
    'swing': 'AC_FUN_DIRECTION',
    'temperature': 'AC_FUN_TEMPSET'
}

map_rac = {
    'purify': 'Mode.options.0',
    'auto_clean': 'Mode.options.0',
    'beep': 'Mode.options.0',
    'hvac': 'Mode.modes.0',
    'preset': 'Mode.options.0',
    'power': 'Operation.power',
    'fan': 'Wind.speedLevel',
    'swing': 'Wind.direction',
    'temperature': 'Temperatures.0.desired'
}

add_state_node('/workspaces/ha_data/config/custom_components/climate_ip/samsung_2878.yaml', map_2878)
add_state_node('/workspaces/ha_data/config/custom_components/climate_ip/samsungrac.yaml', map_rac)
print('Updated YAMLs')
