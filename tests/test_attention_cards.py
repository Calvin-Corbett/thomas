"""Attention cards: what a card may carry, what happens when you answer one, and how one is drawn (2026-11-09).

You asked for more than a chat box: "the AI could be like, hey ... and then have a panel pop up on the left side of
where the chat's not", able to show "different types of information, like even a photo", a preview of a finished
game, a question with "do this or do that", or a message with "a reply thing", and "it shouldn't be so locked in where
it doesn't have the ability to like just code its own like card and put it there."

These are the store (``thomas.core.attention_cards``), the two tools a run is lent (``thomas.server.attention_tools``)
and the drawing (``attention_card_view.js``, in node). The row's own off and on is in
``tests/test_turning_attention_off_touches_only_its_routes.py``; a change to ``thomas.server.rows.attention`` or
``thomas.server.routes.attention_routes`` runs these too.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.core import attention_cards as cards
from thomas.server.attention_tools import build_attention_tools

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas" / "server" / "web" / "js"


def test_a_card_needs_only_a_title_and_a_question_needs_a_button() -> None:
    store = cards.CardStore()
    shown = store.show({"title": "  Your   game is done  "})
    assert shown["title"] == "Your game is done" and shown["kind"] == "notice" and shown["state"] == "open"
    with pytest.raises(ValueError, match="needs a title"):
        store.show({"body": "no title"})
    with pytest.raises(ValueError, match="at least one button"):
        store.show({"title": "Which?", "kind": "question"})
    with pytest.raises(ValueError, match="at most 4 buttons"):
        store.show({"title": "Which?", "kind": "question", "options": ["a", "b", "c", "d", "e"]})
    with pytest.raises(ValueError, match="kind must be one of"):
        store.show({"title": "x", "kind": "popup"})


@pytest.mark.parametrize(
    "address",
    [
        "https://example.com/a.png",
        "//example.com/a.png",
        "http://127.0.0.1.evil.test/a.png",
        "javascript:alert(1)",
        "file:///c:/x.png",
        # A browser reads a backslash as a slash and drops tabs and line breaks, so each of these leaves this PC.
        "/\\example.com/a.png",
        "/\t/example.com/a.png",
        "/\n/example.com/a.png",
        "http://127.0.0.1\\@example.com/a.png",
        "http://127.0.0.1@example.com/a.png",
        "http://user:pw@127.0.0.1/a.png",
        "http://localhost.example.com/a.png",
        "ftp://127.0.0.1/a.png",
    ],
)
def test_a_picture_or_a_preview_from_anywhere_but_this_pc_is_refused(address: str) -> None:
    store = cards.CardStore()
    with pytest.raises(ValueError, match="from Thomas himself or from this PC"):
        store.show({"title": "x", "kind": "image", "image_url": address})
    with pytest.raises(ValueError, match="from Thomas himself or from this PC"):
        store.show({"title": "x", "kind": "preview", "preview_url": address})


def test_a_picture_or_a_preview_thomas_serves_is_taken() -> None:
    store = cards.CardStore()
    assert store.show({"title": "x", "kind": "image", "image_url": "/api/evolve/agent/artifact/c/pong.png"})
    assert store.show({"title": "x", "kind": "preview", "preview_url": "http://127.0.0.1:9123/__enter/abc"})
    assert store.show({"title": "x", "kind": "image", "image_url": "data:image/png;base64,iVBORw0KGgo="})
    with pytest.raises(ValueError):
        store.show({"title": "x", "kind": "preview", "preview_url": "data:text/html;base64,PGI+"})


def test_choosing_a_button_or_sending_a_reply_is_kept_for_whoever_asked() -> None:
    store = cards.CardStore()
    question = store.show(
        {"title": "Ship it?", "kind": "question", "options": [{"id": "yes", "label": "Ship"}, "Wait"]}
    )
    assert [row["id"] for row in question["options"]] == ["yes", "option-2"]
    with pytest.raises(ValueError, match="no such button"):
        store.act(question["id"], "choose", "maybe")
    answered = store.act(question["id"], "choose", "yes")
    assert answered["state"] == "answered" and answered["answer"]["label"] == "Ship"
    assert store.open_cards() == [], "an answered card leaves the screen"
    assert store.read(question["id"])["answer"]["option"] == "yes", "and its answer can still be read"
    with pytest.raises(KeyError):
        store.act(question["id"], "dismiss")

    reply = store.show({"title": "Reply to Sam?", "kind": "reply"})
    with pytest.raises(ValueError, match="needs some"):
        store.act(reply["id"], "reply", "   ")
    assert store.act(reply["id"], "reply", " on my way ")["answer"]["text"] == "on my way"
    notice = store.show({"title": "Just so you know"})
    with pytest.raises(ValueError, match="only a reply card"):
        store.act(notice["id"], "reply", "hello")


def test_a_card_with_a_key_updates_in_place_and_stays_quiet_after_you_close_it() -> None:
    store = cards.CardStore()
    first = store.show({"title": "CPU at 91%", "key": "machine-load"})
    second = store.show({"title": "CPU at 96%", "key": "machine-load"})
    assert second["id"] == first["id"] and [card["title"] for card in store.open_cards()] == ["CPU at 96%"]
    store.act(first["id"], "dismiss")
    assert store.show({"title": "CPU at 97%", "key": "machine-load"}) is None, "closed is closed, for ten minutes"
    assert store.show({"title": "Something else"}) is not None


def test_a_notice_lapses_a_question_waits_and_the_list_never_grows_without_end(monkeypatch: pytest.MonkeyPatch) -> None:
    store = cards.CardStore()
    now = [1000.0]
    monkeypatch.setattr(cards.time, "time", lambda: now[0])
    store.show({"title": "Passing", "ttl_seconds": 30})
    store.show({"title": "Which?", "kind": "question", "options": ["a"]})
    now[0] += 31
    assert [card["title"] for card in store.open_cards()] == ["Which?"], "a question stays until answered"
    for index in range(cards.MAX_OPEN + 5):
        now[0] += 1
        store.show({"title": f"note {index}", "ttl_seconds": 0})
    titles = [card["title"] for card in store.open_cards()]
    assert len(titles) == cards.MAX_OPEN and titles[0] == f"note {cards.MAX_OPEN + 4}", "newest first, oldest dropped"


def test_the_tools_show_a_card_and_read_its_answer() -> None:
    store = cards.CardStore()
    show, read = build_attention_tools(store)
    assert (show.name, read.name) == ("attention_show", "attention_read")
    shown = asyncio.run(
        show.execute(
            {"title": "Run the tests again?", "kind": "question", "options": [{"id": "go", "label": "Run them"}]}
        )
    )
    assert shown.ok and shown.data["shown"] is True
    card_id = shown.data["card_id"]
    assert asyncio.run(read.execute({"card_id": card_id})).data == {
        "state": "open",
        "answer": None,
        "title": "Run the tests again?",
    }
    store.act(card_id, "choose", "go")
    after = asyncio.run(read.execute({"card_id": card_id}))
    assert after.data["state"] == "answered" and after.data["answer"]["label"] == "Run them"
    refused = asyncio.run(show.execute({"title": "x", "kind": "image", "image_url": "https://example.com/a.png"}))
    assert not refused.ok and "this PC" in refused.error
    assert not asyncio.run(read.execute({"card_id": "nope"})).ok


def test_a_card_appears_while_the_pc_is_close_to_its_limit() -> None:
    assert cards.load_card(40, 50, 90) is None
    assert cards.load_card(99, 99, 0) is None, "no limit set, no card"
    near = cards.load_card(87, 60, 90)
    assert near["tone"] == "warn" and "CPU" in near["title"] and "87%" in near["body"] and "90%" in near["body"]
    assert "memory" in cards.load_card(10, 93, 90)["title"]

    async def one_turn(reading: SimpleNamespace | None) -> list[str]:
        store = cards.CardStore()
        watching = asyncio.ensure_future(cards.watch_load(store, read=lambda: reading, cap=lambda: 90.0, interval=0.01))
        await asyncio.sleep(0.05)
        watching.cancel()
        await asyncio.gather(watching, return_exceptions=True)
        return [card["key"] for card in store.open_cards()]

    assert asyncio.run(one_turn(SimpleNamespace(cpu=95.0, memory=40.0))) == ["machine-load"], (
        "one card, however many turns"
    )
    assert asyncio.run(one_turn(SimpleNamespace(cpu=20.0, memory=40.0))) == []
    assert asyncio.run(one_turn(None)) == [], "a load that cannot be read shows nothing"


def test_every_kind_of_card_is_drawn_and_nothing_a_card_carries_reaches_the_page_as_markup() -> None:
    out = subprocess.run(
        ["node", str(ROOT / "tests" / "web_node" / "attention_cards.mjs"), str(JS / "attention_card_view.js")],
        capture_output=True, check=False, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "everyKindDraws": True,
        "framesAreSealed": True,
        "wordsAreEscaped": True,
    }
