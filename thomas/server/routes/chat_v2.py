"""Unified /api/v2/chat route.

Thomas remains the only conversational voice on this route. In Max mode we
can launch silent background delegation in parallel, but user-visible text is
still streamed only from Thomas.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.agent.dispatch import should_dispatch
from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.session_store import SessionMeta, SessionStore
from thomas.core.autonomy import DEFAULT_AUTONOMY_LEVEL
from thomas.core.file_access import parse_file_access_level
from thomas.core.llm import LLMClient
from thomas.marketplace.orchestrator.brain import OrchestratorBrain
from thomas.marketplace.orchestrator.registry import SpecialistRegistry
from thomas.marketplace.specialists.coding import CodingSpecialist
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist
from thomas.marketplace.specialists.research import ResearchSpecialist
from thomas.marketplace.specialists.synthesis import SynthesisSpecialist
from thomas.marketplace.specialists.tools import ToolSpecialist
from thomas.server.chat_delegation import (
    _prompt_targets_live_thomas_repo,
    apply_task_update,
    build_active_task_digest,
    session_active_delegations,
    start_background_delegation,
)
from thomas.tools.voice import AudioData, VoiceBridge, VoiceProviderException

try:
    from thomas.server.app_keys import APP_CONFIG, APP_MEMORY, APP_TOOLS
except ImportError:
    APP_CONFIG = APP_MEMORY = APP_TOOLS = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

APP_SESSION_STORE = web.AppKey("chat_v2_session_store", SessionStore)
APP_SPECIALIST_REGISTRY = web.AppKey("chat_v2_specialist_registry", SpecialistRegistry)
APP_SESSION_LLM_CACHE = web.AppKey("chat_v2_session_llm_cache", dict)
APP_VOICE_BRIDGE = web.AppKey("chat_v2_voice_bridge", VoiceBridge)

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
    # Single mandatory whitespace run; the optional in/into connector carries
    # its own trailing space. Avoids the adjacent \s+...?\s* ambiguity that
    # caused polynomial backtracking (py/polynomial-redos).
    r"|(?:rest|deeper work|longer work)\s+(?:(?:in|into)\s+)?background"
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
    app[APP_VOICE_BRIDGE] = VoiceBridge()
    app.on_cleanup.append(_cleanup_cached_session_llms)

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
    app.router.add_post(
        "/api/v2/chat/session/{session_id}/delegations/{execution_id}/reported",
        handle_mark_delegation_reported,
    )
    app.router.add_post(
        "/api/v2/chat/session/{session_id}/delegations/{execution_id}/announce",
        handle_announce_delegation,
    )
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
    autonomy_level = int(payload.get("autonomy_level", DEFAULT_AUTONOMY_LEVEL))
    # File-access ladder (read_only/workspace/project/pc/full) — the "let Thomas write
    # to my PC" toggle. None = inherit the configured default; a value overrides it for
    # this session. See thomas/core/file_access.py.
    _fa_raw = payload.get("file_access")
    file_access = parse_file_access_level(_fa_raw) if _fa_raw is not None else None
    token_economy = str(payload.get("token_economy", "optimal") or "optimal")
    thomas_guardrails = str(payload.get("thomas_guardrails", "") or "")
    _grm = payload.get("thomas_guardrail_modes")
    thomas_guardrail_modes = _grm if isinstance(_grm, dict) else None

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
    # The model this chat is on; threaded into the background worker so a worker
    # spawned from this chat builds with the SAME model the chat is using.
    model_profile = ""
    if app_config is not None:
        try:
            model_profile = str(payload.get("profile", "") or "")
            if not model_profile or not hasattr(app_config, "models") or model_profile not in app_config.models:
                model_profile = getattr(app_config, "default_model", "")
            model_cfg = app_config.get_model(model_profile)
            requested_model_id = str(payload.get("model_id", "") or "").strip()
            if requested_model_id:
                model_cfg = replace(model_cfg, model=requested_model_id)
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
    recent_messages = conversation.get_context_window(max_tokens=8_000)
    current_active_tasks = session_active_delegations(sid)
    launcher_task: asyncio.Task[Any] | None = None
    live_repo_background = bool(autonomy_level >= 3 and _prompt_targets_live_thomas_repo(prompt))
    dispatch_inline_actionable = False if live_repo_background else _requires_inline_tool_execution(prompt)
    reply_first_background = bool(mode == "auto" and _requests_reply_first_background(prompt))
    explicit_delegation = bool(autonomy_level >= 4 and _requests_explicit_delegation(prompt))
    # No-regex dispatch: the old `should_dispatch` regex that GUESSED whether a
    # message was a task (and then faked an instant ack) is gone. Whether to hand
    # work off is now the MODEL's call, made organically via the send_task tool
    # (wired below). Autonomy still governs it: the tool is only offered at L3+
    # (Agent/Full), so at L1/L2 Thomas talks/offers and never dispatches on its own.
    auto_actionable_background = False
    launch_background = bool(mode == "max" or reply_first_background or explicit_delegation or live_repo_background)
    force_background = bool(reply_first_background or explicit_delegation or live_repo_background)
    background_ack_only = False
    visible_prompt = _foreground_reply_prompt(prompt) if reply_first_background else prompt

    async def _send_task(*, title: str, instructions: str, surface: str = "") -> None:
        """Organic dispatch: the model calls this to hand work to the task manager.
        surface ('canvas'|'task'|'') is the MODEL's choice of where the work appears."""
        await start_background_delegation(
            request.app,
            session_id=sid,
            prompt=str(instructions or title or prompt),
            mode=mode,
            recent_messages=recent_messages,
            emit_event=dispatcher.emit,
            force=True,
            autonomy_level=autonomy_level,
            file_access=file_access,
            profile=model_profile or None,
            effort=token_economy,
            guardrails=thomas_guardrails,
            guardrail_modes=thomas_guardrail_modes,
            session_llm=llm,
            surface=surface,
        )

    # A turn that force-launches in the background must NOT also hand the model the tool
    # (that double-dispatch hole was the "multiple tasks"): offer the tool only when nothing
    # else is auto-launching this turn.
    send_task_cb = _send_task if (autonomy_level >= 3 and not launch_background) else None

    async def _update_task(*, task_ref: str, update: str = "", cancel: bool = False) -> dict[str, Any]:
        """Organic re-direct: the model steers or cancels a RUNNING background task,
        choosing the right one by ref from the digest instead of a blind heuristic."""
        return apply_task_update(sid, task_ref, update, cancel=bool(cancel))

    update_task_cb = _update_task if autonomy_level >= 3 else None

    try:
        if launch_background:
            launcher_task = asyncio.create_task(
                start_background_delegation(
                    request.app,
                    session_id=sid,
                    prompt=prompt,
                    mode=mode,
                    recent_messages=recent_messages,
                    emit_event=dispatcher.emit,
                    force=force_background,
                    autonomy_level=autonomy_level,
                    file_access=file_access,
                    profile=model_profile or None,
                    effort=token_economy,
                    guardrails=thomas_guardrails,
                    guardrail_modes=thomas_guardrail_modes,
                    session_llm=llm,
                )
            )
            await asyncio.sleep(0)

        active_tasks = session_active_delegations(sid)
        active_task_digest = build_active_task_digest(sid) if active_tasks or launch_background else ""

        async def _run_brain_turn() -> ConversationManager:
            return await brain.process_message(
                session_id=sid,
                conversation=conversation,
                prompt=visible_prompt,
                dispatcher=dispatcher,
                mode=mode,
                autonomy_level=autonomy_level,
                token_economy=token_economy,
                images=image_data if image_data else None,
                is_first_message=is_first_message,
                active_task_digest=active_task_digest,
                active_tasks=active_tasks,
                dispatch_actionable=dispatch_inline_actionable,
                background_ack_only=background_ack_only,
                send_task=send_task_cb,
                update_task=update_task_cb,
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

        if launcher_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(launcher_task), timeout=0.75)
            except asyncio.TimeoutError:
                pass
            except Exception as exc:
                log.warning("Max-mode delegation launcher failed for session %s: %s", sid[:12], exc, exc_info=True)
                await dispatcher.emit(
                    {
                        "type": "delegation_failed",
                        "session_id": sid,
                        "backend_type": "task_manager",
                        "state": "failed",
                        "summary": prompt[:160],
                        "last_progress": f"Background delegation failed to start: {exc}",
                    }
                )

    except Exception as exc:
        log.error("Chat V2 failed for session %s: %s", sid[:12], exc, exc_info=True)
        await dispatcher.emit_error(str(exc))

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


