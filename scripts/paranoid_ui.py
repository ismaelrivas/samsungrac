import re

with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_config_flow.py", "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    
    match = re.search(r'^(\s*)assert (\w+)(\["type"\]|\[\'type\'\]) == (?:"form"|FlowResultType\.FORM)(?:\s*|#.*)$', line)
    if match:
        indent = match.group(1)
        res_var = match.group(2)
        new_lines.append(f'{indent}assert {res_var}.get("step_id") is not None\n')
        new_lines.append(f'{indent}assert {res_var}.get("data_schema") is not None\n')

    match_prog = re.search(r'^(\s*)assert (\w+)(\["type"\]|\[\'type\'\]) == (?:"progress"|FlowResultType\.SHOW_PROGRESS)(?:\s*|#.*)$', line)
    if match_prog:
        indent = match_prog.group(1)
        res_var = match_prog.group(2)
        new_lines.append(f'{indent}assert {res_var}.get("step_id") is not None\n')
        new_lines.append(f'{indent}assert {res_var}.get("progress_action") is not None\n')

with open("/workspaces/ha_data/config/custom_components/climate_ip/tests/test_config_flow.py", "w") as f:
    f.writelines(new_lines)

print("Paranoid assertions added correctly!")
