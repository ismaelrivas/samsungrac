#!/usr/bin/env bash
# =============================================================================
# mutmut_run.sh — Pipeline completo de mutation testing para climate_ip
# =============================================================================
# USO DESDE EL HOST:
#   devcontainer exec --workspace-folder /home/cogollo/ha_data \
#     bash custom_components/climate_ip/scripts/mutmut_run.sh [TARGET_FILE]
#
# USO DENTRO DEL DEVCONTAINER:
#   bash custom_components/climate_ip/scripts/mutmut_run.sh [TARGET_FILE]
#
# EJEMPLOS:
#   .../mutmut_run.sh custom_components/climate_ip/token_acquirer.py
#   .../mutmut_run.sh custom_components/climate_ip/config_flow.py
# =============================================================================

set -euo pipefail

# Iniciar cronómetro del pipeline
START_TIME=${SECONDS}

# ── 1. Determinar directorio raíz del workspace ──────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

if [[ ! -f "${WORKSPACE_ROOT}/setup.cfg" ]]; then
    echo "❌ ERROR: No se encontró setup.cfg en ${WORKSPACE_ROOT}"
    echo "   Asegúrate de que el script está en custom_components/climate_ip/scripts/"
    exit 1
fi

cd "${WORKSPACE_ROOT}"
echo "✅ Directorio de trabajo: $(pwd)"

# ── 2. Forzar PYTHONPATH siempre ─────────────────────────────────────────────
export PYTHONPATH="${WORKSPACE_ROOT}:${WORKSPACE_ROOT}/mutmut_antigravity/src"
echo "✅ PYTHONPATH=${PYTHONPATH}"

PYTHON_BIN="/workspaces/ha_data/.dev-tools/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(which python3)"
fi
echo "✅ PYTHON_BIN=${PYTHON_BIN}"

# ── 3. Verificar importaciones ───────────────────────────────────────────────
echo ""
echo "🔍 Verificando importaciones..."
if ! "${PYTHON_BIN}" -c "import custom_components.climate_ip.config_flow" 2>/dev/null; then
    echo "❌ ERROR CRÍTICO: Python no puede importar custom_components.climate_ip.config_flow"
    echo "   PYTHONPATH actual: ${PYTHONPATH}"
    echo "   PYTHON_BIN actual: ${PYTHON_BIN}"
    exit 1
fi
echo "✅ Importaciones OK"

# ── 6. Determinar fichero/módulo objetivo (--source) ─────────────────────────
# Si no se pasa parámetro $1, usa config_flow.py por defecto
TARGET_FILE="${1:-custom_components/climate_ip/config_flow.py}"

[[ $# -gt 0 ]] && shift 1

if [[ ! -e "${WORKSPACE_ROOT}/${TARGET_FILE}" ]]; then
    echo "❌ ERROR: Objetivo no encontrado: ${WORKSPACE_ROOT}/${TARGET_FILE}"
    exit 1
fi
echo ""
echo "🎯 Objetivo para mutmut (--source): ${TARGET_FILE}"

# ── 7. Limpiar estado anterior ────────────────────────────────────────────────
echo ""
echo "🧹 Limpiando artefactos anteriores..."
rm -rf mutants/ .mutmut-cache .coverage custom_components/climate_ip/.coverage \
       mutmut_processed.txt survived_latest.log mutantes.txt mutantes_filtrados.txt \
       mutant_analysis.md
mkdir -p mutants/custom_components/climate_ip/tests
PYTHONPATH=. "${PYTHON_BIN}" -m mutmut reset
echo "✅ Limpieza completa"

# ── 8. Proteger el .git anidado ───────────────────────────────────────────────
GIT_BACKUP="${WORKSPACE_ROOT}/.climate_ip_git_backup"
if [[ -d "custom_components/climate_ip/.git" ]]; then
    rm -rf "${GIT_BACKUP}"
    mv custom_components/climate_ip/.git "${GIT_BACKUP}"
    echo "✅ .git anidado protegido en ${GIT_BACKUP}"
fi

restore_git() {
    trap '' INT TERM
    if [[ -d "${GIT_BACKUP}" ]]; then
        mv "${GIT_BACKUP}" custom_components/climate_ip/.git 2>/dev/null || true
        echo "✅ .git anidado restaurado"
    fi
}
cleanup_on_interrupt() {
    trap '' INT TERM EXIT ERR
    echo -e "\n\n 🛑 \033[31m[!] Abortado (SIGINT capturado en Bash).\033[0m"
    restore_git
    pkill -KILL -P $$ 2>/dev/null || true
    exit 130
}
trap restore_git EXIT ERR
trap cleanup_on_interrupt INT TERM

# ── 9. Ejecutar mutmut ────────────────────────────────────────────────────────
echo ""
echo "☢️  Iniciando mutmut run sobre: ${TARGET_FILE}"

# Corregido: PYTHONPATH aditivo y uso de "${TARGET_FILE}" en --source
OUTPUT_FILE="mutant_analysis.json"
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
    if [[ "${args[i]}" == "--output" ]]; then
        OUTPUT_FILE="${args[i+1]}"
    elif [[ "${args[i]}" == --output=* ]]; then
        OUTPUT_FILE="${args[i]#*=}"
    fi
done

PYTHONPATH="${WORKSPACE_ROOT}/mutants:${PYTHONPATH}" \
"${PYTHON_BIN}" -W "ignore:This process:DeprecationWarning" \
-m mutmut run --source "${TARGET_FILE}" --exclude-dir scripts "$@" &
MUTMUT_PID=$!
wait $MUTMUT_PID || true

# emite un sonido
alerta 2>/dev/null || true &

ELAPSED_TIME=$(( SECONDS - START_TIME ))
export PIPELINE_DURATION_SECONDS="${ELAPSED_TIME}"
MINUTES=$(( ELAPSED_TIME / 60 ))
SECONDS_REM=$(( ELAPSED_TIME % 60 ))

echo ""
echo "=================================================="
echo "✅ PIPELINE COMPLETADO en ${MINUTES}m ${SECONDS_REM}s (${ELAPSED_TIME}s totales)"
