import sys
import ast
import difflib
from pathlib import Path
import time
import os

def main():
    start_total_time = time.time()
    
    # Read survived5.log
    if not os.path.exists('survived5.log'):
        print("Error: survived5.log not found.")
        return

    with open('survived5.log', 'r') as f:
        lines = f.readlines()

    # Parse targets
    mutants_by_file = {}
    for line in lines:
        if 'survived' not in line:
            continue
        target = line.split()[0].replace(':', '')
        
        # Parse target into file_path, mut_id, and clean_target
        if '__mutmut_' in target:
            parts = target.split('.xǁ')
            if len(parts) == 1:
                base, mut_id = target.split('__mutmut_')
                module_dot_path, _ = base.rsplit('.', 1)
                file_path = module_dot_path.replace('.', '/') + '.py'
            else:
                file_path = parts[0].replace('.', '/') + '.py'
                mut_id = target.split('__mutmut_')[-1]
            clean_target = target.split(': survived')[0].strip().split('.')[-1]
        elif ':' in target:
            file_path, mut_id = target.rsplit(':', 1)
            clean_target = f"__mutmut_{mut_id}"
        elif target.isdigit():
            file_path = "custom_components/climate_ip/properties.py"
            mut_id = target
            clean_target = f"__mutmut_{mut_id}"
        else:
            continue

        mutants_by_file.setdefault(file_path, []).append((mut_id, clean_target, target))

    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))

    with open('mutantes.txt', 'w') as out:
        for file_path, mutants in mutants_by_file.items():
            path = script_dir / 'mutants' / file_path
            if not path.exists():
                out.write(f"No se encontró el archivo sombra en {path}\n")
                continue

            # Load and parse shadow file ONCE
            with open(path, 'r') as f:
                source = f.read()

            tree = ast.parse(source)
            
            # Map function/method names to their nodes
            nodes_by_name = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nodes_by_name[node.name] = node

            for mut_id, clean_target, target in mutants:
                suffix = f"__mutmut_{mut_id}"
                
                mutant_node = None
                # Try finding by clean_target
                if clean_target in nodes_by_name:
                    mutant_node = nodes_by_name[clean_target]
                else:
                    # Fallback to search by suffix
                    for name, node in nodes_by_name.items():
                        if name.endswith(suffix):
                            mutant_node = node
                            break

                if not mutant_node:
                    out.write(f"No se pudo encontrar la mutación {mut_id} (target: {clean_target}) en {file_path}\n")
                    continue

                orig_mangled = mutant_node.name.replace(suffix, "__mutmut_orig")
                orig_node = nodes_by_name.get(orig_mangled)
                if not orig_node:
                    out.write(f"No se pudo encontrar la función original ({orig_mangled}) en {file_path}\n")
                    continue

                orig_src = ast.get_source_segment(source, orig_node)
                mutant_src = ast.get_source_segment(source, mutant_node)
                if orig_src is None or mutant_src is None:
                    out.write(f"Error al obtener código fuente para {mut_id} en {file_path}\n")
                    continue

                # Clean up names for diff
                base_mangled = mutant_node.name.replace(suffix, "")
                clean_name = base_mangled.split("ǁ")[-1]
                
                orig_src = orig_src.replace(orig_node.name, clean_name, 1)
                mutant_src = mutant_src.replace(mutant_node.name, clean_name, 1)

                out.write('----\n')
                out.write(f'# Mutante ID: {mut_id} en {file_path}\n')
                out.write(f'# TARGET: {target}\n')
                diff = list(difflib.unified_diff(
                    orig_src.splitlines(), 
                    mutant_src.splitlines(), 
                    fromfile=file_path, 
                    tofile=file_path, 
                    lineterm=''
                ))
                
                for line in diff:
                    # ANSI colors
                    if line.startswith('+'):
                        out.write(f"\033[92m{line}\033[0m\n")
                    elif line.startswith('-'):
                        out.write(f"\033[91m{line}\033[0m\n")
                    elif line.startswith('@@'):
                        out.write(f"\033[96m{line}\033[0m\n")
                    else:
                        out.write(f"{line}\n")
                        
    print(f"Completado en {time.time() - start_total_time:.2f}s")

if __name__ == '__main__':
    main()
