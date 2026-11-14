# For Calvin — two things only you can do, 2026-08-14

Written by the `claude` session you left running. Everything below is in the
working tree of `C:/Users/corbe/Thomas` (branch `dev`). **Nothing is committed.**
Two gates stopped me on purpose, and both were right to.

---

## 1. The big one: your gates were not enforcing anything

All 28 pre-commit gates run through `scripts/_gate_python.py`. It ended in
`os.execv`. Windows has no real `exec` — Python fakes it by launching a separate
child and killing the current process straight away, so pre-commit read *that*
process's exit code (0) and the gate's output went to a process nobody was
reading.

Measured on your machine, same gate both ways:

| how it was run | exit code | output |
|---|---|---|
| `monolith_guard.py` directly | **1** | 23 violations printed |
| identical child through the shim | **0** | nothing at all |

A second, separate defect stacked on top: `monolith_guard.py` works out the repo
root from its own location and lands on `scripts/forge`, so the `--staged-only`
form pre-commit actually uses scans **zero files**. I staged a 1,471-line
violating file and the hook said `Monolith guard OK. Scanned 0 files` and exited 0.

Both had to be true at once for this to stay hidden, which is why 23 size
violations piled up while every commit reported clean.

**I fixed the first one** (`scripts/_gate_python.py`, Windows branch that waits
for the gate and returns its real exit code; the Linux/CI path is untouched
because I can't verify CI from here). Proof: `tests/test_a_failing_gate_must_fail_the_hook.py`
failed 6 of 8 before the change and passes 8 of 8 after.

**I did not fix the second one, and I did not bless my own fix.** Both files are
listed as enforcement scripts in `agent_safety.toml`, and the anti-tamper gate now
correctly flags my edit. The whole point of that control is that the one who
changes a gate isn't the one who certifies it — so it needs your hand:

```bash
python scripts/forge/gates/enforcement_integrity.py --generate-manifest
```

Run that only if you're happy with the change; `git diff scripts/_gate_python.py`
is 9 lines and shows exactly what it does. Codex hit this same wall last night and
also refused to cross it, which was the right call.

Heads up: once this lands, gates start actually failing commits. That's the point,
but it means the 23 existing violations become real — you'll want to decide which
to split and which to record as accepted debt. They're all pre-existing; none came
from this week's work.

---

## 2. Four fixes waiting on your decision about codex's diff

While reviewing codex's 40-file uncommitted diff I found and fixed four real bugs.
Each one is a correction *on top of* codex's unlanded code — the functions they
touch don't exist in the last commit — so they can't be committed separately. They
land when codex's work lands, or not at all.

| what was wrong | where | proof |
|---|---|---|
| A policy file saying `no_human_mode = "Deny"` (capital D) or `approval_timeout_s = 60.0` (a decimal point) switched **every tool off**. Older files wrote it exactly that way. | `marketplace/policy/config.py` | 8 failing tests → passing; codex's 27 policy tests still pass |
| A turn that ran a tool and simply had no sentence to add was filed as a failure, so you'd read *"I couldn't get an answer from the selected model"* about work that succeeded. | `marketplace/orchestrator/brain.py` | new test failed before, passes now; 35 orchestrator tests green |
| With a CSRF token configured, a request carrying one easily-faked header and no token **created a session** (I reproduced it live: HTTP 200). | `server/app_middleware_handlers.py` | now 403; 24 tests + 5 subtests green |
| Ask for two things at once and if one fails, you were told about the one that worked and never the one that didn't. | `marketplace/specialists/reasoning.py` | reasoning + send-task suites green |

Full set re-run after every change: **343 tests + 24 subtests, all passing.**
`ruff` clean on all nine files.

I also **withdrew one of my own findings**: I "fixed" the sandbox-link stripping
and codex's test caught me — it protects something more important (what got saved
must match what you actually saw on screen). I reverted it and left the reasoning
in a comment.

And I **corrected another of my own claims**: I'd told you the oversized files were
a blocker for landing codex's diff. They aren't. That file was already 1,465 lines
before this week and the diff adds 6. No split is needed to land.

---

### One more bug, confirmed but deliberately left alone

A build that **succeeds** gets recorded as a **crash** if the runner prints even one
more progress line after it reports finishing. I reproduced it against the live
code (`_terminal_engine_verdict` in `server/routes/evolve_agent_runtime.py`):

| transcript ends with | recorded as |
|---|---|
| the "finished" marker | success |
| marker + 5 lines of shutdown noise | success |
| marker + 13 lines of shutdown noise | **crash** |
| marker + **one** later progress event | **crash** |

That last row is the likely one in real life. It's the same family as the
crash-filed-as-completed work from earlier this month, pointing the other way.

I did **not** fix it. It's codex's file, and the surrounding logic is deliberately
built so a genuine error still wins — the comments cite the day a design doc got
presented as a finished game. Getting that wrong in the other direction is worse
than the bug. Codex has the repro and the suggested approach in the workboard.

## 3. Things I checked that are fine

- `thomas doctor`, `thomas architecture-doctor`, `thomas doctor --full` — all exit 0.
  Architecture reports HEALTHY, 19 known debt items.
- Chat works. Sent a message on an isolated server, got a reply, no console or
  network errors.
- **Your desktop shortcut was broken and now works.** `Thomas.lnk` pointed at
  `Thomas.vbs`, which didn't exist — it's generated, not stored in git, so it
  vanishes on a clean checkout. Regenerated it with `python scripts/thomas_app.py`;
  clicking it now brings the engine up in ~6 seconds and opens Thomas in its own
  window. Side effect: `assets/thomas.ico` shows as modified because that script
  rebuilds the icon every run. Harmless, revert it if you like.
- Your live server on 8899 was never touched. All my testing ran on port 8912
  against a scratch data directory.

---

## 4. Codex

Frozen and told to stay that way pending your call. It has been working all night
and its 40-file diff is genuinely good work — 343 tests pass. The full review, with
every finding and its evidence, is in the workboard
(`python scripts/crew/workboard/message.py --list --all`, messages from `claude`).

There are **59 worktrees, 56 of them dirty**, against a ceiling of 5. Worth a
consolidation pass when you have the appetite, but nothing is on fire.
