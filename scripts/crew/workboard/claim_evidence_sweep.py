#!/usr/bin/env python3
"""A done that cannot re-prove itself goes back in the queue (phase 1.4,
task 3, fix round 1). Extracted out of `claim_cleanup.py` to keep that file
under the monolith guard's 800-line soft limit; one-way dependency --
`claim_cleanup.py` imports this module, nothing here imports it back.

DELIBERATELY SEPARATE from `claim_cleanup._stale_claim_candidates`: that
detector keys on `git blame` of the claim line, banned for this feature (an
uncommitted line reads age-0.00h). Everything below keys ONLY on
`claim_evidence.read_evidence`'s stored `evidence_recorded_at` (written at
the done transition, phase 1.4 task 2) and a FRESH `claim_evidence.
verify_evidence` re-check run right now.

EXPIRY REQUIRES POSITIVE FAILURE, NO EXCEPTIONS (fix rounds 1 and 2,
post-review). The first version treated any `"failed"` verdict as evidence
the sweep could act on, including `verify_evidence`'s db-absent
short-circuit for run-kind evidence (`db_path=None` -> `"failed"` before any
real check ever ran). That let a legitimately-verified-at-done run expire
simply because the operator running the sweep hadn't configured
`--run-store-db` -- infrastructure absence masquerading as proof the
evidence was bad. Round 2 found the same shape half-applied on the
commit-kind side: `_verify_commit`'s `OSError` branch (`git` itself failing
to run) was still an unmarked `"failed"`. Three things now distinguish a
POSITIVE failure (the check ran and the evidence is genuinely bad -- expire
it) from an ABSENT check (the check never ran -- skip it, flag it, never
silently punish the claim for a state it never entered): `Verdict.
reason_code` membership in `claim_evidence.UNAVAILABLE_REASON_CODES` (covers
both the run-kind db-absent case and the commit-kind git-unavailable case --
membership, not equality to one constant, so a future third code needs no
new branch here), and a stored `evidence=` field that fails to parse at all
(a `ValueError` from `read_evidence` means nothing was ever checked, not
that a check failed). All three land in `skipped`, never `candidates` --
`--apply` never expires any of them; only a human deciding to fix the
config, the environment, or the line itself moves them forward.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.tasks import reactivate as task_reactivate
    from scripts.crew.workboard import claim as workboard_claim
    from scripts.crew.workboard import claim_evidence
    from scripts.crew.workboard import issue as workboard_issue
    from scripts.crew.workboard import message as workboard_message
    from scripts.forge.gates import workboard_claims as claims_gate
    from thomas.marketplace.observability import run_store
except ImportError:  # pragma: no cover
    from crew.tasks import reactivate as task_reactivate  # type: ignore
    from crew.workboard import claim as workboard_claim  # type: ignore
    from crew.workboard import claim_evidence  # type: ignore
    from crew.workboard import message as workboard_message  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore

    from scripts.crew.workboard import issue as workboard_issue  # type: ignore
    from thomas.marketplace.observability import run_store  # type: ignore


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


DEFAULT_TTL_HOURS = 72.0
LEGACY_DONE_WITHOUT_EVIDENCE_REASON = "legacy done without evidence"
RUN_DB_UNAVAILABLE_NOTE = "run evidence unverifiable without --run-store-db - skipped, not expired"
GIT_UNAVAILABLE_NOTE = "commit evidence unverifiable because git itself failed to run - skipped, not expired"
MALFORMED_EVIDENCE_NOTE_SUFFIX = "skipped, not expired, needs human review"

# The rule has no exceptions (fix round 2): ANY reason_code in
# claim_evidence.UNAVAILABLE_REASON_CODES means no real check ran, so every
# one of them routes to `skipped`, never `candidates`. This map supplies the
# human-readable note per code; a code with no entry here still skips (the
# `.get(..., ...)` fallback below), it just gets a generic note instead of a
# tailored one -- so a future third code added to claim_evidence never has
# to be wired in here to stay safe, only to read well.
_UNAVAILABLE_NOTES: dict[str, str] = {
    claim_evidence.REASON_CODE_DB_PATH_REQUIRED: RUN_DB_UNAVAILABLE_NOTE,
    claim_evidence.REASON_CODE_GIT_UNAVAILABLE: GIT_UNAVAILABLE_NOTE,
}
_GENERIC_UNAVAILABLE_NOTE = "evidence unverifiable because the check itself could not run - skipped, not expired"


def parse_recorded_at(raw: str | None) -> datetime | None:
    """Parse a stored `evidence_recorded_at` string into a tz-aware UTC
    datetime. Naive input is treated as UTC (never raises on comparison) --
    the same convention `claim_evidence._ensure_aware` documents, applied
    independently here so this module's TTL math never silently depends on
    that private helper staying naive-tolerant.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _consider_candidate(
    candidates: list[dict[str, object]],
    *,
    task: claims_gate.ActiveTask,
    verdict_status: str,
    reason: str,
    recorded_at: str | None,
    now: datetime,
    ttl_hours: float,
    gate_by_ttl: bool,
) -> None:
    """Append a would-expire entry unless a still-readable recorded
    timestamp is younger than `ttl_hours`. `gate_by_ttl=False` means there
    is nothing to gate on (no timestamp at all) -- expire now.
    """
    age_hours: float | None = None
    if gate_by_ttl:
        recorded_dt = parse_recorded_at(recorded_at)
        if recorded_dt is None:
            return  # a timestamp is present but unreadable -- don't guess an age
        age_hours = (now - recorded_dt).total_seconds() / 3600.0
        if age_hours <= ttl_hours:
            return
        age_hours = round(age_hours, 2)
    candidates.append(
        {
            "task_id": task.task_id,
            "agent": task.agent,
            "summary": task.summary,
            "verdict_status": verdict_status,
            "reason": reason,
            "recorded_at": recorded_at,
            "age_hours": age_hours,
        }
    )


