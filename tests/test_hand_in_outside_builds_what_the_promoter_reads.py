"""The patch and manifest an outside agent's hand-in carries are what the promoter's reader accepts.

Proves scripts.crew.hand_in_outside_build and scripts.crew.hand_in_outside_checks on a throwaway repo; the real cage
is never touched, every inbox is a folder under tmp_path.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from scripts.cage import self_change_checks as promoter
from scripts.crew import hand_in_outside_build as build
from scripts.crew import hand_in_outside_checks as checks

from tests.hand_in_outside_support import Repos, make_repos


@pytest.fixture
def repos(tmp_path):
    return make_repos(tmp_path)


def _change(repos: Repos, tip: str | None = None) -> build.Change:
    return build.read_change(repos.clone, repos.base, tip or repos.plain)


def test_two_commits_become_one_squashed_patch_with_lf_and_relative_paths(repos):
    change = _change(repos)
    assert [subject for _, subject in change.commits] == ["feat: tool answers", "feat: another module"]
    assert sorted(change.files) == ["pkg/other.py", "pkg/tool.py"]
    assert b"diff --git a/pkg/tool.py b/pkg/tool.py" in change.patch
    assert b"\r\n" not in change.patch
    assert checks.applies_to(repos.checkout, checks.dev_tip(repos.checkout, "dev"), change.patch) == ""


def test_the_manifest_has_every_field_the_promoter_and_the_other_writers_use(repos):
    change = _change(repos)
    dev = checks.dev_tip(repos.checkout, "dev")
    manifest = build.manifest_for(
        change, sid="self-outside-abc-1", dev_tip=dev, checkout=repos.checkout,
        title="feat: tool", agent="codex", checked="n", now=5.0,
    )  # fmt: skip
    assert manifest["kind"] == "self_change" and manifest["base"] == dev and manifest["agent"] == "codex"
    assert manifest["patch_sha256"] == hashlib.sha256(change.patch).hexdigest()
    assert "feat: another module" in str(manifest["summary"]) and "A body line." in str(manifest["summary"])
    for name in ("id", "message", "patch", "execution_id", "checked", "chat", "files", "blue", "submitted_at"):
        assert name in manifest


def test_a_dropped_hand_in_is_complete_and_the_promoters_own_reader_accepts_it(repos, tmp_path):
    change = _change(repos)
    dev = checks.dev_tip(repos.checkout, "dev")
    sid = build.submission_id(change.tip, 7.0)
    manifest = build.manifest_for(
        change, sid=sid, dev_tip=dev, checkout=repos.checkout, title="t", agent="a", checked="n", now=7.0
    )
    inbox = tmp_path / "cage" / "inbox"
    folder = build.drop(inbox, manifest, change.patch)
    meta, patch = promoter.read_submission(folder)
    assert meta["id"] == sid and patch == change.patch
    assert json.loads((folder / "submission.json").read_text(encoding="utf-8"))["files"] == change.files
    assert sorted(p.name for p in inbox.iterdir()) == [sid]  # no staging folder is left behind
    with pytest.raises(build.Refusal, match="already"):
        build.drop(inbox, manifest, change.patch)


def test_a_drop_that_fails_leaves_no_staging_folder(repos, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    monkeypatch.setattr(
        build.Path, "rename", lambda self, target: (_ for _ in ()).throw(OSError("full")), raising=False
    )
    with pytest.raises(OSError, match="full"):
        build.drop(inbox, {"id": "self-outside-x-1"}, b"p")
    assert list(inbox.iterdir()) == []


def test_an_id_the_promoter_would_not_accept_is_refused(tmp_path):
    with pytest.raises(build.Refusal, match="not an id"):
        build.drop(tmp_path / "inbox", {"id": "../escape"}, b"p")
    assert not (tmp_path / "inbox").exists()
