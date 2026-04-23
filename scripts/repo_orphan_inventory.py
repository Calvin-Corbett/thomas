#!/usr/bin/env python3
"""Build an actionable inventory of orphan/stale repo files."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = "docs/repo_hygiene_baseline.json"
DEFAULT_JSON_OUTPUT = "docs/ops/repo_orphan_inventory.json"
DEFAULT_MD_OUTPUT = "docs/ops/repo_orphan_inventory.md"

GENERATED_UNTRACKED_PREFIXES = (
    "output/",
    "runtime/",
    "tmp/",
    "logs/",
    "artifacts/",
    "dist/",
    ".inbox_extract_",
)
GENERATED_UNTRACKED_SUFFIXES = (
    ".har",
    ".log",
    ".tmp",
    ".tar",
    ".tar.gz",
    ".zip",
    ".pyc",
)
ROOT_DOC_EXTENSIONS = {".md", ".txt"}
ROOT_DOC_KEYWORDS = {
    "summary",
    "report",
    "readme",
    "quick_start",
    "quickstart",
    "verification",
    "implementation",
    "architecture",
    "index",
}


def _normalize(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _is_numbered_status_line(line: str) -> bool:
    return bool(str(line or "").strip())


def _porcelain_path(line: str) -> str:
    raw = str(line or "")
    if len(raw) <= 3:
        return _normalize(raw)
    return _normalize(raw[3:])


def _any_prefix(path: str, prefixes: Iterable[str]) -> bool:
    item = _normalize(path).lower()
    for raw in prefixes:
        prefix = _normalize(str(raw or "")).lower()
        if prefix and item.startswith(prefix):
            return True
    return False


def _any_suffix(path: str, suffixes: Iterable[str]) -> bool:
    item = _normalize(path).lower()
    for raw in suffixes:
        suffix = str(raw or "").strip().lower()
        if suffix and item.endswith(suffix):
            return True
    return False


def _sample(items: Sequence[str], *, limit: int = 10) -> list[str]:
    cap = max(1, int(limit))
    return [str(item) for item in list(items)[:cap]]


def _git_status_porcelain(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git status --porcelain failed")
    return [str(line or "").rstrip() for line in proc.stdout.splitlines() if _is_numbered_status_line(line)]


def _git_ls_files(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git ls-files failed")
    return sorted({_normalize(line) for line in proc.stdout.splitlines() if _normalize(line)})


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return raw


def _worktree_paths(status_lines: Sequence[str]) -> dict[str, list[str]]:
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    for line in [str(item or "").rstrip() for item in status_lines if _is_numbered_status_line(item)]:
        if line.startswith("??"):
            path = _porcelain_path(line)
            if path:
                untracked.append(path)
            continue
        if line.startswith("!!"):
            continue
        idx = line[0] if len(line) > 0 else " "
        wip = line[1] if len(line) > 1 else " "
        path = _porcelain_path(line)
        if path and idx not in {" ", "?", "!"}:
            staged.append(path)
        if path and wip not in {" ", "?", "!"}:
            unstaged.append(path)
    return {
        "staged": sorted(set(staged)),
        "unstaged": sorted(set(unstaged)),
        "untracked": sorted(set(untracked)),
    }


def _is_root_doc_candidate(path: str, allowed_root: set[str]) -> bool:
    item = _normalize(path)
    if "/" in item or item in allowed_root:
        return False
    ext = Path(item).suffix.lower()
    if ext not in ROOT_DOC_EXTENSIONS:
        return False
    stem = Path(item).stem.lower().replace("-", "_")
    return any(keyword in stem for keyword in ROOT_DOC_KEYWORDS)


def _classify_untracked(path: str, *, allowed_root: set[str]) -> dict[str, str]:
    item = _normalize(path)
    if _any_prefix(item, GENERATED_UNTRACKED_PREFIXES):
        return {
            "category": "generated_artifact",
            "recommendation": "remove",
            "reason": "path is inside generated artifact directory",
        }
    if _any_suffix(item, GENERATED_UNTRACKED_SUFFIXES):
        return {
            "category": "generated_artifact",
            "recommendation": "remove",
            "reason": "path ends with generated artifact suffix",
        }
    if _is_root_doc_candidate(item, allowed_root):
        return {
            "category": "root_doc_sprawl",
            "recommendation": "archive_or_consolidate",
            "reason": "root-level ad hoc documentation not in hygiene allowlist",
        }
    return {
        "category": "untracked_review",
        "recommendation": "review",
        "reason": "untracked path needs explicit keep/remove decision",
    }


def _tracked_debt_entries(
    *,
    tracked_paths: Sequence[str],
    baseline: Mapping[str, Any],
) -> list[dict[str, str]]:
    tracked = sorted({_normalize(item) for item in tracked_paths if _normalize(item)})
    allowed_root = {_normalize(item) for item in (baseline.get("allowed_tracked_root_files") or []) if _normalize(item)}
    forbidden_prefixes = [
        _normalize(item) for item in (baseline.get("forbidden_tracked_prefixes") or []) if _normalize(item)
    ]
    blocked_suffixes = [str(item) for item in (baseline.get("blocked_tracked_suffixes") or []) if str(item).strip()]

    out: list[dict[str, str]] = []
    for path in tracked:
        if "/" not in path and path not in allowed_root:
            out.append(
                {
                    "path": path,
                    "source": "tracked",
                    "category": "tracked_root_sprawl",
                    "recommendation": "move_or_archive",
                    "reason": "tracked root file not in baseline allowlist",
                }
            )
        if _any_prefix(path, forbidden_prefixes):
            out.append(
                {
                    "path": path,
                    "source": "tracked",
                    "category": "tracked_forbidden_prefix",
                    "recommendation": "untrack_or_relocate",
                    "reason": "tracked file is in forbidden tracked prefix",
                }
            )
        if _any_suffix(path, blocked_suffixes):
            out.append(
                {
                    "path": path,
                    "source": "tracked",
                    "category": "tracked_blocked_suffix",
                    "recommendation": "untrack_or_rename",
                    "reason": "tracked file has blocked transient suffix",
                }
            )
    # Deduplicate preserving order.
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for row in out:
        key = (row["path"], row["category"], row["recommendation"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def build_inventory(*, repo_root: Path, baseline_path: Path) -> dict[str, Any]:
    baseline = _load_json(baseline_path)
    status_lines = _git_status_porcelain(repo_root)
    tracked_paths = _git_ls_files(repo_root)
    worktree = _worktree_paths(status_lines)
    allowed_root = {_normalize(item) for item in (baseline.get("allowed_tracked_root_files") or []) if _normalize(item)}

    entries: list[dict[str, str]] = []
    for path in list(worktree.get("untracked") or []):
        classified = _classify_untracked(path, allowed_root=allowed_root)
        entries.append(
            {
                "path": _normalize(path),
                "source": "untracked",
                "category": classified["category"],
                "recommendation": classified["recommendation"],
                "reason": classified["reason"],
            }
        )
    entries.extend(_tracked_debt_entries(tracked_paths=tracked_paths, baseline=baseline))
    entries = sorted(
        entries,
        key=lambda row: (str(row.get("recommendation", "")), str(row.get("category", "")), str(row.get("path", ""))),
    )

    category_counts = Counter(str(row.get("category", "")) for row in entries)
    recommendation_counts = Counter(str(row.get("recommendation", "")) for row in entries)
    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "baseline_path": str(baseline_path),
        "worktree_summary": {
            "staged_count": len(worktree.get("staged") or []),
            "unstaged_count": len(worktree.get("unstaged") or []),
            "untracked_count": len(worktree.get("untracked") or []),
        },
        "tracked_total": len(tracked_paths),
        "inventory_count": len(entries),
        "category_counts": dict(sorted(category_counts.items())),
        "recommendation_counts": dict(sorted(recommendation_counts.items())),
        "sample_paths": _sample([str(row.get("path", "")) for row in entries], limit=20),
        "entries": entries,
    }
    return payload


def render_markdown(payload: Mapping[str, Any], *, max_rows: int = 250) -> str:
    summary = dict(payload.get("worktree_summary") or {})
    categories = dict(payload.get("category_counts") or {})
    recommendations = dict(payload.get("recommendation_counts") or {})
    lines = [
        "# Repo Orphan Inventory",
        "",
        f"- generated_at_utc: `{payload.get('generated_at_utc', '')}`",
        f"- repo_root: `{payload.get('repo_root', '')}`",
        f"- inventory_count: `{payload.get('inventory_count', 0)}`",
        f"- staged_count: `{summary.get('staged_count', 0)}`",
        f"- unstaged_count: `{summary.get('unstaged_count', 0)}`",
        f"- untracked_count: `{summary.get('untracked_count', 0)}`",
        "",
        "## Category Counts",
        "",
    ]
    if categories:
        for key in sorted(categories):
            lines.append(f"- {key}: `{categories[key]}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Recommendation Counts", ""])
    if recommendations:
        for key in sorted(recommendations):
            lines.append(f"- {key}: `{recommendations[key]}`")
    else:
        lines.append("- none")

    rows = list(payload.get("entries") or [])
    if rows:
        lines.extend(
            [
                "",
                "## Inventory",
                "",
                "| path | source | category | recommendation | reason |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows[: max(1, int(max_rows))]:
            path = str(row.get("path", "")).replace("|", "\\|")
            source = str(row.get("source", "")).replace("|", "\\|")
            category = str(row.get("category", "")).replace("|", "\\|")
            recommendation = str(row.get("recommendation", "")).replace("|", "\\|")
            reason = str(row.get("reason", "")).replace("|", "\\|")
            lines.append(f"| `{path}` | {source} | {category} | {recommendation} | {reason} |")
        if len(rows) > max_rows:
            lines.extend(["", f"- truncated rows: `{len(rows) - max_rows}`"])
    else:
        lines.extend(["", "## Inventory", "", "- none"])
    lines.append("")
    return "\n".join(lines)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate verified orphan/stale file inventory with decisions.")
    parser.add_argument("--repo-root", default=None, help="Repository root (default: inferred).")
    parser.add_argument(
        "--baseline", default=DEFAULT_BASELINE, help=f"Baseline JSON path (default: {DEFAULT_BASELINE})."
    )
    parser.add_argument(
        "--json-output",
        default=DEFAULT_JSON_OUTPUT,
        help=f"Inventory JSON output path (default: {DEFAULT_JSON_OUTPUT}).",
    )
    parser.add_argument(
        "--md-output", default=DEFAULT_MD_OUTPUT, help=f"Inventory Markdown output path (default: {DEFAULT_MD_OUTPUT})."
    )
    parser.add_argument("--max-md-rows", type=int, default=250, help="Max rows to include in markdown table.")
    parser.add_argument("--write", action="store_true", help="Write JSON/Markdown outputs to disk.")
    parser.add_argument("--json", action="store_true", help="Emit JSON payload to stdout.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (repo_root / baseline_path).resolve()
    json_output = Path(args.json_output)
    if not json_output.is_absolute():
        json_output = (repo_root / json_output).resolve()
    md_output = Path(args.md_output)
    if not md_output.is_absolute():
        md_output = (repo_root / md_output).resolve()

    try:
        payload = build_inventory(repo_root=repo_root, baseline_path=baseline_path)
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Repo orphan inventory: FAIL\n- {exc}")
        return 1

    payload["ok"] = True
    payload["json_output"] = str(json_output)
    payload["md_output"] = str(md_output)

    if args.write:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        md_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_output.write_text(render_markdown(payload, max_rows=max(1, int(args.max_md_rows))), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "Repo orphan inventory: OK "
            f"(inventory={int(payload.get('inventory_count', 0))}, "
            f"tracked={int(payload.get('tracked_total', 0))}, "
            f"staged={int(dict(payload.get('worktree_summary') or {}).get('staged_count', 0))}, "
            f"unstaged={int(dict(payload.get('worktree_summary') or {}).get('unstaged_count', 0))}, "
            f"untracked={int(dict(payload.get('worktree_summary') or {}).get('untracked_count', 0))})"
        )
        if args.write:
            print(f"- wrote: {json_output}")
            print(f"- wrote: {md_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
