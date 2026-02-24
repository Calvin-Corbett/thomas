# Web/API Threat Model (Baseline)

Date: 2026-02-22  
Last reviewed: 2026-02-22  
Scope: `thomas/server/app.py`, `thomas/server/web/**`, browser chat UI, and mutating `/api/*` routes.

## Assets

- User prompts, attachments, and chat transcripts.
- Local filesystem/tool execution capability reachable through chat/tool calls.
- Session state and workspace membership/invite data.
- API tokens and preference/config secrets.

## Trust Boundaries

- Browser UI (untrusted content stream) -> DOM renderer.
- Browser -> localhost HTTP API.
- Remote clients -> HTTP API in `access_mode=remote`.
- Server process -> local disk persistence.

## Primary Threats

1. DOM XSS through assistant/user-rendered Markdown or attachment metadata.
2. CSRF against mutating local `/api/*` endpoints from hostile web origins.
3. Session/state corruption from concurrent writers and non-atomic writes.
4. Silent data-loss on persistence corruption fallback paths.
5. CI/release bypass or deadlock due misconfigured required checks.

## Current Mitigations

- Markdown rendering now escapes raw HTML and sanitizes rendered HTML.
- Attachment names render via `textContent` (no direct HTML interpolation).
- Mutating local `/api/*` requests receive same-origin CSRF checks via middleware.
- Per-session run guards now fail fast on concurrent same-session requests across normal chat, control, batch, quick-reply, and swarm modes.
- Mutating-route policy snapshot endpoint (`/api/security/mutating-routes`) exposes route-level authz/CSRF metadata and is regression-tested against all mutating `/api/*` routes.
- Public webhook receive routes are explicitly tracked in the mutating-route policy snapshot and default to strict signature enforcement in remote mode.
- Atomic temp-file + replace state writes for core persistence.
- Workspace file corruption quarantine with backup restore attempt.
- Expanded HTTP security headers, including CSP and permissions policy.

## Abuse Cases To Regress-Test

1. Cross-site browser `POST` with `Origin: https://evil.example` and `Sec-Fetch-Site: cross-site` to mutating `/api/*`.
2. Assistant output containing executable HTML (`<svg onload=...>`) rendered in chat.
3. Attachment filename containing HTML/JS payload rendered in preview.
4. Corrupted `thomas_state.json` and workspace JSON stores during restart/load.
5. Parallel chat requests against same session ID.

## Residual Risk / Next Steps

- Add browser-level integration tests for XSS payload execution attempts.
- Expand dependency policy from baseline checks to CVE-aware severity and exception workflows.
