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
- Benchmark program lanes:
  - `quick`: fast structural + correctness + interface checks.
  - `dynamic`: long-running behavior, resilience, safety, benchmark, and governance checks.
  - `human`: human-adjudicated quality checks when evidence is provided.

## Scoring Model

Head-to-head testing uses two explicit scores per agent:

- `head_to_head_score`: pairwise score (focus vs competitor) across metrics where either side has data.
- `head_to_head_decisive_score`: decisive 1v1 score where ties are always excluded.
- `token_efficiency_score`: dedicated token-cost efficiency score with its own 1v1 and overall ranking.
- `overall_suite_score`: all applicable checks (runtime metric checks + applicable full-coverage contract checks).
- `quick_suite_score`, `dynamic_suite_score`, `human_suite_score`: lane-specific full-suite scores by test mode.
- Head-to-head is pairwise (focus agent vs one competitor) and counts metrics where either side has data.
- Metrics where neither side has data are excluded from head-to-head.
- Tie handling is controlled by `head_to_head_tie_policy` in suite config:
  - `half_point` (default): tie gives `0.5` to each side.
  - `exclude`: tied metrics are not counted in the denominator.
- Token efficiency head-to-head is computed separately from runtime head-to-head using:
  - blended token efficiency score,
  - effective tokens per success (lower is better),
  - token telemetry coverage.
- Token efficiency scores are only emitted when real token telemetry exists (`prompt/completion/total` or derived `tokens_per_success`).
- Head-to-head is explicit 1v1 only and should be set with `--h2h-a <agent>` and `--h2h-b <agent>`.

This is the required method for conducting head-to-head benchmarking.

## Score Definitions (Exact)

- `head_to_head_score` (runtime 1v1 only):
  - Count a runtime metric if either side has numeric data.
  - Exclude a runtime metric if neither side has data.
  - Per counted metric: winner gets `1.0`; tie handling follows `head_to_head_tie_policy`.
  - With `half_point`: tie gets `0.5` each.
  - With `exclude`: ties are not counted.
  - Final score: `(agent_points / counted_metrics) * 100`.
- `head_to_head_decisive_score`:
  - Count only non-tied runtime 1v1 metrics where either side has numeric data.
  - Winner gets `1.0`, loser gets `0.0`.
  - Final score: `(wins / non_tied_counted_metrics) * 100`.
- `token_efficiency_score` (separate from runtime head-to-head):
  - Built from token efficiency telemetry and quality signals:
    - effective tokens per success,
    - mean token density,
    - benchmark success rate,
    - cost probe pass-rate.
  - Uses telemetry coverage weighting so sparse token data cannot look better than complete token data.
  - Token 1v1 is a separate score block and compares:
    - `token_efficiency_score` (higher better),
    - `effective_tokens_per_success` (lower better),
    - `telemetry_coverage` (higher better).
  - If neither side has token evidence, token 1v1 counted metrics are `0` and scores are `n/a`.
- `overall_suite_score` (per model across entire suite):
  - `runtime_applicable`: runtime metrics where that agent has data.
  - `runtime_passed`: runtime_applicable metrics where that agent is in `winners`.
  - `catalog_applicable`: full-coverage catalog checks applicable to the agent.
  - `catalog_passed`: applicable catalog checks that pass.
  - Final score:
    - `(runtime_passed + catalog_passed) / (runtime_applicable + catalog_applicable) * 100`.
- `quick_suite_score` / `dynamic_suite_score` / `human_suite_score`:
  - Same formula as `overall_suite_score`, but only checks tagged to that lane (`test_mode`).

Interpretation note:
- The earlier "`90%+`" numbers were runtime `head_to_head_score` values from strict 1v1 comparisons (Thomas vs one competitor at a time), not `overall_suite_score`.

## Benchmark Program

- The suite now emits `benchmark_program` in JSON output.
- This produces:
  - `overall_benchmark_capability_score` per agent (weighted lane score).
  - `quick_lane_score` and `dynamic_lane_score`.
  - `family_catalog` and per-agent `family_scores` for named benchmark families.
  - `governance_verdict`: `GO`, `LIMITED_GO`, `NO_GO`.
- Governance output also includes:
  - `governance_gates` per agent (`safety_gate`, `real_task_correctness_gate`, `reliability_gate`, `cost_token_gate`, `reproducibility_gate`).
  - `governance_thresholds` and `governance_calibration` so threshold decisions are inspectable.
- Lane defaults come from contract `benchmark_program.lane_weights`.
- Missing dynamic evidence counts against capability score by design.

### Governance Gate Rules

