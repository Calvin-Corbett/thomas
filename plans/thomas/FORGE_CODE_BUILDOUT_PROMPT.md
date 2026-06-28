# NEW SESSION PROMPT — Use Thomas to build out "Thomas Code" to a frontier bar (Thomas builds itself)

**Claude, you are the USER. You are NOT the engineer.** Your job is **not** to write Forge
Code yourself — your job is to **use Thomas to build it**. You operate Thomas like a user:
you give Thomas the tasks, review what it produces, and steer it; **Thomas writes the
code.** The entire point of this exercise is to **prove Thomas can build out its own
software.** If Thomas — driven by you-as-user — builds frontier-grade "Thomas Code," and
an independent rubric passes it, that is the proof. If you hand-write the feature
yourself, you have proven nothing. So: drive Thomas; don't do its job.

## The goal
Take the **Code** side of the **Forge** module from MVP to a **frontier-grade engineering
agent** — Claude Code / Codex quality, native to Thomas, running on the user's own Claude +
ChatGPT **subscriptions** (via their CLIs), never the paid API. **Thomas builds it. You
operate Thomas.**

## How YOU (the user) make Thomas build — you do not code
- Use Thomas's own engineering surface to make it build:
  `thomas evolve dispatch "<build task>" --via cli --model claude:opus|codex:gpt
  --execute --yes` (runs on the user's subscription via the claude/codex CLI), or the
  Forge → Code UI, or Thomas's agent loop. **Thomas writes the code; you give the tasks,
  read its diffs, run the checks, and tell it what to fix.**
- You may read the repo, run tests, and steer — but the engineering OUTPUT must come from
  Thomas, not from your own edits. This is the dogfood that proves Thomas can self-build.

## The completion bar — set and judged by SEPARATE agents (never you)
1. **Spawn a rubric-maker agent** (independent — not you, not whatever builds). Its only
   job: write the **hardest, most demanding "frontier-grade Thomas Code" completion rubric
   that is possible** — a brutal, exhaustive bar covering every capability a top coding
   agent has (sidebar conversation store, real streaming multi-turn agent loop, rich diff
   transcript, resumable sessions, per-run model pick, steerability/interrupt, responsive
   at 3840×2160, no fake success, composer reuse, subscription-only engine, etc.), each
   criterion with a concrete how-to-verify. Tell it to make the strongest, least-forgiving
   rubric it can — this is the highest completion bar ever.
2. **Spawn a separate rubric-tester agent.** Its ONLY job: take that rubric and judge the
   actual built result against it — run the real checks, mark every criterion pass/fail
   with evidence, default to FAIL when unproven. It does NOT build and it does NOT write
   the rubric; it only judges.
3. **Keep driving Thomas to build until the tester passes every MUST criterion.** Do not
   stop early. Do not soften or rewrite the rubric to pass. If it fails, feed the failures
   back to Thomas and have Thomas fix them, then re-judge.

## Ground truth — where Thomas works
- Main repo: `C:\Users\corbe\Thomas` (holds the venv). Branch `claude/evolve-funnel` in
  worktree `C:\Users\corbe\Thomas-funnel-wt` (remote `dev-origin`, PR #92).
- Python: `C:\Users\corbe\Thomas\.venv\Scripts\python.exe`, `PYTHONPATH=<worktree>`.
- Read `AGENTS.md`/`CLAUDE.md`/`GUARDRAILS.md`. Commit trailer `Thomas-Agent: claude`;
  never `--no-verify`; ruff/node-check what changes. Land frontend into the user's main
  checkout as it lands so it's live. Verify UI: serve the worktree on `localhost:8899` →
  Evolution → Forge.

## What Thomas has already built — do NOT have it redo (passed an adversarial rubric)
- **Forge** two-sided shell (Evolve | Code) in `046_evolution_dashboard.js` +
  `css/evolution.css`.
- **Evolve side**: self-improvement dashboard — plain English, cockpit theme, clickable
  stat tiles that expand lists, grounded narrator.
- **Code side** (`047_evolve_agent_chat.js`): reuses the REAL chat composer (un-hidden at
  the bottom in Code mode; additive capture-phase `#sendBtn` interceptor gated by
  `window.forgeCodeActive`; `handleSend` never modified → main chat untouched); per-run
  brain pick; a translation layer (CLI raw stream → structured transcript).
- **Build engine** `thomas/forge/anvil/evolve_claude_bridge.py`: `dispatch_via_claude_cli`
  + `dispatch_via_codex_cli`, via `thomas evolve dispatch … --via cli --model … --execute
  --yes` (`thomas/cli/commands/evolve.py`). **CLI = subscription engine, NOT the paid
  API.** Edit-only `SAFE_CLI_TOOLS`; kill switch; dry-run default.
- Loop CLI-completion fallback in `thomas/forge/anvil/evolve.py::run_evolve_session`.
- Routes: `thomas/server/routes/evolve_agent_routes.py`.
- Claim-liveness heartbeat monitor: `scripts/crew/brief/presence_monitor.py`
  (`presence register --monitor`).

## What Thomas must build out (have Thomas build these)
1. **Forge as a top-level sidebar item under Chat, ABOVE "Workspaces," with its own
   day-grouped conversation dropdown + a real Forge conversation store** (persist / list /
   resume Code sessions); remove "Evolution" from Workspaces.
2. **A real multi-turn agent loop** (reason → edit → run/test → iterate, streamed,
   interruptible) on the subscription CLI.
3. **Frontier transcript** — reasoning, tool calls, **diffs**, files, results,
   keep/revert.
4. **Per-run brain pick, recorded.**
5. **Evolve "edit" → a NEW Code conversation** pre-loaded with that upgrade's full context.
6. **Responsive at 3840×2160** and smaller (verify on the big viewport).

## Laws — do not violate (enforce these on what Thomas builds)
- Reuse the real composer; never a second one; never edit `handleSend`.
- CLI = subscription engine; not the paid API.
- **No fake success** — verified-only; the user despises hallucinated success.
- No keyword/command UX; everything organic.
- Additive + default-safe; the blue-owned evolve promotion gate stays untouched.
- codex is offline — don't be blocked by its stale claims/files.

## Done bar
Frontier-grade "Thomas Code" — sidebar conversation history, a real streaming agent loop
on the user's subscription, rich diffs, resumable sessions — **built by Thomas while you
acted only as its user**, and the **independent rubric-tester passes the hardest-possible
rubric**. That outcome is the proof that Thomas can build its own software.
