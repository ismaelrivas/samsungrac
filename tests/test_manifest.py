# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test the manifest.json file for correctness."""
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
    assert "github.com/ismaelrivas" in manifest["documentation"] or "github.com/rtp-p" in manifest["documentation"]

    # Verify codeowners attribution
    assert "@ismaelrivas" in manifest["codeowners"] or "@rtp-p" in manifest["codeowners"]

    # Requirements validation
    assert "requirements" in manifest

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
