import re

test_file = "/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py"

with open(test_file, "r") as f:
    content = f.read()

dummy_classes = """
class DummyHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)

class DummyController:
    def __init__(self):
        self.log_prefix = "[Test]"
        self.hass = DummyHass()
        self.device_id = "test_dev_id"
"""

# Insert dummy classes after imports
content = re.sub(r'(from unittest.mock import MagicMock, patch\n)', r'\1' + dummy_classes, content, count=1)

# Replace mock_controller = MagicMock() with mock_controller = DummyController()
content = content.replace("mock_controller = MagicMock()", "mock_controller = DummyController()")

with open(test_file, "w") as f:
    f.write(content)

print("Fixed mock_controller!")
