# Integration Guide (Repo-adaptive)

This repo isn't present in this environment, so the zip ships **unified diffs** you can `git apply`,
plus instructions for manual merges if your file structure differs.

## 1) Install approvals endpoints in aiohttp app

- Import and construct:
  - `ApprovalBroker` (singleton)
  - `Redactor` (from policy config)
  - `AuditLog` (sqlite path: runtime/.thomas/audit.sqlite3)
- Call:
  - `install_guardrails_routes(app, approvals)`

See: `thomas/server/guardrails_api.py`, `thomas/server/audit_log.py`

## 2) Gate tool execution in AgentLoop

Use `GuardedToolRunner`:

- Build/attach:
  - `PolicyEngine.from_config(load_policy_config(runtime_root))`
  - `ApprovalBroker` (shared with server)
  - `Redactor` (same instance used by audit + UI)
  - `AuditLog`
  - `GuardedToolRunner(...)`

- Replace the point where tool calls execute with:

  `result = await guarded.run(executor=..., tool_call=..., emit_event=...)`

IMPORTANT:
  - Ensure tool results are redacted before they are:
    - emitted to UI
    - appended back into the model context

See: `thomas/agent/guarded_tools.py`

## 3) UI: include guardrails.js + call handler

- Add in your main HTML:

  ```html
  <link rel="stylesheet" href="/static/guardrails.css">
  <script src="/static/guardrails.js"></script>
  ```

- In the code that handles streamed events, call:

  ```js
  if (window.guardrailsHandleEvent) window.guardrailsHandleEvent(evt.type, evt.data);
  ```

- Optional: add a timeline element:

  ```html
  <ul id="runTimeline"></ul>
  ```

## 4) Apply patches

Try:

```bash
git apply patches/*.patch
```

If it fails, open the patch and transplant the blocks marked "GUARDRAILS BEGIN/END".
