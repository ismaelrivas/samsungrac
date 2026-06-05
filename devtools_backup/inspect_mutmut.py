from mutmut import mutate_file
with open("custom_components/climate_ip/connection_aiohttp.py", "r") as f:
    source = f.read()

mutants = []
def callback(mutant_context, mutant):
    mutants.append((mutant_context.current_line_index, mutant))
    return True

# Mutmut 3 uses a different API?
import inspect
import mutmut
print(dir(mutmut))
