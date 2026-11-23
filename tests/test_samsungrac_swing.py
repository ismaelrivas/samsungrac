"""Tests for Samsung RAC (8888) swing mode YAML payloads and template round-trip."""

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
import urllib.request

import pytest

from homeassistant.helpers.template import Template
from homeassistant.util.yaml import load_yaml

from .conftest_emulator import emulator_8888  # noqa: F401

SAMSUNGRAC_YAML = Path(__file__).parent.parent / "samsungrac.yaml"
EXPECTED_SWING_MODES: dict[str, str] = {
    "off": "Fix",
    "vertical": "Up_And_Low",
    "horizontal": "Left_And_Right",
    "both": "All",
}


def _load_swing_operation() -> dict[str, Any]:
    """Load the swing operation section from samsungrac.yaml."""
    raw = load_yaml(str(SAMSUNGRAC_YAML))
    assert isinstance(raw, dict)
    return raw["device"]["operations"]["swing"]


def _put_json(url: str, payload: dict[str, Any]) -> int:
    """Send an HTTP PUT JSON request to the local emulator and return status code."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return int(resp.status)


def test_samsungrac_swing_payloads_are_flat() -> None:
    """All swing modes must send flat {'direction': ...} bodies to /devices/0/wind."""
    swing = _load_swing_operation()
    url = swing["connection"]["params"]["url"]
    assert url.endswith("/devices/0/wind")

    values = swing["values"]
    assert set(values) == set(EXPECTED_SWING_MODES)

    for ha_mode, dev_direction in EXPECTED_SWING_MODES.items():
        entry = values[ha_mode]
        assert entry["value"] == dev_direction
        payload = entry["connection"]["params"]["json"]
        assert "Wind" not in payload
        assert payload == {"direction": dev_direction}


@pytest.mark.parametrize(
    ("raw_direction", "expected_ha_mode"),
    [
        ("Fix", "off"),
        ("Fixed", "off"),
        ("Up_And_Low", "vertical"),
        ("Left_And_Right", "horizontal"),
        ("All", "both"),
        ("Rotation", "both"),
    ],
)
def test_samsungrac_swing_status_template_round_trip(
    hass: Any,
    raw_direction: str,
    expected_ha_mode: str,
) -> None:
    """Swing status_template must map device directions back to HA swing modes."""
    if not isinstance(hass.data, dict):
        hass.data = {}
    if not isinstance(hass.config.legacy_templates, bool):
        hass.config.legacy_templates = False

    swing = _load_swing_operation()
    dev_to_ha = {cfg["value"]: ha_mode for ha_mode, cfg in swing["values"].items()}
    tmpl = Template(swing["status_template"], hass)

    rendered = str(
        tmpl.async_render(
            device_state={"Wind": {"direction": raw_direction}},
            parse_result=False,
        )
    ).strip()
    assert dev_to_ha[rendered] == expected_ha_mode

    missing_wind = str(tmpl.async_render(device_state={}, parse_result=False)).strip()
    assert missing_wind == ""


def test_emulator_rejects_nested_wind_and_accepts_flat(
    emulator_8888: dict[str, Any],  # noqa: F811
) -> None:
    """Emulator /wind accepts all flat YAML swing payloads and rejects nested Wind."""
    swing = _load_swing_operation()
    url = f"http://127.0.0.1:{emulator_8888['port']}/devices/0/wind"

    for cfg in swing["values"].values():
        payload = cfg["connection"]["params"]["json"]
        assert _put_json(url, payload) == 200
        assert emulator_8888["state"]["Devices"][0]["Wind"]["direction"] == cfg["value"]

    last_direction = emulator_8888["state"]["Devices"][0]["Wind"]["direction"]
    with pytest.raises(HTTPError) as exc_info:
        _put_json(url, {"Wind": {"direction": "Fix"}})

    assert exc_info.value.code == 400
    assert emulator_8888["state"]["Devices"][0]["Wind"]["direction"] == last_direction
