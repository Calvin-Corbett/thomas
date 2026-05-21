from pathlib import Path

import pytest

from thomas.demo.snake_h2h_benchmark import (
    _attempt_dir,
    _next_attempt_number,
    _render_report,
    _resolve_benchmark_session_id,
    run_benchmark,
)


def test_resolve_benchmark_session_id_falls_back_to_timestamp_seed() -> None:
    value = _resolve_benchmark_session_id("")
    assert value.startswith("snake-")


def test_attempt_helpers_increment_with_existing_attempt_dirs(tmp_path: Path) -> None:
    session_dir = tmp_path / "snake-session"
    _attempt_dir(session_dir, 1).mkdir(parents=True)
    _attempt_dir(session_dir, 2).mkdir(parents=True)
    assert _next_attempt_number(session_dir) == 3


def test_render_report_mentions_served_and_scored_roots() -> None:
    report = _render_report(
        run_id="session-a-attempt-01",
        records=[
            {
                "competitor": "thomas",
                "benchmark_session_id": "session-a",
                "attempt_number": 1,
                "success": True,
                "elapsed_seconds": 10.0,
                "quality_score": 5,
                "served_root": "C:/tmp/thomas",
                "scored_root": "C:/tmp/thomas",
                "notes": "ok",
            },
            {
                "competitor": "reference_cli",
                "benchmark_session_id": "session-a",
                "attempt_number": 1,
                "success": False,
                "elapsed_seconds": 12.0,
                "quality_score": 2,
                "served_root": "C:/tmp/reference_cli",
                "scored_root": "C:/tmp/reference_cli",
                "notes": "fail",
            },
        ],
    )
    assert "Benchmark session" in report
    assert "Served Root" in report
    assert "Scored Root" in report


@pytest.mark.asyncio
async def test_run_benchmark_rejects_background_only_mode() -> None:
    class _Args:
        benchmark_session_id = ""
        run_id = ""
        thomas_api_base = "http://127.0.0.1:8899"
        start_thomas = False
        thomas_port = 8910
        watch = False
        no_open_browser = True

    with pytest.raises(RuntimeError, match="Visible benchmark execution is required"):
        await run_benchmark(_Args())
