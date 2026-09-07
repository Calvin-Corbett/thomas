"""Canonical PLAN.md metadata parsing and body-preserving reconciliation."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

FIELD_ORDER = ("Owner", "Status", "Updated At", "Scope")
_FIELD_RE = re.compile(r"^\s*-\s*(Owner|Status|Updated\s+At|Scope)\s*:\s*(.*?)\s*$", re.IGNORECASE)
STATUS_ALIASES = {"active": "in_progress", "ready": "queued", "up-for-grabs": "up_for_grabs"}
VALID_STATUSES = {"queued", "claimed", "in_progress", "blocked", "review", "done", "up_for_grabs"}


class PlanMetadataError(ValueError):
    """PLAN metadata is missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class PlanMetadata:
    owner: str
    status: str
    updated_at: str
    scope: str


def normalize_status(status: str) -> str:
    token = str(status or "").strip().casefold().replace(" ", "_")
    token = STATUS_ALIASES.get(token, token)
    if token not in VALID_STATUSES:
        raise PlanMetadataError(f"invalid plan status: {status}")
    return token


def normalize_scope(scope: str) -> str:
    rows: list[str] = []
    for raw in str(scope or "").split(","):
        token = raw.strip().replace("\\", "/")
        while token.startswith("./"):
            token = token[2:]
        while "//" in token:
            token = token.replace("//", "/")
        token = token.rstrip("/")
        if token and token not in rows:
            rows.append(token)
    if not rows:
        raise PlanMetadataError("plan scope is required")
    return ",".join(rows)


def parse_metadata(text: str) -> PlanMetadata:
    lines = str(text or "").splitlines()
    body_at = next((idx for idx, line in enumerate(lines) if line.startswith("## ")), len(lines))
    found: dict[str, str] = {}
    order: list[str] = []
    for line in lines[:body_at]:
        match = _FIELD_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        canonical = "Updated At" if key.casefold().replace(" ", "") == "updatedat" else key.title()
        if canonical in found:
            raise PlanMetadataError(f"duplicate plan metadata field: {canonical}")
        found[canonical] = match.group(2).strip()
        order.append(canonical)
    missing = [key for key in FIELD_ORDER if not found.get(key)]
    if missing:
        raise PlanMetadataError("missing plan metadata: " + ", ".join(missing))
    if tuple(order) != FIELD_ORDER:
        raise PlanMetadataError("plan metadata fields are not in canonical order")
    return PlanMetadata(
        owner=found["Owner"],
        status=normalize_status(found["Status"]),
        updated_at=found["Updated At"],
        scope=normalize_scope(found["Scope"]),
    )


def reconcile_metadata(text: str, expected: PlanMetadata) -> str:
    source = str(text or "")
    lines = source.splitlines()
    if not lines:
        raise PlanMetadataError("PLAN.md is empty")
    body_at = next((idx for idx, line in enumerate(lines) if line.startswith("## ")), len(lines))
    header = [line for line in lines[:body_at] if not _FIELD_RE.match(line)]
    while header and not header[-1].strip():
        header.pop()
    body = lines[body_at:]
    canonical = [
        f"- Owner: {expected.owner.strip()}",
        f"- Status: {normalize_status(expected.status)}",
        f"- Updated At: {expected.updated_at.strip()}",
        f"- Scope: {normalize_scope(expected.scope)}",
    ]
    out = [*header, "", *canonical]
    if body:
        out.extend(["", *body])
    return "\n".join(out).rstrip() + "\n"


def repo_relative_or_absolute(path: Path, *, repo_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root).as_posix()
    except ValueError:
        return str(resolved)


def artifact_root_path(root: str, *, repo_root: Path) -> Path:
    base = Path(str(root or "").strip() or ".").expanduser()
    return base if base.is_absolute() else (repo_root / base).resolve()


def default_artifact_path(task_id: str, root: str, filename: str, *, repo_root: Path) -> str:
    target = artifact_root_path(root, repo_root=repo_root) / str(task_id).strip() / filename
    return repo_relative_or_absolute(target, repo_root=repo_root)


def build_plan_template(*, task_id: str, owner: str, summary: str, scope: str, status: str, now_iso: str) -> str:
    return (
        f"# PLAN for {task_id}\n\n"
        f"- Owner: {owner}\n"
        f"- Status: {status}\n"
        f"- Updated At: {now_iso}\n"
        f"- Scope: {scope}\n\n"
        f"## Summary\n\n{summary}\n\n"
        "## Approach\n\n- Document the intended implementation steps here.\n"
    )


