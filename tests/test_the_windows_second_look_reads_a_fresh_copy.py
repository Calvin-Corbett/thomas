"""The second look a window relies on reads a fresh copy with nothing of the project's loaded (spec 8.1, 8.2 cond. 3).

Since 2026-10-25 it is one plain ChatGPT call with no tools ("make it all chat gpt for the review too"). A fake stands
in for ChatGPT: these tests never call the real model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import window_review as wr

from tests.green_support import git, make_blue

CHANGE = "c" * 64
DIFF = "diff --git a/thomas/fix_me.py b/thomas/fix_me.py\n-VALUE = 1\n+VALUE = 2\n"


class FakeChatGPT:
    def __init__(self, answer: str, *, code: int = 0) -> None:
        self.answer, self.code = answer, code
        self.calls: list[tuple[list[str], Path, str]] = []
        self.seen_files: dict[str, str] = {}

    def __call__(self, argv: list[str], cwd: Path, prompt: str, timeout: float) -> tuple[int, str]:
        self.calls.append((argv, cwd, prompt))
        self.seen_files = {p.relative_to(cwd).as_posix(): p.read_text(encoding="utf-8") for p in cwd.rglob("*.py")}
        self.seen_git = (cwd / ".git").exists()
        return self.code, self.answer


def _json(verdict: str, findings: list[str], **extra: object) -> str:
    inner = json.dumps({"verdict": verdict, "findings": findings})
    return json.dumps({"type": "result", "result": f"I read it.\n{inner}", "is_error": False, **extra})


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    repo = make_blue(tmp_path)
    (repo / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(repo, "commit", "-qam", "the change")
    return repo, git(repo, "rev-parse", "HEAD")


def _reviewer(repo: Path, tmp_path: Path, chat: FakeChatGPT) -> wr.Reviewer:
    return wr.Reviewer(repo=repo, copies=tmp_path / "copies", run=chat)


def test_it_is_one_chatgpt_call_that_names_no_tool() -> None:
    assert wr.call("gpt-6.1-sol", "high") == ["chatgpt", "gpt-6.1-sol", "high"]
    reviewer = wr.Reviewer(repo=Path("."), copies=Path("."))
    assert reviewer.run is wr.run_chatgpt and reviewer.model == wr.DEFAULT_MODEL
    assert "You have no tools" in wr.prompt("s", DIFF)


def test_it_reads_a_copy_of_the_exact_commit_with_no_git_folder(repo: tuple[Path, str], tmp_path: Path) -> None:
    path, commit = repo
    chat = FakeChatGPT(_json("SAFE", []))

    review = _reviewer(path, tmp_path, chat).review(change=CHANGE, commit=commit, summary="Fixed it.", diff=DIFF)

    assert review.safe and review.change == CHANGE
    assert chat.seen_files["thomas/fix_me.py"] == "VALUE = 2\n" and not chat.seen_git
    assert not list((tmp_path / "copies").glob("*")), "the copy is removed after the second look"
    sent = chat.calls[0][2]
    assert "written by the team, not by the owner" in sent
    assert "=== thomas/fix_me.py ===\nVALUE = 2\n" in sent, "the changed file's full text, from the copy"


@pytest.mark.parametrize(
    ("answer", "code", "verdict"),
    [
        (_json("NOT_SAFE", ["thomas/fix_me.py:1 reaches the network"]), 0, wr.NOT_SAFE),
        (_json("NOT_SAFE", []), 0, wr.UNAVAILABLE),
        (_json("MAYBE", []), 0, wr.UNAVAILABLE),
        (_json("SAFE", [], is_error=True), 0, wr.UNAVAILABLE),
        (_json("SAFE", []), 1, wr.UNAVAILABLE),
        ("not json at all", 0, wr.UNAVAILABLE),
    ],
)
def test_only_a_clear_answer_counts(
    repo: tuple[Path, str], tmp_path: Path, answer: str, code: int, verdict: str
) -> None:
    path, commit = repo
    review = _reviewer(path, tmp_path, FakeChatGPT(answer, code=code)).review(
        change=CHANGE, commit=commit, summary="", diff=""
    )
    assert review.verdict == verdict
    assert not review.safe or verdict == wr.SAFE


def test_chatgpt_that_cannot_answer_gives_no_second_look(repo: tuple[Path, str], tmp_path: Path) -> None:
    path, commit = repo
    signed_out = json.dumps({"type": "result", "is_error": True, "result": "ChatGPT gave no answer: not signed in"})
    review = _reviewer(path, tmp_path, FakeChatGPT(signed_out, code=1)).review(
        change=CHANGE, commit=commit, summary="", diff=DIFF
    )
    assert review.verdict == wr.UNAVAILABLE and "not signed in" in review.why


def test_the_prompt_names_every_changed_file() -> None:
    diff = "diff --git a/thomas/a.py b/thomas/a.py\n+x\ndiff --git a/tests/test_a.py b/tests/test_a.py\n+y\n"
    assert "Changed files: thomas/a.py, tests/test_a.py" in wr.prompt("s", diff)


def test_files_beyond_the_budget_are_cut_and_said_to_be(tmp_path: Path) -> None:
    (tmp_path / "big.py").write_text("x" * 50, encoding="utf-8")
    diff = "diff --git a/big.py b/big.py\n+x\ndiff --git a/gone.py b/gone.py\n-y\n"
    text = wr.changed_files(tmp_path, diff, budget=20)
    assert "=== big.py ===\n" + "x" * 20 + "\n(the rest of this file is not shown)" in text
    assert "(further files are not shown)" in text and "gone.py" not in text
    assert text.endswith(wr.CUT), "a cut file is said to be cut, even the last one"


@pytest.mark.parametrize("too_big", ["diff", "files"])
def test_a_change_too_large_to_read_whole_is_never_judged_on_a_part(
    repo: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, too_big: str
) -> None:
    """2026-10-26: a 37-file change cut to 100k characters was refused for the files the reviewer was not shown."""
    path, commit = repo
    chat = FakeChatGPT(_json("NOT_SAFE", ["the rest is not shown"]))
    monkeypatch.setattr(wr, "DIFF_SHOWN" if too_big == "diff" else "FILES_SHOWN", 10)
    if too_big == "files":
        monkeypatch.setattr(wr.changed_files, "__defaults__", (10,))
    review = _reviewer(path, tmp_path, chat).review(change=CHANGE, commit=commit, summary="s", diff=DIFF)
    assert review.verdict == wr.TOO_LARGE and "larger than one second look can read whole" in review.why
    assert chat.calls == [], "ChatGPT is not asked about a part of a change"
