"""Core maintenance checkpoint orchestration."""

from __future__ import annotations

import importlib
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    agent_commit_module = importlib.import_module("scripts.agent_commit")
    from scripts.agent_maintenance_helpers import (
        _finalize_maintenance_payload,
        _preview_paths,
        _suggest_claim_batch_command,
        _suggest_claim_scopes,
        _suggest_workboard_claim_command,
        suggested_checkpoint_command,
    )
    from scripts.agent_maintenance_services import (
        _batch_changed_lines,
        _checkpoint_batches,
        _git_status_paths,
        _group_retry_paths,
        _normalize_repo_path,
        _resolve_active_claim_scopes,
        _split_checkpointable_paths,
        _split_claimed_paths,
        _split_growth_guard_batch,
        _split_ignored_paths,
    )
    from scripts.agent_maintenance_window import (
        EVENT_CHECKPOINT_FAILED,
        EVENT_CHECKPOINT_SUCCEEDED,
        maintenance_quota_status,
        record_maintenance_event,
    )
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    agent_commit_module = importlib.import_module("agent_commit")
    from agent_maintenance_helpers import (  # type: ignore
        _finalize_maintenance_payload,
        _preview_paths,
        _suggest_claim_batch_command,
        _suggest_claim_scopes,
        _suggest_workboard_claim_command,
        suggested_checkpoint_command,
    )
    from agent_maintenance_services import (  # type: ignore
        _batch_changed_lines,
        _checkpoint_batches,
        _git_status_paths,
        _group_retry_paths,
        _normalize_repo_path,
        _resolve_active_claim_scopes,
        _split_checkpointable_paths,
        _split_claimed_paths,
        _split_growth_guard_batch,
        _split_ignored_paths,
    )
    from agent_maintenance_window import (  # type: ignore
        EVENT_CHECKPOINT_FAILED,
        EVENT_CHECKPOINT_SUCCEEDED,
        maintenance_quota_status,
        record_maintenance_event,
    )

DEFAULT_WORKBOARD = agent_commit_module.DEFAULT_WORKBOARD
CommitResult = agent_commit_module.CommitResult
commit_scoped_changes = agent_commit_module.commit_scoped_changes


