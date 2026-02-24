"""thomas sweep — background quality scan outputting structured JSON."""

from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

import click

from thomas._architecture import MODULES, RULES

THOMAS_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = THOMAS_ROOT.parent


def _scan_forbidden() -> list[dict]:
    import fnmatch
    hits = []
    for pattern in RULES["forbidden_patterns"]:
        for match in REPO_ROOT.glob(pattern):
            if match.is_file():
                hits.append({"file": match.name, "pattern": pattern, "location": "repo_root"})
        for py_file in THOMAS_ROOT.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            if fnmatch.fnmatch(py_file.name, pattern):
                hits.append({
                    "file": str(py_file.relative_to(REPO_ROOT)),
                    "pattern": pattern,
                    "location": "thomas/",
                })
    return hits


def _scan_oversized() -> list[dict]:
    import fnmatch
    hard_limit = RULES["max_file_lines_hard"]
    legacy_patterns = RULES.get("legacy_patterns", [])
    debt_files = set()
    for name, mod in MODULES.items():
        for match in re.findall(r"([\w\-/]+\.py)", mod.get("debt", "")):
            debt_files.add(f"thomas/{name}/{match}")

    hits = []
    for py_file in THOMAS_ROOT.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        # Skip legacy pattern files (grandfathered)
        if any(fnmatch.fnmatch(py_file.name, p) for p in legacy_patterns):
            continue
        rel = str(py_file.relative_to(REPO_ROOT)).replace("\\", "/")
        if rel in debt_files:
            continue
        try:
            lines = len(py_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        if lines > hard_limit:
            hits.append({"file": rel, "lines": lines, "limit": hard_limit})
    return hits


def _scan_stale_debt() -> list[dict]:
    soft_limit = RULES["max_new_file_lines"]
    hits = []
    for name, mod in MODULES.items():
        debt = mod.get("debt", "")
        if not debt:
            continue
        for filename in re.findall(r"([\w\-/]+\.py)", debt):
            full_path = THOMAS_ROOT / name / filename
            if not full_path.exists():
                hits.append({"module": name, "file": filename, "issue": "file_missing"})
                continue
            if "exceed" in debt.lower():
                try:
                    lines = len(full_path.read_text(encoding="utf-8", errors="replace").splitlines())
                except OSError:
                    continue
                if lines <= soft_limit:
                    hits.append({"module": name, "file": filename, "issue": "resolved", "lines": lines})
    return hits


def _scan_ceremony_tests() -> list[dict]:
    """Detect tests that only check output format (ceremony)."""
    tests_dir = REPO_ROOT / "tests"
    hits = []
    for test_file in tests_dir.glob("test_*.py"):
        try:
            source = test_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                body = node.body
                # Check if test body is just assert "string" in something
                if len(body) == 1 and isinstance(body[0], ast.Assert):
                    cmp = body[0].test
                    if isinstance(cmp, ast.Compare) and len(cmp.ops) == 1:
                        if isinstance(cmp.ops[0], ast.In) and isinstance(cmp.left, ast.Constant):
                            if isinstance(cmp.left.value, str):
                                hits.append({
                                    "file": test_file.name,
                                    "test": node.name,
                                    "issue": "ceremony_test",
                                })
    return hits


@click.command("sweep")
@click.option("--json-output", "as_json", is_flag=True, help="Output JSON instead of human-readable.")
def sweep_command(as_json: bool) -> None:
    """Run background quality scan."""
    report = {
        "forbidden_files": _scan_forbidden(),
        "oversized_files": _scan_oversized(),
        "stale_debt": _scan_stale_debt(),
        "ceremony_tests": _scan_ceremony_tests(),
    }

    total_issues = sum(len(v) for v in report.values())

    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        click.echo(f"Thomas Sweep Report ({total_issues} issues)")
        for category, items in report.items():
            label = category.replace("_", " ").title()
            if items:
                click.echo(f"  {label}: {len(items)} issues")
                for item in items[:5]:
                    click.echo(f"    - {item.get('file', item.get('module', ''))}: {item.get('issue', item.get('pattern', ''))}")
                if len(items) > 5:
                    click.echo(f"    ... and {len(items) - 5} more")
            else:
                click.echo(f"  {label}: ok")

    if total_issues > 0:
        sys.exit(1)
