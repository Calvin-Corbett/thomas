"""Leaving a guarded file out, and the running copy checked again after your answer.

Split from test_what_is_checked_is_what_lands.py (the commit-growth limit): Cancel on a guarded card leaves out exactly
that file, and the running copy is checked again right after an approval, before anything is committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks

from tests.green_support import git
from tests.test_a_self_fix_lands_only_when_you_approve import (  # noqa: F401
    Asker,
    _outbox,
    _promoter,
    _submit,
    blue,
    pins,
)

# -- leaving a guarded file out ---------------------------------------------------------------------------------- #


def test_cancel_leaves_out_exactly_a_file_whose_name_is_a_pattern(blue: Path, pins: Path) -> None:
    """git reads --exclude as a wildmatch pattern. Cancel on thomas/[f]ix_me.py kept that file, left out
    thomas/fix_me.py, which you were never asked about, and the promoter re-derived without end."""
    files = {"thomas/[f]ix_me.py": "import socket\n", "thomas/fix_me.py": "VALUE = 2\n"}
    sub = _submit(blue, "exec-bracket", files)
    ask = Asker(False, True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert len(ask.asked) == 2
    assert ask.asked[0][0].startswith("Change a file that guards Thomas") and "thomas/[f]ix_me.py" in ask.asked[0][0]
    assert "thomas/fix_me.py (+1 -1)" in ask.asked[1][0] and "[f]ix_me" not in ask.asked[1][0]
    assert outcome.files == ["thomas/fix_me.py"]
    assert git(blue, "show", "dev:thomas/fix_me.py") == "VALUE = 2"
    assert "thomas/[f]ix_me.py" not in git(blue, "ls-tree", "-r", "--name-only", "dev")


def test_exclude_args_name_each_path_exactly() -> None:
    assert checks.exclude_args(["apps/site/[slug]/page.tsx", "a*b?.py", "plain.py"]) == [
        "--exclude=apps/site/\\[slug\\]/page.tsx",
        "--exclude=a\\*b\\?.py",
        "--exclude=plain.py",
    ]


def test_a_file_git_does_not_leave_out_is_refused_not_asked_about_forever(
    blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = _submit(blue, "exec-kept", {"scripts/cage/new_rule.py": "RULE = 1\n", "thomas/fix_me.py": "VALUE = 2\n"})
    before = git(blue, "rev-parse", "dev")
    real = checks.derive_tree
    derived: list[list[str]] = []

    def leaves_nothing_out(repo, parent, patch, exclude=()):  # noqa: ANN001, ANN202 - as derive_tree
        derived.append(list(exclude))
        return real(repo, parent, patch, ())

    monkeypatch.setattr(checks, "derive_tree", leaves_nothing_out)
    ask = Asker(False, True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and "did not leave out scripts/cage/new_rule.py" in outcome.detail, outcome
    assert derived == [[], ["scripts/cage/new_rule.py"]] and len(ask.asked) == 1
    assert git(blue, "rev-parse", "dev") == before


def test_leaving_a_file_out_may_not_drop_another(blue: Path, pins: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = {"scripts/cage/new_rule.py": "RULE = 1\n", "thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "N = 1\n"}
    sub = _submit(blue, "exec-dropped", files)
    real = checks.derive_tree

    def drops_one_more(repo, parent, patch, exclude=()):  # noqa: ANN001, ANN202 - as derive_tree
        return real(repo, parent, patch, [*exclude, "thomas/new.py"] if exclude else ())

    monkeypatch.setattr(checks, "derive_tree", drops_one_more)
    ask = Asker(False, True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and "changed which other files" in outcome.detail, outcome
    assert len(ask.asked) == 1, "never asked about a change missing a file it was never asked about"


# -- the running copy, again after your answer ----------------------------------------------------------------- #


def test_the_running_copy_is_checked_again_after_your_answer(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-dirty-late", {"thomas/fix_me.py": "VALUE = 2\n"})

    def someone_edits_while_the_card_is_up(_action: str, _reason: str) -> bool:
        (blue / "thomas" / "fix_me.py").write_text("VALUE = 'work in progress'\n", encoding="utf-8")
        return True

    outcome = _promoter(blue, pins, someone_edits_while_the_card_is_up).promote(sub)

    assert outcome.status == "refused", outcome.detail
    assert outcome.detail == "the running copy has uncommitted work in thomas/fix_me.py", "today's words, read by SCS"
    assert git(blue, "rev-parse", "dev") == before, "nothing landed"
    assert "work in progress" in (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8"), "the work is intact"


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows reparse point")
def test_a_link_made_on_the_way_while_the_card_is_up_is_never_written_through(
    blue: Path, pins: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    sub = _submit(blue, "exec-junction-late", {"thomas/newdir/x.py": "X = 1\n"})

    def a_link_appears(_action: str, _reason: str) -> bool:
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(blue / "thomas" / "newdir"), str(elsewhere)], capture_output=True
        )
        assert made.returncode == 0, made.stderr
        return True

    outcome = _promoter(blue, pins, a_link_appears).promote(sub)

    assert outcome.status == "refused" and "is a link" in outcome.detail, outcome.detail
    assert list(elsewhere.iterdir()) == [], "nothing was written through the link"


_LINES = "".join(f"LINE_{n} = {n}\n" for n in range(1, 21))


def test_a_commit_to_dev_while_the_card_is_up_is_asked_about_again(blue: Path, pins: Path) -> None:
    """Someone commits in the running copy while the card is up, in another hunk of the change's own file. That is
    dev moving, not uncommitted work: the new tree is asked about again, as it always was. The check after your answer
    used to read the committed file as work missing from the old dev and refuse with "the running copy has uncommitted
    work in thomas/many.py", which was not true."""
    (blue / "thomas" / "many.py").write_text(_LINES, encoding="utf-8")
    git(blue, "add", "-A")
    git(blue, "commit", "-qm", "a file with many lines")
    sub = _submit(blue, "exec-moved-under", {"thomas/many.py": _LINES.replace("LINE_1 = 1\n", "LINE_1 = 100\n")})
    asked: list[str] = []

    def someone_commits_while_the_card_is_up(_action: str, reason: str) -> bool:
        asked.append(reason)
        if len(asked) == 1:
            path = blue / "thomas" / "many.py"
            path.write_text(path.read_text(encoding="utf-8").replace("LINE_20 = 20", "LINE_20 = 2000"), "utf-8")
            git(blue, "commit", "-qam", "someone else's work, in another hunk of the same file")
        return True

    outcome = _promoter(blue, pins, someone_commits_while_the_card_is_up).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert len(asked) == 2 and asked[0] != asked[1], "asked again, about the new tree"
    on_dev = git(blue, "show", "dev:thomas/many.py")
    assert "LINE_1 = 100" in on_dev and "LINE_20 = 2000" in on_dev
    assert (blue / "thomas" / "many.py").read_text(encoding="utf-8") == on_dev + "\n"
