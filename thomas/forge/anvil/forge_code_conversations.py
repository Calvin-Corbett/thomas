"""Which project each Code conversation belongs to: the conversation registry.

Split out of forge_code_projects.py, which had passed 900 lines and so could not
be changed at all under the monolith guard. Every name here still resolves as
``forge_code_projects.<name>`` (that module's ``__getattr__``), so no caller moved.
Project validation stays in forge_code_projects and is looked up at call time, so
a test that patches ``forge_code_projects.validate_project_root`` still reaches it.
"""

from __future__ import annotations

import contextlib
import json
import os
import pickle
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from thomas.core import atomic_json
from thomas.forge.anvil import forge_code_projects as _projects

# How long a memoized root list stays usable when the registry has not changed.
_ROOTS_TTL_S = 15.0
_roots_lock = threading.Lock()
# catalog_root -> (registry signature, monotonic stamp, roots)
_roots_cache: dict[str, tuple[tuple[int, int], float, list[Path]]] = {}
# registry path -> (file signature, the parsed registry as pickle bytes). Every lookup parsed the whole registry:
# 536 rows, 1.37 MB, 27.7 ms each, from 23 call sites (measured 2026-11-06, the server reading ~1 GB every 2 min).
# A copy unpickled from the cached bytes is just as independent of every other caller's and took 8.8 ms. The bytes
# are only ever made here, in this process, from a registry json.loads just produced; they are never written to or
# read from disk, so no outside data is ever unpickled.
_parsed_lock = threading.Lock()
_parsed_cache: dict[str, tuple[tuple[int, int], bytes]] = {}

# Every read-modify-write of the registry runs under this; see _registry_lock.
_lock = threading.Lock()


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _registry_path(catalog_root: str | Path) -> Path:
    """Where this catalog's registry lives -- the one place every read and write of it goes through.

    ``shared_root_sandbox``: a test process that would write this registry into the live checkout or your
    data dir writes it into a throwaway folder instead, and reads it back from there. Measured: a code task
    dispatched from chat mints a project and binds its conversation here
    (``chat_delegation_build_session.open_build_session``), so one run of
    ``tests/test_chat_delegation_worker_contract.py`` used to add its own prompt to the list
    ``GET /api/evolve/agent/conversations`` answers. A catalog a caller named itself is untouched, and
    outside a test process nothing is redirected.
    """
    from thomas.core.shared_root_sandbox import sandboxed

    directory = sandboxed(catalog_root) / ".thomas" / "evolve" / "agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "project_registry.json"


def _load_registry(catalog_root: str | Path, *, strict: bool = False) -> dict[str, dict[str, Any]]:
    """This catalog's registry, a copy of its own for each caller; parsed again only when the file changed."""
    path = _registry_path(catalog_root)
    key, before = str(path), _signature(path)
    if before is not None:
        with _parsed_lock:
            hit = _parsed_cache.get(key)
        if hit is not None and hit[0] == before:
            return pickle.loads(hit[1])
    registry = _parse_registry(path, strict=strict)
    if before is not None and _signature(path) == before:  # unchanged while it was read: the bytes match the file
        with _parsed_lock:
            _parsed_cache[key] = (before, pickle.dumps(registry, protocol=pickle.HIGHEST_PROTOCOL))
    return registry


def _parse_registry(path: Path, *, strict: bool) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(atomic_json.read_text_with_retry(path))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        if strict:
            raise
        return {}
    if not isinstance(payload, dict):
        if strict:
            raise ValueError("conversation registry must be an object")
        return {}
    return {str(cid): row for cid, row in payload.items() if isinstance(row, dict)}


