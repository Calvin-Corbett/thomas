"""The release gate asks "is a release pending?", not "was this pushed?".

Proves scripts.forge.gates.release_update_gate: a product change passes with only a changelog
entry when the project version is ahead of the last release, on the canonical branch itself,
and is refused (with today's message) when the version is not ahead, malformed, in
disagreement, or when no release can be found. Each test builds a throwaway git repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import scripts.forge.gates.release_update_gate as mod

REFUSED = "product-surface changes require release updates; missing changed files: CHANGELOG.md, pyproject.toml, thomas/__init__.py"
FRAGMENT = "changelog.d/claude-fix.md"
PRODUCT = "thomas/server/app.py"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _write_versions(repo: Path, py: str, init: str) -> None:
    (repo / "thomas").mkdir(exist_ok=True)
    (repo / "pyproject.toml").write_text(f'[project]\nname = "thomas"\nversion = "{py}"\n', encoding="utf-8")
    (repo / "thomas" / "__init__.py").write_text(f'__version__ = "{init}"\n', encoding="utf-8")


def _repo(tmp_path: Path, *, py: str, init: str | None = None, tags: tuple[str, ...] = ()) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    _write_versions(repo, py, init or py)
    (repo / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    for tag in tags:
        _git(repo, "tag", tag)
    return repo


def _gate(monkeypatch, repo: Path, capsys, changed: tuple[str, ...]) -> tuple[int, str]:
    monkeypatch.setattr(mod, "ROOT", repo)
    argv = [arg for path in changed for arg in ("--changed-file", path)]
    rc = mod.run(argv)
    return rc, capsys.readouterr().out


def test_a_version_ahead_of_the_last_release_passes_with_only_a_changelog_fragment(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.5", tags=("v0.1.0", "v0.2.4"))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 0, out
    assert "release pending (0.2.5 is ahead of the last release 0.2.4)" in out


def test_the_highest_tag_wins_even_when_it_sorts_lower_as_text(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.10.1", tags=("v0.9.9", "v0.10.0"))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, "CHANGELOG.md"))
    assert rc == 0, out
    assert "ahead of the last release 0.10.0" in out


def test_a_version_equal_to_the_last_release_is_still_refused(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.4", tags=("v0.2.4",))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 1
    assert "missing changed files: pyproject.toml, thomas/__init__.py" in out  # the fragment stands in for CHANGELOG.md


def test_a_version_equal_to_the_last_release_without_any_changelog_gives_todays_message(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.4", tags=("v0.2.4",))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT,))
    assert rc == 1
    assert REFUSED in out


def test_a_version_behind_the_last_release_is_refused(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.3", tags=("v0.2.4",))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 1
    assert "missing changed files" in out


def test_a_version_ahead_without_a_changelog_entry_in_the_change_is_refused(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.5", tags=("v0.2.4",))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT,))
    assert rc == 1
    assert REFUSED in out


def test_the_changelog_readme_is_not_a_changelog_entry(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.5", tags=("v0.2.4",))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, "changelog.d/README.md"))
    assert rc == 1
    assert "missing changed files" in out


@pytest.mark.parametrize("version", ["0.2", "0.2.5.1", "0.2.5rc1", "v0.2.5", "", "0.2.x"])
def test_a_malformed_version_never_passes(monkeypatch, capsys, tmp_path, version):
    repo = _repo(tmp_path, py=version, tags=("v0.1.0",))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 1
    assert "missing changed files" in out


def test_pyproject_and_init_disagreeing_never_passes(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.6", init="0.2.5", tags=("v0.2.4",))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 1
    assert "missing changed files" in out


def test_a_malformed_tag_is_not_a_release(monkeypatch, capsys, tmp_path):
    # Only well-formed v<major>.<minor>.<patch> tags count; a lookalike cannot raise the bar or lower it.
    repo = _repo(tmp_path, py="0.2.5", tags=("v0.2.4", "v9.9", "v1.0.0-rc1", "release-9.9.9"))
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 0, out
    assert "last release 0.2.4" in out


def test_with_no_tags_and_no_public_ref_today_s_behaviour_holds(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.5")
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 1
    assert "missing changed files" in out
    assert mod._last_released_version() is None


def test_the_public_main_version_stands_in_when_there_are_no_tags(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.4")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _write_versions(repo, "0.2.5", "0.2.5")
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 0, out
    assert "last release 0.2.4" in out
    assert mod._last_released_version() == (0, 2, 4)


def test_a_feature_branch_ahead_of_canonical_still_passes_through_the_branch_proof(monkeypatch, capsys, tmp_path):
    # The last release equals the current version, so only the old branch-wide proof can pass this.
    repo = _repo(tmp_path, py="0.2.4", tags=("v0.2.5",))
    _git(repo, "update-ref", "refs/remotes/dev-origin/dev", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    _write_versions(repo, "0.2.5", "0.2.5")
    (repo / "CHANGELOG.md").write_text("# Changelog\n- a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bump")
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT,))
    assert rc == 0, out
    assert "release metadata already updated branch-wide" in out
    assert "release pending" not in out


def test_dev_equal_to_dev_origin_with_a_pending_release_passes(monkeypatch, capsys, tmp_path):
    # The real situation: dev is pushed, so the branch proof cannot engage; the pending release carries it.
    repo = _repo(tmp_path, py="0.2.5", tags=("v0.2.4",))
    _git(repo, "update-ref", "refs/remotes/dev-origin/dev", "HEAD")
    monkeypatch.setattr(mod, "ROOT", repo)
    assert mod._merge_base_with_canonical() is None
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 0, out
    assert "release pending" in out


def test_dev_equal_to_dev_origin_with_the_release_cut_and_no_bump_is_refused(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.5", tags=("v0.2.5",))
    _git(repo, "update-ref", "refs/remotes/dev-origin/dev", "HEAD")
    rc, out = _gate(monkeypatch, repo, capsys, (PRODUCT, FRAGMENT))
    assert rc == 1
    assert "missing changed files" in out


def test_the_unchanged_since_base_check_does_not_reblock_a_pending_release(monkeypatch, capsys, tmp_path):
    # Range mode: the commit changes product code and a fragment, not the version.
    repo = _repo(tmp_path, py="0.2.5", tags=("v0.2.4",))
    (repo / "thomas" / "server").mkdir()
    (repo / PRODUCT).write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir()
    (repo / FRAGMENT).write_text("### Changed\n- a fix\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix")
    monkeypatch.setattr(mod, "ROOT", repo)
    rc = mod.run(["--base", "HEAD~1", "--head", "HEAD", "--no-include-untracked"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "release pending" in out
    assert "did not change relative to base" not in out


def test_the_unchanged_since_base_check_still_blocks_when_no_release_is_pending(monkeypatch, capsys, tmp_path):
    repo = _repo(tmp_path, py="0.2.5", tags=("v0.2.5",))
    (repo / "thomas" / "server").mkdir()
    (repo / PRODUCT).write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir()
    (repo / FRAGMENT).write_text("### Changed\n- a fix\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix")
    monkeypatch.setattr(mod, "ROOT", repo)
    rc = mod.run(["--base", "HEAD~1", "--head", "HEAD", "--no-include-untracked"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "project version did not change relative to base" in out
