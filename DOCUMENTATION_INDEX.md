# Thomas Project Documentation Index

This index points to the current Thomas runtime. Source code, import wiring, and
loader manifests outrank prose when they disagree. Numeric file counts are
deliberately omitted because the runtime changes as modules are added or retired.

## Quick Start for Contributors

Read these in order before changing code:

1. [`AGENTS.md`](AGENTS.md) — repository workflow, safety, and coordination rules.
2. [`ARCHITECTURE.md`](ARCHITECTURE.md) — live module boundaries and data flow.
3. [`docs/CHAT_EXECUTION_MODEL.md`](docs/CHAT_EXECUTION_MODEL.md) — authoritative
   model-owned chat and dispatch contract.
4. [`docs/AGENT_FILE_EDITING_RULES.md`](docs/AGENT_FILE_EDITING_RULES.md) — how
   to identify the source file that actually runs.
5. [`thomas/README.md`](thomas/README.md) — package-level runtime map.
6. Open the current entrypoint, its imports, and any loader manifest before editing.

## Authority Order

When two descriptions conflict, use this order:

1. Active source, import wiring, manifests, and executable tests.
2. `ARCHITECTURE.md` and `docs/CHAT_EXECUTION_MODEL.md`.
3. `docs/AGENT_FILE_EDITING_RULES.md`.
4. Package and component READMEs.
5. Historical plans, ledgers, and archived material.

A count copied into prose is never an architecture contract. Derive collections
from their source manifest or directory at verification time.

## Live Runtime Map

| Area | Start here | What it owns |
|---|---|---|
| CLI | `thomas/cli/main.py` and `thomas/cli/repl_runtime.py` | Command registration and local operator flows |
| HTTP app | `thomas/server/app.py`, `thomas/server/app_core.py`, `thomas/server/app_routes_init.py` | App composition, lifecycle, and route registration |
| Chat registration | `thomas/server/routes/chat_v2_registration.py` | Exclusive live registrar for `/api/chat` and `/api/v2/chat` |
| Chat ingress | `thomas/server/routes/chat_v2.py` | Unified handling for both registered chat routes |
| Model orchestration | `thomas/marketplace/orchestrator/brain.py` | Model-owned response and structured-capability decisions |
| Governed delegation | `thomas/server/chat_delegation.py` | Background task start, update, and lifecycle bridge |
| Specialist registration | `thomas/server/routes/chat_v2_registration.py` and `thomas/marketplace/orchestrator/registry.py` | Registers the specialist implementations exposed to chat |
| Agent execution | `thomas/agent/loop.py` and `thomas/agent/loop_*.py` | LLM streaming, tool execution, context, and completion |
| Conversations | `thomas/chat/session_store.py` and `thomas/chat/conversation.py` | Session persistence and bounded conversation context |
| Memory | `thomas/memory/store.py` and `thomas/memory/v2/` | Active stores and retrieval primitives |
| Tools | `thomas/tools/base.py` and `thomas/tools/registry.py` | Tool contracts and registration |
| Classic web runtime | `thomas/server/web/js/app_runtime_loader.js` and `thomas/server/web/js/runtime/` | Declared-order browser modules |
| Web shell | `thomas/server/web/index.html` | Direct scripts, templates, styles, and runtime-loader entry |
| Crew automation | `scripts/crew/tasks/manager.py` and `scripts/crew/tasks/*.py` | Workboard task-management commands |

## Chat Execution

Thomas does not classify natural-language prose into a local casual/actionable
fork. The configured frontier model sees the conversation and allowed structured
capabilities, then decides whether to answer directly or make a structured call.

```text
Natural-language turn
        |
        v
thomas/server/routes/chat_v2.py
        |
        v
frontier model via thomas/marketplace/orchestrator/brain.py
        |                         |
        | direct response         | structured capability
        v                         v
stream to chat             schema + policy validation
                                  |
                       governed execution + receipt
                                  |
                                  v
                         model explains the result
```

`send_task` is the structured bridge for governed background work. Deterministic
code validates the call and enforces policy; it does not rediscover intent from
keywords, regexes, scores, or fallback classifiers. See
[`docs/CHAT_EXECUTION_MODEL.md`](docs/CHAT_EXECUTION_MODEL.md) for the complete
contract.

## Frontend Source of Truth

`thomas/server/web/js/app_runtime_loader.js` owns the `RUNTIME_SCRIPTS` manifest.
Every JavaScript module declared there is active, in declared order. Names may be
numbered or descriptive. The number of entries can change, so documentation and
tests must derive it from `RUNTIME_SCRIPTS` rather than copy a snapshot.

For a classic-runtime change:

1. Find the feature in `thomas/server/web/js/runtime/`.
2. Confirm the file is declared in `RUNTIME_SCRIPTS`.
3. Preserve dependency order when adding or moving an entry.
4. Check `thomas/server/web/index.html` for scripts loaded directly outside the
   runtime manifest.
