"""The ratchet's backlog: work on refs that is not on dev, found once per commit, in the order it is proven.

Measured 2026-09-24: seven branches pointed at one commit (fcb5f06) and seven
salvage snapshots sat one commit on top of it; the public repository's history
and dependabot's updates sat beside them and must never be proven onto dev.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.ratchet_support import NEW, dev_moves, git, make_repo, on_ref, orphan
from thomas.server.ratchet.candidates import DEPENDABOT_EMAIL, discover, read_census, write_census
from thomas.server.ratchet.gitrepo import Repo


def test_work_not_on_dev_is_found_once_per_commit_smallest_first(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    small = on_ref(repo, "refs/heads/fix/small", base, {"thomas/core/widget.py": "VALUE = 2\n"}, "small")
    git(repo, "update-ref", "refs/heads/praxis/same-commit", small)
    big = on_ref(
        repo,
        "refs/heads/feature/big",
        base,
        {"thomas/core/a.py": "A = 1\n", "thomas/core/b.py": "B = 1\n"},
        "big",
        when="2026-09-03T12:00:00+00:00",
    )
    snap = on_ref(repo, "refs/salvage/run/wt-one", small, {"thomas/core/c.py": "C = 1\n"}, "snapshot")
    on_ref(repo, "refs/archive/stash/old", base, {"thomas/core/z.py": "Z = 1\n"}, "an archived snapshot")
    dev_moves(repo)

    census = discover(Repo(repo))

    assert [c.sha for c in census.candidates] == [small, big, snap]
    first = census.candidates[0]
    assert first.refs == ("refs/heads/fix/small", "refs/heads/praxis/same-commit")
    assert first.files == ("thomas/core/widget.py",)
    assert census.candidates[2].stacked_on == small
    assert census.candidates[2].files == ("thomas/core/c.py", "thomas/core/widget.py")
    assert census.skipped == ()


def test_public_history_dependabot_and_fresh_work_are_reported_not_proven(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    orphan(repo, "refs/remotes/origin/main", {"README.md": "public\n"}, "public line")
    orphan(repo, "refs/heads/public-clean", {"LICENSE": "public\n"}, "another root")
    release = on_ref(repo, "refs/remotes/origin/release/x", base, {"docs/a.md": "a\n"}, "release")
    on_ref(repo, "refs/heads/carries-public", release, {"docs/b.md": "b\n"}, "on top of the release")
    dependabot = "refs/remotes/dev-origin/dependabot/pip/requests"
    on_ref(repo, dependabot, base, {"requirements.txt": "requests==9\n"}, "deps(pip): bump", email=DEPENDABOT_EMAIL)
    on_ref(repo, "refs/heads/wip", base, {"thomas/core/wip.py": "W = 1\n"}, "still going", when=NEW)
    git(repo, "symbolic-ref", "refs/remotes/dev-origin/HEAD", dependabot)
    dev_moves(repo)

    census = discover(Repo(repo))

    assert census.candidates == ()
    reasons = {s.refs[0]: (s.status, s.reason) for s in census.skipped}
    assert reasons["refs/remotes/origin/main"][1].startswith("the public repository's history")
    assert "shares no history with dev" in reasons["refs/heads/public-clean"][1]
    assert reasons["refs/remotes/origin/release/x"][1].startswith("the public repository's history")
    assert "carries 1 commit(s) of the public repository's history" in reasons["refs/heads/carries-public"][1]
    assert "dependabot" in reasons[dependabot][1]
    assert reasons["refs/heads/wip"][0] == "active"
    assert not any(ref.endswith("/HEAD") for s in census.skipped for ref in s.refs)


def test_a_copy_cloned_from_the_work_repository_still_finds_its_backlog(tmp_path: Path) -> None:
    """One remote, named origin, carrying the work: the ref's name is not evidence, its history is.

    Measured in this green on 2026-09-25: every one of the four groups it found sat
    under ``refs/remotes/origin/`` -- including fcb5f06, the commit the plan lands
    first -- and a name-only rule called the whole backlog the public repository's.
    """
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    sanitized = orphan(repo, "refs/remotes/origin/public-clean-signed", {"README.md": "public\n"}, "public line")
    on_ref(repo, "refs/remotes/origin/chore/sanitize", sanitized, {"README.md": "public again\n"}, "on the public line")
    work = on_ref(repo, "refs/remotes/origin/praxis/native", base, {"thomas/core/native.py": "N = 1\n"}, "real work")
    bot = "refs/remotes/origin/dependabot/pip/requests"
    on_ref(repo, bot, base, {"requirements.txt": "requests==9\n"}, "deps(pip): bump", email=DEPENDABOT_EMAIL)
    dev_moves(repo)

    census = discover(Repo(repo))

    assert [c.sha for c in census.candidates] == [work]
    reasons = {s.refs[0]: s.reason for s in census.skipped}
    assert "shares no history with dev" in reasons["refs/remotes/origin/public-clean-signed"]
    assert "shares no history with dev" in reasons["refs/remotes/origin/chore/sanitize"]
    assert "dependabot" in reasons[bot]


def test_the_census_is_written_whole_and_read_back(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    sha = on_ref(repo, "refs/heads/fix/small", base, {"thomas/core/widget.py": "VALUE = 2\n"}, "small")
    dev_moves(repo)

    written = write_census(tmp_path / "ratchet", discover(Repo(repo)))
    data = read_census(tmp_path / "ratchet")

    assert data["candidates"][0]["sha"] == sha
    assert data["candidates"][0]["ref"] == "refs/heads/fix/small"
    assert data["discovered_at"]
    assert json.loads(written.read_text(encoding="utf-8")) == data
    assert read_census(tmp_path / "nowhere") == {}


def test_a_git_stash_snapshot_is_reported_not_proven(tmp_path: Path) -> None:
    """A stash saved as a salvage snapshot is a working-tree save, often a temporary revert, not work meant to land.

    The safety review of 2026-09-28 found the first real run would have started with a two-week-old CHANGELOG stash,
    and that a "temp-verify-preexisting-failure" stash would have asked you to delete 11 files dev still has."""
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    # Dated in their names like the real ones (the custodian reads a salvage snapshot's date there), and old enough
    # that nobody is still on them.
    stash = on_ref(repo, "refs/salvage/stash-2026-09-01/one", base, {"CHANGELOG.md": "stashed\n"}, "On dev: temp")
    kept = on_ref(repo, "refs/salvage/stash-2026-09-01/two", base, {"thomas/core/k.py": "K = 1\n"}, "also a branch")
    git(repo, "update-ref", "refs/heads/keep-me", kept)
    dev_moves(repo)

    census = discover(Repo(repo))

    reasons = {s.sha: s.reason for s in census.skipped}
    assert "stash" in reasons[stash], census.skipped
    assert kept in {c.sha for c in census.candidates}, "work a branch also holds is still the ratchet's"
