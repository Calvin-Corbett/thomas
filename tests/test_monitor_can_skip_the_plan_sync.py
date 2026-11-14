"""`manager.py --monitor --skip-plan-sync` runs the sweep without touching plans or the board.

Without `--apply` the monitor's start-up plan check is a dry run, and a dry run exits 1 when any
task has no plan file, so a monitor started that way never reached its first sweep. With
`--apply` the same step writes plan files and the board. A spawned monitor wants neither, so it
passes `--skip-plan-sync`; the default for a person at a terminal is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import scripts.crew.tasks.manager as manager
import scripts.crew.tasks.sweep as sweep

BOARD_TEXT = (
    "# Board\n\n## Agent Claims (Active)\n\n"
    "- agent=Agent Alpha; scope=thomas/a.py; task=[WIP] ta\n\n"
    "## Active Tasks\n\n"
    "- task_id=ta; agent=Agent Alpha; scope=thomas/a.py; summary=[WIP] ta; status=active\n\n"
    "## Issues / Blockers\n\n- none\n\n## Up For Grabs\n\n- none\n\n"
    "## Supporting Docs (Not Plan Sources)\n\n- docs/PROJECT_SCOPE.md\n"
)


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    board = tmp_path / "WORKBOARD.md"
    board.write_text(BOARD_TEXT, encoding="utf-8")
    return [
        *("--workboard", str(board)),
        *("--plan-root", str(tmp_path / "plans")),
        *("--problem-root", str(tmp_path / "problems")),
        *("--monitor", "--cycles", "1", "--max-idle-minutes", "1"),
        *("--now", "2026-02-25T12:00:00+00:00", "--json"),
        *extra,
    ]


def _run(tmp_path: Path, monkeypatch, capsys, *extra: str) -> tuple[int, str]:
    monkeypatch.setattr(sweep, "_line_commit_unix", lambda *_a, **_k: 1771846200)  # far older than the threshold
    code = manager.run(_argv(tmp_path, *extra))
    return code, capsys.readouterr().out


def test_a_skipped_plan_sync_still_sweeps_and_writes_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    code, out = _run(tmp_path, monkeypatch, capsys, "--skip-plan-sync")
    payload = json.loads(out.strip().splitlines()[-1])
    assert code == 0
    assert payload["plan_sync"] == {"skipped": "--skip-plan-sync"}
    assert payload["stale_claim_count"] == 1, "the sweep still looks"
    assert (tmp_path / "WORKBOARD.md").read_text(encoding="utf-8") == BOARD_TEXT
    assert not (tmp_path / "plans").exists() and not (tmp_path / "problems").exists()


def test_without_the_flag_a_dry_run_monitor_stops_at_a_missing_plan(tmp_path: Path, monkeypatch, capsys) -> None:
    """Why the flag exists: the dry-run plan check fails first and the sweep never runs."""
    code, out = _run(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert "missing task artifact files" in out
    assert (tmp_path / "WORKBOARD.md").read_text(encoding="utf-8") == BOARD_TEXT


def test_the_same_monitor_with_apply_would_write_plans(tmp_path: Path, monkeypatch, capsys) -> None:
    """Control for the first test: it can see a write, so its silence means something."""
    _run(tmp_path, monkeypatch, capsys, "--apply")
    assert (tmp_path / "plans").exists() or (tmp_path / "problems").exists()
