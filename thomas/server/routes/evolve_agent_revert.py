"""Discarding a Code conversation's own file changes, safely.

Split out of ``evolve_agent_runtime.py`` (move-only, no logic changes) to bring
that file back under monolith_guard's unbaselined 800-line soft limit, following
the worker.py -> worker_pipeline.py/worker_dispatch.py precedent (commit
7f1006d7). This is the whole approval-gated revert concern in one place: which
path is safe to touch (``_normalize_repo_file``), which files a conversation
actually owns (``_conversation_changed_files``), whether it is even allowed to
write (``_conversation_is_read_only``), the one-time approval hash a revert is
bound to (``_revert_action_hash``), the authorization/claim step
(``_authorize_conversation_revert``), and closing out a claimed approval
(``_finish_approval_execution``). Self-contained on purpose -- nothing here
calls back into ``evolve_agent_runtime.py`` -- so re-exporting it from there
does not create an import cycle.

``evolve_agent_runtime.py`` re-exports every name here under its original spot;
``evolve_agent_workspace_routes.py`` imports ``_authorize_conversation_revert``,
``_conversation_changed_files``, and ``_finish_approval_execution`` from
``evolve_agent_runtime`` and needed no changes.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_git


def _normalize_repo_file(file: str) -> str:
    """Return one safe repository-relative POSIX path, or an empty string."""

    value = str(file or "").strip().replace("\\", "/")
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return ""
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return ""
    return "/".join(parts)


def _conversation_changed_files(conversation: dict[str, Any] | None) -> set[str] | None:
    """Return only files attributed to agent turns in one conversation."""

    if conversation is None:
        return None
    files: set[str] = set()
    for turn in conversation.get("turns") or []:
        if turn.get("role") != "agent":
            continue
        for file in turn.get("changed_files") or []:
            normalized = _normalize_repo_file(str(file or ""))
            if normalized:
                files.add(normalized)
    return files


def _conversation_is_read_only(metadata: dict[str, Any] | None) -> bool:
    settings = (metadata or {}).get("settings") or {}
    effective = settings.get("effective") or {}
    requested = settings.get("requested") or {}
    return "read_only" in {
        str(effective.get("file_access") or "").strip().lower(),
        str(requested.get("file_access") or "").strip().lower(),
    }


def _revert_action_hash(root: Path, conversation_id: str, file: str) -> str:
    """Bind approval to the exact repo, conversation, path, and current diff."""

    target = root.resolve() / file
    if target.is_file():
        content_hash = hashlib.sha256()
        try:
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    content_hash.update(chunk)
            content_state = content_hash.hexdigest()
        except OSError:
            content_state = "unreadable"
    else:
        content_state = "missing"
    payload = {
        "action": "revert_file",
        "conversation_id": conversation_id,
        "project_root": str(root.resolve()),
        "file": file,
        "untracked": forge_code_git.is_untracked(root, file),
        "diff": forge_code_git.unified_diff(root, file),
        "content": content_state,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _authorize_conversation_revert(
    *,
    root: Path,
    conversation_id: str,
    file: str,
    conversation: dict[str, Any],
    metadata: dict[str, Any] | None,
    approvals: dict[str, dict[str, Any]],
    approval_id: str,
) -> tuple[str, dict[str, Any] | None, int]:
    """Validate policy and atomically claim an exact one-time approval."""

    normalized = _normalize_repo_file(file)
    if not normalized:
        return "", {"ok": False, "error": "unsafe file path", "code": "invalid_file_path"}, 400
    if _conversation_is_read_only(metadata):
        return (
            normalized,
            {
                "ok": False,
                "error": "read-only Code conversations cannot revert files",
                "code": "read_only_mode",
            },
            403,
        )
    owned = _conversation_changed_files(conversation) or set()
    if normalized not in owned:
        return (
            normalized,
            {
                "ok": False,
                "error": "file was not changed by this Code conversation",
                "code": "file_not_owned_by_conversation",
            },
            403,
        )
    if not forge_code_git.file_is_dirty(root, normalized):
        return (
            normalized,
            {
                "ok": False,
                "error": "file is no longer changed",
                "code": "file_not_dirty",
            },
            409,
        )

    action_hash = _revert_action_hash(root, conversation_id, normalized)
    approval = approvals.get(approval_id) if approval_id else None
    valid = bool(
        isinstance(approval, dict)
        and approval.get("state") == "approved"
        and approval.get("action_hash") == action_hash
        and float(approval.get("expires_at") or 0) >= time.time()
    )
    if valid:
        approval["state"] = "executing"
        approval["executing_at"] = time.time()
        return normalized, None, 0

    new_id = f"approval-{secrets.token_urlsafe(10)}"
    approvals[new_id] = {
        "id": new_id,
        "state": "pending",
        "action_hash": action_hash,
        "risk": "discard conversation-owned file changes",
        "summary": f"Revert {normalized}? This permanently discards its current changes.",
        "expires_at": time.time() + 600,
    }
    public = {key: value for key, value in approvals[new_id].items() if key != "action_hash"}
    return (
        normalized,
        {
            "ok": False,
            "error": "explicit approval is required to discard file changes",
            "code": "approval_required",
            "approval": public,
        },
        409,
    )


def _finish_approval_execution(approval: dict[str, Any] | None, *, succeeded: bool) -> None:
    """Consume a claimed approval only after its protected action starts or succeeds."""
    if not isinstance(approval, dict) or approval.get("state") != "executing":
        return
    approval.pop("executing_at", None)
    approval["state"] = "consumed" if succeeded else "approved"
    if succeeded:
        approval["consumed_at"] = time.time()
