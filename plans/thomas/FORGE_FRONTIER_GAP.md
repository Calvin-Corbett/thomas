# Forge Code — Frontier Gap & Fill Backlog

**Author:** synthesis lead (this pass). **Date:** 2026-06-24.
**Inputs:** independent research on 11 frontier coding agents (Cursor, Claude Code, GitHub
Copilot, Windsurf/Cascade, OpenAI Codex, Aider, Cline, Zed AI, Replit Agent, Devin, Amazon Q
Developer) + the current state of Forge Code (Thomas).

**Purpose:** turn the field's distinctive features into a concrete GAP-AND-FILL backlog for
Forge Code — what the frontier has, what Forge already matches, what's missing, and an ordered
build plan to close it. This is the strategy doc that sits above `FORGE_RUBRIC_SCORECARD.md`
(which tracks the *quality* bar) — this one tracks the *capability* bar.

**What Forge Code is today (baseline for this analysis):** a top-level "Forge" sidebar item with
an Evolve|Code toggle; a Code surface that reuses the real chat composer; a persistent
conversation store (persist/list/resume) surfaced via a **day-grouped dropdown** (not a full
sidebar list); per-run model pick (Claude via `claude` CLI, GPT via ChatGPT OAuth in-process —
no codex CLI, no paid API); a real streaming structured transcript (collapsible reasoning,
tool-call cards, tool-result cards); real code-review **diff cards** (line-number gutters, +/−
signs, syntax highlighting, word-level highlight, Copy/Keep/Revert acting on disk); an engine
run loop (reason → edit → VERIFY → iterate) with real exit codes, honest failure, and
self-recovery; a Stop that kills the build process tree; conversation-vs-build intent decided by
the model (no classifier); multi-turn memory; responsive to 380px.

---

## Feature & UX matrix

Legend: **Y** = has it, **P** = partial / weaker form, **—** = no. "Forge" column is the verdict
for Forge Code today. Agent columns are abbreviated: Cur=Cursor, CC=Claude Code, Cop=GitHub
Copilot, Win=Windsurf, Cdx=Codex, Aid=Aider, Cln=Cline, Zed, Rep=Replit, Dev=Devin, AmzQ=Amazon Q.

| Capability / UX quality | Cur | CC | Cop | Win | Cdx | Aid | Cln | Zed | Rep | Dev | AmzQ | **Forge** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Coordinated multi-file edits | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **Y** |
| Real streaming agent loop (reason→edit→run→iterate) | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **Y** |
| Honest failure / no fake success | P | Y | P | Y | Y | Y | Y | P | P | Y | Y | **Y** |
| Real diff cards (gutters, +/−, syntax, word-level) | Y | Y | Y | Y | Y | P | Y | Y | Y | Y | Y | **Y** |
| Diff acts on disk: keep/revert/copy per change | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **Y** |
| Per-run model switching | Y | Y | Y | Y | Y | Y | Y | Y | P | — | Y | **Y** |
| Subscription-only engine (no paid API) | — | — | — | — | — | Y | Y | Y | — | — | — | **Y** ★ |
| Stop / interrupt mid-run | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **Y** |
| Conversation-vs-build intent (model-decided, no keywords) | Y | Y | Y | P | Y | P | Y | P | Y | Y | P | **Y** ★ |
| Multi-turn memory within a session | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **Y** |
| Responsive small-viewport | P | Y | Y | P | Y | Y | Y | P | Y | Y | Y | **Y** |
| **Session-history SIDEBAR (persistent list, search, rename)** | Y | Y | Y | Y | Y | (git) | Y | Y | Y | Y | P | **P** (dropdown only) |
| **Mid-task reasoning / "I'm noticing…" interim insight** | P | Y | P | Y | P | Y | Y | Y | Y | Y | Y | **P** (raw reasoning, not distinct insights) |
| **Artifacts / previews in chat (canvas, file/app preview)** | Y | P | P | Y | Y | P | Y | — | Y | — | P | **—** |
| **Build outputs land in "My Stuff" / workspace** | Y | — | Y | Y | Y | (git) | — | — | Y | Y | — | **—** |
| **Overall UI polish (rated)** | Y | Y | Y | Y | Y | P | Y | Y | Y | Y | Y | **P** (in progress, 87% MUST) |
| Checkpoints / rewind (code state snapshots) | Y | Y | Y | Y | P | (git) | Y | Y | Y | — | Y | **—** |
| Plan mode (review/edit plan before building) | Y | Y | Y | Y | P | Y | Y | — | Y | Y | P | **—** |
| Persistent todo / focus-chain progress list | P | P | Y | Y | P | — | Y | — | Y | Y | — | **—** |
| @-context mentions (files/folders/symbols/url) | Y | Y | Y | Y | Y | P | Y | Y | Y | P | Y | **—** |
| Codebase indexing / repo map | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | Y | **P** (agent reads repo; no index/map) |
| Open-in-editor / round-trip to IDE | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | **—** |
| Parallel agents / multiple concurrent runs | Y | Y | Y | Y | Y | — | P | Y | P | Y | — | **—** |
| MCP / external tools | Y | Y | Y | Y | Y | P | Y | Y | Y | — | Y | **P** (Thomas tools exist; not surfaced in Forge) |
| In-app browser / live preview + send-to-agent | Y | Y | — | Y | Y | — | Y | — | Y | Y | — | **—** |
| PR / git actions from the surface (commit/push/PR) | Y | Y | Y | Y | Y | Y | P | P | Y | Y | Y | **—** |
| Tab / next-edit autocomplete | Y | Y | Y | Y | Y | — | — | Y | — | — | Y | **—** (out of scope — chat surface, not editor) |
| Code review of a PR/diff as a product | P | Y | Y | P | Y | P | P | — | — | Y | Y | **P** (review diffs exist; not PR-scoped) |
| Voice input | Y | — | — | Y | Y | Y | — | — | — | — | — | **—** |
| Notifications when async run finishes | Y | Y | Y | Y | Y | — | — | Y | Y | Y | — | **—** |

