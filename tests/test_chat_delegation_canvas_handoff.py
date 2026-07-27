"""A model-selected Canvas worker receives bounded conversation evidence.

Reproduced live: after a chart succeeded, "yes rerun the chart please" spawned a
fresh worker with an empty workspace that asked the user to re-paste the numbers.
No prompt classifier decides whether a turn is referential.
"""

from __future__ import annotations

from thomas.server.chat_delegation import _canvas_worker_prompt

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


def test_self_contained_request_still_receives_bounded_transcript_evidence() -> None:
    prompt = "make a bar chart of jan 100 feb 200"
    out = _canvas_worker_prompt(prompt, _RECENT)
    assert out.startswith(prompt)
    assert "2100" in out


def test_no_recent_messages_is_noop() -> None:
    assert _canvas_worker_prompt("rerun the chart", []) == "rerun the chart"
    assert _canvas_worker_prompt("rerun the chart", None) == "rerun the chart"
