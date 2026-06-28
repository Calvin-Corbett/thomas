# Work order: make the general chat composer genuinely good

You are fixing the GENERAL CHAT composer (the message-input area at the bottom of
the main chat). The owner has asked for this many times and it keeps not landing.
Diagnose and fix it properly. Frontend-only, additive, default-safe; keep the five
dial `<select>` controls functional and message dispatch/routing UNCHANGED; no
keyword UX.

## Symptoms (observed on the owner's real screen)
1. **A persistent GREEN / TEAL horizontal line across the composer** (most visible
   along the bottom edge). It has survived ~10 fix attempts. Find what actually
   draws it and remove the green for good. (Hint on the mechanism: a low-chroma
   COOL blue-gray color — blue channel higher than red — rendered over the
   near-black cockpit background reads as green/teal via simultaneous contrast.
   Audit EVERY composer color source: borders, box-shadows/rings, ::before/::after,
   gradients, AND interactive STATES like `:focus-within` — the composer textarea
   auto-focuses, so any focus-state color is always on. Make composer separators
   and rings ACHROMATIC, e.g. white-alpha, which has zero hue.)
2. The **send button is oversized** ("humongous") relative to the other controls.
3. The **microphone icon floats in dead space** in the middle-right of the input
   row, visually disconnected from the send button.
4. The **textarea has its own border** — a redundant "box inside a box".
5. **Spacing is scattered**, and the selector status row (RSN / BLD / AUT / FS /
   GRD + model readout) reads as cluttered/"dumb".

Make the composer clean, cohesive, and frontier-grade (think ChatGPT / Claude
composers) while staying native to the dark monospace cockpit theme.

## FIRST — why composer fixes have not been reaching the browser (fix this before anything else)
`thomas/server/web/css/token_economy.css` (line 3) imports the space theme with a
FROZEN, hardcoded cache-bust:

```
@import url("./token_economy_space_theme.css?v=20260402-fix11");
```

That `?v=` literal never changes, so the browser serves a STALE cached copy of
`token_economy_space_theme.css` forever — and that file owns the composer's look
via `!important`. So ANY edit you make to `token_economy_space_theme.css` will be
invisible to the owner until this is fixed. Make this import's cache-bust track the
build/version like the rest of the frontend (the server substitutes
`__THOMAS_WEB_BUILD__` / `__THOMAS_VERSION__` in served files — see
`thomas/server/app_middleware_helpers.py`; note whether substitution runs inside
`.css` files and, if not, make it so, or otherwise tie this import to the build
hash). Verify your fix by confirming the served `token_economy.css` no longer
contains a frozen `?v=20260402-fix11`.

## Files most likely involved
- `thomas/server/web/css/token_economy.css` (the stale @import)
- `thomas/server/web/css/token_economy_space_theme.css` (owns composer look, !important)
- `thomas/server/web/css/component_styles/composer-attachments.css`
- `thomas/server/web/index.html` (composer markup)
- `thomas/server/app_middleware_helpers.py` (version/cache-bust substitution)

## Done =
No green/teal anywhere on the composer in any state (incl. focused); send button
right-sized; mic grouped with send (not floating); no box-in-a-box; clean spacing;
the dials still work; dispatch/routing untouched; and the space-theme CSS cache-bust
is no longer frozen so future edits actually load.

## Verification status (2026-06-26)

- composer cache-bust fix: complete and delivered.
- green-line fixes: complete and delivered.
- funnel CLI dispatch fixed: stdin prompt fix, stream-json input handling, and inbox-gate bypass for edit-only builds.
