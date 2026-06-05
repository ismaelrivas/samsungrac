import re

# Fix properties.py
f = "custom_components/climate_ip/properties.py"
with open(f, "r") as file:
    content = file.read()
content = content.replace("return cv.string if cv else str", "return cv.string")
content = content.replace("return cv.positive_int if cv else int", "return cv.positive_int")
content = content.replace("""        self._connection_template: Template | None = None
        self._validation_template: Template | None = None""", """        self._connection_template: Template | None = None
        self._validation_template: Template | None = None
        self._status_template_raw: Any = None
        self._connection_template_raw: Any = None
        self._validation_template_raw: Any = None""")
content = content.replace("async with connection._lock:", "async with connection._lock:  # pylint: disable=protected-access")
with open(f, "w") as file:
    file.write(content)

# Fix controller_yaml_polling.py
f = "custom_components/climate_ip/controller_yaml_polling.py"
with open(f, "r") as file:
    content = file.read()
content = content.replace("            import copy\n", "")
content = re.sub(r'            state_attrs = {} # Temporary attributes for mode resolution\n            for prop in all_properties:\n                if hasattr\(prop, "all_values"\):\n                    # We might need to handle \'values\' which is dynamic\.\n                    # For now, we take the full list or calculate it if possible\.\n                    # But the simplest is to just rely on what\'s available\.\n                    pass\n', '', content)
with open(f, "w") as file:
    file.write(content)

# Fix connection_request_tls_auto.py
f = "custom_components/climate_ip/connection_request_tls_auto.py"
with open(f, "r") as file:
    content = file.read()
content = content.replace("        import asyncio as _asyncio  # noqa: F401 – already imported; kept for IDE clarity\n", "")
content = content.replace("def execute_internal(", "    # pylint: disable=too-many-statements\n    def execute_internal(")
with open(f, "w") as file:
    file.write(content)

