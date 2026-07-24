import ast

source = open('mutants/custom_components/climate_ip/connection_raw.py').read()
tree = ast.parse(source)

def get_mutants(prefix, base_name):
    mutants = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith(prefix) and not n.name.endswith('orig')]
    orig_node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == f"{prefix}orig")
    orig_src = ast.get_source_segment(source, orig_node)
    orig_src = orig_src.replace(orig_node.name, base_name, 1)

    result = []
    for m in mutants:
        result.append(f"- `{m.name}`")
    return result

phase3_mutants = []
phase3_mutants.extend(get_mutants('xǁConnectionRaw8888ǁasync_get_client__mutmut_', 'async_get_client'))
phase3_mutants.extend(get_mutants('xǁConnectionRaw8888ǁclose__mutmut_', 'close'))

print(f"Total: {len(phase3_mutants)}")
print("\n".join(phase3_mutants))
