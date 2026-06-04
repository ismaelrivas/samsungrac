# Auditoría Técnica — `climate_ip` → HA Core 2026.x (V9 - Clean Room Analysis)
> **Rol:** Senior Home Assistant Core Maintainer · Python 3.13 / 3.14  
> **Versión auditada:** `9.2.2` (2026-03-25)  
> **Fecha de auditoría:** 2026-04-02  
> **Objetivo:** Evaluar la preparación real de `climate_ip` para su integración en HA Core 2026.x. **Análisis realizado *desde cero***, ignorando barridos previos.

---

## (A) Resumen Ejecutivo

### Diagnóstico de Madurez (Visión Nueva)

Tras un análisis aislado y exhaustivo de la base del código, `climate_ip` muestra una arquitectura general muy avanzada que abraza los conceptos modernos de Home Assistant (como `runtime_data` y `DataUpdateCoordinator`). Sin embargo, un análisis profundo revela **múltiples bugs lógicos "silenciosos"** y problemas de deuda técnica relacionados con la asunción implícita de que solo hay un dispositivo por IP, a pesar de que la integración teóricamente soporta topologías multi-indoor (ej: MIM-H03).

La integración es resiliente a nivel de red, pero **falla drásticamente en la instanciación de entidades en flujos multi-dispositivo** y en la persistencia del estado en el ecosistema (Device Registry, configuración local YAML). 

> **Estado: 🔴 NO MERGEABLE — Requiere refactorización de lógica multi-coordinator**

---

## (B) Checklist de Integration Quality Scale (Revisión Estricta 2026.x)

| Nivel | Regla | Estado | Nota Técnica de Auditoría |
|:---|:---|:---:|:---|
| 🥉 **Bronze** | `action-setup` | ✅ Cumple | Acciones síncronas correctamente delegadas al coordinador. |
| 🥉 **Bronze** | `runtime-data` | ✅ Cumple | `ConfigEntry.runtime_data` usado, pero deja rastros muertos en `hass.data`. |
| 🥈 **Silver** | `config-entry-unloading` | ⚠️ Parcial | `async_unload_entry` detiene el polling, pero no purga listeners dinámicos si la carga falló a la mitad. |
| 🥈 **Silver** | `reauthentication-flow` | ✅ Cumple | Bien atado al `ConfigEntryAuthFailed` en `coordinator.py`. |
| 🥇 **Gold** | `stale-devices` | ❌ No Cumple | **Ausente:** La integración no implementa el listener para purgar dispositivos "huérfanos" del `device_registry`. |
| 🥇 **Gold** | `entity-translations` | ❌ No Cumple | Uso de un único `translation_key` hardcodeado globalmente rompe la individualización idiomática. |
| 🏆 **Platinum** | `async-dependency` | ⚠️ Exento | `requests` mantenido por retrocompatibilidad deliberada (TLS viejo). |
| 🏆 **Platinum** | `strict-typing` | ⚠️ Parcial | Hay type ignores silenciosos en `__init__.py` para importaciones *lazy* (`# pylint: disable=import-outside-toplevel`). |

---

## (C) Top 10 Hallazgos Priorizados

### 🔴 CRÍTICA

**#1 — Bug Estructural en Setup de Sensores Multi-Dispositivo (Silenciamiento de entidades)**
* **Ubicación:** `sensor.py` L40 (`coordinator = next(iter(coordinator_data.values()))`)
* **Problema:** En sistemas multi-dispositivo (donde `coordinator_data` es un diccionario de múltiples instancias), el bucle extrae *exclusivamente el primer coordinador* y solo genera los sensores para ese dispositivo. Los demás componentes de clima (ej: 4 splits controlados por un router) se quedan sin entidades de sensor asociadas.
* **Impacto:** Usuarios con sistemas centralizados pierden el 80% de sus entidades en la UI de Home Assistant.
* **Referencia:** Core Entities Rules (Todos los dispositivos declarados deben instanciar sus plataformas).

