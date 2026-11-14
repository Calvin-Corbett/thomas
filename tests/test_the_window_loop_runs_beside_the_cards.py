"""The window's loop: your requests, the window opened only by your sign-in, the check after each landing, its record.

Spec 2026-10-12, sections 8.3-8.8. Stand-ins for the lane, the undoer, the checker and the sign-in (each is tested in
its own file); its own git repo and tmp cage, record and pin folders. No Windows prompt is shown.
"""

from __future__ import annotations

import json
import secrets
import shutil
import threading
import time
from pathlib import Path

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage import self_change_promoter as sp
from scripts.cage import window_control as wc
from scripts.cage import window_loop as wl
from scripts.cage import window_state as ws
from scripts.cage.referee.presence import Presence
from scripts.cage.window_record import Record

from tests.green_support import git, make_blue
from thomas.tools import cage_shell, trusted_card

SID = "self-thomas-0123456789ab"


class Clock:
    wall, mono = 1_000_000.0, 50.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono


class Here:
    def state(self) -> Presence:
        return Presence(False, 3.0, "1:42")


class StubLane:
    def __init__(self, p: sp.Promoter) -> None:
        self.p = p
        self.next: sp.Outcome | None = None
        self.last_landed: tuple[str, str, str, list[str]] | None = None
        self.allowed: list[bool] = []
        self.closed = False
        self.took: list[tuple[bool, bool, bool]] = []  # (window open, reliable, the card loop's lock held)

    def owned(self) -> frozenset[str]:
        return frozenset({SID})

    def takeable(self, card_busy: frozenset[str]) -> list[str]:
        return [] if SID in card_busy else [SID]

    def take(self, window: ws.Window, *, card_busy: frozenset[str], reliable: bool) -> None:
        self.took.append((window.opened is not None, reliable, self.p.taking.locked()))

    def waiting(self) -> list[dict]:
        return [{"sid": SID, "wait": "ready: waiting for your window"}]

    def step(self, window: ws.Window, *, card_busy: frozenset[str], landing_allowed: bool) -> sp.Outcome | None:
        self.allowed.append(landing_allowed)
        outcome, self.next = self.next, None
        return outcome

    def close(self) -> None:
        self.closed = True


class StubUndoer:
    def __init__(self) -> None:
        self.started: list[tuple] = []
        self.current = None
        self.said = ""

    def start(self, sid: str, *, kind: str = "undo_change", failed=(), batch=()) -> str:
        self.started.append((sid, kind, tuple(failed), tuple(batch)))
        return ""

    def step(self) -> str:
        return ""


class FakeLink:
    def __init__(self) -> None:
        self.why_not = ""
        self.jobs: list[cj.Job] = []
        self.verdict: str | None = None

    def answering(self) -> str:
        return self.why_not

    def post(self, kind: str, *, base: str, commit: str, tree: str, changed: list[str], tests=()) -> cj.Job:
        self.jobs.append(cj.Job(secrets.token_hex(12), kind, base, commit, tree, tuple(changed), (), 1.0))
        return self.jobs[-1]

    def result(self, job: cj.Job) -> cj.Result | None:
        if self.verdict is None:
            return None
        return cj.Result(job.id, job.kind, job.base, job.commit, job.tree, self.verdict, "1 test failed",
                         findings=("tests/test_x.py::test_a",))  # fmt: skip

    def forget(self, job: cj.Job) -> None:
        pass


class Asker:
    def __init__(self, answer: str = "approved") -> None:
        self.answer = answer
        self.asked: list[tuple[str, dict]] = []

    def __call__(self, p: sp.Promoter, kind: str, details: dict, digest: str, nonce: str) -> tuple[str, str]:
        self.asked.append((kind, details))
        return self.answer, "ABC-DEF"


class Rig:
    def __init__(self, tmp_path: Path, answer: str = "approved") -> None:
        self.blue = make_blue(tmp_path)
        git(self.blue, "checkout", "-q", "-b", "dev")
        pins = tmp_path / "pins"
        pins.mkdir()
        (pins / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
        (tmp_path / "record").mkdir()
        self.home = tmp_path / "window"
        self.card = sp.Promoter(repo=self.blue, cage_root=cage_shell.cage_root(), ask=lambda a, r: False,
                                pin_root=pins, audit=lambda _r: [])  # fmt: skip
        self.lane, self.undoer, self.link, self.ask = StubLane(self.card), StubUndoer(), FakeLink(), Asker(answer)
        self.record = Record(tmp_path / "record")
        self.window = ws.Window(presence=Here(), off_markers=[self.home / wl.OFF], ceiling_minutes=120,
                                max_landings=25, idle_minutes=15, clock=Clock())  # fmt: skip
        self.loop = wl.WindowLoop(card=self.card, lane=self.lane, undoer=self.undoer, window=self.window,
                                  link=self.link, record=self.record, home=self.home, ask=self.ask)  # fmt: skip

    def events(self) -> list[str]:
        return [str(event["name"]) for event in self.record.events()]

    def status(self) -> dict:
        return json.loads((self.home / wl.STATUS).read_text(encoding="utf-8"))


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_an_open_request_asks_the_pinned_card_and_only_your_approval_opens_the_window(rig: Rig) -> None:
    wc.request(rig.home, "open", minutes=90)
    rig.loop.tick()

    kind, details = rig.ask.asked[0]
    assert kind == "open_window" and details["minutes"] == 90 and details["cap"] == "at most 25"
    assert details["waiting"] == 1, "the card counts what the window would take up: every hand-in on no card"
    opened = rig.window.opened
    assert opened is not None and opened.pairing_code == "ABC-DEF"
    first = rig.record.events()[0]
    assert first["name"] == "window_opened" and first["pairing_code"] == "ABC-DEF" and first["minutes"] == 90
    assert rig.status()["window"]["open"] is True
    assert "No window" not in wc.status_text(rig.home)


@pytest.mark.parametrize("trouble", ["checker", "record", "cancel"])
def test_no_window_without_the_checker_the_record_or_your_yes(tmp_path: Path, trouble: str) -> None:
    rig = Rig(tmp_path, answer="cancelled" if trouble == "cancel" else "approved")
    if trouble == "checker":
        rig.link.why_not = "the checker is not running (no heartbeat)"
    elif trouble == "record":
        (tmp_path / "record").rmdir()
    wc.request(rig.home, "open", minutes=60)
    rig.loop.tick()
    assert rig.window.opened is None
    assert (rig.ask.asked == []) == (trouble != "cancel")


def test_old_or_garbled_requests_are_removed_unasked(rig: Rig) -> None:
    path = wc.request(rig.home, "open", minutes=60)
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "at": time.time() - 3600}), encoding="utf-8")
    (rig.home / "requests" / "x.json").write_text("{not json", encoding="utf-8")
    rig.loop.tick()
    assert rig.ask.asked == [] and not list((rig.home / "requests").glob("*.json"))


