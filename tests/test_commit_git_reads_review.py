"""Review fixes to the batched git reads (scripts/crew/brief/git_reads.py): path spellings, glob characters, packed refs.

Companion to tests/test_commit_git_reads.py, whose helpers these tests use.
"""

from __future__ import annotations

from pathlib import Path

from scripts.crew.brief import git_reads

from tests.test_commit_git_reads import _count_calls, _git, _repo


def test_tracked_among_reads_a_spelling_git_does_not_use_the_way_git_does(tmp_path: Path, monkeypatch) -> None:
    # Review finding: the listing was compared with the caller's own spelling, so a tracked gate registered as
    # "./scripts/x.py" read as untracked and was silently left out. Every spelling below names a tracked file.
    repo = _repo(tmp_path)
    (repo / "untracked.py").write_text("x = 1\n")
    spellings = ["./a.txt", "dir//b c.txt", "dir/../a.txt", "dir\\b c.txt", ".\\dir\\b c.txt", "dir/./b c.txt"]
    assert git_reads.tracked_among(repo, spellings) == set(spellings)
    # ...and the same spellings of a file git does not track are still untracked
    ghost = ["./untracked.py", "dir/../untracked.py", "dir//ghost.py"]
    assert git_reads.tracked_among(repo, ghost + spellings) == set(spellings)
    # a spelling that leaves the repo is "outside": nothing git can say, so it is never reported unreviewed
    assert git_reads.tracked_among(repo, ["../elsewhere.py", "..", "."]) == {"../elsewhere.py", "..", "."}


def test_tracked_among_takes_a_path_with_glob_characters_literally(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "g1.py").write_text("x = 1\n")
    (repo / "g[1].py").write_text("x = 2\n")  # tracked; the pattern would also match g1.py if it were read as a glob
    _git(repo, "add", "g[1].py")
    _git(repo, "commit", "-qm", "glob name")
    assert git_reads.tracked_among(repo, ["g[1].py"]) == {"g[1].py"}
    assert git_reads.tracked_among(repo, ["g?.py"]) == set()  # a glob is not a file


def test_head_probe_is_a_file_read_while_the_ref_is_loose_and_once_it_is_packed(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    probe = git_reads.HeadProbe(repo, "master")
    calls = _count_calls(monkeypatch, git_reads, "run_git")
    assert probe() == _git(repo, "rev-parse", "HEAD")
    assert calls == []  # no process
    _git(repo, "pack-refs", "--all")
    assert not (repo / ".git" / "refs" / "heads" / "master").exists()  # really packed now
    assert probe() == _git(repo, "rev-parse", "HEAD")
    assert calls == [], "a packed ref cost a git process on every read (about 80 per ladder)"
    # a landing after the pack makes the ref loose again, and the loose file wins over the stale packed line
    (repo / "a.txt").write_bytes(b"two\n")
    _git(repo, "commit", "-qam", "next")
    assert probe() == _git(repo, "rev-parse", "HEAD")
    assert probe() != _git(repo, "rev-parse", "HEAD~1")
    assert calls == []


def test_head_probe_asks_git_only_when_neither_ref_file_can_answer(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    probe = git_reads.HeadProbe(repo, "master")
    probe._loose = probe._packed = None  # a ref format with no loose file and no packed-refs (reftable)
    calls = _count_calls(monkeypatch, git_reads, "run_git")
    assert probe() == _git(repo, "rev-parse", "HEAD")
    assert len(calls) == 1


def test_head_probe_does_not_take_another_branchs_packed_line_for_this_one(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    _git(repo, "branch", "master-two")
    _git(repo, "pack-refs", "--all")
    calls = _count_calls(monkeypatch, git_reads, "run_git")
    assert git_reads.HeadProbe(repo, "master")() == _git(repo, "rev-parse", "master")
    assert git_reads.HeadProbe(repo, "master-two")() == _git(repo, "rev-parse", "master-two")
    assert all(call[1][:2] == ["rev-parse", "--git-path"] for call in calls)  # only the two path lookups per probe
