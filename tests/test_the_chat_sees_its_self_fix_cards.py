"""The chat that asked for a self-fix shows each approval card and what happened.

The promoter asks at the Windows sign-in, outside the server. It writes each card
to the outbox first; the chat mirrors it -- the same title, the same pairing code
-- and then the verdict. Each card appears once, not once per look at the outbox,
and the mirror says plainly that it cannot approve anything.

Task 4: a Thomas project that Chat started puts its cards in that chat's question
panel. Before, they went to the Build conversation's id, a session no question
panel polls, so the Chat that asked never saw them.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests.test_a_self_fix_lands_only_when_you_approve import _promoter, _submit, blue, pins  # noqa: F401
from tests.test_a_sign_in_windows_did_not_accept_is_asked_again import Answers, _code
from thomas.core import user_questions
from thomas.core.user_questions import UserQuestionBook
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import green_checkout, green_handoff, self_change_cards, self_change_status, thomas_project
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.user_questions_routes import setup_user_question_routes
from thomas.tools import cage_shell


class Book:
    """The question book's shape: ask returns a record with an id, forget takes it."""

    def __init__(self) -> None:
        self.asked: list[dict] = []
        self.forgotten: list[str] = []

    def ask(self, **kwargs: object) -> object:
        self.asked.append(kwargs)
        return SimpleNamespace(id=f"q{len(self.asked)}")

    def forget(self, question_id: str) -> None:
        self.forgotten.append(question_id)


def _write(outbox: Path, sid: str, kind: str, payload: dict) -> None:
    (outbox / f"{sid}.{kind}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_each_card_and_the_verdict_reach_the_chat_once(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    book = Book()
    card = {"title": "Put Thomas's changes into the running Thomas", "body": "Apply 1 change(s): a.py"}

    async def scenario() -> str:
        following = asyncio.create_task(
            self_change_status.follow("self-e1", "chat-7", outbox=outbox, book=book, poll_s=0.01, timeout_s=5)
        )
        await asyncio.sleep(0.05)
        pending = {**card, "pairing_code": "ABC-DEF", "state": "asking", "excerpt": "+VALUE = 2"}
        _write(outbox, "self-e1", "pending", {"cards": [pending]})
        await asyncio.sleep(0.05)
        _write(outbox, "self-e1", "verdict", {"status": "landed", "detail": "on dev", "commit_sha": "abc1234567"})
        return await following

    assert asyncio.run(scenario()) == "landed"
    assert len(book.asked) == 2
    first, last = book.asked
    assert first["session_id"] == "chat-7" and first["question"] == card["title"]
    assert first["details"]["pairing_code"] == "ABC-DEF"
    assert "cannot approve" in first["details"]["note"]
    assert first["details"]["excerpt"] == "+VALUE = 2"
    assert first["details"]["waits"] is False and last["details"]["waits"] is False, "a mirror holds nothing up"
    assert "running Thomas" in last["question"]
    assert any("abc12345" in f["value"] for f in last["details"]["fields"])


def test_a_withdrawn_hand_in_does_not_leave_a_chat_card_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inbox, outbox = tmp_path / "inbox", tmp_path / "outbox"
    for folder in (inbox, outbox):
        folder.mkdir()
    sid, book = "self-withdrawn", Book()
    (inbox / sid).mkdir()
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: inbox)
    _write(outbox, sid, "pending", {"cards": [{"title": "Approve", "body": "Change", "state": "asking"}]})

    async def scenario() -> str:
        following = asyncio.create_task(
            self_change_status.follow(sid, "chat-8", outbox=outbox, book=book, poll_s=0.01, timeout_s=2)
        )
        for _ in range(100):
            if book.asked:
                break
            await asyncio.sleep(0.01)
        assert book.asked
        withdrawn = tmp_path / "withdrawn"
        withdrawn.mkdir()
        (inbox / sid).rename(withdrawn / sid)
        return await following

    assert asyncio.run(scenario()) == "withdrawn"
    assert book.forgotten == ["q1"]
    assert len(book.asked) == 1


