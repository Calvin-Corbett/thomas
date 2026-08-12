This is a synthesis task. I have all four research inputs. Let me write the design doc directly.

# NIGHTSHIFT — Autonomous Thomas Self-Improvement Loop

**A design doc for a "wake up, improve Thomas, report back" loop, run by Claude on Calvin's behalf.**

---

## 1. Overview — what it is and the promise

NIGHTSHIFT is a scheduled loop that wakes up on a clock (every few hours, mostly overnight), picks **one** real, reproducible defect in Thomas, fixes it on a throwaway branch, proves the fix with a test that went red-then-green, runs it past gates it is structurally forbidden from editing, and leaves Calvin a short morning queue of **reviewed-and-ready branches** plus an honest list of **what it deliberately didn't touch.**

The promise to Calvin, in one line: **it can prepare anything; it can land nothing without your Win-Hello tap.** Unattended means *propose*, never *change what you run*. You wake up, read a one-screen report, and tap to merge the ones you like.

It is a **thin coordinator**, not a new engine. Almost every moving part already exists in Thomas (the evolve loop, the green-mirror builder, the blue supervisor gate, the ship/land path, the workboard, the bible health checks). NIGHTSHIFT's only original parts are: sourcing work from the ranked backlog, injecting Claude's judgment at the existing seams, and the owner-tap pause around landing. Everything else is reuse.

Three laws govern everything below, because they are the failure mode Calvin hates most ("looks done but isn't"):

1. **The loop never grades its own homework.** "Fixed" is defined by a test written *before* the fix and a gate suite the loop **cannot modify**.
2. **The loop never touches the machinery that judges it.** Gates, gate config, protected files, the supervisor, the test harness, this spec — all immutable. A cycle needing to edit them auto-defers to Calvin.
3. **No claim without an artifact.** Every "I fixed X" links to the red-test commit hash, the green run-log, and the diff. Missing artifact → reported as FAILED, full stop.

---

## 2. The wake-cycle pipeline

Each wake processes **exactly one** issue end-to-end. One issue → one branch → one diff Calvin can review and revert atomically. (Batching is how blast radius hides and how half-attributable state accumulates.) A wake may *triage-scan* broadly — cheap, read-only — but it only *fixes* one thing.

Every wake's **first action** is orient: read the ledger tail, `LEARNING.md`, and the inbox; reconcile any `in_progress` row (resume or roll back a crashed prior cycle); check presence + dirty tree. **If Calvin is actively working the target paths, the wake does triage-only and exits** — no branch, no contention. Real fix work concentrates in the quiet overnight window. This honors the standing multi-agent law: yield and message, never bulldoze.

| # | Stage | What it does | Thomas machinery reused | Workflow pattern |
|---|-------|--------------|-------------------------|------------------|
| 0 | **Orient** | Read ledger + LEARNING + inbox; reconcile `in_progress`; presence/dirty check; honor PAUSE sentinel | `startup_router.py --summary`, `message.py --inbox`, `bible_status.py` (abort if red) | Pre-flight gate |
| 1 | **Select** | Pick the single highest-value reproducible defect | `THOMAS_CODEBASE_ISSUE_RANKINGS.md` (primary), `evolve_planner.plan_backlog()` (secondary), with Claude injected at the `ranker` seam → one `EvolveGoal` | Score-and-defer |
| 2 | **Reproduce** | Write a failing test that fails *for the stated reason*; commit it red, alone | green-mirror checkout via `evolve.py`; `Required verification` column → `acceptance_checks` | Test-first |
| 3 | **Fix** | Build the fix in an isolated worktree | `run_evolve_session` (`mode="classic"`) or `run_funnel_session` (`mode="funnel"` for ambiguous/high-leverage), bound via `bind_real_collaborators` | Reproduce→fix→adversarial-review (funnel) |
| 4 | **Verify** | Fail-closed gate: targeted test green + full relevant suite + zero new fails/skips + revert-check + diff-sanity | `evolve_supervisor.decide_for_session` (blue-only, re-derives trust from FS) | Fail-closed promotion |
| 5 | **Land / queue** | Commit to `nightshift/*`, push, open **draft PR**; never auto-merge to dev | `ship.run_ship(dry_run=True)` to preview; live land only behind Win-Hello tap; `dev_land.py` owns protection toggle | Owner-tap gate |
| 6 | **Learn** | Record outcome; update track-record + tarpit; dedup fingerprint | `evolve_loop_learning.rerank_by_history`, `LEDGER.jsonl`, `LEARNING.md`; `problem_record.record_failure()` on failure | Cross-iteration learning |
| 7 | **Report** | One-line inbox summary + branch + evidence link; phone push for urgent | `message.py --send`, `PushNotification`; `REPORT-<date>.md` | Action-queue report |
| 8 | **Reschedule** | Cron guarantees the next wake; self-schedule only to tune density | `CronCreate` heartbeat (fixed), self-scheduled wake as override | Heartbeat |

