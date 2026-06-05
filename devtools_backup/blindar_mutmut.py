#!/usr/bin/env python3
import sys
import ast
import os

def process_file(filepath):
    if not os.path.exists(filepath):
        print(f"Error: El archivo {filepath} no existe.")
        sys.exit(1)

    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()

    source_lines = source.splitlines(keepends=True)
    
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"Error de sintaxis en {filepath}: {e}")
        sys.exit(1)

    targets = []
    # Analizar el árbol AST en busca de _LOGGER y raise
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr):
            call = node.value
            # Buscar llamadas a _LOGGER.metodo(...)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                if isinstance(call.func.value, ast.Name) and call.func.value.id == '_LOGGER':
                    targets.append((node.lineno, node.end_lineno, 'logger', node))
        # Buscar instrucciones raise
        elif isinstance(node, ast.Raise):
            targets.append((node.lineno, node.end_lineno, 'raise', node))

    # Ordenar de abajo hacia arriba (reverso) para que al modificar/borrar líneas 
    # no se alteren los números de línea de los objetivos que están por encima.
    targets.sort(key=lambda x: x[0], reverse=True)

    for start_line, end_line, tgt_type, node in targets:
        # Extraer indentación original de la primera línea del bloque
        first_line = source_lines[start_line - 1]
        indent = len(first_line) - len(first_line.lstrip())
        indent_str = first_line[:indent]

        pragma = "  # pragma: no mutate"

        if start_line == end_line:
            # CASO 1: Ya está en una sola línea
            original_line = source_lines[start_line - 1].rstrip('\n')
            if "# pragma: no mutate" not in original_line:
                source_lines[start_line - 1] = original_line + pragma + "\n"
        else:
            # CASO 2: Ocupa múltiples líneas (hay que colapsarlo)
            # ast.unparse genera el código equivalente de forma canónica (en una sola línea)
            collapsed_code = ast.unparse(node)
            
            if "# pragma: no mutate" not in collapsed_code:
                collapsed_code += pragma
            
            # Comprobar si ya estaba envuelto en # fmt: off / # fmt: on para no duplicarlo
            has_fmt_off = False
            if start_line > 1:
                if source_lines[start_line - 2].strip() == "# fmt: off":
                    has_fmt_off = True
                    
            has_fmt_on = False
            if end_line < len(source_lines):
                if source_lines[end_line].strip() == "# fmt: on":
                    has_fmt_on = True

            new_block = []
            
            if not has_fmt_off:
                new_block.append(indent_str + "# fmt: off\n")
            
            # Insertar el código colapsado respetando la indentación base
            new_block.append(indent_str + collapsed_code + "\n")
            
            if not has_fmt_on:
                new_block.append(indent_str + "# fmt: on\n")

            # Sustituir todo el bloque original multilínea por el nuevo bloque
            source_lines[start_line - 1 : end_line] = new_block

    # Escribir los cambios en el archivo original
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(source_lines)
    
    print(f"Archivo '{filepath}' procesado correctamente. Targets modificados: {len(targets)}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python blindar_mutmut.py <ruta_al_fichero.py>")
        sys.exit(1)
    
    process_file(sys.argv[1])
