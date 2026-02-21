# FR-001 — Agent Door & Sprite Alerts

**Source:** Voice (Calvin)  
**Status:** Idea / Backlog

---

## Summary
On the left side of the chat UI, there's an animated door. Agent sprites (tied to the Virtual Office agents) can open the door and run out onto the UI to alert Calvin about something. Every notification is delivered by a sprite — not a boring toast or banner.

---

## Behavior Flow

1. **Door opens** — animated, on the left edge of the chat UI (above the chat bar)
2. **Sprite bounces out** — cute, bouncy idle animation while on screen
3. **Speech bubble pops up** — *"Hey Calvin, [this just happened]..."*
   - Includes a CTA: **"Click me to take action"** or **"Click me to go there now"**
4. **On click — Mouse Grab sequence:**
   - Sprite grabs the user's mouse cursor (cursor visually "pauses" / gets grabbed)
   - Sprite walks/drags the cursor back toward the door
   - Feels like the agent is physically *taking you* somewhere
   - Door opens, sprite walks through with cursor
   - App navigates to the target page (e.g. Virtual Office / agent detail)
5. **Hang-out mode (optional):**
   - Sprite can stay on screen, watch the conversation, react in real time
   - e.g. *"Whoa Calvin, what are you thinking about?"*

---

## Key Details

- Every notification = a sprite visit. No boring alerts.
- Sprites are bouncy, cute, personality-driven — people will love them
- The "mouse grab" on click is the signature interaction — sprite grabs cursor and walks you through the door
- These are **local bots** — same characters that live in the Virtual Office
- Overlaid on the UI, above the chat bar, non-blocking

---

## Technical Notes (mouse grab)
- CSS `cursor: none` + custom animated cursor element that snaps to sprite position on click
- Sprite plays a "grab" animation, then a walk-back animation toward the door
- On animation end → `router.push()` to target route
- Cursor restored after navigation

---

## Open Questions
- Trigger conditions: task complete, anomaly, threshold crossed, agent wants to say something?
- Max sprites on screen at once?
- Can Calvin click sprite mid-hang to open a chat with that specific agent?
