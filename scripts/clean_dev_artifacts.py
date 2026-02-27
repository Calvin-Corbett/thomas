#!/usr/bin/env python3
"""Clean known local-only development artifacts."""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Keep this list tight and explicit to avoid deleting legitimate project files.
DEV_ARTIFACT_PATTERNS: Sequence[str] = (
    "%s",
    "tmp_companion_*.png",
    "thomas/tmp_script.py",
)
VERIFICATION_PRESETS: dict[str, str] = {
    "strict-worktree": "python -m thomas status --json --strict-worktree",
}
DELETION_POLICY = (
    "Deletion is allowed only after explicit end-to-end verification commands pass "
    "(use --verify-preset/--verify-command with --apply)."
)


def _normalize(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _is_match(path: str, patterns: Sequence[str]) -> bool:
    normalized = _normalize(path)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def _git_tracked_paths(repo_root: Path) -> set[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git ls-files failed")
    return {_normalize(line) for line in proc.stdout.splitlines() if _normalize(line)}


def tracked_dev_artifacts(
    repo_root: Path = ROOT,
    *,
    patterns: Sequence[str] = DEV_ARTIFACT_PATTERNS,
) -> list[str]:
    tracked = _git_tracked_paths(repo_root)
    return sorted(path for path in tracked if _is_match(path, patterns))


def discover_dev_artifacts(
    repo_root: Path = ROOT,
    *,
    patterns: Sequence[str] = DEV_ARTIFACT_PATTERNS,
) -> list[str]:
    discovered: set[str] = set()
    for pattern in patterns:
        for candidate in repo_root.glob(pattern):
            if not candidate.exists():
                continue
            rel = _normalize(candidate.relative_to(repo_root).as_posix())
            if rel:
                discovered.add(rel)
    return sorted(discovered)


def evaluate(
    repo_root: Path = ROOT,
    *,
    include_tracked: bool = False,
) -> dict[str, object]:
    discovered = discover_dev_artifacts(repo_root)
    tracked = _git_tracked_paths(repo_root)

    tracked_matches: list[str] = []
    untracked_matches: list[str] = []
    for rel in discovered:
        if rel in tracked:
            tracked_matches.append(rel)
        else:
            untracked_matches.append(rel)

    removable = list(untracked_matches)
    if include_tracked:
        removable.extend(tracked_matches)
    removable = sorted(set(removable))

    return {
        "discovered": discovered,
        "tracked_matches": sorted(tracked_matches),
        "untracked_matches": sorted(untracked_matches),
        "removable": removable,
        "include_tracked": bool(include_tracked),
        "ok": True,
    }


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def _run_verification_commands(commands: Sequence[str], repo_root: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for command in [str(item or "").strip() for item in commands if str(item or "").strip()]:
        proc = subprocess.run(
            command,
            cwd=repo_root,
            shell=True,
            capture_output=True,
            text=True,
        )
        results.append(
            {
                "command": command,
                "exit_code": int(proc.returncode),
                "ok": proc.returncode == 0,
            }
        )
    return results


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean known local development artifacts.")
    parser.add_argument("--apply", action="store_true", help="Delete detected artifacts.")
    parser.add_argument(
        "--verify-preset",
        action="append",
        choices=sorted(VERIFICATION_PRESETS.keys()),
        default=[],
        help="Named end-to-end verification preset required for --apply (repeatable).",
    )
    parser.add_argument(
        "--verify-command",
        action="append",
        default=[],
        help="Additional end-to-end verification command for --apply (repeatable).",
    )
    parser.add_argument(
        "--include-tracked",
        action="store_true",
        help="Include tracked matches when deleting (default: only untracked files).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        result = evaluate(ROOT, include_tracked=bool(args.include_tracked))
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        else:
            print(f"Dev artifact cleanup: FAIL\n- {exc}")
        return 1

    selected_presets = [str(item or "").strip() for item in list(args.verify_preset or []) if str(item or "").strip()]
    preset_commands = [VERIFICATION_PRESETS[name] for name in selected_presets]
    custom_commands = [str(item or "").strip() for item in list(args.verify_command or []) if str(item or "").strip()]
    verification_commands = [*preset_commands, *custom_commands]
    verification_results: list[dict[str, object]] = []
    verification_ok = True
    failure_message = ""
    if args.apply:
        if not verification_commands:
            verification_ok = False
            # Keep historical wording for compatibility with existing test
            # contracts while documenting the newer preset option.
            failure_message = "--apply requires at least one --verify-command " "(or --verify-preset)"
        else:
            verification_results = _run_verification_commands(verification_commands, ROOT)
            verification_ok = all(bool(item.get("ok", False)) for item in verification_results)
            if not verification_ok:
                failed = [
                    f"{item.get('command')} (exit={item.get('exit_code')})"
                    for item in verification_results
                    if not bool(item.get("ok", False))
                ]
                failure_message = "verification failed: " + ", ".join(failed)

    removed: list[str] = []
    if args.apply and verification_ok:
        for rel in list(result["removable"]):
            path = ROOT / rel
            _remove_path(path)
            removed.append(rel)

    payload: dict[str, object] = {
        "applied": bool(args.apply and verification_ok),
        "include_tracked": bool(args.include_tracked),
        "policy": DELETION_POLICY,
        "verification_required": bool(args.apply),
        "verification_presets": selected_presets,
        "verification_commands": verification_commands,
        "verification_ok": bool(verification_ok),
        "verification_results": verification_results,
        "removed": removed,
        "removed_count": len(removed),
        "discovered": list(result["discovered"]),
        "tracked_matches": list(result["tracked_matches"]),
        "untracked_matches": list(result["untracked_matches"]),
        "ok": bool(verification_ok),
    }
    if failure_message:
        payload["error"] = failure_message

    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 0 if bool(payload["ok"]) else 1

    if not bool(payload["ok"]):
        print("Dev artifact cleanup: FAIL")
        print(f"- {failure_message}")
        print(f"- policy: {DELETION_POLICY}")
        return 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Dev artifact cleanup: {mode}")
    print(f"- policy: {DELETION_POLICY}")
    print(f"- discovered: {len(payload['discovered'])}")
    print(f"- tracked matches: {len(payload['tracked_matches'])}")
    print(f"- untracked matches: {len(payload['untracked_matches'])}")
    print(f"- removed: {payload['removed_count']}")
    if payload["tracked_matches"] and not args.include_tracked:
        sample = ", ".join(payload["tracked_matches"][:5])
        print(f"- skipped tracked matches: {sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
