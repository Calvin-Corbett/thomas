"""A test run does not write to the roots your own Thomas reads its work out of.

You reported your Build project chooser "full of projects your own tests created", with titles like
"Use browser.open and browser.extract then ...". Those are not projects you asked for. Two stores under a
shared root put them there, and a test that starts a real worker reaches both:

* the task ledger, ``<root>/runtime/coordination/task_bots/`` -- a card in the chooser is built from an
  execution record (``local_projects_generated._generated_deliverable_project`` reads
  ``task_bot_runtime.list_executions``) and named with the run's own prompt (``_request_title``);
* the Build conversation registry, ``<root>/.thomas/evolve/agent/project_registry.json`` -- a code task
  mints a project and binds a conversation to it (``chat_delegation_build_session.open_build_session`` ->
  ``forge_code_conversations.bind_conversation``), and ``GET /api/evolve/agent/conversations`` lists
  whatever that registry names. Redirecting only the ledger left this half open, measured: after the ledger
  fix the checkout's registry still gained an entry per run of
  ``tests/test_chat_delegation_worker_contract.py``.

Neither store is handed the root it uses; both resolve one. ``project_root.resolve_project_root()`` answers
the git root above the current directory, and pytest runs from the checkout. Two earlier fixes went at this
by chasing call sites -- a lint for ``repo_root=Path(".")``, which cannot see a call that passes no root at
all, and ``tests/conftest.py`` moving ``THOMAS_DATA_DIR``/``THOMAS_OWNED_ROOT``, which no more moves the
CHECKOUT than a lint sees an absent argument.

So the stores refuse instead: in a test process, a root that would be a shared one -- the live checkout, or
the Thomas data dir -- becomes a throwaway folder. Reads go through the same redirect, so a test that writes
a record and reads it back still works; it simply cannot reach what your library is built from. A root a
test passed in itself (a ``tmp_path``, the board in a fixture) is left exactly as it is, which is why every
existing fixture still works, and outside a test process nothing is redirected at all.

One stand-in per root, not one per process. ``THOMAS_DATA_DIR`` is exactly the kind of thing a fixture
moves, so "the data dir" is a different folder in different tests -- and a single sandbox for the whole
process made those tests share one ledger, which none of them asked for and none of them would have
outside a test run: a two-test probe showed the second test reading the first test's execution record. The
checkout and the data dir were sharing one too, mixing two stores that are separate on a live Thomas. The
throwaway root is now named after the root it stands in for, so tests that name their own data dirs are as
separate from each other as their roots are.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Set by pytest for the duration of each test; the import is there for the whole process, including
# fixtures and collection, so the two together cover every moment a test can write.
_PYTEST_ENV = "PYTEST_CURRENT_TEST"
_SANDBOX_PREFIX = "thomas-test-sandbox"
# A run killed outright (a crash, a stopped CI job) never reaches the atexit hook below, so a sandbox older
# than this is one no live process owns. A day is far longer than any test run and far shorter than the
# "never" these folders used to be kept for.
_STALE_S = 86_400.0
_cleanup_registered = False


def in_test_run() -> bool:
    """Whether this process is a pytest run.

    ``sys.modules`` as well as the env var, because the env var is only set while a test body is running
    and a fixture writes before that. Nothing a live Thomas imports imports pytest -- checked: every
    ``import pytest`` under ``thomas/`` is inside a test file the server never loads -- so this cannot be
    true in production. If Thomas ever ran pytest inside its own process, the effect would be that the
    verification run's own records went to a sandbox, which is the behaviour wanted anyway.
    """
    return _PYTEST_ENV in os.environ or "pytest" in sys.modules


def shared_roots() -> frozenset[Path]:
    """The roots a live Thomas reads its own work out of, so a test must never write to them.

    Resolved on every call, not cached: ``THOMAS_DATA_DIR`` is exactly the kind of thing a fixture moves,
    and a cache warmed inside one fixture's tmp dir would stop protecting the real data dir for the rest of
    the run -- the failure this exists to prevent, reintroduced by the optimisation. ``resolve_thomas_data_dir``
    only reads the environment; it creates nothing. It is imported here rather than at module scope because
    this module sits under the config it asks.
    """
    found = {Path(__file__).resolve().parents[2]}  # the Thomas checkout this code is running out of
    try:
        from thomas.core.config import resolve_thomas_data_dir

        found.add(Path(resolve_thomas_data_dir()).resolve())
    except (ImportError, OSError, ValueError):
        pass  # no data dir to protect is not a reason to stop protecting the checkout
    return frozenset(found)


def sandbox_root(stands_in_for: str | Path | None = None) -> Path:
    """The throwaway root standing in for ``stands_in_for``, or this process's sandbox folder itself.

    Keyed by pid, so writes and reads agree within a run and two runs never meet, and then by the root being
    stood in for, so two tests that name two different data dirs get two different ledgers -- the same
    separation they would have if neither were redirected. A digest rather than the path itself: the path
    can be longer than a filename may be, and Windows has a total length to stay under as well.

    Removing it is part of the bargain: a sandbox that is only ever created turns one kind of litter (records
    in your checkout) into another (``%TEMP%`` filling with a folder per test run). The first call arms an
    atexit hook for this process's folder -- the whole of it, stand-ins included -- and sweeps whatever
    earlier runs left behind.
    """
    global _cleanup_registered
    root = Path(tempfile.gettempdir()) / f"{_SANDBOX_PREFIX}-{os.getpid()}"
    if not _cleanup_registered:
        _cleanup_registered = True
        atexit.register(discard, root)
        _sweep_stale(root)
    if stands_in_for is None:
        return root
    key = hashlib.sha256(str(stands_in_for).encode("utf-8", "replace")).hexdigest()[:16]
    return root / key


def discard(root: Path) -> None:
    """Remove a sandbox. Never raises: a folder Windows still holds open must not fail the run at exit."""
    shutil.rmtree(root, ignore_errors=True)


def _sweep_stale(keep: Path) -> None:
    """Sandboxes of runs that ended without running their atexit hook, and only those."""
    cutoff = time.time() - _STALE_S
    try:
        found = list(keep.parent.glob(f"{_SANDBOX_PREFIX}-*"))
    except OSError:
        return
    for path in found:
        try:
            if path != keep and path.is_dir() and path.stat().st_mtime < cutoff:
                discard(path)
        except OSError:
            continue  # someone else's sandbox, or one being removed right now


def sandboxed(resolved: str | Path) -> Path:
    """``resolved``, unless a test run is about to write into a root that is not its own.

    The stand-in is named after ``here``, the resolved root, so the same shared root answers the same folder
    for every reader and writer in this process, and a different shared root answers a different one.
    """
    if not in_test_run():
        return Path(resolved)
    try:
        here = Path(resolved).resolve()
    except (OSError, ValueError):
        return Path(resolved)
    return sandbox_root(here) if here in shared_roots() else Path(resolved)


def coordination_root(resolved: str | Path) -> Path:
    """The task ledger's root: :func:`sandboxed`, under the name ``task_bot_runtime`` asks for it by."""
    return sandboxed(resolved)


__all__ = ["coordination_root", "discard", "in_test_run", "sandbox_root", "sandboxed", "shared_roots"]
