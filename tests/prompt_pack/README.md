# Prompt Pack Test Stubs

This folder holds per-prompt tests generated and merged through the catch-up pipeline.

Naming convention:
- `test_pNNN_<slug>.py`

Current source prompt pack:
- `docs/OPENCLAW_CATCHUP_PROMPT_PACK_216_2026-02-20.md`

Each prompt-owned test should validate:
- success path
- invalid input path
- stable output contract (especially JSON shapes where applicable)
