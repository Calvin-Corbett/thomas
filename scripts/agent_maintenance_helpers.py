"""Shared maintenance path, timestamp, and recovery helpers."""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    agent_safety_module = importlib.import_module("scripts.agent_safety_config")
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    agent_safety_module = importlib.import_module("agent_safety_config")

load_config = agent_safety_module.load_config

STATE_PATH_PREFIX = "@state/"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _state_root() -> Path:
    if os.name == "nt":
        local_app_data = str(os.getenv("LOCALAPPDATA", "") or "").strip()
        if local_app_data:
            return Path(local_app_data).expanduser().resolve() / "Thomas"
    xdg_state_home = str(os.getenv("XDG_STATE_HOME", "") or "").strip()
    if xdg_state_home:
        return Path(xdg_state_home).expanduser().resolve() / "thomas"
    return Path.home().expanduser().resolve() / ".local" / "state" / "thomas"


def _resolve_storage_path(raw: str, *, root: Path) -> Path:
    value = str(raw or "").strip()
    if not value:
        return root / "runtime" / "maintenance" / "events.jsonl"
    if value.startswith(STATE_PATH_PREFIX):
        suffix = value[len(STATE_PATH_PREFIX) :].lstrip("/\\")
        return _state_root() / Path(suffix)
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def maintenance_log_path(root: Path = ROOT) -> Path:
    config = load_config()
    raw = str(config.worktree_maintenance_log_file() or "").strip()
    return _resolve_storage_path(raw, root=root)


def maintenance_audit_log_path(root: Path = ROOT) -> Path:
    config = load_config()
    raw = str(config.worktree_maintenance_audit_log_file() or "").strip()
    return _resolve_storage_path(raw, root=root)


def suggested_checkpoint_command(
    *,
    agent: str = "<agent-id>",
    message: str = "checkpoint: maintenance mode",
) -> str:
    escaped_agent = str(agent).replace('"', "")
    escaped_message = str(message).replace('"', '\\"')
    return (
        f'python scripts/agent_commit.py --agent "{escaped_agent}" '
        f'--commit-class "private-checkpoint" --message "{escaped_message}"'
    )


def _preview_paths(paths: list[str], *, limit: int = 3) -> str:
    normalized = [str(path or "").strip() for path in paths if str(path or "").strip()]
    if not normalized:
        return "none"
    preview = normalized[:limit]
    suffix = ", ..." if len(normalized) > limit else ""
    return ", ".join(preview) + suffix


def _preview_batch(batch: list[str]) -> str:
    return _preview_paths(batch, limit=4)


def _suggest_claim_batch_command(
    *,
    agent: str,
    message: str,
    paths: list[str],
    max_paths: int = 5,
) -> str | None:
    selected = [str(path or "").strip() for path in paths[:max_paths] if str(path or "").strip()]
    if not selected:
        return None
    escaped_agent = str(agent).replace('"', "")
    escaped_message = str(message).replace('"', '\\"')
    parts = [
        f'python scripts/agent_commit.py --agent "{escaped_agent}"',
        '--commit-class "private-checkpoint"',
        f'--message "{escaped_message}"',
    ]
    for path in selected:
        parts.append(f'--include "{path}"')
    return " ".join(parts)


def _suggest_claim_scopes(paths: list[str], *, normalize_path, limit: int = 4) -> list[str]:
    normalized = [normalize_path(path) for path in paths if normalize_path(path)]
    if not normalized:
        return []
    parent_counts: dict[str, int] = {}
    for path in normalized:
        parts = Path(path).parts[:-1]
        for end in range(1, len(parts) + 1):
            parent = normalize_path(str(Path(*parts[:end])))
            if parent and parent not in {".", ""}:
                parent_counts[parent] = parent_counts.get(parent, 0) + 1

    suggestions: list[str] = []
    covered: set[str] = set()
    ordered = sorted(parent_counts.items(), key=lambda item: (-item[1], -len(Path(item[0]).parts), item[0]))
    for parent, _count in ordered:
        if parent_counts[parent] < 2:
            continue
        matches = [path for path in normalized if path == parent or path.startswith(parent + "/")]
        uncovered = [path for path in matches if path not in covered]
        if len(uncovered) < 2:
            continue
        suggestions.append(parent)
        covered.update(uncovered)
        if len(suggestions) >= limit:
            break

    for path in normalized:
        if path in covered:
            continue
        suggestions.append(path)
        covered.add(path)
        if len(suggestions) >= limit:
            break
    return suggestions


def _suggest_workboard_claim_command(
    *,
    agent: str,
    scopes: list[str],
    task: str = "[WIP] maintenance checkpoint follow-up",
) -> str | None:
    selected = [str(scope or "").strip() for scope in scopes if str(scope or "").strip()]
    if not selected:
        return None
    escaped_agent = str(agent).replace('"', "")
    escaped_task = str(task).replace('"', '\\"')
    scope_value = ",".join(scope.replace('"', "") for scope in selected)
    return (
        "python scripts/workboard_claim.py --claim "
        f'--agent "{escaped_agent}" --name "{escaped_agent}" --role solo --parent none '
        f'--scope "{scope_value}" --task "{escaped_task}"'
    )


def _build_recovery_steps(payload: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    claim_scopes = list(payload.get("suggested_claim_scopes") or [])
    if claim_scopes:
        steps.append("Claim scope: " + _preview_paths(claim_scopes))
    refactor_paths = list(payload.get("refactor_blocked_paths") or [])
    if refactor_paths:
        steps.append("Split oversized files: " + _preview_paths(refactor_paths))
    retry_batches = list(payload.get("retry_batches_after_refactor") or [])
    if retry_batches:
        first = retry_batches[0]
        if isinstance(first, list) and first:
            steps.append("Retry checkpoint batch: " + _preview_batch([str(item) for item in first]))
    blocked_paths = list(payload.get("blocked_paths") or [])
    if blocked_paths:
        steps.append("Review protected files separately: " + _preview_paths(blocked_paths))
    next_step = str(payload.get("next_step") or "").strip()
    if next_step and not steps:
        steps.append(next_step)
    return steps


def _build_recovery_summary(payload: dict[str, Any]) -> str:
    steps = _build_recovery_steps(payload)
    if not steps:
        return ""
    if len(steps) == 1:
        return steps[0]
    return "; then ".join(steps)


def _finalize_maintenance_payload(payload: dict[str, Any]) -> dict[str, Any]:
    recovery_steps = _build_recovery_steps(payload)
    if recovery_steps:
        payload["recovery_steps"] = recovery_steps
        payload["recovery_summary"] = _build_recovery_summary(payload)
    return payload