def test_an_answered_card_stops_saying_it_is_waiting(tmp_path: Path) -> None:
    # Live 2026-09-23: you approved at 08:36 and the chat still read "Waiting for
    # you at the Windows sign-in" under the card that said it had landed.
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    book = UserQuestionBook()
    card = {"title": "Put Thomas's changes into the running Thomas", "body": "Apply 1 change(s): a.py"}

    async def scenario() -> tuple[list[str], list[str]]:
        following = asyncio.create_task(
            self_change_status.follow("self-e2", "chat-8", outbox=outbox, book=book, poll_s=0.01, timeout_s=5)
        )
        _write(outbox, "self-e2", "pending", {"cards": [{**card, "state": "asking"}]})
        await asyncio.sleep(0.05)
        asking = [q["question"] for q in book.pending("chat-8")]
        _write(outbox, "self-e2", "pending", {"cards": [{**card, "state": "approved"}]})
        await asyncio.sleep(0.05)
        answered = [q["question"] for q in book.pending("chat-8")]
        _write(outbox, "self-e2", "verdict", {"status": "landed", "detail": "on dev"})
        await following
        return asking, answered

    asking, answered = asyncio.run(scenario())

    assert asking == [card["title"]]
    assert answered == [], "the card you already answered must leave the chat"
    assert [q["question"] for q in book.pending("chat-8")] == [self_change_status._VERDICTS["landed"]]


def test_a_held_card_leaves_the_chat_and_comes_back_when_it_is_asked_again(tmp_path: Path) -> None:
    """A sign-in Windows did not accept three times puts the card away ("held") and asks it again later."""
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    book = Book()
    card = {"title": "Put Thomas's changes into the running Thomas", "body": "Apply 1 change(s): a.py",
            "pairing_code": "ABC-DEF"}  # fmt: skip

    async def scenario() -> str:
        following = asyncio.create_task(
            self_change_status.follow("self-e3", "chat-9", outbox=outbox, book=book, poll_s=0.01, timeout_s=5)
        )
        for state in ("asking", "held", "asking"):
            _write(outbox, "self-e3", "pending", {"cards": [{**card, "state": state}]})
            await asyncio.sleep(0.05)
        _write(outbox, "self-e3", "verdict", {"status": "landed", "detail": "on dev"})
        return await following

    assert asyncio.run(scenario()) == "landed"
    assert [q["question"] for q in book.asked] == [card["title"], card["title"], self_change_status.VERDICTS["landed"]]
    assert book.forgotten == ["q1", "q2"]


def test_a_refusal_is_never_said_to_come_before_you_were_asked() -> None:
    """Since 2026-10-09 the running copy is checked again right after your answer, so a refusal can follow it."""
    assert "before you were asked" not in self_change_status.VERDICTS["refused"]
    assert "refused" in self_change_status.VERDICTS["refused"]


def test_following_gives_up_quietly_when_nothing_arrives(tmp_path: Path) -> None:
    book = Book()

    status = asyncio.run(
        self_change_status.follow("self-none", "chat-7", outbox=tmp_path, book=book, poll_s=0.01, timeout_s=0.05)
    )

    assert status == "" and book.asked == []


def test_a_card_rewritten_in_the_same_place_replaces_the_one_shown(tmp_path: Path) -> None:
    """A promoter that stopped and started again writes its new card where the old one was, with a new pairing code.
    The chat kept the old card, and its old code, in front of you. A record caught unreadable for a moment changes
    nothing shown: the same card is not shown twice."""
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    book = Book()
    card = {
        "title": "Put Thomas's changes into the running Thomas",
        "body": "Apply 1 change(s): a.py",
        "state": "asking",
    }

    async def scenario() -> str:
        following = asyncio.create_task(
            self_change_status.follow("self-e4", "chat-9", outbox=outbox, book=book, poll_s=0.01, timeout_s=5)
        )
        for code in ("AAA-AAA", "", "AAA-AAA", "BBB-BBB", "BBB-BBB"):
            if code:
                _write(outbox, "self-e4", "pending", {"cards": [{**card, "pairing_code": code}]})
            else:
                (outbox / "self-e4.pending.json").write_text('{"cards": [', encoding="utf-8")
            await asyncio.sleep(0.05)
        _write(outbox, "self-e4", "verdict", {"status": "landed", "detail": "on dev"})
        return await following

    assert asyncio.run(scenario()) == "landed"
    assert [q["details"].get("pairing_code") for q in book.asked] == ["AAA-AAA", "BBB-BBB", None]
    assert book.forgotten == ["q1", "q2"], "the old card left as the new one came, and the new one at the verdict"


