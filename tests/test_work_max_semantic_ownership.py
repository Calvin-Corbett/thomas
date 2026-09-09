"""Regression contracts for model-owned Work and Max routing."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from thomas.marketplace.autonomy.mode_policy import apply_workflow_mode_policy
from thomas.marketplace.autonomy.nl_workflow_compiler import compile_nl_workflow_payload
from thomas.marketplace.orchestrator.exhaustive_pipeline import ExhaustivePipeline
from thomas.server.exhaustive_runtime import run_exhaustive_pipeline

ROOT = Path(__file__).resolve().parents[1]


def _identifiers(relative_path: str) -> set[str]:
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"), filename=relative_path)
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
    return identifiers


@pytest.mark.parametrize(
    ("relative_path", "forbidden"),
    [
        (
            "thomas/marketplace/autonomy/nl_workflow_compiler.py",
            {"_infer_workflow", "_infer_worker_count", "_routes_from_text", "_split_steps"},
        ),
        (
            "thomas/marketplace/autonomy/mode_policy.py",
            {"classify_task", "_CODING_RE", "_FILE_HINT_RE", "_RESEARCH_RE", "_PLAN_RE"},
        ),
        (
            "thomas/marketplace/orchestrator/task_router.py",
            {"classify_task", "_KEYWORD_RULES"},
        ),
        (
            "thomas/core/task_decomposer.py",
            {"analyze_task", "_CLARITY_SIGNALS", "_VAGUE_SIGNALS", "_COMPLEX_SIGNALS"},
        ),
        (
            "thomas/server/exhaustive_runtime.py",
            {"_task_needs_tools", "_task_needs_artifacts", "_TOOL_TASK_RE", "_ARTIFACT_INTENT_RE"},
        ),
    ],
)
def test_work_and_max_modules_have_no_named_prose_classifiers(
    relative_path: str,
    forbidden: set[str],
) -> None:
    present = _identifiers(relative_path).intersection(forbidden)
    assert not present, f"{relative_path} still classifies task prose through {sorted(present)}"


@pytest.mark.parametrize(
    "prose",
    [
        "Run five agents in parallel and build a game.",
        "If urgent then research, otherwise create a PDF.",
        "Refactor app.py and add tests with a coding crew.",
    ],
)
def test_prose_always_gets_the_same_neutral_workflow_contract(prose: str) -> None:
    payload, _meta = compile_nl_workflow_payload({"text": prose})
    assert payload["workflow"] == "chain"
    assert payload["steps"] == [prose]
    assert "workers" not in payload
    assert "worker_count" not in payload
    assert "routes" not in payload

    routed, policy = apply_workflow_mode_policy({**payload, "mode": "thinking", "token_economy": "max"})
    assert routed["workflow"] == "chain"
    assert policy["applied"] is False


@pytest.mark.asyncio
async def test_max_prompt_wording_does_not_choose_route_or_crew() -> None:
    pipeline = ExhaustivePipeline()
    first = await pipeline.run("build research debug security parallel")
    second = await pipeline.run("hello")
    assert first.task_type == second.task_type == "general"
    assert [role for role, _bot in first.crew] == [role for role, _bot in second.crew]


def test_max_tools_are_exposed_by_structured_control_not_prompt_words() -> None:
    parameters = inspect.signature(run_exhaustive_pipeline).parameters
    assert parameters["tools_enabled"].default is True
    assert "expected_artifacts" in parameters
    assert "tool_evidence_required" in parameters
