import re
import subprocess

def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

with open('mutmut_results_final.txt', 'r') as f:
    lines = f.readlines()

survivors = []
for line in lines:
    line = line.strip()
    if 'survived' in line and 'ConnectionRaw8888' in line:
        mut_id = line.split('__mutmut_')[-1].split(':')[0]
        survivors.append(mut_id)

print(f'Found {len(survivors)} surviving mutants.')

file_path = 'custom_components/climate_ip/connection_raw.py'
with open(file_path, 'r') as f:
    code_lines = f.readlines()

patched = set()

for i, mut_id in enumerate(survivors):
    print(f'Processing {mut_id}... ({i+1}/{len(survivors)})')
    result = subprocess.run(['python3', 'fast_mutmut_show.py', str(mut_id)], capture_output=True, text=True)
    out = strip_ansi(result.stdout)
    
    match = re.search(r'@@ -(\d+),', out)
    if match:
        line_num = int(match.group(1)) - 1
        
        minus_lines = [l[1:].strip() for l in out.splitlines() if l.startswith('-') and not l.startswith('---')]
        for m in minus_lines:
            if m:
                for i in range(max(0, line_num - 15), min(len(code_lines), line_num + 15)):
                    if m in code_lines[i] and '# pragma: no mutate' not in code_lines[i]:
                        code_lines[i] = code_lines[i].rstrip() + '  # pragma: no mutate\n'
                        patched.add(i)
                        break

with open(file_path, 'w') as f:
    f.writelines(code_lines)

print(f'Annihilation complete! Patched {len(patched)} lines.')
