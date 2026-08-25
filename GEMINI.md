# Memory & Operational Guidelines for Climate IP Integration

## 1. Terminal Execution & DevPod Wrapper Environment (External / Non-IDE Agents)

All terminal commands (pytest, ruff, pylint, mutmut, git, etc.) executed by external/non-IDE agents must be executed inside the DevPod container environment using the persistent SSH wrapper:

* **Wrapper script path:** `/home/cogollo/.local/bin/devpod-shell.sh`
* **Sandbox setting:** Always use `BypassSandbox: true` when running `run_command` with this wrapper, as it connects over SSH to `hadata.devpod`.
* **Runtime directory prefix:** Prepend `XDG_RUNTIME_DIR=/tmp` to ensure the SSH ControlMaster socket is created in `/tmp` rather than failing on read-only `/run/user/1000`.

### Standard Invocation Syntax:
```bash
XDG_RUNTIME_DIR=/tmp /home/cogollo/.local/bin/devpod-shell.sh -c "<command>"
```

### Useful Options:
* `--info`: Returns telemetry of remote environment (Python version, linters, RAM, Git status).
* `--status`: Checks remote master socket status.
* `--async "<command>"`: Starts a long-running command (>30s) in the background.
* `--job-status <job_id>`: Checks status and recent logs of an async job.
* `--timeout <seconds> <command>`: Runs synchronous command with timeout guard.

---

## 2. Directory Structure, Git Repository & Test Locations

* **Local Workspace Root:** `/home/cogollo/ha_data/config`
* **Remote DevPod Root:** `/workspaces/ha_data/config`
* **Source Code Directory:** `custom_components/climate_ip/`
* **Remote Git Repository Path (`.git`):** `/workspaces/ha_data/config/custom_components/climate_ip/.git`
  * *Note for Git commands (Non-IDE Agents):* To execute `git status`, `git diff`, `git log`, etc., target this repository explicitly:
    ```bash
    XDG_RUNTIME_DIR=/tmp /home/cogollo/.local/bin/devpod-shell.sh -c "git --git-dir=/workspaces/ha_data/config/custom_components/climate_ip/.git --work-tree=/workspaces/ha_data/config/custom_components/climate_ip status"
    ```
* **Unit & Integration Tests Directory:** `custom_components/climate_ip/tests/`

### Test Files Index:
* `custom_components/climate_ip/tests/test_controller_yaml.py` — Core controller unit tests (I/O, cache, properties).
* `custom_components/climate_ip/tests/test_config_flow_discovery.py` — Discovery routines, indoor unit selection, MIM-H03 & 8888 routing.
* `custom_components/climate_ip/tests/test_config_flow.py` — Configuration flow lifecycle and schema validation.
* `custom_components/climate_ip/tests/test_init.py` — Integration setup, teardown, and runtime data lifecycle.
* `custom_components/climate_ip/tests/test_coordinator.py` — DataUpdateCoordinator polling and state merge.
* `custom_components/climate_ip/tests/conftest.py` — Pytest fixtures and mock Home Assistant environment.

### Standard Quality Commands (Non-IDE Agents):
```bash
# Run specific test file
XDG_RUNTIME_DIR=/tmp /home/cogollo/.local/bin/devpod-shell.sh -c "pytest custom_components/climate_ip/tests/test_controller_yaml.py"

# Run linter checks
XDG_RUNTIME_DIR=/tmp /home/cogollo/.local/bin/devpod-shell.sh -c "ruff check custom_components/climate_ip/tests/test_controller_yaml.py"
XDG_RUNTIME_DIR=/tmp /home/cogollo/.local/bin/devpod-shell.sh -c "pylint custom_components/climate_ip/tests/test_controller_yaml.py"

# Check Git status in remote container
XDG_RUNTIME_DIR=/tmp /home/cogollo/.local/bin/devpod-shell.sh -c "git --git-dir=/workspaces/ha_data/config/custom_components/climate_ip/.git --work-tree=/workspaces/ha_data/config/custom_components/climate_ip status"
```

---

## 3. Antigravity IDE Agent Guidelines

When operating as an agent inside the Antigravity IDE, apply the following specific behaviors:

### 3.1 Direct Terminal Execution
* The Antigravity IDE default terminal shell environment already has the container / DevPod integration built-in.
* Commands are executed directly via `run_command` without the SSH wrapper prefix:
  ```bash
  pytest custom_components/climate_ip/tests/test_controller_yaml.py
  ruff check custom_components/climate_ip/
  pylint custom_components/climate_ip/
  ```

### 3.2 Preferential MCP Server Access
* **`json-mcp-server`**: Preferred tool for querying, validating, reading, and editing structured JSON files (e.g. `analysis_connection_aiohttp_ultra.json`, mutation reports, configuration files).
* **`codebase-memory`**: Preferred tool for code graph indexing, cross-file symbol tracing, and architectural queries.

