"""Anti-monolith guard for Thomas.

Fails when source files exceed configured hard limits unless explicitly
baselined. Baselined files are still bounded by a per-file max line cap.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from datetime import date
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HARD_LIMITS: dict[str, int] = {
    "py": 1200,
    "js": 1200,
    "mjs": 1200,
    "cjs": 1200,
    "jsx": 1200,
    "ts": 1200,
    "tsx": 1200,
    "css": 1600,
    "html": 1000,
}

DEFAULT_SCAN_ROOTS: list[str] = ["."]
DEFAULT_BASELINE = "docs/monolith_guard_baseline.json"
_FORBIDDEN_PART_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.part\d+\.[^.]+$", re.IGNORECASE),
    re.compile(r"_part\d+\.\w+$", re.IGNORECASE),
    re.compile(r"^part-\d+[a-z]?\.\w+$", re.IGNORECASE),
)
_FORBIDDEN_SPLIT_DIR_PATTERNS: tuple[re.Pattern[str], ...] = (re.compile(r"[_-]parts?$", re.IGNORECASE),)
_ALLOWED_PART_FILE_PATTERNS: tuple[str, ...] = ()
_FORBIDDEN_LOADER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^\s*def\s+_load_monolith_parts\s*\("),
    re.compile(r"(?m)_load_monolith_parts\s*=\s*"),
    re.compile(r"(?m)_load_monolith_parts\s*\("),
)

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".next",
    ".open-next",
    ".nuxt",
    "build",
    "coverage",
    "dist",
    "generated",
    "runtime",
    "Inbox",
    "output",
    "pack",
    "patches",
    "node_modules",
    "tasks",
    ".inbox_extract_20260210_234207",
    ".feature_backups",
}


def _runtime_protection_disabled() -> bool:
    """Check if a human has temporarily disabled runtime protection."""
    flag = ROOT / "runtime" / ".runtime_protection_disabled"
    return flag.is_file()


def _parse_iso_date(text: str) -> date | None:
    value = str(text or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        return sum(1 for _ in fh)


def _looks_like_legacy_monolith_file(path: Path) -> bool:
    if any(pattern.search(path.name) for pattern in _FORBIDDEN_PART_FILE_PATTERNS):
        return True
    # Check parent directories for split-dir patterns (e.g. app_parts/)
    for parent in path.parents:
        if any(pattern.search(parent.name) for pattern in _FORBIDDEN_SPLIT_DIR_PATTERNS):
            # Allow GUARDRAILS.md / README.md inside split dirs (they document debt)
            return path.name.upper() not in ("GUARDRAILS.MD", "README.MD")
    return False


def _is_allowed_split_file(path: Path, rel: str) -> bool:
    rel_norm = rel.replace("\\", "/")
    return any(fnmatch(rel_norm, pattern) for pattern in _ALLOWED_PART_FILE_PATTERNS)


def _contains_legacy_monolith_loader(path: Path) -> bool:
    if path.suffix.lower() != ".py":
        return False
    if path.name == "check_monolith_guard.py":
        return False
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        sample = fh.read()
    return any(pattern.search(sample) is not None for pattern in _FORBIDDEN_LOADER_PATTERNS)


def _normalize_rel_path(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _iter_candidate_files(
    repo_root: Path,
    scan_roots: Iterable[str],
    hard_limits: dict[str, int],
) -> Iterable[tuple[Path, str]]:
    for rel_root in scan_roots:
        base = (repo_root / rel_root).resolve()
        if not base.exists() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if _is_skipped(path):
                continue
            if not path.is_file():
                continue
            ext = path.suffix.lower().lstrip(".")
            if ext not in hard_limits:
                continue
            yield path, ext


def load_baseline(path: Path) -> dict[str, Any]:
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


def _git_changed_files(repo_root: Path, *, base_ref: str, head_ref: str) -> set[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or "unknown git diff failure"
        raise RuntimeError(msg)
    out: set[str] = set()
    for line in proc.stdout.splitlines():
        rel = _normalize_rel_path(line)
        if rel:
            out.add(rel)
    return out


def _git_staged_files(repo_root: Path) -> set[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or "unknown git diff --cached failure"
        raise RuntimeError(msg)
    out: set[str] = set()
    for line in proc.stdout.splitlines():
        rel = _normalize_rel_path(line)
        if rel:
            out.add(rel)
    return out


def _git_tracked_files(repo_root: Path) -> set[str] | None:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        text=False,
    )
    if proc.returncode != 0:
        return None
    out: set[str] = set()
    for raw in proc.stdout.split(b"\x00"):
        if not raw:
            continue
        rel = _normalize_rel_path(raw.decode("utf-8", errors="ignore"))
        if rel:
            out.add(rel)
    return out


def _git_blob_line_count(repo_root: Path, *, ref: str, rel_path: str) -> int | None:
    rel = _normalize_rel_path(rel_path)
    if not rel:
        return None
    proc = subprocess.run(
        ["git", "show", f"{ref}:{rel}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    text = proc.stdout
    if not text:
        return 0
    return len(text.splitlines())


def _git_ref_exists(repo_root: Path, ref: str) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def run_guard(
    repo_root: Path,
    baseline_path: Path,
    *,
    base_ref: str | None = None,
    head_ref: str = "HEAD",
    staged_only: bool = False,
) -> dict[str, Any]:
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
    waiver_policy_raw = baseline.get("waiver_policy")
    waiver_policy = waiver_policy_raw if isinstance(waiver_policy_raw, dict) else {}
    require_waiver_metadata = bool(waiver_policy.get("require_metadata", True))
    allow_legacy_reason = bool(waiver_policy.get("allow_legacy_reason", False))
    default_owner = str(waiver_policy.get("default_owner", "") or "").strip()
    default_expires = str(waiver_policy.get("default_expires_on", "") or "").strip()
    default_growth = 0
    try:
        default_growth = int(waiver_policy.get("default_max_growth_lines", 0))
    except Exception:
        default_growth = 0
    if default_growth < 0:
        default_growth = 0
    soft_limit = 0
    try:
        soft_limit = int(waiver_policy.get("unbaselined_soft_limit_lines", 0))
    except Exception:
        soft_limit = 0
    if soft_limit < 0:
        soft_limit = 0
    enforce_soft_limit_changed_only = bool(waiver_policy.get("enforce_soft_limit_changed_only", True))

    violations: list[dict[str, Any]] = []
    measured: list[dict[str, Any]] = []
    normalized_base_ref = str(base_ref or "").strip() or None
    growth_context: dict[str, Any] = {
        "staged_only": bool(staged_only),
        "enabled": bool(normalized_base_ref),
        "base_ref": str(normalized_base_ref or ""),
        "head_ref": str(head_ref or "HEAD"),
        "changed_file_count": 0,
    }

    changed_files: set[str] = set()
    scoped_files: set[str] | None = None
    prior_line_cache: dict[str, int | None] = {}
    growth_lookup_error = ""
    tracked_files = _git_tracked_files(repo_root)
    if staged_only and not normalized_base_ref and _git_ref_exists(repo_root, "HEAD"):
        normalized_base_ref = "HEAD"
        growth_context["base_ref"] = normalized_base_ref
        growth_context["enabled"] = True
    if staged_only:
        try:
            scoped_files = _git_staged_files(repo_root)
            growth_context["changed_file_count"] = len(scoped_files)
        except Exception as exc:
            growth_lookup_error = f"{type(exc).__name__}: {exc}"
    elif growth_context["enabled"]:
        try:
            changed_files = _git_changed_files(
                repo_root,
                base_ref=str(normalized_base_ref or "").strip(),
                head_ref=str(head_ref or "").strip() or "HEAD",
            )
            growth_context["changed_file_count"] = len(changed_files)
        except Exception as exc:
            growth_lookup_error = f"{type(exc).__name__}: {exc}"

    for path, ext in _iter_candidate_files(repo_root, scan_roots, hard_limits):
        rel = path.relative_to(repo_root).as_posix()
        if tracked_files is not None and rel not in tracked_files:
            continue
        if scoped_files is not None and rel not in scoped_files:
            continue
        legacy_part_file = _looks_like_legacy_monolith_file(path)
        if legacy_part_file and not _is_allowed_split_file(path, rel):
            violations.append(
                {
                    "path": rel,
                    "ext": ext,
                    "lines": _line_count(path),
                    "hard_limit": int(hard_limits.get(ext, 0) or 0),
                    "reason": "unauthorized split file uses legacy .partNN.ext pattern outside allowlist",
                }
            )
            continue
        legacy_loader_file = _contains_legacy_monolith_loader(path)
        lines = _line_count(path)
        hard = int(hard_limits.get(ext, 0) or 0)
        measured.append({"path": rel, "lines": lines, "ext": ext, "hard_limit": hard})

        if legacy_loader_file:
            violations.append(
                {
                    "path": rel,
                    "ext": ext,
                    "lines": lines,
                    "hard_limit": hard,
                    "reason": "legacy monolith loader scaffold pattern detected",
                }
            )
            continue

        over_hard_limit = lines > hard
        over_soft_limit = soft_limit > 0 and lines > soft_limit
        changed_scope = scoped_files if scoped_files is not None else changed_files
        soft_limit_enforced = over_soft_limit and (not enforce_soft_limit_changed_only or rel in changed_scope)
        if not over_hard_limit and not soft_limit_enforced:
            continue

        entry = allowed.get(rel)
        if isinstance(entry, dict):
            owner = str(entry.get("owner", "") or default_owner).strip()
            expires_on = str(entry.get("expires_on", "") or default_expires).strip()
            waiver_reason = str(entry.get("reason", "") or "").strip()

            if require_waiver_metadata:
                if not owner:
                    violations.append(
                        {
                            "path": rel,
                            "ext": ext,
                            "lines": lines,
                            "hard_limit": hard,
                            "reason": "baselined file missing waiver owner",
                        }
                    )
                expires_date = _parse_iso_date(expires_on)
                if not expires_date:
                    violations.append(
                        {
                            "path": rel,
                            "ext": ext,
                            "lines": lines,
                            "hard_limit": hard,
                            "reason": "baselined file missing/invalid expires_on (YYYY-MM-DD)",
                        }
                    )
                elif expires_date < date.today():
                    violations.append(
                        {
                            "path": rel,
                            "ext": ext,
                            "lines": lines,
                            "hard_limit": hard,
                            "expires_on": expires_on,
                            "reason": "baselined waiver expired",
                        }
                    )
            if not allow_legacy_reason and "legacy" in waiver_reason.lower():
                violations.append(
                    {
                        "path": rel,
                        "ext": ext,
                        "lines": lines,
                        "hard_limit": hard,
                        "reason": "baselined waiver reason uses forbidden 'legacy' wording",
                    }
                )

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
            if growth_context["enabled"]:
                growth_files = scoped_files if scoped_files is not None else changed_files
                growth_raw = entry.get("max_growth_lines", default_growth)
                if rel in growth_files:
                    try:
                        max_growth = int(growth_raw)
                    except Exception:
                        max_growth = 0
                    if max_growth < 0:
                        max_growth = 0
                    if rel not in prior_line_cache:
                        prior_line_cache[rel] = _git_blob_line_count(
                            repo_root,
                            ref=str(normalized_base_ref or "").strip(),
                            rel_path=rel,
                        )
                    prior_lines = prior_line_cache.get(rel)
                    baseline_lines = int(prior_lines) if prior_lines is not None else 0
                    growth = int(lines - baseline_lines)
                    if growth > max_growth:
                        violations.append(
                            {
                                "path": rel,
                                "ext": ext,
                                "lines": lines,
                                "baseline_lines": baseline_lines,
                                "growth_lines": growth,
                                "max_growth_lines": max_growth,
                                "base_ref": str(normalized_base_ref or ""),
                                "head_ref": str(head_ref or "HEAD"),
                                "reason": "baselined file exceeded max_growth_lines",
                            }
                        )
            continue

        if over_hard_limit:
            violations.append(
                {
                    "path": rel,
                    "ext": ext,
                    "lines": lines,
                    "hard_limit": hard,
                    "reason": "file exceeds hard limit and is not baselined",
                }
            )
            continue

        violations.append(
            {
                "path": rel,
                "ext": ext,
                "lines": lines,
                "hard_limit": hard,
                "soft_limit": soft_limit,
                "reason": "changed file exceeds soft limit and is not baselined",
            }
        )

    if growth_lookup_error:
        violations.append(
            {
                "path": "<git-range>",
                "reason": f"unable to compute growth range: {growth_lookup_error}",
                "base_ref": str(normalized_base_ref or ""),
                "head_ref": str(head_ref or "HEAD"),
            }
        )

    return {
        "ok": len(violations) == 0,
        "repo_root": str(repo_root),
        "baseline_path": str(baseline_path),
        "scan_roots": scan_roots,
        "violations": violations,
        "measured_count": len(measured),
        "growth_context": growth_context,
    }


def main() -> int:
    if _runtime_protection_disabled():
        print("Monolith guard: PASS (runtime protection disabled by human)")
        return 0

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
    parser.add_argument(
        "--base",
        default="",
        help="Optional git base ref for growth checks (enables max_growth_lines enforcement).",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Optional git head ref for growth checks (default: HEAD).",
    )
    parser.add_argument(
        "--staged-only",
        action="store_true",
        help="Scan only files currently staged in git index.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (repo_root / baseline_path).resolve()

    base_ref = str(args.base or "").strip() or None
    head_ref = str(args.head or "").strip() or "HEAD"
    result = run_guard(
        repo_root,
        baseline_path,
        base_ref=base_ref,
        head_ref=head_ref,
        staged_only=bool(args.staged_only),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            growth_note = ""
            growth_ctx = dict(result.get("growth_context") or {})
            if bool(growth_ctx.get("enabled")):
                growth_note = (
                    f" Growth checks enabled for {growth_ctx.get('base_ref')}..."
                    f"{growth_ctx.get('head_ref')} ({growth_ctx.get('changed_file_count', 0)} changed files)."
                )
            elif bool(growth_ctx.get("staged_only")):
                growth_note = f" Staged-only mode enabled " f"({growth_ctx.get('changed_file_count', 0)} staged files)."
            print(
                f"Monolith guard OK. Scanned {result['measured_count']} files "
                f"under {', '.join(result['scan_roots'])}.{growth_note}"
            )
        else:
            print(
                f"Monolith guard FAILED: {len(result['violations'])} violation(s). "
                "Split modules or update baseline intentionally."
            )
            for row in result["violations"]:
                hard = row.get("hard_limit")
                max_lines = row.get("max_lines")
                max_growth = row.get("max_growth_lines")
                max_part = f", max {max_lines}" if max_lines is not None else ""
                growth_part = (
                    f", baseline {row.get('baseline_lines')}, growth {row.get('growth_lines')}, "
                    f"max_growth {max_growth}"
                    if max_growth is not None
                    else ""
                )
                print(
                    f"- {row.get('path')}: {row.get('lines')} lines "
                    f"(hard {hard}{max_part}{growth_part}) -> {row.get('reason')}"
                )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
