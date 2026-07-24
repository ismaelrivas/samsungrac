
target_file = "/home/cogollo/ha_data/config/custom_components/climate_ip/config_flow.py"

with open(target_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
in_logger = False
logger_parens = 0

for line in lines:
    stripped = line.strip()
    
    # Check if a _LOGGER statement starts
    if "_LOGGER." in stripped and not stripped.startswith("#"):
        in_logger = True
        logger_parens = 0
    
    if in_logger:
        # Count parenthesis to track if we are still inside the _LOGGER statement
        # We only count parenthesis before any comment on the line
        code_part = line.split("#")[0]
        logger_parens += code_part.count('(') - code_part.count(')')
        
        # Add pragma if missing
        if not line.rstrip("\n").endswith("# pragma: no mutate"):
            # Ensure there's a space before the comment if the line has content
            if line.rstrip("\n"):
                line = line.rstrip("\n") + "  # pragma: no mutate\n"
            else:
                line = "# pragma: no mutate\n"
                
        # If parens balance goes to 0 or below, the statement is complete
        if logger_parens <= 0 and code_part.strip().endswith(')'):
             in_logger = False
        elif logger_parens <= 0 and "(" not in code_part and ")" not in code_part:
             # Just in case it's a single line logger without parenthesis (unlikely but safe)
             pass

    new_lines.append(line)

with open(target_file, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Logger seal complete.")
