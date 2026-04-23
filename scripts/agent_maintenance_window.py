"""Quota tracking and reset handling for maintenance checkpoints."""

from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    agent_safety_module = importlib.import_module("scripts.agent_safety_config")
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    agent_safety_module = importlib.import_module("agent_safety_config")

load_config = agent_safety_module.load_config

from scripts.agent_maintenance_helpers import (  # noqa: E402
    _isoformat,
    _parse_timestamp,
    _utcnow,
    maintenance_audit_log_path,
    maintenance_log_path,
    suggested_checkpoint_command,
)

EVENT_CHECKPOINT_SUCCEEDED = "checkpoint_succeeded"
EVENT_CHECKPOINT_FAILED = "checkpoint_failed"
EVENT_TYPES = frozenset({EVENT_CHECKPOINT_SUCCEEDED, EVENT_CHECKPOINT_FAILED})


def load_maintenance_window(
    root: Path = ROOT,
    *,
    now: datetime | None = None,
    window: timedelta | None = None,
) -> dict[str, object]:
    reference_time = now.astimezone(timezone.utc) if now is not None else _utcnow()
    active_window = window or timedelta(hours=1)
    start_time = reference_time - active_window
    path = maintenance_log_path(root)
    entries: list[dict[str, object]] = []
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = _parse_timestamp(payload.get("timestamp", ""))
            event_name = str(payload.get("event") or "").strip()
            if timestamp is None or event_name not in EVENT_TYPES or timestamp < start_time:
                continue
            entries.append(
                {
                    "timestamp": _isoformat(timestamp),
                    "event": event_name,
                    "changed_lines": max(int(payload.get("changed_lines", 0) or 0), 0),
                }
            )
    successful = [entry for entry in entries if entry["event"] == EVENT_CHECKPOINT_SUCCEEDED]
    failed = [entry for entry in entries if entry["event"] == EVENT_CHECKPOINT_FAILED]
    return {
        "log_path": str(path),
        "window_start": _isoformat(start_time),
        "window_end": _isoformat(reference_time),
        "entries": entries,
        "successful_checkpoints": len(successful),
        "failed_checkpoints": len(failed),
        "checkpointed_lines": sum(int(entry.get("changed_lines", 0) or 0) for entry in successful),
    }


def maintenance_quota_status(
    root: Path = ROOT,
    *,
    total_changed_lines: int,
    now: datetime | None = None,
) -> dict[str, object]:
    config = load_config()
    state = load_maintenance_window(root, now=now)
    max_checkpoints = config.worktree_max_auto_checkpoints_per_hour()
    max_lines = config.worktree_max_checkpointed_lines_per_hour()
    max_failures = config.worktree_max_checkpoint_failures_before_stop()
    next_checkpoint_count = state["successful_checkpoints"] + 1
    next_checkpoint_lines = state["checkpointed_lines"] + max(int(total_changed_lines or 0), 0)

    blocked_reasons: list[str] = []
    if state["failed_checkpoints"] >= max_failures:
        blocked_reasons.append(
            f"checkpoint failure budget exhausted ({state['failed_checkpoints']}/{max_failures} this hour)"
        )
    if next_checkpoint_count > max_checkpoints:
        blocked_reasons.append(
            f"checkpoint count budget exhausted ({state['successful_checkpoints']}/{max_checkpoints} used this hour)"
        )
    if next_checkpoint_lines > max_lines:
        blocked_reasons.append(
            f"checkpoint line budget exhausted ({state['checkpointed_lines']}/{max_lines} changed lines already checkpointed)"
        )

    remaining_checkpoints = max(max_checkpoints - state["successful_checkpoints"], 0)
    remaining_lines = max(max_lines - state["checkpointed_lines"], 0)
    return {
        **state,
        "total_changed_lines": max(int(total_changed_lines or 0), 0),
        "max_auto_checkpoints_per_hour": max_checkpoints,
        "max_checkpointed_lines_per_hour": max_lines,
        "max_checkpoint_failures_before_stop": max_failures,
        "remaining_auto_checkpoints": remaining_checkpoints,
        "remaining_checkpointed_lines": remaining_lines,
        "can_attempt_checkpoint": not blocked_reasons,
        "blocked_reason": "; ".join(blocked_reasons),
        "suggested_checkpoint_command": suggested_checkpoint_command(),
    }


