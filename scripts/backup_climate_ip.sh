#!/usr/bin/env bash

# Timestamp y rutas
TIMESTAMP="$(date +%Y%m%d_%H%M)"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORIGEN="${BASE_DIR}/custom_components"
DESTINO="${BASE_DIR}/copias/${TIMESTAMP}_climate_ip"

# Crear destino
mkdir -p "${DESTINO}"

# Copiar solo climate_ip y climate_ip_tools,
# excluyendo .venv, __pycache__ y tests/__pycache__ dentro de climate_ip
rsync -av --prune-empty-dirs \
  --include='climate_ip/' \
  --include='climate_ip_tools/' \
  --exclude='climate_ip/.venv/***' \
  --exclude='climate_ip/__pycache__/***' \
  --exclude='climate_ip/.pytest_cache/***' \
  --exclude='climate_ip/tests/__pycache__/***' \
  --include='climate_ip/***' \
  --include='climate_ip_tools/***' \
  --exclude='*' \
  "${ORIGEN}/" "${DESTINO}/"

echo "Backup completado en ${DESTINO}"

