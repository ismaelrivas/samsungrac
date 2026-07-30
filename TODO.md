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
