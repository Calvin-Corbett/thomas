# Composer Rebuild Spec — Ground-Up Rebuild of the General Chat Composer

**Status:** Ready to build. Follow this document literally.
**Author:** mapping + spec pass, 2026-06-25
**Owner mandate:** DELETE the old composer and build a NEW, self-contained one. The
goal is to escape years of layered `!important` CSS spread across 4 files (a
green/teal line has survived ~10 patch attempts because of that cruft). The
**UI is new; the message dispatch/routing behavior must be byte-identical.**

---

## 0. The One Rule You Cannot Break

> **The send/dispatch path, the 5-dial state-var contract, and every element id
> the JS reads must survive unchanged.** This is a re-skin of the input area, not
> a rewrite of chat. If you change an id, you MUST rewire every reader of it in
> the same change. If you change `buildChatRequestPayload` output, you have failed.

Verify at the end with the **Wire Checklist (§7)**. Every box must be ticked on
the owner's actual freshly-loaded instance (restart server, hard-reload).

---

## 1. Design Target (look & feel)

Modern ChatGPT/Claude feel. One calm, unified input surface — **no box-in-a-box**.

- **One surface.** A single rounded container (sharp corners, 2–4px radius) holds
  the textarea and the action buttons. The textarea itself is **borderless and
  transparent** — it must not look like a field inside a field.
- **Native dark cockpit theme.** Dark field. Generous internal padding
  (~10–14px). No glassmorphism blur required; flat dark is fine.
- **ALL borders / rings / separators / dividers are ACHROMATIC white-alpha:**
  `rgba(255,255,255,a)` only. **Zero hue. Never** an RGB triple where channels
  differ (no `rgba(88,166,255,…)`, no teal, no green). This is the root-cause fix
  for the persistent green line — a hued low-alpha line on a dark field reads
  green via simultaneous contrast. Achromatic = it physically cannot read green.
  - Resting border: `rgba(255,255,255,0.12)`
  - Focus ring: `rgba(255,255,255,0.22)` (border) + optional `0 0 0 2px rgba(255,255,255,0.08)`
  - Hover on icon buttons: `rgba(255,255,255,0.08)` bg, `rgba(255,255,255,0.16)` border
  - Active/selected state: `rgba(255,255,255,0.14)` bg
- **Bottom action row, left→right:** Actions menu button (`…`), [mode chip when
  set], the textarea (flex-grow), then a tight right cluster: Controls (sliders),
  Mic, **Send**.
- **Send button** is the only accent: right-sized (36–40px square), solid
  light fill on dark (`#e7e9ec` bg / `#0b0f16` glyph), clearly the primary action.
  In stop-state it goes transparent with an achromatic `rgba(255,255,255,0.30)`
  border and a stop glyph.
- **5 dials tucked away.** They live ONLY behind the Controls (sliders) button,
  in a compact popover. The active **model** is shown in that popover's header
  (read-only). No always-visible subbar.
- **Spacing is generous and quiet.** Disclaimer below in small muted achromatic
  text. Status bar muted. Suggestions rail above, calm.

Do NOT introduce any new theme-scoped overrides in the legacy theme files. The
new composer owns its own look in ONE file (§4) with normal specificity — **no
`!important` wars.**

---

## 2. Files Touched (exact)