async def handle_mark_delegation_reported(request: web.Request) -> web.Response:
    """Mark a finished delegation as already announced in chat, so the in-thread
    completion bubble (frontend) and the next-turn brain note do not BOTH report the
    same completion. Whichever surface delivers it first sets this durable flag; the
    other then skips. Best-effort: a write failure is non-fatal."""
    sid = str(request.match_info.get("session_id", "") or "").strip()
    exec_id = str(request.match_info.get("execution_id", "") or "").strip()
    ok = False
    if exec_id:
        try:
            from datetime import datetime, timezone

            from thomas.core import task_bot_runtime

            # Session-scope the mark: a session may only flag its OWN delegations. Fail
            # OPEN — if the row is unknown or carries no conversation id, fall through to
            # the write (preserves behavior for rows predating the field). Only a row that
            # belongs to a DIFFERENT conversation is rejected.
            row = task_bot_runtime.get_execution(exec_id) or {}
            owner = str(row.get("conversation_id") or "").strip()
            if sid and owner and owner != sid:
                return web.json_response(
                    {"session_id": sid, "execution_id": exec_id, "ok": False, "error": "session_mismatch"},
                    status=403,
                )
            task_bot_runtime.update_execution(
                exec_id,
                reported_to_chat_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            )
            ok = True
        except Exception:
            log.debug("mark-reported failed for execution %s", exec_id, exc_info=True)
    return web.json_response({"session_id": sid, "execution_id": exec_id, "ok": ok})


