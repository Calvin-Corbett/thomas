"""Small request-scope helpers shared by the canonical Chat V2 route."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from aiohttp import web

from thomas.core.token_economy import build_token_economy_meta, compute_max_passes, normalize_token_economy_level
from thomas.server.chat_delegation import apply_task_update, session_active_delegations
from thomas.server.routes.chat_v2_session_routes import (
    handle_cancel_delegation as _handle_cancel_delegation,
)
from thomas.server.routes.chat_v2_session_routes import (
    handle_session_delegations as _handle_session_delegations,
)
from thomas.server.work_connector_runtime import request_work_tools


async def handle_session_delegations(request: web.Request) -> web.Response:
    """Keep the public delegation lookup patchable for integrations."""
    return await _handle_session_delegations(request, active_delegations=session_active_delegations)


async def handle_cancel_delegation(request: web.Request) -> web.Response:
    """Keep the public task-update hook patchable for integrations."""
    return await _handle_cancel_delegation(request, task_update=apply_task_update)


def _history_prompt_for_request(
    payload: dict[str, Any],
    *,
    raw_prompt: str,
    surface_mode: str,
    context_id: str,
) -> str:
    requested = str(payload.get("display_prompt") or "").strip()
    if not requested:
        return raw_prompt
    hidden_prefix = raw_prompt[: -len(requested)] if raw_prompt.endswith(requested) else ""
    context_parts = str(context_id or "").split(":")
    if (
        surface_mode != "work"
        or len(context_parts) == 2
        or len(requested) > 4_000
        or not hidden_prefix.startswith("[Private Thomas Work onboarding context.")
        or not hidden_prefix.endswith("]\n\n")
    ):
        raise ValueError("invalid Work display_prompt")
    return requested


def _request_tools_for_chat_surface(
    app: web.Application,
    request_tools: Any,
    *,
    surface_mode: str,
    context_id: str,
    private_context: str,
) -> Any:
    """Bind connector tools only after Thomas resolved an exact Work job."""
    if request_tools is None or surface_mode != "work" or not context_id or not private_context:
        return request_tools
    return request_work_tools(app, request_tools, context_id=context_id)


def _surface_turn_controls(
    *,
    surface_mode: str,
    private_context: str,
    mode: str,
    autonomy_level: int,
    token_economy: str,
) -> tuple[str, int, str]:
    """Keep Work setup conversational while preserving the saved job dials."""
    if surface_mode == "work" and not private_context:
        return "auto", min(autonomy_level, 2), "optimal"
    return mode, autonomy_level, token_economy


def _foreground_runtime_policy(
    runtime_policy: Any,
    config: Any,
    token_economy: str,
    *,
    requested_token_economy: str,
) -> tuple[str, Any, dict[str, str]]:
    """Apply the turn's economy pass budget to the foreground specialist only."""
    applied = normalize_token_economy_level(token_economy)
    quality = runtime_policy.quality
    configured_iterations = int(getattr(quality, "max_agent_iterations", 0) or 0)
    base_iterations = configured_iterations or int(getattr(config, "max_agent_iterations", 0) or 0)
    foreground_quality = replace(
        quality,
        max_agent_iterations=compute_max_passes(applied, base_iterations),
    )
    return (
        applied,
        replace(runtime_policy, quality=foreground_quality),
        build_token_economy_meta(requested_token_economy, applied),
    )


__all__ = [
    "_history_prompt_for_request",
    "_foreground_runtime_policy",
    "_request_tools_for_chat_surface",
    "_surface_turn_controls",
    "handle_cancel_delegation",
    "handle_session_delegations",
]
