# Praxis First: Instruments, Then Repairs, Then the World

**Date:** 2026-08-24 · **Status:** Draft for your review · **Author:** Claude (session 6c3f0ce5)

## Why this exists

You opened the session asking for two things: make Praxis its own repo, because
"it's multi coordination, and no matter what provider you have... it's a great
system"; and adopt the architecture of DeepSeek's newly open-sourced harness,
because "everything's a plug in, and that's Thomas... the marketplace already is,
like, prepared to take in all the plugins... but I didn't have it actually built
correctly."

The session then established, with adversarially-verified evidence, that the
repo's recurring failures — misreporting, resurrection, undelivered fixes, gates
that don't gate — are one class: **claims without instruments**. And you named
the cure yourself: Praxis "has been born... by taking those injured engineering
practices and making practices... automatic." The census proved that model works:
where a practice exists the recurrence count is zero (80/80 custodian-archived
branches stayed dead; all 4 tombstone-tested artifacts refused resurrection);
where none exists, it is not (7 remote branch resurrections, 2 still live).

Your sequencing decision, quoted: "Fix practice first, [then] the rest." This
spec is that order. The original two asks are preserved — they moved to the end,
where they land on proven capability instead of hope.

## Locked decisions

| Decision | Choice | Where decided |
|---|---|---|
| Praxis box | Crew (`scripts/crew/`) + domain-neutral gates (`scripts/forge/gates/`) | you, 2026-08-24 |
| Sync model | One-way auto-mirror; Praxis keeps living in Thomas at current paths | you, 2026-08-24 |
| First DeepSeek move | Session log before kernel | you, 2026-08-24 |
| Sequencing | Phase 0 defuse → 1 Praxis capabilities → 2 repairs → 3 extraction+kernel | you, 2026-08-24 ("ok go") |

## Phase 0 — Defuse (days)

Stop active bleeding before building anything.

1. **Kill the two resurrected landing branches properly.** `landing/converged-2026-08-10`
   (public remote) and `landing/dev-2026-08-10` (private remote) were deleted
   2026-08-12 and re-created ~62 minutes later by a session that kept pushing.
   Order matters: delete/park every LOCAL copy in the 68 worktrees first, then
   delete the remote refs, so nothing remains that can push them back.
2. **Cage the janitor.** `C:\Users\corbe\thomas-ops\janitor.py` still runs with
   `apply=True` out-of-schedule (last: 2026-08-22) although its scheduled task is
   Disabled. Its `push-new` path structurally cannot distinguish squash-merged
   work from unpushed work. Until it routes through the custodian (Phase 1.2),
   it runs dry-run only.
3. **Worktree consolidation.** 64 dirty worktrees over a ceiling of 5, some with
   10,000+ uncommitted files, several in `%TEMP%`. Triage: salvage-list per
   worktree, land or archive, remove. Prerequisite for any scheduled export ever
   running from this machine.
4. **One break-glass batch** for the owner-only mechanics the later phases need:
   monolith baselines (or pre-splits) for `loop_execution.py` (982),
   `llm_client.py` (833), `run_store.py` (929), `commit.py` (846); enforcement
   manifest re-bless for the gate/crew files the ports refactor touches. Prepared
   as one ready-to-sign tap per the standing break-glass arrangement.

Phase 0 items 1, 2 and 4 are owner-authorized actions; they execute only on your
explicit go per item (item 4 via Windows Hello break-glass).

## Phase 1 — Praxis capabilities (the heart)

Ordered so each capability protects the ones after it.

### 1.1 Watcher of the watchers
Every enforcing gate gets a test that makes it FAIL on purpose and asserts the
failure blocks. Rationale: 28 gates sat advisory on Windows for months, unseen —
a practice that can silently stop practicing is not a practice. Deliverable: a
`gate_selftest` harness in the gates suite + CI job; a gate without a red-path
test cannot be registered as enforcing.

