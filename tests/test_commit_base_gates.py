"""Two gates judge the staged set against the temporary index's own base, not against a HEAD a neighbour just moved.

Measured on the live checkout with ten simulated agents: workboard_agent_claim refused 32 of 113 landing attempts and
workboard_changed_files 59 of 125, because `git diff --cached` against a HEAD that had advanced listed the neighbour's
landed files as staged by the committing agent. The commit tool now exports THOMAS_COMMIT_BASE (the tip the index was built
on) and these two gates diff against it when it is a full object name that is an ancestor of HEAD.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from scripts.forge.gates import _commit_base
from scripts.forge.gates import workboard_agent_claim as claim_gate
from scripts.forge.gates import workboard_changed_files as changed_gate

from tests.commit_lane_support import NEIGHBOUR, PY, git, mod, write


@pytest.fixture
def moved(tmp_path: Path, monkeypatch):
    """A temp index built on B0 with `mine.py` staged, then a neighbour commit B1 that adds `theirs.py`. Returns (B0, B1)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.name", "T")
    git(repo, "config", "user.email", "t@example.invalid")
    write(repo / "base.py", "x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    b0 = git(repo, "rev-parse", "HEAD")
    index = os.path.join(tempfile.mkdtemp(prefix=_commit_base.INDEX_DIR_PREFIX, dir=tmp_path), "index")
    env = {**os.environ, "GIT_INDEX_FILE": index}
    subprocess.run(["git", "read-tree", b0], cwd=repo, env=env, check=True)
    write(repo / "mine.py", "y = 2\n")
    subprocess.run(["git", "add", "mine.py"], cwd=repo, env=env, check=True)
    script = tmp_path / "neighbour.py"
    script.write_text(NEIGHBOUR, encoding="utf-8")
    subprocess.run([PY, str(script), str(repo), "theirs.py", "z = 3\n"], cwd=repo, check=True, capture_output=True)
    b1 = git(repo, "rev-parse", "HEAD")
    assert b0 != b1
    monkeypatch.setenv("GIT_INDEX_FILE", index)
    monkeypatch.setattr(claim_gate, "ROOT", repo)
    monkeypatch.setattr(changed_gate, "ROOT", repo)
    monkeypatch.delenv("THOMAS_COMMIT_BASE", raising=False)
    return b0, b1


def _both() -> tuple[list[str], list[str]]:
    return claim_gate._staged_files(), changed_gate._git_changed_files(base=None, head="HEAD", staged=True)


def test_without_a_base_a_neighbours_landed_file_reads_as_staged(moved) -> None:
    claim_files, changed_files = _both()
    assert "theirs.py" in claim_files and "theirs.py" in changed_files  # the measured refusal, reproduced


def test_with_the_base_only_the_agents_own_file_is_staged(moved, monkeypatch) -> None:
    b0, _b1 = moved
    monkeypatch.setenv("THOMAS_COMMIT_BASE", b0)
    assert _both() == (["mine.py"], ["mine.py"])


def test_the_base_is_accepted_in_any_letter_case(moved, monkeypatch) -> None:
    b0, _b1 = moved
    monkeypatch.setenv("THOMAS_COMMIT_BASE", b0.upper())
    assert _both() == (["mine.py"], ["mine.py"])


def test_a_base_that_is_not_a_full_object_name_is_ignored(moved, monkeypatch) -> None:
    b0, _b1 = moved
    for bad in (b0[:39], b0[:7], "not-a-sha", "", "HEAD~1", b0 + "0"):
        monkeypatch.setenv("THOMAS_COMMIT_BASE", bad)
        claim_files, changed_files = _both()
        assert "theirs.py" in claim_files and "theirs.py" in changed_files, bad


def test_a_base_that_is_not_an_ancestor_of_head_is_ignored(moved, monkeypatch) -> None:
    repo = Path(claim_gate.ROOT)
    # an empty tree: a commit made from it is nobody's ancestor
    tree = subprocess.run(
        ["git", "mktree"], cwd=repo, input="", capture_output=True, text=True, check=True
    ).stdout.strip()
    stranger = subprocess.run(
        ["git", "-c", "user.name=N", "-c", "user.email=n@example.invalid", "commit-tree", tree, "-m", "stranger"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    monkeypatch.setenv("THOMAS_COMMIT_BASE", stranger)
    claim_files, changed_files = _both()
    assert "theirs.py" in claim_files and "theirs.py" in changed_files


def test_the_commit_tool_hands_gates_the_base_and_never_a_value_it_inherited(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_COMMIT_BASE", "inherited")
    scope = mod.ScopeSelection(scopes=("src",), source=mod.CLAIM_SOURCE)
    index = tmp_path / "index"
    assert "THOMAS_COMMIT_BASE" not in mod._temp_index_env("a", index, scope_selection=scope)
    assert mod._temp_index_env("a", index, scope_selection=scope, base="abc123")["THOMAS_COMMIT_BASE"] == "abc123"
    assert mod._temp_index_env("a", index)["GIT_INDEX_FILE"] == str(index)  # the old call shape still works


def test_the_base_is_ignored_unless_the_index_is_one_the_commit_tool_built(moved, monkeypatch, tmp_path: Path) -> None:
    # Review finding: any ancestor of HEAD was honoured, so a value left in an agent's shell hid a staged revert of a
    # recent change from both gates. The commit tool's index lives in a thomas-agent-commit-* directory; nothing else counts.
    b0, _b1 = moved
    monkeypatch.setenv("THOMAS_COMMIT_BASE", b0)
    assert _both() == (["mine.py"], ["mine.py"])  # the tool's own index: honoured
    ours = Path(os.environ["GIT_INDEX_FILE"])
    elsewhere = tmp_path / "plain-directory"
    elsewhere.mkdir()
    (elsewhere / "index").write_bytes(ours.read_bytes())
    monkeypatch.setenv("GIT_INDEX_FILE", str(elsewhere / "index"))
    claim_files, changed_files = _both()
    assert "theirs.py" in claim_files and "theirs.py" in changed_files  # not the tool's index: the base is ignored
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert _commit_base.args(Path(claim_gate.ROOT)) == []  # the real index (the pre-commit hook path): ignored
    monkeypatch.setenv("GIT_INDEX_FILE", "")
    assert _commit_base.args(Path(claim_gate.ROOT)) == []


def test_a_staged_revert_of_a_recent_change_stays_visible_with_a_stray_base(moved, monkeypatch, tmp_path: Path) -> None:
    """The reviewer's scenario: the neighbour added a file at the tip, the agent stages its removal, a stray base is set."""
    b0, _b1 = moved
    repo = Path(claim_gate.ROOT)
    plain = tmp_path / "plain"
    plain.mkdir()
    env = {**os.environ, "GIT_INDEX_FILE": str(plain / "index")}
    subprocess.run(["git", "read-tree", "HEAD"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "rm", "-q", "--cached", "theirs.py"], cwd=repo, env=env, check=True)
    monkeypatch.setenv("GIT_INDEX_FILE", str(plain / "index"))
    monkeypatch.setenv("THOMAS_COMMIT_BASE", b0)  # against b0 the staged deletion would read as no change at all
    claim_files, changed_files = _both()
    assert claim_files == ["theirs.py"] and changed_files == ["theirs.py"]


def test_the_prefix_the_gates_look_for_is_the_one_the_commit_tool_creates() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "crew" / "brief" / "commit.py").read_text(
        encoding="utf-8"
    )
    assert f'tempfile.TemporaryDirectory(prefix="{_commit_base.INDEX_DIR_PREFIX}")' in source
