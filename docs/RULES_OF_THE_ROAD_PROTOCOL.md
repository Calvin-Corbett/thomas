# Rules Of The Road Protocol

## Goal

Every task should pass a deterministic quality review before final completion.
If required checks fail, Thomas must continue work (auto-retry) until checks pass
or retry budget is exhausted.

## Job Types

- `coding`
- `config`
- `planning`
- `research`
- `video_design`
- `general`

Job type can be requested explicitly (`job_type`) or inferred from intent route and prompt.

## Required Checks

### Coding

- Non-empty final response.
- If code/file mutation is detected, at least one verification action is required
  (readback, diff, lint/check, test, etc).
- Optional strict mode can require explicit test execution for code edits.
- Monolith guard must run after code edits (`python scripts/forge/gates/monolith_guard.py`)
  so oversized files are blocked consistently across sessions.
  - In CI, monolith guard should run with git range context
    (`python scripts/forge/gates/monolith_guard.py --base <base> --head <head>`)
    so `max_growth_lines` caps for baselined hotspots are enforced.
  - Baseline relaxations (new baselined files, `max_lines` increases, growth-cap relaxations)
    require explicit approval entries and must pass
    `python scripts/forge/gates/monolith_baseline_approval_gate.py --base <base> --head <head>`.
- Repo hygiene guard should run after code edits
  (`python scripts/forge/gates/repo_hygiene.py`) so root/file-layout drift is caught early.
- Feature master list must remain generated from manifest
  (`python scripts/sync_feature_master_list.py --check`).

### Config

- Non-empty final response.
- `thomas.toml` must validate with zero config errors.
- No unknown core config keys are allowed.
- If config mutation is detected, at least one verification action is required.

### Other Job Types

- Non-empty final response is always required.
- Additional checks are advisory (not required) unless promoted to required later.

## Runtime Behavior

- A rules report is attached to run output under `token_report.rules_of_road`.
- Server also surfaces it in top-level `done.rules_of_road`.
- If quality enforcement is enabled and required checks fail, Thomas auto-retries
  with a remediation prompt before returning final done.

## Configuration

`[quality]` in `thomas.toml`:

```toml
[quality]
enabled = true
enforce = true
max_auto_retries = 1
require_verification_for_coding = true
require_tests_for_code_edits = false
require_monolith_guard_for_coding = true
```

Env overrides:

- `THOMAS_QUALITY_ENABLED`
- `THOMAS_QUALITY_ENFORCE`
- `THOMAS_QUALITY_MAX_AUTO_RETRIES`
- `THOMAS_QUALITY_REQUIRE_VERIFICATION_FOR_CODING`
- `THOMAS_QUALITY_REQUIRE_TESTS_FOR_CODE_EDITS`
- `THOMAS_QUALITY_REQUIRE_MONOLITH_GUARD_FOR_CODING`

`quality.max_auto_retries` is capped at `3` to prevent runaway retry loops.