# -- one sign-in for several self-fixes (your decision, 2026-10-08: "Yes, batch cards") ------------------------------ #


def test_a_shared_card_shows_each_change_and_marks_this_chats(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While one Windows sign-in asks about two self-fixes, each chat shows that card from what the promoter wrote:
    which line is its own, every line exactly as the prompt shows it, every file in its own change, its own diff, and
    that the list is a copy. Once both land, each says which card it was approved on."""
    monkeypatch.setattr(self_change_status, "verdict_arrived", lambda *_args, **_kwargs: "")  # no team to settle here
    a = _submit(blue, "exec-chat-a", {"thomas/a.py": "A = 1\n"})
    b = _submit(blue, "exec-chat-b", {"thomas/b.py": "B = 1\n", "tests/test_b.py": "def test_b():\n    pass\n"})
    outbox = cage_shell.cage_root() / "outbox"
    books = {a.name: Book(), b.name: Book()}
    answers = Answers("approved")

    def ask(action: str, reason: str) -> object:  # while the prompt is up, each chat follows its own record
        for sid, book in books.items():
            asyncio.run(self_change_status.follow(sid, "chat-1", outbox=outbox, book=book, poll_s=0.01, timeout_s=0.2))
        return answers(action, reason)

    assert _promoter(blue, pins, ask).run_once().status == "landed"
    [(action, reason)] = answers.asked
    title, _, _head, *lines = action.split("\n")
    rows = [line.split(". ", 1)[1] for line in lines]
    code = _code(reason)
    for n, (sub, mine, theirs, every) in enumerate(
        [
            (a, "+A = 1", "B = 1", "thomas/a.py (new, +1)"),
            (b, "+B = 1", "A = 1", "tests/test_b.py (new, +2), thomas/b.py (new, +1)"),
        ],
        1,
    ):
        [shown] = books[sub.name].asked
        details = shown["details"]
        assert shown["question"] == title and details["pairing_code"] == code
        assert details["fields"] == [
            {"label": "This chat's change", "value": f"Number {n} of the 2 on this card"},
            {"label": "1 (this chat's)" if n == 1 else "1", "value": rows[0]},
            {"label": "2 (this chat's)" if n == 2 else "2", "value": rows[1]},
            {"label": "Every file in this change", "value": every},
        ]
        assert mine in details["excerpt"] and theirs not in details["excerpt"], "its own diff, which is what lands"
        assert "this list is a copy" in details["note"] and "puts all 2 changes in" in details["note"]
        assert "cannot approve anything" in details["note"] and shown["options"] == self_change_status._GOT_IT

        book = Book()
        assert asyncio.run(self_change_status.follow(sub.name, "chat-1", outbox=outbox, book=book, timeout_s=5)) == (
            "landed"
        )
        said = f"one card for 2 changes (pairing code {code}), number {n}"
        assert book.asked[0]["details"]["fields"][-1] == {"label": "Approved on", "value": said}


def test_a_landed_change_says_which_card_it_was_on(tmp_path: Path) -> None:
    """Right after the commit it landed as; a change that had its own card says nothing more."""
    book = Book()
    place = {"pairing_code": "K7Q-MP4", "position": 2, "of": 5}
    for sid, card in (("self-shared", place), ("self-single", {})):
        verdict = {"status": "landed", "detail": "on dev", "commit_sha": "abc1234567", "card": card}
        _write(tmp_path, sid, "verdict", verdict)
        assert (
            asyncio.run(self_change_status.follow(sid, "chat-7", outbox=tmp_path, book=book, timeout_s=5)) == "landed"
        )
    shared, single = (q["details"]["fields"] for q in book.asked)
    assert [f["label"] for f in shared][-2:] == ["Commit", "Approved on"]
    assert shared[-1]["value"] == "one card for 5 changes (pairing code K7Q-MP4), number 2"
    assert "Approved on" not in [f["label"] for f in single]
    for bad in ({**place, "position": "2"}, {**place, "position": 6}, {**place, "pairing_code": ""}, "K7Q-MP4"):
        assert self_change_cards.landed_on({"status": "landed", "card": bad}) is None, bad
    assert self_change_cards.landed_on({"status": "refused", "card": place}) is None, "approved on, once it landed"


SHARED_RECORD = {
    "kind": "promote_several",
    "title": "Put several of Thomas's changes into the running Thomas",
    "body": "Signing in puts these 2 changes into Thomas together. Cancel puts none in and asks about each alone:\n"
    "1. +1 -0 in 1 file(s): thomas/a.py (+1 -0)\n2. +1 -0 in 1 file(s): thomas/b.py (+1 -0)",
    "pairing_code": "ABC-DEF",
    "state": "asking",
    "card": {"position": 1, "of": 2},
    "files": ["thomas/a.py (+1 -0)"],
}


@pytest.mark.parametrize(
    "bad",
    [
        {"card": {"position": "x", "of": 2}},
        {"card": {"position": 3, "of": 2}},
        {"card": {"position": 0, "of": 2}},
        {"card": {"position": True, "of": 2}},
        {"card": {"of": 2}},
        {"card": {"position": 1, "of": 3}},
        {"card": [1, 2]},
        {"files": "abc"},
        {"files": None},
        {"body": SHARED_RECORD["body"].replace("\n2. ", "\n3. ")},
        {"body": SHARED_RECORD["body"].replace("\n2. ", " ")},
    ],
)
def test_a_malformed_shared_card_still_shows_as_one_change(tmp_path: Path, bad: dict) -> None:
    """A record the chat cannot read as a shared card shows as one change, as every card did before, and the chat
    goes on following: one bad record never ends the mirror."""
    fields, _note = self_change_cards.card_fields(SHARED_RECORD)
    assert fields[0]["label"] == "This chat's change", "the record without the fault reads as a shared card"
    record, book = {**SHARED_RECORD, **bad}, Book()

    async def scenario() -> str:
        following = asyncio.create_task(
            self_change_status.follow("self-bad", "chat-7", outbox=tmp_path, book=book, poll_s=0.01, timeout_s=5)
        )
        _write(tmp_path, "self-bad", "pending", {"cards": [record]})
        await asyncio.sleep(0.05)
        _write(tmp_path, "self-bad", "verdict", {"status": "landed", "detail": "on dev"})
        return await following

    assert asyncio.run(scenario()) == "landed"
    card, _verdict = book.asked
    assert card["details"]["fields"] == [{"label": "Change", "value": record["body"]}]
    assert card["details"]["note"] == self_change_cards.SINGLE_NOTE


# ── Task 4: a Thomas project Chat started, settled by Autopilot's done check ──


TASK_TEXT = "This is self-development of Thomas itself, at C:/Users/you/Thomas, NOT a new project"
DONE_REPLY = json.dumps(
    {"fc": "final", "text": "DONE: The setup docs now match the installer. Checked by reading both.\nNEXT: none"}
)


@pytest.fixture
def done_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A real green of a small stand-in for Thomas's source, whose Autopilot project Chat "chat-9" started:
    README.md changed on the first pass, AGENTS.md in the done check's fix round, then the check said done."""
    blue, greens, outbox = tmp_path / "blue", tmp_path / "green", tmp_path / "outbox"
    for folder in (blue, greens / "work", greens / "git", outbox):  # a green root that exists gets no ACLs set
        folder.mkdir(parents=True)
    for name in ("README.md", "AGENTS.md"):
        (blue / name).write_text(f"{name}\n", encoding="utf-8")
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=blue, check=True)
    monkeypatch.setenv("THOMAS_GREEN_ROOT", str(greens))
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)  # no cage runner in a test
    monkeypatch.setattr(self_change_status, "outbox_dir", lambda: outbox)
    green = green_checkout.create_green(blue=blue, execution_id="thomas-cards1")
    record = {"execution_id": green.execution_id, "chat_session_id": "chat-9"}
    cid = forge_code_store.new_conversation(green.work, title=TASK_TEXT, thomas_project=record)["id"]
    catalog = tmp_path / "catalog"
    settings = {"requested": {"autonomy_level": ap.AUTOPILOT}}
    forge_code_projects.bind_conversation(catalog, cid, green.work, settings=settings, allow_without_history=True)
    for goal, name in (("fix the docs", "README.md"), (ap.REVIEW_PREFIX, "AGENTS.md"), (ap.REVIEW_PREFIX, "")):
        forge_code_store.append_user_turn(green.work, cid, goal)
        if name:
            (green.work / name).write_text("better\n", encoding="utf-8")
        forge_code_store.append_agent_turn(
            green.work, cid, model="gpt", transcript="" if name else DONE_REPLY, changed_files=[name] if name else [],
            returncode=0,
            ok=True, noop=False, reason="Thomas replied without changing files" if not name else "1 file(s) changed",
            outcome="completed" if name else "conversation",
        )  # fmt: skip
    return SimpleNamespace(green=green, cid=cid, catalog=catalog, outbox=outbox, inbox=tmp_path / "inbox")


