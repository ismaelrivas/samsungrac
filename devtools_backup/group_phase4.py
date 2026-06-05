import sys
import difflib
import ast

survivors = {
    1, 2, 4, 5, 9, 10, 11, 12, 13, 14, 15, 18, 20, 21, 22, 29, 30, 32, 33, 34, 35, 36, 41, 42, 59, 65, 68, 71, 75, 76, 77, 81, 84, 85, 86, 87, 89, 90, 91, 92, 103, 105, 116, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 151, 154, 155, 157, 162, 166, 170, 171, 179, 181
}

source = open('mutants/custom_components/climate_ip/connection_raw.py').read()
tree = ast.parse(source)

mutants = {}
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('xǁConnectionRaw8888ǁasync_execute__mutmut_') and not n.name.endswith('orig'):
        mut_id = int(n.name.split('_')[-1])
        if mut_id in survivors:
            mutants[mut_id] = n

orig_node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "xǁConnectionRaw8888ǁasync_execute__mutmut_orig")
orig_src = ast.get_source_segment(source, orig_node).replace(orig_node.name, 'async_execute', 1)

groups = {
    "is_poll_y_keep_alive": [],
    "format_placeholders": [],
    "headers": [],
    "client_request": [],
    "embedded_command": [],
    "excepciones": [],
    "otros": []
}

for mut_id in sorted(survivors):
    m = mutants.get(mut_id)
    if not m: continue
    m_src = ast.get_source_segment(source, m).replace(m.name, 'async_execute', 1)
    
    diff = list(difflib.unified_diff(orig_src.splitlines(), m_src.splitlines(), lineterm=''))
    changes = [l for l in diff if l.startswith('+ ') or l.startswith('- ')]
    diff_text = "\n".join(changes)
    
    if "is_poll" in diff_text or "keep_alive" in diff_text:
        groups["is_poll_y_keep_alive"].append(mut_id)
    elif "format_placeholders" in diff_text or "{mac}" in diff_text or "{token}" in diff_text or "{dev_id}" in diff_text:
        groups["format_placeholders"].append(mut_id)
    elif "headers" in diff_text or "CONFIG_DEVICE_CONNECTION_HEADERS" in diff_text:
        groups["headers"].append(mut_id)
    elif "request(" in diff_text or "url" in diff_text or "payload" in diff_text or "method" in diff_text:
        groups["client_request"].append(mut_id)
    elif "embedded_command" in diff_text:
        groups["embedded_command"].append(mut_id)
    elif "except " in diff_text or "LibConnError" in diff_text or "TimeoutError" in diff_text or "CannotConnect" in diff_text:
        groups["excepciones"].append(mut_id)
    else:
        groups["otros"].append(mut_id)

for g, items in groups.items():
    print(f"[{g}] ({len(items)} mutantes): {items}")
