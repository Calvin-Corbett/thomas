#!/usr/bin/env python3
"""Core operations for workboard claims."""

from __future__ import annotations

from pathlib import Path

try:
    from .workboard_claim_utils import (
        LOCK_FILE,
        NONE_ENTRY,
        ROOT,
        _agent_key,
        _append_claim_override_audit,
        _append_release_override_audit,
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
        _validate_and_write,
        _validate_dirty_claim_reason,
        _validate_dirty_release_reason,
        _worktree_dirty_paths,
        workboard_issue_mod,
    )
except ImportError:  # pragma: no cover
    from workboard_claim_utils import (  # type: ignore
        LOCK_FILE,
        NONE_ENTRY,
        ROOT,
        _agent_key,
        _append_claim_override_audit,
        _append_release_override_audit,
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
        _validate_and_write,
        _validate_dirty_claim_reason,
        _validate_dirty_release_reason,
        _worktree_dirty_paths,
        workboard_issue_mod,
    )


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

    with _file_lock(LOCK_FILE):
        dirty_paths = {"staged": [], "unstaged": [], "untracked": []}
        if _scope_guard_supported(workboard_path):
            dirty_paths = _worktree_dirty_paths(ROOT)
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
                        f"repo worktree is dirty ({len(offenders)} paths): {sample}. "
                        "Refusing to claim new work until the repo is clean. "
                        "Run python scripts/check_repo_hygiene.py or python -m thomas status --strict-worktree, "
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
        for idx in range(section[0], min(section[1], len(lines))):
            if lines[idx].strip().startswith("-"):
                entry, fields, err = _parse_claim_line(idx + 1, lines[idx])
                if err:
                    return False, err
                if entry and _agent_key(entry) == _agent_key(agent):
                    return False, f"agent {agent} already has an active claim"

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

        new_text = "".join(lines)
        scope_norm = _normalize_scope_value(scope)
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

    with _file_lock(LOCK_FILE):
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
            return False, f"agent {agent} has no active claim to release"

        section = _find_claim_section(lines)
        bullets = range(section[0], min(section[1], len(lines)))
        if not any(lines[idx].strip().startswith("-") for idx in bullets):
            lines.insert(section[0], NONE_ENTRY + "\n")

        dirty_paths = {"staged": [], "unstaged": [], "untracked": []}
        if _scope_guard_supported(workboard_path):
            from workboard_claim_utils import _claimed_scope_dirty_paths

            dirty_paths = _claimed_scope_dirty_paths([release_scope])
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
                        f"scope `{release_scope}` has dirty files ({len(offenders)} paths): {sample}. "
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

        ok, release_msg = _release_active_task(lines, agent=agent)
        new_text = "".join(lines)
        try:
            ok, violations = _validate_and_write(workboard_path, text, new_text)
            if not ok:
                return False, "; ".join(str(v) for v in violations)
        except Exception as exc:
            return False, str(exc)

        return True, f"released claim for agent `{agent}` from scope `{release_scope}`"


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
                    f"- agent={entry}; "
                    f"scope={fields.get('scope', 'unknown')}; "
                    f"task={fields.get('task', 'unknown')}"
                )
                claims_list.append(claim_str)

    return True, claims_list
