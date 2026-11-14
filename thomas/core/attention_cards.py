"""Cards Thomas puts beside the conversation to tell you something, and what you answered on them.

A card is a small thing with a title: a notice, a question with buttons, a reply box, a picture, a preview of a page
Thomas built, or a layout he wrote himself. The page draws the open ones in the empty space left of the conversation
(``thomas/server/web/js/attention_cards.js``). Everything here is kept in memory: a card is for now, and a restart
starts with none.

Nothing a card carries is trusted to be safe to draw. A picture or a preview may only come from this server or from
this PC's own loopback address, where Thomas serves what he builds; a layout he wrote is text the page puts in a
sandboxed frame with no network. A card cannot make the page call anything: choosing a button or sending a reply
records your answer here, and whoever showed the card reads it back.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from thomas.core.attention_blocks import clean_blocks

KINDS = ("notice", "question", "reply", "image", "preview", "html", "widget")
TONES = ("info", "done", "warn", "ask")
MAX_OPEN = 12
MAX_OPTIONS = 4
MAX_HTML = 20_000
DEFAULT_TTL_S = 300.0
ANSWER_KEPT_S = 3600.0
# A dismissed card with a key stays quiet this long, so a warning you closed does not come straight back.
QUIET_AFTER_DISMISS_S = 600.0
_PICTURE = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$")
_THIS_PC = ("127.0.0.1", "localhost")


def _is_local(text: str) -> bool:
    """Whether a browser would load ``text`` from this server or from this PC, read the way a browser reads it.

    A browser treats a backslash as a slash and drops tabs and line breaks, so ``/\\example.com`` and a ``//`` split by
    a tab both leave this PC. Those characters are refused outright, and the rest is parsed, never matched by prefix.
    """
    if "\\" in text or any(char.isspace() or ord(char) < 32 for char in text):
        return False
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        return False
    if not parts.scheme and not parts.netloc:
        return parts.path.startswith("/") and not parts.path.startswith("//")
    return parts.scheme in ("http", "https") and host in _THIS_PC and not parts.username and not parts.password


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _address(value: Any, *, picture: bool) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _is_local(text) or (picture and len(text) <= 400_000 and _PICTURE.match(text)):
        return text
    raise ValueError("a card may only show a picture or a page from Thomas himself or from this PC (127.0.0.1)")


def _options(value: Any) -> list[dict[str, str]]:
    rows = value if isinstance(value, list) else []
    if len(rows) > MAX_OPTIONS:
        raise ValueError(f"a card takes at most {MAX_OPTIONS} buttons")
    found: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        label = _text(row.get("label") if isinstance(row, dict) else row, 40)
        if not label:
            raise ValueError("every button needs a label")
        key = _text(row.get("id") if isinstance(row, dict) else "", 40) or f"option-{index + 1}"
        option = {"id": key, "label": label}
        # The one thing a button may do besides answer: open a Build task the page already knows how to open.
        task = _text(row.get("open_task") if isinstance(row, dict) else "", 80)
        if task:
            option["open_task"] = task
        found.append(option)
    if len({row["id"] for row in found}) != len(found):
        raise ValueError("two buttons on one card cannot share an id")
    return found


def card_from(spec: Any, *, source: str) -> dict[str, Any]:
    """A card built from what was asked for, or ``ValueError`` saying what is wrong with it."""
    if not isinstance(spec, dict):
        raise ValueError("a card is an object with at least a title")
    kind = str(spec.get("kind") or "notice")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
    title = _text(spec.get("title"), 120)
    if not title:
        raise ValueError("a card needs a title")
    tone = str(spec.get("tone") or ("ask" if kind in ("question", "reply") else "info"))
    if tone not in TONES:
        raise ValueError(f"tone must be one of: {', '.join(TONES)}")
    options = _options(spec.get("options"))
    if kind == "question" and not options:
        raise ValueError("a question needs at least one button")
    html = str(spec.get("html") or "")
    if len(html) > MAX_HTML:
        raise ValueError(f"a layout may be at most {MAX_HTML} characters")
    if kind == "html" and not html.strip():
        raise ValueError("an html card needs its html")
    image = _address(spec.get("image_url"), picture=True)
    preview = _address(spec.get("preview_url"), picture=False)
    if kind == "image" and not image:
        raise ValueError("an image card needs image_url")
    if kind == "preview" and not preview:
        raise ValueError("a preview card needs preview_url")
    # A widget is blocks the page draws natively (thomas.core.attention_blocks). It stays until closed, and its
    # buttons answer the way a question's do.
    blocks = clean_blocks(spec.get("blocks")) if kind == "widget" else []
    for block in blocks:
        options = [
            *options,
            *[row for row in block.get("options", []) if row["id"] not in {held["id"] for held in options}],
        ]
    try:
        every = float(spec.get("every_seconds") or 0.0)
    except (TypeError, ValueError):
        raise ValueError("every_seconds must be a number of seconds, or 0 for a widget that does not refresh") from None
    waits = kind in ("question", "reply", "widget")
    try:
        ttl = float(spec.get("ttl_seconds", 0.0 if waits else DEFAULT_TTL_S))
    except (TypeError, ValueError):
        raise ValueError("ttl_seconds must be a number of seconds, or 0 to stay until closed") from None
    now = time.time()
    return {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "tone": tone,
        "title": title,
        "body": str(spec.get("body") or "").strip()[:600],
        "options": options,
        "image_url": image,
        "preview_url": preview,
        "html": html,
        "blocks": blocks,
        "source_blocks": blocks,
        "every": min(max(every, 2.0), 3600.0) if every > 0 else 0.0,
        "template": _text(spec.get("template"), 40),
        "refreshed": now,
        "key": _text(spec.get("key"), 80),
        "source": source,
        "created": now,
        "expires": now + min(max(ttl, 5.0), 86_400.0) if ttl > 0 else 0.0,
        "state": "open",
        "answer": None,
    }


class CardStore:
    """Every card shown since the server started that is still open, or was answered within the hour."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cards: dict[str, dict[str, Any]] = {}
        self._quiet: dict[str, float] = {}
        # Set by the row: turns a widget's blocks into what to draw now, filling live readings and switches.
        self.resolver: Any = None

    def _sweep(self, now: float) -> None:
        for card_id, card in list(self._cards.items()):
            lapsed = card["state"] == "open" and card["expires"] and card["expires"] <= now
            stale = card["state"] != "open" and now - card.get("closed", now) > ANSWER_KEPT_S
            if lapsed or stale:
                del self._cards[card_id]
        open_cards = sorted((c for c in self._cards.values() if c["state"] == "open"), key=lambda c: c["created"])
        for card in open_cards[: max(0, len(open_cards) - MAX_OPEN)]:
            del self._cards[card["id"]]

    def show(self, spec: Any, *, source: str = "thomas") -> dict[str, Any] | None:
        """Show a card. One with the ``key`` of an open card replaces its words in place; ``None`` while that key is quiet."""
        card = card_from(spec, source=source)
        now = card["created"]
        if card["blocks"] and self.resolver is not None:
            card["blocks"] = self.resolver(card["source_blocks"])
        with self._lock:
            self._sweep(now)
            if card["key"]:
                if self._quiet.get(card["key"], 0.0) > now:
                    return None
                for held in self._cards.values():
                    if held["state"] == "open" and held["key"] == card["key"]:
                        held.update(
                            {
                                k: card[k]
                                for k in (
                                    "kind",
                                    "tone",
                                    "title",
                                    "body",
                                    "options",
                                    "image_url",
                                    "preview_url",
                                    "html",
                                    "blocks",
                                    "source_blocks",
                                    "every",
                                    "template",
                                    "expires",
                                )
                            }
                        )
                        return dict(held)
            self._cards[card["id"]] = card
            return dict(card)

    def refresh(self, *, everything: bool = False) -> int:
        """Fill the live blocks of each open widget that is due again. Answers how many it redrew.

        The readings are taken outside the lock: one may read a file, and a page asking for the cards must not wait
        on it.
        """
        if self.resolver is None:
            return 0
        now = time.time()
        with self._lock:
            due = [
                (card["id"], card["source_blocks"])
                for card in self._cards.values()
                if card["state"] == "open"
                and card["blocks"]
                and card["every"]
                and (everything or now - card["refreshed"] >= card["every"])
            ]
        drawn = [(card_id, self.resolver(blocks)) for card_id, blocks in due]
        with self._lock:
            for card_id, blocks in drawn:
                held = self._cards.get(card_id)
                if held is not None and held["state"] == "open":
                    held.update({"blocks": blocks, "refreshed": now})
        return len(drawn)

    def open_cards(self) -> list[dict[str, Any]]:
        """The cards to draw now, newest first."""
        with self._lock:
            self._sweep(time.time())
            found = [dict(card) for card in self._cards.values() if card["state"] == "open"]
        return sorted(found, key=lambda card: card["created"], reverse=True)

    def read(self, card_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._sweep(time.time())
            card = self._cards.get(str(card_id))
            return dict(card) if card else None

    def act(self, card_id: str, action: str, value: Any = None) -> dict[str, Any]:
        """Close a card with what you did: ``dismiss``, ``choose`` (a button's id) or ``reply`` (your words)."""
        now = time.time()
        with self._lock:
            card = self._cards.get(str(card_id))
            if card is None or card["state"] != "open":
                raise KeyError("that card is no longer open")
            if action == "dismiss":
                card["state"] = "dismissed"
                if card["key"]:
                    self._quiet[card["key"]] = now + QUIET_AFTER_DISMISS_S
            elif action == "choose":
                chosen = next((row for row in card["options"] if row["id"] == str(value)), None)
                if chosen is None:
                    raise ValueError("that card has no such button")
                card["state"] = "answered"
                card["answer"] = {"option": chosen["id"], "label": chosen["label"], "at": now}
            elif action == "reply":
                words = str(value or "").strip()[:2000]
                if card["kind"] != "reply" or not words:
                    raise ValueError("only a reply card takes words, and it needs some")
                card["state"] = "answered"
                card["answer"] = {"text": words, "at": now}
            else:
                raise ValueError("action must be dismiss, choose or reply")
            card["closed"] = now
            return dict(card)


STORE = CardStore()


def load_card(cpu: float, memory: float, cap: float, *, margin: float = 5.0) -> dict[str, Any] | None:
    """The card for a PC close to its load limit, or ``None`` when there is room or no limit is set."""
    if cap <= 0 or max(cpu, memory) < cap - margin:
        return None
    what = "CPU" if cpu >= memory else "memory"
    return {
        "kind": "notice",
        "tone": "warn",
        "key": "machine-load",
        "title": f"This PC's {what} is close to the limit",
        "body": f"CPU is at {cpu:.0f}% and memory at {memory:.0f}%. Thomas holds new work once either reaches {cap:.0f}%.",
        "ttl_seconds": 45,
    }


async def watch_load(store: CardStore, read: Any = None, cap: Any = None, interval: float = 10.0) -> None:
    """Until cancelled, keep one card up while this PC is close to its load limit. It lapses by itself once there is room."""
    import asyncio

    from thomas.core import machine_load

    read = read or machine_load.latest
    cap = cap or machine_load.limit
    while True:
        got = read()
        spec = load_card(got.cpu, got.memory, cap()) if got is not None else None
        if spec is not None:
            store.show(spec, source="system")
        await asyncio.sleep(interval)
