#!/bin/bash
# Script para arrancar HA en segundo plano de forma persistente
# Determinar el directorio del script de forma robusta
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
CONFIG_DIR="$SCRIPT_DIR"

echo "Preparando arranque de Home Assistant en $CONFIG_DIR..."

# Configurar variables de entorno necesarias
export PYTHONPATH="$CONFIG_DIR"

# Localizar binario de hass
HASS_BIN=$(command -v hass)
if [ -z "$HASS_BIN" ]; then
    # Intentar rutas comunes si no está en PATH
    PATHS=(
        "/home/vscode/.local/bin/hass"
        "/usr/local/bin/hass"
        "/usr/bin/hass"
        "$HOME/.local/bin/hass"
    )
    for p in "${PATHS[@]}"; do
        if [ -f "$p" ]; then
            HASS_BIN="$p"
            break
        fi
    done
fi

if [ -z "$HASS_BIN" ]; then
    echo "ERROR: No se encontró el binario 'hass'. Asegúrate de que está instalado."
    exit 1
fi

echo "Usando binario: $HASS_BIN"

# Limpiar posibles bloqueos previos y archivos temporales
rm -f "$CONFIG_DIR/.ha_run.lock"
rm -f "$CONFIG_DIR/ha.pid"

# Cambiar al directorio de configuración
cd "$CONFIG_DIR"

# Lanzar Home Assistant y desvincularlo totalmente
# Se usa nohup y setsid para asegurar que el proceso sobreviva al cierre de la sesión
nohup setsid "$HASS_BIN" --config "$CONFIG_DIR" > "$CONFIG_DIR/ha_launch.log" 2>&1 &

# Esperar un momento para verificar el arranque
sleep 2
HASS_PID=$(pgrep -f "$HASS_BIN --config $CONFIG_DIR")
if [ -n "$HASS_PID" ]; then
    echo "$HASS_PID" > "$CONFIG_DIR/ha.pid"
    echo "Home Assistant lanzado correctamente con PID $HASS_PID"
else
    echo "Home Assistant lanzado (verificar ha_launch.log para estado)"
fi
