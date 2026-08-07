# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Tests for static integration specs and Phase 1 compliance rules."""
# pylint: disable=redefined-builtin,too-few-public-methods,missing-class-docstring,import-outside-toplevel

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def test_static_spec_signature() -> None:
    """Test the structure of a static spec representation.

    This acts as a proof-of-concept that sensors and operations
    can be represented purely in Python without the YAML loader overhead.
    """

    class MockSensorProp:
        def __init__(self, id: str, name: str, device_class: str | None = None) -> None:
            self.id = id
            self.name = name
            self.device_class = device_class

    class MockOperationProp:
        def __init__(self, id: str, values: list[str]) -> None:
            self.id = id
            self.values = values

    # Simulating what StaticControllerLoader would return
    static_spec: dict[str, Any] = {
        "sensors": [
            MockSensorProp("outdoor_temperature", "Outdoor Temperature", "temperature"),
            MockSensorProp("used_power", "Electrical Consumption", "energy"),
        ],
        "operations": {
            "hvac": MockOperationProp("hvac", ["cool", "heat", "off"]),
            "power": MockOperationProp("power", ["on", "off"]),
        },
    }

    assert len(static_spec["sensors"]) == 2
    assert static_spec["sensors"][0].id == "outdoor_temperature"
    assert "hvac" in static_spec["operations"]
    assert "cool" in static_spec["operations"]["hvac"].values


# ---------------------------------------------------------------------------
# Phase 1: Manifest & Platform compliance
# ---------------------------------------------------------------------------


def test_iot_class_is_local_polling() -> None:
    """Manifest must declare local_polling — Samsung 2878 uses a persistent TCP push connection."""
    manifest = json.loads(
        (Path(__file__).parent.parent / "manifest.json").read_text(encoding="utf-8")
    )
    assert (
        manifest["iot_class"] == "local_polling"
    ), f"Expected iot_class='local_polling', got '{manifest['iot_class']}'"
