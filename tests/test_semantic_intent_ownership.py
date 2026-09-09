"""Contracts for model-owned semantic intent.

These tests intentionally target named semantic routing mechanisms. They do not
ban regex generally: validation, security, protocol parsing, redaction, and result
verification remain deterministic runtime responsibilities.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from thomas.core.llm_shared import StreamEvent
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist
from thomas.marketplace.specialists.reasoning_task_briefs import build_send_task_instructions

ROOT = Path(__file__).resolve().parents[1]


def _source_identifiers(relative_path: str) -> set[str]:
    """Return code identifiers, excluding comments and string contents."""
    path = ROOT / relative_path
    if not path.exists():
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit(".", 1)[-1])
    return names


@pytest.mark.parametrize(
    ("relative_path", "forbidden"),
    [
        (
            "thomas/server/routes/chat_v2.py",
            {
                "should_dispatch",
                "_should_auto_background_actionable",
                "_maybe_handle_autopilot_chat",
                "_handle_ui_control_turn",
            },
        ),
        (
            "thomas/server/routes/chat_v2_support.py",
            {
                "should_dispatch",
                "_should_auto_background_actionable",
                "_requests_explicit_delegation",
                "_requires_inline_tool_execution",
            },
        ),
        (
            "thomas/server/routes/chat_aiohttp_streaming.py",
            {"should_dispatch"},
        ),
        (
            "thomas/server/routes/chat_plan_mode.py",
            {"parse_steps_from_text"},
        ),
        (
            "thomas/agent/execution_plan.py",
            {"parse_steps_from_text"},
        ),
        (
            "thomas/marketplace/orchestrator/brain.py",
            {
                "should_dispatch",
                "_classify_and_route",
                "_TOOLS_ROUTE_RE",
                "_CODE_PHRASE_RECALL_RE",
                "_CODE_PHRASE_FACT_RE",
            },
        ),
        (
            "thomas/marketplace/specialists/reasoning.py",
            {
                "_CLAIMS_HANDOFF_RE",
                "_CLAIMS_CANCEL_RE",
                "_TEXT_TOOLCALL_START_RE",
                "_parse_text_toolcall",
                "explicit_web_search_requested",
            },
        ),
        (
            "thomas/server/chat_delegation.py",
            {
                "is_canvas_task",
                "prompt_needs_handoff",
                "_infer_specialist",
                "_requested_delegate_count",
                "_requested_delegate_items",
                "_prompt_targets_live_thomas_repo",
            },
        ),
        (
            "thomas/server/chat_delegation_canvas_intent.py",
            {"is_canvas_task"},
        ),
        (
            "thomas/server/chat_delegation_worker_config.py",
            {
                "_infer_specialist",
                "_requested_delegate_count",
                "_requested_delegate_items",
                "_prompt_requires_artifact_write",
            },
        ),
        (
            "thomas/server/chat_delegation_live_repo.py",
            {"_prompt_targets_live_thomas_repo"},
        ),
        (
            "thomas/server/chat_delegation_deliverable.py",
            {"prompt_needs_handoff"},
        ),
        (
            "thomas/agent/routing.py",
            {
                "_PATHY_RE",
                "_STACK_RE",
                "_LIVENESS_RE",
                "_INTEGRATION_RE",
                "_SETUP_RE",
                "_TROUBLESHOOT_RE",
                "_CODE_CONTEXT_RE",
                "_FIX_RE",
                "_BEHAVIOR_FEEDBACK_RE",
                "_NO_EXECUTION_RE",
                "_EXECUTION_PREFERENCE_RE",
            },
        ),
        (
            "thomas/agent/loop_execution.py",
            {
                "check_if_followup",
                "detect_user_confusion",
                "resolve_message_references",
                "_has_explicit_action_intent",
                "_is_project_related_prompt",
                "_is_tool_usage_question",
            },
        ),
        (
            "thomas/agent/loop_tools.py",
            {"_has_explicit_action_intent", "_is_low_intent_route"},
        ),
        (
            "thomas/server/routes/evolve_agent_runtime.py",
            {
                "_DISCUSSION_ONLY_RISK_REQUEST",
                "_NEGATED_RISK_ACTION",
                "_DISCUSSION_THEN_ACTION",
                "_RISKY_CODE_INTENTS",
                "_risky_code_action",
            },
        ),
        (
            "thomas/server/routes/evolve_agent_routes.py",
            {"_risky_code_action"},
        ),
        (
            "thomas/agent/skills_runtime.py",
            {
                "_keyword_tokens",
                "_skill_relevance_score",
                "keyword_tokens",
                "auto_relevance_enabled",
                "has_skill_approval_phrase",
                "is_globally_approved",
                "prompt_negates_risky_approval",
            },
        ),
        (
            "thomas/agent/skills_policy.py",
            {
                "has_skill_approval_phrase",
                "is_globally_approved",
                "prompt_negates_risky_approval",
                "_APPROVAL_NEGATION_RE",
                "_RISKY_APPROVAL_NEGATION_RE",
            },
        ),
        (
            "thomas/server/chat_delegation_canvas_completion.py",
            {"is_static_chart_request", "export_static_chart"},
        ),
        (
            "thomas/server/chat_delegation_canvas_review.py",
            {"tokenize_prompt", "is_chart_request", "chart_prompt_pairs", "_chart_pair_mismatches"},
        ),
        (
            "thomas/server/chat_delegation_canvas_review_rules.py",
            {"PROMPT_STOPWORDS", "CHART_PAIR_RE", "tokenize_prompt", "is_chart_request", "chart_prompt_pairs"},
        ),
        (
            "thomas/server/chat_delegation_deliverable.py",
            {
                "_claimed_filenames",
                "_claims_file_creation",
                "_claims_action_success",
                "_requests_action_execution",
                "_has_action_or_outcome_claim",
                "_tool_corresponds",
            },
        ),
        (
            "thomas/server/chat_delegation_artifact_verification.py",
            {
                "_prompt_requires_skill_change",
                "_requested_names",
                "_requested_artifact_issues",
                "_reconcile_missing_marker_literals",
                "_reconcile_requested_artifact_from_evidence",
            },
        ),
        (
            "thomas/server/chat_delegation_result_policy.py",
            {
                "_requests_artifact_deliverable",
                "should_finalize_exact_artifact_tool_result",
                "_ACKNOWLEDGEMENT_ONLY_RE",
                "_PROMISE_ONLY_RE",
                "_NONFINAL_PROGRESS_RE",
            },
        ),
        (
            "thomas/server/chat_delegation_live_repo.py",
            {"_prompt_has_hint", "_prompt_allows_docs_only_completion"},
        ),
        (
            "thomas/core/rules_of_road.py",
            {
                "_VIDEO_RE",
                "_CONFIG_RE",
                "_response_has_unresolved_issue_language",
                "_UNRESOLVED_ISSUE_STRONG_RE",
                "_WORKAROUND_LANGUAGE_RE",
            },
        ),
        (
            "thomas/agent/completion_gate.py",
            {
                "parse_give_up",
                "GATE_GIVE_UP",
                "GATE_DEMAND_GIVE_UP",
                "_MARKER_RE",
                "_FIELD_RE",
                "build_give_up_demand_prompt",
            },
        ),
        (
            "thomas/core/ui_review.py",
            {"intent_keywords", "_INTENT_STOPWORDS", "_WORD_RE"},
        ),
        (
            "thomas/core/ui_workflow_engine.py",
            {"_infer_recent_intent"},
        ),
    ],
)
def test_core_orchestration_modules_do_not_use_named_semantic_classifiers(
    relative_path: str,
    forbidden: set[str],
) -> None:
    present = _source_identifiers(relative_path).intersection(forbidden)
    assert not present, f"{relative_path} still owns semantic intent through {sorted(present)}"


def test_canvas_has_no_prompt_classified_export_runtime() -> None:
    assert not (ROOT / "thomas/server/chat_delegation_canvas_export.py").exists()


def test_agent_has_no_prompt_classified_constraint_retention_runtime() -> None:
    """Long-context constraints must not be inferred with marker/token rules."""
    assert not (ROOT / "thomas/agent/constraint_retention.py").exists()


def test_single_dispatch_preserves_the_models_resolved_task_brief() -> None:
    instructions = build_send_task_instructions(
        "I do not care which format; you pick.",
        {
            "instructions": (
                "Create a clear graph of the quarterly sales trend discussed above; "
                "choose the most readable chart type and preserve the supplied data."
            )
        },
        "Graph quarterly sales",
        multi_dispatch=False,
    )

    assert instructions.startswith("Create a clear graph of the quarterly sales trend")
    assert instructions != "I do not care which format; you pick."


class _ScriptedLLM:
    def __init__(self, events: list[StreamEvent]) -> None:
        self._events = events

    def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ARG002
        async def _stream():
            for event in self._events:
                yield event

        return _stream()


async def _run_prose_only_reply(
    text: str,
    *,
    send_task=None,
    update_task=None,
) -> list[dict]:
    specialist = ReasoningSpecialist(
        config=None,
        llm=_ScriptedLLM([StreamEvent(type="token", data={"text": text}), StreamEvent(type="done")]),
    )
    contract = DelegationContract(
        specialist_id="reasoning",
        task_description="semantic ownership test",
        allowed_tools={"reasoning"},
        timeout_seconds=0,
        input_context={
            "send_task": send_task,
            "update_task": update_task,
            "autonomy": {"level": 4},
        },
    )
    token = CapabilityToken(
        specialist_id="reasoning",
        session_id="semantic-ownership",
        allowed_tools={"reasoning"},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    return [
        event
        async for event in specialist.execute(
            contract=contract,
            token=token,
            prompt="Please handle this request.",
            conversation_context=[],
            memory_context="",
        )
    ]


@pytest.mark.asyncio
async def test_assistant_prose_cannot_dispatch_or_cancel_work() -> None:
    effects: list[str] = []

    async def send_task(**kwargs) -> None:  # noqa: ANN003
        effects.append(f"dispatch:{kwargs}")

    async def update_task(**kwargs) -> dict:  # noqa: ANN003
        effects.append(f"update:{kwargs}")
        return {"ok": True, "action": "cancel"}

    for prose in (
        "On it - I handed that to the crew.",
        'send_task {"title":"Wrong","instructions":"Do not execute prose"}',
        "Done - I cancelled the running task.",
    ):
        events = await _run_prose_only_reply(
            prose,
            send_task=send_task,
            update_task=update_task,
        )
        assert not any(event.get("type") in {"task_request", "task_update"} for event in events)

    assert effects == []
