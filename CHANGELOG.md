# Changelog

## [9.2.1] - 2026-03-03

### Changed
- **Core Stability**: Refactored YAML loading mechanism (`controller_yaml_init.py`) to run safely in Home Assistant's thread pool via `hass.async_add_executor_job`, eliminating Event Loop blocking.
- **HA Standards**: Added `strict_typing: true`, `iot_class: local_polling`, and official `"quality_scale": "gold"` to `manifest.json`.
- **Code Harmonization (DRY)**: Refactored `config_flow.py` to consolidate Samsung schema generation into a unified, parametric base helper (`_get_base_samsung_schema`), reducing boilerplate duplication.
- **Log Refinement**: Downgraded state auto-correction and UI flicker notifications to `DEBUG` level to eliminate information noise in the Home Assistant logs.
- **Encapsulation & Architecture (V7 Audit)**: Created robust public APIs (`last_poll_data`, `connection_diagnostics`) in `controller_yaml.py` and replaced all internal private attribute accesses across `diagnostics.py` and `switch.py`.
- **Hygienic Codebase (V7 Audit)**: Performed a full-scope repository purge of development artifacts: deleted persistent `split_controller.py` build script, eradicated milestone scaffolding blocks, relocated nested inline imports, and cleansed internal `[DIAG]` test prints.

### Fixed
- **Socket Memory Leak (CRITICAL)**: Added explicit `wait_closed()` instructions in `connection_raw.py` to prevent File Descriptor exhaustion and RAM leaks on persistent disconnections.
- **Session Resource Leak**: Fixed `aiohttp.ClientSession` memory leak in `__init__.py` by safely awaiting graceful session teardowns during integration unloads.
- **Asymmetric Unload**: Restructured `async_unload_entry` layout (`__init__.py`) to brutally stop `polling` tasks and network loops *before* attempting HA platform teardown, solving teardown race conditions.
- **Exponential Backoff Spam**: Repaired `samsung_2878.py` fallback loops to ensure reconnect delay times properly increment, preventing the integration from spamming unreachable routers.
- **Dynamic Retry Backoff**: Enhanced `properties.py` with a true exponential backoff algorithm (1s to 15s) for asynchronous retries, replacing static delays and improving recovery responsiveness.
- **Config Flow 500 Errors**: Fixed unhandled exceptions (`AuthError`) causing API crashes during AC device pairing by gracefully mapping them to visible UI alerts.
- **Jinja2 High CPU Usage**: Optimized `Template.render()` validation in `properties.py` using per-poll in-memory caching to eliminate redundant CPU evaluation iterations.
- **Deepcopy RAM Spikes**: Replaced expensive `copy.deepcopy` calls in `controller_yaml_state.py` with fast C-level `json.loads(json.dumps())` combinations to optimize optimistic device state construction.
- **Event Loop Blocking**: Rewrote the fallback reconnect loops in `connection_request.py` to remove `time.sleep()`, using a custom `RetryNextAttempt` exception to delegate waits to the `asyncio` event loop.
- **Exception UX**: Migrated custom exceptions to inherit securely from `HomeAssistantError` and properly implemented the native `ConfigEntryNotReady` backoff manager.
- **Diagnostic Entities**: Mapped nested hardware sensors like `Alarms`, `Filter`, and `Energy` directly to Home Assistant's `entity_category: diagnostic` platform standard, purging "magic string" inference logic.
- **Test Determinism**: Refactored `test_integration.py` to replace hardcoded `asyncio.sleep` calls with dynamic `async_timeout` poll loops, ensuring the test suite is stable across different hardware speeds.
- **Strict Typing Fixes**: Injected missing `Dict[str, Any]` type hints in `__init__.py` to satisfy strict MyPy auditing requirements.

## [9.2.0] - 2026-03-02

### Added
- **Config Flow UX (Connection Test)**: Added a mandatory pre-flight connection test step in the configuration flow that validates the IP and Token against the physical AC unit before the integration is created.
- **Config Flow UX (Port Fallback)**: Added seamless auto-detection when pairing. The integration silently falls back to the alternative protocol port and retries if the user selects the wrong port.
- **YAML Hot-Reload Service**: Added a native `climate_ip.reload` service that purges the internal YAML schema cache and applies mapping changes instantly without restarting Home Assistant.
- **Translations**: Added full native localization support for French (`fr.json`) and German (`de.json`). Created a canonical `strings.json` as the source of truth for all UI translations.
- **Ping Gate**: Implemented fast ICMP connectivity pre-checks before TCP reconnections for all devices, bypassing slow socket timeouts when the AC is offline at the network level.
- **HA Repair Issues**: Automatic creation of Home Assistant Repair Issues when a device repeatedly fails to connect. The issue resolves itself upon successful reconnection.
- **Diagnostic Enhancements**: Secured diagnostic exports using an allowlist approach to guarantee sensitive tokens are never exported, and added visibility of the Keep-Alive fallback state.

