# Agent Lane: Benchmark

Use this lane for audited benchmark runs that must work in a dirty repo without touching product code.

Required reads:
- `docs/AGENT_FILE_EDITING_RULES.md`
- `GUARDRAILS.md`

Required checks:
- Confirm benchmark env is complete: `THOMAS_BENCHMARK_MODE=1`, `THOMAS_BENCHMARK_RUN_ID`, `THOMAS_BENCHMARK_REASON`, `THOMAS_BENCHMARK_ROOT`.
- Keep every write inside the benchmark root under `output/benchmarks/...`.
- Produce benchmark proof artifacts and audit output before handoff.

Escalate out of this lane when:
- The task needs edits outside the benchmark root.
- Product UI proof gates or release checks become required.
