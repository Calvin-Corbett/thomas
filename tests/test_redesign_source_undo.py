from pathlib import Path

from thomas.forge.anvil import forge_code_git, forge_code_redesign_undo, forge_code_store


def _redesign_self_edit_and_undo(monkeypatch, tmp_path: Path) -> tuple[Path, Path, str, str]:
    """Drive the same capture/write/persist/undo path as a Redesign Build run."""
    project = tmp_path / "checkout"
    catalog = tmp_path / "conversation-catalog"
    project.mkdir()
    target = project / "redesign_target.js"
    unrelated = project / "teammate_uncommitted.js"
    before = "export const label = 'before redesign';\n"
    teammate_before = "export const teammateWork = 'keep me';\n"
    target.write_text(before, encoding="utf-8")
    unrelated.write_text(teammate_before, encoding="utf-8")
    monkeypatch.setattr(forge_code_git, "_run_git", lambda *_args, **_kwargs: (0, "revision", ""))

    launch = forge_code_redesign_undo.capture_launch_state(
        project,
        {"redesign_target.js": "dirty", "teammate_uncommitted.js": "dirty"},
        catalog_root=catalog,
        conversation_id="redesign-conversation",
        run_id="redesign-run",
    )
    target.write_text("export const label = 'after redesign';\n", encoding="utf-8")
    forge_code_redesign_undo.persist_run_preimages(
        project,
        catalog,
        "redesign-conversation",
        "redesign-run",
        ["redesign_target.js"],
        launch,
    )
    forge_code_redesign_undo.restore_run_preimages(project, catalog, "redesign-conversation", "redesign-run")
    return target, unrelated, before, teammate_before


