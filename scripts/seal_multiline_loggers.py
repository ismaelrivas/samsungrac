
target_file = "/home/cogollo/ha_data/config/custom_components/climate_ip/config_flow.py"

with open(target_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
in_logger = False
logger_parens = 0

for line in lines:
    stripped = line.strip()
    
    if "_LOGGER." in stripped and not stripped.startswith("#"):
        in_logger = True
        logger_parens = 0
    
    if in_logger:
        # Strip existing pragma to avoid duplication
        code_part = line.split("# pragma: no mutate")[0].rstrip()
        if not code_part:
            # If the line was just a pragma or comment, keep it as is
            code_part = line.split("#")[0].rstrip()
            
        # Count parenthesis
        logger_parens += code_part.count('(') - code_part.count(')')
        
        # We must add pragma to THIS line
        if not line.rstrip("\n").endswith("# pragma: no mutate"):
            if code_part:
                line = code_part + "  # pragma: no mutate\n"
            else:
                line = line.rstrip("\n") + "  # pragma: no mutate\n"
        
        # Check if logger statement ends on this line
        if logger_parens <= 0 and code_part.endswith(')'):
             in_logger = False
        elif logger_parens <= 0 and '(' not in code_part and ')' not in code_part:
             pass

    new_lines.append(line)

with open(target_file, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Multiline Logger seal complete.")