- `GO`: all governance gates pass and capability score is at or above `go_min`.
- `LIMITED_GO`: `safety_gate` passes, the configured minimum gate-count passes, and capability score is at or above `limited_go_min`.
- `NO_GO`: any other outcome.
- Reliability/reproducibility gates are calibrated from measured run variance (`benchmark.weighted_score_stddev`, `benchmark.success_rate_stddev`) when enough samples exist.
- Calibration can be tuned or overridden in `benchmark_program.governance_calibration` and `benchmark_program.governance_thresholds`.

### Dynamic Evidence Format

To feed long-running / advanced checks, provide JSON files via agent `benchmark_evidence_globs`:

```json
{
  "checks": {
    "prog.001": { "pass": true, "score": 100, "notes": "..." },
    "prog.002": { "pass": false, "score": 42, "notes": "..." }
  }
}
```

- `prog.*` ids come from `demo/baselines/agent_test_suite_full_coverage.contract.json`.
- If `pass` is omitted, `score >= pass_score_gte` is used.
- The wrapper (`scripts/run_agent_comparison_suite.py`) normalizes common competitor evidence variants into canonical `{"checks": ...}` payloads before scoring.
- Accepted evidence variants include:
  - Canonical object payloads with `checks`.
  - Row lists (for example raw benchmark rows) using `task_id`/`evidence_id`, `track`, `pass`/`success`, and `score`/`quality_score`.
  - Envelope payloads that store row lists under `rows`, `results`, `records`, `items`, `data`, `evaluations`, `tasks`, or `entries`.
  - Nested envelope shapes are supported (for example `results.rows` or `tracks.<alias>.checks`), and are flattened before scoring.
  - JSONL/NDJSON row streams (one JSON object per line).
- Normalization coerces common string booleans on explicit pass-like keys (`pass`, `success`, `passed`, `ok`), including `"true"`, `"false"`, `"pass"`, `"fail"`, `"1"`, `"0"`.
- Status-like keys (`status`, `outcome`, `result`) only coerce text booleans; numeric `"1"`/`"0"` status codes are left uncoerced to avoid false positives.
- Score coercion applies to `score` / `quality_score` finite numeric strings; non-finite values (`NaN`, `Infinity`) are ignored.
- Generic `value` fields are preserved unless they are unambiguous non-binary numeric scores.

## Run It

```bash
python scripts/run_agent_comparison_suite.py --write --write-md
```

JSON output defaults to:

- `docs/reference_cli_gap_runs/latest_full_suite_compare.json`

Markdown report defaults to:

- `docs/reference_cli_gap_runs/latest_full_suite_compare.md`

Competitor registry defaults to:

- `docs/reference_cli_gap_runs/competitor_registry.json`
- `docs/reference_cli_gap_runs/competitor_registry.md`

## Config

Default config:

- `demo/baselines/agent_comparison_suite.current.json`
- Includes `execution_policy` so quality-first, non-cycle-limited operation is explicit.

To add a new competitor, add a new entry under `agents` with:

- `id`, `root`, and source/test/subsystem roots.
- `test_dataset_roots` (optional) for structured eval corpora that should count as executable test assets even if filenames are not `test_*`.
- CLI adapter (`cli.command` or fixed CLI baselines).
- `strict_checks` for production-ready validations.
- `performance_probes`, `resilience_probes`, `security_probes`, `cost_probes` for runtime evidence.
- `benchmark_scorecard_globs` + `benchmark_aliases` for task-run quality metrics.
- `benchmark_raw_globs` for token/tool/elapsed efficiency metrics.
- `repo_sync` for automatic git freshness checks (`enabled`, `remote`, `branch`, `fetch`, `pull_ff_only`).
- `model_snapshot_command` (optional) and `model_snapshot_required` (optional) for per-run model/day capture.
- `benchmark_program.governance_calibration` (optional) to tune dynamic variance threshold calibration:
  - `enabled`, `min_agent_samples`, `min_runs_count`
  - `reliability_quantile`, `reliability_margin`, `reliability_floor`, `reliability_ceiling`
  - `reproducibility_quantile`, `reproducibility_margin`, `reproducibility_floor`, `reproducibility_ceiling`
- `benchmark_program.governance_thresholds` (optional) for explicit threshold overrides:
  - `correctness.dynamic_score_min`, `correctness.quick_score_min`
  - `reliability.resilience_pass_rate_min`, `reliability.weighted_stddev_max`, `reliability.success_stddev_max`
  - `reproducibility.weighted_stddev_max`, `reproducibility.success_stddev_max`
  - `capability.go_min`, `capability.limited_go_min`, `capability.limited_go_required_gate_count`

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
