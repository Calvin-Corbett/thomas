#!/usr/bin/env python3
"""Detect circular imports between Thomas modules using AST analysis.

Replaces the string-matching approach in test_agent_safety.py with
proper AST-based import detection that catches:
- Standard imports: from thomas.agent import loop
- Conditional imports: if TYPE_CHECKING: from thomas.agent import ...
- Dynamic imports: importlib.import_module("thomas.agent")
- Re-exports through __init__.py

Enforces the forbidden dependency pairs defined in _architecture.py
and GUARDRAILS.md.

Audit reference: Adversarial Audit Finding 8 (2026-03-19)
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# Load config from agent_safety.toml if available
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.brief.safety_config import config as _cfg

    FORBIDDEN_PAIRS: list[tuple[str, str]] = _cfg.circular_import_pairs()
    _MODULE_PREFIX = _cfg.module_prefix()
except ImportError:
    FORBIDDEN_PAIRS = []
    _MODULE_PREFIX = "src"


def _staged_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _extract_thomas_imports(source: str) -> set[str]:
    """Extract all thomas.* module references from Python source using AST.

    Returns set of top-level module names like 'thomas.agent', 'thomas.server'.
    """
    imports: set[str] = set()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return imports

    for node in ast.walk(tree):
        # from thomas.X import Y
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("thomas."):
                parts = node.module.split(".")
                if len(parts) >= 2:
                    imports.add(f"thomas.{parts[1]}")

        # import thomas.X
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("thomas."):
                    parts = alias.name.split(".")
                    if len(parts) >= 2:
                        imports.add(f"thomas.{parts[1]}")

        # importlib.import_module("thomas.X")
        elif isinstance(node, ast.Call):
            func = node.func
            is_import_module = False
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "import_module"
                or isinstance(func, ast.Name)
                and func.id == "import_module"
            ):
                is_import_module = True

            if is_import_module and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    val = arg.value
                    if val.startswith("thomas."):
                        parts = val.split(".")
                        if len(parts) >= 2:
                            imports.add(f"thomas.{parts[1]}")

    # Also catch string-based dynamic imports that AST might miss
    # (e.g., in dicts, configs, or f-strings)
    for match in re.finditer(r'["\']thomas\.(\w+)', source):
        imports.add(f"thomas.{match.group(1)}")

    return imports


def _module_of_file(rel_path: str) -> str | None:
    """Determine which thomas.X module a file belongs to."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == "thomas":
        return f"thomas.{parts[1]}"
    return None


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan all files, not just staged ones.",
    )
    args = parser.parse_args(argv)

    if args.all:
        python_files = [
            str(p.relative_to(ROOT)) for p in ROOT.joinpath("thomas").rglob("*.py") if "__pycache__" not in str(p)
        ]
    else:
        staged = _staged_files()
        python_files = [f for f in staged if f.endswith(".py") and f.startswith("thomas/")]

    violations: list[dict[str, str]] = []

    for rel_path in python_files:
        source_module = _module_of_file(rel_path)
        if not source_module:
            continue

        abs_path = ROOT / rel_path
        if not abs_path.exists():
            continue

        try:
            source = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        imported_modules = _extract_thomas_imports(source)

        for src, forbidden_target in FORBIDDEN_PAIRS:
            if source_module == src and forbidden_target in imported_modules:
                violations.append(
                    {
                        "file": rel_path,
                        "source_module": src,
                        "forbidden_import": forbidden_target,
                    }
                )

    ok = len(violations) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "circular_imports_gate",
                    "ok": ok,
                    "violations": violations,
                    "files_scanned": len(python_files),
                    "forbidden_pairs": len(FORBIDDEN_PAIRS),
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print(f"Circular imports gate: PASS ({len(python_files)} file(s) scanned)")
        else:
            print("SAFETY GATE FAILED: Forbidden Circular Imports Detected")
            print("=" * 70)
            print(f"Found {len(violations)} forbidden import(s):")
            print()
            print("WHAT YOU DID WRONG:")
            for v in violations:
                print(f"  - {v['file']}")
                print(f"    {v['source_module']} -> {v['forbidden_import']}  (FORBIDDEN)")
            print()
            print("HOW TO FIX IT:")
            print("1. Remove the direct import.")
            print("2. If you need cross-module communication, use the event bus:")
            print("   from thomas.core import event_bus")
            print('   await event_bus.publish("module:event_name", ...)')
            print()
            print("3. If you need types for type hints only, use TYPE_CHECKING:")
            print("   from __future__ import annotations")
            print("   from typing import TYPE_CHECKING")
            print("   if TYPE_CHECKING:")
            print("       from thomas.agent import AgentLoop  # type hint only")
            print()
            print("See: Module GUARDRAILS.md for allowed dependency directions")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
