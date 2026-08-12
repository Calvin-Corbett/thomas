# Forge Code — Rubric Scorecard (independent tracking)

**Purpose:** track how well the rubric-driven build is converging toward frontier.
Each row is produced by a FRESH, INDEPENDENT reviewer (not the builder, not the
operator) judging the live app against the three union rubrics in a real browser.
Watch the numbers climb — if they don't, the rubric/process isn't working.

**The bar (Calvin's 3 union rubrics, each = union of 3 independent blind writers):**
- `FORGE_UX_RUBRIC.md` — 34 MUST (how it *feels*: steerability, conversation vs build, honesty, recovery)
- `FORGE_UI_RUBRIC.md` — 25 MUST (how it *looks*: diffs, contrast, typography, responsive, polish)
- `FORGE_PERF_RUBRIC.md` — 24 MUST (what it *produces*: streaming, clean output, accurate diffs, real status)
- **Total: 83 MUST.** Acceptance = all 83 MUST pass + no LAW violated.
- (Separately, the original `FORGE_CODE_RUBRIC.md` core 42-MUST passed an independent panel earlier; these 3 rubrics are the harder UX/UI/Perf bar added after.)

---

## Score log

| Date (UTC) | UX | UI | Perf | Total MUST | % | Scored by | After |
|---|---|---|---|---|---|---|---|
| 2026-06-25 ~00:30 | 24/34 | 22/25 | 17/24 | 63/83 | **76%** | independent reviewer (fresh browser, 1 real build + "hello") | R11 (noise/chrome) |
| 2026-06-25 ~03:45 | 30/34 | 22/25 | 20/24 | 72/83 | **87%** | fresh reviewer (real "hi" + build, first-impression weighted) | R12 output-trust + R14 real-agent (chat-vs-build) + R15 codex-strip |

*(New rows appended after each batch + re-review. Trajectory, not a single number, is the signal.)*

---

## Current top failures (from the latest independent review) — being cleared in batches

**Batch A — output trust (in progress):**
- changed-files panel shows whole dirty tree (11) not the run's writes (1) — *Perf-21, UX-2*
- git stderr ("LF will be replaced by CRLF") rendered as ~10 fake diff rows — *Perf-14/20, UI-20*
- final assistant message renders duplicated (twin `<p>`) — *Perf-6*
- harness coaching text + `�` encoding break leak into cards — *Perf-45/14*
- internal id ("SC-UXQ-5") leaks into narration — *UX-23*

**Batch B — conversation routing:**
- "hello" triggers a 90s repo-editing run instead of a chat reply — *UX-7/8*

**Batch C — diff UX:**
- diffs expanded-by-default + 3,551 live rows (no virtualization) — *UI-14, Perf-23*

**Batch D — performance/polish:**
- Stop latency ~4.4s (target <1s) — *UX-1, Perf-29*
- time-to-first-token ~3.3s (target <1.5s) — *UX-28, Perf-1*
- no light theme; console `ERR_CONNECTION_REFUSED` spam w/o backoff — *UI-5, Perf-48*

## What's already strong (independently verified)
Real code-review diffs (per-line gutters, +/- glyphs, line numbers, syntax-in-hunk,
word-level highlighting, colorblind-safe, Copy/Keep/Revert), AA contrast, proportional
prose vs monospace code split, collapsible reasoning, honest exit codes (real `exit 0`
+ `VERIFY_OK`), responsive to 380px, real composer reuse, persistence/resume.

---

## How tracking works
1. After each batch of fixes lands + verifies, a FRESH independent reviewer re-scores
   the live app against all three rubrics (real browser, real build).
2. A new row is appended above with the date, per-rubric MUST counts, and what batch it follows.
3. Acceptance is declared only when an independent reviewer reports **83/83 MUST + no LAW**.
