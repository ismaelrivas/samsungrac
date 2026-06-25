import re

test_file = "/workspaces/ha_data/config/custom_components/climate_ip/tests/test_controller_yaml_config.py"

with open(test_file, "r") as f:
    content = f.read()

strict_mock_code = """
class StrictMock(MagicMock):
    def __getattr__(self, name):
        # We only strictly enforce attributes that the controller uses in getattr() calls
        if name in ("_yaml", "device_id", "_config", "config", "hass", "unique_id", "_session", "ip_address", "id", "config_validation_type", "device_class"):
            # MagicMock stores mocked children in _mock_children or __dict__ depending on how they are set
            if name not in self.__dict__ and name not in self._mock_children:
                raise AttributeError(f"StrictMock: Attribute '{name}' not set!")
        return super().__getattr__(name)
"""

content = re.sub(r'(from unittest.mock import MagicMock, patch, AsyncMock\n)', r'\1' + strict_mock_code, content, count=1)

content = content.replace("mock_controller = MagicMock()", "mock_controller = StrictMock()")
content = content.replace("mock_prop = MagicMock()", "mock_prop = StrictMock()")
content = content.replace("prop_other = MagicMock()", "prop_other = StrictMock()")
content = content.replace("prop_duck = MagicMock()", "prop_duck = StrictMock()")
content = content.replace("prop_isinstance = MagicMock(spec=TemperatureOperation)", "prop_isinstance = StrictMock(spec=TemperatureOperation)")
content = content.replace("mock_temp_prop = MagicMock()", "mock_temp_prop = StrictMock()")

with open(test_file, "w") as f:
    f.write(content)

print("Applied StrictMock!")
