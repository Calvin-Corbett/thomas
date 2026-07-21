"""A referential canvas follow-up must carry the prior conversation's data.

Reproduced live: after a chart succeeded, "yes rerun the chart please" spawned a
fresh worker with an empty workspace that asked the user to re-paste the numbers.
The fix threads the recent conversation into the canvas worker prompt for
referential follow-ups (which charts can safely do — no "wrong build" bleed).
"""

from __future__ import annotations

from thomas.server.chat_delegation import _canvas_worker_prompt, _wants_canvas_delegation

_RECENT = [
    {"role": "user", "content": "make a bar chart of my fuel costs: jan 2100, feb 1850, mar 2400"},
    {"role": "assistant", "content": "Done — here is chart.pdf with the data."},
]


def test_rerun_followup_threads_prior_numbers() -> None:
    out = _canvas_worker_prompt("yes rerun the chart please", _RECENT)
    assert out.startswith("yes rerun the chart please")  # original ask preserved
    assert "2100" in out and "1850" in out and "2400" in out  # prior data carried


def test_add_a_row_followup_carries_context() -> None:
    out = _canvas_worker_prompt("add a row for april 1950", _RECENT)
    assert "2100" in out  # prior data present so the worker appends, not restarts


def test_self_contained_request_is_not_threaded() -> None:
    prompt = "make a bar chart of jan 100 feb 200"
    assert _canvas_worker_prompt(prompt, _RECENT) == prompt


def test_no_recent_messages_is_noop() -> None:
    assert _canvas_worker_prompt("rerun the chart", []) == "rerun the chart"
    assert _canvas_worker_prompt("rerun the chart", None) == "rerun the chart"


def test_chart_reruns_route_to_canvas() -> None:
    # Referential chart re-runs must reach the canvas specialist (where the
    # handoff threading lives), not the generic agent worker.
    assert _wants_canvas_delegation("rerun the chart please")
    assert _wants_canvas_delegation("redo the graph")
    assert _wants_canvas_delegation("make the chart again")
    assert _wants_canvas_delegation("make me a downloadable png bar chart of weekly miles")


def test_non_chart_reruns_stay_off_canvas() -> None:
    # A rerun verb without a chart word must not be misrouted to the canvas.
    assert not _wants_canvas_delegation("run it again")
    assert not _wants_canvas_delegation("rerun the analysis")
    assert not _wants_canvas_delegation("what is the capital of france")
