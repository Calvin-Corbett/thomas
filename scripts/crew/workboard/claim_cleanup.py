#!/usr/bin/env python3
"""Detect and optionally clean stale WORKBOARD claims."""

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
    from scripts.crew.workboard import claim as workboard_claim
    from scripts.crew.workboard import claim_evidence_sweep
    from scripts.crew.workboard import issue as workboard_issue
    from scripts.forge.gates import workboard_claim_freshness as freshness_gate
    from scripts.forge.gates import workboard_claims as claims_gate
except Exception:  # pragma: no cover
    from crew.workboard import claim as workboard_claim  # type: ignore
    from crew.workboard import claim_evidence_sweep  # type: ignore
    from forge.gates import workboard_claim_freshness as freshness_gate  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore

    from scripts.crew.workboard import issue as workboard_issue  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _parse_now(now_value: str | None) -> datetime:
    return freshness_gate._parse_now(now_value)  # type: ignore[attr-defined]


def _line_commit_unix(workboard_path: Path, line_no: int) -> int | None:
    return freshness_gate._line_commit_unix(workboard_path, line_no)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# --evidence-sweep (phase 1.4, task 3): a done that cannot re-prove itself
# goes back in the queue. The actual sweep logic lives in
# claim_evidence_sweep.py (one-way import, extracted to stay under this
# file's 800-line cap) -- this module is CLI plumbing only: argument
# parsing, --run-store-db threading, and result printing (including the
# `skipped` list -- db-absent run evidence and malformed evidence are never
# expired, only flagged; see that module's docstring, "EXPIRY REQUIRES
# POSITIVE FAILURE").
# ---------------------------------------------------------------------------

DEFAULT_TTL_HOURS = claim_evidence_sweep.DEFAULT_TTL_HOURS
LEGACY_DONE_WITHOUT_EVIDENCE_REASON = claim_evidence_sweep.LEGACY_DONE_WITHOUT_EVIDENCE_REASON


