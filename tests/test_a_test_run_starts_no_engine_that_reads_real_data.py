"""A pytest run starts no code issue engine, because its timer shells out to a script that reads your real data.

``thomas.core.code_issue_engine`` starts a thread whose cycle runs ``scripts/heartbeat.py``. Any test that builds a whole
app starts it, and the thread outlives the test. Once the run had gone on for the engine's idle time the thread spawned
that script with the real home folder, which opened your real Work file, and the run failed on the real-data tripwire
in whichever test happened to be running (2026-11-03: three landings in a row, each naming a different test).
``tests/conftest.py`` turns the engine off for every run; a test that wants it sets the switch itself.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import os

from thomas.core import code_issue_engine


def test_the_switch_is_off_for_a_test_run() -> None:
    assert os.environ["THOMAS_CODE_ISSUE_ENGINE_ENABLED"] == "0"


def test_an_engine_built_in_a_test_run_does_not_start_a_thread() -> None:
    engine = code_issue_engine.CodeIssueEngine()
    engine.start()
    assert engine.status_snapshot()["running"] is False
    assert engine._thread is None
