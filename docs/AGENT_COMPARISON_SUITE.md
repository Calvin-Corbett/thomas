# Agent Comparison Suite

This is the repeatable benchmark system for comparing Thomas against any competitor agent.

## What It Measures

- Code surface: total files/LOC, subsystem breadth, docs/config/scripts coverage.
- Test rigor: test files/LOC and test-to-code ratios.
- CLI surface: top-level commands and tracked subcommand depth.
- Compatibility: wiring coverage for key gateway patterns (for example `/v1/chat/completions`, `/v1/responses`).
- Integrity: empty files, syntax/JSON validation, required production paths.
- Production readiness: strict runtime checks (command + JSON assertions).
- Performance/load: repeatable probe commands with pass-rate, p95 latency, and throughput.
- Resilience: repeated stability probes and failure-sensitive pass-rate metrics.
- Security: security probe pass-rate plus static secret/risky-construct scans.
- Cost efficiency: benchmark token/tool-call efficiency and cost probe pass-rate.
- Benchmark execution quality: scorecard means plus raw benchmark row metrics.
- Reliability: score variability across repeated benchmark runs and raw latency variance.
- Competitor pressure board: which competitors are beating the focus agent the most.
- Prediction Evo Scope: competitor delta analysis from last tested version to current version, with predicted next focus and recommended Thomas counter-moves.

## Scoring Model

Head-to-head testing uses two explicit scores per agent:

- `head_to_head_score`: pairwise score (focus vs competitor) across metrics where either side has data.
- `overall_suite_score`: all applicable checks (runtime metric checks + applicable full-coverage contract checks).
- Head-to-head is pairwise (focus agent vs one competitor) and counts metrics where either side has data.
- Metrics where neither side has data are excluded from head-to-head.
- Head-to-head is explicit 1v1 only and should be set with `--h2h-a <agent>` and `--h2h-b <agent>`.

This is the required method for conducting head-to-head benchmarking.

## Run It

```bash
python scripts/run_agent_comparison_suite.py --write --write-md
```

JSON output defaults to:

- `docs/openclaw_gap_runs/latest_full_suite_compare.json`

Markdown report defaults to:

- `docs/openclaw_gap_runs/latest_full_suite_compare.md`

Competitor registry defaults to:

- `docs/openclaw_gap_runs/competitor_registry.json`
- `docs/openclaw_gap_runs/competitor_registry.md`

## Config

Default config:

- `demo/baselines/agent_comparison_suite.current.json`
- Includes `execution_policy` so quality-first, non-cycle-limited operation is explicit.

To add a new competitor, add a new entry under `agents` with:

- `id`, `root`, and source/test/subsystem roots.
- CLI adapter (`cli.command` or fixed CLI baselines).
- `strict_checks` for production-ready validations.
- `performance_probes`, `resilience_probes`, `security_probes`, `cost_probes` for runtime evidence.
- `benchmark_scorecard_globs` + `benchmark_aliases` for task-run quality metrics.
- `benchmark_raw_globs` for token/tool/elapsed efficiency metrics.
- `repo_sync` for automatic git freshness checks (`enabled`, `remote`, `branch`, `fetch`, `pull_ff_only`).
- `model_snapshot_command` (optional) and `model_snapshot_required` (optional) for per-run model/day capture.

To maintain an always-tested competitor list, use top-level `competitor_catalog` entries:

- `id`, `label`, `repo_url`, `root`, `branch`, `enabled`.
- Missing competitors are auto-cloned and auto-added to the run with generic code/test root heuristics.

Notes:

- If an agent does not define a probe list for a category, the suite applies a built-in fallback probe so the metric family still has measured data.
- Composite scoring only counts metrics with 2+ participating agents, so one-sided metrics cannot inflate rankings.
- Required model snapshots are validated every run (Thomas is required by default). If required snapshots are missing, the command exits non-zero.
- A full coverage contract is loaded from `test_suite_contract_path` and summarized in every run (`test_suite_contract` in JSON output).
- Execution policy is emitted in every run (`suite.execution_policy`) and should remain quality-first.

Then run:

```bash
python scripts/run_agent_comparison_suite.py --suite-config demo/baselines/agent_comparison_suite.current.json --focus-agent thomas --write --write-md
```

## Full Coverage Contract

Canonical full-coverage artifacts:

- `demo/baselines/agent_test_suite_full_coverage.contract.json` (machine-readable contract).
- `docs/AGENT_TEST_SUITE_FULL_COVERAGE.md` (human-readable full suite board: current runtime metrics + expanded catalog checks).

Regenerate both with:

```bash
python scripts/generate_full_coverage_contract.py
```

## Quality Policy

Canonical quality policy:

- `docs/QUALITY_EXECUTION_POLICY.md`
