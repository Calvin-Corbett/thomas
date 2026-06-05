# Module: benchmarks

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | partially integrated (benchmark_lane wired; full harness not) |
| Last assessed    | 2026-06-05                                                  |
| Assessed by      | claude-opus-4-8 (wiring truth-up)      |
| Used in prod     | partially — `benchmark_lane.py` imported by `thomas/agent/loop_tool_exec.py:16`; academic harness not wired |
| Has real tests   | not assessed       |
| Blocking issues  | full benchmark harness (runner.py/types.py/adapters) not wired (misc-singletons-03) |

## What This Is

Thomas benchmark harness for measuring model amplification.

**Stats:** 11 Python files, 2,774 lines total.

## Honest Assessment

**Contains real algorithms and logic** with actual implementations. Partially
wired: `benchmark_lane.py` (`audit_benchmark_event`, `get_benchmark_context`)
is imported by the agent at `thomas/agent/loop_tool_exec.py:16` and is part of
the live tool-execution path. The full academic benchmark harness
(`runner.py`, `types.py`, and the adapters) is NOT wired into production yet
(tracked as misc-singletons-03).

## Known Gaps

- Full benchmark harness (runner.py/types.py/adapters) not wired (misc-singletons-03)
- Test coverage not assessed
