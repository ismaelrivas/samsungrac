#!/usr/bin/env python3
import sys
import ast
import difflib
from pathlib import Path
import time

def show_fast(target):
    if '__mutmut_' in target:
        # Formato de mutmut results: modulo.modulo.xǁClaseǁmetodo__mutmut_ID
        parts = target.split('.xǁ')
        if len(parts) == 1:
            # No está en una clase, el target es modulo.funcion__mutmut_ID
            base, mut_id = target.split('__mutmut_')
            module_dot_path, _ = base.rsplit('.', 1)
            module_path = module_dot_path.replace('.', '/') + '.py'
            file_path = module_path
        else:
            module_path = parts[0].replace('.', '/') + '.py'
            file_path = module_path
            mut_id = target.split('__mutmut_')[-1]
    elif ':' in target:
        file_path, mut_id = target.rsplit(':', 1)
    elif target.isdigit():
        file_path = "custom_components/climate_ip/connection_raw.py"
        mut_id = target
    else:
        print("Uso: python3 fast_mutmut_show.py <ruta/archivo.py:ID> o simplemente <ID>")
        return

    import os
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    path = script_dir / 'mutants' / file_path
    if not path.exists():
        print(f"No se encontró el archivo sombra en {path}")
        return

    start_time = time.time()
    with open(path, 'r') as f:
        source = f.read()

    # Parseo ultrarrápido con AST nativo
    tree = ast.parse(source)

    mutant_node = None
    orig_node = None
    
    suffix = f"__mutmut_{mut_id}"

    # Encontrar el mutante
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if '__mutmut_' in target:
                clean_target = target.split(': survived')[0].strip().split('.')[-1]
                if node.name == clean_target:
                    mutant_node = node
                    break
            elif node.name.endswith(suffix):
                mutant_node = node
                break

    if not mutant_node:
        print(f"No se pudo encontrar la mutación {mut_id} en el archivo.")
        return

    # Determinar el nombre del original
    orig_mangled = mutant_node.name.replace(suffix, "__mutmut_orig")

    # Encontrar el original
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == orig_mangled:
                orig_node = node
                break

    if not orig_node:
        print(f"No se pudo encontrar la función original ({orig_mangled}) en el archivo.")
        return

    orig_src = ast.get_source_segment(source, orig_node)
    mutant_src = ast.get_source_segment(source, mutant_node)

    # Limpiar nombres para el diff
    base_mangled = mutant_node.name.replace(suffix, "")
    clean_name = base_mangled.split("ǁ")[-1]
    
    # Reemplazar los nombres engorrosos por el nombre limpio
    orig_src = orig_src.replace(orig_node.name, clean_name, 1)
    mutant_src = mutant_src.replace(mutant_node.name, clean_name, 1)

    print(f'# Mutante ID: {mut_id} en {file_path}')
    diff = list(difflib.unified_diff(
        orig_src.splitlines(), 
        mutant_src.splitlines(), 
        fromfile=file_path, 
        tofile=file_path, 
        lineterm=''
    ))
    
    for line in diff:
        # Coloreado básico para terminal
        if line.startswith('+'):
            print(f"\033[92m{line}\033[0m")
        elif line.startswith('-'):
            print(f"\033[91m{line}\033[0m")
        elif line.startswith('@@'):
            print(f"\033[96m{line}\033[0m")
        else:
            print(line)
            
    print(f"\n\033[90m(Renderizado ultrarrápido en {time.time() - start_time:.2f}s)\033[0m")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python3 fast_mutmut_show.py <mutant_id>")
        sys.exit(1)
        
    show_fast(sys.argv[1])
