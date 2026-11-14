"""A bug in one sweep cycle must not end the monitor, and must not hide.

`run_monitor_cycles` caught only OSError and ValueError, so one KeyError, TypeError
or AttributeError from the sweep ended a loop that is meant to run for days. The
loop now logs the traceback and counts the failure, and raises the fifth failure in
a row so a permanently broken monitor is loud instead of silent.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest
import scripts.crew.tasks.monitor as monitor
import scripts.crew.tasks.sweep as sweep


def _run(tmp_path: Path, cycles: int):
    return monitor.run_monitor_cycles(
        cycles=cycles,
        interval_seconds=0,
        workboard_path=tmp_path / "WORKBOARD.md",
        max_idle_minutes=30.0,
        task_manager_agent="TaskManager",
        now_seed=datetime.fromisoformat("2026-02-25T12:00:00+00:00"),
        require_claims_to_have_active_task=False,
        apply=False,
        sleep=lambda _s: None,
    )


def _script(monkeypatch, outcomes: list) -> list[int]:
    seen: list[int] = []

    def fake(**_kw):
        seen.append(1)
        outcome = outcomes[len(seen) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return True, {"stale_claim_count": 0, "stale_claims": []}

    monkeypatch.setattr(sweep, "_sweep_inactive", fake)
    return seen


@pytest.mark.parametrize("error", [KeyError("agent"), TypeError("bad"), AttributeError("none"), RuntimeError("x")])
def test_any_exception_in_a_cycle_is_logged_and_counted_not_fatal(tmp_path: Path, monkeypatch, caplog, error) -> None:
    _script(monkeypatch, [error, "ok"])
    with caplog.at_level(logging.ERROR, logger=monitor.LOG.name):
        ok, payload = _run(tmp_path, 2)
    assert not ok and payload["cycle_count"] == 2 and payload["failed_cycles"] == 1
    assert type(error).__name__ in str(payload["errors"])
    assert any(record.exc_info for record in caplog.records), "the traceback must be logged"


def test_the_fifth_failure_in_a_row_is_raised(tmp_path: Path, monkeypatch) -> None:
    seen = _script(monkeypatch, [KeyError("k")] * 10)
    with pytest.raises(KeyError):
        _run(tmp_path, 0)
    assert len(seen) == monitor.MAX_CONSECUTIVE_FAILURES == 5


def test_a_good_cycle_resets_the_failure_streak(tmp_path: Path, monkeypatch) -> None:
    pattern = [KeyError("k")] * 4 + ["ok"] + [KeyError("k")] * 4 + ["ok"]
    _script(monkeypatch, pattern)
    ok, payload = _run(tmp_path, len(pattern))
    assert not ok and payload["cycle_count"] == 10 and payload["failed_cycles"] == 8
