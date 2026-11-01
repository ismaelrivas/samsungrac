# Climate IP Archived Components

This directory preserves deprecated and retired code components for historical and reference purposes.

- `token_acquirer_8888.py`: Original legacy raw TCP socket token listener and acquirer for modern Samsung AC units (port 8888). Fully superseded by `token_acquirer_yaml.py` (`GenericYamlTokenAcquirer`) driven by declarative YAML profiles (`samsung_8888.yaml`).
- `test_token_acquirer_8888.py`: Unit test suite for the retired acquirer.
- `token_acquirer.py`: Original legacy raw TCP socket token stream acquirer for legacy Samsung AC units (port 2878). Fully superseded by `token_acquirer_yaml.py` (`GenericYamlTokenAcquirer`) driven by declarative YAML profiles (`samsung_2878_auth.yaml`).
- `test_token_acquirer.py`: Unit test suite for the retired acquirer.
