# TODO

## Future Enhancements
- [ ] **Data-Driven Authentication Flow**: Move the token extraction and pairing logic directly into the YAML configuration files (`samsung_2878.yaml` and `samsungrac.yaml`).
  - Create an `auth_flow` section in the YAML.
  - Define `request_pairing` (initial command to request token).
  - Define `poll_token` (looping command to wait for user to press physical AC button).
  - Define `success_template` to detect when the token is received.
  - Define `extract_template` to extract the token string.
  - Refactor `config_flow.py` to read these YAML properties and execute the pairing process dynamically.
  - *Benefit*: Makes the integration 100% protocol agnostic. Adding support for new AC brands with different pairing processes will only require a new YAML file, without touching Python code.

- [ ] **Migrate to Home Assistant Native Template Engine**: Refactor the integration to use `homeassistant.helpers.template.Template` instead of the bare `jinja2.Template`.
  - Pass the `hass` instance to the classes responsible for evaluating templates (`controller_yaml.py`, `properties.py`, `connection_request.py`).
  - Replace `from jinja2 import Template` with the HA native template engine.
  - *Benefit*: Gives users access to the full suite of Home Assistant Jinja filters (`regex_findall`, `as_timestamp`, `match`, etc.) within the YAML device configurations, adhering to HA best practices.

- [ ] **Data-Driven Optimistic Cascades via YAML (Option B)**: Shift optimistic state cascades (such as toggling `Operation.power` to `"Off"` when `hvac_mode` is set to `"off"`, or `"On"` when set to heating/cooling) from hardcoded Python logic directly into declarative YAML property configurations.
  - **Specification Artifact**: See detailed architectural design and implementation specification in [dynamic_optimistic_cascades_spec.md](file:///home/cogollo/.gemini/antigravity-ide/brain/7183440b-47c1-4c93-8106-21796edf9a10/dynamic_optimistic_cascades_spec.md).
  - **YAML Schema Spec**: Add an `optimistic_cascades` block under property operations in device configuration files (e.g., `samsung_2878.yaml`, `samsungrac.yaml`):
    ```yaml
    operations:
      hvac_mode:
        type: mode
        optimistic_cascades:
          - target_node: "Operation.power"
            value_map:
              off: "Off"
              default: "On"
    ```
  - **Base Class Ingestion (`properties.py`)**:
    - Update `DeviceProperty.__init__` to initialize `self._config: dict[str, Any] = {}`.
    - Update `DeviceProperty.load_from_yaml(node)` to retain the YAML block: `self._config = node if node is not None else {}`.
    - Implement `apply_optimistic_cascades(self, state: dict[str, Any], value: Any, dev_val: Any) -> None` on `DeviceProperty` (or `DeviceOperation`).
  - **Dynamic State Traversal & Mutation**:
    - Parse cascade rules from `self._config.get("optimistic_cascades", [])`.
    - Map requested value (`val_str = str(value).lower()`) using `value_map.get(val_str, value_map.get("default"))`.
    - Split `target_node` by `.` (e.g. `"Operation.power"`) to dynamically navigate or create nested dictionary levels in target states (supporting both root `state` and legacy `state["Devices"][0]`).
  - **Controller Integration**:
    - Automatically integrates with `controller_yaml_polling.py` via `hasattr(prop, "apply_optimistic_cascades")`.
  - **Benefits**: Completely decouples state cascading from Python source code, restoring purity to the YAML controller and enabling custom cascade rules for any AC protocol/brand strictly through YAML configuration.

- [x] **Poller Contracts Verification (Technical Audit)**
  - **Criticality Reason**: This is an architectural observation. As long as `YamlStatePoller` respects debounce timings and does not flood the Event Loop with blocking requests (correctly emulating `DataUpdateCoordinator`), the abstraction is tolerated.
  - **Action**: Schedule a secondary review of `controller_yaml_polling.py` to ensure it correctly implements `async_config_entry_first_refresh` and does not leak synchronous exceptions.
  - **Audit Outcome (Verified)**: Full technical audit confirmed that `SamsungClimateCoordinator` (inheriting from Core's `DataUpdateCoordinator[ClimateIPDeviceState]`) strictly governs `async_config_entry_first_refresh` and exception boundaries, mapping all protocol/network exceptions into typed `UpdateFailed` or `ConfigEntryAuthFailed` without unhandled synchronous leaks. `YamlStatePoller` operates non-blockingly, respects debounce windows (3.0s trailing debounce + 2.0s cache freshness + 3.0s/15s anti-flicker shields), and passes all 1,163 unit/integration tests.
