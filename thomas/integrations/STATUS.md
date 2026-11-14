# Module: integrations

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | wip (infrastructure real; ~10 channel adapters present, dynamically loaded)|
| Last assessed    | 2026-06-05                                             |
| Assessed by      | claude-opus-4-8 (wiring truth-up)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not assessed                                           |
| Blocking issues  | adapter functionality not individually verified end-to-end |

## What This Is

Third-party integration infrastructure plus the provider-contract channel
adapters. ~5,200 lines across 21 files. Has reliability primitives (circuit
breaker, rate limiter, retry, health checks) plus ~10+ channel adapters
(Telegram, GitHub automation, Discord, Slack, Google Chat, iMessage, Matrix,
MS Teams, Signal, WhatsApp, webchat, moltbook).

## Honest Assessment

**Infrastructure is real and solid:**
- `_circuit_breaker.py` (190 lines) — circuit breaker pattern. Real code.
- `_rate_limiter.py` (127 lines) — rate limiting. Real code.
- `_retry.py` (162 lines) — retry with backoff. Real code.
- `_health.py` (211 lines) — health check primitives. Real code.

These are good, clean utility modules that any integration can use.

**Channel adapters (~10+ provider-contract modules):**
- `telegram.py`, `github_automation.py`, `discord.py` (+ `discord_bridge_runtime*.py`),
  `slack/` (package), `googlechat.py`, `imessage.py`, `matrix.py`, `msteams.py`,
  `signal.py`, `whatsapp.py`, `webchat.py`, `moltbook.py`. Each is a real
  provider adapter; individual end-to-end functionality is not all verified.

**Dynamic loading:** adapters are loaded by name via
`thomas/marketplace/channels/_catalog.py` (`provider_module()` →
`importlib.import_module(f"thomas.integrations.{name}")`). Because the import
is dynamic, a static import scan will report these adapter modules as orphans
by design — they are not dead code.

## Product Vision (from the product owner, 2026-03-18)

The integrations module is supposed to be Thomas's **master importer**:
- Thomas should be able to read any other agentic tool's documentation,
  understand its architecture, copy what it needs, and build an integration.
- Thomas can run other tools as sub-agents — not just integrate with their
  APIs but actually operate them.
- Any agentic product's functionality should be importable into Thomas.
- This goes beyond traditional API integrations — it's about absorbing
  entire capability sets from other tools.

**This vision is currently NOT implemented.** What exists is basic
Telegram + GitHub integration with good reliability plumbing underneath.

## Known Gaps

- ~10 channel adapters exist but are not all individually verified end-to-end
- No "master importer" capability exists yet
- No ability to read/absorb other tools' architectures
- No sub-agent execution of external tools
- Telegram exists here but isn't wired through channels/ module
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `_circuit_breaker.py`, `_rate_limiter.py`, `_retry.py`, `_health.py` —
  these are clean, reusable infrastructure. Don't mess with them unless
  you have a specific bug to fix.
