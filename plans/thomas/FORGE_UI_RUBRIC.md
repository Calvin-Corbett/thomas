# FORGE CODE — UI Rubric (frontier bar)

This rubric judges the **visual interface** of the coding agent — the LOOK: transcript layout and visual design, how reasoning / tool-calls / tool-results / diffs are presented, typography, color / theming / contrast, spacing and density, visual hierarchy, iconography, responsive layout, animation / loading states, and pixel-level polish. The bar is "premium frontier product."

**How to judge:**
- **Default to FAIL.** A criterion passes only when there is concrete evidence it is met. Absence of evidence is a FAIL, not a pass.
- **Evidence required.** Every judgment must cite a real observation — a DevTools measurement, a screenshot, a contrast-checker number, a computed-style readout, a grayscale/blur emulation, a resize test. No assertions from reading source alone where a runtime check is specified.
- **Judged in a real browser against the running app.** Verify against the live, rendered product (real input, real streaming, real tool runs), not mockups, not static markup, not synthetic events.

---

## A. Typography

### UI-1 — MUST — Single type scale
A single, deliberate type scale governs all text (~6–8 font sizes max, on a documented modular ramp e.g. 12/13/14/16/20/24), with body copy at 14–16px and clear ratios between steps — no orphan one-off sizes (11/15/17px).
**Verify:** In DevTools console run `[...new Set([...document.querySelectorAll('*')].map(e=>getComputedStyle(e).fontSize))].sort()`. Expect ≤8 distinct values on a recognizable ramp, body text 14–16px; flag any one-off outliers. Confirm headings/labels/code each map to a scale step.

### UI-2 — MUST — Prose vs. code typeface split
Assistant prose uses a high-quality proportional UI font; all code, diffs, tool args, file paths, and terminal output use a single dedicated, ligature-capable true-monospace stack (ui-monospace / SF Mono / JetBrains Mono / Fira / Berkeley Mono) with tabular alignment — distinct from the UI sans, never the OS default fallback.
**Verify:** Inspect a code block and a prose paragraph: `font-family` resolves to a monospace stack for code and a different non-mono stack for prose. Type a line of 80 fixed-width chars vs 80 `i` chars in a code block — column widths must match (tabular). Confirm digits/columns align vertically across multiple code lines.

### UI-3 — MUST — Comfortable prose measure and leading
Body text line-height is 1.5–1.7 and prose line length is capped at ~60–90 characters via a finite max-width on the message column, independent of viewport width — while code/diff blocks may run wider/full-width.
**Verify:** Measure computed line-height/font-size ratio of an assistant paragraph (expect 1.5–1.7). On a 1920px+/2560px window, measure rendered width/character count of a long paragraph — ≤~90ch (≤~720px), and confirm the message content has a finite max-width rather than spanning the full window; a wide diff in the same transcript is allowed to extend wider. Text is not flush against the viewport edges.

---

## B. Color, Theming & Contrast

### UI-4 — MUST — Design-token color system
A single design-token system (CSS custom properties) drives all color, spacing, radius, and type — zero hardcoded hex/px in component styles; colors resolve through `var(--…)` chains from a centralized `:root` token block.
**Verify:** In DevTools, sample 8 disparate elements (message bubble, tool chip, diff line, button, border, code-block bg). Computed colors must resolve to CSS custom properties, not literal hex. Grep the shipped CSS for hardcoded `#rrggbb` in component rules — near-zero outside the token definitions.

