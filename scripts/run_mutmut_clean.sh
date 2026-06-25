#!/usr/bin/env bash
# Script para limpiar todas las cachés y ejecutar mutmut limpio
set -e

echo "Limpiando cachés de Python (__pycache__)..."
find custom_components/climate_ip/ -type d -name "__pycache__" -exec rm -rf {} +

echo "Limpiando cachés de pytest (.pytest_cache)..."
find custom_components/climate_ip/ -type d -name ".pytest_cache" -exec rm -rf {} +

echo "Limpiando base de datos y carpeta de mutantes de mutmut..."
rm -rf mutants/ .mutmut-cache

echo "¡Limpieza completada! Iniciando mutmut run..."
python -m mutmut run
