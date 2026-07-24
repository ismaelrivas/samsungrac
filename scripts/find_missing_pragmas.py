import os

def check_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    missing = []
    
    # Simple line-by-line check. If a line contains _LOGGER and doesn't contain pragma
    in_logger = False
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if "_LOGGER." in line_stripped and not line_stripped.startswith("#"):
            if "# pragma: no mutate" not in line:
                missing.append((i+1, line.rstrip()))
            # check if it's a multiline statement by checking parenthesis
            if line.count('(') > line.count(')'):
                in_logger = True
        elif in_logger:
            if "# pragma: no mutate" not in line:
                missing.append((i+1, line.rstrip()))
            if line.count(')') > line.count('('):
                in_logger = False
            elif line_stripped.endswith(')'):
                in_logger = False
                
    return missing

target_files = [
    "custom_components/climate_ip/config_flow.py",
    "custom_components/climate_ip/controller_yaml_config.py",
    "custom_components/climate_ip/__init__.py",
    "custom_components/climate_ip/climate.py"
]

for tf in target_files:
    path = os.path.join("/home/cogollo/ha_data/config", tf)
    if os.path.exists(path):
        missing = check_file(path)
        if missing:
            print(f"File: {tf} - Missing pragmas: {len(missing)}")
            for num, text in missing:
                print(f"  Line {num}: {text}")

