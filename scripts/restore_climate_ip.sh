#!/usr/bin/env bash
set -euo pipefail

# Configuración de rutas
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORIGEN_DIR="${BASE_DIR}/custom_components"
COPIAS_DIR="${BASE_DIR}/copias"

# Recopilar solo carpetas de backup y ordenarlas por nombre (descendente)
mapfile -t BACKUPS < <(
  for d in "${COPIAS_DIR}"/*_climate_ip; do
    [[ -d "$d" ]] && printf '%s\n' "$d"
  done | sort -r
)

# Verificar que haya al menos un backup
if (( ${#BACKUPS[@]} == 0 )); then
  echo "Error: no se encontró ningún backup en ${COPIAS_DIR}"
  exit 1
fi

# Mostrar menú numerado de backups
echo "Backups disponibles (más reciente primero):"
for i in "${!BACKUPS[@]}"; do
  printf "  %2d) %s\n" "$((i+1))" "${BACKUPS[i]}"
done

# Leer selección del usuario
read -rp "Seleccione un backup [1-${#BACKUPS[@]}]: " SELEC
if [[ ! $SELEC =~ ^[0-9]+$ ]] || (( SELEC < 1 || SELEC > ${#BACKUPS[@]} )); then
  echo "Selección inválida."
  exit 1
fi

# Ruta del backup elegido
SELECCIONADO="${BACKUPS[$((SELEC-1))]}"

# Confirmación antes de restaurar
read -rp "¿Restaurar solo 'climate_ip' y 'climate_ip_tools' desde '${SELECCIONADO}' en '${ORIGEN_DIR}'? (s/N): " CONF
case "${CONF,,}" in
  s|si|y|yes)
    echo "Iniciando restauración..."
    # Asegurar que existe el directorio padre de ORIGEN_DIR
    mkdir -p "${ORIGEN_DIR}"

    # Restaurar únicamente las carpetas climate_ip y climate_ip_tools.
    # - Las exclusiones específicas evitan restaurar .venv y __pycache__ dentro de climate_ip.
    # - --delete hace que el contenido de las carpetas restauradas quede igual que en el backup.
    rsync -av --prune-empty-dirs --delete \
      --include='climate_ip/' \
      --include='climate_ip/***' \
      --exclude='climate_ip/.venv/***' \
      --exclude='climate_ip/**/__pycache__/***' \
      --include='climate_ip_tools/' \
      --include='climate_ip_tools/***' \
      --exclude='*' \
      "${SELECCIONADO}/" "${ORIGEN_DIR}/"

    echo "Restauración completada en ${ORIGEN_DIR}"
    ;;
  *)
    echo "Operación cancelada."
    exit 0
    ;;
esac
