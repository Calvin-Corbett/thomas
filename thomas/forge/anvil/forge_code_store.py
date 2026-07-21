"""Disk-persistent conversation store for Forge Code sessions.

Each Forge Code conversation is persisted as its own JSON file under
``<root>/.thomas/evolve/agent/conversations/<id>.json`` so conversations
survive a server restart, are listable, and are resumable with their full
transcript and the model used per turn.

All reads are defensive: a missing or corrupt file yields ``None`` (or is
skipped during listing) rather than raising, so a single bad file can never
take down the server.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Max characters for a derived title before we truncate with an ellipsis.
_TITLE_MAX = 60
_DEFAULT_TITLE = "Untitled build"

# Renderable artifact classification by file extension. The Forge Code transcript
# shows an INLINE PREVIEW only for files whose extension maps to a kind here;
# ordinary code edits (.py, .ts, .css, ...) deliberately map to NOTHING -- they
# have no artifact card, their diff card stays the output. Kinds:
#   html     -> sandboxed <iframe> preview of the built page
#   image    -> the image rendered inline
#   markdown -> the chat's markdown renderer
#   data     -> a compact scrollable table/preview
#   pdf/document/spreadsheet/presentation -> durable downloadable output
_ARTIFACT_KINDS: dict[str, str] = {
    "html": "html",
    "htm": "html",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "svg": "image",
    "webp": "image",
    "md": "markdown",
    "markdown": "markdown",
    "csv": "data",
    "json": "data",
    "pdf": "pdf",
    "docx": "document",
    "xlsx": "spreadsheet",
    "pptx": "presentation",
}


def detect_artifacts(changed_files: list[str] | None) -> list[dict]:
    """Classify a run's written files into renderable artifact descriptors.

    Returns ``[{"file", "kind", "ext"}]`` for every changed file whose extension
    maps to a renderable or downloadable result -- and NOTHING for a
    run that only touched code (``.py`` etc.), so an ordinary edit never gets a
    fabricated preview. This is the single detector the transcript trusts: it is
    recorded onto the agent turn (so a resumed conversation re-renders identically)
    and emitted on the live ``done`` frame. Order follows ``changed_files`` with
    any HTML promoted to the front so a built web page is the headline preview.
    """
    out: list[dict] = []
    for raw in changed_files or []:
        name = str(raw or "").strip()
        if not name:
            continue
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        kind = _ARTIFACT_KINDS.get(ext)
        if kind:
            out.append({"file": name, "kind": kind, "ext": ext})
    # Stable sort -> HTML first, every other renderable in its original order.
    out.sort(key=lambda a: 0 if a["kind"] == "html" else 1)
    return out


def primary_artifact(artifacts: list[dict] | None) -> dict | None:
    """Return the HEADLINE deliverable from a detector result, or ``None``.

    ``detect_artifacts`` already promotes a built HTML page to the front, so the
    first descriptor is the right thing to feature (a web app/page over a stray
    data file). Returns ``None`` for an empty list -- a code-only run has no
    deliverable. This is the single seam the "My Stuff" registry trusts to pick
    what a build's openable output IS, kept next to the detector that produced it.
    """
    for artifact in artifacts or []:
        if isinstance(artifact, dict) and artifact.get("file"):
            return artifact
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def conversations_dir(root: str | Path) -> Path:
    """Return the conversations directory, creating it if needed."""
    path = Path(root) / ".thomas" / "evolve" / "agent" / "conversations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _conversation_path(root: str | Path, cid: str) -> Path:
    return conversations_dir(root) / f"{cid}.json"


def derive_title(message: str) -> str:
    """Derive a human title from the first non-empty line of a message.

    Truncated to ~60 chars with a trailing ellipsis when longer. Returns
    "Untitled build" for an empty/whitespace message -- never a generic
    "Conversation N".
    """
    for line in (message or "").splitlines():
        stripped = line.strip()
        if stripped:
            if len(stripped) > _TITLE_MAX:
                return stripped[:_TITLE_MAX].rstrip() + "…"
            return stripped
    return _DEFAULT_TITLE


def _new_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"fc_{stamp}_{uuid.uuid4().hex[:6]}"


def _write_conversation(root: str | Path, conversation: dict) -> dict:
    path = _conversation_path(root, conversation["id"])
    path.write_text(
        json.dumps(conversation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return conversation


def draft_conversation(
    *,
    title: str | None = None,
    source_evolve_item: dict | None = None,
) -> dict:
    """Allocate a fresh in-memory conversation without making it durable."""
    now = _now_iso()
    return {
        "id": _new_id(),
        "title": title or _DEFAULT_TITLE,
        "created_at": now,
        "updated_at": now,
        "source_evolve_item": source_evolve_item,
        "turns": [],
    }


def new_conversation(
    root: str | Path,
    *,
    title: str | None = None,
    source_evolve_item: dict | None = None,
) -> dict:
    """Allocate a fresh conversation, persist it, and return the full dict."""
    return _write_conversation(root, draft_conversation(title=title, source_evolve_item=source_evolve_item))


def _user_turn(text: str, *, request_id: str = "", request_fingerprint: str = "") -> dict:
    turn = {"role": "user", "text": text, "ts": _now_iso()}
    if request_id:
        turn.update({"request_id": request_id, "request_fingerprint": request_fingerprint})
    return turn


def persist_draft_with_user_turn(
    root: str | Path,
    conversation: dict,
    text: str,
    *,
    request_id: str = "",
    request_fingerprint: str = "",
) -> dict:
    """Persist a new draft and its first user turn in one conversation write."""
    started = dict(conversation)
    started["turns"] = [_user_turn(text, request_id=request_id, request_fingerprint=request_fingerprint)]
    if started.get("title") == _DEFAULT_TITLE:
        started["title"] = derive_title(text)
    started["updated_at"] = _now_iso()
    return _write_conversation(root, started)


def load_conversation(root: str | Path, cid: str) -> dict | None:
    """Read and parse a conversation; return None if missing or corrupt."""
    path = _conversation_path(root, cid)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        logger.debug("forge code conversation read failed (non-fatal): %s", path, exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    return data


def list_conversations(root: str | Path) -> list[dict]:
    """Return per-conversation summaries, newest-updated first.

    Each summary: ``{"id", "title", "created_at", "updated_at",
    "turn_count", "last_model"}``. Unreadable files are skipped defensively.
    """
    summaries: list[dict] = []
    for path in conversations_dir(root).glob("*.json"):
        conversation = load_conversation(root, path.stem)
        if conversation is None:
            continue
        summaries.append(_summarize(conversation))
    summaries.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return summaries


def _summarize(conversation: dict) -> dict:
    turns = conversation.get("turns") or []
    last_model = ""
    for turn in reversed(turns):
        if turn.get("role") == "agent":
            last_model = str(turn.get("model") or "")
            break
    return {
        "id": conversation.get("id", ""),
        "title": conversation.get("title", ""),
        "created_at": conversation.get("created_at", ""),
        "updated_at": conversation.get("updated_at", ""),
        "turn_count": len(turns),
        "last_model": last_model,
    }


def _clamp_title(title: str | None) -> str:
    """Normalize a title to the store's contract: trimmed, length-capped with an
    ellipsis, or the default when blank -- the same length rule ``derive_title``
    applies to a derived title, so a typed (renamed) title can never be longer."""
    stripped = (title or "").strip()
    if not stripped:
        return _DEFAULT_TITLE
    if len(stripped) > _TITLE_MAX:
        return stripped[:_TITLE_MAX].rstrip() + "…"
    return stripped


def rename_conversation(root: str | Path, cid: str, title: str) -> dict | None:
    """Set a conversation's title; return the updated dict (None if missing).

    The new title is trimmed and length-capped exactly like a derived title; a
    blank title falls back to "Untitled build" rather than persisting an empty
    label. ``updated_at`` is deliberately LEFT UNTOUCHED: a rename relabels a
    conversation, it is not new activity, so the history list keeps its order
    instead of yanking the renamed item to the top.
    """
    conversation = load_conversation(root, cid)
    if conversation is None:
        return None
    conversation["title"] = _clamp_title(title)
    return _write_conversation(root, conversation)


def delete_conversation(root: str | Path, cid: str) -> bool:
    """Delete a conversation file; return True iff a file was actually removed.

    Idempotent and defensive: deleting an unknown/already-gone conversation
    returns False rather than raising, and an OS error while unlinking is logged
    and swallowed so a locked file can never crash the server.
    """
    path = _conversation_path(root, cid)
    try:
        if not path.exists():
            return False
        path.unlink()
        return True
    except OSError:
        logger.debug("forge code conversation delete failed (non-fatal): %s", path, exc_info=True)
        return False


def append_user_turn(
    root: str | Path,
    cid: str,
    text: str,
    *,
    request_id: str = "",
    request_fingerprint: str = "",
) -> dict | None:
    """Append a user turn; title the conversation from the first message."""
    conversation = load_conversation(root, cid)
    if conversation is None:
        return None
    turns = conversation.setdefault("turns", [])
    if request_id:
        prior = next((turn for turn in turns if turn.get("request_id") == request_id), None)
        if prior is not None:
            if prior.get("text") != text or prior.get("request_fingerprint") != request_fingerprint:
                raise ValueError("request_id belongs to a different user turn")
            return conversation
    is_first = len(turns) == 0
    turns.append(_user_turn(text, request_id=request_id, request_fingerprint=request_fingerprint))
    if is_first and conversation.get("title") == _DEFAULT_TITLE:
        conversation["title"] = derive_title(text)
    conversation["updated_at"] = _now_iso()
    return _write_conversation(root, conversation)


def rollback_user_turn(
    root: str | Path,
    cid: str,
    request_id: str,
    *,
    before: dict,
    after: dict,
) -> bool:
    """Restore the exact pre-append snapshot if no concurrent edit intervened."""
    current = load_conversation(root, cid)
    turns = (current or {}).get("turns") or []
    if current != after or not turns:
        return False
    last = turns[-1]
    if last.get("role") != "user" or last.get("request_id") != request_id:
        return False
    _write_conversation(root, dict(before))
    return True


def append_agent_turn(
    root: str | Path,
    cid: str,
    *,
    model: str,
    transcript: str,
    changed_files: list[str],
    returncode: int | None,
    ok: bool,
    noop: bool,
    reason: str,
    run_id: str = "",
    report: dict | None = None,
) -> dict | None:
    """Append an agent turn carrying the model used and the run outcome."""
    conversation = load_conversation(root, cid)
    if conversation is None:
        return None
    turn = {
        "role": "agent",
        "model": model,
        "ts": _now_iso(),
        "transcript": transcript,
        "changed_files": list(changed_files or []),
        # Renderable/downloadable results this run produced,
        # recorded so a resumed conversation re-renders the artifact cards
        # exactly as the live run showed them. Empty for a code-only run.
        "artifacts": detect_artifacts(changed_files),
        "returncode": returncode,
        "ok": ok,
        "noop": noop,
        "reason": reason,
        "run_id": str(run_id or ""),
    }
    if report is not None:
        # CAP-141: the structured post-run report (attempts/validations/risks/
        # pointers/rubric), persisted so a reloaded conversation re-renders it.
        turn["report"] = report
    conversation.setdefault("turns", []).append(turn)
    conversation["updated_at"] = _now_iso()
    return _write_conversation(root, conversation)


def _agent_reply_text(turn: dict) -> str:
    """Best-effort natural-language reply for one agent turn.

    The stored transcript is a mix of forge-event JSON lines and the dispatch
    CLI's own echo. New transcripts identify the completed handoff with an
    explicit ``final`` event; legacy transcripts only have ``say`` events. Prefer
    the last final so progress chatter never pollutes the next prompt, then fall
    back to de-duplicated say text and finally the recorded reason. Defensive: a
    malformed line is skipped, never raised on.
    """
    says: list[str] = []
    finals: list[str] = []
    for raw in str(turn.get("transcript") or "").split("\n"):
        line = raw.strip()
        if not line or line[0] != "{":
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("fc") in {"final", "say"}:
            text = str(obj.get("text") or "").strip()
            if obj.get("fc") == "final" and text:
                finals.append(text)
            elif text and (not says or says[-1] != text):
                says.append(text)
    joined = "\n\n".join(says).strip()
    return (finals[-1] if finals else joined) or str(turn.get("reason") or "").strip()


def history_turns(root: str | Path, cid: str, *, drop_last_user: bool = True) -> list[dict]:
    """Return a clean ``[{"role", "text"}]`` history for the prompt composer.

    Prior turns of conversation ``cid`` as plain natural language — user text
    verbatim, the agent's reply extracted from its forge-event transcript. The
    final user turn (the message being dispatched *now*) is dropped by default so
    it is not duplicated alongside the goal in the prompt. Returns ``[]`` for an
    unknown/empty conversation so the caller simply runs without history.
    """
    conversation = load_conversation(root, cid) if cid else None
    if conversation is None:
        return []
    out: list[dict] = []
    for turn in conversation.get("turns") or []:
        role = turn.get("role")
        if role == "user":
            text = str(turn.get("text") or "").strip()
            if text:
                out.append({"role": "user", "text": text})
        elif role == "agent":
            text = _agent_reply_text(turn)
            if text:
                out.append({"role": "assistant", "text": text})
    if drop_last_user and out and out[-1]["role"] == "user":
        out.pop()
    return out


def group_by_day(summaries: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Bucket summaries by the date of ``updated_at``, most-recent day first.

    Day labels are "Today"/"Yesterday" relative to ``now`` (injectable for
    testing), otherwise the ISO "YYYY-MM-DD" date. Items within a group keep
    their incoming (newest-first) order.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    today = now.date()
    yesterday = today - timedelta(days=1)

    groups: dict[object, list[dict]] = {}
    order: list[object] = []
    for summary in summaries:
        day = _date_of(summary.get("updated_at"))
        if day not in groups:
            groups[day] = []
            order.append(day)
        groups[day].append(summary)

    # Real dates sort most-recent first; None (unparseable) dates sort last.
    order.sort(key=lambda d: (d is not None, d if d is not None else today.min), reverse=True)

    result: list[dict] = []
    for day in order:
        if day == today:
            label = "Today"
        elif day == yesterday:
            label = "Yesterday"
        elif day is None:
            label = ""
        else:
            label = day.isoformat()
        result.append({"day": label, "items": groups[day]})
    return result


def _date_of(value: object):
    """Parse the date portion of an ISO timestamp; None if unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None
