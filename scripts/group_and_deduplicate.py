import re
import os
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
            # Full target string, e.g.:
            #   custom_components.climate_ip.properties.xǁDevicePropertyǁis_valid__mutmut_1
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
                'id': mut_id,
                'target': target,   # Full unique key
                'class': class_name,
                'method': method_name,
                'diff': '',
            })
    return mutants


def parse_mutantes_txt(mutants):
    """
    Parse mutantes.txt and attach the diff to each mutant dict.

    The dump script now writes:
        ----
        # Mutante ID: <id> en <file>
        # TARGET: <full_target>
        <diff lines>
    So we key by full target, not just by numeric ID.
    """
    if not os.path.exists('mutantes.txt'):
        print("Error: mutantes.txt not found.")
        return mutants

    # Build a lookup map: target → diff text
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
                # Accumulate diff lines (skip the human-readable ID line)
                current_diff_lines.append(line)

    # Flush last block
    if current_target is not None:
        diffs_by_target[current_target] = ''.join(current_diff_lines)

    # Attach diffs to mutant metadata
    for m in mutants:
        m['diff'] = diffs_by_target.get(m['target'], '')

    return mutants


def is_redundant(mutant):
    """Return (True, reason) if the mutant is clearly redundant/noise."""
    diff = mutant['diff']

    # Mutations that only alter logging call arguments
    if '_LOGGER' in diff or 'logger' in diff or 'log_prefix' in diff:
        return True, 'Logger / Diagnostics mutation'

    # dict.get(key, None) → dict.get(key) — semantically identical
    if 'node.get(' in diff and ', None)' in diff:
        return True, 'Dict get default None mutation'

    # Empty / missing diff (mutant not found in shadow file)
    if not diff.strip():
        return True, 'Empty diff (not found in shadow file)'

    return False, ''


def main():
    mutants = parse_survived_log()
    mutants = parse_mutantes_txt(mutants)

    grouped: dict[tuple[str, str], list] = {}
    redundant_list: list = []
    non_redundant_count = 0
    redundant_count = 0

    for m in mutants:
        red, reason = is_redundant(m)
        if red:
            m['redundant_reason'] = reason
            redundant_list.append(m)
            redundant_count += 1
        else:
            non_redundant_count += 1
            key = (m['class'], m['method'])
            grouped.setdefault(key, []).append(m)

    # Sort groups for stable output
    sorted_keys = sorted(grouped.keys(), key=lambda x: (x[0], x[1]))

    # ── Write analysis report ──────────────────────────────────────────────
    with open('mutant_analysis.md', 'w') as out:
        out.write('# Mutant Hardening Analysis & Grouping\n\n')
        out.write(f'Generated on: {datetime.datetime.now().isoformat()}\n\n')
        out.write(f'- **Total Mutants Analysed**: {len(mutants)}\n')
        out.write(f'- **Non-Redundant Mutants**: {non_redundant_count}\n')
        out.write(f'- **Redundant/Excluded Mutants**: {redundant_count}\n\n')

        out.write('## Summary of Non-Redundant Mutants by Component\n\n')
        out.write('| Class | Method / Function | Count | Target Mutants |\n')
        out.write('| --- | --- | --- | --- |\n')
        for cls, meth in sorted_keys:
            items = grouped[(cls, meth)]
            ids = [i['id'] for i in items]
            out.write(f'| {cls} | {meth} | {len(items)} | {", ".join(ids)} |\n')

        out.write('\n## Detail of Non-Redundant Mutants\n\n')
        for cls, meth in sorted_keys:
            out.write(f'### {cls}.{meth}\n\n')
            for m in grouped[(cls, meth)]:
                out.write(f'#### Mutant ID: {m["id"]}\n')
                out.write(f'> target: `{m["target"]}`\n\n')
                out.write('```diff\n')
                # Strip ANSI escape sequences for readability
                clean_diff = re.sub(r'\033\[\d+m', '', m['diff'])
                out.write(clean_diff)
                out.write('```\n\n')

        out.write('## Excluded / Redundant Mutants\n\n')
        out.write('| ID | Class | Method | Reason |\n')
        out.write('| --- | --- | --- | --- |\n')
        for m in redundant_list:
            out.write(f'| {m["id"]} | {m["class"]} | {m["method"]} | {m["redundant_reason"]} |\n')

    # ── Write filtered mutants file ────────────────────────────────────────
    with open('mutantes_filtrados.txt', 'w') as f_out:
        for cls, meth in sorted_keys:
            for m in grouped[(cls, meth)]:
                f_out.write(f'----\n# Mutante ID: {m["id"]} ({cls}.{meth})\n')
                f_out.write(f'# TARGET: {m["target"]}\n')
                clean_diff = re.sub(r'\033\[\d+m', '', m['diff'])
                f_out.write(clean_diff)

    print(f"Analysis: {non_redundant_count} non-redundant, {redundant_count} redundant.")
    print("→ mutant_analysis.md")
    print("→ mutantes_filtrados.txt")


if __name__ == '__main__':
    main()
