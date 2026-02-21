# FR-002 — Virtual Office Space (replaces "Mission Control")

**Source:** Voice (Calvin)  
**Status:** Idea / Backlog — needs naming + UI overhaul

---

## Summary
"Mission Control" is being retired. The replacement is a **Virtual Office Space** — a living, animated environment where AI agents exist as sprites, walk around, have names, and can be individually interacted with. This is consumer-facing and needs to feel fun, alive, and polished.

---

## Core Concept

A top-down or side-view virtual office where:
- Each AI agent is a **sprite character** with a name tag floating above them
- Sprites **walk around, hop, idle** — they feel alive
- Clicking a sprite opens an **interaction panel** (agent details, status, chat, tasks)
- The space is the "home base" that the door sprites come from (see FR-001)

---

## Current Problems with Mission Control
- UI is ugly and messy
- Repetitive elements
- Not consumer-friendly
- Doesn't feel alive or engaging
- The name "Mission Control" is generic — Calvin wants to coin something original

---

## Naming Ideas (to be decided)
Calvin wants to coin a unique word/brand for this space. Some directions:
- Something that implies a living workspace, not a control room
- Could be playful, techy, or both
- Examples to riff on: "The Hub", "The Nest", "Basecamp", "The Floor", "AgentVille", "The Grid", "Spritehaus"
- **Action:** Calvin to pick or we brainstorm a shortlist

---

## UI/UX Direction
- Animated 2D environment (pixel art or clean vector sprites)
- Agents visibly present, moving, doing things
- Name tags above each agent (hover or always-on)
- Click agent → side panel or modal with:
  - Agent name + role
  - Current task / status
  - Recent activity
  - Button to chat directly with that agent
- Ambient feel — background has subtle life (maybe other office elements, plants, desks, etc.)

---

## Research: Virtual Office / Sprite World Approaches

### Pre-built / Inspirational References
| Tool/Project | What it is | Relevance |
|---|---|---|
| **Gather.town** | Browser-based virtual office with pixel sprites | High — exact vibe, open API |
| **Workadventure** | Open-source virtual office (self-hostable) | High — can fork/customize |
| **RPG Maker tilesets** | Free/paid sprite + tileset packs | Medium — art assets |
| **Phaser.js** | HTML5 game framework, 2D sprites, tilemaps | High — build custom |
| **PixiJS** | Fast 2D WebGL renderer | High — lightweight sprite rendering |
| **LDtk / Tiled** | Level editors for 2D maps | Medium — design the office layout |
| **Itch.io asset packs** | Free/cheap pixel art office sprites | High — fast art sourcing |

### Recommended Stack for Custom Build
- **PixiJS** or **Phaser.js** for sprite rendering + animation
- **Tiled** for office map layout
- **React** wrapper to embed the canvas in the existing UI
- WebSocket or SSE for real-time agent state → sprite behavior sync

### Fastest Path to a Working Demo
1. Grab a free pixel art office tileset from itch.io
2. Use Phaser.js to render the map + agent sprites
3. Hardcode 2-3 agents walking around with name tags
4. Wire click → agent detail panel
5. Connect to real agent state via API

---

## Open Questions
- What do we call this space? (Calvin to decide/brainstorm)
- Top-down RPG style or side-scroller or isometric?
- How many agents will typically be in the office?
- Do agents visually react to their task state? (e.g. running when busy, sitting when idle)