def record_maintenance_event(
    event: str,
    *,
    root: Path = ROOT,
    changed_lines: int = 0,
    now: datetime | None = None,
) -> Path:
    normalized_event = str(event or "").strip().lower()
    if normalized_event not in EVENT_TYPES:
        allowed = ", ".join(sorted(EVENT_TYPES))
        raise ValueError(f"unsupported maintenance event `{event}`; expected one of: {allowed}")
    path = maintenance_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": _isoformat(now.astimezone(timezone.utc) if now is not None else _utcnow()),
        "event": normalized_event,
        "changed_lines": max(int(changed_lines or 0), 0),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return path


def _authenticate_maintenance_reset() -> dict[str, object]:
    if os.name != "nt":
        return {
            "ok": False,
            "message": "maintenance reset requires an interactive Windows session",
            "actor": None,
            "method": "unsupported-platform",
            "cancelled": False,
        }
    try:
        try:
            from scripts.breakglass_auth import _current_windows_sam_name, _run_windows_credential_prompt
        except (ImportError, ModuleNotFoundError):
            from breakglass_auth import _current_windows_sam_name, _run_windows_credential_prompt  # type: ignore
    except ImportError:
        return {
            "ok": False,
            "message": "could not import breakglass_auth for maintenance reset",
            "actor": None,
            "method": "import-error",
            "cancelled": False,
        }

    current_user = _current_windows_sam_name()
    if not current_user:
        return {
            "ok": False,
            "message": "current Windows user could not be resolved",
            "actor": None,
            "method": "windows-credential-dialog",
            "cancelled": False,
        }
    prompt = _run_windows_credential_prompt(
        prompt_caption="Thomas Maintenance Quota Reset",
        prompt_message=(
            "Confirm maintenance quota reset with your Windows sign-in.\n"
            f"Account: {current_user}\n"
            "This clears the maintenance failure/checkpoint history window."
        ),
    )
    return {
        "ok": bool(prompt.ok),
        "message": str(prompt.message or "").strip(),
        "actor": str(prompt.actor or current_user).strip() or current_user,
        "method": str(prompt.method or "windows-credential-dialog").strip(),
        "cancelled": bool(getattr(prompt, "cancelled", False)),
    }


def reset_maintenance_window(
    *,
    root: Path = ROOT,
    reason: str,
    now: datetime | None = None,
) -> dict[str, object]:
    normalized_reason = " ".join(str(reason or "").split()).strip()
    if len(normalized_reason) < 12:
        return {
            "ok": False,
            "reset": False,
            "message": "maintenance reset requires a reason with at least 12 characters",
            "log_path": str(maintenance_log_path(root)),
            "audit_log_path": str(maintenance_audit_log_path(root)),
        }
    auth = _authenticate_maintenance_reset()
    if not auth.get("ok"):
        return {
            "ok": False,
            "reset": False,
            "message": str(auth.get("message") or "maintenance reset authorization failed"),
            "actor": auth.get("actor"),
            "auth_method": auth.get("method"),
            "cancelled": bool(auth.get("cancelled")),
            "log_path": str(maintenance_log_path(root)),
            "audit_log_path": str(maintenance_audit_log_path(root)),
        }

    path = maintenance_log_path(root)
    previous_entries = 0
    if path.exists():
        try:
            previous_entries = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            previous_entries = 0
        path.unlink(missing_ok=True)
    audit_path = maintenance_audit_log_path(root)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": _isoformat(now.astimezone(timezone.utc) if now is not None else _utcnow()),
        "event": "maintenance_window_reset",
        "actor": str(auth.get("actor") or "").strip(),
        "auth_method": str(auth.get("method") or "").strip(),
        "reason": normalized_reason,
        "previous_entries": previous_entries,
        "log_path": str(path),
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return {
        "ok": True,
        "reset": True,
        "message": "maintenance quota window reset",
        "actor": payload["actor"],
        "auth_method": payload["auth_method"],
        "reason": normalized_reason,
        "previous_entries": previous_entries,
        "log_path": str(path),
        "audit_log_path": str(audit_path),
    }
