import re

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'r') as f:
    content = f.read()

content = content.replace('"{mac}"', '"__CLIMATE_IP_MAC__"')
content = content.replace('"/emb_{mac}"', '"/emb___CLIMATE_IP_MAC__"')
content = content.replace('"{token}"', '"__CLIMATE_IP_TOKEN__"')
content = content.replace('"/path/{token}"', '"/path/__CLIMATE_IP_TOKEN__"')
content = content.replace('"{dev_id}"', '"__DEVICE_ID__"')

with open('custom_components/climate_ip/tests/test_connection_raw.py', 'w') as f:
    f.write(content)

print("Placeholders fixed!")