### Changed
- **Network Ping Optimization**: Replaced crude OS-level `ping` subprocess calls with lightning-fast, native `icmplib.async_ping`. Gracefully falls back to datagram sockets to reduce File Descriptor exhaustion during disconnects.
- **SSL Configuration Persistence**: The integration now permanently saves the last successful SSL configuration (`cert`, `cipher_name`, `verify_mode`) to allow instant reconnection after a Home Assistant restart.
- **TLS Protocol Tolerance**: Made TLS connections more lenient for older Samsung devices that require lower security levels.
- **urllib3 Context**: Scoped the workaround for Samsung's malformed HTTP headers strictly to this integration's requests, preventing cross-contamination with other Home Assistant integrations.
- **Log Refinement & Error Messages**: Improved connection error logs to be human-readable and downgraded expected structural disconnect logs (`Timeout` and `ConnectionError`) to prevent log spam when a device is powered off.
- **Code Refactoring & Modernization**: Significantly refactored `controller_yaml.py`, modernized integration registration syntax (`domain=DOMAIN`), standardized exception handling with `CannotConnect`, and bumped minimum required Home Assistant version to "2024.1.0".

### Fixed
- **Connection Keep-Alive Hang**: Fixed a structural bug where the integration would hang for 10 seconds waiting after the AC finished responding due to malformed headers. The solution safely strips illegal characters and proactively falls back to `Connection: close` on protocol violations.
- **Critical TLS Hang (AC Port 8888/2878)**: Samsung AC firmware hangs indefinitely when receiving a TLS 1.3 Client Hello. Fixed by capping all SSL context creation strictly at `TLSv1_2`.
- **Connection Cleanup Logging**: Fixed a bug where `ConnectionRequest` session cleanup logic would repeatedly log redundant closure messages during garbage collection. 
- **Config Flow Timeout**: Fixed a bug where port 2878 devices would unconditionally time out during connection testing.
- **SSL Context Handling**: Fixed local listener socket configuration to properly handle server-side handshake requests, and resolved Python `ValueError` exceptions caused by conflicting `check_hostname` assignments.
- **Embedded Command Execution**: Fixed nested YAML commands with parameters (like auto power-on) being silently skipped on older devices.
- **Reconnect Jitter**: Added random jitter to exponential backoffs to prevent "thundering herd" reconnects.
- **Task Tracking**: Fixed orphaned background threads during integration unload.
- **Performance & Data Types**: Fixed sensor definitions by converting YAML strings into native `SensorStateClass` enums, resolved fragile template parameter evaluations, and eliminated redundant string searches.

## [9.0.12] - 2026-02-23

### Added
- **Independent Native Temperature Units**: Added two separate configuration options (`Native Current Temperature Unit` and `Native Target Temperature Unit`) accessible from the integration's Options Flow. This allows devices that report temperatures in Fahrenheit to be correctly converted and displayed in the Home Assistant global unit (Celsius or Fahrenheit), independently for current and target temperatures. New constants `CONF_TEMP_NATIVE_CURRENT` and `CONF_TEMP_NATIVE_TARGET` added to `const.py`.

### Fixed
- **Connection Stability**: Fixed a critical bug in `protocol_8888.py` (RAW connection engine) where a missing `Content-Length` header from the AC would cause the raw socket read fallback loop to hang indefinitely, triggering 30-second `Transient connection failure` timeouts in Home Assistant. The read loop now uses an absolute 5.0-second deadline via `asyncio.wait_for` to guarantee execution.
- **Temperature Display**: Fixed a decimal precision bug in the Home Assistant thermostat card where fractional temperatures (e.g. `20.56°C`) were shown instead of integers. Fixed by explicitly rounding in `convert_dev_to_hass` in `properties.py` and overriding `temperature_unit` in `climate.py` to prevent Home Assistant frontend from applying secondary floating-point conversions. Core climate attributes are also filtered from `extra_state_attributes` to prevent raw values silently overwriting the rounded integers.
- **Switch Validation**: Fixed a bug in `controller_yaml.py` where `device_state` passed to switch `validation_template` was incorrectly typed as a `ClimateIPDeviceState` object instead of a raw dictionary, causing `purify` and `auto_clean` switches to always fail validation and not appear in Home Assistant.
- **YAML Config**: Added `validation_template` to all switches in `samsung_2878.yaml` and `samsungrac.yaml` to correctly hide controls not supported by the device.
- **Logs**: Fixed `beep` (and other unsupported switches) triggering spurious state auto-correction warnings by ensuring properties failing validation are skipped during post-update discrepancy checks.
- **Log Cleanup**: Removed verbose `DEBUG` log statements across `switch.py`, `sensor.py`, `samsung_2878.py`, `controller_yaml.py`, and `properties.py` to reduce log noise.

## [9.0.11] - 2026-02-17

### Fixed
- **Connection Stability (CRITICAL)**:
    - Fixed a regression in 9.0.10 where the `device_id` was not being correctly populated for single-device configurations.
    - Ensured `DUID` is explicitly passed to command templates in `properties.py` to prevent empty DUIDs, resolving timeouts for 2878 devices.
