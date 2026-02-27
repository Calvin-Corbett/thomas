# OpenClaw Gap Run Notes

This directory stores per-prompt implementation notes referenced by the
216-prompt catch-up pack.

Expected file naming:
- `pNNN_<slug>.md`

Recommended per-file sections:
- What changed
- Tests run
- Remaining gap / follow-up
- Risks

## Freshness Guard

Weekly freshness is enforced in CI for competitor reports.

- Guard command:
  - `python scripts/check_competitor_freshness_guard.py --max-age-days 7`
- Primary artifacts inspected:
  - `docs/openclaw_gap_runs/latest_full_suite_compare.json`
  - `docs/openclaw_gap_runs/latest_compare.json` (legacy compatibility mirror)
  - `docs/openclaw_gap_runs/competitor_registry.json`
- If stale, refresh with:
  - `powershell -File scripts/competitors/run-full-suite.ps1`

`demo/baselines/agent_comparison_suite.current.json` (`artifact_paths`) is the source
of truth for these artifact locations.

## Weekly Delta Alerting

Week-over-week competitor pressure regressions are also evaluated in CI.

- Guard command:
  - `python scripts/competitors/check_weekly_delta_alert.py --strict`
- Metrics compared (latest run vs latest run at least 7 days earlier):
  - `beat_metric_count` (max `metrics_beating_focus` in ranked competitors)
  - `threat_score` (max `composite_score` in ranked competitors)
- Baseline selection semantics:
  - Picks the newest valid run whose `computed_at_utc` is on/before `latest - lookback_days`.
  - Missing intermediate week snapshots are allowed; the nearest older valid run is used.
  - If no qualifying baseline exists, status is `insufficient_history` (pass, no alert).
- Mixed metric availability semantics:
  - Metrics are compared independently.
  - If one metric is missing on either side, that metric is skipped with a warning.
  - If neither metric is comparable between latest and baseline, the guard fails with a fatal error.
- Registry artifact resolution:
  - Uses `demo/baselines/agent_comparison_suite.current.json` (`artifact_paths.registry_json`) when present.
  - Falls back to `docs/openclaw_gap_runs/competitor_registry.json`.
  - `--registry-json` explicitly overrides both.
- JSON output signal:
  - `status=alert` always means a regression was detected and `ok=false`, even without `--strict`.
  - Non-strict mode (`--strict` omitted) still exits `0` on alerts to support observational/nightly reporting.
  - `would_fail_strict=true` means the run would return non-zero under `--strict` (alerts or fatal errors).
- Nightly operator signals:
  - `nightly-reliability.yml` runs this guard in non-strict mode and writes:
    - `artifacts/nightly_reliability/competitor_delta_alerting.json`
    - `artifacts/nightly_reliability/competitor_delta_alerting.exit_code`
  - Interpret `.exit_code` as:
    - `0`: command completed (including alert-only outcomes in non-strict mode)
    - non-zero: fatal input/runtime error occurred (independent of strict alert semantics)
  - Use `status` + `alert_count` + `would_fail_strict` from JSON to decide whether PR/strict reruns should block.

## Claim Status

- `[READY] [AUTO-01][Codex 3-Worker-1] gap-competitor-delta-alerting`: Verified strict PR guard and nightly non-strict delta signaling; targeted tests pass; no actionable gap found.
