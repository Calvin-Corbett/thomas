# Thomas Web UI Upgrade Plan

> Canonical plan path: `plans/thomas/ui/UI_UPGRADE_PLAN.md`
> Legacy pointer file: `PLAN-UI-UPGRADE.md`

## Context
The Thomas web UI has solid foundations (clean design system, good component library, responsive layout) but suffers from **UX clutter and fragmentation**:
- The Settings modal is a 900-line monolith — 7 unrelated sections in one scroll
- Model management is split across **3 different modals** (Model Picker, Models Manager, Settings providers)
- The header packs too many controls without explanation (mode toggle labels are cryptic)
- New users land on a blank chat with no guidance
- The mic/voice button looks basic — no visual feedback for voice mode, no Gemini-style "lock mic on" UX
- Composer area (send button, mic, attach) needs visual polish to feel professional

This plan reorganizes the UI to be intuitive, professional, and decluttered.

---

## Phase A: Settings Tabs (foundation — do first)

### 1. Extend `createModal()` to support wide modals
**File**: `thomas/server/web/js/components.js`
- Add optional `wide` param to `createModal()` — when true, adds `.modal-wide` class

**File**: `thomas/server/web/css/components.css`
- Add `.modal-wide { width: min(92vw, 720px); }`

### 2. Refactor Settings into tabbed layout
**File**: `thomas/server/web/js/settings.js` (893 lines → restructure)

Replace the single scrolling `<div>` body with **6 tabs** using the existing `createTabs()` from `components.js` (currently unused):

| Tab | Content (existing code, moved into panels) |
|-----|---------------------------------------------|
| **Appearance** | Theme toggle, GPU VRAM input, Inspector default |
| **Providers** | API key management — search, filter, test-all, provider cards |
| **Models** | NEW unified model management (Phase C) |
| **Prompts** | Prompt library — search, add, edit, delete |
| **Voice** | TTS/STT, conversation mode, rate, voice select |
| **About** | Version info |

- Accept `initialTab` parameter: `openSettings('models')` opens directly to Models tab
- Export `openSettings` so other modules can call it with a specific tab
- Use wide modal variant for more breathing room
- All existing section rendering code stays identical — just moves into tab panel containers

---

## Phase B: Header & Sidebar Cleanup

### 3. Add tooltips to mode toggle
**File**: `thomas/server/web/index.html` (lines 91-95)
- Add `tooltip tooltip-below` class + `data-tooltip` to each mode button:
  - fast: "Quick responses, skip deep reasoning"
  - auto: "Auto-decide when to reason deeper"
  - think: "Extended reasoning, slower but thorough"

**File**: `thomas/server/web/css/components.css`
- Add `.tooltip-below::after { bottom: auto; top: calc(100% + 6px); }` variant

### 4. Subtle status chip when connected
**File**: `thomas/server/web/css/layout.css` (lines 323-326)
- When status is "ready" (`.status-chip.connected`), reduce to just a green dot + muted text with transparent background — common state shouldn't compete for attention

### 5. Remove "Models" button from sidebar footer
**File**: `thomas/server/web/index.html` (lines 62-64) — remove the `modelsBtn` element
**File**: `thomas/server/web/js/sidebar.js` (lines 49-50) — remove dead icon-wiring code

Sidebar footer goes from 3 buttons → 2 (Settings + Help). Model management lives in Settings > Models tab.

---

## Phase C: Unified Model UX

### 6. Create unified models module
**File**: `thomas/server/web/js/models-unified.js` (NEW)

Combines logic from `model-picker.js` (373 lines) + `models-manager.js` (461 lines). Exports:

- **`renderModelsTab(container)`** — Full model management UI for the Settings "Models" tab:
  - Active model display bar (current profile + model)
  - Profile chips row (color-coded by connection status)
  - Available models list for selected profile (from models-manager `renderAvailable`)
  - Recommended local models + Pull UI with progress (from models-manager `renderRecommended`)
  - Search bar filtering both lists
  - Uses rich model cards with VRAM badges, tags, quality stars (from model-picker `renderModelCard`)

- **`openQuickModelPicker()`** — Lightweight modal for fast model switching (what header indicator opens):
  - Profile chips at top
  - Search + model cards for current profile
  - Click to select and close
  - Footer link: "Manage all models..." → opens `openSettings('models')`

Shared logic extracted once (currently duplicated in both files):
- `ensureHandshake()`, `getHandshake()`, `setHandshake()`, `refreshDiscovered()`

### 7. Wire up the new module
**File**: `thomas/server/web/js/app.js`
- Replace `initModelPicker()` + `initModelsManager()` with `initModelsUnified()`
- Header `modelIndicator` click → `openQuickModelPicker()`

---

## Phase D: Welcome Screen & Polish

### 8. Rich empty state with quick-action cards
**File**: `thomas/server/web/js/chat.js`

Replace the basic empty state with a welcome screen:
- Title: "What can I help with?"
- Subtitle: brief description
- 4 quick-action cards in a responsive grid:
  - "Debug code" → pre-fills composer
  - "Explain a file" → pre-fills composer
  - "Set up providers" → opens Settings > Providers tab
  - "Keyboard shortcuts" → opens command palette
- Keyboard shortcut hint: "Ctrl+K opens the command palette"

### 9. Command palette: add Models action
**File**: `thomas/server/web/js/command-palette.js`
- Add "Models & Providers" action that opens `openSettings('models')`

### 10. CSS polish
**File**: `thomas/server/web/css/components.css`
- Tab panel fade-in animation (`.tab-panel.active` uses existing `fadeIn` keyframe)
- Consistent card spacing in modals: `.modal-body .card + .card { margin-top: var(--space-2); }`

