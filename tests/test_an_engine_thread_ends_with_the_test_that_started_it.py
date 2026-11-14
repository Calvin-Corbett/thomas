"""An engine thread a test starts is gone when that test ends, and a test that cannot stop one fails.

The engines ``thomas.core.engine_manager`` starts each run a poll loop on a daemon thread. Any test that built a whole
app started them, and the loops outlived the test for the rest of the worker: a test that patched ``time.sleep`` set
them spinning and was starved past 900 s, and each poll re-read THOMAS_DATA_DIR and wrote into whichever test's folder
it named, where a builder snapshotting that project was refused and its test hung until the worker was killed.

``tests/conftest.py`` stops every engine thread when its test ends, through ``tests.between_tests.stop_engine_threads``.
That can only work because each loop waits on a stop event: before, a stopped loop stayed alive until its next poll, up
to an hour away, so nothing could wait for it.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

from tests.between_tests import ENGINE_THREAD_NAMES, engine_threads, stop_engine_threads
from thomas.core import testing_suite
from thomas.core.self_upgrade_engine import SelfUpgradeEngine

ROOT = Path(__file__).resolve().parents[1]
# The modules whose engines the manager starts on a thread of their own.
ENGINE_MODULES = (
    "code_issue_engine",
    "self_upgrade_engine",
    "ui_workflow_engine",
    "local_agent_engine",
    "workspace_sync_engine",
    "testing_suite",
    "initiative",
)
THREAD_NAME = re.compile(r"""name=f?["'](thomas-[a-z-]+)""")


def _names() -> list[str]:
    return [thread.name for thread in engine_threads()]


def test_no_engine_thread_from_an_earlier_test_is_running() -> None:
    assert _names() == []


def test_the_stop_runs_after_every_test(request: pytest.FixtureRequest) -> None:
    assert "_no_engine_thread_outlives_its_test" in request.fixturenames


def test_a_started_loop_is_gone_long_before_its_next_poll() -> None:
    suite = testing_suite.TestingSuite()  # polls every 60 s
    upgrades = SelfUpgradeEngine(poll_interval_s=3600)
    upgrades._enabled = True
    suite.start()
    upgrades.start()
    assert _names() == ["thomas-self-upgrade", "thomas-testing"]

    began = time.monotonic()
    stopped = stop_engine_threads()
    took = time.monotonic() - began

    assert stopped == ["thomas-self-upgrade", "thomas-testing"]
    assert _names() == [], "both threads have ended"
    assert took < 5, f"stopping waited {took:.1f} s for a poll"
    assert suite._thread is not None and not suite._thread.is_alive()
    assert upgrades._thread is not None and not upgrades._thread.is_alive()


def test_a_stopped_engine_starts_again() -> None:
    engine = SelfUpgradeEngine(poll_interval_s=3600)
    engine._enabled = True
    engine.start()
    stop_engine_threads()
    engine.start()
    assert _names() == ["thomas-self-upgrade"]
    assert stop_engine_threads() == ["thomas-self-upgrade"]
    assert _names() == []


def test_a_thread_that_will_not_stop_fails_the_test_that_left_it() -> None:
    let_go = threading.Event()
    thread = threading.Thread(target=let_go.wait, name="thomas-testing", daemon=True)
    thread.start()
    try:
        with pytest.raises(pytest.fail.Exception, match="thomas-testing"):
            stop_engine_threads(within_s=0.2)
    finally:
        let_go.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize("module", ENGINE_MODULES)
def test_every_thread_an_engine_starts_is_named_here(module: str) -> None:
    source = (ROOT / "thomas" / "core" / f"{module}.py").read_text(encoding="utf-8")
    names = THREAD_NAME.findall(source)
    assert names, f"{module} names its threads"
    unlisted = [name for name in names if not name.startswith(ENGINE_THREAD_NAMES)]
    assert unlisted == [], f"add to ENGINE_THREAD_NAMES in tests/between_tests.py: {unlisted}"


@pytest.mark.parametrize("module", ENGINE_MODULES)
def test_every_engine_loop_waits_on_its_stop_event(module: str) -> None:
    """A loop that sleeps cannot be stopped before its next poll, so the stop above would wait for it."""
    source = (ROOT / "thomas" / "core" / f"{module}.py").read_text(encoding="utf-8")
    loop = re.search(r"def _(?:poll_)?loop\(self\) -> None:\n(.*?)\n    def ", source, re.S)
    assert loop is not None, f"{module} has a loop"
    assert "time.sleep(" not in loop.group(1), f"{module}'s loop sleeps through its poll instead of waiting on stop"
    assert "self._stopping.wait(" in loop.group(1)
