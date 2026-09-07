"""The governor is put through every shape of divergence, one repo per case.

On 2026-09-03 a person consolidated this repository by hand: measured the five
dimensions, tidied, pushed. `thomas consolidate` was green throughout, because
it knew only local branch count. The point of these cases is that the governor
now produces the plan, and that it is right across situations - not just the one
that happened to be in front of it.

Each case builds a repository in a named state and asserts the whole verdict:
which dimension fires, what the next move is, and WHO may make it. The last is
the one that matters most. A governor that would publish to a public repository,
or commit another agent's work, is more dangerous than one that does nothing.

The case that earns its keep is the clean-but-deleting branch: three real
branches merged into `dev` with zero conflicts while carrying a squash that
removes 255 live files. Clean is not safe, and only counting the deletions tells
them apart.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "forge"))
import trunk_divergence as td  # noqa: E402

from thomas.forge import consolidation_plan as cp  # noqa: E402

LONG_AGO = "2020-01-01T00:00:00Z"


def _git(repo: Path, *args: str, when: str | None = None) -> str:
    env = dict(os.environ)
    if when:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = when
    return subprocess.run(
        ("git", *args),
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout


def _commit(repo: Path, name: str, body: str = "x", when: str | None = None) -> None:
    (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}", when=when)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A trunk on `dev`, fully pushed, public branch level, clean tree."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "Test")
    _git(work, "checkout", "-q", "-b", "dev")
    # Distinct bodies on purpose: identical content makes git call a delete-plus-add
    # a RENAME, which hid one of the two deletions the first time this was written.
    for name in ("seed.txt", "keep-a.txt", "keep-b.txt"):
        _commit(work, name, body=f"contents of {name}", when=LONG_AGO)
    _git(work, "push", "-q", "-u", "origin", "dev")
    _git(work, "push", "-q", "origin", "dev:main")
    _git(work, "fetch", "-q", "origin")
    return work


def _findings(repo: Path) -> list[str]:
    report = td.build_report(repo=repo, trunk="dev", remote="origin", public="origin/main", scan_clones=False)
    return report.findings


def _plan(repo: Path, **kw) -> list[cp.Action]:
    return cp.advise(_findings(repo), git=cp.subprocess_git_runner(repo), trunk="dev", **kw)


def _by_dimension(actions, dimension: str) -> cp.Action | None:
    return next((a for a in actions if a.dimension == dimension), None)


# -- case 1: nothing wrong --------------------------------------------------
def test_a_level_repo_gets_an_empty_plan(repo: Path) -> None:
    actions = _plan(repo)
    assert actions == []
    assert cp.render_plan(actions).startswith("CONSOLIDATION: nothing to do")


# -- case 2: work only on this machine --------------------------------------
def test_an_unpushed_trunk_is_thomas_own_job(repo: Path) -> None:
    _commit(repo, "new-work.txt")
    action = _by_dimension(_plan(repo), "unpushed")
    assert action is not None
    assert "push" in action.do
    assert action.actor == cp.THOMAS, "pushing a green trunk is safe to automate"


# -- case 3: the public repository is behind --------------------------------
def test_public_lag_is_never_thomas_to_publish(repo: Path) -> None:
    _commit(repo, "after-release.txt")
    _git(repo, "push", "-q", "origin", "dev")
    action = _by_dimension(_plan(repo), "public")
    assert action is not None
    assert action.actor == cp.OWNER, "publishing is irreversible and is the owner's call"
    assert "cut a release" in action.do and "cannot be taken back" in action.why


# -- case 4: THE case - clean merge that quietly deletes --------------------
def test_a_branch_that_merges_clean_but_deletes_is_advised_as_a_cherry_pick(repo: Path) -> None:
    """Zero conflicts, and it would remove files the trunk still has."""
    _git(repo, "checkout", "-q", "-b", "feature/on-a-squash")
    (repo / "keep-a.txt").unlink()
    (repo / "keep-b.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "squash: land months of work")
    _commit(repo, "the-actual-feature.txt", body="a genuinely new file")
    _git(repo, "push", "-q", "origin", "feature/on-a-squash")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "fetch", "-q", "origin")

    git = cp.subprocess_git_runner(repo)
    deletions, conflicts = cp.merge_deletions(git, "dev", "origin/feature/on-a-squash")
    assert conflicts == 0, "the trap is that it looks clean"
    assert deletions == 2, "and it would delete two live files"

    action = cp.advise_branch(git, "dev", "origin/feature/on-a-squash")
    assert "cherry-pick" in action.do and "do NOT merge" in action.do
    assert action.actor == cp.OWNER
    assert "delete 2 file(s)" in action.why


# -- case 5: an ordinary branch that is genuinely safe ----------------------
def test_a_branch_that_adds_only_is_thomas_to_merge(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/additive")
    _commit(repo, "added.txt")
    _git(repo, "push", "-q", "origin", "feature/additive")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "fetch", "-q", "origin")

    action = cp.advise_branch(cp.subprocess_git_runner(repo), "dev", "origin/feature/additive")
    assert action.do.startswith("merge")
    assert action.actor == cp.THOMAS
    assert "deletes nothing" in action.why


# -- case 6: a branch that genuinely conflicts ------------------------------
def test_a_conflicting_branch_goes_to_a_person(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/conflicting")
    _commit(repo, "seed.txt", body="their side")
    _git(repo, "push", "-q", "origin", "feature/conflicting")
    _git(repo, "checkout", "-q", "dev")
    _commit(repo, "seed.txt", body="our side")
    _git(repo, "fetch", "-q", "origin")

    action = cp.advise_branch(cp.subprocess_git_runner(repo), "dev", "origin/feature/conflicting")
    assert action.actor == cp.OWNER
    assert "resolve" in action.do


# -- case 7: the mess belongs to somebody else ------------------------------
def test_another_agents_uncommitted_work_is_never_thomas_to_commit(repo: Path) -> None:
    (repo / "seed.txt").write_text("someone else is mid-edit", encoding="utf-8")
    theirs = _by_dimension(_plan(repo, uncommitted_is_mine=False), "uncommitted")
    assert theirs is not None
    assert theirs.actor == cp.OTHER_AGENT
    assert "ask the agent who owns it" in theirs.do

    mine = _by_dimension(_plan(repo, uncommitted_is_mine=True), "uncommitted")
    assert mine is not None and mine.actor == cp.THOMAS and "commit or park" in mine.do


# -- case 8: order is the order the repository forces -----------------------
def test_the_plan_is_ordered_the_way_the_repository_forces(repo: Path) -> None:
    """An untidy tree blocks the push; an unpushed trunk cannot be published."""
    _commit(repo, "landed.txt")
    (repo / "seed.txt").write_text("dirty", encoding="utf-8")
    dimensions = [a.dimension for a in _plan(repo)]
    assert dimensions.index("uncommitted") < dimensions.index("unpushed")
    assert dimensions.index("unpushed") < dimensions.index("public")


# -- case 9: the plan says how much of itself Thomas may do -----------------
def test_the_plan_states_how_many_steps_thomas_may_take_itself(repo: Path) -> None:
    _commit(repo, "work.txt")
    rendered = cp.render_plan(_plan(repo))
    assert "step(s)," in rendered and "Thomas may take itself" in rendered
    assert "[owner]" in rendered, "an owner-only step is marked as one"


# -- case 10: a stale fork is retirable, and says on whose authority --------
def test_stale_forks_are_retirable_by_thomas(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/ancient")
    _commit(repo, "old.txt", when=LONG_AGO)
    _git(repo, "push", "-q", "origin", "feature/ancient")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "fetch", "-q", "origin")

    findings, _ = td.find_stranded_branches("dev", repo=repo, now=time.time() + 60 * 86400)
    action = _by_dimension(cp.advise(findings, trunk="dev"), "stranded")
    assert action is not None and action.actor == cp.THOMAS
    assert "archive and retire" in action.do
    assert "already has may be retired automatically" in action.why
