from __future__ import annotations

from pathlib import Path

from scripts.crew.brief import landing_briefing, startup_router


def _workboard(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        "# Thomas Workboard\n\nLast updated: 2026-03-18\n\n## Agent Claims\n\n- none\n\n## Active Tasks\n\n- none\n",
        encoding="utf-8",
    )
    return path


def _payload(tmp_path: Path, *, paths: list[str] | None = None, edit_intent: bool = False, benchmark: bool = False):
    return startup_router.classify_task(
        summary="Show landing queue at session start",
        paths=paths or [],
        edit_intent=edit_intent,
        benchmark_mode=benchmark,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_workboard(tmp_path),
    )


def test_summary_only_chat_lane_names_the_landing_queue(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    text = startup_router._text_output(payload)

    assert payload["lane"] == "chat"
    assert payload["landing_queue"] == [landing_briefing.FIRST, landing_briefing.SECOND]
    assert text.count(landing_briefing.FIRST) == 1
    assert text.count(landing_briefing.SECOND) == 1
    assert "landing_queue:" in text


def test_editing_lane_names_the_landing_queue(tmp_path: Path) -> None:
    payload = _payload(tmp_path, paths=["thomas/core/config.py"], edit_intent=True)
    text = startup_router._text_output(payload)

    assert payload["lane"] == "simple-edit"
    assert payload["landing_queue"] == [landing_briefing.FIRST, landing_briefing.SECOND]
    assert text.count(landing_briefing.FIRST) == 1
    assert text.count(landing_briefing.SECOND) == 1
    assert "landing_queue:" in text


def test_benchmark_lane_does_not_name_the_landing_queue(tmp_path: Path) -> None:
    payload = _payload(tmp_path, benchmark=True)
    text = startup_router._text_output(payload)

    assert payload["lane"] == "benchmark"
    assert payload["landing_queue"] == []
    assert landing_briefing.FIRST not in text
    assert landing_briefing.SECOND not in text
    assert "landing_queue:" not in text