**Edit:**
- `thomas/server/web/index.html` — replace composer markup (lines ~593–688); add 1 CSS `<link>` and 1 JS `<script>`.
- `thomas/server/web/css/token_economy_space_theme.css` — DELETE composer-scoped rules (see §6).
- `thomas/server/web/css/components.css` — DELETE composer-scoped rules; KEEP shared (`.btn-icon`, icon mask-image system). (see §6)
- `thomas/server/web/css/component_styles/composer-attachments.css` — KEEP (attachment chips/thumbs/lightbox reused as-is) OR fold into new file; do not break `.attachment-chip`.
- `thomas/server/web/js/runtime/008_easy_setup_onboarding_06.js` — DELETE old composer render helpers (`ensureChatComposerControls`, `wireComposerControlsToggle`, `renderChatComposerSubbar`, `initChatComposerSubbar`, `ensureChatComposerSubbar` shim) IF AND ONLY IF the new module re-provides the same public functions and the same 5 `<select>` ids/handlers (see §5). **Do NOT touch `buildChatRequestPayload`, `resolveChatPayloadTokenEconomy`, `resolveChatPayloadReasoningEffort`, `initComposer`.**
- `thomas/server/web/js/composer_redesign.js` — DELETE its body (send-hint inject + icon MutationObserver). The new markup ships these natively, so the file becomes obsolete. Either empty it to a no-op or remove its `<script>` tag from index.html.

**Create:**
- `thomas/server/web/css/composer.css` — the ONE new stylesheet. Owns the entire composer look. Normal specificity. No `!important`.
- `thomas/server/web/js/composer_controls.js` — the ONE new behavior module (controls popover render + toggle, actions menu, mode chip, mic glue if not already in runtime). Loaded as a classic script alongside the existing runtime concat. It MUST expose the same global function names the runtime calls (`initChatComposerSubbar`, `renderChatComposerSubbar`, `wireComposerControlsToggle`, `ensureChatComposerControls`) so the rest of the runtime is untouched.