def _announce_llm(app: web.Application, sid: str) -> Any | None:
    """Reuse the session's already-warm LLM client (the chat built it for this session);
    fall back to a default-model client if none is cached."""
    cache = app.get(APP_SESSION_LLM_CACHE) or {}
    entry = cache.get(sid)
    if entry is not None and getattr(entry, "llm", None) is not None:
        return entry.llm
    cfg = app.get(APP_CONFIG) if APP_CONFIG is not None else None
    if cfg is None:
        return None
    try:
        from thomas.core.llm_client import LLMClient

        model_cfg = cfg.get_model(getattr(cfg, "default_model", "") or None)
        return LLMClient(model_cfg)
    except (AttributeError, ImportError, LookupError, RuntimeError, TypeError, ValueError) as exc:
        log.debug("announce LLM lookup failed for session %s: %s", sid, exc, exc_info=True)
        return None


async def _generate_note(llm: Any, system: str, user: str, timeout_s: float = 30.0) -> str:
    """Collect a short non-streamed completion. Bounded so a provider stall can't hang."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    parts: list[str] = []

    async def _run() -> None:
        aiter = llm.stream_chat(messages=messages, tools=None).__aiter__()
        while True:
            try:
                ev = await aiter.__anext__()
            except StopAsyncIteration:
                break
            etype = str(getattr(ev, "type", "") or "")
            if etype == "token":
                t = str((getattr(ev, "data", {}) or {}).get("text") or "")
                if t:
                    parts.append(t)
            elif etype == "error":
                break

    try:
        await asyncio.wait_for(_run(), timeout=timeout_s)
    except asyncio.TimeoutError:
        pass
    except (AttributeError, RuntimeError, OSError, TypeError, ValueError) as exc:
        log.debug("announce note generation failed: %s", exc, exc_info=True)
    return "".join(parts).strip()


async def handle_announce_delegation(request: web.Request) -> web.Response:
    """Proactively VOICE a finished delegation: a brief, model-authored 'it's done' note in
    Thomas's own voice, persisted as an assistant turn and marked reported so the next user
    turn doesn't repeat it. Fires once — an already-reported or non-terminal row is skipped.
    This is the in-thread completion bubble the reported-flag was built to coordinate."""
    app = request.app
    sid = str(request.match_info.get("session_id", "") or "").strip()
    exec_id = str(request.match_info.get("execution_id", "") or "").strip()
    if not sid or not exec_id:
        return web.json_response({"ok": False, "error": "missing_ids"}, status=400)
    try:
        from datetime import datetime, timezone

        from thomas.core import task_bot_runtime

        row = task_bot_runtime.get_execution(exec_id) or {}
        owner = str(row.get("conversation_id") or "").strip()
        if owner and owner != sid:
            return web.json_response({"ok": False, "error": "session_mismatch"}, status=403)
        if str(row.get("reported_to_chat_at") or "").strip():
            return web.json_response({"ok": True, "skipped": "already_reported"})
        state = str(row.get("state") or "").lower()
        if state not in {"completed", "done", "verified", "succeeded", "passed", "failed", "blocked", "error"}:
            return web.json_response({"ok": True, "skipped": "not_terminal"})
        failed = state in {"failed", "blocked", "error"}

        session_store: SessionStore = app[APP_SESSION_STORE]
        conversation = await session_store.load(sid)
        if conversation is None:
            conversation = ConversationManager()
        last_user = ""
        for m in reversed(conversation.get_context_window(max_tokens=2000)):
            if str(m.get("role")) == "user":
                last_user = str(m.get("content") or "")
                break
        summary = str(row.get("progress_summary") or row.get("summary") or "").strip()
        bot = str(row.get("bot_name") or row.get("bot_id") or "a worker").strip() or "a worker"
        artifact = ""
        try:
            from thomas.server.routes.deliverable_aiohttp import deliverable_entry

            ent = deliverable_entry(exec_id) or ""
            artifact = ent.rsplit("/", 1)[-1] if ent else ""
        except (AttributeError, ImportError, LookupError, RuntimeError, OSError, TypeError, ValueError):
            artifact = ""

        llm = _announce_llm(app, sid)
        if llm is None or not hasattr(llm, "stream_chat"):
            return web.json_response({"ok": False, "error": "no_llm"}, status=503)

        system = (
            "You are Thomas, the user's warm, capable assistant. Reply in your own natural voice — "
            "brief, human, first person, no preamble, no 'as an AI'."
        )
        bits = [
            f"A task you handed to {bot} "
            + ("ran into a problem and could not finish." if failed else "just finished.")
        ]
        if last_user:
            bits.append(f'The user had asked: "{last_user[:300]}".')
        if summary:
            bits.append(f"Result: {summary[:300]}.")
        if artifact and not failed:
            bits.append(f"It produced a deliverable: {artifact}.")
        bits.append(
            "In one or two short sentences, proactively let the user know it's done and what you've "
            "got for them — like you're telling them the moment it landed; they didn't have to ask."
            if not failed
            else "In one or two short sentences, let the user know it didn't finish and offer to take another run at it."
        )
        note = await _generate_note(llm, system, " ".join(bits))
        if not note:
            return web.json_response({"ok": False, "error": "empty_note"}, status=502)

        conversation = conversation.append_message("assistant", note, metadata={"announce": exec_id})
        await session_store.save(sid, conversation, SessionMeta(session_id=sid), force=True)
        task_bot_runtime.update_execution(
            exec_id, reported_to_chat_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        return web.json_response({"ok": True, "message": note})
    except (KeyError, LookupError, RuntimeError, OSError, TypeError, ValueError) as exc:
        log.debug("announce failed for %s/%s: %s", sid, exec_id, exc, exc_info=True)
        return web.json_response({"ok": False, "error": "exception"}, status=500)


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
