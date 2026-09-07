# Agent File Editing Rules — Read Before Changing Anything

> Verify the live entrypoint, imports, and manifests before editing. A plausible
> filename is not evidence that the runtime executes it.

Last updated: 2026-08-13

These rules supplement [`AGENTS.md`](../AGENTS.md),
[`ARCHITECTURE.md`](../ARCHITECTURE.md), and
[`CHAT_EXECUTION_MODEL.md`](CHAT_EXECUTION_MODEL.md).

## The Source-of-Truth Rule

Use this evidence order:

1. The current entrypoint and its normal imports.
2. An explicit loader manifest or route-registration function.
3. Executable tests that exercise the same surface.
4. Documentation.
5. Historical plans and archived material.

Before editing, answer all three questions:

- What imports or declares this file?
- Does that caller run on the surface being changed?
- Which focused test or runtime proof will demonstrate the change?

## JavaScript: Classic Runtime

The classic browser runtime is declared by:

`thomas/server/web/js/app_runtime_loader.js`

Its `RUNTIME_SCRIPTS` array is the complete ordered manifest. Every declared file
is active. Filenames can be numbered or descriptive, and the set changes as
features are added or split. Never infer the active set from a remembered numeric
range or copy its current count into prose or tests.

### Before editing a runtime module

1. Search `thomas/server/web/js/runtime/` for the implementation.
2. Confirm the exact filename appears in `RUNTIME_SCRIPTS`.
3. Read adjacent manifest entries to understand dependency order.
4. Search for other implementations before adding a new rendering path.
5. If adding a file, add exactly one manifest entry and verify there are no
   missing, duplicate, or unlisted runtime files.
6. Run the affected source-level and browser-level tests.

Useful checks:

```bash
rg -n "RUNTIME_SCRIPTS" thomas/server/web/js/app_runtime_loader.js
rg -n "function_name_or_feature" thomas/server/web/js/runtime
rg -n "<script" thomas/server/web/index.html
```

`thomas/server/web/index.html` is the source of truth for scripts loaded directly
outside `RUNTIME_SCRIPTS`. Do not maintain a second copied list in this document.

### Retired browser paths

Only edit browser code reached from the live HTML shell, `RUNTIME_SCRIPTS`, or a
normal import. Do not recreate a deleted bundle or parallel split tree because an
old plan mentions it. `thomas/server/web/js/app_parts/GUARDRAILS.md` is a policy
sentinel, not an executable runtime module.

### CSS

- `thomas/server/web/css/tokens.css` is the design-token source.
- `thomas/server/web/css/component_styles/` contains split component rules.
- `thomas/server/web/css/layout_styles/` contains split layout rules.
- `thomas/server/web/css/components.css`,
  `thomas/server/web/css/layout.css`, and
  `thomas/server/web/css/evolution.css` are import hubs. Edit the imported file
  that owns the rule.

Trace each stylesheet from `thomas/server/web/index.html` or the page being
changed before assuming it is active.

## Python: Normal Imports First

Thomas uses focused modules and normal imports by default. Do not create new
`*_part*.py` files and do not add exec-based source loaders.

These frequently misidentified files are normal source today:

- `thomas/agent/loop.py` is the live `AgentLoop` facade. It imports
  `thomas/agent/loop_core.py`, `thomas/agent/loop_execution.py`,
  `thomas/agent/loop_streaming.py`, `thomas/agent/loop_tools.py`, and other named
  helpers.
- `thomas/server/routes/chat_aiohttp.py` is a compatibility shim with normal
  imports from `thomas/server/routes/chat_aiohttp_handlers.py` and
  `thomas/server/routes/chat_aiohttp_helpers.py`.
- `scripts/crew/tasks/manager.py` is a normal module that imports
  `scripts/crew/tasks/base.py`, `scripts/crew/tasks/messages.py`,
  `scripts/crew/tasks/plans.py`, `scripts/crew/tasks/reactivate.py`,
  `scripts/crew/tasks/sessions.py`, and `scripts/crew/tasks/sweep.py`.

Edit the named module that owns the behavior. Do not invent a part file because a
historical document described one.

### Residual loader compatibility

Some branches can still contain migration-era `load_monolith_source` callers. The
live callers are exactly the output of this command in the checkout being edited:

```bash
rg -l "load_monolith_source" thomas --glob "*.py"
```

