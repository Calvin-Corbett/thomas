# Phase 0 Fairness Gaps

## Confirmed Gap

The old raw benchmark lane was not a fair tool-using competitor lane.

In `thomas/demo/agentic_benchmark_runners.py`, `_run_raw_task()` called the model with `tools=None` and hard-coded `tool_calls=0`.

That meant tool-requiring packs could produce:
- valid Thomas runs
- invalid raw competitor runs

while still looking like a normal score comparison.

## Required Rule

If a benchmark pack requires a tool-using competitor capability class, a text-only lane is invalid.

It should be reported as:
- `validity=invalid_competitor_capability`

not as:
- a meaningful low benchmark score

## Additional Gaps

- current reporting is score-first instead of metric-first
- benchmark definitions are split across `demo/`, `docs/`, and runtime code
- endurance ladder packs do not yet have a canonical home