★ = a place where Forge is at or **ahead** of most of the field (subscription-only engine;
model-decided routing with zero keyword UX — exactly what the operator wants and what several
"command-trigger" tools get dinged for).

---

## The Gaps (what frontier agents have that Forge Code lacks)

Prioritized highest-impact first. Each gap: the capability, why it matters (who does it well +
why reviewers love it), and a concrete "how Thomas could build it" hint. The five operator-named
gaps are explicitly tagged **[OPERATOR-NAMED]**.

### 1. Real session-history sidebar (like Claude Code) — **[OPERATOR-NAMED]**
**Capability:** a persistent left-rail list of past Code conversations — grouped (Today /
Yesterday / Last 7 days), with AI-generated titles, search, rename, delete, and one-click resume —
not a dropdown you have to open.
**Why it matters:** every top agent treats history as a first-class *surface*, not a menu. Claude
Code's "Session history button… AI-generated titles, search, grouped Today/Yesterday/Last 7 days,
rename/remove" is praised as how you juggle parallel threads. Cline's task-history view (fuzzy
search, date/cost filters, favorites, pinning) and Zed's Threads Sidebar are cited as what makes
long, multi-thread work manageable. A dropdown hides the work; a sidebar makes the agent feel like
a tool you *live in*. The store already exists in Forge — only the surface is missing, so this is
the highest leverage-per-effort gap.
**How Thomas builds it:** the persist/list/resume store is already there. Build a collapsible
left-rail panel in the Forge Code surface (its own component in the `js/runtime/NNN_*.js` split,
sibling to `047_evolve_agent_chat.js`) that renders the existing list grouped by day, wires the
existing resume call on click, adds a search filter (client-side over titles), and reuses the
existing `agent/task_titling.py` model-titler for names. Rename/delete = two small route additions
to `evolve_agent_routes.py`. Make it collapse below ~700px so 380px responsiveness holds.

