"""Guard repo hygiene (tracked layout + dirty worktree checks)."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = "docs/repo_hygiene_baseline.json"


def _normalize(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _git_ls_files(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git ls-files failed")
    out = []
    for raw in proc.stdout.splitlines():
        p = _normalize(raw)
        if p:
            out.append(p)
    return sorted(set(out))


def _git_status_porcelain(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git status --porcelain failed")
    out: list[str] = []
    for raw in proc.stdout.splitlines():
        line = str(raw or "").rstrip()
        if line:
            out.append(line)
    return out


def _load_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing baseline file: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Repo hygiene baseline must be a JSON object.")
    return raw


def _any_suffix(path: str, suffixes: Iterable[str]) -> bool:
    p = _normalize(path).lower()
    for raw in suffixes:
        s = str(raw or "").strip().lower()
        if s and p.endswith(s):
            return True
    return False


def _any_prefix(path: str, prefixes: Iterable[str]) -> bool:
    p = _normalize(path).lower()
    for raw in prefixes:
        prefix = _normalize(str(raw or "")).strip().lower()
        if prefix and p.startswith(prefix):
            return True
    return False


def _porcelain_path(line: str) -> str:
    raw = str(line or "")
    if len(raw) <= 3:
        return _normalize(raw)
    return _normalize(raw[3:])


def _sample_paths(paths: Sequence[str], *, limit: int = 5) -> str:
    if not paths:
        return ""
    cap = max(1, int(limit))
    sample = ", ".join(str(p) for p in paths[:cap])
    if len(paths) > cap:
        sample += f", ... (+{len(paths) - cap} more)"
    return sample


def _tracked_root_files(tracked_paths: Sequence[str]) -> list[str]:
    return sorted(
        {
            normalized
            for path in tracked_paths
            for normalized in [_normalize(path)]
            if normalized and "/" not in normalized
        }
    )


def build_synced_baseline(baseline: dict[str, Any], tracked_paths: Sequence[str]) -> dict[str, Any]:
    synced = dict(baseline)
    root_files = _tracked_root_files(tracked_paths)
    synced["allowed_tracked_root_files"] = root_files
    synced["max_tracked_root_files"] = len(root_files)
    return synced


def evaluate_worktree_clean(status_lines: Sequence[str]) -> dict[str, Any]:
    staged_paths: list[str] = []
    unstaged_paths: list[str] = []
    untracked_paths: list[str] = []
    raw_entries = [str(line or "").rstrip() for line in status_lines if str(line or "").strip()]

    for line in raw_entries:
        if line.startswith("??"):
            path = _porcelain_path(line)
            if path:
                untracked_paths.append(path)
            continue
        if line.startswith("!!"):
            continue

        index_status = line[0] if len(line) > 0 else " "
        worktree_status = line[1] if len(line) > 1 else " "
        path = _porcelain_path(line)
        if index_status not in (" ", "?", "!") and path:
            staged_paths.append(path)
        if worktree_status not in (" ", "?", "!") and path:
            unstaged_paths.append(path)

    staged_paths = sorted(set(staged_paths))
    unstaged_paths = sorted(set(unstaged_paths))
    untracked_paths = sorted(set(untracked_paths))

    violations: list[str] = []
    if staged_paths:
        violations.append(f"{len(staged_paths)} staged path(s): {_sample_paths(staged_paths)}")
    if unstaged_paths:
        violations.append(f"{len(unstaged_paths)} unstaged path(s): {_sample_paths(unstaged_paths)}")
    if untracked_paths:
        violations.append(f"{len(untracked_paths)} untracked path(s): {_sample_paths(untracked_paths)}")

    return {
        "ok": not violations,
        "entry_count": len(raw_entries),
        "staged_paths": staged_paths,
        "unstaged_paths": unstaged_paths,
        "untracked_paths": untracked_paths,
        "summary": {
            "staged_count": len(staged_paths),
            "unstaged_count": len(unstaged_paths),
            "untracked_count": len(untracked_paths),
        },
        "violations": violations,
    }


def evaluate_generated_artifacts(untracked_paths: Sequence[str], baseline: dict[str, Any]) -> dict[str, Any]:
    untracked = sorted({_normalize(p) for p in untracked_paths if _normalize(p)})
    forbidden_prefixes = [
        _normalize(p)
        for p in (
            baseline.get("forbidden_untracked_prefixes") or baseline.get("generated_artifact_untracked_prefixes") or []
        )
        if _normalize(p)
    ]
    blocked_suffixes = [
        str(s)
        for s in (
            baseline.get("blocked_untracked_suffixes") or baseline.get("generated_artifact_untracked_suffixes") or []
        )
        if str(s).strip()
    ]

    prefix_matches = sorted([p for p in untracked if _any_prefix(p, forbidden_prefixes)])
    suffix_matches = sorted([p for p in untracked if _any_suffix(p, blocked_suffixes)])
    offenders = sorted(set(prefix_matches + suffix_matches))

    violations: list[str] = []
    if offenders:
        violations.append(f"generated artifact paths detected ({len(offenders)}): {_sample_paths(offenders)}")

    return {
        "ok": not violations,
        "forbidden_untracked_prefixes": forbidden_prefixes,
        "blocked_untracked_suffixes": blocked_suffixes,
        "prefix_matches": prefix_matches,
        "suffix_matches": suffix_matches,
        "offenders": offenders,
        "violations": violations,
    }


def evaluate_hygiene(tracked_paths: Sequence[str], baseline: dict[str, Any]) -> dict[str, Any]:
    tracked = sorted({_normalize(p) for p in tracked_paths if _normalize(p)})

    allowed_root = {_normalize(p) for p in (baseline.get("allowed_tracked_root_files") or []) if _normalize(p)}
    max_root = int(baseline.get("max_tracked_root_files", 25) or 25)
    forbidden_prefixes = [_normalize(p) for p in (baseline.get("forbidden_tracked_prefixes") or []) if _normalize(p)]
    blocked_suffixes = [str(s) for s in (baseline.get("blocked_tracked_suffixes") or []) if str(s).strip()]

    tracked_root_files = _tracked_root_files(tracked)
    unexpected_root_files = sorted([p for p in tracked_root_files if p not in allowed_root])
    forbidden_tracked_paths = sorted([p for p in tracked if any(p.startswith(prefix) for prefix in forbidden_prefixes)])
    blocked_suffix_paths = sorted([p for p in tracked if _any_suffix(p, blocked_suffixes)])

    violations: list[str] = []
    if len(tracked_root_files) > max_root:
        violations.append(
            f"tracked root file count {len(tracked_root_files)} exceeds max_tracked_root_files={max_root}"
        )
    if unexpected_root_files:
        violations.append(f"unexpected tracked root files: {', '.join(unexpected_root_files)}")
    if forbidden_tracked_paths:
        violations.append(f"tracked files in forbidden prefixes: {', '.join(forbidden_tracked_paths)}")
    if blocked_suffix_paths:
        violations.append(f"tracked files with blocked suffixes: {', '.join(blocked_suffix_paths)}")

    return {
        "ok": not violations,
        "tracked_total": len(tracked),
        "tracked_root_files": tracked_root_files,
        "unexpected_root_files": unexpected_root_files,
        "forbidden_tracked_paths": forbidden_tracked_paths,
        "blocked_suffix_paths": blocked_suffix_paths,
        "violations": violations,
    }


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when repo layout hygiene constraints are violated.")
    parser.add_argument("--repo-root", default=None, help="Repository root (default: inferred from script path).")
    parser.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help=f"Baseline JSON path, relative to repo root by default (default: {DEFAULT_BASELINE}).",
    )
    parser.add_argument(
        "--require-clean-worktree",
        dest="require_clean_worktree",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail when git status reports staged/unstaged/untracked files (default: enabled).",
    )
    parser.add_argument(
        "--sync-baseline",
        action="store_true",
        help="Update baseline root-file allowlist/max from current tracked files and exit.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)
    gate_name = "repo_hygiene"

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (repo_root / baseline_path).resolve()

    try:
        baseline = _load_baseline(baseline_path)
        tracked = _git_ls_files(repo_root)
        if args.sync_baseline:
            synced = build_synced_baseline(baseline, tracked)
            baseline_path.write_text(json.dumps(synced, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload = {
                "ok": True,
                "gate": gate_name,
                "action": "sync_baseline",
                "repo_root": str(repo_root),
                "baseline_path": str(baseline_path),
                "tracked_root_file_count": len(list(synced.get("allowed_tracked_root_files") or [])),
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Repo hygiene baseline synced: " f"tracked_root_file_count={payload['tracked_root_file_count']}")
            return 0

        worktree = evaluate_worktree_clean(_git_status_porcelain(repo_root))
        result = evaluate_hygiene(tracked, baseline)
        result["worktree"] = worktree
        result["worktree_clean"] = bool(worktree.get("ok", False))
        generated_artifacts = evaluate_generated_artifacts(list(worktree.get("untracked_paths") or []), baseline)
        result["generated_artifacts"] = generated_artifacts
        if not bool(generated_artifacts.get("ok", True)):
            for msg in list(generated_artifacts.get("violations") or []):
                result["violations"].append(msg)
            result["ok"] = False
        if bool(args.require_clean_worktree) and not bool(worktree.get("ok", False)):
            for msg in list(worktree.get("violations") or []):
                result["violations"].append(f"dirty worktree: {msg}")
            result["ok"] = False
    except Exception as exc:
        message = f"Repo hygiene gate failed: {exc}"
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "gate": gate_name,
                        "error": message,
                        "repo_root": str(repo_root),
                        "baseline_path": str(baseline_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(message)
        return 1

    if args.json:
        payload = dict(result)
        payload.update(
            {
                "gate": gate_name,
                "repo_root": str(repo_root),
                "baseline_path": str(baseline_path),
                "require_clean_worktree": bool(args.require_clean_worktree),
            }
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    if result["ok"]:
        worktree_summary = dict((result.get("worktree") or {}).get("summary") or {})
        print(
            "Repo hygiene gate: OK "
            f"(tracked files={result['tracked_total']}, "
            f"tracked root files={len(result['tracked_root_files'])}, "
            f"staged={int(worktree_summary.get('staged_count', 0))}, "
            f"unstaged={int(worktree_summary.get('unstaged_count', 0))}, "
            f"untracked={int(worktree_summary.get('untracked_count', 0))})"
        )
        return 0

    print("Repo hygiene gate FAILED:")
    for msg in result["violations"]:
        print(f"- {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
