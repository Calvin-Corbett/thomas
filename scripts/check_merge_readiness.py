#!/usr/bin/env python3
"""Run repo-wide merge and release readiness checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
MERGE_GATE_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("repo_hygiene", (sys.executable, "scripts/check_repo_hygiene.py")),
    ("plan_structure", (sys.executable, "scripts/forge/gates/plan_structure_gate.py")),
    ("release_hygiene", (sys.executable, "scripts/check_release_hygiene.py")),
    (
        "architecture",
        (sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "tests/test_architecture.py", "-x", "--tb=short", "-q"),
    ),
    ("workboard_audit_backstop", (sys.executable, "scripts/workboard_audit_backstop.py")),
    ("auto_checks_quick", (sys.executable, "scripts/auto_checks.py", "--quick")),
)


def evaluate_merge_readiness(
    *,
    repo_root: Path = ROOT,
    commands: Sequence[tuple[str, Sequence[str]]] = MERGE_GATE_COMMANDS,
) -> tuple[bool, list[dict[str, object]]]:
    results: list[dict[str, object]] = []
    ok = True
    for name, command in commands:
        proc = subprocess.run(
            list(command),
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        results.append(
            {
                "name": name,
                "ok": proc.returncode == 0,
                "returncode": int(proc.returncode),
                "command": list(command),
                "output": output,
            }
        )
        if proc.returncode != 0:
            ok = False
    return ok, results


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run repo-wide merge readiness gates.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    ok, results = evaluate_merge_readiness()
    if args.json:
        print(json.dumps({"ok": ok, "results": results}, sort_keys=True))
        return 0 if ok else 1

    print("Merge readiness: PASS" if ok else "Merge readiness: FAIL")
    for result in results:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"- {result['name']}: {status}")
        output = str(result.get("output") or "")
        if output:
            for line in output.splitlines()[:20]:
                print(f"  {line}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
