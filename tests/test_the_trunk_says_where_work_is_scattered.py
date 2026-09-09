"""Every way work can sit outside the trunk has a number, and it can go red.

`thomas consolidate` reported "2 branches (ceiling 10); 1 carry unique work" -
green - on 2026-09-03, while the trunk was 73 commits unpushed, the public repo
889 behind, 9 remote branches carried live unlanded work, another clone sat on
the disk, and 27 files were uncommitted. One dimension of five, and the one it
measured was the one already fine.

So each detector here gets a pair: a repo built to make it fire, and the same
repo made healthy so it goes quiet. A gauge that only ever prints zero cannot
be told apart from a gauge that is broken.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "forge"))
import trunk_divergence as td  # noqa: E402

LONG_AGO = "2020-01-01T00:00:00Z"


def _git(repo: Path, *args: str, when: str | None = None) -> str:
    env = dict(os.environ)
    if when:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = when
    return subprocess.run(
        ("git", *args), cwd=str(repo), capture_output=True, text=True, check=True, env=env,
    ).stdout


def _commit(repo: Path, name: str, when: str | None = None) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}", when=when)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clone of a bare 'remote', on `dev`, fully pushed and clean."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "Test")
    _git(work, "checkout", "-q", "-b", "dev")
    _commit(work, "seed.txt", when=LONG_AGO)
    _git(work, "push", "-q", "-u", "origin", "dev")
    # A public branch level with the trunk, so "fully consolidated" is a state
    # this fixture can actually reach rather than an unmeasured dimension.
    _git(work, "push", "-q", "origin", "dev:main")
    _git(work, "fetch", "-q", "origin")
    return work


def _report(repo: Path, **kw):
    return td.build_report(repo=repo, trunk="dev", remote="origin", public="origin/main", **kw)


def test_a_fully_consolidated_repo_reports_none(repo: Path) -> None:
    report = _report(repo, scan_clones=False)
    assert report.findings == [], f"a clean repo must be quiet, got {report.findings}"
    assert td.render(report) == "DIVERGENCE: none"


def test_unpushed_trunk_commits_are_counted(repo: Path) -> None:
    assert td.find_unpushed("dev", "origin", repo=repo) == ([], []), "nothing unpushed yet"
    _commit(repo, "later.txt")
    findings, unknown = td.find_unpushed("dev", "origin", repo=repo)
    assert unknown == []
    assert len(findings) == 1 and "1 commit(s)" in findings[0]

    _git(repo, "push", "-q", "origin", "dev")
    assert td.find_unpushed("dev", "origin", repo=repo) == ([], []), "pushing clears it"


def test_a_public_branch_left_behind_is_counted_with_the_date_it_forked(repo: Path) -> None:
    assert td.find_public_lag("dev", "origin/main", repo=repo) == ([], []), "public is level"

    _commit(repo, "after-release.txt")
    findings, _ = td.find_public_lag("dev", "origin/main", repo=repo)
    assert len(findings) == 1
    assert "1 commit(s) behind" in findings[0]
    assert "last shared commit 2020-01-01" in findings[0], "it must say since when"


def test_a_missing_public_ref_is_unmeasured_not_clean(repo: Path) -> None:
    """The honesty contract: an instrument that read nothing must not say fine."""
    findings, unknown = td.find_public_lag("dev", "origin/nope", repo=repo)
    assert findings == [] and len(unknown) == 1 and "cannot be counted" in unknown[0]
    report = td.build_report(repo=repo, trunk="dev", remote="origin", public="origin/nope", scan_clones=False)
    assert report.consolidated is False, "an unmeasured dimension is not consolidation"


def test_stranded_branches_are_split_into_live_work_and_stale_forks(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/live")
    _commit(repo, "live.txt")
    _git(repo, "push", "-q", "origin", "feature/live")
    _git(repo, "checkout", "-q", "-b", "feature/ancient", "dev")
    _commit(repo, "ancient.txt", when=LONG_AGO)
    _git(repo, "push", "-q", "origin", "feature/ancient")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "fetch", "-q", "origin")

    findings, unknown = td.find_stranded_branches("dev", repo=repo)
    assert unknown == []
    assert len(findings) == 1
    assert "1 with a tip inside 14d" in findings[0], "recent work is named, not buried in a count"
    assert "feature/live" in findings[0]
    assert "1 stale fork(s)" in findings[0], "an old fork is counted, not listed"
    assert "feature/ancient" not in findings[0]


def test_a_branch_already_merged_into_the_trunk_is_not_stranded(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/landed")
    _commit(repo, "landed.txt")
    _git(repo, "push", "-q", "origin", "feature/landed")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "-m", "land it", "feature/landed")
    _git(repo, "fetch", "-q", "origin")
    assert td.find_stranded_branches("dev", repo=repo) == ([], []), "landed work is not scattered"


def test_uncommitted_work_is_counted(repo: Path) -> None:
    assert td.find_uncommitted(repo=repo) == ([], []), "a clean tree is quiet"
    (repo / "seed.txt").write_text("edited", encoding="utf-8")
    (repo / "brand-new.txt").write_text("new", encoding="utf-8")
    findings, _ = td.find_uncommitted(repo=repo)
    assert len(findings) == 1
    assert "1 tracked file(s) modified" in findings[0] and "1 untracked" in findings[0]


def test_only_clones_of_this_repository_are_counted(repo: Path, tmp_path: Path) -> None:
    """The first version reported 53 - every git repo in the home directory.

    Noise is how a gauge gets ignored, so a candidate must prove it is this
    repository: same root commit, or a shared remote URL.
    """
    scan = tmp_path / "scan"
    scan.mkdir()
    _git(tmp_path, "clone", "-q", str(repo), str(scan / "a-real-clone"))
    stranger = scan / "unrelated-project"
    stranger.mkdir()
    _git(stranger, "init", "-q")
    _git(stranger, "config", "user.email", "t@example.invalid")
    _git(stranger, "config", "user.name", "Test")
    _commit(stranger, "theirs.txt", when=LONG_AGO)

    findings, _ = td.find_clones(repo_root=repo, roots=[scan])
    assert len(findings) == 1
    assert "1 other working cop" in findings[0]
    assert "a-real-clone" in findings[0]
    assert "unrelated-project" not in findings[0], "an unrelated repo is not a clone of this one"


def test_the_gauge_never_refuses_a_caller(repo: Path) -> None:
    """It reports. A gauge that can block a commit becomes what it measures."""
    proc = subprocess.run(
        (sys.executable, str(Path(td.__file__)), "--json", "--no-clones"),
        cwd=str(repo), capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    assert '"consolidated"' in proc.stdout


def test_a_live_branch_becomes_stale_purely_by_getting_older(repo: Path) -> None:
    """The live/stale split is a date, so the same repo must flip on time alone."""
    _git(repo, "checkout", "-q", "-b", "feature/x")
    _commit(repo, "x.txt")
    _git(repo, "push", "-q", "origin", "feature/x")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "fetch", "-q", "origin")

    fresh, _ = td.find_stranded_branches("dev", repo=repo)
    assert "1 with a tip inside 14d" in fresh[0]

    later, _ = td.find_stranded_branches("dev", repo=repo, now=time.time() + 30 * 86400)
    assert "stale fork(s)" in later[0] and "inside 14d" not in later[0]
