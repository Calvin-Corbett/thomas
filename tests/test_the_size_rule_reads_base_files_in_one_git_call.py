"""The size rule reads every measured file's earlier version with one git process, and reads what git show read.

Measured 2026-11-06: the server started about 100 git processes a minute, and green_handoff.size_problems ran one
``git show base:rel`` per measured file, twice per hand-in. Regression for green_handoff._blobs_at against a real git.
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from thomas.server import green_handoff


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def green(tmp_path: Path) -> types.SimpleNamespace:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "core.autocrlf", "true")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (tmp_path / "pkg" / "with space.py").write_text("x = 'é'\n", encoding="utf-8")
    (tmp_path / "empty.py").write_text("", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    return types.SimpleNamespace(git_dir=tmp_path / ".git", work=tmp_path, base=base)


def test_one_call_reads_what_git_show_read(green: types.SimpleNamespace) -> None:
    rels = ["pkg/a.py", "pkg/with space.py", "empty.py", "pkg/new.py", "pkg"]
    found = green_handoff._blobs_at(green, green.base, rels)
    assert found is not None
    assert set(found) == {"pkg/a.py", "pkg/with space.py", "empty.py"}, "a missing path or a folder is left out"
    for rel in found:
        assert found[rel] == green_handoff._green_git(green, "show", f"{green.base}:{rel}")


def test_no_files_asks_git_nothing(green: types.SimpleNamespace) -> None:
    assert green_handoff._blobs_at(green, green.base, []) == {}


def test_a_git_that_cannot_answer_lets_the_caller_ask_one_at_a_time(green: types.SimpleNamespace) -> None:
    broken = types.SimpleNamespace(git_dir=green.work / "nowhere", work=green.work, base=green.base)
    assert green_handoff._blobs_at(broken, green.base, ["pkg/a.py"]) is None
