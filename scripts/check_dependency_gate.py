#!/usr/bin/env python3
"""Detect new dependency additions and require acknowledgment.

When pyproject.toml or requirements files are staged, this gate
checks if NEW dependencies were added (not just version bumps).
New dependencies require the verification record to include a
dependencies_reviewed field.

This prevents agents from silently adding packages that may be
unmaintained, have vulnerabilities, or conflict with existing deps.

Gap closed: 5 (agent can add dependencies freely)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_RECORD = ROOT / ".git" / "agent_verification.json"

DEPENDENCY_FILES = [
    "pyproject.toml",
    "requirements-lock.txt",
    "requirements.txt",
]


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


def _staged_diff(filepath: str) -> str:
    """Get the diff for a specific staged file."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--", filepath],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _extract_new_deps_from_pyproject(diff: str) -> list[str]:
    """Extract newly added dependency names from pyproject.toml diff."""
    new_deps = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:].strip()
        # Match patterns like: "requests>=2.0", "flask", "aiohttp~=3.9"
        dep_match = re.match(r'^"?([a-zA-Z0-9_-]+)', content)
        if dep_match:
            dep_name = dep_match.group(1).lower()
            # Filter out common non-dependency lines
            if dep_name not in (
                "version",
                "name",
                "description",
                "python",
                "requires",
                "readme",
                "license",
                "authors",
                "classifiers",
                "dependencies",
                "optional",
                "build",
                "tool",
                "project",
            ):
                new_deps.append(dep_name)
    return new_deps


def _extract_new_deps_from_requirements(diff: str) -> list[str]:
    """Extract newly added dependency names from requirements.txt diff."""
    new_deps = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:].strip()
        if not content or content.startswith("#"):
            continue
        # Match package name before version specifier
        dep_match = re.match(r"^([a-zA-Z0-9_-]+)", content)
        if dep_match:
            new_deps.append(dep_match.group(1).lower())
    return new_deps


def _load_verification_record() -> dict | None:
    if not VERIFICATION_RECORD.exists():
        return None
    try:
        return json.loads(VERIFICATION_RECORD.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    staged = _staged_files()
    dep_files_staged = [f for f in staged if f in DEPENDENCY_FILES]

    if not dep_files_staged:
        if args.json:
            print(json.dumps({"gate": "dependency", "ok": True, "skipped": True}, sort_keys=True))
        else:
            print("Dependency gate: PASS (no dependency files staged)")
        return 0

    # Check each dependency file for new additions
    all_new_deps: list[str] = []
    for dep_file in dep_files_staged:
        diff = _staged_diff(dep_file)
        if not diff:
            continue

        if dep_file == "pyproject.toml":
            new_deps = _extract_new_deps_from_pyproject(diff)
        else:
            new_deps = _extract_new_deps_from_requirements(diff)

        all_new_deps.extend(new_deps)

    if not all_new_deps:
        if args.json:
            print(
                json.dumps({"gate": "dependency", "ok": True, "reason": "no new dependencies detected"}, sort_keys=True)
            )
        else:
            print("Dependency gate: PASS (dependency files changed but no new packages)")
        return 0

    # New deps found — check verification record
    record = _load_verification_record()
    reviewed = False
    if record:
        reviewed = bool(record.get("dependencies_reviewed", False))

    ok = reviewed

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "dependency",
                    "ok": ok,
                    "new_dependencies": all_new_deps,
                    "dependencies_reviewed": reviewed,
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print(f"Dependency gate: PASS ({len(all_new_deps)} new dep(s), reviewed)")
        else:
            print("SAFETY GATE FAILED: New Dependencies Added Without Review")
            print("=" * 70)
            print(f"Found {len(all_new_deps)} new dependency/dependencies:")
            for dep in all_new_deps[:10]:
                print(f"  - {dep}")
            if len(all_new_deps) > 10:
                print(f"  ... and {len(all_new_deps) - 10} more")
            print()
            print("HOW TO FIX IT:")
            print("1. Verify each dependency is:")
            print("   - Actively maintained")
            print("   - Free of known vulnerabilities")
            print("   - Actually needed for your changes")
            print("   - Compatible with existing dependencies")
            print()
            print("2. Create a verification record acknowledging the review:")
            print("   python scripts/create_verification_record.py \\")
            print('     --test-command "python -m pytest tests/ -v" \\')
            print('     --task "your task"')
            print()
            print("   Then add dependencies_reviewed: true to the record.")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
