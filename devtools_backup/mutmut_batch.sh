#!/usr/bin/env bash
# mutmut_batch_pause.sh
set -uo pipefail

LOGFILE="mutmut_batch.log"
PROCESSED_FILE="mutmut_processed.txt"
TMPFILE="$(mktemp)"
# Asegurar la limpieza de todos los archivos temporales generados
trap 'rm -f "$TMPFILE" "${TMPFILE}.new" "${TMPFILE}.batch"' EXIT

: > "$LOGFILE"
touch "$PROCESSED_FILE"

echo "=== $(date --iso-8601=seconds) Inicio" | tee -a "$LOGFILE"

while true; do
  # Obtener todos los ids que terminan en ": survived", limpiar y ordenar
  mutmut results | grep survi | sed 's/: survived$//' | sed 's/^[[:space:]]*//' | sort -u > "$TMPFILE"

  # Excluir los ya procesados
  if [ -s "$PROCESSED_FILE" ]; then
    grep -Fxv -f "$PROCESSED_FILE" "$TMPFILE" > "${TMPFILE}.new" || true
    mv "${TMPFILE}.new" "$TMPFILE"
  fi

  # Tomar los primeros 10
  head -n 12 "$TMPFILE" > "${TMPFILE}.batch"

  if [ ! -s "${TMPFILE}.batch" ]; then
    echo "No hay nuevos supervivientes para procesar." | tee -a "$LOGFILE"
    echo "Fin del script." | tee -a "$LOGFILE"
    exit 0
  fi

  echo "Procesando lote de $(wc -l < "${TMPFILE}.batch") mutantes en PARALELO (máx 5 simultáneos)..." | tee -a "$LOGFILE"

  # Usar xargs para ejecutar hasta 6 procesos mutmut show simultáneamente
  cat "${TMPFILE}.batch" | xargs -P 6 -I {} bash -c '
    output=$(python3 fast_mutmut_show.py "{}" 2>&1)
    echo "----"
    printf "%s\n" "$output"
  ' | tee -a "$LOGFILE"

  # Marcar el lote actual como procesado
  cat "${TMPFILE}.batch" >> "$PROCESSED_FILE"

  # Pausa entre lotes: Enter para continuar, q para salir
  printf "\nPresiona Enter para procesar el siguiente lote, o escribe '\''q'\'' y Enter para salir: "
  read -r answer
  if [ "$answer" = "q" ] || [ "$answer" = "Q" ]; then
    echo "Usuario solicitó salir. Saliendo..." | tee -a "$LOGFILE"
    echo "=== $(date --iso-8601=seconds) Fin" | tee -a "$LOGFILE"
    exit 0
  fi
  clear
  echo "Continuando con el siguiente lote..." | tee -a "$LOGFILE"
done
