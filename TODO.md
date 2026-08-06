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
