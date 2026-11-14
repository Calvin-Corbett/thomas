"""What a test starts without: what an earlier test on its worker left in a store they share."""

from __future__ import annotations

import shutil
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_test_reads_another_tests_board() -> None:
    """Every test starts with the delegation board unread.

    ``chat_delegation_session.board_rows`` memoizes each board by its file
    signature, process-wide. A test that swaps ``list_executions`` for a stub
    never reaches the stub if an earlier test already read the same root --
    test_chat_delegation.py before test_chat_delegation_partial_artifacts.py
    served the live board's rows and the stubbed record went missing. Only a module some test already imported has a
    cache to clear: importing it here cost every test process 1.3 s and 138 modules (2026-10-29).
    """
    if session := sys.modules.get("thomas.server.chat_delegation_session"):
        session.reset_board_cache()


@pytest.fixture(autouse=True)
def _no_test_starts_inside_a_closing_server() -> None:
    """Every test starts with no server generation on record, so ``workers.closing()`` is False.

    ``workers.closing()`` answers for the newest server generation in the process, and that answer outlives the
    generation on purpose: once a server's ``serve_async`` has returned, Python still waits for its threads, and a
    survey still running then must see the server as closing (the 261 s exit of 2026-11-09). A real restart replaces it
    when the next generation starts. A test that ran ``serve_async`` in-process left it set, and every later test on
    the worker that walked a copy or surveyed branches failed with "Thomas is closing" (2026-11-13). Only a module some
    test already imported has a generation to forget.
    """
    if workers := sys.modules.get("thomas.server.precard.workers"):
        workers._newest = None


def forget_other_tests_work(owned_root: Path) -> None:
    """Empty the task ledger and the Build projects every test on this worker shares.

    Pass the folder this test run made for itself. Never read ``owned_root`` from THOMAS_OWNED_ROOT: on a caged Thomas
    that variable names your ~/.thomas, and this deletes what it is given.
    """
    shutil.rmtree(owned_root, ignore_errors=True)
    if sandbox := sys.modules.get("thomas.core.shared_root_sandbox"):
        sandbox.discard(sandbox.sandbox_root())


# The threads the engines ``thomas.core.engine_manager`` starts run on: each engine's poll loop, the cycle it starts
# when idle, and an initiative goal. Each is a prefix of the names the engine gives its threads.
ENGINE_THREAD_NAMES = (
    "thomas-code-issue",
    "thomas-self-upgrade",
    "thomas-ui-workflow",
    "thomas-local-agent",
    "thomas-workspace-sync",
    "thomas-testing",
    "thomas-test-cycle",
    "thomas-initiative",
    "thomas-goal-",
)


def engine_threads() -> list[threading.Thread]:
    """Every engine thread alive in this process, by the names the engines give them."""
    found = [thread for thread in threading.enumerate() if thread.name.startswith(ENGINE_THREAD_NAMES)]
    return sorted(found, key=lambda thread: thread.name)


def stop_engine_threads(*, within_s: float = 30.0) -> list[str]:
    """Stop every engine thread alive now and wait for each to end; fail for one still running after ``within_s``.

    An engine's thread runs one of the engine's own bound methods, so the thread leads back to the engine that owns it,
    whether that is the module's singleton or one the test built itself, and the engine's ``stop()`` is what ends it.
    Every poll loop waits on a stop event, so ``stop()`` wakes it at once; a cycle thread runs to the end of its cycle.
    A thread still alive when the wait is up fails the test that left it, naming the thread, so no test can leave a loop
    running beside the tests after it. Returns the names of the threads it found.
    """
    threads = engine_threads()
    if not threads:
        return []
    for thread in threads:
        owner = getattr(getattr(thread, "_target", None), "__self__", None)
        stop = getattr(owner, "stop", None)
        if callable(stop):
            stop()
    for thread in threads:
        thread.join(timeout=within_s)
    if still_running := [thread.name for thread in threads if thread.is_alive()]:
        pytest.fail(
            f"engine threads still running {within_s:.0f} s after the test ended; the test that started them stops "
            f"them: {still_running}"
        )
    return [thread.name for thread in threads]


@pytest.fixture(autouse=True)
def _nobody_is_waiting_on_the_owner() -> None:
    """Every test starts with no owner wait on record.

    thomas/core/owner_wait.py is process-wide by design: after the owner answers
    a prompt, worker watchdogs measure staleness from that answer. Across tests
    that leaks -- a question-card test just before a watchdog test made a stale
    worker look fresh (test_supervised_agent_worker_fails_stale_first_event_from_web_loop).
    """
    from thomas.core import owner_wait

    owner_wait.reset()


@pytest.fixture(autouse=True)
def _no_engine_thread_outlives_its_test() -> Iterator[None]:
    """An engine loop a test started ends with the test.

    Building a whole app starts the engines, and their poll loops lived on in the worker for the rest of the run. A test
    that patched ``time.sleep`` set them spinning and they starved it (12 s became more than 900). Each poll re-read
    THOMAS_DATA_DIR and wrote into whichever test's folder it named; when that was a project a builder was snapshotting,
    the builder was refused and tests/test_build_agent_scheduler.py hung 900 s until the worker was killed (2026-11-08).
    """
    yield
    stop_engine_threads()


@pytest.fixture(autouse=True)
def _no_saved_anthropic_key_outlives_its_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building the Build routes tells ``coding_agents`` where the app saves your
    Anthropic key, process-wide. A later test must not read an earlier test's app (only one already imported has one)."""
    if coding_agent_builtins := sys.modules.get("thomas.core.coding_agents.builtins"):
        monkeypatch.setattr(coding_agent_builtins, "_stored_key_reader", None)
