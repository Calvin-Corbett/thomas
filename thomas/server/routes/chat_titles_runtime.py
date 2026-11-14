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

import asyncio
import dataclasses
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from thomas.server.routes.work_llm_helpers import _build_llm, _extract_json

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

    # The title model (the "title" role, fast and low effort), unless a caller named a profile on purpose: naming a list
    # with the main model at its top effort was slow.
    llm = _build_llm(root, profile) if profile else _open_title_llm(root, *title_role_model(root))
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


# ---- Smart titles: named after the first prompt, and again from the whole chat after the fifth ----------------------

# The title model is a role ("title") in the advanced model settings, so it can be changed there; until it is set these
# are used. The default is whichever of the two candidates answered faster in the timing test (see the changelog).
DEFAULT_TITLE_PROFILE = "openai_codex"
DEFAULT_TITLE_MODEL = "gpt-6-luna"
DEFAULT_TITLE_EFFORT = "low"
FIRST_STAGE = 1
FULL_STAGE = 5
_CONTEXT_CHARS = 7000
_PER_MESSAGE = 500

_FIRST_PROMPT = """Turn the user's first message into a title for a chat list.

Write a SHORT title: 2 to 6 words, sentence case, no trailing punctuation, naming what the chat is ABOUT, not the
request ("fix the login redirect loop" -> "Login redirect loop"). Keep concrete nouns (files, products, errors). If the
message is too thin to name (a greeting), return exactly: New chat

Return ONLY the title.

First message:
"""

_FULL_CONTEXT = """Here is a whole conversation so far. Rename it so the title fits what it has turned out to be about.

Write a SHORT title: 2 to 6 words, sentence case, no trailing punctuation, naming the subject or the goal, not a request.
Prefer where the conversation ended up over where it began. Keep concrete nouns (files, products, errors).

Return ONLY the title.

Conversation:
"""

_title_lock = threading.Lock()


def titles_path(store_dir: Path) -> Path:
    """Beside the sessions, not inside one, so a title can change while a reply is saving."""
    return Path(store_dir).parent / "chat_titles.json"


