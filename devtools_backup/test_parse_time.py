import time
import ast
import libcst as cst

start = time.time()
with open('/workspaces/ha_data/config/mutants/custom_components/climate_ip/connection_raw.py') as f:
    source = f.read()

# Fast AST parse
tree = ast.parse(source)

# Find mutant function
mutant_name = "158"
func_name_suffix = f"__mutmut_{mutant_name}"

for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name.endswith(func_name_suffix):
        mutant_node = node
        break

# Extract source
mutant_source = ast.get_source_segment(source, mutant_node)

# libcst parse ONLY the function
cst_func = cst.parse_module(mutant_source)
print(f"Total time: {time.time() - start}")
