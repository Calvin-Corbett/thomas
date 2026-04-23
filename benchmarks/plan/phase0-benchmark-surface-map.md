# Phase 0 Benchmark Surface Map

## Current Runtime Code

- `thomas/demo/agentic_benchmark.py`
- `thomas/demo/agentic_benchmark_core.py`
- `thomas/demo/agentic_benchmark_helpers.py`
- `thomas/demo/agentic_benchmark_runners.py`
- `thomas/demo/harness.py`
- `scripts/run_agentic_benchmark.py`

## Current Pack Locations

- `demo/task_pack.agentic.local.json`
- `demo/task_pack.agentic.product_capability_smoke10.json`
- `demo/task_pack.agentic.product_capability_50.json`
- `demo/task_pack.agentic.smoke.json`
- `demo/task_pack.default.json`

## Current Output Locations

- `demo/agentic-runs/*`

## Current Strategy / Spec Docs

- `demo/README.md`
- `docs/AGENT_COMPARISON_SUITE.md`

## Canonical Direction

- definitions move to `benchmarks/`
- outputs move to `runtime/benchmarks/agentic-runs/`
- `demo/` benchmark packs remain compatibility-only until migrated
