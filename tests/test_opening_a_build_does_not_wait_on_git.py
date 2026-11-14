"""Opening a build must not cost 15 to 40 seconds of git every time.

You said: "its taking a long time to load pages and chats ... make them pages stop loading so slow". Measured on
2026-11-06, the page's CHANGED FILES request took 17.8 s for a small build, 14.9 s for gates and 39.3 s for AI control,
on every open: one git status, then up to three git calls per file, one file after another.

Two things fixed it, and each test here fails without its fix:
* a build nobody touched is answered from memory, and anything git could see differently still goes to git;
* a page of many files reads its diffs side by side, in the order asked, and the first failure still wins.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_git
from thomas.server import change_evidence_cache as cache

SCOPED = [f"tracked{i}.txt" for i in range(5)] + [f"new{i}.txt" for i in range(3)]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "core.autocrlf", "false")
    for i in range(5):
        (root / f"tracked{i}.txt").write_text(f"line {i}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "first")
    for i in range(5):
        (root / f"tracked{i}.txt").write_text(f"changed {i}\n", encoding="utf-8")
    for i in range(3):
        (root / f"new{i}.txt").write_text(f"new {i}\n", encoding="utf-8")
    cache.forget_all()
    return root


def _count_git_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = forge_code_git._run_git

    def counting(root, args, timeout=30):
        calls.append(args[0])
        return real(root, args, timeout)

    monkeypatch.setattr(forge_code_git, "_run_git", counting)
    return calls


def test_a_build_nobody_touched_is_answered_without_asking_git(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = cache.scoped_evidence(repo, SCOPED)
    assert len(first) == len(SCOPED)
    assert any("changed 0" in row["diff"] for row in first), "the diffs must still be real git output"
    calls = _count_git_calls(monkeypatch)

    second = cache.scoped_evidence(repo, SCOPED)

    assert calls == [], f"an untouched build still asked git {len(calls)} times: {calls}"
    assert second == first


def test_an_edit_is_seen_at_once(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache.scoped_evidence(repo, SCOPED)
    (repo / "tracked0.txt").write_text("edited after the first look, and longer\n", encoding="utf-8")
    calls = _count_git_calls(monkeypatch)

    after = cache.scoped_evidence(repo, SCOPED)

    assert calls, "an edited file must go back to git"
    assert any("edited after the first look" in row["diff"] for row in after if row["file"] == "tracked0.txt")


def test_staging_a_file_is_seen_at_once(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache.scoped_evidence(repo, SCOPED)
    _git(repo, "add", "tracked1.txt")
    calls = _count_git_calls(monkeypatch)

    cache.scoped_evidence(repo, SCOPED)

    assert calls, "a change to the index must go back to git"


def test_a_commit_is_seen_at_once(repo: Path) -> None:
    before = cache.scoped_evidence(repo, SCOPED)
    assert before
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "everything")

    assert cache.scoped_evidence(repo, SCOPED) == [], "committed files are no longer changes"


def test_a_folder_it_cannot_prove_is_always_read_from_git(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache.scoped_evidence(repo, None)
    calls = _count_git_calls(monkeypatch)

    cache.scoped_evidence(repo, None)

    assert calls, "with no list of files to prove, every look goes to git"


def test_a_remembered_answer_cannot_be_changed_by_whoever_got_it(repo: Path) -> None:
    cache.scoped_evidence(repo, SCOPED)
    mine = cache.scoped_evidence(repo, SCOPED)
    mine[0]["diff"] = "scribbled on"
    mine.pop()

    again = cache.scoped_evidence(repo, SCOPED)

    assert len(again) == len(SCOPED)
    assert again[0]["diff"] != "scribbled on"


def test_a_page_of_many_files_reads_its_diffs_side_by_side_in_order(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [f"f{i:02d}.txt" for i in range(12)]
    lock = threading.Lock()
    running = {"now": 0, "most": 0}

    def slow_diff(_root, file, *, untracked=None):
        with lock:
            running["now"] += 1
            running["most"] = max(running["most"], running["now"])
        time.sleep(0.05)
        with lock:
            running["now"] -= 1
        return f"diff of {file}"

    monkeypatch.setattr(forge_code_git, "unified_diff", slow_diff)

    rows = forge_code_git.change_evidence(repo, files)

    assert [row["file"] for row in rows] == files, "the files must stay in the order asked"
    assert [row["diff"] for row in rows] == [f"diff of {file}" for file in files]
    assert running["most"] >= 2, "twelve files were read one after another"


def test_the_first_failure_still_wins(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_diff(_root, file, *, untracked=None):
        if file == "f03.txt":
            raise forge_code_git.ForgeCodeGitError("git could not confirm f03.txt")
        return f"diff of {file}"

    monkeypatch.setattr(forge_code_git, "unified_diff", failing_diff)

    with pytest.raises(forge_code_git.ForgeCodeGitError, match="f03.txt"):
        forge_code_git.change_evidence(repo, [f"f{i:02d}.txt" for i in range(8)])
