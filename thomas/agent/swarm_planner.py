"""Generic prompt-to-task decomposition helpers for Thomas swarm flows.

This module is intentionally stdlib-only and independent from the runtime
orchestrator so both benchmarks and future chat/server integrations can share
the same decomposition logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

DEFAULT_SWARM_MAX_TASKS = 12

_STOPWORDS = set(
    "a an and app application build create for from in make of on project "
    "required should task that the to useful with you".split()
)

_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")
_SKIP_REQUEST_LINE_RE = re.compile(
    r"^(?:you are|act as|pretend|role:|required broad capabilities:?|in addition to)\b",
    flags=re.IGNORECASE,
)
_REQUEST_VERB_RE = re.compile(
    r"^(?:please\s+)?(?:we\s+need(?:\s+to)?|need(?:\s+to)?|build|create|make|design|develop|implement|ship)\s+",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class PromptTaskSlice:
    key: str
    title: str
    focus_term: str
    task_prompt: str
    mission: str
    deliverable: str
    depends_on: tuple[str, ...]


def normalize_request(user_request: str | None) -> str:
    text = str(user_request or "").strip()
    return text or "Build a useful project from the requested task."


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return value or "project"


def prompt_terms(user_request: str) -> list[str]:
    prompt = normalize_request(user_request)
    source = " ".join(
        part
        for part in (
            _extract_subject(prompt),
            _request_sentence(prompt),
            " ".join(_bullet_units(prompt)[:4]),
        )
        if part
    )
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", source or prompt)
    terms: list[str] = []
    for word in words:
        lowered = word.lower().strip("-")
        if lowered in _STOPWORDS or lowered in terms:
            continue
        terms.append(lowered)
    return terms[:8] or ["project"]


def project_label(user_request: str) -> str:
    return " ".join(term.title() for term in prompt_terms(user_request)[:4])


def _clean_unit(text: str, fallback: str = "project") -> str:
    unit = re.sub(r"\s+", " ", str(text or "").strip(" ,.;:-")).strip()
    unit = _REQUEST_VERB_RE.sub("", unit)
    unit = re.sub(r"^(?:a|an|the)\s+", "", unit, flags=re.IGNORECASE)
    return unit.strip() or fallback


def _request_sentence(user_request: str) -> str:
    prompt = normalize_request(user_request)
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    fallback = lines[0] if lines else prompt
    for line in lines:
        if _BULLET_RE.match(line) or _SKIP_REQUEST_LINE_RE.match(line):
            continue
        return re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0]
    return re.split(r"(?<=[.!?])\s+", fallback, maxsplit=1)[0]


def _extract_subject(user_request: str) -> str:
    sentence = _request_sentence(user_request)
    subject = _REQUEST_VERB_RE.sub("", sentence)
    subject = re.split(
        r"\b(?:with|including|featuring|plus|keep|it should|this should|that should|must)\b",
        subject,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return _clean_unit(subject)


def _bullet_units(user_request: str) -> list[str]:
    units: list[str] = []
    seen: set[str] = set()
    for raw_line in normalize_request(user_request).splitlines():
        match = _BULLET_RE.match(raw_line.strip())
        if not match:
            continue
        unit = _clean_unit(match.group(1), fallback="")
        unit_key = slug(unit)
        if not unit or not unit_key or unit_key in seen:
            continue
        units.append(unit)
        seen.add(unit_key)
    return units


def _append_unique_unit(units: list[str], seen: set[str], raw_unit: str) -> None:
    unit = _clean_unit(raw_unit, fallback="")
    unit_key = slug(unit)
    if not unit or not unit_key or unit_key in seen:
        return
    units.append(unit)
    seen.add(unit_key)


def prompt_units(user_request: str) -> list[str]:
    prompt = normalize_request(user_request)
    subject = _extract_subject(prompt)
    units: list[str] = []
    seen: set[str] = set()
    _append_unique_unit(units, seen, subject)
    for unit in _bullet_units(prompt):
        _append_unique_unit(units, seen, unit)
    if len(units) == 1:
        request_sentence = _request_sentence(prompt)
        parts = re.split(
            r"\b(?:with|including|featuring|plus)\b",
            request_sentence,
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        if len(parts) > 1:
            raw_units = re.split(r",|\band\b|\bplus\b|/|&", parts[1], flags=re.IGNORECASE)
            for raw in raw_units:
                _append_unique_unit(units, seen, raw)
    for term in prompt_terms(prompt):
        phrase = term.replace("-", " ")
        _append_unique_unit(units, seen, phrase)
        if len(units) >= 8:
            break
    return units[:8] or ["project"]


def _focus_term(unit: str, fallback: tuple[str, ...]) -> str:
    terms = prompt_terms(unit)
    if terms:
        return terms[0]
    return fallback[0] if fallback else "project"


def _task_unit_key(unit: str, subject: str, subject_key: str) -> str:
    if unit == subject:
        return subject_key
    return slug(unit)


def build_prompt_task_slices(user_request: str | None, max_slices: int) -> list[PromptTaskSlice]:
    prompt = normalize_request(user_request)
    if int(max_slices) < 1:
        raise ValueError("max_slices must be at least 1")
    units = prompt_units(prompt)
    focus_terms = tuple(prompt_terms(prompt))
    subject = units[0]
    subject_key = f"{slug(subject)}_foundation"
    slices: list[PromptTaskSlice] = [
        PromptTaskSlice(
            key=subject_key,
            title=f"{subject.title()} Shared Foundation",
            focus_term=_focus_term(subject, focus_terms),
            task_prompt=f"Establish the shared shell, state, and contracts for {prompt}.",
            mission=f"Create the first coordinated slice of the project so later workers can build on the same base: {prompt}",
            deliverable=f"shared shell and state for {subject}",
            depends_on=(),
        )
    ]
    feature_units = units[1:] or [f"{subject} core workflow"]
    for unit in feature_units:
        slices.append(
            PromptTaskSlice(
                key=_task_unit_key(unit, subject, subject_key),
                title=f"{unit.title()} Workstream",
                focus_term=_focus_term(unit, focus_terms),
                task_prompt=f"Implement the {unit} portion of {prompt}.",
                mission=f"Turn the task prompt into executable code focused on {unit}: {prompt}",
                deliverable=f"working {unit} contribution",
                depends_on=(subject_key,),
            )
        )
    for left, right in zip(feature_units, feature_units[1:]):
        left_key = _task_unit_key(left, subject, subject_key)
        right_key = _task_unit_key(right, subject, subject_key)
        slices.append(
            PromptTaskSlice(
                key=f"{left_key}_{right_key}_handoff",
                title=f"{left.title()} to {right.title()} Handoff",
                focus_term=_focus_term(right, focus_terms),
                task_prompt=f"Make {left} and {right} work together cleanly inside {prompt}.",
                mission=f"Coordinate adjacent work slices so they integrate instead of drifting apart: {prompt}",
                deliverable=f"coordinated behavior between {left} and {right}",
                depends_on=(left_key, right_key),
            )
        )
    index = 0
    while len(slices) < max_slices:
        source = feature_units[index % len(feature_units)]
        target = units[(index + 1) % len(units)]
        source_key = _task_unit_key(source, subject, subject_key)
        target_key = _task_unit_key(target, subject, subject_key)
        if source_key == target_key:
            key = f"{source_key}_extension_{index + 1}"
            title = f"{source.title()} Extension {index + 1}"
            task_prompt = f"Extend the {source} capability with another concrete slice for {prompt}."
            deliverable = f"extended {source} behavior"
            depends_on = (source_key,)
        else:
            key = f"{source_key}_{target_key}_coordination_{index + 1}"
            title = f"{source.title()} with {target.title()} Coordination"
            task_prompt = f"Coordinate {source} with {target} so the project behaves as one product for {prompt}."
            deliverable = f"coordinated {source} and {target} behavior"
            depends_on = (source_key, target_key)
        slices.append(
            PromptTaskSlice(
                key=key,
                title=title,
                focus_term=_focus_term(source, focus_terms),
                task_prompt=task_prompt,
                mission=f"Produce another task-derived implementation slice without using a prebuilt lane template: {prompt}",
                deliverable=deliverable,
                depends_on=depends_on,
            )
        )
        index += 1
    unique_slices: list[PromptTaskSlice] = []
    seen_keys: set[str] = set()
    for slice_ in slices:
        if slice_.key in seen_keys:
            continue
        unique_slices.append(slice_)
        seen_keys.add(slice_.key)
    return unique_slices[:max_slices]


def build_task_graph_dict(user_request: str | None, max_tasks: int = DEFAULT_SWARM_MAX_TASKS) -> dict[str, Any]:
    from thomas.agent.swarm_planner_graph import build_task_graph_dict as _build_task_graph_dict

    return _build_task_graph_dict(user_request, max_tasks=max_tasks)


def build_task_graph_json(user_request: str | None, max_tasks: int = DEFAULT_SWARM_MAX_TASKS) -> str:
    return json.dumps(build_task_graph_dict(user_request, max_tasks=max_tasks), indent=2)


__all__ = [
    "DEFAULT_SWARM_MAX_TASKS",
    "PromptTaskSlice",
    "build_prompt_task_slices",
    "build_task_graph_dict",
    "build_task_graph_json",
    "normalize_request",
    "project_label",
    "prompt_terms",
    "prompt_units",
    "slug",
]
