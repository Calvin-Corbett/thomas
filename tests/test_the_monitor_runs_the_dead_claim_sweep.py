"""`manager.py --monitor` must actually sweep dead claims.

Measured 2026-10-03: `--sweep-inactive` had no caller outside tests and docs.
`--monitor` (spawned as a persistent loop by `bootstrap_claim`) ended in
`messages._monitor_loop`, a stub returning `{"cycle_count": n}`, so a claim whose
agent died stayed on the board forever.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
import scripts.crew.tasks.manager as mod
import scripts.crew.tasks.monitor as monitor
import scripts.crew.tasks.sweep as sweep

CLAIM = "- agent=Codex Offline; scope=thomas/cli/main.py; task=[WIP] models lane"
TASK = "- task_id=models-lane; agent=Codex Offline; scope=thomas/cli/main.py; summary=[WIP] models lane; status=active"
BOARD = f"""# Thomas Workboard

## Agent Claims (Active)

{CLAIM}

## Active Tasks

{TASK}

## Issues / Blockers

- none

## Up For Grabs

- none

## Supporting Docs (Not Plan Sources)

- docs/PROJECT_SCOPE.md
"""
OLD = 1771846200  # 2026-02-23: far older than the 1 minute threshold at NOW
NOW = "2026-02-25T12:00:00+00:00"


@pytest.fixture(autouse=True)
def _fresh_blame_cache():
    monitor._BLAME_CACHE.clear()
    yield
    monitor._BLAME_CACHE.clear()


def _run(tmp_path: Path, capsys, *extra: str) -> tuple[int, dict]:
    board = tmp_path / "WORKBOARD.md"
    rc = mod.run(
        [
            "--workboard",
            str(board),
            "--monitor",
            "--max-idle-minutes",
            "1",
            "--task-manager-agent",
            "TaskManager",
            "--plan-root",
            str(tmp_path / "plans"),
            "--problem-root",
            str(tmp_path / "problems"),
            "--now",
            NOW,
            "--cycles",
            "1",
            "--json",
            *extra,
        ]
    )
    return rc, json.loads(capsys.readouterr().out)


def _setup(tmp_path: Path, monkeypatch, blame) -> Path:
    board = tmp_path / "WORKBOARD.md"
    board.write_text(BOARD, encoding="utf-8")
    monkeypatch.setattr(sweep, "_line_commit_unix", blame)
    return board


def test_monitor_apply_reclaims_a_dead_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    """The load-bearing case: the stub left the claim on the board."""
    board = _setup(tmp_path, monkeypatch, lambda *_a, **_k: OLD)
    rc, payload = _run(tmp_path, capsys, "--apply", "--only", "Codex Offline")
    text = board.read_text(encoding="utf-8")
    assert rc == 0, payload
    assert payload["stale_claim_count"] == 1
    assert payload["moved_task_ids"] == ["models-lane"], payload
    assert CLAIM not in text
    assert "task_id=models-lane; agent=Codex Offline;" not in text


def test_monitor_without_apply_only_reports(tmp_path: Path, monkeypatch) -> None:
    board = _setup(tmp_path, monkeypatch, lambda *_a, **_k: OLD)
    before = board.read_text(encoding="utf-8")
    ok, payload = monitor.run_monitor_cycles(
        cycles=1,
        interval_seconds=0,
        workboard_path=board,
        max_idle_minutes=1.0,
        task_manager_agent="TaskManager",
        now_seed=datetime.fromisoformat(NOW),
        require_claims_to_have_active_task=False,
        apply=False,
    )
    assert ok, payload
    assert payload["stale_claim_count"] == 1
    assert payload["moved_task_ids"] == []
    assert board.read_text(encoding="utf-8") == before, "a report-only monitor must not touch the board"


def test_monitor_never_reaps_a_claim_with_no_timing_evidence(tmp_path: Path, monkeypatch, capsys) -> None:
    """A claim written a second ago on a board git cannot blame reads as stale; do not take it."""
    board = _setup(tmp_path, monkeypatch, lambda *_a, **_k: None)
    rc, payload = _run(tmp_path, capsys, "--apply", "--only", "Codex Offline")
    assert rc == 0, payload
    assert payload["held_back_no_evidence"] == ["Codex Offline"]
    assert payload["moved_task_ids"] == []
    assert CLAIM in board.read_text(encoding="utf-8")


def test_cycles_sweep_each_time_and_sleep_between_only(tmp_path: Path, monkeypatch) -> None:
    calls: list[bool] = []
    sleeps: list[float] = []

    def fake(**kw):
        calls.append(bool(kw["apply"]))
        return True, {"stale_claim_count": 0, "stale_claims": []}

    monkeypatch.setattr(sweep, "_sweep_inactive", fake)
    ok, payload = monitor.run_monitor_cycles(
        cycles=3,
        interval_seconds=7.0,
        workboard_path=tmp_path / "WORKBOARD.md",
        max_idle_minutes=30.0,
        task_manager_agent="TaskManager",
        now_seed=None,
        require_claims_to_have_active_task=False,
        apply=True,
        only=frozenset({"codex offline"}),
        sleep=sleeps.append,
    )
    assert ok and payload["cycle_count"] == 3
    assert calls == [False, False, False], "nothing stale: only the read-only pass runs"
    assert sleeps == [7.0, 7.0]


def test_one_bad_cycle_does_not_end_the_loop(tmp_path: Path, monkeypatch) -> None:
    seen: list[int] = []

    def fake(**_kw):
        seen.append(1)
        if len(seen) == 1:
            raise OSError("board busy")
        return True, {"stale_claim_count": 0, "stale_claims": []}

    monkeypatch.setattr(sweep, "_sweep_inactive", fake)
    ok, payload = monitor.run_monitor_cycles(
        cycles=2,
        interval_seconds=0,
        workboard_path=tmp_path / "WORKBOARD.md",
        max_idle_minutes=30.0,
        task_manager_agent="TaskManager",
        now_seed=None,
        require_claims_to_have_active_task=False,
        apply=False,
        sleep=lambda _s: None,
    )
    assert payload["cycle_count"] == 2
    assert not ok and "board busy" in str(payload["errors"])
    assert payload["failed_cycles"] == 1
