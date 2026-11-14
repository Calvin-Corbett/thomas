"""What Thomas projects were sent back for, kept after each project is gone, and told to the next team.

You said on 2026-09-25: "he is really dumb like it doenst seem like he is learning anything". A repair round's
reason lived only on its own project's record (``thomas_project.prepare_repair``), so what one team was sent back
for, the next team did again. Now every round that is stamped also lands here, as the kind of thing it came back
for -- never the whole findings -- and a new project's notes say which kinds came back most often
(:func:`lessons_note`, sent by ``thomas_project.start_thomas_project``).

The ledger is one JSON list in your Thomas data folder (``resolve_thomas_data_dir()``), never in a repo or a green,
holding the most recent :data:`MAX_RECORDS` records. It is written atomically (a temporary file, then
``os.replace``). A ledger that cannot be read or written is logged and skipped: it never stops a repair round or a
project start.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from thomas.core.config import resolve_thomas_data_dir
from thomas.server.precard import CONFLICT_HEAD, FINDINGS_HEAD, FORMER_HEADINGS, HEADINGS, MOVED_HEAD

log = logging.getLogger(__name__)

MAX_RECORDS = 200
LESSON_LINES = 5
SAID_MAX_CHARS = 200
LEDGER_NAME = "repair_ledger.json"

# The reasons ``thomas_project`` stamps (its DEV_MOVED, TOO_LARGE and SENT_BACK), spelled out here because
# ``thomas_project`` imports this module.
_DEV_MOVED, _TOO_LARGE = "dev_moved", "too_large"
MANUAL = "sent_back_by_hand"
# Each kind, in the words the next team reads. The first eight are ``report.findings_text``'s headings.
KIND_WORDS = {
    "regressed": "tests that pass on dev failed with the change",
    "added_fail": "tests the change added failed",
    "unconfirmed": "test failures the check could not settle one at a time",
    "timed_out": "a failing test's re-run on its own did not finish in time",
    "broke": "the tests could not be run with the change at all",
    "ruff": "ruff check findings the change added",
    "unformatted": "files the change left unformatted (`ruff format --check`)",
    "size": "the repo's size rule, found by the check before the card",
    "conflict": "the change would not apply to dev",
    "moved": "the change changed while it was being checked",
    _TOO_LARGE: "the change broke the repo's size rule",
    MANUAL: "sent back by hand",
}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")
_lock = threading.Lock()


def ledger_path() -> Path:
    return resolve_thomas_data_dir() / "thomas_projects" / LEDGER_NAME


def first_sentence(text: str) -> str:
    """The first sentence of a manual send-back, on one line, at most :data:`SAID_MAX_CHARS` characters."""
    words = " ".join(str(text or "").split())
    return _SENTENCE_END.split(words, maxsplit=1)[0][:SAID_MAX_CHARS].rstrip()


def _carries(text: str, key: str, heading: str) -> bool:
    """Whether *text* carries the heading of *key* in today's words or in the words it had before."""
    return any(words in text for words in (heading, *FORMER_HEADINGS.get(key, ())))


def kinds(why: str, detail: str) -> list[dict[str, str]]:
    """What a repair round came back for: one entry per kind, never the findings themselves.

    Any dev-moved round is ``conflict`` -- the check's own (``report.conflict_findings``) and the promoter's
    refusal alike. A sent-back round is sorted by how its findings start: the check's findings by each heading
    they carry, a change that moved (``handover.moved_findings``) as ``moved``, anything else as your own words.
    Findings are read in today's words and in the words they had before (``report.FORMER_HEADINGS``).
    """
    text = str(detail or "")
    if why == _DEV_MOVED or text.startswith(CONFLICT_HEAD):
        return [{"kind": "conflict"}]
    if why == _TOO_LARGE:
        return [{"kind": _TOO_LARGE}]
    if text.startswith(MOVED_HEAD):
        return [{"kind": "moved"}]
    if text.startswith(FINDINGS_HEAD):
        found = [{"kind": key} for key, heading in HEADINGS.items() if _carries(text, key, heading)]
        if found:
            return found
    return [{"kind": MANUAL, "said": first_sentence(text) or "(no reason given)"}]


def _read() -> list[dict[str, Any]]:
    """The records, oldest first; [] when there is no ledger or it cannot be read."""
    try:
        records = json.loads(ledger_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.warning("the repair ledger could not be read, so it counts as empty: %s", exc)
        return []
    return [r for r in records if isinstance(r, dict) and r.get("kind")] if isinstance(records, list) else []


def record(why: str, detail: str) -> int:
    """Add what one repair round came back for; how many records were added (0 when the ledger could not be written).

    Never raises: the round goes ahead whatever happens here.
    """
    try:
        stamp = datetime.now(timezone.utc).isoformat()
        added = [{**entry, "why": str(why), "at": stamp} for entry in kinds(why, detail)]
        with _lock:
            path = ledger_path()
            records = (_read() + added)[-MAX_RECORDS:]
            path.parent.mkdir(parents=True, exist_ok=True)
            scratch = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
            try:
                scratch.write_text(json.dumps(records, indent=1), encoding="utf-8")
                os.replace(scratch, path)
            finally:
                scratch.unlink(missing_ok=True)
        return len(added)
    except Exception as exc:  # noqa: BLE001 -- the round or start goes ahead whatever broke here
        log.warning("could not add a %s round to the repair ledger: %s", why, exc)
        return 0


def _words(entry: tuple[str, str]) -> str:
    kind, said = entry
    words = KIND_WORDS.get(kind, kind)
    return f"{words}: {said}" if said else words


def lessons_note() -> str:
    """What earlier teams were sent back for most often, most frequent first; "" when nothing is recorded."""
    try:
        counted = Counter((str(r["kind"]), str(r.get("said") or "")) for r in _read())
    except Exception as exc:  # noqa: BLE001 -- the round or start goes ahead whatever broke here
        log.warning("could not count the repair ledger: %s", exc)
        return ""
    if not counted:
        return ""
    lines = ["What earlier Thomas projects were sent back for most often (counted from their repair rounds):"]
    for entry, count in counted.most_common(LESSON_LINES):
        lines.append(f"- {count} {'time' if count == 1 else 'times'}: {_words(entry)}")
    return "\n".join(lines)


__all__ = ["KIND_WORDS", "MAX_RECORDS", "first_sentence", "kinds", "ledger_path", "lessons_note", "record"]
