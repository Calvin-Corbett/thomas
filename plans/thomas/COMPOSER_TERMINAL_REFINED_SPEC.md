# Composer redesign — "TERMINAL, REFINED" (build spec)

> Frontend-only (JS/CSS) redesign of the GENERAL CHAT composer. Produced by a
> research→funnel pipeline (research graded 97–98/100; 5 design directions judged
> 5→3→1; unanimous winner = D4 "Terminal, Refined" + grafts from D2 + D5).
> **Implement this exactly.** Do not change message dispatch/routing logic, do not
> change what the dial controls DO, do not touch protected files or gate scripts.

## The idea in one line
The composer becomes ONE continuous, calm monospace command surface. The dense
top "instrument cluster" HUD dissolves into an airy, **borderless** status line of
**identical `LABEL value` segments**. There is **no internal tinted hairline
anywhere** (that hairline is the "green line"). Send stays a real visible button.

## Why (the three complaints being fixed)
1. **"Weird green line through it."** Root cause: the injected subbar's
   `border-bottom: 1px solid rgba(140,160,180,0.16)` — a low-chroma blue-gray
   hairline over the near-black space theme — is perceptually pushed toward its
   complement (simultaneous contrast) and reads teal/green; near-black banding +
   alpha-over-near-black instability make it worse.
2. **"Feels out of place / bolted-on."** The HUD reads as a separate two-zone strip
   grafted onto the input (its own gradient + hairline + negative margins).
3. **"Reads like a big blob."** Five mismatched widgets (a pill, pips, two bar
   gauges, a shield gauge) crammed into one dense strip. The user is sick of the
   "instrument-cluster" look — a *tidier cluster is still a cluster*; the fix is
   restraint + uniformity + air, not a re-skin.

## Files to edit (all confirmed present; all unprotected)
- `thomas/server/web/js/runtime/008_easy_setup_onboarding_06.js`
  - `ensureChatComposerSubbar()` — the injected `<style id="chatComposerSubbarStyle">` block.
  - `renderChatComposerSubbar()` — the `#chatComposerSubbar` innerHTML + wiring.
- `thomas/server/web/css/component_styles/composer-attachments.css` — `.composer-box`,
  `.composer-input-row`, `.composer-textarea`, the icon/send buttons, focus-within.
- `thomas/server/web/css/token_economy_space_theme.css` — `body.te-space-active .composer-box`
  and friends (the space/cockpit theme owns the live composer look); surface ladder,
  focus ring, prompt glyph.
- `thomas/server/web/js/composer_redesign.js` — presentational binding only
  (value readouts, focus-state niceties, send hint). Must be default-safe.

Read these files first; match the surrounding code style. The live frontend is the
split `js/runtime/NNN_*.js` files (NOT the dead `app_runtime_primary.mjs` bundle).

## Requirements

### 1. Kill the green line at the root
- In the `#chatComposerSubbarStyle` block, on `.chat-composer-subbar`: **delete**
  `border-bottom: 1px solid rgba(140,160,180,0.16)`, **delete** the
  `background: linear-gradient(...)`, and **delete** the negative `margin: -5px -8px 5px`.
- Separate the status line from the textarea with **space only** (e.g. `margin` of
  ~14–16px). No border, no gradient, no low-alpha tinted line anywhere in the composer.
- **Rule (encode it):** an internal separator may ONLY ever be pure space, a surface
  *lightness* step, or a **fully-opaque achromatic gray** (e.g. `#1c2025`) — **never**
  a low-alpha tinted `rgba()` hairline. Ship with **no internal line** (space only).
- The `.composer-box` outer perimeter border may stay, but neutralize its hue: prefer
  a neutral `rgba(150,160,175,0.26)` over the current cool `rgba(140,160,180,0.28)`.

### 2. Dissolve the blob into a uniform status line (graft from D2)
- Keep the segment row **at its current position (top of the `.composer-box`)** — do
  NOT relocate it below the input row or evict controls from the box (that path was
  rejected as too risky for the offset/layout plumbing). Restyle in place.
- Replace the five heterogeneous widgets with **one repeated segment primitive**: a
  muted uppercase micro-label + a brighter value readout, sharing a baseline, uniform
  letter-spacing, **no per-segment border / fill / pill / gauge** at rest. Uniformity
  is what de-blobs — five identical `LABEL value` registers read as one calm instrument
  panel, not five competing shapes.
  - Reasoning → `RSN` + value (e.g. `min` / `std` / `high`)
  - Autonomy → `AUT` + value (e.g. `L1`…`L4` or the existing word)
  - Effort/token-economy → `BLD` + value (e.g. `quick` / `std` / `thorough`)
  - Guardrails → `GRD` + value (e.g. `off` / `guarded` / `fortress`)
  - File access → `FS` + value (e.g. `none` / `workspace` / `repo` / `max`)
  - Use whatever value words the existing `<select>` options already provide.
