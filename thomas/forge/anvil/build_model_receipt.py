"""Which model actually answered a Build run, and where that fact is kept.

A Build turn recorded the model it ASKED for — ``claude:opus`` — and nothing
else. Claude Code says which model it really started, twice: a ``system``/
``init`` event at the top of the stream, and ``modelUsage`` on the terminal
``result``, keyed by exact model id. Both were dropped on the floor, so a run
last night could be labelled Opus with no way, ever, to find out which Opus.

This module is the whole of that repair:

* ``engine_model_events`` reads the exact ids out of one stream-json line and
  turns them into ``{"fc": "meta", "receipt": "model", ...}`` forge events,
  which the translator emits into the run transcript like any other event.
* ``engine_models_in_transcript`` reads them back out of a stored transcript,
  which is how the server records the model on the turn after the run ends.

Kept beside the translator rather than inside it because the reader and the
writer of this one fact belong together: a change to the event's shape has to
move both, and having them in one file is what makes that obvious.
"""

from __future__ import annotations

import json
from typing import Any

# A forge event naming the model the ENGINE reported it ran. Its kind is the
# existing ``meta`` -- a build-status line -- so the Build view, live and on a
# reopened conversation, already shows it as one: a kind of its own fell through
# to the agent's-speech bubble, and teaching the view a new kind meant growing
# 047_evolve_agent_chat.js, which is past the size rule's hard limit. The
# ``receipt`` key is what tells this meta line apart for the readers below.
# ``model`` rather than ``text`` carries the id, because forge_code_http_stream
# already forwards a ``model`` key to the browser.
MODEL_EVENT_KIND = "meta"
RECEIPT_KEY = "receipt"
MODEL_RECEIPT = "model"


def is_model_receipt(event: dict[str, Any]) -> bool:
    """True iff ``event`` is the engine's report of which model ran."""
    return event.get("fc") == MODEL_EVENT_KIND and event.get(RECEIPT_KEY) == MODEL_RECEIPT


def _exact_ids(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Every ``(exact_id, source)`` this one stream-json object names.

    Three places, in the order the CLI produces them. ``modelUsage`` is a dict
    keyed by model id, so its keys ARE the answer; a run that switched models
    mid-stream names more than one and every one is kept.
    """
    found: list[tuple[str, str]] = []
    if payload.get("type") == "system" and payload.get("subtype") == "init":
        found.append((str(payload.get("model") or ""), "init"))
    message = payload.get("message")
    if payload.get("type") == "assistant" and isinstance(message, dict):
        found.append((str(message.get("model") or ""), "assistant"))
    if payload.get("type") == "result":
        usage = payload.get("modelUsage")
        if isinstance(usage, dict):
            found.extend((str(model_id or ""), "modelUsage") for model_id in usage)
    return [(model_id.strip(), source) for model_id, source in found if str(model_id or "").strip()]


def reported_model_events(found: list[tuple[str, str]], seen: list[str]) -> list[dict[str, Any]]:
    """Forge ``model`` events for the ``(exact_id, source)`` pairs not already in ``seen``.

    ``seen`` is the run's ordered list of ids and is APPENDED TO, so an assistant
    message repeating the model on all forty of its events produces one event.
    Both engines come through here: Claude Code's stream (``engine_model_events``)
    and the GPT loop's provider report (``dispatch_agent_loop_translator``).
    """
    events: list[dict[str, Any]] = []
    for model_id, source in found:
        model_id = str(model_id or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.append(model_id)
        events.append(
            {
                "fc": MODEL_EVENT_KIND,
                RECEIPT_KEY: MODEL_RECEIPT,
                "model": model_id,
                "source": str(source or ""),
                # The status line the Build view shows for it.
                "text": f"Ran on {model_id}",
            }
        )
    return events


def engine_model_events(payload: dict[str, Any], seen: list[str]) -> list[dict[str, Any]]:
    """Forge ``model`` events for the exact ids one Claude stream-json object names."""
    return reported_model_events(_exact_ids(payload), seen)


def started_model(event: dict[str, Any]) -> str:
    """The exact id when ``event`` is Claude Code's report of the model it STARTED, else "".

    Only the ``init`` receipt answers what an alias starts. ``modelUsage`` also
    lists every helper model the run called -- a run on ``claude-opus-5-5`` that
    used ``claude-haiku-4-5-20251001`` for a side task names both -- so teaching
    the alias memory from every receipt made the menu say ``opus`` started Haiku.
    """
    if not is_model_receipt(event) or event.get("source") != "init":
        return ""
    return str(event.get("model") or "").strip()


def _receipts_in_transcript(transcript_text: str) -> list[dict[str, Any]]:
    """Every model receipt a stored transcript holds, in order.

    Defensive in the same way the verdict reader is: a transcript is a mix of
    forge-event JSON lines and whatever else the child process printed, so a
    line that does not parse is skipped rather than raised on.
    """
    receipts: list[dict[str, Any]] = []
    for raw_line in str(transcript_text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("{") or f'"{RECEIPT_KEY}"' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and is_model_receipt(event):
            receipts.append(event)
    return receipts


def engine_models_in_transcript(transcript_text: str) -> list[str]:
    """The exact model ids a stored transcript recorded, first seen first."""
    models: list[str] = []
    for event in _receipts_in_transcript(transcript_text):
        model_id = str(event.get("model") or "").strip()
        if model_id and model_id not in models:
            models.append(model_id)
    return models


def started_model_in_transcript(transcript_text: str) -> str:
    """The model Claude Code reported STARTING in a stored transcript, or "" (see ``started_model``)."""
    for event in _receipts_in_transcript(transcript_text):
        model_id = started_model(event)
        if model_id:
            return model_id
    return ""


def engine_model_from_transcript(transcript_text: str) -> str:
    """The one exact id to record on the turn, or "".

    The FIRST is the answer, not the last: it is the ``init`` event, which names
    the model the run started on. A later id means the engine moved (a fallback,
    a compaction pass); ``engine_models_in_transcript`` keeps all of them for a
    caller that needs the whole story.
    """
    models = engine_models_in_transcript(transcript_text)
    return models[0] if models else ""
