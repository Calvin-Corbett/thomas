"""Concurrent workers must not lose each other's work.

Measured on 2026-09-09 with scripted workers -- no model calls, so this tests the
coordination layer rather than the agents. Every worker edits a path no other
worker touches, so a missing file is the substrate losing work, never two workers
disagreeing.

    isolation   workers  intended  in tree  LOST  commits/s
    shared      2        6         6        0     3.49
    shared      5        15        15       0     3.13
    shared      20       60        58       2     3.25
    worktree    2        6         6        0     5.33
    worktree    5        15        15       0     6.56
    worktree    20       60        60       0     6.65      (5/5 runs clean)

Two things in that table matter more than the pass.

Shared throughput is FLAT: 3.2 commits/sec whether two workers run or twenty.
Twenty agents on one checkout do the work of two and then lose a file. The failures
name the mechanism, and it is not the lock everyone assumes -- `lock_waits` was
zero across every run. It is that `git commit` rewrites the whole index, so one
worker's commit discards another's completed `git add`, and the victim then fails
with `pathspec ... did not match any file(s) known to git` after adding it
successfully. The second failure is `cannot lock ref HEAD: is at X but expected Y`
-- ref updates are compare-and-swap, so concurrent commits to one branch make
losers. Private worktrees fix the first; private branches fix the second.

Isolated throughput rises but is already flattening by 20 (6.56 -> 6.65), because
integration is serial. That is the next ceiling, and it is where batching belongs.
"""

from __future__ import annotations

from pathlib import Path

from scripts.forge.swarm import harness


def test_isolated_workers_lose_nothing(tmp_path: Path):
    """The load-bearing case, scaled down so it can run in a suite."""
    repo = harness.make_repo(tmp_path / "repo")
    report = harness.run_swarm(repo, workers=3, edits=2, out_dir=tmp_path / "results", isolation="worktree")
    assert report["setup_failed"] is False
    assert report["lost"] == [], f"work went missing: {report['lost']}"
    assert report["actually_in_tree"] == report["intended"] == 6


def test_the_verdict_is_the_tree_not_the_exit_code(tmp_path: Path):
    """`committed` counts commands that returned 0. Only the tree is evidence.

    Kept separate because the whole point of the harness is that a worker can
    report success for work that is not there -- which is exactly what shared mode
    does when another commit rewrites the index underneath it.
    """
    repo = harness.make_repo(tmp_path / "repo")
    report = harness.run_swarm(repo, workers=2, edits=1, out_dir=tmp_path / "results", isolation="worktree")
    tracked = set(harness._run(["git", "ls-files"], cwd=repo).stdout.split())
    assert {"work/w000/file_0.txt", "work/w001/file_0.txt"} <= tracked


def test_a_broken_setup_refuses_instead_of_measuring_something_else(tmp_path: Path):
    """A harness that misreports its own configuration is worse than none.

    The first version swallowed `git worktree add` failures and printed
    `isolation: worktree` over a shared-index run. Numbers from that are not weak
    evidence, they are wrong evidence, and they looked identical to real ones.
    """
    repo = harness.make_repo(tmp_path / "repo")
    # No `main` to branch from: worktree creation cannot succeed.
    harness._run(["git", "branch", "-m", "main", "trunk"], cwd=repo)
    report = harness.run_swarm(repo, workers=2, edits=1, out_dir=tmp_path / "results", isolation="worktree")
    assert report["setup_failed"] is True
    assert report["failures"], "a refused run must say why"
    assert report["actually_in_tree"] == 0


def test_throughput_is_reported_apart_from_worker_count(tmp_path: Path):
    """Twenty launched workers is not twenty workers' worth of work."""
    repo = harness.make_repo(tmp_path / "repo")
    report = harness.run_swarm(repo, workers=2, edits=1, out_dir=tmp_path / "results", isolation="worktree")
    assert "commits_per_second" in report and "workers" in report
    assert report["os_processes"] == report["workers"]