@contextlib.contextmanager
def _registry_lock(catalog_root: str | Path) -> Iterator[None]:
    """This process's lock, then a lock on a file beside the registry, which another server's process also takes.

    Binding is read the registry, add a row, write it back. Two binds at once with nothing between the read and
    the write each read the same file, each add their own row, and the second write erases the first's row --
    a conversation that has lost its project. Measured with two threads binding 150 conversations each: 153 of
    the 300 rows were gone (``tests/test_two_binds_at_once_keep_both_rows.py``). Same shape, same cure as the
    Autopilot park list in ``thomas.server.autopilot_park._parks_lock``.
    """
    path = _registry_path(catalog_root).with_suffix(".lock")
    with _lock, open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # waits up to 10 s, then raises OSError
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _write_registry(catalog_root: str | Path, registry: dict[str, dict[str, Any]]) -> None:
    """Replace the registry file. Callers that first read it hold ``_registry_lock`` across both."""
    path = _registry_path(catalog_root)
    temporary = atomic_json.temp_path_for(path)  # a fixed name was one file for every writer
    try:
        temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        atomic_json._replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    # The only writer, so the only place the memoized root list must be dropped.
    # The file signature would catch this too, but not if two writes land inside
    # one filesystem timestamp tick at the same size.
    reset_conversation_roots_cache()


def bind_conversation(
    catalog_root: str | Path,
    conversation_id: str,
    project_root: str | Path,
    *,
    settings: dict[str, Any] | None = None,
    allow_without_history: bool = False,
) -> dict[str, Any]:
    """Persist the selected repository and settings for one Code conversation.

    ``allow_without_history`` has to be threaded through: the caller has already
    resolved the root and, for a folder opened deliberately without undo, this
    second validation would otherwise reject what was just accepted.
    """

    cid = str(conversation_id or "").strip()
    if not cid:
        raise _projects.ForgeCodeProjectError("conversation_id is required")
    root = _projects.validate_project_root(
        project_root,
        fallback=catalog_root,
        allow_without_history=allow_without_history,
    )
    row = {"project_root": str(root), "settings": dict(settings or {})}
    with _registry_lock(catalog_root):
        registry = _load_registry(catalog_root)
        registry[cid] = row
        _write_registry(catalog_root, registry)
    # Binding is the moment Thomas commits to writing its bookkeeping under
    # this root (conversation transcripts land in <root>/.thomas/...), so it is
    # the moment to keep that bookkeeping out of the project's git status.
    _projects.shield_thomas_dir(root)
    return dict(row)


def update_conversation_settings(
    catalog_root: str | Path,
    conversation_id: str,
    settings: dict[str, Any],
) -> dict[str, Any] | None:
    with _registry_lock(catalog_root):
        registry = _load_registry(catalog_root)
        row = registry.get(str(conversation_id or ""))
        if row is None:
            return None
        row["settings"] = dict(settings)
        _write_registry(catalog_root, registry)
    return dict(row)


def rebind_project_root(catalog_root: str | Path, conversation_id: str, project_root: str | Path) -> bool:
    """Point an existing row at a moved project folder; False when the conversation has no row.

    The root is taken as given: the caller has just renamed the folder itself, so the usual
    validation would only re-resolve a path it already holds.
    """
    with _registry_lock(catalog_root):
        registry = _load_registry(catalog_root)
        row = registry.get(str(conversation_id or ""))
        if row is None:
            return False
        row["project_root"] = str(project_root)
        _write_registry(catalog_root, registry)
    return True


def conversation_registry(catalog_root: str | Path) -> dict[str, dict[str, Any]]:
    """Read the whole registry once for a single project listing; do not cache it between listings."""
    return _load_registry(catalog_root)


def conversation_metadata(catalog_root: str | Path, conversation_id: str) -> dict[str, Any] | None:
    row = _load_registry(catalog_root).get(str(conversation_id or ""))
    return dict(row) if row is not None else None


def conversation_project(catalog_root: str | Path, conversation_id: str) -> Path:
    """Return a validated bound project, falling back for legacy conversations."""

    row = conversation_metadata(catalog_root, conversation_id)
    selected = row.get("project_root") if row else catalog_root
    return _projects.validate_project_root(selected, fallback=catalog_root)


def _registry_signature(catalog_root: str | Path) -> tuple[int, int]:
    """(mtime_ns, size) of the registry file -- "" as (0, 0) when it is absent.

    The whole answer of :func:`conversation_roots` is derived from this one file,
    so its signature is the only thing that has to be re-read to know whether a
    cached answer is still the current one.
    """
    try:
        stat = _registry_path(catalog_root).stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


def reset_conversation_roots_cache() -> None:
    """Forget every memoized root list. For tests, and for a caller that moved a folder."""
    with _roots_lock:
        _roots_cache.clear()
    with _parsed_lock:
        _parsed_cache.clear()