def test_closing_ends_the_window_and_records_what_it_landed(rig: Rig) -> None:
    wc.request(rig.home, "open", minutes=60)
    rig.loop.tick()
    wc.request(rig.home, "close")
    rig.loop.tick()
    assert rig.window.opened is None
    closed = rig.record.events()[-1]
    assert closed["name"] == "window_closed" and closed["reason"] == "you closed it" and closed["landed"] == []


def test_the_off_switch_ends_an_open_window(rig: Rig) -> None:
    wc.request(rig.home, "open", minutes=60)
    rig.loop.tick()
    wc.main(["off"], folder=rig.home)
    rig.loop.tick()
    assert rig.window.opened is None and "off switch" in rig.record.events()[-1]["reason"]
    wc.request(rig.home, "open", minutes=60)
    rig.loop.tick()
    assert rig.window.opened is None and len(rig.ask.asked) == 1, "no card is asked while windows are off"
    wc.main(["on"], folder=rig.home)
    wc.request(rig.home, "open", minutes=60)
    rig.loop.tick()
    assert rig.window.opened is not None


def _land_one(rig: Rig) -> tuple[str, str]:
    parent = git(rig.blue, "rev-parse", "dev")
    (rig.blue / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(rig.blue, "commit", "-qam", "landed")
    commit = git(rig.blue, "rev-parse", "dev")
    rig.lane.next = sp.Outcome("landed", "", commit, ["thomas/fix_me.py"])
    rig.lane.last_landed = (SID, commit, parent, ["thomas/fix_me.py"])
    return commit, parent


def test_after_a_landing_nothing_else_lands_until_the_check_after_it_passes(rig: Rig) -> None:
    wc.request(rig.home, "open", minutes=60)
    rig.loop.tick()
    commit, parent = _land_one(rig)
    rig.loop.tick()

    job = rig.link.jobs[0]
    assert (job.kind, job.base, job.commit, job.changed) == (cj.AFTER, parent, commit, ("thomas/fix_me.py",))
    rig.loop.tick()
    assert rig.lane.allowed[-1] is False
    rig.link.verdict = cj.PASSED
    rig.loop.tick()
    assert rig.lane.allowed[-1] is True and rig.window.opened is not None and "after_check" in rig.events()


def test_a_failed_check_after_landing_closes_the_window_and_starts_the_revert_on_its_card(rig: Rig) -> None:
    wc.request(rig.home, "open", minutes=60)
    rig.loop.tick()
    _land_one(rig)
    rig.loop.tick()
    rig.link.verdict = cj.FAILED
    rig.loop.tick()

    assert rig.window.opened is None
    assert "revert_pending" in rig.events()  # the revert is queued, on record, before the check is (review D8)
    assert rig.events().index("revert_pending") < rig.events().index("after_check")
    assert rig.events().index("after_check") < rig.events().index("window_closed")
    assert rig.undoer.started == [(SID, "revert_change", ("tests/test_x.py::test_a",), (SID,))]


def test_an_undo_request_starts_the_undo(rig: Rig) -> None:
    wc.request(rig.home, "undo", sid=SID)
    rig.loop.tick()
    assert rig.undoer.started == [(SID, "undo_change", (), ())]


def test_the_card_loop_leaves_the_lanes_hand_ins_alone(rig: Rig) -> None:
    assert rig.loop.card_skip() == frozenset({SID})


def test_one_sign_in_prompt_at_a_time_across_both_loops() -> None:
    inside, most = [0], [0]
    lock = threading.Lock()

    def slow(action: str, reason: str) -> str:
        with lock:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        time.sleep(0.05)
        with lock:
            inside[0] -= 1
        return "approved"

    one = wl.OnePrompt(slow)
    threads = [threading.Thread(target=one, args=("a", "b")) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert most[0] == 1
