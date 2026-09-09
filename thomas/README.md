# Thomas Application Package

The `thomas/` package contains the CLI, HTTP server, model-led chat runtime,
governed background workers, memory, tools, and browser application.

For repository-wide rules, read [`AGENTS.md`](../AGENTS.md). For the current
architecture and chat contract, read [`ARCHITECTURE.md`](../ARCHITECTURE.md) and
[`docs/CHAT_EXECUTION_MODEL.md`](../docs/CHAT_EXECUTION_MODEL.md).

## Live Chat Flow

Natural-language turns are model-owned. Thomas does not run a deterministic
classifier in front of the model to decide whether prose deserves a reply or a
task.

```text
browser or API client
        |
        v
thomas/server/routes/chat_v2_registration.py
        |
        v
thomas/server/routes/chat_v2.py
        |
        v
thomas/marketplace/orchestrator/brain.py
        |
        +--> direct model response --> streamed chat events
        |
        +--> structured send_task call
                  |
                  v
            schema + policy checks
                  |
                  v
       thomas/server/chat_delegation.py
                  |
          +-------+----------------+
          |                        |
          v                        v
  governed AgentLoop worker   Task Manager fallback
          |                        |
          +-----------+------------+
                      v
              receipt returned to chat
```

The frontier model chooses the semantic action. Deterministic code validates
structured calls, enforces permissions and budgets, executes accepted calls, and
reports receipts. It must not infer a different action from words, regexes,
scores, or fallback intent classifiers.

## Runtime Entry Points

| Path | Responsibility |
|---|---|
| `thomas/cli/main.py` | CLI command registration |
| `thomas/cli/repl_runtime.py` | Interactive local chat entry |
| `thomas/server/app.py` | HTTP application facade |
| `thomas/server/app_core.py` | Core application composition |
| `thomas/server/app_routes_init.py` | Route-set registration |
| `thomas/server/routes/chat_v2_registration.py` | Exclusive live registrar for `/api/chat` and `/api/v2/chat`, plus chat state and specialists |
| `thomas/server/routes/chat_v2.py` | Unified chat-turn handling |
| `thomas/marketplace/orchestrator/brain.py` | Model-led response and structured-capability loop |
| `thomas/server/chat_delegation.py` | Governed background delegation |
| `thomas/server/worker_runtime.py` | Provider-agnostic background `AgentLoop` |
| `thomas/agent/loop.py` | Real agent-loop facade over named modules |

## Major Areas

| Area | Current source |
|---|---|
| Agent execution | `thomas/agent/loop.py`, `thomas/agent/loop_core.py`, `thomas/agent/loop_execution.py`, `thomas/agent/loop_streaming.py`, `thomas/agent/loop_tools.py` |
| Conversation state | `thomas/chat/conversation.py` and `thomas/chat/session_store.py` |
| Memory | `thomas/memory/store.py` and `thomas/memory/v2/` |
| Tool contracts | `thomas/tools/base.py` and `thomas/tools/registry.py` |
| Specialist registry | `thomas/marketplace/orchestrator/registry.py` |
| Specialist implementations | `thomas/marketplace/specialists/` |
| Server routes | `thomas/server/routes/` |
| Classic browser runtime | `thomas/server/web/js/app_runtime_loader.js` and `thomas/server/web/js/runtime/` |
| Browser shell | `thomas/server/web/index.html` |

Top-level domain packages can be scaffolds or compatibility surfaces. Do not infer
that a directory is on the production path merely because it exists; trace its
imports from an entrypoint.

## Python Editing Model

Normal imports and focused modules are the default. In particular:

- `thomas/agent/loop.py` contains the live `AgentLoop` facade and imports named
  modules such as `thomas/agent/loop_core.py` and
  `thomas/agent/loop_execution.py`.
- `thomas/server/routes/chat_aiohttp.py` is a compatibility shim that imports
  `thomas/server/routes/chat_aiohttp_handlers.py` and
  `thomas/server/routes/chat_aiohttp_helpers.py`; it does not own live route
  registration.
- `scripts/crew/tasks/manager.py` imports named modules under
  `scripts/crew/tasks/`.

Do not create new `*_part*.py` files or exec-based source loaders. A branch may
still contain migration compatibility, so discover its current callers instead of
copying a permanent list:

