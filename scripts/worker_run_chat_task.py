#!/usr/bin/env python3
"""Execute a task-bot chat request through Thomas's tools specialist.

This is the generic background worker for chat-dispatched tasks. It reuses the
same tools specialist Thomas already uses inline, but runs it under the
task-manager workflow so Mission Control and the chat task strip can reflect
real background execution.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import worker_run_chat_task_policy as _task_policy  # noqa: E402
from thomas.agent.approval import ApprovalBroker  # noqa: E402
from thomas.agent.guarded_tools import GuardedToolRunner  # noqa: E402
from thomas.agent.loop import AgentLoop  # noqa: E402
from thomas.agent.skills_runtime import format_runtime_skills_context, resolve_runtime_skills  # noqa: E402
from thomas.chat.session_store import SessionStore  # noqa: E402
from thomas.core import task_bot_runtime  # noqa: E402
from thomas.core.config import load_config  # noqa: E402
from thomas.core.events import EventType  # noqa: E402
from thomas.core.llm import LLMClient  # noqa: E402
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract  # noqa: E402
from thomas.marketplace.policy.config import load_policy_config  # noqa: E402
from thomas.marketplace.policy.policy import PolicyEngine  # noqa: E402
from thomas.marketplace.policy.redact import Redactor  # noqa: E402
from thomas.marketplace.specialists.tools import ToolSpecialist  # noqa: E402
from thomas.server.app_helpers import _build_tools  # noqa: E402

_apply_task_policy_prompt = _task_policy._apply_task_policy_prompt
_background_execution_guidance = _task_policy._background_execution_guidance
_base_prompt = _task_policy._base_prompt
_legacy_task_execution_policy = _task_policy._legacy_task_execution_policy
_policy_from_capability_class = _task_policy._policy_from_capability_class
_resolve_task_execution_policy = _task_policy._resolve_task_execution_policy
_should_waive_dirty_worktree_for_artifact_task = _task_policy._should_waive_dirty_worktree_for_artifact_task
_task_policy_mismatch_reason = _task_policy._task_policy_mismatch_reason

DEFAULT_ENGINE = "specialist"
GUARDED_LOOP_ENGINE = "guarded_loop"
_GUARDED_LOOP_CAPABILITY_CLASSES = {"default", "repo_edit_green_only", "repo_edit_private_checkpointable"}


def _session_id_for(record: dict[str, Any]) -> str:
    return str(record.get("session_id") or record.get("conversation_id") or record.get("thread_id") or "").strip()


async def _load_conversation_context(config: Any, session_id: str) -> list[dict[str, Any]]:
    if not session_id:
        return []
    store = SessionStore(config.memory.root_path / ".thomas" / "sessions_v2")
    conversation = await store.load(session_id)
    if conversation is None:
        return []
    return [msg for msg in conversation.last_n(8) if msg.get("role") != "system"]


def _resolve_task_runtime_skills_context(config: Any, prompt: str) -> str:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return ""
    try:
        selection = resolve_runtime_skills(
            config,
            prompt_text=prompt_text,
            relevance_text=prompt_text,
            route_path="task_manager_background_dispatch",
            cwd=ROOT,
        )
    except (OSError, RuntimeError, ValueError):
        return ""
    return format_runtime_skills_context(selection)


def _progress_text_for_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    if event_type == "thinking":
        return str(event.get("text") or "Thinking about the task...").strip()
    if event_type == "tool_start":
        name = str(event.get("name") or "tool").strip()
        return f"Starting {name}..."
    if event_type == "tool_result":
        name = str(event.get("name") or "tool").strip()
        ok = bool(event.get("ok"))
        result = str(event.get("result") or "").strip()
        if result:
            result = result.splitlines()[0].strip()
            result = result[:220]
        status = "completed" if ok else "failed"
        return f"{name} {status}{': ' + result if result else ''}"
    if event_type == "text":
        return str(event.get("text") or "").strip()
    if event_type == "done":
        return str(event.get("content") or "").strip()
    if event_type == "error":
        return str(event.get("error") or "Worker task failed").strip()
    return ""


def _normalize_engine_name(value: str | None) -> str:
    engine = str(value or DEFAULT_ENGINE).strip().lower().replace("-", "_")
    return GUARDED_LOOP_ENGINE if engine == GUARDED_LOOP_ENGINE else DEFAULT_ENGINE


def _build_guarded_runner(config: Any, tools: Any) -> GuardedToolRunner:
    policy_cfg = load_policy_config(str(config.memory.root_path))
    tool_categories = {
        str(tool.name): str(tool.category)
        for tool in list(tools.list_tools())
        if getattr(tool, "name", None) and getattr(tool, "category", None)
    }
    policy = PolicyEngine.from_config(policy_cfg, tool_categories=tool_categories)
    return GuardedToolRunner(
        policy=policy,
        approvals=ApprovalBroker(),
        redactor=Redactor(additional_patterns=policy_cfg.redact_additional_patterns),
        approval_timeout_s=policy_cfg.guardrails.approval_timeout_s,
        no_human_mode=policy_cfg.guardrails.no_human_mode,
    )


def _progress_text_for_agent_event(event: Any) -> str:
    if getattr(event, "type", None) == EventType.THINKING:
        return str(event.data.get("text") or "Thinking about the task...").strip()
    if getattr(event, "type", None) in {EventType.TOOL_CALL_START, EventType.TOOL_START}:
        name = str(event.data.get("tool_name") or event.data.get("name") or "tool").strip()
        return f"Starting {name}..."
    if getattr(event, "type", None) == EventType.TOOL_RESULT:
        name = str(event.data.get("tool_name") or "tool").strip()
        ok = bool(event.data.get("ok"))
        result = str(event.data.get("result") or "").strip()
        if result:
            result = result.splitlines()[0].strip()[:220]
        status = "completed" if ok else "failed"
        return f"{name} {status}{': ' + result if result else ''}"
    if getattr(event, "type", None) == EventType.TEXT_DELTA:
        return str(event.data.get("text") or "").strip()
    if getattr(event, "type", None) == EventType.AGENT_DONE:
        return str(event.data.get("text") or "").strip()
    if getattr(event, "type", None) == EventType.AGENT_ERROR:
        return str(event.data.get("error") or "Worker task failed").strip()
    if getattr(event, "type", None) == EventType.AGENT_END:
        reason = str(event.data.get("reason") or "").strip()
        if reason:
            return f"Task ended: {reason}"
    return ""


def _should_use_guarded_loop(task_policy: Any, engine: str) -> bool:
    if _normalize_engine_name(engine) != GUARDED_LOOP_ENGINE:
        return False
    capability_class = str(getattr(task_policy, "capability_class", "") or "").strip().lower()
    return capability_class in _GUARDED_LOOP_CAPABILITY_CLASSES


def _build_agent_loop_prompt(base_prompt: str, task_policy: Any) -> str:
    guided_prompt = _apply_task_policy_prompt(base_prompt, task_policy)
    guidance = _background_execution_guidance(base_prompt, policy=task_policy)
    if guidance:
        return f"{guidance}\n\n{guided_prompt}".strip()
    return guided_prompt


async def _run_task_with_guarded_loop(
    *,
    config: Any,
    session_id: str,
    execution_id: str,
    worker_agent: str,
    prompt: str,
    conversation_context: list[dict[str, Any]],
) -> str:
    profile = str(getattr(config, "default_model", "") or "").strip()
    if not profile:
        raise RuntimeError("Thomas has no default model configured")
    model_cfg = config.get_model(profile) if hasattr(config, "get_model") else config.models[profile]
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    tools = _build_tools(config)
    guarded_runner = _build_guarded_runner(config, tools)
    run_id = execution_id or f"task-bot:{worker_agent}:{int(time.time())}"
    agent = AgentLoop(
        config=config,
        llm=llm,
        tools=tools,
        conversation=conversation_context,
        thread_id=session_id or "task-bot",
        session_id=session_id or "task-bot",
        run_id=run_id,
        guarded_tool_runner=guarded_runner,
        autonomy_level=4,
    )

    final_text = ""
    streamed_parts: list[str] = []
    try:
        async for event in agent.run(
            prompt,
            mode="auto",
            tools_policy="auto",
            job_type="task_execution",
            max_iterations=10,
        ):
            progress_text = _progress_text_for_agent_event(event)
            if progress_text and execution_id:
                with contextlib.suppress(Exception):
                    task_bot_runtime.update_execution(
                        execution_id,
                        state="executing",
                        claimed_owner=worker_agent,
                        progress_summary=progress_text,
                        actor=worker_agent,
                        repo_root=ROOT,
                        force=True,
                    )
            if event.type == EventType.TEXT_DELTA:
                delta = str(event.data.get("text") or "")
                if delta:
                    streamed_parts.append(delta)
            elif event.type == EventType.AGENT_DONE:
                final_text = str(event.data.get("text") or "").strip()
                break
            elif event.type == EventType.AGENT_ERROR:
                raise RuntimeError(str(event.data.get("error") or "Worker task failed"))
    finally:
        with contextlib.suppress(Exception):
            await llm.close()

    final_text = final_text.strip() or "".join(streamed_parts).strip()
    if not final_text:
        raise RuntimeError("Agent loop returned no final output")
    return final_text


async def _run_task_with_specialist(
    *,
    config: Any,
    session_id: str,
    execution_id: str,
    worker_agent: str,
    base_prompt: str,
    prompt: str,
    task_policy: Any,
    conversation_context: list[dict[str, Any]],
) -> str:
    profile = str(getattr(config, "default_model", "") or "").strip()
    if not profile:
        raise RuntimeError("Thomas has no default model configured")
    model_cfg = config.get_model(profile) if hasattr(config, "get_model") else config.models[profile]
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    specialist = ToolSpecialist(config, llm, _build_tools(config))
    contract = DelegationContract(
        specialist_id="tools",
        task_description=prompt,
        timeout_seconds=120,
        max_iterations=10,
    )
    token = CapabilityToken(
        specialist_id="tools",
        session_id=session_id,
        allowed_actions=set(task_policy.allowed_actions),
        autonomy_level=4,
    )
    memory_parts = [
        _background_execution_guidance(base_prompt, policy=task_policy),
        _resolve_task_runtime_skills_context(config, base_prompt),
    ]
    memory_context = "\n\n".join(part for part in memory_parts if str(part or "").strip())

    final_text = ""
    try:
        async for event in specialist.execute(contract, token, prompt, conversation_context, memory_context):
            event_type = str(event.get("type") or "")
            progress_text = _progress_text_for_event(event)
            if progress_text and execution_id:
                with contextlib.suppress(Exception):
                    task_bot_runtime.update_execution(
                        execution_id,
                        state="executing",
                        claimed_owner=worker_agent,
                        progress_summary=progress_text,
                        actor=worker_agent,
                        repo_root=ROOT,
                        force=True,
                    )
            if event_type == "text":
                final_text = progress_text or final_text
            elif event_type == "done":
                final_text = progress_text or final_text
                break
            elif event_type == "error":
                raise RuntimeError(progress_text or "Worker task failed")
    finally:
        with contextlib.suppress(Exception):
            await llm.close()

    final_text = final_text.strip()
    if not final_text:
        raise RuntimeError("Tools specialist returned no final output")
    return final_text


async def _run_task(task_id: str, *, worker_agent: str, engine: str = DEFAULT_ENGINE) -> str:
    record = task_bot_runtime.find_by_task_id(task_id, repo_root=ROOT)
    if not isinstance(record, dict):
        raise FileNotFoundError(f"Task-bot execution not found for task_id={task_id}")

    execution_id = str(record.get("execution_id") or "").strip()
    session_id = _session_id_for(record)
    base_prompt = _base_prompt(record)
    task_policy = _resolve_task_execution_policy(record, base_prompt)
    mismatch_reason = _task_policy_mismatch_reason(base_prompt, task_policy)
    if mismatch_reason:
        raise RuntimeError(f"task policy mismatch: {mismatch_reason}")
    prompt = _apply_task_policy_prompt(base_prompt, task_policy)

    config = load_config()
    conversation_context = await _load_conversation_context(config, session_id)

    if _should_use_guarded_loop(task_policy, engine):
        final_text = await _run_task_with_guarded_loop(
            config=config,
            session_id=session_id,
            execution_id=execution_id,
            worker_agent=worker_agent,
            prompt=_build_agent_loop_prompt(base_prompt, task_policy),
            conversation_context=conversation_context,
        )
    else:
        final_text = await _run_task_with_specialist(
            config=config,
            session_id=session_id,
            execution_id=execution_id,
            worker_agent=worker_agent,
            base_prompt=base_prompt,
            prompt=prompt,
            task_policy=task_policy,
            conversation_context=conversation_context,
        )

    if execution_id:
        task_bot_runtime.update_execution(
            execution_id,
            state="executing",
            claimed_owner=worker_agent,
            progress_summary=final_text,
            actor=worker_agent,
            repo_root=ROOT,
            force=True,
        )
    return final_text


def execute_task_sync(
    task_id: str,
    *,
    worker_agent: str,
    engine: str = DEFAULT_ENGINE,
    emit_stdout: bool = False,
) -> str:
    final_text = asyncio.run(_run_task(task_id, worker_agent=worker_agent, engine=engine))
    if emit_stdout:
        print(final_text)
    return final_text


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a chat-dispatched task through Thomas's tools specialist.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--worker-agent", default="thomas-chat-worker")
    parser.add_argument("--engine", default=DEFAULT_ENGINE, choices=[DEFAULT_ENGINE, GUARDED_LOOP_ENGINE])
    args = parser.parse_args(argv)
    try:
        execute_task_sync(
            str(args.task_id),
            worker_agent=str(args.worker_agent or "thomas-chat-worker"),
            engine=str(args.engine or DEFAULT_ENGINE),
            emit_stdout=True,
        )
        return 0
    except (OSError, RuntimeError, ValueError, TimeoutError, asyncio.TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
