import re

with open("custom_components/climate_ip/coordinator.py", "r") as f:
    content = f.read()

# Replace pragma start/end blocks that contain a single statement
def replace_block(match):
    block = match.group(0)
    lines = block.strip().split('\n')
    
    # Extract the statement inside
    statement_lines = lines[1:-1]
    
    # We want to join them, but handle strings properly
    joined_statement = " ".join(line.strip() for line in statement_lines)
    
    # Remove " " concatenations for long strings
    joined_statement = re.sub(r'"\s+"', '', joined_statement)
    joined_statement = re.sub(r"'\s+'", '', joined_statement)
    joined_statement = re.sub(r'"\s+\'', '"', joined_statement) # Edge cases
    joined_statement = re.sub(r"'\s+\"", "'", joined_statement)
    
    # Re-add the proper leading spaces
    leading_spaces = len(lines[0]) - len(lines[0].lstrip())
    indent = " " * leading_spaces
    
    # If it's raise UpdateFailed(...) but it's short, just return the single line with pragma
    if "raise UpdateFailed" in joined_statement and "Switching" not in joined_statement:
        return f"{indent}{joined_statement}  # pragma: no mutate"
    elif "raise ConfigEntryAuthFailed" in joined_statement:
        return f"{indent}{joined_statement}  # pragma: no mutate"
        
    return f"{indent}# fmt: off\n{indent}{joined_statement}  # pragma: no mutate\n{indent}# fmt: on"

# Find blocks
content = re.sub(r'^[ \t]*# pragma: no mutate start\n(?:.*?\n)+?[ \t]*# pragma: no mutate end\n', 
                 lambda m: replace_block(m) + '\n', content, flags=re.MULTILINE)

# Replace pragma blocks on else
content = content.replace("else:  # pragma: no mutate block", "else:")

with open("custom_components/climate_ip/coordinator.py", "w") as f:
    f.write(content)
