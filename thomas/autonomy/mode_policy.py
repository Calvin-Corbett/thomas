from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_MODE_SET = {"fast", "auto", "thinking", "swarm", "batch"}
_TOKEN_ECONOMY_SET = {"cheap", "optimal", "max"}
_DEFAULT_WORKFLOW_SET = {
    "",
    "chain",
    "prompt_chain",
    "sequential",
    "parallel",
    "map_reduce",
    "orchestrator_worker",
    "orchestrator-workers",
    "orchestrate",
}
_CODING_RE = re.compile(
    r"\b(code|coding|bug|fix|refactor|function|class|module|repo|commit|"
    r"test|unit test|integration test|api|endpoint|traceback|stack trace)\b",
    re.I,
)
_FILE_HINT_RE = re.compile(
    r"[A-Za-z]:\\|/[\w./-]+|\.(py|ts|tsx|js|jsx|go|rs|java|kt|cs|json|toml|yaml|yml|md)\b",
    re.I,
)
_RESEARCH_RE = re.compile(r"\b(research|compare|latest|look up|online|search)\b", re.I)
_PLAN_RE = re.compile(r"\b(plan|roadmap|workflow|strategy|steps)\b", re.I)


def _text(value: Any, *, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    return default


def _as_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        parsed = int(default)
    return max(minimum, min(maximum, parsed))


def _task_source(payload: Mapping[str, Any]) -> str:
    parts = [
        _text(payload.get("goal")),
        _text(payload.get("prompt")),
        _text(payload.get("task")),
        _text(payload.get("text")),
        _text(payload.get("description")),
        _text(payload.get("instructions")),
    ]
    return "\n".join([p for p in parts if p]).strip()


def classify_task(payload: Mapping[str, Any]) -> str:
    source = _task_source(payload)
    if not source:
        return "general"
    if _CODING_RE.search(source) or _FILE_HINT_RE.search(source):
        return "coding"
    if _RESEARCH_RE.search(source):
        return "research"
    if _PLAN_RE.search(source):
        return "planning"
    return "general"


def apply_workflow_mode_policy(
    payload: Mapping[str, Any],
    *,
    compile_meta: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    out: dict[str, Any] = dict(payload or {})
    mode = _text(out.get("mode"), default="auto").lower()
    if mode not in _MODE_SET:
        mode = "auto"
    token_economy = _text(out.get("token_economy"), default="optimal").lower()
    if token_economy not in _TOKEN_ECONOMY_SET:
        token_economy = "optimal"

    workflow_in = _text(out.get("workflow")).lower()
    task_class = classify_task(out)
    policy_locked = bool(out.get("workflow_mode_lock") or out.get("workflow_lock"))
    desired_workflow = workflow_in
    reason = "noop"

    if not policy_locked and task_class == "coding":
        if token_economy == "max":
            reason = "max_coding_pipeline"
            if workflow_in in _DEFAULT_WORKFLOW_SET:
                desired_workflow = "coding_pipeline"
            out.setdefault("max_rounds", 2 if mode in {"auto", "thinking"} else 1)
            out.setdefault("coder_capability", "chat")
            out.setdefault("reviewer_capability", "chat")
            out.setdefault("fixer_capability", "chat")
        elif mode == "fast" and token_economy == "cheap":
            reason = "fast_cheap_minimal"
            if workflow_in in _DEFAULT_WORKFLOW_SET:
                desired_workflow = "chain"
            out["worker_count"] = 1
        elif workflow_in in {"", "chain", "prompt_chain", "sequential"}:
            reason = "coding_orchestrated_default"
            desired_workflow = "orchestrator_worker"
            out["worker_count"] = max(
                2,
                _as_int(out.get("worker_count"), default=3, minimum=1, maximum=8),
            )

    applied = bool(desired_workflow and desired_workflow != workflow_in)
    if desired_workflow:
        out["workflow"] = desired_workflow
    compile_changes = []
    if isinstance(compile_meta, Mapping):
        raw_changes = compile_meta.get("changes")
        if isinstance(raw_changes, list):
            compile_changes = [str(x) for x in raw_changes]

    policy_meta = {
        "applied": bool(applied),
        "mode": mode,
        "token_economy": token_economy,
        "task_class": task_class,
        "policy_locked": bool(policy_locked),
        "reason": reason,
        "input_workflow": workflow_in or "unspecified",
        "effective_workflow": _text(out.get("workflow"), default="chain").lower(),
        "compile_changes": compile_changes,
    }
    return out, policy_meta
