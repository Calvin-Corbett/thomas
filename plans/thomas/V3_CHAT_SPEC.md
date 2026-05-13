# Thomas V3 Chat System Spec

## The Vision

Thomas is the fast, friendly chat layer. He replies instantly. When work needs to happen, he picks a bot from the official roster — a named character like Trey, Brandon, Nova, or Pixel — and that bot spawns into the chat through a portal to show it's working. The user can keep talking to Thomas the entire time. Multiple bots can work simultaneously, each visible by name in the chat.

The virtual office where bots walk around, go to rooms, do stuff like fishing and lifting weights — that's a separate future feature. V3 is about making the bots visible **in the chat** when they're active on tasks.

## The Bot Roster

Thomas has 12 named bots that live in his system. When Thomas delegates a task, he picks from this roster — not generic names like "Reasoning Agent":

| Bot | Color | Costume | Specialty |
|-----|-------|---------|-----------|
| Brandon | Blue | Visor | General |
| Trey | Green | Headset | Research |
| Zach | Orange | Cap | Engineering |
| Matt | Pink | Bowtie | Design |
| Taylor | Purple | None | Analysis |
| John | Yellow | Visor | Support |
| Nova | Blue | Cap | Research |
| Pixel | Green | Headset | Creative |
| Byte | Purple | Bowtie | Data |
| Orbit | Blue | None | Ops |
| Echo | Green | Visor | Comms |
| Glitch | Orange | Cap | Debug |

The roster lives in `OFFICE_AGENT_SEEDS` in the runtime JS and `virtual_office_roster.py` in Python.

## What Changes vs V2

| Aspect | V2 (Current) | V3 (New) |
|--------|-------------|----------|
| User sends message | Thomas blocks until done | Thomas replies instantly, bots work in background |
| Multiple messages | Kills current generation | Queue alongside, Thomas stays responsive |
| Agent visibility | Hidden, generic "Reasoning" badge | Named bot spawns in chat with portal animation |
| Response streaming | All-or-nothing chunked text | Real-time token-by-token as bots produce it |
| Bot identity | "reasoning", "coding", "research" | Trey, Brandon, Nova — real characters |
| Thinking | Duplicated inline text | Expandable block per bot, click to see details |
| Conversation context | System prompt leaks, truncated | Clean context, full history, filtered |
| Frontend | 41K line monolith | Modular components |

## How It Works in Chat

### User sends a casual message
```
User: yo what's up
Thomas: not much, what's going on?
```
No bots. No delegation. Just Thomas being Thomas.

### User sends an actionable message
```
User: research [REDACTED-NAME] from [REDACTED-TOWN] Texas

Thomas: On it.

    ┌──🟢── Portal opens ──────────────────┐
    │ 🤖 Nova spawned                       │
    │ Task: Research [REDACTED-NAME]            │
    │ ▸ Thinking... (click to expand)       │
    │                                       │
    │ Nova: Found some results. Trey        │
    │ Corbett appears to be...              │
    │ [streaming response]                  │
    └───────────────────────────────────────┘
```

### Multiple bots working simultaneously
```
User: research the company AND write me an email draft

Thomas: Got it — sending Nova on the research and Echo on the draft.

    ┌──🟢── Nova ──────────────────────────┐
    │ Task: Research the company             │
    │ ▸ Thinking...                         │
    │ [streaming...]                        │
    └───────────────────────────────────────┘
    ┌──🟢── Echo ──────────────────────────┐
    │ Task: Draft email                      │
    │ ▸ Thinking...                         │
    │ [streaming...]                        │
    └───────────────────────────────────────┘
```

### User keeps chatting while bots work
```
    ┌── Nova working... ───────────────────┐
    │ [still streaming research results]    │
    └───────────────────────────────────────┘

User: also what's for lunch today

Thomas: idk but I could go for tacos right now

    ┌── Nova done ─────────────────────────┐
    │ Here's what I found about...          │
    └───────────────────────────────────────┘
```

Thomas answers casual messages instantly even while bots are working.

## Bot Spawn Animation in Chat

When Thomas picks a bot for a task:
1. Portal animation plays in the chat (CSS already exists — `chat-robot-portal` with cyan glow, rotation, scale)
2. Bot appears with its name, color, and costume indicator
3. "Thinking..." appears as an expandable block
4. Response streams token-by-token below the bot card
5. When done, bot card collapses to a summary line

## What Gets REUSED from V2 (80% of the backend)

All production-ready, no changes needed:

- **ConversationManager** (`thomas/chat/conversation.py`) — immutable, copy-on-write
- **SessionStore** (`thomas/chat/session_store.py`) — atomic saves, debounced
- **EventDispatcher** (`thomas/chat/event_stream.py`) — NDJSON streaming
- **ThinkingTracker** (`thomas/chat/thinking.py`) — per-phase timing
- **MemoryCoordinator** (`thomas/chat/memory_layers.py`) — 3-layer memory
- **SpecialistRegistry** (`thomas/orchestrator/registry.py`) — capability lookup
- **SpecialistProtocol** (`thomas/orchestrator/protocol.py`) — contracts, tokens
- **BaseSpecialist** (`thomas/specialists/base.py`) — event streaming pattern
- **All 5 specialists** — reasoning, coding, research, synthesis, tools
- **dispatch.py** — instant casual/actionable classification
- **Portal CSS animation** — already built, just needs wiring
- **Bot roster** — `OFFICE_AGENT_SEEDS` with all 12 named bots

