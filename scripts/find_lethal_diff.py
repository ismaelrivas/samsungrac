import json

# 1. Cargar los dos JSON de análisis que me acabas de mostrar
with open("mutant_analysis_fast.json") as f:
    fast_data = json.load(f)

with open("mutant_analysis_old.json") as f:
    old_data = json.load(f)

# 2. Extraer los diffs (textos de mutación) de los supervivientes de FAST
fast_surviving_diffs = set()
for func_list in fast_data["non_redundant_mutants_details"]["SamsungTokenAcquirer"].values():
    for m in func_list:
        # Extraer la línea mutada limpia del diff (+ o -)
        lines = [l.strip() for l in m["diff"].splitlines() if l.startswith("+ ") or l.startswith("- ")]
        fast_surviving_diffs.add("\n".join(lines))

# 3. Extraer los diffs de los supervivientes de OLD
old_surviving_diffs = set()
for func_list in old_data["non_redundant_mutants_details"]["SamsungTokenAcquirer"].values():
    for m in func_list:
        lines = [l.strip() for l in m["diff"].splitlines() if l.startswith("+ ") or l.startswith("- ")]
        old_surviving_diffs.add("\n".join(lines))

# 4. BUSCAR LA ANOMALÍA:
# ¿Qué mutante SOBREVIVIÓ en FAST pero NO SOBREVIVIÓ en OLD? (Es decir, OLD lo mató)
escaped_alive_in_fast = fast_surviving_diffs - old_surviving_diffs

print(f"🎯 Mutantes supervivientes en FAST que OLD mató: {len(escaped_alive_in_fast)}")
for idx, diff in enumerate(escaped_alive_in_fast, 1):
    print(f"\n--- [SOSPECHOSO {idx}] ---")
    print(diff)