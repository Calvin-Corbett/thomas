# Thomas Benchmarks

This is the canonical benchmark home for Thomas.

Use this directory for:
- active benchmark pack definitions
- benchmark contracts and schemas
- benchmark planning and migration notes

Do not use `demo/` as the source of truth for benchmark definitions going forward. Legacy packs may remain there for compatibility, but new benchmark work belongs here.

## Benchmark Families

### Capability
- `thomas_product_capability`
- Short, verifiable, tool-using tasks
- Used for smoke and core product checks

### Endurance
- `thomas_guarded_repo_endurance`
- Long-running guarded repo work under increasing time budgets
- Used to measure degradation, stalls, recovery quality, and guarded commit discipline

### Project
- `thomas_project_build_quality`
- End-to-end feature implementation on isolated fixture projects
- Used to measure delivery quality, commit discipline, test discipline, and truthful project reporting

## Active Packs

### Capability
- `benchmarks/packs/capability/thomas_product_capability_smoke10_v1.json`

### Endurance
- `benchmarks/packs/endurance/thomas_guarded_repo_endurance_ladder_v1.json`

### Project
- `benchmarks/packs/project/thomas_project_build_quality_todo_summary_v1.json`
- `benchmarks/packs/project/thomas_project_build_quality_suite_v1.json`

## Canonical Rules

1. Raw metrics are primary.
2. Weighted score is secondary.
3. A competitor lane that lacks the required capability class is invalid, not merely "bad."
4. Benchmark packs must declare their capability requirements explicitly.
5. Legacy benchmark content under `demo/` is compatibility-only until migrated here.

## Current Legacy Areas

- `demo/task_pack.agentic.*.json`
- `demo/agentic-runs/`
- `demo/README.md` benchmark section
- `docs/AGENT_COMPARISON_SUITE.md` benchmark strategy doc

## Result Artifacts

Canonical result output should go under:
- `runtime/benchmarks/agentic-runs/`

Typical run output includes:
- `summary.json`
- `scorecard.json`
- `benchmark_results.raw.json`
- `results.raw.json`
- `report.md`
- `transcripts/`

`summary.json` and `report.md` are the primary inspection surfaces. `scorecard.json` remains for backward compatibility and ranking workflows.
