import glob
import re

files_to_update = glob.glob("custom_components/climate_ip/*.py") + glob.glob("custom_components/climate_ip/tests/*.py")
disable_str = "# pylint: disable="
for f in files_to_update:
    with open(f, "r") as file:
        content = file.read()
    
    if "import-outside-toplevel" not in content and disable_str in content:
        content = content.replace(disable_str, disable_str + "import-outside-toplevel,")
        with open(f, "w") as file:
            file.write(content)
