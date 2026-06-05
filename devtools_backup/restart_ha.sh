#!/bin/bash
# Script para reiniciar Home Assistant
# Determinar el directorio del script de forma robusta
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
CONFIG_DIR="$SCRIPT_DIR"

echo "DEBUG: SCRIPT_DIR = $SCRIPT_DIR"
echo "DEBUG: CONFIG_DIR = $CONFIG_DIR"

# --- DETECCIÓN DE ENTORNO ---
# Si NO estamos en el contenedor (no existe /.dockerenv) e intentamos ejecutar esto en el host
if [ ! -f "/.dockerenv" ] && command -v devcontainer &> /dev/null; then
    echo "Detectado ejecución en el host. Arrancando el devcontainer si está apagado..."
    WORKSPACE_DIR="$(dirname "$SCRIPT_DIR")"
    devcontainer up --workspace-folder "$WORKSPACE_DIR" >/dev/null 2>&1
    
    echo "Re-lanzando dentro del devcontainer..."
    # Usar ruta relativa al workspace dentro del contenedor
    devcontainer exec --workspace-folder "$WORKSPACE_DIR" bash -c "cd /workspaces/ha_data && bash config/restart_ha.sh"
    exit $?
fi

echo "--- Reiniciando Home Assistant ---"

# --- REINICIO POR API ---
echo "Solicitando reinicio a la API de Home Assistant..."

ENV_FILE="$CONFIG_DIR/.env"

# 1. Verificar si el archivo de secretos existe
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: Archivo $ENV_FILE no encontrado. Imposible autenticar con la API."
    exit 1
fi

# 2. Cargar las variables del archivo
source "$ENV_FILE"

# 3. Verificar que la variable no esté vacía
if [ -z "$HA_BEARER_TOKEN" ]; then
    echo "ERROR: La variable HA_BEARER_TOKEN está vacía o no definida en el .env."
    exit 1
fi

# 4. Ejecutar la llamada a la API con captura del código HTTP
HTTP_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Authorization: Bearer $HA_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8123/api/services/homeassistant/restart)

# 5. Evaluar la respuesta del servidor
if [ "$HTTP_RESPONSE" -eq 200 ]; then
    echo "Reinicio de Home Assistant solicitado con éxito (HTTP 200)."
else
    echo "ERROR: La API rechazó la solicitud. Código HTTP: $HTTP_RESPONSE"
    echo "Ejecutando SIGTERM como plan de contingencia..."
    pkill -SIGTERM -f hass 2>/dev/null
fi

# 2. Bucle de espera estricto
# Espera a que el proceso desaparezca de la tabla de procesos antes de arrancar
echo "Esperando a que el Event Loop se vacíe y el proceso termine..."
while pgrep -f hass > /dev/null; do
    sleep 1
done

echo "Proceso finalizado y puertos liberados."

# 3. Arranque en frío
echo "Iniciando Home Assistant..."
"$SCRIPT_DIR/start_ha.sh"