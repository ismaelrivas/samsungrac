#!/bin/bash
# Absolute path to the project root — mutmut copies this script into mutants/
# but runs it from there, so all paths in this script must be absolute.
PROJECT_ROOT=/workspaces/ha_data/config

export PYTHONPATH="${PROJECT_ROOT}"

pytest \
    -p pytest_homeassistant_custom_component \
    -o asyncio_mode=auto \
    -o "markers=skip_legacy: legacy tests" \
    -c "${PROJECT_ROOT}/custom_components/climate_ip/pytest.ini" \
    "${PROJECT_ROOT}/custom_components/climate_ip/tests/"
