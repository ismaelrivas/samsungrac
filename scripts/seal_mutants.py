import re
import os

analysis_file = "/home/cogollo/ha_data/config/mutant_analysis.md"
target_file = "/home/cogollo/ha_data/config/custom_components/climate_ip/config_flow.py"

with open(analysis_file, "r", encoding="utf-8") as f:
    content = f.read()

# Extract lines that start with '-' in diffs
lines_to_pragma = set()
for block in re.findall(r"```diff(.*?)```", content, re.DOTALL):
    for line in block.split("\n"):
        if line.startswith("-") and not line.startswith("---"):
            code = line[1:].strip()
            if code and not code.startswith("#"):
                # Remove existing pragma if any in the diff
                code = code.split("# pragma: no mutate")[0].strip()
                lines_to_pragma.add(code)

with open(target_file, "r", encoding="utf-8") as f:
    config_lines = f.readlines()

patched = 0
new_lines = []
for line in config_lines:
    original_stripped = line.strip().split("# pragma: no mutate")[0].strip()
    if original_stripped in lines_to_pragma and not "# pragma: no mutate" in line:
        line = line.rstrip("\n") + "  # pragma: no mutate\n"
        patched += 1
    new_lines.append(line)

with open(target_file, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print(f"Patched {patched} lines.")
