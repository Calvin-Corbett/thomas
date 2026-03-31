"""Shared helpers for Discord-owned chat controls and context parsing."""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntime
from thomas.server.app_keys import ChatSession

_WHITESPACE_RE = re.compile(r"\s+")
_SEARCH_PATTERNS = (
    re.compile(r"^(?:search|find)\s+discord\s+(?:history|conversations?)\s+(?:for|about)\s+(.+)$", re.I),
    re.compile(r"^what\s+did\s+(?:we|i)\s+say\s+on\s+discord\s+(?:for|about)\s+(.+)$", re.I),
)
_STATUS_PATTERN = re.compile(r"^(?:show\s+)?discord\s+status$", re.I)
_STATUS_ALT_PATTERN = re.compile(r"^what(?:'s| is)\s+discord\s+status$", re.I)
_START_PATTERN = re.compile(r"^start\s+(?:the\s+)?discord\s+bot$", re.I)
_STOP_PATTERN = re.compile(r"^stop\s+(?:the\s+)?discord\s+bot$", re.I)
_RESTART_PATTERN = re.compile(r"^restart\s+(?:the\s+)?discord\s+bot$", re.I)
_RECENT_PATTERN = re.compile(r"^(?:show|list)\s+(?:recent\s+)?discord\s+(?:history|conversations?)$", re.I)
_SESSION_PATTERN = re.compile(r"^(?:show|open)\s+discord\s+(?:session|conversation)\s+(.+)$", re.I)


@dataclass(frozen=True)
class DiscordRequestContext:
    is_discord_origin: bool
    source: str
    surface: str
    client: str
    session_id: str
    scope_key: str
    user_id: str
    display_name: str
    guild_id: str
    channel_id: str
    request_kind: str
    slash_command: str
    is_owner: bool
    owner_only_mode: bool
    owner_authorized_for_settings_actions: bool
    granted_capabilities: tuple[str, ...]

    def history_metadata(self) -> dict[str, Any]:
        return {
            "scope_key": self.scope_key,
            "user_id": self.user_id,
            "display_name": self.display_name,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "surface": self.surface,
            "request_kind": self.request_kind,
            "owner": self.is_owner,
            "granted_capabilities": list(self.granted_capabilities),
        }


def build_discord_request_context(payload: dict[str, Any], session_id: str) -> DiscordRequestContext:
    metadata = payload.get("metadata")
    metadata_obj = metadata if isinstance(metadata, dict) else {}
    discord_raw = metadata_obj.get("discord")
    discord = discord_raw if isinstance(discord_raw, dict) else {}
    source = str(metadata_obj.get("source") or payload.get("source") or "").strip().lower()
    surface = str(payload.get("surface") or discord.get("surface") or "").strip().lower()
    client = str(payload.get("client") or discord.get("client") or "").strip().lower()
    is_discord_origin = (
        str(payload.get("channel") or "").strip().lower() == "discord"
        or source.startswith("discord")
        or surface == "discord"
        or client == "discord_bot"
        or bool(discord)
    )
    granted_capabilities = discord.get("granted_capabilities")
    if not isinstance(granted_capabilities, list):
        granted_capabilities = []
    normalized_capabilities = tuple(
        sorted({str(item or "").strip().lower() for item in granted_capabilities if str(item or "").strip()})
    )
    return DiscordRequestContext(
        is_discord_origin=is_discord_origin,
        source=source,
        surface=surface or ("discord" if is_discord_origin else ""),
        client=client,
        session_id=str(session_id or "").strip(),
        scope_key=str(metadata_obj.get("scope_key") or "").strip(),
        user_id=str(discord.get("user_id") or "").strip(),
        display_name=str(discord.get("display_name") or "").strip(),
        guild_id=str(discord.get("guild_id") or "").strip(),
        channel_id=str(discord.get("channel_id") or "").strip(),
        request_kind=str(discord.get("request_kind") or "message").strip().lower(),
        slash_command=str(discord.get("slash_command") or "").strip(),
        is_owner=bool(discord.get("owner")),
        owner_only_mode=bool(discord.get("owner_only_mode")),
        owner_authorized_for_settings_actions=bool(discord.get("owner_authorized_for_settings_actions")),
        granted_capabilities=normalized_capabilities,
    )


