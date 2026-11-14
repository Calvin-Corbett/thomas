"""Two conversations bound at the same moment both keep their row.

Binding is read the registry, add one row, write the registry. With nothing
between the read and the write, two binds running at once can each read the
same file, each add their own row, and each write a file that holds only their
own addition -- the second write erases the first's row. A conversation whose
row is gone has lost its project: every later read of it falls back to the
catalog root and comes back empty.

The park list in ``thomas.server.autopilot_park`` already keeps the same shape
safe with one lock around each read-modify-write, taken by every writer in the
process and by any other server's process through a file beside the list. The
registry follows that pattern, and this test is the proof: run it against the
unlocked functions and rows go missing.
"""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_conversations as conversations
from thomas.forge.anvil import forge_code_projects
from thomas.forge.anvil.forge_code_git import _run_git

ROUNDS = 150
PREFIXES = ("left", "right")


def _repo(path: Path) -> Path:
    path.mkdir()
    _run_git(path, ["init"])
    return path.resolve()


def _bind_many(catalog: Path, project: Path, prefix: str, failures: list[Exception]) -> None:
    # What a bind can raise: the lock's 10 s wait ran out or the file would not write (OSError), the
    # registry would not parse (ValueError), or the project was refused. Anything else kills the
    # thread, and the missing rows fail the test on the main thread.
    try:
        for index in range(ROUNDS):
            conversations.bind_conversation(catalog, f"{prefix}-{index}", project)
    except (OSError, ValueError, forge_code_projects.ForgeCodeProjectError) as exc:
        failures.append(exc)


def _run_two_binders(catalog: Path, project: Path) -> set[str]:
    failures: list[Exception] = []
    threads = [
        threading.Thread(target=_bind_many, args=(catalog, project, prefix, failures), name=f"binder-{prefix}")
        for prefix in PREFIXES
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not [t for t in threads if t.is_alive()], "a binder never finished"
    if failures:
        raise failures[0]
    return set(conversations._load_registry(catalog, strict=True))


def _expected() -> set[str]:
    return {f"{prefix}-{index}" for prefix in PREFIXES for index in range(ROUNDS)}


def test_two_binds_at_once_keep_every_row(tmp_path: Path) -> None:
    catalog = _repo(tmp_path / "catalog")
    project = _repo(tmp_path / "project")

    survivors = _run_two_binders(catalog, project)

    lost = _expected() - survivors
    assert not lost, f"{len(lost)} of {2 * ROUNDS} bound conversations lost their row: {sorted(lost)[:5]}"
    for cid in _expected():
        assert forge_code_projects.conversation_project(catalog, cid) == project


def test_without_the_lock_two_binds_lose_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: the same binders with the lock taken out drop rows.

    This keeps the test above honest. A race that no longer shows without the
    lock would mean the test above passes for a reason other than the lock, and
    this test would start failing instead of the fix silently losing its proof.
    """

    @contextlib.contextmanager
    def no_lock(_catalog_root):
        yield

    monkeypatch.setattr(conversations, "_registry_lock", no_lock)
    catalog = _repo(tmp_path / "catalog")
    project = _repo(tmp_path / "project")

    survivors = _run_two_binders(catalog, project)

    assert _expected() - survivors, "the race did not show without the lock; the test above proves nothing now"


def test_every_registry_write_happens_under_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind, settings update, forget and the task-folder rename all write inside the lock."""
    catalog = _repo(tmp_path / "catalog")
    project = _repo(tmp_path / "project")
    conversations.bind_conversation(catalog, "c-1", project)

    held: list[bool] = []
    depth = {"n": 0}
    real_lock = conversations._registry_lock
    real_write = conversations._write_registry

    @contextlib.contextmanager
    def counting_lock(catalog_root):
        with real_lock(catalog_root):
            depth["n"] += 1
            try:
                yield
            finally:
                depth["n"] -= 1

    def recording_write(catalog_root, registry):
        held.append(depth["n"] > 0)
        real_write(catalog_root, registry)

    monkeypatch.setattr(conversations, "_registry_lock", counting_lock)
    monkeypatch.setattr(conversations, "_write_registry", recording_write)

    conversations.bind_conversation(catalog, "c-2", project)
    conversations.update_conversation_settings(catalog, "c-1", {"model": "x"})
    conversations.forget_conversation(catalog, "c-2")
    conversations.rebind_project_root(catalog, "c-1", project / "elsewhere")

    assert held == [True, True, True, True]
    assert conversations.conversation_metadata(catalog, "c-1")["project_root"] == str(project / "elsewhere")
