"""Per-turn context assembly for the main agent execution loop.

Split from ``loop_execution_setup.py``: that module carries the once-per-run
setup (``ExecutionSetup``, ``prepare_execution_setup``), while this one carries
the work done for each turn - memory retrieval, the library context block, the
optional hints, and the acceptance contract required on every model call.

Two modules rather than one because a single extracted file came to 324 lines and
``commit_growth_guard`` caps any file's growth at 300 lines in one commit. The
seam is the honest one anyway: run setup and turn context are different
lifetimes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from thomas.agent.acceptance_runtime import begin_contract, shorter_contract_blocks
from thomas.agent.loop_execution_setup import ExecutionSetup
from thomas.core.events import AgentEvent
from thomas.core.tokens import ContextBudgetExhausted, RequiredRequestTooLarge, estimate_tokens

if TYPE_CHECKING:
    from thomas.agent.loop import AgentLoop


def prepare_turn_context(
    self: AgentLoop,
    setup: ExecutionSetup,
    *,
    quality_retry_count: int,
) -> None:
    """Load optional memory/library context and retain the required acceptance contract."""
    if not setup.benchmark_mode:
        self._apply_memory_policy(setup.route)
        if setup.request_text:
            self._record_event("user_message", setup.request_text)
        if setup.routing_text:
            memory_mode = self.config.memory.mode or "auto"
            if setup.effective_mode == "fast":
                memory_mode = "fast"
            if setup.effective_mode == "thinking":
                memory_mode = "thorough"
            setup.memory_text = self._retrieve_memory(
                setup.routing_text,
                mode=memory_mode,
                budget_override=setup.route.memory_budget_tokens,
            )

    if setup.best_practice_gate_active and setup.best_practice_hint:
        if not setup.memory_text:
            setup.memory_text = setup.best_practice_hint
        elif setup.best_practice_hint not in setup.memory_text:
            setup.memory_text += "\n\n" + setup.best_practice_hint

    if setup.overhead_policy.include_library_context and not setup.benchmark_mode:
        setup.library_text = self._retrieve_library(setup.routing_text, setup.route)
        context_parts = [
            setup.memory_text,
            setup.continuity_hint,
            (
                setup.best_practice_hint
                if setup.best_practice_gate_active and setup.best_practice_hint not in setup.memory_text
                else ""
            ),
            (
                "Return ONLY the requested output format for this task, no prose or commentary."
                if setup.code_output_validation_enabled
                else ""
            ),
            setup.review_quality_hint,
            setup.test_visibility_hint,
            setup.library_text,
        ]
        setup.memory_text = "\n\n".join(part for part in context_parts if str(part).strip())
        setup.memory_tokens = estimate_tokens(setup.memory_text)

    repairing = quality_retry_count > 0 and bool(getattr(self, "_context_anchors", None))
    request_text = getattr(self, "_active_request_text", setup.request_text) if repairing else setup.request_text
    contract_block = begin_contract(
        self,
        prompt_text=request_text,
        route_path=str(setup.route.path or ""),
        attempt=int(quality_retry_count),
    )
    if repairing and not contract_block:
        contract_block = getattr(self, "_active_contract_block", "")
    if not repairing:
        self._active_request_text = setup.request_text
        self._active_contract_block = contract_block
    setup.contract_block = contract_block
    setup.memory_tokens = estimate_tokens(setup.memory_text) + estimate_tokens(contract_block)


def build_turn_messages(
    self: AgentLoop,
    state: Any,
    setup: ExecutionSetup,
    *,
    memory_text: str,
    preserve_first: int,
    preserve_last: int,
    iteration: int,
) -> tuple[list[dict[str, Any]], AgentEvent | None]:
    """Build one request, or stop the run before it can lose its own evidence.

    The contract block repeats every requirement whole. Where that second copy would push anything out of the
    window, a shorter block points at your messages instead, which are pinned to every call and hold each whole.
    """
    helper_role = str(getattr(self, "_build_helper_role_text", "") or "")
    required_text = setup.contract_block
    if helper_role:
        required_text = f"{helper_role}\n\n{required_text}" if required_text else helper_role
    try:
        messages = self._build_messages(
            state,
            memory_text=memory_text,
            tool_specs=setup.tool_specs,
            include_purpose=bool(setup.route.include_purpose) and bool(setup.overhead_policy.include_purpose_brief),
            preserve_first=preserve_first,
            preserve_last=preserve_last,
            history_token_cap=setup.history_token_cap,
            route_path=setup.prompt_route_path,
            skills_context=setup.runtime_skills_context,
            include_autonomy_profile=bool(setup.overhead_policy.include_autonomy_profile),
            include_editing_policy=bool(setup.overhead_policy.include_editing_policy)
            and setup.current_job_type != "self_development",
            include_project_instructions=bool(setup.overhead_policy.include_project_instructions),
            required_system_text=required_text,
            shorter_required_texts=[
                f"{helper_role}\n\n{short}" if helper_role else short
                for short in shorter_contract_blocks(self, setup.contract_block)
            ],
        )
        acceptance_state = getattr(self, "_acceptance_state", None)
        if isinstance(acceptance_state, dict):
            from thomas.core.tokens import estimate_messages_tokens

            acceptance_state["last_request_tokens"] = estimate_messages_tokens(messages)
            acceptance_state["last_request_messages"] = messages
            acceptance_state["repair_tool_specs"] = setup.tool_specs
    except (ContextBudgetExhausted, RequiredRequestTooLarge) as exc:
        message = str(exc)
        state.error = message
        state.finished = True
        self._context_budget_stop = message
        return [], AgentEvent.agent_error(message, iteration=iteration)
    return messages, None


def context_breakdown_of(messages: Any, token_estimate: Any) -> list[dict[str, Any]]:
    """Where this request's tokens went, for the context panel. A number for a panel never stops a step."""
    from thomas.agent.context_breakdown import context_breakdown

    try:
        return context_breakdown(messages, int(token_estimate or 0))
    except (TypeError, ValueError, KeyError, AttributeError):
        return []
