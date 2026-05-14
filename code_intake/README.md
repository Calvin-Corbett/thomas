# Code Intake Queue

This directory is for high-volume code-drop intake from external generation flows
(for example many parallel ChatGPT tabs).

Use the queue model:
- `queue/incoming`: newly received drops
- `queue/staged`: validated and ready to apply
- `queue/applied`: successfully applied drops
- `queue/rejected`: blocked/failed/manual-reject drops
- `reports`: validation/apply/reject reports
- `templates`: manifest templates
- `logs`: optional operator logs

Primary CLI:
- `python scripts/forge/intake/cli.py init`
- `python scripts/forge/intake/cli.py new --drop-id D20260220_001 --prompt-id P001 --batch-id B01 --title "Browser command registry scaffold"`
- `python scripts/forge/intake/cli.py validate --drop-id D20260220_001`
- `python scripts/forge/intake/cli.py stage --drop-id D20260220_001`
- `python scripts/forge/intake/cli.py apply --drop-id D20260220_001 --execute`

Security and quality controls:
- Path ownership enforcement (`allowed_paths` / `forbidden_paths`)
- Naming guard to avoid benchmark-name leakage (`openclaw`, `clawbot`)
- `git apply --check` validation for unified diff artifacts
- Per-drop JSON reports in `reports/`

See full runbook: `docs/CODE_INTAKE_PIPELINE.md`