## What Gets REBUILT

### 1. Orchestrator Brain — Bot-Aware Async Dispatch

Current brain picks a "specialist" (reasoning, coding, etc.). V3 brain picks a NAMED BOT from the roster AND a specialist type. The bot is the character, the specialist is the capability.

```
User message
    │
    ├── dispatch.py: casual or actionable?
    │
    ├── CASUAL → Thomas replies directly (no bot)
    │
    └── ACTIONABLE:
        ├── Thomas replies immediately
        ├── Pick specialist type (reasoning, coding, research...)
        ├── Pick a bot from roster for that specialty
        ├── Emit "agent_start" event with bot name + portal
        ├── Specialist executes in background
        ├── Bot streams results in chat
        └── User keeps chatting the whole time
```

### 2. Event Schema (V3)

```json
{"type": "ack", "text": "On it."}

{"type": "bot_spawn", "bot_id": "nova", "bot_name": "Nova", "bot_color": "#4fc3f7", "bot_costume": "cap", "task": "Research [REDACTED-NAME]", "specialist": "research"}

{"type": "bot_thinking", "bot_id": "nova", "text": "Searching for information..."}

{"type": "bot_text", "bot_id": "nova", "text": "Found some results. "}

{"type": "bot_tool", "bot_id": "nova", "tool": "web_search", "query": "[REDACTED-NAME] [REDACTED-TOWN] Texas"}

{"type": "bot_done", "bot_id": "nova", "content": "full response", "elapsed_ms": 3200}

{"type": "done", "session_id": "...", "bots_used": ["nova"]}
```

### 3. Frontend Modules

```
thomas/server/web/js/v3/
├── chat-core.js          — Message sending, NDJSON stream parsing, multi-message queue
├── chat-renderer.js      — Renders messages, bot cards, portal animations
├── chat-composer.js       — Input box, always-on, never locked
├── chat-bots.js           — Bot roster, spawn logic, expandable thinking
├── chat-streaming.js      — Token-by-token text rendering per bot
└── chat-init.js           — Bootstraps everything
```

### 4. Bot-to-Specialist Mapping

The roster maps bots to specialties. When the brain picks "research" as the specialist type, it randomly picks from bots tagged for research (Nova or Trey). This gives variety — not always the same bot for the same task type.

```python
SPECIALTY_TO_BOTS = {
    "reasoning": ["Brandon", "Taylor", "John"],
    "coding": ["Zach", "Glitch", "Byte"],
    "research": ["Nova", "Trey", "Echo"],
    "synthesis": ["Pixel", "Matt"],
    "tools": ["Orbit", "Zach"],
}
```

## File Size Guidelines

No hard 500-line limit. Real code varies. Guidelines:

- **Soft limit: 800 lines** — If a file crosses this, consider if it should be split. Maybe it should, maybe it shouldn't. Use judgment.
- **Hard limit: 2,000 lines** — If a file hits this, it MUST be split. No single file should be this big in V3.
- **Monolith threshold: 5,000+ lines** — This is what V2's 41K monolith is. Never again.

The monolith guard script (`scripts/forge/gates/monolith_guard.py`) already enforces limits. V3 files just need to stay reasonable.

## Implementation Phases

### Phase 1: Backend (1 week)
- `thomas/server/routes/chat_v3.py` — V3 endpoint
- `thomas/orchestrator/brain_v3.py` — Async dispatch with bot selection
- `thomas/orchestrator/bot_roster.py` — Bot-to-specialist mapping
- New event types for bot spawn/thinking/text/done
- Multi-message queue in endpoint
- Clean conversation context (no system prompt leaks)

### Phase 2: Frontend (1-2 weeks)
- `thomas/server/web/js/v3/` module directory
- Bot cards with portal spawn animation
- Expandable thinking blocks per bot
- Token-by-token streaming per bot
- Always-enabled composer
- Multiple simultaneous bot cards
- `thomas/server/web/v3.html` — V3 chat page

### Phase 3: Polish (3-5 days)
- Bot personality (each bot has slightly different speech style)
- Memory display
- Tool execution visualization
- Error recovery (retry buttons)
- Mobile responsive

### Phase 4: Future — Virtual Office
- Full office with rooms, navigation, pathfinding (code already exists)
- Bots walk to rooms matching their task type
- Click/drag bots, watch them interact
- Portal spawns from chat carry over to office view
- This is a separate phase, not part of V3 chat

## Migration

- V2 stays live at `/api/v2/chat`
- V3 launches at `/api/v3/chat`
- Feature flag: `window.__THOMAS_CHAT_V3__`
- New sessions default to V3 when ready
- Old sessions load in V2 mode
- 41K monolith stays untouched — V3 frontend is separate modules
