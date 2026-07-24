from mutmut.file_mutation import mutate_file_contents
with open('/workspaces/ha_data/config/custom_components/climate_ip/connection_raw.py') as f:
    code = f.read()
print("Starting mutate_file_contents")
try:
    mutated_source, mutant_names = mutate_file_contents('connection_raw.py', code)
    print('Found mutations:', len(mutant_names))
except Exception as e:
    print(f"Exception: {e}")