**Admission control between Select and Fix:** before creating any worktree, call `native_orchestration.plan_orchestration_run()` / `collect_repo_signals()` to dedupe against work already in flight and refuse to start on broad dirty-conflict or stale-lease conditions. Then `claim.py` the paths; `message.py --send/--wait` if codex overlaps. This is the pre-flight that stops two loops colliding.

---

## 3. The safety model — the bright line at Win-Hello

### Auto vs human-tap boundary

**The loop MAY do fully autonomously:**
- Create worktrees and `nightshift/*` branches.
- Commit to its own branch (through the full gate stack).
- Push the branch to origin (so Calvin can review from anywhere).
- Open a **draft PR** into `dev` with the full evidence bundle.
- Write to its own scratch/report/ledger area.

**REQUIRES Calvin's Win-Hello tap — no automation, no `THOMAS_SKIP_BREAKGLASS`, ever:**
- Any merge/push to `dev` or `main`.
- Any edit landing to the **immutable set**: gates, gate config, protected files, auth/step-up, billing, schema/migrations, the chat identity prompt, `apps/site` (owner-only law).
- Marking a draft PR ready / merging it.
- Anything that would consume a breakglass.

The morning ritual is the entire landing mechanism: **Calvin reads the report, taps to merge the ones he likes. The tap is the landing.** The loop never drives its own breakglass. `ship.run_ship()` is the only land path, `dev_land.py` owns the protection toggle (lift `enforce_admins` → merge `--admin` → always restore in `try/finally`), and `phase_sync` pulls dev back to the local checkout afterward.

### Gates (never bypassed, never replicated)

Every change passes the existing ~50-module pre-commit stack via the commit phase — protected-files, secret-scan, monolith/size guards, `worktree_branch_guard` (blocks a branch >5 commits behind dev), workboard-claim integrity, verification-record gate. The loop **does not call gates individually or replicate their logic**, and it **never tries to make a gate pass by touching the gate** — that path does not exist. The code-quality + security spine is always enforced; only workflow/coordination gates relax under the signed QuickBuilder flag.

The promotion gate itself — `decide_for_session` — is **blue-only**: it imports neither `thomas` nor `scripts` (the green mirror can rewrite those) and re-derives trust from filesystem state. The known fail-OPEN hole (`all([]) == True` auto-passing an empty result set) is closed: empty or unparseable results are treated as **FAIL**, never pass.

### Anti-"looks-done" defenses

- **Revert-check:** every fix is proven load-bearing — revert it, watch the test go red. Green with *and* without the fix proves nothing → rejected.
- **Assertion-strength monitor:** the diff-sanity gate rejects any change that deletes a test, skips a test (skip = fail), weakens an assertion (`assertEqual`→`assertTrue`), or wraps code under test in a broad `try/except: pass`. These are the fingerprints of fake-green.
- **Independent re-run:** the targeted test runs a second time in a *fresh process* to catch state-dependent green (the documented cross-cycle state-bleed footgun).
- **No success without artifact:** the report generator refuses to print "fixed" for any cycle missing the red-commit + green-log + revert-check triad. The loop literally cannot phrase a win it can't prove.
- **Scope-creep tripwire:** if the diff exceeds the predicted blast radius by >2×, the cycle auto-aborts and defers.
- **UI items:** verification is real-browser on Calvin's actual instance (restart his server so the cache-bust fingerprint applies, hard-reload, screenshot) — never synthetic events or computed styles.

### Kill switch — three independent triggers, any one halts everything

1. **Soft pause (recommended everyday control):** a sentinel file `memory/thomas_loop/PAUSE` (or `~/.claude/NIGHTSHIFT_STOP`). Step 0 checks it first; if present, the wake logs "paused" and exits doing nothing. Calvin drops the file to pause, deletes it to resume. Reversible, instant, leaves the audit trail intact.
2. **Budget / wall-clock exhaustion** (see §5).
3. **Anomaly auto-halt:** ≥2 consecutive cycles ending in an unexpected gate-fail, any attempt to write outside the worktree, any push rejected by the protected-branch hook, or any detected attempt to touch the immutable set → the loop halts the **entire wake** and reports "halted: anomaly." A loop behaving unexpectedly stops; it does not push harder.

