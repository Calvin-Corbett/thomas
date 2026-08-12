"""Workflow schema, legacy normalization, and durable validation."""

from __future__ import annotations

import copy
from typing import Any

from .validation import (
    WorkCorruptStateError,
    WorkValidationError,
    legacy_safe_id,
    require_safe_id,
    utc_now_iso,
)

WORKFLOW_STATUSES = frozenset({"planned", "configuring", "active", "completed", "archived"})
WORKFLOW_TYPES = frozenset({"manual", "scheduled", "event"})
_FOCUS_STATUSES = frozenset({"configuring", "active"})
_TRIGGERS_BY_WORKFLOW_TYPE = {
    "manual": frozenset({"manual"}),
    "scheduled": frozenset({"interval", "daily", "weekly"}),
    "event": frozenset({"event"}),
}
_REQUIRED_WORKFLOW_FIELDS = frozenset(
    {
        "id",
        "name",
        "purpose",
        "type",
        "status",
        "steps",
        "success_criteria",
        "connector_suggestions",
        "automation_id",
        "learning",
        "created_at",
        "updated_at",
    }
)


def workflow_memory_is_legacy(memory: dict[str, Any]) -> bool:
    """Return true only for the pre-typed workflow shape that is safe to upgrade."""

    rows = memory.get("workflows")
    metadata = memory.get("metadata")
    if not isinstance(rows, list) or not isinstance(metadata, dict):
        return False
    if "active_workflow_id" in metadata or any(not isinstance(row, dict) for row in rows):
        return False
    return all(not _REQUIRED_WORKFLOW_FIELDS.issubset(row) for row in rows)


def _unique_legacy_id(value: Any, *, position: int, used: set[str]) -> str:
    candidate = legacy_safe_id(value or f"workflow-{position + 1}", prefix="workflow")
    base = candidate
    suffix = 2
    while candidate in used:
        candidate = f"{base[:76]}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def normalize_workflow_memory(memory: dict[str, Any]) -> bool:
    """Upgrade legacy free-form workflow notes to the typed durable shape."""

    if not workflow_memory_is_legacy(memory):
        return False
    original = copy.deepcopy(memory)
    raw_rows = memory["workflows"]
    metadata = memory["metadata"]
    used: set[str] = set()
    rows: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            continue
        workflow_id = _unique_legacy_id(raw.get("id") or raw.get("name"), position=position, used=used)
        fallback = str(raw.get("step") or raw.get("goal") or raw.get("name") or f"Workflow {position + 1}").strip()
        workflow_type = str(raw.get("type") or "manual").strip().lower()
        status = str(raw.get("status") or "planned").strip().lower()
        automation_id = str(raw.get("automation_id") or "").strip().lower()
        try:
            automation_id = require_safe_id(automation_id, field="automation_id") if automation_id else ""
        except WorkValidationError:
            automation_id = ""
        rows.append(
            {
                **raw,
                "id": workflow_id,
                "name": str(raw.get("name") or fallback or f"Workflow {position + 1}")[:160],
                "purpose": str(raw.get("purpose") or raw.get("goal") or fallback)[:4_000],
                "type": workflow_type if workflow_type in WORKFLOW_TYPES else "manual",
                "status": status if status in WORKFLOW_STATUSES else "planned",
                "steps": (
                    [dict(item) for item in raw.get("steps", []) if isinstance(item, dict)][:100]
                    if isinstance(raw.get("steps"), list)
                    else ([{"description": fallback}] if raw.get("step") else [])
                ),
                "success_criteria": [str(item)[:240] for item in raw.get("success_criteria", []) if str(item).strip()][
                    :64
                ]
                if isinstance(raw.get("success_criteria"), list)
                else [],
                "connector_suggestions": [
                    str(item).strip().lower() for item in raw.get("connector_suggestions", []) if str(item).strip()
                ][:16]
                if isinstance(raw.get("connector_suggestions"), list)
                else [],
                "automation_id": automation_id,
                "learning": dict(raw.get("learning") or {}) if isinstance(raw.get("learning"), dict) else {},
                "created_at": str(raw.get("created_at") or utc_now_iso()),
                "updated_at": str(raw.get("updated_at") or utc_now_iso()),
            }
        )

    requested = str(metadata.get("active_workflow_id") or "").strip().lower()
    focus = next((row for row in rows if row["id"] == requested), None)
    if focus is None:
        focus = next((row for row in rows if row["status"] in _FOCUS_STATUSES), None)
    if focus is None and rows:
        focus = rows[0]
    for row in rows:
        if row is focus:
            if row["status"] not in _FOCUS_STATUSES:
                row["status"] = "configuring"
        elif row["status"] in _FOCUS_STATUSES:
            row["status"] = "planned"
    metadata["active_workflow_id"] = str(focus["id"]) if focus else ""
    memory["metadata"] = metadata
    memory["workflows"] = rows
    return memory != original


def validate_workflow_memory(memory: dict[str, Any]) -> None:
    rows = memory.get("workflows")
    metadata = memory.get("metadata")
    if not isinstance(rows, list) or not isinstance(metadata, dict):
        raise WorkCorruptStateError("durable Work workflow metadata is invalid")
    if any(not isinstance(row, dict) for row in rows):
        raise WorkCorruptStateError("durable Work workflow entries are invalid")
    ids = [str(row.get("id") or "") for row in rows]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise WorkCorruptStateError("durable Work workflow ids are invalid")
    for row in rows:
        try:
            require_safe_id(row.get("id"), field="workflow_id")
            automation_id = str(row.get("automation_id") or "")
            if automation_id:
                require_safe_id(automation_id, field="automation_id")
        except WorkValidationError as exc:
            raise WorkCorruptStateError("durable Work workflow ids are invalid") from exc
        if (
            not str(row.get("name") or "").strip()
            or not str(row.get("purpose") or "").strip()
            or row.get("type") not in WORKFLOW_TYPES
            or row.get("status") not in WORKFLOW_STATUSES
            or not isinstance(row.get("steps"), list)
            or not isinstance(row.get("success_criteria"), list)
            or not isinstance(row.get("connector_suggestions"), list)
            or not isinstance(row.get("learning"), dict)
            or any(not isinstance(step, dict) for step in row["steps"])
            or any(not isinstance(item, str) for item in row["success_criteria"])
            or any(not isinstance(item, str) for item in row["connector_suggestions"])
        ):
            raise WorkCorruptStateError("durable Work workflow definition is invalid")
    active_id = str(metadata.get("active_workflow_id") or "")
    focused = [row for row in rows if row.get("status") in _FOCUS_STATUSES]
    if (rows and (len(focused) != 1 or focused[0]["id"] != active_id)) or (not rows and active_id):
        raise WorkCorruptStateError("durable Work workflow focus is invalid")
