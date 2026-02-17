# Integration Guide (Thomas)

## The contract
In Thomas, the LLM should NEVER receive plaintext secrets. Instead it passes around:
- `vault://scope/name` references
- human-readable labels (safe)
- audit receipts (safe)

## Where to integrate
### 1) Planner / Cortex
- When the model wants an API key, it requests a `SecretRef` and a **purpose** string.
- The purpose string must be stable and specific (e.g. "call OpenAI Responses API for summarizing invoice PDF").

### 2) Body / Tools
- The tool client asks the broker to `resolve` the secret by ref.
- For high/critical secrets it requires a confirm token minted by UI.

### 3) UI
- UI shows:
  - vault status, current unlock scopes, TTL, inactivity timeout
  - a button to mint confirm token for a given `ref + purpose`
  - a history view (audit log) if you choose to expose it

## Recommended purpose string format
Use a structured phrase so humans can recognize weirdness quickly:
`<toolName>: <action> for <taskId> (resource=<...>)`

Example:
`web_fetch: call OpenAI for task=invoice_summarize (resource=inv_2026_02_01.pdf)`

## DO NOT
- Do not store secrets in Thomas memory logs.
- Do not let the model generate ref names dynamically without validation.
- Do not add an HTTP route that returns secrets. Keep it IPC-only.

## Optional: two-person rule
If you have multiple admins:
- Make UI require two confirm tokens (different admin keys) for critical secrets.
This repo doesn’t implement 2-person rule, but the protocol can support it.
