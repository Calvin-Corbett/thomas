#!/usr/bin/env python3
"""Require explicit approvals when monolith baseline constraints are relaxed."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from typing import Any, Dict, List, Optional, Sequence, Set

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASELINE = "docs/monolith_guard_baseline.json"
DEFAULT_APPROVALS = "docs/ops/monolith_baseline_approvals.json"


def _normalize(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _git_changed_files(repo_root: Path, *, base_ref: str, head_ref: str) -> set[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or "git diff failed"
        raise RuntimeError(msg)
    out: set[str] = set()
    for line in proc.stdout.splitlines():
        rel = _normalize(line)
        if rel:
            out.add(rel)
    return out


def _git_show_text(repo_root: Path, *, ref: str, rel_path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{ref}:{_normalize(rel_path)}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _load_json_obj(text: str | None, *, default: dict[str, Any]) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return dict(default)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON payload must be an object")
    return parsed


def _extract_allowed(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = doc.get("allowed_large_files")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        rel = _normalize(str(key or ""))
        if not rel or not isinstance(value, dict):
            continue
        out[rel] = value
    return out


def _extract_approvals(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = doc.get("approvals")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
    return out


def _find_relaxations(base_doc: dict[str, Any], head_doc: dict[str, Any]) -> list[dict[str, Any]]:
    base_allowed = _extract_allowed(base_doc)
    head_allowed = _extract_allowed(head_doc)

    out: list[dict[str, Any]] = []
    for path, head_entry in sorted(head_allowed.items()):
        base_entry = base_allowed.get(path)
        head_max = _to_int(head_entry.get("max_lines"), 0)
        head_growth_raw = head_entry.get("max_growth_lines")
        head_growth = _to_int(head_growth_raw, -1) if head_growth_raw is not None else None

        if base_entry is None:
            out.append(
                {
                    "path": path,
                    "change": "new_baselined_file",
                    "new_value": head_max,
                    "detail": f"new baseline entry with max_lines={head_max}",
                }
            )
            continue

        base_max = _to_int(base_entry.get("max_lines"), 0)
        if head_max > base_max:
            out.append(
                {
                    "path": path,
                    "change": "max_lines_increase",
                    "old_value": base_max,
                    "new_value": head_max,
                    "detail": f"max_lines increased {base_max} -> {head_max}",
                }
            )

        base_growth_raw = base_entry.get("max_growth_lines")
        base_growth = _to_int(base_growth_raw, -1) if base_growth_raw is not None else None
        if base_growth is not None and head_growth is None:
            out.append(
                {
                    "path": path,
                    "change": "max_growth_lines_removed",
                    "old_value": base_growth,
                    "new_value": None,
                    "detail": f"max_growth_lines removed (was {base_growth})",
                }
            )
        elif base_growth is not None and head_growth is not None and head_growth > base_growth:
            out.append(
                {
                    "path": path,
                    "change": "max_growth_lines_relaxed",
                    "old_value": base_growth,
                    "new_value": head_growth,
                    "detail": f"max_growth_lines increased {base_growth} -> {head_growth}",
                }
            )

    return out


def _approval_matches(relaxation: dict[str, Any], approval: dict[str, Any]) -> bool:
    if _normalize(str(approval.get("path") or "")) != _normalize(str(relaxation.get("path") or "")):
        return False
    if str(approval.get("change") or "").strip() != str(relaxation.get("change") or "").strip():
        return False
    approved_by = str(approval.get("approved_by") or "").strip()
    approved_on = str(approval.get("approved_on") or "").strip()
    reason = str(approval.get("reason") or "").strip()
    if not approved_by or not approved_on or not reason:
        return False

    expected = relaxation.get("new_value")
    if expected is None:
        return True
    approved_new = approval.get("new_value")
    try:
        return int(approved_new) == int(expected)
    except Exception:
        return False


def evaluate_relaxation_gate(
    base_doc: dict[str, Any],
    head_doc: dict[str, Any],
    approvals_doc: dict[str, Any],
) -> dict[str, Any]:
    relaxations = _find_relaxations(base_doc, head_doc)
    approvals = _extract_approvals(approvals_doc)

    violations: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    for row in relaxations:
        matched_row = next((a for a in approvals if _approval_matches(row, a)), None)
        if matched_row is None:
            violations.append(dict(row))
        else:
            matched.append(
                {
                    "path": row.get("path"),
                    "change": row.get("change"),
                    "new_value": row.get("new_value"),
                    "approval_id": str(matched_row.get("id") or ""),
                    "approved_by": str(matched_row.get("approved_by") or ""),
                }
            )

    return {
        "ok": len(violations) == 0,
        "relaxation_count": len(relaxations),
        "relaxations": relaxations,
        "matched_approvals": matched,
        "violations": violations,
    }


def apply_approval_file_change_requirement(
    result: dict[str, Any],
    *,
    approvals_changed: bool,
    allow_existing_approvals: bool,
) -> dict[str, Any]:
    """Require the approvals registry file to change whenever relaxations occur."""
    payload = dict(result or {})
    violations = list(payload.get("violations") or [])
    relaxations = list(payload.get("relaxations") or [])

    if allow_existing_approvals:
        return payload
    if not relaxations:
        return payload
    if approvals_changed:
        return payload

    violations.append(
        {
            "path": "<approvals-registry>",
            "change": "approvals_registry_unchanged",
            "detail": "baseline relaxations detected but approvals registry file was not modified in diff range",
        }
    )
    payload["violations"] = violations
    payload["ok"] = False
    return payload


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when monolith baseline constraints are relaxed without explicit approval entries."
        )
    )
    parser.add_argument("--repo-root", default=None, help="Repository root (default: inferred from script path).")
    parser.add_argument("--base", default=None, help="Diff base ref/sha (optional).")
    parser.add_argument("--head", default="HEAD", help="Diff head ref/sha (default: HEAD).")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE, help="Baseline JSON path.")
    parser.add_argument("--approvals", default=DEFAULT_APPROVALS, help="Approval registry JSON path.")
    parser.add_argument(
        "--allow-existing-approvals",
        action="store_true",
        help="Allow baseline relaxations backed by pre-existing approvals without changing approvals file.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    baseline_rel = _normalize(str(args.baseline or DEFAULT_BASELINE))
    approvals_rel = _normalize(str(args.approvals or DEFAULT_APPROVALS))
    head_ref = str(args.head or "HEAD").strip() or "HEAD"
    base_ref = str(args.base or "").strip() or f"{head_ref}~1"

    try:
        changed = _git_changed_files(repo_root, base_ref=base_ref, head_ref=head_ref)
    except Exception as exc:
        print(f"Monolith baseline approval gate: FAIL (diff resolution error: {exc})")
        return 1

    baseline_changed = baseline_rel in changed
    approvals_changed = approvals_rel in changed
    if not baseline_changed:
        payload = {
            "ok": True,
            "skipped": True,
            "reason": "baseline_not_changed",
            "base_ref": base_ref,
            "head_ref": head_ref,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("Monolith baseline approval gate: PASS (baseline unchanged)")
        return 0

    base_text = _git_show_text(repo_root, ref=base_ref, rel_path=baseline_rel)
    head_text = _git_show_text(repo_root, ref=head_ref, rel_path=baseline_rel)
    if head_text is None:
        print("Monolith baseline approval gate: FAIL (head baseline file missing)")
        return 1
    approvals_text = _git_show_text(repo_root, ref=head_ref, rel_path=approvals_rel)

    try:
        base_doc = _load_json_obj(base_text, default={"allowed_large_files": {}})
        head_doc = _load_json_obj(head_text, default={"allowed_large_files": {}})
        approvals_doc = _load_json_obj(approvals_text, default={"approvals": []})
    except Exception as exc:
        print(f"Monolith baseline approval gate: FAIL (json parse error: {exc})")
        return 1

    result = evaluate_relaxation_gate(base_doc, head_doc, approvals_doc)
    result = apply_approval_file_change_requirement(
        result,
        approvals_changed=bool(approvals_changed),
        allow_existing_approvals=bool(args.allow_existing_approvals),
    )
    payload = {
        **result,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "baseline_path": baseline_rel,
        "approvals_path": approvals_rel,
        "baseline_changed": baseline_changed,
        "approvals_changed": approvals_changed,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload["ok"]:
            print(
                "Monolith baseline approval gate: PASS "
                f"(relaxations={payload['relaxation_count']}, approvals matched={len(payload['matched_approvals'])})"
            )
        else:
            print(
                "Monolith baseline approval gate: FAIL "
                f"({len(payload['violations'])} unapproved relaxation(s))"
            )
            for row in payload["violations"]:
                print(
                    f"- {row.get('path')} [{row.get('change')}]: {row.get('detail', '')}"
                )
    return 0 if bool(payload["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(run())