def _malformed_evidence_recorded_at(workboard_path: Path, task_id: str) -> str | None:
    """Recover `evidence_recorded_at` for a task whose stored `evidence=`
    field failed to parse (`read_evidence` raises before it can return one).
    Reuses `claim_evidence`'s own private line-grammar helpers.
    """
    lines = workboard_path.read_text(encoding="utf-8").splitlines(keepends=True)
    try:
        idx = claim_evidence._find_task_line(lines, task_id)  # type: ignore[attr-defined]
    except ValueError:
        return None
    fields = claim_evidence._parse_task_line_fields(lines[idx])  # type: ignore[attr-defined]
    return fields.get("evidence_recorded_at")


def _skip(skipped: list[dict[str, object]], *, task: claims_gate.ActiveTask, note: str) -> None:
    skipped.append({"task_id": task.task_id, "agent": task.agent, "note": note})


def evidence_sweep_candidates(
    *,
    workboard_path: Path,
    ttl_hours: float,
    now: datetime,
    repo_root: Path,
    db_path: Path | None,
) -> tuple[list[str], list[dict[str, object]], list[dict[str, object]]]:
    """Find `status=done` Active Tasks whose recorded evidence cannot
    re-prove itself. Returns `(violations, candidates, skipped)`; never
    mutates the workboard. `now` must be tz-aware.

    `candidates` expire on `--apply`: (a) NO evidence and NO recorded
    timestamp at all (legacy -- predates evidence recording, not gated by
    `ttl_hours`, reason `LEGACY_DONE_WITHOUT_EVIDENCE_REASON`); (b) evidence
    re-verifies `"failed"` for a REAL reason (`reason_code` not in
    `claim_evidence.UNAVAILABLE_REASON_CODES`) AND its recorded timestamp is
    older than `ttl_hours`.

    `skipped` NEVER expires, even under `--apply` -- these are cases where
    no real check ran: a stored `evidence=` field that fails to parse
    (flagged for human review), run-kind evidence whose verify came back
    `"failed"` only because `db_path` was `None` (pass `--run-store-db` to
    actually re-check it), and commit-kind evidence whose verify failed only
    because `git` itself could not run.

    `"verified"`/`"attested"` NEVER expire in phase 1.4: attested is a real,
    checkable claim, just not proof bound to this task, and re-verifying
    without the original claim-time `not_before` routinely downgrades an
    originally-verified commit/run to attested here -- deliberately, so the
    sweep never punishes evidence for losing a binding context it never
    stored in the first place.
    """
    violations, _claims, active_tasks, _grab, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return list(violations), [], []

    candidates: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for task in active_tasks:
        if _norm(task.status) != "done":
            continue

        try:
            record = claim_evidence.read_evidence(task.task_id, workboard_path=workboard_path)
        except ValueError as exc:
            _skip(skipped, task=task, note=f"stored evidence is malformed: {exc} - {MALFORMED_EVIDENCE_NOTE_SUFFIX}")
            continue

        if record.evidence is None:
            _consider_candidate(
                candidates,
                task=task,
                verdict_status="missing",
                reason=(LEGACY_DONE_WITHOUT_EVIDENCE_REASON if not record.recorded_at else "no evidence recorded"),
                recorded_at=record.recorded_at,
                now=now,
                ttl_hours=ttl_hours,
                gate_by_ttl=bool(record.recorded_at),
            )
            continue

        # A run-kind verify re-points run_store's module-global _DB_PATH as a
        # side effect (claim_evidence's BINDING SEMANTICS docstring). Save
        # and restore around the call exactly like reactivate.set_task_status
        # does, so a sweep never leaves a process pointed at a fixture db.
        saved_db_path = run_store._DB_PATH
        try:
            verdict = claim_evidence.verify_evidence(
                record.evidence,
                repo_root,
                db_path=db_path,
                task_id=task.task_id,
            )
        finally:
            run_store._DB_PATH = saved_db_path

        if verdict.status in ("verified", "attested"):
            continue

        if verdict.reason_code in claim_evidence.UNAVAILABLE_REASON_CODES:
            note = _UNAVAILABLE_NOTES.get(verdict.reason_code, _GENERIC_UNAVAILABLE_NOTE)
            _skip(skipped, task=task, note=note)
            continue

        _consider_candidate(
            candidates,
            task=task,
            verdict_status=verdict.status,
            reason=verdict.reason,
            recorded_at=record.recorded_at,
            now=now,
            ttl_hours=ttl_hours,
            gate_by_ttl=True,
        )

    return [], candidates, skipped


