#!/bin/bash
cd /workspaces/ha_data/config
echo "1. Ejecutando mutmut run sobre config_flow.py..."
bash custom_components/climate_ip/scripts/run_mutmut_ultimate.sh custom_components/climate_ip/config_flow.py

echo "2. Extrayendo sobrevivientes..."
mutmut results | grep survived > survived_latest.log

echo "3. Generando diffs (dump_all_fast_optimized)..."
python3 custom_components/climate_ip/scripts/dump_all_fast_optimized.py survived_latest.log mutantes.txt

echo "4. Agrupando y deduplicando..."
python3 custom_components/climate_ip/scripts/group_and_deduplicate.py mutantes.txt custom_components/climate_ip/config_flow.py

echo "PIPELINE FASE 8 COMPLETADO!"