> **Do NOT** create `*_part*.py`, do not `exec()`, run `ruff` only if you touch
> Python (you won't here). All CSS/JS links use `?v=__THOMAS_WEB_BUILD__` so the
> content-hash fingerprint cache-busts them on the owner's machine.

---

## 3. New Markup (index.html, replaces lines ~593–688)

Clean semantic markup. **Every id below is load-bearing — keep exactly.**

```html
<div class="composer-container">
  <div class="composer-inner">

    <!-- Suggestions rail (above, calm) -->
    <div class="assistant-suggestion-rail hidden" id="assistantSuggestionRail">
      <div class="assistant-suggestion-head">
        <span class="assistant-suggestion-title" id="assistantSuggestionTitle">Try asking</span>
        <button class="assistant-suggestion-dismiss hidden" id="assistantSuggestionDismissBtn" type="button" aria-label="Dismiss suggestions">
          <i class="ph ph-x"></i>
        </button>
      </div>
      <div class="assistant-suggestion-bubbles" id="assistantSuggestionBubbles"></div>
    </div>

    <!-- ONE unified input surface -->
    <div class="composer-box">
      <div id="attachmentsPreview" class="attachments-preview"></div>

      <div class="composer-input-row">
        <button class="btn-icon" id="attachBtn" type="button" title="Actions menu"
                aria-expanded="false" aria-controls="composerActionPopover">
          <i class="ph ph-dots-three-outline"></i>
        </button>

        <div class="composer-mode-chip hidden" id="composerModeChip" role="status" aria-live="polite">
          <span class="composer-mode-chip-label" id="composerModeChipLabel"></span>
          <button class="composer-mode-chip-close" id="composerModeChipCloseBtn" type="button" aria-label="Clear selected mode">
            <i class="ph ph-x"></i>
          </button>
        </div>

        <textarea class="composer-textarea" id="composerTextarea" rows="1"
                  placeholder="Message Thomas…"
                  data-agent-placeholder-template="Message {{agent}}…" autofocus></textarea>

        <div class="composer-right-cluster">
          <button class="btn-icon" id="composerControlsBtn" type="button" title="Controls"
                  aria-label="Conversation controls" aria-haspopup="dialog"
                  aria-expanded="false" aria-controls="composerControlsPopover">
            <i class="ph ph-sliders-horizontal"></i>
          </button>
          <button class="btn-icon" id="micBtn" type="button" title="Use microphone">
            <i class="ph ph-microphone"></i>
          </button>
          <button class="btn-send" id="sendBtn" type="button" disabled>
            <i class="ph ph-arrow-up"></i>
          </button>
        </div>
      </div>

      <!-- Controls popover (5 dials) — emptied; filled by renderChatComposerSubbar() -->
      <div class="composer-controls-popover hidden" id="composerControlsPopover"
           role="dialog" aria-label="Conversation controls" aria-hidden="true">
        <div class="composer-controls-list" id="composerControlsList"></div>
      </div>

      <div class="composer-status-bar" id="composerStatusBar" role="status" aria-live="polite"></div>

      <!-- Actions menu (Research / Evolve / images / add files / games) -->
      <div class="composer-action-popover hidden" id="composerActionPopover" role="menu" aria-label="Quick actions">
        <div class="composer-action-column" id="composerActionList">
          <button class="composer-action-btn" type="button" data-action="research">Research</button>
          <button class="composer-action-btn" type="button" data-action="evolve">Evolve</button>
          <button class="composer-action-btn" type="button" data-action="create_image">Create image</button>
          <button class="composer-action-btn" type="button" data-action="create_video">Create video</button>
          <button class="composer-action-btn" type="button" data-action="create_song">Create song</button>
          <button class="composer-action-btn" type="button" data-action="add_files">Add files</button>
          <button class="composer-action-btn has-submenu" type="button" data-action="games" aria-expanded="false">Games <i class="ph ph-caret-right"></i></button>
        </div>
        <div class="composer-games-column hidden" id="composerGamesColumn" aria-label="Game options">
          <div class="composer-games-title">Playable now</div>
          <button class="composer-game-btn" type="button" data-game="cloud_jump">Cloud Jump</button>
          <button class="composer-game-btn" type="button" data-game="jetpack_joyride">Jetpack Joyride</button>
          <button class="composer-game-btn" type="button" data-game="dino_run">Dino Run</button>
          <div class="composer-games-empty">More arcade modes will appear here as they ship.</div>
        </div>
      </div>

      <!-- Dino game overlay (keep verbatim — game runtime reads these ids) -->
      <section class="composer-dino-shell hidden" id="composerDinoShell" aria-label="Dino Run game area">
        <canvas class="composer-dino-canvas" id="composerDinoCanvas" width="760" height="214" aria-label="Dino Run game canvas"></canvas>
        <div class="composer-dino-hud" id="composerDinoHud">
          <div class="composer-dino-score-line composer-dino-score-high">
            <span class="composer-dino-score-label">High</span><strong id="composerDinoHighScore">0</strong>
          </div>
          <div class="composer-dino-score-line composer-dino-score-live">
            <span class="composer-dino-score-label">Score</span><strong id="composerDinoScore">0</strong>
          </div>
        </div>
        <p class="composer-dino-status" id="composerDinoStatusText">Press Space to start | Esc to exit</p>
        <div class="chat-game-portal hidden" id="chatGamePortal" aria-hidden="true">
          <span class="chat-game-portal-ring"></span>
          <span class="chat-game-portal-ring ring-inner"></span>
          <span class="chat-game-portal-core"></span>
        </div>
      </section>
    </div>

    <div class="disclaimer" id="composerDisclaimer"
         data-agent-template="{{agent}} can make mistakes. Consider verifying important information.">
      Thomas can make mistakes. Consider verifying important information.
    </div>
  </div>
</div>
```

**index.html `<head>` — add the new stylesheet** (after `components.css`, line ~23, so it can override base structure without `!important`):
```html
<link rel="stylesheet" href="/static/css/composer.css?v=__THOMAS_WEB_BUILD__">
```
Place it LAST among composer-relevant sheets (after `token_economy_space_theme.css`, ~line 28) so source order alone wins — that is what removes the need for `!important`.

**index.html `<body>` scripts** — replace the `composer_redesign.js` line (865) with:
```html
<script src="/static/js/composer_controls.js?v=__THOMAS_WEB_BUILD__"></script>
```
(Load it BEFORE `app_runtime_loader.js` so its globals exist when the runtime's `initChatComposerSubbar()` runs.)

---

## 4. New Stylesheet (`css/composer.css`) — requirements

Self-contained. Normal specificity. **No `!important`.** Achromatic only.

Must style (own contracts):
- `.composer-container` — wrapper, dark gradient/flat bg, generous padding, safe-area inset bottom.
- `.composer-box` — the ONE surface: dark bg (`#101216`-ish), `border:1px solid rgba(255,255,255,0.12)`, radius 4px. `:focus-within` → `border-color:rgba(255,255,255,0.22)`. NO inner frame.
- `.composer-input-row` — flex, `align-items:flex-end`, gap ~6px.
- `.composer-textarea` — `background:transparent; border:0; color:#ececf1; resize:none;` autosize via JS, `max-height:160px; overflow-y:auto`. Placeholder muted achromatic.
- `.composer-right-cluster` — flex, gap 4px, align-items center.
- `.btn-icon` overrides for composer context ONLY (size 32px, radius 4px, transparent bg, hover `rgba(255,255,255,0.08)`). **Do not redefine global `.btn-icon` behavior** — scope your rule under `.composer-box .btn-icon` so you don't disturb sidebar/nav usage.
- `#sendBtn` (`.btn-send`) — 38px square, radius 4px, `background:#e7e9ec; color:#0b0f16`. `.stop-state` → `background:transparent; border:1px solid rgba(255,255,255,0.30); color:#ececf1`. Disabled → dim, not-allowed.
- `#composerControlsBtn.active`, `#attachBtn.active` — `background:rgba(255,255,255,0.14)` (achromatic — replaces the old blue `rgba(88,166,255,0.2)`).
- `.composer-controls-popover` — absolute, `right:8px; bottom:calc(100% + 8px)`, z-index 36, width `min(300px,calc(100vw-24px))`, dark bg, `border:1px solid rgba(255,255,255,0.14)`, radius 4px.
- `.composer-controls-head` / `.composer-controls-title` / `.composer-controls-model` (`#tcsModelReadout`) — header row, model name muted on the right.
- `.composer-control-row` — label + select per dial; `.is-active` → slightly brighter (achromatic).
- `.composer-control-select` — dark, `border:1px solid rgba(255,255,255,0.14)`; `:focus` → `border-color:rgba(255,255,255,0.32)`, `box-shadow:0 0 0 2px rgba(255,255,255,0.10)`.
- `.composer-action-popover` — absolute, `left:6px; bottom:calc(100% + 8px)`, z-index 35 (below controls popover). `.composer-action-btn` hover/active achromatic. `.composer-games-column`, `.composer-game-btn`, divider `border-left:1px solid rgba(255,255,255,0.12)`.
- `.composer-mode-chip` — inline-flex pill, `border:1px solid rgba(255,255,255,0.22)` (achromatic — was blue), ellipsis truncation, close button.
- `.composer-status-bar` — flex, gap 6px, small, `color:rgba(255,255,255,0.45)`.
- `.disclaimer` — small, `color:rgba(255,255,255,0.20)`, letter-spacing, uppercase.
- `.composer-dino-shell` (+`.is-open`, `.phase-*`), `.composer-dino-*` — keep the opacity/scale animation; recolor any hued borders to achromatic.
- `.attachments-preview` / `.attachment-chip` — if not kept in `composer-attachments.css`, define here; achromatic borders.
- `.composer-drop-overlay` (+`.visible`) — drag overlay (created by `initComposer` in runtime); style it achromatic.
- `.assistant-suggestion-rail` / `-bubbles` / `.suggestion-chip` — calm, achromatic.

**Icon mask-image system stays in `components.css`** — do NOT copy or remove it.
If the new send/stop/mic/attach glyphs use Phosphor `<i class="ph …">` (they do
in the markup above), you don't need the mask system for the composer at all;
leave it untouched for the rest of the app.

---

## 5. New Behavior Module (`js/composer_controls.js`) — requirements

This module replaces ONLY the composer-controls render/toggle + actions/mode glue
that previously lived in `008_easy_setup_onboarding_06.js` and `composer_redesign.js`.
**It must export the same global function names the runtime already calls** so no
other runtime file changes:

Provide (identical signatures/behavior to the deleted originals):
- `ensureChatComposerControls()` → returns `#composerControlsList`, creating the
  button/popover/list shell if markup drifted. Same return contract.
- `ensureChatComposerSubbar()` → back-compat shim → `ensureChatComposerControls()`.
- `renderChatComposerSubbar()` → fills `#composerControlsList` with the **5 dials**
  exactly as today (see §5.1). MUST keep the same `<select>` ids, the same option
  sets, the same `change` side-effects, the same module-var writes, and the silent
  value-seeding + `markActive` `is-active` toggling.
- `wireComposerControlsToggle()` → toggles `#composerControlsPopover` on
  `#composerControlsBtn` click; Escape + outside-click close; `aria-expanded` /
  `aria-hidden` sync; idempotent via `dataset.controlsWired`.
- `initChatComposerSubbar()` → calls the three above (runtime calls this at init).

Carry over the send-hint behavior from `composer_redesign.js` only if you want it
(it is purely presentational; the owner is fine dropping it). The icon
MutationObserver from that file is obsolete — the markup ships final icons.

> Everything else in the send path (`initComposer`, keydown, paste, drop, mic,
> `handleSend`, `buildSendJobFromComposer`, `buildChatRequestPayload`,
> `streamChatResponse`, send→stop morph) is OWNED BY THE EXISTING RUNTIME FILES
> AND STAYS. Do not move it. composer_controls.js only owns the controls/menu chrome.

### 5.1 The 5 Dials — IMMUTABLE contract

`renderChatComposerSubbar()` MUST emit these exact `<select>` ids, in the popover,
seeded from these exact module vars, firing these exact side-effects on `change`:

| Dial | `<select>` id | Module var | Default | On-change side-effects |
|---|---|---|---|---|
| Reasoning | `chatComposerReasoningSelect` | `activeReasoningEffort` | `'medium'` | set var (via `normalizeReasoningEffort`); `setSegmentedControlSelection('setupReasoningEffortGroup', …)`; set `settingAdvReasoningEffort.value` |
| Build/Token | `chatComposerTokenEconomySelect` | `activeTokenEconomy` | `'balanced'` | set var; `setSegmentedControlSelection('setupEconomyGroup', …)`; set `settingAdvDefaultTokenEconomy.value` (balanced→optimal) |
| Autonomy | `chatComposerAutonomySelect` | `activeAutonomyLevel` | `1` | set `autonomyLevelManuallySet=true`; set var (int); `setSegmentedControlSelection('setupAutonomyGroup', …)`; set `settingAutonomy.value=`L${n}``; **PATCH `/api/preferences`** `{autonomy:{default_level:'L'+n}}` |
| File access | `chatComposerFileAccessSelect` | `activeFileAccess` | `'workspace'` | set var; `localStorage.setItem('thomasFileAccess', v)` |
| Guardrails | `chatComposerGuardrailsSelect` | `activeGuardrails` | `'guarded'` | set var; `localStorage.setItem('thomasGuardrails', v)`; `syncGuardrailPresetModes(v)` (writes `thomasGuardrailModes` + PUT `/api/guardrails/policy`) |

Options come from `resolveProfileChatControls(profileName)` with the SAME literal
fallback option arrays currently in the file. Reasoning row is `hidden` unless
`reasoningControl.supported`. Model readout `#tcsModelReadout` =
`resolveActiveModelIdForProfile(profileName)` (fallbacks as today; never the raw
profile key).

These vars are the SOLE source `buildChatRequestPayload()` reads for
`autonomy_level`, `file_access`, `token_economy`, `thomas_guardrails`,
`reasoning_effort`. **If you rename or relocate any var, the payload breaks.**
Do not. Seed selects programmatically (does not fire `change`, so render = no
side-effects).

---

## 6. Removal List (delete ONLY composer-scoped selectors — never shared)

### 6.1 `index.html`
- Replace composer markup block, **lines ~593–688** (`<div class="composer-container">` … its closing `</div>`), with §3.
- Remove `<script src="/static/js/composer_redesign.js?v=…">` (line ~865) → replace with `composer_controls.js`.

### 6.2 `js/runtime/008_easy_setup_onboarding_06.js`
Delete these functions (now provided by `composer_controls.js`):
- `ensureChatComposerControls()` (~lines 661–720)
- `ensureChatComposerSubbar()` shim (~722–725)
- `wireComposerControlsToggle()` (~727–767)
- `renderChatComposerSubbar()` (~769–970)
- `initChatComposerSubbar()` (~972–976)

**KEEP (do NOT touch):** `resolveChatPayloadTokenEconomy` (643–647),
`resolveChatPayloadReasoningEffort`, `syncSetupReasoningVisibility`,
`buildChatRequestPayload` (978–1018), `initComposer` (1020+) and all its
keydown/paste/drop/autosize wiring.

### 6.3 `js/composer_redesign.js`
- Delete entire body (send-hint inject + attach-icon MutationObserver, ~lines 1–103). Leave a no-op or remove the file + its `<script>` tag.

### 6.4 `css/token_economy_space_theme.css` — delete composer-scoped rules ONLY
- `body.te-space-active .composer-container` and all `body.te-space-active .composer-*` rules (~lines 97–322, 775–804): container gradient, input-row glyph `::before`, textarea transparent override, `#sendBtn` 34px, `#micBtn`/`#attachBtn`/`#composerControlsBtn` 30px + active states, controls popover, action popover, disclaimer spacing.
- `body.te-theme-light .composer-*` rules (~1187–1230).
- `body.te-theme-dark .composer-container` / `.composer-*` rules (~2366–2376).
- Legacy send-button aliases `.send-btn`, `button[aria-label="Send"]`, `.primary` (~206–219) — **grep first**; delete only if no other live markup uses them. The real button is `#sendBtn`.
- **DO NOT delete** anything not under a `.composer-*` / `#sendBtn`/`#micBtn`/`#attachBtn`/`#composerControlsBtn` selector. Leave all non-composer space-theme rules intact.

### 6.5 `css/components.css` — delete composer-scoped rules ONLY
- `.composer-box`, `.composer-input-row`, `.composer-textarea` (~142–277, the composer-only parts)
- `.composer-status-bar` (~176–206), `.composer-mode-chip` (~208–253)
- `.composer-action-popover` / `.composer-action-btn` / `.composer-games-column` (~635–709)
- `.composer-controls-popover` / `.composer-control-row` / `.composer-control-select` (~716–802)
- `.composer-dino-shell` / `.composer-dino-*` (~834–855)
- `.attachments-preview` / `.attachment-chip` (~23–63) — **only if** you move them to `composer.css`; otherwise leave.
- **DO NOT delete:** `.btn-icon` and its hover (~280–352) — globally shared (sidebar, debug dock, nav). The **icon mask-image system (~354–632)** — keep entirely.

### 6.6 `css/component_styles/composer-attachments.css`
- KEEP as-is (attachment preview chips/thumbnails/lightbox). If you fold it into `composer.css`, recolor any hued borders to achromatic; do not break `.attachment-chip`.

---

## 7. Wire Checklist (every box must pass on the owner's fresh-loaded instance)

Restart `system_py -m thomas.server --port 8899`, hard-reload, verify each:

1. Type in `#composerTextarea` → `#sendBtn` enables/disables (`composerSyncSendButtonState`).
2. Textarea auto-resizes on input (height = scrollHeight, max 160px then scroll).
3. Enter (no Shift) sends (`sendBtn.click()` via runtime keydown); Shift+Enter = newline.
4. Ctrl/Cmd+Enter still sends (send-hint behavior); Esc closes menus/palettes.
5. `#sendBtn` click → `handleSend()` → `buildSendJobFromComposer()` → `runChatSendJob()` → POST to `/api/v2/chat` (or `/api/chat`).
6. `buildChatRequestPayload()` output is byte-identical to pre-rebuild (message, docs, images, session_id, profile, model, model_id, autonomy_level, file_access, token_economy, thomas_guardrails, thomas_guardrail_modes, reasoning_effort, module).
7. During streaming `#sendBtn` morphs to stop (`.stop-state` + stop glyph via `setGeneratingState(true)`); click aborts via `currentAbortController.abort()` → restores send.
8. Sending while `isGenerating` sends `busy_strategy:'interrupt'` WITHOUT aborting the live stream (non-blocking).
9. `composerInputLockUntil` debounce (1600ms) still prevents double-send.
10. `#attachBtn` toggles `#composerActionPopover`; outside-click closes; `aria-expanded` syncs; `.active` uses achromatic bg.
11. Action buttons (`data-action`) → `composerHandleQuickAction()`; `add_files` opens hidden `#docFileInput`/`#imageFileInput`.
12. `#composerGamesColumn` toggles from the Games submenu; `data-game` → `composerHandleGameChoice()`; Dino shell + `#chatGamePortal` still render.
13. `#composerControlsBtn` toggles `#composerControlsPopover`; Escape + outside-click close; idempotent (`dataset.controlsWired`).
14. All 5 dials render with ids `chatComposerReasoningSelect`, `chatComposerTokenEconomySelect`, `chatComposerAutonomySelect`, `chatComposerFileAccessSelect`, `chatComposerGuardrailsSelect`.
15. Each dial's `change` fires the exact side-effects in §5.1 (module var + setup-group mirror + settings mirror + persistence). Verify autonomy PATCHes `/api/preferences` and guardrails PUTs `/api/guardrails/policy`.
16. Dial values seed from current module vars on open (no spurious `change` side-effects on render); `.is-active` toggles when off-default.
17. `#tcsModelReadout` shows the active model id (never the raw profile key) in the popover header.
18. Token economy `balanced` → `optimal` mapping preserved in `resolveChatPayloadTokenEconomy()`.
19. `#composerModeChip` shows/hides on `composerSetMode()`; `#composerModeChipCloseBtn` clears `composerModeSelection` and refocuses textarea; mode prefix still baked via `composerBuildMessageForModel()`.
20. `#micBtn` toggles voice; `recognition.onresult` dispatches `input` event to drive autosize + send-state.
21. Paste image → `pendingImages` + `renderAttachmentsPreview()` + send-state sync.
22. Drag-and-drop → `_dragCounter` overlay (`.composer-drop-overlay.visible`), images→`pendingImages`, docs→`pendingDocs`, toast.
23. `#attachmentsPreview` chips render; cleared AFTER copy into sendJob in `buildSendJobFromComposer()`.
24. `renderMessage()` shows the user message immediately (before fetch).
25. `#assistantSuggestionRail` + `.suggestion-chip` populate textarea + focus; `#assistantSuggestionDismissBtn` hides rail.
26. Slash palette + model palette keydown nav still work (ArrowUp/Down/Enter/Tab/Esc) in the textarea handler.
27. `syncChatComposerOffset()` resize-observer still sets the scroll-area bottom-padding CSS var (messages not hidden under composer).
28. `#composerDisclaimer` renders muted; agent-name templating intact.
29. **No green/teal line anywhere.** Inspect every border/ring in DevTools: each must be `rgba(255,255,255,a)` with equal RGB channels. Confirm in fresh Incognito on the owner's actual screen.

---

## 8. Done Definition
All 29 wire-checklist boxes pass on the owner's freshly-loaded instance; the
payload is byte-identical; the composer is one calm achromatic dark surface with
the 5 dials behind the Controls button; and a search for hued low-alpha colors
(`rgba(88,166,255`, teal, green) in `composer.css` returns nothing.
