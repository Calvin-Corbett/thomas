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
  - `docs/openclaw_gap_runs/competitor_registry.json`
- If stale, refresh with:
  - `powershell -File scripts/competitors/run-full-suite.ps1`
