"""A server that cannot show a prompt still gets your answer, and cannot forge it.

Project 4 runs the server as thomas-agent. That server has no desktop to show the
Windows sign-in on -- and a hacked one would skip it anyway -- so it files a
request on the owner's desk instead: a catalogue card kind, its details and a
content hash. Never words. The desk runs as you, renders the card from the pinned
catalogue, asks at the Windows sign-in and writes the answer into a folder the
cage account can read but never write. The server honours an answer only when it
names the request's id, kind and content hash.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from scripts.cage import owner_desk as desk

from thomas.tools import owner_desk, trusted_card

# What thomas/server/dial_elevation.py sends for a raise of autonomy to 5: the dial's words, and "dial=value".
_AUTONOMY_5 = {"dial": "its autonomy", "value": "5"}


@pytest.fixture
def pins(tmp_path: Path) -> Path:
    root = tmp_path / "pins"
    root.mkdir()
    (root / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
    return root


def _answer_in_background(root: Path, pins: Path, answer: bool, asked: list[tuple[str, str]]) -> threading.Thread:
    def serve() -> None:
        deadline = time.time() + 5
        while time.time() < deadline:
            if desk.serve_once(root, ask=lambda a, r: bool(asked.append((a, r))) or answer, pin_root=pins):
                return
            time.sleep(0.02)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    return worker


@pytest.mark.parametrize("answer", [True, False])
def test_the_desk_asks_with_the_catalogue_and_the_server_gets_your_answer(
    tmp_path: Path, pins: Path, answer: bool
) -> None:
    asked: list[tuple[str, str]] = []
    worker = _answer_in_background(tmp_path, pins, answer, asked)

    got = owner_desk.ask_owner(
        "raise_dial",
        {"dial": "its autonomy", "value": "Autopilot"},
        content_hash="autonomy=Autopilot",
        root=tmp_path,
        poll_s=0.02,
    )
    worker.join()

    assert got is answer
    action, reason = asked[0]
    assert action.startswith("Raise one of Thomas's own limits")
    assert "Pairing code" in reason


def test_an_answer_for_different_content_is_refused(tmp_path: Path, pins: Path) -> None:
    """The cage account cannot write answers at all once the folder is locked; this
    is the second wall: an answer only counts for exactly what was asked."""

    def forge_approval() -> None:
        deadline = time.time() + 5
        while time.time() < deadline:
            for request in (tmp_path / "desk" / "requests").glob("*.json"):
                data = json.loads(request.read_text(encoding="utf-8"))
                forged = {"id": data["id"], "kind": data["kind"], "content_hash": "something-else", "approved": True}
                (tmp_path / "desk" / "answers").mkdir(parents=True, exist_ok=True)
                (tmp_path / "desk" / "answers" / request.name).write_text(json.dumps(forged), encoding="utf-8")
                return
            time.sleep(0.02)

    forger = threading.Thread(target=forge_approval, daemon=True)
    forger.start()

    got = owner_desk.ask_owner(
        "raise_dial", _AUTONOMY_5, content_hash="autonomy=5", root=tmp_path, poll_s=0.02, timeout_s=1.0
    )
    forger.join()

    assert got is False


def test_no_answer_is_a_no_and_the_request_is_withdrawn(tmp_path: Path) -> None:
    got = owner_desk.ask_owner(
        "raise_dial", _AUTONOMY_5, content_hash="autonomy=5", root=tmp_path, poll_s=0.02, timeout_s=0.1
    )

    assert got is False
    assert list((tmp_path / "desk" / "requests").glob("*.json")) == []


def test_a_request_for_words_the_catalogue_does_not_have_is_refused_without_asking(tmp_path: Path, pins: Path) -> None:
    requests = tmp_path / "desk" / "requests"
    requests.mkdir(parents=True)
    (requests / "r1.json").write_text(
        json.dumps({"id": "r1", "kind": "anything_i_like", "details": {"x": "y"}, "content_hash": "h"}),
        encoding="utf-8",
    )
    asked: list[tuple[str, str]] = []

    desk.serve_once(tmp_path, ask=lambda a, r: bool(asked.append((a, r))) or True, pin_root=pins)

    answer = json.loads((tmp_path / "desk" / "answers" / "r1.json").read_text(encoding="utf-8"))
    assert answer["approved"] is False and asked == []


def test_a_tampered_catalogue_refuses_without_asking(tmp_path: Path, pins: Path) -> None:
    (pins / trusted_card.PIN_NAME).write_text("0" * 64)
    asked: list[tuple[str, str]] = []
    worker = _answer_in_background(tmp_path, pins, True, asked)

    got = owner_desk.ask_owner(
        "raise_dial", _AUTONOMY_5, content_hash="autonomy=5", root=tmp_path, poll_s=0.02, timeout_s=2.0
    )
    worker.join()

    assert got is False and asked == []


def test_a_dial_raise_goes_through_the_desk_when_the_server_cannot_prompt(
    tmp_path: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import dial_elevation
    from thomas.tools import cage_shell

    monkeypatch.setenv(owner_desk.DESK_ENV, "1")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path))

    def never(*_args: object) -> bool:
        raise AssertionError("a server that runs as the cage account must not prompt by itself")

    monkeypatch.setattr(dial_elevation, "_fresh_native_prompt", never)
    dial_elevation.reset_grants()
    asked: list[tuple[str, str]] = []
    worker = _answer_in_background(tmp_path, pins, True, asked)

    assert dial_elevation.approve("autonomy", 5) is True
    worker.join()

    assert asked and asked[0][0].startswith("Raise one of Thomas's own limits")
    dial_elevation.reset_grants()


def test_asking_from_a_coroutine_does_not_block_the_loop(tmp_path: Path, pins: Path) -> None:
    asked: list[tuple[str, str]] = []
    worker = _answer_in_background(tmp_path, pins, True, asked)

    got = asyncio.run(
        owner_desk.ask_owner_async("raise_dial", _AUTONOMY_5, content_hash="autonomy=5", root=tmp_path, poll_s=0.02)
    )
    worker.join()

    assert got is True


def _serve(tmp_path: Path, pins: Path, kind: str, details: dict[str, str], content_hash: str) -> tuple[bool, list]:
    """File one request as the caged server would, let the desk serve it, and return its answer and every prompt."""
    requests = tmp_path / "desk" / "requests"
    requests.mkdir(parents=True, exist_ok=True)
    request = {"id": "r1", "kind": kind, "details": details, "content_hash": content_hash}
    (requests / "r1.json").write_text(json.dumps(request), encoding="utf-8")
    asked: list[tuple[str, str]] = []

    desk.serve_once(tmp_path, ask=lambda a, r: bool(asked.append((a, r))) or True, pin_root=pins)

    answer = json.loads((tmp_path / "desk" / "answers" / "r1.json").read_text(encoding="utf-8"))
    return answer["approved"], asked


@pytest.mark.parametrize(
    ("kind", "details"),
    [
        ("promote_batch", {"count": "1", "files": "thomas/x.py (+1 -1)"}),
        ("protected_write", {"path": "thomas/x.py", "diffstat": "+1 -0 line(s)"}),
        ("promote_dangerous", {"category": "the cage and approvals", "path": "scripts/cage/x.py", "diffstat": "+1"}),
        ("guarded_tool", {"tool": "shell", "args": "dir"}),
    ],
)
def test_the_desk_asks_only_to_raise_a_limit(tmp_path: Path, pins: Path, kind: str, details: dict[str, str]) -> None:
    """The desk shows what the caged server names. Its one real request is a raise of one of Thomas's own limits
    (thomas/server/dial_elevation.py). Any other card from it -- a change card with a file list the server chose,
    shown between your real cards -- is answered no without a prompt."""
    approved, asked = _serve(tmp_path, pins, kind, details, "h")

    assert approved is False and asked == []


@pytest.mark.parametrize(
    ("details", "content_hash"),
    [
        (_AUTONOMY_5, "autonomy=4"),
        ({"dial": "the files it can change", "value": "5"}, "autonomy=5"),
        (_AUTONOMY_5, "speed=5"),
    ],
    ids=["another value", "another dial's words", "a dial Thomas does not have"],
)
def test_the_desk_shows_exactly_the_raise_it_records(
    tmp_path: Path, pins: Path, details: dict[str, str], content_hash: str
) -> None:
    """The prompt shows the request's details; the desk records the raise from its content hash. Unless the two say
    the same raise, you would approve one and the desk would record another."""
    approved, asked = _serve(tmp_path, pins, "raise_dial", details, content_hash)

    assert approved is False and asked == []
    assert not (tmp_path / "desk" / "answers" / owner_desk.GRANTS_NAME).exists(), "nothing was raised"
