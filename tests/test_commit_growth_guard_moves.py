"""A split moves code; the commit growth guard must not count it as growth.

On 2026-09-07 the REPL split (f94894e2) created repl_turns.py with 786 lines
taken out of repl.py in the same commit, and CI's commit-growth-guard called
it 786 lines of growth. A new file whose non-blank lines are at least 80%
lines deleted elsewhere in the same commit is a move. The guard is a
protected file; the fix is a prepared owner tap, and the move test stays a
strict xfail until it lands.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.forge.gates.commit_growth_guard import _evaluate_commit  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "thomas").mkdir()
    return repo


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _lines(prefix: str, n: int) -> str:
    return "".join(f"def {prefix}_{i}():\n    return {i}\n\n" for i in range(n))


@pytest.mark.xfail(strict=True, reason="waits on the growth-guard tap (tap_growth_guard_moves.py)")
def test_a_split_that_moves_lines_into_a_new_file_is_not_growth(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    big = repo / "thomas" / "big.py"
    big.write_text(_lines("a", 60) + _lines("b", 120), encoding="utf-8")
    _commit(repo, "one big file")
    big.write_text(_lines("a", 60), encoding="utf-8")
    (repo / "thomas" / "moved.py").write_text(_lines("b", 120), encoding="utf-8")
    sha = _commit(repo, "split: b_* move out")

    record = _evaluate_commit(repo, sha, max_growth=300, waivers=[], today=date(2026, 9, 7))

    assert record["ok"], record
    assert record["violations"] == []
    assert [m["path"] for m in record.get("moves", [])] == ["thomas/moved.py"]


def test_a_genuinely_new_file_over_the_cap_still_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "thomas" / "seed.py").write_text("x = 1\n", encoding="utf-8")
    _commit(repo, "seed")
    (repo / "thomas" / "new.py").write_text(_lines("n", 120), encoding="utf-8")
    sha = _commit(repo, "a new 360-line file")

    record = _evaluate_commit(repo, sha, max_growth=300, waivers=[], today=date(2026, 9, 7))

    assert not record["ok"]
    assert record["violations"][0]["path"] == "thomas/new.py"
    assert record["violations"][0]["is_new_file"]