def test_the_card_and_the_landed_subject_name_every_file_the_patch_changes(done_project: SimpleNamespace) -> None:
    """NEW-1: the summary counted only the last turn that changed files ("1 file(s) changed: AGENTS.md")."""
    p = done_project

    decision = asyncio.run(ap.after_run({}, p.green.work, p.catalog, p.cid))

    assert decision.action == "done"
    manifest = json.loads((p.inbox / f"self-{p.green.execution_id}" / "submission.json").read_text(encoding="utf-8"))
    assert manifest["files"] == ["AGENTS.md", "README.md"]
    # Round 2 (live, 4e8a28cb): the subject was the request's first line, path and all. Now: the team's DONE reply.
    assert manifest["message"] == "The setup docs now match the installer -- 2 file(s) changed: AGENTS.md, README.md"
    assert manifest["chat"] == "chat-9"


def test_a_thomas_project_started_from_chat_shows_its_card_in_that_chats_panel(
    done_project: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = done_project
    book = UserQuestionBook()
    monkeypatch.setattr(user_questions, "question_book", lambda: book)
    card = {"title": "Put Thomas's changes into the running Thomas", "pairing_code": "QRS-TUV", "state": "asking"}
    _write(p.outbox, f"self-{p.green.execution_id}", "pending", {"cards": [card]})  # the promoter is asking

    async def scenario() -> tuple[dict, dict]:
        await ap.after_run({}, p.green.work, p.catalog, p.cid)  # settles, then follows the promoter's cards
        for _ in range(200):
            if book.pending("chat-9") or book.pending(p.cid):
                break
            await asyncio.sleep(0.01)
        app = web.Application()
        setup_user_question_routes(app, book=book)
        async with TestClient(TestServer(app)) as client:  # what the Chat page's question panel asks for
            chat = await (await client.get("/api/chat/questions", params={"session_id": "chat-9"})).json()
            build = await (await client.get("/api/chat/questions", params={"session_id": p.cid})).json()
        return chat, build

    chat, build = asyncio.run(scenario())

    assert [(q["question"], q["details"]["pairing_code"]) for q in chat["questions"]] == [(card["title"], "QRS-TUV")]
    assert build["questions"] == [], "the Build conversation's id is not a chat anyone reads"


def test_the_approval_cards_subject_is_the_teams_own_title_never_a_path() -> None:
    """Round 2 (live, 4e8a28cb): the landed subject was the request's first line, path and all."""

    def said(text: str) -> dict:
        return {"role": "agent", "reason": "2 file(s) changed", "transcript": json.dumps({"fc": "final", "text": text})}

    titled = [said("Done, see below."), said("Wired it up.\n**TITLE:** `Composer keeps drafts across reloads`")]
    assert thomas_project._subject(titled) == "Composer keeps drafts across reloads"
    pathy = said("Fixed C:/Users/you/Thomas/thomas/app.py and /home/you/x/y.py today. Then more.")
    assert thomas_project._subject([pathy]) == "Fixed and today"
    assert thomas_project._subject([{"role": "agent", "reason": "2 file(s) changed"}]) == "Thomas self-change"
