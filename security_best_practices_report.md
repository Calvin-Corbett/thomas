# Security Best Practices Report

Date: 2026-02-11
Scope: `thomas/` runtime code and related tests

## Executive Summary

No critical or high-severity issues remain after remediation.  
Auth handling, secret persistence, token accounting, and outbound timeout behavior were hardened.  
Dynamic SQL construction hotspots were refactored to allowlisted/static query patterns, clearing previous medium scanner findings.
Low-severity scanner noise from silent exception handlers/asserts was reduced with explicit logging/guards, and intentional subprocess call sites were annotated.

## Remediated Findings

### SBP-001 (High) Timing-safe API token validation and safer default API exposure
Impact: Non-constant token checks and no-token deployments increase abuse risk for autonomy APIs.

- Fixed token comparison using `hmac.compare_digest` in `thomas/autonomy/api.py:84`.
- Added explicit loopback-only middleware when no token is configured in `thomas/autonomy/api.py:91` and wired in `thomas/autonomy/api.py:117`.
- Added auth regression coverage in `tests/test_autonomy_api.py:57` and `tests/test_autonomy_api.py:86`.

### SBP-002 (Medium) Anthropic token accounting under-reported prompt usage
Impact: Token telemetry drift across tasks can hide context pressure and cost signals.

- Added Anthropic usage extraction for both top-level and nested usage payloads in `thomas/core/llm.py:244`.
- Accounted for input, output, and cache token fields before emitting final usage in `thomas/core/llm.py:500` and `thomas/core/llm.py:545`.
- Added regression tests in `tests/test_llm_anthropic_usage.py:55` and `tests/test_llm_anthropic_usage.py:82`.

### SBP-003 (Medium) Secret file persistence permissions hardening
Impact: Persisted key material should be private to the running user wherever possible.

- Added best-effort private permissions for persisted secret files in `thomas/server/secrets.py:134`.
- Applied permission hardening on temp and final files in `thomas/server/secrets.py:129` and `thomas/server/secrets.py:131`.

### SBP-004 (Medium) Unbounded HTTP client timeout during local model pulls
Impact: Unlimited connect/write timeout can cause stuck resource consumption.

- Replaced `timeout=None` with bounded connect/write/pool and unbounded read streaming in `thomas/server/app.py:582`.

### SBP-005 (Low) Prompt/token overhead cleanup
Impact: Redundant prompt context and inconsistent memory token estimate increase avoidable token usage.

- Removed duplicate context fields in system prompt at `thomas/agent/loop.py:146`.
- Switched memory token estimation to shared token estimator in `thomas/agent/loop.py:601`.

### SBP-006 (Low) Hashlib weak-hash scanner hardening
Impact: Security scanners flagged MD5/SHA1 usage even though use is non-cryptographic.

- Marked MD5 feature hashing as non-security usage in `thomas/memory/embedder.py:55`.
- Marked SHA1 helper as non-security usage in `thomas/realtime/utils.py:17`.

### SBP-007 (Medium) Dynamic SQL construction hardening
Impact: Runtime query generation can drift into injection-prone patterns over time.

- Replaced dynamic `UPDATE ... SET` builder with fixed `CASE WHEN` update in `thomas/autonomy/store.py:387`.
- Replaced dynamic `IN (...)` SQL fragments with `json_each(?)` membership and fallback-safe lookups in:
  - `thomas/memory/store.py:240`
  - `thomas/memory/store.py:613`
  - `thomas/memory/store.py:642`
  - `thomas/memory/store.py:737`
- Replaced dynamic thread-settings and packs filters with static allowlisted SQL branches in:
  - `thomas/memory/v2/fabric.py:151`
  - `thomas/memory/v2/fabric.py:863`
- Replaced dynamic run-list query assembly with fixed optional-filter SQL in `thomas/observability/run_store.py:129`.

### SBP-008 (Low) Silent-failure and assertion hardening
Impact: Silent exception swallowing and runtime `assert` usage can hide operational faults and weaken diagnostics.

- Replaced production `assert` checks with explicit runtime guards in:
  - `thomas/codex/bridge.py:492`
  - `thomas/memory/__init__.py:57`
  - `thomas/memory/embedder.py:77`
  - `thomas/agent/swarm.py:292`
- Replaced broad `except ...: pass` paths with explicit debug logging in:
  - `thomas/server/app.py:614`
  - `thomas/server/secrets.py:112`
  - `thomas/memory/v2/fabric.py:500`
  - `thomas/models/discovery.py:145`
  - `thomas/upgrade/doppelganger.py:149`
  - `thomas/cli/main.py:532`
  - `thomas/cli/repl.py:161`
- Updated autonomy retry jitter to use `secrets.randbits` in `thomas/autonomy/models.py:46` to eliminate non-crypto RNG scanner noise.

## Residual Findings

No Bandit findings remain in scope (`bandit -r thomas -q -l` clean on 2026-02-11, plus `-ll` and `-lll` clean).
