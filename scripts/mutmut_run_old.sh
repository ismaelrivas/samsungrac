#!/usr/bin/env bash
# =============================================================================
# mutmut_run.sh — Pipeline completo de mutation testing para climate_ip
# =============================================================================
# USO DESDE EL HOST:
#   devcontainer exec --workspace-folder /home/cogollo/ha_data \
#     bash custom_components/climate_ip/scripts/mutmut_run.sh [TARGET_FILE]
#
# USO DENTRO DEL DEVCONTAINER (ssh hadata.devpod):
#   cd /workspaces/ha_data/config
#   bash custom_components/climate_ip/scripts/mutmut_run.sh [TARGET_FILE]
#
# Si no se especifica TARGET_FILE, usa config_flow.py por defecto.
# =============================================================================

set -euo pipefail

# Iniciar cronómetro del pipeline
START_TIME=${SECONDS}

# ── 1. Determinar directorio raíz del workspace ──────────────────────────────
# El script puede ser llamado desde cualquier directorio. Buscamos la raíz
# del proyecto detectando la presencia de setup.cfg (marcador inequívoco).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Subir desde scripts/ → climate_ip → custom_components → config (raíz con setup.cfg)
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Verificar que realmente estamos en la raíz correcta
if [[ ! -f "${WORKSPACE_ROOT}/setup.cfg" ]]; then
    echo "❌ ERROR: No se encontró setup.cfg en ${WORKSPACE_ROOT}"
    echo "   Asegúrate de que el script está en custom_components/climate_ip/scripts/"
    exit 1
fi

cd "${WORKSPACE_ROOT}"
echo "✅ Directorio de trabajo: $(pwd)"

# ── 2. Forzar PYTHONPATH siempre, independientemente de quién llame al script ─
export PYTHONPATH="${WORKSPACE_ROOT}"
echo "✅ PYTHONPATH=${PYTHONPATH}"

# ── 3. Verificar que Python puede importar custom_components ──────────────────
echo ""
echo "🔍 Verificando importaciones..."
if ! python -c "import custom_components.climate_ip.config_flow" 2>/dev/null; then
    echo "❌ ERROR CRÍTICO: Python no puede importar custom_components.climate_ip.config_flow"
    echo "   Esto significa que PYTHONPATH no está configurado correctamente."
    echo "   PYTHONPATH actual: ${PYTHONPATH}"
    echo "   Directorio actual: $(pwd)"
    exit 1
fi
echo "✅ Importaciones OK"

# ── 4. Verificar que pytest puede recolectar los tests ────────────────────────
# echo ""
# echo "🔍 Verificando que pytest recolecta los tests correctamente..."
# if ! python -m pytest custom_components/climate_ip/tests/test_config_flow.py \
#         --collect-only \
#         -p no:pytest_homeassistant_custom_component \
#         -o asyncio_mode=auto \
#         --import-mode=prepend \
#         -q \
#         2>&1 | grep -qE "^[0-9]+ test"; then
#     echo "❌ ERROR: pytest no puede recolectar los tests. Verificando..."
#     python -m pytest custom_components/climate_ip/tests/test_config_flow.py \
#         --collect-only \
#         -p no:pytest_homeassistant_custom_component \
#         -o asyncio_mode=auto \
#         --import-mode=prepend \
#         2>&1 | tail -20
#     exit 1
# fi
# echo "✅ pytest recolecta los tests correctamente"

# ── 5. Verificar que la suite de tests pasa en verde ─────────────────────────
# echo ""
# echo "🔍 Ejecutando suite completa de tests (validación previa a mutmut)..."
# TEST_RESULT=$(python  -W "ignore:This process:DeprecationWarning" -m pytest custom_components/climate_ip/tests/ \
#     -p no:pytest_homeassistant_custom_component \
#     -o asyncio_mode=auto \
#     --import-mode=prepend \
#     -q 2>&1 | tail -5)

# if echo "${TEST_RESULT}" | grep -qE "failed|error"; then
#     echo "❌ ERROR: La suite de tests tiene fallos ANTES de ejecutar mutmut."
#     echo "   Mutmut no tiene sentido si los tests base fallan."
#     echo ""
#     python -m pytest custom_components/climate_ip/tests/ \
#         -p no:pytest_homeassistant_custom_component \
#         -o asyncio_mode=auto \
#         --import-mode=prepend \
#         --tb=short 2>&1 | tail -30
#     exit 1
# fi
# echo "✅ Suite de tests: ${TEST_RESULT}"

# ── 6. Determinar fichero objetivo ────────────────────────────────────────────
TARGET_FILE="${1:-custom_components/climate_ip/config_flow.py}"
if [[ ! -f "${WORKSPACE_ROOT}/${TARGET_FILE}" ]]; then
    echo "❌ ERROR: Fichero objetivo no encontrado: ${WORKSPACE_ROOT}/${TARGET_FILE}"
    exit 1
fi
echo ""
echo "🎯 Fichero objetivo: ${TARGET_FILE}"

