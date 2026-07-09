#!/usr/bin/env bash
set -e

cd /workspaces/ha_data/config

TARGET_FILE=${1:-custom_components/climate_ip/properties.py}

echo "1. Limpiando TODO (incluyendo .coverage viejo y sandbox)..."
rm -rf mutants/ .mutmut-cache .coverage custom_components/climate_ip/.coverage mutmut_processed.txt
mkdir -p mutants/custom_components/climate_ip/tests

echo "2. Iniciando mutmut run SIN archivo de cobertura en el fichero: $TARGET_FILE"
echo "   (Mutmut correrá la suite completa para cada mutante, lo cual es más lento pero 100% seguro)."

mv custom_components/climate_ip/.git /tmp/climate_ip_git_backup || true
trap "mv /tmp/climate_ip_git_backup custom_components/climate_ip/.git || true" EXIT ERR INT TERM

PYTHONPATH=. python -m mutmut run || true

echo "3. Resumen final:"
#mutmut results
