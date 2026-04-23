# Code Intake Pipeline (High-Volume Prompt Drops)

Last updated: 2026-02-20

This pipeline is for ingesting large numbers of generated code drops safely,
with queue state, validation reports, and controlled apply flow.

## Directory Layout

- `code_intake/queue/incoming`
- `code_intake/queue/staged`
- `code_intake/queue/applied`
- `code_intake/queue/rejected`
- `code_intake/reports`
- `code_intake/templates`
- `code_intake/logs`

## CLI

Primary tool:
- `python scripts/code_intake.py`
- `python scripts/code_intake_seed_batch.py`

Commands:
- `init`: create queue structure and template
- `new`: create a new incoming drop skeleton
- `validate`: run policy checks + optional `git apply --check`
- `stage`: move validated drop from incoming to staged
- `apply`: apply staged drop (dry-run by default; use `--execute`)
- `reject`: move drop to rejected queue
- `status`: queue and report summary

Batch seeding helper:
- `python scripts/code_intake_seed_batch.py --batch-id B01`
- Seeds incoming drops from `docs/OPENCLAW_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv`
- Creates manifest + diff placeholder per prompt in that batch

## Supported Artifact Types

- `unified_diff`: patch file; validated via `git apply --check`
- `feature_pack`: extracted feature pack directory with optional `apply_feature_pack.py`
- `file_bundle`: manual apply flow (tracked, but not auto-applied)

## Fast Start (Per Drop)

1. Create intake skeleton:
   - `python scripts/code_intake.py init`
2. Create drop:
   - `python scripts/code_intake.py new --drop-id D20260220_001 --prompt-id P001 --batch-id B01 --title "Browser command registry scaffold" --artifact-type unified_diff`
3. Paste diff into:
   - `code_intake/queue/incoming/D20260220_001/change.diff`
4. Validate:
   - `python scripts/code_intake.py validate --drop-id D20260220_001`
5. Stage:
   - `python scripts/code_intake.py stage --drop-id D20260220_001`
6. Apply (explicit):
   - `python scripts/code_intake.py apply --drop-id D20260220_001 --execute`

## Policy Guardrails

- Ownership checks:
  - `ownership.allowed_paths`
  - `ownership.forbidden_paths`
- Naming guard:
  - blocks benchmark-name leakage in added lines (`openclaw`, `clawbot`) by default
- Artifact integrity:
  - optional `artifact.sha256`
- Reports:
  - every validate/apply/reject operation writes JSON in `code_intake/reports/`

## Suggested Operating Cadence

Use prompt batches from:
- `docs/OPENCLAW_CATCHUP_PROMPT_PACK_216_2026-02-20.md`
- `docs/OPENCLAW_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv`

Recommended batch cycle:
1. Seed one batch into `incoming`
   - `python scripts/code_intake_seed_batch.py --batch-id B01`
2. Validate all 8
3. Stage only passing drops
4. Apply one-by-one with tests after each
5. Move failures to `rejected` with reason
6. Update `docs/OPENCLAW_GAP_CHANGELOG.md`
