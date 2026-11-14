"""An omitted pre-image must never be replaced by an older Git or missing file."""

import stat
import subprocess
from unittest.mock import patch

import pytest

from thomas.forge.anvil import forge_code_redesign_undo as undo


@pytest.mark.parametrize("content_changed", [False, True])
def test_undo_restores_readonly_preimage_and_exact_bytes(tmp_path, content_changed):
    target = tmp_path / "file.txt"
    target.write_bytes(b"before\r\n")
    target.chmod(stat.S_IREAD)
    mode = stat.S_IMODE(target.stat().st_mode)
    launch = undo.capture_launch_state(tmp_path, {"file.txt": "dirty"})
    target.chmod(mode | stat.S_IWRITE)
    if content_changed:
        target.write_bytes(b"after\r\n")
    assert undo.persist_run_preimages(tmp_path, tmp_path / "catalog", "chat", "mode", ["file.txt"], launch)["available"]
    try:
        assert undo.restore_run_preimages(tmp_path, tmp_path / "catalog", "chat", "mode") == ["file.txt"]
        assert target.read_bytes() == b"before\r\n"
        assert stat.S_IMODE(target.stat().st_mode) == mode
    finally:
        target.chmod(mode | stat.S_IWRITE)


def test_undo_refuses_permission_only_later_edit(tmp_path):
    target = tmp_path / "file.txt"
    target.write_bytes(b"before")
    launch = undo.capture_launch_state(tmp_path, {"file.txt": "dirty"})
    target.write_bytes(b"after")
    assert undo.persist_run_preimages(tmp_path, tmp_path / "catalog", "chat", "mode", ["file.txt"], launch)["available"]
    target.chmod(stat.S_IREAD)
    try:
        with pytest.raises(undo.RedesignUndoError, match="later edits"):
            undo.restore_run_preimages(tmp_path, tmp_path / "catalog", "chat", "mode")
        assert target.read_bytes() == b"after"
        assert not target.stat().st_mode & stat.S_IWRITE
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("attributes_changed", [False, True])
def test_clean_git_checkout_restores_actual_crlf_and_readonly_mode(tmp_path, attributes_changed):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "clean.txt"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "core.autocrlf", "true"], check=True)
    target.write_bytes(b"original\r\n")
    subprocess.run(["git", "-C", str(project), "add", "clean.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Proof",
            "-c",
            "user.email=proof@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
        check=True,
    )
    assert subprocess.check_output(["git", "-C", str(project), "show", "HEAD:clean.txt"]) == b"original\n"
    target.chmod(stat.S_IREAD)
    before_mode = stat.S_IMODE(target.stat().st_mode)
    launch = undo.capture_launch_state(project, {})
    changed = ["clean.txt"]
    if attributes_changed:
        (project / ".gitattributes").write_text("clean.txt -text\n", encoding="utf-8")
        changed.append(".gitattributes")
    target.chmod(before_mode | stat.S_IWRITE)
    target.write_bytes(b"changed\n")
    try:
        assert undo.persist_run_preimages(project, tmp_path / "catalog", "chat", "clean", changed, launch)["available"]
        undo.restore_run_preimages(project, tmp_path / "catalog", "chat", "clean")
        assert target.read_bytes() == b"original\r\n"
        assert stat.S_IMODE(target.stat().st_mode) == before_mode
        assert not (project / ".gitattributes").exists()
    finally:
        target.chmod(before_mode | stat.S_IWRITE)


def test_failed_tracked_inventory_cannot_restore_clean_file_from_git(tmp_path):
    target = tmp_path / "clean.txt"
    target.write_bytes(b"original\r\n")
    with patch.object(undo.forge_code_git, "_run_git", side_effect=[(0, "HEAD", ""), (1, "", "inventory failed")]):
        launch = undo.capture_launch_state(tmp_path, {})
    target.write_bytes(b"current\r\n")
    with patch.object(undo, "_git_blob") as fallback:
        result = undo.persist_run_preimages(tmp_path, tmp_path / "catalog", "chat", "failed", ["clean.txt"], launch)
    assert result["available"] is False
    assert "inventory was unavailable" in result["reason"]
    fallback.assert_not_called()
    assert target.read_bytes() == b"current\r\n"


def test_oversized_dirty_preimage_refuses_undo_without_modifying_current_file(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "existing.txt"
    target.write_bytes(b"Original user content")
    with patch.object(undo, "_MAX_LAUNCH_DIRTY_BYTES", 4):
        launch = undo.capture_launch_state(project, {"existing.txt": "dirty"})
    target.write_bytes(b"Redesign output")
    with patch.object(undo, "_git_blob") as fallback:
        result = undo.persist_run_preimages(project, tmp_path / "catalog", "chat", "run", ["existing.txt"], launch)
    assert result["available"] is False
    assert "not captured" in result["reason"]
    fallback.assert_not_called()
    assert target.read_bytes() == b"Redesign output"


def test_legacy_capture_without_dirty_inventory_cannot_guess_a_preimage(tmp_path):
    target = tmp_path / "old.txt"
    target.write_bytes(b"Current user content")
    with patch.object(undo, "_git_blob") as fallback:
        result = undo.persist_run_preimages(
            tmp_path, tmp_path / "catalog", "chat", "old-run", ["old.txt"], {"revision": "old-commit", "dirty": {}}
        )
    assert result["available"] is False
    fallback.assert_not_called()
    assert target.read_bytes() == b"Current user content"


@pytest.mark.parametrize("failure", [OSError("Git unavailable"), subprocess.TimeoutExpired("git", 30)])
def test_git_read_failure_cannot_turn_a_tracked_file_into_missing(tmp_path, failure):
    target = tmp_path / "tracked.txt"
    target.write_bytes(b"Current tracked content")
    with patch.object(undo.subprocess, "run", side_effect=failure):
        result = undo.persist_run_preimages(
            tmp_path,
            tmp_path / "catalog",
            "chat",
            "run",
            ["tracked.txt"],
            {"revision": "pinned", "dirty": {}, "dirty_paths": []},
        )
    assert result["available"] is False
    assert target.read_bytes() == b"Current tracked content"


def test_complete_non_git_inventory_supports_undo_of_new_files(tmp_path):
    from thomas.forge.anvil import forge_code_manifest

    project = tmp_path / "project"
    project.mkdir()
    existing = project / "existing.txt"
    existing.write_bytes(b"Original")
    snapshot = forge_code_manifest.snapshot(project)
    launch = undo.capture_launch_state(project, snapshot)
    new_file = project / "new.txt"
    new_file.write_bytes(b"New output")
    result = undo.persist_run_preimages(project, tmp_path / "catalog", "chat", "run", ["new.txt"], launch)
    assert result["available"] is True
    undo.restore_run_preimages(project, tmp_path / "catalog", "chat", "run")
    assert not new_file.exists()
    assert existing.read_bytes() == b"Original"


def test_locked_second_file_keeps_its_bytes_and_undo_can_resume(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    a, b = project / "a.txt", project / "b.txt"
    a.write_bytes(b"before a")
    b.write_bytes(b"before b")
    launch = undo.capture_launch_state(project, {"a.txt": "dirty", "b.txt": "dirty"})
    a.write_bytes(b"after a")
    b.write_bytes(b"after b")
    catalog = tmp_path / "catalog"
    assert undo.persist_run_preimages(project, catalog, "chat", "run", ["a.txt", "b.txt"], launch)["available"]
    replace = undo.os.replace

    def locked(source, destination):
        if destination == b:
            raise PermissionError("Editor holds b.txt")
        return replace(source, destination)

    with patch.object(undo.os, "replace", side_effect=locked), pytest.raises(PermissionError):
        undo.restore_run_preimages(project, catalog, "chat", "run")
    assert a.read_bytes() == b"before a"
    assert b.read_bytes() == b"after b"
    assert not list(project.glob(".redesign-undo-*"))
    assert undo.restore_run_preimages(project, catalog, "chat", "run") == ["a.txt", "b.txt"]
    assert a.read_bytes() == b"before a" and b.read_bytes() == b"before b"


def test_git_symlink_mode_preserves_link_identity(tmp_path):
    responses = [
        subprocess.CompletedProcess([], 0, stdout=b"120000 blob hash\tlink\0"),
        subprocess.CompletedProcess([], 0, stdout=b"target.txt"),
    ]
    with patch.object(undo.subprocess, "run", side_effect=responses):
        before = undo._git_blob(tmp_path, "pinned", "link")
    assert before["kind"] == "symlink"
    assert before["value"] == "target.txt"


def test_parent_path_cannot_escape_project(tmp_path):
    with pytest.raises(undo.RedesignUndoError):
        undo._safe_path(tmp_path, "..")


def test_manifest_excluded_dependency_file_is_not_treated_as_new(tmp_path):
    from thomas.forge.anvil import forge_code_manifest

    project = tmp_path / "project"
    dependency = project / "node_modules" / "custom.js"
    dependency.parent.mkdir(parents=True)
    dependency.write_bytes(b"Existing dependency")
    launch = undo.capture_launch_state(project, forge_code_manifest.snapshot(project))
    dependency.write_bytes(b"Modified dependency")
    result = undo.persist_run_preimages(
        project, tmp_path / "catalog", "chat", "run", ["node_modules/custom.js"], launch
    )
    assert result["available"] is False
    assert dependency.read_bytes() == b"Modified dependency"


def test_manifest_excluded_leaf_is_not_treated_as_new(tmp_path):
    from thomas.forge.anvil import forge_code_manifest

    leaf = tmp_path / "excluded.txt"
    leaf.write_bytes(b"Existing excluded content")
    inside = forge_code_manifest._inside
    # Exercise the actual manifest exclusion for a leaf whose resolved target
    # is outside; Windows need not grant symlink-creation privilege to this test.
    with patch.object(
        forge_code_manifest, "_inside", side_effect=lambda base, full: False if full == leaf else inside(base, full)
    ):
        snapshot = forge_code_manifest.snapshot(tmp_path)
        launch = undo.capture_launch_state(tmp_path, snapshot)
    leaf.write_bytes(b"Replacement content")
    result = undo.persist_run_preimages(tmp_path, tmp_path / "catalog", "chat", "run", [leaf.name], launch)
    assert result["available"] is False
    assert leaf.read_bytes() == b"Replacement content"