def _print_evidence_sweep_result(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    print("Workboard evidence sweep: PASS" if payload.get("ok") else "Workboard evidence sweep: FAIL")
    if payload.get("error"):
        print(f"- {payload['error']}")
        for item in list(payload.get("violations") or []):
            print(f"- {item}")
        return
    print(f"- ttl_hours: {payload.get('ttl_hours')}")
    print(f"- expired candidates: {payload.get('expired_candidate_count', 0)}")
    for item in list(payload.get("expired_candidates") or []):
        print(
            f"  - {item.get('task_id')} (agent={item.get('agent')}, verdict={item.get('verdict_status')}): "
            f"{item.get('reason')}"
        )
    for item in list(payload.get("skipped") or []):
        print(f"  - SKIPPED {item.get('task_id')} (agent={item.get('agent')}): {item.get('note')}")
    if payload.get("applied"):
        print(f"- expired: {len(payload.get('expired_task_ids') or [])}")
        print(f"- released claims: {payload.get('released_agent_count', 0)}")
        print(f"- messaged agents: {payload.get('messaged_agent_count', 0)}")
    for item in list(payload.get("errors") or []):
        print(f"- {item}")


def _evidence_sweep_error(workboard_path: Path, applied: bool, error: str, as_json: bool) -> int:
    payload = {
        "action": "workboard_evidence_sweep",
        "ok": False,
        "applied": applied,
        "error": error,
        "workboard": str(workboard_path),
    }
    _print_evidence_sweep_result(payload, as_json)
    return 1


def _run_evidence_sweep(args: argparse.Namespace) -> int:
    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    if args.ttl_hours <= 0:
        return _evidence_sweep_error(workboard_path, bool(args.apply), "--ttl-hours must be > 0", args.json)

    try:
        now = _parse_now(args.now)
    except (ValueError, TypeError) as exc:
        return _evidence_sweep_error(workboard_path, bool(args.apply), f"invalid --now value: {exc}", args.json)

    run_store_db = Path(args.run_store_db).expanduser() if args.run_store_db else None

    violations, candidates, skipped = claim_evidence_sweep.evidence_sweep_candidates(
        workboard_path=workboard_path,
        ttl_hours=float(args.ttl_hours),
        now=now,
        repo_root=ROOT,
        db_path=run_store_db,
    )
    if violations:
        payload = {
            "action": "workboard_evidence_sweep",
            "ok": False,
            "applied": False,
            "error": "workboard claims invalid",
            "expired_candidate_count": 0,
            "expired_candidates": [],
            "violations": list(violations),
            "workboard": str(workboard_path),
        }
        _print_evidence_sweep_result(payload, args.json)
        return 1

    expired_task_ids: list[str] = []
    released_agents: list[str] = []
    messaged_agents: list[str] = []
    apply_errors: list[str] = []
    if args.apply and candidates:
        expired_task_ids, released_agents, messaged_agents, apply_errors = claim_evidence_sweep.apply_evidence_sweep(
            workboard_path=workboard_path,
            candidates=candidates,
            reported_by=args.reported_by,
        )

    payload = {
        "action": "workboard_evidence_sweep",
        "ok": not apply_errors,
        "applied": bool(args.apply),
        "ttl_hours": float(args.ttl_hours),
        "expired_candidate_count": len(candidates),
        "expired_candidates": candidates,
        "expired_task_ids": expired_task_ids,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "released_agent_count": len(sorted(set(released_agents))),
        "released_agents": sorted(set(released_agents), key=str.lower),
        "messaged_agent_count": len(sorted(set(messaged_agents))),
        "messaged_agents": sorted(set(messaged_agents), key=str.lower),
        "workboard": str(workboard_path),
    }
    if apply_errors:
        payload["errors"] = apply_errors
    _print_evidence_sweep_result(payload, args.json)
    return 1 if apply_errors else 0


def _stale_claim_candidates(
    *,
    workboard_path: Path,
    max_age_hours: float,
    now: datetime,
) -> tuple[list[str], list[dict[str, object]]]:
    violations, claims, active_tasks, _grab, issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return list(violations), []

    max_age_seconds = float(max_age_hours) * 3600.0
    now_ts = now.timestamp()
    tasks_by_agent: dict[str, list[claims_gate.ActiveTask]] = {}
    for task in active_tasks:
        tasks_by_agent.setdefault(_norm(task.agent), []).append(task)

    stale_claims: list[dict[str, object]] = []
    for claim in claims:
        claim_ts = _line_commit_unix(workboard_path, int(claim.line_no))
        stale = False
        claim_item: dict[str, object] = {
            "agent": claim.agent,
            "line_no": int(claim.line_no),
            "task": claim.task,
            "scopes": list(claim.scopes),
        }
        if claim_ts is None:
            stale = True
            claim_item["issue"] = "missing_blame_timestamp"
        else:
            age_seconds = max(0.0, now_ts - float(claim_ts))
            if age_seconds > max_age_seconds:
                stale = True
                claim_item["age_hours"] = round(age_seconds / 3600.0, 2)
                claim_item["last_update_utc"] = datetime.fromtimestamp(claim_ts, tz=timezone.utc).isoformat()

        if not stale:
            continue

        task_rows = tasks_by_agent.get(_norm(claim.agent), [])
        task_ids = [task.task_id for task in task_rows]
        claim_item["task_ids"] = sorted(set(task_ids), key=str.lower)
        unresolved_issue_ids = sorted(
            {
                issue.issue_id
                for issue in issues
                if _norm(issue.task_id) in {_norm(task_id) for task_id in task_ids} and _norm(issue.state) != "resolved"
            },
            key=str.lower,
        )
        claim_item["unresolved_issue_ids"] = unresolved_issue_ids
        stale_claims.append(claim_item)
    return [], stale_claims


def _unique_stale_agents(stale_claims: list[dict[str, object]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in stale_claims:
        agent = str(item.get("agent", "")).strip()
        key = _norm(agent)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(agent)
    return ordered


def _reassign_owned_open_issues(
    *,
    workboard_path: Path,
    from_owner: str,
    to_owner: str,
) -> tuple[bool, list[str], str | None]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    section_start, section_end = workboard_issue._find_issues_section(lines)  # type: ignore[attr-defined]
    issue_ids: list[str] = []

    for idx in workboard_issue._bullet_indices(lines, section_start, section_end):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue._parse_issue_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, [], err
        if entry is not None and workboard_issue._is_none_entry(entry):  # type: ignore[attr-defined]
            continue
        if not fields:
            continue
        if _norm(fields.get("owner", "")) != _norm(from_owner):
            continue
        if _norm(fields.get("state", "")) == "resolved":
            continue
        fields["owner"] = to_owner
        lines[idx] = workboard_issue._format_issue(  # type: ignore[attr-defined]
            issue_id=fields["issue_id"],
            task_id=fields["task_id"],
            reporter=fields["reporter"],
            owner=fields["owner"],
            state=fields["state"],
            summary=fields["summary"],
        )
        issue_ids.append(fields["issue_id"])

    if not issue_ids:
        return True, [], None

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    ok, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path, original_text, new_text
    )
    if not ok:
        return False, [], "; ".join(violations)
    return True, issue_ids, None


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report stale WORKBOARD claims and optionally move stale-owned active tasks to "
            "`## Up For Grabs` while releasing stale claims."
        )
    )
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=72.0,
        help="Maximum allowed age for active claim lines in hours (default: 72).",
    )
    parser.add_argument(
        "--now",
        default="",
        help="Optional ISO-8601 current time override (for deterministic tests).",
    )
    parser.add_argument(
        "--reported-by",
        default="workboard-automation",
        help="Reporter id used when moving stale tasks to `## Up For Grabs`.",
    )
    parser.add_argument(
        "--issue-owner",
        default="unassigned",
        help="Owner assigned to unresolved issues currently owned by stale agents (default: unassigned).",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Return non-zero when stale claims are detected (without requiring --apply).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply stale-claim cleanup by moving active tasks to up-for-grabs and releasing claims.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--evidence-sweep",
        action="store_true",
        help=(
            "Walk `status=done` Active Tasks and re-verify their recorded evidence "
            "(claim_evidence.py) instead of the git-blame-based staleness check this tool "
            "otherwise runs; never uses `git blame`. `verified` evidence never expires. "
            "`attested` evidence (e.g. gate kind, or a landed-but-unbound commit/run) does "
            "NOT expire in phase 1.4. Missing/failed evidence whose recorded-done timestamp "
            "(`evidence_recorded_at`, written at the done transition by "
            "reactivate.set_task_status) is older than --ttl-hours expires: driven "
            "done->queued (legal, needs no evidence for that direction), moved to "
            "`## Up For Grabs` annotated with the failed verdict, and the claiming agent is "
            "messaged naming it. A done task with NO evidence and NO recorded timestamp is "
            "the legacy case (predates evidence recording) and expires immediately "
            "regardless of --ttl-hours -- the mechanism that drains pre-1.4 dones. Run-kind "
            "evidence that cannot be re-checked because no --run-store-db was given, and a "
            "stored evidence= field that fails to parse at all, are SKIPPED and printed "
            "loudly for human review -- never auto-expired, since no real check ran (see "
            "--run-store-db). Dry-run by default (prints the would-expire list with "
            "per-task reasons, mutates nothing); combine with --apply to mutate."
        ),
    )
    parser.add_argument(
        "--ttl-hours",
        type=float,
        default=DEFAULT_TTL_HOURS,
        help="With --evidence-sweep, maximum age in hours for a done task's recorded evidence before it expires (default: 72).",
    )
    parser.add_argument(
        "--run-store-db",
        default="",
        help=(
            "With --evidence-sweep, path to a run_store sqlite db to re-verify run-kind evidence against. "
            "Without it, run-kind evidence is SKIPPED (never expired) with a loud note, not treated as failed -- "
            "infrastructure absence is never treated as proof the evidence is bad."
        ),
    )
    args = parser.parse_args(argv)

    if args.evidence_sweep:
        return _run_evidence_sweep(args)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    if args.max_age_hours <= 0:
        message = "--max-age-hours must be > 0"
        payload = {
            "action": "workboard_claim_cleanup",
            "ok": False,
            "applied": bool(args.apply),
            "error": message,
            "workboard": str(workboard_path),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard claim cleanup: FAIL")
            print(f"- {message}")
        return 1

    try:
        now = _parse_now(args.now)
    except Exception as exc:
        message = f"invalid --now value: {exc}"
        payload = {
            "action": "workboard_claim_cleanup",
            "ok": False,
            "applied": bool(args.apply),
            "error": message,
            "workboard": str(workboard_path),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard claim cleanup: FAIL")
            print(f"- {message}")
        return 1

    violations, stale_claims = _stale_claim_candidates(
        workboard_path=workboard_path,
        max_age_hours=float(args.max_age_hours),
        now=now,
    )
    if violations:
        payload = {
            "action": "workboard_claim_cleanup",
            "ok": False,
            "applied": False,
            "error": "workboard claims invalid",
            "stale_claim_count": 0,
            "stale_claims": [],
            "violations": list(violations),
            "workboard": str(workboard_path),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard claim cleanup: FAIL")
            for item in violations:
                print(f"- {item}")
        return 1

    moved_task_ids: list[str] = []
    released_agents: list[str] = []
    reassigned_issue_ids: list[str] = []
    apply_errors: list[str] = []
    stale_agents = _unique_stale_agents(stale_claims)

    if args.apply and stale_agents:
        for agent in stale_agents:
            board_violations, _claims, active_tasks, _grab, _issues = claims_gate.evaluate_board(workboard_path)
            if board_violations:
                apply_errors.append("workboard became invalid before cleanup apply")
                break

            for task in sorted(
                [row for row in active_tasks if _norm(row.agent) == _norm(agent)],
                key=lambda item: str(item.task_id).lower(),
            ):
                ok, message = workboard_issue.move_task_to_up_for_grabs(
                    workboard_path,
                    task_id=task.task_id,
                    reported_by=args.reported_by,
                    summary=None,
                )
                if ok:
                    moved_task_ids.append(task.task_id)
                else:
                    apply_errors.append(f"failed moving task `{task.task_id}` for `{agent}` to up-for-grabs: {message}")

            # Stale-claim reclaim: the task is moved to up-for-grabs above precisely
            # because the claim went stale before the task finished.
            ok_release, release_msg = workboard_claim.release(
                workboard_path, agent=agent, require_done_state=False
            )
            if ok_release:
                released_agents.append(agent)
            elif "no active claim found" in _norm(release_msg):
                post_violations, post_claims, _post_tasks, _post_grab, _post_issues = claims_gate.evaluate_board(
                    workboard_path
                )
                if post_violations:
                    apply_errors.append("workboard became invalid while checking claim release result")
                elif not any(_norm(claim.agent) == _norm(agent) for claim in post_claims):
                    released_agents.append(agent)
            else:
                apply_errors.append(f"failed releasing claim for `{agent}`: {release_msg}")

            ok_reassign, issue_ids, issue_err = _reassign_owned_open_issues(
                workboard_path=workboard_path,
                from_owner=agent,
                to_owner=args.issue_owner,
            )
            if ok_reassign:
                reassigned_issue_ids.extend(issue_ids)
            else:
                apply_errors.append(
                    f"failed reassigning unresolved issues for `{agent}`: {issue_err or 'unknown error'}"
                )

    stale_task_ids = sorted(
        {
            str(task_id).strip()
            for claim in stale_claims
            for task_id in (claim.get("task_ids") or [])
            if str(task_id).strip()
        },
        key=str.lower,
    )
    payload = {
        "action": "workboard_claim_cleanup",
        "ok": not apply_errors,
        "applied": bool(args.apply),
        "max_age_hours": float(args.max_age_hours),
        "stale_claim_count": len(stale_claims),
        "stale_claims": stale_claims,
        "stale_agent_count": len(stale_agents),
        "stale_agents": stale_agents,
        "candidate_task_count": len(stale_task_ids),
        "candidate_task_ids": stale_task_ids,
        "moved_task_count": len(sorted(set(moved_task_ids))),
        "moved_task_ids": sorted(set(moved_task_ids), key=str.lower),
        "released_agent_count": len(sorted(set(released_agents))),
        "released_agents": sorted(set(released_agents), key=str.lower),
        "reassigned_issue_count": len(sorted(set(reassigned_issue_ids))),
        "reassigned_issue_ids": sorted(set(reassigned_issue_ids), key=str.lower),
        "workboard": str(workboard_path),
    }
    if apply_errors:
        payload["errors"] = apply_errors

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        if payload["ok"]:
            print("Workboard claim cleanup: PASS")
        else:
            print("Workboard claim cleanup: FAIL")
        print(f"- stale claims: {payload['stale_claim_count']} (max age {float(args.max_age_hours):.1f}h)")
        if stale_agents:
            print(f"- stale agents: {', '.join(stale_agents)}")
        if args.apply:
            print(f"- moved tasks: {payload['moved_task_count']}")
            print(f"- released claims: {payload['released_agent_count']}")
            print(f"- reassigned issues: {payload['reassigned_issue_count']}")
        if apply_errors:
            for item in apply_errors:
                print(f"- {item}")

    if apply_errors:
        return 1
    if args.fail_on_stale and stale_claims:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