def read_titles(store_dir: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(titles_path(store_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_title(store_dir: Path, session_id: str, title: str, stage: int) -> None:
    path = titles_path(store_dir)
    with _title_lock:
        data = read_titles(store_dir)
        data[session_id] = {"title": title, "stage": stage, "at": int(time.time())}
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".chat_titles.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(data, out, ensure_ascii=False)
            os.replace(name, path)
        except OSError:
            try:
                os.unlink(name)
            except OSError:
                pass
            raise


def title_role_model(root: Path) -> tuple[str, str, str]:
    """(profile, model id, reasoning effort) for titles: the "title" role in the advanced model settings, else defaults."""
    profile, model_id = DEFAULT_TITLE_PROFILE, DEFAULT_TITLE_MODEL
    try:
        from thomas.preferences.model_prefs import read_user_model_role_preferences

        saved_profile, saved_model = read_user_model_role_preferences(user_id="default", role="title")
        if saved_profile:
            profile, model_id = saved_profile, saved_model
        elif saved_model:
            model_id = saved_model
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        log.debug("title role preference unavailable: %s", exc)
    return profile, model_id, DEFAULT_TITLE_EFFORT


def _open_title_llm(root: Path, profile: str, model_id: str, effort: str) -> Any | None:
    try:
        from thomas.core.config import load_config
        from thomas.core.llm_slot import models

        config = load_config(Path(root) / "thomas.toml")
        base = config.get_model(profile or None)
        # Short answers, little thinking: a title is a few words, and the main model's top effort made naming slow.
        tuned = dataclasses.replace(
            base, model=model_id or base.model, reasoning_effort=effort or base.reasoning_effort, max_tokens=48
        )
        return models().open(tuned)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as exc:
        log.warning("title model could not be opened: %s", exc)
        return None


def conversation_text(messages: list[dict[str, str]]) -> str:
    """The chat for the title model: the first message always, then as much of the latest as fits."""
    lines = [
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {' '.join(m['content'].split())[:_PER_MESSAGE]}"
        for m in messages
    ]
    if not lines:
        return ""
    used = len(lines[0])
    tail: list[str] = []
    for line in reversed(lines[1:]):
        if used + len(line) > _CONTEXT_CHARS:
            break
        tail.append(line)
        used += len(line)
    return "\n".join([lines[0], *reversed(tail)])


async def name_conversation(
    root: Path, messages: list[dict[str, str]], stage: int, *, profile: str = "", model_id: str = "", effort: str = ""
) -> dict[str, Any]:
    """Ask the title model for a name. ``stage`` 1 names it from the exact first prompt, 5 from the whole chat."""
    users = [m for m in messages if m["role"] == "user"]
    if not users:
        return {"title": "", "error": "no user message"}
    default_profile, default_model, default_effort = title_role_model(root)
    profile, model_id, effort = profile or default_profile, model_id or default_model, effort or default_effort
    llm = _open_title_llm(root, profile, model_id, effort)
    if llm is None:
        return {"title": "", "error": "no model available", "model": model_id}
    if stage <= FIRST_STAGE:
        prompt = _FIRST_PROMPT + users[0]["content"][:_CONTEXT_CHARS]
    else:
        prompt = _FULL_CONTEXT + conversation_text(messages)
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(llm.chat([{"role": "user", "content": prompt}]), 45)
    except (OSError, RuntimeError, TypeError, ValueError, asyncio.TimeoutError) as exc:
        ms = int((time.perf_counter() - started) * 1000)
        return {"title": "", "error": f"model call failed: {exc}", "model": model_id, "ms": ms}
    ms = int((time.perf_counter() - started) * 1000)
    text = str((result or {}).get("text") or "").strip()
    title = _clean_title(text.splitlines()[0]) if text else ""
    return {"title": "" if title.lower() == "new chat" else title, "model": model_id, "effort": effort, "ms": ms}


def session_messages(path: Path) -> list[dict[str, str]]:
    """The user and assistant text of a saved chat, in order."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    conversation = data.get("conversation") if isinstance(data, dict) else None
    out: list[dict[str, str]] = []
    for message in (conversation or {}).get("messages") or []:
        if not isinstance(message, dict):
            continue
        role, content = str(message.get("role") or ""), message.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    return out


def register_chat_title_routes(app: Any, *, guard: Any, root: Path) -> None:
    """Register POST /api/chats/title and POST /api/chats/auto-title."""
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

    async def auto_title(request: web.Request) -> web.Response:
        """After a reply is saved: name the chat after its first prompt, and again from the whole chat after the fifth.

        Body ``{"session_id": ...}``. ``model``, ``effort`` and ``profile`` override the title role for one call (used
        to time the models); ``stage`` forces a stage and skips the saved-state check."""
        guard(request)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        body = body if isinstance(body, dict) else {}
        session_id = str(body.get("session_id") or "").strip()
        try:
            from thomas.server.chat_app_keys import APP_SESSION_STORE

            store = app[APP_SESSION_STORE]
        except (KeyError, ImportError):
            return web.json_response({"ok": True, "skipped": "no chat store"})
        if not session_id:
            return web.json_response({"ok": True, "skipped": "no session"})
        if "/" in session_id or "\\" in session_id or ".." in session_id:
            return web.json_response({"ok": False, "error": "that is not a session id"}, status=400)
        session_path = store.path_of(session_id)
        messages = await asyncio.to_thread(session_messages, session_path)
        prompts = sum(1 for m in messages if m["role"] == "user")
        if not prompts:
            return web.json_response({"ok": True, "skipped": "nothing to name yet"})
        saved = read_titles(session_path.parent).get(session_id) or {}
        done = int(saved.get("stage") or 0)
        stage = int(body.get("stage") or 0)
        if not stage:
            if prompts >= FULL_STAGE and done < FULL_STAGE:
                stage = FULL_STAGE
            elif done < FIRST_STAGE:
                stage = FIRST_STAGE
        if not stage:
            return web.json_response({"ok": True, "skipped": "already named", "title": saved.get("title") or ""})
        timing_only = bool(body.get("model") or body.get("effort"))
        result = await name_conversation(
            root,
            messages,
            stage,
            profile=str(body.get("profile") or ""),
            model_id=str(body.get("model") or ""),
            effort=str(body.get("effort") or ""),
        )
        title = result.get("title") or ""
        if title and not timing_only:  # a timing call never changes a chat's name
            await asyncio.to_thread(write_title, session_path.parent, session_id, title, stage)
        return web.json_response({"ok": True, "stage": stage, "prompts": prompts, **result})

    app.router.add_post("/api/chats/title", chat_titles)
    app.router.add_post("/api/chats/auto-title", auto_title)


__all__ = ["name_conversation", "read_titles", "register_chat_title_routes", "title_threads", "write_title"]
