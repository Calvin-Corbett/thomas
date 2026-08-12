"""Shared helpers for web chat plan mode."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from thomas.agent.execution_plan import (
    ExecutionPlan,
    PlanStep,
    coerce_plan_status,
    default_allowed_decisions,
    new_plan_id,
    plan_to_markdown,
    plan_to_payload,
)
from thomas.agent.loop import AgentLoop
from thomas.core.events import EventType

SendEventFn = Callable[[dict[str, Any]], Awaitable[None]]

_PLAN_ACTIONS = {"approve", "refine", "reject"}
_WEB_SHARED_SLASH_COMMANDS = {"/plan", "/model", "/status", "/clear", "/export", "/help"}


def normalize_conversation_mode(raw: Any) -> str:
    mode = str(raw or "default").strip().lower()
    if mode in {"plan", "default"}:
        return mode
    return "default"


def normalize_plan_action(raw: Any) -> str:
    action = str(raw or "").strip().lower()
    if action in _PLAN_ACTIONS:
        return action
    return ""


def serialize_web_slash_specs() -> list[dict[str, Any]]:
    # Imported here, not at module scope: thomas.cli.repl_slash pulls in
    # prompt_toolkit (~580ms), and the web server was paying that on every boot
    # for a CLI dependency only this one function needs.
    from thomas.cli.repl_slash import list_slash_specs

    specs: list[dict[str, Any]] = []
    for spec in list_slash_specs():
        command = str(getattr(spec, "command", "") or "").strip().lower()
        if command not in _WEB_SHARED_SLASH_COMMANDS:
            continue
        specs.append(
            {
                "cmd": command,
                "desc": str(getattr(spec, "summary", "") or "").strip(),
                "usage": str(getattr(spec, "usage", "") or "").strip(),
                "modeId": "plan" if command == "/plan" else "",
                "webAction": command.lstrip("/"),
            }
        )
    return specs


async def _run_agent_capture(
    prompt: str,
    *,
    config: Any,
    llm: Any,
    tools: Any,
    conversation: list[dict[str, Any]],
    memory: Any,
    thread_id: str,
    run_id: str,
    session_id: str,
    system_prompt: str | None,
    autonomy_level: int,
    mode: str,
    tools_policy: str,
    send_event: SendEventFn | None,
    forward_text: bool,
    forward_tools: bool,
) -> str:
    agent = AgentLoop(
        config,
        llm,
        tools,
        system_prompt=system_prompt,
        conversation=conversation,
        memory=memory,
        thread_id=thread_id,
        run_id=run_id,
        session_id=session_id,
        autonomy_level=autonomy_level,
    )
    chunks: list[str] = []
    tool_args_by_id: dict[str, str] = {}
    async for event in agent.run(
        prompt,
        mode=mode,
        tools_policy=tools_policy,
        token_economy="optimal",
    ):
        if event.type == EventType.THINKING and send_event is not None:
            text = str(event.data.get("text") or "")
            if text:
                await send_event({"type": "thinking", "text": text})
            continue
        if event.type == EventType.TEXT_DELTA:
            text = str(event.data.get("text") or "")
            if not text:
                continue
            chunks.append(text)
            if forward_text and send_event is not None:
                await send_event({"type": "text", "text": text})
            continue
        if event.type == EventType.TOOL_CALL_START and forward_tools and send_event is not None:
            await send_event(
                {
                    "type": "tool_start",
                    "id": str(event.data.get("tool_id") or ""),
                    "name": str(event.data.get("tool_name") or ""),
                }
            )
            continue
        if event.type == EventType.TOOL_CALL_ARGS_DELTA and forward_tools and send_event is not None:
            tool_id = str(event.data.get("tool_id") or "")
            delta = str(event.data.get("delta") or "")
            tool_args_by_id[tool_id] = f"{tool_args_by_id.get(tool_id, '')}{delta}"
            await send_event(
                {
                    "type": "tool_args",
                    "id": tool_id,
                    "delta": delta,
                    "args": tool_args_by_id[tool_id],
                }
            )
            continue
        if event.type == EventType.TOOL_RESULT and forward_tools and send_event is not None:
            await send_event(
                {
                    "type": "tool_result",
                    "id": str(event.data.get("tool_id") or ""),
                    "name": str(event.data.get("tool_name") or ""),
                    "ok": bool(event.data.get("ok", False)),
                    "ms": float(event.data.get("duration_ms", 0.0) or 0.0),
                    "result": event.data.get("result", ""),
                }
            )
            continue
        if event.type == EventType.AGENT_ERROR:
            raise RuntimeError(str(event.data.get("error") or "Plan execution failed."))
        if event.type == EventType.AGENT_END:
            raise RuntimeError(str(event.data.get("message") or event.data.get("reason") or "Plan execution ended."))
        if event.type == EventType.AGENT_DONE:
            final = str(event.data.get("text") or "").strip()
            if final:
                return final
    return "".join(chunks).strip()


def build_plan_payload(plan: ExecutionPlan) -> dict[str, Any]:
    payload = plan_to_payload(plan)
    payload["status"] = coerce_plan_status(payload.get("status"))
    payload["allowed_decisions"] = default_allowed_decisions(plan)
    return payload


async def draft_plan(
    task_description: str,
    *,
    config: Any,
    llm: Any,
    tools: Any,
    conversation: list[dict[str, Any]],
    memory: Any,
    session_id: str,
    system_prompt: str | None,
    send_event: SendEventFn | None = None,
) -> tuple[ExecutionPlan, str]:
    """Ask the model for a plan preview without turning its prose into actions.

    This compatibility path has no structured plan-submission tool.  Until it
    does, model text is display-only and the executable plan remains empty.
    """
    task = str(task_description or "").strip()
    plan = ExecutionPlan(plan_id=new_plan_id(), task_description=task or "Planned task")
    prompt = (
        f"Create a detailed implementation plan for: {plan.task_description}\n\n"
        "Format the response as a numbered list of concrete steps. "
        "Keep each step actionable and specific."
    )
    response = await _run_agent_capture(
        prompt,
        config=config,
        llm=llm,
        tools=tools,
        conversation=conversation,
        memory=memory,
        thread_id=f"{session_id}-{plan.plan_id}",
        run_id=plan.plan_id,
        session_id=session_id,
        system_prompt=system_prompt,
        autonomy_level=1,
        mode="thinking",
        tools_policy="never",
        send_event=send_event,
        forward_text=False,
        forward_tools=False,
    )
    return plan, response


async def refine_plan(
    current_plan: ExecutionPlan,
    refinement_note: str,
    *,
    config: Any,
    llm: Any,
    tools: Any,
    conversation: list[dict[str, Any]],
    memory: Any,
    session_id: str,
    system_prompt: str | None,
    send_event: SendEventFn | None = None,
) -> tuple[ExecutionPlan, str]:
    """Ask for a revised preview while keeping model prose non-executable."""
    note = str(refinement_note or "").strip()
    prompt = (
        f"Revise this plan for the task: {current_plan.task_description}\n\n"
        f"Current plan:\n{plan_to_markdown(current_plan)}\n\n"
        f"User feedback: {note}\n\n"
        "Return only a numbered list of revised concrete steps."
    )
    response = await _run_agent_capture(
        prompt,
        config=config,
        llm=llm,
        tools=tools,
        conversation=conversation,
        memory=memory,
        thread_id=f"{session_id}-{current_plan.plan_id}-refine",
        run_id=f"{current_plan.plan_id}-refine",
        session_id=session_id,
        system_prompt=system_prompt,
        autonomy_level=1,
        mode="thinking",
        tools_policy="never",
        send_event=send_event,
        forward_text=False,
        forward_tools=False,
    )
    # A prose refinement cannot preserve or create executable steps.  Clearing
    # them fails inertly instead of leaving an older plan executable after the
    # model described a different one.
    current_plan.steps = []
    current_plan.status = "draft"
    current_plan.note = note
    current_plan.last_result = ""
    current_plan.finished_at = 0.0
    return current_plan, response


def build_execution_prompt(
    plan: ExecutionPlan,
    step: PlanStep,
    step_index: int,
    total_steps: int,
    prior_results: list[str],
) -> str:
    prior_text = "\n".join(f"- {item}" for item in prior_results if str(item).strip())
    if not prior_text:
        prior_text = "- None yet."
    return (
        f"Execute approved plan step {step_index} of {total_steps}.\n\n"
        f"Task: {plan.task_description}\n\n"
        f"Full plan:\n{plan_to_markdown(plan)}\n\n"
        f"Completed step results:\n{prior_text}\n\n"
        f"Current step: {step.description}\n\n"
        "Perform the work needed for this step. Use tools when required. "
        "Return a concise execution update with concrete outcomes."
    )


async def execute_plan(
    plan: ExecutionPlan,
    *,
    config: Any,
    llm: Any,
    tools: Any,
    conversation: list[dict[str, Any]],
    memory: Any,
    session_id: str,
    system_prompt: str | None,
    send_event: SendEventFn | None = None,
) -> tuple[ExecutionPlan, str]:
    outputs: list[str] = []
    prior_results: list[str] = []
    executable_steps = [step for step in plan.steps if step.status != "skipped"]
    total_steps = len(executable_steps)
    if total_steps == 0:
        plan.status = "draft"
        plan.last_result = "No structured executable plan steps were provided."
        if send_event is not None:
            await send_event({"type": "plan_state", "plan": build_plan_payload(plan)})
        return plan, f"{plan.last_result} Nothing was run."
    plan.status = "executing"
    if send_event is not None:
        await send_event({"type": "plan_state", "plan": build_plan_payload(plan)})
    for index, step in enumerate(plan.steps, 1):
        if step.status == "skipped":
            continue
        step.status = "running"
        if send_event is not None:
            await send_event({"type": "plan_state", "plan": build_plan_payload(plan)})
            await send_event(
                {
                    "type": "thinking",
                    "text": f"Executing step {len(prior_results) + 1} of {total_steps}: {step.description}\n",
                }
            )
        try:
            step_output = await _run_agent_capture(
                build_execution_prompt(plan, step, len(prior_results) + 1, total_steps, prior_results),
                config=config,
                llm=llm,
                tools=tools,
                conversation=list(conversation),
                memory=memory,
                thread_id=f"{session_id}-{plan.plan_id}-step-{index}",
                run_id=f"{plan.plan_id}-step-{index}",
                session_id=session_id,
                system_prompt=system_prompt,
                autonomy_level=3,
                mode="auto",
                tools_policy="auto",
                send_event=send_event,
                forward_text=True,
                forward_tools=True,
            )
            step.status = "done"
            step.result = step_output.strip()
            plan.last_result = step.result[:400]
            if step.result:
                prior_results.append(f"Step {len(prior_results) + 1}: {step.result[:240]}")
            outputs.append(
                f"### Step {len(outputs) + 1}: {step.description}\n\n{step_output.strip() or '_Completed without a textual summary._'}"
            )
        except Exception as exc:
            step.status = "error"
            step.result = str(exc)
            plan.last_result = step.result[:400]
            outputs.append(f"### Step {len(outputs) + 1}: {step.description}\n\n**Error:** {step.result}")
            if send_event is not None:
                await send_event({"type": "thinking", "text": f"Step failed: {step.result}\n"})
            break
        if send_event is not None:
            await send_event({"type": "plan_state", "plan": build_plan_payload(plan)})
    plan.status = "done"
    plan.finished_at = time.time()
    if send_event is not None:
        await send_event({"type": "plan_state", "plan": build_plan_payload(plan)})
    return plan, "\n\n".join(outputs).strip() or "Plan execution complete."