def apply_evidence_sweep(
    *,
    workboard_path: Path,
    candidates: list[dict[str, object]],
    reported_by: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Drive each candidate's legal done->queued transition, move it to
    `## Up For Grabs` annotated with the failed verdict, release the claim
    (ONLY when zero active tasks remain for that agent -- a candidate is
    scoped to one task, and the agent may still be working another), and
    message the claiming agent. Returns `(expired_task_ids, released_agents,
    messaged_agents, errors)`. `candidates` must never include `skipped`
    entries -- callers only pass the expiring list.
    """
    expired_task_ids: list[str] = []
    released_agents: list[str] = []
    messaged_agents: list[str] = []
    errors: list[str] = []

    for item in candidates:
        task_id = str(item["task_id"])
        agent = str(item["agent"])
        reason = str(item["reason"])

        # done -> queued is legal and needs no evidence for this direction.
        ok_status, payload_status = task_reactivate.set_task_status(
            workboard_path,
            task_id=task_id,
            status="queued",
            actor=reported_by,
            enforce_transition=True,
        )
        if not ok_status:
            errors.append(f"failed to queue expired task `{task_id}`: {payload_status.get('error')}")
            continue

        annotated_summary = f"{item.get('summary')} [evidence expired: {reason}]"
        ok_move, move_msg = workboard_issue.move_task_to_up_for_grabs(
            workboard_path,
            task_id=task_id,
            reported_by=reported_by,
            summary=annotated_summary,
        )
        if not ok_move:
            errors.append(f"failed moving expired task `{task_id}` to up-for-grabs: {move_msg}")
            continue
        expired_task_ids.append(task_id)

        board_violations, _claims, remaining_active, _grab, _issues = claims_gate.evaluate_board(workboard_path)
        if board_violations:
            errors.append(f"workboard became invalid after moving `{task_id}`: {'; '.join(board_violations)}")
            continue
        if not any(_norm(row.agent) == _norm(agent) for row in remaining_active):
            # require_done_state=False: the task this claim covered is no
            # longer `done`, it was just driven to `queued` and moved off
            # the board. Same tolerant "no active claim found" handling as
            # claim_cleanup's stale-claim loop -- move_task_to_up_for_grabs
            # may already have released the claim itself.
            ok_release, release_msg = workboard_claim.release(workboard_path, agent=agent, require_done_state=False)
            if ok_release:
                released_agents.append(agent)
            elif "no active claim found" in _norm(release_msg):
                post_violations, post_claims, _post_active, _post_grab, _post_issues = claims_gate.evaluate_board(
                    workboard_path
                )
                if post_violations:
                    errors.append(f"workboard became invalid while checking claim release result for `{agent}`")
                elif not any(_norm(c.agent) == _norm(agent) for c in post_claims):
                    released_agents.append(agent)
            else:
                errors.append(f"failed releasing claim for `{agent}` after expiry: {release_msg}")

        ok_msg, msg_payload = workboard_message.send_message(
            workboard_path,
            sender=reported_by,
            recipient=agent,
            summary=(f"Task `{task_id}` done-claim expired: {reason}. Returned to queue / Up For Grabs."),
            task_id=task_id,
            kind="status",
            priority="p1",
            requested_action="re-claim with valid evidence if you can still supply it",
            decision="none",
        )
        if ok_msg:
            messaged_agents.append(agent)
        else:
            errors.append(f"failed messaging `{agent}` about expired task `{task_id}`: {msg_payload.get('error')}")

    return expired_task_ids, released_agents, messaged_agents, errors
