"""The public release preview: what would go public, every check against it, and whether it is safe to publish.

Proves scripts.forge.publish.public_release_preview and scripts.forge.publish.public_release (build, describe). Uses a
fixture development repo and a local bare repo as the "public" one, with the preflight stood in by a fast function where
a test is about something else. Nothing reaches GitHub.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.forge.publish import preflight
from scripts.forge.publish import public_release as pr
from scripts.forge.publish import public_release_preview as prev

from tests.public_release_support import (  # noqa: F401
    CHANGELOG,
    clean_git_settings,
    make_dev,
    make_public,
    ok_preflight,
    sh,
)


def _build(tmp_path: Path, extra: dict[str, str] | None = None, **kwargs: object) -> prev.Preview:
    dev = make_dev(tmp_path, extra)
    bare, _old = make_public(tmp_path)
    kwargs.setdefault("preflight", ok_preflight)
    return prev.build(dev, remote=str(bare), scratch_parent=tmp_path, **kwargs)  # type: ignore[arg-type]


def test_a_clean_release_is_safe_and_the_preview_counts_what_goes(tmp_path: Path) -> None:
    dev = make_dev(tmp_path)
    bare, old = make_public(tmp_path)
    before = sh(dev, "rev-parse", "HEAD"), sh(dev, "status", "--porcelain")

    preview = prev.build(dev, remote=str(bare), preflight=ok_preflight, scratch_parent=tmp_path)

    assert preview.safe_to_publish, [c for c in preview.checks if not c.ok]
    assert preview.version == "1.2.3"
    assert preview.parent == old
    assert preview.files == 5
    assert set(preview.removed) == {
        "OWNER_STEPS.md",
        "thomas/security/secret_canaries.py",
        "tests/test_secret_canaries.py",
    }
    assert all(preview.removed.values())
    assert preview.changed == 5
    assert (sh(dev, "rev-parse", "HEAD"), sh(dev, "status", "--porcelain")) == before
    assert "a private commit message" not in json.dumps(preview.to_dict())
    preview.close()
    assert not Path(preview.scratch or "x").exists()


def test_an_excluded_file_never_reaches_the_tree(tmp_path: Path) -> None:
    preview = _build(tmp_path)

    in_tree = sh(Path(preview.scratch) / "tree", "ls-tree", "-r", "--name-only", preview.tree).splitlines()

    assert not {"OWNER_STEPS.md", "thomas/security/secret_canaries.py", "tests/test_secret_canaries.py"} & set(in_tree)
    assert "thomas/security/__init__.py" in in_tree
    assert not (Path(preview.scratch) / "tree" / "OWNER_STEPS.md").exists()


def test_the_preview_refuses_when_a_check_fails(tmp_path: Path) -> None:
    preview = _build(tmp_path, preflight=lambda _tree: (False, "1 unexpected file at the root"))

    assert not preview.safe_to_publish
    failed = [c for c in preview.checks if not c.ok]
    assert [c.name for c in failed] == ["Publish safety checks"]
    assert failed[0].reason == "1 unexpected file at the root"
    assert "Not safe to publish yet." in pr.describe(preview)


def test_a_kept_file_that_needs_a_left_out_file_fails_the_preview(tmp_path: Path) -> None:
    preview = _build(tmp_path, {"thomas/app.py": "from thomas.security import secret_canaries\n"})

    failed = [c for c in preview.checks if not c.ok]
    assert [c.name for c in failed] == ["Nothing kept needs a left-out file"]
    assert "thomas/app.py" in failed[0].reason
    assert not preview.safe_to_publish


def test_a_file_that_does_not_compile_fails_the_preview(tmp_path: Path) -> None:
    preview = _build(tmp_path, {"thomas/broken.py": "def (:\n"})

    assert [c.name for c in preview.checks if not c.ok] == ["Every Python file compiles"]


def test_a_version_with_no_release_notes_fails_the_preview(tmp_path: Path) -> None:
    preview = _build(tmp_path, {"CHANGELOG.md": CHANGELOG.replace("[1.2.3]", "[9.9.9]")})

    failed = [c for c in preview.checks if not c.ok]
    assert [c.name for c in failed] == ["Version and release notes"]
    assert "1.2.3" in failed[0].reason


def test_without_a_public_repository_nothing_can_be_published(tmp_path: Path) -> None:
    preview = prev.build(make_dev(tmp_path), remote=None, preflight=ok_preflight, scratch_parent=tmp_path)

    assert [c.name for c in preview.checks if not c.ok] == ["Public copy"]
    assert preview.parent is None and preview.changed is None


def test_a_public_repository_that_cannot_be_read_is_a_failed_check_not_a_crash(tmp_path: Path) -> None:
    preview = prev.build(
        make_dev(tmp_path), remote=str(tmp_path / "nowhere.git"), preflight=ok_preflight, scratch_parent=tmp_path
    )

    failed = [c for c in preview.checks if not c.ok]
    assert [c.name for c in failed] == ["Public copy"]
    assert "could not be read" in failed[0].reason


def test_a_public_copy_that_already_holds_the_tree_has_nothing_new(tmp_path: Path) -> None:
    dev = make_dev(tmp_path)
    bare, _old = make_public(tmp_path)
    first = prev.build(dev, remote=str(bare), preflight=ok_preflight, scratch_parent=tmp_path)
    tree = Path(first.scratch) / "tree"
    ident = ("-c", "user.name=x", "-c", "user.email=x@x.invalid")
    same = sh(tree, *ident, "commit-tree", first.tree, "-p", str(first.parent), "-m", "same")
    sh(tree, "push", "-q", str(bare), f"{same}:refs/heads/main")

    second = prev.build(dev, remote=str(bare), preflight=ok_preflight, scratch_parent=tmp_path)

    failed = [c for c in second.checks if not c.ok]
    assert [c.name for c in failed] == ["Public copy"] and "nothing new" in failed[0].reason
    assert second.changed == 0


def test_the_digest_follows_what_the_preview_says(tmp_path: Path) -> None:
    preview = _build(tmp_path)
    same = preview.digest()
    preview.files += 1

    assert preview.digest() != same
    assert len(same) == 64


def test_the_real_preflight_runs_deep_and_strict_on_the_pruned_tree(monkeypatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_run(argv: list[str]) -> int:
        seen.append(list(argv))
        print(json.dumps({"errors": ["tool failed: not json"]}))
        return 1

    monkeypatch.setattr(preflight, "run", fake_run)

    ok, reason = prev.default_preflight(tmp_path)

    assert seen == [["--repo-root", str(tmp_path), "--deep", "--strict", "--json"]]
    assert not ok and reason == "tool failed: not json"


def test_a_scratch_folder_the_module_did_not_make_is_never_removed(tmp_path: Path) -> None:
    mine = tmp_path / "keep-me"
    mine.mkdir()
    (mine / "file.txt").write_text("x", encoding="utf-8")

    prev.Preview("1", "a", "b", None, "", "main", 0, {}, None, scratch=str(mine)).close()

    assert (mine / "file.txt").is_file()