**Hard stop:** `CronDelete` removes the heartbeat. **In-flight runaway:** `TaskStop` on the active workflow. On any kill, worktrees are archived (not deleted — forensics), the ledger is flushed, and the report says exactly why it stopped. Failing safe = stopping with a clean trail, never "do something anyway."

---

## 4. State & learning — how it carries across wakes

Single source of truth, all in the memory directory, append-only so partial writes survive a crash:

- **`memory/thomas_loop/LEDGER.jsonl`** — one JSON object per line:
  ```
  { "id": "TL-0042", "title": "...", "source": "ranking|test_failure|bible_drift|inbox|calvin",
    "status": "queued|in_progress|verified|landed|rejected|parked",
    "priority": 1-5, "branch": "nightshift/06-26-flaky-auth", "attempts": 2,
    "repro": "...", "last_error": "...", "wake_ts": "...", "evidence_path": "...",
    "promotion": "passed|failed|null" }
  ```
  - **Resumable:** a wake reads the tail first; any `in_progress` row means a prior wake died mid-cycle → resume or roll back its branch before picking new work.
  - **Idempotent:** `id` is content-derived (hash of the failing-test name / drift signature), so the same defect never gets two entries; re-running on an already-`landed` item is a no-op.
  - **Anti-tarpit:** `attempts >= 3` (or 2 failed cycles) auto-flips to `parked` and force-defers to Calvin with the failure history attached — the loop never burns a whole night re-failing the same impossible fix. This reuses the tarpit-drop already built into the evolve loop.
  - **Fingerprint dedup:** file + symbol + failure signature; if a fingerprint is already an open `nightshift/*` PR or in the tarpit, skip it.

- **`memory/thomas_loop/BACKLOG.md`** — human-readable view derived from the ledger, for Calvin to read and edit.

- **`memory/thomas_loop/LEARNING.md`** — cross-wake lessons: per-category track record `{category → attempts, lands-Calvin-approved, gate-fails, reverts}`, known-flaky tests, paths to avoid. Categories Calvin **merges** get reranked up; categories that repeatedly fail gates get reranked down — **approval, not self-grade, is the success signal.** Negative results are first-class: "tried X, gate Y failed because Z" is logged and surfaced, so a quiet night that found nothing safe is a *valid, reported outcome.*

The ledger is **append-only for run records but immutable for the scoring logic** — the loop cannot rewrite its own track record to look better.

---

## 5. Cadence + concrete cron config

**Recommendation: a fixed cron every 3 hours (8×/day) as the liveness heartbeat, with real work concentrated overnight.**

Why 3 hours: nightly (1×/day) wastes an autonomous agent — ~30 items/month cleared when ~240 is reachable, and Thomas has a deep backlog. Hourly-or-faster risks colliding with Calvin and burning compute on an empty backlog. Three hours gives ~3 quiet overnight cycles plus daytime cycles that politely yield when Calvin is present.

**The cron is the heartbeat — it can never silently die.** A self-scheduled wake that crashes before scheduling its successor is gone forever; a cron always fires again. Self-scheduling is used only as an *override*: shorten the next fire when mid-multi-step on a hot issue, or no-op when the backlog is empty or Calvin is active. Cron guarantees liveness; self-scheduling tunes density.

