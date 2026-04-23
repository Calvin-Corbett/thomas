"""Presence inference: detecting inferred agent candidates from activity patterns.

This module handles the logic for inferring agent presence from file activity,
process trees, and family matching algorithms.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import agent_presence as presence_lib


def apply_file_activity(
    rows: list[dict[str, Any]], activity: list[dict[str, Any]], global_presence: dict[str, dict[str, Any]]
) -> None:
    """Apply file activity information to agent rows, updating state and signals."""
    for row in rows:
        scope = presence_lib._normalize_scope(row.get("scope"))
        if not scope:
            continue
        matches = [
            item
            for item in activity
            if any(presence_lib._paths_overlap(str(item.get("path") or ""), claimed) for claimed in scope)
        ]
        if not matches:
            continue
        matches.sort(
            key=lambda item: (
                (item.get("age_seconds") is None),
                int(item.get("age_seconds") or 10**9),
                str(item.get("path") or ""),
            )
        )
        recent_paths = [str(item.get("path") or "") for item in matches[:8] if str(item.get("path") or "").strip()]
        row["recent_paths"] = presence_lib._dedupe([*list(row.get("recent_paths") or []), *recent_paths])[:8]
        row["activity_count"] = len(matches)
        latest = next(
            (str(item.get("modified_at") or "") for item in matches if str(item.get("modified_at") or "").strip()), ""
        )
        if latest:
            row["last_activity_at"] = latest
        row["source_signals"] = presence_lib._dedupe([*list(row.get("source_signals") or []), "file_activity"])
        family = presence_lib._family_from_agent_label(str(row.get("agent_id") or row.get("display_name") or ""))
        family_presence = global_presence.get(family) if family else None
        if "process_tree" in list(row.get("source_signals") or []) and str(row.get("state") or "") in {
            "declared",
            "unregistered",
            "stale",
        }:
            row["state"] = "active"
            row["confidence"] = "high" if str(row.get("confidence") or "") == "high" else "medium"
        elif family_presence and str(row.get("state") or "") in {"declared", "stale"}:
            row["state"] = "active"
            row["confidence"] = "medium"
            row["source_signals"] = presence_lib._dedupe(
                [*list(row.get("source_signals") or []), "global_agent_process"]
            )
            row["warnings"] = presence_lib._dedupe(
                [
                    *list(row.get("warnings") or []),
                    f"{presence_lib._display_name_for_family(family)} has a live process tree and fresh activity in its claimed scope.",
                ]
            )
            row["evidence"] = presence_lib._dedupe(
                [*list(row.get("evidence") or []), *list(family_presence.get("commands") or [])]
            )[:8]
            row["process_pids"] = presence_lib._dedupe(
                [*list(row.get("process_pids") or []), *list(family_presence.get("pids") or [])]
            )
        elif str(row.get("state") or "") == "unregistered" and recent_paths:
            row["confidence"] = "medium"


def _read_inferred_state(repo_root: Path) -> dict[str, Any]:
    payload = presence_lib._read_json(presence_lib.inferred_state_path(repo_root), {})
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("entries", [])
    payload.setdefault("inferred_applied", [])
    payload.setdefault("inferred_suppressed", [])
    payload.setdefault("inferred_expired", [])
    return payload


def _reduce_inferred_scope(path: str) -> str:
    token = presence_lib._normalize_relpath(path)
    if not token or presence_lib._is_noise_activity_path(token):
        return ""
    parts = [piece for piece in token.split("/") if piece]
    if not parts:
        return ""
    if len(parts) >= 2 and parts[0] == "thomas":
        return "/".join(parts[:2])
    if len(parts) >= 2 and parts[0] == "apps":
        return "/".join(parts[:2])
    if len(parts) >= 2 and parts[0] == "plans" and parts[1] == "thomas":
        return "plans/thomas"
    if parts[0] == "scripts":
        return "scripts"
    if len(parts) >= 2 and parts[0] in {"tests", "docs"}:
        return parts[0]
    if len(parts) == 1:
        return parts[0]
    return parts[0]


def _live_family_presence(
    rows: Sequence[dict[str, Any]], global_presence: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {
        str(key): dict(value or {}) for key, value in dict(global_presence or {}).items() if str(key).strip()
    }
    for row in rows:
        family = presence_lib._family_from_agent_label(str(row.get("agent_id") or row.get("display_name") or ""))
        if not family:
            continue
        if str(row.get("state") or "") not in {"active", "alive"}:
            continue
        item = families.setdefault(family, {"family": family, "pids": [], "commands": []})
        item["pids"] = presence_lib._dedupe(
            [*list(item.get("pids") or []), *[str(v) for v in list(row.get("process_pids") or []) if str(v).strip()]]
        )
        item["commands"] = presence_lib._dedupe(
            [*list(item.get("commands") or []), *[str(v) for v in list(row.get("evidence") or []) if str(v).strip()]]
        )[:8]
    return families


def _claim_conflict(
    claims: Sequence[dict[str, Any]], *, agent_id: str, scope: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    same_agent: dict[str, Any] | None = None
    other_agent: dict[str, Any] | None = None
    for row in claims:
        claim_scope = presence_lib._normalize_scope(row.get("scope"))
        if not claim_scope or not any(presence_lib._paths_overlap(scope, item) for item in claim_scope):
            continue
        row_agent = str(row.get("agent_id") or "").strip()
        if not row_agent:
            continue
        if row_agent.lower() == str(agent_id or "").strip().lower():
            same_agent = row
        elif not bool(row.get("inferred")):
            other_agent = row
            break
    return same_agent, other_agent


def _match_families_for_scope(
    rows: Sequence[dict[str, Any]], *, scope: str, path: str, live_families: set[str]
) -> set[str]:
    matches: set[str] = set()
    for row in rows:
        family = presence_lib._family_from_agent_label(str(row.get("agent_id") or row.get("display_name") or ""))
        if not family or family not in live_families:
            continue
        row_scope = presence_lib._normalize_scope(row.get("scope"))
        recent_paths = [str(item) for item in list(row.get("recent_paths") or []) if str(item).strip()]
        if row_scope and any(
            presence_lib._paths_overlap(scope, item) or presence_lib._paths_overlap(path, item) for item in row_scope
        ):
            matches.add(family)
            continue
        if recent_paths and any(
            presence_lib._paths_overlap(path, item) or presence_lib._paths_overlap(scope, _reduce_inferred_scope(item))
            for item in recent_paths
        ):
            matches.add(family)
    return matches


def infer_claim_candidates(
    *,
    rows: Sequence[dict[str, Any]],
    activity: Sequence[dict[str, Any]],
    global_presence: dict[str, dict[str, Any]],
    workboard_claims: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Infer agent candidates from activity, process trees, and scope matching.

    Returns (candidates, suppressed).
    """
    family_presence = _live_family_presence(rows, global_presence)
    live_families = {
        family
        for family, details in family_presence.items()
        if list(details.get("pids") or []) or list(details.get("commands") or [])
    }
    candidates_by_key: dict[str, dict[str, Any]] = {}
    suppressed: list[dict[str, Any]] = []
    scope_agents: dict[str, set[str]] = {}

    for item in activity:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        scope = _reduce_inferred_scope(path)
        if not scope:
            continue
        matches = _match_families_for_scope(rows, scope=scope, path=path, live_families=live_families)
        reason = "scope_match"
        confidence = "high"
        if not matches:
            if len(live_families) == 1:
                matches = set(live_families)
                reason = "sole_live_family"
                confidence = "medium"
            else:
                if live_families:
                    suppressed.append(
                        {
                            "scope": scope,
                            "recent_paths": [path],
                            "state": "suppressed_ambiguous",
                            "reason": "multiple live families but no attributable scope owner",
                            "candidate_agents": sorted(live_families),
                        }
                    )
                continue
        if len(matches) > 1:
            suppressed.append(
                {
                    "scope": scope,
                    "recent_paths": [path],
                    "state": "suppressed_ambiguous",
                    "reason": "multiple live families match the same inferred scope",
                    "candidate_agents": sorted(matches),
                }
            )
            continue
        family = next(iter(matches))
        family_rows = [
            row
            for row in rows
            if presence_lib._family_from_agent_label(str(row.get("agent_id") or row.get("display_name") or ""))
            == family
        ]
        preferred = next(
            (
                row
                for row in family_rows
                if str(row.get("state") or "") in {"active", "alive"}
                and presence_lib._normalize_scope(row.get("scope"))
            ),
            None,
        )
        preferred = preferred or next(
            (row for row in family_rows if str(row.get("state") or "") in {"active", "alive"}), None
        )
        agent_id = str((preferred or {}).get("agent_id") or family).strip() or family
        display_name = str(
            (preferred or {}).get("display_name") or presence_lib._display_name_for_family(family)
        ).strip()
        same_agent, other_agent = _claim_conflict(workboard_claims, agent_id=agent_id, scope=scope)
        key = f"{agent_id.lower()}::{scope.lower()}"
        scope_agents.setdefault(scope.lower(), set()).add(agent_id)
        candidate = candidates_by_key.setdefault(
            key,
            {
                "agent_id": agent_id,
                "display_name": display_name,
                "family": family,
                "scope": scope,
                "confidence": confidence,
                "recent_paths": [],
                "process_pids": list(family_presence.get(family, {}).get("pids") or []),
                "evidence": list(family_presence.get(family, {}).get("commands") or []),
                "recommended_task_summary": f"Inferred work in {scope}",
                "source": "presence-monitor",
                "claim_status": "inferred_candidate",
                "supporting_process_evidence": list(family_presence.get(family, {}).get("commands") or [])[:3],
                "has_same_agent_claim": bool(same_agent),
                "conflicts_with_explicit_claim": bool(other_agent),
                "reason": reason,
            },
        )
        candidate["recent_paths"] = presence_lib._dedupe([*list(candidate.get("recent_paths") or []), path])[:8]
        if reason == "sole_live_family" and str(candidate.get("confidence") or "") != "high":
            candidate["confidence"] = "medium"
        if other_agent:
            candidate["conflict_agent_id"] = str(other_agent.get("agent_id") or "").strip()
        elif same_agent:
            candidate["existing_agent_id"] = str(same_agent.get("agent_id") or "").strip()

    for scope_key, agents_for_scope in list(scope_agents.items()):
        if len(agents_for_scope) <= 1:
            continue
        for key, candidate in list(candidates_by_key.items()):
            if str(candidate.get("scope") or "").strip().lower() != scope_key:
                continue
            suppressed.append(
                {
                    "agent_id": str(candidate.get("agent_id") or ""),
                    "scope": str(candidate.get("scope") or ""),
                    "recent_paths": list(candidate.get("recent_paths") or []),
                    "state": "suppressed_ambiguous",
                    "reason": "multiple inferred agents contend for the same scope",
                    "candidate_agents": sorted(agents_for_scope),
                }
            )
            candidates_by_key.pop(key, None)

    candidates = sorted(
        candidates_by_key.values(), key=lambda row: (str(row.get("scope") or ""), str(row.get("agent_id") or ""))
    )
    suppressed = sorted(suppressed, key=lambda row: (str(row.get("scope") or ""), str(row.get("agent_id") or "")))
    return candidates, suppressed
