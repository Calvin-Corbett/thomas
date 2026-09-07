"""Phase 2 batch 2 (batch-2 reviewer lead, informational): `release_sync_gate.py`'s
`_check_tag` used to establish tag existence with `git rev-parse -q --verify
refs/tags/v{version}`, then hand the BARE name `v{version}^{{commit}}` to
`git merge-base --is-ancestor` -- the same DWIM class closed for
`claim_evidence.py` by 9ac14311 (show-ref, no fallback disambiguation) and
f7a523f0 (fully-qualified ref paths, sha passed onward -- not the name).

THE LAST REF TRICK (mirrors claim_evidence.py's `_ref_resolves` docstring,
"fix round 6, T3 review"): `rev-parse --verify <ref>` disambiguates a ref
that fails its own exact lookup by retrying it under `refs/`, `refs/tags/`,
`refs/heads/`, `refs/remotes/` in turn (gitrevisions(7)). Asking it to
resolve the already-qualified `refs/tags/v1.2.3` when the REAL tag is ABSENT
still finds a match if a branch is created literally NAMED
`refs/tags/v1.2.3` (`git branch refs/tags/v1.2.3 <start>` is legal --
slashes are allowed in branch names), because git stores that branch at
`refs/heads/refs/tags/v1.2.3`, and that IS what `refs/heads/<x>` prefixing
finds. Reproduced directly below: this gate would report `tag_exists: PASS`
and (if the branch also happens to be an ancestor of HEAD, as any ordinary
branch off the current history is) `tag_points_at_shipped_code: PASS` for a
tag that was never actually created -- exactly the false assurance this
gate exists to prevent (see its module docstring: "A gate that reports a
record it did not read is worse than no gate").

`release_sync_gate.py` is not wired into `.pre-commit-config.yaml`,
`commit.py`, or any of the other sources `tests/test_no_gate_enforces_unwatched.py`
scans -- it is a manually-run reporting tool ("This gate REPORTS; it never
edits. Run it before claiming a push is done."), so it carries no
RED_PATH_CASES / gate_selftest_baseline.json obligation either.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import scripts.forge.gates.release_sync_gate as mod


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
    monkeypatch.setattr(mod, "REPO_ROOT", root)
    return root


def test_a_branch_literally_named_refs_tags_vX_never_stands_in_for_an_absent_real_tag(repo: Path) -> None:
    """The real tag `v1.2.3` is absent. Only a local branch literally NAMED
    `refs/tags/v1.2.3` exists (stored by git at
    `refs/heads/refs/tags/v1.2.3`), pointing at ordinary shipped history.
    `_tag_sha` (and therefore `_check_tag`) must report the tag as genuinely
    missing -- never resolve the nested branch as if it were the tag.
    """
    _commit(repo, "a.txt", "a\n", "seed")
    _git(repo, "branch", "refs/tags/v1.2.3", "main")

    assert mod._tag_sha("1.2.3") is None

    report = mod._Report()
    mod._check_tag(report, "1.2.3", "origin", remote_calls=False)

    checks = {f["check"]: f["detail"] for f in report.findings}
    assert "tag_exists" in checks, "must be a real, reported failure -- not a silent pass"
    assert "tag_points_at_shipped_code" not in report.checked, (
        "must never even reach the ancestry check -- let alone a false PASS -- for a tag that does not exist"
    )


def test_a_real_tag_still_correctly_verifies_as_shipped(repo: Path) -> None:
    """Sanity check: when the real tag genuinely exists and points at shipped
    history, the fix must not have broken the honest, intended PASS."""
    sha = _commit(repo, "a.txt", "a\n", "seed")
    _git(repo, "tag", "v1.2.3", sha)

    assert mod._tag_sha("1.2.3") == sha

    report = mod._Report()
    mod._check_tag(report, "1.2.3", "origin", remote_calls=False)

    assert "tag_exists" in report.checked
    assert not any(f["check"] in ("tag_exists", "tag_points_at_shipped_code") for f in report.findings)


def test_a_tag_pointing_outside_shipped_history_still_correctly_fails(repo: Path) -> None:
    """Sanity check: a real tag on an orphan/unrelated commit must still
    fail `tag_points_at_shipped_code` -- the fix must not have loosened the
    genuine negative case."""
    _commit(repo, "a.txt", "a\n", "seed")
    _git(repo, "checkout", "--orphan", "unrelated")
    tag_sha = _commit(repo, "z.txt", "z\n", "unrelated history")
    _git(repo, "tag", "v1.2.3", tag_sha)
    _git(repo, "checkout", "main")

    assert mod._tag_sha("1.2.3") == tag_sha

    report = mod._Report()
    mod._check_tag(report, "1.2.3", "origin", remote_calls=False)

    assert any(f["check"] == "tag_points_at_shipped_code" for f in report.findings)
