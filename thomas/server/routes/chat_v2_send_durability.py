"""Make the user's message durable at SEND time, not at reply time.

Measured 2026-08-05, live server: /api/chats listed 476 chats and none of them
contained the message the user had just sent. The cause was structural -- the
only ``session_store.save`` for a Chat V2 turn ran AFTER ``brain.process_message``
returned. Every way a turn can end early destroyed the whole turn, including
the user's own words:

* the tab is closed or navigated away -> aiohttp cancels the handler task,
  ``CancelledError`` skips the save;
* the model or a tool crashes mid-reply -> the ``except`` path emitted an error
  event and saved nothing;
* the server dies -> nothing was ever on disk to begin with.

The fix is to write the user turn to the session store the moment the request
is accepted (``persist_user_turn_at_send``), so the WORST outcome of an
interrupted turn is a saved user message with no reply -- never an empty store.

Two consequences are handled here rather than left to the caller:

* ``process_message`` appends the user turn itself, and the turn handler
  reloads the session from the store mid-turn (to pick up concurrent saves).
  The send-time copy is marked ``metadata={"pending_reply": True}`` so
  ``strip_pending_user_turn`` can remove exactly that one trailing message
  before the model sees the reloaded conversation. Older pending turns deeper
  in the history are real abandoned turns and are kept -- the marker on them
  is honest: that turn never received a reply.
* A turn that dies AFTER streaming part of a reply should keep that part.
  ``salvage_interrupted_turn`` appends whatever text reached the wire as an
  assistant message marked ``metadata={"interrupted": True}`` -- visibly a
  fragment, never passed off as a finished answer.
"""

from __future__ import annotations

import asyncio
import logging

from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionMeta, SessionStore

log = logging.getLogger(__name__)

# The failures a session-store save can realistically produce. Named rather
# than a bare `except Exception`, so a bug in the salvage path still surfaces
# while a storage hiccup never masks the turn's real error. Mirrors the
# run-store recorders' pattern.
_SALVAGE_SAVE_ERRORS = (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError)

PENDING_REPLY_KEY = "pending_reply"
INTERRUPTED_KEY = "interrupted"


async def persist_user_turn_at_send(
    session_store: SessionStore,
    *,
    session_id: str,
    conversation: ConversationManager,
    meta: SessionMeta | None,
    user_text: str,
) -> ConversationManager:
    """Write the user turn to the store immediately; return the pending state.

    The returned conversation (prior history + this turn's user message) is
    what an interrupted turn should fall back to. The save is forced past the
    debounce: this is the write that makes the message survive a crash, so it
    must actually hit the disk.
    """
    pending = conversation.append_message("user", user_text, metadata={PENDING_REPLY_KEY: True})
    await session_store.save(session_id, pending, meta, force=True)
    return pending


def strip_pending_user_turn(conversation: ConversationManager, *, user_text: str) -> ConversationManager:
    """Drop THIS turn's send-time user message from a store-reloaded conversation.

    Only the trailing message is examined, and only when it carries the pending
    marker AND matches this turn's text -- the send-time save wrote it last, so
    anything else at the tail belongs to history and stays.
    """
    messages = conversation.get_messages()
    if messages:
        last = messages[-1]
        metadata = last.get("metadata") if isinstance(last.get("metadata"), dict) else {}
        if last.get("role") == "user" and metadata.get(PENDING_REPLY_KEY) and last.get("content") == user_text:
            return ConversationManager(messages[:-1], version=conversation.version)
    return conversation


async def salvage_interrupted_turn(
    session_store: SessionStore,
    *,
    session_id: str,
    pending_conversation: ConversationManager,
    meta: SessionMeta | None,
    partial_text: str,
) -> ConversationManager:
    """Persist whatever reply text an interrupted turn managed to produce.

    Returns the conversation that now represents the turn's best-known state --
    the caller must treat THAT as the current conversation from here on, because
    the turn handler's trailing budget sync force-saves whatever it holds and
    would otherwise clobber this salvage with the pre-turn state (measured: a
    failed turn ended as an EMPTY stored conversation for exactly that reason).

    Best-effort by design: the user turn is already on disk from the send-time
    save, so when nothing streamed (or this save itself fails) the store still
    holds the user's message. Called from both the ``CancelledError`` path
    (abandoned tab -- the save is shielded because the task is being torn down)
    and the failure path (model/tool crash mid-reply).
    """
    text = str(partial_text or "").strip()
    if not text:
        return pending_conversation
    salvaged = pending_conversation.append_message("assistant", text, metadata={INTERRUPTED_KEY: True})
    try:
        await asyncio.shield(
            asyncio.ensure_future(session_store.save(session_id, salvaged, meta, force=True))
        )
    except asyncio.CancelledError:
        # A second cancellation arrived while saving; the shielded write keeps
        # running to completion in the background. Nothing more to do here --
        # re-raising would only hide the original cancellation semantics.
        pass
    except _SALVAGE_SAVE_ERRORS:
        # Named rather than broad, and deliberately not re-raised: this runs
        # inside the turn's OWN failure path, and letting a salvage problem
        # propagate would replace the real error with the bookkeeping one.
        # The user turn is already on disk from the send-time save.
        log.exception("Failed to salvage the interrupted turn for session %s", session_id[:12])
    return salvaged


__all__ = [
    "INTERRUPTED_KEY",
    "PENDING_REPLY_KEY",
    "persist_user_turn_at_send",
    "salvage_interrupted_turn",
    "strip_pending_user_turn",
]