def match_discord_chat_command(text: str) -> dict[str, str] | None:
    normalized = _WHITESPACE_RE.sub(" ", str(text or "").strip())
    if not normalized:
        return None
    if _START_PATTERN.match(normalized):
        return {"kind": "lifecycle", "action": "start"}
    if _STOP_PATTERN.match(normalized):
        return {"kind": "lifecycle", "action": "stop"}
    if _RESTART_PATTERN.match(normalized):
        return {"kind": "lifecycle", "action": "restart"}
    if _STATUS_PATTERN.match(normalized) or _STATUS_ALT_PATTERN.match(normalized):
        return {"kind": "status"}
    if _RECENT_PATTERN.match(normalized):
        return {"kind": "recent"}
    for pattern in _SEARCH_PATTERNS:
        match = pattern.match(normalized)
        if match:
            return {"kind": "search", "query": str(match.group(1) or "").strip()}
    session_match = _SESSION_PATTERN.match(normalized)
    if session_match:
        return {"kind": "session", "session_id": str(session_match.group(1) or "").strip()}
    return None


def format_discord_status_message(payload: dict[str, Any]) -> str:
    bridge = payload.get("bridge") if isinstance(payload.get("bridge"), dict) else {}
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    conversations = payload.get("conversations") if isinstance(payload.get("conversations"), dict) else {}
    lines = [
        "Discord bridge status:",
        f"Runtime: {str(bridge.get('status') or 'unknown')}",
        f"Enabled: {'on' if bridge.get('enabled') else 'off'}",
        f"Configured: {'yes' if bridge.get('configured') else 'no'}",
        f"Mention mode: {'mentions only' if config.get('require_mention') else 'reply to everyone'}",
        f"Owner-only mode: {'on' if config.get('owner_only_mode') else 'off'}",
        f"Wake word: {'required' if runtime.get('voice_require_wake_word') else 'not required'}",
        f"Indexed Discord turns: {int(conversations.get('indexed_turns') or 0)} across {int(conversations.get('indexed_sessions') or 0)} sessions",
    ]
    last_error = str(bridge.get("last_error") or "").strip()
    if last_error:
        lines.append(f"Last error: {last_error.splitlines()[-1][:240]}")
    return "\n".join(lines)


