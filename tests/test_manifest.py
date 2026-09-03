# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test the manifest.json file for correctness."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

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


def test_manifest_keys_order_and_cleanliness():
    """Verify manifest.json has keys sorted per hassfest rules: domain, name, then alphabetical."""
    manifest_path = os.path.join(os.path.dirname(__file__), "..", "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest_raw = json.load(f)

    keys = list(manifest_raw.keys())
    assert keys[0] == "domain"
    assert keys[1] == "name"
    assert keys[2:] == sorted(keys[2:])

    # Ensure no deprecated/illegal keys in manifest
    forbidden_keys = {"config_entry_version", "homeassistant", "strict_typing"}
    found_forbidden = forbidden_keys.intersection(keys)
    assert not found_forbidden, f"Forbidden keys in manifest.json: {found_forbidden}"


def test_translations_hassfest_rules():
    """Verify translations obey Home Assistant hassfest rules."""
    integration_root = Path(__file__).parent.parent
    files_to_check = [integration_root / "strings.json"] + list(
        (integration_root / "translations").glob("*.json")
    )

    placeholder_quote_regex = re.compile(r"'\{[a-zA-Z0-9_]+\}'")
    slug_regex = re.compile(r"^[a-z0-9-_]+$")

    for file_path in files_to_check:
        data = json.loads(file_path.read_text(encoding="utf-8"))

        # 1. No placeholders inside single quotes in messages
        def check_strings(val, path="", current_file=file_path):
            if isinstance(val, str):
                match = placeholder_quote_regex.search(val)
                assert not match, (
                    f"Placeholder in single quotes in {current_file} at {path}: {val}"
                )
            elif isinstance(val, dict):
                for k, v in val.items():
                    check_strings(v, f"{path}.{k}", current_file)

        check_strings(data)

        # 2. Issues: mutually exclusive description vs fix_flow
        issues = data.get("issues", {})
        for issue_id, issue_data in issues.items():
            if "fix_flow" in issue_data:
                assert "description" not in issue_data, (
                    f"Issue '{issue_id}' in {file_path} has both description and fix_flow"
                )

        # 3. Entity translation keys must be valid slugs
        entities = data.get("entity", {})
        for platform, platform_entities in entities.items():
            for entity_id, entity_data in platform_entities.items():
                state_attrs = entity_data.get("state_attributes", {})
                for attr_id, attr_data in state_attrs.items():
                    states = attr_data.get("state", {})
                    for state_key in states:
                        assert slug_regex.match(state_key), (
                            f"Invalid translation key '{state_key}' in {file_path} at {platform}.{entity_id}.{attr_id}"
                        )


def test_hassfest_validation_suite():
    """Run core hassfest validator if available in the environment."""
    core_path = Path("/workspaces/ha_data/core")
    integration_path = Path(__file__).parent.parent

    if not (core_path / "script" / "hassfest").exists():
        return

    python_bin = "/usr/local/bin/python3.14"
    if not Path(python_bin).exists():
        python_bin = sys.executable

    result = subprocess.run(
        [
            python_bin,
            "-m",
            "script.hassfest",
            "--action",
            "validate",
            "--integration-path",
            str(integration_path),
        ],
        cwd=str(core_path),
        env={**os.environ, "PYTHONPATH": str(core_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Hassfest validation failed:\n{result.stdout}\n{result.stderr}"
    )
