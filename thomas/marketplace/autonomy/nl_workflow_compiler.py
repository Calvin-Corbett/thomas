"""Structured workflow normalization with neutral single-task defaults.

Natural-language instructions are task content, not routing metadata.  Only
explicit structured fields may select a workflow or request fan-out.  This
compatibility entry point therefore fills the smallest runnable contract when
callers provide prose alone: one ``chain`` step containing the original text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_TEXT_KEYS: tuple[str, ...] = (
    "workflow_text",
    "workflow_prompt",
    "request",
    "instructions",
    "description",
    "text",
    "prompt",
    "goal",
    "task",
)

_WORKFLOW_ALIASES = {
    "prompt_chain": "chain",
    "sequential": "chain",
    "map_reduce": "parallel",
    "orchestrator-workers": "orchestrator_worker",
    "orchestrate": "orchestrator_worker",
    "router": "routing",
    "eval_opt": "evaluator_optimizer",
    "optimize": "evaluator_optimizer",
}
_WORKFLOWS = {
    "chain",
    "parallel",
    "orchestrator_worker",
    "routing",
    "evaluator_optimizer",
    "coding_pipeline",
}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _extract_source_text(payload: Mapping[str, Any]) -> str:
    for key in _TEXT_KEYS:
        raw = _text(payload.get(key))
        if raw:
            return raw
    return ""


def _structured_workflow(value: Any) -> str:
    requested = _text(value).lower()
    requested = _WORKFLOW_ALIASES.get(requested, requested)
    return requested if requested in _WORKFLOWS else ""


def compile_nl_workflow_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Normalize an explicit workflow contract without interpreting prose.

    The historic public name is retained for callers, but no natural-language
    compilation remains. Unknown or absent workflow values become a single
    ``chain`` task. Explicit worker, route, rubric, and round fields are left for
    the workflow schema and runner to validate.
    """

    out: dict[str, Any] = dict(payload) if isinstance(payload, Mapping) else {}
    source_text = _extract_source_text(out)
    changes: list[str] = []

    workflow = _structured_workflow(out.get("workflow") or out.get("pattern"))
    if not workflow:
        workflow = "chain"
        changes.append("workflow(neutral_default)")
    out["workflow"] = workflow

    if not _text(out.get("goal")) and source_text:
        out["goal"] = source_text
        changes.append("goal")

    if workflow == "chain" and not isinstance(out.get("steps"), list) and source_text:
        out["steps"] = [source_text]
        changes.append("steps(single_task_default)")

    if not changes:
        return out, None

    compile_meta = {
        "version": "structured_workflow_defaults_v2",
        "workflow": workflow,
        "changes": changes,
        "source_text_preview": source_text[:240],
    }
    return out, compile_meta
