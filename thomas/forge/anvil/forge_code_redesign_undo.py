"""Run-scoped pre-images for undoing Redesign source edits without Git checkout."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_git, forge_code_manifest

_MAX_PREIMAGE_BYTES = 25 * 1024 * 1024
_MAX_LAUNCH_DIRTY_BYTES = _MAX_PREIMAGE_BYTES * 2


class RedesignUndoError(RuntimeError):
    """A Redesign pre-image could not be captured or restored safely."""


def _manifest_path(catalog_root: str | Path, conversation_id: str, run_id: str) -> Path:
    """Return the private, run-scoped manifest path for one Redesign operation."""
    root = Path(catalog_root).resolve()
    conversation_key = hashlib.sha256(str(conversation_id).encode("utf-8")).hexdigest()
    run_key = hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()
    # Keep undo evidence beside the owning conversation records, never in the
    # selected project's source tree. The hashed directory is private to this
    # conversation and each manifest is private to one Redesign run.
    return (
        root
        / ".thomas"
        / "evolve"
        / "agent"
        / "conversations"
        / f"{conversation_key}.redesign-undo"
        / f"{run_key}.json"
    )


def _safe_path(root: Path, relative: str) -> Path:
    normalized = str(relative or "").replace("\\", "/").lstrip("/")
    # Resolve parents for confinement, but preserve the leaf symlink itself.
    # Undo replaces a link; it must never write through it to its referent.
    lexical = Path(os.path.abspath(root / normalized))
    target = lexical.parent.resolve() / lexical.name
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RedesignUndoError(f"Refusing a path outside the selected project: {relative}") from exc
    return target


def _file_state(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        value = os.readlink(path)
        digest = hashlib.sha256(f"symlink:{value}".encode()).hexdigest()
        return {"kind": "symlink", "value": value, "sha256": digest}
    if not path.is_file():
        return {"kind": "missing", "sha256": "missing"}
    payload = path.read_bytes()
    return {
        "kind": "file",
        "data": base64.b64encode(payload).decode("ascii"),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mode": stat.S_IMODE(path.stat().st_mode),
    }


def _git_blob(root: Path, revision: str, relative: str) -> dict[str, Any]:
    """Read an exact repository blob without text decoding or newline conversion."""
    return _git_preimage(root, revision, relative, apply_worktree_filters=False)


def _git_preimage(
    root: Path,
    revision: str,
    relative: str,
    *,
    apply_worktree_filters: bool,
    mode: int | None = None,
) -> dict[str, Any]:
    """Read a pinned blob, optionally reproducing its launch working-tree bytes."""
    if not revision:
        raise RedesignUndoError("No pinned Git revision proves this file's original state.")
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-z", revision, "--", relative],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if listing.returncode != 0:
            raise RedesignUndoError("The pinned Git revision could not be read.")
        if not listing.stdout:
            return {"kind": "missing", "sha256": "missing"}
        command = ["git", "-C", str(root), "show", f"{revision}:{relative}"]
        if apply_worktree_filters and not listing.stdout.startswith(b"120000 "):
            command = [
                "git",
                "-C",
                str(root),
                "cat-file",
                "--filters",
                f"--path={relative}",
                f"{revision}:{relative}",
            ]
        process = subprocess.run(command, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RedesignUndoError("The original Git file could not be read.") from exc
    if process.returncode != 0:
        raise RedesignUndoError("The original Git file could not be read.")
    payload = process.stdout
    if listing.stdout.startswith(b"120000 "):
        value = os.fsdecode(payload)
        return {"kind": "symlink", "value": value, "sha256": hashlib.sha256(f"symlink:{value}".encode()).hexdigest()}
    state = {
        "kind": "file",
        "data": base64.b64encode(payload).decode("ascii"),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if mode is None:
        tree_mode = listing.stdout.split(b" ", 1)[0]
        mode = 0o755 if tree_mode == b"100755" else 0o644
    state["mode"] = mode
    return state


def capture_launch_state(
    root: str | Path,
    initial_snapshot: dict[str, str],
    *,
    catalog_root: str | Path | None = None,
    conversation_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Capture bounded working-file pre-images, including clean checkout bytes."""
    project = Path(root).resolve()
    complete_inventory = forge_code_manifest.is_manifest(initial_snapshot)
    inventory_exclusions: list[str] = []
    if complete_inventory:
        # A manifest excludes dependencies and linked directories. Preserve
        # those boundaries before the run can replace a link with a directory.
        def unreadable(error: OSError) -> None:
            raise RedesignUndoError("The launch snapshot boundaries could not be read.") from error

        seen = {project}
        for here, dirs, files in os.walk(project, onerror=unreadable):
            for name in files:
                leaf = Path(here) / name
                if not forge_code_manifest._inside(project, leaf) or not leaf.is_file():
                    inventory_exclusions.append(leaf.relative_to(project).as_posix())
            kept = []
            for name in dirs:
                directory = Path(here) / name
                if name in forge_code_manifest._SKIP_DIRS or not forge_code_manifest._real_directory(
                    Path(here), name, seen
                ):
                    inventory_exclusions.append(directory.relative_to(project).as_posix())
                else:
                    kept.append(name)
            dirs[:] = kept
    rc, revision, _error = forge_code_git._run_git(project, ["rev-parse", "HEAD"])
    dirty: dict[str, Any] = {}
    total = 0
    dirty_paths = sorted(path for path in (initial_snapshot or {}) if path != forge_code_manifest.MARKER)
    tracked_paths: list[str] = []
    tracked_modes: dict[str, int] = {}
    index_preimages: dict[str, Any] = {}
    clean_capture_complete = True
    working_inventory_complete = complete_inventory
    if not complete_inventory:
        tracked_rc, tracked, _error = forge_code_git._run_git(project, ["ls-files", "-z"])
        working_inventory_complete = tracked_rc == 0
        if tracked_rc == 0:
            tracked_paths = sorted(path for path in tracked.split("\0") if path)
            for relative in tracked_paths:
                path = _safe_path(project, relative)
                if path.is_file() and not path.is_symlink():
                    tracked_modes[relative] = stat.S_IMODE(path.stat().st_mode)
        # Snapshot exact launch bytes now. They are narrowed to touched paths at
        # finalization, but Undo never reconstructs them from Git after the run.
        # This is intentionally bounded: an uncaptured touched file gets an
        # honest disabled Undo rather than a risky checkout.
        for relative in sorted(set(tracked_paths) - set(dirty_paths)):
            path = _safe_path(project, relative)
            if path.is_file() and not path.is_symlink() and path.stat().st_size > _MAX_LAUNCH_DIRTY_BYTES - total:
                clean_capture_complete = False
                continue
            state = _file_state(path)
            size = len(base64.b64decode(state.get("data") or "")) if state.get("kind") == "file" else 0
            if total + size <= _MAX_LAUNCH_DIRTY_BYTES:
                index_preimages[relative] = state
                total += size
            else:
                clean_capture_complete = False
    # Dirty and otherwise uncaptured tracked files still use the remaining bound.
    preimages: dict[str, Any] = {}
    literal_paths = dirty_paths + sorted(set(tracked_paths) - set(dirty_paths) - set(index_preimages))
    for relative in literal_paths:
        path = _safe_path(project, relative)
        if path.is_file() and not path.is_symlink() and path.stat().st_size > _MAX_LAUNCH_DIRTY_BYTES - total:
            continue
        state = _file_state(path)
        size = len(base64.b64decode(state.get("data") or "")) if state.get("kind") == "file" else 0
        if total + size <= _MAX_LAUNCH_DIRTY_BYTES:
            (dirty if relative in dirty_paths else preimages)[relative] = state
            total += size
    # A large unrelated dirty file must not abort the Build run. Its path stays
    # absent, so persist_run_preimages honestly marks Undo unavailable only if
    # this Redesign actually touches that uncaptured file.
    capture = {
        "revision": revision.strip() if rc == 0 else "",
        "dirty": dirty,
        "preimages": preimages,
        "dirty_paths": dirty_paths,
        "tracked_paths": tracked_paths,
        "index_preimages": index_preimages,
        "tracked_modes": tracked_modes,
        "complete_inventory": complete_inventory,
        "working_inventory_complete": working_inventory_complete,
        "clean_capture_complete": clean_capture_complete,
        "inventory_exclusions": inventory_exclusions,
    }
    if catalog_root is not None and conversation_id and run_id:
        path = _manifest_path(catalog_root, conversation_id, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # This conversation-owned record is written synchronously before the
        # Build process starts.  ``captured`` is deliberately not restorable:
        # finalization must first narrow it to the exact files this run wrote
        # and attach their post-run fingerprints.
        _write_manifest(
            path,
            {
                "run_id": run_id,
                "state": "captured",
                "available": False,
                "reason": "This Redesign run has not finished recording its touched files.",
                "launch": capture,
            },
        )
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("state") != "captured" or saved.get("launch") != capture:
            raise RedesignUndoError("The Redesign launch pre-images could not be read back.")
    return capture


def persist_run_preimages(
    project_root: str | Path,
    catalog_root: str | Path,
    conversation_id: str,
    run_id: str,
    changed_files: list[str],
    launch_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Finalize only this run's touched pre-images beside its conversation record."""
    project = Path(project_root).resolve()
    launch = launch_state or {}
    dirty = launch.get("dirty") if isinstance(launch.get("dirty"), dict) else {}
    captured = launch.get("preimages") if isinstance(launch.get("preimages"), dict) else {}
    indexed = launch.get("index_preimages") if isinstance(launch.get("index_preimages"), dict) else {}
    files: dict[str, Any] = {}
    total = 0
    for relative in sorted(set(changed_files or [])):
        # ``missing`` is a valid pre-image and is falsey only by accident if
        # callers provide a dict subclass. Membership, not truthiness, decides
        # whether this run owns exact launch evidence for the path.
        before = captured[relative] if relative in captured else dirty.get(relative)
        if before is None and relative in indexed:
            before = indexed[relative]
        if before is None:
            dirty_paths = launch.get("dirty_paths")
            if not isinstance(dirty_paths, list) or relative in dirty_paths:
                return {
                    "available": False,
                    "reason": f"The original contents of {relative} were not captured; Undo would risk earlier edits.",
                    "run_id": run_id,
                }
            if launch.get("working_inventory_complete") is False:
                return {
                    "available": False,
                    "reason": f"The launch working-file inventory was unavailable for {relative}.",
                    "run_id": run_id,
                }
            if launch.get("complete_inventory") is not True and launch.get("clean_capture_complete") is False:
                return {
                    "available": False,
                    "reason": f"The original contents of {relative} were not captured; Undo would risk earlier edits.",
                    "run_id": run_id,
                }
            if launch.get("complete_inventory") is True:
                parts = Path(relative).parts
                exclusions = launch.get("inventory_exclusions")
                if (
                    not isinstance(exclusions, list)
                    or any(part in forge_code_manifest._SKIP_DIRS for part in parts[:-1])
                    or any(Path(relative) == Path(item) or Path(item) in Path(relative).parents for item in exclusions)
                ):
                    return {
                        "available": False,
                        "reason": f"The launch snapshot did not cover {relative}.",
                        "run_id": run_id,
                    }
                before = {"kind": "missing", "sha256": "missing"}
            else:
                tracked_paths = launch.get("tracked_paths")
                if isinstance(tracked_paths, list) and relative not in tracked_paths:
                    before = {"kind": "missing", "sha256": "missing"}
                else:
                    return {
                        "available": False,
                        "reason": f"The original contents of {relative} were not captured; Undo would risk earlier edits.",
                        "run_id": run_id,
                    }
        after = _file_state(_safe_path(project, relative))
        total += len(base64.b64decode(before.get("data") or "")) if before.get("kind") == "file" else 0
        if total > _MAX_PREIMAGE_BYTES * 2:
            return {
                "available": False,
                "reason": "The touched pre-images are too large to store safely.",
                "run_id": run_id,
            }
        files[relative] = {
            "before": before,
            "after_sha256": after["sha256"],
            "after": {key: value for key, value in after.items() if key != "data"},
        }
    if not files:
        return {"available": False, "reason": "This Redesign run did not write a file.", "run_id": run_id}
    manifest = _manifest_path(catalog_root, conversation_id, run_id)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    _write_manifest(manifest, {"run_id": run_id, "files": files, "state": "ready"})
    return {
        "available": True,
        "reason": "",
        "run_id": run_id,
        "files": sorted(files),
        "file_count": len(files),
        "undone": False,
    }


def stage_run_preimages(
    catalog_root: str | Path,
    conversation_id: str,
    run_id: str,
    preimages: dict[str, Any],
) -> Path:
    """Durably stage exact pre-images beside the conversation before source writes.

    Self-edit candidates already contain the verified source bytes that will be
    replaced. This converts those bytes to the Redesign manifest format and
    writes them before application starts, so a process interruption can never
    leave a source write whose original bytes existed only in memory.
    """
    if not conversation_id or not run_id:
        raise RedesignUndoError("A conversation and run are required for Redesign Undo.")
    if not isinstance(preimages, dict) or not preimages:
        raise RedesignUndoError("No pre-image exists for this Redesign run.")
    files: dict[str, Any] = {}
    total = 0
    for relative in sorted(preimages):
        state = preimages[relative]
        if not isinstance(state, dict) or state.get("kind") not in {"file", "missing", "symlink"}:
            raise RedesignUndoError(f"The pre-image for {relative} is invalid.")
        normalized = str(relative or "").replace("\\", "/")
        if (
            not normalized
            or normalized.startswith("/")
            or Path(normalized).is_absolute()
            or ".." in Path(normalized).parts
        ):
            raise RedesignUndoError(f"Refusing a path outside the selected project: {relative}")
        if state.get("kind") == "file":
            try:
                payload = base64.b64decode(state.get("data") or "", validate=True)
            except (ValueError, TypeError) as exc:
                raise RedesignUndoError(f"The pre-image for {relative} is unreadable.") from exc
            if hashlib.sha256(payload).hexdigest() != state.get("sha256"):
                raise RedesignUndoError(f"The pre-image for {relative} failed readback validation.")
            total += len(payload)
        if total > _MAX_PREIMAGE_BYTES * 2:
            raise RedesignUndoError("The touched pre-images are too large to store safely.")
        files[relative] = {"before": state}
    manifest = _manifest_path(catalog_root, conversation_id, run_id)
    if manifest.exists():
        raise RedesignUndoError("An Undo record already exists for this Redesign run.")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    _write_manifest(manifest, {"run_id": run_id, "files": files, "state": "staged"})
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    if saved.get("run_id") != run_id or saved.get("files") != files or saved.get("state") != "staged":
        raise RedesignUndoError("The Redesign pre-images could not be read back.")
    return manifest


def finalize_staged_preimages(
    project_root: str | Path,
    catalog_root: str | Path,
    conversation_id: str,
    run_id: str,
    changed_files: list[str],
) -> dict[str, Any]:
    """Attach exact post-write evidence to an already staged pre-image record."""
    project = Path(project_root).resolve()
    manifest = _manifest_path(catalog_root, conversation_id, run_id)
    if not manifest.is_file():
        return {"available": False, "reason": "No pre-image exists for this Redesign run.", "run_id": run_id}
    record = json.loads(manifest.read_text(encoding="utf-8"))
    files = record.get("files") if isinstance(record.get("files"), dict) else {}
    touched = sorted(set(changed_files or []))
    if record.get("state") != "staged" or set(files) != set(touched):
        return {
            "available": False,
            "reason": "The staged pre-images do not match the files written by this Redesign run.",
            "run_id": run_id,
        }
    for relative in touched:
        after = _file_state(_safe_path(project, relative))
        files[relative]["after_sha256"] = after["sha256"]
        files[relative]["after"] = {key: value for key, value in after.items() if key != "data"}
    record.update(files=files, state="ready")
    _write_manifest(manifest, record)
    return {
        "available": True,
        "reason": "",
        "run_id": run_id,
        "files": touched,
        "file_count": len(touched),
        "undone": False,
    }


def discard_run_preimages(catalog_root: str | Path, conversation_id: str, run_id: str) -> None:
    """Delete one consumed manifest without touching sibling runs or project files."""
    manifest = _manifest_path(catalog_root, conversation_id, run_id)
    try:
        manifest.unlink(missing_ok=True)
        manifest.parent.rmdir()
    except OSError:
        pass


def _write_manifest(manifest: Path, record: dict[str, Any]) -> None:
    temp = manifest.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(manifest)


def _replace_file(target: Path, payload: bytes, mode: int | None = None) -> None:
    """A locked destination leaves its old bytes intact and is retryable."""
    descriptor, name = tempfile.mkstemp(prefix=".redesign-undo-", dir=target.parent)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            staged.chmod(mode)
        original_mode = stat.S_IMODE(target.stat().st_mode) if target.is_file() and not target.is_symlink() else None
        if original_mode is not None:
            target.chmod(original_mode | stat.S_IWRITE)
        try:
            os.replace(staged, target)
        except OSError:
            if original_mode is not None:
                target.chmod(original_mode)
            raise
    finally:
        if staged.exists():
            staged.chmod(stat.S_IMODE(staged.stat().st_mode) | stat.S_IWRITE)
        staged.unlink(missing_ok=True)


def _same_state(current: dict[str, Any], expected: dict[str, Any], *, recovering: bool = False) -> bool:
    if current.get("sha256") != expected.get("sha256"):
        return False
    if "mode" not in expected:
        return True  # Legacy manifests did not retain permission evidence.
    allowed = {expected["mode"]}
    if recovering:
        allowed.add(expected["mode"] | stat.S_IWRITE)
    return current.get("mode") in allowed


def _replace_symlink(target: Path, value: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".redesign-undo-", dir=target.parent)
    os.close(descriptor)
    staged = Path(name)
    staged.unlink()
    try:
        staged.symlink_to(value)
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)


def restore_run_preimages(
    project_root: str | Path, catalog_root: str | Path, conversation_id: str, run_id: str
) -> list[str]:
    """Restore exactly one Redesign run after proving none of its outputs changed later."""
    from .forge_code_self_edit import SelfEditSnapshotError, source_application_gate

    try:
        with source_application_gate(Path(project_root)):
            return _restore_run_preimages_locked(project_root, catalog_root, conversation_id, run_id)
    except SelfEditSnapshotError as exc:
        raise RedesignUndoError(str(exc)) from exc


def _restore_run_preimages_locked(project_root, catalog_root, conversation_id, run_id) -> list[str]:
    project = Path(project_root).resolve()
    manifest = _manifest_path(catalog_root, conversation_id, run_id)
    if not manifest.is_file():
        raise RedesignUndoError("No pre-image exists for this Redesign run.")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if record.get("undone"):
        return sorted(str(item) for item in (record.get("restored") or []))
    if record.get("state") == "staged":
        raise RedesignUndoError("This Redesign run did not finish recording its source writes; Undo is unavailable.")
    if record.get("state") not in (None, "ready"):
        raise RedesignUndoError("This Redesign Undo record is not ready.")
    files = record.get("files") if isinstance(record.get("files"), dict) else {}
    if not files:
        raise RedesignUndoError("No pre-image exists for this Redesign run.")
    for relative, entry in files.items():
        current = _file_state(_safe_path(project, relative))
        recovering = bool(record.get("restore_started"))
        already_restored = recovering and _same_state(current, entry.get("before") or {}, recovering=True)
        after = entry.get("after") or {"sha256": entry.get("after_sha256")}
        if not _same_state(current, after, recovering=recovering) and not already_restored:
            raise RedesignUndoError(
                f"Undo stopped because {relative} changed after this Redesign. Those later edits were left untouched."
            )
    # Durable before touching files: after an interruption, only exact before
    # or after hashes are accepted. Later edits still fail the same guard.
    record["restore_started"] = True
    _write_manifest(manifest, record)
    restored: list[str] = []
    for relative, entry in files.items():
        target = _safe_path(project, relative)
        before = entry.get("before") or {}
        if _same_state(_file_state(target), before):
            restored.append(relative)
            continue
        kind = before.get("kind")
        if kind == "missing":
            if target.is_file() or target.is_symlink():
                if not target.is_symlink():
                    target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWRITE)
                target.unlink()
        elif kind == "symlink":
            target.parent.mkdir(parents=True, exist_ok=True)
            _replace_symlink(target, str(before.get("value") or ""))
        elif kind == "file":
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = base64.b64decode(str(before.get("data") or ""))
            if "mode" in before:
                _replace_file(target, payload, before["mode"])
            else:
                _replace_file(target, payload)
        else:
            raise RedesignUndoError(f"The saved pre-image for {relative} is invalid.")
        if not _same_state(_file_state(target), before):
            raise RedesignUndoError(f"Undo readback failed for {relative}.")
        restored.append(relative)
    record["undone"] = True
    record["restored"] = sorted(restored)
    record["undone_at"] = dt.datetime.now(dt.UTC).isoformat()
    _write_manifest(manifest, record)
    return sorted(restored)
