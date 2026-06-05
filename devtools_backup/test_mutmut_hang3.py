import libcst as cst
from mutmut.file_mutation import MutationVisitor

with open('/workspaces/ha_data/config/custom_components/climate_ip/connection_raw.py') as f:
    code = f.read()

tree = cst.parse_module(code)
visitor = MutationVisitor({}, set())
tree.visit(visitor)

print('Mutations generated:', len(visitor.mutations))
