"""A decided hand-in does not ask the question book to show an old waiting card."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from tests.test_the_chat_sees_its_self_fix_cards import Book
from thomas.server import self_change_status


def _write(outbox: Path, sid: str, kind: str, cards_or_verdict: dict) -> None:
    (outbox / f"{sid}.{kind}.json").write_text(json.dumps(cards_or_verdict), encoding="utf-8")


def test_decided_hand_in_posts_only_its_verdict(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    book = Book()
    sid = "self-decided"
    _write(
        outbox,
        sid,
        "pending",
        {
            "cards": [
                {"title": "First change", "state": "approved"},
                {"title": "Second change", "state": "approved"},
            ]
        },
    )
    _write(outbox, sid, "verdict", {"status": "landed", "detail": "on dev"})

    status = asyncio.run(self_change_status.follow(sid, "chat-decided", outbox=outbox, book=book, poll_s=0.01))

    assert status == "landed"
    assert len(book.asked) == 1
    assert book.asked[0]["question"] == self_change_status.VERDICTS["landed"]
    assert all(ask["details"]["kicker"] != "Waiting for you at the Windows sign-in" for ask in book.asked)


def test_answered_before_follow_starts_never_posts_waiting(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    book = Book()
    sid = "self-answered"
    _write(outbox, sid, "pending", {"cards": [{"title": "Already answered", "state": "approved"}]})

    async def scenario() -> str:
        following = asyncio.create_task(
            self_change_status.follow(sid, "chat-answered", outbox=outbox, book=book, poll_s=0.01, timeout_s=2)
        )
        await asyncio.sleep(0.05)
        assert book.asked == []
        _write(outbox, sid, "verdict", {"status": "landed", "detail": "on dev"})
        return await following

    assert asyncio.run(scenario()) == "landed"
    assert len(book.asked) == 1
    assert book.asked[0]["question"] == self_change_status.VERDICTS["landed"]
    assert all(ask["details"]["kicker"] != "Waiting for you at the Windows sign-in" for ask in book.asked)


def test_asking_card_is_shown_then_forgotten_when_answered(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    book = Book()
    sid = "self-asking"
    _write(
        outbox,
        sid,
        "pending",
        {
            "cards": [
                {"title": "Already answered", "state": "approved"},
                {"title": "Still asking", "state": "asking"},
            ]
        },
    )

    async def scenario() -> str:
        following = asyncio.create_task(
            self_change_status.follow(sid, "chat-asking", outbox=outbox, book=book, poll_s=0.01, timeout_s=2)
        )
        for _ in range(100):
            if book.asked:
                break
            await asyncio.sleep(0.01)
        assert len(book.asked) == 1
        assert book.asked[0]["details"]["kicker"] == "Waiting for you at the Windows sign-in"
        _write(
            outbox,
            sid,
            "pending",
            {
                "cards": [
                    {"title": "Already answered", "state": "approved"},
                    {"title": "Still asking", "state": "approved"},
                ]
            },
        )
        for _ in range(100):
            if book.forgotten:
                break
            await asyncio.sleep(0.01)
        assert book.forgotten == ["q1"]
        _write(outbox, sid, "verdict", {"status": "landed", "detail": "on dev"})
        return await following

    assert asyncio.run(scenario()) == "landed"
    assert len(book.asked) == 2
    assert book.asked[1]["question"] == self_change_status.VERDICTS["landed"]
