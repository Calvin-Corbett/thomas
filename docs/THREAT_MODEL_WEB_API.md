# Web/API Threat Model (Baseline)

Date: 2026-03-29  
Last reviewed: 2026-08-12  
Cadence touch on 2026-08-12: a real review, not a metadata refresh — 597 commits landed since the prior touch, the largest gap this document has had. Findings, all verified rather than reasoned about: (1) **Gateway authentication was enforced on 1 of 27 gateway routes.** `p136_gateway_auth_policy_enforcement` was correct but missing from both the import list and the registration tuple in `thomas/server/routes/gateway/__init__.py`, so it never ran; the other 26 routes were unauthenticated. Fixed, `/v1/gateway` added to its prefixes, and confirmed with wrong-token probes in both directions. (2) **The SSRF guard validated only the first URL and then followed redirects anywhere.** `validate_public_url` correctly refuses private, loopback and link-local addresses — including the metadata endpoint at 169.254.169.254 — but two plugin-store call sites ran their client with `follow_redirects=True`, so a `Location` header could walk the request back to an address the guard had already refused. Both take a caller-supplied `store_url`. Fixed with `request_validated`/`request_validated_async`, which re-run the guard on every hop; mutation-tested. (3) **New surfaces added since the last review** — `/api/system-map`, `/api/landing-health`, `/agent-ops`, `/system-map` — were checked individually: both API routes call `_require_api_access`; both page routes serve a static shell only, with all data arriving through the authenticated API. (4) **112 open CodeQL alerts** (5 critical, 88 high, 19 medium), 101 of them in shipped code. The 5 critical are `py/full-ssrf` at the two sites above and are largely false positives — CodeQL does not model `validate_public_url` as a sanitizer — but reading them is what surfaced finding (2), which CodeQL had not articulated. The remaining high/medium backlog (`py/path-injection` ×51, `py/stack-trace-exposure` ×17, `py/clear-text-storage-sensitive-data` ×8) is **not triaged and is carried into the next review as open work.** Mutating-route policy remains green; the 3 webhook exceptions were re-reviewed 2026-07-18 and expire 2026-10-18.  
Cadence touch on 2026-06-26: release-hygiene/security-audit review. `python scripts/security_audit.py --repo-root . --json --strict` reported only this document's stale cadence as the high-severity release blocker before this review; mutating-route policy remained green with 186 routes and 3 approved webhook exceptions. No threat-model content changes were required for this release-hygiene metadata fix.  
Cadence touch on 2026-05-19: no security-relevant code changes since prior review (Praxis rename arc was structural reorganization only — no new attack surface, no auth/authz logic changes, no new public endpoints).  
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
