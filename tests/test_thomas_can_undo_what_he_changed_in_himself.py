"""What Thomas changes about himself is retractable, on a card at the end.

Owner direction, 2026-09-22: on Autopilot he fixes his own blockers first --
"obviously retractable ... then he gives a card ... here's an undo button here's
an accept button to accept it forever ... you already made the change fixed it
and then you have to click on it to put it into stone".

So the bytes that were there before a self-change are kept, Undo puts them back
exactly, and nothing is permanent until the owner accepts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thomas.core import self_change_ledger as ledger
from thomas.core.user_questions import UserQuestionBook
from thomas.server import self_change_review as review


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "thomas" / "core").mkdir(parents=True)
    return tmp_path


def _record(repo: Path, path: str, before: str | None, after: str, *, chat: str = "chat-1") -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(after, encoding="utf-8")
    return ledger.record(path=path, before=before, after=after, why="fix a crash", chat=chat, repo_root=repo)


def test_undo_puts_back_exactly_what_was_there(repo: Path) -> None:
    original = "def f():\n    return 1\n"
    entry = _record(repo, "thomas/core/a.py", original, "def f():\n    return 2\n")
    assert ledger.undo([entry], repo) == ["thomas/core/a.py"]
    assert (repo / "thomas/core/a.py").read_text(encoding="utf-8") == original


def test_undo_removes_a_file_thomas_created(repo: Path) -> None:
    entry = _record(repo, "thomas/core/new.py", None, "print('hi')\n")
    ledger.undo([entry], repo)
    assert not (repo / "thomas/core/new.py").exists()


def test_accepting_makes_it_permanent(repo: Path) -> None:
    entry = _record(repo, "thomas/core/a.py", "old\n", "new\n")
    assert ledger.accept([entry], repo) == 1
    assert ledger.pending(repo_root=repo) == [], "an accepted change is no longer offered"
    assert (repo / "thomas/core/a.py").read_text(encoding="utf-8") == "new\n"


def test_an_undone_change_is_not_offered_twice(repo: Path) -> None:
    entry = _record(repo, "thomas/core/a.py", "old\n", "new\n")
    ledger.undo([entry], repo)
    assert ledger.pending(repo_root=repo) == []


def test_one_chats_card_offers_only_that_chats_changes(repo: Path) -> None:
    _record(repo, "thomas/core/a.py", "a\n", "A\n", chat="chat-1")
    _record(repo, "thomas/core/b.py", "b\n", "B\n", chat="chat-2")
    mine = ledger.pending(repo_root=repo, chat="chat-1")
    assert [row["path"] for row in mine] == ["thomas/core/a.py"]


def test_the_card_names_every_file_and_why(repo: Path) -> None:
    _record(repo, "thomas/core/a.py", "a\n", "A\n")
    body = review.summarize(ledger.pending(repo_root=repo))
    assert body["fields"] == [{"label": "thomas/core/a.py", "value": "fix a crash"}]
    assert "Nothing is permanent until you accept" in body["note"]


def _answer_card(repo: Path, choice: str) -> None:
    book = UserQuestionBook()

    async def go() -> None:
        task = review.offer("chat-1", book=book, repo_root=repo, timeout_s=5)
        assert task is not None
        for _ in range(500):
            if book.pending(None):
                break
            await asyncio.sleep(0.01)
        row = book.pending(None)[0]
        assert row["kind"] == "card" and row["session_id"] == "chat-1"
        assert [o["label"] for o in row["options"]] == [review.ACCEPT, review.UNDO, review.LATER]
        assert all("requires_password" not in o for o in row["options"]), "taking a change back needs no password"
        book.answer(row["id"], [choice])
        await task

    asyncio.run(go())


def test_pressing_undo_on_the_card_restores_the_file(repo: Path) -> None:
    _record(repo, "thomas/core/a.py", "old\n", "new\n")
    _answer_card(repo, review.UNDO)
    assert (repo / "thomas/core/a.py").read_text(encoding="utf-8") == "old\n"
    assert ledger.pending(repo_root=repo) == []


def test_pressing_accept_on_the_card_keeps_it(repo: Path) -> None:
    _record(repo, "thomas/core/a.py", "old\n", "new\n")
    _answer_card(repo, review.ACCEPT)
    assert (repo / "thomas/core/a.py").read_text(encoding="utf-8") == "new\n"
    assert ledger.pending(repo_root=repo) == []


def test_leaving_it_keeps_the_change_undoable(repo: Path) -> None:
    _record(repo, "thomas/core/a.py", "old\n", "new\n")
    _answer_card(repo, review.LATER)
    assert (repo / "thomas/core/a.py").read_text(encoding="utf-8") == "new\n"
    assert len(ledger.pending(repo_root=repo)) == 1, "still listed, still undoable"


def test_no_card_when_thomas_changed_nothing(repo: Path) -> None:
    assert review.offer("chat-1", book=UserQuestionBook(), repo_root=repo) is None


def test_the_protected_write_tool_records_what_it_replaced() -> None:
    """The recording sits in the write itself, so no self-change escapes it."""
    import inspect

    from thomas.tools import filesystem

    src = inspect.getsource(filesystem.WriteProtectedFileTool.execute)
    assert "_record_self_change" in src
    assert src.index("read_text") < src.index("write_text"), "the previous bytes must be read before overwriting"
