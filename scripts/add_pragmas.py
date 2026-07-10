import re
import sys
from pathlib import Path


def process_file(file_path: Path) -> None:
    lines = file_path.read_text(encoding="utf-8").splitlines()

    modified_lines = []
    added_count = 0
    already_had_count = 0
    added_lines = []

    # Control de estado del bloque LOGGER
    in_logger_block = False
    logger_start_idx = -1
    open_parentheses = 0
    had_pragma_in_block = False

    # Detecta el pragma tenga o no almohadilla originalmente
    pragma_pattern = r"\s*(?:#\s*)?pragma:\s*no\s*mutate\s*"

    for idx, line in enumerate(lines):
        line_no = idx + 1

        if not in_logger_block:
            if "_LOGGER." in line:
                in_logger_block = True
                logger_start_idx = len(modified_lines)
                had_pragma_in_block = bool(re.search(pragma_pattern, line))

                # Balance de paréntesis inicial
                open_parentheses = line.count("(") - line.count(")")
                cleaned_line = re.sub(pragma_pattern, "", line)

                if open_parentheses <= 0:
                    # Abre y cierra en la misma línea
                    in_logger_block = False
                    if had_pragma_in_block:
                        already_had_count += 1
                        modified_lines.append(
                            f"{cleaned_line}  # pragma: no mutate"
                        )
                    else:
                        added_count += 1
                        added_lines.append(line_no)
                        modified_lines.append(
                            f"{cleaned_line}  # pragma: no mutate"
                        )
                else:
                    # El bloque continúa
                    modified_lines.append(cleaned_line)
            else:
                modified_lines.append(line)
        else:
            # Dentro de un bloque multilínea
            if re.search(pragma_pattern, line):
                had_pragma_in_block = True

            cleaned_line = re.sub(pragma_pattern, "", line)
            open_parentheses += cleaned_line.count("(") - cleaned_line.count(")")

            if open_parentheses <= 0:
                # Cierre real y balanceado del _LOGGER
                in_logger_block = False

                if had_pragma_in_block:
                    already_had_count += 1
                    # Si no estaba en esta última línea, cuenta como movido/corregido
                    if not re.search(pragma_pattern, line):
                        added_lines.append(line_no)
                else:
                    added_count += 1
                    added_lines.append(line_no)

                modified_lines.append(f"{cleaned_line}  # pragma: no mutate")
            else:
                # Línea intermedia interna
                modified_lines.append(cleaned_line)

    modified_content = "\n".join(modified_lines) + "\n"
    original_content = "\n".join(lines) + "\n"

    # Reporte por consola
    if original_content != modified_content:
        file_path.write_text(modified_content, encoding="utf-8")
        print(f"[MODIFICADO] {file_path}")
        print(f"    -> Pragmas añadidos/corregidos: {added_count}")
        if added_lines:
            print(f"    -> Posición en las filas: {added_lines}")
        print(
            f"    -> Total de pragmas finales: {added_count + already_had_count}\n"
        )
    else:
        print(f"[SIN CAMBIOS] {file_path}")
        print(f"    -> Pragmas añadidos: 0")
        print(
            f"    -> Total de pragmas finales: {already_had_count}\n"
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python add_pragma.py <ruta_al_archivo_o_directorio>")
        sys.exit(1)

    target = Path(sys.argv[1])

    if target.is_file():
        process_file(target)
    elif target.is_directory():
        for py_file in target.rglob("*.py"):
            process_file(py_file)
    else:
        print(f"Error: {target} no es un archivo o directorio válido.")