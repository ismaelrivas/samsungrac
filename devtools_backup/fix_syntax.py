with open("custom_components/climate_ip/coordinator.py", "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if " raise UpdateFailed" in line and "_LOGGER" in line:
        # Split them
        idx = line.find(" raise UpdateFailed")
        line1 = line[:idx].strip()
        line2 = line[idx:].strip()
        indent = len(line) - len(line.lstrip())
        
        # We need to wrap _LOGGER with fmt:off if it was intended to have it
        if "_LOGGER" in line1:
            line1 = line1 + "  # pragma: no mutate"
            new_lines.append(" " * indent + "# fmt: off\n")
            new_lines.append(" " * indent + line1 + "\n")
            new_lines.append(" " * indent + "# fmt: on\n")
        
        if "raise UpdateFailed" in line2:
            new_lines.append(" " * indent + line2 + "\n")
    else:
        new_lines.append(line)

with open("custom_components/climate_ip/coordinator.py", "w") as f:
    f.writelines(new_lines)
