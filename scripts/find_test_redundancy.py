#!/usr/bin/env python3
"""Tactical Test Redundancy & Overlap Detection Tool.

Analyzes Python pytest files to detect:
1. Exact duplicate test names across multiple files.
2. High code similarity (AST/Token/Normalized sequence matching).
3. Overlapping methods under test (mocking and target call intersections).
4. Redundant assertion profiles and semantic duplicates.

Usage:
  python scripts/find_test_redundancy.py tests/test_config_flow*.py
  python scripts/find_test_redundancy.py tests/
  python scripts/find_test_redundancy.py tests/test_*.py --threshold 0.70 --json
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from difflib import SequenceMatcher
import glob
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


class TestExtractor(ast.NodeVisitor):
    """AST Visitor to extract test functions and their analytical signatures."""

    def __init__(self, filepath: str, source_code: str):
        self.filepath = filepath
        self.source_code = source_code
        self.lines = source_code.splitlines()
        self.tests: list[dict[str, Any]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_func(node)
        self.generic_visit(node)

    def _process_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not node.name.startswith("test_"):
            return

        doc = ast.get_docstring(node) or ""
        body_src = ast.get_source_segment(self.source_code, node) or ""

        # Extract calls (e.g. flow.async_step_*, controller.*, mock assertions)
        calls = set()
        assertions = []
        patches = []

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_repr = self._get_call_name(child.func)
                if call_repr:
                    calls.add(call_repr)
                if call_repr and "patch" in call_repr.lower():
                    # Extract patch targets if string literal
                    if child.args and isinstance(child.args[0], ast.Constant):
                        patches.append(str(child.args[0].value))

            elif isinstance(child, ast.Assert):
                assert_src = ast.get_source_segment(self.source_code, child) or ""
                assertions.append(assert_src.strip())

        # Normalize body (strip docstrings and whitespace) for AST token similarity
        clean_lines = [
            l.strip()
            for l in body_src.splitlines()
            if l.strip() and not l.strip().startswith(('"""', "'''", "#"))
        ]
        normalized_body = " ".join(clean_lines)

        self.tests.append(
            {
                "file": self.filepath,
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", node.lineno),
                "doc": doc.strip(),
                "body": body_src,
                "normalized_body": normalized_body,
                "calls": sorted(list(calls)),
                "patches": sorted(patches),
                "assertions": assertions,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            }
        )

    def _get_call_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            val = self._get_call_name(node.value)
            return f"{val}.{node.attr}" if val else node.attr
        return None


def collect_test_files(patterns: list[str]) -> list[str]:
    """Resolve file patterns and directory inputs into distinct test file paths."""
    resolved = set()
    for pat in patterns:
        path = Path(pat)
        if path.is_dir():
            for f in path.rglob("test_*.py"):
                resolved.add(str(f.resolve()))
        else:
            matches = glob.glob(pat, recursive=True)
            if matches:
                for m in matches:
                    if m.endswith(".py"):
                        resolved.add(str(Path(m).resolve()))
            elif path.is_file() and str(path).endswith(".py"):
                resolved.add(str(path.resolve()))
    return sorted(list(resolved))


def analyze_redundancies(
    tests: list[dict[str, Any]], similarity_threshold: float = 0.60
) -> dict[str, Any]:
    """Execute multi-tier redundancy analysis."""
    # 1. Exact Duplicate Names
    name_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in tests:
        name_map[t["name"]].append(t)

    exact_duplicates = {
        name: occurrences
        for name, occurrences in name_map.items()
        if len(occurrences) > 1
    }

    # 2. Body / Sequence Similarity across different files
    high_similarity_pairs = []
    n = len(tests)
    for i in range(n):
        for j in range(i + 1, n):
            t1, t2 = tests[i], tests[j]
            if t1["file"] == t2["file"]:
                continue

            ratio = SequenceMatcher(
                None, t1["normalized_body"], t2["normalized_body"]
            ).ratio()
            if ratio >= similarity_threshold:
                high_similarity_pairs.append(
                    {
                        "similarity": round(ratio, 4),
                        "test_a": {
                            "file": t1["file"],
                            "name": t1["name"],
                            "lineno": t1["lineno"],
                            "doc": t1["doc"],
                        },
                        "test_b": {
                            "file": t2["file"],
                            "name": t2["name"],
                            "lineno": t2["lineno"],
                            "doc": t2["doc"],
                        },
                    }
                )

    high_similarity_pairs.sort(key=lambda x: x["similarity"], reverse=True)

    # 3. Call & Assertion Overlap (Method-Under-Test intersection)
    calls_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in tests:
        # Filter high-signal calls (e.g., flow.*, step_*, controller.*)
        for c in t["calls"]:
            if any(
                sig in c
                for sig in (
                    "flow.",
                    "async_step",
                    "_async_",
                    "controller.",
                    "coordinator.",
                )
            ):
                calls_map[c].append(t)

    overloaded_methods = {
        method: callers
        for method, callers in calls_map.items()
        if len(set(c["file"] for c in callers)) > 1
    }

    return {
        "total_tests": len(tests),
        "total_files": len(set(t["file"] for t in tests)),
        "exact_duplicates": exact_duplicates,
        "high_similarity_pairs": high_similarity_pairs,
        "overloaded_methods_count": len(overloaded_methods),
        "overloaded_methods": {
            k: [f"{c['file']}:{c['lineno']} ({c['name']})" for c in v]
            for k, v in sorted(
                overloaded_methods.items(), key=lambda item: len(item[1]), reverse=True
            )
        },
    }


