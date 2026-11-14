"""The speed scoreboard says what one landed change cost: Thomas's hours, prompt tokens, cache share, machine load.

You asked on 2026-11-06 that every efficiency gain "should always be tracked" and that "thomas should track it all":
the 2x goal is measured in hours of runs, checks and second looks per landed change (baseline 18.4 h, 72M prompt
tokens), and until now that number was worked out by hand. Regression for thomas.core.landing_cost and
its use in thomas.server.routes.self_project_speed.speed_scoreboard.
"""

from __future__ import annotations

from datetime import datetime, timezone

from thomas.core.landing_cost import landing_cost
from thomas.server.routes.self_project_speed import speed_scoreboard

ROWS = [
    {"ts": 100.0, "step": "run", "seconds": 7200.0, "cpu": 40.0, "memory": 60.0},
    {"ts": 110.0, "step": "check", "seconds": 3600.0, "cpu": 80.0, "memory": 70.0},
    {"ts": 120.0, "step": "second_look", "seconds": 1800.0},
    {"ts": 130.0, "step": "tool", "seconds": 999.0},  # inside a run already counted
    {"ts": 140.0, "step": "model", "prompt_tokens": 3000, "cached_prompt_tokens": 1500, "seconds": 5.0},
    {"ts": 900.0, "step": "run", "seconds": 50000.0},  # outside the window
]


def test_a_period_divides_its_hours_and_tokens_by_what_landed() -> None:
    cost = landing_cost(ROWS, 2, 0.0, 500.0)
    assert cost["hours"] == 3.5 and cost["hours_per_landing"] == 1.75
    assert cost["prompt_tokens_per_landing"] == 1500 and cost["cached_share"] == 0.5
    assert cost["average_cpu"] == 60.0 and cost["average_memory"] == 65.0


def test_nothing_landed_shows_the_hours_spent_and_no_per_landing_number() -> None:
    cost = landing_cost(ROWS, 0, 0.0, 500.0)
    assert cost["hours"] == 3.5 and cost["hours_per_landing"] is None and cost["prompt_tokens_per_landing"] is None


def test_the_scoreboard_carries_a_cost_for_each_period() -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    today = now.replace(hour=1).timestamp()
    rows = [{"ts": today, "step": "run", "seconds": 3600.0}]
    board = speed_scoreboard({}, {}, None, now, step_rows=rows)
    assert board["today"]["cost"]["hours"] == 1.0 and board["today"]["cost"]["landed"] == 0
    assert board["last_week"]["cost"]["hours"] == 0.0


def test_without_the_step_log_the_scoreboard_is_unchanged() -> None:
    board = speed_scoreboard({}, {}, None, datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc))
    assert board["today"]["cost"] is None and board["last_week"]["cost"] is None
