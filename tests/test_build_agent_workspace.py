"""Private snapshots preserve current work and reject stale integrations."""

from __future__ import annotations

import asyncio
import os

import pytest

from thomas.forge.anvil.build_agent_workspace import BuildWorkspace, integration_guard, relative_file
from thomas.forge.anvil.forge_code_manifest import ManifestTooLarge


def test_snapshot_preserves_dirty_bytes_and_excludes_runtime(tmp_path):
    (tmp_path / "index.html").write_bytes(b"unmerged UI\r\nsecond line\r\n")
    (tmp_path / "styles.css").write_bytes(b"old style\r\n")
    runtime = tmp_path / ".thomas"
    runtime.mkdir()
    (runtime / "private.txt").write_text("runtime", encoding="utf-8")
    item = BuildWorkspace.create(tmp_path, "child_000000000001", "styles.css")
    assert (item.root / "index.html").read_bytes() == b"unmerged UI\r\nsecond line\r\n"
    assert not (item.root / ".thomas").exists()
    (item.root / "styles.css").write_text("body {color: orange}", encoding="utf-8")
    assert item.candidate() == "body {color: orange}"
    item.check_base()
    assert (tmp_path / "styles.css").read_bytes() == b"old style\r\n"
    assert item.receipt["state"] == "candidate" and item.receipt["base_file"]


def test_collateral_changes_and_deletion_are_not_candidates(tmp_path):
    (tmp_path / "a.txt").write_text("original a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("original b", encoding="utf-8")
    item = BuildWorkspace.create(tmp_path, "child_000000000002", "a.txt")
    (item.root / "a.txt").write_text("new a", encoding="utf-8")
    (item.root / "b.txt").write_text("new b", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly"):
        item.candidate()
    (item.root / "b.txt").write_text("original b", encoding="utf-8")
    (item.root / "a.txt").unlink()
    with pytest.raises(ValueError, match="cannot delete"):
        item.candidate()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "original a"


@pytest.mark.parametrize("existing", [True, False])
def test_parent_changes_since_snapshot_are_conflicts(tmp_path, existing):
    if existing:
        (tmp_path / "a.txt").write_text("original", encoding="utf-8")
    item = BuildWorkspace.create(tmp_path, "child_000000000003", "a.txt")
    (item.root / "a.txt").write_text("helper", encoding="utf-8")
    (tmp_path / "a.txt").write_text("user's newer edit", encoding="utf-8")
    with pytest.raises(ValueError, match="integration conflict"):
        item.check_base()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "user's newer edit"


@pytest.mark.parametrize("path", ["../a", "/a", "C:/a", "a/../b", ".git/config", ".thomas/a", "NUL", "a:stream", "a."])
def test_assignment_paths_fail_closed(tmp_path, path):
    with pytest.raises(ValueError):
        relative_file(tmp_path, path)


def test_linked_target_is_not_an_assignment(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("real", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(target)
    except OSError:
        pytest.skip("host does not permit creation of test symlinks")
    with pytest.raises(ValueError, match="link"):
        relative_file(tmp_path, "link.txt")


def test_snapshot_refuses_oversized_project_before_copying(tmp_path):
    with (tmp_path / "large.bin").open("wb") as handle:
        handle.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(ManifestTooLarge):
        BuildWorkspace.create(tmp_path, "child_000000000004", "new.txt")
    assert not (tmp_path / ".thomas").exists()


def test_selected_context_supports_large_projects_without_silently_truncating(tmp_path):
    with (tmp_path / "unrelated.bin").open("wb") as handle:
        handle.truncate(64 * 1024 * 1024 + 1)
    (tmp_path / "contract.txt").write_text("shared contract")
    item = BuildWorkspace.create(tmp_path, "child_000000000010", "new.txt", context_files=["contract.txt"])
    assert item.receipt["snapshot_kind"] == "selected_files"
    assert item.receipt["context_files"] == ["contract.txt"]
    assert not (item.root / "unrelated.bin").exists()
    assert (item.root / "contract.txt").read_text() == "shared contract"
    (item.root / "new.txt").write_text("new file")
    assert item.candidate() == "new file"
    (item.root / "contract.txt").write_text("tampered")
    with pytest.raises(ValueError, match="exactly"):
        item.candidate()


@pytest.mark.parametrize("context", [["missing.txt"], ["../outside"], [".env"], "contract.txt", [1], ["x"] * 101])
def test_selected_context_is_complete_and_validated(tmp_path, context):
    (tmp_path / ".env").write_text("private")
    with pytest.raises((ValueError, OSError)):
        BuildWorkspace.create(tmp_path, "child_000000000011", "new.txt", context_files=context)
    assert not (tmp_path / ".thomas").exists()


@pytest.mark.parametrize("missing", ["missing.txt", "new_folder/context.py"])
def test_missing_context_names_the_file_before_creating_workspace(tmp_path, missing):
    with pytest.raises(ValueError, match=f"context file does not exist: {missing}"):
        BuildWorkspace.create(tmp_path, "child_000000000012", "new.py", context_files=[missing])
    assert not (tmp_path / ".thomas").exists()


@pytest.mark.parametrize("missing", ["missing.txt", "new_folder/context.py", "new.py"])
def test_missing_context_after_existing_file_is_rejected_before_artifacts(tmp_path, missing):
    (tmp_path / "contract.txt").write_text("shared contract", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        BuildWorkspace.create(tmp_path, "child_000000000013", "new.py", context_files=["contract.txt", missing])
    assert str(exc.value) == f"context file does not exist: {missing}"
    assert not (tmp_path / ".thomas").exists()
    assert not (tmp_path / "new.py").exists()


def test_hard_links_are_refused_initially_and_when_swapped_after_snapshot(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("same original bytes", encoding="utf-8")
    target = project / "a.txt"
    os.link(outside, target)
    with pytest.raises(ValueError, match="hard-linked"):
        BuildWorkspace.create(project, "child_000000000005", "a.txt")
    target.unlink()
    target.write_bytes(outside.read_bytes())
    workspace = BuildWorkspace.create(project, "child_000000000006", "a.txt")
    target.unlink()
    os.link(outside, target)  # same content hash; link identity still must fail
    with pytest.raises(ValueError, match="hard-linked"):
        workspace.check_base()
    assert outside.read_text(encoding="utf-8") == "same original bytes"


@pytest.mark.asyncio
async def test_integration_lock_serializes_waiters_and_releases_on_cancel(tmp_path):
    clock = asyncio.get_running_loop()
    entered = asyncio.Event()

    async def waiting():
        async with integration_guard(tmp_path, clock.time() + 10):
            entered.set()

    async with integration_guard(tmp_path, clock.time() + 10):
        pending = asyncio.create_task(waiting())
        await asyncio.sleep(0)
        assert not entered.is_set()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        with pytest.raises(TimeoutError):
            async with integration_guard(tmp_path, clock.time() + 0.01):
                pytest.fail("second integration acquired the occupied lock")
    async with integration_guard(tmp_path, clock.time() + 1):
        assert not entered.is_set()
