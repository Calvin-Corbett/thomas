"""Validate structured workflow controls without classifying task prose."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_MODE_SET = {"fast", "auto", "thinking"}
_TOKEN_ECONOMY_SET = {"cheap", "optimal", "max"}
_TASK_CLASS_SET = {"", "general", "coding", "research", "planning"}


def _text(value: Any, *, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    return default


def apply_workflow_mode_policy(
    payload: Mapping[str, Any],
    *,
    compile_meta: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return validated mode metadata while leaving routing model-owned.

    ``mode`` and ``token_economy`` are explicit controls. They may tune the
    already-selected workflow at execution time, but they do not infer a task
    class, select another workflow, or increase worker count.
    """

    out: dict[str, Any] = dict(payload or {})
    mode = _text(out.get("mode"), default="auto").lower()
    if mode not in _MODE_SET:
        mode = "auto"
    token_economy = _text(out.get("token_economy"), default="optimal").lower()
    if token_economy not in _TOKEN_ECONOMY_SET:
        token_economy = "optimal"
    task_class = _text(out.get("task_class"), default="general").lower()
    if task_class not in _TASK_CLASS_SET:
        task_class = "general"

    compile_changes: list[str] = []
    if isinstance(compile_meta, Mapping):
        raw_changes = compile_meta.get("changes")
        if isinstance(raw_changes, list):
            compile_changes = [str(item) for item in raw_changes]

    workflow = _text(out.get("workflow"), default="chain").lower()
    policy_meta = {
        "applied": False,
        "mode": mode,
        "token_economy": token_economy,
        "task_class": task_class,
        "policy_locked": bool(out.get("workflow_mode_lock") or out.get("workflow_lock")),
        "reason": "structured_routing_only",
        "input_workflow": workflow or "unspecified",
        "effective_workflow": workflow or "chain",
        "compile_changes": compile_changes,
    }
    return out, policy_meta
