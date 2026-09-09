"""Diagnostics for canonical and suspicious Thomas workboard messages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.crew.workboard.message_queries import empty_audit_payload


def audit_messages(
    workboard_path: Path,
    *,
    agent: str = "",
    peer: str = "",
    task_id: str = "",
    limit: int = 20,
    core: Any,
) -> tuple[bool, dict[str, object]]:
    agent_clean = str(agent or "").strip()
    peer_clean = str(peer or "").strip()
    task_key = core._norm(task_id)
    max_rows = max(1, int(limit or 20))
    if not workboard_path.exists():
        return True, empty_audit_payload(
            agent=agent_clean,
            peer=peer_clean,
            task_id=str(task_id or "").strip(),
            diagnosis="workboard missing; no message lane state is available",
            marker="missing_workboard",
        )

    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = core._find_section(lines, heading_prefix=core.MESSAGE_HEADING)
    if section is None:
        return True, empty_audit_payload(
            agent=agent_clean,
            peer=peer_clean,
            task_id=str(task_id or "").strip(),
            diagnosis="missing Agent Message Traffic section",
            marker="missing_section",
        )

    rows: list[dict[str, str]] = []
    parse_errors: list[dict[str, object]] = []
    candidate_mentions: list[dict[str, object]] = []
    identity_mismatches: list[dict[str, object]] = []
    stale_identity_mismatches: list[dict[str, object]] = []
    for idx in range(section[0], section[1]):
        raw = lines[idx]
        stripped = raw.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if stripped.startswith("- "):
            entry, fields, err = core._parse_kv_entry(idx + 1, raw)
            if err:
                parse_errors.append({"line": idx + 1, "error": err, "text": stripped})
                if core._mentions_agent_context(stripped, agent=agent_clean, peer=peer_clean):
                    candidate_mentions.append({"line": idx + 1, "kind": "malformed_bullet", "text": stripped})
                continue
            if entry is not None and entry.lower() in core.claims_gate.NONE_TOKENS:
                continue
            if not fields:
                continue
            try:
                rows.append(core._normalize_message_fields(fields))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                parse_errors.append({"line": idx + 1, "error": str(exc), "text": stripped})
                if core._mentions_agent_context(stripped, agent=agent_clean, peer=peer_clean):
                    candidate_mentions.append({"line": idx + 1, "kind": "invalid_bullet", "text": stripped})
            continue
        if core._mentions_agent_context(stripped, agent=agent_clean, peer=peer_clean):
            candidate_mentions.append({"line": idx + 1, "kind": "noncanonical_text", "text": stripped})

    agent_key = core._norm(agent_clean)
    peer_key = core._norm(peer_clean)
    agent_is_tm = core._is_task_manager_agent(agent_clean)
    peer_is_tm = core._is_task_manager_agent(peer_clean)

    def _matches(value: str, key: str, is_task_manager: bool) -> bool:
        return (is_task_manager and core._is_task_manager_agent(value)) or core._norm(value) == key

    inbox_rows: list[dict[str, str]] = []
    current_rows: list[dict[str, str]] = []
    cross_task_open_p0: list[dict[str, str]] = []
    awaiting_me = 0
    awaiting_peer = 0
    awaiting_peer_oldest: dict[str, str] | None = None
    for row in rows:
        state = core._norm(row.get("state", ""))
        sender = str(row.get("from") or "")
        recipient = str(row.get("to") or "")
        from_agent = bool(agent_key) and _matches(sender, agent_key, agent_is_tm)
        to_agent = bool(agent_key) and _matches(recipient, agent_key, agent_is_tm)
        from_peer = bool(peer_key) and _matches(sender, peer_key, peer_is_tm)
        row_task_key = core._norm(row.get("task_id", ""))
        if task_key and row_task_key != task_key:
            if (
                state == "open"
                and to_agent
                and (not peer_key or from_peer)
                and core._norm(row.get("priority", "")) == "p0"
            ):
                cross_task_open_p0.append(core._decorate_message(dict(row)))
            continue
        message_text = core._message_search_text(row)
        if to_agent and state == "open":
            inbox_rows.append(core._decorate_message(dict(row)))
        elif (
            state == "open"
            and agent_key
            and not from_agent
            and (
                (from_peer and core._is_ephemeral_agent_identity(recipient))
                or core._mentions_agent_context(message_text, agent=agent_clean, peer=peer_clean)
            )
        ):
            mismatch = core._decorate_message(dict(row))
            mismatch["expected_to"] = agent_clean
            mismatch["actual_to"] = recipient
            mismatch["reason"] = (
                "open peer message is addressed to an ephemeral/unregistered identity"
                if core._is_ephemeral_agent_identity(recipient)
                else "open message mentions this agent but is not addressed to its canonical identity"
            )
            if not task_key and int(mismatch.get("age_seconds") or 0) > core.IDENTITY_MISMATCH_STALE_SECONDS:
                stale_identity_mismatches.append(mismatch)
            else:
                identity_mismatches.append(mismatch)
        if not (from_agent or to_agent):
            continue
        if peer_key:
            to_peer = _matches(recipient, peer_key, peer_is_tm)
            if not (from_peer or to_peer):
                continue
        if state == "resolved":
            continue
        next_row = core._decorate_message(dict(row))
        if to_agent:
            next_row["direction"] = "incoming"
            next_row["awaiting"] = "me" if state == "open" else "thread"
            if state == "open":
                awaiting_me += 1
        else:
            next_row["direction"] = "outgoing"
            next_row["awaiting"] = "peer" if state == "open" else "thread"
            if state == "open":
                awaiting_peer += 1
                if awaiting_peer_oldest is None or int(next_row.get("age_seconds") or 0) > int(
                    awaiting_peer_oldest.get("age_seconds") or 0
                ):
                    awaiting_peer_oldest = next_row
        current_rows.append(next_row)

    current_rows.sort(
        key=lambda row: (
            core._parse_iso_utc(str(row.get("updated_at") or row.get("created_at") or ""))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("msg_id") or ""),
        ),
        reverse=True,
    )
    problem_count = len(parse_errors) + len(candidate_mentions) + len(identity_mismatches) + len(cross_task_open_p0)
    if parse_errors:
        diagnosis = "message section has parse errors; canonical inbox/current views may be incomplete"
    elif candidate_mentions:
        diagnosis = "message section contains noncanonical agent mentions that inbox/current views ignore"
    elif identity_mismatches:
        diagnosis = (
            "message section has open messages routed to noncanonical identities; canonical inbox may be incomplete"
        )
    elif cross_task_open_p0:
        diagnosis = "task filter hides open p0 inbound message(s) on other task ids"
    elif inbox_rows:
        diagnosis = "canonical inbox has open messages for this agent"
    elif awaiting_peer:
        diagnosis = "canonical inbox is empty; current thread is waiting on the peer"
    else:
        diagnosis = "canonical inbox is empty and no suspicious message-section mentions were found"
    payload: dict[str, object] = {
        "agent": agent_clean,
        "peer": peer_clean,
        "task_id": str(task_id or "").strip(),
        "canonical_inbox_count": len(inbox_rows),
        "canonical_current_count": len(current_rows),
        "awaiting_me": awaiting_me,
        "awaiting_peer": awaiting_peer,
        "awaiting_peer_oldest_seconds": int(awaiting_peer_oldest.get("age_seconds") or 0)
        if awaiting_peer_oldest
        else 0,
        "awaiting_peer_msg_id": str(awaiting_peer_oldest.get("msg_id") or "") if awaiting_peer_oldest else "",
        "parse_error_count": len(parse_errors),
        "candidate_mention_count": len(candidate_mentions),
        "identity_mismatch_count": len(identity_mismatches),
        "stale_identity_mismatch_count": len(stale_identity_mismatches),
        "cross_task_open_p0_count": len(cross_task_open_p0),
        "problem_count": problem_count,
        "parse_errors": parse_errors[:max_rows],
        "candidate_mentions": candidate_mentions[:max_rows],
        "identity_mismatches": identity_mismatches[:max_rows],
        "stale_identity_mismatches": stale_identity_mismatches[:max_rows],
        "cross_task_open_p0": cross_task_open_p0[:max_rows],
        "messages": current_rows[:max_rows],
        "diagnosis": diagnosis,
    }
    if problem_count:
        payload["error"] = "message lane audit found problems"
    return problem_count == 0, payload


def record_takeover_decision(
    lines: list[str],
    *,
    taker: str,
    holders: list[str] | tuple[str, ...],
    task: str,
    scope: str,
    authorization_id: str,
    evidence: dict[str, object],
    core: Any,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Resolve only authorization-named rows, or append unique explicit decisions."""
    current = now or datetime.now(timezone.utc)
    now_iso = current.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    section = core._ensure_section(lines, heading=core.MESSAGE_HEADING)
    existing, errors = core._load_messages(lines, section)
    if errors:
        return False, errors[0]
    target_ids = [str(item).strip() for item in list(evidence.get("target_message_ids") or [])]
    if target_ids:
        wanted = set(target_ids)
        holder_keys = {core._norm(holder) for holder in holders}
        hits: dict[str, list[int]] = {msg_id: [] for msg_id in wanted}
        normalized: dict[int, dict[str, str]] = {}
        for idx in core._bullet_indices(lines, section[0], section[1]):
            entry, fields, err = core._parse_kv_entry(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None and entry.lower() in core.claims_gate.NONE_TOKENS:
                continue
            if not fields:
                continue
            row = core._normalize_message_fields(fields)
            if row["msg_id"] in wanted:
                hits[row["msg_id"]].append(idx)
                normalized[idx] = row
        invalid = [msg_id for msg_id, indices in hits.items() if len(indices) != 1]
        if invalid:
            return False, f"takeover target message ids are missing or duplicated: {', '.join(sorted(invalid))}"
        for msg_id, indices in hits.items():
            idx = indices[0]
            row = normalized[idx]
            parties = {core._norm(row.get("from", "")), core._norm(row.get("to", ""))}
            if (
                core._norm(row.get("task_id", "")) != core._norm(task)
                or row.get("kind") not in {"handoff", "blocker"}
                or row.get("state") != "open"
                or not parties.intersection(holder_keys)
            ):
                return False, f"takeover target `{msg_id}` is not an exact open holder handoff/blocker"
            row.update({"state": "resolved", "decision": "approved", "updated_at": now_iso, "updated_by": taker})
            lines[idx] = core._format_message(row) + ("\n" if lines[idx].endswith("\n") else "")
        return True, f"resolved {len(target_ids)} authorization-targeted handoff/blocker message(s)"

    requested_action = json.dumps(
        {
            "action": "exact_takeover_decision",
            "authorization_id": authorization_id,
            "evidence_mode": str(evidence.get("mode") or ""),
            "scope": scope,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    for holder in holders:
        row = {
            "msg_id": core._next_message_id(existing, taker),
            "from": taker,
            "to": holder,
            "task_id": task,
            "kind": "handoff",
            "priority": "p0",
            "state": "resolved",
            "summary": "Exact takeover recorded after holder eligibility verification",
            "requested_action": requested_action,
            "decision": "approved",
            "created_at": now_iso,
            "updated_at": now_iso,
            "updated_by": taker,
        }
        section = core._ensure_section(lines, heading=core.MESSAGE_HEADING)
        none_idx = next(
            (
                idx
                for idx in core._bullet_indices(lines, section[0], section[1])
                if lines[idx].strip().casefold() in {"- none", "- none."}
            ),
            None,
        )
        rendered = core._format_message(row) + "\n"
        if none_idx is None:
            lines.insert(section[1], rendered)
        else:
            lines[none_idx] = rendered
        existing.append(row)
    return True, "recorded explicit resolved takeover decision"
