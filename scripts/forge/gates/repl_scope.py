#!/usr/bin/env python3
"""Guardrail for REPL-only tasks.

Checks current git changes for files outside the allowed scope and exits non-zero
if likely web/UI areas changed during a REPL-only task.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ScopePolicy:
    disallow_prefixes: tuple[str, ...]


SCOPE_POLICIES: dict[str, ScopePolicy] = {
    "repl": ScopePolicy(
        disallow_prefixes=(
            "thomas/server/web/",
            "apps/site/",
            "apps/site/src/app/",
            "apps/site/src/components/",
            "docs/site/",
        )
    )
}


def get_changed_paths(repo_root: Path) -> set[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    )
    changed: set[str] = set()

    for line in completed.stdout.splitlines():
        if not line:
            continue
        payload = line[3:]
        if line.startswith("??"):
            path = payload
        else:
            if " -> " in payload:
                path = payload.split(" -> ", 1)[1]
            else:
                path = payload
        if path:
            changed.add(path.strip())
    return changed


def run(scope: str, allowlist_path: list[str], verbose: bool = False) -> int:
    policy = SCOPE_POLICIES[scope]
    if verbose:
        print(f"Checking scope '{scope}' against {len(policy.disallow_prefixes)} disallowed prefixes")

    changed = get_changed_paths(REPO_ROOT)
    if verbose:
        print(f"Detected {len(changed)} changed file paths")

    if allowlist_path:
        allowlist = tuple(path.rstrip("/") + "/" for path in allowlist_path)
        if verbose:
            print("Allowlist:")
            for path in allowlist:
                print(f"  - {path}")
    else:
        allowlist = tuple()

    normalized_paths = {path.replace("\\", "/") for path in changed}
    violations = []

    def is_allowed(path: str) -> bool:
        if not allowlist:
            return False
        return any(path.startswith(prefix) for prefix in allowlist)

    for path in sorted(normalized_paths):
        if any(path.startswith(prefix) for prefix in policy.disallow_prefixes) and not is_allowed(path):
            violations.append(path)

    if not violations:
        if verbose:
            print("Scope check passed.")
        return 0

    print(f"Scope '{scope}' check failed: {len(violations)} path(s) are outside REPL scope", file=sys.stderr)
    for path in violations:
        print(f"  - {path}", file=sys.stderr)
    print("\nIf these are intended web changes, rerun with:", file=sys.stderr)
    print("  python scripts/forge/gates/repl_scope.py --scope repl --allow thomas/server/web", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Check git changes against a REPL-only scope policy.")
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPE_POLICIES.keys()),
        default="repl",
        help="Scope to validate against",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Path prefix to allow for this run (can pass multiple times)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print diagnostic lines while validating",
    )
    args = parser.parse_args()
    return run(args.scope, args.allow, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