### 1.2 Graveyard with teeth
Deletion becomes a recorded intent with enforcement:
- **Refs:** custodian records every deliberate branch deletion (it already
  archives to `refs/archive`); a pre-push gate refuses re-creating a dead name;
  the janitor and every other pusher route through the custodian (sole-custodian
  rule). This makes the Aug-12 push-through cycle structurally impossible.
- **Files:** deletion records return (they were retired 2026-08-12 by 75b25c80 /
  67c24e69) as an enforced registry: a merge gate diffs any incoming merge
  against the graveyard and refuses resurrections by default. Rationale: "a
  three-way merge cannot tell a deletion from an absence" (c14859ff) — but a
  gate with a graveyard can.
- **Standing hazard this neutralizes:** `origin/main`'s tip is a squash whose
  merge-base with dev is 2026-06-09; the next merge from public main makes every
  dev deletion since June 9 resurrection-eligible. Until the merge gate exists,
  any merge from main requires a manual c14859ff-style refusal pass.

### 1.3 The honesty spine (session log)
The DeepSeek-derived design, as revised by the red team:
- **Boundary:** the LLM client, not any message builder. ~24 call sites build
  message lists (OrchestratorBrain, specialists, AgentLoop, workers, REPL); the
  client is the narrow waist they all pass through. A capture hook there records
  the exact message list entering every request.
- **Not a fifth ledger:** extends the existing `run_store` spine (run_id + seq +
  append; NDJSON replay), subsuming the forge event transcript as a view. One
  writer per log; contiguous `seq` validated at derivation (fail loud on gaps or
  repeats); idempotency keys on append.
- **Envelope (phase-2-proof, per dsh):** `seq`, `time`, `callId` on tool events,
  `source` on every context injection, `surfaceOp`/`sourceEventSeqs`; assembled
  `assistant/message` is the derivation surface (raw chunks kept log-only for
  replay); `turn/end{reason}` + `step/end`; history-mutation events:
  `context/compaction`, `history/truncate` (edit-and-resend), fork boundaries,
  `history/imported` (bootstrap for pre-existing conversations).
- **Cutover discipline:** shadow soak first — derivation runs in parallel with
  the live builders, per-step diffs logged; builders collapse only after a
  zero-diff soak, behind a flag whose off-position is the rollback.
- **Honest scope statement:** the Code surface's claude-CLI executor assembles
  its payload inside an external binary; Thomas logs the composed handoff prompt
  as its own event and states that path is outside the derivation guarantee.
- **The test:** `derive_messages(log)` structurally equals the message list at
  the client boundary, across real runs; provider serializers get separate
  pure-function snapshot tests. (Byte-for-byte wire equality was refuted:
  provider transforms and send-time state make it compare different objects.)
- **Growth policy:** per-conversation logs; content-hash dedup for repeated
  injections; never prune an open conversation's log; archive, don't delete.

### 1.4 Claims that verify and expire
"Done" becomes a checked status: a workboard claim of completion requires
evidence (commit landed on dev, gate results, or log-derived proof) and expires
if unverified. Kills the family the transcript sweep found behind much of the
"broken again" experience: fixes stranded on branches, cached pre-fix frontends,
sibling elements never patched.

### 1.5 The forging loop (meta-capability)
The incident→practice pipeline itself becomes fast and standard: an incident
record template that ends in either a new gate/tombstone or an explicit
owner-accepted risk. Rationale: gates only guard scars already earned; permanence
comes from making the next scar cost one incident, not a season. Standing rule
inherited by this spec: no future diagnosis may declare a root cause without
stating its red condition.

## Phase 2 — Repairs, with working instruments

The bug backlog (dead fallback sentences, unwired features, silent failures)
gets fixed under Phase-1 protection, so fixes land, stay landed, and are honestly
reported. No fixed inventory here — the instruments will surface and rank it.
Exit criterion: a month of organic use without a new instance of the
misreporting / resurrection / undelivered-fix families.

