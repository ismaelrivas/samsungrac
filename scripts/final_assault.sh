#!/bin/bash
cd /workspaces/ha_data/config
echo "Ejecutando mutmut ultimate..."
bash custom_components/climate_ip/scripts/run_mutmut_ultimate.sh

echo "Procesando resultados..."
cat mutmut_results_final.txt | grep survived > mutantes_finales_fase8.txt
python3 custom_components/climate_ip/scripts/group_and_deduplicate.py mutantes_finales_fase8.txt custom_components/climate_ip/config_flow.py > mutant_analysis_fase8_summary.md

echo "COMPLETADO. Revisa mutant_analysis_fase8_summary.md y mutant_analysis.md"
