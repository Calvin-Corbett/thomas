"""Real tokens and real speed per run, so the Build home can show them instead of an empty graph."""

from __future__ import annotations

import json
import time
from pathlib import Path

from thomas.core.events import EventType
from thomas.forge.anvil import run_control
from thomas.forge.anvil.dispatch_agent_loop_translator import _AgentLoopForgeTranslator

REGISTRATION = Path(__file__).resolve().parents[1] / "thomas" / "server" / "routes" / "evolve_agent_registration.py"


def test_each_finished_pass_adds_to_the_runs_totals(tmp_path):
    run_control.add_usage(tmp_path, 1000, 200, 1200, 10.0)
    run_control.add_usage(tmp_path, 3000, 400, 3400, 20.0)

    row = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert (row["prompt"], row["completion"], row["total"], row["seconds"], row["passes"]) == (4000, 600, 4600, 30.0, 2)


def test_nonsense_usage_is_never_recorded(tmp_path):
    run_control.add_usage(tmp_path, -1, 5, 5, 1.0)
    run_control.add_usage(tmp_path, "x", 5, 5, 1.0)
    run_control.add_usage(tmp_path, 1, 1, 2, -3.0)

    assert not (tmp_path / "usage.json").exists()


def test_the_first_output_time_is_kept_once_and_survives_later_usage(tmp_path):
    run_control.write_first_output(tmp_path, 4.5)
    run_control.write_first_output(tmp_path, 99.0)
    run_control.add_usage(tmp_path, 10, 5, 15, 2.0)

    row = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert row["first_output_s"] == 4.5 and row["total"] == 15


def _make_run(root: Path, run_id: str, *, total: int, completion: int, seconds: float, first: float | None = None):
    folder = root / ".thomas" / "evolve" / "agent" / "run_control" / run_id
    folder.mkdir(parents=True)
    run_control.add_usage(folder, total - completion, completion, total, seconds)
    if first is not None:
        run_control.write_first_output(folder, first)


def test_the_summary_totals_per_day_and_works_out_speed(tmp_path):
    _make_run(tmp_path, "run_a", total=6000, completion=1000, seconds=30.0, first=3.0)
    _make_run(tmp_path, "run_b", total=4000, completion=500, seconds=20.0, first=7.0)

    summary = run_control.usage_summary(tmp_path, 7)

    today = time.strftime("%Y-%m-%d")
    assert summary["runs"] == 2
    assert summary["days"] == [{"date": today, "total": 10000, "prompt": 8500, "completion": 1500, "runs": 2}]
    assert summary["tokens_per_second"] == 200.0 and summary["reply_tokens_per_second"] == 30.0
    assert summary["first_output_median_s"] == 7.0


def test_an_empty_catalog_has_no_days_and_no_speed(tmp_path):
    summary = run_control.usage_summary(tmp_path, 7)

    assert summary["days"] == [] and summary["runs"] == 0
    assert summary["tokens_per_second"] is None and summary["first_output_median_s"] is None


def test_the_translator_hands_a_finished_pass_and_the_first_output_to_its_sinks():
    usage: list[tuple] = []
    firsts: list[float] = []
    translator = _AgentLoopForgeTranslator(lambda event: None)
    translator.usage_sink = lambda *args: usage.append(args)
    translator.first_output_sink = firsts.append

    translator.feed(EventType.TEXT_DELTA.value, {"text": "On it"})
    translator.feed(
        EventType.AGENT_DONE.value,
        {"text": "done", "token_report": {"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000}},
    )

    assert len(firsts) == 1 and firsts[0] >= 0
    assert len(usage) == 1 and usage[0][:3] == (900, 100, 1000) and usage[0][3] >= 0


def test_the_performance_url_is_registered():
    assert '("GET", "/api/evolve/agent/performance", "run_performance")' in REGISTRATION.read_text(encoding="utf-8")
