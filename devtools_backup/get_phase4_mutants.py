import ast

source = open('mutants/custom_components/climate_ip/connection_raw.py').read()
tree = ast.parse(source)

def get_mutants(prefix, base_name):
    mutants = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith(prefix) and not n.name.endswith('orig')]
    return len(mutants)

count = get_mutants('xǁConnectionRaw8888ǁasync_execute__mutmut_', 'async_execute')
print(f"Total: {count}")