### 2. Artifacts / previews rendered in chat — **[OPERATOR-NAMED]**
**Capability:** rich outputs rendered inline in the transcript — a live preview of a built web
page/app, a rendered file (image, HTML, markdown, data table), a canvas — not just diff cards and
text.
**Why it matters:** this is the single biggest *visible* differentiator the leaders share. Windsurf
and Replit render the running app in an in-editor Preview with a click-an-element-and-send-it-back
loop ("like watching a QA engineer at work"); Codex has an artifact viewer (PDFs, spreadsheets,
docs) + in-app browser; Cursor's embedded browser + Visual Editor is a marquee 2.0 feature. For a
*chat-shaped* agent like Forge, an artifact panel is what turns "it edited files" into "look at
what I made." Thomas already has upload previews and a deliverable/⭐ concept in main chat — Forge
Code is the one surface that doesn't show its outputs.
**How Thomas builds it:** add an artifact card type to the transcript translation layer. When a run
produces a renderable output (an HTML/page file written, an image, a markdown doc, a data file),
emit an artifact card that renders inline: for web, an iframe pointed at a served preview of the
build output (reuse the same-site/sandbox handling already learned for multi-file games — see the
CORP white-screen fix in memory); for images/markdown/tables, render directly. Gate behind a
detector on the run's written files. Reuse the existing diff-card infrastructure for layout.