- **Sensor Reliability**: Added safe navigation to the `outdoor_temperature` sensor template in `samsung_2878.yaml` to prevent Jinja2 errors ("dict object has no attribute") during initial connection or partial state updates.
- **Connection Robustness**:
    - Fixed a `NoneType` error that could occur when the connection was closed unexpectedly (e.g., device offline), ensuring proper cleanup and reconnection attempts.
    - Handled `InvalidateAccount` response gracefully during handshake (session collision), triggering a clean retry instead of an error log.
- **Native Switches**:
    - Introduced `switch` platform for `purify` and `auto_clean` controls, replacing the deprecated `switch.template` workarounds.
    - Added dedicated `switches` section to `samsung_2878.yaml` and `samsungrac.yaml` for better configuration management.

## [9.0.10] - 2026-02-17

### Added
- **Polling Control**: Added `Enable Polling` option in configuration flow (default: True). Users can now disable periodic status updates to prevent IP bans on sensitive 2878 devices.
- **Connection**: Added support for **Anonymous TLS** connections (Cipher Suite D: `ALL:@SECLEVEL=0`) for devices that do not require a certificate.
- **Emulator**: Added `--no-cert` flag to `emulator_2878.py` to simulate devices requiring Anonymous TLS.
- **Native Switches**: Introduced `switch` platform for `purify` and `auto_clean` controls, replacing the deprecated `switch.template` workarounds.

### Fixed
- **SSL Compatibility**:
    - Prioritized Anonymous Cipher Suite (Suite D) when no certificate is provided, speeding up connection.
    - Fixed `ValueError` when using `ssl.CERT_NONE` by ensuring `server_hostname` is always passed to `asyncio.open_connection`.
- **Config Flow**: Added `Enable Polling` checkbox to Options Flow for existing installations.
- **Coordinator**: Updated coordinator to respect the polling setting, disabling automatic updates if unchecked.
- **Lifecycle Management**: Improved connection cleanup during reloads to prevent "zombie" connections.

## [9.0.9] - 2026-02-12

### Added
- **Sensors**: Added `auto_clean` and `purify` sensors to `samsungrac.yaml` (8888) and `samsung_2878.yaml` (2878) to monitor these states.

### Fixed
- **Token Acquisition**: Replaced `aiohttp` server with a custom Raw TCP server in `token_acquirer_8888.py` to handle devices with malformed headers (missing `Content-Length`).
- **FilterTime Scaling**: Corrected `FilterTime` value in `samsungrac.yaml` (8888) by dividing by 10.
- **Connection Stability**: Implemented TCP Keep-Alive for port 2878 to prevent zombie connections after router reboots.
- **Service Restoration**: Restored `climate_ip.set_property` service to allow control of custom attributes like `purify` and `auto_clean`.

## [9.0.8] - 2026-02-11

### Fixed
- **Outdoor Temperature**: Changed logic for 8888-port devices to subtract 55 from the raw value and use Celsius units, matching the behavior of 2878-port devices.

## [9.0.7] - 2026-02-11

### Added
- **Sensors (8888 Protocol)**:
    - Added native support for `outdoor_temperature` sensor in `samsungrac.yaml` (8888 models).
    - Added `filter_clean_alarm`, `filter_time`, and `filter_alarm_time` sensors.
    - Implemented logic to expose unwrapped device state in `controller_yaml.py` to allow sensor templates to access nested data easily.

### Changed
- **SSL Security**:
    - Updated `samsung_smartthings_hvac.yaml` and `samsung_smartthings_dhw.yaml` to enforce `insecure_ssl: false` and `verify: True` for secure connections to SmartThings Cloud.
- **Internal**:
    - Updated `sensor.py` to use the new exposed device state for validation, fixing the "missing sensor" issue on 8888 devices.

## [9.0.6] - 2026-01-07

### Added
- **Connection Engines**:
    - Implemented `asyncio.Lock` in `connection_aiohttp.py` and `connection_raw.py` to serialize requests and properly share SSL contexts.
    - Added SSL optimizations (`OP_NO_TICKET`, `OP_NO_COMPRESSION`) in `protocol_8888.py` for low-resource devices.
    - Added tolerant header parsing in `connection_request_tls_auto.py`.
- **Config Flow**:
    - Added connection method selector (`aiohttp`, `requests`, `raw`) in `config_flow.py`.
    - Defined explicit device types for SmartThings HVAC and DHW in `const.py`.
- **Sensors**: Added `sensors` property support in `controller_yaml.py`.
- **Logging**: Added verification logs for SSL optimizations.

### Changed
- **Stability**:
    - Introduced a "strike system" in `coordinator.py` and `samsung_2878.py` (max 3 strikes) to handle transient network failures without marking entities unavailable immediately.
    - Added automatic fallback to the Legacy (requests) engine if `InvalidHeaderError` is detected.
- **Properties**:
    - Fixed temperature conversions (~line 173 `properties.py`) by enforcing float parsing and handling units dynamically.
    - Updated `insecure_ssl` handling in SmartThings YAML templates.

### Fixed
- **Outdoor Temperature**: Corrected calculation in `samsung_2878.yaml` (subtracting 55 from raw value) and set unit to Celsius.
