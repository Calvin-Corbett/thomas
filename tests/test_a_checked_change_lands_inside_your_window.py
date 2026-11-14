"""A hand-in lands inside your window only with every condition of spec section 8.2, and never asks a card.

No one outside Thomas looks at it first: while a window is open the lane takes up every hand-in no card has taken, and
Thomas's own gates (the checker, the second look, the never-in-a-window list and every card landing's checks) decide.
Its own git repo stands in for the running Thomas, its own tmp cage, pin and record folders for the real ones. The
checker and the second look are stand-ins that answer as told; no Windows sign-in can be shown (the asker fails the
test if it is called).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import time
from pathlib import Path

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp
from scripts.cage import window_evidence as we
from scripts.cage import window_lane as wl
from scripts.cage import window_review as wrev
from scripts.cage import window_state as ws
from scripts.cage.referee.presence import Presence
from scripts.cage.window_record import Record
from scripts.cage.window_rules import Rules

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


class FakeLink:
    def __init__(self, verdict: str = cj.PASSED, why: str = "", findings: tuple[str, ...] = ()) -> None:
        self.verdict, self.why, self.findings = verdict, why, findings
        self.jobs: list[cj.Job] = []
        self.forgotten: list[str] = []

    def post(self, kind: str, *, base: str, commit: str, tree: str, changed: list[str], tests=()) -> cj.Job:
        job = cj.Job(secrets.token_hex(12), kind, base, commit, tree, tuple(changed), tuple(tests), 1.0)
        self.jobs.append(job)
        return job

    def result(self, job: cj.Job) -> cj.Result:
        # As the real checker answers: a test ran (a PASSED with no test seen is no pass: 2026-10-14 review, B3).
        return cj.Result(job.id, job.kind, job.base, job.commit, job.tree, self.verdict, self.why,
                         findings=self.findings, ran=1, seen=3)  # fmt: skip

    def forget(self, job: cj.Job) -> None:
        self.forgotten.append(job.id)


class FakeReviewer:
    def __init__(self, verdict: str = wrev.SAFE, findings: tuple[str, ...] = ()) -> None:
        self.verdict, self.findings = verdict, findings
        self.read: list[str] = []

    def review(self, *, change: str, commit: str, summary: str, diff: str) -> wrev.Review:
        self.read.append(commit)
        return wrev.Review(change, self.verdict, self.findings)


def _never_ask(action: str, reason: str) -> bool:
    raise AssertionError(f"a window landing must never ask a card: {action}")


@pytest.fixture
def blue(tmp_path: Path) -> Path:
    repo = make_blue(tmp_path)
    git(repo, "checkout", "-q", "-b", "dev")
    return repo


@pytest.fixture
def pins(tmp_path: Path) -> Path:
    root = tmp_path / "pins"
    root.mkdir()
    (root / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
    return root


def _hand_in(blue: Path, files: dict[str, str], sid: str = SID) -> tuple[Path, bytes]:
    """A hand-in as green_handoff writes one: the patch of *files* on dev, and its manifest."""
    base = git(blue, "rev-parse", "dev")
    git(blue, "checkout", "-q", "-b", f"work-{sid}")
    for rel, text in files.items():
        (blue / rel).parent.mkdir(parents=True, exist_ok=True)
        (blue / rel).write_text(text, encoding="utf-8")
    git(blue, "add", "-A")
    git(blue, "commit", "-qm", "work")
    patch = subprocess.run(
        ["git", "diff", "--binary", "--full-index", base, "HEAD"], cwd=blue, capture_output=True
    ).stdout
    git(blue, "checkout", "-q", "dev")
    sub = cage_shell.cage_root() / "inbox" / sid
    sub.mkdir(parents=True)
    (sub / "change.patch").write_bytes(patch)
    manifest = {"kind": "self_change", "id": sid, "base": base, "patch_sha256": hashlib.sha256(patch).hexdigest(),
                "summary": "Fixed it.", "chat": "chat-1", "execution_id": "exec-1", "submitted_at": time.time()}  # fmt: skip
    (sub / "submission.json").write_text(json.dumps(manifest), encoding="utf-8")
    return sub, patch


class World:
    def __init__(self, blue: Path, pins: Path, tmp_path: Path, link: FakeLink, reviewer: FakeReviewer) -> None:
        self.blue, self.link, self.reviewer = blue, link, reviewer
        (tmp_path / "record").mkdir()
        self.record = Record(tmp_path / "record")
        self.promoter = sp.Promoter(
            repo=blue, cage_root=cage_shell.cage_root(), ask=_never_ask, pin_root=pins, audit=lambda _r: []
        )
        self.lane = wl.Lane(self.promoter, link=link, reviewer=reviewer, rules=Rules(blue, modules={}),
                            record=self.record, clock=time.time)  # fmt: skip
        self.window = ws.Window(presence=Here(), off_markers=[tmp_path / "off"], ceiling_minutes=120,
                                max_landings=25, idle_minutes=15, clock=Clock())  # fmt: skip

    def open(self) -> ws.Opened:
        return self.window.open(60, "ABC-DEF", "0123456789abcdef", before=Presence(False, 3.0, "1:42"))

    def run(
        self, *, busy: frozenset[str] = frozenset(), allowed: bool = True, passes: int = 40, reliable: bool = True
    ) -> sp.Outcome | None:
        """Passes of the window's loop as far as the lane goes: take up what an open window may land, then step."""
        for _ in range(passes):
            self.lane.take(self.window, card_busy=busy, reliable=reliable)
            outcome = self.lane.step(self.window, card_busy=busy, landing_allowed=allowed)
            if outcome is not None:
                return outcome
            time.sleep(0.02)  # the second look runs on a thread of its own
        return None


