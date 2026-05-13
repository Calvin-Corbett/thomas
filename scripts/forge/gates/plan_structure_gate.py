#!/usr/bin/env python3
"""Enforce canonical planning structure and redirects."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
REQUIRED_FILES: Sequence[str] = (
    "docs/REPO_STRUCTURE_PROTOCOL.md",
    "plans/README.md",
    "plans/thomas/README.md",
    "plans/thomas/WORKBOARD.md",
)

LEGACY_POINTER_FILES: Sequence[str] = (
    "PLAN-UI-UPGRADE.md",
    "docs/WEEKLY_DEEP_DIVE_PLAN.md",
    "docs/LAUNCH_V1.md",
    "docs/COMPANION_STORE_COMPLIANCE_PLAN.md",
    "docs/THOMAS_ONBOARDING_UX_PLAN.md",
)

PLAN_NAME_RE = re.compile(r"(plan|roadmap|workboard|launch)", re.IGNORECASE)
POINTER_RE = re.compile(r"Canonical location:\s*\n- `([^`]+)`", re.IGNORECASE)
PATH_REF_RE = re.compile(r"`(plans/thomas/[^`]+\.md)`")
GENERATED_PLAN_PREFIXES: Sequence[str] = (
    "plans/thomas/tasks/",
    "plans/thomas/problems/",
    "plans/thomas/swarm/",
)


def _normalize(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _collect_md_candidates() -> list[str]:
    out: set[str] = set()
    for candidate in ROOT.glob("*.md"):
        out.add(_normalize(candidate.relative_to(ROOT).as_posix()))
    docs_dir = ROOT / "docs"
    if docs_dir.exists():
        for candidate in docs_dir.glob("*.md"):
            out.add(_normalize(candidate.relative_to(ROOT).as_posix()))
    return sorted(out)


def _plan_docs_in_workspace() -> list[str]:
    base = ROOT / "plans" / "thomas"
    if not base.exists():
        return []
    out: list[str] = []
    for candidate in base.rglob("*.md"):
        rel = _normalize(candidate.relative_to(ROOT).as_posix())
        if rel in {"plans/thomas/README.md", "plans/thomas/WORKBOARD.md"}:
            continue
        out.append(rel)
    return sorted(set(out))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check_required_files(violations: list[str]) -> None:
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            violations.append(f"missing required structure file: {rel}")


def _check_noncanonical_plan_files(violations: list[str]) -> None:
    allow = set(LEGACY_POINTER_FILES)
    for rel in _collect_md_candidates():
        name = Path(rel).name
        if not PLAN_NAME_RE.search(name):
            continue
        if rel in allow:
            continue
        violations.append(f"non-canonical plan-like file outside plans/: {rel} (move to plans/ and leave pointer)")


def _check_pointer_files(violations: list[str]) -> None:
    for rel in LEGACY_POINTER_FILES:
        path = ROOT / rel
        if not path.exists():
            violations.append(f"missing legacy pointer file: {rel}")
            continue
        text = _read(path)
        match = POINTER_RE.search(text)
        if not match:
            violations.append(f"legacy pointer missing canonical location block: {rel}")
            continue
        target = _normalize(match.group(1))
        if not target.startswith("plans/"):
            violations.append(f"legacy pointer target must be under plans/: {rel} -> {target}")
            continue
        if not (ROOT / target).exists():
            violations.append(f"legacy pointer target does not exist: {rel} -> {target}")


def _extract_plan_refs(text: str) -> set[str]:
    out: set[str] = set()
    for m in PATH_REF_RE.finditer(text or ""):
        out.add(_normalize(m.group(1)))
    return out


def _is_generated_plan_doc(rel: str) -> bool:
    normalized = _normalize(rel)
    return any(normalized.startswith(prefix) for prefix in GENERATED_PLAN_PREFIXES)


def _is_template_path(rel: str) -> bool:
    normalized = _normalize(rel)
    return "<" in normalized and ">" in normalized


def _check_workboard_coverage(violations: list[str]) -> None:
    workboard = ROOT / "plans" / "thomas" / "WORKBOARD.md"
    hub = ROOT / "plans" / "thomas" / "README.md"
    if not workboard.exists() or not hub.exists():
        return
    workboard_refs = _extract_plan_refs(_read(workboard))
    hub_refs = _extract_plan_refs(_read(hub))
    plan_docs = _plan_docs_in_workspace()

    for rel in plan_docs:
        if _is_generated_plan_doc(rel):
            continue
        if rel not in workboard_refs:
            violations.append(f"plan missing from workboard references: {rel}")
        if rel not in hub_refs:
            violations.append(f"plan missing from plans/thomas/README.md references: {rel}")

    for rel in sorted(workboard_refs | hub_refs):
        if _is_template_path(rel):
            continue
        if rel.startswith("plans/thomas/") and not (ROOT / rel).exists():
            violations.append(f"stale plan reference to missing file: {rel}")


def evaluate() -> list[str]:
    violations: list[str] = []
    _check_required_files(violations)
    _check_noncanonical_plan_files(violations)
    _check_pointer_files(violations)
    _check_workboard_coverage(violations)
    return violations


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce canonical plan structure and pointers.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    violations = evaluate()
    payload = {
        "ok": not violations,
        "gate": "plan_structure",
        "violation_count": len(violations),
        "violations": list(violations),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1

    if violations:
        print("Plan structure gate: FAIL")
        for item in violations:
            print(f"- {item}")
        return 1

    print("Plan structure gate: PASS")
    print("- planning files are in canonical locations")
    print("- legacy pointer files resolve into plans/")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
