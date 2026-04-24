# Module: preferences

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (store and API work, vision goes much further)|
| Last assessed    | 2026-03-18                                             |
| Assessed by      | internal product review|
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none for current scope; vision is much bigger          |

## What This Is

User preferences storage and API. 1,600 lines across 6 files. Handles
settings persistence, API key encryption at rest, per-thread memory overrides,
and preference tool wrappers.

## Product Vision

Preferences is supposed to be **deeply tied to memory.** The full vision:

- **Background AI preference builder.** A model (cloud or local, user's choice)
  runs in the background on your conversations. It reads what you say, extracts
  the most important things, and builds a preference/profile summary of you
  automatically.
- **User chooses the model.** You can select which AI does this background
  processing — a cloud model (costs money, more capable) or a local model
  (free, private, runs on your hardware).
- **Intelligent indexing.** The background model doesn't just store key-value
  pairs. It actually organizes your information into a well-indexed,
  structured representation. It understands what matters to you.
- **Feeds into memory.** The preference profile feeds directly into the memory
  system. When Thomas retrieves context for a conversation, your preferences
  and profile inform what gets surfaced and how Thomas responds.

**This connects preferences ↔ memory ↔ the background curation pipeline.**
The `memory/curator.py` (1134 lines) already has a background promotion
pipeline. The preferences background model would be a parallel/complementary
system.

## What Actually Works

- `store.py` → monolith-loaded from `store_part01.py` + `store_part02.py` —
  SQLite-backed preference store with:
  - Durable persistence
  - API key encryption at rest (Fernet, from env key or derived from secret)
  - Safe partial updates (PATCH semantics)
  - Per-thread memory overrides (thread_preferences table)
  - Masked key display (show last 4 chars without decrypting)
  **This is real, well-documented, production code.**

- `api.py` (82 lines) — FastAPI router for GET/PATCH /api/preferences plus
  settings page serving. Real.

- `tools.py` (134 lines) — PreferencesGetTool and PreferencesSetTool for
  AI-driven preference access. Real.

## What Does NOT Exist Yet

- No background AI model processing conversations into preferences
- No model selector (cloud vs local) for background processing
- No intelligent indexing beyond key-value storage
- No automatic preference extraction from conversations
- No integration between preferences and the memory retrieval pipeline
- The preference store is "dumb" storage — it stores what you explicitly
  set, not what it learns about you

## Architecture Notes

The preference store is solid infrastructure. The gap is not in storage —
it's in the intelligence layer that would feed it. The pieces that need
to connect:

1. Conversation stream → background model (doesn't exist)
2. Background model → preference extraction (doesn't exist)
3. Extracted preferences → preference store (store exists, input doesn't)
4. Preference store → memory retrieval scoring (connection doesn't exist)
5. User UI for model selection (doesn't exist)

## Known Gaps

- No background preference extraction model
- No cloud/local model selection
- No connection to memory retrieval pipeline
- store_part01.py is 822 lines (slightly over 800 limit)
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `store_part01.py` / `store_part02.py` — The encryption and PATCH logic
  is carefully implemented. Don't change the crypto without review.