- **Two clusters, separated by space not borders (graft from D5):**
  ENGINE = [RSN, BLD] (cognition); EXECUTION = [AUT, FS, GRD] (permission).
  Gap WITHIN a cluster ~14px; gap BETWEEN clusters ~22–24px. The larger between-gap
  is the only grouping cue.
- Right-align the row. Put the **active-model readout** at the far right as a quiet
  **whisper** (`gpt-5.5`), the most recessive thing in the row (graft from D5 tone).
- Interaction unchanged in behavior: clicking a segment opens/cycles its underlying
  native `<select>` exactly as today (proxy the click to the select, or open its
  popover). **Non-default** value: render the value text in a brighter/heavier weight
  (NOT a chip/box) so off-default dials are glanceable (graft from D2 active-state).

### 3. One accent, used once
- `--accent` (#8a9aad) is reserved for the **send button** (ready state) and the
  box focus ring (and, momentarily, the focused/open dial's ring) — **never two lit
  at once**. Everything else uses the neutral gray ramp. Leave `--accent-mint` unused.

### 4. Prompt glyph
- Keep/elevate the existing `.composer-box::before` `›` glyph as the prompt marker at
  the input's left gutter. On `:focus-within` it brightens to the accent (the single
  accent "ignition"). Resting it is muted.

### 5. SEND — hard requirement (do not get this wrong)
- Keep a **real, persistent, always-visible, clickable send button** (`#sendBtn`),
  ≥44px hit target, as the **primary** send affordance and the brightest/accent
  element. **Do NOT** turn send into a text-only register.
- A `Ctrl/⌘+↵ send` *hint* may appear as an ADDITIONAL muted cue (e.g. trailing the
  status line or beside send) while composing — never as a replacement for the button.
- Preserve the existing Send→Stop morph and the existing send/dispatch wiring exactly.

### 6. Surfaces & type (on-theme; depth by lightness, not shadow)
- Surface ladder by lightness: near-black canvas → composer box one notch lighter →
  on `:focus-within` the box steps up one more notch. Concrete targets (tune to fit
  the existing palette): box `#121519`/current family, focus `#171b20`. Status
  segments live ON the box surface (no separate fill).
- Type (monospace, airy on dark): labels ~10.5px, `letter-spacing:0.5–0.6px`,
  uppercase, muted (`#7e8893` — WCAG-AA on the `#121519`/`#171b20` surfaces);
  values ~11.5px, `letter-spacing:0.2px`, `#8e99a4` resting → `#c7d0d9`
  active/non-default; model whisper `#808a94` (recessive but AA-passing on both
  surfaces); input 13–14px, `line-height:1.5`, `letter-spacing:~0.15px`. Positive
  tracking is what keeps dense mono from clotting. (All text must clear AA ≥4.5:1.)
- Embrace the globally-forced sharp 2–4px corners. **No drop shadows** on the segments.

### 7. Affordances
- `:focus-within` ring on the whole `.composer-box` (one outer ring, accent at low
  alpha) — replace the current no-op focus rule. **No inner line.**
- Placeholder as a prompt: `Message Thomas…`, muted.
- Attachments preview stays inside the box above the input row (behavior unchanged);
  restyle neutral, no tinted chips.
- Multiline: grow-to-cap-then-scroll (preserve existing behavior).
- Hit targets ≥44px for send/attach/segments (use transparent padding).
- WCAG AA: text contrast ≥4.5:1; focus ring / accent non-text ≥3:1.

### 8. Default-safe (graft from D5)
- Drive focus transitions via CSS `:focus-within` where possible so the composer
  renders fully usable with **no JS**. The five native `<select>`s must remain in the
  DOM and reachable even if `composer_redesign.js` fails to load; the value-readout
  binding is a JS enhancement that degrades to the select's own text. Respect
  `prefers-reduced-motion`.

## Hard constraints (must all hold)
- Keep all five native `<select>` IDs and their options and `change`-event
  side-effects UNCHANGED: `#chatComposerReasoningSelect`, `#chatComposerAutonomySelect`,
  `#chatComposerTokenEconomySelect`, `#chatComposerGuardrailsSelect`,
  `#chatComposerFileAccessSelect`. You may restyle/rewrap the widgets that drive them,
  never change what they do.
- Do **not** change message dispatch/routing logic anywhere. No keyword/command UX.
- Additive + default-safe: touch only the composer surface; do not regress other screens.
- `renderChatComposerSubbar` is re-invoked from several call sites — keep all wiring
  re-render-safe and preserve any existing teardown/listener-cleanup pattern.

## Acceptance (what "done" looks like)
- No tinted hairline / gradient strip in the composer; no perceptible green line.
- The five dials read as one calm, uniform, airy status line in two spaced clusters;
  all still click-operable and still firing their `change` side-effects.
- Send is an obvious, clickable, 44px button; Send→Stop still works; dispatch unchanged.
- Composer renders and dials are reachable even with JS disabled.
