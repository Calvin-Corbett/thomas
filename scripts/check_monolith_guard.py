"""Anti-monolith guard for Thomas.

Fails when source files exceed configured hard limits unless explicitly
baselined. Baselined files are still bounded by a per-file max line cap.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


DEFAULT_HARD_LIMITS: Dict[str, int] = {
    "py": 1200,
    "js": 1200,
    "ts": 1200,
    "css": 1600,
    "html": 1000,
}

DEFAULT_SCAN_ROOTS: List[str] = ["thomas"]
DEFAULT_BASELINE = "docs/monolith_guard_baseline.json"

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "runtime",
    "Inbox",
    "output",
    "pack",
    "patches",
    "tasks",
    ".inbox_extract_20260210_234207",
    ".feature_backups",
}


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        return sum(1 for _ in fh)


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _iter_candidate_files(
    repo_root: Path,
    scan_roots: Iterable[str],
    hard_limits: Dict[str, int],
) -> Iterable[Tuple[Path, str]]:
    for rel_root in scan_roots:
        base = (repo_root / rel_root).resolve()
        if not base.exists() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if _is_skipped(path):
                continue
            ext = path.suffix.lower().lstrip(".")
            if ext not in hard_limits:
                continue
            yield path, ext


def load_baseline(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "scan_roots": list(DEFAULT_SCAN_ROOTS),
            "hard_limits": dict(DEFAULT_HARD_LIMITS),
            "allowed_large_files": {},
        }
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Baseline file must be a JSON object.")
    return raw


def run_guard(repo_root: Path, baseline_path: Path) -> Dict[str, Any]:
    baseline = load_baseline(baseline_path)
    hard_limits = dict(DEFAULT_HARD_LIMITS)
    if isinstance(baseline.get("hard_limits"), dict):
        for key, val in baseline["hard_limits"].items():
            try:
                hard_limits[str(key)] = int(val)
            except Exception:
                continue

    scan_roots = list(DEFAULT_SCAN_ROOTS)
    if isinstance(baseline.get("scan_roots"), list):
        scan_roots = [str(x) for x in baseline["scan_roots"] if str(x).strip()]
        if not scan_roots:
            scan_roots = list(DEFAULT_SCAN_ROOTS)

    allowed_raw = baseline.get("allowed_large_files")
    allowed = allowed_raw if isinstance(allowed_raw, dict) else {}

    violations: List[Dict[str, Any]] = []
    measured: List[Dict[str, Any]] = []

    for path, ext in _iter_candidate_files(repo_root, scan_roots, hard_limits):
        rel = path.relative_to(repo_root).as_posix()
        lines = _line_count(path)
        hard = int(hard_limits.get(ext, 0) or 0)
        measured.append({"path": rel, "lines": lines, "ext": ext, "hard_limit": hard})
        if lines <= hard:
            continue

        entry = allowed.get(rel)
        if isinstance(entry, dict):
            try:
                max_lines = int(entry.get("max_lines", hard))
            except Exception:
                max_lines = hard
            if lines > max_lines:
                violations.append(
                    {
                        "path": rel,
                        "ext": ext,
                        "lines": lines,
                        "hard_limit": hard,
                        "max_lines": max_lines,
                        "reason": "baselined file exceeded max_lines",
                    }
                )
            continue

        violations.append(
            {
                "path": rel,
                "ext": ext,
                "lines": lines,
                "hard_limit": hard,
                "reason": "file exceeds hard limit and is not baselined",
            }
        )

    return {
        "ok": len(violations) == 0,
        "repo_root": str(repo_root),
        "baseline_path": str(baseline_path),
        "scan_roots": scan_roots,
        "violations": violations,
        "measured_count": len(measured),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when source files exceed anti-monolith limits.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred from script location).",
    )
    parser.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help=f"Baseline JSON path, relative to repo root by default (default: {DEFAULT_BASELINE}).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (repo_root / baseline_path).resolve()

    result = run_guard(repo_root, baseline_path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print(
                f"Monolith guard OK. Scanned {result['measured_count']} files "
                f"under {', '.join(result['scan_roots'])}."
            )
        else:
            print(
                f"Monolith guard FAILED: {len(result['violations'])} violation(s). "
                "Split modules or update baseline intentionally."
            )
            for row in result["violations"]:
                hard = row.get("hard_limit")
                max_lines = row.get("max_lines")
                max_part = f", max {max_lines}" if max_lines is not None else ""
                print(
                    f"- {row.get('path')}: {row.get('lines')} lines "
                    f"(hard {hard}{max_part}) -> {row.get('reason')}"
                )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