def attempt_maintenance_checkpoint(
    *,
    root: Path = ROOT,
    agent: str,
    message: str = "checkpoint: maintenance mode",
    total_changed_lines: int = 0,
    workboard_path: Path = DEFAULT_WORKBOARD,
) -> dict[str, Any]:
    resolved_agent = str(agent or "").strip()
    if not resolved_agent:
        return _finalize_maintenance_payload(
            {
                "ok": False,
                "attempted": False,
                "blocker_class": "missing_agent",
                "message": "maintenance checkpoint requires an agent id",
                "next_step": "Re-run maintenance with --agent <agent-id> so the claim-scoped checkpoint can be validated.",
                "suggested_command": suggested_checkpoint_command(),
            }
        )

    changed_paths = _git_status_paths(root)
    if not changed_paths:
        return _finalize_maintenance_payload({"ok": True, "attempted": False, "blocker_class": None, "message": "worktree already clean", "selected_paths": []})
    candidate_paths, ignored_paths = _split_ignored_paths(changed_paths)
    if not candidate_paths:
        return _finalize_maintenance_payload({"ok": True, "attempted": False, "blocker_class": None, "message": "only ignored transient maintenance paths are dirty", "selected_paths": [], "ignored_paths": ignored_paths})

    checkpointable_paths, blocked_paths = _split_checkpointable_paths(candidate_paths)
    if not checkpointable_paths:
        return _finalize_maintenance_payload(
            {
                "ok": False,
                "attempted": False,
                "blocker_class": "protected_policy_pending",
                "message": "maintenance checkpoint cannot auto-commit immutable policy or enforcement files",
                "selected_paths": [],
                "blocked_paths": blocked_paths,
                "ignored_paths": ignored_paths,
                "next_step": "Review the protected files separately before checkpointing anything else: " + _preview_paths(blocked_paths),
            }
        )

    try:
        claim_scopes = _resolve_active_claim_scopes(resolved_agent, workboard_path)
    except ValueError as exc:
        suggested_claim_scopes = _suggest_claim_scopes(checkpointable_paths, normalize_path=_normalize_repo_path)
        return _finalize_maintenance_payload(
            {
                "ok": False,
                "attempted": False,
                "blocker_class": "claim_scope_mismatch",
                "message": str(exc),
                "selected_paths": [],
                "checkpointable_paths": checkpointable_paths,
                "blocked_paths": blocked_paths,
                "ignored_paths": ignored_paths,
                "unclaimed_paths": checkpointable_paths,
                "suggested_claim_scopes": suggested_claim_scopes,
                "next_step": "Create or refresh the agent's workboard claim so it covers the current dirty files: " + _preview_paths(suggested_claim_scopes or checkpointable_paths),
                "suggested_claim_command": _suggest_workboard_claim_command(agent=resolved_agent, scopes=suggested_claim_scopes),
            }
        )
    except (OSError, RuntimeError) as exc:
        return _finalize_maintenance_payload({"ok": False, "attempted": False, "blocker_class": "broken_repo_tool", "message": f"could not resolve active claim for maintenance checkpoint: {exc}", "selected_paths": [], "checkpointable_paths": checkpointable_paths, "blocked_paths": blocked_paths, "ignored_paths": ignored_paths})

    claimed_paths, unclaimed_paths = _split_claimed_paths(checkpointable_paths, claim_scopes)
    if not claimed_paths:
        suggested_claim_scopes = _suggest_claim_scopes(unclaimed_paths, normalize_path=_normalize_repo_path)
        return _finalize_maintenance_payload(
            {
                "ok": False,
                "attempted": False,
                "blocker_class": "claim_scope_mismatch",
                "message": "maintenance checkpoint found no changed files inside the agent's active claim scope",
                "selected_paths": [],
                "claim_scopes": list(claim_scopes),
                "checkpointable_paths": checkpointable_paths,
                "blocked_paths": blocked_paths,
                "ignored_paths": ignored_paths,
                "unclaimed_paths": unclaimed_paths,
                "suggested_claim_scopes": suggested_claim_scopes,
                "next_step": "Claim the dirty files first: " + _preview_paths(suggested_claim_scopes or unclaimed_paths),
            }
        )

    total_checkpointable = len(claimed_paths)
    pending_batches = _checkpoint_batches(claimed_paths)
    results: list[dict[str, Any]] = []
    remaining_lines = max(int(total_changed_lines or 0), 0)
    deferred_refactor_paths: list[str] = []
    deferred_refactor_violations: list[dict[str, Any]] = []
    processed_paths: set[str] = set()

    while pending_batches:
        batch = pending_batches.pop(0)
        is_last = not pending_batches
        current_index = len(results) + 1
        current_total = current_index + len(pending_batches)
        batch_lines = _batch_changed_lines(total_changed_lines=remaining_lines if is_last else max(int(total_changed_lines or 0), 0), batch_size=len(batch), total_paths=total_checkpointable, is_last=is_last)
        quota = maintenance_quota_status(root, total_changed_lines=batch_lines)
        blocked_reason = str(quota.get("blocked_reason") or "").strip()
        if not quota.get("can_attempt_checkpoint"):
            return _finalize_maintenance_payload(
                {
                    "ok": False,
                    "attempted": bool(results),
                    "blocker_class": "maintenance_quota_exhausted",
                    "message": blocked_reason or "maintenance checkpoint budget exhausted",
                    "selected_paths": claimed_paths,
                    "claim_scopes": list(claim_scopes),
                    "checkpointable_paths": claimed_paths,
                    "blocked_paths": blocked_paths,
                    "ignored_paths": ignored_paths,
                    "unclaimed_paths": unclaimed_paths,
                    "completed_batches": results,
                    "quota": quota,
                    "next_step": "Wait for the maintenance quota window to recover, then retry the next claimed batch.",
                    "suggested_command": _suggest_claim_batch_command(agent=resolved_agent, message=message, paths=claimed_paths),
                    "refactor_blocked_paths": deferred_refactor_paths,
                    "refactor_violations": deferred_refactor_violations,
                }
            )

        batch_message = message if current_total == 1 else f"{message} ({current_index}/{current_total})"
        result: CommitResult = commit_scoped_changes(message=batch_message, agent=resolved_agent, include_paths=tuple(batch), allow_scope_fallback=False, prefer_scope_fallback=False, commit_class="private-checkpoint", repo_root=root, workboard_path=workboard_path)
        payload = asdict(result) if is_dataclass(result) else dict(vars(result))
        payload["attempted"] = True
        payload["selected_paths"] = list(batch)
        payload["quota"] = quota

        if not result.ok and str(result.gate_name or "").strip() == "commit_growth_guard":
            retry_batches, violations = _split_growth_guard_batch(batch, str(result.gate_output or ""))
            if violations:
                paths = [str(item.get("path") or "").strip() for item in violations if str(item.get("path") or "").strip()]
                deferred_refactor_paths.extend(path for path in paths if path not in deferred_refactor_paths)
                deferred_refactor_violations.extend(violations)
                for retry_batch in reversed(retry_batches):
                    pending_batches.insert(0, retry_batch)
                continue

        record_maintenance_event(EVENT_CHECKPOINT_SUCCEEDED if result.ok else EVENT_CHECKPOINT_FAILED, root=root, changed_lines=batch_lines)
        results.append(payload)
        if not result.ok:
            payload.update({"blocked_paths": blocked_paths, "claim_scopes": list(claim_scopes), "checkpointable_paths": claimed_paths, "ignored_paths": ignored_paths, "unclaimed_paths": unclaimed_paths, "completed_batches": results[:-1], "refactor_blocked_paths": deferred_refactor_paths, "refactor_violations": deferred_refactor_violations})
            if not str(payload.get("suggested_command") or "").strip():
                payload["suggested_command"] = _suggest_claim_batch_command(agent=resolved_agent, message=batch_message, paths=list(batch))
            return _finalize_maintenance_payload(payload)
        remaining_lines = max(remaining_lines - batch_lines, 0)
        processed_paths.update(batch)

    final_payload = dict(results[-1]) if results else {}
    final_payload.update({"ok": not blocked_paths and not deferred_refactor_paths, "attempted": bool(results) or bool(deferred_refactor_paths), "selected_paths": sorted(processed_paths), "claim_scopes": list(claim_scopes), "checkpointable_paths": claimed_paths, "blocked_paths": blocked_paths, "ignored_paths": ignored_paths, "unclaimed_paths": unclaimed_paths, "completed_batches": results, "batch_count": len(results), "commit_shas": [str(item.get('commit_sha') or '').strip() for item in results if item.get('commit_sha')], "refactor_blocked_paths": deferred_refactor_paths, "refactor_violations": deferred_refactor_violations})

    if deferred_refactor_paths:
        retry_batches_after_refactor = _group_retry_paths(deferred_refactor_paths)
        final_payload.update({"retry_batches_after_refactor": retry_batches_after_refactor, "blocker_class": "needs_refactor", "message": "maintenance checkpoint saved checkpointable files, but oversized files still need refactor before they can be checkpointed", "next_step": "Split the oversized files before retrying the remaining claimed work: " + _preview_paths(deferred_refactor_paths)})
        if retry_batches_after_refactor:
            final_payload["suggested_command"] = _suggest_claim_batch_command(agent=resolved_agent, message=message, paths=retry_batches_after_refactor[0])
    if blocked_paths:
        final_payload.update({"blocker_class": "protected_policy_pending", "message": "maintenance checkpoint saved checkpointable files, but immutable policy or enforcement files still need explicit review" if not deferred_refactor_paths else "maintenance checkpoint saved checkpointable files, but oversized files still need refactor and immutable policy or enforcement files still need explicit review", "next_step": "Review the protected files separately before retrying maintenance: " + _preview_paths(blocked_paths)})
    if unclaimed_paths:
        suggested_claim_scopes = _suggest_claim_scopes(unclaimed_paths, normalize_path=_normalize_repo_path)
        final_payload["ok"] = False
        final_payload["blocker_class"] = "claim_scope_pending"
        final_payload["suggested_claim_scopes"] = suggested_claim_scopes
        final_payload["message"] = "maintenance checkpoint saved claimed files, but unclaimed dirty files still need an explicit workboard claim"
        if blocked_paths and deferred_refactor_paths:
            final_payload["message"] = "maintenance checkpoint saved claimed files, but unclaimed dirty files, oversized files, and immutable policy or enforcement files still need explicit follow-up"
        elif blocked_paths:
            final_payload["message"] = "maintenance checkpoint saved claimed files, but unclaimed dirty files and immutable policy or enforcement files still need explicit follow-up"
        elif deferred_refactor_paths:
            final_payload["message"] = "maintenance checkpoint saved claimed files, but unclaimed dirty files and oversized files still need explicit follow-up"
        final_payload["next_step"] = "Claim the remaining dirty files before retrying maintenance: " + _preview_paths(suggested_claim_scopes or unclaimed_paths)
    return _finalize_maintenance_payload(final_payload)
