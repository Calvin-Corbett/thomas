"""Glue between the agent loop and the acceptance contract.

Four moments: ``begin_contract`` before the first model call (build the list,
put it in front of the model, start the clock); ``hold_at_finish`` every time
the model replies without a tool call - a text reply is never "done": the
contract is checked in the workspace and, while a checked item fails and a
revision round remains, the gaps go back to the model as the next user turn
of the SAME loop (what NOOA's synthetic return_result and deep-agents' grader
feedback both do); ``settle_contract`` after the loop ends (final verdict,
evaluator at xhigh+); ``finish_contract`` once the run ends (record misses,
restore the slider). Every step is wrapped so a contract failure can never
take the run down with it.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from thomas.agent.acceptance_evaluator import evaluate_with_model
from thomas.agent.sandboxed_runners import contract_runner
from thomas.agent.verification_contract import VerificationPlan, plan_for, verification_contract_enabled
from thomas.core import acceptance_contract as ac
from thomas.core.acceptance_compact_block import compact_contract_prompt_blocks, repair_gaps
from thomas.core.acceptance_learning import load_learned, record_misses
from thomas.core.tokens import estimate_message_tokens, estimate_messages_tokens

log = logging.getLogger(__name__)

_ATTR = "_acceptance_state"
LOW_INTENT_ROUTES = frozenset({"casual_chat", "personal_context", "assistant_meta", "general"})
# Everything the contract's own file, regex, subprocess and record handling can raise. The
# contract must never take a run down, but it reports the outage rather than faking a verdict.
_CONTRACT_ERRORS = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    RuntimeError,
    subprocess.SubprocessError,
    re.error,
)

NOT_FINISHED = (
    "Status: commentary only - the task is NOT finished. Your reply was checked against the "
    "acceptance contract in the workspace and these items do not hold:"
)


@dataclass
class Settlement:
    payload: dict[str, Any]
    blocking: bool = False
    remediation: str = ""
    trailer: str = ""
    items: list[ac.ContractItem] = field(default_factory=list)


def _state(loop: Any) -> dict[str, Any] | None:
    state = getattr(loop, _ATTR, None)
    return state if isinstance(state, dict) else None


def _config(loop: Any) -> Any:
    return getattr(getattr(loop, "llm", None), "config", None)


def effort_level(loop: Any) -> str:
    """The slider as the user set it - not the phase override the sandwich applies."""

    state = _state(loop)
    if state and state.get("effort_original") is not None:
        return str(state["effort_original"])
    return str(getattr(_config(loop), "reasoning_effort", "") or "")


def _set_effort(loop: Any, value: str | None) -> None:
    cfg = _config(loop)
    if cfg is None or value is None:
        return
    try:
        cfg.reasoning_effort = value
    except (AttributeError, TypeError, ValueError) as exc:  # a frozen config just means no sandwich
        log.debug("acceptance: cannot set reasoning_effort: %s", exc)


def verification_workspace(loop: Any) -> Path:
    """Private builders use their tool sandbox; other callers retain cwd semantics."""
    if bool(getattr(loop, "verify_in_tool_workspace", False)):
        return Path(loop.config.tools.sandbox_path).resolve()
    return Path.cwd()


def begin_contract(loop: Any, *, prompt_text: str, route_path: str, attempt: int = 0) -> str:
    """Build the contract and return the block to put in front of the model as turn
    context ('' when there is nothing to hold the run to). Never touches the prompt."""

    try:
        if not verification_contract_enabled() or str(route_path or "") in LOW_INTENT_ROUTES:
            return ""
        if attempt > 0:
            # A remediation pass keeps the contract its first pass built, and never builds one: its prompt is
            # Thomas's own "Quality gate failed" message, whose guard command became a check that must exit 0
            # when the first pass had nothing to check (2026-09-27).
            return ""
        plan = plan_for(effort_level(loop))
        if not plan.build_acceptance:
            return ""
        workspace = verification_workspace(loop)
        try:
            learned = load_learned(workspace)
        except _CONTRACT_ERRORS as exc:  # a broken record must not stop the contract
            log.debug("acceptance: learned checks unavailable: %s", exc)
            learned = []
        if not plan.separate_evaluator:  # below xhigh no judge checks a goal: it would only be listed as unchecked
            learned = [row for row in learned if row.get("source") != "goal"]
        owned_output = (
            getattr(loop, "acceptance_owned_output", None) if getattr(loop, "verify_in_tool_workspace", False) else None
        )
        items = ac.build_contract(prompt_text, workspace, learned=learned, owned_output=owned_output)
        if ac.is_trivial(items):
            return ""  # a turn that names no output, data, command or requirement has nothing to check
        require_finish = plan.run_checks and ac.needs_finish(items)
        state: dict[str, Any] = {
            "items": items,
            "block": (list(items), require_finish),  # what the block lists; ``items`` becomes the verdicts
            "started_at": ac.now(),
            "level": plan.level,
            "workspace": str(workspace),
            "prompt_text": str(prompt_text or ""),
            "first_unmet": None,
            "rounds": 0,
            "effort_original": str(getattr(_config(loop), "reasoning_effort", "") or ""),
        }
        setattr(loop, _ATTR, state)
        if plan.reasoning_sandwich:
            _set_effort(loop, plan.reasoning_sandwich[1])  # build phase runs at the middle setting
        return ac.contract_prompt_block(items, require_finish=require_finish)
    except _CONTRACT_ERRORS as exc:  # the contract never takes the run down
        log.warning("acceptance: begin_contract failed: %s", exc)
        return ""


def _pinned_texts(loop: Any) -> list[str]:
    """The text of your request and your amendments, which go out with every model call. Thomas's own steer (the
    last repair message) is left out: ``add_steering`` unpins it as soon as the next one arrives."""
    steer = getattr(loop, "_steering_anchor", None)
    texts: list[str] = []
    for message in getattr(loop, "_context_anchors", None) or ():
        if message is steer:
            continue
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            texts.append("\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict)))
        elif content:
            texts.append(str(content))
    return texts


def shorter_contract_blocks(loop: Any, whole_block: str) -> list[str]:
    """Shorter forms of the run's contract block, each repeating less of what a pinned message holds whole
    (``acceptance_compact_block``); none when there is no contract or nothing a pinned message carries."""

    state = _state(loop)
    if not state or not whole_block or "block" not in state:
        return []
    try:
        items, require_finish = state["block"]
        request = str(state.get("prompt_text") or "")
        return compact_contract_prompt_blocks(
            items, _pinned_texts(loop), request=request, require_finish=require_finish
        )
    except _CONTRACT_ERRORS as exc:  # the whole block still goes out; nothing is lost but room
        log.warning("acceptance: shorter_contract_blocks failed: %s", exc)
        return []


async def _evaluate(
    loop: Any,
    state: dict[str, Any],
    plan: VerificationPlan,
    *,
    response_text: str,
    tool_events: Sequence[dict[str, Any]],
) -> tuple[list[ac.ContractItem], dict[str, Any] | None]:
    """Machine checks in the workspace, then the separate evaluator at xhigh+."""

    workspace = Path(str(state.get("workspace") or verification_workspace(loop)))
    items = list(state["items"])
    if plan.run_checks and ac.needs_finish(items):
        items = ac.with_finish_items(items, response_text)  # the reply's own VERIFY command becomes a check
    evaluated = ac.evaluate_contract(
        items,
        workspace=workspace,
        tool_events=tool_events,
        response_text=response_text,
        started_at=float(state.get("started_at") or 0.0) or None,
        run_commands=bool(plan.run_checks),
        runner=contract_runner,
        command_timeout=600.0,  # a real verification run can take minutes; a false timeout is a false failure
    )
    evaluator_payload: dict[str, Any] | None = None
    if plan.separate_evaluator:
        if plan.reasoning_sandwich:
            _set_effort(loop, plan.reasoning_sandwich[2])  # verify phase at the top setting
        result = await evaluate_with_model(
            getattr(loop, "llm", None),
            task_text=str(state.get("prompt_text") or ""),
            response_text=response_text,
            items=evaluated,
            workspace=workspace,
            run_checks=bool(plan.evaluator_runs_checks),
            adversarial=bool(plan.adversarial),
        )
        if plan.reasoning_sandwich:
            _set_effort(loop, plan.reasoning_sandwich[1])
        evaluator_payload = result.to_payload()
        if result.available:
            evaluated = result.items
    if state.get("first_unmet") is None:
        state["first_unmet"] = [it for it in evaluated if it.checked and not it.satisfied]
    state["items"] = evaluated
    state["evaluator"] = evaluator_payload
    return evaluated, evaluator_payload


async def hold_at_finish(loop: Any, *, response_text: str, tool_events: Sequence[dict[str, Any]]) -> str:
    """The model replied without a tool call. Return the next user turn that keeps
    the loop going ('' when the contract holds, is off, or its rounds are spent)."""

    state = _state(loop)
    if not state:
        return ""
    try:
        plan = plan_for(str(state.get("level") or effort_level(loop)))
        if not plan.run_checks:
            return ""
        evaluated, _payload = await _evaluate(loop, state, plan, response_text=response_text, tool_events=tool_events)
        verdict = ac.contract_verdict(evaluated)
        if verdict.met or int(state.get("rounds") or 0) >= int(plan.retry_budget):
            return ""
        state["rounds"] = int(state.get("rounds") or 0) + 1
        from thomas.core.tokens import estimate_message_tokens

        opening = f"{NOT_FINISHED}\n"
        # The last call can contain old turns that the builder will drop on repair.
        # Reserve only its system, pinned turns and this run's tool exchange, then the
        # assistant reply and repair opening. Optional old conversation is not required.
        tool_specs = state.get("repair_tool_specs") or []
        request_budget = getattr(loop, "_request_message_budget", None)
        last_messages = state.get("last_request_messages")
        if callable(request_budget) and last_messages is not None:
            anchors = getattr(loop, "_context_anchors", None) or ()
            pinned_ids = {id(anchor) for anchor in anchors}
            conversation = getattr(loop, "_conversation", ())
            run_start = next(
                (index for index, message in enumerate(conversation) if anchors and message is anchors[0]),
                len(conversation),
            )
            current_run_ids = {id(message) for message in conversation[run_start:]}
            kept_ids = pinned_ids | current_run_ids
            required = [last_messages[0]] + [
                message for message in last_messages[1:] if id(message) in kept_ids or message.get("role") == "tool"
            ]
            limit = request_budget(tool_specs)
            room = limit - estimate_messages_tokens(required)
            room -= estimate_message_tokens({"role": "assistant", "content": response_text})
            room -= estimate_message_tokens({"role": "user", "content": opening})
        else:  # small loop stubs used outside the request builder
            room = int(getattr(loop, "_context_window", 0) or 0) // 4 or 10**6
        gaps = repair_gaps(
            evaluated,
            _pinned_texts(loop),
            request=str(state.get("prompt_text") or ""),
            budget_tokens=max(0, room),
        )
        return f"{NOT_FINISHED}\n{gaps}"
    except _CONTRACT_ERRORS as exc:  # never hold a run on the contract's own failure
        log.warning("acceptance: hold_at_finish failed: %s", exc)
        return ""


async def settle_contract(
    loop: Any,
    *,
    plan: VerificationPlan,
    prompt_text: str,
    response_text: str,
    tool_events: Sequence[dict[str, Any]],
    attempt: int = 0,
) -> Settlement:
    """The final verdict once the loop has ended. Revision rounds happen inside the
    loop (``hold_at_finish``); this only decides whether "done" holds and reports."""

    state = _state(loop)
    if not state:
        return Settlement(payload={"active": False})
    try:
        stop_message = getattr(loop, "_context_budget_stop", "")
        if stop_message:
            kept = list(state.get("items") or [])
            return Settlement(
                payload={
                    "active": True,
                    "level": plan.level,
                    "attempt": int(attempt),
                    "rounds": int(state.get("rounds") or 0),
                    "outcome": "context_budget_exhausted",
                    "recoverable": True,
                    "evaluated": False,
                    "reason": stop_message,
                    "items": ac.items_to_dicts(kept),
                    "evaluator": None,
                },
                blocking=bool(plan.run_checks),
                items=kept,
            )
        evaluated = state.get("items") or []
        evaluator_payload = state.get("evaluator")
        if not any(it.checked for it in evaluated):  # the loop ended without a finish check (error, cap)
            evaluated, evaluator_payload = await _evaluate(
                loop, state, plan, response_text=response_text, tool_events=tool_events
            )
        verdict = ac.contract_verdict(evaluated)
        blocking = bool(plan.run_checks) and not verdict.met
        payload = {
            "active": True,
            "level": plan.level,
            "attempt": int(attempt),
            "rounds": int(state.get("rounds") or 0),
            "verdict": verdict.to_payload(),
            "items": ac.items_to_dicts(evaluated),
            "evaluator": evaluator_payload,
        }
        return Settlement(
            payload=payload, blocking=blocking, trailer=ac.verification_trailer(evaluated), items=list(evaluated)
        )
    except _CONTRACT_ERRORS as exc:  # never fake a verdict; report the outage
        log.warning("acceptance: settle_contract failed: %s", exc)
        return Settlement(payload={"active": True, "error": f"{type(exc).__name__}: {exc}"})


def finish_contract(loop: Any, *, plan: VerificationPlan) -> None:
    """Record misses for the project (max only), restore the slider, forget the run."""

    state = _state(loop)
    if not state:
        return
    try:
        if plan.learn_from_misses and state.get("first_unmet"):
            final = {it.item_id: it for it in state.get("items") or []}
            caught = [
                it for it in state["first_unmet"] if final.get(it.item_id) is not None and final[it.item_id].satisfied
            ]
            caught_ids = {c.item_id for c in caught}
            escaped = [it for it in state["first_unmet"] if it.item_id not in caught_ids]
            workspace = str(state.get("workspace") or verification_workspace(loop))
            run_id = str(getattr(loop, "_run_id", "") or "")
            if caught:
                record_misses(workspace, caught, caught=True, run_id=run_id)
            if escaped:
                record_misses(workspace, escaped, caught=False, run_id=run_id)
    except _CONTRACT_ERRORS as exc:  # learning is best-effort
        log.warning("acceptance: recording misses failed: %s", exc)
    finally:
        if plan.reasoning_sandwich:
            _set_effort(loop, state.get("effort_original"))
        try:
            delattr(loop, _ATTR)
        except AttributeError:
            pass


__all__ = [
    "NOT_FINISHED",
    "Settlement",
    "begin_contract",
    "shorter_contract_blocks",
    "effort_level",
    "finish_contract",
    "hold_at_finish",
    "settle_contract",
]
