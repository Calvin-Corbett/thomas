# Competitor Deep Dive - What Needs Attention (2026-02-25)

Data source for this deep dive:
- Fresh suite artifact: `<repo_root>/docs/openclaw_gap_runs/latest_full_suite_compare.json`
- Computed at: `2026-02-25T16:04:32Z`

## Executive Readout

- Thomas remains top-ranked but benchmark governance verdict is still `NO_GO`.
- Only 8 runtime gaps remain, concentrated in OpenClaw latency/variance and test/maintainability ratios.
- The biggest blocker is not broad parity; it is scorecard and governance plumbing:
  - stale artifact split between C-drive repo and F-drive suite output,
  - missing benchmark evidence ingestion (`prog.*` evidence-required checks),
  - missing token telemetry (all token-efficiency scores are `n/a`),
  - reliability/reproducibility gate thresholds that currently pass for `0/14` agents.

## Measured Gaps Requiring Action

Open runtime gaps for Thomas (`open_gap_count=8`):
- `benchmark.raw_elapsed_seconds_p95` (winner: `openclaw`, gap `0.06215`, lower is better)
- `benchmark.weighted_score_stddev` (winner: `openclaw`, gap `5.965341`, lower is better)
- `benchmark.raw_elapsed_seconds_stddev` (winner: `openclaw`, gap `1.670548`, lower is better)
- `benchmark.success_rate_stddev` (winner: `openclaw`, gap `0.089898`, lower is better)
- `tests.loc_per_file` (winner: `autogpt`, gap `30.442541`, higher is better)
- `tests.to_code_file_ratio` (winner: `crewai`, gap `0.035555`, higher is better)
- `code.non_python_files` (winner: `openclaw`, gap `1574.0`, higher is better)
- `maintainability.large_code_files_over_800` (winner: `swe_agent`, gap `0.640503`, lower is better)

## Governance and Scoring Blockers

Thomas benchmark gates:
- `safety_gate=true`
- `real_task_correctness_gate=true`
- `reliability_gate=false`
- `cost_token_gate=false`
- `reproducibility_gate=false`

Cross-agent gate pass counts:
- `safety_gate`: `2/14`
- `real_task_correctness_gate`: `1/14`
- `reliability_gate`: `0/14`
- `cost_token_gate`: `0/14`
- `reproducibility_gate`: `0/14`

Benchmark evidence status:
- `thomas_benchmark_evidence_checks=0` in latest run artifact.
- Evidence-required families (evaluation, safety, task quality, reliability, release decisioning, human quality) stay at `0` when evidence is absent.

Freshness signal in C-drive repo:
- `scripts/competitors/check-freshness.ps1 -MaxAgeDays 2` fails as stale because local latest result is from `2026-02-21`.
- This indicates the suite output path split must be fixed first.

## Priority Focus

1. Unify suite artifact paths and freshness gating so board decisions use the true latest result.
2. Implement benchmark evidence ingestion (`benchmark_evidence_globs`) and generate `prog.*` evidence payloads.
3. Capture real token telemetry in benchmark raw rows and enable non-`n/a` token-efficiency scoring.
4. Close OpenClaw latency and variance gaps on dynamic runs.
5. Calibrate governance thresholds and reproducibility logic to metric scale so verdicts are meaningful.