---

## Phase E: Voice Mode & Composer Polish

### 11. Voice mode visual overhaul
**Files**: `thomas/server/web/js/composer.js`, `thomas/server/web/css/layout.css`

The voice logic already exists (STT via SpeechRecognition, continuous mode, auto-send, TTS loop).
The problem is purely visual — the mic button just turns red when active. No "voice mode" feel.

**Changes to `composer.js`**:
- When voice conversation mode activates (`_voiceSessionActive = true`), add class `.voice-mode` to the composer element
- Show a **voice overlay** inside the composer area that replaces the textarea:
  - Animated pulsing mic circle (CSS animation, similar to Gemini's breathing circle)
  - Current state text: "Listening..." / "Thinking..." / "Speaking..."
  - Live transcript preview (the interim STT text already exists in `_sttInterimText`)
  - A "Stop" button to end voice conversation
- When voice mode is off, composer looks normal

**New CSS in `layout.css`**:
```css
/* Voice mode overlay */
.composer.voice-mode .composer-textarea { display: none; }
.composer.voice-mode .composer-actions { display: none; }

.voice-overlay {
  display: none;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
}
.composer.voice-mode .voice-overlay { display: flex; }

.voice-circle {
  width: 64px; height: 64px;
  border-radius: 50%;
  background: var(--accent);
  display: flex; align-items: center; justify-content: center;
  animation: voicePulse 1.5s ease-in-out infinite;
  cursor: pointer;
  transition: all 0.2s ease;
}
.voice-circle.listening { background: var(--danger); }
.voice-circle.thinking { background: var(--warning); animation: none; }
.voice-circle.speaking { background: var(--accent); }

.voice-status { font-size: var(--text-sm); color: var(--text-secondary); }
.voice-transcript {
  font-size: var(--text-sm); color: var(--text-muted);
  font-style: italic; max-width: 500px; text-align: center;
}

@keyframes voicePulse {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(var(--accent-rgb), 0.4); }
  50% { transform: scale(1.08); box-shadow: 0 0 0 12px rgba(var(--accent-rgb), 0); }
}
```

**Voice mode entry**:
- Single click on mic → push-to-talk (existing behavior, no overlay)
- **Long-press or double-click** on mic → enters full voice conversation mode with the overlay
- Or: add a small dropdown/toggle next to mic: "Voice mode" that activates the full experience

### 12. Composer visual polish
**Files**: `thomas/server/web/css/layout.css`, `thomas/server/web/index.html`

- **Send button**: Make it slightly larger (40px), with a smooth gradient background instead of flat color. Add a subtle scale+shadow on hover.
- **Mic button**: Give it a distinct circular shape instead of generic `btn-icon`. When active (listening), show a pulsing ring animation around it.
- **Attachment buttons**: Use slightly more visible icons, add labels on hover (tooltip: "Attach file", "Attach image")
- **Composer row**: Add subtle inner shadow to the textarea wrapper for depth
- **Composer actions row**: Tighten spacing, align action icons in a visually balanced way

CSS additions:
```css
/* Polished send button */
.composer-send {
  width: 40px; height: 40px;
  background: linear-gradient(135deg, var(--accent), var(--accent-hover));
  box-shadow: 0 2px 8px rgba(13, 148, 136, 0.3);
}
.composer-send:hover:not(:disabled) {
  transform: scale(1.08);
  box-shadow: 0 4px 12px rgba(13, 148, 136, 0.4);
}

/* Mic button - circular, distinct */
#micBtn {
  width: 36px; height: 36px;
  border-radius: 50%;
  position: relative;
}
#micBtn.listening {
  color: var(--danger);
  background: var(--danger-subtle);
}
#micBtn.listening::after {
  content: '';
  position: absolute; inset: -4px;
  border-radius: 50%;
  border: 2px solid var(--danger);
  animation: voiceRing 1.2s ease-in-out infinite;
}

@keyframes voiceRing {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0; transform: scale(1.3); }
}
```

---

## Implementation Order & Dependencies

```
A1: components.js (modal-wide)  ─┐
A2: components.css (modal-wide)  ─┤
                                  ├─→ A3: settings.js (tabbed refactor) ─┐
B3: components.css (tooltip-below)┘                                      │
                                                                         ├─→ C: models-unified.js
B4: layout.css (status chip) ──── independent                            │
B5: index.html + sidebar.js ──── independent                             │
                                                                         │
D8: chat.js (welcome) ──────────── independent                           │
D9: command-palette.js ──────────── depends on settings export ──────────┘
D10: components.css (polish) ──── independent

E11: composer.js + layout.css (voice mode overlay) ──── independent
E12: layout.css + index.html (composer visual polish) ──── independent
```

## Verification
1. `thomas serve` → open http://localhost:8899
2. Click Settings → verify 6 tabs render, switching works, no data loss
3. Click header model indicator → verify quick picker opens, model switching works
4. Settings > Models tab → verify profile switching, model discovery, pull UI
5. New Chat → verify welcome screen with quick-action cards
6. Hover mode toggle buttons → verify tooltips appear below
7. Test dark mode — all new elements must respect theme tokens
8. Test responsive (< 768px) — modals and tabs must not overflow
9. Click mic → verify pulsing ring animation appears on button
10. Double-click mic (or long-press) → verify voice overlay appears with animated circle + "Listening..."
11. Speak → verify live transcript shows in voice overlay
12. Stop speaking → verify auto-send triggers, circle changes to "Thinking...", then "Speaking..."
13. Verify send button has gradient + hover animation
14. Verify attachment buttons have tooltips
