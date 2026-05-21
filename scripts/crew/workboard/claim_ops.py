#!/usr/bin/env python3
"""Core operations for workboard claims."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.workboard.claim_utils import (
        LOCK_FILE,
        NONE_ENTRY,
        _agent_key,
        _append_claim_override_audit,
        _append_release_override_audit,
        _claimed_scope_dirty_paths,
        _file_lock,
        _find_claim_section,
        _format_claim,
        _normalize_parent_token,
        _normalize_scope_value,
        _normalize_task_id,
        _parse_claim_line,
        _presence_gate,
        _release_active_task,
        _resolve_claim_role,
        _resolve_display_name,
        _sample_paths,
        _scope_guard_supported,
        _upsert_active_task,
        _validate_and_write,
        _validate_dirty_claim_reason,
        _validate_dirty_release_reason,
        workboard_issue_mod,
    )
except ImportError:  # pragma: no cover
    from crew.workboard.claim_utils import (  # type: ignore
        LOCK_FILE,
        NONE_ENTRY,
        _agent_key,
        _append_claim_override_audit,
        _append_release_override_audit,
        _claimed_scope_dirty_paths,
        _file_lock,
        _find_claim_section,
        _format_claim,
        _normalize_parent_token,
        _normalize_scope_value,
        _normalize_task_id,
        _parse_claim_line,
        _presence_gate,
        _release_active_task,
        _resolve_claim_role,
        _resolve_display_name,
        _sample_paths,
        _scope_guard_supported,
        _upsert_active_task,
        _validate_and_write,
        _validate_dirty_claim_reason,
        _validate_dirty_release_reason,
        workboard_issue_mod,
    )


# Test-patchable function resolution: tests patch attributes on
# `scripts.crew.workboard.claim`; this helper makes those patches reach the
# internals here. If `claim` doesn't override a name (production), fall through
# to the module-local symbol.
def _via_claim(name: str, default):
    claim_mod = sys.modules.get("scripts.crew.workboard.claim")
    if claim_mod is not None:
        value = getattr(claim_mod, name, None)
        if value is not None and value is not default:
            return value
    return default


def _remove_up_for_grabs_entry(lines: list[str], task_id: str) -> tuple[bool, str]:
    if workboard_issue_mod is None:
        return False, "workboard_issue module unavailable"
    if not task_id:
        return False, "task_id is required to remove up-for-grabs entry"
    section = workboard_issue_mod._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    key = _normalize_task_id(task_id)
    remove_idx: int | None = None
    entry_field: dict[str, str] | None = None
    for idx in workboard_issue_mod._bullet_indices(lines, section[0], section[1]):  # type: ignore[attr-defined]
        entry, fields, err = workboard_issue_mod._parse_up_for_grabs_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, err
        if entry is not None and workboard_issue_mod._is_none_entry(entry):  # type: ignore[attr-defined]
            continue
        if fields and _normalize_task_id(fields.get("task_id", "")) == key:
            remove_idx = idx
            entry_field = fields
            break

    if remove_idx is None:
        return False, f"up-for-grabs task `{task_id}` not found"
    if not entry_field:
        return False, f"up-for-grabs task `{task_id}` entry is malformed"

    del lines[remove_idx]
    section = workboard_issue_mod._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    workboard_issue_mod._ensure_none_if_empty(lines, section_start=section[0], section_end=section[1])  # type: ignore[attr-defined]
    return True, f"removed up-for-grabs task `{entry_field.get('task_id', task_id)}`"


def claim(
    workboard_path: Path,
    *,
    agent: str,
    scope: str,
    task: str,
    name: str | None = None,
    role: str | None = None,
    parent: str | None = None,
    require_claims_to_have_active_task: bool = True,
    allow_blocked_without_issue: bool = False,
    allow_dirty: bool = False,
    dirty_reason: str = "",
    allow_presence_override: bool = False,
    presence_override_reason: str = "",
) -> tuple[bool, str]:
    ok_presence, presence_message = _presence_gate(
        workboard_path=workboard_path,
        purpose="workboard_claim",
        agent=agent,
        requested_scope=scope,
        allow_override=bool(allow_presence_override),
        override_reason=str(presence_override_reason or ""),
    )
    if not ok_presence:
        return False, presence_message

    with _via_claim("_file_lock", _file_lock)(_via_claim("LOCK_FILE", LOCK_FILE)):
        dirty_paths = {"staged": [], "unstaged": [], "untracked": []}
        scope_norm = _normalize_scope_value(scope)
        scope_guard = _via_claim("_scope_guard_supported", _scope_guard_supported)
        dirty_paths_fn = _via_claim("_claimed_scope_dirty_paths", _claimed_scope_dirty_paths)
        if scope_guard(workboard_path):
            dirty_paths = dirty_paths_fn(scope_norm.split(","))
            offenders = sorted(
                set(
                    list(dirty_paths.get("staged") or [])
                    + list(dirty_paths.get("unstaged") or [])
                    + list(dirty_paths.get("untracked") or [])
                )
            )
            if offenders and not allow_dirty:
                sample = _sample_paths(offenders)
                return (
                    False,
                    (
                        f"claimed scope `{scope_norm}` has dirty files ({len(offenders)} paths): {sample}. "
                        "Refusing to claim overlapping work until the scope is clean, "
                        "or pass --allow-dirty-claim with --dirty-claim-reason."
                    ),
                )
            if offenders and allow_dirty:
                try:
                    reason = _validate_dirty_claim_reason(dirty_reason)
                except ValueError as exc:
                    return False, str(exc)
                _append_claim_override_audit(
                    agent=agent,
                    reason=reason,
                    scope=scope,
                    dirty_paths=dirty_paths,
                )
        claim_name = _resolve_display_name(name, agent)
        claim_parent = _normalize_parent_token(parent)
        claim_role = _resolve_claim_role(role, claim_parent)
        formatted = _format_claim(
            agent,
            scope,
            task,
            name=claim_name,
            role=claim_role,
            parent=claim_parent,
        )
        text = workboard_path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        section = _find_claim_section(lines)
        # If the agent already has a claim, UPDATE the existing line in place
        # (idempotent claim semantics — agent can refine scope/task without
        # release-then-reclaim). The "already has a claim" error is reserved for
        # the edge cases below (parse errors, etc).
        existing_idx: int | None = None
        for idx in range(section[0], min(section[1], len(lines))):
            if lines[idx].strip().startswith("-"):
                entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
                if err:
                    return False, err
                if entry and _agent_key(entry) == _agent_key(agent):
                    existing_idx = idx
                    break

        if existing_idx is not None:
            lines[existing_idx] = formatted + "\n"
        else:
            none_idx: int | None = None
            for idx in range(section[0], min(section[1], len(lines))):
                if lines[idx].strip() == NONE_ENTRY:
                    none_idx = idx
                    break
            if none_idx is not None:
                lines[none_idx] = formatted + "\n"
            else:
                insert_idx = section[1]
                if insert_idx <= len(lines):
                    lines.insert(insert_idx, formatted + "\n")
                else:
                    lines.append(formatted + "\n")

        active_ok, active_message = _upsert_active_task(
            lines,
            task,
            agent=agent,
            scope=scope_norm,
            summary=task,
            status="active",
        )
        if not active_ok:
            return False, active_message

        new_text = "".join(lines)
        try:
            ok, violations = _validate_and_write(
                workboard_path,
                text,
                new_text,
                require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
                allow_blocked_without_issue=bool(allow_blocked_without_issue),
            )
            if not ok:
                return False, "; ".join(str(v) for v in violations)
        except Exception as exc:
            return False, str(exc)

        if existing_idx is not None:
            return True, f"updated claim for `{agent}` to scope `{scope_norm}` with task `{task}`"
        return True, f"claimed scope `{scope_norm}` for agent `{agent}` with task `{task}`"


def release(
    workboard_path: Path,
    *,
    agent: str,
    allow_dirty: bool = False,
    dirty_reason: str = "",
    allow_presence_override: bool = False,
    presence_override_reason: str = "",
) -> tuple[bool, str]:
    ok_presence, presence_message = _presence_gate(
        workboard_path=workboard_path,
        purpose="workboard_release",
        agent=agent,
        requested_scope="",
        allow_override=bool(allow_presence_override),
        override_reason=str(presence_override_reason or ""),
    )
    if not ok_presence:
        return False, presence_message

    with _via_claim("_file_lock", _file_lock)(_via_claim("LOCK_FILE", LOCK_FILE)):
        text = workboard_path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        section = _find_claim_section(lines)
        release_scope: str = ""
        for idx in range(section[0], min(section[1], len(lines))):
            if lines[idx].strip().startswith("-"):
                entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
                if err:
                    return False, err
                if entry and _agent_key(entry) == _agent_key(agent):
                    release_scope = fields.get("scope", "")
                    del lines[idx]
                    break

        if not release_scope:
            return False, f"no active claim found for `{agent}`"

        section = _find_claim_section(lines)
        bullets = range(section[0], min(section[1], len(lines)))
        if not any(lines[idx].strip().startswith("-") for idx in bullets):
            lines.insert(section[0], NONE_ENTRY + "\n")

        dirty_paths = {"staged": [], "unstaged": [], "untracked": []}
        scope_guard = _via_claim("_scope_guard_supported", _scope_guard_supported)
        dirty_paths_fn = _via_claim("_claimed_scope_dirty_paths", _claimed_scope_dirty_paths)
        if scope_guard(workboard_path):
            dirty_paths = dirty_paths_fn([release_scope])
            offenders = sorted(
                set(
                    list(dirty_paths.get("staged") or [])
                    + list(dirty_paths.get("unstaged") or [])
                    + list(dirty_paths.get("untracked") or [])
                )
            )
            if offenders and not allow_dirty:
                sample = _sample_paths(offenders)
                return (
                    False,
                    (
                        f"dirty files in claimed scope `{release_scope}` ({len(offenders)} paths): {sample}. "
                        "Refusing to release until the scope is clean, "
                        "or pass --allow-dirty-release with --dirty-release-reason."
                    ),
                )
            if offenders and allow_dirty:
                try:
                    reason = _validate_dirty_release_reason(dirty_reason)
                except ValueError as exc:
                    return False, str(exc)
                _append_release_override_audit(
                    agent=agent,
                    reason=reason,
                    scope=release_scope,
                )

        # Collect task_ids about to be released BEFORE _release_active_task
        # mutates the lines list, so we can clean up any `auto-inactive`
        # issues that reference them (otherwise validation will fail with
        # "issue X references unknown task_id Y" after the active-task line
        # is gone).
        from scripts.crew.workboard.claim_utils import _find_active_tasks_section, _parse_active_task_line

        released_task_ids: list[str] = []
        at_section = _find_active_tasks_section(lines)
        for idx in range(at_section[0], min(at_section[1], len(lines))):
            raw = lines[idx]
            if not raw.strip().startswith("-"):
                continue
            try:
                entry, fields, err = _parse_active_task_line(idx + 1, raw)
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            if err:
                continue
            if fields and _agent_key(str(fields.get("agent") or "")) == _agent_key(agent):
                task_id = str(entry or fields.get("task_id") or "").strip()
                if task_id:
                    released_task_ids.append(task_id)

        ok, release_msg = _release_active_task(lines, agent=agent)
        cleaned_count = 0
        if released_task_ids:
            from scripts.crew.workboard.claim_utils import _cleanup_auto_inactive_issues_for_tasks

            cleanup_ok, cleaned_count = _cleanup_auto_inactive_issues_for_tasks(lines, released_task_ids)
            if not cleanup_ok:
                cleaned_count = 0

        new_text = "".join(lines)
        try:
            ok, violations = _validate_and_write(workboard_path, text, new_text)
            if not ok:
                return False, "; ".join(str(v) for v in violations)
        except Exception as exc:
            return False, str(exc)

        msg = f"released claim for `{agent}` from scope `{release_scope}`"
        if cleaned_count:
            msg += f"; cleaned_auto_inactive_issues={cleaned_count}"
        return True, msg


def list_claims(workboard_path: Path) -> tuple[bool, list[str] | str]:
    try:
        text = workboard_path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, f"failed to read workboard: {exc}"

    lines = text.splitlines(keepends=True)
    section = _find_claim_section(lines)
    claims_list: list[str] = []
    for idx in range(section[0], min(section[1], len(lines))):
        if lines[idx].strip().startswith("-"):
            entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
            if err:
                return False, err
            if entry is not None:
                claim_str = (
                    f"- agent={entry}; scope={fields.get('scope', 'unknown')}; task={fields.get('task', 'unknown')}"
                )
                claims_list.append(claim_str)

    return True, claims_list