def build_problem_template(*, task_id: str, owner: str, summary: str, scope: str, status: str, now_iso: str) -> str:
    return (
        f"# PROBLEM for {task_id}\n\n"
        f"task_id: `{task_id}`\n\n"
        f"- Owner: {owner}\n"
        f"- Status: {status}\n"
        f"- Updated At: {now_iso}\n"
        f"- Scope: {scope}\n\n"
        f"## Current Problem\n\n{summary}\n\n"
        "## Blocking Details\n\n- Capture blockers, failures, and observations here.\n\n"
        "## Closure\n\n"
        "This incident resolves only once this file carries exactly one "
        "`closure:` line, in one of three forms "
        "(see `scripts/forge/gates/problem_closure_gate.py` for exactly how "
        "each one resolves). The examples below are illustration, not a real "
        "closure -- do not remove this fence when copying the line you need:\n\n"
        "```\n"
        "- closure: gate:<filename>          a RED_PATH-covered gate now catches this\n"
        "- closure: tombstone:<id>           a graveyard record for a deliberate removal\n"
        "- closure: accepted-risk:<id>       an owner's dated, expiring sign-off\n"
        "```\n\n"
        "Add the real line, in that exact bulleted form (unfenced, exactly "
        "one), only once something actually resolves it -- a closure string "
        "that names nothing is a FAIL naming the defect.\n"
    )


def normalize_artifact_path(path: str, *, repo_root: Path) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return repo_relative_or_absolute(candidate, repo_root=repo_root)
    return raw.replace("\\", "/")


def ensure_problem_marker(path: Path, *, task_id: str) -> None:
    marker = f"task_id: `{task_id}`"
    body = path.read_text(encoding="utf-8")
    if marker in body:
        return
    lines = body.splitlines()
    updated = [lines[0], "", marker, "", *lines[1:]] if lines else [marker]
    path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")


def upsert_target_entry(
    lines: list[str],
    *,
    heading: str,
    task_id: str,
    rendered: str,
    find_section: Callable[..., tuple[int, int] | None],
    bullet_indices: Callable[..., list[int]],
    parse_entry: Callable[..., tuple[str | None, dict[str, str] | None, str | None]],
    norm: Callable[[str], str],
    none_tokens: frozenset[str] | set[str] | tuple[str, ...],
) -> tuple[bool, str]:
    section = find_section(lines, heading_prefix=heading)
    if section is None:
        return False, f"missing `## {heading}` section"
    matches: list[int] = []
    none_rows: list[int] = []
    for idx in bullet_indices(lines, section[0], section[1]):
        entry, fields, err = parse_entry(idx + 1, lines[idx])
        if err:
            return False, err
        if entry is not None and entry.lower() in none_tokens:
            none_rows.append(idx)
        elif fields and norm(fields.get("task_id", "")) == norm(task_id):
            matches.append(idx)
    if len(matches) > 1:
        return False, f"task `{task_id}` has duplicate rows in `## {heading}`"
    if matches:
        lines[matches[0]] = rendered
        return True, "updated"
    if none_rows:
        lines[none_rows[0]] = rendered
        for idx in reversed(none_rows[1:]):
            del lines[idx]
        return True, "inserted"
    lines.insert(section[1], rendered)
    return True, "inserted"


def parse_cli_now(raw: str) -> datetime:
    token = str(raw or "").strip()
    if not token:
        return datetime.now(timezone.utc)
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    parsed = datetime.fromisoformat(token)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def run_targeted_sync(argv: Sequence[str] | None, *, core: ModuleType) -> int:
    parser = argparse.ArgumentParser(description="Reconcile one task's canonical PLAN and Workboard metadata.")
    parser.add_argument("--workboard", default=str(core.ROOT / "plans" / "thomas" / "WORKBOARD.md"))
    parser.add_argument("--task-id", required=True, help="Exact active or up-for-grabs task to reconcile.")
    parser.add_argument("--plan-root", default="plans/thomas/tasks")
    parser.add_argument("--problem-root", default="plans/thomas/problems")
    parser.add_argument("--now", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    workboard = Path(args.workboard).expanduser()
    if not workboard.is_absolute():
        workboard = (core.ROOT / workboard).resolve()
    ok, details = core._sync_task_plans(
        workboard_path=workboard,
        plan_root=str(args.plan_root),
        problem_root=str(args.problem_root),
        require_claims_to_have_active_task=True,
        apply=bool(args.apply),
        now=parse_cli_now(str(args.now)),
        task_id=str(args.task_id),
    )
    payload = {"ok": bool(ok), "action": "sync_task_plan", "workboard": str(workboard), **details}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Targeted task plan sync: PASS" if ok else "Targeted task plan sync: FAIL")
        print(f"- task: {args.task_id}")
        if not ok:
            print(f"- {payload.get('error', 'sync failed')}")
    return 0 if ok else 1
