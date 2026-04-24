#!/usr/bin/env python3
"""Task-type to specialist routing helpers for task-manager orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class SpecialistRule:
    task_type: str
    specialist: str
    keywords: tuple[str, ...]


SPECIALIST_RULES: tuple[SpecialistRule, ...] = (
    SpecialistRule(
        task_type="brainstorm_orchestration",
        specialist="specialist-brainstorm-facilitator",
        keywords=(
            "brainstorm",
            "all-hands",
            "all hands",
            "workshop",
            "design spike",
            "whiteboard",
            "consensus",
            "facilitate",
        ),
    ),
    SpecialistRule(
        task_type="openai_specialist_framework",
        specialist="specialist-openai-framework",
        keywords=(
            "openai specialist",
            "openai agents",
            "specialist framework",
            "specialist agent",
            "agent sdk",
            "agents sdk",
            "responses api",
            "tool calling",
        ),
    ),
    SpecialistRule(
        task_type="quality_benchmark",
        specialist="specialist-quality-benchmark",
        keywords=(
            "benchmark",
            "quality benchmark",
            "evaluation",
            "agent quality",
            "baselines",
            "token efficiency",
            "latency",
            "reliability",
        ),
    ),
    SpecialistRule(
        task_type="testing_quality",
        specialist="specialist-test-rigor",
        keywords=(
            "tests",
            "pytest",
            "regression",
            "coverage",
            "workflow",
            ".github/workflows",
            "ci",
            "gate",
        ),
    ),
    SpecialistRule(
        task_type="task_ecosystem_ops",
        specialist="specialist-task-ecosystem",
        keywords=(
            "ecosystem",
            "workboard",
            "task manager",
            "task ecosystem",
            "claim",
            "issues / blockers",
            "up for grabs",
            "delegation",
            "coordination",
            "orchestration",
            "dispatch",
            "triage",
            "dependency",
            "backlog",
            "reassign",
            "priority refresh",
            "task queue",
            "swarm",
            "terminal orchestration",
            "spawn terminals",
            "agent traffic",
            "session",
            "specialist",
            "message",
        ),
    ),
    SpecialistRule(
        task_type="ui_operator_experience",
        specialist="specialist-ui-operator",
        keywords=(
            "ui",
            "web-ui",
            "thomas/server/web",
            "operator",
            "companion",
            "frontend",
            "mission control",
            "screenshots",
        ),
    ),
    SpecialistRule(
        task_type="repo_hygiene_cleanup",
        specialist="specialist-repo-hygiene",
        keywords=(
            "cleanup",
            "orphan",
            "unused",
            "stale",
            "archive",
            ".gitignore",
            "tmp",
            "output",
            "generated artifact",
            "dead code",
            "root task md",
            "legacy ui",
        ),
    ),
    SpecialistRule(
        task_type="preferences_onboarding",
        specialist="specialist-preferences-onboarding",
        keywords=(
            "preferences",
            "onboarding",
            "profile",
            "setup wizard",
            "experience",
            "review depth",
            "non_coder",
            "coder",
        ),
    ),
    SpecialistRule(
        task_type="security_compliance",
        specialist="specialist-security-compliance",
        keywords=(
            "security",
            "compliance",
            "policy",
            "auth",
            "permission",
            "branch protection",
            "audit",
        ),
    ),
)

FALLBACK_ROUTE: dict[str, str] = {
    "task_type": "generalist_engineering",
    "specialist": "specialist-generalist-engineering",
}

TASK_ID_PREFIX_BOOSTS: tuple[tuple[str, str, int], ...] = (
    ("ecosystem-", "task_ecosystem_ops", 3),
    ("task-creator", "task_ecosystem_ops", 3),
    ("cleanup-", "repo_hygiene_cleanup", 2),
)


def _normalize_text(parts: Iterable[str]) -> str:
    rows: list[str] = []
    for item in parts:
        text = str(item or "").strip().lower()
        if text:
            rows.append(text)
    return " ".join(rows)


def _task_id_boost(*, task_id: str, task_type: str) -> int:
    normalized_task_id = str(task_id or "").strip().lower()
    if not normalized_task_id:
        return 0
    bonus = 0
    for prefix, routed_type, points in TASK_ID_PREFIX_BOOSTS:
        if normalized_task_id.startswith(prefix) and task_type == routed_type:
            bonus += int(points)
    return bonus


def infer_specialist(
    *,
    task_id: str,
    scope: str,
    summary: str,
) -> dict[str, object]:
    corpus = _normalize_text([task_id, scope, summary])
    if not corpus:
        return {
            "task_type": FALLBACK_ROUTE["task_type"],
            "specialist": FALLBACK_ROUTE["specialist"],
            "matched_keywords": [],
            "score": 0,
            "reason": "no task text available; routed to fallback specialist",
        }

    scored: list[tuple[int, SpecialistRule, list[str]]] = []
    for rule in SPECIALIST_RULES:
        matched = [token for token in rule.keywords if token in corpus]
        score = len(matched) + _task_id_boost(task_id=task_id, task_type=rule.task_type)
        scored.append((score, rule, matched))

    scored.sort(key=lambda item: (-item[0], item[1].task_type))
    top_score, top_rule, matched_tokens = scored[0]
    if top_score <= 0:
        return {
            "task_type": FALLBACK_ROUTE["task_type"],
            "specialist": FALLBACK_ROUTE["specialist"],
            "matched_keywords": [],
            "score": 0,
            "reason": "no specialist keywords matched; routed to fallback specialist",
        }

    return {
        "task_type": top_rule.task_type,
        "specialist": top_rule.specialist,
        "matched_keywords": matched_tokens[:6],
        "score": int(top_score),
        "reason": _build_reason(task_id=task_id, task_type=top_rule.task_type, matched_tokens=matched_tokens[:6]),
    }


def _build_reason(*, task_id: str, task_type: str, matched_tokens: list[str]) -> str:
    hints: list[str] = []
    if matched_tokens:
        hints.append("matched specialist keywords: " + ", ".join(matched_tokens))
    if _task_id_boost(task_id=task_id, task_type=task_type) > 0:
        hints.append("task-id prefix routing hint applied")
    if not hints:
        return "specialist selected from rule fallback"
    return " | ".join(hints)