def print_cli_report(results: dict[str, Any], verbose: bool = False) -> None:
    """Render tactical human-readable terminal report."""
    print("=" * 80)
    print(" 🎯 TEST SUITE REDUNDANCY & OVERLAP AUDIT REPORT")
    print("=" * 80)
    print(f"Total Test Files Scanned: {results['total_files']}")
    print(f"Total Test Cases Analyzed: {results['total_tests']}")
    print("-" * 80)

    # Section 1: Exact Duplicate Names
    exact_dups = results["exact_duplicates"]
    print(f"\n[1] Exact Duplicate Test Names: {len(exact_dups)} found")
    if exact_dups:
        for name, occurrences in exact_dups.items():
            print(f"  🔴 {name} ({len(occurrences)} occurrences):")
            for occ in occurrences:
                print(f"     -> {occ['file']}:{occ['lineno']}")
    else:
        print("  ✅ Zero exact name collisions.")

    # Section 2: High Body Similarity Pairs
    sim_pairs = results["high_similarity_pairs"]
    print(f"\n[2] High AST / Body Similarity Pairs: {len(sim_pairs)} found")
    if sim_pairs:
        for pair in sim_pairs:
            sim = pair["similarity"]
            ta = pair["test_a"]
            tb = pair["test_b"]
            print(f"  ⚠️  Similarity: {sim*100:.1f}%")
            print(f"     A: {ta['file']}:{ta['lineno']} [{ta['name']}]")
            if ta["doc"]:
                print(f"        Doc: {ta['doc'][:80]}")
            print(f"     B: {tb['file']}:{tb['lineno']} [{tb['name']}]")
            if tb["doc"]:
                print(f"        Doc: {tb['doc'][:80]}")
            print()
    else:
        print("  ✅ Zero pairs above the similarity threshold.")

    # Section 3: Overloaded Methods under test
    overloaded = results.get("overloaded_methods", {})
    print(
        f"[3] Cross-File Overloaded Methods Under Test: {len(overloaded)} detected"
    )
    if overloaded:
        top_methods = list(overloaded.items())[:10]
        for method, callers in top_methods:
            print(f"  🔹 Method `{method}` called across {len(callers)} test cases:")
            if verbose:
                for c in callers:
                    print(f"     - {c}")
            else:
                for c in callers[:4]:
                    print(f"     - {c}")
                if len(callers) > 4:
                    print(f"     ... and {len(callers)-4} more tests.")
    print("=" * 80)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit test suites for duplicates, high body similarity, and overlapping assertions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Test files or directories to scan (e.g. tests/test_config_flow*.py)",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=0.60,
        help="Similarity ratio threshold between 0.0 and 1.0 (default: 0.60)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Display verbose output including full call lists",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output analysis report as JSON"
    )

    args = parser.parse_args()

    files = collect_test_files(args.paths)
    if not files:
        print(f"ERROR: No test files found matching: {args.paths}", file=sys.stderr)
        return 1

    all_tests = []
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as fp:
                code = fp.read()
            extractor = TestExtractor(fpath, code)
            extractor.visit(ast.parse(code, filename=fpath))
            all_tests.extend(extractor.tests)
        except Exception as err:
            print(f"Warning: Failed to parse {fpath}: {err}", file=sys.stderr)

    report = analyze_redundancies(all_tests, similarity_threshold=args.threshold)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_cli_report(report, verbose=args.verbose)

    return 0


if __name__ == "__main__":
    sys.exit(main())
