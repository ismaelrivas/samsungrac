import re

with open("custom_components/climate_ip/coordinator.py", "r") as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    if line.startswith("# fmt: off") or line.startswith("# fmt: on") or \
       line.startswith("_LOGGER") or line.startswith("raise UpdateFailed") or \
       line.startswith("raise ConfigEntryAuthFailed"):
        
        # Check if the previous line has leading spaces we can copy
        if i > 0 and not line.startswith(" "):
            # Find the closest non-empty, non-comment line above to guess indentation
            j = i - 1
            while j >= 0:
                if lines[j].strip() and not lines[j].strip().startswith("#"):
                    spaces = len(lines[j]) - len(lines[j].lstrip())
                    
                    # If the previous line is "except ...:", we need to add 4 spaces
                    if lines[j].strip().startswith("except ") or lines[j].strip().startswith("else:"):
                        spaces += 4
                    break
                j -= 1
            
            line = (" " * spaces) + line

    # Fix the weird spacing inside the function calls created by the previous script
    if "# fmt: off" not in line and "# fmt: on" not in line and line.strip().startswith("_LOGGER"):
        line = line.replace("_LOGGER.warning( ", "_LOGGER.warning(")
        line = line.replace("_LOGGER.debug( ", "_LOGGER.debug(")
        line = line.replace("_LOGGER.error( ", "_LOGGER.error(")
        line = line.replace("_LOGGER.critical( ", "_LOGGER.critical(")
        line = line.replace(", )", ")")
    
    if line.strip().startswith("raise UpdateFailed( "):
        line = line.replace("raise UpdateFailed( ", "raise UpdateFailed(")
        line = line.replace(" ) from None", ") from None")
    
    new_lines.append(line)

with open("custom_components/climate_ip/coordinator.py", "w") as f:
    f.writelines(new_lines)

