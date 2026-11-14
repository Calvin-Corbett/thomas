"""The canary measures a commit's own test selection, in an exported copy of that commit (2026-10-27).

e51b2c7f's selection took 20 to 83 minutes and was first run after it landed. The canary runs each commit's own
selection code on one fixed real change, so the code that would run is the code that is measured.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts.pipeline_canary import measure

STUB = """
import time
from pathlib import Path


class Selection:
    def __init__(self, files, left_out=()):
        self.files = tuple(files)
        self.left_out = tuple(left_out)


def select(root, changed, cap=360):
    delay, count, left = (Path(root) / "stub.txt").read_text().split()
    if int(count) < 0:
        raise RuntimeError("selection broke")
    time.sleep(float(delay))
    return Selection([f"tests/test_{i}.py" for i in range(int(count))], [f"tests/x_{i}.py" for i in range(int(left))])
"""


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    proof = repo / "thomas" / "server" / "proof"
    proof.mkdir(parents=True)
    for package in (repo / "thomas", repo / "thomas" / "server", proof):
        (package / "__init__.py").write_text("", encoding="utf-8")
    (proof / "selection.py").write_text(STUB, encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "dev", str(repo))
    _git(repo, "config", "user.email", "canary@test")
    _git(repo, "config", "user.name", "canary")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def commit_stub(repo: Path, delay: float, count: int, left: int = 0) -> str:
    (repo / "stub.txt").write_text(f"{delay} {count} {left}", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"stub {delay} {count} {left}")
    return _git(repo, "rev-parse", "HEAD")


def test_a_commit_is_measured_with_its_own_selection(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    first = commit_stub(repo, 0, 3, 1)
    second = commit_stub(repo, 0, 7)
    one = measure.measure(repo, first, tmp_path / "trees", python=sys.executable)
    two = measure.measure(repo, second, tmp_path / "trees", python=sys.executable)
    assert (one.files, one.left_out, one.error) == (3, 1, "") and one.seconds is not None
    assert (two.files, two.left_out, two.error) == (7, 0, "")
    assert one.commit == first and two.commit == second


def test_a_selection_past_the_backstop_is_reported_not_waited_on(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    slow = commit_stub(repo, 30, 3)
    result = measure.measure(repo, slow, tmp_path / "trees", timeout_s=2, python=sys.executable)
    assert result.seconds is None and result.error == "it did not finish: over 2 s"


def test_a_selection_that_raises_names_its_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    broken = commit_stub(repo, 0, -1)
    result = measure.measure(repo, broken, tmp_path / "trees", python=sys.executable)
    assert result.seconds is None and "RuntimeError: selection broke" in result.error


def test_an_export_is_reused_and_prune_keeps_only_the_named_trees(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    first, second = commit_stub(repo, 0, 1), commit_stub(repo, 0, 2)
    root = tmp_path / "trees"
    tree = measure.export(repo, first, root)
    (tree / "marker").write_text("kept", encoding="utf-8")
    assert measure.export(repo, first, root) == tree and (tree / "marker").exists()
    measure.export(repo, second, root)
    measure.prune(root, [second])
    assert sorted(p.name for p in root.iterdir()) == [second[:12]]


@pytest.mark.parametrize("bad", ["not-a-commit", ""])
def test_a_commit_that_cannot_be_exported_is_an_error(tmp_path: Path, bad: str) -> None:
    repo = make_repo(tmp_path)
    commit_stub(repo, 0, 1)
    result = measure.measure(repo, bad, tmp_path / "trees", python=sys.executable)
    assert result.seconds is None and result.error.startswith("it could not be exported")
