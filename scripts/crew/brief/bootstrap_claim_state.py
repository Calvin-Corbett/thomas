"""Claim-state selection and task-manager helpers for agent bootstrap."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path

from scripts.crew.workboard import claim as claim_tool

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUTO_DISPATCH_TARGET_WORKERS = max(int(getattr(claim_tool, "DEFAULT_DISPATCH_TARGET_WORKERS", 2)), 3)
DEFAULT_MIN_AUTO_DISPATCH_TARGET_WORKERS = 2


def _agent_key(value: str | None) -> str:
    return str(value or "").strip().lower()


def normalize_scope_name(value: str | None) -> str:
    return str(value or "").strip()


def normalize_dispatch_target_workers(value: int | None) -> int:
    candidate = DEFAULT_AUTO_DISPATCH_TARGET_WORKERS if value is None else int(value)
    return max(DEFAULT_MIN_AUTO_DISPATCH_TARGET_WORKERS, candidate)


def is_worker_claim(role: str | None, parent: str | None) -> bool:
    return _agent_key(role) == "worker" or _agent_key(parent) not in {"", "none"}


def extract_claim_field(claim_row: object, field: str) -> str:
    if claim_row is None:
        return ""
    if isinstance(claim_row, str):
        raw = str(claim_row).strip().removeprefix("- ")
        for piece in raw.split(";"):
            if "=" in piece:
                key, value = piece.split("=", 1)
                if key.strip().lower() == field:
                    return value.strip()
        return ""
    if isinstance(claim_row, dict):
        return str(claim_row.get(field, "") or "")
    return str(getattr(claim_row, field, "") or "")


def extract_claim_agent(claim_row: object) -> str:
    return extract_claim_field(claim_row, "agent")


def task_subject(value: str) -> str:
    raw = str(value or "").strip()
    match = re.match(r"^\[WIP\](?:\[[^\]]+\])?\s+(?P<subject>.+)$", raw, flags=re.IGNORECASE)
    return str(match.group("subject") if match else raw).strip()


def select_bootstrap_task(
    workboard_path: Path,
    *,
    agent: str,
    requested: str,
    ticket: str,
    build_task: Callable[[str, str], str],
) -> str:
    requested_clean = str(requested or "").strip()
    ok, active_claims = claim_tool.list_claims(workboard_path)
    if not ok or not isinstance(active_claims, Sequence):
        raise ValueError(str(active_claims))
    existing = [row for row in active_claims if _agent_key(extract_claim_agent(row)) == _agent_key(agent)]
    if len(existing) > 1:
        raise ValueError(f"multiple active claims found for agent `{agent}`")
    if existing:
        current = extract_claim_field(existing[0], "task")
        if _agent_key(task_subject(current)) == _agent_key(task_subject(requested_clean)):
            return current
        raise ValueError(f"agent `{agent}` already claims task `{current}`; release it before bootstrapping another")
    if not str(ticket or "").strip():
        # No live claim, no explicit ticket: a job that already has a task folder keeps
        # its id. Minting a fresh HSK stamp every bootstrap left five identical
        # `LAND-THREE` folders and two `VERIFICATION-CONTRACT` ids on one board.
        reuse = existing_task_for_subject(workboard_path, requested_clean)
        if reuse:
            return reuse
    return build_task(requested_clean, ticket)


def existing_task_for_subject(workboard_path: Path, requested: str) -> str:
    """The newest `[WIP][...] <subject>` task folder beside the board whose subject
    matches ``requested``, or '' when there is none."""

    wanted = _agent_key(task_subject(requested))
    if not wanted:
        return ""
    tasks_dir = Path(workboard_path).resolve().parent / "tasks"
    if not tasks_dir.is_dir():
        return ""
    matches = sorted(
        entry.name
        for entry in tasks_dir.iterdir()
        if entry.is_dir() and entry.name.startswith("[WIP]") and _agent_key(task_subject(entry.name)) == wanted
    )
    return matches[-1] if matches else ""


def is_task_manager_claimed(workboard_path: Path, task_manager_agent: str) -> bool:
    manager_key = _agent_key(task_manager_agent)
    try:
        ok, active_claims = claim_tool.list_claims(workboard_path)
    except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError):
        return False
    return bool(
        ok
        and isinstance(active_claims, Sequence)
        and any(_agent_key(extract_claim_agent(row)) == manager_key for row in active_claims)
    )


def default_task_manager_scope(workboard_path: Path) -> str:
    try:
        return str(workboard_path.parent.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError):
        return str(workboard_path.parent).replace("\\", "/")


def claim_task_manager_position(
    *, workboard_path: Path, task_manager_agent: str, allow_dirty: bool = False, dirty_reason: str = ""
) -> tuple[bool, str]:
    ok, message = claim_tool.claim(
        workboard_path,
        agent=task_manager_agent,
        scope=default_task_manager_scope(workboard_path),
        task="[WIP][TM] task-manager control loop",
        name=task_manager_agent,
        role="solo",
        parent="none",
        allow_dirty=bool(allow_dirty),
        dirty_reason=str(dirty_reason or ""),
        allow_presence_override=False,
        presence_override_reason="",
    )
    return (True, str(message)) if ok else (False, str(message))
