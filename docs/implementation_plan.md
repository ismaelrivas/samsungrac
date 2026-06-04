# Plan de Optimización de Rendimiento (Puntuación 10.0)

Este plan detalla las mejoras técnicas necesarias para optimizar el uso de CPU y evitar bloqueos en el bucle de eventos (Event Loop) de Home Assistant, elevando la calificación de rendimiento de la integración `climate_ip` al máximo posible.

## User Review Required

> [!IMPORTANT]
> La migración a `homeassistant.helpers.json` y la delegación al `executor_job` son cambios estructurales que mejoran la estabilidad del sistema bajo carga, pero requieren una validación cuidadosa de los flujos de datos.

## Proposed Changes

### 1. Precompilación de Expresiones Regulares
Centralizar y precompilar los patrones de búsqueda para evitar el overhead de compilación en cada ciclo de polling o autenticación.

#### [MODIFY] [token_acquirer.py](file:///workspaces/ha-climate-ip/config/custom_components/climate_ip/token_acquirer.py)
- Precompilar `RE_ERROR_CODE` y `RE_TOKEN`.

#### [MODIFY] [token_acquirer_8888.py](file:///workspaces/ha-climate-ip/config/custom_components/climate_ip/token_acquirer_8888.py)
- Precompilar `RE_DEVICE_TOKEN`.

#### [MODIFY] [samsung_2878.py](file:///workspaces/ha-climate-ip/config/custom_components/climate_ip/samsung_2878.py)
- Precompilar `RE_ERROR_CODE`.

#### [MODIFY] [helpers.py](file:///workspaces/ha-climate-ip/config/custom_components/climate_ip/helpers.py)
- Precompilar `RE_MAC_ADDRESS`.

---

### 2. Delegación de Parseo Pesado al Executor
Mover el procesamiento de XML y JSON masivos fuera del Event Loop principal.

#### [MODIFY] [helpers.py](file:///workspaces/ha-climate-ip/config/custom_components/climate_ip/helpers.py)
- Refactorizar `xml_to_dict` para usar `hass.async_add_executor_job` cuando se invoque desde un contexto asíncrono.

---

### 3. Migración a Helpers de JSON de Home Assistant
Sustituir el módulo `json` estándar por las versiones optimizadas de Home Assistant que utilizan `orjson` internamente.

#### [MODIFY] Archivos: `controller_yaml_polling.py`, `connection_request.py`, `connection_raw.py`, `token_acquirer_8888.py`, `protocol_8888.py`, `samsung_2878.py`, `connection_aiohttp.py`
- Reemplazar `import json` por `from homeassistant.helpers.json import json_loads, json_dumps`.
- Actualizar llamadas a `json.loads` y `json.dumps`.

---

### 4. Optimización de Estado y "Dirty Checks"
Evitar recálculos innecesarios de las propiedades de las entidades si el estado del dispositivo no ha cambiado.

#### [MODIFY] [controller_yaml_polling.py](file:///workspaces/ha-climate-ip/config/custom_components/climate_ip/controller_yaml_polling.py)
- **Copia Profunda**: Reemplazar el patrón `json.loads(json.dumps(x))` por `copy.deepcopy(x)`.
- **Short-circuit de actualización**: En `async_update_properties_from_state`, comparar el nuevo `full_device_state` con el anterior. Si son idénticos y no hay actualizaciones pendientes (`_pending_updates`), omitir la actualización intensiva de las ~70 sub-propiedades.

---

### 5. Optimización de Templates Jinja2
Uso de renders asíncronos cuando sea posible para evitar bloqueos en operaciones de red que dependen de plantillas.

#### [MODIFY] Motores de Conexión
- Revisar si el renderizado de `rendered_template` puede ser optimizado mediante `template.async_render()` si ya se dispone del objeto `Template` de Home Assistant.

## Open Questions

- ¿Hay algún dispositivo Samsung específico que envíe payloads XML de más de 100KB? (Esto justificaría aún más la delegación al executor).
- ¿Prefieres mantener `copy.deepcopy` o usar el patrón de JSON optimized de HA para las copias? (Deepcopy suele ser más rápido para objetos Python puros).

## Verification Plan

### Automated Tests
- Ejecutar la suite completa de `pytest` (159 tests) para asegurar que las optimizaciones no rompen la lógica de negocio.
- Verificar logs de Home Assistant en busca de avisos de "Blocking call in event loop" relacionados con XML/JSON.

### Manual Verification
- Monitorear el uso de CPU del contenedor `hass` durante un ciclo de polling intenso.
- Validar que la respuesta de la UI (cambio de iconos y estados) sigue siendo inmediata tras las optimizaciones.
