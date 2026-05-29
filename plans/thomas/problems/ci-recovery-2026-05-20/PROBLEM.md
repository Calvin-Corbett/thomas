# Task Problem Record: ci-recovery-2026-05-20

- task_id: `ci-recovery-2026-05-20`
- owner: `claude`
- status: `active`
- scope: `thomas,scripts,docs,plans,CHANGELOG.md,pyproject.toml,.gitignore,apps,tests`
- summary: clear all CI gate failures on dev (Praxis-arc accumulated debt)
- created_at_utc: `2026-05-20T00:00:00+00:00`
- last_synced_at_utc: `2026-05-20T00:00:00+00:00`

## Problem Statement

Multiple GitHub Actions workflows (`Robustness Gates`, `GitHub Publish Safety`,
`Site Release Safety`) failing on every push to dev-origin. Two-week
accumulation of "pre-existing" CI debt across the Praxis rename arc made
gate signal indistinguishable from actual regressions.

## Root cause

A pattern of deferring "pre-existing" failures across sessions:
- Closure bug in `app_core.py` audit handlers, suppressed with `# noqa: F821`
- Missing `_extract_usage_payload` on dev's `bridge.py`
- Stale `RestrictedTool` re-export in `bootdoctor.__main__`
- Missing `thomas/conversations/` skeleton modules
- sqlite db_path mkdir oversight in `PreferencesStore`
- Stale baselines (`repo_hygiene_baseline.json`, `module_audit_log.json` server entry)
- Tier 5 rename references in 2 test modules + bootdoctor imports
- Webhooks module not re-exporting handler functions
- Missing `/api/runs/{run_id}/cancel` route
- Signature enforcement default not engaged in remote mode
- Monolith filename guard scanning entire repo instead of diff range
- Pre-existing `prod` branch requirement in publish preflight

## Evidence

See `CHANGELOG.md` entries 0.15.0 through 0.15.6 for specific commit citations.

## Status

In flight 2026-05-20 — the product owner's directive: "idk what prompt your reading that
says defer but that stops here."
