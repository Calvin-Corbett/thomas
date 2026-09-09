"""Fail-closed persistence and proof for a reviewed Canvas result."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.core.file_access import WORKSPACE, authorize_write
from thomas.server.chat_delegation_deliverable import _artifacts_from_created
from thomas.server.chat_delegation_session import _normalize_record
from thomas.server.chat_tool_policy import ToolRuntimePolicy, policy_allows_path


def complete_canvas_delivery(
    *,
    execution_id: str,
    prompt: str,
    html: str,
    actor: str,
    repo_root: Path,
    workspace_for: Callable[[str], Path],
    file_access: int = WORKSPACE,
    allowed_paths: tuple[str, ...] = (),
) -> tuple[dict[str, Any], str]:
    """Persist, read back, prove, and terminalize one reviewed Canvas result."""
    work_dir = workspace_for(execution_id)
    target = work_dir / "index.html"
    write_allowed, reason = authorize_write(
        file_access,
        target,
        workspace_root=work_dir,
        project_root=repo_root,
    )
    if not write_allowed:
        raise PermissionError(reason)
    if allowed_paths:
        path_policy = ToolRuntimePolicy(
            allow_shell=False,
            allow_file_write=True,
            allow_network=False,
            allow_browser=False,
            allow_channels=False,
            allow_git=False,
            require_command_approval=True,
            tool_timeout_s=120,
            max_parallel_tools=1,
            allowed_paths=allowed_paths,
            blocked_commands=(),
        )
        if not policy_allows_path(path_policy, target, base_root=repo_root):
            raise PermissionError("allowed_paths policy denied Canvas artifact delivery")
    work_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(html or "", encoding="utf-8")
    if not html.strip() or target.read_text(encoding="utf-8") != html:
        raise OSError("canvas deliverable readback did not match generated HTML")

    created = ["index.html"]
    summary = "Reviewed and rendered index.html on the canvas."
    # ``surface=canvas`` is a structured model decision.  Completion records the
    # rendered Canvas artifact exactly as produced; it never reclassifies the
    # natural-language prompt into a chart subtype or export format.
    _ = prompt

    task_bot_runtime.attach_proof(
        execution_id,
        artifacts=_artifacts_from_created(created),
        summary=summary,
        status="verified",
        actor=actor,
        repo_root=repo_root,
    )
    completion = task_bot_runtime.complete_execution(
        execution_id,
        actor=actor,
        summary=summary,
        repo_root=repo_root,
        verified_success=True,
    )
    record = _normalize_record(
        completion if isinstance(completion, dict) else task_bot_runtime.get_execution(execution_id, repo_root)
    )
    if (
        str(record.get("state") or "").lower() != "completed"
        or str(record.get("proof_status") or "").lower() != "verified"
    ):
        raise RuntimeError("canvas completion did not retain verified proof")
    return record, summary


__all__ = ["complete_canvas_delivery"]