### 3. Mid-task reasoning / interim "I'm noticing…" insight updates — **[OPERATOR-NAMED]**
**Capability:** distinct, surfaced interim insights while the agent works ("I'm noticing the auth
flow has no test coverage", "this refactor touches 3 callers") — separate from the raw collapsible
reasoning stream.
**Why it matters:** Claude Code's inline "Pondering…" + collapsible extended-thinking is cited as
making the agent feel like it's *genuinely reasoning, not pattern-matching*. Codex's honest
self-reporting ("when uncertain or facing test failures, explicitly communicates the problem") and
Cline/Windsurf's transcript cards that surface tool reasoning are repeatedly called the trust
builders. Forge has the raw reasoning stream collapsed, but doesn't *promote* salient insights — so
the user can't see the agent "thinking out loud" at a glance.
**How Thomas builds it:** add an "insight" card type distinct from the reasoning blob. In the
agent loop, have the model emit short, structured interim notes (a lightweight tool/marker the
model calls, NOT a keyword scan — stays organic per the no-keyword law) at decision points; render
them as a pinned, lightweight strip above the live tool-call cards. Keep them honest: tie them to
real observations (files read, exit codes), never speculative cheerleading.

### 4. Build outputs integrated into "My Stuff" / workspace — **[OPERATOR-NAMED]**
**Capability:** when a Code run produces something shippable (an app, a page, a doc, a game), it
shows up in the app's "My Stuff" section as a first-class artifact the user can open later — not
just files left on disk.
**Why it matters:** Replit's App History (cross-session timeline of every built version, live
click-around preview, restore code+data) and the standalone-app principle Thomas already committed
to (every workspace opens as its own app via `/app/<id>` + Desktop shortcut) point the same way:
the *output* of a build should be a durable, openable thing, not a diff that scrolls away. This is
what closes the loop from "Forge edited files" to "I have a thing I made." Devin's PRs and Copilot's
branch-as-progress-log are the enterprise version of the same idea.
**How Thomas builds it:** on run completion, if the run produced a coherent deliverable (detector
from gap #2), register it as a "My Stuff" entry pointing at the standalone `/app/<id>` runner
Thomas already has. Persist a thumbnail/title (model-titled) + the originating Code conversation id
so "open" deep-links back to the transcript. This is mostly wiring two existing systems (the
standalone-app runner + the Forge conversation store) plus a small registry.

### 5. Overall UI polish — **[OPERATOR-NAMED]**
**Capability:** the surface *looks* frontier — light + dark themes, no console error spam, fast
time-to-first-token, virtualized diffs, no leaked harness/internal text, clean empty states.
**Why it matters:** polish is the most-cited *first-impression* lever across reviews (Zed's speed,
Cursor's familiarity, Codex "most user-friendly"). The current independent scorecard already names
the exact deductions: whole-dirty-tree changed-files panel, git stderr rendered as fake diff rows,
duplicated final message, leaked harness coaching text + internal ids, no light theme,
`ERR_CONNECTION_REFUSED` spam, ~3.3s TTFT, ~4.4s Stop latency, 3,551 un-virtualized diff rows.
Forge is at 87% MUST — polish is what converts "impressive demo" into "I trust this daily."
**How Thomas builds it:** this is the existing `FORGE_RUBRIC_SCORECARD.md` punch list — drive it to
83/83. Concretely: scope the changed-files panel to the run's writes (not the dirty tree); filter
git stderr out of diff parsing; de-dupe the final message; strip harness/internal ids from
narration; add a light theme; backoff the reconnect loop; virtualize the diff list; cut TTFT and
Stop latency. Each is a scoped builder task already itemized in the scorecard.

### 6. Checkpoints / rewind (code-state snapshots)
**Capability:** auto-snapshot code state before each run/edit; one-click restore (files /
conversation / both).
**Why it matters:** universally praised as the safety net that makes ambitious edits low-risk —
Cline's per-tool-call shadow-git checkpoints (files-only / conversation-only / both) are rated
*superior to Cursor's per-prompt restore*; Claude Code's Esc-Esc rewind and Zed's Restore
Checkpoint are top trust features. Forge has keep/revert per diff but no whole-run rollback.
**How Thomas builds it:** snapshot via a shadow git stash/commit (or a `git worktree`-scoped
snapshot — Thomas already uses worktrees heavily) before each run; add a "Restore to before this
run" control on each run header that resets the working tree to the snapshot. Offer
files-only vs files+conversation. Don't pollute the real branch history (shadow ref, like Cline).

### 7. Plan mode (review/edit plan before building)
**Capability:** the agent researches and proposes an editable plan/step-list *before* writing code.
**Why it matters:** Cursor ("saves you from watching the agent confidently code the wrong
architecture for ten minutes"), Claude Code's annotatable markdown plan, Cline's Plan/Act split,
Devin's interactive planning with code citations — all cite plan-first as the thing that prevents
wasted runs. The operator's own Idea-Funnel/Evolve work is plan-shaped already.
**How Thomas builds it:** add a "plan first" run mode where the loop's first phase returns a
structured, editable step-list (rendered as cards the user can edit/approve) before any edit tool
fires. Reuse the existing reasoning stream; gate the edit phase on user approval. Keep it organic
(a mode the model enters when the task is big, or a tool the user invokes) — not a keyword.

### 8. @-context mentions
**Capability:** `@file` / `@folder` / `@symbol` / `@url` to pull exact context into the prompt.
**Why it matters:** every editor-native agent has it; reviewers call it the low-friction way to
scope the agent without copy-paste. Forge relies on the agent reading the repo, which is slower and
less precise for targeted tasks.
**How Thomas builds it:** add an `@` affordance to the (reused) composer that fuzzy-matches repo
paths and inserts a context pill; on send, resolve pills to file contents handed to the agent.
Careful: must not modify `handleSend` (law) — implement as a composer decoration + a pre-send
context attachment in the Forge capture-phase interceptor.

### 9. Codebase index / repo map
**Capability:** a ranked dependency-graph map of the repo so the agent gets cross-file context
without manually adding files (Aider's tree-sitter repo map; Cursor/Windsurf/Cline embeddings).
**Why it matters:** "whole-codebase awareness" is the #1 praised strength of Cursor and Claude Code.
Forge's agent reads the repo per-run but has no persistent map — slower and weaker recall on large
trees.
**How Thomas builds it:** generate a lightweight repo map (tree-sitter symbol ranking like Aider,
or reuse Thomas's bible/coverage tooling which already enumerates repo paths) and inject the
ranked map into the agent's context at run start. Incremental-update on file change.

### 10. Open-in-editor / round-trip to IDE
**Capability:** click a diff/file to open it in the user's real editor for manual edits.
**Why it matters:** Codex's "no inline editing in the diff viewer, must round-trip to VS Code" is a
*criticism* precisely because the round-trip exists and is expected; every IDE-native tool has it.
**How Thomas builds it:** add an "Open in editor" action on diff/file cards that shells out to the
user's configured editor (`code <path>` / OS default) at the file+line. Small, high-satisfaction.

### 11. Persistent todo / focus-chain progress list
**Capability:** an auto-generated, self-updating numbered task list with a progress indicator
(e.g. "3/8") for long multi-step runs.
**Why it matters:** Cline's Focus Chain and Copilot's live PR checklist are cited as what keeps long
tasks from drifting ("lost in the middle"). Forge's transcript is linear with no at-a-glance
progress.
**How Thomas builds it:** have the loop maintain a structured todo (model emits/updates it) rendered
as a sticky progress strip in the run header with an "n/m done" badge. Pairs naturally with plan
mode (#7).

### 12. Notifications when an async run finishes
**Capability:** a status-bar/desktop notification when a long run completes or needs input.
**Why it matters:** Cursor's background-agent status-bar pings, Zed's done/waiting sound+visual,
Replit's mobile progress — all cited as what lets you walk away. Forge requires watching.
**How Thomas builds it:** fire an in-app toast (and optional OS notification) on run completion /
needs-input. Thomas already has notification plumbing (inbox/hooks) to reuse.

### 13. MCP / external tools surfaced in Forge
**Capability:** connect external tools/data and let the Code agent use them.
**Why it matters:** MCP is table stakes across the field (Claude Code, Cursor, Copilot, Codex,
Cline, Zed, Q). Thomas *has* a tool registry — it's just not exposed/used in the Forge Code loop.
**How Thomas builds it:** wire Thomas's existing tool registry (`thomas/tools/`) into the Forge
agent loop's tool set, with per-tool allow/confirm gating (Cline/Zed-style profiles). Render tool
calls in the existing tool-call cards (already built).

### 14. Parallel agents / concurrent runs (lower priority)
**Capability:** run multiple Code runs at once on isolated worktrees.
**Why it matters:** Cursor 2.0, Codex, Zed (first native parallel agents), Devin all market
fan-out/best-of-N. High-end; not core to a single-user chat surface yet.
**How Thomas builds it:** Thomas already uses `git worktree` per session — allow N concurrent Forge
runs each in its own worktree, surfaced as tabs/rows in the new sidebar (#1). Defer until #1 lands.

---

## Fill-the-gap build backlog

Ordered highest-impact first. Each is scoped to dispatch to a builder (via
`thomas evolve dispatch "<task>" --via cli --model … --execute --yes` or the Forge → Code UI).
All tasks obey the laws: reuse the real composer, never edit `handleSend`, CLI = subscription
engine, no fake success, no keyword UX, additive + default-safe.

1. **Session-history sidebar.** Build a collapsible left-rail panel in the Forge Code surface that
   renders the existing persist/list store grouped by day (Today/Yesterday/Last 7 days), with
   model-generated titles (reuse `agent/task_titling.py`), client-side search, rename, delete, and
   click-to-resume (reuse existing resume call). Add rename/delete routes to
   `evolve_agent_routes.py`. Collapse below ~700px; verify 380px + 3840×2160. *(Gap 1)*

2. **Polish punch-list to 83/83 MUST.** Drive the existing `FORGE_RUBRIC_SCORECARD.md` failures:
   scope changed-files panel to the run's writes; filter git stderr from diff parsing; de-dupe final
   message; strip harness coaching text + internal ids (e.g. "SC-UXQ-5") from narration; add a light
   theme; backoff the reconnect loop (kill `ERR_CONNECTION_REFUSED` spam); virtualize the diff list;
   cut TTFT (<1.5s) and Stop latency (<1s). Re-score with a fresh independent reviewer. *(Gap 5)*

3. **Artifacts/previews in the transcript.** Add an artifact card type: detect renderable run
   outputs (HTML/page → sandboxed iframe of a served preview, reusing the same-site/CORP fix for
   multi-file outputs; image/markdown/data → render inline). Reuse diff-card layout. Gate behind a
   written-files detector. *(Gap 2)*

4. **"My Stuff" integration for build outputs.** On run completion, when a coherent deliverable is
   produced (reuse the gap-3 detector), register a "My Stuff" entry pointing at the standalone
   `/app/<id>` runner, with a model-titled name, thumbnail, and a deep-link back to the originating
   Code conversation. *(Gap 4)*

5. **Mid-task insight cards.** Add an "insight" card type distinct from the collapsed reasoning
   stream; have the agent loop emit short, evidence-tied interim notes at decision points (organic
   marker/tool, not a keyword scan) and render them as a pinned strip above the live tool-call
   cards. Keep them honest (tied to real reads/exit codes). *(Gap 3)*

6. **Checkpoints / rewind per run.** Snapshot the working tree (shadow git ref / worktree-scoped)
   before each run; add "Restore to before this run" on the run header with files-only vs
   files+conversation options; never pollute branch history. *(Gap 6)*

7. **Plan-first run mode + todo/progress strip.** Add a plan-first mode whose first phase returns an
   editable, approvable step-list before edits fire; render a sticky "n/m done" progress strip in
   the run header that the loop self-updates. Organic entry (model enters it for big tasks / user
   invokes), not a keyword. *(Gaps 7 + 11)*

8. **@-context mentions.** Add an `@` affordance to the reused composer (fuzzy repo-path match →
   context pill); resolve pills to file contents attached pre-send via the Forge capture-phase
   interceptor — without touching `handleSend`. *(Gap 8)*

9. **Open-in-editor + run-finished notifications.** Add "Open in editor" on diff/file cards
   (`code <path:line>` / OS default) and an in-app toast (+ optional OS notification) on run
   completion / needs-input, reusing existing notification plumbing. *(Gaps 10 + 12)*

10. **Repo map + MCP/tool wiring.** Inject a ranked repo map (tree-sitter symbols, or reuse
    bible/coverage path enumeration) into the agent's run-start context; wire Thomas's `thomas/tools/`
    registry into the Forge loop with per-tool allow/confirm gating, rendered in existing tool-call
    cards. *(Gaps 9 + 13)*

11. **(Deferred) Parallel runs.** Allow N concurrent Forge runs, each in its own `git worktree`,
    surfaced as rows/tabs in the session sidebar from task 1. *(Gap 14)*

---

## What Forge Code already does as well as / better than the field

Being fair — Forge Code is not behind on the fundamentals, and on two axes it's ahead of most
named competitors:

- **Subscription-only engine (AHEAD of most).** Forge runs on the user's own Claude + ChatGPT
  *subscriptions* via their CLIs/OAuth — never the paid API. Only Aider, Cline, and Zed offer
  comparable bring-your-own/no-API freedom; Cursor, Copilot, Codex, Replit, Devin, and Q are all
  metered-credit or premium-request economies that reviewers repeatedly flag as the dominant
  complaint (token burn, confusing billing, mid-month credit surprises). Forge sidesteps the single
  most-cited cost criticism in the entire field.

- **Model-decided conversation-vs-build routing with zero keyword UX (AHEAD).** Forge decides chat
  vs build with the model, no classifier and no command triggers — exactly the organic UX the
  operator demands, and exactly what several tools get dinged for not having. Windsurf/Zed/Aider/Q
  lean on modes or commands; Forge's routing is more natural than most.

- **Honest failure / no fake success (AT the top of the field).** Real exit codes, real `VERIFY_OK`,
  honest failure + self-recovery. This matches Codex's praised honest self-reporting and Claude
  Code's verified loop, and beats the documented failure modes of Replit (silently swaps in mock
  data when blocked) and the "variable code quality / claims success" criticisms leveled at Cursor
  and Copilot.

- **Real, high-quality diff cards (AT the top).** Per-line gutters, +/− glyphs, line numbers,
  in-hunk syntax highlighting, word-level highlighting, colorblind-safe, and Copy/Keep/Revert that
  act on disk. This is the same diff-staging trust flow Windsurf, Aider, Cline, and Zed are
  *specifically praised for* — Forge already has the "is this safe to land" review loop the field
  treats as a killer feature.

- **Real streaming structured transcript** (collapsible reasoning, tool-call cards, tool-result
  cards), **per-run model pick**, **Stop that kills the process tree**, **multi-turn memory**,
  **real composer reuse** (no second composer; `handleSend` untouched), **persistence/resume**, and
  **responsive to 380px** — all present and independently verified (87% MUST on the current
  scorecard). These are the table-stakes the matrix marks **Y**, and Forge has them for real, not as
  scaffolding.

**Net read:** Forge Code is *capability-complete on the core agent loop and the trust-critical diff
review*, and *ahead of the field on cost model and organic routing*. The gaps are concentrated in
**surfacing and polish** — history sidebar, artifacts/previews, mid-task insight, "My Stuff"
integration, and the UI-polish punch list — plus a second tier of well-understood conveniences
(checkpoints, plan mode, @-context, repo map, open-in-editor, notifications, MCP). None of the gaps
are architectural blockers; all are additive builds on systems Thomas already has.