Do not cache that output in documentation; parallel repairs can remove a caller.
For every result:

1. Open the caller.
2. Inspect its condition, fallback, and listed source files.
3. Verify every referenced source file exists.
4. Do not recreate an absent source fragment.
5. Prefer the named-import path and prove the import surface with a focused test.

A loader reference is migration debt, not a standing exception to the repository
ban on new part files or exec-based loaders.

## Chat and Specialist Paths

The live web chat route is registered by
`thomas/server/routes/chat_v2_registration.py` and handled by
`thomas/server/routes/chat_v2.py`. The route gives the frontier model structured
capabilities through `thomas/marketplace/orchestrator/brain.py`.

`thomas/server/routes/chat_v2_registration.py` is the exclusive live registrar
for `/api/chat` and `/api/v2/chat`.
`thomas/server/routes/chat_aiohttp.py` is compatibility-only; it does not own
either live route registration.

The model can answer directly or issue a structured `send_task` call.
`thomas/server/chat_delegation.py` validates and starts governed background work,
and `thomas/server/worker_runtime.py` runs the standard `AgentLoop`. Task Manager
is an explicit fallback path. No deterministic prose classifier owns this choice.

Live specialist registration is in
`thomas/server/routes/chat_v2_registration.py`. Registry behavior lives in
`thomas/marketplace/orchestrator/registry.py`, and implementations live under
`thomas/marketplace/specialists/`.

## Memory Paths

Start with `thomas/memory/store.py` and `thomas/memory/v2/`. Trace the configured
store and caller before editing persistence. Do not infer a live implementation
from a filename remembered from an older architecture.

## Cache and Restart

After changing Python, stop the foreground server with `Ctrl+C`. Clear only
bytecode under the checked-out `thomas/` package, then restart the Click
`thomas serve` surface.

Windows PowerShell:

```powershell
Get-ChildItem -LiteralPath thomas -Recurse -File -Filter *.pyc | Remove-Item -Force
.\.venv\Scripts\python.exe -m thomas serve
```

POSIX shell:

```bash
find thomas -type f -name '*.pyc' -delete
.venv/bin/python -m thomas serve
```

Do not kill every Python process on the machine; other Thomas tasks and unrelated
applications may be using Python. After JavaScript or CSS changes, hard-refresh
the affected page (`Ctrl+Shift+R` on Windows/Linux; `Cmd+Shift+R` on macOS).

## Verification Checklist

Before handing off a change:

1. **Entrypoint:** Did you identify the caller that executes the edited file?
2. **Manifest/import:** Is the file declared or imported by that caller?
3. **No duplicate path:** Did you search for an existing implementation first?
4. **No invented parts:** Did you avoid new `*_part*.py` files and exec loaders?
5. **Frontend correspondence:** Does `RUNTIME_SCRIPTS` correspond one-to-one with
   the tracked JavaScript files under `thomas/server/web/js/runtime/`?
6. **Chat ownership:** Does natural-language meaning remain with the frontier
   model and structured capability call?
7. **Focused proof:** Did the targeted tests and relevant runtime proof pass?
8. **Cache discipline:** Did you use the platform-specific project bytecode
   cleanup above before testing?
9. **Counts:** Does the verification report say how many documents, links,
   source paths, manifest entries, files, and tests it examined?

## Quick Reference

| Change | Source of truth |
|---|---|
| Chat route and model capabilities | `thomas/server/routes/chat_v2.py` |
| Chat route/specialist registration | `thomas/server/routes/chat_v2_registration.py` |
| Model orchestration | `thomas/marketplace/orchestrator/brain.py` |
| Background delegation | `thomas/server/chat_delegation.py` |
| Worker execution | `thomas/server/worker_runtime.py` and `thomas/agent/loop.py` |
| Runtime JavaScript | `RUNTIME_SCRIPTS` in `thomas/server/web/js/app_runtime_loader.js` |
| Direct browser assets | `thomas/server/web/index.html` |
| Design tokens | `thomas/server/web/css/tokens.css` |
| Component CSS | `thomas/server/web/css/component_styles/` |
| Layout CSS | `thomas/server/web/css/layout_styles/` |
| Memory | `thomas/memory/store.py` and `thomas/memory/v2/` |
| Crew task manager | `scripts/crew/tasks/manager.py` and its named imports |

The focused regression contract for this document is
`tests/test_documentation_truth.py`.
