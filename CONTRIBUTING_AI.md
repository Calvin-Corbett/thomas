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

## Semantic Intent Ownership

Thomas's conversational judgment comes from the configured frontier model, not a
keyword router in front of it. For every natural-language turn, give the frontier
model the conversation and the structured capabilities it is allowed to use. The
model alone decides whether to reply directly or invoke a capability.

Do not add regex, keyword, fuzzy-match, scoring, or secondary-classifier logic that
infers any of the following from ordinary user prose:

- reply versus dispatch;
- specialist, skill, mode, surface, or workspace selection;
- task count, decomposition, handoff, continuation, or live-project targeting;
- cancel, update, monitor, or other side-effect intent;
- a tool call encoded as assistant prose.

Do not pre-reject, quarantine, relabel, or require a local approval merely because
ordinary prompt text matches a suspicious-word pattern. Provider policy owns
model-input safety. Local authorization begins only after the model requests a
concrete structured action whose risk can be evaluated from its typed payload.

This rule applies before and after the model call. It is not acceptable to prelaunch
work before the model decides, reclassify a structured tool call from its text, or
scan the model's visible reply and turn prose into a side effect. If no valid
structured call exists, no semantic action occurred.

Deterministic code still owns governance after a structured choice. It may parse and validate a structured
payload, normalize literal schema values, enforce authorization and risk policy,
veto unsafe actions, redact secrets, check paths and URLs, apply resource limits,
and verify execution receipts. Those checks may narrow or reject a model request;
they must not invent, promote, or substitute a semantic request.

Explicit structured client controls remain valid. An exact `$skill-name` invocation
is also an explicit control; skill discovery may present available skills to the
model, but ordinary prose must not be keyword-ranked into a skill behind its back.

When changing orchestration, add regression coverage for both directions:

1. a structured model call produces the requested governed action with its supplied
   fields preserved; and
2. similar words in user or assistant prose produce no side effect on their own.

Do not write a blanket "no regex" test. Regex remains appropriate for schema,
path, URL, protocol, redaction, and artifact verification. It is not appropriate
for deciding whether natural-language prompt content is allowed to reach Thomas.
Tests should name the semantic decision boundary they protect.
