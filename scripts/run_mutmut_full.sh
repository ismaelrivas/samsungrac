#!/usr/bin/env bash
# Full Mutmut pipeline for climate_ip integration
# -------------------------------------------------
# 1. Clean previous mutmut cache and run a fresh mutation test suite
# -------------------------------------------------
cd /workspaces/ha_data/config && ./run_mutmut_clean.sh

# 2. Show raw mutmut results (for debugging)
# -------------------------------------------------
cd /workspaces/ha_data/config && python -m mutmut results

# 3. Count surviving mutants
# -------------------------------------------------
cd /workspaces/ha_data/config && python -m mutmut results | grep survived | wc -l

# 4. Save survived mutant identifiers to a log file
# -------------------------------------------------
cd /workspaces/ha_data/config && mutmut results | grep survived > survived_latest.log

# 5. Dump all mutant diffs to a plain‑text file
# -------------------------------------------------
cd /workspaces/ha_data/config && python custom_components/climate_ip/scripts/dump_all_fast_optimized.py survived_latest.log mutantes.txt

# 6. Quick sanity check – view first 20 lines of the diff dump
# -------------------------------------------------
head -n 20 /workspaces/ha_data/config/mutantes.txt

# 7. Group, deduplicate and generate the final markdown report
# -------------------------------------------------
cd /workspaces/ha_data/config && python custom_components/climate_ip/scripts/group_and_deduplicate.py

# 8. Verify the report header (includes timestamp)
# -------------------------------------------------
head -n 10 /workspaces/ha_data/config/mutant_analysis.md

# End of pipeline