@pytest.fixture
def world(blue: Path, pins: Path, tmp_path: Path) -> World:
    return World(blue, pins, tmp_path, FakeLink(), FakeReviewer())


def _verdict(sid: str = SID) -> dict:
    return json.loads((cage_shell.cage_root() / "outbox" / f"{sid}.verdict.json").read_text(encoding="utf-8"))


def test_a_checked_change_lands_in_an_open_window_with_no_card_and_no_one_asked(world: World) -> None:
    before = git(world.blue, "rev-parse", "dev")
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n", "tests/test_fix_me.py": "def test(): pass\n"})
    opened = world.open()

    outcome = world.run()

    assert outcome is not None and outcome.status == "landed", outcome
    assert git(world.blue, "rev-parse", "dev") == outcome.commit_sha != before
    assert (world.blue / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    message = git(world.blue, "log", "-1", "--format=%B", "dev")
    assert f"(window {opened.window_id}, pairing code ABC-DEF)" in message and "no card of its own" in message
    assert "passed by the checker and a second look" in message and "operator" not in message
    assert "Thomas-Gated: owner-window/windows-sign-in" in message and "card(s)" not in message
    assert f"Thomas-Submission-Id: {SID}" in message and "Thomas-Committed-By: self-change-promoter" in message
    verdict = _verdict()
    assert verdict["status"] == "landed" and verdict["window"]["window_id"] == opened.window_id
    assert not sub.exists() and SID not in world.lane.owned(), "the hand-in is done and has left the lane"
    names = [event["name"] for event in world.record.events()]
    assert names.index("landing_intent") < names.index("landed")
    assert world.window.landings == 1
    job = world.link.jobs[0]
    assert (job.base, job.tree) == (before, git(world.blue, "rev-parse", "dev^{tree}")), "checked = landed tree"


def test_a_change_with_a_never_in_a_window_file_goes_to_the_card_loop(world: World) -> None:
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n", "scripts/cage/new_rule.py": "RULE = 1\n"})
    world.open()

    assert world.run(passes=5) is None and sub.exists()
    assert SID not in world.lane.owned() and world.lane.takeable(frozenset()) == [], "never taken up again"
    assert "scripts/cage/new_rule.py" in world.lane.waiting()[0]["wait"] and world.link.jobs == []


@pytest.mark.parametrize(
    ("link", "reviewer", "words"),
    [
        (FakeLink(cj.FAILED, "1 test(s) fail alone", ("tests/test_fix_me.py::test",)), FakeReviewer(), "checker"),
        (FakeLink(), FakeReviewer(wrev.NOT_SAFE, ("thomas/fix_me.py:1 reaches out",)), "second look"),
    ],
)
def test_a_failed_check_or_a_not_safe_second_look_refuses_it_back_to_its_team(
    blue: Path, pins: Path, tmp_path: Path, link: FakeLink, reviewer: FakeReviewer, words: str
) -> None:
    world = World(blue, pins, tmp_path, link, reviewer)
    before = git(blue, "rev-parse", "dev")
    _hand_in(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()

    outcome = world.run()

    assert outcome is not None and outcome.status == "refused" and words in outcome.detail
    assert git(blue, "rev-parse", "dev") == before and _verdict()["status"] == "refused"
    assert SID not in world.lane.owned()


@pytest.mark.parametrize(
    ("link", "reviewer"),
    [(FakeLink(cj.UNAVAILABLE, "no copies"), FakeReviewer()), (FakeLink(), FakeReviewer(wrev.UNAVAILABLE))],
)
def test_nothing_lands_without_both_a_passed_check_and_a_safe_second_look(
    blue: Path, pins: Path, tmp_path: Path, link: FakeLink, reviewer: FakeReviewer
) -> None:
    world = World(blue, pins, tmp_path, link, reviewer)
    before = git(blue, "rev-parse", "dev")
    sub, _ = _hand_in(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()

    assert world.run(passes=8) is None and sub.exists() and git(blue, "rev-parse", "dev") == before
    assert "tried again" in world.lane.waiting()[0]["wait"]


def test_a_check_that_could_not_run_waits_and_is_tried_again(blue: Path, pins: Path, tmp_path: Path) -> None:
    world = World(blue, pins, tmp_path, FakeLink(cj.UNAVAILABLE, "no copies"), FakeReviewer())
    sub, _ = _hand_in(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()

    assert world.run(passes=5) is None and sub.exists()
    assert "tried again" in world.lane.waiting()[0]["wait"] and len(world.link.jobs) == 1
    world.link.verdict = cj.PASSED
    world.lane.evidence.clock = lambda: time.time() + we.RETRY_S + 1
    assert world.run().status == "landed" and len(world.link.jobs) == 2  # type: ignore[union-attr]


def test_dev_moving_after_the_check_means_a_new_check_before_landing(world: World) -> None:
    _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()
    world.run(allowed=False, passes=5)  # checked and read, waiting for the check after the last landing
    (world.blue / "README.md").write_text("moved on\n", encoding="utf-8")
    git(world.blue, "commit", "-qam", "someone else landed")

    outcome = world.run()

    assert outcome is not None and outcome.status == "landed"
    assert len(world.link.jobs) == 2 and world.link.jobs[1].base == git(world.blue, "rev-parse", "dev^")


def test_nothing_lands_while_the_check_after_the_last_landing_runs_or_the_card_loop_holds_it(world: World) -> None:
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()
    assert world.run(allowed=False, passes=10) is None
    assert world.run(busy=frozenset({SID}), passes=5) is None and sub.exists()
