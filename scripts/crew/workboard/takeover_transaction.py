"""In-memory exact-scope handoff preparation for Workboard claims."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from scripts.crew.workboard.claim_utils import (
    _agent_key,
    _find_claim_section,
    _normalize_scope_token,
    _parse_claim_line,
)

ReleaseTask = Callable[..., tuple[bool, str]]
ValidateWrite = Callable[..., tuple[bool, Sequence[str]]]
AppendAudit = Callable[..., dict[str, object]]
CheckBarrier = Callable[[str], None]


def _transaction_marker_path(workboard_path: Path) -> Path:
    resolved = workboard_path.resolve()
    root = (
        resolved.parents[2]
        if resolved.name.casefold() == "workboard.md" and resolved.parent.name.casefold() == "thomas"
        else resolved.parent
    )
    return root / "runtime" / "coordination" / "workboard_takeover_transaction.json"


def _persist_marker(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    if json.loads(path.read_text(encoding="utf-8")) != payload:
        raise RuntimeError("takeover transaction marker durability readback failed")


def _clear_marker(path: Path) -> None:
    path.unlink()
    if path.exists():
        raise RuntimeError("takeover transaction marker could not be cleared")


def _scope_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in (_normalize_scope_token(part) for part in str(value or "").split(",")) if token)


def prepare_exact_takeover(
    lines: list[str],
    *,
    requested_scope: str,
    conflicting_agents: Sequence[str],
    release_active_task: ReleaseTask,
) -> tuple[bool, str, tuple[str, ...]]:
    """Remove complete foreign claims/tasks in memory or refuse unchanged scope."""
    requested = _scope_tokens(requested_scope)
    if not requested:
        return False, "takeover scope is required", ()
    targets = tuple(sorted({_agent_key(agent): agent for agent in conflicting_agents}.values(), key=str.casefold))
    rows: dict[str, tuple[int, dict[str, str]]] = {}
    start, end = _find_claim_section(lines)
    for idx in range(start, min(end, len(lines))):
        if not lines[idx].strip().startswith("-"):
            continue
        entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
        if err:
            return False, err, ()
        if entry and fields:
            rows[_agent_key(entry)] = (idx, fields)

    for other in targets:
        row = rows.get(_agent_key(other))
        if row is None:
            return False, f"takeover claim for `{other}` disappeared before handoff", ()
        held = _scope_tokens(row[1].get("scope", ""))
        if len(requested) != len(held) or set(requested) != set(held):
            return (
                False,
                (
                    f"exact-scope takeover required for `{other}`: requested `{requested_scope}` "
                    f"but the claim also owns `{','.join(held)}`"
                ),
                (),
            )

    # Work on a copy until every release succeeds. The caller's board buffer
    # remains untouched on a multi-task or parse failure.
    staged = list(lines)
    for other in targets:
        released, release_message = release_active_task(staged, agent=other)
        if not released:
            return False, f"cannot release `{other}` for takeover: {release_message}", ()
        start, end = _find_claim_section(staged)
        removed = False
        for idx in range(min(end, len(staged)) - 1, start - 1, -1):
            if not staged[idx].strip().startswith("-"):
                continue
            entry, _fields, err = _parse_claim_line(idx + 1, staged[idx])
            if err:
                return False, err, ()
            if entry and _agent_key(entry) == _agent_key(other):
                del staged[idx]
                removed = True
                break
        if not removed:
            return False, f"takeover claim for `{other}` could not be removed", ()
    start, end = _find_claim_section(staged)
    if not any(staged[idx].strip().startswith("-") for idx in range(start, min(end, len(staged)))):
        staged.insert(start, "- none\n")
    lines[:] = staged
    return True, "foreign claims released in memory", targets


def record_takeover_decision(
    lines: list[str],
    *,
    taker: str,
    holders: Sequence[str],
    task: str,
    scope: str,
    authorization_id: str,
    evidence: dict[str, object],
    now=None,
) -> tuple[bool, str]:
    from scripts.crew.workboard import message as message_core
    from scripts.crew.workboard.message_audit import record_takeover_decision as record

    return record(
        lines,
        taker=taker,
        holders=tuple(holders),
        task=task,
        scope=scope,
        authorization_id=authorization_id,
        evidence=evidence,
        core=message_core,
        now=now,
    )


def execute_takeover_transaction(
    *,
    workboard_path: Path,
    original_text: str,
    intermediate_text: str,
    successor_text: str,
    agent: str,
    holders: Sequence[str],
    task: str,
    scope: str,
    reason: str,
    authorization_id: str,
    evidence: dict[str, object],
    validate_write: ValidateWrite,
    append_audit: AppendAudit,
    check_barrier: CheckBarrier,
    require_claims_to_have_active_task: bool,
    allow_blocked_without_issue: bool,
) -> tuple[bool, str]:
    before_sha = hashlib.sha256(workboard_path.read_bytes()).hexdigest()
    if workboard_path.read_text(encoding="utf-8") != original_text:
        return False, "workboard changed before takeover transaction intent"
    marker_path = _transaction_marker_path(workboard_path)
    if marker_path.exists():
        return False, f"an unresolved takeover transaction marker already exists: {marker_path}"
    transaction_id = str(uuid.uuid4())
    marker: dict[str, object] = {
        "transaction_id": transaction_id,
        "workboard": str(workboard_path.resolve()),
        "agent": agent,
        "holders": sorted(set(holders)),
        "task": task,
        "scope": scope,
        "before_sha": before_sha,
        "state": "prepared",
    }

    def audit(stage: str, board_sha: str, rollback_reason: str = "") -> dict[str, object]:
        record = append_audit(
            agent=agent,
            reason=reason,
            scope=scope,
            takeover_from=holders,
            stage=stage,
            task=task,
            authorization_id=authorization_id,
            before_sha=before_sha,
            board_sha=board_sha,
            evidence={**evidence, "transaction_id": transaction_id},
            rollback_reason=rollback_reason,
            workboard_path=workboard_path,
        )
        if not isinstance(record, dict) or record.get("event") != stage or record.get("board_sha") != board_sha:
            raise RuntimeError(f"takeover {stage} audit did not confirm a durable exact append")
        return record

    def mark(state: str, **updates: object) -> None:
        marker.update({"state": state, **updates})
        _persist_marker(marker_path, marker)

    def write(expected: str, replacement: str) -> tuple[bool, str]:
        try:
            ok, violations = validate_write(
                workboard_path,
                expected,
                replacement,
                require_claims_to_have_active_task=require_claims_to_have_active_task,
                allow_blocked_without_issue=allow_blocked_without_issue,
            )
        except Exception as exc:
            return False, str(exc)
        if not ok:
            return False, "; ".join(str(item) for item in violations)
        try:
            if workboard_path.read_text(encoding="utf-8") != replacement:
                return False, "workboard durability readback differs from takeover state"
        except OSError as exc:
            return False, f"workboard durability readback failed: {exc}"
        return True, ""

    def current_sha() -> str:
        return hashlib.sha256(workboard_path.read_bytes()).hexdigest()

    def rollback(current_expected: str, expected_sha: str, failure: str) -> tuple[bool, str]:
        try:
            current_matches = (
                current_sha() == expected_sha and workboard_path.read_text(encoding="utf-8") == current_expected
            )
        except OSError as exc:
            current_matches = False
            failure = f"{failure}; rollback read failed: {exc}"
        if not current_matches:
            mark("recovery_required", failure=failure, observed_sha=current_sha())
            try:
                audit("takeover_recovery_required", current_sha(), failure)
            except Exception:
                pass
            return False, "takeover requires manual recovery because current board is not the known transaction state"
        restored, restore_error = write(current_expected, original_text)
        if not restored or current_sha() != before_sha:
            detail = f"{failure}; rollback restore failed: {restore_error or 'original SHA mismatch'}"
            mark("recovery_required", failure=detail, observed_sha=current_sha())
            try:
                audit("takeover_recovery_required", current_sha(), detail)
            except Exception:
                pass
            return False, "takeover requires manual recovery because exact board restoration failed"
        try:
            mark("rolled_back", failure=failure, board_sha=before_sha)
            audit("takeover_rolled_back", before_sha, failure)
            _clear_marker(marker_path)
        except Exception as exc:
            mark("recovery_required", failure=f"rollback audit failed: {exc}", board_sha=before_sha)
            return False, f"takeover board restored but rollback audit requires recovery: {exc}"
        return True, "takeover rolled back to the exact original board"

    try:
        check_barrier("")
        mark("prepared")
        audit("takeover_intent", before_sha)
        mark("intent_recorded", board_sha=before_sha)
    except Exception as exc:
        if marker_path.exists():
            mark("recovery_required", failure=f"intent audit failed: {exc}")
        return False, f"cannot append takeover intent audit; recovery marker retained: {exc}"
    try:
        check_barrier(transaction_id)
    except Exception as exc:
        rolled_back, rollback_message = rollback(original_text, before_sha, f"barrier before holder release: {exc}")
        return False, f"takeover blocked before holder release: {exc}; {rollback_message}"
    ok, failure = write(original_text, intermediate_text)
    if not ok:
        observed_sha = current_sha()
        if workboard_path.read_text(encoding="utf-8") == intermediate_text:
            rolled_back, rollback_message = rollback(
                intermediate_text, observed_sha, f"intermediate release failed: {failure}"
            )
        else:
            mark("recovery_required", failure=f"intermediate release failed: {failure}", observed_sha=observed_sha)
            rolled_back, rollback_message = False, "takeover requires manual recovery"
        return False, f"takeover intermediate release failed: {failure}; {rollback_message}"
    intermediate_sha = current_sha()
    try:
        mark("holder_released", board_sha=intermediate_sha)
        check_barrier(transaction_id)
        audit("takeover_holder_released", intermediate_sha)
        mark("holder_release_recorded", board_sha=intermediate_sha)
    except Exception as exc:
        _rolled_back, rollback_message = rollback(
            intermediate_text, intermediate_sha, f"holder release audit failed: {exc}"
        )
        return False, f"takeover holder release audit failed: {exc}; {rollback_message}"
    try:
        check_barrier(transaction_id)
    except Exception as exc:
        _rolled_back, rollback_message = rollback(
            intermediate_text, intermediate_sha, f"barrier before successor ownership: {exc}"
        )
        return False, f"takeover blocked before successor ownership: {exc}; {rollback_message}"
    ok, failure = write(intermediate_text, successor_text)
    if not ok:
        _rolled_back, rollback_message = rollback(
            intermediate_text, intermediate_sha, f"successor ownership failed: {failure}"
        )
        return False, f"takeover successor ownership failed: {failure}; {rollback_message}"
    final_sha = current_sha()
    try:
        mark("successor_owned", board_sha=final_sha)
        check_barrier(transaction_id)
        audit("takeover_committed", final_sha)
        mark("committed", board_sha=final_sha)
        _clear_marker(marker_path)
    except Exception as exc:
        _rolled_back, rollback_message = rollback(successor_text, final_sha, f"commit audit failed: {exc}")
        return False, f"takeover commit audit failed: {exc}; {rollback_message}"
    return True, "takeover transaction committed"
