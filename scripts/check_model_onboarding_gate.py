"""Gate model-surface changes behind mandatory onboarding artifacts.

If model-facing files change, require:
- changelog update
- onboarding log update
- at least one research note update
- protocol safety tests present
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_DIRNAME = ROOT.name

MODEL_SURFACE_EXACT: set[str] = {
    "thomas.toml",
    "thomas/core/llm.py",
    "thomas/core/config.py",
    "thomas/server/web/models.json",
    "thomas/models/protocol.py",
}
MODEL_SURFACE_PREFIXES: Sequence[str] = ("thomas/models/",)

REQUIRED_CHANGED_EXACT: set[str] = {
    "CHANGELOG.md",
    "docs/MODEL_ONBOARDING_LOG.md",
}
RESEARCH_NOTES_PREFIX = "library/entries/research-notes/"

REQUIRED_TEST_FILES: Sequence[str] = (
    "tests/test_llm_openai_tool_compat.py",
    "tests/test_agent_loop_tool_policy.py",
    "tests/test_tool_registry_resolution.py",
)


def _git_changed_files(base: str | None, head: str | None) -> list[str]:
    if head is None:
        head = "HEAD"

    range_expr = None
    if base and base.strip("0"):
        range_expr = f"{base}...{head}"
    else:
        range_expr = f"{head}~1...{head}"

    cmd = ["git", "diff", "--name-only", range_expr]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        # Last-resort fallback for shallow/new history.
        fallback = subprocess.run(
            ["git", "diff", "--name-only", head],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if fallback.returncode != 0:
            raise RuntimeError(
                f"Unable to compute git diff.\n"
                f"primary: {' '.join(cmd)} => {proc.stderr.strip()}\n"
                f"fallback: git diff --name-only {head} => {fallback.stderr.strip()}"
            )
        out = fallback.stdout
    else:
        out = proc.stdout
    changed = {_normalize_path(line) for line in out.splitlines() if line.strip()}

    # Include local working tree changes for local developer runs.
    for cmd in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
    ):
        local_proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if local_proc.returncode == 0:
            for line in local_proc.stdout.splitlines():
                p = _normalize_path(line)
                if p:
                    changed.add(p)

    # Include untracked files so local runs catch newly added protocol artifacts.
    untracked_proc = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if untracked_proc.returncode == 0:
        for line in untracked_proc.stdout.splitlines():
            p = _normalize_path(line)
            if p:
                changed.add(p)

    return sorted(changed)


def _normalize_path(path: str) -> str:
    p = str(path).strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    prefix = ROOT_DIRNAME + "/"
    if p.startswith(prefix):
        p = p[len(prefix) :]
    return p


def _is_model_surface(path: str) -> bool:
    if path in MODEL_SURFACE_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in MODEL_SURFACE_PREFIXES)


def _ensure_paths_exist(paths: Iterable[str]) -> list[str]:
    missing = []
    for rel in paths:
        if not (ROOT / rel).exists():
            missing.append(rel)
    return missing


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce model onboarding protocol for model-surface changes.")
    parser.add_argument("--base", default=None, help="Diff base ref/sha (optional)")
    parser.add_argument("--head", default=None, help="Diff head ref/sha (default: HEAD)")
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Explicit changed file path (repeatable). If provided, git diff is skipped.",
    )
    args = parser.parse_args(argv)

    changed: list[str]
    if args.changed_file:
        changed = [_normalize_path(x) for x in args.changed_file if str(x).strip()]
    else:
        changed = _git_changed_files(args.base, args.head)

    if not changed:
        print("Model onboarding gate: no changed files detected; skipping.")
        return 0

    model_surface_changed = [p for p in changed if _is_model_surface(p)]
    if not model_surface_changed:
        print("Model onboarding gate: no model-surface changes detected; skipping.")
        return 0

    print("Model onboarding gate: model-surface changes detected:")
    for p in model_surface_changed:
        print(f"  - {p}")

    failed = False

    missing_required_changed = sorted(REQUIRED_CHANGED_EXACT - set(changed))
    if missing_required_changed:
        failed = True
        print("\nMissing required changed files for model onboarding:")
        for p in missing_required_changed:
            print(f"  - {p}")

    if not any(p.startswith(RESEARCH_NOTES_PREFIX) for p in changed):
        failed = True
        print("\nMissing onboarding research note update.")
        print(f"  - Add/update a file under {RESEARCH_NOTES_PREFIX}")

    required_present = ["docs/MODEL_ONBOARDING_PROTOCOL.md"]
    missing_required_present = _ensure_paths_exist(required_present)
    if missing_required_present:
        failed = True
        print("\nMissing required protocol docs in repository:")
        for p in missing_required_present:
            print(f"  - {p}")

    missing_tests = _ensure_paths_exist(REQUIRED_TEST_FILES)
    if missing_tests:
        failed = True
        print("\nMissing required protocol safety tests:")
        for p in missing_tests:
            print(f"  - {p}")

    if failed:
        return 1

    print("Model onboarding gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
