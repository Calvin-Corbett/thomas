# Code Intake Pipeline (High-Volume Prompt Drops)

Last updated: 2026-06-26

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
- `python scripts/forge/intake/cli.py`
- `python scripts/forge/intake/seed_batch.py`

Both scripts resolve the default intake root from the repository root:
`code_intake/`. They do not use `scripts/forge/code_intake/` when run
directly from the repository root.

Commands:
- `init`: create queue structure and template
- `new`: create a new incoming drop skeleton
- `validate`: run policy checks + optional `git apply --check`
- `stage`: move validated drop from incoming to staged
- `apply`: apply staged drop (dry-run by default; use `--execute`)
- `reject`: move drop to rejected queue
- `status`: queue and report summary

Batch seeding helper:
- `python scripts/forge/intake/seed_batch.py --batch-id B01`
- Seeds incoming drops from `docs/REFERENCE_CLI_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv`
- Creates manifest + diff placeholder per prompt in that batch
- `--dry-run` validates the batch and prints planned drops without creating
  queue directories or files.

## Supported Artifact Types

- `unified_diff`: patch file; validated via `git apply --check`
- `feature_pack`: extracted feature pack directory with optional `apply_feature_pack.py`
- `file_bundle`: manual apply flow (tracked, but not auto-applied)

## Fast Start (Per Drop)

1. Create intake skeleton:
   - `python scripts/forge/intake/cli.py init`
2. Create drop:
   - `python scripts/forge/intake/cli.py new --drop-id D20260220_001 --prompt-id P001 --batch-id B01 --title "Browser command registry scaffold" --artifact-type unified_diff`
3. Paste diff into:
   - `code_intake/queue/incoming/D20260220_001/change.diff`
4. Validate:
   - `python scripts/forge/intake/cli.py validate --drop-id D20260220_001`
5. Stage:
   - `python scripts/forge/intake/cli.py stage --drop-id D20260220_001`
6. Apply (explicit):
   - `python scripts/forge/intake/cli.py apply --drop-id D20260220_001 --execute`

## Policy Guardrails

- Ownership checks:
  - `ownership.allowed_paths`
  - `ownership.forbidden_paths`
- Naming guard:
  - blocks benchmark-name leakage in added lines (`reference_cli`, `clawbot`) by default
- Artifact integrity:
  - optional `artifact.sha256`
- Reports:
  - every validate/apply/reject operation writes JSON in `code_intake/reports/`

## Suggested Operating Cadence

Use prompt batches from:
- `docs/REFERENCE_CLI_CATCHUP_PROMPT_PACK_216_2026-02-20.md`
- `docs/REFERENCE_CLI_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv`

Recommended batch cycle:
1. Seed one batch into `incoming`
   - `python scripts/forge/intake/seed_batch.py --batch-id B01`
2. Validate all 8
3. Stage only passing drops
4. Apply one-by-one with tests after each
5. Move failures to `rejected` with reason
6. Update `docs/REFERENCE_CLI_GAP_CHANGELOG.md`
