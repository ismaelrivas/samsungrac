#!/usr/bin/env bash

# Configuración de rutas basada en tu entorno de Codespaces
WORKSPACE_ROOT="/workspaces/ha_data"
TARGET_SCRIPT="${WORKSPACE_ROOT}/config/custom_components/climate_ip/scripts/mutmut_run.sh"
TARGET_FILE="custom_components/climate_ip/token_acquirer.py"
TESTS_PATH="custom_components/climate_ip/tests/test_token_acquirer.py"

# Cambiar al directorio de trabajo correcto antes de ejecutar
cd "${WORKSPACE_ROOT}/config" || { echo "❌ No se pudo acceder al directorio de configuración"; exit 1; }

# Tamaños de chunk solicitados para el benchmark
CHUNK_SIZES=(15 20)

echo "=============================================================="
echo "🚀 Iniciando Benchmark de Chunk Sizes para mutmut"
echo "🎯 Archivo objetivo: ${TARGET_FILE}"
echo "=============================================================="

for chunk in "${CHUNK_SIZES[@]}"; do
    echo -e "\n--------------------------------------------------------------"
    echo "⏱️  Ejecutando con --chunk-size ${chunk}..."
    echo "--------------------------------------------------------------"
    
    # Ejecución del script original inyectando el chunk-size correspondiente
    "${TARGET_SCRIPT}" "${TARGET_FILE}" \
        --no-cache \
        --tests-path "${TESTS_PATH}" \
        --workers 0 \
        --exclude-dir scripts \
        --chunk-size "${chunk}"
        
    # Pequeña pausa opcional para permitir que la CPU y el I/O del contenedor se estabilicen
    sleep 3
done

echo -e "\n=============================================================="
echo "✅ Benchmark completado. Revisa la telemetría impresa arriba."
echo "=============================================================="