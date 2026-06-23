#!/usr/bin/env bash
set -e

cd /workspaces/ha_data/config

TARGET_FILE=${1:-custom_components/climate_ip/properties.py}

echo "1. Limpiando TODO (incluyendo .coverage viejo y sandbox)..."
rm -rf mutants/ .mutmut-cache .coverage custom_components/climate_ip/.coverage mutmut_processed.txt

echo "2. Iniciando mutmut run SIN archivo de cobertura en el fichero: $TARGET_FILE"
echo "   (Mutmut correrá la suite completa para cada mutante, lo cual es más lento pero 100% seguro)."
python -m mutmut run
echo "3. Resumen final:"
#mutmut results
