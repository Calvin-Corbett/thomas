# Brief: Companion Module Store Hardening

Last updated: 2026-08-31
Intended executor: the evolve loop (green agent), `propose` or `auto_safe` posture
Prerequisite: the surface host and bridge landed (`thomas/marketplace/companion/store.py`)

## Why this brief is scoped the way it is

The evolve loop can promote changes to some of this repository and not the rest.
The boundaries are not arbitrary and this brief is drawn to fit inside them:

| Boundary | Where it is enforced | Consequence here |
|---|---|---|
| `thomas/server/`, `thomas/core/`, `thomas/tools/`, `thomas/agent/`, `scripts/` are runtime-protected | `evolve_supervisor/supervisor.py` `DEFAULT_RUNTIME_PROTECTED_PREFIXES`, checked at `_candidate_violations` | A candidate touching them is a `protected_path_changed` violation and is **rejected outright**, not held for review. Nothing in this brief may edit them. |
| Any non-`.py` file forces the risk floor to `critical` | `evolve_supervisor/decision.py` `session_risk_floor` | A candidate touching JS/CSS/HTML/JSON needs human approval in every posture. Every unit below is Python-only so the loop can actually finish. |
| `tests/` is a blocked prefix | `supervisor.py` `_load_agent_safety_paths` | **The loop cannot write its own tests.** Each unit below names the tests that must exist first; a human or Claude adds them, then the loop implements until they pass. The loop does not get to grade its own exam. |
| `thomas/marketplace/` is not protected | absent from both lists above | This is the lane. All work below lives in `thomas/marketplace/companion/`. |

Keep every unit inside `thomas/marketplace/companion/**/*.py`. One unit per
session. Message Claude after each per `AGENTS.md`, and stop.

## What exists now

`thomas/marketplace/companion/store.py` is deliberately minimal: one JSON
document per module under the kernel's `data/` directory, addressed by
`module_id` so a module never supplies a path, with atomic replace on write.
`StoreQuota` caps bytes and key count. `ModuleStore` exposes
`get / set / delete / keys / entries / clear / usage`.

It is correct but naive. Everything below makes it survive contact with real
apps.

## Unit 1 — Quotas come from policy, not from constants

`StoreQuota` defaults are module-level constants. A photo-heavy app and a
counter app get the same 1 MiB.

Read the ceiling from the kernel policy document (`CompanionKernel.load_policy()`,
which already round-trips `policy.json`) with the current constants as the
fallback when the key is absent. Add the key to `CompanionKernel.default_policy()`
so new installs get it written out.

Tests to add first: quota read from policy; missing key falls back to the
constant; malformed value falls back rather than raising.

## Unit 2 — Decide and document what happens at the ceiling

Today a write past quota raises `ModuleStoreQuotaError` and the prior contents
survive intact (there is a test asserting that). That is a defensible policy but
it was never actually chosen — it is just what the simplest implementation did.

Pick one and write it down in the module docstring:

- **Reject** (current). Simple, predictable, and the app has to cope.
- **Evict** least-recently-written keys until the write fits. Needs a per-key
  timestamp, which changes the on-disk document shape — see Unit 5.

Recommendation: keep reject as the default and make eviction opt-in per module,
because silently dropping a user's logged workouts is worse than an error the
app can show. Do not implement eviction without also implementing Unit 5.

Tests to add first: whichever policy you implement, at the boundary and one byte
over it.

## Unit 3 — Uninstall garbage collection

`ModuleStore.clear()` exists and has **no call site**, because `ModuleRegistry`
has no uninstall path at all — only `set_enabled`. So a disabled module keeps
its data forever and a reinstall silently inherits it.

Add `ModuleRegistry.remove(module_id)` and have the uninstall path call
`ModuleStore.clear()` for the same id. Removing a module must not be able to
delete another module's document; the id validation in `store.py` is the only
thing standing between those two outcomes, so exercise it.

Note: wiring an uninstall *route* is out of scope — routes live in
`thomas/server/`, which is protected. Deliver the registry and store side and
stop; the route is a separate human task.

Tests to add first: remove drops the registry row and the data document;
removing a missing module is a no-op, not an error; a crafted id cannot reach a
sibling document.

## Unit 4 — Schema migration

Documents carry `schema_version` and nothing ever reads it. The moment Unit 2 or
any later change alters the document shape, every existing document is
unreadable or silently misread.

Add a migration step on read: recognise the version, upgrade older shapes in
memory, and write the upgraded form back on the next write. An unknown *newer*
version must refuse to load rather than guess — a store written by a newer
Thomas should not be silently truncated by an older one.

Tests to add first: a v1 document loads unchanged; a hand-written older shape
upgrades; an unknown future version raises.

## Unit 5 — Per-module ask accounting

`thomas.ask()` lets a generated app call a model. Prompt length is capped, but
nothing counts how often an app asks, so a bad loop in generated code is
unbounded token spend.

Add the *ledger* — a per-module counter with a window, in
`thomas/marketplace/companion/`, in the shape `spend_governor.py` already uses
elsewhere. Enforcement in the route is a human task (protected path); this unit
delivers something the route can call, plus tests proving the accounting.

Tests to add first: counts increment per call; the window rolls over; the ledger
survives a reload.

## Not in scope

- Anything under `thomas/server/` — including the surface routes, the bridge,
  and the client. Protected path, instant rejection.
- Encryption at rest. It needs a key-management decision that is a person's call,
  not the loop's.
- The shell redesign (left rail, home grid). Non-Python, and it is a design
  question before it is a code question.

## House rules that still apply

- `ruff check` every file you touch (`line-length = 120`).
- Tag commits `Thomas-Agent: <model>`.
- No `--no-verify`. No `*_part*.py`. No `exec()` to load code.
- Do not grow a file by more than 300 lines in one commit.
- `CHANGELOG.md` is required once the change is real.
