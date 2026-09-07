"""Phase 2 batch 2 (batch-2 reviewer lead, informational): `tidy_refs.py`'s
`classify_branches` used to hand bare ref NAMES straight to
`git merge-base --is-ancestor`, the same DWIM class closed for
`claim_evidence.py` by 9ac14311 (show-ref, no fallback disambiguation) and
f7a523f0 (fully-qualified ref paths, sha passed onward -- not the name).

`tidy_refs.py` is a maintenance janitor (not a pre-commit gate; it lives at
scripts/forge/tidy_refs.py, not under scripts/forge/gates/, so it carries no
RED_PATH_CASES / gate_selftest_baseline.json obligation), but its
`reap_branches(..., apply=True)` runs `git branch -d/-D` on whatever
`classify_branches` calls "reapable" -- a wrong ancestry read here is not
cosmetic, it deletes branches.

git's ref disambiguation (gitrevisions(7)) checks refs/tags/<name> BEFORE
refs/heads/<name>, so a bare name handed to `merge-base` can resolve to a
same-named TAG instead of the intended BRANCH -- reachable with nothing more
exotic than `git tag <name>`, which is easy to create by accident (a stray
release-tag naming collision) as well as on purpose. Two call sites were
affected:

  * `base` (the CLI `--base`, default `dev`) -- a stray tag named `dev` can
    stand in for an ABSENT `dev` branch and become the merge target.
  * `name` (each candidate branch, enumerated from `for-each-ref
    refs/heads/`) -- a stray tag sharing a branch's name can stand in for
    that branch's OWN tip when its ancestry is checked.

Either shadow can turn a genuinely unmerged branch into one classified
"merged into dev" and therefore deleted. The fix (mirroring claim_evidence's
landed pattern): `_ref_resolves` resolves a ref via `git show-ref --verify`
on an EXACT, fully-qualified path (no DWIM fallback at all), and the
resolved SHA -- never the ref name -- is what reaches `merge-base`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import scripts.forge.tidy_refs as mod


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit(repo: Path, rel_path: str, content: str, message: str) -> str:
    path = repo / rel_path
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _init_repo(repo: Path, *, branch: str) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", branch)
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    # This machine's global gitconfig sets tag.gpgsign=true, which turns a
    # plain `git tag <name> <sha>` into an implicit annotated+signed tag
    # (requiring a message and a GPG key) -- irrelevant to what these tests
    # check, so it is disabled per-repo.
    _git(repo, "config", "tag.gpgsign", "false")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    _init_repo(root, branch="main")
    monkeypatch.setattr(mod, "ROOT", root)
    return root


def test_a_stray_tag_named_dev_does_not_stand_in_for_an_absent_dev_branch(repo: Path) -> None:
    """No `dev` branch exists at all. A tag literally named `dev` points at
    `topic`'s own WIP tip -- a plausible accidental collision (e.g. an old
    release-tag naming scheme), not just an adversarial one. Before the fix,
    bare `merge-base --is-ancestor topic dev` DWIM-resolved `dev` to the tag
    (tags outrank absent branches), and a commit is trivially an ancestor of
    itself, so `topic` was wrongly classified "merged into dev" -- and
    `reap_branches(apply=True)` would delete it.
    """
    _commit(repo, "a.txt", "a\n", "seed")
    _git(repo, "checkout", "-b", "topic")
    topic_sha = _commit(repo, "b.txt", "b\n", "wip on topic")
    _git(repo, "tag", "dev", topic_sha)
    _git(repo, "checkout", "main")

    buckets = mod.classify_branches("dev")

    reapable_names = {name for name, _ in buckets["reapable"]}
    kept_names = {name for name, _ in buckets["kept"]}
    assert "topic" not in reapable_names, "a stray tag named `dev` must not stand in for the branch"
    assert "topic" in kept_names


def test_the_real_dev_branch_still_correctly_reaps_a_merged_topic(repo: Path) -> None:
    """Sanity check: when a real `dev` branch exists and genuinely contains
    `topic`'s history, the fix must not have broken the intended, honest
    "merged" classification."""
    seed_sha = _commit(repo, "a.txt", "a\n", "seed")
    _git(repo, "branch", "dev", "main")
    _git(repo, "checkout", "-b", "topic")
    assert seed_sha  # topic == dev's tip here, i.e. trivially merged
    _git(repo, "checkout", "main")

    buckets = mod.classify_branches("dev")

    reapable = dict(buckets["reapable"])
    assert "topic" in reapable
    assert reapable["topic"] == "merged into dev"


def test_a_tag_sharing_a_branchs_name_never_makes_that_branch_falsely_merged(repo: Path) -> None:
    """A real `dev` branch exists. `topic` has genuine unmerged work beyond
    `dev`. A tag literally named `topic` points at `dev`'s own tip (a
    plausible naming collision). `git for-each-ref`'s OWN short-name
    disambiguation (core.warnAmbiguousRefs) already lengthens the branch's
    `%(refname:short)` to `heads/topic` whenever a same-named tag exists --
    which happens to save the ORIGINAL bare-name code here too (`heads/topic`
    still resolves unambiguously to `refs/heads/topic` via git's own
    disambiguation rule 2, "try refs/<name>"), so this is a regression/
    correctness check rather than a red-before-this-fix repro: `topic`
    (bucketed under its disambiguated name) must never be reachable through
    `reapable` -- with or without the fix -- and the fix's use of the FULL
    `%(refname)` (not a `refs/heads/<name>` reconstruction of the short
    form) must not change that.
    """
    dev_sha = _commit(repo, "a.txt", "a\n", "seed")
    _git(repo, "branch", "dev", "main")
    _git(repo, "checkout", "-b", "topic")
    _commit(repo, "b.txt", "b\n", "real unmerged work on topic")
    _git(repo, "tag", "topic", dev_sha)
    _git(repo, "checkout", "main")

    buckets = mod.classify_branches("dev")

    reapable_names = {name for name, _ in buckets["reapable"]}
    kept_names = {name for name, _ in buckets["kept"]}
    assert not reapable_names, "the same-named tag must never make `topic` read as merged"
    assert "heads/topic" in kept_names  # git's own disambiguated short name for this collision


def test_ref_resolves_returns_none_for_a_tag_when_asked_for_the_qualified_heads_path(repo: Path) -> None:
    """Direct unit check of the exact-match contract `_ref_resolves` gives
    `classify_branches`: a tag existing at the bare name must not satisfy a
    fully-qualified refs/heads/ lookup for that same name."""
    sha = _commit(repo, "a.txt", "a\n", "seed")
    _git(repo, "tag", "dev", sha)

    assert mod._ref_resolves("refs/heads/dev", mod.ROOT) is None
    assert mod._ref_resolves("refs/tags/dev", mod.ROOT) == sha
