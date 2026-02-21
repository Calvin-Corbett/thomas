"""Guard repo layout drift (root clutter and tracked artifact pollution)."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = "docs/repo_hygiene_baseline.json"


def _normalize(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _git_ls_files(repo_root: Path) -> List[str]:
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


def _load_baseline(path: Path) -> Dict[str, Any]:
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


def evaluate_hygiene(tracked_paths: Sequence[str], baseline: Dict[str, Any]) -> Dict[str, Any]:
    tracked = sorted({_normalize(p) for p in tracked_paths if _normalize(p)})

    allowed_root = {
        _normalize(p)
        for p in (baseline.get("allowed_tracked_root_files") or [])
        if _normalize(p)
    }
    max_root = int(baseline.get("max_tracked_root_files", 25) or 25)
    forbidden_prefixes = [_normalize(p) for p in (baseline.get("forbidden_tracked_prefixes") or []) if _normalize(p)]
    blocked_suffixes = [str(s) for s in (baseline.get("blocked_tracked_suffixes") or []) if str(s).strip()]

    tracked_root_files = sorted([p for p in tracked if "/" not in p])
    unexpected_root_files = sorted([p for p in tracked_root_files if p not in allowed_root])
    forbidden_tracked_paths = sorted(
        [p for p in tracked if any(p.startswith(prefix) for prefix in forbidden_prefixes)]
    )
    blocked_suffix_paths = sorted([p for p in tracked if _any_suffix(p, blocked_suffixes)])

    violations: List[str] = []
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
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (repo_root / baseline_path).resolve()

    try:
        baseline = _load_baseline(baseline_path)
        tracked = _git_ls_files(repo_root)
        result = evaluate_hygiene(tracked, baseline)
    except Exception as exc:
        print(f"Repo hygiene gate failed: {exc}")
        return 1

    if args.json:
        payload = dict(result)
        payload.update({"repo_root": str(repo_root), "baseline_path": str(baseline_path)})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    if result["ok"]:
        print(
            "Repo hygiene gate: OK "
            f"(tracked files={result['tracked_total']}, tracked root files={len(result['tracked_root_files'])})"
        )
        return 0

    print("Repo hygiene gate FAILED:")
    for msg in result["violations"]:
        print(f"- {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
