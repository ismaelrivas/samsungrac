import difflib
import ast

source = open('mutants/custom_components/climate_ip/connection_raw.py').read()
tree = ast.parse(source)
mutants = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('xǁConnectionRaw8888ǁ__init____mutmut_') and not n.name.endswith('orig')]

orig_node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'xǁConnectionRaw8888ǁ__init____mutmut_orig')
orig_src = ast.get_source_segment(source, orig_node)
orig_src = orig_src.replace(orig_node.name, 'xǁConnectionRaw8888ǁ__init__', 1)

for m in mutants:
    m_src = ast.get_source_segment(source, m)
    m_src = m_src.replace(m.name, 'xǁConnectionRaw8888ǁ__init__', 1)
    diff = list(difflib.unified_diff(orig_src.splitlines(), m_src.splitlines(), lineterm=''))
    print(f"--- Mutant: {m.name} ---")
    print('\n'.join(diff))
