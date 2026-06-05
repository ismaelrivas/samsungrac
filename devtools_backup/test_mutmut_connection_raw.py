from mutmut.file_mutation import create_mutations
import libcst as cst

with open('/workspaces/ha_data/config/custom_components/climate_ip/connection_raw.py') as f:
    code = f.read()

module, mutations = create_mutations(code, None)
print(f"Found {len(mutations)} mutations.")