Budgets bound each wake (reuse the evolve loop's existing spend-governor + watchdog plumbing — do not fork it):
- **Per-wake:** ~2M tokens / ~6 cycles, whichever first.
- **Per-cycle:** ~300K tokens; a cycle that blows its cap is killed and archived as inconclusive (high spend is itself a low-confidence signal → auto-defer).
- **Wall-clock:** stop at a fixed time before Calvin's expected return so the report is ready and the machine idle when he sits down.

Concrete config (via `mcp__scheduled-tasks__create_scheduled_task` / `CronCreate`), fixed prompt:

```
schedule:  0 */3 * * *          # every 3 hours, on the hour
prompt:    "Run one cycle of the NIGHTSHIFT Thomas-improvement loop per the
            operating model in memory/thomas_loop/. Orient (read ledger tail +
            LEARNING.md + inbox; reconcile any in_progress row). If
            memory/thomas_loop/PAUSE exists, log 'paused' and exit. If Calvin is
            active on the target paths, triage-only and exit. Otherwise: select
            ONE issue, reproduce with a red test, fix on a nightshift/* branch,
            verify fail-closed, record, and report to inbox. Never auto-land to
            dev — leave a ready-to-merge branch for Calvin's tap."
budget:    2M tokens / wake, 300K / cycle, wall-clock stop 1h before 08:00 local
```

---

## 6. What Calvin sees + how he steers it

**One artifact over coffee: `nightshift/REPORT-<date>.md`**, plus a phone push with the one-line headline. Decisions at the top, evidence one click down.

**Top — the action queue (what needs his tap):**
> `3 branches ready to review · 2 deferred to you · 1 night halted-clean`

| Branch | Issue (1 line) | Score | Proof | Diff | Action |
|---|---|---|---|---|---|
| `nightshift/06-26-flaky-auth` | flaky test X reproduced + fixed | 48 | red→green→revert ✓ | +12/−3 | **[Review & tap to merge]** |

Every row links to the draft PR, the red-commit hash, the green run-log, the revert-check log, and the diff. **No row exists without that bundle.**

**Deferred section** — candidates the loop *refused* to touch, each with a plain reason (blast-radius, ambiguity, tarpit, would-need-breakglass): *"I saw these, I didn't trust myself to do them unattended, here's why."*

**Tarpit / failures section** — what failed gates, in plain English, no code walls: *"Tried the cache-bust fix, it broke 2 other tests, dropped it."*

**Health line** — token spend, cycles run, `bible_status.py` result, and an explicit `loop integrity: OK` (no immutable-set touches, no anomaly halts) so Calvin can trust at a glance the loop stayed in its lane.

**How Calvin steers:**
- **Inject** — drop a line in the inbox or append a row to `BACKLOG.md` with `source: calvin`. Next wake's Select ranks `calvin`-source at **priority 1**; his items jump the queue.
- **Reprioritize** — edit the `priority` field on any row; Select honors it next wake.
- **Approve** — review the branch and owner-merge (`thomas ship` / `dev_land` tap). The loop sees it landed and marks `landed`.
- **Reject** — reply `rejected` in the inbox (existing ACK protocol) or set `status: rejected` with a note. Next wake deletes the branch and feeds the reason into `LEARNING.md` so it doesn't repeat the mistake.
- **Pause / stop** — drop the `PAUSE` sentinel (soft, recommended), `CronDelete` (hard), `TaskStop` (in-flight).

The loop is graded on **Calvin-merge-rate**, not cycles-completed or tests-added — so there is no busywork metric it can game. A night with zero proposals because nothing cleared the bar is explicitly a *success*.

---

## 7. Phased rollout — start safe, earn trust, widen autonomy

**Phase 0 — Propose-only, dry-run land (week 1).** The loop runs the full pipeline but stops at `ship.run_ship(dry_run=True)`: it produces branches, pushes them, opens draft PRs, and writes reports — but never even *offers* a live merge. Calvin lands everything by hand the way he does today. Goal: confirm the candidate sourcing, the red→green→revert evidence, and the report are trustworthy. Cadence dialed conservative (nightly only).

**Phase 1 — Tap-to-land, narrow scope (weeks 2–3).** Enable the Win-Hello-tap land path, but restrict the loop's `Select` to the **lowest-blast-radius categories only** — flaky tests, lint/coverage gaps, single-pure-function fixes. Confidence floor stays high (`< 4 → don't start`). Calvin's merge-rate on these builds the track record. Cadence to every 6 hours.

**Phase 2 — Widen categories (weeks 4–6).** As `LEARNING.md` shows categories with a strong Calvin-merge-rate, let `Select` reach into them — cross-module reliability fixes, the deferred dispatch/cache-bust/memory items from the seed backlog. The funnel (`mode="funnel"`) comes online for higher-leverage ambiguous goals. Cadence to every 3 hours. The immutable-set boundary never moves.

**Phase 3 — Steady state (week 7+).** Full 3-hour heartbeat, presence-aware daytime throttle, self-scheduling density tuning. The loop runs every night; Calvin's morning ritual is a 2-minute report read and a few taps. Autonomy has been *earned per category by merge-rate*, never granted wholesale — and the one thing he hates, *"looks done but isn't,"* remains the one outcome it is architecturally unable to produce.

---

## The whole thing in one breath

NIGHTSHIFT is a cron heartbeat that wakes every few hours, yields if Calvin is working, and otherwise picks one reproducible defect from the ranked backlog, fixes it in a disposable worktree, proves it red→green→revert, runs it past gates it cannot edit and a blue supervisor it cannot fool, and leaves a short morning queue of ready-to-merge branches plus an honest list of what it left alone. It reuses everything Thomas already has — the evolve loop, green mirror, funnel, blue gate, workboard, ship/land, bible health — and adds only sourcing, judgment-at-the-seams, and the owner-tap pause. It can prepare anything; it can land nothing without Calvin's tap; and it is graded on what he merges, not on how busy it looks.