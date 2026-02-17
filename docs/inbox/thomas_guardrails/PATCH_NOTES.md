# Thomas Guardrails — Policy Engine + Approvals + Redaction + Audit Log

This zip adds a **first-class Guardrails subsystem** using **stdlib only**, designed to be **off by default**.

## Enable Guardrails

Guardrails are disabled unless explicitly enabled via config or env:

### Option A — policy.toml (preferred)
Create: `runtime/.thomas/policy.toml`

```toml
[guardrails]
enabled = true
approval_timeout_s = 60

# Optional: force approvals for specific tools
tools_require_approval = ["shell.exec"]

# Optional: tool allow/deny lists
allow_tools = []
deny_tools = []
```

### Option B — environment variable
- Enable: `THOMAS_GUARDRAILS=1`
- Disable: `THOMAS_GUARDRAILS=0`
- Override timeout: `THOMAS_GUARDRAILS_TIMEOUT_S=90`

## What it does

- Runs every tool call through `PolicyEngine`.
- Default rules:
  - **DENY** reads under typical secret roots (e.g. `~/.ssh`, `%APPDATA%\...`, `runtime/.thomas/secrets.json`)
  - **REQUIRE_APPROVAL** for `shell.exec` and `git push`
  - **REQUIRE_APPROVAL** for filesystem mutation outside `sandbox_root`
- Redacts secrets/PII in:
  - tool results (before UI + before re-feeding model)
  - model output events (when you apply the loop patch)
  - audit log payloads
- Provides an approval broker with timeout default-deny.

## Integration (required)

This zip includes **code + route installer + UI assets**. You must wire it into:
- `thomas/core/events.py` (add TOOL_APPROVAL_* events)
- `thomas/agent/loop.py` (policy gate before tool execution)
- `thomas/server/app.py` (install approvals endpoints; create broker; create audit log; pass into agent)
- `thomas/server/static/index.html` + `main.js` (load guardrails.js and call guardrailsHandleEvent)

See `patches/` for unified diffs and `INTEGRATION_GUIDE.md` for anchor-based manual application.

## Demo approvals in UI

1) Enable guardrails and restart server
2) Ask Thomas to run a tool that triggers approval (e.g., shell.exec or write outside sandbox)
3) A modal appears with tool + args and you can Approve/Deny
4) Decision is sent to `/api/approvals/resolve` (localhost-only)

## Audit log

Audit DB stored at: `runtime/.thomas/audit.sqlite3`.

Events recorded:
- policy_decision
- approval_resolved
- tool_result

All payloads are redacted before persistence.