def format_discord_recent_message(sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return "No indexed Discord conversations yet."
    lines = ["Recent Discord conversations:"]
    for row in sessions[:6]:
        session_id = str(row.get("session_id") or "").strip()
        preview = str(row.get("preview") or "").strip() or "No preview yet."
        scope_key = str(row.get("scope_key") or "").strip() or "unknown scope"
        updated_at = str(row.get("updated_at") or "").strip() or "unknown time"
        lines.append(
            f"- {session_id} | {scope_key} | {updated_at} | {int(row.get('turn_count') or 0)} turns | {preview[:140]}"
        )
    return "\n".join(lines)


def format_discord_search_message(query: str, hits: list[dict[str, Any]]) -> str:
    if not hits:
        return f'No indexed Discord history matched "{query}".'
    lines = [f'Discord history matches for "{query}":']
    for hit in hits[:6]:
        session_id = str(hit.get("session_id") or "").strip()
        created_at = str(hit.get("created_at") or "").strip() or "unknown time"
        excerpt = str(hit.get("excerpt") or "").strip() or "No excerpt available."
        lines.append(f"- {created_at} | {session_id} | {excerpt[:180]}")
    return "\n".join(lines)


def format_discord_session_message(payload: dict[str, Any]) -> str:
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    turns = payload.get("turns") if isinstance(payload.get("turns"), list) else []
    session_id = str(session.get("session_id") or "").strip() or "unknown session"
    scope_key = str(session.get("scope_key") or "").strip() or "unknown scope"
    lines = [f"Discord session {session_id} ({scope_key}):"]
    if not turns:
        lines.append("No indexed turns in that session yet.")
        return "\n".join(lines)
    for turn in turns[-6:]:
        created_at = str(turn.get("created_at") or "").strip() or "unknown time"
        speaker = str(turn.get("display_name") or "Discord user").strip()
        user_text = str(turn.get("user_text") or "").strip()
        assistant_text = str(turn.get("assistant_text") or "").strip()
        lines.append(f"- {created_at} | {speaker}: {user_text[:120]}")
        if assistant_text:
            lines.append(f"  Thomas: {assistant_text[:160]}")
    return "\n".join(lines)


def discord_command_denied_message() -> str:
    return "Discord bridge controls and history lookup are owner-only from Discord."


async def stream_static_chat_response(
    *,
    request: web.Request,
    session: ChatSession,
    sid: str,
    user_text: str,
    reply_text: str,
    token_economy_meta: dict[str, Any],
    start_t: float,
) -> web.StreamResponse:
    if not isinstance(session.conversation, list):
        session.conversation = []
    session.conversation.append({"role": "user", "content": str(user_text or "")})
    session.conversation.append({"role": "assistant", "content": str(reply_text or "")})
    session.last_user_message = str(user_text or "")
    session.last_assistant_message = str(reply_text or "")
    run_id = f"discord-quick-{secrets.token_urlsafe(8)}"
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Cache-Control": "no-cache",
        },
    )
    await response.prepare(request)
    events = [
        {"type": "text", "text": reply_text, "seq": 0, "run_id": run_id},
        {
            "type": "done",
            "text": reply_text,
            "iterations": 1,
            "tool_calls": 0,
            "usage": {},
            "run_usage": {},
            "session_usage": {},
            "token_report": {"token_economy": dict(token_economy_meta or {})},
            "elapsed_ms": float((time.monotonic() - start_t) * 1000.0),
            "session_id": sid,
            "seq": 1,
            "run_id": run_id,
        },
    ]
    for event in events:
        await response.write(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n")
    await response.write_eof()
    return response


async def maybe_handle_discord_chat_command(
    *,
    request: web.Request,
    session: ChatSession,
    sid: str,
    text: str,
    cfg: Any,
    token_economy_meta: dict[str, Any],
    start_t: float,
    request_context: DiscordRequestContext,
) -> web.StreamResponse | None:
    command = match_discord_chat_command(text)
    if command is None:
        return None
    runtime = DiscordBridgeRuntime(cfg)
    if request_context.is_discord_origin and not request_context.is_owner:
        reply_text = discord_command_denied_message()
        runtime.append_history_turn(
            session_id=sid,
            user_text=text,
            assistant_text=reply_text,
            context=request_context.history_metadata(),
            tool_calls=0,
        )
        return await stream_static_chat_response(
            request=request,
            session=session,
            sid=sid,
            user_text=text,
            reply_text=reply_text,
            token_economy_meta=token_economy_meta,
            start_t=start_t,
        )

    kind = command["kind"]
    if kind == "status":
        reply_text = format_discord_status_message(runtime.status())
    elif kind == "recent":
        reply_text = format_discord_recent_message(runtime.list_sessions(limit=8))
    elif kind == "search":
        query = command.get("query", "")
        reply_text = format_discord_search_message(query, runtime.search_history(query=query, limit=8))
    elif kind == "session":
        session_id = command.get("session_id", "")
        reply_text = format_discord_session_message(runtime.get_session_context(session_id, limit=10))
    else:
        action = command.get("action", "")
        if action == "start":
            reply_text = format_discord_status_message(runtime.start())
        elif action == "stop":
            reply_text = format_discord_status_message(runtime.stop())
        elif action == "restart":
            reply_text = format_discord_status_message(runtime.restart())
        else:
            return None

    if request_context.is_discord_origin:
        runtime.append_history_turn(
            session_id=sid,
            user_text=text,
            assistant_text=reply_text,
            context=request_context.history_metadata(),
            tool_calls=0,
        )
    return await stream_static_chat_response(
        request=request,
        session=session,
        sid=sid,
        user_text=text,
        reply_text=reply_text,
        token_economy_meta=token_economy_meta,
        start_t=start_t,
    )
