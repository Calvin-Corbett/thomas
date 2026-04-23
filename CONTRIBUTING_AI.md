# AI Contributor Guide

## Read First

Before editing, read these files in this order:

1. `AGENTS.md`
2. `README.md`
3. `PROJECT_INDEX.md`
4. `KNOWN_ISSUES.md`
5. `GUARDRAILS.md`
6. `ARCHITECTURE.md` (this document)
7. `CHANGELOG.md`

## How to Run

Use the smallest reliable slice first, then escalate.

- `python -m pytest tests/test_smoke_integration.py -q`  (broad startup sanity)
- `python -m pytest tests/test_repl_slash.py -q`          (slash command behavior)
- `python -m pytest tests/test_ai_first_smoke.py -q`      (new smoke checks)
- `python -m pytest tests/test_architecture.py -x --tb=short -q` (architecture guard)

If any command fails, fix code first; do not relax tests.

## Adding a Feature Safely

1. Make the change in small diff chunks.
2. Preserve existing interfaces unless a coordinated migration is required.
3. Update only the module(s) that own the contract you touch.
4. Add/adjust tests in the same cycle as code changes.
5. Run the affected tests before and after edits.
6. If behavior impacts startup, orchestrator flow, tool contracts, or memory,
   include contract-level test coverage in one pass.

Keep interface names stable (`ToolResult`, `create_app`, slash command names, memory
entry paths). If they must change, first add migration notes and compatibility tests.

## What Not to Commit

Do not commit runtime artifacts, generated debug files, or secrets, including but not
limited to:

- `.thomas/`, `runtime/`, `tmp/`, `dist/`, `logs/`, `artifacts/`
- `.env`, `.env.local`, `.env.*`, `thomas_state.json`, `thomas.db*`, `*.db`, `*.log`
- `tasks/`, `tmp_cli_test*`, `server_output.txt`, `response*.txt`, caches, screenshots
- any API keys, tokens, webhook secrets, or credentials.

If any of these exist locally, ensure they are ignored before commit by keeping
`.gitignore` in sync.

## PR Output Requirements

Every PR from this workflow must include:

- **Tests updated**: new/adjusted tests for the changed contract.
- **Docs updated**: relevant sections in `ARCHITECTURE.md` and/or this file.
- **Acceptance criteria met**:
  - The stated acceptance criteria for the issue are demonstrated in test output.
  - Runtime contracts and architecture guards pass (`test_architecture.py` and the
    touched feature tests).

## Working Assumptions

Changes should be narrow, deterministic, and reversible. If behavior is uncertain,
prefer a two-step workflow: update tests first to lock expected behavior, then
implement to satisfy them.