def test_redesign_undo_restores_only_this_runs_preimages(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "shell.js"
    unrelated = tmp_path / "other.js"
    target.write_text("before redesign\n", encoding="utf-8")
    unrelated.write_text("someone else's uncommitted work\n", encoding="utf-8")

    monkeypatch.setattr(
        forge_code_git,
        "_run_git",
        lambda *_args, **_kwargs: (0, "revision-before-run", ""),
    )
    launch = forge_code_redesign_undo.capture_launch_state(
        tmp_path,
        {"shell.js": "dirty-before", "other.js": "unrelated-before"},
    )

    target.write_text("after redesign\n", encoding="utf-8")
    undo = forge_code_redesign_undo.persist_run_preimages(
        tmp_path,
        tmp_path / "conversation-records",
        "conversation-1",
        "run-1",
        ["shell.js"],
        launch,
    )
    assert undo["available"] is True
    assert undo["files"] == ["shell.js"]

    restored = forge_code_redesign_undo.restore_run_preimages(
        tmp_path,
        tmp_path / "conversation-records",
        "conversation-1",
        "run-1",
    )

    assert restored == ["shell.js"]
    assert target.read_text(encoding="utf-8") == "before redesign\n"
    assert unrelated.read_text(encoding="utf-8") == "someone else's uncommitted work\n"
    assert not (tmp_path / ".thomas").exists()


def test_redesign_undo_refuses_to_overwrite_a_later_edit(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "shell.js"
    target.write_text("before redesign\n", encoding="utf-8")
    monkeypatch.setattr(forge_code_git, "_run_git", lambda *_args, **_kwargs: (0, "revision", ""))
    launch = forge_code_redesign_undo.capture_launch_state(tmp_path, {"shell.js": "dirty"})
    target.write_text("after redesign\n", encoding="utf-8")
    forge_code_redesign_undo.persist_run_preimages(
        tmp_path,
        tmp_path / "conversation-records",
        "conversation-1",
        "run-1",
        ["shell.js"],
        launch,
    )
    target.write_text("later teammate edit\n", encoding="utf-8")

    try:
        forge_code_redesign_undo.restore_run_preimages(
            tmp_path,
            tmp_path / "conversation-records",
            "conversation-1",
            "run-1",
        )
    except forge_code_redesign_undo.RedesignUndoError as exc:
        assert "changed after this Redesign" in str(exc)
    else:
        raise AssertionError("later edits must block Redesign undo")

    assert target.read_text(encoding="utf-8") == "later teammate edit\n"


def test_large_unrelated_dirty_file_does_not_block_redesign_launch(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "target.js"
    unrelated = tmp_path / "large.bin"
    target.write_text("before\n", encoding="utf-8")
    unrelated.write_bytes(b"x" * 9)
    monkeypatch.setattr(forge_code_git, "_run_git", lambda *_args, **_kwargs: (0, "revision", ""))
    monkeypatch.setattr(forge_code_redesign_undo, "_MAX_LAUNCH_DIRTY_BYTES", 8)

    launch = forge_code_redesign_undo.capture_launch_state(tmp_path, {"target.js": "dirty", "large.bin": "dirty"})

    assert "target.js" in launch["dirty"]
    assert "large.bin" not in launch["dirty"]


def test_a_self_edit_undo_matches_its_pre_run_file_and_preserves_other_uncommitted_work(
    monkeypatch, tmp_path: Path
) -> None:
    target, unrelated, before, teammate_before = _redesign_self_edit_and_undo(monkeypatch, tmp_path)

    assert target.read_text(encoding="utf-8") == before
    assert unrelated.read_text(encoding="utf-8") == teammate_before


def test_redesign_undo_evidence_lives_with_conversation_records(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    catalog = tmp_path / "catalog"
    project.mkdir()
    target = project / "shell.js"
    target.write_text("before redesign\n", encoding="utf-8")
    monkeypatch.setattr(forge_code_git, "_run_git", lambda *_args, **_kwargs: (0, "revision", ""))

    launch = forge_code_redesign_undo.capture_launch_state(
        project,
        {"shell.js": "dirty"},
        catalog_root=catalog,
        conversation_id="conversation-1",
        run_id="run-1",
    )
    target.write_text("after redesign\n", encoding="utf-8")
    forge_code_redesign_undo.persist_run_preimages(project, catalog, "conversation-1", "run-1", ["shell.js"], launch)

    records = catalog / ".thomas" / "evolve" / "agent" / "conversations"
    manifests = list(records.glob("*.redesign-undo/*.json"))
    assert len(manifests) == 1
    assert not (project / ".thomas").exists()

    forge_code_redesign_undo.discard_run_preimages(catalog, "conversation-1", "run-1")
    assert not list(records.glob("*.redesign-undo/*.json"))


def test_preimage_is_durable_before_self_edit_source_write(tmp_path: Path) -> None:
    project = tmp_path / "checkout"
    catalog = tmp_path / "catalog"
    project.mkdir()
    target = project / "shell.js"
    target.write_text("before\n", encoding="utf-8")
    before = forge_code_redesign_undo._file_state(target)

    manifest = forge_code_redesign_undo.stage_run_preimages(catalog, "conversation", "run", {"shell.js": before})

    assert manifest.is_file()
    assert not manifest.is_relative_to(project)
    assert '"state": "staged"' in manifest.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "before\n"

    target.write_text("after\n", encoding="utf-8")
    result = forge_code_redesign_undo.finalize_staged_preimages(project, catalog, "conversation", "run", ["shell.js"])
    assert result["available"] is True
    assert forge_code_redesign_undo.restore_run_preimages(project, catalog, "conversation", "run") == ["shell.js"]
    assert target.read_text(encoding="utf-8") == "before\n"


def test_staged_preimage_cannot_restore_until_the_run_records_its_write(tmp_path: Path) -> None:
    project = tmp_path / "checkout"
    catalog = tmp_path / "catalog"
    project.mkdir()
    target = project / "shell.js"
    target.write_text("before\n", encoding="utf-8")
    forge_code_redesign_undo.stage_run_preimages(
        catalog, "conversation", "run", {"shell.js": forge_code_redesign_undo._file_state(target)}
    )

    try:
        forge_code_redesign_undo.restore_run_preimages(project, catalog, "conversation", "run")
    except forge_code_redesign_undo.RedesignUndoError as exc:
        assert "did not finish recording" in str(exc)
    else:
        raise AssertionError("a staged-only pre-image must keep Undo disabled")
