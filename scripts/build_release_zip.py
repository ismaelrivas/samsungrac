#!/usr/bin/env python3
"""Build a clean distribution ZIP archive for HACS (Home Assistant Community Store).

This script packages exclusively production integration files and excludes
all development artifacts, test suites, and internal scripts.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import zipfile

# File extensions strictly required for runtime execution
ALLOWED_EXTENSIONS = {".py", ".json", ".yaml", ".pem"}

# Directories excluded from release distribution
EXCLUDED_DIRS = {
    "tests",
    "scripts",
    "__pycache__",
    ".git",
    ".github",
    ".pytest_cache",
    ".ruff_cache",
    ".codebase-memory",
}

# Individual files excluded from release distribution
EXCLUDED_FILES = {
    "pytest.ini",
    "setup.cfg",
    ".pre-commit-config.yaml",
    "GEMINI.md",
    "TODO.md",
    "CHANGELOG.md",
    "README.md",
    "hacs.json",
    ".gitignore",
    ".cbmignore",
    ".hacsignore",
}

# Critical files that MUST exist for a valid release
MANDATORY_FILES = [
    "__init__.py",
    "manifest.json",
    "climate.py",
    "const.py",
    "strings.json",
    "services.yaml",
]


def build_release_zip(output_path: Path | None = None) -> Path:
    """Package clean integration files into a ZIP archive for HACS."""
    repo_root = Path(__file__).resolve().parent.parent

    # Verify repository root integrity
    for mandatory in MANDATORY_FILES:
        if not (repo_root / mandatory).exists():
            raise FileNotFoundError(f"Mandatory file missing in {repo_root}: {mandatory}")

    if output_path is None:
        output_path = repo_root / "climate_ip.zip"

    output_path = Path(output_path).resolve()

    packaged_files: list[str] = []

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _, filenames in os.walk(repo_root):
            rel_dir = os.path.relpath(dirpath, repo_root)
            parts = Path(rel_dir).parts

            if any(part in EXCLUDED_DIRS for part in parts):
                continue

            for filename in sorted(filenames):
                if (
                    filename in EXCLUDED_FILES
                    or filename.endswith((".borrar", ".pyc", ".bak"))
                    or filename.startswith(".")
                ):
                    continue

                ext = os.path.splitext(filename)[1]
                if ext in ALLOWED_EXTENSIONS:
                    file_full_path = os.path.join(dirpath, filename)
                    archive_name = os.path.relpath(file_full_path, repo_root)
                    zf.write(file_full_path, archive_name)
                    packaged_files.append(archive_name)

    size_kb = output_path.stat().st_size / 1024
    print(f"Successfully packaged {len(packaged_files)} production files into:")
    print(f"  -> {output_path} ({size_kb:.1f} KB)")

    return output_path


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Build clean release zip for HACS.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Target output zip file path (default: <repo_root>/climate_ip.zip)",
    )
    args = parser.parse_args()

    try:
        build_release_zip(args.output)
    except Exception as exc:
        print(f"Error building release zip: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
