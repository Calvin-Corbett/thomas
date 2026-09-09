"""A Build on a folder without history still knows what it changed (2026-09-05).

Codex reproduced it: a project opened with "work without history" saves that
choice, but the run launch still calls ``forge_code_git.snapshot`` and refuses
a folder that is not a repository, so the choice could open the project and
never build in it. The snapshot for such a folder is a content manifest (path,
size, sha256) taken before the run and diffed after: real file attribution,
nothing that pretends to be git. Undo says it is unavailable and why; a run
snapshot reports that there is no history to commit into.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_git, forge_code_manifest


def _folder(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / ".thomas").mkdir()
    (tmp_path / ".thomas" / "notes.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_a_folder_without_history_is_refused_unless_the_choice_was_made(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    with pytest.raises(forge_code_git.ForgeCodeGitError):
        forge_code_git.snapshot(root)
    snap = forge_code_git.snapshot(root, allow_without_history=True)
    assert forge_code_manifest.is_manifest(snap)
    assert "src/main.js" in snap and "index.html" in snap
    assert not any(p.startswith(".thomas/") for p in snap)


def test_the_delta_names_added_modified_and_deleted_files(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    snap = forge_code_git.snapshot(root, allow_without_history=True)
    (root / "src" / "main.js").write_text("console.log(2)", encoding="utf-8")
    (root / "new.css").write_text("body{}", encoding="utf-8")
    (root / "index.html").unlink()
    (root / ".thomas" / "transcript.txt").write_text("x", encoding="utf-8")
    assert forge_code_git.delta_since(root, snap) == ["index.html", "new.css", "src/main.js"]
    assert forge_code_git.project_delta_since(root, snap) == ["index.html", "new.css", "src/main.js"]
    rows = forge_code_manifest.change_evidence(root, ["src/main.js", "new.css", "index.html"], snap)
    by_file = {r["file"]: r for r in rows}
    assert by_file["src/main.js"]["status"] == "modified"
    assert by_file["src/main.js"]["before"] != by_file["src/main.js"]["after"]
    assert by_file["new.css"]["status"] == "added" and by_file["new.css"]["before"] == ""
    assert by_file["index.html"]["status"] == "deleted" and by_file["index.html"]["after"] == ""
    assert all(r["history_available"] is False and r["diff"] == "" for r in rows)


def test_an_untouched_folder_has_an_empty_delta(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    snap = forge_code_git.snapshot(root, allow_without_history=True)
    assert forge_code_git.project_delta_since(root, snap) == []


def test_undo_and_run_snapshots_say_there_is_no_history(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    result = forge_code_git.revert_file(root, "src/main.js")
    assert result["ok"] is False and result["clean"] is False
    assert "no version history" in result["reason"], result
    assert (root / "src" / "main.js").exists()  # nothing was touched
    committed = forge_code_git.commit_run_snapshot(root, run_id="run-x")
    assert committed.get("committed") is False and "history" in str(committed.get("reason") or ""), committed


def test_a_real_repository_still_uses_git_when_the_flag_is_on(tmp_path: Path) -> None:
    import subprocess

    root = _folder(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    snap = forge_code_git.snapshot(root, allow_without_history=True)
    assert not forge_code_manifest.is_manifest(snap)


def test_the_scan_stays_inside_the_folder_and_is_bounded(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("nope", encoding="utf-8")
    try:
        os.symlink(outside, root / "escape", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges here")
    snap = forge_code_manifest.snapshot(root)
    assert not any(p.startswith("escape") for p in snap), [p for p in snap if p.startswith("escape")]
    (root / "node_modules").mkdir()
    (root / "node_modules" / "big.js").write_text("x" * 10, encoding="utf-8")
    assert "node_modules/big.js" not in forge_code_manifest.snapshot(root)
    with pytest.raises(forge_code_manifest.ManifestTooLarge):
        forge_code_manifest.snapshot(root, max_files=1)


# Codex's review of the first cut found five ways it failed open. Each is a test.


def test_a_dunder_file_is_attributed_like_any_other(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    snap = forge_code_git.snapshot(root, allow_without_history=True)
    (root / "pkg" / "__init__.py").write_text("VERSION = 2\n", encoding="utf-8")
    assert forge_code_git.delta_since(root, snap) == ["pkg/__init__.py"]


def test_an_unreadable_file_refuses_the_whole_snapshot(tmp_path: Path, monkeypatch) -> None:
    root = _folder(tmp_path)
    real = forge_code_manifest._fingerprint

    def flaky(path: Path, st):
        if path.name == "main.js":
            raise OSError(13, "locked")
        return real(path, st)

    monkeypatch.setattr(forge_code_manifest, "_fingerprint", flaky)
    with pytest.raises(forge_code_manifest.ManifestUnreadable, match="src/main.js"):
        forge_code_manifest.snapshot(root)
    with pytest.raises(forge_code_git.ForgeCodeGitError, match="src/main.js"):
        forge_code_git.snapshot(root, allow_without_history=True)
    monkeypatch.setattr(forge_code_manifest, "_fingerprint", real)
    snap = forge_code_git.snapshot(root, allow_without_history=True)
    monkeypatch.setattr(forge_code_manifest, "_fingerprint", flaky)
    with pytest.raises(forge_code_git.ForgeCodeGitError):  # a file that became unreadable during the run
        forge_code_git.project_delta_since(root, snap)


def test_too_many_files_refuses_rather_than_attributing_part_of_the_folder(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    with pytest.raises(forge_code_manifest.ManifestTooLarge):
        forge_code_manifest.snapshot(root, max_files=1)
    with pytest.raises(forge_code_git.ForgeCodeGitError):
        forge_code_git.snapshot(root, allow_without_history=True, max_files=1)


def test_too_many_bytes_refuses_and_every_entry_is_a_real_hash(tmp_path: Path, monkeypatch) -> None:
    root = _folder(tmp_path)
    (root / "__manifest__").write_text("a file with the marker's old name", encoding="utf-8")
    snap = forge_code_manifest.snapshot(root)
    assert all(v.startswith("sha256:") for k, v in snap.items() if k != forge_code_manifest.MARKER), snap
    assert "__manifest__" in snap and forge_code_manifest.is_manifest(snap)
    monkeypatch.setattr(forge_code_manifest, "MAX_TOTAL_BYTES", 4)
    with pytest.raises(forge_code_manifest.ManifestTooLarge, match="bytes"):
        forge_code_manifest.snapshot(root)
    with pytest.raises(forge_code_git.ForgeCodeGitError):
        forge_code_git.snapshot(root, allow_without_history=True)


def test_a_directory_that_cannot_be_listed_refuses_the_snapshot(tmp_path: Path, monkeypatch) -> None:
    root = _folder(tmp_path)
    real_walk = forge_code_manifest.os.walk

    def walk(top, onerror=None, **kw):
        onerror(OSError(13, "denied", str(Path(top) / "src")))
        return real_walk(top, onerror=onerror, **kw)

    monkeypatch.setattr(forge_code_manifest.os, "walk", walk)
    with pytest.raises(forge_code_manifest.ManifestUnreadable, match="cannot list"):
        forge_code_manifest.snapshot(root)


def test_a_junction_or_link_out_of_the_folder_is_not_followed(tmp_path: Path) -> None:
    import subprocess

    root = _folder(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-out"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("nope", encoding="utf-8")
    link = root / "jump"
    if os.name == "nt":
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if proc.returncode != 0:
            pytest.skip("junctions unavailable here")
    else:
        os.symlink(outside, link, target_is_directory=True)
    snap = forge_code_manifest.snapshot(root)
    assert not any(p.startswith("jump") for p in snap), [p for p in snap if p.startswith("jump")]


def test_a_delta_over_a_folder_that_outgrew_the_bound_fails_as_a_git_error(tmp_path: Path, monkeypatch) -> None:
    root = _folder(tmp_path)
    snap = forge_code_git.snapshot(root, allow_without_history=True)
    monkeypatch.setattr(forge_code_manifest, "MAX_FILES", 1)
    with pytest.raises(forge_code_git.ForgeCodeGitError):
        forge_code_git.delta_since(root, snap)
    with pytest.raises(forge_code_git.ForgeCodeGitError):
        forge_code_git.project_delta_since(root, snap)


def test_a_junction_back_into_the_folder_is_not_walked_and_cannot_loop(tmp_path: Path) -> None:
    import subprocess

    root = _folder(tmp_path)
    link = root / "src" / "loop"
    if os.name == "nt":
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(root)], capture_output=True)
        if proc.returncode != 0:
            pytest.skip("junctions unavailable here")
    else:
        os.symlink(root, link, target_is_directory=True)
    snap = forge_code_manifest.snapshot(root, max_files=50)  # a cycle would hit the bound or hang
    assert sorted(k for k in snap if k != forge_code_manifest.MARKER) == ["index.html", "src/main.js"]
