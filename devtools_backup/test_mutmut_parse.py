import configparser
import glob

config = configparser.ConfigParser()
config.read('setup.cfg')
if 'mutmut' not in config:
    print("NO MUTMUT SECTION")
    exit(1)

paths = config.get('mutmut', 'paths_to_mutate', fallback=None)
print(f"RAW PATHS: {repr(paths)}")

if paths is None:
    print("PATHS IS NONE")
    exit(1)

parsed = [
    path.strip()
    for path in paths.split(',')
    if path.strip()
]
print(f"PARSED: {parsed}")

expanded = []
for p in parsed:
    expanded.extend(glob.glob(p))

print(f"EXPANDED: {expanded}")
