from mutmut.file_mutation import get_mutations
with open('/workspaces/ha_data/config/custom_components/climate_ip/connection_raw.py') as f:
    code = f.read()
get_mutations(code, {})
