"""Route registration table for the directed Code surface."""

from __future__ import annotations

from typing import Any

from aiohttp import web


def register_evolve_agent_handler_map(app: web.Application, handlers: dict[str, Any]) -> None:
    """Attach the already-built handler map to its public API paths."""
    routes = (
        ("POST", "/api/evolve/agent/send", "send"),
        ("POST", "/api/evolve/agent/approve", "approve"),
        ("POST", "/api/evolve/agent/steer", "steer"),
        ("GET", "/api/evolve/agent/stream", "stream"),
        ("GET", "/api/evolve/agent/status", "status"),
        ("POST", "/api/evolve/agent/stop", "stop"),
        # A live run's controls (evolve_agent_run_control_routes): hold it, speak to one of its agents, answer it.
        ("POST", "/api/evolve/agent/pause", "run_pause"),
        ("POST", "/api/evolve/agent/resume", "run_resume"),
        ("POST", "/api/evolve/agent/message", "run_message"),
        ("GET", "/api/evolve/agent/messages", "run_messages"),
        ("GET", "/api/evolve/agent/performance", "run_performance"),
        ("POST", "/api/evolve/agent/compact", "run_compact"),
        ("POST", "/api/evolve/agent/context-window", "run_context_window"),
        ("POST", "/api/evolve/agent/answer", "run_answer"),
        ("GET", "/api/evolve/agent/live-diff", "live_diff"),
        ("GET", "/api/evolve/agent/self-edit/{cid}/status", "self_edit_status"),
        ("POST", "/api/evolve/agent/self-edit/{action}", "self_edit_action"),
        ("GET", "/api/evolve/agent/deliverables", "deliverables_list"),
        ("GET", "/api/evolve/agent/conversations", "conversations_list"),
        ("POST", "/api/evolve/agent/conversations/new", "conversation_new"),
        ("GET", "/api/evolve/agent/conversations/{cid}/tree", "conversation_tree"),
        ("GET", "/api/evolve/agent/conversations/{cid}/file", "conversation_file"),
        ("GET", "/api/evolve/agent/conversations/{cid}/preview", "conversation_preview"),
        ("GET", "/api/evolve/agent/conversations/{cid}", "conversation_get"),
        ("POST", "/api/evolve/agent/conversations/{cid}/rename", "conversation_rename"),
        ("DELETE", "/api/evolve/agent/conversations/{cid}", "conversation_delete"),
        ("GET", "/api/evolve/agent/changes", "changes"),
        ("POST", "/api/evolve/agent/revert", "revert"),
        ("POST", "/api/evolve/agent/keep", "keep"),
        ("POST", "/api/evolve/agent/checkpoint", "checkpoint"),
        ("GET", "/api/evolve/agent/artifact-content/{capability}/{cid}/{tail:.*}", "artifact_content"),
        ("GET", "/api/evolve/agent/artifact/{cid}/{tail:.*}", "artifact"),
        ("GET", "/api/evolve/agent/playtest/stream", "playtest_stream"),
    )
    for method, path, name in routes:
        app.router.add_route(method, path, handlers[name])
