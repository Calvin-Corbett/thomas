from __future__ import annotations

import re
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


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _has_list_payload(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _extract_source_text(payload: Mapping[str, Any]) -> str:
    for key in _TEXT_KEYS:
        raw = _text(payload.get(key))
        if raw:
            return raw
    return ""


def _split_steps(text: str) -> list[str]:
    raw = _text(text)
    if not raw:
        return []

    lines = [line.strip(" -\t") for line in raw.replace("\r", "\n").split("\n") if line.strip()]
    if len(lines) <= 1:
        line = lines[0] if lines else raw
        line = re.sub(r"\b(and then|then)\b", "|", line, flags=re.IGNORECASE)
        line = line.replace(";", "|").replace("->", "|")
        lines = [part.strip(" -\t") for part in line.split("|") if part.strip()]

    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        cleaned = re.sub(r"^\d+[\).\s-]+", "", line).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _infer_workflow(text: str) -> str:
    source = _text(text).lower()
    if not source:
        return "chain"
    if any(token in source for token in ("orchestrate", "delegate", "multi-agent", "multi agent", "fan out")):
        return "orchestrator_worker"
    if any(token in source for token in ("parallel", "simultaneous", "at the same time", "in parallel")):
        return "parallel"
    if any(token in source for token in ("evaluate and improve", "critique and refine", "iterate until", "optimize")):
        return "evaluator_optimizer"
    if " if " in f" {source} " and any(token in source for token in (" then ", " else ", "otherwise")):
        return "routing"
    return "chain"


def _infer_worker_count(text: str) -> int:
    source = _text(text).lower()
    match = re.search(r"\b(\d{1,2})\s+(workers|agents|tracks|streams)\b", source)
    if match is not None:
        try:
            count = int(match.group(1))
            return max(1, min(8, count))
        except (ValueError, TypeError):
            pass
    if "two" in source:
        return 2
    if "three" in source:
        return 3
    if "four" in source:
        return 4
    return 3


def _routes_from_text(text: str) -> list[dict[str, str]]:
    source = _text(text)
    compact = " ".join(source.split())
    m = re.search(
        r"\bif\s+(?P<when>.+?)\s+then\s+(?P<then>.+?)(?:\s+else\s+(?P<else>.+))?$",
        compact,
        flags=re.IGNORECASE,
    )
    if m is None:
        return []

    when_text = _text(m.group("when"))
    then_text = _text(m.group("then"))
    else_text = _text(m.group("else"))
    routes: list[dict[str, str]] = []
    if when_text and then_text:
        routes.append(
            {
                "name": "if-true",
                "when": when_text,
                "prompt": then_text,
                "capability": "chat",
            }
        )
    if else_text:
        routes.append(
            {
                "name": "if-false",
                "when": f"not ({when_text})" if when_text else "fallback",
                "prompt": else_text,
                "capability": "chat",
            }
        )
    return routes


def _compile_chain(payload: dict[str, Any], source_text: str, changes: list[str]) -> None:
    if _has_list_payload(payload.get("steps")) or _text(payload.get("step")):
        return
    steps = _split_steps(source_text)
    if not steps and source_text:
        steps = [source_text]
    if steps:
        payload["steps"] = steps[:8]
        changes.append("steps")


def _compile_parallel(payload: dict[str, Any], source_text: str, changes: list[str]) -> None:
    if _has_list_payload(payload.get("workers")):
        return
    tasks = _split_steps(source_text)
    if not tasks and source_text:
        tasks = [source_text]
    workers = [
        {"name": f"worker-{idx + 1}", "prompt": prompt, "capability": "chat"} for idx, prompt in enumerate(tasks[:8])
    ]
    if workers:
        payload["workers"] = workers
        changes.append("workers")


def _compile_orchestrator(payload: dict[str, Any], source_text: str, changes: list[str]) -> None:
    if payload.get("worker_count") is None:
        payload["worker_count"] = _infer_worker_count(source_text)
        changes.append("worker_count")


def _compile_routing(payload: dict[str, Any], source_text: str, changes: list[str]) -> None:
    if _has_list_payload(payload.get("routes")):
        return
    routes = _routes_from_text(source_text)
    if routes:
        payload["routes"] = routes
        changes.append("routes")
        return
    # If route extraction fails, degrade to a deterministic chain so workflow execution still succeeds.
    payload["workflow"] = "chain"
    changes.append("workflow(chain_fallback)")
    _compile_chain(payload, source_text, changes)


def _compile_evaluator(payload: dict[str, Any], source_text: str, changes: list[str]) -> None:
    if not _text(payload.get("rubric")):
        payload["rubric"] = "Correctness, completeness, clarity, and actionable next steps."
        changes.append("rubric")
    if payload.get("max_rounds") is None:
        payload["max_rounds"] = 2
        changes.append("max_rounds")


def compile_nl_workflow_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Compile natural-language workflow payloads into structured workflow contracts.

    Returns:
    - normalized payload
    - compile metadata (or None when no compilation/enrichment happened)
    """

    out: dict[str, Any] = dict(payload) if isinstance(payload, Mapping) else {}
    source_text = _extract_source_text(out)
    changes: list[str] = []

    workflow = _text(out.get("workflow") or out.get("pattern")).lower()
    if not workflow:
        workflow = _infer_workflow(source_text)
        out["workflow"] = workflow
        changes.append("workflow")
    else:
        out["workflow"] = workflow

    if not _text(out.get("goal")) and source_text:
        out["goal"] = source_text
        changes.append("goal")

    if workflow in {"chain", "prompt_chain", "sequential"}:
        _compile_chain(out, source_text, changes)
    elif workflow in {"parallel", "map_reduce"}:
        _compile_parallel(out, source_text, changes)
    elif workflow in {"orchestrator_worker", "orchestrator-workers", "orchestrate"}:
        _compile_orchestrator(out, source_text, changes)
    elif workflow in {"routing", "router"}:
        _compile_routing(out, source_text, changes)
    elif workflow in {"evaluator_optimizer", "eval_opt", "optimize"}:
        _compile_evaluator(out, source_text, changes)

    if not changes:
        return out, None

    compile_meta = {
        "version": "nl_workflow_compiler_v1",
        "workflow": _text(out.get("workflow")),
        "changes": changes,
        "source_text_preview": source_text[:240],
    }
    return out, compile_meta