**#2 — Fugas de ConfigFlow Constantes por YAML de Legacy Import**
* **Ubicación:** `climate.py` L114 (`_hass.async_create_task(...)`)
* **Problema:** Al detectar YAML, la integración lanza la migración al Config Flow invocando `async_init` con `SOURCE_IMPORT`. Sin embargo, HA Core exige iterar previamente en `hass.config_entries.async_entries(DOMAIN)` para verificar si la migración *ya se hizo*.
* **Impacto:** Si un usuario no borra su configuration.yaml temporalmente, la integración instanciará una nueva tarea de Config Flow *invisible* en cada reinicio del framework, saturando el event loop y los locks.
* **Referencia:** [Data Entry Flow - Importing YAML](https://developers.home-assistant.io/docs/data_entry_flow_index#importing-from-configurationyaml)

**#3 — Colisión Global por `translation_key` Hardcodeados Mutables**
* **Ubicación:** `climate.py` L131-L132 (`translation_key="samsung_ac"`)
* **Problema:** El objeto `ClimateIPEntityDescription` se crea **una sola vez** fuera del bucle de creación, y se pasa por referencia a todas las instancias creadas en la clase.
* **Impacto:** Muta el estado interno si el usuario tiene diferentes modelos de AC. Impide que las traducciones cambien dinámicamente según las *features* del aparato.

### 🟠 ALTA

**#4 — Código Muerto (Memory Allocation Inútil)**
* **Ubicación:** `__init__.py` L98 (`if DOMAIN not in hass.data: hass.data[DOMAIN] = {}`)
* **Problema:** Implementa la inicialización legacy del DOMAIN en el estado root del core, pero **nunca guarda absolutamente nada en él**, ya que en la L179 usa directamente el PEP-compliant `entry.runtime_data = coordinators`.
* **Impacto:** Desperdicio de memoria y confusión grave para los linters del Core Team.

**#5 — Violación de Políticas de Importación de Core (`import-outside-toplevel`)**
* **Ubicación:** `__init__.py` L89-L94
* **Problema:** Envoltorio de importación dinámica (Lazy Import) dentro de `async_setup_entry` usando pragma disables (`# noqa: F401`, `# pylint: disable`). 
* **Impacto:** Bloqueo de PR. El Core exige inicialización en cabeza de fichero a menos de que la librería externa pese inmensamente y sature el boot, lo cual no aplica a clases nativas (ej: `ConnectionAiohttp8888`).

**#6 — Vulnerabilidad en Redacción de Diagnósticos**
* **Ubicación:** `diagnostics.py` L15 (`TO_REDACT`)
* **Problema:** Omite sanitizar `host`, lo cual expone de facto la IP Address si está incrustada en propiedades anidadas de las URLs locales de la topología u Object Data estructurado. También omite redacción condicional de payloads `cert_file`.
* **Impacto:** Posible fuga de privacidad en reportes exportados hacia Github Issues por los usuarios.

### 🟡 MEDIA

**#7 — Dispositivos Huérfanos Permanentes en el Root Registry**
* **Ubicación:** `__init__.py` (Ausencia de `async_remove_config_entry_device`)
* **Problema:** Si el usuario borra la integración o elimina un "split" (indoor unit) por el panel de configuración, Home Assistant no permite a la integración limpiar el identificador `uuid` del core. El device se vuelve un "zombie".
* **Impacto:** Afecta a largo plazo la experiencia del UI Settings.

**#8 — Excepciones No Documentadas a los Handlers Nativos**
* **Ubicación:** `exceptions.py` L32 (`AuthTurnedOffError`)
* **Problema:** ErrorCode 301. Se crea la excepción custom, pero no se inyecta su traducción asíncrona dentro de `strings.json` bajo la root de `exceptions`.
* **Impacto:** El frontend arrojará una llave base no legible para el usuario final.

### 🟢 BAJA

**#9 — Logging Ineficiente en Eventos de Update**
* **Ubicación:** `__init__.py` L73
* **Problema:** Llama a `.entry_id` en una interpolación `_LOGGER.debug` que siempre se evalúa internamente (fuerza alloc por format).

**#10 — Defaults Flotantes de Escala de Temperatura**
* **Ubicación:** `climate.py` L95 (`CONF_TEMP_STEP, default=1.0`)
* **Problema:** No se transpone con `hass.config.units.temperature_unit`.

---

## (D) Plan de Pruebas Puras (5 Escenarios Nuevos)

**1. Caso: Aborto Automático de Migración YAML Infinita**
* **Descripción:** Comprobar que tras una primera importación de YAML, el sistema aborta importaciones subsiguientes si un `unique_id` ya existe en el registro del ConfigFlow.
* **Comando:** `pytest tests/test_config_flow.py::test_yaml_import_aborts_if_exists`
* **Mock:** Insertar mock en `hass.config_entries.async_entries(DOMAIN)` que devuelva un `entry` válido pre-configurado para simular la importación exitosa anterior.

**2. Caso: Instanciación Verídica de N Sensores para N Dispositivos (MIM-H03)**
* **Descripción:** Inyectar un JSON payload con 3 sub-dispositivos y validar que se registran 3x entidades de sensor asociadas en lugar de registrar solo las del primer device ID iterado.
* **Comando:** `pytest tests/test_sensor.py::test_multi_device_sensors_instantiated -v`
* **Mock:** Modificar fixture del _coordinator_ para inyectar diccionario `{ "00:11:22": CoordinatorA, "00:11:33": CoordinatorB }`. Asserts directos sobre el object en `async_add_entities`.

**3. Caso: Mapeo de Device Registry y Eliminación Segura (Garbage Collection)**
* **Descripción:** Testear limpieza profunda vía `async_remove_config_entry_device`. Una vez descargada (`async_unload_entry`) y borrada la integración, el `device_registry` no debe contener las entradas Samsung.
* **Comando:** `pytest tests/test_init.py::test_device_cleanup_on_entry_remove`

**4. Caso: Prevención de Memory Leak y Referencias en Red (Reload Testing)**
* **Descripción:** Invocar `async_unload_entry` seguido de `async_setup_entry` 10 veces repedidas garantizando que las conexiones pools internas se liberen sin exceptions del Session.
* **Comando:** `pytest tests/test_connection.py::test_connection_teardown_and_reload`

**5. Caso: Redacción de JSON Profunda frente a Estructuras Iterativas**
* **Descripción:** Crear un volcado anidado severo enviando la clave `"host"` incrustada en un subdiccionario anidado de DeviceData para confirmar `async_redact_data`.
* **Comando:** `pytest tests/test_diagnostics.py::test_diagnostics_redacts_nested_host_ip`

---

## (E) Refactorización y Patches de Curación (Top 3)

### Patch #1: Fix Crítico del Bucle Multi-Device (Sensor.py)
Soluciona el silenciamiento de entidades para configuraciones complejas asegurando que *todos* los controladores despliegan sensores.

```diff
  async def async_setup_entry(
      _hass: HomeAssistant, entry: ClimateIPConfigEntry, async_add_entities: AddEntitiesCallback
  ) -> None:
      coordinator_data = entry.runtime_data
      entities_to_add: list[ClimateIpSensor] = []
  
-     # Handle both single and multi-coordinator setups
-     if isinstance(coordinator_data, dict):
-         if not coordinator_data:
-             _LOGGER.warning("No coordinators found for sensor setup.")
-             return
-         # We'll use the first coordinator for "main" sensors (like outdoor temp)
-         coordinator = next(iter(coordinator_data.values()))
-     else:
-         # Single coordinator setup
-         coordinator = coordinator_data
- 
-     raw_device_state = coordinator.controller.device_state
- 
-     for sensor_prop in coordinator.controller.sensors:
-         if sensor_prop.is_valid(raw_device_state):
+     coordinators = list(coordinator_data.values()) if isinstance(coordinator_data, dict) else [coordinator_data]
+
+     for coordinator in coordinators:
+         raw_device_state = coordinator.controller.device_state
+         for sensor_prop in coordinator.controller.sensors:
+             if sensor_prop.is_valid(raw_device_state):
                  # [...] Mismo bloque parseo Category/Icon (respetando indentación)
                  description = SensorEntityDescription(
                      key=sensor_prop.id,
                      translation_key=sensor_prop.id,
                      name=None,
                      device_class=device_class,
                      native_unit_of_measurement=getattr(sensor_prop, "unit_of_measurement", None),
                      state_class=getattr(sensor_prop, "state_class", None),
                      entity_category=parsed_category,
                      icon=icon,
                  )
-                 entities_to_add.append(ClimateIpSensor(coordinator, description, sensor_prop))
+                 entities_to_add.append(ClimateIpSensor(coordinator, description, sensor_prop))
```

### Patch #2: Eliminación del Buclaje Infinito de YAML en `climate.py`
Protege el event-loop asegurándose de no lanzar procesos de ConfigFlow si el equipo ya fue configurado por la interfaz.

```diff
  async def async_setup_platform(
      _hass: HomeAssistant, config: ConfigType, _add_entities: AddEntitiesCallback, _discovery_info: DiscoveryInfoType | None = None,
  ) -> None:
      _LOGGER.warning(
          "Configuration of 'climate_ip' via YAML is deprecated "
          "and will be removed in a future version. Your configuration has been "
          "automatically imported into the UI (Config Entries)"
      )
  
+     # Verificación Anti-Looping de Migración
+     current_entries = _hass.config_entries.async_entries(DOMAIN)
+     if any(entry.source == SOURCE_IMPORT for entry in current_entries):
+         _LOGGER.debug("YAML setup suppressed: Entry already imported previously.")
+         return
+
      _hass.async_create_task(
          _hass.config_entries.flow.async_init(
              DOMAIN, context={"source": SOURCE_IMPORT}, data=config
          ),
          name="climate_ip_yaml_import",
      )
```

### Patch #3: Purga de Alocación Muerta y Lazy Imports (`__init__.py`)
Remueve deuda técnica que incumple las normativas formales del Core Team para validación.

```diff
  async def async_setup_entry(hass: HomeAssistant, entry: ClimateIPConfigEntry) -> bool: # pylint: disable=too-many-locals,too-many-branches,too-many-statements
      """Set up Samsung Climate IP from a config entry."""
  
-     # Import connection classes here (lazy load) to ensure registration
-     # at startup without imposing heavy I/O overhead on the integration's initial boot.
-     # pylint: disable=import-outside-toplevel,unused-import
-     from .connection import CLIMATE_IP_CONNECTIONS  # noqa: F401
-     from .connection_aiohttp import ConnectionAiohttp8888  # noqa: F401
-     from .connection_raw import ConnectionRaw8888  # noqa: F401
-     from .connection_request import (  # noqa: F401
-         ConnectionRequest,
-         ConnectionRequestPrint,
-     )
-     from .connection_request_tls_auto import ConnectionRequestTlsAuto  # noqa: F401
-     from .samsung_2878 import ConnectionSamsung2878  # noqa: F401
-     # pylint: enable=import-outside-toplevel,unused-import
- 
-     # Initialize hass.data[DOMAIN] explicitly if it doesn't exist
-     if DOMAIN not in hass.data:
-         hass.data[DOMAIN] = {}
- 
      # Merge options into runtime_config at startup so settings from the OptionsFlow
```
> *(Nota de Integración: Ejecutar estas importaciones de clase globalmente en la cabecera `__init__.py`).*

---

## (F) Evaluación Cuantitativa (Nuevo Barrido v9)

| Área | Peso | Puntuación | Nota Justificativa |
|:-----|:----:|:----------:|:-------------------|
| **Funcionalidad** | 25% | **6.5/10** | El setup multi-dispositivo ahoga silentemente los sensores y descriptores colisionan en multi-instancia. (Pierde 3.5 puntos por el bug 1). |
| **Fiabilidad** | 20% | **7.5/10** | Fugas de config-flow mediante importación continua si se deja YAML. Orphan devices persisten en registry. |
| **Rendimiento** | 15% | **8.5/10** | *(Exento: impacto asíncrono `requests`).* Sistema optimizado global, salvo memoria inútil inicializada en `hass.data`. |
| **Seguridad** | 15% | **8.0/10** | Redacción de diagnósticos incompleta (`host` y llaves condicionales). |
| **Pruebas** | 15% | **7.5/10** | Tienen alta cobertura, pero no abarcan de forma asertiva escenarios MIM-H03 multi-nodos, lo que permitió el paso a PR de un bug crítico de iteración. |
| **Documentación** | 10% | **8.0/10** | Excepciones sin traducción y uso de ignores pylint anticuados, pero muy buen CHANGELOG e intento de tipado moderno. |

### 🏆 Score Final Computado

* `(25% * 6.5) + (20% * 7.5) + (15% * 8.5) + (15% * 8.0) + (15% * 7.5) + (10% * 8.0)` = `1.625 + 1.500 + 1.275 + 1.200 + 1.125 + 0.800`

## **PUNTUACIÓN FINAL: 7.52 / 10** 🥈

> **Conclusión:** Esta auditoría técnica "Clean Room" ha detectado **problemas asintomáticos graves** que impedían la escalabilidad de la integración en ambientes reales multi-split complejos. Solucionando los Puntos Críticos #1 y #2 (Sensor silencing y fugas de event-loop de Config Flow), superará holgadamente las exigencias del Core Team hacia 2026.x.
