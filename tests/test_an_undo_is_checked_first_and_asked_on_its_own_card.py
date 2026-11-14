"""An undo is checked by the checker on today's dev, then asked on its own card; nothing lands until you approve.

Spec 2026-10-12, sections 8.5 and 8.6. Its own git repo, tmp cage and record; a stand-in checker and a stand-in asker
(no Windows sign-in is shown).
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp
from scripts.cage import window_undo as wu
from scripts.cage.window_record import Record

from tests.green_support import git, make_blue
from thomas.tools import cage_shell, trusted_card

SID = "self-thomas-0123456789ab"


class FakeLink:
    def __init__(self, verdict: str = cj.PASSED) -> None:
        self.verdict = verdict
        self.jobs: list[cj.Job] = []

    def post(self, kind: str, *, base: str, commit: str, tree: str, changed: list[str], tests=()) -> cj.Job:
        self.jobs.append(cj.Job(secrets.token_hex(12), kind, base, commit, tree, tuple(changed), (), 1.0))
        return self.jobs[-1]

    def result(self, job: cj.Job) -> cj.Result:
        return cj.Result(job.id, job.kind, job.base, job.commit, job.tree, self.verdict, "1 test fails")

    def forget(self, job: cj.Job) -> None:
        pass


class Asker:
    def __init__(self, answer: str = "approved") -> None:
        self.answer = answer
        self.asked: list[tuple[str, dict[str, object]]] = []

    def __call__(self, p: sp.Promoter, kind: str, details: dict, digest: str, nonce: str) -> tuple[str, str]:
        self.asked.append((kind, details))
        return self.answer, "ABC-DEF"


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


def _land(blue: Path, files: dict[str, str], sid: str = SID) -> str:
    """A change as the promoter lands one: its own two trailers, dev and the running copy moved."""
    parent = git(blue, "rev-parse", "dev")
    for rel, text in files.items():
        (blue / rel).parent.mkdir(parents=True, exist_ok=True)
        (blue / rel).write_text(text, encoding="utf-8")
    git(blue, "add", "-A")
    tree = git(blue, "write-tree")
    trailers = [("Thomas-Committed-By", "self-change-promoter"), ("Thomas-Submission-Id", sid)]
    commit = checks.make_commit(blue, tree, parent, f"self-fix: {sid}", trailers)
    git(blue, "update-ref", "refs/heads/dev", commit, parent)
    git(blue, "reset", "-q", "--hard", "dev")
    return commit


def _undoer(blue: Path, pins: Path, tmp_path: Path, link: FakeLink, ask: Asker) -> wu.Undoer:
    (tmp_path / "record").mkdir(exist_ok=True)
    p = sp.Promoter(repo=blue, cage_root=cage_shell.cage_root(), ask=lambda a, r: False, pin_root=pins,
                    audit=lambda _r: [])  # fmt: skip
    return wu.Undoer(p, link=link, record=Record(tmp_path / "record"), ask=ask)


def _until_done(undoer: wu.Undoer, passes: int = 6) -> str:
    said = ""
    for _ in range(passes):
        said = undoer.step()
        if undoer.current is None:
            return said
    return said


def test_an_undo_the_checker_passed_lands_after_you_approve_its_card(blue: Path, pins: Path, tmp_path: Path) -> None:
    landed = _land(blue, {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "NEW = 1\n"})
    ask, link = Asker(), FakeLink()
    undoer = _undoer(blue, pins, tmp_path, link, ask)

    assert undoer.start(SID) == ""
    said = _until_done(undoer)

    assert said.startswith("undone:"), said
    assert (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (blue / "thomas" / "new.py").exists()
    assert git(blue, "rev-parse", "dev^") == landed, "a forward commit, never a rewind"
    message = git(blue, "log", "-1", "--format=%B", "dev")
    assert f"Thomas-Submission-Id: undo-{SID}" in message and "Thomas-Gated: owner-approved/windows-sign-in" in message
    kind, details = ask.asked[0]
    assert kind == "undo_change" and details["sid"] == SID and "thomas/new.py" in str(details["files"])
    assert link.jobs[0].base == landed and sorted(link.jobs[0].changed) == ["thomas/fix_me.py"]
    assert [e["name"] for e in Record(tmp_path / "record").events()] == ["undo_landed"]


def test_cancel_undoes_nothing(blue: Path, pins: Path, tmp_path: Path) -> None:
    _land(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    before = git(blue, "rev-parse", "dev")
    undoer = _undoer(blue, pins, tmp_path, FakeLink(), Asker("cancelled"))
    undoer.start(SID)
    assert "cancelled" in _until_done(undoer) and git(blue, "rev-parse", "dev") == before


def test_an_undo_that_fails_the_checker_is_never_asked(blue: Path, pins: Path, tmp_path: Path) -> None:
    _land(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Asker()
    undoer = _undoer(blue, pins, tmp_path, FakeLink(cj.FAILED), ask)
    undoer.start(SID)
    assert "fails the checker" in _until_done(undoer) and ask.asked == []


def test_an_undo_a_later_change_blocks_names_that_change(blue: Path, pins: Path, tmp_path: Path) -> None:
    _land(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    _land(blue, {"thomas/fix_me.py": "VALUE = 3\n"}, "self-thomas-later0000000")
    ask = Asker()
    undoer = _undoer(blue, pins, tmp_path, FakeLink(), ask)
    undoer.start(SID)

    said = _until_done(undoer)

    assert "does not apply" in said and "self-thomas-later0000000" in said and ask.asked == []


def test_only_a_change_the_promoter_landed_can_be_undone(blue: Path, pins: Path, tmp_path: Path) -> None:
    undoer = _undoer(blue, pins, tmp_path, FakeLink(), Asker())
    assert "no change the promoter landed" in undoer.start("self-thomas-nothing0000")
    assert "no undo card" in undoer.start(SID, kind="anything")


def test_a_revert_after_a_failed_check_names_the_failures_and_the_batch(blue: Path, pins: Path, tmp_path: Path) -> None:
    _land(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Asker()
    undoer = _undoer(blue, pins, tmp_path, FakeLink(), ask)
    undoer.start(SID, kind="revert_change", failed=["tests/test_x.py::test_a"], batch=[SID, "self-thomas-other"])

    assert _until_done(undoer).startswith("undone:")
    kind, details = ask.asked[0]
    assert (
        kind == "revert_change"
        and details["failed"] == "tests/test_x.py::test_a"
        and "self-thomas-other" in details["batch"]
    )
