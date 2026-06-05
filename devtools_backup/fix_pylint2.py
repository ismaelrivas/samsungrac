import re

# connection_aiohttp.py: ungrouped imports
f = "custom_components/climate_ip/connection_aiohttp.py"
with open(f, "r") as file: content = file.read()
content = content.replace("from homeassistant.util.json import json_loads, JSON_DECODE_EXCEPTIONS\nfrom homeassistant.helpers.json import json_dumps", "from homeassistant.helpers.json import json_dumps\nfrom homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads")
with open(f, "w") as file: file.write(content)

# config_flow.py: W0611 unused import functools
f = "custom_components/climate_ip/config_flow.py"
with open(f, "r") as file: content = file.read()
content = content.replace("import functools\n", "")
with open(f, "w") as file: file.write(content)

# test_arp_discovery.py: protected access & redefined outer name
f = "custom_components/climate_ip/tests/test_arp_discovery.py"
with open(f, "r") as file: content = file.read()
content = content.replace("mock_hass", "hass_mock")
content = content.replace("mock_entry._async_resolve_mac_and_set_unique_id(", "# pylint: disable=protected-access\n    mock_entry._async_resolve_mac_and_set_unique_id(")
with open(f, "w") as file: file.write(content)

# test_placeholders.py: missing docstring & unused variables
f = "custom_components/climate_ip/tests/test_placeholders.py"
with open(f, "r") as file: content = file.read()
if not content.startswith('"""'):
    content = '"""Tests for placeholder rendering routines."""\n' + content
content = content.replace("conn_raw = ", "")
content = content.replace("conn_aio._format_url", "conn_aio._format_url  # pylint: disable=protected-access")
content = re.sub(r'from unittest\.mock import AsyncMock, patch\n', 'from unittest.mock import MagicMock\n', content)
with open(f, "w") as file: file.write(content)

# test_actions.py: unused pytest, unnecessary pass, abstract-method
f = "custom_components/climate_ip/tests/test_actions.py"
with open(f, "r") as file: content = file.read()
content = content.replace("import pytest\n", "")
content = content.replace("from custom_components.climate_ip.climate import ClimateIP\n", "")
content = content.replace("from custom_components.climate_ip import async_setup_entry\n", "")
with open(f, "w") as file: file.write(content)
