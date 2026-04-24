# Module: channels

| Field            | Value                                               |
|------------------|-----------------------------------------------------|
| Status           | scaffold (framework exists, ZERO adapters work)     |
| Last assessed    | 2026-03-18                                          |
| Assessed by      | claude-opus-4-6 (Cowork session)                    |
| Used in prod     | no — imported by production code but no adapter runs |
| Has real tests   | no real adapter tests (contract test file exists)    |
| Blocking issues  | every single channel adapter is a source placeholder |

## What This Is

The multi-channel delivery system for Thomas. Supposed to let Thomas talk
through Discord, WhatsApp, Teams, Signal, iMessage, Google Chat, Matrix,
webchat, and CLI. 10,000 lines across 37 files.

## Honest Assessment

**The framework is real:**
- `_base.py` — ChannelAdapter base class. Real abstract interface.
- `_registry.py` — ChannelRegistry for registering/looking up adapters. Works.
- `_delivery.py` — Delivery primitives. Exists.
- `_router.py` — Message routing logic. Exists.
- `tools.py` — Channel tool definitions. Exists.
- `_examples.py` — Example/reference code. Exists.
- Numbered files `p075-p096` — Channel infrastructure (provider interface,
  config schema, add/remove/login/logout commands, auth validation, throttling,
  retry/backoff, webhook bridge, delivery ack mapping, failure taxonomy,
  docs generator, contract tests, integration scaffold). These are the PLUMBING.

**EVERY SINGLE CHANNEL ADAPTER IS A PLACEHOLDER:**
- `discord.py` — **PLACEHOLDER** (source placeholder comment + padding)
- `whatsapp.py` — **PLACEHOLDER**
- `teams.py` — **PLACEHOLDER**
- `signal_adapter.py` — **PLACEHOLDER**
- `imessage.py` — **PLACEHOLDER**
- `google_chat.py` — **PLACEHOLDER**
- `matrix_adapter.py` — **PLACEHOLDER**
- `webchat.py` — **PLACEHOLDER**
- `cli.py` — **PLACEHOLDER**

**Translation: Thomas has 10,000 lines of channel infrastructure with zero
channels that actually connect to anything.** The pipes are built. Nothing
flows through them.

## Product Vision

Channels are things you add through the marketplace. If you want Discord
support, you go to the marketplace (or tell Thomas) and add it. Each
channel is a module — installable, removable, independent.

The priority order for channel support should probably be:
1. Discord — large community demand
2. Telegram — already has integration code in `thomas/integrations/telegram.py`
3. Webchat — embedded widget for websites
4. WhatsApp / Signal — messaging apps
5. Teams / Google Chat / Slack — workplace tools
6. iMessage — Apple ecosystem
7. Matrix — open protocol

## Known Gaps

- Zero working channel adapters
- All 9 adapter files are source placeholders (comment + padding bytes)
- Framework exists but has never been tested with real message delivery
- Telegram adapter exists in integrations/ but not wired through channels/
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `_base.py` / `_registry.py` — these define the adapter contract. Don't
  change the interface without checking all p075-p096 infrastructure files.
