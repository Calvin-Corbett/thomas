"""Readable thread titles.

A sidebar title was the first 60 characters of whatever you happened to type
first, so the list filled with "# MASTER PROMPT — Build a Tarot Game on…" and
"send me your icons suck I want to change…". Those are prompts, not names.

This asks the model to name a batch of threads in one call: a short noun
phrase that says what the thread is ABOUT. Batched deliberately — one request
covers the whole visible page of the sidebar instead of one call per row.

Nothing here invents a title for a thread it was given no text for, and a
model answer that comes back empty or over-long is dropped rather than
written over a name the user can already read.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from thomas.server.routes.work_dashboard_runtime import _build_llm, _extract_json

log = logging.getLogger(__name__)

_MAX_ITEMS = 16
_MAX_SOURCE = 600
_MAX_TITLE = 48

_PROMPT = """You are naming saved conversation threads for a sidebar list.

For each item below, write a SHORT title: a noun phrase naming what the thread
is about, in the user's own vocabulary. Think of how a person would refer to
it a week later.

Rules:
- 2 to 6 words. Never a sentence, never trailing punctuation.
- Title Case is wrong; use sentence case ("Tarot game build", not "Tarot Game Build").
- Name the SUBJECT, not the request. "fix the login redirect loop" -> "Login redirect loop".
- Keep concrete nouns: file names, product names, error names, people.
- Never invent detail that is not in the text. If the text is too thin to name,
  return an empty string for that id and nothing else.
- Do not mention "chat", "thread", "conversation", "task", or "request".

Return ONLY a JSON object mapping each id to its title:
{"<id>": "Login redirect loop", "<id2>": ""}

Items:
"""


def _clean_title(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    # Models like to wrap a title in quotes or end it with a period.
    text = text.strip("\"'` ").rstrip(".!,;:")
    if len(text) > _MAX_TITLE:
        return ""
    # A "title" that is really a sentence is worse than the raw prompt, because
    # it looks deliberate. Reject rather than truncate into nonsense.
    if len(text.split()) > 8:
        return ""
    return text


async def title_threads(root: Path, profile: str, items: list[dict[str, Any]]) -> tuple[dict[str, str], str]:
    """Name a batch of threads. Returns (titles_by_id, error)."""
    clean: list[dict[str, str]] = []
    for row in items[:_MAX_ITEMS]:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip()
        text = " ".join(str(row.get("text") or "").split())[:_MAX_SOURCE]
        if row_id and text:
            clean.append({"id": row_id, "text": text})
    if not clean:
        return {}, "nothing to title"

    llm = _build_llm(root, profile)
    if llm is None:
        return {}, "no model available"

    listing = "\n".join(f'- id "{row["id"]}": {row["text"]}' for row in clean)
    try:
        result = await llm.chat([{"role": "user", "content": _PROMPT + listing}])
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {}, f"model call failed: {exc}"

    parsed = _extract_json(str((result or {}).get("text") or ""))
    if parsed is None:
        return {}, "model did not return valid titles"

    known = {row["id"] for row in clean}
    titles = {}
    for key, value in parsed.items():
        row_id = str(key).strip()
        if row_id not in known:
            continue
        title = _clean_title(value)
        if title:
            titles[row_id] = title
    return titles, ""


def register_chat_title_routes(app: Any, *, guard: Any, root: Path) -> None:
    """Register POST /api/chats/title."""
    from aiohttp import web

    async def chat_titles(request: web.Request) -> web.Response:
        guard(request)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        body = body if isinstance(body, dict) else {}
        items = body.get("items")
        items = items if isinstance(items, list) else []
        profile = str(body.get("profile") or "").strip()
        titles, error = await title_threads(root, profile, items)
        if error and not titles:
            # Not a failure worth shouting about: the list still works with the
            # names it already had.
            return web.json_response({"ok": True, "titles": {}, "skipped": error})
        return web.json_response({"ok": True, "titles": titles})

    app.router.add_post("/api/chats/title", chat_titles)


__all__ = ["register_chat_title_routes", "title_threads"]
