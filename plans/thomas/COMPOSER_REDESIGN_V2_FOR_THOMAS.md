# Work order: REDESIGN the general chat composer (clean, modern, frontier-grade)

The owner wants the composer **redesigned**, not tweaked. The current version is the
old layout with a cluttered always-visible dial row — he wants it gone and the whole
thing to feel like a modern ChatGPT/Claude composer: one calm input, controls tucked
away, lots of breathing room. Frontend-only, additive, default-safe. Keep message
dispatch/routing UNCHANGED and keep all five dial `<select>`s FUNCTIONAL (same ids,
options, change handlers) — you may relocate/hide them, never break them. No keyword UX.

## The redesign (do this)
1. **Remove the always-visible dial status row** (`#chatComposerSubbar` with the
   RSN/BLD/AUT/FS/GRD segments and the model readout). It currently sits at the top of
   the box and reads as clutter. Do NOT delete the five native `<select>` controls —
   move them into a popover (next item).
2. **Tuck the 5 dials behind ONE quiet control.** Add a single small "controls" button
   in the composer's bottom row (a sliders/tune icon, e.g. a horizontal-sliders glyph)
   that opens a compact popover/panel containing the 5 dials (Reasoning, Build,
   Autonomy, File access, Guardrails) as a clean little list (label + the existing
   control). The popover closes on outside-click / Esc. The native `<select>`s stay the
   source of truth and keep firing their existing `change` handlers. Show the active
   model as a small muted label inside that popover (not in the main row).
3. **The resting composer = one clean, unified input.** Bottom row, left-to-right:
   `[+ attach]  [textarea — the hero, grows to a cap then scrolls]  [controls/sliders]
   [mic]  [send]`. Generous padding (~12-14px), comfortable line-height, the textarea
   borderless inside the box (NO box-in-a-box). One unified rounded container (respect
   the global 2-4px sharp-corner theme — don't fight it).
4. **Calm, on-theme, ACHROMATIC.** Dark monospace cockpit theme. ALL borders/rings/
   separators must be white-alpha (`rgba(255,255,255,α)`) — zero hue, so nothing can
   read green/teal on the near-black background (a cool blue-gray border was the old
   "green line"). Depth by a subtle lightness step, not heavy borders or shadows.
5. **Send button:** a real, always-visible, clickable button, reasonably sized
   (~32-36px, not huge), the single accent element (the one place `--accent`/a fill is
   used). Send->Stop morph preserved. Keep the `Ctrl/⌘+↵ send` hint subtle/optional.
6. **Default-safe:** the popover/reveal must be CSS/JS that degrades gracefully — if JS
   fails, the dials must still be reachable and the composer usable.

## Files
- `thomas/server/web/js/runtime/008_easy_setup_onboarding_06.js` (the subbar build/render — repurpose into the popover)
- `thomas/server/web/css/token_economy_space_theme.css` (owns the composer look via !important)
- `thomas/server/web/css/component_styles/composer-attachments.css`
- `thomas/server/web/index.html` (composer markup; add the controls button)
- `thomas/server/web/js/composer_redesign.js` (presentational glue, if needed)

## Done =
A visibly different, clean, modern composer: no dial row (dials live behind one
controls button), one calm unified input, no green anywhere, no box-in-a-box, right-
sized accent send button, generous spacing. All five dials still work via the popover;
dispatch/routing untouched.
