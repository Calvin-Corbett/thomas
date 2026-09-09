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
from thomas.agent.verification_contract import VerificationPlan, plan_for, verification_contract_enabled
from thomas.core import acceptance_contract as ac
from thomas.core.acceptance_learning import load_learned, record_misses

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


def begin_contract(loop: Any, *, prompt_text: str, route_path: str, attempt: int = 0) -> str:
    """Build the contract and return the block to put in front of the model as turn
    context ('' when there is nothing to hold the run to). Never touches the prompt."""

    try:
        if not verification_contract_enabled() or str(route_path or "") in LOW_INTENT_ROUTES:
            return ""
        if attempt > 0 and _state(loop):
            return ""  # a remediation pass keeps the contract it was built with
        plan = plan_for(effort_level(loop))
        if not plan.build_acceptance:
            return ""
        workspace = Path(os.getcwd())
        try:
            learned = load_learned(workspace)
        except _CONTRACT_ERRORS as exc:  # a broken record must not stop the contract
            log.debug("acceptance: learned checks unavailable: %s", exc)
            learned = []
        items = ac.build_contract(prompt_text, workspace, learned=learned)
        if ac.is_trivial(items):
            return ""  # a turn that names no output, data, command or requirement has nothing to check
        state: dict[str, Any] = {
            "items": items,
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
        return ac.contract_prompt_block(items, require_finish=plan.run_checks and ac.needs_finish(items))
    except _CONTRACT_ERRORS as exc:  # the contract never takes the run down
        log.warning("acceptance: begin_contract failed: %s", exc)
        return ""


async def _evaluate(
    loop: Any,
    state: dict[str, Any],
    plan: VerificationPlan,
    *,
    response_text: str,
    tool_events: Sequence[dict[str, Any]],
) -> tuple[list[ac.ContractItem], dict[str, Any] | None]:
    """Machine checks in the workspace, then the separate evaluator at xhigh+."""

    workspace = Path(str(state.get("workspace") or os.getcwd()))
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
        gaps = ac.remediation_prompt(evaluated).split("\n", 1)[-1]
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
            workspace = str(state.get("workspace") or os.getcwd())
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
    "effort_level",
    "finish_contract",
    "hold_at_finish",
    "settle_contract",
]
