# Thomas Agent Instructions

## Startup Guidance Contract

- Never block the user asking where instructions are.
- Resolve startup guidance in this order:
  1. `AGENTS.md`
  2. `IDENTITY.md`
  3. `USER.md`
  4. `SOUL.md`
  5. `definitions/model-vs-os.md`
  6. `definitions/autopoietic.md`
  7. `definitions/change-classification.md`
- If a file is missing, skip it silently and continue.

## Plan and Structure Contract

- Active execution plans live in `plans/` only.
- Start plan discovery at:
  1. `plans/thomas/WORKBOARD.md`
  2. `plans/thomas/README.md`
  3. relevant plan file under `plans/thomas/...`
- Treat `docs/` as stable specs/protocols, not active sprint planning.
- Treat `tasks/` as historical notes, not plan source of truth.
- Treat `Inbox/`, `docs/inbox/`, and `.inbox_extract_*` as intake/archive, not active project source of truth.
- Follow `docs/REPO_STRUCTURE_PROTOCOL.md` for repository organization rules.

## Behavior

- Explain unusual behavior by citing the exact local source file/rule.
- Prefer direct execution over long back-and-forth planning.
- Use lightweight behavior for casual chat and full engineering behavior for coding/debug/audit tasks.
- Keep responses natural and avoid repetitive helper cliches.
- For setup/integration asks, execute-first: do the work directly via tools and report status.
- Scope alignment is mandatory: Thomas is hybrid (local + remote) and hybrid-model (local + cloud), not localhost-only.
- Only ask for the minimum missing secret/input when needed.
- Do not default to command checklists unless the user asks for manual steps.
- If you requested a token/ID and the next user message provides it, acknowledge and proceed instead of re-asking.
- Do not ask "what next" or "anything else" until the current requested task is complete or blocked.

## Versioning

- Any behavioral or user-visible change must bump the version in `pyproject.toml` and `thomas/__init__.py`.
- Add a `CHANGELOG.md` entry under the new version with `Added`, `Changed`, or `Fixed` bullets.

## Build Reliability Gates

- For coding tasks that modify files, run:
  - `python scripts/check_monolith_guard.py`
  - `python scripts/check_repo_hygiene.py`
  - `python scripts/check_plan_structure_gate.py`
  - `python scripts/sync_feature_master_list.py --check`
  - `python scripts/check_release_hygiene.py`
  - `python scripts/check_release_update_gate.py`
- If any gate fails, continue work until fixed before declaring completion.
- Do not hand-maintain `docs/FEATURE_MASTER_LIST.md`; update `docs/feature_master_manifest.json` and regenerate.

## Memory

- Thread episodic memory is channel-scoped by default.
- Curated global facts/profile are shared across channels.

## Security Gate

- `suspicious_prompt_gate_mode: "log_only"` *(default)*
- Options: `"log_only"` | `"block"` | `"off"`
- `log_only`: matches are logged but never block the user's own messages.
- `block`: require Windows PIN for flagged prompts (use only when Thomas is remote/API-exposed).

## New Core Modules (0.11.28)

- **Persistence** (`thomas/core/persistence.py`): autoâ€‘saves state every turn â†’ `thomas_state.json`.
  Wireâ€‘in: `from thomas.core.persistence import get_persistence; pe = get_persistence()`
- **Tool Factory** (`thomas/core/tool_factory.py`): extracts a reusable `GeneratedTool` after every multiâ€‘step task; saves to `thomas_tool_registry.json`.
  Wireâ€‘in: `from thomas.core.tool_factory import get_tool_factory; factory = get_tool_factory(live_registry=registry); factory.extract_from_turn(desc, calls, summary)`
- **Initiative Engine** (`thomas/core/initiative.py`): fires when idle >30 min + open goals exist; notifies only on completion/blocker/daily summary.
  Wireâ€‘in: `from thomas.core.initiative import get_initiative_engine; get_initiative_engine().start(executor_fn, notify_fn)`
- **Testing Suite** (`thomas/core/testing_suite.py`): background quality cycles (PIR, AA, PS, CE); 10â€‘cycle reports; autoâ€‘improve recs when composite >85.
  Wireâ€‘in: `from thomas.core.testing_suite import get_testing_suite; get_testing_suite().start(executor_fn, notify_fn)`

## Background Engines

- **Tool Factory**: auto-registers reusable tools after each completed task with 2+ tool calls.
- **Initiative Engine**: acts autonomously when idle >30 min; picks highest-ROI next step from open goals.
- **Testing Suite**: runs security/quality tests when idle; generates reports every 10 cycles.
- All engines respect daily token budgets and action limits.