```bash
rg -l "load_monolith_source" thomas --glob "*.py"
```

Open each result and verify which path actually executes. A reference to a missing
part is migration debt, not an instruction to recreate the part. Follow
[`docs/AGENT_FILE_EDITING_RULES.md`](../docs/AGENT_FILE_EDITING_RULES.md) before
changing a facade or compatibility module.

## Browser Editing Model

`thomas/server/web/js/app_runtime_loader.js` contains the `RUNTIME_SCRIPTS`
manifest for the classic runtime. Every listed module is active in declared order.
Both numbered and descriptive filenames are valid. The list changes over time, so
do not document or test a copied file count or numeric range.

For a browser-runtime change:

1. Locate the implementation in `thomas/server/web/js/runtime/`.
2. Confirm the filename appears in `RUNTIME_SCRIPTS`.
3. Preserve manifest order and dependencies.
4. Inspect `thomas/server/web/index.html` for scripts loaded directly outside the
   manifest.
5. Run the focused source contract and prove the affected UI behavior.

Design tokens live in `thomas/server/web/css/tokens.css`. Split component and
layout rules live in `thomas/server/web/css/component_styles/` and
`thomas/server/web/css/layout_styles/`.

## Common Changes

### Chat behavior

Start with `thomas/server/routes/chat_v2.py` and
`thomas/marketplace/orchestrator/brain.py`. Preserve model ownership of semantic
decisions and the structured `send_task` boundary.

### Background work

Trace `send_task` into `thomas/server/chat_delegation.py` and
`thomas/server/worker_runtime.py`. Background execution uses the standard
`AgentLoop` with governed tools; Task Manager is an explicit fallback, not a prose
classifier.

### Specialists

The live chat registration set is in
`thomas/server/routes/chat_v2_registration.py`. Registry behavior lives in
`thomas/marketplace/orchestrator/registry.py`, and implementations live under
`thomas/marketplace/specialists/`.

### Tools and model access

Tool contracts and registration begin in `thomas/tools/base.py` and
`thomas/tools/registry.py`; trace construction through
`thomas/core/tool_factory.py`. Use the shared `thomas/core/llm.py` facade for
model access instead of creating a separate provider client.

### HTTP endpoints

Use a focused module under `thomas/server/routes/` and wire it through
`thomas/server/app_routes_init.py`. Add a route contract test.

### Memory

Start with `thomas/memory/store.py` and `thomas/memory/v2/`. Verify the configured
persistence boundary and its caller before editing storage behavior.

### UI

Use `RUNTIME_SCRIPTS` for classic-runtime files and
`thomas/server/web/index.html` for directly loaded assets. Never choose an edit
target from a remembered sequence number.

### Crew automation

Read [`scripts/README.md`](../scripts/README.md), then start with
`scripts/crew/tasks/manager.py` and its named imports. Coordination state belongs
in `plans/thomas/WORKBOARD.md` and must not be treated as application source.

## Repository Boundaries

- `thomas/_archived/` is historical code, not a production edit target.
- `thomas/_vendor/` contains vendored dependencies; do not rewrite or remove it
  as part of an unrelated feature.
- A domain package containing only scaffolding is not proof of a live product
  surface. Trace imports and route/tool registration.
- Follow `AGENTS.md` for protected-file approval, versioning, and coordination.
- After Python changes, stop the foreground server with `Ctrl+C`, clear only
  project bytecode, and restart the live `thomas serve` surface:

  ```powershell
  Get-ChildItem -LiteralPath thomas -Recurse -File -Filter *.pyc | Remove-Item -Force
  .\.venv\Scripts\python.exe -m thomas serve
  ```

  ```bash
  find thomas -type f -name '*.pyc' -delete
  .venv/bin/python -m thomas serve
  ```

  Do not kill every Python process on the machine.
- After JavaScript or CSS changes, hard-refresh the affected page
  (`Ctrl+Shift+R` on Windows/Linux; `Cmd+Shift+R` on macOS).
- Test the changed contract directly before running broader gates.

## Verification

`tests/test_documentation_truth.py` guards the onboarding map, live path
references, and one-to-one correspondence between `RUNTIME_SCRIPTS` and the
tracked runtime JavaScript files. Run targeted behavior tests for the subsystem
you change as well.
