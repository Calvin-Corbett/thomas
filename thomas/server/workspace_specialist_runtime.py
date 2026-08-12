"""Chat V2 HTTP adapter for direct resident workspace specialists."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from thomas.chat.event_stream import EventDispatcher
from thomas.core.llm_shared import LLMError
from thomas.server.chat_budget_ledger import ChatBudgetError, ChatBudgetExceeded
from thomas.server.model_runtime_receipt import model_runtime_receipt
from thomas.server.routes.chat_v2_budget import prepare_chat_turn_budget, sync_chat_turn_budget
from thomas.server.routes.chat_v2_model import initialize_chat_v2_llm
from thomas.server.routes.chat_v2_run_store import ChatV2RunLifecycle, start_chat_v2_run
from thomas.server.routes.chat_v2_support import _evict_session_llm
from thomas.server.routes.chat_v2_ui_control import _chat_stream_headers
from thomas.server.routes.chat_v2_usage import UsageReceiptDispatcher
from thomas.server.workspace_specialist_operator import WorkspaceResidentOperator
from thomas.server.workspace_specialist_policy import (
    WORKSPACE_ACTION_POLICIES,
    workspace_key_from_context,
    workspace_tool_spec,
)
from thomas.server.workspace_specialist_turn import run_workspace_resident_turn

try:
    from thomas.server.app_keys import APP_GUARDED_TOOL_RUNNER, APP_GUARDRAILS_ENABLED, APP_TOOLS
except ImportError:  # pragma: no cover - compatibility with trimmed server builds
    APP_GUARDED_TOOL_RUNNER = APP_GUARDRAILS_ENABLED = APP_TOOLS = None  # type: ignore[assignment]

log = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkspaceChatRouteContext:
    sid: str
    context_id: str
    temporary: bool
    external_access: bool
    session_store: Any
    conversation: Any
    meta: Any
    app_config: Any
    runtime_policy: Any
    app_memory: Any
    requested_profile: str
    requested_model_id: str
    requested_reasoning_effort: str
    turn_mode: str
    turn_autonomy_level: int
    foreground_runtime_policy: Any
    token_economy_meta: dict[str, str]
    request_user_id: str
    prompt: str
    history_prompt: str
    image_data: list[dict[str, Any]]


def workspace_chat_route_context(
    identity: tuple[str, str, bool, bool],
    session: tuple[Any, Any, Any],
    runtime: tuple[Any, Any, Any],
    model: tuple[str, str, str],
    turn: tuple[str, int, Any, dict[str, str], str],
    prompt: tuple[str, str, list[dict[str, Any]]],
) -> WorkspaceChatRouteContext:
    """Build the typed adapter from explicit, related Chat V2 dependencies."""

    return WorkspaceChatRouteContext(*identity, *session, *runtime, *model, *turn, *prompt)


async def handle_workspace_chat_v2(
    request: web.Request, *, route_context: WorkspaceChatRouteContext
) -> web.StreamResponse:
    """Run a Chat V2-compatible workspace turn without general orchestration."""

    sid = route_context.sid
    context_id = route_context.context_id
    temporary = route_context.temporary
    external_access = route_context.external_access
    session_store = route_context.session_store
    conversation = route_context.conversation
    meta = route_context.meta
    app_config = route_context.app_config
    runtime_policy = route_context.runtime_policy
    requested_model_id = route_context.requested_model_id
    requested_reasoning_effort = route_context.requested_reasoning_effort
    turn_autonomy_level = route_context.turn_autonomy_level
    request_user_id = route_context.request_user_id
    try:
        llm, llm_lock, model_profile = await initialize_chat_v2_llm(
            request.app,
            config=app_config,
            runtime_policy=runtime_policy,
            session_id=sid,
            requested_model_id=requested_model_id,
            requested_reasoning_effort=requested_reasoning_effort,
        )
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        log.error("Failed to initialize workspace resident model policy", exc_info=True)
        return web.json_response({"error": "Workspace model policy could not be initialized"}, status=503)
    try:
        budget_ledger, budget_scope, _worker_policy = await prepare_chat_turn_budget(
            request.app,
            runtime_policy=runtime_policy,
            user_id=request_user_id,
            session_id=sid,
            prior_session_tokens=int(meta.token_spend or 0),
        )
    except ChatBudgetExceeded as exc:
        return web.json_response({"error": str(exc)}, status=429)
    except ChatBudgetError as exc:
        return web.json_response({"error": str(exc)}, status=503)

    response = web.StreamResponse(
        status=200,
        headers={
            **_chat_stream_headers(request),
            "X-Thomas-Temporary": "true" if temporary else "false",
            "X-Thomas-External-Access": "allowed" if external_access else "blocked",
            "X-Thomas-Workspace": workspace_key_from_context(context_id),
        },
    )
    await response.prepare(request)
    recorder = start_chat_v2_run(
        request.app,
        session_id=sid,
        profile=route_context.requested_profile,
        model_id=requested_model_id,
        mode="workspace",
        autonomy_level=turn_autonomy_level,
    )
    dispatcher = UsageReceiptDispatcher(
        EventDispatcher(response.write, run_id=recorder.run_id, event_sink=recorder.record),
        llm,
        prior_session_tokens=meta.token_spend,
        token_economy=route_context.token_economy_meta,
    )
    lifecycle = ChatV2RunLifecycle(recorder, usage=lambda: dispatcher.run_usage)
    run_ok = True
    workspace_key = workspace_key_from_context(context_id)
    await dispatcher.emit(
        {
            "type": "privacy_mode",
            "temporary": temporary,
            "retention": "none" if temporary else "session",
            "memory": "disabled" if route_context.app_memory is None else "enabled",
            "external_access": "allowed" if external_access else "blocked",
            "background_persistence": "blocked",
        }
    )
    await dispatcher.emit(
        {
            "type": "route",
            "route": {"path": "workspace_resident", "confidence": 1.0},
            "mode": route_context.turn_mode,
            "autonomy_level": turn_autonomy_level,
            "workspace": workspace_key,
            "token_economy": dict(route_context.token_economy_meta),
        }
    )

    tools = request.app.get(APP_TOOLS) if APP_TOOLS is not None else None
    guardrails_enabled = (
        bool(request.app.get(APP_GUARDRAILS_ENABLED, False))
        if APP_GUARDRAILS_ENABLED is not None
        else False
    )
    guarded_runner = (
        request.app.get(APP_GUARDED_TOOL_RUNNER)
        if guardrails_enabled and APP_GUARDED_TOOL_RUNNER is not None
        else None
    )
    operator = WorkspaceResidentOperator(
        app=request.app,
        context_id=context_id,
        tools=tools,
        guarded_runner=guarded_runner,
        config=app_config,
        session_id=sid,
        autonomy_level=turn_autonomy_level,
        user_prompt=route_context.prompt,
        emit_event=dispatcher.emit,
        user_id=request_user_id,
        tool_policy=runtime_policy.tools,
    )
    reset_trace = getattr(llm, "reset_runtime_trace", None)
    if callable(reset_trace):
        reset_trace()

    async def _run() -> Any:
        set_budget_scope = getattr(llm, "set_budget_scope", None)
        previous_scope = set_budget_scope(budget_scope) if callable(set_budget_scope) else None
        try:
            latest = None if temporary else await session_store.load(sid)
            active_conversation = latest if latest is not None else conversation
            return await run_workspace_resident_turn(
                llm=llm,
                conversation=active_conversation,
                prompt=route_context.prompt,
                history_prompt=route_context.history_prompt,
                session_id=sid,
                operator=operator,
                dispatcher=dispatcher,
                memory_engine=route_context.app_memory,
                memory_policy=getattr(route_context.foreground_runtime_policy, "memory", None),
                persistent_instructions=str(getattr(runtime_policy, "system_prompt", "") or ""),
                images=route_context.image_data,
            )
        finally:
            if callable(set_budget_scope):
                set_budget_scope(previous_scope)

    try:
        if llm_lock is not None:
            async with llm_lock:
                conversation = await _run()
        else:
            conversation = await _run()
        if not temporary:
            await session_store.save(sid, conversation, meta, force=True)
        await dispatcher.emit(
            {
                "type": "model_runtime",
                "runtime": model_runtime_receipt(
                    llm,
                    requested_profile=model_profile,
                    requested_model_id=requested_model_id,
                ),
            }
        )
    except (LLMError, ChatBudgetError, RuntimeError, ValueError, TypeError, OSError):
        run_ok = False
        log.exception("Workspace resident turn failed for session %s", sid[:12])
        await dispatcher.emit_error("Thomas could not complete this workspace turn safely.")
    try:
        try:
            await sync_chat_turn_budget(
                budget_ledger,
                scope=budget_scope,
                usage=dispatcher.run_usage,
                user_id=request_user_id,
                session_id=sid,
                meta=meta,
                session_store=session_store,
                conversation=conversation,
                temporary=temporary,
            )
        except ChatBudgetError:
            run_ok = False
            log.error("Workspace resident budget settlement failed for %s", sid[:12], exc_info=True)
            await dispatcher.emit_error("Token usage could not be recorded safely.")
        if temporary:
            await _evict_session_llm(request.app, sid)
        await response.write_eof()
    finally:
        lifecycle.finish(ok=run_ok)
    return response


__all__ = [
    "WORKSPACE_ACTION_POLICIES",
    "WorkspaceResidentOperator",
    "WorkspaceChatRouteContext",
    "handle_workspace_chat_v2",
    "run_workspace_resident_turn",
    "workspace_key_from_context",
    "workspace_chat_route_context",
    "workspace_tool_spec",
]
