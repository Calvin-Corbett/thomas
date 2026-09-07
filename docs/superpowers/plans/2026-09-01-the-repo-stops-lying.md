# The Repo Stops Lying (owner-directed, 2026-09-01)

> **RETRACTED 2026-09-01, same day, before any deletion landed.** This plan's
> central measurement was WRONG. It claimed 125 marketplace modules have zero
> live importers. They are in fact loaded at every server and CLI boot by
> `thomas/server/tool_extensions.py`'s 136-entry `_OPTIONAL_TOOL_MODULES`
> table, whose `_try_import` falls back from `thomas.<name>.tools` to
> `thomas.marketplace.<name>.tools`. The live server log reads
> `Loaded 131/136 optional tool modules`; those modules register **522
> callable tools**. The error was a static grep for `marketplace.<name>` that
> could not see a dynamic import table. The README claim this plan called a
> lie -- "domain modules the agent can call into" -- is TRUE.
>
> No deletion landed. A staged 8-module deletion was fully restored (4 of the
> 8 were themselves in the tool table). The tree is unchanged at 131/136.
>
> What survives as real work: the 5 modules whose registration FAILS every
> boot and is silently swallowed (`codex`, `groupchat`, `human_loop`,
> `learning`, `reference_cli_compat` -- one raises "type object is not
> iterable"); the genuinely importer-free `app_provisioning`, `approvals`,
> `dsl`, `sandbox`; and the stale documentation (a status block dated
> 2026-05-21 and a "gradual cleanup in progress" line that describes no real
> cleanup). Any successor plan starts from the tool table as the source of
> truth, never from a grep.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Thomas's public face tells the truth about what Thomas is. The 125 orphaned "marketplace domain" modules — 407,416 lines of library code with zero live importers, plus the 570 test files and 124 re-export shims that exist only to serve them — are deleted with death records, and the documentation that advertised them as working features is rewritten to describe the real product.

**Owner instruction (verbatim, 2026-09-01):** "github main and dev i feel descirbe thomas wrong fo what he really is and its doucmenation and a lot is wrong. no whewre it mentions like all those market place things are fake. actually remove them from the main and dev thaose barely built markeplavce things i havent touched in 6 months just waste ai reviwers time"

This explicitly lifts the standing CLAUDE.md/AGENTS.md protection on domain modules ("Do not suggest removing... unless the user explicitly asks you to"). That protection is itself part of the problem — see Task 4.

## Measured evidence (2026-09-01, against dev at 209ed2d9)

| Fact | Number | How measured |
|---|---|---|
| `thomas/marketplace/*` subdirs | 139 | `ls -d` |
| ...with external importers (KEEP) | 13 | grep for `marketplace.<m>` outside own tree |
| ...orphaned, zero importers (DELETE) | 125 | the remainder |
| Orphan python lines | 407,416 | `find -name '*.py' \| cat \| wc -l` |
| Test files existing only for orphans | 570 of 1,211 (47%) | grep tests/ per orphan module |
| Those test files' lines | 106,815 | same |
| Top-level `thomas/<name>/` re-export shims | 124 | 1 file, <=5 lines, `from thomas.marketplace.X import *` |
| **Total deletion** | **~514,000 lines** | sum |

**The 13 WIRED modules that MUST survive** (importer counts): `observability` (24 — the phase-1.3 honesty spine: session_log_events, run_store, derive_messages), `orchestrator` (14), `security` (9), `channels` (4), `nodes` (4), `asset_studio` (3), `autonomy` (2), `paper_trading` (2), `policy` (2 — guardrails config, fixed tonight), `specialists` (2 — reasoning loop, active work), `realtime` (1), `vision` (1), `webhooks` (1). Deleting any of these breaks live code; `observability` would tear out the instrument this program spent a month building.

**The documentation's false claims** (README.md on dev; `origin/main` carries the same text under the stale 2026-08-12 squash `ca4949d9`):
- L23: "`thomas/marketplace/` — domain modules ... **that the agent can call into**" — the agent cannot; there are zero live imports.
- L26: "kitchen-sink platform on purpose — Thomas's value is that one workspace covers tasks that today require a half-dozen separate tools" — the product's stated value rests on unreachable code.
- L7: status block dated 2026-05-21 calls the packages "still mid-build" — untouched for 3-6 months.
- L98: "gradual cleanup in progress" — no cleanup ever ran.

**Tech Stack:** Python 3.12, pytest, git. No new dependencies.

## Global Constraints

All prior plans' Global Constraints (wrapper commits via `scripts/crew/brief/commit.py`, no double quotes in messages, no manual trailers, CHANGELOG entry per commit, ruff, sentence-named tests, <800-line files, no `*_part*.py`/`exec()`), plus:
- **Every deletion gets a graveyard death record** (`scripts/forge/graveyard.py record-file`). This is not ceremony: `merge_resurrection_gate.py` reads the graveyard, and a stale branch merge that resurrected 514,000 lines would be the worst incident in this repo's history. `docs/ops/graveyard.json` is a protected `enforcement_file` — appends need the break-glass window, so deaths are recorded in one batched tap-window commit (Task 3), and the deletions themselves land first with a MUST-NOT-exist test as the interim guard (the phase-2 salvage precedent).
- **The 13 wired modules are untouchable.** Re-verify each module's importer count immediately before deleting it — the tree is live and another session may wire something new. Any module that gains an importer moves to KEEP and is reported, not deleted.
- **Deletions land in reviewed batches**, never one 514k-line commit: the commit-growth and bulk-commit guards will refuse it, and a reviewer cannot check it.
- **`main` is the PUBLIC repo** (`origin` = github.com/Calvin-Corbett/thomas.git). It currently holds the stale 2026-08-12 squash. Task 5 handles it; nothing is pushed there until dev's truth is landed and reviewed.

---

### Task 1: Prove the orphan set, then delete it in batches

**Files:** delete `thomas/marketplace/<orphan>/` (125 dirs), `thomas/<shim>/` (124 dirs), `tests/<orphan-only>.py` (570 files). Create `tests/test_the_orphan_modules_stay_deleted.py`.

**Behavior:** regenerate the orphan list fresh (do not trust this plan's list — the tree is live); for each candidate, re-verify zero external importers AND that no test outside the orphan-only set imports it. Delete in coherent batches (suggested: alphabetical groups of ~15 modules with their shims and tests, one commit each). After every batch: `pytest` the remaining suite must stay green, `ruff` clean, no import errors (`python -c "import thomas"`). The new test asserts a representative sample of deleted paths MUST NOT exist (phase-1.2 anti-resurrection pattern) until the graveyard records land in Task 3.

**Contracts:** zero remaining references to any deleted module anywhere in `thomas/`, `scripts/`, `tests/` (grep proves it); the 13 wired modules untouched and their importers still green; the full remaining suite passes; `thomas/_architecture.py` debt strings referencing deleted modules are cleaned.

- [ ] Steps: regenerate + re-verify list → batch deletions with per-batch green suite → MUST-NOT-exist test → wrapper commits: `chore(marketplace): <N> orphaned domain modules die - nothing imported them`

### Task 2: The documentation describes the real Thomas

**Files:** `README.md`, `STATUS.md` (if it makes marketplace claims), `docs/` files that advertise domain modules, `thomas/_architecture.py` (module map).

**Behavior:** rewrite the architecture section to list what actually exists and runs; delete the "kitchen-sink platform" value claim and the "agent can call into" claim; replace the stale status block with a current, dated one. State plainly what Thomas is: a local-first AI workspace — one server, one web UI, one CLI — with chat, memory, tools, browser automation, mission control, an installable-plugin marketplace (`extensions/` + `/api/marketplace/*`, which is REAL and stays), and the Praxis coordination/trust rails. Where a capability is partial, say so with a date. No claim ships that the tree cannot back.

**Contracts:** every capability claim in README maps to code with a live caller (spot-verify each); no deleted module is named anywhere in docs; the status block is dated today; second person for owner-facing text, no name.

- [ ] Steps: audit every claim → rewrite → verify each survivor claim by grep/execution → wrapper commit: `docs: the readme describes the thomas that exists`

### Task 3: The dead stay dead (tap-window batch)

**Files:** `docs/ops/graveyard.json` (protected — break-glass), `plans/thomas/tasks/PRAXIS-REPO-TRUTH-BREAKGLASS/batch.md`.

**Behavior:** a single batched `record_death` append covering every deleted module (one record per top-level module, not per file — 125 marketplace + 124 shims + a summary record for the test files, cause `orphaned-domain-module`, evidence citing this plan and the importer-count method). Prepared as a STATUS: PREPARED batch doc with the verbatim recovery block (the phase-2 precedent), executed in the owner's next break-glass window. Until it lands, Task 1's MUST-NOT-exist test is the guard, carrying an expiry.

- [ ] Steps: generate records → batch doc with verbatim JSON → wrapper commit: `docs(worktrees): the orphan graveyard append is prepared`

### Task 4: The instructions stop protecting the dead weight

**Files:** `CLAUDE.md`, `AGENTS.md`.

**Behavior:** the standing rule "Thomas is an AI-first workspace platform with a marketplace of domain modules. The repo is intentionally broad in scope — that is a feature, not a problem. Do not suggest removing, consolidating, or refactoring domain modules" is why 514,000 unreachable lines survived every review for six months — it told every agent to protect them. Replace it with the truth: the marketplace is the *plugin* system (`extensions/`, `/api/marketplace/*`); `thomas/marketplace/` holds the modules that live code actually imports; new domain modules need a caller and a test before they land. State the rule that would have prevented this: **code with no caller is not a feature, it is debt — flag it.**

- [ ] Steps: rewrite both rules → wrapper commit: `docs: the house rule stops protecting code nobody calls`

### Task 5: main tells the same truth

**Behavior:** `origin/main` (public) is the stale 2026-08-12 squash carrying every orphan and every false claim. After Tasks 1-4 land and pass final review on dev, bring main to the same truth. Determine the honest mechanism with evidence (fast-forward from dev if history allows; otherwise a reviewed sync commit — NEVER a fresh squash: this repo's whole history-integrity program exists because of one). Verify `origin`'s branch protection allows it before starting; report to the owner rather than forcing anything.

- [ ] Steps: assess main's divergence → choose + justify mechanism → execute → verify the public repo shows the real Thomas

## Self-review notes
- The 13-module KEEP list is the load-bearing safety property; every task re-verifies it rather than trusting this document.
- Deletion is reversible in the only way that matters: git history retains everything, and the graveyard records what died and why.
- Task 4 is the practice that stops the recurrence — without it, the next agent re-adds domain modules and the next reviewer protects them again.