### UI-5 — MUST — Complete dark + light themes, no flash
Full dark and light themes both ship and are visually complete; the dark theme uses a non-pure-black surface (#0d–#18 range) with elevation via subtle surface tints (not borders only), and the light theme is equally polished. Theme choice persists, and switching/loading shows no flash of unstyled/wrong-theme content.
**Verify:** Toggle theme. Every surface (transcript, code, diffs, tool chips, scrollbars, focus rings, selection, empty states) recolors correctly with no orphan light-on-light / dark-on-dark / white code block. Sample the dark background — confirm dark grey, not `#000000`, with cards/code on a slightly lighter surface. Reload in each theme (cache disabled, throttled): no white/light-to-dark flash before paint and no large reflow (CLS < 0.1). Reload confirms persistence.

### UI-6 — MUST — WCAG AA contrast in both themes
Body/code text meets WCAG AA contrast (≥4.5:1 normal, ≥3:1 large text & meaningful UI borders/icons) in BOTH themes — including muted/secondary text, status pills, and every syntax-highlight token on the code background.
**Verify:** Run axe-core or Lighthouse a11y audit in both themes — zero contrast violations on body text. Manually sample the lightest secondary text, the dimmest syntax token (e.g. comments), and status-pill colors with a contrast checker; each must pass its size threshold (body/secondary ≥4.5:1, large/UI ≥3:1).

### UI-7 — SHOULD — Disciplined semantic & accent color
Color is systematized and used sparingly: a restrained neutral base with one or two accent hues applied consistently to primary actions / active / focus, and status colors (success=green, error=red, warning=amber, info/running=accent) reserved for meaning — no rainbow of competing brand hues. The same semantic maps to one hue everywhere (a failing test and a removed diff line don't use two unrelated reds), in both themes.
**Verify:** Catalog every place color conveys state (tool success/fail, diff add/remove, error banner, test pass/fail) and every accent usage. Confirm one primary accent drives CTAs/active/focus, the rest is neutral, and each semantic maps to one consistent token in both themes. Sample the dominant colors of a full transcript screenshot — mostly neutral, saturated color correlates with meaning, not decoration.

---

## C. Roles, Hierarchy & Transcript Layout

### UI-8 — MUST — Per-role visual differentiation
Roles are distinct at a glance and consistent down the whole transcript: user messages, assistant prose, reasoning/thinking, tool calls, and tool results each have a unique, consistent treatment (alignment, surface, accent, avatar/role glyph, or rail). Holds for edge cases (consecutive agent turns, tool-only turns).
**Verify:** Screenshot/thumbnail a 20-message transcript containing all block types; each is visually separable within ~1 second without reading text. Inspect DOM for distinct role classes/containers and confirm consistent treatment across repeated instances. No turn is ambiguous.

### UI-9 — MUST — Reasoning de-emphasized & collapsible
Reasoning/thinking content is visually demoted (muted/secondary color, lighter weight, smaller or italic, distinct container/left rail or muted background) and clearly subordinate to the final answer, with a label (e.g. "Thought for Ns") and a collapse/expand affordance.
**Verify:** Trigger a response with a thinking phase. Confirm the reasoning block has measurably lower text contrast/opacity or a distinct container vs the final answer, exposes a collapse affordance, and that the final answer remains the highest-contrast / dominant text in the turn. Collapse it and confirm the answer stays the focus.

### UI-10 — MUST — Clear intra-turn visual hierarchy
Within a turn the user's latest request and the agent's final answer are the most prominent elements; tool calls, reasoning, and metadata progressively recede via size / weight / contrast. Markdown structure (headings, lists, emphasis) is rendered as styled hierarchy, not raw markdown.
**Verify:** Squint/blur-test (apply `filter: blur(3px)`) a complex completed turn: the final answer and latest user message remain the dominant visual mass while tool/reasoning chrome recedes. Have the agent produce headings, nested bullets, bold, a numbered list, and a table — each renders as proper styled HTML with a distinguishable type scale (h-levels differ in size/weight), tables have borders/zebra or clean separation, and no raw markdown characters leak.

### UI-11 — SHOULD — Inline code / path / @-mention tokenization
Inline code, code blocks, file paths, identifiers, and @-mentions each have a distinct, consistent visual treatment (subtle mono chip/background/radius, optional file-type icon) separate from prose, and are visually linkable/actionable — identical everywhere those tokens appear.
**Verify:** In one agent message containing inline `` `code` ``, a path like `src/main.py`, and a code block, confirm visibly distinct treatments. Inline code/paths render in monospace with a subtle background+radius distinct from prose; the pattern is identical across all occurrences; paths ideally have a hover affordance.

---

## D. Tool Calls, Results & Diffs

### UI-12 — MUST — Tool calls as structured cards
Tool calls render as distinct, scannable, collapsible cards/chips — leading icon, human-readable verb-first action label (e.g. "Read src/app.ts", "Ran tests"), key argument summary, status indicator, and (ideally) duration — NOT raw inline function-call JSON (expandable raw is acceptable).
**Verify:** Trigger a read, an edit, a bash run. Each appears as its own visually-bounded unit: tool icon, verb-first label, summarized key arg (filename), status pill, elapsed time. No unformatted multi-line JSON object shown by default; the verbose payload is collapsed.

### UI-13 — MUST — Distinct live tool states
Each tool call shows clear real-time state — running/pending (animated spinner/shimmer), success (check), error (distinct color + icon), and cancelled (dash) — updating live in place, distinguishable by BOTH icon shape and color.
**Verify:** Induce a success and a failing tool call, plus a long-running one. Confirm the running state animates, then resolves in place; the error card uses a different icon AND color treatment (e.g. red border + alert glyph) vs success. The states are distinguishable in a screenshot without reading text.

### UI-14 — MUST — Progressive-disclosure for long output
Tool inputs/outputs, large diffs, and big file reads are collapsed/clamped by default with a one-line summary + expand ("show N more lines") affordance and a fade/overflow indicator; expanded output is scroll-bounded (max-height container, own scroll, no page scroll-jacking) with a copy button — so a 5,000-line log can't blow out the transcript.
**Verify:** Run a command / file read with very long output (>200 lines, and a 500+ line case). Default shows a summary + expand affordance; transcript height unaffected and other messages stay reachable. Expand: output appears in a max-height container with its own smooth scroll and a copy button. Collapse returns to the summary line.

### UI-15 — MUST — Diffs render as real code-review diffs
Diffs render as syntax-highlighted, line-numbered hunks with per-line add/remove background tints AND a fixed-width gutter sign (+/-) — not raw unified-diff text in a gray box. Includes optional intra-line (word-level) sub-highlighting for changed tokens.
**Verify:** Render a hunk with a one-word change. Confirm green-tinted added rows with `+` gutter, red-tinted removed rows with `-` gutter, line numbers, and that the changed token is sub-highlighted. Syntax colors persist inside added/removed lines (not flat red/green text).

### UI-16 — MUST — Diff change signaled beyond color alone
Added/removed diff lines are distinguished by more than hue — a gutter glyph (+/-) and/or border/pattern — so colorblind users and projector/grayscale viewing still parse changes (WCAG 1.4.1).
**Verify:** Apply a grayscale filter (`document.body.style.filter='grayscale(1)'`) to a diff; added vs removed lines remain distinguishable via gutter symbol/border, not just color.

### UI-17 — MUST — Diff context: file path, language, stable gutter
Diffs show line numbers in a fixed-width gutter (old/new columns for split, or unified) with a header bar showing the file path and a language badge, and respect that language's syntax highlighting inside the diff.
**Verify:** Open a multi-file change. Each diff has a header with file path + language badge; line numbers are right-aligned in a gutter that does not shift width as numbers go 9 → 10 → 100. Syntax colors persist inside the hunk.

### UI-18 — MUST — Syntax highlighting, theme-matched
Code and diffs have language-aware syntax highlighting with a cohesive, theme-matched token palette (keywords / strings / comments / numbers distinct), across common languages — not monochrome log text and not a clashing off-the-shelf default (e.g. raw highlight.js GitHub theme inside a dark UI).
**Verify:** Render code in 3+ languages (TS, Python, JSON). Confirm token types resolve to distinct, consistent hues via highlighting spans, that the palette visually belongs to the surrounding UI (shared accent/neutral family), and that highlighting is present inside diffs too.

### UI-19 — SHOULD — Code-block header & copy affordance
Code / diff / result blocks have a hover/affordance toolbar or header bar (language and/or file path, copy, copy-path, wrap, collapse) that appears cleanly without overlapping text and gives visual feedback (icon morph to check / transient "Copied") on action; resting state is clean.
**Verify:** Hover a code block: a copy control appears within the block's chrome; the header shows language or path. Click copy: a transient confirmation/check shows. The button is keyboard-reachable with an `aria-label`. No-hover resting state is uncluttered.

### UI-20 — MUST — Designed error/failure surfaces
Errors and failures render as designed surfaces — error icon + concise human summary + the failing command and bounded-scroll stderr/exit code + a retry/explain affordance — using the semantic error token at AA contrast (not pure-red on pure-black), NOT a raw red stack-trace dumped into prose.
**Verify:** Force a tool error (bad command). The result is a contained error card: error icon, human summary, exit code/stderr in a bounded scroll, retry/explain affordance, semantic error color, AA-contrast text.

---

## E. Spacing, Density & Alignment

### UI-21 — MUST — Consistent spacing scale / vertical rhythm
Spacing follows a consistent base unit (4/8px grid); message padding, inter-turn gaps, and card/code insets snap to that scale with uniform vertical rhythm (generous between blocks, tighter inside cards) — no 7/11/13/19/27px outliers.
**Verify:** Measure padding/margins on 6+ components (message containers, tool cards across tool types, code blocks) in DevTools. Values are multiples of 4/8; inter-turn gap is uniform; tool-card internal padding is uniform across tool types. Flag any odd one-offs.

### UI-22 — MUST — Shared alignment grid
Elements share a consistent alignment grid: gutters, icons, text baselines, card edges, message content left edges, code-block edges, diff gutter/line-numbers/code origin, and timestamps line up to shared vertical guides; nested sub-steps indent by a consistent amount. Nothing is off by a stray 1–3px.
**Verify:** Overlay a screenshot with guides / DevTools rulers. Tool-card left edges align with message text left edge; status icons vertically center to their label baseline; diff gutter, line numbers, and code share one left origin; nested tool sub-steps indent consistently. No element is 1–3px off its expected column.

### UI-23 — SHOULD — Deliberate, high-but-legible density
A deliberate information-density choice suited to developers: dense and scannable without crowding, and not bubble-chat whitespace bloat — ideally with a compact/comfortable density toggle that persists.
**Verify:** On a 1440px-tall window, count visible real content (messages + tool cards) vs empty padding without scrolling; whitespace should not dominate and assistant turns aren't dominated by oversized avatars/padding. If a density control exists, toggling visibly changes line-height/padding and persists across reload.

### UI-24 — SHOULD — Border / radius / shadow discipline
Borders, corner radii, and shadows are consistent and restrained: one small radius scale (e.g. one md, one lg — not a dozen values), one or two shadow elevations, and disciplined hairline border weights (mostly one weight; 2px reserved intentionally for emphasis) — no arbitrary mix of sharp/pill or bold black lines competing with content. A single accent hue recurs as the primary interactive/brand color (brand identity coherent and restrained).
**Verify:** Sample `border-radius` across cards, chips, buttons, inputs, code blocks — a small consistent set. Confirm `box-shadow` uses a consistent elevation system and borders are subtle (low-opacity / single hairline). Confirm one accent hue recurs as the brand/interactive color.

### UI-25 — SHOULD — Pixel-level / optical polish
Sub-pixel and optical consistency: icons baseline-align with adjacent text, cards share consistent radius/border-color/elevation tokens, edges line up on a grid — ruler-straight, no stray-pixel misalignment.
**Verify:** Screenshot a turn with mixed cards/icons/text at 2× zoom; check icons vertically center with labels, all cards share the same radius/border treatment, and left edges align to a common gutter.

---

## F. Iconography

### UI-26 — SHOULD — Single coherent icon set
A single-source icon family (uniform stroke weight, optical size, and grid; all line or all solid) is used semantically for tools, file types, and statuses — never mixed icon styles and never emoji-as-icons. File-type icons map sensibly (.ts vs .json vs folder distinguishable).
**Verify:** Collect every icon in a working session (tool chips, file-type glyphs, status, toolbar). Confirm uniform `viewBox`/stroke-width and a single family/style, common optical size, consistent meaning across occurrences, and no emoji used as functional UI icons.

---

## G. Animation, Streaming & Loading

### UI-27 — MUST — First-class streaming
Streaming is first-class: text renders token-by-token smoothly with a visible caret/typing indicator, in-flight tool calls show a live spinner/shimmer, and there is always a visible "working" indicator between steps — no dead blank gaps and no layout jank/reflow as content grows.
**Verify:** Issue a multi-step task. Tokens appear progressively (not one chunk) with a caret/typing cue; in-flight tool calls show an animated running state; between steps there is always visible activity. No >1s frame where the UI looks frozen, and the page/surrounding layout does not jump or reflow as tokens append (CLS near 0 within the message).

### UI-28 — SHOULD — Skeleton/shimmer loading states
Pending and loading states use tasteful, theme-matched skeletons/shimmer or subtle animated indicators that match the eventual layout (e.g. a shaped pending tool-card skeleton) — not bare centered spinners, raw "Loading…" text, or blank gaps — and stop cleanly when content arrives.
**Verify:** Trigger a latency action (new-session load, long tool). Confirm a shaped skeleton/placeholder matching the eventual card layout (or a subtle animated indicator) appears rather than only a spinner / static text / empty space, themed correctly, and clears cleanly.

### UI-29 — SHOULD — Subtle, fast, purposeful animation
Transitions (collapse/expand, message entrance, hover, status change) are subtle, fast (~120–250ms), eased, and purposeful — never bouncy, gratuitous, or >400ms blocking; no infinite decorative motion; no layout-shift jank as content streams.
**Verify:** Expand/collapse a tool card and a thinking block, send a message: measure `transition-duration` (~120–300ms), eased not linear-snap, no jank/bounce. Confirm no transition delays interaction >400ms and no infinite decorative animations.

### UI-30 — SHOULD — Respects prefers-reduced-motion
`prefers-reduced-motion` is honored: streaming, entrance, expand, and shimmer animations are reduced/disabled (or replaced with instant/opacity-only changes) when the OS setting is on, while the UI stays fully functional.
**Verify:** Emulate `prefers-reduced-motion: reduce` in DevTools Rendering; reload and trigger a message + an expand: non-essential animation is suppressed/instant, UI remains usable.

---

## H. Responsive Layout

### UI-31 — MUST — Responsive integrity, narrow → 4K
Layout holds from a narrow pane (~360–480px side-panel/mobile) up to ultra-wide/4K: content reflows with no page-level horizontal scroll on prose, no clipped/overlapping controls, tool cards stack and stay usable, and a mid breakpoint (~768px) collapses panels gracefully.
**Verify:** Resize to 360/375, 768, 1280, 2560, 3840px. At narrow: no horizontal scrollbar on prose, tool cards stack and remain usable/tappable, controls not clipped. At each breakpoint: no page-level horizontal scrollbar, no overlapping/clipped buttons. Mid breakpoint collapses panels cleanly.

### UI-32 — MUST — Contained horizontal overflow for code/diffs
Long code lines and wide diffs get a contained internal horizontal scroll (or a soft-wrap toggle), never forcing the whole page/transcript to scroll sideways.
**Verify:** Render a code block with a 200-char line. The block scrolls horizontally within its own bounds (or wraps if wrap on); the surrounding page/transcript gains no horizontal scrollbar. A wrap toggle, if present, re-flows without reload.

### UI-33 — SHOULD — 4K containment / multi-column
At ultra-wide/4K the layout uses max-width containment (readable measure ~80–100ch) or a multi-column / side-panel arrangement (file tree, plan, preview) rather than stretching one column edge-to-edge or leaving giant empty bands of unstyled background.
**Verify:** At 3840px wide, confirm the conversation column is centered/capped (or a secondary pane occupies surplus width) with balanced gutters, no edge-to-edge single line, no large empty unstyled bands.

### UI-34 — SHOULD — Comfortable targets, hover & focus on touch/desktop
Interactive targets meet ~40–44px effective tap/click size on touch and have visible, consistent hover and keyboard-focus states.
**Verify:** Measure bounding boxes of buttons/icon controls (copy, expand, send) — ≥~40px effective hit area. Hover each for a distinct hover state; Tab to confirm a visible focus ring.

### UI-35 — SHOULD — Crisp on high-DPI / zoom
Crisp rendering on high-DPI/4K: vector (SVG/icon-font) icons not blurry raster, hairline borders that don't vanish, and text/controls that stay sharp and uncropped when the OS/browser is zoomed 150–200%.
**Verify:** View on a 4K/Retina display or emulate `devicePixelRatio` 2–3; confirm icons are crisp and borders remain visible. Set browser zoom to 150% and 200%; confirm layout reflows cleanly and text/controls stay sharp and uncropped.

---

## I. Composer / Input

### UI-36 — MUST — Polished, anchored composer
A persistent, visually-anchored composer, clearly elevated/distinct from message bubbles, with clear affordances (send, stop/interrupt during generation, attach, model/context indicators), a visible focus ring, auto-grow (to a cap, then scroll), consistent corner radius, and accessible labels. It stays pinned, never jumps as the transcript grows, and never occludes the last message.
**Verify:** Inspect the composer idle, focused, while-streaming, and disabled. Focus shows a clear ring/border; during generation a Stop control replaces/accompanies Send; affordances have hover/active states and aria-labels. Type a multi-line message: it auto-grows to a cap then scrolls, transcript bottom padding keeps the last message visible above it, and the composer has clear elevation (shadow/border/surface) and stays pinned without jumping.

---

## J. Browser Chrome & Focus

### UI-37 — SHOULD — Themed scrollbars, selection & focus rings
Scrollbars, text-selection highlight, overflow shadows, and keyboard focus rings are themed to match the palette (accent-tinted selection, surface-matched scrollbars) across panes in both themes — not default OS blue/gray clashing inside a custom (esp. dark) UI.
**Verify:** In both themes, scroll a code block and the transcript: scrollbar styling and selection color match the theme rather than falling back to default browser chrome; overflow shadows are consistent.

### UI-38 — MUST — Visible keyboard focus on every interactive element
Every interactive element (composer, buttons, expandable cards, copy, links) shows a clearly visible, consistent, high-contrast focus indicator using the design accent — never suppressed by a global `outline:none` without a `:focus-visible` replacement.
**Verify:** Tab through the entire UI: a clearly visible on-brand focus ring moves through composer, controls, and expandable tool cards. Grep CSS for `outline:none` without an accompanying `:focus-visible` style.

---

## K. Empty / Edge / Error States

### UI-39 — SHOULD — Designed empty / first-run / offline states
Empty, first-run, idle, and offline/disconnected states are intentionally designed (welcome/orientation, suggested actions or example prompts, retry affordance) — correctly themed and centered, not a blank canvas, raw scroll area, or unstyled traceback — and clear cleanly on first message.
**Verify:** Open a fresh session: confirm a designed, themed, centered empty state (branding/orientation, maybe example prompts) that disappears cleanly on first message. Kill the backend mid-run: confirm a styled connection-error/retry banner rather than a frozen UI or unstyled error text.

---

## L. Structure, Navigation & Robustness Under Load

### UI-40 — SHOULD — Multi-file / multi-step work is grouped
Large or multi-step work is visually grouped (file-tree/changed-files summary with counts, plan/todo list with per-item status, or collapsible per-step sections) so a big change reads as orchestrated, structured progress — not N flat consecutive messages. Completed vs pending steps are visually distinct.
**Verify:** Run a task that edits 3+ files across steps. Confirm a grouping affordance (plan/todo with per-item status, changed-files summary with counts, or collapsible per-step sections), with completed vs pending visually distinct — not a flat message stream.

### UI-41 — SHOULD — Quiet, well-aligned metadata
Timestamps, token/cost meters, model labels, and other metadata are present but visually subordinate (tertiary color, small, consistently positioned in a turn header/footer), informative without competing with content; hover reveals fuller detail if truncated.
**Verify:** Locate metadata (timestamp, model name, token/cost). It uses tertiary text color and small size, sits in a consistent position, never out-weights the message body, and hover reveals fuller detail if truncated.

### UI-42 — SHOULD — Traceable nested/structured hierarchy
Nested/structured content (collapsed sub-tool calls, sub-agent output, file trees) uses consistent indentation rails or connectors so parent/child depth is traceable at a glance — uniform, subtle rail color/weight — not inferred from spacing alone.
**Verify:** Trigger nested activity (a tool that spawns sub-steps, or a sub-agent). Confirm consistent indentation and/or connector rails communicate depth, with uniform subtle rail color/weight; depth is readable at a glance.

### UI-43 — SHOULD — Long-session navigability
Long transcripts stay navigable and oriented: sticky context (current task/file/step/branch header), a "jump to latest / new activity" affordance when scrolled up, and stable scroll anchoring — auto-scroll follows new output but pauses and yields when the user scrolls up, then resumes at bottom; incoming tokens never yank the viewport.
**Verify:** During an active long run, scroll up: auto-scroll pauses and a "jump to latest"/new-activity affordance appears; scroll back to bottom and it resumes. Any sticky header (current file/step/branch) stays pinned, correct, and legible as sections pass. No abrupt scroll jumps when new tokens arrive while reading history.

### UI-44 — MUST — Visual consistency under volume
Visual consistency holds across repeated elements and over a long session — the 10th tool card looks identical to the 1st with no style drift, no misrendered markdown, no broken nested formatting. Rich markdown (tables, nested lists, nested code-in-list, blockquotes, headings, links) renders correctly with proper styling/spacing throughout.
**Verify:** Run a long multi-tool session; compare early vs late instances of the same component for identical styling. Render markdown with nested lists, tables, blockquotes, and code-in-list; confirm each renders correctly (aligned table columns/separators, clear list indentation, distinct heading weights) without broken spacing or escaped artifacts.

### UI-45 — SHOULD — Robust under real content stress
No visual regressions under messy real inputs: emoji, RTL text, very long unbroken tokens (URLs/hashes), mixed-language code, and wide tables don't break layout, overflow the transcript, or force horizontal page scroll — handled via wrapping/ellipsis/contained-scroll with alignment intact.
**Verify:** Paste a 120-char no-space hash, an emoji-laden commit message, an RTL string, and a wide table into a turn. Confirm wrapping/ellipsis/contained-scroll handle each — nothing overflows the transcript, no horizontal page scroll, alignment holds.

---

## Scoring

**Default to FAIL. Every MUST below must PASS for the UI dimension to pass. A single failing MUST fails the dimension. SHOULDs are graded for polish/completeness but do not block.**

**MUST criteria (all must PASS):**
UI-1, UI-2, UI-3, UI-4, UI-5, UI-6, UI-8, UI-9, UI-10, UI-12, UI-13, UI-14, UI-15, UI-16, UI-17, UI-18, UI-20, UI-21, UI-22, UI-27, UI-31, UI-32, UI-36, UI-38, UI-44

**MUST count: 25**

**SHOULD criteria (graded, non-blocking):**
UI-7, UI-11, UI-19, UI-23, UI-24, UI-25, UI-26, UI-28, UI-29, UI-30, UI-33, UI-34, UI-35, UI-37, UI-39, UI-40, UI-41, UI-42, UI-43, UI-45

**SHOULD count: 20**

**Total criteria: 45**
