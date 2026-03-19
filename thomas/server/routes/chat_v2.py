"""Unified Chat V2 Endpoint — Brain/Orchestrator architecture.

Replaces the fragmented chat_aiohttp + chat_modes + chat_stream_events
pipeline with a single clean endpoint.

Key changes from V1:
    1. ConversationManager (COW) — no more shared mutable references
    2. Auto-save after every turn — no frontend PUT dependency
    3. 3-layer memory — refreshes every iteration, not just #0
    4. Single endpoint — no more batch/swarm/control/quick fragmentation
    5. Orchestrator brain — delegates to specialists, never executes directly
    6. Thinking events — exposed at every decision point
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.session_store import SessionMeta, SessionStore
from thomas.core.llm import LLMClient

# V3 brain swap (2026-03-18): Use V3 brain with named bots and async dispatch.
# Falls back to V2 brain if V3 import fails.
try:
    from thomas.orchestrator.brain_v3 import OrchestratorBrainV3 as OrchestratorBrain
except ImportError:
    from thomas.orchestrator.brain import OrchestratorBrain
from thomas.orchestrator.registry import SpecialistRegistry
from thomas.specialists.coding import CodingSpecialist
from thomas.specialists.reasoning import ReasoningSpecialist
from thomas.specialists.research import ResearchSpecialist
from thomas.specialists.synthesis import SynthesisSpecialist
from thomas.specialists.tools import ToolSpecialist

# Import app keys for proper config/memory/tools access
try:
    from thomas.server.app_keys import APP_CONFIG, APP_MEMORY, APP_TOOLS
except ImportError:
    APP_CONFIG = APP_MEMORY = APP_TOOLS = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# ── app keys ─────────────────────────────────────────────────────
# These are registered in app.py during startup

APP_SESSION_STORE = web.AppKey("chat_v2_session_store", SessionStore)
APP_SPECIALIST_REGISTRY = web.AppKey("chat_v2_specialist_registry", SpecialistRegistry)


# ── route registration ───────────────────────────────────────────


def register_chat_v2_routes(
    app: web.Application,
    *,
    config: Any,
    llm: Any,
    memory: Any,
    tools: Any,
    chat_store_dir: Path | None = None,
) -> None:
    """Register the V2 chat routes and initialise supporting infrastructure.

    Call this from ``app.py`` during server startup.
    """
    # Initialise session store
    store_dir = chat_store_dir or Path(".thomas") / "sessions_v2"
    session_store = SessionStore(store_dir)
    app[APP_SESSION_STORE] = session_store

    # Build specialist registry
    registry = SpecialistRegistry()

    # Register built-in specialists (graceful fallback — never block boot)
    for SpecialistClass in [
        ReasoningSpecialist,
        CodingSpecialist,
        ResearchSpecialist,
        ToolSpecialist,
        SynthesisSpecialist,
    ]:
        try:
            specialist = SpecialistClass(config=config, llm=llm, tools=tools)
            registry.register(specialist)
        except Exception as exc:
            log.warning(
                "Failed to register specialist %s: %s",
                SpecialistClass.__name__,
                exc,
            )

    app[APP_SPECIALIST_REGISTRY] = registry

    # Register V2 chat API route and session helpers.
    app.router.add_post("/api/v2/chat", handle_chat_v2)
    app.router.add_get("/api/v2/chat/session/{session_id}", handle_session_get)
    app.router.add_delete("/api/v2/chat/session/{session_id}", handle_session_delete)
    app.router.add_get("/api/v2/chat/specialists", handle_specialists_list)

    log.info(
        "Chat V2 routes registered (%d specialists available)",
        len(registry.specialist_ids),
    )


# ── main chat handler ────────────────────────────────────────────


async def handle_chat_v2(request: web.Request) -> web.StreamResponse:
    """POST /api/v2/chat — Unified chat endpoint.

    Request body (JSON):
        message:          str   — User's message text
        session_id:       str   — Session ID (auto-generated if missing)
        mode:             str   — "auto" | "fast" | "thinking" | "max"
        autonomy_level:   int   — 1-4
        profile:          str   — LLM profile name
        model_id:         str   — Specific model ID (optional)

    Response: NDJSON stream with events:
        thinking, delegation, agent_activity, tool_start, tool_result,
        text, memory_refresh, done, error
    """
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    prompt = str(payload.get("message", "")).strip()
    if not prompt:
        prompt = str(payload.get("text", "")).strip()
    if not prompt:
        return web.json_response({"error": "Empty message"}, status=400)

    # ── File attachments (match V1 behaviour) ───────────────────
    docs = payload.get("docs") or []
    images = payload.get("images") or []

    if isinstance(docs, list) and docs:
        blocks: list[str] = []
        for d in docs[:6]:  # max 6 documents
            if not isinstance(d, dict):
                continue
            name = str(d.get("name") or "document")
            content = str(d.get("text") or "")
            if not content.strip():
                continue
            if len(content) > 50_000:
                content = content[:50_000] + "\n... (truncated)"
            blocks.append(f"--- {name} ---\n{content}\n--- end {name} ---")
        if blocks:
            prompt = (prompt.rstrip() + "\n\n[Attached documents]\n" + "\n\n".join(blocks)).strip()

    # Images: pass through for multimodal-capable models
    image_data: list[dict[str, Any]] = []
    if isinstance(images, list) and images:
        for img in images[:4]:  # max 4 images
            if isinstance(img, dict) and img.get("data_url"):
                image_data.append({"type": "image_url", "image_url": {"url": str(img["data_url"])}})

    sid = str(payload.get("session_id", "") or secrets.token_urlsafe(18))
    mode = str(payload.get("mode", "auto"))
    autonomy_level = int(payload.get("autonomy_level", 3))

    # Get infrastructure from app
    session_store: SessionStore = request.app[APP_SESSION_STORE]
    registry: SpecialistRegistry = request.app[APP_SPECIALIST_REGISTRY]

    # Load or create conversation
    conversation = await session_store.load(sid)
    if conversation is None:
        conversation = ConversationManager()

    # Create orchestrator brain with proper app-key access
    app_config = None
    app_memory = None
    if APP_CONFIG is not None:
        try:
            app_config = request.app.get(APP_CONFIG)
        except Exception:
            pass
    if APP_MEMORY is not None:
        try:
            app_memory = request.app.get(APP_MEMORY)
        except Exception:
            pass

    # ── Create per-request LLM client ────────────────────────────
    # V1 creates an LLMClient on every request from the live config.
    # V2 must do the same — specialists and the brain both need a
    # working LLM client to call the model.
    llm: Any = None
    if app_config is not None:
        try:
            model_profile = str(payload.get("profile", "") or "")
            if not model_profile or not hasattr(app_config, "models") or model_profile not in app_config.models:
                model_profile = getattr(app_config, "default_model", "")
            model_cfg = app_config.get_model(model_profile)
            failover_cfgs = app_config.failover_chain(model_profile) if hasattr(app_config, "failover_chain") else []
            failover_enabled = bool(
                getattr(app_config, "failover", None)
                and getattr(app_config.failover, "enabled", False)
                and getattr(app_config.failover, "chat_auto_failover", False)
            )
            llm = LLMClient(
                model_cfg,
                fallback_configs=failover_cfgs,
                failover_enabled=failover_enabled,
            )
        except Exception as exc:
            log.warning("Failed to create LLM client for V2 chat: %s", exc)

    # Inject live LLM into every specialist for this request
    if llm is not None:
        for specialist in registry.all_specialists:
            specialist.llm = llm

    brain = OrchestratorBrain(
        config=app_config,
        llm=llm,
        memory_engine=app_memory,
        registry=registry,
    )

    # Prepare streaming response
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

    # Detect first message in session (for welcome hint)
    is_first_message = conversation.length == 0

    try:
        # Process through orchestrator
        conversation = await brain.process_message(
            session_id=sid,
            conversation=conversation,
            prompt=prompt,
            dispatcher=dispatcher,
            mode=mode,
            autonomy_level=autonomy_level,
            images=image_data if image_data else None,
            is_first_message=is_first_message,
        )

        # Auto-save conversation (CRITICAL FIX for bug #2)
        meta = SessionMeta(
            session_id=sid,
            autonomy_level=autonomy_level,
        )
        await session_store.save(sid, conversation, meta, force=True)

    except Exception as exc:
        log.error("Chat V2 failed for session %s: %s", sid[:12], exc)
        await dispatcher.emit_error(str(exc))

    await response.write_eof()
    return response


# ── session management ───────────────────────────────────────────


async def handle_session_get(request: web.Request) -> web.Response:
    """GET /api/v2/chat/session/{session_id} — Load session history."""
    sid = request.match_info["session_id"]
    session_store: SessionStore = request.app[APP_SESSION_STORE]

    conversation = await session_store.load(sid)
    if conversation is None:
        return web.json_response({"error": "Session not found"}, status=404)

    return web.json_response(
        {
            "session_id": sid,
            "conversation": conversation.to_dict(),
        }
    )


async def handle_session_delete(request: web.Request) -> web.Response:
    """DELETE /api/v2/chat/session/{session_id} — Delete a session."""
    sid = request.match_info["session_id"]
    session_store: SessionStore = request.app[APP_SESSION_STORE]

    deleted = await session_store.delete(sid)
    return web.json_response(
        {
            "deleted": deleted,
            "session_id": sid,
        }
    )


async def handle_specialists_list(request: web.Request) -> web.Response:
    """GET /api/v2/chat/specialists — List available specialists."""
    registry: SpecialistRegistry = request.app[APP_SPECIALIST_REGISTRY]

    specialists = []
    for s in registry.all_specialists:
        health = await s.check_health()
        specialists.append(
            {
                "id": s.specialist_id,
                "description": s.description,
                "capabilities": sorted(s.capabilities),
                "healthy": health.healthy,
                "executions": health.total_executions,
            }
        )

    return web.json_response({"specialists": specialists})
