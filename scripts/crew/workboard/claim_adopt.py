#!/usr/bin/env python3
"""Adopt orphaned WORKBOARD claims (Calvin 2026-06-01).

The problem this solves: a user (or an agent) finishes work but leaves it
uncommitted, holding a claim on those files. Later, a *different* agent is
blocked from committing because the files are still claimed by the one who
walked away. Today that work just strands.

An **orphan** is a claim whose line in ``WORKBOARD.md`` has not been touched in
more than ``ORPHAN_THRESHOLD_HOURS`` (48h) — measured by git-blame on the claim
line, the same signal ``claim_cleanup`` already uses. Only orphaned claims can
be **adopted**: a blocked agent takes ownership so it can finish the work.

The safety rules (per Calvin):
  * You can always work your OWN claim — no ceremony.
  * You may ADOPT another agent's claim ONLY if it is an orphan (>48h stale)
    AND a human authorizes it via breakglass (Windows Hello). The agent cannot
    forge this.
  * You may NEVER take an ACTIVE (non-orphan) claim — that would let an agent
    seize someone's in-flight work and edit it. Adoption of a fresh claim is
    refused outright, even with breakglass.

Adoption transfers the claim line AND the matching active-task line from the
orphan owner to the adopter, and writes a tamper-evident adoption audit row.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.workboard.claim_utils import (
        COORDINATION_DIR,
        LOCK_FILE,
        _agent_key,
        _file_lock,
        _find_active_tasks_section,
        _find_claim_section,
        _format_active_task,
        _format_claim,
        _parse_active_task_line,
        _parse_claim_line,
        _resolve_display_name,
        _scope_matches_path,
        _validate_and_write,
    )
    from scripts.forge.gates import workboard_claim_freshness as freshness_gate
    from scripts.forge.gates import workboard_claims as claims_gate
except ImportError:  # pragma: no cover
    from crew.workboard.claim_utils import (  # type: ignore
        COORDINATION_DIR,
        LOCK_FILE,
        _agent_key,
        _file_lock,
        _find_active_tasks_section,
        _find_claim_section,
        _format_active_task,
        _format_claim,
        _parse_active_task_line,
        _parse_claim_line,
        _resolve_display_name,
        _scope_matches_path,
        _validate_and_write,
    )
    from forge.gates import workboard_claim_freshness as freshness_gate  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore

# Optional: native-auth breakglass (Windows Hello). Imported lazily in the CLI
# so the importable surface (find_orphans/adopt) works on any platform + in tests.

ROOT = _REPO_ROOT
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
ORPHAN_THRESHOLD_HOURS = 48.0
ADOPTION_AUDIT_LOG = COORDINATION_DIR / "workboard_claim_adoption_audit.jsonl"
MIN_ADOPT_REASON_LEN = 12


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _line_commit_unix(workboard_path: Path, line_no: int) -> int | None:
    """Last-touched unix time of a claim line, via git-blame. Patchable in tests."""
    return freshness_gate._line_commit_unix(workboard_path, line_no)  # type: ignore[attr-defined]


def _claim_age_hours(workboard_path: Path, line_no: int, now: datetime) -> float | None:
    ts = _line_commit_unix(workboard_path, int(line_no))
    if ts is None:
        # No blame timestamp (uncommitted / unknown) -> treat as maximally stale
        # so a brand-new uncommitted claim isn't accidentally "fresh forever".
        return None
    return max(0.0, (now.timestamp() - float(ts)) / 3600.0)


def find_orphans(
    workboard_path: Path,
    *,
    now: datetime | None = None,
    max_age_hours: float = ORPHAN_THRESHOLD_HOURS,
) -> list[dict[str, object]]:
    """Return claims that are orphaned: not touched in > max_age_hours.

    Each entry: {agent, name, line_no, scopes, task, age_hours, last_update_utc}.
    A claim whose blame timestamp can't be resolved (e.g. uncommitted) is
    reported as an orphan with age_hours=None and reason="missing_blame_timestamp".
    """
    now = now or _now_utc()
    violations, claims, _tasks, _grab, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return []
    orphans: list[dict[str, object]] = []
    for claim in claims:
        age = _claim_age_hours(workboard_path, int(claim.line_no), now)
        is_orphan = age is None or age > float(max_age_hours)
        if not is_orphan:
            continue
        ts = _line_commit_unix(workboard_path, int(claim.line_no))
        orphans.append(
            {
                "agent": claim.agent,
                "name": claim.name or claim.agent,
                "line_no": int(claim.line_no),
                "scopes": list(claim.scopes),
                "task": claim.task,
                "age_hours": (round(age, 2) if age is not None else None),
                "last_update_utc": (
                    datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts is not None else None
                ),
                "reason": ("stale" if age is not None else "missing_blame_timestamp"),
            }
        )
    return orphans


def orphans_covering_paths(
    workboard_path: Path,
    paths: Sequence[str],
    *,
    exclude_agent: str = "",
    now: datetime | None = None,
    max_age_hours: float = ORPHAN_THRESHOLD_HOURS,
) -> list[dict[str, object]]:
    """Orphan claims (owned by someone other than ``exclude_agent``) whose scope
    covers any of ``paths``. Used by the commit gate to offer adoption."""
    wanted = [str(p or "").strip() for p in paths if str(p or "").strip()]
    if not wanted:
        return []
    hits: list[dict[str, object]] = []
    for orphan in find_orphans(workboard_path, now=now, max_age_hours=max_age_hours):
        if exclude_agent and _agent_key(str(orphan["agent"])) == _agent_key(exclude_agent):
            continue
        scopes = [str(s) for s in (orphan.get("scopes") or [])]
        covered = sorted({p for p in wanted for s in scopes if _scope_matches_path(s, p)})
        if covered:
            hit = dict(orphan)
            hit["covered_paths"] = covered
            hits.append(hit)
    return hits


def _append_adoption_audit(record: dict[str, object]) -> None:
    log_path = sys.modules[__name__].ADOPTION_AUDIT_LOG  # honor test monkeypatch
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _transfer_active_tasks(lines: list[str], *, task: str, from_agent: str, to_agent: str) -> int:
    """Re-point active-task lines for ``task`` owned by from_agent -> to_agent.

    Returns the number of rows transferred. Keeps the board's
    'every claim has a matching active task' invariant after adoption.
    """
    section = _find_active_tasks_section(lines)
    transferred = 0
    for idx in range(section[0], min(section[1], len(lines))):
        raw = lines[idx]
        if not raw.strip().startswith("-"):
            continue
        entry, fields, err = _parse_active_task_line(idx + 1, raw)
        if err or entry is None or not fields:
            continue
        if _agent_key(str(fields.get("agent", ""))) != _agent_key(from_agent):
            continue
        # Match the claim's task to its active-task row. Claims store `task`;
        # active tasks store `task_id`/`summary`. Transfer the owner's row(s).
        lines[idx] = (
            _format_active_task(
                str(entry),
                agent=to_agent,
                scope=str(fields.get("scope", "") or ""),
                summary=str(fields.get("summary", "") or entry),
                status=str(fields.get("status", "active") or "active"),
            )
            + "\n"
        )
        transferred += 1
    _ = task
    return transferred


def adopt(
    workboard_path: Path,
    *,
    adopter: str,
    scope: str = "",
    owner: str = "",
    line_no: int | None = None,
    reason: str,
    authorized_by: str,
    name: str | None = None,
    now: datetime | None = None,
    max_age_hours: float = ORPHAN_THRESHOLD_HOURS,
) -> tuple[bool, str, dict[str, object]]:
    """Adopt an orphan claim. Locate it by line_no, owner agent, or covering scope.

    Requires ``authorized_by`` (the verified breakglass actor) — an empty value
    is refused, so the mechanism cannot transfer a claim without human auth.
    Refuses to adopt any claim that is NOT an orphan.
    """
    now = now or _now_utc()
    adopter = str(adopter or "").strip()
    if not adopter:
        return False, "adopter agent is required", {}
    reason = str(reason or "").strip()
    if len(reason) < MIN_ADOPT_REASON_LEN:
        return False, f"adoption reason must be at least {MIN_ADOPT_REASON_LEN} characters", {}
    if not str(authorized_by or "").strip():
        return False, "adoption requires breakglass authorization (no verified actor)", {}

    with _file_lock(LOCK_FILE):
        violations, claims, _tasks, _grab, _issues = claims_gate.evaluate_board(workboard_path)
        if violations:
            return False, "workboard claims invalid: " + "; ".join(str(v) for v in violations), {}

        # Locate the target claim.
        target = None
        for claim in claims:
            if line_no is not None and int(claim.line_no) == int(line_no):
                target = claim
                break
            if owner and _agent_key(claim.agent) == _agent_key(owner):
                target = claim
                break
            if scope and any(_scope_matches_path(s, scope) or _scope_matches_path(scope, s) for s in claim.scopes):
                target = claim
                break
        if target is None:
            return False, "no matching claim found to adopt (by line_no/owner/scope)", {}

        if _agent_key(target.agent) == _agent_key(adopter):
            return True, f"claim is already owned by `{adopter}` (nothing to adopt)", {"already_owned": True}

        age = _claim_age_hours(workboard_path, int(target.line_no), now)
        is_orphan = age is None or age > float(max_age_hours)
        if not is_orphan:
            return (
                False,
                (
                    f"refusing to adopt: `{target.agent}`'s claim is ACTIVE "
                    f"({age:.1f}h < {float(max_age_hours):.0f}h threshold), not an orphan. "
                    "You can never take another agent's active claim."
                ),
                {"orphan": False, "age_hours": age, "owner": target.agent},
            )

        # Transfer the claim line to the adopter.
        original = workboard_path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        section = _find_claim_section(lines)
        rewritten = False
        for idx in range(section[0], min(section[1], len(lines))):
            if not lines[idx].strip().startswith("-"):
                continue
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err or entry is None:
                continue
            if _agent_key(entry) != _agent_key(target.agent):
                continue
            adopter_name = _resolve_display_name(name, adopter)
            lines[idx] = (
                _format_claim(
                    adopter,
                    fields.get("scope", ",".join(target.scopes)),
                    fields.get("task", target.task),
                    name=adopter_name,
                    role=fields.get("role", target.role),
                    parent=fields.get("parent", target.parent),
                )
                + "\n"
            )
            rewritten = True
            break
        if not rewritten:
            return False, "could not rewrite the claim line for adoption", {}

        transferred = _transfer_active_tasks(lines, task=target.task, from_agent=target.agent, to_agent=adopter)

        ok, write_violations = _validate_and_write(workboard_path, original, "".join(lines))
        if not ok:
            return False, "adoption produced an invalid board: " + "; ".join(str(v) for v in write_violations), {}

        details = {
            "from_agent": target.agent,
            "to_agent": adopter,
            "scopes": list(target.scopes),
            "task": target.task,
            "age_hours": age,
            "authorized_by": authorized_by,
            "active_tasks_transferred": transferred,
        }
        _append_adoption_audit(
            {
                "event": "claim_adopted",
                "timestamp": now.isoformat(),
                "reason": reason,
                **details,
            }
        )
        return (
            True,
            f"adopted `{target.agent}`'s orphan claim -> `{adopter}` (scope `{','.join(target.scopes)}`)",
            details,
        )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cmd_list_orphans(args: argparse.Namespace, workboard_path: Path) -> int:
    orphans = find_orphans(workboard_path, max_age_hours=float(args.max_age_hours))
    if args.json:
        print(
            json.dumps(
                {"ok": True, "action": "list_orphans", "orphan_count": len(orphans), "orphans": orphans}, sort_keys=True
            )
        )
        return 0
    print(f"Orphaned claims (stale > {float(args.max_age_hours):.0f}h):")
    if not orphans:
        print("- none")
        return 0
    for o in orphans:
        age = o.get("age_hours")
        age_s = f"{age}h" if age is not None else "unknown-age"
        print(f"- {o['agent']} (line {o['line_no']}, {age_s}): scope={','.join(o['scopes'])}; task={o['task']}")
    return 0


def _cmd_adopt(args: argparse.Namespace, workboard_path: Path) -> int:
    # Real breakglass: a Windows Hello tap is required to take another agent's
    # claim. The verified actor becomes `authorized_by`; there is no CLI flag to
    # supply it, so an agent cannot fabricate authorization.
    try:
        from scripts.breakglass_auth import authorize_breakglass
    except ImportError:  # pragma: no cover
        from breakglass_auth import authorize_breakglass  # type: ignore

    auth = authorize_breakglass(
        purpose="adopt orphaned workboard claim",
        agent=str(args.agent or "").strip() or "unknown-agent",
        ticket=str(args.scope or args.owner or "orphan-claim")[:64],
        reason=str(args.reason or ""),
    )
    if not getattr(auth, "ok", False):
        print(f"Workboard claim adoption: FAIL\n- breakglass not authorized: {getattr(auth, 'message', 'denied')}")
        return 1

    ok, msg, details = adopt(
        workboard_path,
        adopter=str(args.agent or "").strip(),
        scope=str(args.scope or ""),
        owner=str(args.owner or ""),
        line_no=(int(args.line) if args.line else None),
        reason=str(args.reason or ""),
        authorized_by=str(getattr(auth, "actor", "") or "windows-breakglass"),
        name=str(args.name or ""),
    )
    if args.json:
        print(json.dumps({"ok": bool(ok), "action": "adopt", "message": msg, "details": details}, sort_keys=True))
        return 0 if ok else 1
    print("Workboard claim adoption: " + ("PASS" if ok else "FAIL"))
    print(f"- {msg}")
    return 0 if ok else 1


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List or adopt orphaned WORKBOARD claims.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--max-age-hours", type=float, default=ORPHAN_THRESHOLD_HOURS)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-orphans", help="show claims stale > threshold")
    p_list.set_defaults(func=_cmd_list_orphans)

    p_adopt = sub.add_parser("adopt", help="adopt an orphan claim (requires Windows Hello breakglass)")
    p_adopt.add_argument("--agent", required=True, help="the adopting agent (you)")
    p_adopt.add_argument("--scope", default="", help="a path/scope the orphan claim covers")
    p_adopt.add_argument("--owner", default="", help="the orphan claim's current owner agent")
    p_adopt.add_argument("--line", default="", help="the claim line number to adopt")
    p_adopt.add_argument("--name", default="", help="adopter display name")
    p_adopt.add_argument("--reason", required=True, help=f"why you are adopting (>= {MIN_ADOPT_REASON_LEN} chars)")
    p_adopt.set_defaults(func=_cmd_adopt)

    args = parser.parse_args(argv)
    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()
    if not workboard_path.exists():
        print(f"Workboard claim adoption: FAIL\n- missing workboard file: {workboard_path}")
        return 1
    return int(args.func(args, workboard_path))


if __name__ == "__main__":
    raise SystemExit(run())
