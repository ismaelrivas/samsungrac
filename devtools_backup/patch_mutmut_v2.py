import sys
import re

path = '/home/vscode/.local/lib/python3.14/site-packages/mutmut/__main__.py'
with open(path, 'r') as f:
    code = f.read()

# Replace config loading to just hardcode our target
code = code.replace(
    'paths_to_mutate = split_paths(paths_to_mutate)',
    'paths_to_mutate = ["custom_components/climate_ip/connection_raw.py"]'
)

with open(path, 'w') as f:
    f.write(code)

print('Patched mutmut v2 __main__.py!')
