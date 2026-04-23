"""Unified /api/v2/chat route.

Actionable requests acknowledge immediately and enter the task-manager
workflow. Conversational requests stay inline on this route.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import secrets
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.agent.chat_dispatcher import dispatch_async, is_task_manager_dispatch_ready
from thomas.agent.dispatch import should_dispatch
from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.session_store import SessionMeta, SessionStore
from thomas.core.llm import LLMClient
from thomas.marketplace.orchestrator.brain import OrchestratorBrain, _is_deterministic_tools_route
from thomas.marketplace.orchestrator.registry import SpecialistRegistry
from thomas.marketplace.specialists.coding import CodingSpecialist
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist
from thomas.marketplace.specialists.research import ResearchSpecialist
from thomas.marketplace.specialists.synthesis import SynthesisSpecialist
from thomas.marketplace.specialists.tools import ToolSpecialist
from thomas.server.chat_acknowledgment import stream_task_start_acknowledgment
from thomas.server.chat_delegation import (
    build_active_task_digest,
    session_active_delegations,
)
from thomas.server.routes.discord_channels_support import (
    append_discord_history_turn_if_needed,
    build_discord_request_context,
)
from thomas.tools.browser import shutdown_browser, warm_browser_session
from thomas.tools.voice import AudioData, VoiceBridge, VoiceProviderException

try:
    from thomas.server.app_keys import APP_CONFIG, APP_MEMORY, APP_TOOLS
except ImportError:
    APP_CONFIG = APP_MEMORY = APP_TOOLS = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

APP_SESSION_STORE = web.AppKey("chat_v2_session_store", SessionStore)
APP_SPECIALIST_REGISTRY = web.AppKey("chat_v2_specialist_registry", SpecialistRegistry)
APP_SESSION_LLM_CACHE = web.AppKey("chat_v2_session_llm_cache", dict)
APP_WARM_CODEX_POOL = web.AppKey("chat_v2_warm_codex_pool", dict)
APP_WARM_CODEX_TASKS = web.AppKey("chat_v2_warm_codex_tasks", dict)
APP_VOICE_BRIDGE = web.AppKey("chat_v2_voice_bridge", VoiceBridge)
APP_BROWSER_PREWARM_STATE = web.AppKey("chat_v2_browser_prewarm_state", dict)

_MAX_TRANSCRIBE_BYTES = 10 * 1024 * 1024


@dataclass
class _CachedSessionLLM:
    llm: Any
    signature: tuple[str, str, str, str, str]
    lock: asyncio.Lock


_BACKGROUND_REPLY_NOW_RE = (
    r"(?:answer|reply|respond)\s+(?:now|first|quickly|fast)"
    r"|(?:quick|fast)\s+(?:reply|answer|response)"
    r"|don't wait"
)
_BACKGROUND_DELEGATION_RE = (
    r"(?:background|delegate|delegation|parallel|while you work|in the background)"
    r"|(?:rest|deeper work|longer work)\s+(?:in|into)?\s*background"
)
_EXPLICIT_DELEGATION_RE = (
    r"(?:spawn|start|launch|run|use|create)\s+(?:exactly\s+|real\s+|live\s+|multiple\s+|few\s+|three\s+|four\s+|five\s+)*"
    r"(?:sub[- ]?agents?|agents?|helpers?|workers?)"
    r"|(?:delegate|delegation|parallel|multi-agent|multi agent|swarm)\b"
)
_INLINE_TOOL_REQUEST_RE = re.compile(
    r"(?:\buse\s+(?:your\s+)?(?:file|files|tool|tools)\b|"
    r"\b(?:file|files|tool|tools)\b.*\b(?:repo|repository|workspace|folder|directory|path)\b|"
    r"\btop[- ]level\s+files?\b|"
    r"\bcurrent\s+(?:repo|repository|workspace)\b|"
    r"\b(?:shell|command|directory listing|list files)\b)",
    re.I,
)


def _requests_reply_first_background(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    return bool(re.search(_BACKGROUND_REPLY_NOW_RE, text) and re.search(_BACKGROUND_DELEGATION_RE, text))


def _requests_explicit_delegation(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    return bool(re.search(_EXPLICIT_DELEGATION_RE, text))


def _requires_inline_tool_execution(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    return bool(_INLINE_TOOL_REQUEST_RE.search(text))


def _should_auto_background_actionable(
    prompt: str,
    *,
    mode: str,
    autonomy_level: int,
    recent_messages: list[dict[str, Any]] | None = None,
    active_tasks: list[dict[str, Any]] | None = None,
    requires_inline_tools: bool = False,
) -> bool:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode != "auto":
        return False
    if int(autonomy_level or 0) < 3:
        return False
    if requires_inline_tools:
        return False
    decision = should_dispatch(
        prompt,
        recent_messages=recent_messages,
        active_tasks=active_tasks,
        mode=normalized_mode,
    )
    return str(decision.action or "").strip().lower() == "dispatch"


_BACKGROUND_SPLIT_PATTERNS = (
    r"\bthen,?\s+in the background\b",
    r"\bin the background\b",
    r"\bwhile you work\b",
    r"\bdelegate the rest\b",
)


def _foreground_reply_prompt(prompt: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        return text
    cut_idx: int | None = None
    for pattern in _BACKGROUND_SPLIT_PATTERNS:
        match = re.search(pattern, text, re.I)
        if match:
            start = int(match.start())
            cut_idx = start if cut_idx is None else min(cut_idx, start)
    visible_prompt = text[:cut_idx].rstrip(" ,.;:") if cut_idx is not None else text
    if not visible_prompt:
        visible_prompt = text
    return (
        visible_prompt
        + "\n\n[Visible reply constraint]\n"
        + "Give only the immediate user-facing answer in one or two sentences. "
        + "Do not include the deferred background work, long-form deliverable, or any narration about delegation."
    )


def _uploaded_audio_format(filename: str = "", content_type: str = "") -> str:
    name = str(filename or "").strip().lower()
    mime = str(content_type or "").strip().lower()
    if "." in name:
        ext = name.rsplit(".", 1)[-1]
        if ext in {"wav", "wave", "mp3", "mpeg", "ogg", "oga", "flac", "webm", "m4a", "mp4"}:
            return "wav" if ext == "wave" else ("ogg" if ext == "oga" else ("mp3" if ext == "mpeg" else ext))
    if "webm" in mime:
        return "webm"
    if "ogg" in mime:
        return "ogg"
    if "mpeg" in mime or "mp3" in mime:
        return "mp3"
    if "flac" in mime:
        return "flac"
    if "mp4" in mime or "m4a" in mime:
        return "m4a"
    return "wav"


async def _voice_bridge_for_request(app: web.Application) -> VoiceBridge:
    bridge = app.get(APP_VOICE_BRIDGE)
    if isinstance(bridge, VoiceBridge):
        return bridge
    bridge = VoiceBridge()
    app[APP_VOICE_BRIDGE] = bridge
    return bridge


def _normalize_reasoning_effort(value: str) -> str:
    level = str(value or "").strip().lower()
    if level in {"low", "medium", "high", "xhigh"}:
        return level
    return ""


def _llm_signature(model_cfg: Any) -> tuple[str, str, str, str, str]:
    return (
        str(getattr(model_cfg, "provider", "") or "").strip().lower(),
        str(getattr(model_cfg, "base_url", "") or "").strip(),
        str(getattr(model_cfg, "api_key", "") or "").strip(),
        str(getattr(model_cfg, "api_key_header", "") or "").strip(),
        str(getattr(model_cfg, "api_key_prefix", "") or "").strip(),
    )


def _warm_codex_pool_key(model_cfg: Any) -> tuple[str, str, str, str, str, str]:
    return (
        str(getattr(model_cfg, "provider", "") or "").strip().lower(),
        str(getattr(model_cfg, "model", "") or "").strip(),
        str(getattr(model_cfg, "base_url", "") or "").strip(),
        str(getattr(model_cfg, "api_key", "") or "").strip(),
        str(getattr(model_cfg, "api_key_header", "") or "").strip(),
        str(getattr(model_cfg, "api_key_prefix", "") or "").strip(),
    )


def _is_codex_model_cfg(model_cfg: Any) -> bool:
    return str(getattr(model_cfg, "provider", "") or "").strip().lower() == "codex"


def _should_keep_inline_fast_lane(prompt: str) -> bool:
    return _is_deterministic_tools_route(prompt, ("tools",))


async def _warm_codex_provider(model_cfg: Any) -> Any:
    from thomas.marketplace.codex.provider import CodexProvider

    provider = CodexProvider(model_cfg)
    messages = [
        {
            "role": "system",
            "content": "You are Thomas. This is an internal warmup turn. Reply with exactly OK.",
        },
        {
            "role": "user",
            "content": "Internal warmup ping. This is not part of any user conversation. Reply with exactly OK.",
        },
    ]
    async for _event in provider.stream_chat(messages=messages, tools=None):
        pass
    return provider


def _schedule_codex_prewarm(app: web.Application, model_cfg: Any) -> None:
    if not _is_codex_model_cfg(model_cfg):
        return
    pool = app.get(APP_WARM_CODEX_POOL)
    tasks = app.get(APP_WARM_CODEX_TASKS)
    if not isinstance(pool, dict) or not isinstance(tasks, dict):
        return
    key = _warm_codex_pool_key(model_cfg)
    if key in pool:
        return
    task = tasks.get(key)
    if task is not None and not task.done():
        return

    async def _runner() -> None:
        provider = None
        try:
            provider = await _warm_codex_provider(model_cfg)
            active_pool = app.get(APP_WARM_CODEX_POOL)
            if isinstance(active_pool, dict) and key not in active_pool:
                active_pool[key] = provider
                provider = None
        except Exception as exc:
            log.warning("Codex prewarm failed for %s: %s", str(getattr(model_cfg, "model", "") or "codex"), exc)
        finally:
            active_tasks = app.get(APP_WARM_CODEX_TASKS)
            if isinstance(active_tasks, dict):
                active_tasks.pop(key, None)
            if provider is not None:
                with contextlib.suppress(Exception):
                    await provider.close()

    tasks[key] = asyncio.create_task(_runner())


def _take_warm_codex_provider(app: web.Application, model_cfg: Any) -> Any | None:
    if not _is_codex_model_cfg(model_cfg):
        return None
    pool = app.get(APP_WARM_CODEX_POOL)
    if not isinstance(pool, dict):
        return None
    key = _warm_codex_pool_key(model_cfg)
    provider = pool.pop(key, None)
    _schedule_codex_prewarm(app, model_cfg)
    return provider


def _refresh_cached_llm(
    entry: _CachedSessionLLM,
    *,
    model_cfg: Any,
    fallback_cfgs: list[Any],
    failover_enabled: bool,
) -> Any:
    llm = entry.llm
    llm.config = model_cfg
    if hasattr(llm, "_primary_config"):
        llm._primary_config = model_cfg
    if hasattr(llm, "_fallback_configs"):
        llm._fallback_configs = list(fallback_cfgs or [])
    if hasattr(llm, "_failover_enabled"):
        llm._failover_enabled = bool(failover_enabled and fallback_cfgs)
    if hasattr(llm, "_codex_provider") and getattr(llm, "_codex_provider", None) is not None:
        with contextlib.suppress(Exception):
            llm._codex_provider.config = model_cfg
    return llm


async def _close_cached_llm(llm: Any) -> None:
    close = getattr(llm, "close", None)
    if callable(close):
        await close()


async def _get_or_create_session_llm(
    app: web.Application,
    *,
    session_id: str,
    model_cfg: Any,
    fallback_cfgs: list[Any],
    failover_enabled: bool,
) -> tuple[Any, asyncio.Lock]:
    cache = app[APP_SESSION_LLM_CACHE]
    signature = _llm_signature(model_cfg)
    entry = cache.get(session_id)
    if entry is not None and entry.signature == signature:
        return _refresh_cached_llm(
            entry,
            model_cfg=model_cfg,
            fallback_cfgs=fallback_cfgs,
            failover_enabled=failover_enabled,
        ), entry.lock

    preserved_lock = entry.lock if entry is not None else asyncio.Lock()
    if entry is not None:
        with contextlib.suppress(Exception):
            await _close_cached_llm(entry.llm)

    llm = LLMClient(
        model_cfg,
        fallback_configs=fallback_cfgs,
        failover_enabled=failover_enabled,
    )
    warm_provider = _take_warm_codex_provider(app, model_cfg)
    if warm_provider is not None and hasattr(llm, "_codex_provider"):
        llm._codex_provider = warm_provider
    new_entry = _CachedSessionLLM(llm=llm, signature=signature, lock=preserved_lock)
    cache[session_id] = new_entry
    return _refresh_cached_llm(
        new_entry,
        model_cfg=model_cfg,
        fallback_cfgs=fallback_cfgs,
        failover_enabled=failover_enabled,
    ), new_entry.lock


async def _evict_session_llm(app: web.Application, session_id: str) -> None:
    cache = app.get(APP_SESSION_LLM_CACHE) or {}
    entry = cache.pop(session_id, None)
    if entry is None:
        return
    with contextlib.suppress(Exception):
        await _close_cached_llm(entry.llm)


async def _cleanup_cached_session_llms(app: web.Application) -> None:
    cache = app.get(APP_SESSION_LLM_CACHE) or {}
    entries = list(cache.values())
    cache.clear()
    for entry in entries:
        with contextlib.suppress(Exception):
            await _close_cached_llm(entry.llm)


async def _cleanup_warm_codex_pool(app: web.Application) -> None:
    pool = app.get(APP_WARM_CODEX_POOL) or {}
    providers = list(pool.values())
    pool.clear()
    tasks = app.get(APP_WARM_CODEX_TASKS) or {}
    running = list(tasks.values())
    tasks.clear()
    for task in running:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    for provider in providers:
        with contextlib.suppress(Exception):
            await provider.close()


async def _cleanup_browser_prewarm(app: web.Application) -> None:
    state = app.get(APP_BROWSER_PREWARM_STATE)
    task = state.get("task") if isinstance(state, dict) else None
    if isinstance(state, dict):
        state["task"] = None
    if isinstance(task, asyncio.Task):
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    with contextlib.suppress(Exception):
        await shutdown_browser()


def _browser_prewarm_enabled() -> bool:
    raw = str(os.environ.get("THOMAS_BROWSER_PREWARM", "")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return "PYTEST_CURRENT_TEST" not in os.environ


def register_chat_v2_routes(
    app: web.Application,
    *,
    config: Any,
    llm: Any,
    memory: Any,
    tools: Any,
    chat_store_dir: Path | None = None,
) -> None:
    store_dir = chat_store_dir or Path(".thomas") / "sessions_v2"
    session_store = SessionStore(store_dir)
    app[APP_SESSION_STORE] = session_store
    app[APP_SESSION_LLM_CACHE] = {}
    app[APP_WARM_CODEX_POOL] = {}
    app[APP_WARM_CODEX_TASKS] = {}
    app[APP_VOICE_BRIDGE] = VoiceBridge()
    app[APP_BROWSER_PREWARM_STATE] = {"task": None}
    app.on_cleanup.append(_cleanup_cached_session_llms)
    app.on_cleanup.append(_cleanup_warm_codex_pool)
    app.on_cleanup.append(_cleanup_browser_prewarm)

    if config is not None and getattr(config, "models", None):

        async def _startup_prewarm(app_ref: web.Application) -> None:
            for profile_name, model_cfg in list(getattr(config, "models", {}).items()):
                try:
                    resolved_cfg = config.get_model(profile_name) if hasattr(config, "get_model") else model_cfg
                except Exception:
                    resolved_cfg = model_cfg
                _schedule_codex_prewarm(app_ref, resolved_cfg)
            if _browser_prewarm_enabled():
                state = app_ref.get(APP_BROWSER_PREWARM_STATE)
                if isinstance(state, dict):
                    async def _warm_browser_read_sessions() -> None:
                        await asyncio.gather(
                            warm_browser_session("headline-read", headless=True, lane="read"),
                            warm_browser_session("content-read", headless=True, lane="read"),
                            warm_browser_session("action-direct", headless=True, lane="action"),
                        )

                    state["task"] = asyncio.create_task(_warm_browser_read_sessions())

        app.on_startup.append(_startup_prewarm)

    registry = SpecialistRegistry()
    for specialist_cls in [
        ReasoningSpecialist,
        CodingSpecialist,
        ResearchSpecialist,
        ToolSpecialist,
        SynthesisSpecialist,
    ]:
        try:
            specialist = specialist_cls(config=config, llm=llm, tools=tools)
            registry.register(specialist)
        except Exception as exc:
            log.warning("Failed to register specialist %s: %s", specialist_cls.__name__, exc)

    app[APP_SPECIALIST_REGISTRY] = registry
    app.router.add_post("/api/v2/chat", handle_chat_v2)
    app.router.add_post("/api/v2/chat/transcribe", handle_chat_transcribe)
    app.router.add_get("/api/v2/chat/session/{session_id}", handle_session_get)
    app.router.add_get("/api/v2/chat/session/{session_id}/delegations", handle_session_delegations)
    app.router.add_delete("/api/v2/chat/session/{session_id}", handle_session_delete)
    app.router.add_get("/api/v2/chat/specialists", handle_specialists_list)

    log.info("Chat V2 routes registered (%d specialists available)", len(registry.specialist_ids))


async def handle_chat_v2(request: web.Request) -> web.StreamResponse:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    prompt = str(payload.get("message", "")).strip()
    if not prompt:
        prompt = str(payload.get("text", "")).strip()
    if not prompt:
        return web.json_response({"error": "Empty message"}, status=400)

    docs = payload.get("docs") or []
    images = payload.get("images") or []

    if isinstance(docs, list) and docs:
        blocks: list[str] = []
        for doc in docs[:6]:
            if not isinstance(doc, dict):
                continue
            name = str(doc.get("name") or "document")
            content = str(doc.get("text") or "")
            if not content.strip():
                continue
            if len(content) > 50_000:
                content = content[:50_000] + "\n... (truncated)"
            blocks.append(f"--- {name} ---\n{content}\n--- end {name} ---")
        if blocks:
            prompt = (prompt.rstrip() + "\n\n[Attached documents]\n" + "\n\n".join(blocks)).strip()

    image_data: list[dict[str, Any]] = []
    if isinstance(images, list) and images:
        for img in images[:4]:
            if isinstance(img, dict) and img.get("data_url"):
                image_data.append({"type": "image_url", "image_url": {"url": str(img["data_url"])}})

    sid = str(payload.get("session_id", "") or secrets.token_urlsafe(18))
    mode = str(payload.get("mode", "auto"))
    autonomy_level = int(payload.get("autonomy_level", 3))
    token_economy = str(payload.get("token_economy", "optimal") or "optimal")
    request_context = build_discord_request_context(payload, sid)

    session_store: SessionStore = request.app[APP_SESSION_STORE]
    registry: SpecialistRegistry = request.app[APP_SPECIALIST_REGISTRY]

    conversation = await session_store.load(sid)
    if conversation is None:
        conversation = ConversationManager()

    app_config = None
    app_memory = None
    if APP_CONFIG is not None:
        try:
            app_config = request.app.get(APP_CONFIG)
        except Exception:
            app_config = None
    if APP_MEMORY is not None:
        try:
            app_memory = request.app.get(APP_MEMORY)
        except Exception:
            app_memory = None

    llm: Any = None
    llm_lock: asyncio.Lock | None = None
    if app_config is not None:
        try:
            model_profile = str(payload.get("profile", "") or "")
            if not model_profile or not hasattr(app_config, "models") or model_profile not in app_config.models:
                model_profile = getattr(app_config, "default_model", "")
            model_cfg = app_config.get_model(model_profile)
            requested_reasoning_effort = _normalize_reasoning_effort(str(payload.get("reasoning_effort", "") or ""))
            if requested_reasoning_effort:
                model_cfg = replace(model_cfg, reasoning_effort=requested_reasoning_effort)
            failover_cfgs = app_config.failover_chain(model_profile) if hasattr(app_config, "failover_chain") else []
            failover_enabled = bool(
                getattr(app_config, "failover", None)
                and getattr(app_config.failover, "enabled", False)
                and getattr(app_config.failover, "chat_auto_failover", False)
            )
            llm, llm_lock = await _get_or_create_session_llm(
                request.app,
                session_id=sid,
                model_cfg=model_cfg,
                fallback_cfgs=list(failover_cfgs or []),
                failover_enabled=failover_enabled,
            )
        except Exception as exc:
            log.warning("Failed to create LLM client for V2 chat: %s", exc)

    recent_messages = conversation.get_context_window(max_tokens=8_000)
    current_active_tasks = session_active_delegations(sid)

    keep_inline_fast_lane = _should_keep_inline_fast_lane(prompt)
    dispatch_decision = should_dispatch(
        prompt,
        recent_messages=recent_messages,
        active_tasks=current_active_tasks,
        mode=str(mode or "").strip().lower(),
    )
    dispatch_action = str(getattr(dispatch_decision, "action", "") or "").strip().lower()
    task_manager_ready = dispatch_action == "dispatch" and is_task_manager_dispatch_ready()
    if dispatch_action == "dispatch" and task_manager_ready:
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/x-ndjson; charset=utf-8",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        dispatcher = EventDispatcher(response.write)

        updated_conversation = conversation.append_message("user", prompt)
        if llm_lock is not None:
            async with llm_lock:
                ack_text = await stream_task_start_acknowledgment(
                    llm,
                    user_text=prompt,
                    emit_text=dispatcher.emit_text,
                )
        else:
            ack_text = await stream_task_start_acknowledgment(
                llm,
                user_text=prompt,
                emit_text=dispatcher.emit_text,
            )

        updated_conversation = updated_conversation.append_message(
            "assistant",
            ack_text,
            metadata={"specialists": ["task_manager"], "mode": "dispatch"},
        )
        meta = SessionMeta(session_id=sid, autonomy_level=autonomy_level)
        await session_store.save(sid, updated_conversation, meta, force=True)
        with contextlib.suppress(Exception):
            append_discord_history_turn_if_needed(
                cfg=app_config,
                request_context=request_context,
                session_id=sid,
                user_text=prompt,
                assistant_text=ack_text,
                tool_calls=0,
            )

        try:
            dispatch_result = await dispatch_async(prompt, sid, emit_event=dispatcher.emit)
        except Exception as exc:
            await dispatcher.emit_error(str(exc))
            await dispatcher.emit_done(
                session_id=sid,
                conversation_version=updated_conversation.version,
                thinking_summary="task_manager_dispatch_failed",
                iterations=1,
                tool_calls=0,
                tokens_used=0,
                specialists_used=["task_manager"],
            )
            await response.write_eof()
            return response

        if dispatch_result.ok:
            await dispatcher.emit(
                {
                    "type": "task_dispatched",
                    "task_id": dispatch_result.task_id,
                    "execution_id": dispatch_result.execution_id,
                    "text": f"Task {dispatch_result.task_id} dispatched.",
                }
            )
            await dispatcher.emit_done(
                session_id=sid,
                conversation_version=updated_conversation.version,
                thinking_summary="task_manager_background_dispatch",
                iterations=1,
                tool_calls=0,
                tokens_used=0,
                specialists_used=["task_manager"],
            )
        else:
            await dispatcher.emit_error(dispatch_result.error or "Task-manager dispatch failed.")
            await dispatcher.emit_done(
                session_id=sid,
                conversation_version=updated_conversation.version,
                thinking_summary="task_manager_dispatch_failed",
                iterations=1,
                tool_calls=0,
                tokens_used=0,
                specialists_used=["task_manager"],
            )
        await response.write_eof()
        return response
    if dispatch_action == "dispatch" and not task_manager_ready:
        if keep_inline_fast_lane:
            log.info(
                "Task-manager lane unavailable for deterministic task in chat session %s; falling back to inline fast orchestrator.",
                sid[:12],
            )
        else:
            log.info("Task-manager lane unavailable for chat session %s; falling back to inline orchestrator.", sid[:12])

    if llm is not None:
        for specialist in registry.all_specialists:
            specialist.llm = llm

    brain = OrchestratorBrain(
        config=app_config,
        llm=llm,
        memory_engine=app_memory,
        registry=registry,
    )

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    dispatcher = EventDispatcher(response.write)
    is_first_message = conversation.length == 0
    active_tasks = current_active_tasks
    active_task_digest = build_active_task_digest(sid) if active_tasks else ""

    try:

        async def _run_brain_turn() -> ConversationManager:
            return await brain.process_message(
                session_id=sid,
                conversation=conversation,
                prompt=prompt,
                dispatcher=dispatcher,
                mode=mode,
                autonomy_level=autonomy_level,
                token_economy=token_economy,
                images=image_data if image_data else None,
                is_first_message=is_first_message,
                active_task_digest=active_task_digest,
                active_tasks=active_tasks,
                dispatch_actionable=keep_inline_fast_lane or (dispatch_action == "dispatch" and not task_manager_ready),
                background_ack_only=False,
            )

        if llm_lock is not None:
            async with llm_lock:
                conversation = await _run_brain_turn()
                meta = SessionMeta(session_id=sid, autonomy_level=autonomy_level)
                await session_store.save(sid, conversation, meta, force=True)
        else:
            conversation = await _run_brain_turn()
            meta = SessionMeta(session_id=sid, autonomy_level=autonomy_level)
            await session_store.save(sid, conversation, meta, force=True)

    except Exception as exc:
        log.error("Chat V2 failed for session %s: %s", sid[:12], exc, exc_info=True)
        await dispatcher.emit_error(str(exc))
    finally:
        with contextlib.suppress(Exception):
            append_discord_history_turn_if_needed(
                cfg=app_config,
                request_context=request_context,
                session_id=sid,
                user_text=prompt,
                assistant_text=str(conversation.last_assistant_message() or ""),
                tool_calls=0,
            )

    await response.write_eof()
    return response


async def handle_chat_transcribe(request: web.Request) -> web.Response:
    if not str(request.content_type or "").lower().startswith("multipart/"):
        return web.json_response({"error": "Expected multipart/form-data"}, status=400)

    try:
        reader = await request.multipart()
    except Exception:
        return web.json_response({"error": "Unable to read upload"}, status=400)

    audio_bytes = b""
    audio_name = "audio.webm"
    audio_content_type = "audio/webm"

    while True:
        field = await reader.next()
        if field is None:
            break
        if str(getattr(field, "name", "") or "") != "audio":
            with contextlib.suppress(Exception):
                await field.release()
            continue
        audio_name = str(getattr(field, "filename", "") or "audio.webm")
        audio_content_type = str(field.headers.get("Content-Type", "audio/webm") or "audio/webm")
        parts = []
        total = 0
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_TRANSCRIBE_BYTES:
                return web.json_response({"error": "Audio upload too large"}, status=413)
            parts.append(chunk)
        audio_bytes = b"".join(parts)
        break

    if not audio_bytes:
        return web.json_response({"error": "Missing audio upload"}, status=400)

    bridge = await _voice_bridge_for_request(request.app)
    audio = AudioData(
        data=audio_bytes,
        format=_uploaded_audio_format(audio_name, audio_content_type),
        sample_rate=16000,
        duration_ms=0,
    )
    try:
        text = await bridge.transcribe(audio)
    except VoiceProviderException as exc:
        return web.json_response({"error": str(exc)}, status=503)
    except Exception as exc:
        log.warning("Chat transcription failed: %s", exc, exc_info=True)
        return web.json_response({"error": f"Transcription failed: {exc}"}, status=500)

    provider = getattr(getattr(bridge, "_current_stt", None), "get_provider_name", lambda: "")()
    return web.json_response({"ok": True, "text": str(text or ""), "provider": str(provider or "")})


async def handle_session_get(request: web.Request) -> web.Response:
    sid = request.match_info["session_id"]
    session_store: SessionStore = request.app[APP_SESSION_STORE]

    conversation = await session_store.load(sid)
    if conversation is None:
        return web.json_response({"error": "Session not found"}, status=404)

    return web.json_response({"session_id": sid, "conversation": conversation.to_dict()})


async def handle_session_delete(request: web.Request) -> web.Response:
    sid = request.match_info["session_id"]
    session_store: SessionStore = request.app[APP_SESSION_STORE]

    deleted = await session_store.delete(sid)
    await _evict_session_llm(request.app, sid)
    return web.json_response({"deleted": deleted, "session_id": sid})


async def handle_session_delegations(request: web.Request) -> web.Response:
    sid = request.match_info["session_id"]
    delegations = session_active_delegations(sid)
    return web.json_response({"session_id": sid, "delegations": delegations})


async def handle_specialists_list(request: web.Request) -> web.Response:
    registry: SpecialistRegistry = request.app[APP_SPECIALIST_REGISTRY]

    specialists = []
    for specialist in registry.all_specialists:
        health = await specialist.check_health()
        specialists.append(
            {
                "id": specialist.specialist_id,
                "description": specialist.description,
                "healthy": health.healthy,
                "message": health.message,
                "capabilities": sorted(specialist.capabilities),
            }
        )

    return web.json_response({"specialists": specialists})