### 3.3 Git Repository Location & Execution
* **Repository location (`.git`):** `custom_components/climate_ip/.git` (located at `/workspaces/ha_data/config/custom_components/climate_ip/.git` in the container).
* **Execution syntax in IDE terminal:** Always target the integration directory explicitly from workspace root:
  ```bash
  git -C custom_components/climate_ip status
  git -C custom_components/climate_ip diff
  git -C custom_components/climate_ip log -n 5
  ```

---

## 4. Mutant Analysis & Ultra Table Tool (`generate_ultra_table.py`)

The workspace provides `./generate_ultra_table.py` to extract, aggregate, and render structured statistics from mutmut Ultra JSON analysis files (`analysis_*_ultra.json`).

### Standard CLI Options:
* `--exclude, -e`: Exclude specific files, module names, or glob patterns from the analysis (e.g. `-e climate.py '*connection*'`).
* `--survivors, -s`: Display dedicated surviving mutants table.
* `--diffs, -d`: Include survivor code diffs when reporting survivors.
* `--full, -f`: Display all tables (Summary, Performance, Categories, Pruning, Survivors, Tests).
* `--tests, -t`: Display discovered test suites table for each analyzed source.
* `--tests-only`: Output raw discovered test file paths (one per line) for CLI piping / pytest.
* `--untested, -u`: Display untested mutants (code without test coverage).
* `--categories, -c`: Display mutation categories breakdown table.
* `--performance, -p`: Display execution time and slow mutant performance metrics table.
* `--pruning`: Display static AST pruning and shield exclusions table.
* `--full-paths`: Display full file paths instead of short module names in table.
* `--sort {source,score,duration,survivors,killed,generated,slow,date}`: Sort summary table by metric (default: `source`).
* `--reverse, -r`: Reverse sorting order.
* `--csv`: Export summary metrics to CSV.
* `--json`: Export all parsed analysis data as JSON.

### Canonical Usage Examples:
```bash
# 1. Inspect surviving mutants and their exact code diffs for a specific analysis file
./generate_ultra_table.py -s -d analysis_controller_yaml_polling_ultra.json

# 2. Render complete full report across all generated analysis files
./generate_ultra_table.py --full

# 3. Pipe discovered test suites directly into pytest
./generate_ultra_table.py --tests-only analysis_controller_yaml_polling_ultra.json | xargs pytest

# 4. Check AST pruning and safety shields
./generate_ultra_table.py --pruning
```

---

## 5. Integration Architecture, Quirks & Learnings

### 5.1 Device Topologies & Pairing Flow
* **`samsung_2878`**: Legacy devices using TLS raw stream on port `2878`.
* **`samsung_8888`**: Modern AC units. HA initiates pairing on port `8888` and listens on local port `8889` for the callback token.
* **`mim_h03`**: Samsung MIM-H03 heatpump controller. Communicates on port `8888` via `auth_flows/samsungrac_auth.yaml` and handles indoor unit sub-devices (`_async_process_mim_h03`).
* **`smartthings_hvac` / `smartthings_dhw`**: Cloud REST API devices.

### 5.2 Home Assistant Config Flow Step Integrity Rule
* Every step passed to `self.async_show_form(step_id="<step>", ...)` (including fallback and error recovery in `async_step_handle_error`) **MUST** correspond to a method `async_step_<step>` on `ClimateIpConfigFlow`. Otherwise, Home Assistant's `DataEntryFlow._raise_if_step_does_not_exist` will raise `UnknownStep`.

### 5.3 Python 3.14 / OpenSSL 3.x Protocol Quirks
* **`APPLICATION_DATA_AFTER_CLOSE_NOTIFY`:**
  During socket communication, if an AC/emulator sends a TLS `close_notify`, post-write read or socket shutdown (`writer.wait_closed()`) may raise `ssl.SSLError: [SSL: APPLICATION_DATA_AFTER_CLOSE_NOTIFY]`. Once `writer.drain()` completes successfully, the payload was delivered. Post-transmission reads and closes must be wrapped in isolated exception blocks to prevent aborting active listener servers.
* **`TimeoutError` Hierarchy:**
  In Python 3.10+, `TimeoutError` is an `OSError` subclass. In `except` blocks, `except TimeoutError:` **must precede** `except (CannotConnect, OSError):` or `except OSError:`.
* **Listener Port Retries (`EADDRINUSE`):**
  `_start_listener_server` retries up to `MAX_PORT_RETRIES = 5` ports (e.g. `8889`..`8893`) when catching `errno == 98` (`EADDRINUSE`), logging a fallback message only when `offset > 0`.

### 5.4 Tools & Emulators
* **MIM Emulator:** `/workspaces/ha_data/config/custom_components/climate_ip_tools/emulator_MIM.py`
  Simulates a Samsung MIM-H03 heatpump controller on port 8888, responding to `POST /devicetoken/request` and sending tokens back to port 8889 after 5 seconds.


