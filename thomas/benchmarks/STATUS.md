# Module: benchmarks

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | not integrated (full harness not wired; benchmark_lane moved to thomas/core) |
| Last assessed    | 2026-06-05                                                  |
| Assessed by      | claude-opus-4-8 (wiring truth-up)      |
| Used in prod     | no — the academic harness is not wired; the live `benchmark_lane.py` now lives in `thomas/core/`, not here |
| Has real tests   | not assessed       |
| Blocking issues  | full benchmark harness (runner.py/types.py/adapters) not wired (misc-singletons-03) |

## What This Is

Thomas benchmark harness for measuring model amplification.

**Stats:** 11 Python files, 2,774 lines total.

## Honest Assessment

**Contains real algorithms and logic** with actual implementations. The academic
benchmark harness (`runner.py`, `types.py`, and the adapters) is NOT wired into
production yet (tracked as misc-singletons-03). `benchmark_lane.py`
(`audit_benchmark_event`, `get_benchmark_context`) used to live here; it moved to
`thomas/core/benchmark_lane.py` because the agent loop reads it on every tool call
(imported in `thomas/agent/loop_tool_exec.py`) and it can never be off.

## Known Gaps

- Full benchmark harness (runner.py/types.py/adapters) not wired (misc-singletons-03)
- Test coverage not assessed
