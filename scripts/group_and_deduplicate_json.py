import re
import os
import json
import datetime

def parse_survived_log():
    """Parse survived_latest.log and return a list of mutant metadata dicts."""
    if not os.path.exists('survived_latest.log'):
        print("Error: survived_latest.log not found.")
        return []

    mutants = []
    with open('survived_latest.log', 'r') as f:
        for line in f:
            if 'survived' not in line:
                continue
            target = line.split()[0].replace(':', '').strip()

            mut_id = target.split('__mutmut_')[-1]
            path_part = target.split('__mutmut_')[0]

            class_name = "Module Level"
            method_name = ""

            if 'ǁ' in path_part:
                subparts = path_part.split('ǁ')
                if len(subparts) == 3:
                    class_name = subparts[1]
                    method_name = subparts[2]
                elif len(subparts) == 2:
                    method_name = subparts[1]
            else:
                method_name = path_part.split('.')[-1]

            mutants.append({
                'id': int(mut_id) if mut_id.isdigit() else mut_id,
                'target': target,
                'class': class_name,
                'method': method_name,
                'diff': '',
            })
    return mutants


def parse_mutantes_txt(mutants):
    """Parse mutantes.txt and attach the diff to each mutant dict."""
    if not os.path.exists('mutantes.txt'):
        print("Error: mutantes.txt not found.")
        return mutants

    diffs_by_target: dict[str, str] = {}
    current_target = None
    current_diff_lines: list[str] = []

    with open('mutantes.txt', 'r') as f:
        for line in f:
            if line.startswith('----'):
                if current_target is not None:
                    diffs_by_target[current_target] = ''.join(current_diff_lines)
                current_target = None
                current_diff_lines = []
            elif line.startswith('# TARGET:'):
                current_target = line.removeprefix('# TARGET:').strip()
            elif current_target is not None and not line.startswith('# Mutante ID:'):
                current_diff_lines.append(line)

    if current_target is not None:
        diffs_by_target[current_target] = ''.join(current_diff_lines)

    for m in mutants:
        m['diff'] = diffs_by_target.get(m['target'], '')

    return mutants


def is_redundant(mutant):
    """Return (True, reason) if the mutant is clearly redundant/noise."""
    diff = mutant['diff']

    if '_LOGGER' in diff or 'logger' in diff or 'log_prefix' in diff:
        return True, 'Logger / Diagnostics mutation'

    if 'node.get(' in diff and ', None)' in diff:
        return True, 'Dict get default None mutation'

    if not diff.strip():
        return True, 'Empty diff (not found in shadow file)'

    return False, ''


def main():
    mutants = parse_survived_log()
    mutants = parse_mutantes_txt(mutants)

    # Captura y formateo del tiempo de ejecución heredado del script bash
    elapsed_sec = int(os.environ.get("PIPELINE_DURATION_SECONDS", 0))
    minutes, seconds = divmod(elapsed_sec, 60)
    hours, minutes = divmod(minutes, 60)
    
    if hours > 0:
        duration_formatted = f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        duration_formatted = f"{minutes}m {seconds}s"
    else:
        duration_formatted = f"{seconds}s"

    grouped: dict[tuple[str, str], list] = {}
    redundant_list: list = []
    non_redundant_count = 0
    redundant_count = 0

    for m in mutants:
        red, reason = is_redundant(m)
        # Limpiar secuencias de escape ANSI del diff antes de estructurar
        m['diff'] = re.sub(r'\033\[\d+m', '', m['diff']).strip()
        
        if red:
            m['redundant_reason'] = reason
            redundant_list.append({
                "id": m['id'],
                "class": m['class'],
                "method": m['method'],
                "reason": reason,
                "target": m['target']
            })
            redundant_count += 1
        else:
            non_redundant_count += 1
            key = (m['class'], m['method'])
            grouped.setdefault(key, []).append(m)

    sorted_keys = sorted(grouped.keys(), key=lambda x: (x[0], x[1]))

    # ── Construcción de la estructura JSON de alto rendimiento ──
    json_output = {
        "metadata": {
            "generated_at": datetime.datetime.now().isoformat(),
            "execution_time": {
                "duration_seconds": elapsed_sec,
                "duration_formatted": duration_formatted
            },
            "stats": {
                "total_mutants_analysed": len(mutants),
                "non_redundant_mutants": non_redundant_count,
                "redundant_excluded_mutants": redundant_count
            }
        },
        "non_redundant_mutants_summary": [],
        "non_redundant_mutants_details": {},
        "excluded_mutants": redundant_list
    }

    # Generar el sumario y los detalles dinámicos por Clase -> Método
    for cls, meth in sorted_keys:
        items = grouped[(cls, meth)]
        
        # Añadir al sumario tabular plano
        json_output["non_redundant_mutants_summary"].append({
            "class": cls,
            "method": meth,
            "count": len(items),
            "target_ids": [i['id'] for i in items]
        })

        # Añadir al mapa de detalles estructurado por clase y método
        if cls not in json_output["non_redundant_mutants_details"]:
            json_output["non_redundant_mutants_details"][cls] = {}
            
        json_output["non_redundant_mutants_details"][cls][meth] = [
            {
                "id": m["id"],
                "target": m["target"],
                "diff": m["diff"]
            }
            for m in items
        ]

    # Guardar archivo JSON con sangría estándar
    with open('mutant_analysis.json', 'w', encoding='utf-8') as j_out:
        json.dump(json_output, j_out, indent=2, ensure_ascii=False)

    print(f"JSON Analysis: {non_redundant_count} non-redundant, {redundant_count} redundant.")
    print("→ mutant_analysis.json")


if __name__ == '__main__':
    main()