# Changelog

## [9.2.4] - 2026-04-15

### Changed
- **HA Core 2026.x Compliance**: Implemented `is_matching` in `config_flow.py`. This ensures Home Assistant correctly consolidates discovery flows (e.g., DHCP and manual) for the same physical device, preventing duplicate entries.
- **Code Quality Hardening**: Addressed high-visibility Pylint warnings to align with Core maintainer standards:
    - Fixed `W0613` (unused-argument) in `__init__.py` for the device removal callback.
    - Resolved `W0718` (broad-exception-caught) in `helpers.py` by implementing specific handlers for subprocess and networking failures in MAC address resolution.
- **Improved MAC Resolution Resilience**: Added specific handling for systems without the `arp` command and better error logging for IO/Decoding failures during network discovery.

## [9.2.3] - 2026-04-09

### Added
- **Startup Stability (Issue #12)**: Implemented `RestoreEntity` in `climate.py`. The integration now pre-populates the climate entity state from the Home Assistant internal cache during startup, effectively eliminating the "Unavailable" flash while the first network poll is in progress.

### Fixed
- **Malformed HTTP Header Fallback**: Implemented a robust fallback mechanism in `config_flow.py` for devices that send non-standard HTTP headers (Samsung AC specific issue). When `InvalidHeaderError` is detected during discovery, the flow automatically suppresses the error, shuts down the `aiohttp` controller, and retries with the "Robust (raw socket)" engine, ensuring a seamless pairing experience.
- **Config Flow Session Injection**: Fixed a critical `AttributeError` in `YamlController` instantiation during discovery by explicitly passing `hass` and `session` as named arguments. This ensures the controller always has access to the Home Assistant `ClientSession`.
- **Options Flow UI Consistency**: Fixed a bug where the connection method selector in the Options Flow would ignore the current engine saved in `entry.data`. It now correctly prioritizes `options` -> `data` -> `default`, ensuring that a discovery-time engine fallback is correctly reflected in the UI.
- **Event Loop Safety (Blocking I/O)**: Resolved the `Detected blocking call to open` warning in `controller_yaml_config.py` by ensuring all controller instances receive the `hass` object, allowing the integration to use `hass.async_add_executor_job` for synchronous configuration loading.

## [9.2.2] - 2026-04-02

### Changed
- **Reconfiguration Flow (Issue #6)**: Implemented `async_step_reconfigure` in `config_flow.py`, allowing users to update IP address, MAC, token, and certificate of an existing entry without deleting it—meeting the HA Core 2024.11+ Gold requirement.
- **Stale Device Management**: Implemented `async_remove_config_entry_device` in `__init__.py`. This enables Home Assistant to safely garbage-collect "orphaned" split units from the Device Registry if they are removed from the configuration, completing the `stale_devices` Gold requirement.
- **Native Exception Translations**: Integrated `translation_key` into all custom exception classes in `exceptions.py` and added corresponding `"exceptions"` strings. This ensures the Home Assistant frontend displays user-friendly error messages for specific network and authentication failures.
- **Dynamic Temperature Step**: Refactored `target_temp_step` in `climate.py` to default to `None`. This allows Home Assistant to dynamically choose the optimal precision (0.5 for Celsius, 1.0 for Fahrenheit) based on the user's global system settings.
- **Frontend / Icons Migration (Issue #8)**: Created `icons.json` and removed all hardcoded icons from `climate.py` entity properties. All HVAC state and accessory icons are now managed via the standard Home Assistant icon translation system.
- **MIM-H03 Multi-Device State Isolation**: Fixed a critical bug in `properties.py` where multi-device (MIM/Multi-split) setups shared state polling contexts. Injected `device_id` into the render context to ensure total state isolation between indoor units.
- **Memory Optimization (MIM-H03)**: Eliminated lazy imports in `__init__.py` and migrated all state management to the modern `entry.runtime_data` API, reducing the memory footprint for multi-device installations.
- **Diagnostic Privacy (PII)**: Added `host` to the `TO_REDACT` set in `diagnostics.py` to ensure local IP addresses are scrubbed from diagnostic exports.
- **UI UX Smoothing**: Replaced arbitrary `asyncio.sleep(0.001)` hacks in the fan mode picker with a non-blocking `asyncio.sleep(0)` yield, ensuring stable UI remounts when fan modes change without adding artificial latency.
- **Test Suite Completion**: Achieved 159 passing tests, including new coverage for optimistic state reverts, network error recovery, config entry migration paths (v1→v2), and reauthentication triggers.
- **Code Quality Hardening**: Resolved all remaining Pylint violations across the codebase (including C0301, R0801, and E0705), achieving a perfect 10/10 score and Platinum Standard compliance.
- **DRY Refactoring (Issue #10)**: Centralized `EntityCategory` parsing into a shared `parse_entity_category()` helper, eliminating code duplication between the sensor and switch platforms.
- **Event Loop & CPU Optimization (JSON)**: Migrated all connection engines and core logic to use `homeassistant.util.json` and `homeassistant.helpers.json`. This enables `orjson` support, reducing CPU usage during heavy state polling.
- **State Processing Efficiency (Dirty Checks)**:
    - Implemented "Dirty Checks" in the polling controller to skip expensive property decomposition when the raw device state is unchanged.
    - Optimized `climate.py` to skip `async_write_ha_state()` when the entity state and attributes remain identical, significantly reducing UI overhead and state-machine churn.
- **Asynchronous Template Rendering (Phase 3)**:
    - Migrated `samsung_2878.py`, `connection_aiohttp.py`, and `connection_raw.py` to use `homeassistant.helpers.template.Template` and `async_render()`.
    - Fully eliminated synchronous `jinja2` calls from the connection pipeline to ensure zero Event Loop blocking during command execution and handshakes.
- **Base Connection Architecture**: Refactored the `Connection` base class with duck-typing support for `async_render`, ensuring future-proof compatibility for all connection engines.
- **Test Suite Modernization**: Updated the test suite to support `AsyncMock` and `hass` injection for the new Home Assistant template engine, maintaining 100% test coverage.
- **Security Hardening (V12)**: Hardened default TLS cipher suite to `HIGH:!aNULL:!MD5:@SECLEVEL=0` in `helpers.py`. This ensures "Secure by Default" behavior while allowing legacy hardware to explicitly request weaker suites if necessary.
- **Deep PII Masking**: Expanded `TO_REDACT` in `diagnostics.py` to include `DUID` (uppercase variant), `serial_number`, and `serialNumber`, ensuring full compliance with Home Assistant's strict diagnostic privacy standards.
- **Token Sanitization**: Implemented `sanitize_token()` in `config_flow.py` to strip control characters and Jinja2 delimiters from acquired tokens, providing defense-in-depth against template injection attacks before they reach the render engine.


- **Config Flow Reliability**:
    - Sanitized MAC address resolution by enforcing uppercase formatting and automatic colon removal to prevent duplicate entry collisions.
    - Optimized `get_mac_address` resolution: Instead of removing the library, the call was moved to Home Assistant's executor pool (`async_add_executor_job`) to prevent event loop blocking while maintaining seamless automatic discovery.
    - Added `async_remove` to the config flow to ensure background tasks (pairing, discovery) are properly cancelled if the user aborts setup.
    - Refined device identity logic to strictly enforce MAC or UUID matching, removing insecure IP-based fallbacks.
- **Improved Options Flow**:
    - Replaced manual poll interval input with Home Assistant's `cv.time_period` validator for better feedback and support for "hh:mm:ss" formats.
    - Conditionally displays the connection method selector (`aiohttp`, `requests`, `raw`) only for supported modern devices.
- **Latency Optimization**: Bypassed full `YamlController` allocation during pairing validation in the config flow. The connection tester now communicates directly with the low-level `_state_getter`, slashing UI blocking time in half.
- **Network Security**: Hardened the token acquisition TCP listener (port 8889) to bind strictly to Home Assistant's internal network interface instead of `0.0.0.0`.
- **Config Defaults**: Migrated `DEFAULT_CONF_TEMP_UNIT` from a string constant to the canonical `UnitOfTemperature.CELSIUS` Enum.
- **Connection Pipeline**: Restored native concurrent throughput (10 threads/pool size) in `ConnectionRequestBase` to prevent IO bottlenecks.
- **Session Manager**: Migrated dedicated `aiohttp.ClientSession` management to Home Assistant's native `async_get_clientsession(hass)` helper.
- **Legacy Connection Deprecation**: Added active deprecation warnings for the `requests` and `tls_auto` engines.
- **Modernized Actions**: Migrated `services.yaml` to `actions.yaml` as per modern Home Assistant standards (requires HA 2024.8+), updating all internal terminology from "services" to "actions" and removing obsolete `async_register_entity_service` hooks from `climate.py`.
- **Maintainer Attribution**: Updated `manifest.json` codeowners and documentation links to correctly attribute `@ismaelrivas` as the primary maintainer of this AsyncIO hard-fork.
- **Modernized Climate Features**: Refactored `supported_features` in `climate.py` to strictly use the modern Bitwise `ClimateEntityFeature` Enum mapping, replacing manual integer combinations if present.
- **Modernized Entities**: Transitioned `sensor.py` and `switch.py` to use `SensorEntityDescription` and `SwitchEntityDescription` objects for standardized attribute management.
- **Frontend / UX Overhaul**: 
    - Purged explicit `name` hardcoding across secondary entities (`sensor.py`, `switch.py`), fully delegating names to Home Assistant's native translations logic (`en.json`, `es.json`) using `translation_key` strings.
    - Improved `climate.py` precision rendering `PRECISION_HALVES` conditionally based on the user's `CONF_TEMP_STEP` choices.
    - Interpolated dynamic `icon` properties based on the state of `ClimateEntity` (e.g., `mdi:snowflake`, `mdi:fire`, `mdi:fan`).
    - Guarded `ClimateEntityFeature.SWING_MODE` rendering to check whether the controller genuinely populated the internal `swing_modes` list, preventing broken Lovelace toggles in units that don't support oscillation.
- **Generic ConfigEntry & Runtime Data**: Implemented PEP 695 type aliases and migrated data storage from `hass.data` to `entry.runtime_data`, aligning with the latest Home Assistant architectural patterns.
- **Centralized Constants**: Refactored hardcoded mapping strings (e.g., "hvac", "fan") in `properties.py` and `const.py` into centralized, isolated constant definitions.

### Fixed
- **Aiohttp Session Management (CRITICAL)**: Fixed `AttributeError: 'NoneType' object has no attribute 'request'` in `connection_aiohttp.py` occurring when `keep_alive=False`. The connection probe now correctly acquires the session via `_get_session()` instead of accessing `self._session` directly.
- **Resource Management (CRITICAL)**: Implemented mandatory controller shutdown (`async_shutdown`) in `async_step_rest_api` and `async_step_discover_uuid` to ensure temporary connection objects are destroyed immediately.
- **MIM-H03 Discovery**: Fixed a bug where solitary MIM-H03 coordinators were not properly identified.
- **Legacy Regression**: Fixed a regression in the `async_execute` signature for `ConnectionRaw8888`.
- **Connection Manager**: Fixed an unhandled exception crash (`_handle_reconnection`) in `samsung_2878.py`.
- **Thundering Herd Mitigation**: Appended a +/-20% random exponential backoff jitter to the reconnection logic to prevent network stampedes.
- **Event Loop Blocking**: Isolated synchronous XML parsing (`xmltodict.parse` in `samsung_2878.py`) and OS-level operations to the Home Assistant asynchronous executor pool to prevent freezing during heavy payloads.
- **Test Stability**: Purged explicit legacy mock hooks for services from `tests/conftest.py` and successfully migrated the entire test suite `124/124` to Home Assistant's native testing framework (`pytest-homeassistant-custom-component`), eradicating legacy `anyio` event loop conflicts and safely mocking remote socket connections using `pytest_socket`.
- **Race Condition Mutation**: Rewrote dictionary iteration loops in `controller_yaml_state.py` using `list()` copies to prevent runtime crashes during state syncing.
- **Diagnostic Filters**: Relaxed greedy regular expressions in `mask_sensitive_data` to specifically target tokens with assignment operators, avoiding false positive redactions.
- **Logging Anomalies**: Fixed `[NO_ID]` log saturation in early connection phases by implementing recursive ID truncation fallbacks (e.g., `[0f1f1f]`).
- **Pairing Robustness**: Improved error handling during pairing initiation to gracefully catch `TokenAcquisitionError` and `CannotConnect`, preventing noisy tracebacks in Home Assistant logs when connecting to invalid IPs.
- **Dependency Reduction**: Removed the external `getmac` library in favor of a native, asynchronous ARP discovery helper (`async_get_mac_address`) in `helpers.py`. This improves security and aligns with Home Assistant Core requirements for local network discovery.
- **Property Defaulters**: Fixed a bug where offline controllers would publish empty strings instead of `Unavailable`.
- **XML Security Mitigation (CRITICAL)**: Replaced the vulnerable `xmltodict` library with a secure, custom-built `safe_xml_to_dict` helper in `helpers.py`. This implementation uses `defusedxml` to protect against "Billion Laughs" and other XML entity expansion attacks while maintaining 100% dictionary structure compatibility for the Samsung 2878 protocol.
- **Task Deprecation**: Resolved Home Assistant 2024.x deprecation warnings by providing mandatory `name` parameters to internal `async_create_task` calls.
- **Consistent Certificate Loading**: Hardened certificate path handling by using `hass.config.path()` for `ac14k_m.pem`, preventing collisions and improving compatibility with restricted Docker Alpine environments.
- **Native Host-Based Locking**: Eliminated the global `PARALLEL_UPDATES = 1` bottleneck. Replaced it with a native, host-based `asyncio.Lock` registry in `connection.py` that serializes requests per IP while allowing real concurrent updates for independent devices.
- **Atomic Push Updates**: Implemented a transactional "Dry-Run" mechanism for PUSH updates. Merged status is validated against property templates before committing to the baseline, preventing state corruption from malformed payloads and ensuring true `async_set_updated_data` transactionality.
- **Deterministic ARP Discovery**: Eliminated arbitrary `asyncio.sleep(0.2)` from the Config Flow MAC discovery. Optimized the flow to check the ARP cache first and trigger forced updates only when necessary, improving pairing responsiveness.
- **Translation Backend Cleanup**: Purged redundant UI attributes and state translations from `strings.json` and `en.json`. Delegated standard entity naming and preset translations to Home Assistant's native frontend logic, reducing maintenance debt.
- **XML Security Hardening**: Added regression tests to `test_samsung_2878.py` to ensure Billion Laughs (XML expansion) attacks are rejected via `defusedxml`, preventing memory exhaustion from malicious local network payloads.
- **Improved Network Resilience**: Implemented `test_coordinator_handles_503_transient_smartthings` to verify that transient cloud API timeouts (503 Gateway Timeout) are handled gracefully. The coordinator now reliably uses its optimistic status cache for up to 3 consecutive failures before marking entities as unavailable.
- **Automated Re-authentication Trigger**: Verified via `test_smartthings_token_reauth_triggers_flow` that expired SmartThings API tokens (401 Unauthorized) correctly raise `ConfigEntryAuthFailed`, automatically triggering the Home Assistant re-authentication flow to prompt the user for a new token.
- **ARP Discovery Resilience**: Added `test_mac_arp_miss_samsung_devices` to verify that the configuration flow gracefully handles failures in automatic MAC discovery (e.g., due to firewalls). The flow now correctly prompts for manual entry instead of aborting when ARP resolution fails.
- **Optimistic Reversion (Flicker Protection)**: Implemented `test_auto_mode_correction_revert` to ensure that entities correctly reconcile their state with the device's true hardware status after an optimistic update. If a predicted state is contradicted by a subsequent device update, the entity now reverts asynchronously without causing UI flicker loops or deadlocks.

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