# ── 7. Limpiar estado anterior ────────────────────────────────────────────────
echo ""
echo "🧹 Limpiando artefactos anteriores..."
rm -rf mutants/ .mutmut-cache .coverage custom_components/climate_ip/.coverage \
       mutmut_processed.txt survived_latest.log mutantes.txt mutantes_filtrados.txt \
       mutant_analysis.md
mkdir -p mutants/custom_components/climate_ip/tests
echo "✅ Limpieza completa"

# ── 8. Proteger el .git anidado (mutmut no funciona con submódulos) ───────────
GIT_BACKUP="/tmp/climate_ip_git_backup_$$"
if [[ -d "custom_components/climate_ip/.git" ]]; then
    mv custom_components/climate_ip/.git "${GIT_BACKUP}"
    echo "✅ .git anidado protegido en ${GIT_BACKUP}"
fi

# Restaurar .git siempre al salir (éxito, error, o Ctrl+C)
restore_git() {
    if [[ -d "${GIT_BACKUP}" ]]; then
        mv "${GIT_BACKUP}" custom_components/climate_ip/.git 2>/dev/null || true
        echo "✅ .git anidado restaurado"
    fi
}
trap restore_git EXIT ERR INT TERM

# ── 9. Ejecutar mutmut ────────────────────────────────────────────────────────
echo ""
echo "☢️  Iniciando mutmut run sobre: ${TARGET_FILE}"
echo "   (La suite completa se ejecuta por cada mutante — proceso largo)"
echo ""

# mutmut usa setup.cfg para su configuración (tests_dir, pytest_add_cli_args, etc.)
# PYTHONPATH ya está exportado, por lo que mutmut lo hereda automáticamente.
#PYTHONPATH="${WORKSPACE_ROOT}/mutants:${PYTHONPATH}" /workspaces/ha_data/.dev-tools/bin/python -m mutmut run || true   # "|| true" para continuar aunque haya mutantes sobrevivientes
mutmut run

echo ""
echo "📊 Resumen mutmut:"
mutmut results 2>/dev/null | tail -5 || true

# ── 10. Extraer supervivientes ────────────────────────────────────────────────
echo ""
echo "🔍 Extrayendo supervivientes..."
mutmut results 2>/dev/null | grep survived > survived_latest.log || true

SURVIVED_COUNT=$(wc -l < survived_latest.log || echo 0)
echo "   → ${SURVIVED_COUNT} mutantes sobrevivieron"

if [[ "${SURVIVED_COUNT}" -eq 0 ]]; then
    echo ""
    echo "🏆 ¡CERO ABSOLUTO ALCANZADO! No hay supervivientes."
    ELAPSED_TIME=$(( SECONDS - START_TIME ))
    export PIPELINE_DURATION_SECONDS="${ELAPSED_TIME}"
    MINUTES=$(( ELAPSED_TIME / 60 ))
    SECONDS_REM=$(( ELAPSED_TIME % 60 ))
    echo "✅ PIPELINE COMPLETADO en ${MINUTES}m ${SECONDS_REM}s (${ELAPSED_TIME}s totales)"

    exit 0
fi

# ── 11. Generar diffs ─────────────────────────────────────────────────────────
echo ""
echo "🔬 Generando diffs (dump_all_fast_optimized)..."
/workspaces/ha_data/.dev-tools/bin/python custom_components/climate_ip/scripts/dump_all_fast_optimized.py \
    survived_latest.log mutantes.txt

# ── 12. Agrupar y deduplicar ──────────────────────────────────────────────────
echo ""
echo "📋 Agrupando y deduplicando mutantes..."

# Calcular tiempo transcurrido y exportarlo para que Python lo lea
ELAPSED_TIME=$(( SECONDS - START_TIME ))
export PIPELINE_DURATION_SECONDS="${ELAPSED_TIME}"

/workspaces/ha_data/.dev-tools/bin/python custom_components/climate_ip/scripts/group_and_deduplicate_json.py \
    mutantes.txt "${TARGET_FILE}"


# Convertir segundos a formato mm:ss en bash para el log final
MINUTES=$(( ELAPSED_TIME / 60 ))
SECONDS_REM=$(( ELAPSED_TIME % 60 ))

echo ""
echo "=================================================="
echo "✅ PIPELINE COMPLETADO en ${MINUTES}m ${SECONDS_REM}s (${ELAPSED_TIME}s totales)"
echo "   Supervivientes totales : ${SURVIVED_COUNT}"
echo "   Análisis detallado     : ${WORKSPACE_ROOT}/mutant_analysis.json"
echo "   Análisis detallado     : /home/cogollo/ha_data/config/mutant_analysis.json"
echo "   Diffs filtrados        : ${WORKSPACE_ROOT}/mutantes_filtrados.txt"
echo "   Diffs filtrados        : /home/cogollo/ha_data/config/mutantes_filtrados.txt"
echo "   Mutantes Raw           : ${WORKSPACE_ROOT}/mutantes.txt"
echo "   Mutantes Raw           : /home/cogollo/ha_data/config/mutantes.txt"
echo "=================================================="
