# Web/API Threat Model (Baseline)

Date: 2026-03-29  
Last reviewed: 2026-06-26  
Cadence touch on 2026-06-26: reviewed current web/API release posture after the main-integration queue exposed the stale cadence gate. The aggregated security audit was rerun, mutating-route policy passed for 186 routes with the 3 expected webhook exceptions, and the active H3 non-Python promotion lane does not change web/API routes, auth/authz logic, CSRF policy, or public endpoints. Existing webhook exception reviews still expire on 2026-06-30 and remain the next dated follow-up.  
Scope: `thomas/server/app.py`, `thomas/server/web/**`, browser chat UI, mutating `/api/*` and `/gateway/*` routes, the root OpenAI-compatible `/openai-compat/*` proxy surface, and public webhook receivers.

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
- Mutating local `/gateway/*`, `/openai-compat/*`, and `/v1/*` requests receive the same API-access and CSRF middleware enforcement as the core `/api/*` surface.
- Per-session run guards now fail fast on concurrent same-session requests across normal chat, control, batch, quick-reply, and swarm modes.
- Mutating-route policy snapshot endpoint (`/api/security/mutating-routes`) exposes route-level authz/CSRF metadata and is regression-tested against all mutating `/api/*` routes.
- Public webhook receive routes are explicitly registered in the aiohttp server, tracked in the mutating-route policy snapshot, and default to provider-signature or shared-secret enforcement in remote mode.
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
