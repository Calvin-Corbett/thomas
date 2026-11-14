"""A sign-in covers where a release goes, as well as what goes: the repository's address and the branch name.

Proves scripts.forge.publish.public_release_publish and scripts.forge.publish.public_release_preview. The address a
remote name stands for, and the branch that would be written, are part of the preview and so of the hash a sign-in
confirms. ``publish`` takes no remote or branch of its own, and refuses when the remote now points somewhere else.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from scripts.forge.publish import public_release as pr
from scripts.forge.publish import public_release_preview as prev

from tests.public_release_support import (  # noqa: F401
    clean_git_settings,
    make_dev,
    make_public,
    ok_preflight,
    refs,
    sh,
)

TODAY = "2026-11-03"


def _yes(_action: str, _reason: str) -> bool:
    return True


def _named(tmp_path: Path, name: str = "public") -> tuple[Path, Path, prev.Preview]:
    dev = make_dev(tmp_path)
    bare, _old = make_public(tmp_path)
    sh(dev, "remote", "add", name, str(bare))
    return dev, bare, prev.build(dev, remote=name, preflight=ok_preflight, scratch_parent=tmp_path, today=TODAY)


def test_publish_takes_no_remote_or_branch_of_its_own() -> None:
    names = set(inspect.signature(pr.publish).parameters)

    assert not names & {"remote", "branch", "today", "url"}


def test_the_preview_holds_the_address_and_the_branch_and_the_hash_follows_them(tmp_path: Path) -> None:
    _dev, bare, preview = _named(tmp_path)
    facts = preview.facts()
    same = preview.digest()

    assert facts["remote"] == "public" and facts["remote_url"] == str(bare)
    assert facts["branch"] == "release/1.2.3-2026-11-03"
    preview.branch = "release/elsewhere"
    assert preview.digest() != same
    preview.branch = "release/1.2.3-2026-11-03"
    preview.remote_url = "https://example.invalid/other.git"
    assert preview.digest() != same


def test_a_sign_in_for_one_destination_cannot_publish_to_another(tmp_path: Path) -> None:
    dev, bare_a, preview_a = _named(tmp_path)
    bare_b = tmp_path / "other.git"
    sh(tmp_path, "init", "-q", "--bare", str(bare_b))
    preview_b = prev.build(dev, remote=str(bare_b), preflight=ok_preflight, scratch_parent=tmp_path, today=TODAY)
    record_a = pr.confirm(preview_a, _yes)
    before = refs(bare_a), refs(bare_b)

    result = pr.publish(preview_b, record_a)

    assert not result.ok and "different preview" in result.refused
    assert (refs(bare_a), refs(bare_b)) == before


def test_a_sign_in_for_one_branch_name_cannot_publish_under_another(tmp_path: Path) -> None:
    dev, bare, preview = _named(tmp_path)
    other = prev.build(dev, remote="public", preflight=ok_preflight, scratch_parent=tmp_path, branch="release/else")
    before = refs(bare)

    result = pr.publish(other, pr.confirm(preview, _yes))

    assert not result.ok and "different preview" in result.refused
    assert refs(bare) == before


def test_a_remote_pointed_somewhere_else_after_the_preview_is_refused(tmp_path: Path) -> None:
    dev, bare, preview = _named(tmp_path)
    elsewhere = tmp_path / "elsewhere.git"
    sh(tmp_path, "init", "-q", "--bare", str(elsewhere))
    record = pr.confirm(preview, _yes)
    sh(dev, "remote", "set-url", "public", str(elsewhere))
    before = refs(bare), refs(elsewhere)

    result = pr.publish(preview, record)

    assert not result.ok and "no longer points at" in result.refused
    assert (refs(bare), refs(elsewhere)) == before


def test_a_remote_renamed_after_the_preview_is_refused(tmp_path: Path) -> None:
    dev, bare, preview = _named(tmp_path)
    record = pr.confirm(preview, _yes)
    sh(dev, "remote", "rename", "public", "renamed")
    before = refs(bare)

    result = pr.publish(preview, record)

    assert not result.ok and "no longer points at" in result.refused
    assert refs(bare) == before


def test_the_prompt_names_the_destination_in_plain_words(tmp_path: Path) -> None:
    _dev, bare, preview = _named(tmp_path)
    seen: list[str] = []

    pr.confirm(preview, lambda action, reason: seen.append(action) or False)

    assert seen[0].startswith(f"Publish a review copy to {bare} as branch release/1.2.3-2026-11-03")
    assert "main branch is not changed" in seen[0]


def test_an_address_with_a_password_in_it_is_shown_without_one(tmp_path: Path) -> None:
    dev = make_dev(tmp_path)
    sh(dev, "remote", "add", "public", "https://someone:secret-token@example.invalid/org/thomas.git")

    url = prev.resolve_remote(dev, "public")

    assert prev.display_remote(url) == "https://example.invalid/org/thomas.git"
    assert "secret-token" not in prev.display_remote(url)