5. Verify the affected browser behavior and targeted contract tests.

CSS tokens live in `thomas/server/web/css/tokens.css`. Component and layout rules
live under `thomas/server/web/css/component_styles/` and
`thomas/server/web/css/layout_styles/`; their top-level CSS files are import hubs.

## Desktop Shell

[`docs/DESKTOP.md`](docs/DESKTOP.md) — Thomas as its own windowed browser
(`desktop.cmd`): why Electron, the security posture that may not be lowered, the
single CDP agent channel and its verbs, where the browser profile lives, the
gauntlet that must pass on every Electron bump, and the three silent reasons a
click can land nowhere. The browser chrome (`browser_shell*.js` under
`thomas/server/web/js/`) is served from `/static` but attached by
`desktop/preload.js`, not linked from `chat.html`.

## Python Source Composition

Normal Python imports are the default. `thomas/agent/loop.py` is a real facade over
named modules, `thomas/server/routes/chat_aiohttp.py` is a compatibility shim with
normal imports rather than a live chat-route registrar, and
`scripts/crew/tasks/manager.py` imports named task modules.

Never create a missing `*_part*.py` file or a new exec-based source loader. A small
amount of migration compatibility can remain on a branch, so discover it instead
of trusting a hard-coded list:

```bash
rg -l "load_monolith_source" thomas --glob "*.py"
```

A loader reference is a migration signal, not permission to recreate absent parts.
Open the file, verify every referenced path exists, follow its active fallback or
named imports, and test the actual import surface.

## Common Tasks

### Change chat behavior

- Read [`docs/CHAT_EXECUTION_MODEL.md`](docs/CHAT_EXECUTION_MODEL.md).
- Trace `thomas/server/routes/chat_v2.py` into
  `thomas/marketplace/orchestrator/brain.py` and the structured capability being
  changed.
- Use `thomas/agent/loop.py` for agent-loop behavior, not for pre-model prose
  classification.

### Add or change a specialist

- Inspect `thomas/server/routes/chat_v2_registration.py` for the live registration
  set.
- Implement the appropriate interface under
  `thomas/marketplace/specialists/`.
- Use `thomas/marketplace/orchestrator/registry.py` for registry behavior.

### Add or change a tool

- Start with `thomas/tools/base.py` and `thomas/tools/registry.py`.
- Trace construction through `thomas/core/tool_factory.py` and the surface that
  exposes the tool.
- Use the shared `thomas/core/llm.py` facade for model access rather than creating
  a parallel provider client.
- Add contract tests for registration, arguments, policy, and failure receipts.

### Add an HTTP endpoint

- Add the route in the focused module under `thomas/server/routes/`.
- Wire it through `thomas/server/app_routes_init.py`.
- Add a route-level contract test.

### Change the classic UI

- Use `RUNTIME_SCRIPTS` to locate active runtime modules.
- Use `thomas/server/web/index.html` for directly loaded scripts and styles.
- Test both the source contract and the visible behavior.

### Work on memory

- Start with `thomas/memory/store.py` and `thomas/memory/v2/`.
- Confirm the caller and configured persistence path before changing storage.

### Work on automation or the workboard

- Read [`scripts/README.md`](scripts/README.md).
- Start with `scripts/crew/tasks/manager.py` and its named imports.
- Treat `plans/thomas/WORKBOARD.md` as coordination state, not application source.

## Debugging and Handoff

1. Trace the failing surface from its current entrypoint.
2. Search for every implementation and caller before changing code.
3. Confirm the edited path is imported, registered, or declared by a live caller.
4. Follow `AGENTS.md` for protected-file approval, versioning, and coordination.
5. After Python changes, clear only project bytecode and restart the foreground
   server:

   ```powershell
   Get-ChildItem -LiteralPath thomas -Recurse -File -Filter *.pyc | Remove-Item -Force
   .\.venv\Scripts\python.exe -m thomas serve
   ```

   ```bash
   find thomas -type f -name '*.pyc' -delete
   .venv/bin/python -m thomas serve
   ```

   Stop the existing foreground server with `Ctrl+C` before restarting it; do not
   kill every Python process on the machine.
6. After JavaScript or CSS changes, hard-refresh the affected page
   (`Ctrl+Shift+R` on Windows/Linux; `Cmd+Shift+R` on macOS).
7. Run focused tests first, then the required broader gates for the change.
8. Report exact items scanned and distinguish source checks from live runtime
   proof.

## Documentation Verification

The focused contract is `tests/test_documentation_truth.py`. It verifies:

- local Markdown links in the four onboarding documents resolve;
- repo-relative source paths cited in code spans exist;
- retired architecture names do not return;
- the runtime manifest has no duplicates, missing files, or unlisted files; and
- each onboarding document describes the runtime through `RUNTIME_SCRIPTS`
  without freezing a file count or numeric range.

When reporting a check, include the number of documents, links, path references,
manifest entries, and runtime files examined.

---

**Last updated:** 2026-08-13
