"""`--apply` reaps only the claims it is told to, says honestly what happened, and never repeats itself.

Measured 2026-10-03 on a copy of the real board: one unattended `--monitor --apply`
cycle reaped both stale claims, reported two failures for claims that were gone
(the presence gate refused the release, the task move had already removed the
row), and a half-failed cycle pinged again on the next run.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import scripts.crew.tasks.monitor as monitor
import scripts.crew.tasks.sweep as sweep

NOW = datetime.fromisoformat("2026-02-25T12:00:00+00:00")
OLD = 1771846200  # far older than the 1 minute threshold at NOW
A, B = "Agent Alpha", "Agent Beta"


@pytest.fixture(autouse=True)
def _fresh_blame_cache():
    monitor._BLAME_CACHE.clear()
    yield
    monitor._BLAME_CACHE.clear()


PING_A = "inactivity detected for `Agent Alpha`"


def _board(tmp_path: Path, agents=(A, B)) -> Path:
    claims = "\n".join(f"- agent={a}; scope=thomas/{i}.py; task=[WIP] t{i}" for i, a in enumerate(agents))
    tasks = "\n".join(
        f"- task_id=t{i}; agent={a}; scope=thomas/{i}.py; summary=[WIP] t{i}; status=active"
        for i, a in enumerate(agents)
    )
    board = tmp_path / "WORKBOARD.md"
    board.write_text(
        f"# Board\n\n## Agent Claims (Active)\n\n{claims}\n\n## Active Tasks\n\n{tasks}\n\n"
        "## Issues / Blockers\n\n- none\n\n## Up For Grabs\n\n- none\n\n"
        "## Supporting Docs (Not Plan Sources)\n\n- docs/PROJECT_SCOPE.md\n",
        encoding="utf-8",
    )
    return board


def _old(*_args, **_kwargs):
    return OLD


def _cycle(board: Path, monkeypatch, *, apply: bool, only, blame=_old, **extra):
    monkeypatch.setattr(sweep, "_line_commit_unix", blame)
    return monitor.sweep_once(
        workboard_path=board,
        max_idle_minutes=1.0,
        task_manager_agent="TaskManager",
        now=NOW,
        require_claims_to_have_active_task=False,
        apply=apply,
        only=only,
        **extra,
    )


def test_without_apply_the_board_is_byte_identical(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path)
    before = board.read_bytes()
    ok, details = _cycle(board, monkeypatch, apply=False, only=monitor.parse_only(A))
    assert ok and details["stale_claim_count"] == 2
    assert board.read_bytes() == before


def test_apply_without_only_reaps_nothing_and_says_so(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path)
    before = board.read_bytes()
    ok, details = _cycle(board, monkeypatch, apply=True, only=None)
    assert ok
    assert board.read_bytes() == before, "no implicit reap-all"
    assert sorted(details["would_reap"]) == [A, B]
    assert "--only" in str(details["apply_refused"])


def test_apply_with_only_reaps_exactly_the_named_claim(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path)
    ok, details = _cycle(board, monkeypatch, apply=True, only=monitor.parse_only("agent alpha"))
    text = board.read_text(encoding="utf-8")
    assert ok, details
    assert details["reaped_agents"] == [A]
    assert f"agent={A}; scope" not in text
    assert f"agent={B}; scope=thomas/1.py; task=[WIP] t1" in text, "the other claim is untouched"


def test_the_second_cycle_is_a_no_op(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path)
    _cycle(board, monkeypatch, apply=True, only=monitor.parse_only(A))
    after_first = board.read_bytes()
    ok, details = _cycle(board, monkeypatch, apply=True, only=monitor.parse_only(A))
    assert ok, details
    assert details["only_not_stale"] == ["agent alpha"], "the named claim is already gone"
    assert board.read_bytes() == after_first
    assert after_first.decode().count(PING_A) == 1


def test_a_release_refused_by_the_presence_gate_is_an_override_not_a_failure(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, (A,))
    calls: list[dict] = []

    def fake_release(_path, **kw):
        calls.append(kw)
        if kw.get("allow_presence_override"):
            return False, f"no active claim found for `{kw['agent']}`"
        return False, "presence gate requires override: 1 conflict(s)"

    monkeypatch.setattr(sweep.workboard_claim, "release", fake_release)
    ok, details = _cycle(board, monkeypatch, apply=True, only=monitor.parse_only(A))
    assert ok, details
    assert details["released_agents"] == [A] and details["reaped_agents"] == [A]
    (override,) = details["presence_overrides"]
    assert override["agent"] == A and "presence gate requires override" in override["refused_with"]
    assert "inactivity reclaim" in override["reason"]
    assert [bool(c.get("allow_presence_override")) for c in calls] == [False, True]
    assert calls[1]["presence_override_reason"] == override["reason"]


def test_a_real_release_failure_is_still_an_error(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, (A,))
    monkeypatch.setattr(sweep.workboard_claim, "release", lambda _p, **_k: (False, "disk on fire"))
    ok, details = _cycle(board, monkeypatch, apply=True, only=monitor.parse_only(A))
    assert not ok and "disk on fire" in str(details["errors"]) and details["presence_overrides"] == []


def test_a_half_failed_cycle_does_not_ping_or_open_a_second_issue_on_the_rerun(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, (A,))
    monkeypatch.setattr(sweep.workboard_issue, "move_task_to_up_for_grabs", lambda *_a, **_k: (False, "boom"))
    monkeypatch.setattr(sweep.workboard_claim, "release", lambda _p, **_k: (False, "boom"))
    ok, _details = _cycle(board, monkeypatch, apply=True, only=monitor.parse_only(A))
    assert not ok
    first = board.read_text(encoding="utf-8")
    assert first.count(PING_A) == 1 and first.count("issue_id=t0-inactive") == 1
    _ok2, details2 = _cycle(board, monkeypatch, apply=True, only=monitor.parse_only(A))
    second = board.read_text(encoding="utf-8")
    assert second.count(PING_A) == 1, "no second p0 ping"
    assert second.count("issue_id=t0-inactive") == 1, "no second issue"
    assert details2["skipped_repeat_notices"] == [A]


def test_one_claim_without_timing_evidence_does_not_block_the_others(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path)
    text = board.read_text(encoding="utf-8").splitlines()
    first_claim_line = next(i for i, line in enumerate(text, 1) if f"agent={A};" in line)

    def blame(_path, line_no):
        return None if line_no == first_claim_line else OLD

    ok, details = _cycle(board, monkeypatch, apply=True, only=monitor.parse_only(f"{A},{B}"), blame=blame)
    assert ok, details
    assert details["held_back_no_evidence"] == [A]
    assert details["reaped_agents"] == [B]
    assert f"agent={A}; scope" in board.read_text(encoding="utf-8")


def test_a_blame_is_cached_by_board_content_and_stops_at_the_time_budget(tmp_path: Path) -> None:
    board = _board(tmp_path)
    calls: list[int] = []

    def inner(_path, line_no):
        calls.append(line_no)
        return OLD

    monitor._BLAME_CACHE.clear()
    first = monitor.BlameBudget(inner, 60.0)
    assert first(board, 5) == OLD and first(board, 5) == OLD
    assert calls == [5], "same board content, same line: one git call"
    board.write_text(board.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    assert first(board, 5) == OLD and calls == [5, 5], "changed board: blamed again"
    spent = monitor.BlameBudget(inner, 0.0)
    assert spent(board, 9) is None and spent.skipped == [9] and calls == [5, 5], "budget spent: git not called"


def test_blame_runs_only_for_claims_that_have_no_other_timing_evidence(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, (A,))
    monkeypatch.setattr(sweep, "_latest_message_timestamp_by_sender", lambda **_k: {A.casefold(): NOW})
    seen: list[int] = []
    monkeypatch.setattr(sweep, "_line_commit_unix", lambda _p, n: seen.append(n) or OLD)
    monitor._BLAME_CACHE.clear()
    monitor.sweep_once(
        workboard_path=board,
        max_idle_minutes=1.0,
        task_manager_agent="TaskManager",
        now=NOW,
        require_claims_to_have_active_task=False,
        apply=False,
    )
    assert seen == []


def test_the_budget_skip_is_reported(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path, (A,))
    monitor._BLAME_CACHE.clear()
    ok, details = _cycle(board, monkeypatch, apply=False, only=None, blame_budget_seconds=0.0)
    assert ok and details["blame_skipped_lines"], details
    assert details["stale_claims"][0]["issue"] == monitor.NO_EVIDENCE_ISSUE


@pytest.mark.parametrize("raw,expected", [(None, None), ("", frozenset()), (" A , b,,", frozenset({"a", "b"}))])
def test_only_parses_claim_ids_case_insensitively(raw, expected) -> None:
    assert monitor.parse_only(raw) == expected