def conversation_roots(catalog_root: str | Path) -> list[Path]:
    """Return unique, still-valid roots that may hold Code conversations.

    Memoized on the registry file's signature and a short TTL. Measured
    2026-09-24: 213 registered roots cost 433-505 ms per call, every call
    resolving and stat-ing folders that had not moved, and a single chat turn
    asks for this list four times -- half a second of the server's only thread
    per message, for an answer that changes only when a conversation is bound.

    The TTL is what covers the one thing the signature cannot see: a project
    folder deleted on disk without the registry being rewritten. A stale extra
    root is harmless to every caller (the conversation file simply is not in it),
    so bounded staleness is the right trade against re-deriving a constant.
    """
    key = str(catalog_root)
    signature = _registry_signature(catalog_root)
    now = time.monotonic()
    with _roots_lock:
        cached = _roots_cache.get(key)
    if cached is not None and cached[0] == signature and now - cached[1] < _ROOTS_TTL_S:
        return list(cached[2])

    roots: list[Path] = []
    candidates: list[str | Path] = [catalog_root]
    candidates.extend(
        row.get("project_root", "") for row in _load_registry(catalog_root).values() if row.get("project_root")
    )
    for candidate in candidates:
        try:
            root = _projects.validate_project_root(candidate, fallback=catalog_root)
        except _projects.ForgeCodeProjectError:
            continue
        if root not in roots:
            roots.append(root)
    with _roots_lock:
        _roots_cache[key] = (signature, now, list(roots))
    return roots


def resolve_conversation_root(catalog_root: str | Path, conversation_id: str) -> Path:
    """The root a conversation's file is ACTUALLY in, not the one it is filed under.

    ``conversation_project`` answers from the registry, and falls back to the
    catalog root when a conversation has no row. Plenty have none -- they were
    written straight into a project by a path that never called
    ``bind_conversation`` -- so that fallback names a folder the file is not in,
    and every read through it comes back empty.

    An empty read is the dangerous part: it is indistinguishable from "this
    conversation has nothing in it", so callers treat it as a fact rather than a
    miss. Measured on this workspace, the CLI's multi-turn history did exactly
    that -- ``history_turns(repo_root, cid)`` returned 0 turns for **110 of 113**
    conversations that have real turns, and the caller's own comment described
    the empty result as the normal no-history case.

    So this checks the binding first and then walks the same roots the Code
    history endpoint walks. The conversation id itself is the check: a root that
    does not hold the file is skipped, and if none does, the binding is returned
    unchanged so the caller's own not-found handling still runs.
    """

    catalog = Path(catalog_root)
    bound = conversation_project(catalog, conversation_id)
    if not conversation_id:
        return bound
    if _conversation_file(bound, conversation_id).is_file():
        return bound
    for root in conversation_roots(catalog):
        if root != bound and _conversation_file(root, conversation_id).is_file():
            return root
    return bound


def _conversation_file(root: Path, conversation_id: str) -> Path:
    """Where a conversation's JSON lives under ``root``.

    Kept beside the resolver rather than imported from ``forge_code_store``:
    this module sits UNDER the store in the import order, and reaching upward
    for one path join would invert that for no benefit. The layout is asserted
    against the store's own resolver in
    ``tests/test_forge_code_projects.py`` so the two cannot drift apart.
    """

    return Path(root) / ".thomas" / "evolve" / "agent" / "conversations" / f"{conversation_id}.json"


def forget_conversation(catalog_root: str | Path, conversation_id: str) -> None:
    with _registry_lock(catalog_root):
        registry = _load_registry(catalog_root)
        if registry.pop(str(conversation_id or ""), None) is not None:
            _write_registry(catalog_root, registry)


NAMES = frozenset(
    {
        "_registry_path",
        "_load_registry",
        "_write_registry",
        "bind_conversation",
        "update_conversation_settings",
        "rebind_project_root",
        "conversation_metadata",
        "conversation_project",
        "conversation_roots",
        "reset_conversation_roots_cache",
        "resolve_conversation_root",
        "_conversation_file",
        "forget_conversation",
    }
)
