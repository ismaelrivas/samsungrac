#!/usr/bin/env bash
set -e
cd /workspaces/ha_data/config
mutmut results | grep survived > survived5.log || true
cp survived5.log survived_latest.log
python3 custom_components/climate_ip/scripts/dump_all_fast_optimized.py
python3 custom_components/climate_ip/scripts/group_and_deduplicate.py
