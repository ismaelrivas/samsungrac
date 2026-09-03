# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test the manifest.json file for correctness."""

from __future__ import annotations

import json
import os

from custom_components.climate_ip.const import DOMAIN


def test_manifest_validation():
    """Verify manifest.json has correct structure and values."""
    manifest_path = os.path.join(os.path.dirname(__file__), "..", "manifest.json")
    assert os.path.exists(manifest_path)

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["domain"] == DOMAIN
    assert "name" in manifest
    assert "documentation" in manifest
    assert "codeowners" in manifest
    assert isinstance(manifest["codeowners"], list)

    # Verify documentation URL points to the real repository
    assert (
        "github.com/ismaelrivas" in manifest["documentation"]
        or "github.com/rtp-p" in manifest["documentation"]
    )

    # Verify codeowners attribution
    assert (
        "@ismaelrivas" in manifest["codeowners"] or "@rtp-p" in manifest["codeowners"]
    )

    # Requirements validation
    assert "requirements" in manifest
    assert isinstance(manifest["requirements"], list)
    for req in manifest["requirements"]:
        assert not req.startswith("git+"), (
            f"Direct git dependencies are forbidden: {req}"
        )
        assert not req.startswith("http"), (
            f"HTTP/HTTPS dependencies are forbidden: {req}"
        )


def test_services_yaml_valid():
    """Verify services.yaml exists and is valid YAML."""
    from pathlib import Path

    import yaml

    integration_root = Path(__file__).parent.parent
    services_file = integration_root / "services.yaml"
    if services_file.exists():
        data = yaml.safe_load(services_file.read_text(encoding="utf-8"))
        assert isinstance(data, dict)


def test_icons_and_quality_scale_valid():
    """Verify icons.json and quality_scale.yaml if present."""
    from pathlib import Path

    import yaml

    integration_root = Path(__file__).parent.parent
    icons_file = integration_root / "icons.json"
    if icons_file.exists():
        data = json.loads(icons_file.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    qs_file = integration_root / "quality_scale.yaml"
    if qs_file.exists():
        qs_data = yaml.safe_load(qs_file.read_text(encoding="utf-8"))
        assert isinstance(qs_data, dict)


def test_translation_files_coherent():
    """All translation files must have the same leaf keys as strings.json to avoid UI blanks."""
    import json
    from pathlib import Path

    # Paths relative to the root of the integration
    integration_root = Path(__file__).parent.parent
    strings_path = integration_root / "strings.json"

    assert strings_path.exists(), f"strings.json not found at {strings_path}"
    strings = json.loads(strings_path.read_text(encoding="utf-8"))

    def get_leaf_keys(d, prefix=""):
        """Recursively collect all leaf keys (dot notation)."""
        keys = set()
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys |= get_leaf_keys(v, full)
            else:
                keys.add(full)
        return keys

    base_keys = get_leaf_keys(strings)

    translations_dir = integration_root / "translations"
    supported_langs = ["en", "es", "fr", "de"]

    for lang in supported_langs:
        lang_file = translations_dir / f"{lang}.json"
        assert lang_file.exists(), f"Translation file {lang_file} is missing"

        lang_data = json.loads(lang_file.read_text(encoding="utf-8"))
        lang_keys = get_leaf_keys(lang_data)

        missing = base_keys - lang_keys
        assert not missing, f"{lang}.json is missing translation keys: {missing}"
