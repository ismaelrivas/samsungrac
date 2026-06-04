# Plan de Implementación Eficiente: Resolución Auditoría 2026.4

Para **ahorrar tokens** y ser extremadamente eficientes, aplicaremos los cambios mediante herramientas de reemplazo de contenido por bloques (`replace_file_content`) en lugar de reescribir archivos enteros. Los cambios se dividen en 3 fases agrupadas por tipo:

## Fase 1: Metadatos y Limpieza (Bajo impacto, alta prioridad)
1. **`manifest.json`**:
   - Reemplazar `"quality_scale": "gold"` por `"quality_scale": "platinum"`.
   - Reemplazar `"homeassistant": "2024.5.0"` por `"homeassistant": "2024.11.0"`.
2. **Archivos Basura**:
   - Ejecutar comando de terminal para eliminar `config_flow.py.old`.

## Fase 2: Fixes Lógicos en Python (Prioridad Alta y Baja)
1. **`tests/test_resilience_2026.py`**:
   - Corregir el falso positivo en la aserción de timeout. Reemplazar `assert coordinator.data == {"power": "On"}` por `assert isinstance(coordinator.data, ClimateIPDeviceState)` y añadir el import necesario.
2. **`switch.py`**:
   - Modificar la propiedad `available` para que dependa exclusivamente de `self.coordinator.last_update_success` y no de `self._controller.available`.
3. **`climate.py`**:
   - Reemplazar el obsoleto `self.async_schedule_update_ha_state(force_refresh=True)` por la llamada estándar al coordinador `await self.coordinator.async_request_refresh()`.

## Fase 3: Mejoras de UX y Traducciones (Prioridad Media)
1. **`config_flow.py`**:
   - Agregar `CONF_TARGET_TEMP_STEP` en el esquema del paso `async_step_init` dentro del `OptionsFlowHandler` para permitir cambiar la precisión en caliente sin reconfigurar.
2. **Traducción de Comentarios**:
   - Buscar (grep) y reemplazar comentarios aislados detectados en español dentro de `switch.py`, `coordinator.py` y `test_resilience_2026.py` al inglés.

> **Nota de Eficiencia:** El uso de librerías síncronas (`requests`) se omite de este plan al considerarse una excepción aprobada.