**Red condition (pinned in memory 2026-08-24):** if the honesty spine and
fail-closed gates land and within about a month you again report "it keeps
saying it's lying," the class model is wrong and rewrite-from-scratch becomes a
serious option on its merits.

## Phase 3 — The original asks

### 3.1 Praxis extraction and public mirror (revised by red team)
- **Ports layer (5+1):** `HostPresence`, `HostPrefs`, `HostBranchPolicy`,
  `HostBenchmarks`, **`HostConfig`** (workboard path, problems dir, env-var
  prefix, trailer name, hook-id prefix — the gates split is a parameterization,
  not a pick-list), plus optional **`HostApproval`** (no-op default) for
  breakglass. Standalone sqlite/file adapters ship as defaults;
  `thomas/praxis_host.py` registers Thomas's implementations.
- **Gate registry:** `commit.py` / `land_checks.py` / `safety_init.py` replace
  hardcoded gate tuples (~60 literal-path sites) with a data-driven registry so
  Thomas-specific gates are host-registered, not baked in.
- **Export:** a new destination on the EXISTING `forge/publish` pipeline —
  sources bytes only from git blobs of a committed ref (never the working tree:
  kills the gitignored-PII leak, dirty-tree risk, and CRLF/mojibake in one move);
  explicit allowlist manifest including the test subset + generated conftest;
  rewriter covers `scripts/crew→praxis` AND `scripts/forge/gates→praxis/gates`
  including subprocess string literals; `public_repo_leak_guard` mandatory;
  staging smoke-runs every entry point; push `--force-with-lease`; public repo
  is mirror-only (PRs auto-closed with a courteous upstream pointer).
- **Clean-room CI:** the public repo installs with no Thomas present and runs
  its bundled tests. This is the only honest proof of extraction.

### 3.2 Kernel (dsh/Cordis-style)
Remount the four existing plugin systems (`thomas/plugins` p097–p106 lifecycle,
`agent_plugins_*`, `desktop_plugins_*`, marketplace content) onto one kernel with
registries and seams. Deliberately not designed further here: it inherits the
session log's envelope and events, and it gets designed against a
then-stable dsh (currently a developer preview promising breaking changes).

## Out of scope
- Any rewrite-from-scratch of Thomas (rejected on evidence: the failure class
  lives in how work enters and lands, which a fresh repo would inherit; the red
  condition above is the reopening clause).
- Marketplace domain-module changes.
- dsh file-format compatibility (concepts are copied, not formats).

## Evidence appendix (session 2026-08-24)
- **Red team:** 16 agents; 9 findings adversarially verified, 8 confirmed, 0
  refuted. Fatal-as-written: Code-surface scope contradiction (claude-CLI
  assembles externally; live chat is OrchestratorBrain, not `_build_messages`);
  byte-for-byte equality compares different objects; working-tree export would
  publish gitignored PII (owner email, competitor blocklist) and uncommitted
  state; crew→gates coupling ~60 literal-path sites; box not import-closed
  (4 stray `scripts/*` imports + Windows-only breakglass chain).
- **Transcript sweep (6 searchers):** built-but-never-wired in 13 sessions /
  ~10 subsystems (every month of the project); fixes-that-don't-stick in 16;
  misreporting in 10; verification-theater in 9 (+~25 by an earlier audit);
  complaints do not track model choice (measured per-model rates flat; Thomas
  also mislabeled models — non-GPT picks silently ran the Claude CLI).
- **Resurrection census (verified against GitHub's complete server-side
  activity ledger):** 7 branch resurrection events ever (3 real, 2 still live);
  29 file D-then-A events on dev in 8 incidents (21 via two snapshot commits;
  banned `app_part03.py` still present); c14859ff refused 4 attempted merge
  resurrections; the hourly-janitor resurrection story is REFUTED lore (0
  provable janitor re-creations — the Jul-2 wave was first-time sprawl export).
