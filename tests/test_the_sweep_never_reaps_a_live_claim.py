"""The dead-claim sweep must not take a claim that is provably live.

Measured 2026-10-03: a claim made just now by an agent whose last board message
was three days old read as `agent_activity_timeout` (4320 minutes) and would have
been reaped on the next cycle. `claimed_at` and the presence heartbeat are timing
evidence the sweep ignored.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scripts.crew.tasks.claim_liveness as liveness
import scripts.crew.tasks.sweep as sweep

NOW = datetime(2026, 2, 25, 12, 0, tzinfo=timezone.utc)
AGENT = "Codex Offline"
OLD_MESSAGE = NOW - timedelta(days=3)


def _board(tmp_path: Path, claimed_at: datetime | None) -> Path:
    stamp = f"; claimed_at={claimed_at.isoformat()}" if claimed_at else ""
    text = f"""# Thomas Workboard

## Agent Claims (Active)

- agent={AGENT}; scope=thomas/cli/main.py; task=[WIP] lane{stamp}

## Active Tasks

- task_id=lane; agent={AGENT}; scope=thomas/cli/main.py; summary=[WIP] lane; status=active

## Issues / Blockers

- none

## Up For Grabs

- none

## Supporting Docs (Not Plan Sources)

- docs/PROJECT_SCOPE.md
"""
    board = tmp_path / "WORKBOARD.md"
    board.write_text(text, encoding="utf-8")
    return board


def _stale(board: Path, monkeypatch, presence_dir: Path | None = None) -> tuple[list, list]:
    monkeypatch.setattr(sweep, "_latest_message_timestamp_by_sender", lambda **_k: {AGENT.casefold(): OLD_MESSAGE})
    monkeypatch.setattr(sweep, "_line_commit_unix", lambda *_a, **_k: int(OLD_MESSAGE.timestamp()))
    spared: list = []
    violations, stale, _tasks = sweep._stale_claims(
        workboard_path=board,
        now=NOW,
        max_idle_minutes=30.0,
        require_claims_to_have_active_task=False,
        presence_dir=presence_dir,
        spared=spared,
    )
    assert not violations, violations
    return stale, spared


def _session(folder: Path, agent: str, beat: datetime, state: str = "active") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    row = {"session_id": "s1", "agent_id": agent, "last_heartbeat_at": beat.isoformat(), "state": state}
    (folder / "s1.json").write_text(json.dumps(row), encoding="utf-8")


def test_a_claim_made_just_now_is_not_stale_over_a_three_day_old_message(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, NOW - timedelta(minutes=1))
    stale, spared = _stale(board, monkeypatch)
    assert stale == []
    assert [row["spared_because"] for row in spared] == ["claim_younger_than_floor"]


def test_a_claim_older_than_the_floor_with_an_old_message_is_stale(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, NOW - timedelta(hours=30))
    stale, spared = _stale(board, monkeypatch)
    assert [row["issue"] for row in stale] == ["agent_activity_timeout"]
    assert spared == []


def test_a_claim_with_no_claimed_at_gets_no_floor(tmp_path: Path, monkeypatch) -> None:
    stale, _spared = _stale(_board(tmp_path, None), monkeypatch)
    assert len(stale) == 1


def test_a_recent_heartbeat_spares_the_claim(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, NOW - timedelta(days=2))
    folder = tmp_path / "presence"
    _session(folder, AGENT.upper(), NOW - timedelta(minutes=5))
    stale, spared = _stale(board, monkeypatch, folder)
    assert stale == [] and spared[0]["spared_because"] == "recent_heartbeat"


def test_a_stale_closed_or_foreign_heartbeat_does_not_spare_it(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, NOW - timedelta(days=2))
    folder = tmp_path / "presence"
    for agent, beat, state in (
        (AGENT, NOW - timedelta(minutes=90), "active"),
        (AGENT, NOW - timedelta(minutes=1), "closed"),
        ("someone-else", NOW - timedelta(minutes=1), "active"),
    ):
        _session(folder, agent, beat, state)
        stale, spared = _stale(board, monkeypatch, folder)
        assert len(stale) == 1 and spared == [], (agent, beat, state)


def test_a_failing_liveness_check_spares_the_claim(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, NOW - timedelta(days=2))

    def boom(*_a, **_k):
        raise OSError("board unreadable")

    monkeypatch.setattr(liveness, "declared_unix_for_agent", boom)
    stale, spared = _stale(board, monkeypatch)
    assert stale == [] and spared[0]["spared_because"] == "liveness_check_failed"


def test_the_claim_is_found_by_agent_id_when_lines_shift(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, NOW - timedelta(minutes=1))
    text = board.read_text(encoding="utf-8")
    other = "- agent=Someone Else; scope=docs/x.md; task=other; claimed_at=2020-01-01T00:00:00+00:00\n"
    board.write_text(text.replace("- agent=" + AGENT, other + "- agent=" + AGENT, 1), encoding="utf-8")
    assert liveness.declared_unix_for_agent(board, AGENT) == int((NOW - timedelta(minutes=1)).timestamp())
    assert liveness.declared_unix_for_agent(board, "nobody") is None


def test_an_inactive_agents_row_is_not_a_claim(tmp_path: Path) -> None:
    board = tmp_path / "WORKBOARD.md"
    board.write_text("- agent=A; state=inactive; claimed_at=2020-01-01T00:00:00+00:00\n", encoding="utf-8")
    assert liveness.declared_unix_for_agent(board, "A") is None


def test_an_unreadable_or_empty_board_spares_the_claim(tmp_path: Path) -> None:
    for board in (tmp_path / "missing.md", tmp_path / "empty.md"):
        if board.name == "empty.md":
            board.write_text("", encoding="utf-8")
        reason = liveness.live_reason(
            workboard_path=board, line_no=5, agent=AGENT, now=NOW, max_idle_minutes=30.0, presence_dir=None
        )
        assert reason == "liveness_check_failed", board.name
