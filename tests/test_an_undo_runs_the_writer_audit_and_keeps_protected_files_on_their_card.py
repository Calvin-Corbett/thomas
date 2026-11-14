"""An undo runs the writer audit every landing runs, and never stands in for a protected file's own card (2026-10-14 review, D7). From Codex's lineage (work/part4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.green_support import git
from tests.test_a_checked_change_lands_inside_your_window import (
    SID,
    blue,  # noqa: F401 -- shared isolated-repository fixture
    pins,  # noqa: F401 -- shared fake pin fixture
    world,  # noqa: F401 -- shared isolated window fixture
)
from tests.test_an_undo_is_checked_first_and_asked_on_its_own_card import (
    Asker,
    FakeLink,
    _land,
    _undoer,
    _until_done,
)


def test_an_undo_does_not_land_when_a_writer_appears_while_the_card_is_up(
    blue: Path, pins: Path, tmp_path: Path
) -> None:
    git(blue, "config", "commit.gpgsign", "false")
    _land(blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    before = git(blue, "rev-parse", "dev")
    ask, link = Asker(), FakeLink()
    undoer = _undoer(blue, pins, tmp_path, link, ask)
    seen: list[str] = []

    def writer_audit(repo: Path) -> list[str]:
        seen.append("audit")
        assert ask.asked, "the writer audit must still protect the interval spent at the sign-in"
        return ["unexpected-writer"]

    undoer.p.audit = writer_audit
    assert undoer.start(SID) == ""
    said = _until_done(undoer)

    assert seen == ["audit"]
    assert "unexpected writers" in said and "unexpected-writer" in said
    assert git(blue, "rev-parse", "dev") == before
    assert (blue / "thomas/fix_me.py").read_text() == "VALUE = 2\n"


@pytest.mark.parametrize("path", ["scripts/cage/guard.py", "thomas/policy.py"])
def test_an_undo_of_a_dangerous_file_requires_its_normal_protected_change_path(
    blue: Path, pins: Path, tmp_path: Path, path: str
) -> None:
    git(blue, "config", "commit.gpgsign", "false")
    files = {path: "GUARD = True\n"}
    if path == "thomas/policy.py":
        files["agent_safety.toml"] = '[protected]\npolicy_files = ["thomas/policy.py"]\n'
    _land(blue, files)
    before = git(blue, "rev-parse", "dev")
    ask = Asker()
    undoer = _undoer(blue, pins, tmp_path, FakeLink(), ask)

    assert undoer.start(SID) == ""
    said = _until_done(undoer)

    assert "own protected-change card" in said and path in said
    assert ask.asked == [], "a single undo card cannot replace the dangerous-file card"
    assert git(blue, "rev-parse", "dev") == before
